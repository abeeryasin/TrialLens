"""One-time backfill: populate the narrative/design fields added 2026-08-29
(brief_summary, lead_sponsor, real dates, interventions, primary_outcomes,
locations — see db/schema.sql) for every study ingested before those
columns existed.

No CT.gov re-fetch needed: every existing row already has its full raw API
response in raw_json (CLAUDE.md sec. 4 — store the raw record). This just
re-runs the same extract_fields() parser ingest.py already trusts, against
data already on disk.

Connects to Postgres directly rather than going through FastAPI/POST
/studies/batch on purpose: that endpoint's diff logic would log a
"field changed" entry in study_changes for every one of these ~11k rows
(NULL -> a real value), which isn't a real Monitor-detected change, just
this project starting to track more about a trial it already had — would
flood the real change log with same-day noise. A one-time structural
backfill is administrative work, the same category as
scripts/apply_schema.py and scripts/create_readonly_role.py, both of
which already connect directly for the same reason.

Uses a single bulk `UPDATE ... FROM (VALUES ...)` per batch (via
execute_values), not one UPDATE per row: a first version issued 200
separate round trips per batch against Neon's pooled endpoint and was on
pace for something like 90 minutes for ~11.5k rows. This version sends one
statement per batch instead.

Run manually, once:
    .venv/bin/python scripts/backfill_narrative_fields.py
"""
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

from ctgov_client import extract_fields  # noqa: E402

BATCH_SIZE = 1000

UPDATE_SQL = """
    UPDATE studies AS s SET
        brief_summary = v.brief_summary,
        lead_sponsor = v.lead_sponsor,
        start_date = v.start_date,
        primary_completion_date = v.primary_completion_date,
        completion_date = v.completion_date,
        interventions = v.interventions::jsonb,
        primary_outcomes = v.primary_outcomes::jsonb,
        locations = v.locations::jsonb
    FROM (VALUES %s) AS v(
        nct_id, brief_summary, lead_sponsor, start_date,
        primary_completion_date, completion_date,
        interventions, primary_outcomes, locations
    )
    WHERE s.nct_id = v.nct_id
"""


def main():
    database_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT nct_id, raw_json FROM studies WHERE brief_summary IS NULL")
        rows = cur.fetchall()

    print(f"{len(rows)} studies need backfilling.", flush=True)
    if not rows:
        conn.close()
        return

    updated = 0
    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch = rows[batch_start : batch_start + BATCH_SIZE]
        values = []
        for row in batch:
            fields = extract_fields(row["raw_json"])
            values.append((
                row["nct_id"],
                fields["brief_summary"],
                fields["lead_sponsor"],
                fields["start_date"],
                fields["primary_completion_date"],
                fields["completion_date"],
                psycopg2.extras.Json(fields["interventions"]),
                psycopg2.extras.Json(fields["primary_outcomes"]),
                psycopg2.extras.Json(fields["locations"]),
            ))

        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, UPDATE_SQL, values, page_size=BATCH_SIZE)
        conn.commit()
        updated += len(batch)
        print(f"  backfilled {updated}/{len(rows)}", flush=True)

    conn.close()
    print("Backfill complete.", flush=True)


if __name__ == "__main__":
    main()
