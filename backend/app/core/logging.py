"""Structured process logs with an allowlist of application events and numeric context."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum


class LogEvent(StrEnum):
    API_READY = "api_ready"
    ARTICLE_TEXT_EVALUATED = "article_text_evaluated"
    ARTICLE_PROCESSING_FAILED = "article_processing_failed"
    FEED_FETCH_FAILED = "feed_fetch_failed"
    FEED_PARSE_FAILED = "feed_parse_failed"
    JOB_CLAIMED = "job_claimed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_FINALIZE_FAILED = "job_finalize_failed"
    JOB_RECOVERY_STARTED = "job_recovery_started"
    MODEL_LOADING = "model_loading"
    MODEL_LOADED = "model_loaded"
    SCHEDULED_JOB_ENQUEUED = "scheduled_job_enqueued"
    SCHEDULED_TICK_FAILED = "scheduled_tick_failed"
    SCHEDULED_TICK_SKIPPED = "scheduled_tick_skipped"
    WORKER_READY = "worker_ready"
    WORKER_STOPPED = "worker_stopped"


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Raw messages, arguments and tracebacks can contain request or provider data.
        event = record.msg if isinstance(record.msg, LogEvent) else "external_log"
        fields = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
        }
        for key in ("job_id", "source_id", "article_id", "latency_ms"):
            value = getattr(record, key, None)
            fields[key] = value if type(value) is int else None
        return json.dumps(fields)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)
    # Access logs can contain query strings. App logs capture the events we need.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("httpx", "httpcore", "google_genai", "apscheduler", "sqlalchemy"):
        logging.getLogger(name).setLevel(logging.WARNING)
