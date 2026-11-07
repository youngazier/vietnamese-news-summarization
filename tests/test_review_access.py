"""Reviewer access stays local, regardless of untrusted forwarded headers."""

import pytest
from app.api.reviews import ReviewDecision, require_local_reviewer
from fastapi import HTTPException
from starlette.requests import Request


@pytest.mark.parametrize(
    "host,origin,allowed",
    [
        ("127.0.0.1", None, True),
        ("::1", "http://localhost:5173", True),
        ("127.0.0.1", "http://127.0.0.1:5173", True),
        ("192.0.2.1", None, False),
        ("127.0.0.1", "https://evil.example", False),
        ("127.0.0.1", "null", False),
        ("127.0.0.1", "http://localhost.evil.example", False),
    ],
)
def test_local_review_access(host, origin, allowed):
    headers = [(b"x-forwarded-for", b"127.0.0.1")]
    if origin:
        headers.append((b"origin", origin.encode()))
    request = Request({"type": "http", "client": (host, 1234), "headers": headers})
    if allowed:
        require_local_reviewer(request)
    else:
        with pytest.raises(HTTPException) as error:
            require_local_reviewer(request)
        assert error.value.status_code == 403


def test_note_validation():
    with pytest.raises(ValueError):
        ReviewDecision(decision="decline", expected_version="a" * 64, note=" ")
