"""Calibration freezes and retention flags in a disposable PostgreSQL schema."""

import pytest
from app.evaluation import corpus
from app.models import Article, ContentOrigin, Source
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration


def test_snapshot_protection_is_idempotent_and_rejects_stale_data(
    db_session, migrated_database, api_article, monkeypatch
):
    with db_session.begin():
        source = db_session.get(Source, api_article.source_id)
        source.rss_url = "https://vnexpress.net/rss/tin-moi-nhat.rss"
        api_article.content = "Nội dung giả lập"
        api_article.content_origin = ContentOrigin.EXTRACTED
        second = Article(
            source_id=source.id,
            title="Second fixture",
            original_url="https://example.com/second",
            canonical_url="https://example.com/second",
            content="Trích đoạn giả lập",
            content_origin=ContentOrigin.RSS_EXCERPT,
        )
        db_session.add(second)
    factory = sessionmaker(bind=migrated_database.connection)
    monkeypatch.setattr(corpus, "get_session_factory", lambda: factory)

    snapshot = corpus.freeze_snapshot(50)
    assert len(snapshot.items) == 2
    assert corpus.protect_snapshot(snapshot) == 2
    assert corpus.protect_snapshot(snapshot) == 2
    with factory() as session, session.begin():
        rows = session.scalars(select(Article).order_by(Article.id)).all()
        assert all(row.evaluation_exempt for row in rows)
        for row in rows:
            row.evaluation_exempt = False
        # The frozen rows are ordered newest first. Change the other row so that
        # protection encounters a valid row before detecting stale data.
        rows[0].content = "Nội dung đã thay đổi"

    with pytest.raises(ValueError, match="no longer matches"):
        corpus.protect_snapshot(snapshot)
    with factory() as session:
        assert not any(session.scalars(select(Article.evaluation_exempt)))


def test_evaluation_exempt_migration_preserves_publisher_metadata(test_database):
    db = test_database
    db.migrate("upgrade", "0005")
    with db.connection.begin():
        article_id = db.connection.scalar(
            text(
                "WITH source AS (INSERT INTO sources (name, rss_url) "
                "VALUES ('Fixture', 'https://example.com/rss') RETURNING id) "
                "INSERT INTO articles (source_id, title, original_url, canonical_url, publisher_meta) "
                "SELECT id, 'Title', 'https://example.com/a', 'https://example.com/a', "
                "CAST(:meta AS jsonb) FROM source RETURNING id"
            ),
            {"meta": '{"article:tag":["One","Two"]}'},
        )

    db.migrate("upgrade", "head")
    with db.connection.begin():
        assert (
            db.connection.scalar(
                text("SELECT evaluation_exempt FROM articles WHERE id = :id"), {"id": article_id}
            )
            is False
        )
        db.connection.execute(
            text("UPDATE articles SET evaluation_exempt = true WHERE id = :id"), {"id": article_id}
        )

    db.migrate("upgrade", "head")
    with db.connection.begin():
        assert (
            db.connection.scalar(
                text("SELECT evaluation_exempt FROM articles WHERE id = :id"), {"id": article_id}
            )
            is True
        )

    db.migrate("downgrade", "0005")
    with db.connection.begin():
        columns = {column["name"] for column in inspect(db.connection).get_columns("articles")}
        assert "evaluation_exempt" not in columns
        assert db.connection.scalar(
            text("SELECT publisher_meta FROM articles WHERE id = :id"), {"id": article_id}
        ) == {"article:tag": ["One", "Two"]}

    db.migrate("upgrade", "head")
    with db.connection.begin():
        assert (
            db.connection.scalar(
                text("SELECT evaluation_exempt FROM articles WHERE id = :id"), {"id": article_id}
            )
            is False
        )
