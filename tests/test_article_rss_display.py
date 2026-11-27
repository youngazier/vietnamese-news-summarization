"""Article RSS serialization without a live database or provider."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.db.session import get_db
from app.main import app
from app.models import ProcessingStatus
from app.services.rss_collector import parse_feed
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, None),
        (" \n ", None),
        ("Ví dụ <code> giữ nguyên.", "Ví dụ <code> giữ nguyên."),
        ("Literal &copy; và &lt;b&gt;.", "Literal &copy; và &lt;b&gt;."),
        ("  Giữ khoảng trắng.  ", "  Giữ khoảng trắng.  "),
        ("Mô tả đầy đủ. " * 100, "Mô tả đầy đủ. " * 100),
    ],
)
@pytest.mark.parametrize(
    ("status", "approved", "visible"),
    [
        (ProcessingStatus.READY, True, True),
        (ProcessingStatus.READY, False, False),
        (ProcessingStatus.PENDING, True, False),
        (ProcessingStatus.FAILED, False, False),
        (ProcessingStatus.READY, None, False),
    ],
)
def test_rss_in_list_and_detail_preserves_summary_gate(stored, expected, status, approved, visible):
    _check_routes(stored, expected, status, approved, visible)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Ví dụ &lt;code&gt; giữ nguyên.", "Ví dụ <code> giữ nguyên."),
        ("Literal &amp;copy; giữ nguyên.", "Literal &copy; giữ nguyên."),
        ("<p>Tin <b>mới</b> &amp; dữ kiện.</p><script>bad()</script>", "Tin mới & dữ kiện."),
    ],
)
def test_feed_to_api_preserves_ingested_plain_text(description, expected):
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Fixture feed</title>
    <link>https://example.com</link><description>Fixture</description>
    <item><title>Fixture news</title><link>https://example.com/news</link>
    <description><![CDATA[{description}]]></description></item>
    </channel></rss>""".encode()
    (entry,) = parse_feed(payload, 1, ["example.com"])
    assert entry.rss_description == expected
    # The insertion path stores FeedEntry.rss_description without further conversion.
    _check_routes(entry.rss_description, expected, ProcessingStatus.READY, True, True)


def _check_routes(stored, expected, status, approved, visible):
    now = datetime(2026, 11, 27, tzinfo=UTC)
    source = SimpleNamespace(
        id=1, name="Fixture publisher", rss_url="https://example.com/rss", last_fetched_at=None
    )
    summary = SimpleNamespace(
        approved=approved,
        summary_text="Approved candidate. " * 50,
        category="other",
        keywords=["fixture"],
        summarize_model_name="vit5",
        agent_model_name="fixture",
        created_at=now,
        input_truncated=False,
    )
    article = SimpleNamespace(
        id=1,
        title="Fixture news",
        original_url="https://example.com/news",
        rss_description=stored,
        image_url=None,
        source=source,
        published_at=now,
        created_at=now,
        content_origin="extracted",
        processing_status=status,
        summary=summary if approved is not None else None,
    )

    class ReadOnlyFixtureSession:
        def scalar(self, statement):
            return 1 if "count(" in str(statement) else article

        def scalars(self, statement):
            return SimpleNamespace(all=lambda: [article])

    def fixture_db():
        yield ReadOnlyFixtureSession()

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = fixture_db
    try:
        with TestClient(app) as client:
            card = client.get("/api/v1/articles").json()["items"][0]
            response = client.get("/api/v1/articles/1")
            assert response.status_code == 200
            detail = response.json()
        assert card["rss_description"] == detail["rss_description"] == expected
        assert detail["ai_generated"] is visible
        if visible:
            assert detail["summary"]["summary_text"] == summary.summary_text
            assert card["summary_preview"] == summary.summary_text[:240]
        else:
            assert detail["summary"] is None
            assert card["summary_preview"] is None
            assert card["category"] is None
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
