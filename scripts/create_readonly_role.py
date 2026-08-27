"""Create (or reset) a SELECT-only Postgres role for FastAPI's read path.

This is the real enforcement layer behind "read-only access": even if
application code has a bug, Postgres itself refuses any write from this
role. Run manually whenever the role needs to be (re)created:

    .venv/bin/python scripts/create_readonly_role.py

Writes/updates DATABASE_URL_READONLY in .env.local. Safe to re-run —
resets the password and re-applies grants each time.
"""
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_LOCAL = ROOT / ".env.local"
load_dotenv(ENV_LOCAL)
load_dotenv(ROOT / ".env")

ROLE_NAME = "trial_lens_reader"

admin_url = os.environ["DATABASE_URL"]
parsed = urlparse(admin_url)
db_name = parsed.path.lstrip("/")
password = secrets.token_urlsafe(24)

conn = psycopg2.connect(admin_url)
conn.autocommit = True  # CREATE ROLE can't run inside a transaction block on Neon
try:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_NAME,))
        exists = cur.fetchone() is not None
        if exists:
            cur.execute(f'ALTER ROLE "{ROLE_NAME}" WITH LOGIN PASSWORD %s', (password,))
            print(f"Reset password for existing role: {ROLE_NAME}")
        else:
            cur.execute(f'CREATE ROLE "{ROLE_NAME}" WITH LOGIN PASSWORD %s', (password,))
            print(f"Created role: {ROLE_NAME}")

        cur.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO "{ROLE_NAME}"')
        cur.execute(f'GRANT USAGE ON SCHEMA public TO "{ROLE_NAME}"')
        cur.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{ROLE_NAME}"')
        cur.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "{ROLE_NAME}"'
        )
        print("Granted: CONNECT, USAGE, SELECT-only on all current + future tables in public.")
finally:
    conn.close()

readonly_url = parsed._replace(netloc=f"{ROLE_NAME}:{password}@{parsed.hostname}").geturl()
if parsed.port:
    readonly_url = parsed._replace(
        netloc=f"{ROLE_NAME}:{password}@{parsed.hostname}:{parsed.port}"
    ).geturl()

lines = ENV_LOCAL.read_text().splitlines() if ENV_LOCAL.exists() else []
lines = [l for l in lines if not l.startswith("DATABASE_URL_READONLY=")]
lines.append(f"DATABASE_URL_READONLY={readonly_url}")
ENV_LOCAL.write_text("\n".join(lines) + "\n")
print(f"Wrote DATABASE_URL_READONLY to {ENV_LOCAL}")
