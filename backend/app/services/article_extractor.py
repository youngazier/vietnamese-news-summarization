"""Prepare bounded source text using reviewed public HTML or permitted RSS excerpts."""

import logging
import posixpath
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from app.models import ContentOrigin
from app.seed_sources import SourceConfig
from app.services.rss_collector import (
    HTTP_TIMEOUT_SECONDS,
    MAX_HTTP_ATTEMPTS,
    REDIRECT_STATUSES,
    REQUEST_DELAY_SECONDS,
    RETRYABLE_STATUSES,
    USER_AGENT,
    FeedFetchError,
    retry_delay,
    validate_source_url,
)
from bs4 import BeautifulSoup

MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
MAX_TEXT_CHARACTERS = 20_000
MIN_TEXT_CHARACTERS = 200
NOISE_SELECTOR = (
    "script, style, noscript, nav, header, footer, aside, form, iframe, svg, "
    "[hidden], [aria-hidden='true'], .advertisement, .ads, .related, .related-news, "
    ".comments, .social-share, .author"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    text: str | None
    content_origin: ContentOrigin | None
    usable: bool
    failure_reason: str | None = None


class ExtractionError(Exception):
    """Only fixed failure codes may be passed to this exception."""


def clean_text(markup: str | bytes, *, selector: str | None = None) -> str:
    """Use the reviewed container; never fall back to the entire page."""
    soup = BeautifulSoup(markup, "html.parser")
    for element in soup.select(NOISE_SELECTOR):
        element.decompose()
    container = soup.select_one(selector) if selector else soup
    if container is None:
        return ""
    return " ".join(container.get_text(separator=" ").replace("\x00", "").split())[
        :MAX_TEXT_CHARACTERS
    ]


def validate_article_url(url: str, source: SourceConfig) -> None:
    try:
        validate_source_url(url, source.allowed_hosts)
    except FeedFetchError:
        raise ExtractionError("url_blocked") from None
    policy = source.article_extraction
    # Decode before path checks to prevent encoded traversal escaping a reviewed scope.
    path = unquote(urlsplit(url).path)
    if (
        policy is None
        or "\\" in path
        or "%" in path
        or any(ord(char) < 32 for char in path)
        or posixpath.normpath(path) != (path.rstrip("/") or "/")
        or not any(
            path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
            for prefix in policy.public_path_prefixes
        )
    ):
        raise ExtractionError("url_blocked")
    # A robots review is tied to one origin, not every configured RSS/navigation host.
    if urlsplit(url).hostname != urlsplit(source.robots_url).hostname:
        raise ExtractionError("url_blocked")


class ArticleExtractor:
    def __init__(
        self,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.sleep = sleep
        self._robots: dict[str, RobotFileParser] = {}

    def _fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        validate: Callable[[str], None],
        html: bool = False,
    ) -> bytes:
        # Redirects and retries share one budget; httpx never follows on its own.
        for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
            validate(url)
            self.sleep(REQUEST_DELAY_SECONDS)
            try:
                with self.client.stream(
                    "GET",
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=HTTP_TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("Location")
                        if not location:
                            raise ExtractionError("invalid_redirect")
                        try:
                            url = urljoin(str(response.url), location)
                        except ValueError:
                            raise ExtractionError("invalid_redirect") from None
                        validate(url)
                        continue
                    if response.status_code in RETRYABLE_STATUSES:
                        if attempt == MAX_HTTP_ATTEMPTS:
                            raise ExtractionError("http_attempt_limit")
                        delay = retry_delay(response.headers.get("Retry-After"), attempt)
                    elif response.status_code in {401, 403, 451}:
                        raise ExtractionError("access_denied")
                    elif response.status_code != 200:
                        raise ExtractionError("http_error")
                    else:
                        content_type = response.headers.get("Content-Type", "").split(";")[0]
                        if html and content_type.lower() not in {
                            "text/html",
                            "application/xhtml+xml",
                        }:
                            raise ExtractionError("unexpected_content_type")
                        body = bytearray()
                        for chunk in response.iter_bytes(chunk_size=64 * 1024):
                            if len(body) + len(chunk) > max_bytes:
                                raise ExtractionError("response_too_large")
                            body.extend(chunk)
                        return bytes(body)
            except httpx.TimeoutException:
                if attempt == MAX_HTTP_ATTEMPTS:
                    raise ExtractionError("timeout") from None
                delay = retry_delay(None, attempt)
            except httpx.TransportError:
                if attempt == MAX_HTTP_ATTEMPTS:
                    raise ExtractionError("transport_error") from None
                delay = retry_delay(None, attempt)
            except (FeedFetchError, httpx.DecodingError):
                raise ExtractionError("response_unavailable") from None
            self.sleep(delay)
        raise ExtractionError("redirect_attempt_limit")

    def _robots_for(self, source: SourceConfig) -> RobotFileParser:
        if source.robots_url not in self._robots:

            def validate(url: str) -> None:
                try:
                    validate_source_url(url, [urlsplit(source.robots_url).hostname])
                except FeedFetchError:
                    raise ExtractionError("url_blocked") from None

            try:
                body = self._fetch(source.robots_url, max_bytes=MAX_ROBOTS_BYTES, validate=validate)
            except ExtractionError:
                raise ExtractionError("robots_unavailable") from None
            parser = RobotFileParser()
            parser.parse(body.decode("utf-8", errors="replace").splitlines())
            self._robots[source.robots_url] = parser
        return self._robots[source.robots_url]

    def extract(
        self,
        url: str,
        rss_description: str | None,
        source: SourceConfig,
        *,
        source_id: int | None = None,
        article_id: int | None = None,
        job_id: int | None = None,
    ) -> ExtractionResult:
        failure = None
        text = ""
        origin = None
        if not source.is_active or source.review_status != "rss_reader_supported":
            # No fallback reuse for an inactive/unreviewed source.
            result = ExtractionResult(None, None, False, "source_not_permitted")
        else:
            try:
                if not source.article_extraction_allowed:
                    raise ExtractionError("extraction_disabled")
                validate_article_url(url, source)
                robots = self._robots_for(source)

                def validate(destination: str) -> None:
                    validate_article_url(destination, source)
                    if not robots.can_fetch(USER_AGENT, destination):
                        raise ExtractionError("robots_blocked")

                payload = self._fetch(url, max_bytes=MAX_HTML_BYTES, validate=validate, html=True)
                text = clean_text(payload, selector=source.article_extraction.content_selector)
                if not text:
                    raise ExtractionError("missing_article_body")
                origin = ContentOrigin.EXTRACTED
                if len(text) < MIN_TEXT_CHARACTERS:
                    raise ExtractionError("short_article_body")
            except ExtractionError as exc:
                failure = str(exc)
                excerpt = clean_text(rss_description or "")
                if excerpt:
                    text, origin = excerpt, ContentOrigin.RSS_EXCERPT
            usable = len(text) >= MIN_TEXT_CHARACTERS
            if not usable:
                failure = f"{failure}; {'insufficient_text' if text else 'missing_text'}"
            result = ExtractionResult(text or None, origin, usable, failure)
        logger.info(
            "Article source text evaluated source_id=%s article_id=%s job_id=%s failure_class=%s",
            source_id,
            article_id,
            job_id,
            result.failure_reason,
            extra={
                "source_id": source_id,
                "article_id": article_id,
                "job_id": job_id,
                "failure_class": result.failure_reason,
                "usable": result.usable,
            },
        )
        return result
