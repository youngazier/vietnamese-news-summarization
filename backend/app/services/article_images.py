"""Extract image URLs from publisher metadata without downloading image files."""

import ipaddress
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def image_url(value: object, base_url: str) -> str | None:
    """Resolve a public HTTPS image URL; reject local and executable URL schemes."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if len(value) > 4096 or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    if "\\" in value:
        return None
    try:
        resolved = urljoin(base_url, value)
        parts = urlsplit(resolved)
        host = parts.hostname
        if (
            parts.scheme != "https"
            or not host
            or parts.port not in (None, 443)
            or parts.username is not None
            or parts.password is not None
            or host.rstrip(".").lower() == "localhost"
            or "." not in host
            or host.lower().endswith((".local", ".localhost", ".internal"))
        ):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                return None
        return resolved
    except ValueError:
        return None


def image_from_html(
    markup: str | bytes, base_url: str, *, content_selector: str | None = None
) -> str | None:
    soup = BeautifulSoup(markup, "html.parser")
    candidates = [
        tag.get("content")
        for selector in (
            'meta[property="og:image"]',
            'meta[property="og:image:secure_url"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image"]',
        )
        for tag in soup.select(selector)
    ]
    if content_selector is not None:
        container = soup.select_one(content_selector)
        if container is not None:
            for tag in container.select("img"):
                candidates.extend([tag.get("data-src"), tag.get("src")])
    return next((url for candidate in candidates if (url := image_url(candidate, base_url))), None)


def image_from_feed(entry: dict, base_url: str) -> str | None:
    candidates = []
    for key in ("media_thumbnail", "media_content"):
        for media in entry.get(key, []):
            if (
                key == "media_thumbnail"
                or media.get("medium") == "image"
                or str(media.get("type", "")).startswith("image/")
            ):
                candidates.append(media.get("url"))
    for enclosure in entry.get("enclosures", []):
        if str(enclosure.get("type", "")).startswith("image/"):
            candidates.append(enclosure.get("href"))
    for candidate in candidates:
        if url := image_url(candidate, base_url):
            return url
    # Parse before the collector strips HTML for rss_description.
    markup = entry.get("summary", "")
    if isinstance(markup, str):
        return image_from_html(f"<body>{markup}</body>", base_url, content_selector="body")
    return None
