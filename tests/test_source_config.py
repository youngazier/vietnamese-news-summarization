"""Validate source review gates without publisher or database access."""

import json
from pathlib import Path

import pytest
from app.seed_sources import SourceConfig, load_source_config
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sources.json"


def test_committed_source_configuration() -> None:
    sources = load_source_config(CONFIG)
    assert len(sources) == 3
    assert [source.name for source in sources if source.is_active] == ["VnExpress", "Tuổi Trẻ"]
    assert all(not source.article_extraction_allowed for source in sources)
    assert all(not source.ai_processing_allowed for source in sources)


@pytest.mark.parametrize(
    "change",
    [
        {"review_status": "reuse_unresolved"},
        {"rss_url": "https://unreviewed.example/feed.rss"},
        {"is_active": "false"},
        {"ai_processing_allowed": True},
        {"article_extraction_allowed": True},
        {"article_extraction_allowed": "true"},
        {
            "article_extraction": {
                "public_path_prefixes": ["news"],
                "content_selector": "article",
                "review_note": "Fixture",
            }
        },
        {
            "article_extraction": {
                "public_path_prefixes": ["/news/"],
                "content_selector": "article[",
                "review_note": "Fixture",
            }
        },
        {"availability": {"status": 200, "robots_allowed": False}},
    ],
)
def test_reject_unsafe_configuration(tmp_path: Path, change: dict) -> None:
    source = json.loads(CONFIG.read_text())[0]
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([{**source, **change}]))
    with pytest.raises(ValidationError):
        load_source_config(path)


def test_reject_duplicate_feeds(tmp_path: Path) -> None:
    source = json.loads(CONFIG.read_text())[0]
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([source, source]))
    with pytest.raises(ValueError, match="duplicate RSS"):
        load_source_config(path)


def test_ai_processing_requires_explicit_review_on_an_active_source():
    source = load_source_config(CONFIG)[0].model_dump()
    reviewed = source | {
        "ai_processing_allowed": True,
        "ai_processing_review_note": "Authored fixture approved for local/provider processing.",
    }
    assert SourceConfig.model_validate(reviewed).ai_processing_allowed is True
    for change in [{"is_active": False}, {"ai_processing_review_note": "   "}]:
        with pytest.raises(ValidationError):
            SourceConfig.model_validate(reviewed | change)
