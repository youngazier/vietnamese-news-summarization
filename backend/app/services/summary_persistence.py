"""Atomic, replay-safe finalization; the caller owns commit or rollback."""

from app.agents.schemas import ReviewedNews
from app.agents.state import NewsState
from app.models import Article, ProcessingStatus, Summary
from app.services.job_service import record_article_result
from sqlalchemy import select
from sqlalchemy.orm import Session


def persist_summary(
    session: Session,
    result: NewsState | ReviewedNews,
    *,
    summarize_model_name: str,
    agent_model_name: str,
    job_id: int | None = None,
) -> bool:
    candidate = ReviewedNews.model_validate(result)
    for model_name in (summarize_model_name, agent_model_name):
        if not model_name.strip() or len(model_name) > 160:
            raise ValueError("Model identifiers must contain 1–160 characters")
    article = session.scalar(
        select(Article).where(Article.id == candidate.article_id).with_for_update()
    )
    if article is None:
        raise ValueError("Article no longer exists")
    if article.processing_status != ProcessingStatus.PROCESSING:
        return False
    if (
        article.title != candidate.title
        or article.content != candidate.source_text
        or article.content_origin != candidate.content_origin
    ):
        raise ValueError("Article source changed during AI processing")
    session.add(
        Summary(
            article_id=article.id,
            summary_text=candidate.summary,
            category=candidate.category,
            keywords=candidate.keywords,
            summarize_model_name=summarize_model_name,
            agent_model_name=agent_model_name,
            approved=candidate.approved,
            review_feedback=candidate.feedback,
            draft_attempts=candidate.attempts,
            input_truncated=candidate.input_truncated,
        )
    )
    article.processing_status = (
        ProcessingStatus.READY if candidate.approved else ProcessingStatus.NEEDS_REVIEW
    )
    article.processing_error = None
    if job_id is not None:
        record_article_result(session, job_id, article.processing_status)
    session.flush()
    return True
