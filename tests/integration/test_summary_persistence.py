"""Day 6 graph/ingestion/REST contract in migrated, disposable PostgreSQL schemas."""

from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from app.agents.graph import build_news_graph
from app.agents.schemas import ArticleMetadata, ReviewResult
from app.db.session import get_db
from app.main import app
from app.models import Article, ContentOrigin, ProcessingStatus, Summary
from app.seed_sources import SourceConfig, load_source_config
from app.services.gemini_service import GeminiServiceError
from app.services.ingestion import process_article
from app.services.summary_persistence import persist_summary
from app.services.summary_service import SMOKE_TEXT, SMOKE_TITLE, SummaryResult
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration
MODELS = {"summarize_model_name": "fixture/vit5", "agent_model_name": "fixture/gemini"}


@pytest.fixture
def pipeline(migrated_database, db_session, api_article):
    with db_session.begin():
        api_article.title = SMOKE_TITLE
        api_article.content = SMOKE_TEXT
        api_article.content_origin = ContentOrigin.RSS_EXCERPT
    config = SourceConfig.model_validate(
        load_source_config()[0].model_dump()
        | {
            "name": "Authored fixture",
            "rss_url": "https://example.com/fixture.xml",
            "official_rss_url": "https://example.com/rss",
            "robots_url": "https://example.com/robots.txt",
            "allowed_hosts": ["example.com"],
            "ai_processing_allowed": True,
            "ai_processing_review_note": "Authored fictional test text; no publisher content.",
        }
    )
    factory = sessionmaker(bind=migrated_database.connection, expire_on_commit=False)
    return factory, api_article.id, config


@pytest.fixture
def adapters(migrated_database):
    summarizer, provider = Mock(), Mock()

    def summarize(source_text, *, attempt):
        assert not migrated_database.connection.in_transaction()
        assert source_text == SMOKE_TEXT
        return SummaryResult(
            f"Thư viện mở lớp kỹ năng số miễn phí. Lần {attempt}.",
            "Nguồn đã giữ lại",
            True,
            1024,
            18,
            0.1,
        )

    summarizer.summarize.side_effect = summarize
    provider.metadata.return_value = ArticleMetadata(
        category="society", keywords=["thư viện", "kỹ năng số", "học miễn phí"]
    )
    provider.review.return_value = ReviewResult(approved=True, feedback="Được nguồn hỗ trợ")
    return summarizer, provider


@pytest.fixture
def client(migrated_database) -> Iterator[TestClient]:
    def override_db():
        with Session(bind=migrated_database.connection) as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def run(pipeline, graph):
    factory, article_id, config = pipeline
    return process_article(factory, article_id, config, graph, **MODELS)


@pytest.mark.parametrize("approvals", [[True], [False, True], [False, False]])
def test_pipeline_atomic_provenance_rest_visibility_and_replay(
    pipeline, adapters, client, approvals
):
    factory, article_id, _ = pipeline
    adapters[1].review.side_effect = [
        ReviewResult(approved=approved, feedback="Được hỗ trợ" if approved else "Sai số liệu")
        for approved in approvals
    ]
    graph = build_news_graph(*adapters)
    assert run(pipeline, graph) is True
    assert run(pipeline, graph) is False
    assert adapters[0].summarize.call_count == len(approvals)
    with factory() as session:
        article = session.get(Article, article_id)
        summary = session.scalar(select(Summary).where(Summary.article_id == article_id))
        assert article.processing_status == ("ready" if approvals[-1] else "needs_review")
        assert article.content == SMOKE_TEXT and article.content_origin == "rss_excerpt"
        assert article.processing_error is None
        assert summary.approved is approvals[-1]
        assert summary.draft_attempts == len(approvals)
        assert summary.review_feedback == ("Được hỗ trợ" if approvals[-1] else "Sai số liệu")
        assert summary.input_truncated is True
        assert summary.summarize_model_name == MODELS["summarize_model_name"]
        assert summary.agent_model_name == MODELS["agent_model_name"]
        assert summary.keywords == ["thư viện", "kỹ năng số", "học miễn phí"]
        assert session.scalar(select(func.count()).select_from(Summary)) == 1
    detail = client.get(f"/api/v1/articles/{article_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["ai_generated"] is approvals[-1]
    assert (data["summary"] is not None) is approvals[-1]
    assert (data["category"] is not None) is approvals[-1]
    card = client.get("/api/v1/articles").json()["items"][0]
    assert (card["summary_preview"] is not None) is approvals[-1]
    filtered = client.get("/api/v1/articles", params={"category": "society"}).json()
    assert filtered["total"] == int(approvals[-1])
    assert "review_feedback" not in detail.text and "source_text" not in detail.text


@pytest.mark.parametrize("operation", ["summarize", "metadata", "review"])
def test_provider_failure_marks_failed_without_candidate_or_private_error(
    pipeline, adapters, client, operation
):
    method = adapters[0].summarize if operation == "summarize" else getattr(adapters[1], operation)
    method.side_effect = GeminiServiceError("secret-key and private source text")
    assert run(pipeline, build_news_graph(*adapters)) is True
    factory, article_id, _ = pipeline
    with factory() as session:
        article = session.get(Article, article_id)
        assert article.processing_status == ProcessingStatus.FAILED
        assert article.processing_error == "AI processing failed"
        assert session.scalar(select(func.count()).select_from(Summary)) == 0
    assert run(pipeline, build_news_graph(*adapters)) is False
    assert client.get(f"/api/v1/articles/{article_id}").json()["summary"] is None


@pytest.fixture
def candidate(pipeline, adapters):
    factory, article_id, _ = pipeline
    result = build_news_graph(*adapters).invoke(
        {
            "article_id": article_id,
            "title": SMOKE_TITLE,
            "source_text": SMOKE_TEXT,
            "content_origin": ContentOrigin.RSS_EXCERPT,
        }
    )
    with factory() as session, session.begin():
        session.get(Article, article_id).processing_status = ProcessingStatus.PROCESSING
    return result


def test_direct_persistence_replay_preserves_original_summary(pipeline, candidate):
    factory, article_id, _ = pipeline
    with factory() as session, session.begin():
        assert persist_summary(session, candidate, **MODELS) is True
    with factory() as session, session.begin():
        assert persist_summary(session, candidate | {"summary": "Replacement"}, **MODELS) is False
    with factory() as session:
        summary = session.scalar(select(Summary).where(Summary.article_id == article_id))
        assert summary.summary_text == candidate["summary"]
        assert session.scalar(select(func.count()).select_from(Summary)) == 1


def test_rollback_keeps_claim_and_removes_summary(pipeline, candidate):
    factory, article_id, _ = pipeline
    with (
        pytest.raises(RuntimeError, match="injected rollback"),
        factory() as session,
        session.begin(),
    ):
        assert persist_summary(session, candidate, **MODELS) is True
        raise RuntimeError("injected rollback")
    with factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.PROCESSING
        assert session.scalar(select(func.count()).select_from(Summary)) == 0


def test_unique_summary_enforced_and_failed_write_rolls_back(pipeline, candidate):
    factory, article_id, _ = pipeline
    with factory() as session, session.begin():
        persist_summary(session, candidate, **MODELS)
    with pytest.raises(IntegrityError), factory() as session, session.begin():
        article = session.get(Article, article_id)
        article.processing_status = ProcessingStatus.PROCESSING
        persist_summary(session, candidate, **MODELS)
    with factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.READY
        assert session.scalar(select(func.count()).select_from(Summary)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"approved": "true"},
        {"outcome": "needs_review"},
        {"attempts": 3},
        {"input_truncated": "false"},
        {"source_text": "Different source"},
        {"title": "Different title"},
        {"content_origin": "extracted"},
    ],
)
def test_invalid_or_stale_output_never_writes(pipeline, candidate, change):
    factory, article_id, _ = pipeline
    with pytest.raises(ValueError), factory() as session, session.begin():
        persist_summary(session, candidate | change, **MODELS)
    with factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.PROCESSING
        assert session.scalar(select(func.count()).select_from(Summary)) == 0


def test_graph_cannot_finalize_a_different_article(pipeline):
    graph = Mock()
    graph.invoke.side_effect = lambda state: state | {"article_id": state["article_id"] + 1}
    assert run(pipeline, graph) is True
    factory, article_id, _ = pipeline
    with factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.FAILED
        assert session.scalar(select(func.count()).select_from(Summary)) == 0


def test_ai_gate_stops_before_claim_or_graph(pipeline):
    factory, article_id, config = pipeline
    config = config.model_copy(update={"ai_processing_allowed": False})
    graph = Mock()
    with pytest.raises(ValueError, match="disabled"):
        process_article(factory, article_id, config, graph, **MODELS)
    graph.invoke.assert_not_called()
    with factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.PENDING


@pytest.mark.parametrize("text", [None, "too short"])
def test_inadequate_text_is_not_sent_to_models(pipeline, text):
    factory, article_id, _ = pipeline
    with factory() as session, session.begin():
        session.get(Article, article_id).content = text
    graph = Mock()
    assert run(pipeline, graph) is True
    graph.invoke.assert_not_called()
    with factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.NEEDS_REVIEW
