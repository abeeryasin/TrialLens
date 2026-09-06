"""scripts/check_ops_health.py — the part that makes an alert reach a human.

`GET /ops/status` can say the autonomous half of TrialLens is broken. This
script is what goes and looks, from inside the 6-hourly workflow, and turns
a critical alert into a failed GitHub Actions run (which is the escalation:
GitHub then sends its own notification, with no email provider, no extra
secret, and nothing new that can itself break).

So the exit code IS the feature, and these tests are about the exit code.
The two mistakes worth guarding are opposite ones: staying green when
something is critically wrong, and going red for a warning until people stop
reading the red.

Free: no network, no database, no model — the HTTP client is stubbed.

Run: PYTHONPATH=. python3 -m pytest tests/test_ops_escalation.py -v
"""
import pytest

from scripts import check_ops_health


def status(alerts=(), **overrides):
    body = {
        "checked_at": "2026-09-06T12:00:00Z",
        "is_healthy": not any(a["severity"] == "critical" for a in alerts),
        "alerts": list(alerts),
        "jobs": [
            {
                "name": "monitor", "last_completed_at": "2026-09-06T11:00:00Z",
                "hours_since_completion": 1.0, "last_status": "completed",
                "last_work_done": 11416, "work_label": "trials checked",
                "window_hours": 168, "runs_in_window": 17,
                "expected_runs_in_window": 13, "failed_in_window": 0,
                "degraded_in_window": 0,
            },
        ],
        "budget": {
            "window_days": 30, "ceiling_usd": 1.0,
            "spent_usd": 0.1479, "remaining_usd": 0.8521,
        },
        "tracked_conditions": 2,
    }
    body.update(overrides)
    return body


def alert(severity="critical", code="job_stale"):
    return {
        "code": code, "severity": severity, "title": "something",
        "detail": "with its evidence", "job": "monitor",
    }


def stub_get(monkeypatch, body=None, error=None):
    def _get(path, params=None):
        assert path == "/ops/status"
        if error is not None:
            raise error
        return body

    monkeypatch.setattr(check_ops_health.api_client, "get", _get)


def test_a_critical_alert_fails_the_job(monkeypatch, capsys):
    stub_get(monkeypatch, status([alert("critical")]))
    assert check_ops_health.main() == 1
    assert "FAILING this job" in capsys.readouterr().out


def test_a_warning_alone_does_not_fail_the_job(monkeypatch, capsys):
    """A red build for something nobody must act on today is how red builds
    stop meaning anything."""
    stub_get(monkeypatch, status([alert("warning", "budget_exhausted")]))
    assert check_ops_health.main() == 0
    assert "1 warning(s)" in capsys.readouterr().out


def test_a_warning_beside_a_critical_still_fails(monkeypatch):
    stub_get(monkeypatch, status([alert("warning"), alert("critical")]))
    assert check_ops_health.main() == 1


def test_a_healthy_system_passes(monkeypatch, capsys):
    stub_get(monkeypatch, status())
    assert check_ops_health.main() == 0
    assert "Healthy." in capsys.readouterr().out


def test_an_unreachable_api_is_itself_critical(monkeypatch, capsys):
    """A health check that returns "fine, I couldn't check" is worse than
    none — a green tick attached to no evidence."""
    stub_get(monkeypatch, error=check_ops_health.api_client.ApiError("no route"))
    assert check_ops_health.main() == 1
    assert "CRITICAL" in capsys.readouterr().out


def test_the_printed_summary_names_the_evidence(monkeypatch, capsys):
    """The log is where whoever opens the failed run starts. It has to carry
    the numbers, not just the verdict."""
    stub_get(monkeypatch, status([alert("critical")]))
    check_ops_health.main()
    out = capsys.readouterr().out
    assert "11416 trials checked" in out
    assert "$0.1479 of $1.00" in out
    assert "with its evidence" in out


def test_a_missing_field_does_not_crash_the_checker(monkeypatch):
    """This runs `if: always()`, including after a failed ingest. It has to
    survive a partial or unexpected payload rather than replacing a real
    failure with its own traceback."""
    stub_get(monkeypatch, {"alerts": [], "jobs": [], "budget": {}})
    assert check_ops_health.main() == 0
