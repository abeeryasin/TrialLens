"""GET /investigate/landscape — the corpus view, over HTTP and against real data.

Both halves live in one file because the landscape route is mostly SQL
with very little assembly: the fake-connection tests pin the shape and the
honesty rules, and the real-data tests are the only thing that can say the
nine queries are right.
"""
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from api.main import app

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

THIS_YEAR = datetime.now(timezone.utc).year


def results(trials=100, years=(), phases=(), statuses=(), bands=(), terms=(),
            term_denominator=0, sponsors=(), results_posted=0):
    """The nine result sets the route asks for, in order."""
    return [
        [{"n": trials}],
        [{"yr": y, "n": n} for y, n in years],
        [{"label": l, "n": n} for l, n in phases],
        [{"label": l, "n": n} for l, n in statuses],
        [{"label": l, "n": n} for l, n in bands],
        [{"name": n, "type": t, "trials": c} for n, t, c in terms],
        [{"n": term_denominator}],
        [{"name": n, "trials": c} for n, c in sponsors],
        [{"n": results_posted}],
    ]


# ============================================================================
# Shape and honesty, over HTTP
# ============================================================================


def test_the_unstated_phase_share_is_kept_not_dropped(api):
    """52% of breast-cancer trials report NA or no phase. A phase chart
    that drops them describes a tidier field than the one that exists."""
    body = api(results(
        phases=[("PHASE2", 10), ("NA", 30), ("(not stated)", 20)]
    )).get("/investigate/landscape").json()

    assert body["phases"]["stated"] == 10
    assert body["phases"]["unstated"] == 50
    assert [b["label"] for b in body["phases"]["buckets"]] == ["PHASE2"]
    assert body["phases"]["unstated_label"]


def test_na_is_counted_as_unstated_not_plotted_beside_phase_three(api):
    """CT.gov's 'NA' means the trial does not use phases at all — a real
    answer, but not a rung on the ladder."""
    body = api(results(phases=[("NA", 30), ("PHASE3", 5)])).get("/investigate/landscape").json()
    assert [b["label"] for b in body["phases"]["buckets"]] == ["PHASE3"]
    assert body["phases"]["unstated"] == 30


def test_the_current_year_is_marked_as_incomplete(api):
    """2025 started 899 trials and 2026 shows 756 in September. Drawn side
    by side that is a decline, and it is the calendar."""
    body = api(results(
        years=[(str(THIS_YEAR - 1), 899), (str(THIS_YEAR), 756)]
    )).get("/investigate/landscape").json()

    last, current = body["started_per_year"]
    assert last["note"] is None
    assert current["note"] == "part year so far"


def test_a_future_start_is_marked_as_planned(api):
    body = api(results(
        years=[(str(THIS_YEAR + 1), 18)]
    )).get("/investigate/landscape").json()
    assert body["started_per_year"][0]["note"] == "planned start"


def test_intervention_reach_is_measured_against_trials_that_list_one(api):
    """4,938 of 5,377 breast-cancer trials list an intervention. A term's
    reach against the slice size would understate every one of them."""
    body = api(results(
        trials=5377,
        terms=[("Paclitaxel", "DRUG", 163)],
        term_denominator=4938,
    )).get("/investigate/landscape").json()

    assert body["trials"] == 5377
    assert body["interventions_denominator"] == 4938
    assert body["interventions"][0]["trials"] == 163


def test_enrollment_bands_are_always_all_six_in_order(api):
    """A band with no trials renders as a zero, not as a gap — the same
    rule Home's quiet week keeps."""
    body = api(results(bands=[("1-49", 5), ("1000+", 2)])).get("/investigate/landscape").json()
    assert [b["label"] for b in body["enrollment_bands"]] == [
        "1-49", "50-99", "100-249", "250-499", "500-999", "1000+"
    ]
    assert [b["count"] for b in body["enrollment_bands"]] == [5, 0, 0, 0, 0, 2]
    assert body["enrollment_stated"] == 7


def test_a_condition_filter_is_reported_back_and_reaches_the_sql(api):
    holder = []
    body = api(results(), keep=holder).get(
        "/investigate/landscape", params={"condition": "Breast Cancer"}
    ).json()
    assert body["condition"] == "Breast Cancer"
    assert any(p.get("condition") == "%Breast Cancer%" for _, p in holder[0].cursor_obj.executed)


def test_without_a_condition_the_whole_watch_is_described(api):
    holder = []
    body = api(results(), keep=holder).get("/investigate/landscape").json()
    assert body["condition"] is None
    assert all("study_conditions" not in sql for sql, _ in holder[0].cursor_obj.executed)


def test_the_slice_is_the_active_watch(api):
    holder = []
    api(results(), keep=holder).get("/investigate/landscape")
    assert all("active_in_scope" in sql for sql, _ in holder[0].cursor_obj.executed)


# ============================================================================
# Against the live database
# ============================================================================

DSN = os.getenv("DATABASE_URL_READONLY")
real_data = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set; real-data checks skipped"
)


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(DSN) if DSN else None
    if conn is None:
        pytest.skip("no database")
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.close()


@pytest.fixture(scope="module")
def real():
    response = TestClient(app).get(
        "/investigate/landscape", params={"condition": "Breast Cancer"}
    )
    assert response.status_code == 200
    return response.json()


@real_data
def test_the_slice_matches_an_independent_count(cur, real):
    cur.execute(
        """
        SELECT count(*) AS n FROM studies s
        WHERE s.active_in_scope AND EXISTS (
            SELECT 1 FROM study_conditions sc
            WHERE sc.nct_id = s.nct_id AND sc.condition ILIKE %s
        )
        """,
        ("%Breast Cancer%",),
    )
    assert real["trials"] == cur.fetchone()["n"]


@real_data
def test_the_phase_buckets_plus_unstated_account_for_every_trial(real):
    """Nothing may fall between the two. A trial missing from both would
    make every share on the chart wrong."""
    total = sum(b["count"] for b in real["phases"]["buckets"]) + real["phases"]["unstated"]
    assert total == real["trials"]
    assert real["phases"]["stated"] == sum(b["count"] for b in real["phases"]["buckets"])


@real_data
def test_the_status_buckets_account_for_every_trial(real):
    assert sum(b["count"] for b in real["statuses"]["buckets"]) == real["trials"]


@real_data
def test_the_intervention_join_is_not_a_self_join(cur, real):
    """The mutation this test exists for.

    Joining intervention_terms to itself on coalesce(canonical_id, id)
    cross-products the table, and every term comes back with the SAME
    count — the trials-listing-an-intervention total. That looks like a
    working chart. It was written that way once on 2026-09-04.
    """
    counts = [i["trials"] for i in real["interventions"]]
    assert len(set(counts)) > 1, "every term has the same count — the join cross-products"
    assert max(counts) < real["interventions_denominator"], (
        "a term reaching every trial that lists any intervention is the self-join signature"
    )


@real_data
def test_a_named_intervention_matches_an_independent_count(cur, real):
    """Checked against a second query written without the canonical join,
    resolving the merge by hand."""
    top = real["interventions"][0]
    cur.execute(
        """
        SELECT count(DISTINCT ti.nct_id) AS n
        FROM trial_interventions ti
        JOIN intervention_terms raw ON raw.id = ti.term_id
        JOIN studies s ON s.nct_id = ti.nct_id
        WHERE s.active_in_scope
          AND coalesce(raw.canonical_id, raw.id) = (
              SELECT id FROM intervention_terms WHERE name = %s AND type = %s LIMIT 1
          )
          AND EXISTS (
              SELECT 1 FROM study_conditions sc
              WHERE sc.nct_id = s.nct_id AND sc.condition ILIKE %s
          )
        """,
        (top["name"], top["type"], "%Breast Cancer%"),
    )
    assert cur.fetchone()["n"] == top["trials"]


@real_data
def test_years_are_ordered_and_only_the_current_one_is_partial(real):
    labels = [b["label"] for b in real["started_per_year"]]
    assert labels == sorted(labels)
    partial = [b for b in real["started_per_year"] if b["note"] == "part year so far"]
    assert len(partial) <= 1
    for bucket in real["started_per_year"]:
        if int(bucket["label"]) > THIS_YEAR:
            assert bucket["note"] == "planned start"


@real_data
def test_results_posted_never_exceeds_the_slice(real):
    assert 0 <= real["results_posted"] <= real["trials"]


@real_data
def test_a_condition_slice_is_smaller_than_the_whole_watch():
    client = TestClient(app)
    whole = client.get("/investigate/landscape").json()
    sliced = client.get("/investigate/landscape", params={"condition": "Breast Cancer"}).json()
    assert sliced["trials"] < whole["trials"]
    assert sliced["interventions_denominator"] <= whole["interventions_denominator"]
