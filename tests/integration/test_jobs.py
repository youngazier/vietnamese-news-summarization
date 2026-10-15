"""Day 7 coordination and crash boundaries in owned PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
from unittest.mock import Mock

import httpx
import pytest
from app.core.config import Settings
from app.db.session import get_db
from app.main import app
from app.models import (
    Article,
    ContentOrigin,
    IngestionJob,
    JobStatus,
    JobTrigger,
    ProcessingStatus,
    Source,
    Summary,
)
from app.seed_sources import SourceConfig, load_source_config
from app.services.article_extractor import ArticleExtractor
from app.services.ingestion import ingest_entries, process_article
from app.services.job_service import (
    JobSubmissionError,
    claim_job,
    enqueue_job,
    recover_abandoned_work,
)
from app.services.rss_collector import FeedEntry, FeedFetchError, RSSCollector
from app.services.summary_persistence import persist_summary
from app.services.summary_service import SMOKE_TEXT
from app.worker import Worker, scheduled_tick
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
def pipeline(migrated_database, db_session, api_article):
    with db_session.begin():
        api_article.rss_description = SMOKE_TEXT
    config = SourceConfig.model_validate(
        load_source_config()[0].model_dump()
        | {
            "rss_url": "https://example.com/fixture.xml",
            "official_rss_url": "https://example.com/rss",
            "robots_url": "https://example.com/robots.txt",
            "allowed_hosts": ["example.com"],
            "ai_processing_allowed": True,
            "ai_processing_review_note": "Authored fixture text.",
        }
    )
    factory = sessionmaker(bind=migrated_database.connection, expire_on_commit=False)
    graph = Mock()

    def invoke(state):
        assert not migrated_database.connection.in_transaction()
        return state | {
            "summary": "Thư viện mở lớp kỹ năng số miễn phí.",
            "category": "society",
            "keywords": ["thư viện", "kỹ năng số", "miễn phí"],
            "approved": True,
            "feedback": "Được nguồn hỗ trợ",
            "attempts": 1,
            "inference_text": state["source_text"],
            "input_truncated": False,
            "outcome": "approved",
        }

    graph.invoke.side_effect = invoke
    collector = Mock()
    collector.collect.return_value = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("Fixture extraction must use RSS only")
        )
    )
    worker = Worker(
        factory,
        Settings(_env_file=None),
        [config],
        collector,
        ArticleExtractor(client),
        graph,
        summarize_model_name="fixture/vit5",
        agent_model_name="fixture/gemini",
        stop=Event(),
    )
    try:
        yield worker, api_article.id, api_article.source_id, config
    finally:
        client.close()


def enqueue(worker, source_id=None, **kwargs):
    with worker.factory() as session, session.begin():
        return enqueue_job(session, source_id=source_id, **kwargs).id


def read_job(worker, job_id):
    with worker.factory() as session:
        return session.get(IngestionJob, job_id)


@pytest.fixture
def client(migrated_database):
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


def test_post_only_enqueues_and_get_returns_durable_status(pipeline, client):
    worker, _, source_id, _ = pipeline
    response = client.post("/api/v1/ingestion-jobs", json={"source_id": source_id})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert response.json() == {"job_id": job_id, "status": "pending"}
    worker.collector.collect.assert_not_called()
    worker.graph.invoke.assert_not_called()
    pending = client.get(f"/api/v1/ingestion-jobs/{job_id}").json()
    assert pending["status"] == "pending" and pending["attempts"] == 0
    assert pending["source_id"] == source_id and pending["trigger"] == "manual"
    assert pending["articles_processed"] == pending["articles_created"] == 0
    assert pending["started_at"] is None and pending["finished_at"] is None
    worker.run_once()
    result = client.get(f"/api/v1/ingestion-jobs/{job_id}").json()
    assert result["status"] == "completed" and result["attempts"] == 1
    assert result["articles_summarized"] == result["articles_processed"] == 1
    assert result["created_at"] and result["started_at"] and result["finished_at"]


@pytest.mark.parametrize("source_id", [0, -1, "wrong"])
def test_post_invalid_scope_is_422(client, source_id):
    assert client.post("/api/v1/ingestion-jobs", json={"source_id": source_id}).status_code == 422


def test_post_scope_errors_and_backlog(pipeline, client):
    worker, _, source_id, _ = pipeline
    assert client.post("/api/v1/ingestion-jobs", json={"source_id": 999999}).status_code == 404
    with worker.factory() as session, session.begin():
        session.get(Source, source_id).is_active = False
    assert client.post("/api/v1/ingestion-jobs", json={"source_id": source_id}).status_code == 422
    assert client.post("/api/v1/ingestion-jobs", json={}).status_code == 422
    with worker.factory() as session, session.begin():
        session.get(Source, source_id).is_active = True
    for _ in range(5):
        assert client.post("/api/v1/ingestion-jobs", json={}).status_code == 202
    assert client.post("/api/v1/ingestion-jobs", json={}).status_code == 429
    assert client.get("/api/v1/ingestion-jobs/999999").status_code == 404
    assert client.get("/api/v1/ingestion-jobs/0").status_code == 422


@pytest.fixture
def concurrent_factory(migrated_database):
    # Concurrent claim tests need independent connections in the SAME owned schema.
    # Migrations/ordinary tests still use the fixture's original connection.
    @contextmanager
    def factory():
        with migrated_database.connection.engine.connect() as connection:
            with connection.begin():
                connection.execute(
                    text("SELECT set_config('search_path', :schema, false)"),
                    {"schema": migrated_database.schema},
                )
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session

    return factory


def test_two_claimers_have_one_winner(pipeline, concurrent_factory):
    worker, *_ = pipeline
    job_id = enqueue(worker)
    claimed = Event()
    release = Event()

    def first():
        with concurrent_factory() as session, session.begin():
            claim = claim_job(session)
            claimed.set()
            assert release.wait(10)
            return claim

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first)
        try:
            assert claimed.wait(10)
            with concurrent_factory() as session, session.begin():
                assert claim_job(session) is None
        finally:
            release.set()
        assert future.result().id == job_id
    assert read_job(worker, job_id).attempts == 1


def test_concurrent_submissions_share_backlog_lock(pipeline, concurrent_factory):
    worker, *_ = pipeline
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=10)
        try:
            with concurrent_factory() as session, session.begin():
                enqueue_job(session, max_backlog=1)
            return 202
        except JobSubmissionError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        assert sorted(future.result() for future in futures) == [202, 429]
    with worker.factory() as session:
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1


def test_oldest_job_and_claim_rollback(pipeline):
    worker, *_ = pipeline
    first, second = enqueue(worker), enqueue(worker)
    with pytest.raises(RuntimeError), worker.factory() as session, session.begin():
        assert claim_job(session).id == first
        raise RuntimeError("crash before claim commit")
    assert read_job(worker, first).status == JobStatus.PENDING
    with worker.factory() as session, session.begin():
        assert claim_job(session).id == first
    with worker.factory() as session, session.begin():
        assert claim_job(session).id == second


def test_backlog_precedes_collection_with_independent_global_caps(pipeline):
    worker, article_id, source_id, _ = pipeline
    worker.settings.JOB_MAX_ARTICLE_INSERTIONS = 2
    worker.settings.JOB_MAX_ARTICLE_RESULTS = 1
    events = []
    invoke = worker.graph.invoke.side_effect
    worker.graph.invoke.side_effect = lambda state: events.append("backlog") or invoke(state)

    def collect(*args):
        events.append("feed")
        return [
            FeedEntry(source_id, f"New {i}", f"https://example.com/new-{i}", None, SMOKE_TEXT)
            for i in range(3)
        ]

    worker.collector.collect.side_effect = collect
    job_id = enqueue(worker)
    worker.run_once()
    assert events == ["backlog", "feed"]
    job = read_job(worker, job_id)
    assert job.articles_created == 2 and job.articles_processed == 1
    with worker.factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.READY
        assert session.scalar(select(func.count()).select_from(Article)) == 3


def test_source_scoped_job_leaves_other_sources_alone(pipeline):
    worker, article_id, source_id, config = pipeline
    with worker.factory() as session, session.begin():
        other = Source(
            name="Other fixture", rss_url="https://example.com/other.xml", is_active=True
        )
        session.add(other)
        session.flush()
        article = Article(
            source_id=other.id,
            title="Other",
            original_url="https://example.com/other",
            canonical_url="https://example.com/other",
            rss_description=SMOKE_TEXT,
        )
        session.add(article)
    worker.configs[other.rss_url] = config.model_copy(update={"rss_url": other.rss_url})
    enqueue(worker, source_id)
    worker.run_once()
    worker.collector.collect.assert_called_once_with(source_id, config)
    with worker.factory() as session:
        assert session.get(Article, article.id).processing_status == ProcessingStatus.PENDING
        assert session.get(Article, article_id).processing_status == ProcessingStatus.READY


def test_duplicate_only_cycle_never_regenerates_or_counts_again(pipeline):
    worker, _, source_id, _ = pipeline
    worker.collector.collect.return_value = [
        FeedEntry(source_id, "Existing", "https://example.com/fixture-article", None, SMOKE_TEXT)
    ]
    enqueue(worker)
    worker.run_once()
    second = enqueue(worker)
    worker.run_once()
    job = read_job(worker, second)
    assert job.status == JobStatus.COMPLETED
    assert job.articles_created == job.articles_processed == 0
    assert worker.graph.invoke.call_count == 1


def test_total_feed_failure_keeps_committed_results_and_redacts(pipeline):
    worker, *_ = pipeline
    worker.collector.collect.side_effect = FeedFetchError("private URL and secret")
    job_id = enqueue(worker)
    worker.run_once()
    job = read_job(worker, job_id)
    assert job.status == JobStatus.FAILED and job.articles_summarized == 1
    assert job.error_message == "No source feed succeeded"
    assert worker.collector.collect.call_count == 1


def test_partial_feed_failure_is_completed(pipeline):
    worker, _, _, config = pipeline
    with worker.factory() as session, session.begin():
        other = Source(
            name="Other fixture", rss_url="https://example.com/other.xml", is_active=True
        )
        session.add(other)
    worker.configs[other.rss_url] = config.model_copy(update={"rss_url": other.rss_url})
    worker.collector.collect.side_effect = [FeedFetchError("private URL"), []]
    job_id = enqueue(worker)
    worker.run_once()
    job = read_job(worker, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.error_message == "Some source feeds failed or lacked active reviewed configuration"


def test_isolated_article_failure_preserves_other_results_without_worker_retry(pipeline):
    worker, _, source_id, _ = pipeline
    worker.collector.collect.return_value = [
        FeedEntry(source_id, "Next", "https://example.com/next", None, SMOKE_TEXT)
    ]
    invoke = worker.graph.invoke.side_effect
    calls = 0

    def fail_first(state):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private provider response")
        return invoke(state)

    worker.graph.invoke.side_effect = fail_first
    job_id = enqueue(worker)
    worker.run_once()
    job = read_job(worker, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.articles_processed == 2 and job.articles_failed == job.articles_summarized == 1
    assert calls == 2


def test_feed_wire_attempt_budget_is_not_multiplied(pipeline):
    worker, *_ = pipeline
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        worker.collector = RSSCollector(client, sleep=lambda _: None)
        job_id = enqueue(worker)
        worker.run_once()
    assert len(requests) == 3
    assert read_job(worker, job_id).status == JobStatus.FAILED


@pytest.mark.parametrize("approved", [True, False])
def test_result_counter_and_summary_roll_back_together_and_replay_is_safe(pipeline, approved):
    worker, article_id, _, _ = pipeline
    job_id = enqueue(worker)
    with worker.factory() as session, session.begin():
        claim_job(session)
        article = session.get(Article, article_id)
        article.processing_status = ProcessingStatus.PROCESSING
        article.content, article.content_origin = SMOKE_TEXT, ContentOrigin.RSS_EXCERPT
        title = article.title
    result = worker.graph.invoke(
        {
            "article_id": article_id,
            "title": title,
            "source_text": SMOKE_TEXT,
            "content_origin": ContentOrigin.RSS_EXCERPT,
        }
    )
    result.update(approved=approved, outcome="approved" if approved else "needs_review")
    with pytest.raises(RuntimeError), worker.factory() as session, session.begin():
        persist_summary(session, result, job_id=job_id, **worker.model_names)
        raise RuntimeError("crash before result commit")
    assert read_job(worker, job_id).articles_processed == 0
    with worker.factory() as session:
        assert session.scalar(select(func.count()).select_from(Summary)) == 0
        assert session.get(Article, article_id).processing_status == ProcessingStatus.PROCESSING
    with worker.factory() as session, session.begin():
        assert persist_summary(session, result, job_id=job_id, **worker.model_names)
    with worker.factory() as session, session.begin():
        assert not persist_summary(session, result, job_id=job_id, **worker.model_names)
    job = read_job(worker, job_id)
    assert job.articles_processed == 1
    assert job.articles_summarized == int(approved)
    assert job.articles_needs_review == int(not approved)


def test_insertion_counter_rolls_back_with_article(pipeline):
    worker, _, source_id, _ = pipeline
    job_id = enqueue(worker)
    with worker.factory() as session, session.begin():
        claim_job(session)
    entry = FeedEntry(source_id, "New", "https://example.com/new", None, SMOKE_TEXT)
    with pytest.raises(RuntimeError), worker.factory() as session, session.begin():
        ingest_entries(session, [entry], job_id=job_id)
        raise RuntimeError("crash before insertion commit")
    assert read_job(worker, job_id).articles_created == 0
    with worker.factory() as session, session.begin():
        assert len(ingest_entries(session, [entry], job_id=job_id).inserted_ids) == 1
    with worker.factory() as session, session.begin():
        assert not ingest_entries(session, [entry], job_id=job_id).inserted_ids
    assert read_job(worker, job_id).articles_created == 1


def test_short_text_counts_once_without_ai(pipeline):
    worker, article_id, _, config = pipeline
    with worker.factory() as session, session.begin():
        session.get(Article, article_id).rss_description = "short"
    job_id = enqueue(worker)
    worker.run_once()
    assert read_job(worker, job_id).articles_needs_review == 1
    worker.graph.invoke.assert_not_called()
    assert not process_article(
        worker.factory, article_id, config, worker.graph, job_id=job_id, **worker.model_names
    )
    assert read_job(worker, job_id).articles_processed == 1


def test_ai_disabled_leaves_usable_text_pending(pipeline):
    worker, article_id, _, config = pipeline
    worker.configs[config.rss_url] = config.model_copy(update={"ai_processing_allowed": False})
    job_id = enqueue(worker)
    worker.run_once()
    worker.graph.invoke.assert_not_called()
    assert read_job(worker, job_id).articles_processed == 0
    with worker.factory() as session:
        article = session.get(Article, article_id)
        assert article.processing_status == ProcessingStatus.PENDING and article.content


def test_oldest_prepared_backlog_is_not_starved_by_short_new_text(pipeline):
    worker, article_id, source_id, _ = pipeline
    worker.settings.JOB_MAX_ARTICLE_RESULTS = 1
    with worker.factory() as session, session.begin():
        article = session.get(Article, article_id)
        article.content, article.content_origin = SMOKE_TEXT, ContentOrigin.RSS_EXCERPT
        session.add(
            Article(
                source_id=source_id,
                title="Short new text",
                original_url="https://example.com/short",
                canonical_url="https://example.com/short",
                rss_description="short",
            )
        )
    job_id = enqueue(worker)
    worker.run_once()
    assert read_job(worker, job_id).articles_summarized == 1
    assert worker.graph.invoke.call_args.args[0]["article_id"] == article_id


def test_restart_preserves_results_and_counters_and_next_job_resumes(pipeline):
    worker, article_id, source_id, _ = pipeline
    first = enqueue(worker)
    worker.run_once()
    with worker.factory() as session, session.begin():
        orphan = Article(
            source_id=source_id,
            title="Interrupted",
            original_url="https://example.com/orphan",
            canonical_url="https://example.com/orphan",
            content=SMOKE_TEXT,
            content_origin=ContentOrigin.RSS_EXCERPT,
            processing_status=ProcessingStatus.PROCESSING,
        )
        session.add(orphan)
        # Model the crash after one durable result and a subsequent processing claim.
        job = session.get(IngestionJob, first)
        job.status, job.finished_at = JobStatus.RUNNING, None
    with worker.factory() as session, session.begin():
        recover_abandoned_work(session)
    recovered = read_job(worker, first)
    assert recovered.status == JobStatus.FAILED and recovered.articles_summarized == 1
    assert recovered.finished_at is not None and recovered.attempts == 1
    with worker.factory() as session:
        assert session.get(Article, article_id).processing_status == ProcessingStatus.READY
        assert session.get(Article, orphan.id).processing_status == ProcessingStatus.PENDING
    second = enqueue(worker)
    worker.run_once()
    assert read_job(worker, second).articles_summarized == 1
    assert read_job(worker, first).articles_summarized == 1
    assert worker.graph.invoke.call_count == 2


def test_shutdown_keeps_running_job_for_recovery(pipeline):
    worker, *_ = pipeline
    invoke = worker.graph.invoke.side_effect

    def stop_after_result(state):
        worker.stop.set()
        return invoke(state)

    worker.graph.invoke.side_effect = stop_after_result
    job_id = enqueue(worker)
    worker.run_once()
    job = read_job(worker, job_id)
    assert job.status == JobStatus.RUNNING and job.articles_summarized == 1
    worker.collector.collect.assert_not_called()


def test_fatal_final_write_fails_job_and_startup_recovers_claim(pipeline, monkeypatch):
    worker, article_id, _, _ = pipeline
    monkeypatch.setattr(
        "app.services.ingestion.persist_summary",
        Mock(side_effect=SQLAlchemyError("private database details")),
    )
    job_id = enqueue(worker)
    with pytest.raises(SQLAlchemyError):
        worker.run_once()
    job = read_job(worker, job_id)
    assert job.status == JobStatus.FAILED and job.articles_processed == 0
    assert job.error_message == "Job failed: database or pipeline error"
    with worker.factory() as session, session.begin():
        assert session.get(Article, article_id).processing_status == ProcessingStatus.PROCESSING
        assert session.scalar(select(func.count()).select_from(Summary)) == 0
        recover_abandoned_work(session)
    monkeypatch.setattr("app.services.ingestion.persist_summary", persist_summary)
    resumed = enqueue(worker)
    worker.run_once()
    assert read_job(worker, resumed).articles_summarized == 1


def test_schedule_ticks_deduplicate_and_resume_after_terminal_job(pipeline):
    worker, *_ = pipeline
    scheduled_tick(worker.factory, worker.settings, worker.stop)
    scheduled_tick(worker.factory, worker.settings, worker.stop)
    with worker.factory() as session:
        jobs = session.scalars(select(IngestionJob)).all()
        assert len(jobs) == 1 and jobs[0].trigger == JobTrigger.SCHEDULED
    with worker.factory() as session, session.begin():
        claim = claim_job(session)
    scheduled_tick(worker.factory, worker.settings, worker.stop)
    with worker.factory() as session:
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
    worker.run_job(claim)
    scheduled_tick(worker.factory, worker.settings, worker.stop)
    with worker.factory() as session:
        jobs = session.scalars(select(IngestionJob).order_by(IngestionJob.id)).all()
        assert [job.status for job in jobs] == [JobStatus.COMPLETED, JobStatus.PENDING]
