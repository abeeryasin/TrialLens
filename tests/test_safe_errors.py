"""api/safe_errors.py must not let a credential reach a database column.

This is the 2026-09-05 leak's second door. That incident went
config -> exception text -> public page, and was closed in
frontend/api_client.py for the frontend's own HTTP errors. Step 11 opens a
different route to the same place: a scheduled job catches an exception,
writes it to monitor_runs.error / synthesis_runs.error, GET /ops/status
reads the row back, and the Ops page prints it. The jobs that write it are
exactly the processes holding DATABASE_URL and ANTHROPIC_API_KEY.

Free: no network, no database, no model.

Run: PYTHONPATH=. python3 -m pytest tests/test_safe_errors.py -v
"""
import psycopg2
import pytest

from api import safe_errors

# The real shape, fake secret — same layout as the string that actually
# leaked (tests/test_api_client_redaction.py uses the same one).
DSN = (
    "postgresql://neondb_owner:SUPERSECRETPASSWORD@ep-x.us-east-2.aws.neon.tech"
    "/neondb?channel_binding=require&sslmode=require"
)
PASSWORD = "SUPERSECRETPASSWORD"
KEY = "sk-ant-api03-NOTAREALKEY_0123456789abcdef"


def test_the_connection_string_this_process_holds_never_survives(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DSN)
    cleaned = safe_errors.scrub(f"could not connect to {DSN}")
    assert PASSWORD not in cleaned
    assert DSN not in cleaned
    assert "DATABASE_URL redacted" in cleaned


def test_the_readonly_url_counts_too(monkeypatch):
    """Two URLs, two passwords. A guard that only knows about the write
    credential leaks the read one, and both open the same database."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL_READONLY", DSN)
    assert PASSWORD not in safe_errors.scrub(f"boom: {DSN}")


def test_an_api_key_is_redacted_by_shape_not_only_by_value(monkeypatch):
    """The key in the message is NOT the key in the environment — this is
    the case where a library quotes a credential we never handed it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cleaned = safe_errors.scrub(f"401 from provider, sent x-api-key: {KEY}")
    assert KEY not in cleaned
    assert "[redacted]" in cleaned


def test_a_password_in_a_url_we_have_never_seen_is_still_a_password(monkeypatch):
    """Belt and braces. Exact-value replacement cannot catch a credential
    this process does not hold — a second database, a proxy, a webhook URL —
    so the userinfo pattern has to catch it by shape."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
    cleaned = safe_errors.scrub("failed against postgresql://other:hunter2@db:5432/x")
    assert "hunter2" not in cleaned
    assert "postgresql://[redacted]@db:5432/x" in cleaned


def test_http_urls_with_credentials_are_covered(monkeypatch):
    """Credentials in an http:// URL are still credentials — the same point
    the api_client fix had to make: this cannot stop at postgres://."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert "hunter2" not in safe_errors.scrub("GET https://svc:hunter2@example.com/x")


def test_an_empty_env_var_does_not_shred_the_message(monkeypatch):
    """`"".replace` splices the placeholder between every character. An
    unset-but-present variable is normal in local dev."""
    monkeypatch.setenv("DATABASE_URL", "")
    assert safe_errors.scrub("plain message") == "plain message"


def test_a_huge_traceback_is_truncated():
    cleaned = safe_errors.scrub("x" * (safe_errors.MAX_LENGTH * 3))
    assert len(cleaned) < safe_errors.MAX_LENGTH + 50
    assert cleaned.endswith("[truncated]")


def test_describe_keeps_the_exception_type():
    """OperationalError and ValueError need different responses, and the
    message alone often does not say which happened."""
    assert safe_errors.describe(ValueError("bad")) == "ValueError: bad"


def test_describe_scrubs_a_real_psycopg2_failure(monkeypatch):
    """The realistic case, end to end: psycopg2 raising on a bad DSN, with
    the DSN in its own message. Not a mock — a genuine
    psycopg2.OperationalError, raised by psycopg2, carrying the string."""
    monkeypatch.setenv("DATABASE_URL", DSN)
    try:
        raise psycopg2.OperationalError(f"could not translate host name in {DSN}")
    except psycopg2.OperationalError as exc:
        described = safe_errors.describe(exc)
    assert PASSWORD not in described
    assert described.startswith("OperationalError:")


@pytest.mark.parametrize("message", ["", None, 0])
def test_falsy_messages_do_not_raise(message):
    """An exception with an empty message still has to produce a string —
    the write path calls this unconditionally."""
    assert isinstance(safe_errors.scrub(message), str)
