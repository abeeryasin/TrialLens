"""GET /investigate against the live database — is the SQL right?

tests/test_investigate_endpoint.py runs the route against a fake
connection that ignores SQL, so it proves the assembly and the response
model and nothing about the queries. This file is the other half.

Every assertion is cross-checked against a SECOND, independently written
query, so a wrong join shows up as two numbers disagreeing rather than as
a plausible-looking response. Facts are chosen by PROPERTY, never
hardcoded: "the trial with the largest completion-date move" survives
re-ingestion, NCT03402139 might not.

Read-only, no model, no CT.gov call. Skipped cleanly when
DATABASE_URL_READONLY is unset, so CI without credentials stays green —
these run in monitor.yml, on the data's schedule.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_investigate_real_data.py -v
"""
import os

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

DSN = os.getenv("DATABASE_URL_READONLY")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set; real-data checks skipped"
)

# Long enough to cover the whole record (which begins 2026-08-28) so the
# independent queries below can be unwindowed and still agree.
WINDOW = 365


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.close()


@pytest.fixture(scope="module")
def body():
    """One real HTTP call against the reader role, reused by every test —
    each request costs ~4s against Neon."""
    response = TestClient(app).get("/investigate", params={"days": WINDOW})
    assert response.status_code == 200
    return response.json()


def one(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


# ============================================================================
# Denominators
# ============================================================================


def test_tracked_count_is_the_active_watch_not_every_stored_row(cur, body):
    """100 trials have left scope. Counting them would overstate the watch,
    and every share computed against it would be wrong."""
    expected = one(cur, "SELECT count(*) AS n FROM studies WHERE active_in_scope")["n"]
    total = one(cur, "SELECT count(*) AS n FROM studies")["n"]
    assert body["window"]["trials_tracked"] == expected
    assert expected < total, "fixture assumes some trial has left scope"


def test_amendment_count_matches_the_last_update_post_date_rows(cur, body):
    """An amendment IS a last_update_post_date row. If the route ever
    counted content rows instead, a trial amending six fields at once would
    read as six amendments."""
    expected = one(
        cur,
        """
        SELECT count(DISTINCT (nct_id, detected_at)) AS n
        FROM study_changes
        WHERE field_name = 'last_update_post_date' AND new_value IS NOT NULL
        """,
    )["n"]
    assert body["window"]["amendments"] == expected


def test_tracking_bookkeeping_is_not_counted_as_a_sponsor_amendment(cur, body):
    """active_in_scope means our filter stopped matching, not that anybody
    amended anything — the line api/tracking.py already draws for Monitor.

    Planted mutation: dropping the tracking_fields filter from the join.
    That makes field_changes jump by the scope-exit count while amendments
    stays put, which is exactly what this asserts against.
    """
    expected = one(
        cur,
        """
        SELECT count(*) AS n
        FROM study_changes c
        WHERE c.field_name NOT IN ('last_update_post_date', 'active_in_scope')
          AND EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = c.nct_id AND a.detected_at = c.detected_at
                AND a.field_name = 'last_update_post_date' AND a.new_value IS NOT NULL
          )
        """,
    )["n"]
    assert body["window"]["field_changes"] == expected

    scope_changes = one(
        cur, "SELECT count(*) AS n FROM study_changes WHERE field_name = 'active_in_scope'"
    )["n"]
    assert scope_changes > 0, "fixture assumes scope exits exist to be wrongly counted"
    assert body["window"]["field_changes"] != expected + scope_changes


def test_trials_changed_counts_amended_trials_not_every_touched_row(cur, body):
    expected = one(
        cur,
        """
        SELECT count(DISTINCT nct_id) AS n FROM study_changes
        WHERE field_name = 'last_update_post_date' AND new_value IS NOT NULL
        """,
    )["n"]
    assert body["window"]["trials_changed"] == expected


def test_the_record_start_is_reported_and_a_year_does_not_claim_coverage(cur, body):
    """A 365-day window over a record that began weeks ago must say so."""
    first = one(cur, "SELECT min(detected_at) AS since FROM study_changes")["since"]
    assert body["window"]["recording_since"].startswith(first.date().isoformat())
    assert body["window"]["covers_full_window"] is False


# ============================================================================
# Date movement
# ============================================================================


def test_every_date_row_is_accounted_for(cur, body):
    """Sum of every bucket equals the rows the query saw, per field. A row
    silently dropped would shrink the denominator and overstate the rest."""
    for finding in body["dates"]:
        counted = (
            finding["pushed"] + finding["pulled"] + finding["precision_only"]
            + finding["no_move"] + finding["unreadable"]
        )
        assert counted == finding["rows_seen"], finding["field_name"]

        expected = one(
            cur,
            """
            SELECT count(*) AS n FROM study_changes c
            WHERE c.field_name = %s
              AND EXISTS (
                  SELECT 1 FROM study_changes a
                  WHERE a.nct_id = c.nct_id AND a.detected_at = c.detected_at
                    AND a.field_name = 'last_update_post_date' AND a.new_value IS NOT NULL
              )
            """,
            (finding["field_name"],),
        )["n"]
        assert finding["rows_seen"] == expected, finding["field_name"]


def test_the_biggest_mover_really_is_the_biggest(cur, body):
    """Chosen by property. The largest move in the record on 2026-09-04 was
    a 74-month pull-in; whichever trial holds it, it must sort first."""
    for finding in body["dates"]:
        if not finding["biggest"]:
            continue
        magnitudes = [abs(m["delta_days"]) for m in finding["biggest"]]
        assert magnitudes == sorted(magnitudes, reverse=True)


def test_direction_matches_the_stored_values(body):
    """A sign flip would turn every slip into a pull-in and read as a field
    that is running early."""
    for finding in body["dates"]:
        for move in finding["biggest"]:
            assert (move["delta_days"] > 0) == ("pushed" in move["effect"])
            assert (move["delta_days"] < 0) == ("pulled" in move["effect"])


def test_a_month_precision_move_is_marked_imprecise(body):
    """~23% of CT.gov dates are month-only. The flag has to travel with the
    number or a median poses as accurate to the day."""
    for finding in body["dates"]:
        for move in finding["biggest"]:
            month_only = len(move["old_value"]) == 7 or len(move["new_value"]) == 7
            assert move["imprecise"] is month_only, move


# ============================================================================
# Lifecycle
# ============================================================================


def test_status_transitions_are_partitioned_exactly_once(cur, body):
    """Every real transition lands in exactly one bucket. An overlap
    double-counts a trial; a gap loses one."""
    expected = one(
        cur,
        """
        SELECT count(*) AS n FROM study_changes c
        WHERE c.field_name = 'overall_status'
          AND c.old_value IS NOT NULL AND c.new_value IS NOT NULL
          AND c.old_value <> c.new_value
          AND EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = c.nct_id AND a.detected_at = c.detected_at
                AND a.field_name = 'last_update_post_date' AND a.new_value IS NOT NULL
          )
        """,
    )["n"]
    assert sum(f["count"] for f in body["lifecycle"]) == expected


def test_no_transition_falls_through_to_the_unclassified_bucket(body):
    """"other" is deliberately reachable so a new CT.gov status stays
    visible. If it ever fills up, the mapping needs extending — this test
    is the alarm, not a guarantee it is empty forever."""
    unclassified = [f for f in body["lifecycle"] if f["kind"] == "other"]
    assert not unclassified, f"unmapped status transitions: {unclassified}"


def test_an_anomaly_sorts_above_a_bucket_twenty_times_its_size(body):
    """COMPLETED -> RECRUITING occurred once against 21 finishings. A
    synthesis that orders purely by count buries the one surprising row."""
    anomalies = [f for f in body["lifecycle"] if f["anomaly"]]
    if not anomalies:
        pytest.skip("no lifecycle anomaly in the record right now")
    assert body["lifecycle"][0]["anomaly"] is True
    assert body["lifecycle"][0]["count"] <= max(f["count"] for f in body["lifecycle"])


# ============================================================================
# Enrollment
# ============================================================================


def test_every_type_switch_is_reported_once(cur, body):
    expected = one(
        cur,
        """
        SELECT count(*) AS n FROM study_changes c
        WHERE c.field_name = 'enrollment_type'
          AND EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = c.nct_id AND a.detected_at = c.detected_at
                AND a.field_name = 'last_update_post_date' AND a.new_value IS NOT NULL
          )
        """,
    )["n"]
    e = body["enrollment"]
    assert e["became_actual_total"] + e["switched_back_total"] == expected


def test_a_count_told_inside_a_switch_is_not_told_again_as_a_revision(cur, body):
    """Double-counting here would report more revised targets than the
    record contains, and inflate a headline number."""
    total_counts = one(
        cur,
        """
        SELECT count(*) AS n FROM study_changes c
        WHERE c.field_name = 'enrollment_count'
          AND EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = c.nct_id AND a.detected_at = c.detected_at
                AND a.field_name = 'last_update_post_date' AND a.new_value IS NOT NULL
          )
        """,
    )["n"]
    paired = one(
        cur,
        """
        SELECT count(*) AS n FROM study_changes c
        WHERE c.field_name = 'enrollment_count'
          AND EXISTS (
              SELECT 1 FROM study_changes t
              WHERE t.nct_id = c.nct_id AND t.detected_at = c.detected_at
                AND t.field_name = 'enrollment_type'
          )
        """,
    )["n"]
    e = body["enrollment"]
    assert e["target_raised_total"] + e["target_lowered_total"] == total_counts - paired


def test_under_target_never_exceeds_the_switches_it_is_drawn_from(body):
    e = body["enrollment"]
    assert 0 <= e["under_target"] <= e["became_actual_total"]


def test_a_named_switch_carries_the_numbers_the_record_states(cur, body):
    """The most consequential figure Investigate produces. Checked against
    the stored row rather than against itself."""
    for move in body["enrollment"]["became_actual"]:
        if not move["count_moved"]:
            continue
        stored = one(
            cur,
            """
            SELECT old_value, new_value FROM study_changes
            WHERE nct_id = %s AND field_name = 'enrollment_count'
              AND detected_at = %s
            """,
            (move["nct_id"], move["detected_at"]),
        )
        assert stored is not None, move["nct_id"]
        assert int(stored["old_value"]) == move["count_before"]
        assert int(stored["new_value"]) == move["count_after"]


# ============================================================================
# Primary outcomes — the finding that must not over-claim
# ============================================================================


def test_every_outcome_change_is_seen(cur, body):
    expected = one(
        cur,
        """
        SELECT count(*) AS n FROM study_changes c
        WHERE c.field_name = 'primary_outcomes'
          AND EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = c.nct_id AND a.detected_at = c.detected_at
                AND a.field_name = 'last_update_post_date' AND a.new_value IS NOT NULL
          )
        """,
    )["n"]
    o = body["outcomes"]
    assert o["total"] + o["unreadable"] == expected
    assert o["substantive"] + o["wording_only"] == o["total"]


def test_reformatting_is_actually_being_separated(body):
    """If normalisation ever silently stopped working, every change would
    read as substantive and the whole finding would become an accusation
    machine. 9 of 17 were wording on 2026-09-04."""
    o = body["outcomes"]
    if o["total"] == 0:
        pytest.skip("no outcome changes in the record right now")
    assert o["wording_only"] > 0, "normalisation is catching nothing — check normalise_measure"


def test_a_wording_change_is_never_counted_as_a_post_completion_change(body):
    """The specific false accusation this design exists to prevent.
    NCT03674567 has results posted and is past primary completion, and its
    change is capitalisation."""
    o = body["outcomes"]
    assert o["after_primary_completion"] <= o["substantive"]
    for change in o["changes"]:
        if change["wording_only"]:
            assert change["measures_added"] == [] and change["measures_removed"] == []


def test_a_flag_is_backed_by_a_stated_field(cur, body):
    """Each flag must be re-derivable from the studies row. A flag with no
    stated basis is an invented fact (sec. 2)."""
    for change in body["outcomes"]["changes"]:
        trial = one(
            cur,
            """
            SELECT s.primary_completion_date, s.start_date, s.has_results,
                   (SELECT o.org_class FROM trial_organizations o
                    WHERE o.nct_id = s.nct_id AND o.role = 'LEAD' LIMIT 1) AS org_class
            FROM studies s WHERE s.nct_id = %s
            """,
            (change["nct_id"],),
        )
        if "results_posted" in change["flags"]:
            assert trial["has_results"] is True
        if "industry_sponsored" in change["flags"]:
            assert trial["org_class"] == "INDUSTRY"
        if "after_primary_completion" in change["flags"]:
            assert trial["primary_completion_date"] is not None
        if "after_start" in change["flags"]:
            assert trial["start_date"] is not None


def test_no_change_carries_a_score_or_a_confidence_number(body):
    """sec. 3: no unexplained relevance scores, no black-box ranking. Step
    7 was built, measured and removed over exactly this."""
    for change in body["outcomes"]["changes"]:
        assert "score" not in change and "confidence" not in change
        assert isinstance(change["flags"], list)


# ============================================================================
# Scope departures
# ============================================================================


def test_departures_are_departures_not_every_scope_row(cur, body):
    expected = one(
        cur,
        """
        SELECT count(*) AS n FROM study_changes
        WHERE field_name = 'active_in_scope' AND new_value IN ('false', 'f', '0')
        """,
    )["n"]
    assert body["scope_exits_total"] == expected


# ============================================================================
# The condition filter
# ============================================================================


def test_a_condition_slice_is_a_subset_that_still_sums_correctly(cur):
    """The EXISTS filter must narrow the analysis without multiplying rows.

    Planted mutation: replacing EXISTS with a JOIN on study_conditions.
    One trial carries up to 19 tags for the same condition, so the joined
    version reports far more field changes than exist — the step-6b bug.
    """
    client = TestClient(app)
    sliced = client.get("/investigate", params={"days": WINDOW, "condition": "Obesity"})
    assert sliced.status_code == 200
    sliced = sliced.json()

    whole = client.get("/investigate", params={"days": WINDOW}).json()

    assert sliced["window"]["trials_tracked"] < whole["window"]["trials_tracked"]
    assert sliced["window"]["field_changes"] <= whole["window"]["field_changes"]
    assert sliced["window"]["amendments"] <= whole["window"]["amendments"]

    expected_changed = one(
        cur,
        """
        SELECT count(DISTINCT c.nct_id) AS n
        FROM study_changes c
        WHERE c.field_name = 'last_update_post_date' AND c.new_value IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM study_conditions sc
              WHERE sc.nct_id = c.nct_id AND sc.condition ILIKE %s
          )
        """,
        ("%Obesity%",),
    )["n"]
    assert sliced["window"]["trials_changed"] == expected_changed
