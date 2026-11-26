from unittest.mock import Mock

import pytest
from app.models import Article, ContentOrigin, ProcessingStatus
from app.services import summary_persistence


@pytest.mark.parametrize(
    ("outcome", "status"),
    [("approved", ProcessingStatus.READY), ("needs_review", ProcessingStatus.NEEDS_REVIEW)],
)
def test_publication_and_job_counter_follow_graph_outcome(monkeypatch, outcome, status):
    approved = outcome == "approved"
    article = Article(
        id=7,
        title="Fixture",
        content="Fictional source text",
        content_origin=ContentOrigin.EXTRACTED,
        processing_status=ProcessingStatus.PROCESSING,
    )
    session = Mock()
    session.scalar.return_value = article
    record_result = Mock()
    monkeypatch.setattr(summary_persistence, "record_article_result", record_result)
    result = {
        "article_id": article.id,
        "title": article.title,
        "source_text": article.content,
        "content_origin": article.content_origin,
        "inference_text": article.content,
        "summary": "Draft",
        "category": "other",
        "keywords": ["một", "hai", "ba"],
        "approved": approved,
        "feedback": "" if approved else "Review rejected the draft",
        "attempts": 1 if approved else 2,
        "input_truncated": False,
        "outcome": outcome,
    }

    assert summary_persistence.persist_summary(
        session,
        result,
        summarize_model_name="fixture/vit5",
        agent_model_name="fixture/gemini",
        job_id=10,
    )
    assert article.processing_status == status
    summary = session.add.call_args.args[0]
    assert summary.approved is approved
    assert summary.review_feedback == result["feedback"]
    record_result.assert_called_once_with(session, 10, status)
    session.flush.assert_called_once()
