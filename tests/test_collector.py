"""RSS collection tests without external networking."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from app.seed_sources import SourceConfig, load_source_config
from app.services.rss_collector import (
    MAX_FEED_BYTES,
    USER_AGENT,
    FeedFetchError,
    FeedParseError,
    RSSCollector,
    parse_feed,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "rss" / "valid.xml"

EMPTY_FEED = b"""\
<rss version="2.0">
  <channel>
    <title>Empty fixture</title>
    <link>https://example.com/</link>
    <description>No articles</description>
  </channel>
</rss>
"""


@pytest.fixture
def source() -> SourceConfig:
    original = load_source_config(ROOT / "config" / "sources.json")[0]
    # JSON round-trip preserves strict date validation in SourceConfig.
    return SourceConfig.model_validate_json(
        original.model_copy(
            update={
                "name": "Fixture",
                "rss_url": "https://example.com/feed.xml",
                "allowed_hosts": ["example.com"],
                "official_rss_url": "https://example.com/rss",
                "robots_url": "https://example.com/robots.txt",
            }
        ).model_dump_json()
    )


def test_parse_valid_feed() -> None:
    entries = parse_feed(FIXTURE.read_bytes(), 7, ["example.com"])

    assert len(entries) == 2
    first, second = entries
    assert first.source_id == 7
    assert first.title == "Tin thử nghiệm"
    assert first.original_url == "https://example.com/news?id=42&utm_source=rss"
    assert first.published_at == datetime(2026, 10, 14, 3, tzinfo=UTC)
    assert first.rss_description == "Nội dung thử nghiệm ."
    assert second.published_at is None
    assert second.rss_description is None


def test_valid_empty_feed_succeeds() -> None:
    assert parse_feed(EMPTY_FEED, 7, ["example.com"]) == []


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html><body>Not a feed</body></html>",
        b"<rss><channel><item>",
    ],
)
def test_reject_invalid_feed(payload: bytes) -> None:
    with pytest.raises(FeedParseError):
        parse_feed(payload, 7, ["example.com"])


def test_fetch_success(source: SourceConfig) -> None:
    waits = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        assert request.extensions["timeout"]["read"] == 15.0
        return httpx.Response(200, content=FIXTURE.read_bytes())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=waits.append)
        assert len(collector.collect(7, source)) == 2

    assert waits == [1.0]


@pytest.mark.parametrize("failure", ["timeout", "rate_limit", "server_error"])
def test_retry_budget(source: SourceConfig, failure: str) -> None:
    requests = []
    waits = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("Fixture timeout", request=request)
        status = 429 if failure == "rate_limit" else 503
        return httpx.Response(status, headers={"Retry-After": "2"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=waits.append)
        with pytest.raises(FeedFetchError):
            collector.fetch(source)

    assert len(requests) == 3
    assert len(waits) == 5  # Three request delays and two retry delays.


def test_retry_then_success(source: SourceConfig) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=EMPTY_FEED)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=lambda _: None)
        assert collector.collect(7, source) == []

    assert len(requests) == 2


def test_access_denial_is_not_retried(source: SourceConfig) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=lambda _: None)
        with pytest.raises(FeedFetchError, match="HTTP 403"):
            collector.fetch(source)

    assert len(requests) == 1


@pytest.mark.parametrize(
    ("destination", "allowed"),
    [
        ("/new-feed.xml", True),
        ("https://unreviewed.example/feed.xml", False),
        ("http://example.com/feed.xml", False),
    ],
)
def test_redirect_scope(
    source: SourceConfig,
    destination: str,
    allowed: bool,
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": destination})
        return httpx.Response(200, content=EMPTY_FEED)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=lambda _: None)
        if allowed:
            assert collector.fetch(source) == EMPTY_FEED
        else:
            with pytest.raises(FeedFetchError):
                collector.fetch(source)

    assert len(requests) == (2 if allowed else 1)


def test_oversized_body_without_content_length(source: SourceConfig) -> None:
    class OversizedStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(33):
                yield b"x" * (64 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=OversizedStream())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=lambda _: None)
        with pytest.raises(FeedFetchError, match="size limit"):
            collector.fetch(source)


def test_parse_size_limit() -> None:
    with pytest.raises(FeedParseError, match="size limit"):
        parse_feed(b"x" * (MAX_FEED_BYTES + 1), 7, ["example.com"])


def test_inactive_source_is_not_requested(source: SourceConfig) -> None:
    inactive = source.model_copy(update={"is_active": False})

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Inactive sources must not make HTTP requests")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=lambda _: None)
        with pytest.raises(FeedFetchError, match="inactive"):
            collector.fetch(inactive)


def test_long_retry_after_stops_collection(source: SourceConfig) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client, sleep=lambda _: None)
        with pytest.raises(FeedFetchError, match="longer retry delay"):
            collector.fetch(source)

    assert len(requests) == 1
