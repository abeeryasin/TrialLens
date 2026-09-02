"""Seed monitor_runs with the one run we have real evidence of (step 7b
direction 3, 2026-09-02).

The table ships empty, and an empty run table reads as "no check has ever
run" — which fires the alarm on a watch that is actually healthy. That was
the reason direction 3 was deferred in the first place (docs/roadmap.md).

The way out is that the proxy it replaces IS evidence: POST /studies/
reconcile-scope stamps last_matched_at on every in-scope trial at the end of
every run, so max(last_matched_at) is a real completion time for a real run.
This records that one run explicitly, then the cron takes over.

changes_detected stays NULL: nothing on file says how many changes THAT run
found, and writing a number would invent one (CLAUDE.md sec. 2).

Run once:
    .venv/bin/python scripts/backfill_monitor_runs.py
"""
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM monitor_runs")
        if cur.fetchone()[0]:
            print("monitor_runs already has rows — nothing to backfill.")
            raise SystemExit(0)

        cur.execute(
            """
            INSERT INTO monitor_runs
                (started_at, completed_at, status, trials_checked, changes_detected)
            SELECT max(last_matched_at), max(last_matched_at), 'completed',
                   count(*) FILTER (WHERE active_in_scope), NULL
            FROM studies
            HAVING max(last_matched_at) IS NOT NULL
            RETURNING id, completed_at, trials_checked
            """
        )
        row = cur.fetchone()

    if row is None:
        print("No last_matched_at on record — nothing to backfill.")
    else:
        print(f"Seeded run #{row[0]}: completed {row[1]}, {row[2]:,} trials in scope.")
