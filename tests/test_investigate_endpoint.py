"""GET /investigate over HTTP, against a fake connection.

The fake ignores SQL by design (see tests/conftest.py), so nothing here
says the queries are right — that is tests/test_investigate_real_data.py's
job, and the split matters: on 2026-09-04 a mutation that removed the
canonical join from Explore passed every fake-connection test in the repo.

What these cover is what only an HTTP call can: request binding, the
route's assembly between query and response, and the response model.
"""
from datetime import datetime, timedelta, timezone

import pytest

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
RECORDING_SINCE = datetime(2026, 8, 28, 12, 55, tzinfo=timezone.utc)


def amendment_row(field_name=None, old=None, new=None, nct_id="NCT1", at=T0, **extra):
    """One row of the amendment query's LEFT JOIN. field_name None is the
    real shape for an amendment whose changes were all filtered out."""
    base = {
        "nct_id": nct_id,
        "brief_title": f"Trial {nct_id}",
        "detected_at": at,
        "posted_on": "2026-08-30",
        "field_name": field_name,
        "old_value": old,
        "new_value": new,
        "prose_interpretation": None,
        "current_enrollment_count": None,
        "primary_completion_date": None,
        "start_date": None,
        "has_results": False,
        "org_class": None,
    }
    base.update(extra)
    return base


def results(amendments=(), scope=(), tracked=11444, recording_since=RECORDING_SINCE):
    """The four result sets the route consumes, in the order it asks."""
    return [
        list(amendments),
        list(scope),
        [{"tracked": tracked}],
        [{"since": recording_since}],
    ]


def test_returns_the_full_shape(api):
    body = api(results()).get("/investigate").json()
    assert set(body) == {
        "window", "dates", "lifecycle", "enrollment", "outcomes",
        "scope_exits", "scope_exits_total",
    }


def test_window_carries_every_denominator(api):
    rows = [
        amendment_row("overall_status", "RECRUITING", "COMPLETED", nct_id="NCT1"),
        amendment_row("brief_title", "a", "b", nct_id="NCT1"),
        amendment_row("overall_status", "RECRUITING", "COMPLETED", nct_id="NCT2"),
    ]
    window = api(results(rows)).get("/investigate", params={"days": 7}).json()["window"]

    assert window["days"] == 7
    assert window["trials_tracked"] == 11444
    assert window["trials_changed"] == 2
    assert window["amendments"] == 2  # two (trial, detected_at) pairs
    assert window["field_changes"] == 3


def test_an_amendment_with_no_readable_change_still_counts_as_an_amendment(api):
    """A LEFT JOIN row with field_name NULL is an amendment whose changes
    were all prose or all filtered. Counting only content rows would report
    a quieter week than the one that happened."""
    window = api(results([amendment_row()])).get("/investigate").json()["window"]
    assert window["amendments"] == 1
    assert window["field_changes"] == 0
    assert window["trials_changed"] == 1


def test_a_window_longer_than_the_record_says_so(api):
    """A 90-day window over an 8-day record must not imply 82 quiet days
    nobody was watching (sec. 2)."""
    window = api(results()).get("/investigate", params={"days": 90}).json()["window"]
    assert window["covers_full_window"] is False
    assert window["recording_since"].startswith("2026-08-28")


def test_a_window_inside_the_record_is_fully_covered(api):
    window = api(results()).get("/investigate", params={"days": 1}).json()["window"]
    assert window["covers_full_window"] is True


def test_an_empty_record_does_not_claim_coverage(api):
    window = api(results(recording_since=None)).get("/investigate").json()["window"]
    assert window["recording_since"] is None
    assert window["covers_full_window"] is False


@pytest.mark.parametrize("days", [0, -1, 366, 100000])
def test_the_window_is_bounded(api, days):
    assert api(results()).get("/investigate", params={"days": days}).status_code == 422


@pytest.mark.parametrize("days", [1, 7, 365])
def test_valid_windows_are_accepted(api, days):
    assert api(results()).get("/investigate", params={"days": days}).status_code == 200


def test_default_window_is_a_week(api):
    assert api(results()).get("/investigate").json()["window"]["days"] == 7


def test_a_condition_filter_is_reported_back(api):
    body = api(results()).get("/investigate", params={"condition": "Breast Cancer"}).json()
    assert body["window"]["condition"] == "Breast Cancer"


def test_a_condition_filter_reaches_the_sql_as_exists_not_a_join(api):
    """study_conditions has 32,701 rows over 11,544 trials and one trial
    carries up to 19 tags for the same condition, so a JOIN multiplies
    every change row by its tag count. That exact mistake logged 19 copies
    of one change in step 6b."""
    holder = []
    api(results(), keep=holder).get("/investigate", params={"condition": "Obesity"})
    statements = [sql for sql, _ in holder[0].cursor_obj.executed]

    assert all("JOIN study_conditions" not in sql for sql in statements)
    assert any("EXISTS" in sql and "study_conditions" in sql for sql in statements)
    assert any(params.get("condition") == "%Obesity%" for _, params in holder[0].cursor_obj.executed)


def test_without_a_condition_no_condition_clause_is_sent(api):
    holder = []
    api(results(), keep=holder).get("/investigate")
    assert all("study_conditions" not in sql for sql, _ in holder[0].cursor_obj.executed)


def test_tracking_fields_are_excluded_from_amendments(api):
    """active_in_scope is TrialLens's own bookkeeping, not something a
    sponsor did — the same line api/tracking.py draws for Monitor."""
    holder = []
    api(results(), keep=holder).get("/investigate")
    _, params = holder[0].cursor_obj.executed[0]
    assert params["tracking_fields"] == ["active_in_scope"]


def test_the_window_start_is_days_before_now(api):
    body = api(results()).get("/investigate", params={"days": 30}).json()["window"]
    since = datetime.fromisoformat(body["since"].replace("Z", "+00:00"))
    until = datetime.fromisoformat(body["until"].replace("Z", "+00:00"))
    assert timedelta(days=29, hours=23) < until - since < timedelta(days=30, hours=1)


# ---------------------------------------------------------------------------
# as_of (2026-09-05) — a historical window, for the weekly synthesis agent's
# "was last week's movement a pattern or a coincidence?" question. That needs
# the exact same 7-day arithmetic applied to a week that already ended, not
# only the trailing week from right now.
# ---------------------------------------------------------------------------

def test_as_of_moves_the_window_instead_of_defaulting_to_now(api):
    as_of = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    body = api(results()).get(
        "/investigate", params={"days": 7, "as_of": as_of.isoformat()}
    ).json()["window"]
    until = datetime.fromisoformat(body["until"].replace("Z", "+00:00"))
    since = datetime.fromisoformat(body["since"].replace("Z", "+00:00"))
    assert until == as_of
    assert since == as_of - timedelta(days=7)


def test_as_of_reaches_the_sql_as_an_upper_bound(api):
    """Without this, a historical as_of would still pull every amendment up
    to the real present — the exact bug that would make two 'weekly' windows
    overlap instead of being distinct."""
    holder = []
    as_of = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    api(results(), keep=holder).get(
        "/investigate", params={"days": 7, "as_of": as_of.isoformat()}
    )
    _, params = holder[0].cursor_obj.executed[0]
    assert params["until"] == as_of


def test_omitting_as_of_still_behaves_like_before(api):
    """The default caller (every page except the synthesis agent) must see
    no change: until defaults to now, same as it always did."""
    body = api(results()).get("/investigate", params={"days": 7}).json()["window"]
    until = datetime.fromisoformat(body["until"].replace("Z", "+00:00"))
    assert (datetime.now(timezone.utc) - until) < timedelta(seconds=30)


def test_findings_render_through_the_response_model(api):
    """One row of each kind, so a schema that cannot serialise a finding
    fails here rather than in the browser."""
    rows = [
        amendment_row("primary_completion_date", "2026-01-01", "2027-01-01", nct_id="NCT1"),
        amendment_row("overall_status", "COMPLETED", "RECRUITING", nct_id="NCT2"),
        amendment_row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT3",
                      current_enrollment_count=200),
        amendment_row(
            "primary_outcomes",
            '[{"measure": "Overall survival"}]',
            '[{"measure": "Adverse events"}]',
            nct_id="NCT4",
            primary_completion_date="2025-01-01",
            org_class="INDUSTRY",
        ),
    ]
    scope = [{
        "nct_id": "NCT5", "brief_title": "Dropped", "overall_status": "COMPLETED",
        "last_update_post_date": None, "field_name": "active_in_scope",
        "old_value": "true", "new_value": "false", "detected_at": T0,
    }]
    body = api(results(rows, scope)).get("/investigate").json()

    (date_finding,) = body["dates"]
    assert date_finding["label"] == "Primary completion" and date_finding["pushed"] == 1

    assert body["lifecycle"][0]["kind"] == "reopened_after_finishing"
    assert body["lifecycle"][0]["anomaly"] is True

    assert body["enrollment"]["became_actual_total"] == 1
    assert body["enrollment"]["became_actual"][0]["count_after"] == 200

    outcomes = body["outcomes"]
    assert outcomes["substantive"] == 1
    assert outcomes["changes"][0]["measures_removed"] == ["Overall survival"]
    assert "after_primary_completion" in outcomes["changes"][0]["flags"]

    assert body["scope_exits_total"] == 1
    assert body["scope_exits"][0]["nct_id"] == "NCT5"


def test_scope_arrivals_are_not_counted_as_departures(api):
    scope = [{
        "nct_id": "NCT9", "brief_title": "Back", "overall_status": "RECRUITING",
        "last_update_post_date": None, "field_name": "active_in_scope",
        "old_value": "false", "new_value": "true", "detected_at": T0,
    }]
    body = api(results(scope=scope)).get("/investigate").json()
    assert body["scope_exits_total"] == 0
    assert body["scope_exits"] == []


def test_an_empty_window_is_a_finding_not_an_error(api):
    """A quiet week is an answer. It renders as zeros, never as a blank
    page or a 404 — the same rule Home's quiet-week state keeps."""
    body = api(results()).get("/investigate").json()
    assert body["window"]["amendments"] == 0
    assert body["dates"] == [] and body["lifecycle"] == []
    assert body["outcomes"]["total"] == 0
    assert body["enrollment"]["became_actual_total"] == 0
