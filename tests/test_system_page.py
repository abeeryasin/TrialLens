"""frontend/pages/6_System.py — what an operator actually sees.

AppTest runs the real script and returns its element tree, so these assert
the rendered page rather than the code's intent. The API is stubbed;
GET /ops/status has its own tests.

The states that matter here are the ones a convenient development database
never shows:

  - **Healthy.** Must not read as an empty page. This is the common case,
    the same problem the watch's quiet week had.
  - **Green but doing nothing.** A monitor run that completed successfully
    having checked zero trials is the failure this page exists for, and it
    is the one a grid of OK tiles would render as fine.
  - **The API is unreachable.** "Cannot check" must never look like
    "healthy" — a health page that fails open is worse than no page.
  - **A recorded error.** It has to be visible, and it must not carry a
    credential onto the screen (CLAUDE.md sec. 2).

Free: no database, no network, no model.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_system_page.py -v
"""
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit not installed"
).AppTest

PAGE = str(FRONTEND / "pages" / "6_System.py")


def job(name="monitor", **overrides):
    body = {
        "name": name,
        "cadence_hours": 6 if name == "monitor" else 168,
        "stale_after_hours": 12 if name == "monitor" else 336,
        "last_started_at": "2026-09-06T10:00:00Z",
        "last_completed_at": "2026-09-06T10:05:00Z",
        "hours_since_completion": 1.5,
        "last_status": "completed",
        "last_error": None,
        "last_work_done": 11416 if name == "monitor" else 0,
        "work_label": "trials checked" if name == "monitor" else "proposals filed",
        "consecutive_failures": 0,
        "window_hours": 168,
        "runs_in_window": 17,
        "expected_runs_in_window": 13,
        "failed_in_window": 0,
        "degraded_in_window": 0,
        "stuck_runs": 0,
    }
    body.update(overrides)
    return body


def status(alerts=(), jobs=None, **overrides):
    body = {
        "checked_at": "2026-09-06T12:00:00Z",
        "is_healthy": not any(a["severity"] == "critical" for a in alerts),
        "alerts": list(alerts),
        "jobs": jobs if jobs is not None else [job("monitor"), job("synthesis")],
        "budget": {
            "window_days": 30, "ceiling_usd": 1.0, "spent_usd": 0.1479,
            "remaining_usd": 0.8521, "share_used": 0.1479,
        },
        "tracked_conditions": 2,
    }
    body.update(overrides)
    return body


def run(monkeypatch_body=None, error=None):
    at = AppTest.from_file(PAGE, default_timeout=30)

    import api_client

    # The page does `from api_client import get`, but AppTest re-executes the
    # script on every run, so that name is re-bound from the patched module
    # attribute each time.
    def fake_get(path, params=None):
        if error is not None:
            raise error
        return monkeypatch_body

    original = api_client.get
    api_client.get = fake_get
    try:
        at.run()
    finally:
        api_client.get = original
    return at


def text_of(at):
    parts = []
    for kind in ("markdown", "caption", "success", "warning", "error", "subheader"):
        try:
            parts.extend(el.value for el in getattr(at, kind))
        except AttributeError:
            continue
    return "\n".join(str(p) for p in parts)


def test_a_healthy_system_says_so_in_words(monkeypatch):
    at = run(status())
    body = text_of(at)
    assert "running on time" in body
    assert not at.exception


def test_it_leads_with_what_the_last_run_did_not_that_it_finished(monkeypatch):
    """'Completed successfully' is also true of a run that checked nothing."""
    at = run(status())
    assert "11,416 trials checked" in text_of(at)


def test_a_green_run_that_checked_nothing_is_stated_loudly(monkeypatch):
    at = run(status(
        alerts=[{
            "code": "job_did_nothing", "severity": "critical",
            "title": "The last monitor run did no work",
            "detail": "It completed with 0 trials checked.",
            "job": "monitor",
        }],
        jobs=[job("monitor", last_work_done=0), job("synthesis")],
    ))
    body = text_of(at)
    assert "need attention" in body
    # The evidence, not just the headline (sec. 3).
    assert "It completed with 0 trials checked." in body


def test_an_unreachable_api_never_reads_as_healthy(monkeypatch):
    import api_client

    at = run(error=api_client.ApiError("Could not reach the API at http://x"))
    body = text_of(at)
    assert "cannot say whether the system is healthy" in body
    assert "running on time" not in body


def test_a_recorded_error_is_shown(monkeypatch):
    at = run(status(jobs=[
        job("monitor", last_error="OperationalError: server closed the connection"),
        job("synthesis"),
    ]))
    assert any(
        "server closed the connection" in str(el.value) for el in at.code
    )


def test_more_runs_than_slots_is_explained_rather_than_left_odd(monkeypatch):
    """17 of 13 looks like a bug until you know workflow_dispatch exists."""
    at = run(status())
    assert "cannot tell a scheduled run from one started by hand" in text_of(at)


def test_the_budget_is_shown_as_a_real_position(monkeypatch):
    at = run(status())
    body = text_of(at)
    assert "$0.1479" in body and "$1.00 ceiling" in body


def test_a_job_with_no_runs_at_all_does_not_crash(monkeypatch):
    at = run(status(jobs=[
        job("monitor", last_completed_at=None, hours_since_completion=None,
            last_work_done=None, last_status=None, runs_in_window=0,
            expected_runs_in_window=0),
    ]))
    assert not at.exception
    assert "No completed run on record" in text_of(at)
