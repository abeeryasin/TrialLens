"""The real Monitor job: run scripts/ingest.py's run_ingest() for every
condition in config/tracked_conditions.json.

This is what .github/workflows/monitor.yml actually calls on a schedule.
Tracking a therapeutic area is its own explicit action (see
docs/decisions.md, 2026-08-26, "Discover vs. Monitor") — this file, not an
ad-hoc CLI argument, is the real registry of what's being monitored.

After ingestion, step 7c interprets prose amendments (eligibility_criteria,
brief_summary, primary_outcomes) in the scheduled job, never in the request
path. Cost is capped and bounded by max_calls.

Run manually:
    .venv/bin/python scripts/run_monitor.py
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

from scripts.ingest import run_ingest  # noqa: E402
from api.prose_interpreter import get_prose_amendments, interpret_amendments_batch  # noqa: E402
from api.cost_budget import (  # noqa: E402
    ROLLING_CEILING_USD as PROSE_ROLLING_CEILING_USD,
    ROLLING_WINDOW_DAYS as PROSE_ROLLING_WINDOW_DAYS,
    rolling_budget_remaining,
)

CONDITIONS_FILE = ROOT / "config" / "tracked_conditions.json"

# Step 7c budget and limits.
PROSE_BUDGET_USD = 0.25  # Hard cap for ONE monitor run
PROSE_MAX_CALLS = 50  # Never interpret more than this per run

# The rolling ceiling itself (PROSE_ROLLING_CEILING_USD / _WINDOW_DAYS) and
# rolling_budget_remaining() moved to api/cost_budget.py on 2026-09-05: the
# weekly synthesis agent draws from the same $1.00/30-day window, not a
# second one, so the sum and the constant needed one home. Imported under
# their old names here so nothing else in this file, or in
# tests/test_prose_budget.py, has to change.
#
# A per-run cap says nothing about what a 6-hourly cron adds up to: 0.25 x 4
# runs x 30 days is ~$30/month against a project whose standing budget is a
# few dollars. This is the ceiling that actually binds. Spend is recorded on
# monitor_runs.prose_spend_usd, so the window survives restarts and is
# auditable after the fact rather than living in a variable.
#
# Sized against real volume, not the worst case: 42 prose amendments existed
# on file in total, at ~$0.004 each, so a genuinely busy month is cents. This
# leaves roughly 5-10x headroom and still fails long before the cron could
# quietly drain the account.


def create_run_record(conn):
    """Create a monitor_runs record and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO monitor_runs (status) VALUES ('running') RETURNING id"
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def update_run_record(conn, run_id, trials_checked, changes_detected,
                      prose_spend_usd=0.0, status="completed"):
    """Update a monitor_runs record with results."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE monitor_runs
            SET completed_at = now(), status = %s,
                trials_checked = %s, changes_detected = %s,
                prose_spend_usd = %s
            WHERE id = %s
            """,
            (status, trials_checked, changes_detected, prose_spend_usd, run_id),
        )
    conn.commit()


def run_prose_interpretation():
    """Step 7c: After ingestion, interpret prose amendments from last 6 hours.

    Runs in the scheduled job only, never in request path.
    Respects both cost and call limits to prevent runaway spend.
    Stores interpretations in study_changes.prose_interpretation (JSONB).
    """
    print("\nStep 7c: Interpreting prose amendments...", flush=True)
    # Declared OUTSIDE the try on purpose. The except below used to return a
    # flat 0.0, so a run that spent money and then failed while storing would
    # record nothing — a budget guard fed by an accounting hole. Whatever was
    # actually spent has to survive the exception and reach monitor_runs.
    spend = 0.0
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])

        remaining = rolling_budget_remaining(conn)
        if remaining <= 0:
            print(
                f"  SKIPPED: the last {PROSE_ROLLING_WINDOW_DAYS} days already "
                f"spent the ${PROSE_ROLLING_CEILING_USD:.2f} ceiling. No call "
                "made. Raise PROSE_ROLLING_CEILING_USD deliberately if this is "
                "wrong — it is not supposed to be routine.",
                flush=True,
            )
            conn.close()
            return 0.0

        amendments = get_prose_amendments(conn, hours_ago=6)

        if not amendments:
            print("  No prose amendments detected in last 6 hours.", flush=True)
            conn.close()
            return 0.0

        # The tighter of the two caps. Without the min(), a single run could
        # spend its full per-run budget straight through a ceiling that had
        # only cents left.
        budget = min(PROSE_BUDGET_USD, remaining)
        print(
            f"  Found {len(amendments)} prose field changes — interpreting "
            f"(budget ${budget:.4f}: ${remaining:.4f} left in the "
            f"{PROSE_ROLLING_WINDOW_DAYS}-day window)...",
            flush=True,
        )
        results, spend = interpret_amendments_batch(
            amendments, max_cost_usd=budget, max_calls=PROSE_MAX_CALLS
        )

        # Store interpretations
        cursor = conn.cursor()
        stored = 0
        for result in results:
            interp = result.get("prose_interpretation")
            if interp:
                # By primary key. The previous version was
                # `WHERE nct_id = %s AND field_name = %s ORDER BY detected_at
                # DESC LIMIT 1` — MySQL syntax that Postgres rejects outright
                # ("syntax error at or near ORDER"), swallowed by this
                # function's except clause and printed as a one-line ERROR.
                # It never stored a single row: step 7c's $0.168 bought
                # interpretations that were computed and then dropped.
                cursor.execute(
                    "UPDATE study_changes SET prose_interpretation = %s WHERE id = %s",
                    (json.dumps(interp), result["id"]),
                )
                if cursor.rowcount > 0:
                    stored += 1
        conn.commit()
        cursor.close()
        conn.close()

        print(
            f"  Step 7c complete: ${spend:.4f} spent, {len(results)} amendments "
            f"processed, {stored} interpretations stored",
            flush=True,
        )
        return spend
    except Exception as e:
        # Don't fail the whole monitor job if prose interpretation fails —
        # but DO return whatever was already spent. Returning 0.0 here is how
        # a guard silently stops guarding: the money leaves the account and
        # the rolling window never learns about it.
        print(f"  ERROR in step 7c after ${spend:.4f} spent: {e}", flush=True)
        return spend


def main():
    # Record this run
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    run_id = create_run_record(conn)
    conn.close()

    conditions = json.loads(CONDITIONS_FILE.read_text())
    print(f"Monitor run #{run_id} starting for {len(conditions)} tracked condition(s): {conditions}", flush=True)

    # Both figures come from run_ingest itself — the count POST
    # /studies/batch reported as it wrote. Counting study_changes rows by
    # `detected_at >= started_at` afterwards would have been close but not
    # true: it also sweeps in anything else writing in that window (a manual
    # ingest, a backfill) and files it under this run's id.
    total_trials_checked = 0
    total_changes = 0
    for condition in conditions:
        print(f"\n--- {condition} ---", flush=True)
        result = run_ingest(condition)
        total_trials_checked += len(result.nct_ids)
        total_changes += result.changes

    total_spend = run_prose_interpretation()

    # Close the run record. Nothing marks it 'failed' on the way out: if this
    # script dies earlier, the row simply stays 'running', /watch keeps
    # reading the previous completed run, and the gap grows until the alarm
    # fires — which is the honest outcome for a run that did not finish.
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    update_run_record(conn, run_id, total_trials_checked, total_changes,
                      prose_spend_usd=total_spend)
    conn.close()

    print(f"\nMonitor run #{run_id} complete.", flush=True)
    print(f"  Trials checked: {total_trials_checked}", flush=True)
    print(f"  Changes detected: {total_changes}", flush=True)
    if total_spend > 0:
        print(f"  Total spend on step 7c: ${total_spend:.4f}", flush=True)


if __name__ == "__main__":
    main()
