"""Thin HTTP wrapper around the FastAPI layer.

The frontend is not allowed to touch Postgres directly — "FastAPI is the
only door to the database" (CLAUDE.md sec. 5) applies to Streamlit the
same way it already applies to ingest.py. Every page goes through the
functions here instead of calling `requests` on its own, so that rule
stays true even as more pages get added.

**Errors here never echo API_BASE_URL's raw value** (added 2026-09-05 after
a real incident). On the first Render deploy, API_BASE_URL was set to the
Postgres connection string by mistake; `requests` refused the scheme, and
the old error text — which interpolated both API_BASE_URL and the raw
exception — printed the live database password onto a public page. The
misconfiguration was the user's, but the leak was this module's: an error
message is user-visible output, and user-visible output must not carry a
credential (CLAUDE.md sec. 2). Messages now name the host only, and a
non-HTTP address is refused up front with a message that says so plainly
instead of failing confusingly several layers down.
"""
import os
from urllib.parse import urlsplit

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")


def _safe_base_url() -> str:
    """API_BASE_URL reduced to scheme://host[:port] — no userinfo, no path,
    no query. Safe to show a user; a connection string's password lives in
    the userinfo and query parts this drops."""
    parsed = urlsplit(API_BASE_URL)
    if parsed.scheme and parsed.hostname:
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return "the configured API address"


def _redact(text: str) -> str:
    """requests puts the full request URL inside its own exception text, so
    sanitising our message is not enough on its own."""
    cleaned = str(text)
    if API_BASE_URL:
        cleaned = cleaned.replace(API_BASE_URL, _safe_base_url())
    return cleaned


def _require_http_address() -> None:
    """Fail early, and say which variable is wrong. Anything that isn't
    http(s) can only produce a confusing failure deeper in requests — and if
    it happens to be a connection string, one that carries a password."""
    if urlsplit(API_BASE_URL).scheme not in ("http", "https"):
        raise ApiError(
            "API_BASE_URL is not an HTTP address, so the API cannot be "
            "reached. It must be the API service's URL, e.g. "
            "https://triallens-api.onrender.com — check the environment "
            "variable on this service."
        )


class ApiError(Exception):
    """Raised when FastAPI is unreachable or returns an error response.
    Pages catch this and show it explicitly rather than a blank page —
    "couldn't reach the API" is a different, honest state from "no
    results", and the two must never look the same to the user.

    Carries status_code (None for a network-level failure, e.g. the API
    process isn't running at all) so a page can tell "not found" apart
    from "something's actually broken" instead of showing the same
    generic error for both."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


def get(path: str, params: dict = None) -> dict:
    _require_http_address()
    try:
        response = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=15)
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the API at {_safe_base_url()}: {_redact(exc)}")

    if not response.ok:
        raise ApiError(
            f"API returned {response.status_code} for {path}: {_redact(response.text)}",
            status_code=response.status_code,
        )

    return response.json()


def post(path: str, data: dict = None, json_data: dict = None, params: dict = None) -> dict:
    _require_http_address()
    try:
        response = requests.post(
            f"{API_BASE_URL}{path}",
            params=params,
            data=data,
            json=json_data,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the API at {_safe_base_url()}: {_redact(exc)}")

    if not response.ok:
        raise ApiError(
            f"API returned {response.status_code} for {path}: {_redact(response.text)}",
            status_code=response.status_code,
        )

    return response.json()
