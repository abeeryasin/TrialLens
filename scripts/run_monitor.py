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

CONDITIONS_FILE = ROOT / "config" / "tracked_conditions.json"

# Step 7c budget and limits
PROSE_BUDGET_USD = 0.25  # Hard cap for this monitor run
PROSE_MAX_CALLS = 50  # Never interpret more than this per run


def run_prose_interpretation():
    """Step 7c: After ingestion, interpret prose amendments from last 6 hours.

    Runs in the scheduled job only, never in request path.
    Respects both cost and call limits to prevent runaway spend.
    Stores interpretations in study_changes.prose_interpretation (JSONB).
    """
    print("\nStep 7c: Interpreting prose amendments...", flush=True)
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        amendments = get_prose_amendments(conn, hours_ago=6)

        if not amendments:
            print("  No prose amendments detected in last 6 hours.", flush=True)
            conn.close()
            return 0.0

        print(f"  Found {len(amendments)} prose field changes — interpreting...", flush=True)
        results, spend = interpret_amendments_batch(
            amendments, max_cost_usd=PROSE_BUDGET_USD, max_calls=PROSE_MAX_CALLS
        )

        # Store interpretations
        cursor = conn.cursor()
        stored = 0
        for result in results:
            interp = result.get("prose_interpretation")
            if interp:
                cursor.execute(
                    """
                    UPDATE study_changes
                    SET prose_interpretation = %s
                    WHERE nct_id = %s AND field_name = %s
                    ORDER BY detected_at DESC LIMIT 1
                    """,
                    (json.dumps(interp), result["nct_id"], result["field_name"]),
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
        print(f"  ERROR in step 7c: {e}", flush=True)
        # Don't fail the whole monitor job if prose interpretation fails
        return 0.0


def main():
    conditions = json.loads(CONDITIONS_FILE.read_text())
    print(f"Monitor run starting for {len(conditions)} tracked condition(s): {conditions}", flush=True)
    for condition in conditions:
        print(f"\n--- {condition} ---", flush=True)
        run_ingest(condition)

    total_spend = run_prose_interpretation()
    print("\nMonitor run complete.", flush=True)
    if total_spend > 0:
        print(f"Total spend on step 7c: ${total_spend:.4f}", flush=True)


if __name__ == "__main__":
    main()
