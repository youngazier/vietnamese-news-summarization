from urllib.parse import unquote_plus, urlsplit, urlunsplit

TRACKING_PARAMETERS = frozenset({
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
})

def normalize_url(url: str) -> str:
    """Normalize an absolute HTTP(S) URL without changing article identity."""
    url = url.strip()
    if not url or any(character.isspace() for character in url):
        raise ValueError("URL must be nonempty and contain no whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("URL must not contain control characters")
    if "\\" in url:
        raise ValueError("URL must not contain backslashes")

    # urlsplit and accessing .port can raise ValueError for malformed URLs.
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    hostname = parts.hostname
    port = parts.port

    if scheme not in {"http", "https"} or not hostname:
        raise ValueError("URL must be an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL must not contain credentials")

    hostname = hostname.lower()
    # Preserve brackets around IPv6 addresses when rebuilding the authority.
    authority = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"

    retained_parameters = []
    for parameter in parts.query.split("&"):
        name = unquote_plus(parameter.partition("=")[0]).lower()
        if name.startswith("utm_") or name in TRACKING_PARAMETERS:
            continue
        retained_parameters.append(parameter)

    return urlunsplit((
        scheme,
        authority,
        parts.path,
        "&".join(retained_parameters),
        "",
    ))