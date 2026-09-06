"""GET /ops/status over HTTP, plus the alert rules on their own.

Two halves, deliberately:

  * The HTTP half goes through TestClient against the fake connection
    (tests/conftest.py) — routing, assembly and the response model. The
    fake ignores SQL, so nothing here says the queries are right; that is
    what tests/test_ops_real_data.py is for.
  * The `build_alerts` half calls a plain function with plain values. The
    judgment about what counts as broken does not need a database, and
    faking one to test it would only hide the rules behind scaffolding.

Every alert rule below is a failure this project has actually had — see
api/ops.py's module docstring for which incident each one comes from.

Free: no network, no database, no model.

Run: PYTHONPATH=. python3 -m pytest tests/test_ops_endpoint.py -v
"""
from datetime import datetime, timedelta, timezone

from api.ops import CRITICAL, WARNING, build_alerts
from api.schemas import OpsBudget, OpsJob

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# HTTP: the route, its assembly, and the response model.
# --------------------------------------------------------------------------

def run_row(**overrides):
    row = {
        "id": 17,
        "status": "completed",
        "error": None,
        "started_at": NOW - timedelta(hours=2),
        "completed_at": NOW - timedelta(hours=1, minutes=50),
        "work_done": 11416,
    }
    row.update(overrides)
    return row


def counts_row(**overrides):
    row = {
        "last_completed_at": NOW - timedelta(hours=1, minutes=50),
        "first_started_at": NOW - timedelta(days=4),
        "last_work_done": 11416,
        "runs_in_window": 17,
        "failed_in_window": 0,
        "degraded_in_window": 0,
        "stuck_runs": 0,
    }
    row.update(overrides)
    return row


def healthy_results(monitor_recent=None, monitor_counts=None,
                    synthesis_recent=None, synthesis_counts=None,
                    spend=0.1479, conditions=(("breast cancer",), ("melanoma",))):
    """The seven results the route draws, in the order it draws them."""
    return [
        [{"now": NOW}],
        monitor_recent if monitor_recent is not None else [run_row()],
        [monitor_counts or counts_row()],
        synthesis_recent if synthesis_recent is not None else [
            run_row(id=1, work_done=0)
        ],
        [synthesis_counts or counts_row(last_work_done=0, runs_in_window=1)],
        [(spend,)],
        list(conditions),
    ]


def test_a_healthy_system_reports_healthy_with_no_alerts(api):
    body = api(healthy_results()).get("/ops/status").json()
    assert body["is_healthy"] is True
    assert body["alerts"] == []
    assert [j["name"] for j in body["jobs"]] == ["monitor", "synthesis"]
    assert body["tracked_conditions"] == 2


def test_both_scheduled_jobs_are_covered_not_just_the_monitor(api):
    """GET /watch sees the monitor only. The synthesis agent spends money on
    its own schedule and had no health surface at all before this."""
    body = api(healthy_results()).get("/ops/status").json()
    names = {j["name"] for j in body["jobs"]}
    assert names == {"monitor", "synthesis"}


def test_the_budget_is_reported_as_a_real_position(api):
    body = api(healthy_results(spend=0.1479)).get("/ops/status").json()
    budget = body["budget"]
    assert budget["spent_usd"] == 0.1479
    assert budget["remaining_usd"] == 0.8521
    assert budget["ceiling_usd"] == 1.0
    assert budget["window_days"] == 30


def test_an_error_recorded_on_a_completed_run_is_surfaced(api):
    """The degraded state — the one that used to be invisible."""
    results = healthy_results(
        monitor_recent=[run_row(error="RuntimeError: prose call failed")],
        monitor_counts=counts_row(degraded_in_window=1),
    )
    body = api(results).get("/ops/status").json()
    monitor = body["jobs"][0]
    assert monitor["last_status"] == "completed"
    assert "prose call failed" in monitor["last_error"]
    assert monitor["degraded_in_window"] == 1
    assert any(a["code"] == "run_degraded" for a in body["alerts"])


def test_a_credential_in_a_stored_error_is_scrubbed_on_the_way_out(api, monkeypatch):
    """Defence in depth. The write side scrubs (api/safe_errors.py), but this
    column is read back onto a page, and a row could predate that guard."""
    dsn = "postgresql://neondb_owner:SUPERSECRET@ep-x.neon.tech/neondb"
    monkeypatch.setenv("DATABASE_URL", dsn)
    results = healthy_results(
        monitor_recent=[run_row(error=f"OperationalError: {dsn} refused")]
    )
    body = api(results).get("/ops/status").json()
    assert "SUPERSECRET" not in body["jobs"][0]["last_error"]


def test_the_cadence_denominator_is_measured_not_assumed(api):
    """A job younger than its own observation window must not be scored
    against history that never existed."""
    results = healthy_results(
        synthesis_counts=counts_row(
            last_work_done=0,
            runs_in_window=1,
            first_started_at=NOW - timedelta(hours=27),
        ),
    )
    body = api(results).get("/ops/status").json()
    synthesis = body["jobs"][1]
    assert synthesis["runs_in_window"] == 1
    # 27h on a 168h cadence is one run due, not four.
    assert synthesis["expected_runs_in_window"] == 1


def test_a_table_with_no_runs_at_all_does_not_crash(api):
    """An empty run table is a real state — it is what a fresh deploy looks
    like, and what a wiped table looks like."""
    results = healthy_results(
        monitor_recent=[],
        monitor_counts=counts_row(
            last_completed_at=None, first_started_at=None, last_work_done=None,
            runs_in_window=0,
        ),
    )
    body = api(results).get("/ops/status").json()
    monitor = body["jobs"][0]
    assert monitor["last_status"] is None
    assert monitor["expected_runs_in_window"] == 0
    assert body["is_healthy"] is False
    assert any(a["code"] == "job_never_completed" for a in body["alerts"])


# --------------------------------------------------------------------------
# The rules themselves.
# --------------------------------------------------------------------------

def job(name="monitor", **overrides):
    fields = {
        "name": name,
        "cadence_hours": 6 if name == "monitor" else 168,
        "stale_after_hours": 12 if name == "monitor" else 336,
        "hours_since_completion": 1.5,
        "last_status": "completed",
        "last_work_done": 11416 if name == "monitor" else 0,
        "work_label": "trials checked" if name == "monitor" else "proposals filed",
        "consecutive_failures": 0,
        "window_hours": 168 if name == "monitor" else 672,
        "runs_in_window": 17,
        "expected_runs_in_window": 13,
        "failed_in_window": 0,
        "degraded_in_window": 0,
        "stuck_runs": 0,
    }
    fields.update(overrides)
    return OpsJob(**fields)


def budget(spent=0.1479):
    return OpsBudget(
        window_days=30, ceiling_usd=1.0, spent_usd=spent,
        remaining_usd=max(0.0, 1.0 - spent), share_used=spent,
    )


def codes(alerts):
    return [a.code for a in alerts]


def both_jobs(**monitor_overrides):
    return [job("monitor", **monitor_overrides), job("synthesis")]


def test_nothing_fires_when_everything_is_fine():
    assert build_alerts(both_jobs(), budget(), ["breast cancer"]) == []


def test_a_stale_monitor_is_critical():
    alerts = build_alerts(
        both_jobs(hours_since_completion=19.4), budget(), ["breast cancer"]
    )
    stale = [a for a in alerts if a.code == "job_stale"]
    assert stale and stale[0].severity == CRITICAL
    # Sec. 3: the evidence, not just the conclusion.
    assert "19.4" in stale[0].detail and "6h" in stale[0].detail


def test_a_stale_synthesis_agent_is_only_a_warning():
    """A missed week of advisory output is not the watch going dark. Wiring
    both to 'critical' is how an alarm stops meaning anything."""
    alerts = build_alerts(
        [job("monitor"), job("synthesis", hours_since_completion=400)],
        budget(), ["breast cancer"],
    )
    stale = [a for a in alerts if a.code == "job_stale"]
    assert stale and stale[0].severity == WARNING


def test_one_late_run_is_not_an_alarm():
    """7 hours on a 6-hour cadence is a hiccup — GitHub's schedules are
    best-effort. The threshold is two consecutive misses (api/watch.py)."""
    assert build_alerts(
        both_jobs(hours_since_completion=7.0), budget(), ["breast cancer"]
    ) == []


def test_a_monitor_run_that_checked_nothing_is_critical():
    """The failure that looks most like health: green run, zero work."""
    alerts = build_alerts(both_jobs(last_work_done=0), budget(), ["breast cancer"])
    assert "job_did_nothing" in codes(alerts)
    assert not any(a.severity != CRITICAL for a in alerts if a.code == "job_did_nothing")


def test_a_synthesis_run_that_filed_nothing_is_NOT_a_fault():
    """Zero proposals is a legitimate answer — the first real run filed zero
    because it had one week of history to compare against (2026-09-05). An
    agent that finds nothing and says so is working."""
    alerts = build_alerts(
        [job("monitor"), job("synthesis", last_work_done=0)],
        budget(), ["breast cancer"],
    )
    assert "job_did_nothing" not in codes(alerts)


def test_an_empty_tracking_registry_is_critical():
    """2026-09-05: a `LIKE '__%'` cleanup emptied tracked_conditions. The
    cron would have kept completing successfully while watching nothing."""
    alerts = build_alerts(both_jobs(), budget(), [])
    assert "no_tracked_conditions" in codes(alerts)


def test_consecutive_failures_are_critical_and_name_the_error():
    alerts = build_alerts(
        both_jobs(consecutive_failures=3, last_status="failed",
                  last_error="OperationalError: server closed the connection"),
        budget(), ["breast cancer"],
    )
    failing = [a for a in alerts if a.code == "job_failing"]
    assert failing and failing[0].severity == CRITICAL
    assert "server closed the connection" in failing[0].detail


def test_a_stuck_run_is_reported_but_does_not_cry_wolf():
    """run_monitor.py deliberately leaves a dying run's row as 'running'.
    That is honest, and until now invisible. It is a warning: staleness is
    what escalates if the job has genuinely stopped."""
    alerts = build_alerts(both_jobs(stuck_runs=1), budget(), ["breast cancer"])
    stuck = [a for a in alerts if a.code == "run_stuck"]
    assert stuck and stuck[0].severity == WARNING


def test_an_exhausted_budget_is_a_warning_not_a_failure():
    """The ceiling refusing a call is the guard working."""
    alerts = build_alerts(both_jobs(), budget(spent=1.0), ["breast cancer"])
    spent = [a for a in alerts if a.code == "budget_exhausted"]
    assert spent and spent[0].severity == WARNING


def test_criticals_are_listed_first():
    alerts = build_alerts(
        both_jobs(stuck_runs=1, hours_since_completion=19.4),
        budget(spent=1.0), [],
    )
    severities = [a.severity for a in alerts]
    assert severities == sorted(severities, key=lambda s: 0 if s == CRITICAL else 1)


def test_alerts_are_a_list_of_named_conditions_never_a_score():
    """Sec. 3, and the whole reason step 7's ranking layer was removed. Two
    unrelated problems must stay two facts, not one number."""
    alerts = build_alerts(both_jobs(stuck_runs=1), budget(spent=1.0), [])
    assert len(alerts) == 3
    assert set(codes(alerts)) == {"run_stuck", "budget_exhausted", "no_tracked_conditions"}
    for alert in alerts:
        assert alert.detail and alert.title
