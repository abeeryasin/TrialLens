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


# ---------------------------------------------------------------------------
# The review half (2026-09-06): a person accepts or dismisses a proposal.
# ---------------------------------------------------------------------------

def reviewed_row(**overrides):
    row = proposal_row(
        status="accepted",
        reviewed_at=T0,
        reviewed_note="Matches what I saw in the outcome table.",
        evidence={"evidence": "get_window weeks_ago=0 returned 8 outcome changes"},
    )
    row.update(overrides)
    return row


def test_evidence_is_off_by_default(api):
    """Load-bearing default. The agent reads this same endpoint every week
    to avoid re-filing a story it already told, and it pays by the token —
    evidence is the biggest field on the row, and the agent never uses it."""
    holder = []
    api([[]], keep=holder).get("/synthesis/proposals")
    sql, _ = holder[0].cursor_obj.executed[0]
    assert "evidence" not in sql


def test_evidence_is_returned_when_the_page_asks_for_it(api):
    holder = []
    body = api([[reviewed_row()]], keep=holder).get(
        "/synthesis/proposals", params={"include_evidence": True}
    ).json()
    sql, _ = holder[0].cursor_obj.executed[0]
    assert "evidence" in sql
    assert body["proposals"][0]["evidence"]["evidence"].startswith("get_window")


def test_accepting_a_proposal_returns_the_updated_row(api):
    body = api([[reviewed_row()]]).post(
        "/synthesis/proposals/1/review",
        json={"decision": "accepted", "note": "Matches what I saw in the outcome table."},
    ).json()
    assert body["status"] == "accepted"
    assert body["reviewed_note"] == "Matches what I saw in the outcome table."


def test_dismissing_is_a_first_class_outcome_not_a_delete(api):
    """A dismissed proposal stays fully readable — the record is what the
    agent said AND what the human decided, not only the agreements."""
    body = api([[reviewed_row(status="dismissed")]]).post(
        "/synthesis/proposals/1/review", json={"decision": "dismissed"}
    ).json()
    assert body["status"] == "dismissed"
    assert body["summary"], "the proposal's own text must survive the dismissal"
    assert body["evidence"], "so must its evidence"


def test_the_proposal_itself_is_never_edited(api):
    """Only the review fields move. A row that recorded a human disagreeing
    with the agent, but no longer said what the agent had claimed, would be
    useless as a record."""
    holder = []
    api([[reviewed_row()]], keep=holder).post(
        "/synthesis/proposals/1/review", json={"decision": "accepted"}
    )
    sql, _ = holder[0].cursor_obj.executed[0]
    assert "SET status" in sql
    for untouchable in ("summary =", "confidence =", "evidence =", "finding_type ="):
        assert untouchable not in sql


def test_an_unknown_decision_is_refused(api):
    response = api([[]]).post(
        "/synthesis/proposals/1/review", json={"decision": "maybe"}
    )
    assert response.status_code == 400
    assert "accepted" in response.json()["detail"]


def test_a_missing_proposal_is_a_404_not_a_silent_success(api):
    response = api([[]]).post(
        "/synthesis/proposals/999/review", json={"decision": "accepted"}
    )
    assert response.status_code == 404


def test_a_blank_note_is_stored_as_nothing_not_as_an_empty_string(api):
    holder = []
    api([[reviewed_row(reviewed_note=None)]], keep=holder).post(
        "/synthesis/proposals/1/review", json={"decision": "accepted", "note": "   "}
    )
    _, params = holder[0].cursor_obj.executed[0]
    assert params["note"] is None


def test_a_decision_can_be_changed(api):
    """A researcher who dismisses something on Monday and reconsiders on
    Friday is doing their job. reviewed_at moves with the decision, so the
    row always says when the standing verdict was made."""
    holder = []
    api([[reviewed_row(status="accepted")]], keep=holder).post(
        "/synthesis/proposals/1/review", json={"decision": "accepted"}
    )
    sql, _ = holder[0].cursor_obj.executed[0]
    assert "reviewed_at = now()" in sql
    assert "WHERE id" in sql and "status = 'pending'" not in sql
