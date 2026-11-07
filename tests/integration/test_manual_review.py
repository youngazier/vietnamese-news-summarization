"""Human review uses isolated PostgreSQL data; never publish application articles."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.db.session import get_db, get_engine
from app.main import app
from app.models import Article, Category, ProcessingStatus, Source, Summary
from app.services.manual_review import ReviewConflict, decide_review
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration


@pytest.fixture
def review_data(db_session):
    with db_session.begin():
        source = Source(name="Fictional review source", rss_url="https://example.com/review.rss")
        articles = []
        for name, status in [
            ("draft", ProcessingStatus.NEEDS_REVIEW),
            ("blocked", ProcessingStatus.NEEDS_REVIEW),
            ("ready", ProcessingStatus.READY),
        ]:
            article = Article(
                source=source,
                title=f"Review fixture {name}",
                original_url=f"https://example.com/{name}",
                canonical_url=f"https://example.com/{name}",
                content="Văn bản nguồn hư cấu. " * 20,
                processing_status=status,
            )
            if name != "blocked":
                article.summary = Summary(
                    summary_text=f"Bản nháp {name} hư cấu.",
                    category=Category.SOCIETY,
                    keywords=["hư cấu", "kiểm thử", "duyệt"],
                    summarize_model_name="fixture-model",
                    agent_model_name="fixture-reviewer",
                    approved=name == "ready",
                    review_feedback="Kiểm tra thông tin với nguồn.",
                )
            else:
                article.processing_error = "extraction_disabled; insufficient_text"
            db_session.add(article)
            articles.append(article)
        db_session.flush()
        return dict(
            zip(["draft", "blocked", "ready"], [article.id for article in articles], strict=True)
        )


@pytest.fixture
def review_client(db_session) -> Iterator[TestClient]:
    def override():
        try:
            yield db_session
        finally:
            db_session.rollback()

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_queue_and_private_draft(review_data, review_client):
    queue = review_client.get("/api/v1/reviews").json()
    assert queue["total"] == 2
    assert queue["items"][0]["id"] == review_data["draft"]
    detail = review_client.get(f"/api/v1/reviews/{review_data['draft']}").json()
    assert detail["can_review"] and detail["has_draft"]
    assert detail["draft"]["ai_feedback"] == "Kiểm tra thông tin với nguồn."
    public = review_client.get(f"/api/v1/articles/{review_data['draft']}").json()
    assert public["summary"] is None and public["summary_preview"] is None
    blocked = review_client.get(f"/api/v1/reviews/{review_data['blocked']}").json()
    assert not blocked["can_review"] and blocked["draft"] is None
    assert "Chưa có bản nháp" in blocked["reason"]


@pytest.mark.parametrize("decision", ["accept", "decline"])
def test_review_decision_persists_and_changes_public_visibility(
    review_data, review_client, decision
):
    url = f"/api/v1/reviews/{review_data['draft']}"
    draft = review_client.get(url).json()
    response = review_client.post(
        url,
        json={
            "decision": decision,
            "expected_version": draft["version"],
            "note": "Đã đối chiếu nội dung.",
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["decision"] == decision and not saved["can_review"]
    assert saved["note"] == "Đã đối chiếu nội dung."
    assert saved["draft"]["ai_feedback"] == draft["draft"]["ai_feedback"]
    assert review_client.get("/api/v1/reviews").json()["total"] == 1
    decided = review_client.get("/api/v1/reviews", params={"decision": decision}).json()
    assert decided["total"] == 1 and decided["items"][0]["id"] == review_data["draft"]
    public = review_client.get(f"/api/v1/articles/{review_data['draft']}").json()
    assert public["review_decision"] == decision
    assert public["ai_generated"] == (decision == "accept")
    assert (public["summary"] is not None) == (decision == "accept")
    assert public["processing_status"] == ("ready" if decision == "accept" else "needs_review")
    assert (
        review_client.post(
            url, json={"decision": "accept", "expected_version": draft["version"]}
        ).status_code
        == 409
    )


def test_decline_validation_and_blocked_draft(review_data, review_client):
    detail = review_client.get(f"/api/v1/reviews/{review_data['draft']}").json()
    for note in ["", "   ", "x" * 1001]:
        assert (
            review_client.post(
                f"/api/v1/reviews/{review_data['draft']}",
                json={"decision": "decline", "expected_version": detail["version"], "note": note},
            ).status_code
            == 422
        )
    blocked = review_client.get(f"/api/v1/reviews/{review_data['blocked']}").json()
    assert (
        review_client.post(
            f"/api/v1/reviews/{review_data['blocked']}",
            json={"decision": "accept", "expected_version": blocked["version"]},
        ).status_code
        == 409
    )
    ready = review_client.get(f"/api/v1/reviews/{review_data['ready']}").json()
    assert (
        review_client.post(
            f"/api/v1/reviews/{review_data['ready']}",
            json={"decision": "decline", "expected_version": ready["version"], "note": "Fixture"},
        ).status_code
        == 409
    )


def test_stale_version_and_rollback(review_data, review_client, db_session):
    article_id = review_data["draft"]
    detail = review_client.get(f"/api/v1/reviews/{article_id}").json()
    with db_session.begin():
        db_session.get(Article, article_id).summary.summary_text = "Bản nháp đã đổi."
    assert (
        review_client.post(
            f"/api/v1/reviews/{article_id}",
            json={"decision": "accept", "expected_version": detail["version"]},
        ).status_code
        == 409
    )
    current = review_client.get(f"/api/v1/reviews/{article_id}").json()
    with pytest.raises(RuntimeError), db_session.begin():
        decide_review(
            db_session, article_id, decision="accept", expected_version=current["version"], note=""
        )
        raise RuntimeError("Force rollback")
    assert review_client.get(f"/api/v1/reviews/{article_id}").json()["can_review"]


def test_two_reviewers_cannot_overwrite_each_other(review_data, review_client, migrated_database):
    article_id = review_data["draft"]
    version = review_client.get(f"/api/v1/reviews/{article_id}").json()["version"]
    engine = create_engine(
        get_engine().url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "hostaddr": migrated_database.connection.connection.driver_connection.info.hostaddr,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
    )
    barrier = Barrier(2)

    def decide(decision):
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(
                    text("SELECT set_config('search_path', :schema, false)"),
                    {"schema": migrated_database.schema},
                )
            with Session(bind=connection) as session:
                barrier.wait(timeout=10)
                try:
                    with session.begin():
                        decide_review(
                            session,
                            article_id,
                            decision=decision,
                            expected_version=version,
                            note="Concurrent fixture",
                        )
                    return "saved"
                except ReviewConflict:
                    return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(decide, ["accept", "decline"]))
        assert sorted(results) == ["conflict", "saved"]
    finally:
        engine.dispose()
