"""Persist deduplicated RSS articles."""

from collections.abc import Iterable
from dataclasses import dataclass

from app.models import Article, IngestionJob, JobStatus, ProcessingStatus
from app.services.rss_collector import FeedEntry
from app.services.url_normalization import normalize_url
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class IngestionResult:
    inserted_ids: tuple[int, ...]
    duplicates: int
    examined: int


def insert_article(session: Session, entry: FeedEntry) -> int | None:
    """Return a new ID or None on a canonical-URL conflict; caller owns commit."""
    statement = (
        insert(Article)
        .values(
            source_id=entry.source_id,
            title=entry.title,
            original_url=entry.original_url,
            canonical_url=normalize_url(entry.original_url),
            published_at=entry.published_at,
            rss_description=entry.rss_description,
            image_url=entry.image_url,
            processing_status=ProcessingStatus.PENDING,
        )
        .on_conflict_do_nothing(index_elements=[Article.canonical_url])
        .returning(Article.id)
    )
    return session.scalar(statement)


def ingest_entries(
    session: Session,
    entries: Iterable[FeedEntry],
    *,
    max_insertions: int = 20,
    job_id: int | None = None,
) -> IngestionResult:
    """Duplicates consume no insertion capacity and never update existing rows."""
    if max_insertions <= 0:
        raise ValueError("Insertion limit must be positive")
    inserted_ids = []
    duplicates = 0
    examined = 0
    for entry in entries:
        article_id = insert_article(session, entry)
        examined += 1
        if article_id is None:
            duplicates += 1
        else:
            inserted_ids.append(article_id)
        if len(inserted_ids) == max_insertions:
            break
    if inserted_ids and job_id is not None:
        changed = session.scalar(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == JobStatus.RUNNING)
            .values(articles_created=IngestionJob.articles_created + len(inserted_ids))
            .returning(IngestionJob.id)
        )
        if changed is None:
            raise ValueError("Article insertions require a running job")
    return IngestionResult(tuple(inserted_ids), duplicates, examined)
