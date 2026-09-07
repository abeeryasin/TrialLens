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
from api.safe_errors import describe  # noqa: E402

import requests  # noqa: E402

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
WINDOW_DAYS = 7

# How many COMPLETE prior windows the record must reach back over before
# there is anything for the agent to compare this week against.
#
# Not a tuned number: it is read straight off the agent's own system prompt
# — "Compare the current window against at least 2-3 prior weeks before
# calling anything a pattern. One week's number alone is never enough."
# If the record cannot supply two prior weeks, the agent is being asked a
# question it has already been told it must not answer, and the outcome is
# determined before any money is spent.
#
# This is not hypothetical. The first real run (2026-09-05) cost $0.1099 and
# filed zero proposals for exactly this reason: monitoring began 2026-08-28,
# so weeks_ago=2,3,4 all returned nothing. That was the agent behaving
# correctly and the spend being wasted anyway. CLAUDE.md sec. 5 —
# deterministic first: "has the record got two prior weeks in it" is a
# database question, not a judgment.
MIN_PRIOR_WINDOWS = 2

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


def update_run_record(conn, run_id, proposals_created, spend_usd,
                      status="completed", error=None, skipped_reason=None):
    """Close the run record, including why it ended badly if it did.

    `error` added in step 11 (2026-09-06). This script already re-raised on
    failure so GitHub Actions would go red, but a red workflow is a
    notification, not a record: the run row said 'failed' with no reason, and
    the log holding the reason expires. GET /ops/status reads this column.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE synthesis_runs
            SET completed_at = now(), status = %s,
                proposals_created = %s, spend_usd = %s, error = %s,
                skipped_reason = %s
            WHERE id = %s
            """,
            (status, proposals_created, spend_usd, error, skipped_reason,
             run_id),
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


def prior_windows_available(api_base_url, days, window_since):
    """How many complete prior windows the record actually covers.

    Reads GET /investigate's own `recording_since` — the earliest change on
    file — through the API rather than the database, because the API is the
    only door (sec. 5) and this script already talks to it. Returns None
    when the question cannot be answered, which is deliberately NOT treated
    as "skip": refusing to spend on the strength of a failed lookup would
    turn a transient API blip into a silently skipped week, and a skipped
    week is the failure mode step 11 was built to make visible.
    """
    try:
        response = requests.get(
            f"{api_base_url}/investigate", params={"days": 1}, timeout=30
        )
        response.raise_for_status()
        recording_since = response.json()["window"]["recording_since"]
    except Exception:  # noqa: BLE001 — a failed lookup must not block the run
        return None
    if not recording_since:
        return 0
    earliest = datetime.fromisoformat(recording_since.replace("Z", "+00:00"))
    return int((window_since - earliest).total_seconds() // (days * 86400))


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
        # Still writes NO `error` — a ceiling that refuses a call is the
        # guard working, not a fault, and filing it as an error would report
        # a degraded run every week the guard did its job.
        #
        # But it DOES write skipped_reason (2026-09-07). Unlike the monitor,
        # there is no "nothing to do" case here: the weekly agent always has
        # a window to read, so a budget skip always means a real week went
        # unexamined. Without this the run closes as 'completed' with zero
        # proposals — identical to a week the agent looked at and correctly
        # found nothing, which is the one reading it must never be confused
        # with.
        update_run_record(
            conn, run_id, proposals_created=0, spend_usd=0.0,
            skipped_reason=(
                "budget: the weekly synthesis run made no call — the shared "
                "30-day ceiling is spent, so this week was never examined"
            ),
        )
        conn.close()
        return

    window_until = datetime.now(timezone.utc)
    window_since = window_until - timedelta(days=WINDOW_DAYS)

    # The second precondition, added 2026-09-07. The budget check above asks
    # "may we spend?"; this one asks "is there anything to buy?".
    prior = prior_windows_available(API_BASE_URL, WINDOW_DAYS, window_since)
    if prior is not None and prior < MIN_PRIOR_WINDOWS:
        print(
            f"  SKIPPED: the record covers {prior} complete prior "
            f"{'window' if prior == 1 else 'windows'}, and the agent needs "
            f"{MIN_PRIOR_WINDOWS} to call anything a trend. No call made.",
            flush=True,
        )
        # skipped_reason, not error: a run that declines to buy a
        # foregone conclusion is the guard working. But it must NOT close as
        # a plain 'completed' with zero proposals either — that reads
        # identically to a week the agent examined and found quiet, which is
        # the one thing this record must never blur (see the budget skip
        # above, same rule).
        update_run_record(
            conn, run_id, proposals_created=0, spend_usd=0.0,
            skipped_reason=(
                f"history: the record covers {prior} complete prior "
                f"{'window' if prior == 1 else 'windows'} of "
                f"{WINDOW_DAYS} days; the agent needs {MIN_PRIOR_WINDOWS} "
                "before a week's numbers can be compared against anything"
            ),
        )
        conn.close()
        return

    budget = min(SYNTHESIS_BUDGET_USD, remaining)
    print(
        f"  Budget for this run: ${budget:.4f} (${remaining:.4f} left in the "
        "shared 30-day window)",
        flush=True,
    )

    # run_synthesis RETURNS its error rather than raising it, so whatever was
    # spent before a failure reaches the record. The previous shape — a
    # `try` around `proposals, spend = ...` with an `except` that logged
    # `spend` — could not work: the tuple never binds when the callee raises,
    # so `spend` stayed 0.0. On 2026-09-07 that recorded "$0.0000 spent" for
    # a run that had made five paid calls, hiding real money from the
    # rolling ceiling meant to bound it. The comment there claimed the
    # opposite of what the code did.
    proposals, spend, error = run_synthesis(
        API_BASE_URL,
        days=WINDOW_DAYS,
        max_cost_usd=budget,
        max_turns=SYNTHESIS_MAX_TURNS,
    )

    if error:
        # The spend is banked FIRST, then the job goes red. Both matter:
        # GitHub's own notification is this project's escalation channel
        # (scripts/check_ops_health.py), and the ceiling only bounds what it
        # can see. `error` is already scrubbed (api/safe_errors.describe) —
        # this row is read back through GET /ops/status onto a page, and this
        # process holds both a database URL and an API key.
        print(f"  ERROR after ${spend:.4f} spent: {error}", flush=True)
        stored = write_proposals(conn, run_id, proposals, window_since, window_until)
        if stored:
            # Proposals filed before the failure are real work and are kept.
            # Discarding them would spend the money twice.
            print(f"  Kept {stored} proposal(s) filed before the failure.", flush=True)
        update_run_record(
            conn, run_id, proposals_created=stored, spend_usd=spend,
            status="failed", error=error,
        )
        conn.close()
        sys.exit(1)

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
