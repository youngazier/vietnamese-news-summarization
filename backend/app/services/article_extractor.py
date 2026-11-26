"""Prepare bounded source text using reviewed public HTML or permitted RSS excerpts."""

import logging
import posixpath
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from app.core.logging import LogEvent
from app.core.source_config import SourceConfig
from app.models import ContentOrigin
from app.services.article_images import image_from_document, image_from_html
from app.services.article_quality import MAX_TEXT_CHARACTERS, is_media_url, quality_reasons
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
from bs4 import BeautifulSoup, NavigableString, Tag

MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
NOISE_SELECTOR = (
    "script, style, noscript, nav, header, footer, aside, form, iframe, svg, "
    "[hidden], [aria-hidden='true'], .advertisement, .ads, .related, .related-news, "
    "figure, figcaption, .box-tinlienquan, .box-related, .box-tinkhac, "
    ".related-articles, .detail__related, .box-category, .box-comment, .comment, "
    ".comments, .social-share, .social, .share, .detail__share, .detail__comment, .author"
)
PUBLISHER_META = {
    "article:section",
    "its_subsection",
    "news_keywords",
    "article:tag",
    "its_tag",
    "its_type",
    "its_wordcount",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    text: str | None
    content_origin: ContentOrigin | None
    usable: bool
    failure_reason: str | None = None
    image_url: str | None = None
    publisher_meta: dict[str, list[str]] | None = None


class ExtractionError(Exception):
    """Only fixed failure codes may be passed to this exception."""


def clean_text(markup: str | bytes, *, selector: str | None = None) -> str:
    """Use the reviewed container; never fall back to the entire page."""
    soup = BeautifulSoup(markup, "html.parser")
    container = soup.select_one(selector) if selector else soup
    return _body_text(container) if container is not None else ""


class _ParagraphBreak(NavigableString):
    pass


def _body_text(container: Tag) -> str:
    if container.css.match(NOISE_SELECTOR) or any(
        parent.css.match(NOISE_SELECTOR) for parent in container.parents
    ):
        return ""
    for element in container.select(NOISE_SELECTOR):
        element.decompose()
    for paragraph in container.find_all("p"):
        paragraph.insert_before(_ParagraphBreak(""))
        paragraph.insert_after(_ParagraphBreak(""))

    chunks: list[str] = []
    paragraphs: list[str] = []
    for node in container.descendants:
        if isinstance(node, _ParagraphBreak) or (isinstance(node, Tag) and node.name == "br"):
            paragraphs.append("".join(chunks))
            chunks.clear()
        elif type(node) in container.MAIN_CONTENT_STRING_TYPES:
            chunks.append(str(node))
    paragraphs.append("".join(chunks))
    text = "\n\n".join(
        cleaned
        for paragraph in paragraphs
        if (cleaned := " ".join(paragraph.replace("\x00", "").split()))
    )
    return text[:MAX_TEXT_CHARACTERS].rstrip()


def _publisher_meta(soup: BeautifulSoup) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for tag in soup.find_all("meta"):
        value = tag.get("content")
        if not isinstance(value, str) or not value.strip():
            continue
        keys = {
            key.strip().lower()
            for key in (tag.get("name"), tag.get("property"))
            if isinstance(key, str)
        }
        for key in keys & PUBLISHER_META:
            fields.setdefault(key, []).append(value.replace("\x00", ""))
    return fields


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
    ) -> tuple[bytes, str]:
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
                        return bytes(body), str(response.url)
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
                body, _ = self._fetch(
                    source.robots_url, max_bytes=MAX_ROBOTS_BYTES, validate=validate
                )
            except ExtractionError:
                raise ExtractionError("robots_unavailable") from None
            parser = RobotFileParser()
            parser.parse(body.decode("utf-8", errors="replace").splitlines())
            self._robots[source.robots_url] = parser
        return self._robots[source.robots_url]

    def fetch_image_metadata(self, url: str, source: SourceConfig) -> str | None:
        """Opt-in metadata backfill, independent of full-text extraction and AI processing.

        Read only metadata from a stored article URL. Keep the same request limits,
        reviewed host boundary and robots checks as source-text extraction.
        """
        if not source.is_usable:
            return None
        try:
            robots = self._robots_for(source)

            def validate(destination: str) -> None:
                try:
                    validate_source_url(destination, source.allowed_hosts)
                except FeedFetchError:
                    raise ExtractionError("url_blocked") from None
                if urlsplit(destination).hostname != urlsplit(source.robots_url).hostname:
                    raise ExtractionError("url_blocked")
                if not robots.can_fetch(USER_AGENT, destination):
                    raise ExtractionError("robots_blocked")

            payload, final_url = self._fetch(
                url, max_bytes=MAX_HTML_BYTES, validate=validate, html=True
            )
            return image_from_html(payload, final_url)
        except ExtractionError:
            return None

    def extract(
        self,
        url: str,
        rss_description: str | None,
        source: SourceConfig,
        *,
        title: str = "",
        source_id: int | None = None,
        article_id: int | None = None,
        job_id: int | None = None,
    ) -> ExtractionResult:
        failure = None
        text = ""
        origin = None
        image = None
        metadata = None
        final_url = url
        if not source.is_usable:
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

                payload, final_url = self._fetch(
                    url, max_bytes=MAX_HTML_BYTES, validate=validate, html=True
                )
                soup = BeautifulSoup(payload, "html.parser")
                container = soup.select_one(source.article_extraction.content_selector)
                metadata = _publisher_meta(soup) or None
                image = image_from_document(soup, final_url, container)
                text = _body_text(container) if container is not None else ""
                if not text:
                    raise ExtractionError("missing_article_body")
                origin = ContentOrigin.EXTRACTED
            except ExtractionError as exc:
                failure = str(exc)
                excerpt = clean_text(rss_description or "") if rss_description else ""
                if excerpt:
                    text, origin = excerpt, ContentOrigin.RSS_EXCERPT
            reasons = quality_reasons(
                text=text,
                origin=origin,
                url=final_url,
                title=title,
                description=rss_description,
                publisher_meta=metadata,
            )
            if (
                origin == ContentOrigin.EXTRACTED
                and is_media_url(url)
                and "media_url" not in reasons
            ):
                reasons = ("media_url", *reasons)
            codes = (*reasons, failure) if failure else reasons
            result = ExtractionResult(
                text or None, origin, not codes, "; ".join(codes) or None, image, metadata
            )
        logger.info(
            LogEvent.ARTICLE_TEXT_EVALUATED,
            extra={
                "source_id": source_id,
                "article_id": article_id,
                "job_id": job_id,
                "failure_class": result.failure_reason,
                "usable": result.usable,
            },
        )
        return result
