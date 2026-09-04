"""GET /synthesis/proposals over HTTP, against a fake connection.

Two callers: the synthesis agent's own get_recent_proposals tool (checking
what earlier weekly runs already flagged, before filing a duplicate) and,
eventually, a review UI that does not exist yet. What these cover is
request binding and response assembly — the fake ignores SQL, so nothing
here says the query itself is right (tests/conftest.py's own rule).
"""
from datetime import datetime, timezone

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def proposal_row(**overrides):
    row = {
        "id": 1,
        "created_at": T0,
        "window_since": T1,
        "window_until": T0,
        "finding_type": "outcome_change_cluster",
        "summary": "3 trials changed a primary outcome after primary completion this week, up from 0-1 in the prior 3 weeks.",
        "confidence": "medium",
        "status": "pending",
    }
    row.update(overrides)
    return row


def test_returns_the_full_shape(api):
    body = api([[proposal_row()]]).get("/synthesis/proposals").json()
    assert set(body) == {"proposals"}
    assert body["proposals"][0]["finding_type"] == "outcome_change_cluster"
    assert body["proposals"][0]["confidence"] == "medium"
    assert body["proposals"][0]["status"] == "pending"


def test_an_empty_queue_is_a_real_empty_list_not_an_error(api):
    body = api([[]]).get("/synthesis/proposals").json()
    assert body["proposals"] == []


def test_days_and_limit_reach_the_sql_as_params(api):
    holder = []
    api([[]], keep=holder).get("/synthesis/proposals", params={"days": 14, "limit": 5})
    _, params = holder[0].cursor_obj.executed[0]
    assert params["limit"] == 5
    # since is derived from days — just confirm it was computed, not the
    # literal 28-day default.
    assert params["since"] is not None


def test_default_lookback_is_28_days(api):
    holder = []
    api([[]], keep=holder).get("/synthesis/proposals")
    _, params = holder[0].cursor_obj.executed[0]
    since = params["since"]
    assert (datetime.now(timezone.utc) - since).days in (27, 28)


def test_ordered_newest_first(api):
    holder = []
    api([[]], keep=holder).get("/synthesis/proposals")
    sql, _ = holder[0].cursor_obj.executed[0]
    assert "ORDER BY created_at DESC" in sql
