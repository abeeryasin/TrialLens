"""Per-request Postgres connections, two roles: one SELECT-only, one full-privilege.

DATABASE_URL points at Neon's "-pooler" endpoint, which is already a
PgBouncer pool on Neon's side. Layering our own long-lived client-side
pool on top of that caused a real failure during development: an idle
connection our pool held open got silently dropped server-side, and
psycopg2 didn't find out until the next query tried to use it
(OperationalError: server closed the connection unexpectedly). Opening a
fresh connection per request avoids that — Neon's pooler is built for
exactly this pattern.

Every GET route depends on get_readonly_db — backed by the
trial_lens_reader Postgres role (see scripts/create_readonly_role.py),
which cannot write no matter what the route code does. Only the write
route (POST /studies/batch) uses get_db, the full-privilege connection.
"""
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")


def get_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_readonly_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL_READONLY"])
    try:
        yield conn
    finally:
        conn.close()
