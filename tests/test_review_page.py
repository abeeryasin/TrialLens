"""frontend/pages/7_Review.py — the human half of the synthesis agent.

AppTest runs the real script and returns its element tree. The API is
stubbed; the endpoints have their own tests.

The states worth guarding are the ones a convenient fixture never shows:

  - **An empty queue**, which is the COMMON case and must read as a finding
    with the agent's own run record behind it, not as a blank page. Same
    rule as the watch's quiet week.
  - **Empty because it never ran**, which is a different fact from "ran and
    found nothing" and must not render the same.
  - **A dismissed proposal**, which stays fully readable including its
    evidence — the record is what the agent said and what the human
    decided, not only the agreements.
  - **Evidence present**, one click away, on every proposal.

Free: no database, no network, no model.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_review_page.py -v
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

PAGE = str(FRONTEND / "pages" / "7_Review.py")


def proposal(**overrides):
    body = {
        "id": 1,
        "created_at": "2026-09-07T13:04:00Z",
        "window_since": "2026-08-31T13:00:00Z",
        "window_until": "2026-09-07T13:00:00Z",
        "finding_type": "outcome_change_cluster",
        "summary": "8 trials changed a primary outcome after their own primary "
                   "completion date this week, against 1-2 in each of the prior "
                   "three weeks.",
        "confidence": "medium",
        "status": "pending",
        "reviewed_at": None,
        "reviewed_note": None,
        "evidence": {"evidence": "get_window weeks_ago=0 returned 8; weeks_ago=1,2,3 returned 2, 1, 1."},
    }
    body.update(overrides)
    return body


def synthesis_job(**overrides):
    body = {
        "name": "synthesis", "last_completed_at": "2026-09-07T13:04:00Z",
        "hours_since_completion": 3.0, "last_work_done": 0,
        "work_label": "proposals filed", "runs_in_window": 2,
        "cadence_hours": 168, "stale_after_hours": 336, "window_hours": 672,
        "expected_runs_in_window": 2, "failed_in_window": 0,
        "degraded_in_window": 0, "stuck_runs": 0, "last_status": "completed",
    }
    body.update(overrides)
    return body


def run(proposals=(), job=None, list_error=None):
    at = AppTest.from_file(PAGE, default_timeout=30)
    import api_client

    def fake_get(path, params=None):
        if path == "/synthesis/proposals":
            if list_error is not None:
                raise list_error
            return {"proposals": list(proposals)}
        if path == "/ops/status":
            return {"jobs": [job if job is not None else synthesis_job()]}
        raise AssertionError(f"unexpected path {path}")

    original = api_client.get
    api_client.get = fake_get
    try:
        at.run()
    finally:
        api_client.get = original
    return at


def text_of(at):
    parts = []
    for kind in ("markdown", "caption", "success", "warning", "error", "info",
                 "subheader"):
        try:
            parts.extend(str(el.value) for el in getattr(at, kind))
        except AttributeError:
            continue
    return "\n".join(parts)


def test_a_pending_proposal_is_shown_with_its_summary(monkeypatch):
    at = run([proposal()])
    body = text_of(at)
    assert not at.exception
    assert "8 trials changed a primary outcome" in body
    assert "Waiting for you (1)" in body


def test_the_evidence_is_always_one_click_away(monkeypatch):
    at = run([proposal()])
    assert any(
        "weeks_ago=1,2,3" in str(el.value) for el in at.markdown
    ), "the agent's evidence is not rendered anywhere"


def test_accept_and_dismiss_are_both_offered(monkeypatch):
    at = run([proposal()])
    labels = {b.label for b in at.button}
    assert {"Accept", "Dismiss"} <= labels


def test_an_empty_queue_reads_as_a_finding_not_a_blank_page(monkeypatch):
    at = run([])
    body = text_of(at)
    assert "Nothing is waiting for review" in body
    # The run record is what makes it a finding rather than an absence.
    assert "filed 0 proposal(s)" in body
    assert "valid outcome" in body


def test_never_run_is_a_different_message_from_ran_and_found_nothing(monkeypatch):
    at = run([], job=synthesis_job(last_completed_at=None,
                                   hours_since_completion=None))
    body = text_of(at)
    assert "No completed synthesis run is on record" in body
    assert "filed 0 proposal(s)" not in body


def test_a_dismissed_proposal_stays_readable(monkeypatch):
    at = run([proposal(status="dismissed", reviewed_at="2026-09-07T15:00:00Z",
                       reviewed_note="Reformatting, not a real change.")])
    body = text_of(at)
    assert "Already decided (1)" in body
    assert "8 trials changed a primary outcome" in body
    assert "Reformatting, not a real change." in body
    # And it is not sitting in the queue any more.
    assert "Waiting for you (0)" in body


def test_proposals_are_never_sorted_by_confidence(monkeypatch):
    """A confidence label is the agent's statement about its own evidence,
    not a priority. Ordering by it would quietly make it a score."""
    at = run([proposal(id=1, confidence="low", summary="FIRST, newest"),
              proposal(id=2, confidence="high", summary="SECOND, older")])
    rendered = "\n".join(str(el.value) for el in at.markdown)
    assert rendered.index("FIRST, newest") < rendered.index("SECOND, older")


def test_an_unreachable_api_says_so_rather_than_showing_an_empty_queue(monkeypatch):
    import api_client

    at = run(list_error=api_client.ApiError("Could not reach the API at http://x"))
    body = text_of(at)
    assert "review queue can't be read" in body
    assert "Nothing is waiting for review" not in body
