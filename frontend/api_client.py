"""Thin HTTP wrapper around the FastAPI layer.

The frontend is not allowed to touch Postgres directly — "FastAPI is the
only door to the database" (CLAUDE.md sec. 5) applies to Streamlit the
same way it already applies to ingest.py. Every page goes through the
functions here instead of calling `requests` on its own, so that rule
stays true even as more pages get added.
"""
import os

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")


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
    try:
        response = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=15)
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the API at {API_BASE_URL}: {exc}")

    if not response.ok:
        raise ApiError(
            f"API returned {response.status_code} for {path}: {response.text}",
            status_code=response.status_code,
        )

    return response.json()


def post(path: str, data: dict = None, json_data: dict = None, params: dict = None) -> dict:
    try:
        response = requests.post(
            f"{API_BASE_URL}{path}",
            params=params,
            data=data,
            json=json_data,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the API at {API_BASE_URL}: {exc}")

    if not response.ok:
        raise ApiError(
            f"API returned {response.status_code} for {path}: {response.text}",
            status_code=response.status_code,
        )

    return response.json()
