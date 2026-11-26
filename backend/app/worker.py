"""Single-process worker: durable PostgreSQL jobs and an in-memory enqueue timer."""

import argparse
import logging
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import LogSettings, Settings, get_settings
from app.core.logging import LogEvent, configure_logging
from app.core.source_config import DEFAULT_SOURCE_CONFIG, SourceConfig, load_source_config
from app.db.session import get_engine, get_session_factory
from app.models import Article, IngestionJob, JobTrigger, ProcessingStatus, Source
from app.services.article_extractor import ArticleExtractor
from app.services.article_processing import NewsProcessor, process_article
from app.services.feed_ingestion import ingest_entries
from app.services.job_service import (
    JobClaim,
    JobSubmissionError,
    claim_job,
    enqueue_job,
    finish_job,
    recover_abandoned_work,
)
from app.services.pipeline import open_pipeline
from app.services.rss_collector import FeedError, FeedParseError, RSSCollector
from app.services.source_guard import require_active_source
from app.services.text_preparation import prepare_pending_articles, recover_review_articles

logger = logging.getLogger(__name__)


def scheduled_tick(factory: Callable[[], Session], settings: Settings, stop: Event) -> None:
    if stop.is_set():
        return
    job_id = None
    try:
        # Each invocation owns its Session; no Session crosses a thread boundary.
        with factory() as session, session.begin():
            if not stop.is_set():
                job = enqueue_job(
                    session, trigger=JobTrigger.SCHEDULED, max_backlog=settings.MAX_JOB_BACKLOG
                )
                job_id = job.id if job is not None else None
        if job_id is not None:
            logger.info(LogEvent.SCHEDULED_JOB_ENQUEUED, extra={"job_id": job_id})
    except JobSubmissionError:
        logger.info(LogEvent.SCHEDULED_TICK_SKIPPED)
    except SQLAlchemyError:
        logger.error(LogEvent.SCHEDULED_TICK_FAILED)


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


@dataclass(frozen=True)
class JobBudget:
    insertions: int
    results: int


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

    def remaining(self, job_id: int) -> JobBudget:
        with self.factory() as session:
            job = session.get(IngestionJob, job_id)
            return JobBudget(
                insertions=max(0, self.settings.JOB_MAX_ARTICLE_INSERTIONS - job.articles_created),
                results=max(0, self.settings.JOB_MAX_ARTICLE_RESULTS - job.articles_processed),
            )

    def _recover_excerpts(self, source_id: int, config: SourceConfig, limit: int) -> None:
        recover_review_articles(
            self.factory,
            source_id,
            config,
            self.extractor,
            max_articles=limit,
            should_stop=self.stop.is_set,
        )

    def _prepare_text(
        self, job_id: int, source_id: int, config: SourceConfig, limit: int
    ) -> list[int]:
        with self.factory() as session:
            query = select(Article.id).where(
                Article.source_id == source_id,
                Article.processing_status == ProcessingStatus.PENDING,
            )
            if not config.ai_processing_allowed:
                query = query.where(Article.content.is_(None), Article.content_origin.is_(None))
            ids = list(session.scalars(query.order_by(Article.id).limit(limit)))
        if not ids:
            return []
        prepare_pending_articles(
            self.factory,
            source_id,
            config,
            self.extractor,
            max_articles=limit,
            job_id=job_id,
            should_stop=self.stop.is_set,
            article_ids=ids,
        )
        return ids

    def _summarize(
        self, job_id: int, source_id: int, config: SourceConfig, candidate_ids: list[int]
    ) -> None:
        budget = self.remaining(job_id)
        with self.factory() as session:
            ids = session.scalars(
                select(Article.id)
                .where(
                    Article.source_id == source_id,
                    Article.processing_status == ProcessingStatus.PENDING,
                    Article.id.in_(candidate_ids),
                )
                .order_by(Article.id)
                .limit(budget.results)
            ).all()
        for article_id in ids:
            if self.stop.is_set():
                break
            process_article(
                self.factory, article_id, config, self.graph, job_id=job_id, **self.model_names
            )

    def process_pending(self, job_id: int, source_id: int, config: SourceConfig) -> None:
        budget = self.remaining(job_id)
        if not budget.results or self.stop.is_set():
            return
        self._recover_excerpts(source_id, config, budget.results)
        if self.stop.is_set():
            return
        ids = self._prepare_text(job_id, source_id, config, budget.results)
        if not ids or not config.ai_processing_allowed or self.stop.is_set():
            return
        self._summarize(job_id, source_id, config, ids)

    def run_job(self, claim: JobClaim) -> None:
        """External work happens only after the caller has committed the job claim."""
        started = monotonic()
        logger.info(LogEvent.JOB_CLAIMED, extra={"job_id": claim.id, "source_id": claim.source_id})
        try:
            self._run_job(claim, started)
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
                logger.error(LogEvent.JOB_FINALIZE_FAILED, extra={"job_id": claim.id})
            raise

    def _run_job(self, claim: JobClaim, started: float) -> None:
        with self.factory() as session:
            query = select(Source.id, Source.rss_url).where(Source.is_active.is_(True))
            if claim.source_id is not None:
                query = query.where(Source.id == claim.source_id)
            sources = session.execute(query.order_by(Source.id)).all()
        eligible = []
        failures = 0
        for source_id, url in sources:
            config = self.configs.get(url)
            if config is None or not config.is_usable:
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
            except FeedError as exc:
                event = (
                    LogEvent.FEED_PARSE_FAILED
                    if isinstance(exc, FeedParseError)
                    else LogEvent.FEED_FETCH_FAILED
                )
                logger.warning(event, extra={"job_id": claim.id, "source_id": source_id})
                failures += 1
                continue
            if self.stop.is_set():
                return
            budget = self.remaining(claim.id)
            with self.factory() as session, session.begin():
                require_active_source(session, source_id, config)
                if budget.insertions:
                    ingest_entries(
                        session, entries, max_insertions=budget.insertions, job_id=claim.id
                    )
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
        logger.log(
            logging.INFO if successes else logging.ERROR,
            LogEvent.JOB_COMPLETED if successes else LogEvent.JOB_FAILED,
            extra={
                "job_id": claim.id,
                "source_id": claim.source_id,
                "latency_ms": round((monotonic() - started) * 1000),
            },
        )

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
    if not settings.GEMINI_API_KEY or not settings.GEMINI_MODEL.strip():
        raise ValueError("Worker requires GEMINI_API_KEY and GEMINI_MODEL")
    with open_pipeline(settings) as (graph, summarize_model_name, agent_model_name):
        logger.info(LogEvent.JOB_RECOVERY_STARTED)
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
                summarize_model_name=summarize_model_name,
                agent_model_name=agent_model_name,
                stop=stop,
            )
            scheduler = build_scheduler(factory, settings, stop)
            scheduler.start()
            logger.info(LogEvent.WORKER_READY)
            try:
                worker.run_forever()
            finally:
                stop.set()
                scheduler.shutdown(wait=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    args = parser.parse_args()
    stop = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        configure_logging(LogSettings().LOG_LEVEL)
        serve(get_session_factory(), get_settings(), load_source_config(args.config), stop)
    except Exception:  # noqa: BLE001 -- redact provider/DB credentials at the process boundary.
        logger.error(LogEvent.WORKER_STOPPED)
        raise SystemExit(1) from None
    finally:
        if get_engine.cache_info().currsize:
            get_engine().dispose()


if __name__ == "__main__":
    main()
