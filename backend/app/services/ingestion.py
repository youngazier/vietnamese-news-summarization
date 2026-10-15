"""Persist deduplicated RSS articles and run one bounded manual collection."""

import argparse
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
from app.agents.schemas import ReviewedNews
from app.agents.state import NewsState
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models import Article, IngestionJob, JobStatus, ProcessingStatus, Source
from app.seed_sources import DEFAULT_SOURCE_CONFIG, SourceConfig, load_source_config
from app.services.article_extractor import (
    MAX_TEXT_CHARACTERS,
    MIN_TEXT_CHARACTERS,
    ArticleExtractor,
)
from app.services.job_service import record_article_result
from app.services.rss_collector import FeedEntry, FeedError, RSSCollector
from app.services.summary_persistence import persist_summary
from app.services.url_normalization import normalize_url
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class IngestionResult:
    inserted_ids: tuple[int, ...]
    duplicates: int
    examined: int


@dataclass(frozen=True)
class TextPreparationResult:
    prepared_ids: tuple[int, ...]
    pending: int
    needs_review: int
    skipped: int


class NewsProcessor(Protocol):
    def invoke(self, input: NewsState) -> NewsState: ...


def process_article(
    factory: Callable[[], Session],
    article_id: int,
    config: SourceConfig,
    graph: NewsProcessor,
    *,
    summarize_model_name: str,
    agent_model_name: str,
    job_id: int | None = None,
) -> bool:
    """Claim one eligible pending article; run inference without an open transaction.

    Returns True only for a new terminal transition. Provider/model/schema failures
    become failed articles with a fixed error. Database failures propagate so the
    caller can stop the cycle; the committed processing claim remains recoverable.
    """
    if not config.ai_processing_allowed:
        raise ValueError("Source AI processing is disabled")
    with factory() as session, session.begin():
        source_id = session.scalar(select(Article.source_id).where(Article.id == article_id))
        if source_id is None:
            raise ValueError("Article does not exist")
        require_active_source(session, source_id, config)
        article = session.scalar(select(Article).where(Article.id == article_id).with_for_update())
        if article.processing_status != ProcessingStatus.PENDING:
            return False
        if (
            article.content is None
            or not MIN_TEXT_CHARACTERS <= len(article.content.strip()) <= MAX_TEXT_CHARACTERS
            or article.content_origin is None
        ):
            article.processing_status = ProcessingStatus.NEEDS_REVIEW
            article.processing_error = "Insufficient prepared source text"
            if job_id is not None:
                record_article_result(session, job_id, ProcessingStatus.NEEDS_REVIEW)
            return True
        state: NewsState = {
            "article_id": article.id,
            "title": article.title,
            "source_text": article.content,
            "content_origin": article.content_origin,
            "attempts": 0,
            "approved": False,
            "feedback": "",
        }
        article.processing_status = ProcessingStatus.PROCESSING
        article.processing_error = None

    try:
        result = ReviewedNews.model_validate(graph.invoke(state))
        # A graph must return a decision about this exact immutable snapshot.
        if any(
            getattr(result, key) != state[key]
            for key in ("article_id", "title", "source_text", "content_origin")
        ):
            raise ValueError("Graph changed article input")
    except Exception:  # noqa: BLE001 -- model/provider/schema failures share a redacted boundary.
        with factory() as session, session.begin():
            changed = session.scalar(
                update(Article)
                .where(
                    Article.id == article_id,
                    Article.processing_status == ProcessingStatus.PROCESSING,
                    Article.title == state["title"],
                    Article.content == state["source_text"],
                    Article.content_origin == state["content_origin"],
                )
                .values(
                    processing_status=ProcessingStatus.FAILED,
                    processing_error="AI processing failed",
                )
                .returning(Article.id)
            )
            if changed is not None and job_id is not None:
                record_article_result(session, job_id, ProcessingStatus.FAILED)
        return changed is not None

    with factory() as session, session.begin():
        require_active_source(session, source_id, config)
        return persist_summary(
            session,
            result,
            summarize_model_name=summarize_model_name,
            agent_model_name=agent_model_name,
            job_id=job_id,
        )


def require_active_source(session: Session, source_id: int, config: SourceConfig) -> None:
    source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if (
        source is None
        or not source.is_active
        or source.rss_url != config.rss_url
        or not config.is_active
        or config.review_status != "rss_reader_supported"
    ):
        raise ValueError("Source configuration changed during collection")


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

    prepared_ids = []
    pending = needs_review = skipped = 0
    for article_id, url, description in rows:
        if should_stop():
            break
        result = extractor.extract(
            url, description, config, source_id=source_id, article_id=article_id, job_id=job_id
        )
        status = ProcessingStatus.PENDING if result.usable else ProcessingStatus.NEEDS_REVIEW
        with factory() as session, session.begin():
            require_active_source(session, source_id, config)
            saved_id = session.scalar(
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
                    content=result.text,
                    content_origin=result.content_origin,
                    processing_status=status,
                    processing_error=result.failure_reason,
                )
                .returning(Article.id)
            )
            if saved_id is not None and not result.usable and job_id is not None:
                record_article_result(session, job_id, ProcessingStatus.NEEDS_REVIEW)
        if saved_id is None:
            skipped += 1
        else:
            prepared_ids.append(saved_id)
            pending += int(result.usable)
            needs_review += int(not result.usable)
    return TextPreparationResult(tuple(prepared_ids), pending, needs_review, skipped)


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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    # HTTPX's INFO request lines include full URLs; keep only our redacted events.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    parser.add_argument("--verify-repeat", action="store_true")
    parser.add_argument(
        "--process-article-id",
        type=int,
        help="Process one stored article with a reviewed AI-enabled source; no feed fetch",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Resume stored pending articles without fetching the feed",
    )
    args = parser.parse_args()

    try:
        configs = load_source_config(args.config)
        factory = get_session_factory()
        # End this short read transaction before any publisher request.
        with factory() as session:
            source = session.get(Source, args.source_id)
            if source is None or not source.is_active:
                raise ValueError("Source must exist and be active")
            config = next((item for item in configs if item.rss_url == source.rss_url), None)
            if config is None or not config.is_active:
                raise ValueError("Source must have active reviewed configuration")
            source_id = source.id

        if args.process_article_id is not None:
            if not config.ai_processing_allowed:
                raise ValueError("Source AI processing is disabled")
            with factory() as session:
                article_source_id = session.scalar(
                    select(Article.source_id).where(Article.id == args.process_article_id)
                )
                if article_source_id != source_id:
                    raise ValueError("Article must belong to the selected source")
            # Import/load worker dependencies only for this explicit processing path.
            from app.agents.graph import build_news_graph
            from app.services.gemini_service import GeminiService
            from app.services.summary_service import get_summary_service

            settings = get_settings()
            summarizer = get_summary_service()
            provider = GeminiService(settings)
            try:
                graph = build_news_graph(
                    summarizer, provider, max_attempts=settings.MAX_GRAPH_DRAFT_ATTEMPTS
                )
                changed = process_article(
                    factory,
                    args.process_article_id,
                    config,
                    graph,
                    summarize_model_name=summarizer.model_id,
                    agent_model_name=provider.model_id,
                )
            finally:
                provider.close()
            print(json.dumps({"article_id": args.process_article_id, "changed": changed}))
            return

        result = IngestionResult((), 0, 0)
        entries = []
        with httpx.Client() as client:
            if not args.prepare_only:
                entries = RSSCollector(client).collect(source_id, config)

                with factory() as session, session.begin():
                    require_active_source(session, source_id, config)
                    result = ingest_entries(
                        session, entries, max_insertions=get_settings().JOB_MAX_ARTICLE_INSERTIONS
                    )
                    session.get(Source, source_id).last_fetched_at = datetime.now(UTC)

            extractor = ArticleExtractor(client)
            prepared = prepare_pending_articles(
                factory,
                source_id,
                config,
                extractor,
                max_articles=get_settings().JOB_MAX_ARTICLE_RESULTS,
            )

        output = {
            "source_id": source_id,
            "feed_entries": len(entries),
            "examined": result.examined,
            "inserted_ids": result.inserted_ids,
            "duplicates": result.duplicates,
            "prepared_ids": prepared.prepared_ids,
            "text_pending": prepared.pending,
            "text_needs_review": prepared.needs_review,
            "text_skipped": prepared.skipped,
        }
        if args.verify_repeat:
            # Replay precisely the attempted entries, excluding unprocessed overflow.
            with factory() as session, session.begin():
                repeated = ingest_entries(session, entries[: result.examined])
            if repeated.inserted_ids:
                raise RuntimeError("Replay unexpectedly inserted articles")
            output["repeat_inserted"] = len(repeated.inserted_ids)
            output["repeat_duplicates"] = repeated.duplicates
        print(json.dumps(output))
    except SQLAlchemyError:
        raise SystemExit("Ingestion failed: database operation unavailable") from None
    except (FeedError, ValueError, RuntimeError) as exc:
        # Validation/feed errors are deliberately short; do not print DB exceptions.
        raise SystemExit(f"Ingestion failed: {exc}") from None


if __name__ == "__main__":
    main()
