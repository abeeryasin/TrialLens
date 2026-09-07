"""Removing a condition, against real Postgres — does the SQL do what the
fake-connection tests only assert the shape of?

tests/test_conditions_endpoint.py runs DELETE /tracked-conditions with a
connection that ignores SQL entirely, so it proves the routing, the two
refusals and the arithmetic, and **nothing about the queries**. Everything
load-bearing here is in the queries: three levels of EXISTS, a join back to
the live registry, and a case-insensitive match.

The one case that matters most is the overlap. A trial brought in by BOTH
watched conditions must keep being watched when one of them is removed — on
the live record that is only 14 trials out of 9,294, which is exactly the
kind of minority a hand-check misses and a wrong query silently drops off
the watch.

**Writes, then rolls back.** Attribution rows are inserted for real nct_ids,
the queries run against them, and the transaction is rolled back — nothing is
committed, and the registry is never touched. That matters twice over here:
this suite's own subject is a delete endpoint, and this project has twice
destroyed real rows during cleanup (the `LIKE '__%%'` incident of 2026-09-05
emptied this very table). The safest cleanup is the one that never has to
run.

Free — read-only in effect, no model, no network beyond Neon. Skipped
cleanly when DATABASE_URL isn't set.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_conditions_real_data.py -v
"""
import os

import psycopg2
import pytest

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

# The write connection, not the read-only role: this exercises INSERT and
# UPDATE paths. Nothing is committed.
DSN = os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL not set — real-data test skipped"
)

UNTRACK = """
SELECT s.nct_id FROM studies s
WHERE s.active_in_scope
  AND EXISTS (SELECT 1 FROM study_tracked_conditions st
              WHERE st.nct_id = s.nct_id AND lower(st.condition) = lower(%s))
  AND NOT EXISTS (
    SELECT 1 FROM study_tracked_conditions live
    JOIN tracked_conditions tc ON lower(tc.condition) = lower(live.condition)
    WHERE live.nct_id = s.nct_id AND live.untracked_at IS NULL)
"""

KEPT = """
SELECT count(DISTINCT st.nct_id) FROM study_tracked_conditions st
JOIN studies s ON s.nct_id = st.nct_id
WHERE lower(st.condition) = lower(%s) AND s.active_in_scope
  AND EXISTS (SELECT 1 FROM study_tracked_conditions live
              JOIN tracked_conditions tc ON lower(tc.condition) = lower(live.condition)
              WHERE live.nct_id = st.nct_id AND live.untracked_at IS NULL)
"""

UNATTRIBUTED = """
SELECT count(*) FROM studies s WHERE s.active_in_scope
  AND NOT EXISTS (SELECT 1 FROM study_tracked_conditions live
                  JOIN tracked_conditions tc ON lower(tc.condition) = lower(live.condition)
                  WHERE live.nct_id = s.nct_id AND live.untracked_at IS NULL)
"""


@pytest.fixture
def rolled_back():
    """A cursor on a transaction that is always rolled back, plus four real
    in-scope nct_ids to attribute."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT nct_id FROM studies WHERE active_in_scope LIMIT 4")
    ncts = [row[0] for row in cur.fetchall()]
    if len(ncts) < 4:
        pytest.skip("needs at least 4 in-scope trials on the live record")
    try:
        yield cur, ncts
    finally:
        conn.rollback()
        cur.close()
        conn.close()


@pytest.fixture
def watched(rolled_back):
    """Two conditions really on the registry, so the join back to it is
    exercised against live values rather than invented ones."""
    cur, ncts = rolled_back
    cur.execute("SELECT condition FROM tracked_conditions ORDER BY condition LIMIT 2")
    conditions = [row[0] for row in cur.fetchall()]
    if len(conditions) < 2:
        pytest.skip("needs two tracked conditions to test an overlap")
    return cur, ncts, conditions


class TestUntrackingIsExact:
    def test_a_trial_another_watched_condition_brings_in_keeps_being_watched(self, watched):
        """The whole reason attribution exists. Removing one condition must
        not untrack a trial the other one also returns."""
        cur, (a, b, c, d), (first, second) = watched
        cur.execute(
            "INSERT INTO study_tracked_conditions (nct_id, condition) VALUES "
            "(%s,%s),(%s,%s),(%s,%s),(%s,%s),(%s,%s)",
            (a, first, b, first, c, first, b, second, d, second),
        )
        cur.execute(
            "UPDATE study_tracked_conditions SET untracked_at = now() "
            "WHERE lower(condition) = lower(%s) AND untracked_at IS NULL",
            (first,),
        )

        cur.execute(UNTRACK, (first,))
        untracked = sorted(row[0] for row in cur.fetchall())
        cur.execute(KEPT, (first,))
        kept = cur.fetchone()[0]

        assert untracked == sorted([a, c]), (
            "only the trials no remaining watched condition brings in should "
            f"stop being watched; b={b} is also on '{second}'"
        )
        assert kept == 1

    def test_nothing_is_untracked_before_the_condition_is_stamped(self, watched):
        """Order is load-bearing: the untrack query reads "has no LIVE
        attribution", so the removed condition's rows must be stamped first.
        Unstamped, it would find nothing and the removal would silently be a
        no-op."""
        cur, (a, b, c, d), (first, _) = watched
        cur.execute(
            "INSERT INTO study_tracked_conditions (nct_id, condition) VALUES (%s,%s),(%s,%s)",
            (a, first, c, first),
        )
        cur.execute(UNTRACK, (first,))
        assert cur.fetchall() == []

    def test_the_match_is_case_insensitive_on_both_sides(self, watched):
        cur, (a, b, c, d), (first, _) = watched
        cur.execute(
            "INSERT INTO study_tracked_conditions (nct_id, condition) VALUES (%s,%s)",
            (a, first.upper()),
        )
        cur.execute(
            "UPDATE study_tracked_conditions SET untracked_at = now() "
            "WHERE lower(condition) = lower(%s) AND untracked_at IS NULL",
            (first.lower(),),
        )
        cur.execute(UNTRACK, (first.lower(),))
        assert [row[0] for row in cur.fetchall()] == [a]


class TestTheAttributionWriteItself:
    def test_re_adding_a_condition_revives_its_attribution(self, watched):
        """ON CONFLICT clears untracked_at, which is what makes a removal
        reversible: re-add the condition and the next monitor run puts the
        trial back on the watch rather than needing a repair script."""
        cur, (a, b, c, d), (first, _) = watched
        cur.execute(
            "INSERT INTO study_tracked_conditions (nct_id, condition, untracked_at) "
            "VALUES (%s, %s, now())",
            (a, first),
        )
        cur.execute(
            """
            INSERT INTO study_tracked_conditions (nct_id, condition)
            SELECT s.nct_id, %s FROM studies s WHERE s.nct_id = ANY(%s)
            ON CONFLICT (nct_id, condition) DO UPDATE
                SET last_matched_at = now(), untracked_at = NULL
            """,
            (first, [a]),
        )
        cur.execute(
            "SELECT untracked_at FROM study_tracked_conditions "
            "WHERE nct_id = %s AND condition = %s",
            (a, first),
        )
        assert cur.fetchone()[0] is None

    def test_an_unknown_nct_id_is_skipped_not_rejected(self, watched):
        """INSERT ... SELECT against studies rather than a values list: the
        ingest sends every id its query returned, and one not yet written
        would otherwise fail the whole statement on the foreign key."""
        cur, (a, b, c, d), (first, _) = watched
        cur.execute(
            """
            INSERT INTO study_tracked_conditions (nct_id, condition)
            SELECT s.nct_id, %s FROM studies s WHERE s.nct_id = ANY(%s)
            ON CONFLICT (nct_id, condition) DO UPDATE
                SET last_matched_at = now(), untracked_at = NULL
            """,
            (first, [a, "NCT00000000-not-real"]),
        )
        assert cur.rowcount == 1


class TestWhatTheRecordSaysAboutItself:
    def test_the_unattributed_count_is_real_and_bounded(self, rolled_back):
        """Reported on every removal as evidence the answer may be narrower
        than it looks. It must never exceed the trials in scope."""
        cur, _ = rolled_back
        cur.execute(UNATTRIBUTED)
        unattributed = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM studies WHERE active_in_scope")
        in_scope = cur.fetchone()[0]
        assert 0 <= unattributed <= in_scope
