"""One-off: seed tracked_conditions from config/tracked_conditions.json.

Structural migration (the table) lives in db/schema.sql; this script is the
real data population, same split every other backfill_*.py in this
directory already follows. Idempotent — ON CONFLICT DO NOTHING means a
second run against a database that already has these rows changes nothing.

Run once, before deleting config/tracked_conditions.json:
    .venv/bin/python scripts/backfill_tracked_conditions.py
"""
import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

CONDITIONS_FILE = ROOT / "config" / "tracked_conditions.json"


def main():
    conditions = json.loads(CONDITIONS_FILE.read_text())
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with conn.cursor() as cur:
        for condition in conditions:
            cur.execute(
                "INSERT INTO tracked_conditions (condition) VALUES (%s) "
                "ON CONFLICT (condition) DO NOTHING",
                (condition,),
            )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT condition FROM tracked_conditions ORDER BY condition")
        print("tracked_conditions now holds:", [r[0] for r in cur.fetchall()])
    conn.close()


if __name__ == "__main__":
    main()
