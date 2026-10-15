"""D2.2/D2.7: PostgreSQL enforces rules declared by the models."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.models import (
    Article,
    Category,
    ContentOrigin,
    IngestionJob,
    JobStatus,
    JobTrigger,
    ProcessingStatus,
    Source,
    Summary,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


@pytest.fixture
def saved_article(db_session):
    """A committed source/article for checks that need valid parent rows."""
    with db_session.begin():
        source = Source(
            name="D2 test fixture", rss_url="https://example.com/fixture.xml"
        )
        article = Article(
            source=source,
            title="Bài viết thử nghiệm",
            original_url="https://example.com/article",
            canonical_url="https://example.com/article",
        )
        db_session.add(article)
    return article


def make_summary(article_id):
    return Summary(
        article_id=article_id,
        summary_text="Tóm tắt thử nghiệm; không phải kết quả AI thật.",
        category=Category.OTHER,
        keywords=["thử nghiệm"],
        summarize_model_name="fixture-model",
        agent_model_name="fixture-reviewer",
    )


def assert_constraint(error, expected_name):
    # Check the exact PostgreSQL constraint, not merely that some insert failed.
    assert error.value.orig.diag.constraint_name == expected_name


def test_database_defaults_and_relationships(db_session, saved_article):
    article_id = saved_article.id
    with db_session.begin():
        summary = make_summary(article_id)
        job = IngestionJob(source_id=saved_article.source_id, trigger=JobTrigger.MANUAL)
        db_session.add_all([summary, job])

    # Reload from PostgreSQL instead of inspecting only in-memory assigned values.
    db_session.expire_all()
    article = db_session.get(Article, article_id)
    assert article.source.is_active is True
    assert article in article.source.articles
    assert article.summary.article is article
    assert job in article.source.ingestion_jobs
    assert article.processing_status == ProcessingStatus.PENDING
    assert article.content_origin is None
    assert article.published_at is None
    assert article.created_at.tzinfo is not None
    assert article.updated_at.tzinfo is not None
    assert summary.approved is False
    assert summary.draft_attempts == 1
    assert summary.input_truncated is False
    assert job.status == JobStatus.PENDING
    for field in (
        "attempts",
        "articles_created",
        "articles_processed",
        "articles_summarized",
        "articles_failed",
        "articles_needs_review",
    ):
        assert getattr(job, field) == 0


def test_duplicate_canonical_url(db_session, saved_article):
    duplicate = Article(
        source_id=saved_article.source_id,
        title="Duplicate",
        original_url="https://example.com/different-original",
        canonical_url=saved_article.canonical_url,
    )
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.add(duplicate)
        db_session.flush()
    assert_constraint(error, "uq_articles_canonical_url")
    assert db_session.scalar(select(func.count()).select_from(Article)) == 1


def test_duplicate_rss_url(db_session, saved_article):
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.add(Source(name="Duplicate", rss_url=saved_article.source.rss_url))
        db_session.flush()
    assert_constraint(error, "uq_sources_rss_url")


def test_one_summary_per_article(db_session, saved_article):
    with db_session.begin():
        db_session.add(make_summary(saved_article.id))
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.add(make_summary(saved_article.id))
        db_session.flush()
    assert_constraint(error, "uq_summaries_article_id")


@pytest.mark.parametrize("child", ["article", "summary", "job"])
def test_missing_parent_foreign_key(db_session, child):
    missing_id = 999999  # Every test schema is initially empty.
    if child == "article":
        row = Article(
            source_id=missing_id,
            title="Missing source",
            original_url="https://example.com/missing",
            canonical_url="https://example.com/missing",
        )
        constraint = "fk_articles_source_id_sources"
    elif child == "summary":
        row = make_summary(missing_id)
        constraint = "fk_summaries_article_id_articles"
    else:
        row = IngestionJob(source_id=missing_id, trigger=JobTrigger.MANUAL)
        constraint = "fk_ingestion_jobs_source_id_sources"

    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.add(row)
        db_session.flush()
    assert_constraint(error, constraint)


@pytest.mark.parametrize(
    ("table", "column", "invalid", "constraint"),
    [
        ("articles", "processing_status", "invalid", "ck_articles_processing_status"),
        ("articles", "content_origin", "invalid", "ck_articles_content_origin"),
        ("summaries", "category", "invalid", "ck_summaries_category"),
        ("summaries", "draft_attempts", 0, "ck_summaries_draft_attempts"),
        ("summaries", "draft_attempts", 3, "ck_summaries_draft_attempts"),
        ("ingestion_jobs", "status", "invalid", "ck_ingestion_jobs_status"),
        ("ingestion_jobs", "trigger", "invalid", "ck_ingestion_jobs_trigger"),
        (
            "ingestion_jobs",
            "articles_processed",
            1,
            "ck_ingestion_jobs_processed_counter_total",
        ),
        *[
            ("ingestion_jobs", column, -1, "ck_ingestion_jobs_nonnegative_counters")
            for column in ("attempts", "articles_created")
        ],
    ],
)
def test_database_checks(db_session, saved_article, table, column, invalid, constraint):
    with db_session.begin():
        summary = make_summary(saved_article.id)
        job = IngestionJob(trigger=JobTrigger.MANUAL)
        db_session.add_all([summary, job])
    ids = {
        "articles": saved_article.id,
        "summaries": summary.id,
        "ingestion_jobs": job.id,
    }

    # Identifiers come only from this fixed test list, never from user input.
    # Raw SQL bypasses ORM enum validation so PostgreSQL must enforce the rule.
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.execute(
            text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"value": invalid, "id": ids[table]},
        )
    assert_constraint(error, constraint)


def test_keywords_must_be_json_array(db_session, saved_article):
    with db_session.begin():
        summary = make_summary(saved_article.id)
        db_session.add(summary)
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.execute(
            text(
                "UPDATE summaries SET keywords = CAST(:value AS jsonb) WHERE id = :id"
            ),
            {"value": '{"keyword": "invalid object"}', "id": summary.id},
        )
    assert_constraint(error, "ck_summaries_keywords_array")


def test_timezone_round_trip(db_session, saved_article):
    supplied = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=7)))
    article_id = saved_article.id
    with db_session.begin():
        saved_article.published_at = supplied
        saved_article.content_origin = ContentOrigin.RSS_EXCERPT
    db_session.expire_all()
    stored = db_session.get(Article, article_id)
    assert stored.published_at.tzinfo is not None
    assert stored.published_at == supplied.astimezone(UTC)
    assert stored.content_origin == ContentOrigin.RSS_EXCERPT


def test_transaction_rollback_removes_partial_write(db_session):
    with pytest.raises(RuntimeError, match="simulated failure"), db_session.begin():
        db_session.add(
            Source(name="Rolled back", rss_url="https://example.com/rollback.xml")
        )
        db_session.flush()  # Actually INSERT before the failure.
        raise RuntimeError("simulated failure")
    assert db_session.scalar(select(func.count()).select_from(Source)) == 0


def test_source_deletion_restricted(db_session, saved_article):
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.execute(
            text("DELETE FROM sources WHERE id = :id"),
            {"id": saved_article.source_id},
        )
    assert_constraint(error, "fk_articles_source_id_sources")


def test_article_deletion_cascades_to_summary(db_session, saved_article):
    with db_session.begin():
        db_session.add(make_summary(saved_article.id))
    with db_session.begin():
        db_session.execute(
            text("DELETE FROM articles WHERE id = :id"), {"id": saved_article.id}
        )
    assert db_session.scalar(select(func.count()).select_from(Summary)) == 0
    assert db_session.scalar(select(func.count()).select_from(Source)) == 1


@pytest.mark.parametrize(
    "counter", ["articles_summarized", "articles_failed", "articles_needs_review"]
)
def test_negative_outcome_counters(db_session, counter):
    with db_session.begin():
        job = IngestionJob(trigger=JobTrigger.MANUAL)
        db_session.add(job)

    # Preserve the equality rule so only the nonnegative check is violated.
    with pytest.raises(IntegrityError) as error, db_session.begin():
        db_session.execute(
            text(
                f"UPDATE ingestion_jobs SET {counter} = -1, "
                "articles_processed = -1 WHERE id = :id"
            ),
            {"id": job.id},
        )
    assert_constraint(error, "ck_ingestion_jobs_nonnegative_counters")
