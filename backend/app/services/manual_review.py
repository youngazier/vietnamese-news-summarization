"""Manual summary decisions; the caller owns the transaction and access checks."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from app.models import Article, ProcessingStatus, Summary
from sqlalchemy import select
from sqlalchemy.orm import Session


class ReviewConflict(Exception):
    """The caller must reload rather than overwriting a changed draft."""


def review_version(article: Article, summary: Summary | None) -> str:
    payload = {
        "article_id": article.id,
        "title": article.title,
        "content": article.content,
        "origin": article.content_origin,
        "status": article.processing_status,
        "article_updated": str(article.updated_at),
        "summary": None
        if summary is None
        else {
            "id": summary.id,
            "text": summary.summary_text,
            "category": summary.category,
            "keywords": summary.keywords,
            "approved": summary.approved,
            "updated": str(summary.updated_at),
            "decision": summary.human_review_decision,
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def can_review(article: Article, summary: Summary | None) -> bool:
    return (
        article.processing_status == ProcessingStatus.NEEDS_REVIEW
        and bool(article.content and article.content.strip())
        and summary is not None
        and bool(summary.summary_text.strip())
        and not summary.approved
        and summary.human_review_decision is None
    )


def decide_review(
    db: Session,
    article_id: int,
    *,
    decision: Literal["accept", "decline"],
    expected_version: str,
    note: str,
) -> Article:
    # Same article-first locking order as AI persistence; concurrent reviewers serialize.
    article = db.scalar(select(Article).where(Article.id == article_id).with_for_update())
    if article is None:
        raise LookupError("Article not found")
    summary = db.scalar(select(Summary).where(Summary.article_id == article_id).with_for_update())
    if not can_review(article, summary) or review_version(article, summary) != expected_version:
        raise ReviewConflict("Draft changed or cannot be reviewed")
    if decision == "decline" and not note.strip():
        raise ValueError("Declining requires a reason")
    assert summary is not None
    summary.approved = decision == "accept"
    summary.human_review_decision = decision
    summary.human_review_note = note.strip() or None
    summary.human_reviewed_at = datetime.now(UTC)
    article.processing_status = (
        ProcessingStatus.READY if decision == "accept" else ProcessingStatus.NEEDS_REVIEW
    )
    # Preserve the original processing error and AI feedback for diagnosis.
    db.flush()
    return article
