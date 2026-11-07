"""Image metadata parsing never downloads images or visits publisher pages."""

import pytest
from app.services.article_images import image_from_feed, image_from_html, image_url
from app.services.rss_collector import parse_feed


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:image/png;base64,test",
        "http://cdn.example.com/a.jpg",
        "https://user:secret@cdn.example.com/a.jpg",
        "https://127.0.0.1/a.jpg",
        "https://localhost/a.jpg",
        "https://10.0.0.1/a.jpg",
        "https://cdn.example.com:444/a.jpg",
        "https://[",
        "https://cdn.example.com/a\n.jpg",
        "https://cdn.example.com/" + "a" * 4096,
    ],
)
def test_unsafe_image_urls_rejected(url):
    assert image_url(url, "https://example.com/article") is None


def test_relative_image_and_cdn_host():
    assert (
        image_url("//cdn.example.com/a.jpg?q=80", "https://example.com/news/a")
        == "https://cdn.example.com/a.jpg?q=80"
    )
    assert image_url("../a.jpg", "https://example.com/news/article") == "https://example.com/a.jpg"


def test_rss_html_image_is_preserved_before_description_cleaning():
    payload = b"""<rss version="2.0"><channel><title>Fixture</title><link>https://example.com</link><description>Test</description><item><title>News</title><link>https://example.com/news</link><description><![CDATA[<img src="https://cdn.example.com/news.jpg"><p>Plain description</p>]]></description></item></channel></rss>"""
    entry = parse_feed(payload, 1, ["example.com"])[0]
    assert entry.rss_description == "Plain description"
    assert entry.image_url == "https://cdn.example.com/news.jpg"


@pytest.mark.parametrize(
    "field",
    [
        {"media_thumbnail": [{"url": "https://cdn.example.com/a.jpg"}]},
        {"media_content": [{"url": "https://cdn.example.com/a.jpg", "medium": "image"}]},
        {"enclosures": [{"href": "https://cdn.example.com/a.jpg", "type": "image/jpeg"}]},
        {"summary": '<img data-src="https://cdn.example.com/a.jpg">'},
    ],
)
def test_rss_image_formats(field):
    assert image_from_feed(field, "https://example.com/article") == "https://cdn.example.com/a.jpg"


def test_invalid_metadata_does_not_hide_valid_fallback():
    markup = '<meta property="og:image" content="javascript:bad"><meta name="twitter:image" content="/fallback.jpg">'
    assert (
        image_from_html(markup, "https://example.com/article") == "https://example.com/fallback.jpg"
    )


def test_open_graph_preferred_to_body_images():
    markup = (
        '<meta property="og:image" content="/lead.jpg"><article><img src="/body.jpg"></article>'
    )
    assert (
        image_from_html(markup, "https://example.com/article", content_selector="article")
        == "https://example.com/lead.jpg"
    )


def test_body_image_fallback_stays_inside_article():
    markup = '<img src="/advert.jpg"><article><img src="/article.jpg"></article>'
    assert (
        image_from_html(markup, "https://example.com/a", content_selector="article")
        == "https://example.com/article.jpg"
    )
    assert image_from_html(markup, "https://example.com/a") is None


def test_video_enclosure_is_not_an_article_image():
    assert (
        image_from_feed(
            {"enclosures": [{"href": "https://example.com/movie.mp4", "type": "video/mp4"}]},
            "https://example.com/article",
        )
        is None
    )
