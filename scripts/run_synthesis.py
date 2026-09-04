"""The weekly synthesis agent's scheduled job.

Runs once a week (.github/workflows/synthesis.yml), separately from
scripts/run_monitor.py's 6-hourly cadence — see docs/decisions.md,
2026-09-05, for why this is its own workflow rather than a day-of-week gate
inside monitor.yml: monitor.yml already runs three unrelated jobs on a
6-hour cycle, and folding a weekly, budget-gated, agent-driven step in
there means every 6-hour run pays a conditional check for something that
fires 1/28th as often, with a failure risking the run record /watch reads
last_checked_at from.

This script owns everything api/synthesis_agent.py does not: creating and
closing the synthesis_runs record, the shared rolling-budget preflight
(api/cost_budget.py — the SAME $1.00/30-day ceiling step 7c's prose
interpreter draws from), and writing accepted proposals to review_queue.
The agent module itself never touches the database.

Run manually:
    .venv/bin/python scripts/run_synthesis.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

from api.synthesis_agent import run_synthesis  # noqa: E402
from api.cost_budget import rolling_budget_remaining  # noqa: E402

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
WINDOW_DAYS = 7

# Per-run guardrails (docs/decisions.md, 2026-09-05). $0.20 sits comfortably
# above the ~$0.145 measured/costed estimate for a 10-turn run — the same
# over-estimate-on-purpose logic as api/prose_interpreter.py's
# COST_ESTIMATE_PER_CALL: a guard that stops early costs nothing, one that
# lets a run through past the ceiling is the real failure.
SYNTHESIS_BUDGET_USD = 0.20
SYNTHESIS_MAX_TURNS = 10


def create_run_record(conn):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO synthesis_runs (status) VALUES ('running') RETURNING id"
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def update_run_record(conn, run_id, proposals_created, spend_usd, status="completed"):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE synthesis_runs
            SET completed_at = now(), status = %s,
                proposals_created = %s, spend_usd = %s
            WHERE id = %s
            """,
            (status, proposals_created, spend_usd, run_id),
        )
    conn.commit()


def write_proposals(conn, run_id, proposals, window_since, window_until):
    """Write the agent's proposals to review_queue as 'pending'. The agent
    proposes; a human decides — nothing here sets status to anything else."""
    stored = 0
    with conn.cursor() as cur:
        for proposal in proposals:
            cur.execute(
                """
                INSERT INTO review_queue
                    (run_id, window_since, window_until, finding_type,
                     summary, evidence, confidence, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    run_id,
                    window_since,
                    window_until,
                    proposal["finding_type"],
                    proposal["summary"],
                    json.dumps({"evidence": proposal["evidence"]}),
                    proposal["confidence"],
                ),
            )
            stored += 1
    conn.commit()
    return stored


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    run_id = create_run_record(conn)
    print(f"Synthesis run #{run_id} starting.", flush=True)

    remaining = rolling_budget_remaining(conn)
    if remaining <= 0:
        print(
            "  SKIPPED: the shared 30-day ceiling is already spent. No call "
            "made. See api/cost_budget.py.",
            flush=True,
        )
        update_run_record(conn, run_id, proposals_created=0, spend_usd=0.0)
        conn.close()
        return

    budget = min(SYNTHESIS_BUDGET_USD, remaining)
    print(
        f"  Budget for this run: ${budget:.4f} (${remaining:.4f} left in the "
        "shared 30-day window)",
        flush=True,
    )

    window_until = datetime.now(timezone.utc)
    window_since = window_until - timedelta(days=WINDOW_DAYS)

    spend = 0.0
    proposals = []
    try:
        proposals, spend = run_synthesis(
            API_BASE_URL,
            days=WINDOW_DAYS,
            max_cost_usd=budget,
            max_turns=SYNTHESIS_MAX_TURNS,
        )
    except Exception as exc:
        # Whatever was spent before the failure must still reach the run
        # record — the same accounting-hole lesson step 7c's except clause
        # already paid for once (docs/decisions.md, 2026-09-03: an except
        # that returned 0.0 made a real failed spend invisible to the
        # ceiling that is supposed to bound it).
        print(f"  ERROR after ${spend:.4f} spent: {exc}", flush=True)
        update_run_record(
            conn, run_id, proposals_created=0, spend_usd=spend, status="failed"
        )
        conn.close()
        raise

    stored = write_proposals(conn, run_id, proposals, window_since, window_until)
    update_run_record(conn, run_id, proposals_created=stored, spend_usd=spend)
    conn.close()

    print(
        f"Synthesis run #{run_id} complete: ${spend:.4f} spent, "
        f"{stored} proposal(s) filed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
