"""GET /studies/{nct_id}/amendments, over real HTTP.

CLAUDE.md sec. 7: "A test that calls an endpoint function directly is not
testing the endpoint — request binding and response validation are
FastAPI's job, and only an HTTP-level call exercises them." That rule was
written after bug #9, where POST /rank returned 500 on every request while
the function underneath it worked fine, and it cost $0.13 of live model
calls to discover. So these go through TestClient.

No database and no network: get_readonly_db is overridden with a scripted
fake, because what is under test is the grouping and the response contract,
not Postgres. The properties that DO depend on real data have their own
file — tests/test_amendment_grouping_real_data.py.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.database import get_readonly_db
from api.main import app

RUN_1 = datetime(2026, 8, 28, 12, 55, 52, 606898, tzinfo=timezone.utc)
RUN_2 = datetime(2026, 8, 31, 18, 2, 40, 817298, tzinfo=timezone.utc)


class FakeCursor:
    """Returns queued results in order, ignoring the SQL.

    Deliberately dumb. A fake that tried to interpret the SQL would be a
    second, worse Postgres, and passing against it would prove nothing about
    the real query — that is what the real-data tests are for. This one
    exists to exercise the route: binding, assembly, and the response model.
    """

    def __init__(self, results):
        self._results = list(results)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def _next(self):
        assert self._results, "the route ran more queries than the fake was given"
        return self._results.pop(0)

    def fetchone(self):
        rows = self._next()
        return rows[0] if rows else None

    def fetchall(self):
        return self._next()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, results):
        self.cursor_obj = FakeCursor(results)

    def cursor(self, **kwargs):
        return self.cursor_obj


def client_returning(results):
    app.dependency_overrides[get_readonly_db] = lambda: FakeConnection(results)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# Query order in the route: exists-check, amendment join, orphans, recording_since.
def results(*, exists=True, amendment_rows=(), orphans=(), since=RUN_1):
    return [
        [{"?column?": 1}] if exists else [],
        list(amendment_rows),
        list(orphans),
        [{"since": since}],
    ]


def test_unknown_trial_is_404_not_an_empty_history():
    """The honesty case that motivated the exists-check.

    An empty 200 says "we have a record and it shows no amendments". For an
    nct_id we have never seen, that is a false statement about a trial
    (sec. 2), and it reads to a researcher as "this trial has been quiet".
    """
    response = client_returning(results(exists=False)).get("/studies/NCT99999999/amendments")
    assert response.status_code == 404
    assert "NCT99999999" in response.json()["detail"]


def test_a_trial_with_no_amendments_returns_an_empty_history_not_an_error():
    response = client_returning(results()).get("/studies/NCT00002644/amendments")
    assert response.status_code == 200
    body = response.json()
    assert body["amendments"] == []
    assert body["total_amendments"] == 0
    assert body["recording_since"] is not None, (
        "the window must be stated even when empty — a count of zero means "
        "nothing without the date it counts from"
    )


def test_changes_are_grouped_under_the_amendment_that_caused_them():
    """The real NCT02954874 shape: four fields moved in one amendment."""
    rows = [
        {
            "posted_on": "2026-08-31", "previously_posted_on": "2026-08-28",
            "detected_at": RUN_2, "field_name": field,
            "old_value": old, "new_value": new,
        }
        for field, old, new in [
            ("completion_date", "2026-08-31", "2027-08-27"),
            ("enrollment_count", "1155", "1195"),
            ("enrollment_type", "ESTIMATED", "ACTUAL"),
            ("primary_completion_date", "2026-08-31", "2026-08-03"),
        ]
    ]
    body = client_returning(results(amendment_rows=rows)).get(
        "/studies/NCT02954874/amendments"
    ).json()

    assert body["total_amendments"] == 1, "four field changes are ONE amendment, not four"
    amendment = body["amendments"][0]
    assert amendment["posted_on"] == "2026-08-31"
    assert amendment["previously_posted_on"] == "2026-08-28"
    assert amendment["content_is_visible"] is True
    assert len(amendment["changes"]) == 4
    assert {c["field_name"] for c in amendment["changes"]} == {
        "completion_date", "enrollment_count", "enrollment_type", "primary_completion_date"
    }


def test_an_amendment_touching_only_untracked_fields_is_flagged_not_dropped():
    """47% of real amendments look like this (measured 2026-09-01).

    The LEFT JOIN yields one row with a NULL field_name. It must produce an
    amendment marked content_is_visible=False — not a missing amendment, and
    not an amendment with a phantom change.
    """
    rows = [{
        "posted_on": "2026-08-28", "previously_posted_on": "2026-07-31",
        "detected_at": RUN_1, "field_name": None,
        "old_value": None, "new_value": None,
    }]
    body = client_returning(results(amendment_rows=rows)).get(
        "/studies/NCT02954874/amendments"
    ).json()

    assert body["total_amendments"] == 1
    assert body["invisible_amendment_count"] == 1
    amendment = body["amendments"][0]
    assert amendment["content_is_visible"] is False
    assert amendment["changes"] == [], "a NULL join row is not a change"


def test_two_amendments_stay_separate_and_newest_first():
    rows = [
        {"posted_on": "2026-08-31", "previously_posted_on": "2026-08-28",
         "detected_at": RUN_2, "field_name": "enrollment_count",
         "old_value": "1155", "new_value": "1195"},
        {"posted_on": "2026-08-28", "previously_posted_on": "2026-07-31",
         "detected_at": RUN_1, "field_name": None,
         "old_value": None, "new_value": None},
    ]
    body = client_returning(results(amendment_rows=rows)).get(
        "/studies/NCT02954874/amendments"
    ).json()

    assert body["total_amendments"] == 2
    assert [a["posted_on"] for a in body["amendments"]] == ["2026-08-31", "2026-08-28"]
    assert body["invisible_amendment_count"] == 1
    assert len(body["amendments"][0]["changes"]) == 1
    assert body["amendments"][1]["changes"] == []


def test_amendments_at_different_timestamps_never_merge():
    """Two amendments that happen to post the same CT.gov date must stay
    apart — the grouping key is detected_at, and merging them would fold two
    real registry versions into one."""
    rows = [
        {"posted_on": "2026-08-31", "previously_posted_on": "2026-08-30",
         "detected_at": RUN_2, "field_name": "overall_status",
         "old_value": "RECRUITING", "new_value": "ACTIVE_NOT_RECRUITING"},
        {"posted_on": "2026-08-31", "previously_posted_on": "2026-08-30",
         "detected_at": RUN_1, "field_name": "brief_title",
         "old_value": "Old", "new_value": "New"},
    ]
    body = client_returning(results(amendment_rows=rows)).get(
        "/studies/NCT02954874/amendments"
    ).json()
    assert body["total_amendments"] == 2


def test_unattributed_changes_are_surfaced_rather_than_silently_dropped():
    """Should never happen; must never be invisible if it does.

    A content change with no matching amendment is a recorded fact about a
    trial. Dropping it makes the trial look quieter than it was, which is
    the worst available failure for a monitoring tool.
    """
    orphan = {
        "field_name": "eligibility_criteria", "old_value": "a", "new_value": "b",
        "detected_at": RUN_2,
    }
    body = client_returning(results(orphans=[orphan])).get(
        "/studies/NCT02954874/amendments"
    ).json()

    assert len(body["unattributed_changes"]) == 1
    assert body["unattributed_changes"][0]["field_name"] == "eligibility_criteria"


def test_tracking_fields_are_excluded_by_the_query_not_by_the_caller():
    """The exclusion must reach the database, and must come from
    TRACKING_FIELDS rather than a string typed into the SQL.

    Filtering in Python instead would leave the orphan query unfiltered, and
    every active_in_scope event would then surface as an unattributed
    change — our own bookkeeping presented as an unexplained trial change.
    """
    fake = FakeConnection(results())
    app.dependency_overrides[get_readonly_db] = lambda: fake
    TestClient(app).get("/studies/NCT02954874/amendments")

    sql_sent = " ".join(sql for sql, _ in fake.cursor_obj.executed)
    params_sent = [params for _, params in fake.cursor_obj.executed if params]

    assert "active_in_scope" not in sql_sent, (
        "the field name is hardcoded in SQL — it must come from "
        "api.tracking.TRACKING_FIELDS so there is one definition"
    )
    assert sum("active_in_scope" in str(p) for p in params_sent) == 2, (
        "both the amendment query and the orphan query must exclude tracking "
        "fields; excluding it from only one leaks it into unattributed_changes"
    )
