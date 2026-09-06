"""GET /ops/status against the live database — does the SQL say what it claims?

tests/test_ops_endpoint.py runs the route against a fake connection that
ignores SQL, so it proves the assembly, the rules and the response model and
nothing at all about the queries. This file runs the real endpoint over HTTP
against the real database and checks each figure against an independent
query, plus the one cross-surface invariant that matters.

**The invariant: /ops/status and /watch must not disagree about when the
monitor last ran.** Both read `monitor_runs`; they are read by different
people for different reasons (a researcher asking "is the watch live?", an
operator asking "are the jobs healthy?"), and two surfaces quoting different
last-check times would leave nobody able to say which is true.

Free — read-only, no model, no network beyond Neon. Skipped cleanly when
DATABASE_URL_READONLY isn't set, so CI without credentials stays green;
these run in monitor.yml, on the data's schedule.

Run: PYTHONPATH=. python3 -m pytest tests/test_ops_real_data.py -v
"""
import os

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from api.main import app

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

DSN = os.getenv("DATABASE_URL_READONLY")
pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set — real-data test skipped"
)


@pytest.fixture(scope="module")
def status():
    with TestClient(app) as client:
        response = client.get("/ops/status")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(DSN)
    yield conn
    conn.close()


def one(conn, sql, params=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def job_named(status, name):
    return next(j for j in status["jobs"] if j["name"] == name)


def test_the_endpoint_answers_at_all_against_the_real_schema(status):
    """Covers the migration as much as the route: the read-only role has to
    be able to SELECT the `error` column added on 2026-09-06, and a
    table-level grant is the only reason it can."""
    assert {j["name"] for j in status["jobs"]} == {"monitor", "synthesis"}


def test_the_run_counts_match_a_direct_count(status, db):
    job = job_named(status, "monitor")
    row = one(
        db,
        """
        SELECT count(*) AS runs
        FROM monitor_runs
        WHERE started_at > now() - make_interval(hours => %s)
        """,
        (job["window_hours"],),
    )
    assert job["runs_in_window"] == row["runs"]


def test_the_last_completed_run_is_the_last_completed_run(status, db):
    job = job_named(status, "monitor")
    row = one(
        db,
        """
        SELECT completed_at, trials_checked
        FROM monitor_runs
        WHERE status = 'completed'
        ORDER BY completed_at DESC LIMIT 1
        """,
    )
    if row is None:
        pytest.skip("no completed monitor run on file yet")
    assert job["last_completed_at"].startswith(
        row["completed_at"].isoformat()[:19]
    )
    assert job["last_work_done"] == row["trials_checked"]


def test_ops_and_watch_agree_on_when_the_monitor_last_ran(status):
    """The cross-surface invariant. Different readers, same fact."""
    with TestClient(app) as client:
        watch = client.get("/watch").json()
    if watch["last_checked_at"] is None:
        pytest.skip("no completed run for either surface to read")
    assert job_named(status, "monitor")["last_completed_at"] == watch["last_checked_at"]


def test_the_spend_figure_is_the_shared_window_not_one_job(status, db):
    """Both paid callers draw from one ceiling (api/cost_budget.py). Reading
    only monitor_runs here would report the synthesis agent's money as free."""
    row = one(
        db,
        """
        SELECT
            coalesce((SELECT sum(prose_spend_usd) FROM monitor_runs
                      WHERE started_at > now() - interval '30 days'), 0)
          + coalesce((SELECT sum(spend_usd) FROM synthesis_runs
                      WHERE started_at > now() - interval '30 days'), 0)
            AS spent
        """,
    )
    assert status["budget"]["spent_usd"] == pytest.approx(float(row["spent"]), abs=1e-4)


def test_the_tracking_registry_count_is_real(status, db):
    row = one(db, "SELECT count(*) AS n FROM tracked_conditions")
    assert status["tracked_conditions"] == row["n"]
    # Not an assertion about health — a registry can legitimately be empty
    # for a moment — but if it IS empty, the endpoint must be saying so.
    if row["n"] == 0:
        assert any(a["code"] == "no_tracked_conditions" for a in status["alerts"])


def test_every_alert_carries_its_evidence(status):
    """Sec. 3 holds on live data, not just in the unit tests: no alert may be
    a bare conclusion."""
    for alert in status["alerts"]:
        assert alert["detail"].strip(), alert
        assert alert["severity"] in ("critical", "warning"), alert


def test_no_stored_error_reaches_the_response_with_a_credential_in_it(status):
    """The live version of the scrubbing test. If a real run has recorded an
    error, whatever is in it must not contain a password."""
    secrets = [
        os.environ.get("DATABASE_URL", ""),
        os.environ.get("DATABASE_URL_READONLY", ""),
        os.environ.get("ANTHROPIC_API_KEY", ""),
    ]
    for job in status["jobs"]:
        text = job.get("last_error") or ""
        for secret in secrets:
            if secret:
                assert secret not in text
