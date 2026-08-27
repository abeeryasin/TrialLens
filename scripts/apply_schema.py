"""Apply db/schema.sql to the database pointed to by DATABASE_URL.

Run manually whenever schema.sql changes:
    .venv/bin/python scripts/apply_schema.py
"""
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

database_url = os.environ["DATABASE_URL"]
schema_sql = (ROOT / "db" / "schema.sql").read_text()

with psycopg2.connect(database_url) as conn:
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()

print("Schema applied.")
