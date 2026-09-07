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

**Reads are cached per endpoint** (added 2026-09-07), by an allowlist, with
every write clearing the cache immediately. The reasoning, the measurements
it rests on, and what is deliberately left uncached are all beside the
allowlist itself further down.
"""
import os
import re
from urllib.parse import urlsplit

import requests

try:
    import streamlit as st
except ImportError:
    # This module's own tests (tests/test_api_client_redaction.py) import it
    # with no streamlit installed at all, and the redaction rules they hold
    # are the last thing that should depend on a UI library being present.
    # Without streamlit there is simply no cache — every read goes to the API,
    # which is exactly the behaviour that existed before caching.
    st = None

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


def _fetch(path: str, params: dict = None) -> dict:
    """One real HTTP GET. Every read ends up here, cached or not."""
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


# ---------------------------------------------------------------------------
# Caching — per endpoint, by allowlist, with the write paths exempt
#
# Streamlit re-runs the whole page script on every widget interaction, and
# nothing here used to remember anything, so one filter change on Investigate
# re-issued that page's entire read set. Measured against the live API on
# 2026-09-07:
#
#     /investigate            37,711 B        /watch                2,500 B
#     /changes?limit=25        8,577 B        /changes/fields       1,058 B
#     /investigate/landscape   3,604 B        /tracked-conditions      27 B
#
# One Investigate rerun is 43,842 of those bytes and a working session is
# dozens of reruns. It is not only the frontend's bill: each GET is an API
# request, and each API request is a query against Neon, whose free tier
# allows 5 GB of transfer a month.
#
# An allowlist, deliberately, rather than a blanket cache on get():
#
#   - Nothing whose whole purpose is "as of now" is cached. /ops/status is the
#     health surface, and a five-minute-old all-clear during an incident is
#     the exact failure this project builds against; /discover runs a live
#     CT.gov fallback, so a cached search could hide a trial registered
#     minutes ago (that page keeps its result in session_state anyway, so it
#     has no rerun amplification to fix); /synthesis/proposals is a work queue
#     a human is actively changing, and it measures 16 bytes.
#   - Anything not classified is not cached. An endpoint added later is slow
#     by default, never silently stale — tests/test_api_client_cache.py fails
#     if a page reads a path that appears in neither list.
#
# The TTL is five minutes against a record that moves every six hours, so the
# data cannot be stale in a way a reader could notice; what it covers is one
# person's session of filter changes. Writes do not wait for it (see post()).
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS = float(os.environ.get("FRONTEND_CACHE_TTL_SECONDS", 300))

# A bound, because Streamlit's default is unbounded and Render's free tier
# gives this service 512 MB. Worst case here is ~64 x 40 KB of /investigate
# responses, ~2.5 MB.
CACHE_MAX_ENTRIES = 64

CACHEABLE_PATHS = (
    r"/watch",
    r"/tracked-conditions",
    r"/changes",
    r"/changes/fields",
    r"/investigate",
    r"/investigate/landscape",
    r"/investigate/trials",
    r"/discover/NCT\d+",
    r"/studies/NCT\d+/amendments",
    r"/studies/NCT\d+/changes",
    r"/explore/NCT\d+",
)

# Read paths a page uses that are deliberately NOT cached. Kept as a list, not
# as an absence, so the cache canary can tell "considered and refused" apart
# from "nobody thought about it".
UNCACHED_ON_PURPOSE = (
    r"/ops/status",
    r"/discover",
    r"/synthesis/proposals",
)


def _is_cacheable(path: str) -> bool:
    return any(re.fullmatch(pattern, path) for pattern in CACHEABLE_PATHS)


def _params_key(params: dict):
    """A hashable, order-independent cache key for a params dict.

    None values are dropped because `requests` drops them too — {"a": None}
    and {} issue the identical request and must not become two entries.
    Returns None, meaning "don't cache this call", for a value requests would
    expand into repeated params (a list); no call site passes one today, and
    guessing at its key is worse than fetching it.
    """
    if not params:
        return ()
    items = []
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        if not isinstance(value, (str, int, float, bool)):
            return None
        items.append((key, value))
    return tuple(items)


def _fetch_cached(path: str, params_key) -> dict:
    return _fetch(path, dict(params_key) or None)


if st is not None:
    # show_spinner=False for two reasons: a spinner on a 27-byte call is
    # noise, and st.cache_data's spinner is the one part of it that needs a
    # script context, which pytest does not have.
    _fetch_cached = st.cache_data(
        ttl=CACHE_TTL_SECONDS,
        max_entries=CACHE_MAX_ENTRIES,
        show_spinner=False,
    )(_fetch_cached)


def clear_cache() -> None:
    """Drop every cached read. Called after any successful write."""
    if st is not None:
        _fetch_cached.clear()


def get(path: str, params: dict = None) -> dict:
    _require_http_address()
    if st is not None and _is_cacheable(path):
        key = _params_key(params)
        if key is not None:
            return _fetch_cached(path, key)
    return _fetch(path, params)


def delete(path: str, params: dict = None) -> dict:
    """The third verb the API door opens, added with DELETE
    /tracked-conditions. It clears the cache for the same reason post() does:
    a page still listing a condition someone just removed is the failure the
    invalidation exists to prevent."""
    _require_http_address()
    try:
        response = requests.delete(f"{API_BASE_URL}{path}", params=params, timeout=30)
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the API at {_safe_base_url()}: {_redact(exc)}")

    if not response.ok:
        raise ApiError(
            f"API returned {response.status_code} for {path}: {_redact(response.text)}",
            status_code=response.status_code,
        )

    clear_cache()

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

    # Any write invalidates every cached read, bluntly and on purpose. The
    # alternative — a map from each write path to the reads it affects — is
    # one more table to forget an entry in, and a forgotten entry shows the
    # user a page that ignored what they just did. A monitoring tool that
    # appears not to register a condition someone just added is worse than
    # one that costs bandwidth. Writes are rare (adding a condition, reviewing
    # a proposal); one full refetch on the next rerun is the cheap half of
    # that trade.
    clear_cache()

    return response.json()
