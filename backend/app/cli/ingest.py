"""Persist deduplicated RSS articles and run one bounded manual collection."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from app.core.config import LogSettings, get_settings
from app.core.logging import configure_logging
from app.core.source_config import DEFAULT_SOURCE_CONFIG, load_source_config
from app.db.session import get_session_factory
from app.models import Article, Source
from app.services.article_extractor import ArticleExtractor
from app.services.article_processing import process_article
from app.services.feed_ingestion import IngestionResult, ingest_entries
from app.services.pipeline import open_pipeline
from app.services.rss_collector import FeedError, RSSCollector
from app.services.source_guard import require_active_source
from app.services.text_preparation import prepare_pending_articles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError


def main() -> None:
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
            with open_pipeline(get_settings()) as (
                graph,
                summarize_model_name,
                agent_model_name,
            ):
                changed = process_article(
                    factory,
                    args.process_article_id,
                    config,
                    graph,
                    summarize_model_name=summarize_model_name,
                    agent_model_name=agent_model_name,
                )
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
    except (FeedError, ValueError, RuntimeError):
        raise SystemExit(
            "Ingestion failed: check source, feed and processing configuration"
        ) from None


if __name__ == "__main__":
    try:
        configure_logging(LogSettings().LOG_LEVEL)
        main()
    except Exception:  # noqa: BLE001 -- keep credentials out of CLI tracebacks.
        raise SystemExit("Command failed: check configuration and service availability") from None
