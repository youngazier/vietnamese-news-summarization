import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.articles import router as articles_router
from app.api.ingestion_jobs import router as ingestion_jobs_router
from app.api.sources import router as sources_router
from app.core.config import LogSettings
from app.core.logging import LogEvent, configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(LogSettings().LOG_LEVEL)
    logging.getLogger(__name__).info(LogEvent.API_READY)
    yield


app = FastAPI(title="Vietnamese News Summarization API", version="0.1.0", lifespan=lifespan)
app.include_router(sources_router, prefix="/api/v1")
app.include_router(articles_router, prefix="/api/v1")
app.include_router(ingestion_jobs_router, prefix="/api/v1")


@app.exception_handler(OperationalError)
def database_unavailable(_request: Request, _error: OperationalError) -> JSONResponse:
    """Return a stable response without exposing database or credential details."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "database_unavailable",
                "message": "Database is temporarily unavailable.",
            }
        },
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint that works independently without database or external services."""
    return {"status": "ok"}
