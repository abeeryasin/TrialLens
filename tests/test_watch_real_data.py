"""GET /watch against the live database — does the SQL say what it claims?

tests/test_watch_endpoint.py runs the route with a fake connection that
ignores SQL, so it proves the arithmetic and the response model and nothing
about the queries. This file runs the real endpoint over HTTP against the
real database, and then checks the one assumption the whole screen rests on.

**The assumption: `monitor_runs` records every scheduled check.** Direction 3
replaced the old proxy (`max(studies.last_matched_at)`) with a real run log:
scripts/run_monitor.py opens a row at the start of a run and closes it as
'completed' at the end, so the watch has direct evidence a check happened
even on a quiet week when nothing was detected.

It holds only while run_monitor.py actually closes its rows. If it starts
failing before the update — or stops writing the table at all — the newest
completed run falls behind the changes the same runs are still recording,
and this endpoint reports a dead watch on live data, **silently**, with no
error anywhere. That is what test_the_run_record_is_not_behind_the_changes_
it_should_explain exists to catch.

Free — read-only, no model, no network beyond Neon. Skipped cleanly when
DATABASE_URL_READONLY isn't set, so CI without credentials stays green;
these run in monitor.yml, on the data's schedule.

Run: PYTHONPATH=. python3 -m pytest tests/test_watch_real_data.py -v
"""
import os
from datetime import timedelta

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.watch import RECORD_DAYS

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

DSN = os.getenv("DATABASE_URL_READONLY")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set; real-data checks skipped"
)


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.close()


@pytest.fixture(scope="module")
def watch():
    """The real route, real SQL, real database, over HTTP.

    No dependency_overrides: get_readonly_db opens its own connection from
    DATABASE_URL_READONLY, which is the same read-only Postgres role the
    deployed app uses. A test that called watch_status() directly would skip
    request binding and response validation (CLAUDE.md sec. 7).
    """
    response = TestClient(app).get("/watch")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_run_record_is_not_behind_the_changes_it_should_explain(cur, watch):
    """The newest completed run must be at least as recent as the newest
    detected change. If it is older, a run wrote changes and then never
    closed its row — the log has stopped tracking the job it describes, and
    the alarm can no longer be trusted in either direction.

    Allows a small tolerance: within one run the diff is written before the
    run record is closed, so completed_at is normally LATER — the failure
    being caught is it being meaningfully earlier.
    """
    cur.execute("SELECT max(detected_at) AS mx FROM study_changes")
    newest_change = cur.fetchone()["mx"]
    if newest_change is None:
        pytest.skip("no changes recorded yet")

    cur.execute(
        "SELECT max(completed_at) AS mx FROM monitor_runs WHERE status = 'completed'"
    )
    newest_run = cur.fetchone()["mx"]
    assert newest_run is not None, "no completed run on record"

    assert newest_run >= newest_change - timedelta(minutes=5), (
        f"the newest completed run ({newest_run}) is behind the newest recorded "
        f"change ({newest_change}) — run_monitor.py is recording changes but no "
        "longer closing its run record, so /watch's 'last checked' is stale"
    )


def test_the_reported_check_time_is_the_one_in_the_table(cur, watch):
    cur.execute(
        "SELECT max(completed_at) AS mx FROM monitor_runs WHERE status = 'completed'"
    )
    assert watch["last_checked_at"].startswith(
        cur.fetchone()["mx"].isoformat()[:19]
    )


def test_the_record_strip_is_exactly_a_week_including_its_empty_days(watch):
    """generate_series, not GROUP BY. A week with three quiet days must
    still come back as seven entries — the zeros are the finding."""
    assert len(watch["daily"]) == RECORD_DAYS
    days = [d["day"] for d in watch["daily"]]
    assert days == sorted(days), "the strip must read left to right in time"
    assert len(set(days)) == RECORD_DAYS, "a day appears twice"


def test_the_strip_counts_the_same_amendments_a_direct_count_finds(cur, watch):
    """The LEFT JOIN in the strip query could quietly over-count if an
    amendment row ever matched more than one generated day."""
    cur.execute(
        """
        SELECT count(*) AS n FROM study_changes
        WHERE field_name = 'last_update_post_date'
          AND detected_at::date > current_date - %s
        """,
        (RECORD_DAYS,),
    )
    assert sum(d["amendments"] for d in watch["daily"]) == cur.fetchone()["n"]


def test_the_totals_match_the_database(cur, watch):
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE active_in_scope) AS watched,
               count(*) FILTER (WHERE active_in_scope AND has_results) AS with_results,
               count(*) FILTER (WHERE active_in_scope AND has_results
                                  AND overall_status = 'COMPLETED') AS completed
        FROM studies
        """
    )
    row = cur.fetchone()
    assert watch["trials_watched"] == row["watched"]
    assert watch["trials_with_results"] == row["with_results"]
    assert watch["completed_with_results"] == row["completed"]
    assert watch["completed_with_results"] <= watch["trials_with_results"]

    cur.execute(
        """
        SELECT count(*) AS changes,
               count(*) FILTER (WHERE field_name = 'last_update_post_date') AS amendments
        FROM study_changes
        """
    )
    row = cur.fetchone()
    assert watch["changes_recorded"] == row["changes"]
    assert watch["amendments_seen"] == row["amendments"]


def test_the_headline_counts_amendments_not_changed_rows(cur, watch):
    """An amendment that moved four dates is ONE thing that happened. If
    this ever counted rows, a quiet day with one busy trial would be
    announced as four amendments."""
    cur.execute(
        """
        SELECT count(*) AS amendments, count(DISTINCT nct_id) AS trials
        FROM study_changes
        WHERE field_name = 'last_update_post_date'
          AND detected_at >= now() - make_interval(hours => %s)
        """,
        (watch["recent"]["window_hours"],),
    )
    row = cur.fetchone()
    assert watch["recent"]["amendments"] == row["amendments"]
    assert watch["recent"]["trials"] == row["trials"]


def test_the_finding_never_exceeds_the_total_it_is_drawn_from(watch):
    """results_posted ⊆ scientific ⊆ amendments. The UI subtracts these to
    say "N others changed something scientific"; if the containment broke,
    that subtraction would go negative and the page would state a
    nonsense fact about real trials."""
    recent = watch["recent"]
    assert recent["results_posted"] <= recent["scientific"] <= recent["amendments"]
    assert recent["trials"] <= recent["amendments"]


def test_the_last_amendment_is_really_the_last_one(cur, watch):
    """Ties are the normal case — one cron run posts dozens sharing an exact
    detected_at (63 on 2026-09-01) — so this does not assert WHICH row was
    picked. It asserts the only thing that must be true: no amendment was
    posted later than the one shown.
    """
    if watch["last_amendment"] is None:
        pytest.skip("no amendments recorded yet")

    cur.execute(
        """
        SELECT max(new_value) AS latest FROM study_changes
        WHERE field_name = 'last_update_post_date' AND new_value IS NOT NULL
        """
    )
    assert watch["last_amendment"]["posted_on"] == cur.fetchone()["latest"]


def test_every_field_shown_under_the_last_amendment_belongs_to_it(cur, watch):
    """The fields are pulled by an exact detected_at equality. If ingest ever
    splits one trial's diff across two transactions, this endpoint would show
    a partial amendment while claiming it is the whole one."""
    last = watch["last_amendment"]
    if last is None or not last["changes"]:
        pytest.skip("no visible amendment content to check")

    cur.execute(
        """
        SELECT count(*) AS n FROM study_changes
        WHERE nct_id = %s
          AND detected_at = %s
          AND field_name <> 'last_update_post_date'
        """,
        (last["nct_id"], last["detected_at"]),
    )
    assert len(last["changes"]) == cur.fetchone()["n"]


def test_a_live_watch_reports_itself_healthy(watch):
    """Not a tautology — this is the smoke alarm for the cron itself. The
    6-hour job has been firing since 2026-08-28; if this fails in
    monitor.yml, the run that just finished did not leave the evidence
    /watch reads, and the front page is about to show the alarm.
    """
    assert watch["last_checked_at"] is not None, "no check has ever been recorded"
    assert watch["is_healthy"], (
        f"the watch reports itself stopped — last check "
        f"{watch['hours_since_check']}h ago, {watch['checks_missed']} missed"
    )
