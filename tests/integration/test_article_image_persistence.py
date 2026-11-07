"""Persist and expose image metadata only in disposable PostgreSQL schemas."""

from dataclasses import replace

import pytest
from app.backfill_article_images import ImageCandidate, save_article_image
from app.models import Article, ProcessingStatus
from app.services.ingestion import insert_article
from app.services.rss_collector import FeedEntry
from sqlalchemy import select

pytestmark = pytest.mark.integration


def test_image_backfill_preserves_article_and_summary_state(db_session, api_article):
    candidate = ImageCandidate(api_article.id, api_article.original_url, api_article.source_id)
    original_status = api_article.processing_status
    with db_session.begin():
        assert save_article_image(db_session, candidate, "https://cdn.example.com/a.jpg")
    with db_session.begin():
        db_session.expire_all()
        article = db_session.get(Article, api_article.id)
        assert article.image_url == "https://cdn.example.com/a.jpg"
        assert article.processing_status == original_status
        assert article.summary is None
        assert not save_article_image(
            db_session, candidate, "https://cdn.example.com/replacement.jpg"
        )
        assert not save_article_image(db_session, candidate, "javascript:bad")


def test_backfill_rollback_and_changed_article_guard(db_session, api_article):
    candidate = ImageCandidate(api_article.id, api_article.original_url, api_article.source_id)
    with pytest.raises(RuntimeError), db_session.begin():
        assert save_article_image(db_session, candidate, "https://cdn.example.com/a.jpg")
        raise RuntimeError("Simulated rollback")
    with db_session.begin():
        db_session.expire_all()
        assert db_session.get(Article, api_article.id).image_url is None
        assert not save_article_image(
            db_session,
            replace(candidate, original_url="https://example.com/changed"),
            "https://cdn.example.com/a.jpg",
        )
        db_session.get(Article, api_article.id).source.is_active = False
        db_session.flush()
        assert not save_article_image(db_session, candidate, "https://cdn.example.com/a.jpg")


def test_collected_image_persists_without_changing_duplicate(db_session, api_article):
    entry = FeedEntry(
        source_id=api_article.source_id,
        title="New image article",
        original_url="https://example.com/new",
        published_at=None,
        rss_description="Description",
        image_url="https://cdn.example.com/rss.jpg",
    )
    with db_session.begin():
        article_id = insert_article(db_session, entry)
    with db_session.begin():
        article = db_session.get(Article, article_id)
        assert article.image_url == entry.image_url
        assert article.processing_status == ProcessingStatus.PENDING
        assert (
            insert_article(
                db_session, replace(entry, image_url="https://cdn.example.com/changed.jpg")
            )
            is None
        )
        db_session.expire_all()
        assert (
            db_session.scalar(select(Article.image_url).where(Article.id == article_id))
            == entry.image_url
        )
