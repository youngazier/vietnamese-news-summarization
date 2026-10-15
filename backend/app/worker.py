"""Single-process worker: durable PostgreSQL jobs and an in-memory enqueue timer."""

import argparse
import logging
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_engine, get_session_factory
from app.models import Article, IngestionJob, JobTrigger, ProcessingStatus, Source
from app.seed_sources import DEFAULT_SOURCE_CONFIG, SourceConfig, load_source_config
from app.services.article_extractor import ArticleExtractor
from app.services.ingestion import (
    NewsProcessor,
    ingest_entries,
    prepare_pending_articles,
    process_article,
    require_active_source,
)
from app.services.job_service import (
    JobClaim,
    JobSubmissionError,
    claim_job,
    enqueue_job,
    finish_job,
    recover_abandoned_work,
)
from app.services.rss_collector import FeedError, RSSCollector

logger = logging.getLogger(__name__)


def scheduled_tick(factory: Callable[[], Session], settings: Settings, stop: Event) -> None:
    if stop.is_set():
        return
    try:
        # Each invocation owns its Session; no Session crosses a thread boundary.
        with factory() as session, session.begin():
            if not stop.is_set():
                enqueue_job(
                    session, trigger=JobTrigger.SCHEDULED, max_backlog=settings.MAX_JOB_BACKLOG
                )
    except JobSubmissionError:
        logger.info("Scheduled tick skipped: scope unavailable or backlog full")
    except SQLAlchemyError:
        logger.error("Scheduled tick failed: database unavailable")


def build_scheduler(
    factory: Callable[[], Session], settings: Settings, stop: Event
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=UTC)
    scheduler.add_job(
        scheduled_tick,
        "interval",
        minutes=settings.COLLECTION_INTERVAL_MINUTES,
        args=(factory, settings, stop),
        id="collection",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    return scheduler


class Worker:
    def __init__(
        self,
        factory: Callable[[], Session],
        settings: Settings,
        configs: list[SourceConfig],
        collector: RSSCollector,
        extractor: ArticleExtractor,
        graph: NewsProcessor,
        *,
        summarize_model_name: str,
        agent_model_name: str,
        stop: Event,
    ) -> None:
        self.factory = factory
        self.settings = settings
        self.configs = {config.rss_url: config for config in configs}
        self.collector = collector
        self.extractor = extractor
        self.graph = graph
        self.model_names = {
            "summarize_model_name": summarize_model_name,
            "agent_model_name": agent_model_name,
        }
        self.stop = stop

    def remaining(self, job_id: int) -> tuple[int, int]:
        with self.factory() as session:
            job = session.get(IngestionJob, job_id)
            return (
                max(0, self.settings.JOB_MAX_ARTICLE_INSERTIONS - job.articles_created),
                max(0, self.settings.JOB_MAX_ARTICLE_RESULTS - job.articles_processed),
            )

    def process_pending(self, job_id: int, source_id: int, config: SourceConfig) -> None:
        _, remaining = self.remaining(job_id)
        if not remaining or self.stop.is_set():
            return
        with self.factory() as session:
            query = select(Article.id).where(
                Article.source_id == source_id,
                Article.processing_status == ProcessingStatus.PENDING,
            )
            if not config.ai_processing_allowed:
                query = query.where(Article.content.is_(None), Article.content_origin.is_(None))
            ids = list(session.scalars(query.order_by(Article.id).limit(remaining)))
        if not ids:
            return
        prepare_pending_articles(
            self.factory,
            source_id,
            config,
            self.extractor,
            max_articles=remaining,
            job_id=job_id,
            should_stop=self.stop.is_set,
            article_ids=ids,
        )
        if not config.ai_processing_allowed or self.stop.is_set():
            return
        _, remaining = self.remaining(job_id)
        with self.factory() as session:
            ids = session.scalars(
                select(Article.id)
                .where(
                    Article.source_id == source_id,
                    Article.processing_status == ProcessingStatus.PENDING,
                    Article.id.in_(ids),
                )
                .order_by(Article.id)
                .limit(remaining)
            ).all()
        for article_id in ids:
            if self.stop.is_set():
                break
            process_article(
                self.factory, article_id, config, self.graph, job_id=job_id, **self.model_names
            )

    def run_job(self, claim: JobClaim) -> None:
        """External work happens only after the caller has committed the job claim."""
        try:
            self._run_job(claim)
        except Exception:
            # Stop this worker on fatal DB/pipeline errors. Startup recovery resets
            # any processing claim; continuing could strand it indefinitely.
            try:
                with self.factory() as session, session.begin():
                    finish_job(
                        session,
                        claim.id,
                        failed=True,
                        message="Job failed: database or pipeline error",
                    )
            except SQLAlchemyError:
                logger.error("Could not finalize job; startup recovery is required")
            raise

    def _run_job(self, claim: JobClaim) -> None:
        with self.factory() as session:
            query = select(Source.id, Source.rss_url).where(Source.is_active.is_(True))
            if claim.source_id is not None:
                query = query.where(Source.id == claim.source_id)
            sources = session.execute(query.order_by(Source.id)).all()
        eligible = []
        failures = 0
        for source_id, url in sources:
            config = self.configs.get(url)
            if (
                config is None
                or not config.is_active
                or config.review_status != "rss_reader_supported"
            ):
                failures += 1
                continue
            eligible.append((source_id, config))

        # Resume backlog for every source before inserting any new articles.
        for source_id, config in eligible:
            if self.stop.is_set():
                return
            self.process_pending(claim.id, source_id, config)

        successes = 0
        for source_id, config in eligible:
            if self.stop.is_set():
                return
            try:
                entries = self.collector.collect(source_id, config)
            except FeedError:
                failures += 1
                continue
            if self.stop.is_set():
                return
            insertions, _ = self.remaining(claim.id)
            with self.factory() as session, session.begin():
                require_active_source(session, source_id, config)
                if insertions:
                    ingest_entries(session, entries, max_insertions=insertions, job_id=claim.id)
                session.get(Source, source_id).last_fetched_at = datetime.now(UTC)
            successes += 1
            self.process_pending(claim.id, source_id, config)

        if self.stop.is_set():
            return
        message = None
        if not successes:
            message = "No source feed succeeded"
        elif failures:
            message = "Some source feeds failed or lacked active reviewed configuration"
        with self.factory() as session, session.begin():
            finish_job(session, claim.id, failed=not successes, message=message)

    def run_once(self) -> bool:
        if self.stop.is_set():
            return False
        with self.factory() as session, session.begin():
            claim = claim_job(session)
        if claim is None:
            return False
        self.run_job(claim)
        return True

    def run_forever(self) -> None:
        while not self.stop.is_set():
            if not self.run_once():
                self.stop.wait(self.settings.WORKER_POLL_INTERVAL_SECONDS)


def serve(
    factory: Callable[[], Session], settings: Settings, configs: list[SourceConfig], stop: Event
) -> None:
    # Worker-only imports: API startup never loads inference libraries or a model.
    from app.agents.graph import build_news_graph
    from app.services.gemini_service import GeminiService
    from app.services.summary_service import get_summary_service

    if not settings.GEMINI_API_KEY or not settings.GEMINI_MODEL.strip():
        raise ValueError("Worker requires GEMINI_API_KEY and GEMINI_MODEL")
    logger.info("Loading local summarizer")
    summarizer = get_summary_service()
    logger.info("Local summarizer loaded; initializing provider and graph")
    provider = GeminiService(settings)
    try:
        graph = build_news_graph(
            summarizer, provider, max_attempts=settings.MAX_GRAPH_DRAFT_ATTEMPTS
        )
        logger.info("Recovering abandoned database work")
        with factory() as session, session.begin():
            recover_abandoned_work(session)
        if stop.is_set():
            return
        with httpx.Client() as client:
            worker = Worker(
                factory,
                settings,
                configs,
                RSSCollector(client),
                ArticleExtractor(client),
                graph,
                summarize_model_name=summarizer.model_id,
                agent_model_name=provider.model_id,
                stop=stop,
            )
            scheduler = build_scheduler(factory, settings, stop)
            scheduler.start()
            logger.info("Worker ready; scheduler and job polling started")
            try:
                worker.run_forever()
            finally:
                stop.set()
                scheduler.shutdown(wait=True)
    finally:
        provider.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    stop = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        serve(get_session_factory(), get_settings(), load_source_config(args.config), stop)
    except Exception:  # noqa: BLE001 -- redact provider/DB credentials at the process boundary.
        # Provider/DB exception strings can contain credentials, URLs or source text.
        raise SystemExit(
            "Worker stopped: check database, provider, model and source configuration"
        ) from None
    finally:
        if get_engine.cache_info().currsize:
            get_engine().dispose()


if __name__ == "__main__":
    main()
