"""The two questions asked before the weekly agent spends anything.

The budget check asks "may we spend?". The history check added 2026-09-07
asks "is there anything to buy?" — and it exists because of a real receipt,
not a hypothetical: the first live synthesis run (2026-09-05) cost $0.1099
and filed zero proposals, because monitoring began 2026-08-28 and so
weeks_ago=2,3,4 all returned nothing. The agent behaved correctly; its own
system prompt forbids calling one week's number a pattern. The money was
still gone.

Whether the record holds two prior windows is a database question, so it is
answered by plain code before the model is reached (CLAUDE.md sec. 5).

Free: no database, no network, no model.
"""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.run_synthesis import MIN_PRIOR_WINDOWS, prior_windows_available

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
WINDOW_SINCE = NOW - timedelta(days=7)


class _Response:
    def __init__(self, recording_since, status=200):
        self._since = recording_since
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"window": {"recording_since": self._since}}


@pytest.fixture
def stub(monkeypatch):
    def _stub(response):
        def fake_get(url, params=None, timeout=None):
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr("scripts.run_synthesis.requests.get", fake_get)

    return _stub


def test_a_record_reaching_back_two_windows_is_enough(stub):
    stub(_Response((WINDOW_SINCE - timedelta(days=15)).isoformat()))
    assert prior_windows_available("http://x", 7, WINDOW_SINCE) >= MIN_PRIOR_WINDOWS


def test_the_first_live_run_would_have_been_skipped(stub):
    """The exact receipt. Monitoring began 2026-08-28; the run's window
    started 2026-09-05, which is 8 days later — one complete prior week, and
    the agent needs two."""
    stub(_Response("2026-08-28T12:55:52+00:00"))
    since = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc) - timedelta(days=7)
    assert prior_windows_available("http://x", 7, since) < MIN_PRIOR_WINDOWS


def test_an_empty_record_has_no_prior_windows(stub):
    stub(_Response(None))
    assert prior_windows_available("http://x", 7, WINDOW_SINCE) == 0


def test_a_partial_window_does_not_count_as_a_whole_one(stub):
    """13 days back is one complete 7-day window and a fragment. Rounding
    the fragment up would buy the run the check exists to refuse."""
    stub(_Response((WINDOW_SINCE - timedelta(days=13)).isoformat()))
    assert prior_windows_available("http://x", 7, WINDOW_SINCE) == 1


def test_a_failed_lookup_returns_none_and_never_skips(stub):
    """The dangerous failure mode is the opposite of the one being fixed. A
    transient API blip must not silently skip a week — a skipped week that
    nobody notices is exactly what step 11 was built to surface. None means
    'could not tell', and main() runs the agent on it."""
    stub(RuntimeError("connection refused"))
    assert prior_windows_available("http://x", 7, WINDOW_SINCE) is None


def test_an_http_error_is_treated_the_same_way(stub):
    stub(_Response("2026-01-01T00:00:00+00:00", status=503))
    assert prior_windows_available("http://x", 7, WINDOW_SINCE) is None


def test_a_z_suffixed_timestamp_is_parsed(stub):
    """Python 3.9's fromisoformat rejects a trailing Z, and the API emits
    one. Getting this wrong would raise inside the try and read as 'could
    not tell' — the check would silently never fire."""
    stub(_Response("2026-07-01T00:00:00Z"))
    assert prior_windows_available("http://x", 7, WINDOW_SINCE) >= MIN_PRIOR_WINDOWS


def test_the_threshold_matches_what_the_agent_is_told(self=None):
    """MIN_PRIOR_WINDOWS is read off the agent's own system prompt rather
    than picked. If the prompt stops asking for prior weeks, this check is
    enforcing a rule nobody stated."""
    from api.synthesis_agent import SYSTEM_PROMPT

    assert "2-3 prior weeks" in SYSTEM_PROMPT
    assert MIN_PRIOR_WINDOWS == 2
