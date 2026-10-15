"""Fetch reviewed RSS feeds and parse article metadata."""

import calendar
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from app.seed_sources import SourceConfig
from app.services.url_normalization import normalize_url
from bs4 import BeautifulSoup

USER_AGENT = "VietnameseNewsSummarization/0.1 (local educational RSS reader)"
HTTP_TIMEOUT_SECONDS = 15.0
MAX_HTTP_ATTEMPTS = 3
MAX_FEED_BYTES = 2 * 1024 * 1024
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 60.0

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class FeedError(Exception):
    """Base error with a short message suitable for application logs."""


class FeedFetchError(FeedError):
    """The feed could not be downloaded within its limits."""


class FeedParseError(FeedError):
    """The downloaded bytes are not a usable feed."""


@dataclass(frozen=True)
class FeedEntry:
    source_id: int
    title: str
    original_url: str
    published_at: datetime | None
    rss_description: str | None


def clean_html(value: str) -> str:
    """Convert publisher HTML into plain text without fetching resources."""
    soup = BeautifulSoup(value, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def validate_source_url(url: str, allowed_hosts: list[str]) -> None:
    """Require HTTPS, the default port, and an exact reviewed hostname."""
    try:
        # Reuse basic URL validation, but keep the original URL unchanged.
        normalize_url(url)
        parts = urlsplit(url.strip())
        allowed = (
            parts.scheme.lower() == "https"
            and parts.hostname in allowed_hosts
            and parts.port in (None, 443)
        )
    except ValueError:
        raise FeedFetchError("Invalid publisher URL") from None

    if not allowed:
        raise FeedFetchError("URL is outside the reviewed publisher scope")


def retry_delay(value: str | None, attempt: int) -> float:
    """Use bounded backoff and honor valid Retry-After values."""
    backoff = float(2 ** (attempt - 1))
    if value is None:
        return backoff

    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            delay = (retry_at - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return backoff

    # Do not retry earlier when a server requests a longer wait.
    if delay > MAX_RETRY_DELAY_SECONDS:
        raise FeedFetchError("Publisher requested a longer retry delay")

    # This also rejects NaN and negative values.
    if not 0 <= delay <= MAX_RETRY_DELAY_SECONDS:
        return backoff

    return max(backoff, delay)


def read_feed_body(response: httpx.Response) -> bytes:
    """Bound decoded bytes even when Content-Length is absent or misleading."""
    body = bytearray()

    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        if len(body) + len(chunk) > MAX_FEED_BYTES:
            raise FeedFetchError("Feed exceeds the 2 MiB size limit")
        body.extend(chunk)

    return bytes(body)


class RSSCollector:
    """Sequential collector with a shared three-request budget per feed."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.sleep = sleep

    def fetch(self, source: SourceConfig) -> bytes:
        """Fetch an active feed; validate redirects before following them."""
        if not source.is_active or source.review_status != "rss_reader_supported":
            raise FeedFetchError("Source is inactive or RSS use is unresolved")

        current_url = source.rss_url

        # Redirects and retries both consume this budget.
        for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
            validate_source_url(current_url, source.allowed_hosts)
            self.sleep(REQUEST_DELAY_SECONDS)

            try:
                with self.client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=HTTP_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as response:
                    status = response.status_code

                    if status in REDIRECT_STATUSES:
                        location = response.headers.get("Location")
                        if not location:
                            raise FeedFetchError("Feed redirect has no destination")

                        destination = urljoin(str(response.url), location)
                        validate_source_url(destination, source.allowed_hosts)
                        current_url = destination
                        continue

                    if status in RETRYABLE_STATUSES:
                        if attempt == MAX_HTTP_ATTEMPTS:
                            raise FeedFetchError("Feed HTTP attempt limit reached")

                        delay = retry_delay(
                            response.headers.get("Retry-After"),
                            attempt,
                        )
                    elif status != 200:
                        raise FeedFetchError(f"Feed returned HTTP {status}")
                    else:
                        return read_feed_body(response)

            except httpx.TransportError:
                if attempt == MAX_HTTP_ATTEMPTS:
                    raise FeedFetchError("Feed transport attempt limit reached") from None
                delay = retry_delay(None, attempt)

            # The response context closes before we wait for a retry.
            self.sleep(delay)

        raise FeedFetchError("Feed redirect attempt limit reached")

    def collect(self, source_id: int, source: SourceConfig) -> list[FeedEntry]:
        payload = self.fetch(source)
        return parse_feed(payload, source_id, source.allowed_hosts)


def parse_publication_date(entry: feedparser.FeedParserDict) -> datetime | None:
    """Convert feedparser's parsed publication date into an aware UTC datetime."""
    parsed = entry.get("published_parsed")
    if parsed is None:
        return None

    try:
        timestamp = calendar.timegm(parsed)
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def parse_feed(
    payload: bytes,
    source_id: int,
    allowed_hosts: list[str],
) -> list[FeedEntry]:
    """Parse a valid feed; skip entries without usable titles or links."""
    if source_id <= 0:
        raise ValueError("Source ID must be positive")
    if len(payload) > MAX_FEED_BYTES:
        raise FeedParseError("Feed exceeds the 2 MiB size limit")

    parsed = feedparser.parse(payload)

    # Feedparser can recover entries from broken XML. Our initial policy
    # rejects such feeds so malformed responses are explicit failures.
    if parsed.bozo:
        raise FeedParseError("Feed is malformed")
    if not parsed.get("version") or not parsed.get("feed"):
        raise FeedParseError("Response is not a recognized feed")

    entries = []

    for item in parsed.entries:
        raw_title = item.get("title", "")
        raw_link = item.get("link", "")

        if not isinstance(raw_title, str) or not isinstance(raw_link, str):
            continue

        title = clean_html(raw_title)
        original_url = raw_link.strip()
        if not title or not original_url:
            continue

        try:
            validate_source_url(original_url, allowed_hosts)
        except FeedFetchError:
            continue

        raw_description = item.get("summary", "")
        description = clean_html(raw_description) if isinstance(raw_description, str) else ""

        entries.append(
            FeedEntry(
                source_id=source_id,
                title=title,
                original_url=original_url,
                published_at=parse_publication_date(item),
                rss_description=description or None,
            )
        )

    # A valid feed with no entries is a successful empty result.
    return entries
