import unicodedata

import pytest
from app.agents.schemas import ArticleMetadata, NewsDraft, ReviewResult
from app.models.enums import Category
from pydantic import ValidationError


def test_metadata_normalizes_vietnamese_keywords():
    metadata = ArticleMetadata(
        category="society",
        keywords=[" thư viện ", unicodedata.normalize("NFD", "kỹ năng"), "học"],
    )
    assert metadata.category == Category.SOCIETY
    assert metadata.keywords == ["thư viện", "kỹ năng", "học"]


@pytest.mark.parametrize(
    "update",
    [
        {"category": "invented"},
        {"keywords": ["hai", "từ"]},
        {"keywords": [str(number) for number in range(6)]},
        {"keywords": ["", "thư viện", "học"]},
        {"keywords": ["   ", "thư viện", "học"]},
        {"keywords": ["x" * 81, "thư viện", "học"]},
        {"keywords": ["Thư viện", "thư viện", "học"]},
        {"keywords": ["kỹ năng", unicodedata.normalize("NFD", "kỹ năng"), "học"]},
        {"keywords": [123, "thư viện", "học"]},
        {"summary": "Provider must not supply a summary"},
    ],
)
def test_invalid_metadata_is_rejected(update):
    payload = {"category": "society", "keywords": ["thư viện", "kỹ năng", "học"]}
    with pytest.raises(ValidationError):
        ArticleMetadata.model_validate(payload | update)


@pytest.mark.parametrize("summary", ["", "   ", "x" * 4001])
def test_draft_requires_nonempty_bounded_local_summary(summary):
    with pytest.raises(ValidationError):
        NewsDraft(summary=summary, category="society", keywords=["thư viện", "kỹ năng", "học"])


@pytest.mark.parametrize(
    "payload",
    [
        {"approved": "true", "feedback": ""},
        {"approved": "false", "feedback": "Lỗi"},
        {"approved": 1, "feedback": ""},
        {"approved": 0, "feedback": "Lỗi"},
        {"approved": None, "feedback": "Lỗi"},
        {"approved": False, "feedback": "   "},
        {"approved": False, "feedback": "x" * 1001},
        {"approved": True},
        {"approved": True, "feedback": "", "summary": "Injected"},
    ],
)
def test_invalid_review_results_fail(payload):
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(payload)


def test_review_feedback_is_bounded_and_trimmed():
    assert ReviewResult(approved=True, feedback="").approved is True
    assert ReviewResult(approved=False, feedback=" Lỗi số liệu ").feedback == "Lỗi số liệu"
    assert len(ReviewResult(approved=False, feedback="x" * 1000).feedback) == 1000
