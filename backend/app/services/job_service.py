"""Durable job coordination. Callers own each short transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import Article, IngestionJob, JobStatus, JobTrigger, ProcessingStatus, Source
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

# Shared by API and scheduler; never hold this lock during external work.
SUBMISSION_LOCK = 748_203_701
ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


class JobSubmissionError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class JobClaim:
    id: int
    source_id: int | None


def enqueue_job(
    session: Session,
    *,
    source_id: int | None = None,
    trigger: JobTrigger = JobTrigger.MANUAL,
    max_backlog: int = 5,
) -> IngestionJob | None:
    session.execute(select(func.pg_advisory_xact_lock(SUBMISSION_LOCK)))
    if source_id is not None:
        source = session.get(Source, source_id)
        if source is None:
            raise JobSubmissionError(404, "source_not_found", "Source not found.")
        if not source.is_active:
            raise JobSubmissionError(422, "source_inactive", "Source is inactive.")
    elif session.scalar(select(Source.id).where(Source.is_active.is_(True)).limit(1)) is None:
        raise JobSubmissionError(422, "no_active_sources", "No active sources are available.")

    if (
        trigger == JobTrigger.SCHEDULED
        and session.scalar(
            select(IngestionJob.id)
            .where(IngestionJob.trigger == trigger, IngestionJob.status.in_(ACTIVE_JOB_STATUSES))
            .limit(1)
        )
        is not None
    ):
        return None
    count = session.scalar(
        select(func.count())
        .select_from(IngestionJob)
        .where(IngestionJob.status.in_(ACTIVE_JOB_STATUSES))
    )
    if count >= max_backlog:
        raise JobSubmissionError(429, "job_backlog_full", "Job backlog is full.")
    job = IngestionJob(source_id=source_id, trigger=trigger, status=JobStatus.PENDING)
    session.add(job)
    session.flush()
    return job


def claim_job(session: Session) -> JobClaim | None:
    job = session.scalar(
        select(IngestionJob)
        .where(IngestionJob.status == JobStatus.PENDING)
        .order_by(IngestionJob.created_at, IngestionJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job.finished_at = None
    job.error_message = None
    session.flush()
    return JobClaim(job.id, job.source_id)


def recover_abandoned_work(session: Session) -> None:
    """Only at single-worker startup, after the previous worker has stopped."""
    session.execute(
        update(IngestionJob)
        .where(IngestionJob.status == JobStatus.RUNNING)
        .values(
            status=JobStatus.FAILED,
            finished_at=datetime.now(UTC),
            error_message="Worker stopped before the job finished",
        )
    )
    session.execute(
        update(Article)
        .where(Article.processing_status == ProcessingStatus.PROCESSING)
        .values(processing_status=ProcessingStatus.PENDING, processing_error=None)
    )


def record_article_result(
    session: Session, job_id: int, status: ProcessingStatus, *, count: int = 1
) -> None:
    field = {
        ProcessingStatus.READY: "articles_summarized",
        ProcessingStatus.FAILED: "articles_failed",
        ProcessingStatus.NEEDS_REVIEW: "articles_needs_review",
    }[status]
    changed = session.scalar(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.status == JobStatus.RUNNING)
        .values(
            {
                field: getattr(IngestionJob, field) + count,
                "articles_processed": IngestionJob.articles_processed + count,
            }
        )
        .returning(IngestionJob.id)
    )
    if changed is None:
        raise ValueError("Article results require a running job")


def finish_job(session: Session, job_id: int, *, failed: bool, message: str | None) -> None:
    """Messages must be fixed application text, never raw exception strings."""
    session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.status == JobStatus.RUNNING)
        .values(
            status=JobStatus.FAILED if failed else JobStatus.COMPLETED,
            finished_at=datetime.now(UTC),
            error_message=message,
        )
    )
