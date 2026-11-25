"""Prepare stored article text before AI processing."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.models import Article, ContentOrigin, ProcessingStatus
from app.seed_sources import SourceConfig
from app.services.article_extractor import ArticleExtractor, ExtractionResult
from app.services.job_service import record_article_result
from app.services.source_guard import require_active_source
from sqlalchemy import Executable, func, select, update
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class TextPreparationResult:
    prepared_ids: tuple[int, ...]
    pending: int
    needs_review: int
    skipped: int


def _extract_and_update(
    factory: Callable[[], Session],
    source_id: int,
    config: SourceConfig,
    extractor: ArticleExtractor,
    rows: Iterable[tuple[int, str, str | None]],
    build_update: Callable[[int, str, str | None, ExtractionResult], tuple[Executable, bool]],
    *,
    job_id: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> TextPreparationResult:
    prepared_ids = []
    pending = needs_review = skipped = 0
    for article_id, url, description in rows:
        if should_stop():
            break
        result = extractor.extract(
            url, description, config, source_id=source_id, article_id=article_id, job_id=job_id
        )
        statement, is_pending = build_update(article_id, url, description, result)
        with factory() as session, session.begin():
            require_active_source(session, source_id, config)
            saved_id = session.scalar(statement)
            if saved_id is not None and not is_pending and job_id is not None:
                record_article_result(session, job_id, ProcessingStatus.NEEDS_REVIEW)
        if saved_id is None:
            skipped += 1
        else:
            prepared_ids.append(saved_id)
            pending += int(is_pending)
            needs_review += int(not is_pending)
    return TextPreparationResult(tuple(prepared_ids), pending, needs_review, skipped)


def prepare_pending_articles(
    factory: Callable[[], Session],
    source_id: int,
    config: SourceConfig,
    extractor: ArticleExtractor,
    *,
    max_articles: int = 20,
    job_id: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    article_ids: list[int] | None = None,
) -> TextPreparationResult:
    """Resume the oldest unprepared pending rows, including rows absent from today's feed.

    Snapshot primitives and close the read session before publisher IO. Each result
    commits in a short transaction with a status guard, so a concurrent finalization
    or a replay cannot overwrite ready/previously prepared text.
    """
    if max_articles <= 0:
        raise ValueError("Text preparation limit must be positive")
    with factory() as session, session.begin():
        require_active_source(session, source_id, config)
        query = (
            select(Article.id, Article.original_url, Article.rss_description)
            .where(
                Article.source_id == source_id,
                Article.processing_status == ProcessingStatus.PENDING,
                Article.content.is_(None),
                Article.content_origin.is_(None),
            )
            .order_by(Article.id)
        )
        if article_ids is not None:
            query = query.where(Article.id.in_(article_ids))
        rows = session.execute(query.limit(max_articles)).all()

    def build_update(
        article_id: int, url: str, description: str | None, result: ExtractionResult
    ) -> tuple[Executable, bool]:
        status = ProcessingStatus.PENDING if result.usable else ProcessingStatus.NEEDS_REVIEW
        statement = (
            update(Article)
            .where(
                Article.id == article_id,
                Article.processing_status == ProcessingStatus.PENDING,
                Article.content.is_(None),
                Article.content_origin.is_(None),
                Article.original_url == url,
                Article.rss_description.is_not_distinct_from(description),
            )
            .values(
                image_url=func.coalesce(Article.image_url, result.image_url),
                content=result.text,
                content_origin=result.content_origin,
                processing_status=status,
                processing_error=result.failure_reason,
            )
            .returning(Article.id)
        )
        return statement, result.usable

    return _extract_and_update(
        factory,
        source_id,
        config,
        extractor,
        rows,
        build_update,
        job_id=job_id,
        should_stop=should_stop,
    )


def recover_review_articles(
    factory: Callable[[], Session],
    source_id: int,
    config: SourceConfig,
    extractor: ArticleExtractor,
    *,
    max_articles: int = 20,
    should_stop: Callable[[], bool] = lambda: False,
) -> TextPreparationResult:
    """Retry old excerpt-only articles after full-text extraction is enabled.

    Only articles without an AI draft and with the earlier extraction-disabled
    reason qualify. A failed extraction is recorded once, avoiding a publisher
    request on every scheduled job. Human decisions and rejected drafts are untouched.
    """
    if max_articles <= 0:
        raise ValueError("Text preparation limit must be positive")
    if not (config.article_extraction_allowed and config.ai_processing_allowed):
        return TextPreparationResult((), 0, 0, 0)
    with factory() as session, session.begin():
        require_active_source(session, source_id, config)
        rows = session.execute(
            select(Article.id, Article.original_url, Article.rss_description)
            .where(
                Article.source_id == source_id,
                Article.processing_status == ProcessingStatus.NEEDS_REVIEW,
                ~Article.summary.has(),
                Article.processing_error.like("extraction_disabled;%"),
            )
            .order_by(Article.id)
            .limit(max_articles)
        ).all()

    def build_update(
        article_id: int, url: str, description: str | None, result: ExtractionResult
    ) -> tuple[Executable, bool]:
        recovered = result.usable and result.content_origin == ContentOrigin.EXTRACTED
        statement = (
            update(Article)
            .where(
                Article.id == article_id,
                Article.processing_status == ProcessingStatus.NEEDS_REVIEW,
                ~Article.summary.has(),
                Article.original_url == url,
                Article.rss_description.is_not_distinct_from(description),
                Article.processing_error.like("extraction_disabled;%"),
            )
            .values(
                image_url=func.coalesce(Article.image_url, result.image_url),
                content=result.text if recovered else Article.content,
                content_origin=result.content_origin if recovered else Article.content_origin,
                processing_status=(
                    ProcessingStatus.PENDING if recovered else ProcessingStatus.NEEDS_REVIEW
                ),
                processing_error=(
                    None if recovered else result.failure_reason or "full_text_unavailable"
                ),
            )
            .returning(Article.id)
        )
        return statement, recovered

    return _extract_and_update(
        factory,
        source_id,
        config,
        extractor,
        rows,
        build_update,
        should_stop=should_stop,
    )
