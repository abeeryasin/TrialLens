"""One-time backfill of studies.enrollment_type from the already-stored raw_json.

No ClinicalTrials.gov re-fetch needed — the raw record was kept for exactly
this kind of case (CLAUDE.md sec. 4).

Connects to Postgres directly rather than through POST /studies/batch, for
the same reason scripts/backfill_narrative_fields.py does: that endpoint's
diff logic would log a "changed" entry for all ~11k rows (NULL -> real
value), which isn't a real Monitor-detected change and would flood
study_changes with noise. A one-time structural backfill is administrative
work, the same category as apply_schema.py.

Run:  .venv/bin/python scripts/backfill_enrollment_type.py
"""
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

BATCH_SIZE = 1000

conn = psycopg2.connect(os.environ["DATABASE_URL"])

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute(
        """
        SELECT nct_id,
               raw_json->'protocolSection'->'designModule'->'enrollmentInfo'->>'type' AS enrollment_type
        FROM studies
        WHERE enrollment_type IS NULL
        """
    )
    rows = [(r["nct_id"], r["enrollment_type"]) for r in cur.fetchall() if r["enrollment_type"]]

print(f"{len(rows)} rows to backfill", flush=True)

written = 0
for start in range(0, len(rows), BATCH_SIZE):
    batch = rows[start : start + BATCH_SIZE]
    with conn.cursor() as cur:
        # One bulk UPDATE ... FROM (VALUES ...) per batch, not one UPDATE per
        # row: the per-row version was on pace for ~90 minutes against Neon's
        # pooled endpoint last time (docs/decisions.md, 2026-08-29).
        psycopg2.extras.execute_values(
            cur,
            """
            UPDATE studies SET enrollment_type = data.enrollment_type
            FROM (VALUES %s) AS data (nct_id, enrollment_type)
            WHERE studies.nct_id = data.nct_id
            """,
            batch,
        )
        written += cur.rowcount
    conn.commit()
    print(f"  {written}/{len(rows)}", flush=True)

with conn.cursor() as cur:
    cur.execute("SELECT enrollment_type, count(*) FROM studies GROUP BY 1 ORDER BY 2 DESC")
    print("\nfinal distribution:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

conn.close()
