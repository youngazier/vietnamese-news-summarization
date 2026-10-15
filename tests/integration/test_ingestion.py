"""D3 article ingestion on real PostgreSQL, only in owned disposable schemas."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from app.db.session import get_db, get_engine
from app.main import app
from app.models import Article, ContentOrigin, ProcessingStatus, Source
from app.seed_sources import ArticleExtractionPolicy, SourceConfig, load_source_config
from app.services.article_extractor import ArticleExtractor
from app.services.ingestion import ingest_entries, insert_article, prepare_pending_articles
from app.services.rss_collector import FeedEntry, parse_feed
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rss" / "valid.xml"


@pytest.fixture
def feed_entries(db_session: Session) -> list[FeedEntry]:
    with db_session.begin():
        source = Source(name="Fixture RSS", rss_url="https://example.com/feed.xml", is_active=True)
        db_session.add(source)
        db_session.flush()
        source_id = source.id
    return parse_feed(FIXTURE.read_bytes(), source_id, ["example.com"])


def test_repeated_ingestion_and_rest(db_session: Session, feed_entries: list[FeedEntry]) -> None:
    with db_session.begin():
        first = ingest_entries(db_session, feed_entries)
    with db_session.begin():
        second = ingest_entries(db_session, feed_entries)
    assert len(first.inserted_ids) == 2
    assert second.inserted_ids == ()
    assert second.duplicates == 2
    with db_session.begin():
        rows = db_session.scalars(select(Article).order_by(Article.id)).all()
        assert len(rows) == 2
        assert rows[0].canonical_url == "https://example.com/news?id=42"
        assert rows[0].original_url.endswith("&utm_source=rss")
        assert rows[0].rss_description == feed_entries[0].rss_description
        assert rows[0].published_at == feed_entries[0].published_at
        assert rows[1].published_at is None
        assert all(row.processing_status == ProcessingStatus.PENDING for row in rows)
        assert all(row.content is None and row.content_origin is None for row in rows)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/articles", params={"source_id": feed_entries[0].source_id}
            )
            assert response.status_code == 200
            assert response.json()["total"] == 2
            detail = client.get(f"/api/v1/articles/{first.inserted_ids[0]}")
            assert detail.status_code == 200
            assert detail.json()["summary"] is None
            assert detail.json()["ai_generated"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_duplicate_keeps_ready_article_and_batch_continues(
    db_session: Session, feed_entries: list[FeedEntry]
) -> None:
    with db_session.begin():
        article_id = insert_article(db_session, feed_entries[0])
        article = db_session.get(Article, article_id)
        article.processing_status = ProcessingStatus.READY
        article.title = "Previously processed title"
    changed = replace(
        feed_entries[0],
        title="Changed title",
        original_url="https://example.com/news?id=42&fbclid=abc",
    )
    with db_session.begin():
        result = ingest_entries(db_session, [changed, feed_entries[1]])
    assert result.duplicates == 1
    assert len(result.inserted_ids) == 1
    with db_session.begin():
        db_session.expire_all()
        article = db_session.get(Article, article_id)
        assert article.title == "Previously processed title"
        assert article.processing_status == ProcessingStatus.READY


def test_insertion_cap_does_not_count_duplicates(
    db_session: Session, feed_entries: list[FeedEntry]
) -> None:
    with db_session.begin():
        insert_article(db_session, feed_entries[0])
    with db_session.begin():
        result = ingest_entries(db_session, feed_entries, max_insertions=1)
    assert result.examined == 2
    assert result.duplicates == 1
    assert len(result.inserted_ids) == 1


def test_failure_rolls_back_entire_batch(
    db_session: Session, feed_entries: list[FeedEntry]
) -> None:
    invalid = replace(feed_entries[1], source_id=0)
    with pytest.raises(IntegrityError), db_session.begin():
        ingest_entries(db_session, [feed_entries[0], invalid])
    with db_session.begin():
        assert db_session.scalar(select(func.count()).select_from(Article)) == 0


def test_two_sessions_race_for_one_canonical_url(
    migrated_database, feed_entries: list[FeedEntry]
) -> None:
    schema = migrated_database.schema
    # The fixture owns migrations/cleanup; extra connections use only its schema.
    barrier = Barrier(2)
    engine = create_engine(
        get_engine().url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000"},
    )

    def compete(entry: FeedEntry) -> int | None:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(
                    text("SELECT set_config('search_path', :schema, false)"), {"schema": schema}
                )
            with Session(bind=connection) as session, session.begin():
                barrier.wait(timeout=10)
                return insert_article(session, entry)

    try:
        variant = replace(feed_entries[0], original_url="https://example.com/news?id=42&fbclid=abc")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(compete, entry) for entry in (feed_entries[0], variant)]
            results = [future.result(timeout=20) for future in futures]
        assert sum(result is not None for result in results) == 1
        with migrated_database.connection.begin():
            assert (
                migrated_database.connection.scalar(select(func.count()).select_from(Article)) == 1
            )
    finally:
        engine.dispose()


@pytest.fixture
def preparation_config() -> SourceConfig:
    original = load_source_config(Path(__file__).resolve().parents[2] / "config/sources.json")[0]
    return SourceConfig.model_validate_json(
        original.model_copy(
            update={
                "rss_url": "https://example.com/feed.xml",
                "official_rss_url": "https://example.com/rss",
                "robots_url": "https://example.com/robots.txt",
                "allowed_hosts": ["example.com"],
            }
        ).model_dump_json()
    )


def no_publisher_request(request: httpx.Request) -> httpx.Response:
    pytest.fail("Disabled article extraction must not contact a publisher")


def test_prepare_persists_provenance_quality_and_replay(
    db_session, migrated_database, feed_entries, preparation_config
):
    long_entry = replace(feed_entries[0], rss_description="Nội dung tiếng Việt. " * 20)
    missing_entry = replace(feed_entries[1], original_url="https://example.com/missing")
    with db_session.begin():
        inserted = ingest_entries(db_session, [long_entry, feed_entries[1], missing_entry])
    factory = sessionmaker(bind=migrated_database.connection, expire_on_commit=False)
    with httpx.Client(transport=httpx.MockTransport(no_publisher_request)) as client:
        extractor = ArticleExtractor(client, sleep=lambda _: None)
        result = prepare_pending_articles(
            factory, long_entry.source_id, preparation_config, extractor
        )
        repeat = prepare_pending_articles(
            factory, long_entry.source_id, preparation_config, extractor
        )
    assert result.prepared_ids == inserted.inserted_ids
    assert result.pending == 1 and result.needs_review == 2
    assert repeat.prepared_ids == ()
    with db_session.begin():
        db_session.expire_all()
        rows = db_session.scalars(select(Article).order_by(Article.id)).all()
        assert rows[0].content == long_entry.rss_description.strip()
        assert rows[0].content_origin == ContentOrigin.RSS_EXCERPT
        assert rows[0].processing_status == ProcessingStatus.PENDING
        assert rows[0].processing_error == "extraction_disabled"
        assert rows[1].content is rows[1].content_origin is None
        assert rows[1].processing_status == ProcessingStatus.NEEDS_REVIEW
        assert rows[1].processing_error == "extraction_disabled; missing_text"
        assert rows[2].processing_status == ProcessingStatus.NEEDS_REVIEW


def test_prepare_short_excerpt_and_old_backlog_respects_limit(
    db_session, migrated_database, feed_entries, preparation_config
):
    old_entries = [
        replace(
            feed_entries[0],
            original_url=f"https://example.com/old/{i}",
            rss_description="Chỉ có một đoạn rất ngắn.",
        )
        for i in range(3)
    ]
    with db_session.begin():
        inserted = ingest_entries(db_session, old_entries)
    factory = sessionmaker(bind=migrated_database.connection, expire_on_commit=False)
    with httpx.Client(transport=httpx.MockTransport(no_publisher_request)) as client:
        extractor = ArticleExtractor(client, sleep=lambda _: None)
        first = prepare_pending_articles(
            factory, old_entries[0].source_id, preparation_config, extractor, max_articles=2
        )
        resumed = prepare_pending_articles(
            factory, old_entries[0].source_id, preparation_config, extractor, max_articles=2
        )
    assert first.prepared_ids == inserted.inserted_ids[:2]
    assert resumed.prepared_ids == inserted.inserted_ids[2:]
    with db_session.begin():
        row = db_session.get(Article, inserted.inserted_ids[0])
        assert row.content_origin == ContentOrigin.RSS_EXCERPT
        assert row.processing_status == ProcessingStatus.NEEDS_REVIEW
        assert row.processing_error == "extraction_disabled; insufficient_text"


@pytest.mark.parametrize(
    "status",
    [
        ProcessingStatus.READY,
        ProcessingStatus.PROCESSING,
        ProcessingStatus.FAILED,
        ProcessingStatus.NEEDS_REVIEW,
    ],
)
def test_prepare_skips_terminal_and_in_progress_articles(
    db_session, migrated_database, feed_entries, preparation_config, status
):
    with db_session.begin():
        article_id = insert_article(db_session, feed_entries[0])
        db_session.get(Article, article_id).processing_status = status
    factory = sessionmaker(bind=migrated_database.connection)
    with httpx.Client(transport=httpx.MockTransport(no_publisher_request)) as client:
        result = prepare_pending_articles(
            factory, feed_entries[0].source_id, preparation_config, ArticleExtractor(client)
        )
    assert result.prepared_ids == ()
    with db_session.begin():
        db_session.expire_all()
        row = db_session.get(Article, article_id)
        assert row.processing_status == status and row.content is None


@pytest.mark.parametrize("during_fetch", ["none", "finalize", "deactivate"])
def test_extraction_outside_transaction_and_rechecks_before_save(
    db_session, migrated_database, feed_entries, preparation_config, during_fetch
):
    config = preparation_config.model_copy(
        update={
            "article_extraction_allowed": True,
            "article_extraction": ArticleExtractionPolicy(
                public_path_prefixes=["/news"],
                content_selector="article.news-body",
                review_note="Fictional HTML fixture, permitted by test only.",
            ),
        }
    )
    with db_session.begin():
        article_id = insert_article(db_session, feed_entries[0])
    factory = sessionmaker(bind=migrated_database.connection, expire_on_commit=False)
    payload = (
        Path(__file__).resolve().parents[1] / "fixtures/html/public_article.html"
    ).read_bytes()
    requests = []

    def handler(request):
        # This assertion covers both robots and article HTTP requests.
        assert not migrated_database.connection.in_transaction()
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if during_fetch != "none":
            with factory() as session, session.begin():
                if during_fetch == "finalize":
                    session.get(Article, article_id).processing_status = ProcessingStatus.READY
                else:
                    session.get(Source, feed_entries[0].source_id).is_active = False
        return httpx.Response(200, content=payload, headers={"Content-Type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        extractor = ArticleExtractor(client, sleep=lambda _: None)
        if during_fetch == "deactivate":
            with pytest.raises(ValueError, match="Source configuration changed"):
                prepare_pending_articles(factory, feed_entries[0].source_id, config, extractor)
        else:
            result = prepare_pending_articles(factory, feed_entries[0].source_id, config, extractor)
            assert result.skipped == int(during_fetch == "finalize")
    assert requests == ["/robots.txt", "/news"]
    with db_session.begin():
        db_session.expire_all()
        row = db_session.get(Article, article_id)
        if during_fetch == "none":
            assert row.content_origin == ContentOrigin.EXTRACTED
            assert row.processing_status == ProcessingStatus.PENDING
        else:
            assert row.content is row.content_origin is None


def test_preparation_crash_keeps_committed_progress_resumable(
    db_session, migrated_database, feed_entries, preparation_config
):
    with db_session.begin():
        inserted = ingest_entries(db_session, feed_entries)
    factory = sessionmaker(bind=migrated_database.connection)
    with httpx.Client(transport=httpx.MockTransport(no_publisher_request)) as client:

        class InterruptedExtractor(ArticleExtractor):
            def extract(self, *args, **kwargs):
                if kwargs["article_id"] == inserted.inserted_ids[1]:
                    raise RuntimeError("Simulated process interruption")
                return super().extract(*args, **kwargs)

        with pytest.raises(RuntimeError, match="Simulated"):
            prepare_pending_articles(
                factory, feed_entries[0].source_id, preparation_config, InterruptedExtractor(client)
            )
        resumed = prepare_pending_articles(
            factory, feed_entries[0].source_id, preparation_config, ArticleExtractor(client)
        )
    assert resumed.prepared_ids == inserted.inserted_ids[1:]
