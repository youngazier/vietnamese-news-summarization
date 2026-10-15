"""Local job submission and polling; no worker/model imports."""

from typing import Annotated

from app.core.config import get_settings
from app.db.session import get_db
from app.models import IngestionJob
from app.schemas import IngestionJobAccepted, IngestionJobCreate, IngestionJobRead
from app.services.job_service import JobSubmissionError, enqueue_job
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion-jobs"])


@router.post("", response_model=IngestionJobAccepted, status_code=202)
def create_job(
    body: IngestionJobCreate, db: Annotated[Session, Depends(get_db)]
) -> IngestionJobAccepted:
    try:
        with db.begin():
            job = enqueue_job(
                db, source_id=body.source_id, max_backlog=get_settings().MAX_JOB_BACKLOG
            )
            response = IngestionJobAccepted(job_id=job.id, status=job.status)
    except JobSubmissionError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}
        ) from None
    return response


@router.get("/{job_id}", response_model=IngestionJobRead)
def get_job(
    job_id: Annotated[int, Path(gt=0)], db: Annotated[Session, Depends(get_db)]
) -> IngestionJobRead:
    job = db.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": "Job not found."},
        )
    return IngestionJobRead.model_validate(job)
