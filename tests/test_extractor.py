"""Source text boundaries with fictional HTML and no external network or AI."""

import gzip
import logging
from pathlib import Path

import httpx
import pytest
from app.models import ContentOrigin
from app.seed_sources import ArticleExtractionPolicy, SourceConfig, load_source_config
from app.services.article_extractor import (
    MAX_HTML_BYTES,
    MAX_ROBOTS_BYTES,
    MAX_TEXT_CHARACTERS,
    ArticleExtractor,
    clean_text,
)

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "tests/fixtures/html/public_article.html").read_bytes()
EXCERPT = "Nội dung tiếng Việt giả lập dùng để kiểm tra bản trích RSS. " * 5
URL = "https://example.com/news/article"
ROBOTS = "User-agent: *\nDisallow: /news/private/\n"


@pytest.fixture
def source() -> SourceConfig:
    original = load_source_config(ROOT / "config/sources.json")[0]
    return SourceConfig.model_validate_json(
        original.model_copy(
            update={
                "name": "Fictional fixture",
                "rss_url": "https://example.com/feed.xml",
                "official_rss_url": "https://example.com/rss",
                "robots_url": "https://example.com/robots.txt",
                "allowed_hosts": ["example.com"],
                "article_extraction_allowed": True,
                "article_extraction": ArticleExtractionPolicy(
                    public_path_prefixes=["/news/"],
                    content_selector="article.news-body",
                    review_note="Fictional public fixture only; no publisher permissions implied.",
                ),
            }
        ).model_dump_json()
    )


def run_extraction(source, handler, *, url=URL, excerpt=EXCERPT):
    requests = []
    waits = []

    def transport(request):
        requests.append(request)
        assert request.headers["User-Agent"].startswith("VietnameseNewsSummarization/")
        assert request.extensions["timeout"]["read"] == 15.0
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return handler(request)

    with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as client:
        result = ArticleExtractor(client, sleep=waits.append).extract(
            url, excerpt, source, source_id=7, article_id=11, job_id=13
        )
    return result, requests, waits


def html_response(request):
    return httpx.Response(200, content=HTML, headers={"Content-Type": "text/html; charset=utf-8"})


def test_permitted_extraction_cleans_fixture(source):
    result, requests, _ = run_extraction(source, html_response)
    assert result.usable and result.content_origin == ContentOrigin.EXTRACTED
    assert result.failure_reason is None
    assert result.text.startswith("Thư viện cộng đồng")
    assert "dữ liệu hư cấu" in result.text
    assert "KHÔNG LẤY" not in result.text
    assert "SECRET_SCRIPT" not in result.text
    assert "<" not in result.text
    assert [request.url.path for request in requests] == ["/robots.txt", "/news/article"]


def test_extraction_disabled_makes_no_requests(source):
    source = source.model_copy(update={"article_extraction_allowed": False})
    result, requests, waits = run_extraction(source, html_response)
    assert result.usable and result.content_origin == ContentOrigin.RSS_EXCERPT
    assert result.failure_reason == "extraction_disabled"
    assert requests == waits == []


@pytest.mark.parametrize("change", [{"is_active": False}, {"review_status": "reuse_unresolved"}])
def test_no_fallback_reuse_for_unreviewed_source(source, change):
    result, requests, _ = run_extraction(source.model_copy(update=change), html_response)
    assert result.text is result.content_origin is None
    assert not result.usable and result.failure_reason == "source_not_permitted"
    assert requests == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/news/article",
        "http://example.com/news/article",
        "https://user:secret@example.com/news/article",
        "https://example.com:444/news/article",
        "https://example.com/private/article",
        "https://example.com/newspaper/article",
        "https://example.com/news/%2e%2e/private",
        "https://example.com/news/%252e%252e/private",
        "https://example.com/news/%5cprivate",
        "https://example.com/news/%00private",
    ],
)
def test_unreviewed_url_is_never_requested(source, url):
    result, requests, _ = run_extraction(source, html_response, url=url)
    assert result.content_origin == ContentOrigin.RSS_EXCERPT
    assert result.failure_reason == "url_blocked"
    assert requests == []


@pytest.mark.parametrize(
    "destination, reason",
    [
        ("https://evil.example/leak?key=SECRET", "url_blocked"),
        ("http://example.com/news/article", "url_blocked"),
        ("/private/article", "url_blocked"),
        ("/news/private/article", "robots_blocked"),
    ],
)
def test_blocked_redirect_is_not_followed(source, destination, reason):
    result, requests, _ = run_extraction(
        source, lambda _: httpx.Response(302, headers={"Location": destination})
    )
    assert result.usable and result.failure_reason == reason
    assert len(requests) == 2


def test_allowed_redirect_and_robots_cache(source):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == "/news/article":
            return httpx.Response(302, headers={"Location": "/news/final"})
        return html_response(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        extractor = ArticleExtractor(client, sleep=lambda _: None)
        assert extractor.extract(URL, None, source).usable
        assert extractor.extract(URL, None, source).usable
    assert requests.count("/robots.txt") == 1
    assert requests.count("/news/final") == 2


@pytest.mark.parametrize(
    "failure, reason",
    [
        ("timeout", "timeout"),
        ("transport", "transport_error"),
        (429, "http_attempt_limit"),
        (503, "http_attempt_limit"),
        (403, "access_denied"),
        (404, "http_error"),
        (302, "redirect_attempt_limit"),
    ],
)
def test_http_failures_fall_back_with_bounded_requests(source, failure, reason):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("https://user:SECRET@host/payload", request=request)
        if failure == "transport":
            raise httpx.ConnectError("SECRET_DSN", request=request)
        return httpx.Response(failure, headers={"Location": "/news/loop", "Retry-After": "0"})

    result, requests, _ = run_extraction(source, handler)
    assert result.usable and result.text == EXCERPT.strip()
    assert result.failure_reason == reason
    assert len(requests) == (2 if failure in {403, 404} else 4)


@pytest.mark.parametrize(
    "payload, content_type, reason",
    [
        (
            (ROOT / "tests/fixtures/html/missing_body.html").read_bytes(),
            "text/html",
            "missing_article_body",
        ),
        (b"<article class='news-body'>Short</article>", "text/html", "short_article_body"),
        (b"SECRET_PAYLOAD", "application/json", "unexpected_content_type"),
    ],
)
def test_unusable_html_falls_back(source, payload, content_type, reason):
    result, _, _ = run_extraction(
        source,
        lambda _: httpx.Response(200, content=payload, headers={"Content-Type": content_type}),
    )
    assert result.usable and result.content_origin == ContentOrigin.RSS_EXCERPT
    assert result.failure_reason == reason


@pytest.mark.parametrize("length, usable", [(0, False), (199, False), (200, True), (201, True)])
def test_exact_adequacy_boundary(source, length, usable):
    source = source.model_copy(update={"article_extraction_allowed": False})
    result, requests, _ = run_extraction(source, html_response, excerpt="á" * length)
    assert result.usable is usable
    assert result.content_origin == (ContentOrigin.RSS_EXCERPT if length else None)
    assert result.text == ("á" * length or None)
    if not usable:
        assert result.failure_reason.endswith("insufficient_text" if length else "missing_text")
    assert requests == []


def test_empty_markup_has_null_origin(source):
    source = source.model_copy(update={"article_extraction_allowed": False})
    result, _, _ = run_extraction(source, html_response, excerpt="<script>SECRET</script>  \x00")
    assert result.text is result.content_origin is None


def test_short_extracted_text_keeps_provenance_without_excerpt(source):
    result, _, _ = run_extraction(
        source,
        lambda _: httpx.Response(
            200,
            text="<article class='news-body'>Đoạn ngắn.</article>",
            headers={"Content-Type": "text/html"},
        ),
        excerpt=None,
    )
    assert result.text == "Đoạn ngắn." and result.content_origin == ContentOrigin.EXTRACTED
    assert not result.usable
    assert result.failure_reason == "short_article_body; insufficient_text"


def test_malformed_redirect_uses_redacted_fallback(source):
    result, requests, _ = run_extraction(
        source, lambda _: httpx.Response(302, headers={"Location": "https://["})
    )
    assert result.usable and result.failure_reason == "invalid_redirect"
    assert len(requests) == 2


def test_retained_text_cap():
    assert clean_text("<p>" + "ộ" * 30_000 + "</p>") == "ộ" * MAX_TEXT_CHARACTERS


@pytest.mark.parametrize("compressed", [False, True])
def test_decoded_response_size_cap(source, compressed):
    payload = b"x" * (MAX_HTML_BYTES + 1)
    headers = {"Content-Type": "text/html"}
    if compressed:
        payload = gzip.compress(payload)
        headers["Content-Encoding"] = "gzip"
    result, requests, _ = run_extraction(
        source, lambda _: httpx.Response(200, content=payload, headers=headers)
    )
    assert result.usable and result.failure_reason == "response_too_large"
    assert len(requests) == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403),
        httpx.Response(200, content=b"x" * (MAX_ROBOTS_BYTES + 1)),
        httpx.Response(302, headers={"Location": "https://evil.example/robots.txt"}),
    ],
)
def test_robots_unavailable_never_fetches_article(source, response):
    requests = []

    def handler(request):
        requests.append(request)
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ArticleExtractor(client, sleep=lambda _: None).extract(URL, EXCERPT, source)
    assert result.failure_reason == "robots_unavailable"
    assert len(requests) == 1 and requests[0].url.path == "/robots.txt"


def test_logging_keeps_context_without_payloads(source, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.article_extractor"):
        result, _, _ = run_extraction(source, lambda _: httpx.Response(403, text="SECRET_PAYLOAD"))
    record = caplog.records[-1]
    assert (record.source_id, record.article_id, record.job_id) == (7, 11, 13)
    assert record.failure_class == result.failure_reason == "access_denied"
    assert "SECRET" not in caplog.text and EXCERPT not in caplog.text and URL not in caplog.text
