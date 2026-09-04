"""frontend/api_client.py must never put a credential in a user-visible error.

Why this exists, precisely. On the first Render deploy (2026-09-05), the
frontend service's API_BASE_URL was set to the Postgres connection string
instead of the API's URL. `requests` refused the scheme, and the old error
text interpolated both API_BASE_URL and the raw exception — so the live
database password rendered onto a public page.

The misconfiguration was human; the leak was this module's. An error message
is user-visible output, and user-visible output must not carry a credential
(CLAUDE.md sec. 2). These tests hold that line.

Free: no network, no database.
"""
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

# The exact shape that leaked — a real connection-string layout, fake secret.
LEAKY = (
    "postgresql://neondb_owner:SUPERSECRETPASSWORD@ep-x.us-east-2.aws.neon.tech"
    "/neondb?channel_binding=require&sslmode=require"
)
SECRET = "SUPERSECRETPASSWORD"


@pytest.fixture
def client(monkeypatch):
    """api_client with a chosen API_BASE_URL. Reloaded per test because the
    value is read at import time."""
    import importlib

    import api_client

    def _configure(base_url):
        monkeypatch.setenv("API_BASE_URL", base_url)
        return importlib.reload(api_client)

    yield _configure
    monkeypatch.delenv("API_BASE_URL", raising=False)
    importlib.reload(api_client)


class TestANonHttpAddressIsRefusedBeforeAnyRequest:
    def test_get_raises_without_leaking_the_value(self, client):
        api_client = client(LEAKY)
        with pytest.raises(api_client.ApiError) as caught:
            api_client.get("/watch")
        assert SECRET not in str(caught.value)
        assert "neondb_owner" not in str(caught.value)
        assert "API_BASE_URL" in str(caught.value), (
            "the message must name the variable to fix, or the operator is "
            "left guessing at exactly the moment they misconfigured it"
        )

    def test_post_raises_without_leaking_the_value(self, client):
        api_client = client(LEAKY)
        with pytest.raises(api_client.ApiError) as caught:
            api_client.post("/tracked-conditions", json_data={"condition": "x"})
        assert SECRET not in str(caught.value)

    def test_no_request_is_attempted_at_all(self, client, monkeypatch):
        """Refused up front, not after requests has already built a URL with
        the credential in it."""
        api_client = client(LEAKY)
        called = []
        monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: called.append(a))
        with pytest.raises(api_client.ApiError):
            api_client.get("/watch")
        assert called == []


class TestNetworkFailuresAgainstARealHttpAddress:
    def test_unreachable_host_names_the_host_but_not_userinfo(self, client, monkeypatch):
        """Credentials can sit in an http:// URL too — user:pass@host is
        still valid HTTP, so stripping is not only about postgres://."""
        api_client = client("https://user:hunter2@api.example.com")

        def boom(*a, **k):
            raise api_client.requests.RequestException(
                "failed connecting to https://user:hunter2@api.example.com/watch"
            )

        monkeypatch.setattr(api_client.requests, "get", boom)
        with pytest.raises(api_client.ApiError) as caught:
            api_client.get("/watch")
        message = str(caught.value)
        assert "hunter2" not in message
        assert "api.example.com" in message, "the host is what makes the error useful"
        assert "Could not reach the API" in message


class TestTheNormalPathIsUnchanged:
    def test_a_plain_http_base_url_is_accepted(self, client, monkeypatch):
        api_client = client("http://127.0.0.1:8000")

        class Response:
            ok = True

            @staticmethod
            def json():
                return {"status": "ok"}

        monkeypatch.setattr(api_client.requests, "get", lambda *a, **k: Response())
        assert api_client.get("/health") == {"status": "ok"}
