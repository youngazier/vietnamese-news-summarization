"""Run the AI graph for one stored article."""

import logging
from collections.abc import Callable
from typing import Protocol

from app.agents.schemas import ReviewedNews
from app.agents.state import NewsState
from app.core.logging import LogEvent
from app.core.source_config import SourceConfig
from app.models import Article, ProcessingStatus
from app.services.article_extractor import MAX_TEXT_CHARACTERS, MIN_TEXT_CHARACTERS
from app.services.job_service import record_article_result
from app.services.source_guard import require_active_source
from app.services.summary_persistence import persist_summary
from sqlalchemy import select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


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

    Returns True for a new terminal transition, including an exhausted review.
    The validated graph outcome controls publication. Provider/model/schema failures
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
        if changed is not None:
            logger.warning(
                LogEvent.ARTICLE_PROCESSING_FAILED,
                extra={"job_id": job_id, "source_id": source_id, "article_id": article_id},
            )
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
