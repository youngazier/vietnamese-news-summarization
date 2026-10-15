"""One genuine Developer API metadata request using an authored fictional source."""

import json

import pytest
from app.agents.schemas import NewsDraft
from app.core.config import Settings
from app.models.enums import Category, ContentOrigin
from app.services.gemini_service import GeminiService
from app.services.summary_service import SMOKE_TEXT, SMOKE_TITLE

pytestmark = pytest.mark.live


def test_real_developer_api_metadata(request, record_property):
    if request.config.getoption("markexpr").strip() != "live":
        pytest.skip("Explicitly select -m live to call the real Gemini Developer API")
    # Explicit live selection fails if credentials/model access are unavailable.
    service = GeminiService(Settings())
    try:
        result = service.metadata(
            title=SMOKE_TITLE,
            source_text=SMOKE_TEXT,
            content_origin=ContentOrigin.EXTRACTED,
        )
    finally:
        service.close()
    assert result.category == Category.SOCIETY
    assert 3 <= len(result.keywords) <= 5
    evidence = {"model_id": service.model_id, **result.model_dump(mode="json")}
    record_property("gemini_metadata", json.dumps(evidence, ensure_ascii=False))
    print(json.dumps(evidence, ensure_ascii=False))


def test_real_source_review_approves_supported_and_rejects_invented_facts(request, record_property):
    if request.config.getoption("markexpr").strip() != "live":
        pytest.skip("Explicitly select -m live to call the real Gemini Developer API")
    service = GeminiService(Settings())
    try:
        results = []
        for summary in [
            "Trong tình huống giả định, thư viện Bình Minh mở lớp kỹ năng số miễn phí cho 30 học viên.",
            "Ngày 15/10/2026, Thủ tướng Nguyễn Văn An khai trương lớp học cho 3000 người tại Huế.",
        ]:
            result = service.review(
                title=SMOKE_TITLE,
                source_text=SMOKE_TEXT,
                content_origin=ContentOrigin.EXTRACTED,
                inference_text=SMOKE_TEXT,
                input_truncated=False,
                draft=NewsDraft(
                    summary=summary,
                    category="society",
                    keywords=["thư viện", "kỹ năng số", "học miễn phí"],
                ),
            )
            results.append(result)
    finally:
        service.close()
    assert results[0].approved is True
    assert results[1].approved is False and results[1].feedback
    evidence = {"model_id": service.model_id, "reviews": [r.model_dump() for r in results]}
    record_property("gemini_reviews", json.dumps(evidence, ensure_ascii=False))
    print(json.dumps(evidence, ensure_ascii=False))
