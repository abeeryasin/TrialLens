"""Populate studies.has_results from raw_json, without refetching anything.

`hasResults` sits at the TOP level of the CT.gov response, not inside
protocolSection, which is why the original parser missed it — every module
it read was one level down. The column was added 2026-09-02.

No network call is needed: raw_json already holds the untouched response
for every stored trial, which is exactly what CLAUDE.md sec. 4 keeps it
for. This is the first time that decision has paid for itself — a field
nobody thought to normalize was recoverable for 11,518 trials from data
already on disk.

**Backfilled values are deliberately NOT written to study_changes.** Doing
so would log 1,056 "results were posted" amendments dated today, for trials
that published their results months or years ago — a false claim about when
something happened (sec. 2). The backfill establishes the baseline; only
future transitions detected by the real diff are amendments.

Read-mostly and idempotent: re-running it changes nothing once values match.

    PYTHONPATH=. .venv/bin/python scripts/backfill_has_results.py
    PYTHONPATH=. .venv/bin/python scripts/backfill_has_results.py --apply
"""
import os
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env.local")
except ImportError:
    pass


def main() -> int:
    apply = "--apply" in sys.argv
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set.")
        return 1

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE has_results IS NULL) AS unset,
                       count(*) FILTER (WHERE raw_json->>'hasResults' = 'true') AS truthy,
                       count(*) FILTER (WHERE raw_json->>'hasResults' IS NULL) AS absent,
                       count(*) AS total
                FROM studies
                """
            )
            unset, truthy, absent, total = cur.fetchone()
            print(f"{total:,} studies · has_results unset on {unset:,}")
            print(f"raw_json says results posted for {truthy:,}; "
                  f"{absent:,} records carry no hasResults key at all")

            if not apply:
                print("\nDry run. Re-run with --apply to write.")
                return 0

            # Only where the stored value actually disagrees, so a re-run is
            # a no-op rather than a full-table rewrite.
            cur.execute(
                """
                UPDATE studies
                SET has_results = (raw_json->>'hasResults')::boolean
                WHERE raw_json->>'hasResults' IS NOT NULL
                  AND has_results IS DISTINCT FROM (raw_json->>'hasResults')::boolean
                """
            )
            written = cur.rowcount
            conn.commit()
            print(f"\nWrote has_results for {written:,} studies.")

            cur.execute(
                "SELECT has_results, count(*) FROM studies GROUP BY 1 ORDER BY 2 DESC"
            )
            for value, n in cur.fetchall():
                print(f"  has_results={value!s:<6} {n:,}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
