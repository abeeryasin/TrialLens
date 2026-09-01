"""The three properties amendment grouping rests on, against the real database.

`GET /studies/{nct_id}/amendments` groups study_changes rows into amendments
by joining each content change to the last_update_post_date change with the
same nct_id and the same detected_at. That is an exact equality join, not a
time window, and it is only correct because of three facts about how the
data is written. All three were measured on 2026-09-01 and all three could
stop being true — if ingest ever splits one trial's diff across two
transactions, or CT.gov starts posting two versions between two cron runs,
the grouping mis-reports **silently**: no error, just amendments split in
two or changes attached to the wrong one.

Free — no model calls, read-only, and skipped when DATABASE_URL_READONLY
isn't set, so CI without credentials stays green.

Run: PYTHONPATH=. python3 -m pytest tests/test_amendment_grouping_real_data.py -v
"""
import os

import psycopg2
import psycopg2.extras
import pytest

from api.tracking import TRACKING_FIELDS

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

DSN = os.getenv("DATABASE_URL_READONLY")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set; real-data checks skipped"
)

AMENDMENT_FIELD = "last_update_post_date"


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.close()


def test_every_content_change_shares_an_exact_timestamp_with_its_amendment(cur):
    """Property 1 — the join is an equality, so it must hold exactly.

    Postgres `now()` is transaction-start time, and one trial's whole diff
    is written in one transaction, so every row of one amendment carries an
    identical detected_at. Measured 2026-09-01: 195 of 195, no exceptions.

    If this fails, the endpoint is dropping real changes on the floor — they
    would land in `unattributed_changes` rather than under the amendment
    that caused them, and the trial would read as quieter than it was.
    """
    cur.execute(
        """
        SELECT count(*) AS orphans
        FROM study_changes sc
        WHERE sc.field_name <> %s
          AND NOT (sc.field_name = ANY(%s))
          AND NOT EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = sc.nct_id
                AND a.field_name = %s
                AND a.detected_at = sc.detected_at
          )
        """,
        (AMENDMENT_FIELD, sorted(TRACKING_FIELDS), AMENDMENT_FIELD),
    )
    orphans = cur.fetchone()["orphans"]
    assert orphans == 0, (
        f"{orphans} content changes have no last_update_post_date change at the "
        f"same detected_at. The exact-equality grouping in "
        f"api/studies.get_study_amendments can no longer attribute them, and "
        f"they will surface as unattributed_changes. Most likely cause: one "
        f"trial's diff is now written across more than one transaction."
    )


def test_no_trial_gets_two_amendments_in_one_run(cur):
    """Property 2 — detected_at must uniquely identify an amendment.

    Two last_update_post_date changes sharing a detected_at for one trial
    would make the grouping key ambiguous, and content changes would attach
    to whichever came back first.
    """
    cur.execute(
        """
        SELECT count(*) AS collisions FROM (
            SELECT nct_id, detected_at
            FROM study_changes WHERE field_name = %s
            GROUP BY 1, 2 HAVING count(*) > 1
        ) x
        """,
        (AMENDMENT_FIELD,),
    )
    collisions = cur.fetchone()["collisions"]
    assert collisions == 0, (
        f"{collisions} (trial, timestamp) pairs carry two amendments. The "
        f"grouping key is no longer unique."
    )


def test_tracking_events_never_masquerade_as_amendments(cur):
    """Property 3 — our bookkeeping is not something a sponsor did.

    `active_in_scope` records whether TrialLens is still watching a trial.
    It is not a study fact, and showing it as an amendment would attribute
    our own scope rules to ClinicalTrials.gov. Measured 2026-09-01: all 91
    such events are standalone, never sharing a timestamp with an amendment.

    Note this asserts something stronger than the endpoint needs — the
    endpoint excludes tracking fields explicitly, so it stays correct even
    if this changes. It is here because a tracking event landing inside an
    amendment window would mean the scope reconciler had started running
    inside the ingest transaction, which is worth knowing about for its own
    sake.
    """
    cur.execute(
        """
        SELECT count(*) AS co_occurring
        FROM study_changes t
        WHERE t.field_name = ANY(%s)
          AND EXISTS (
              SELECT 1 FROM study_changes a
              WHERE a.nct_id = t.nct_id
                AND a.field_name = %s
                AND a.detected_at = t.detected_at
          )
        """,
        (sorted(TRACKING_FIELDS), AMENDMENT_FIELD),
    )
    co_occurring = cur.fetchone()["co_occurring"]
    assert co_occurring == 0, (
        f"{co_occurring} tracking events share a timestamp with an amendment. "
        f"Scope reconciliation appears to be running inside the ingest "
        f"transaction; check that the endpoint's exclusion still holds."
    )


def test_the_invisible_amendment_case_is_real_and_common(cur):
    """Not a guard — a standing measurement of the system's blind spot.

    47% of amendments (99 of 212) moved last_update_post_date and nothing
    else TrialLens stores, measured 2026-09-01. The UI's handling of this
    case is not an edge case being defensive; it is nearly half of all
    amendments, and this test fails loudly if that ever stops being true so
    the wording can be revisited rather than quietly becoming wrong.
    """
    cur.execute(
        """
        SELECT
          count(*) AS total,
          count(*) FILTER (WHERE NOT EXISTS (
              SELECT 1 FROM study_changes c
              WHERE c.nct_id = a.nct_id
                AND c.detected_at = a.detected_at
                AND c.field_name <> %s
                AND NOT (c.field_name = ANY(%s))
          )) AS invisible
        FROM study_changes a WHERE a.field_name = %s
        """,
        (AMENDMENT_FIELD, sorted(TRACKING_FIELDS), AMENDMENT_FIELD),
    )
    row = cur.fetchone()
    total, invisible = row["total"], row["invisible"]
    print(
        f"\n  {invisible:,} of {total:,} amendments ({100 * invisible // max(total, 1)}%) "
        f"changed only fields TrialLens does not store."
    )
    assert total > 0, "no amendments on record at all — has the cron stopped?"
    assert invisible > 0, (
        "no invisible amendments found. Either TrialLens now stores every "
        "field CT.gov amends (good — simplify the UI), or the query is wrong."
    )
