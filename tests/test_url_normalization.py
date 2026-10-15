"""Article URL identity and validation checks."""

import pytest

from app.services.url_normalization import normalize_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://VNEXPRESS.NET:443/news.html?id=42&utm_source=rss#comments",
            "https://vnexpress.net/news.html?id=42",
        ),
        (
            "http://example.com:80/news?fbclid=abc&id=42",
            "http://example.com/news?id=42",
        ),
        (
            "https://example.com:8443/News/?id=42&id=43&tag=a%20b",
            "https://example.com:8443/News/?id=42&id=43&tag=a%20b",
        ),
    ],
)
def test_normalize_url(url: str, expected: str) -> None:
    assert normalize_url(url) == expected
    assert normalize_url(expected) == expected


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://example.com/news?id=42", "https://example.com/news?id=43"),
        ("https://example.com/News", "https://example.com/news"),
        ("https://example.com/news", "https://example.com/news/"),
        ("http://example.com/news", "https://example.com/news"),
    ],
)
def test_preserve_distinct_articles(first: str, second: str) -> None:
    assert normalize_url(first) != normalize_url(second)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "/relative/news",
        "ftp://example.com/news",
        "https://",
        "https://user:password@example.com/news",
        "https://example.com:invalid/news",
        "https://example.com/news item",
        "https://example.com/\nnews",
    ],
)
def test_reject_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(url)