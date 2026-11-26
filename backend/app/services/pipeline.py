"""Lazy AI pipeline wiring shared by the worker and manual CLI."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import Settings
from app.core.logging import LogEvent
from app.services.article_processing import NewsProcessor

logger = logging.getLogger(__name__)


@contextmanager
def open_pipeline(settings: Settings) -> Iterator[tuple[NewsProcessor, str, str]]:
    """Load the local summarizer, provider, and LangGraph pipeline; close provider on exit."""
    # Lazy imports keep API startup free of inference libraries and model weights.
    from app.agents.graph import build_news_graph
    from app.services.gemini_service import GeminiService
    from app.services.summary_service import get_summary_service

    logger.info(LogEvent.MODEL_LOADING)
    summarizer = get_summary_service()
    logger.info(LogEvent.MODEL_LOADED)
    provider = GeminiService(settings)
    try:
        graph = build_news_graph(
            summarizer, provider, max_attempts=settings.MAX_GRAPH_DRAFT_ATTEMPTS
        )
        yield graph, summarizer.model_id, provider.model_id
    finally:
        provider.close()
