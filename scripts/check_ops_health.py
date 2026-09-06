"""Escalation: turn a critical ops alert into something that reaches a human.

Step 11 (2026-09-06). `GET /ops/status` can say the autonomous half of
TrialLens is broken, but an endpoint nobody opens is not monitoring — it is
a page that would have told you. This script is the part that goes looking.

It runs as the last step of `.github/workflows/monitor.yml`, reads
`/ops/status` over HTTP (FastAPI is the only door — CLAUDE.md sec. 5, and
this script deliberately holds no database credential of its own), prints
every alert, and **exits non-zero if any of them is critical**. GitHub then
marks the workflow failed and sends its own notification.

That last part is the whole design. The escalation channel is one this
project already has, already trusts, and pays nothing for: no email
provider, no account, no secret, no new failure mode of its own. Step 12's
Resend digest is a product feature for a researcher; this is an operational
alarm for whoever runs the thing, and wiring the alarm to the digest would
have made an ops outage depend on the notification system that outage might
have taken down.

A warning does not fail the job. A workflow that goes red for something
nobody needs to act on today is a workflow people learn to ignore, and then
the one real alarm is ignored too.

Run manually:
    API_BASE_URL=https://triallens-api.onrender.com \
        .venv/bin/python scripts/check_ops_health.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
for path in (str(ROOT), str(FRONTEND)):
    if path not in sys.path:
        sys.path.insert(0, path)

# The frontend's HTTP client, reused rather than reimplemented: it already
# refuses a non-HTTP address up front and keeps the configured address out
# of its own error text (frontend/api_client.py, after the 2026-09-05 leak).
# A CI log is user-visible output too — on a public repo, very visible.
import api_client  # noqa: E402

CRITICAL = "critical"


def format_status(status: dict) -> str:
    lines = []
    for job in status.get("jobs", []):
        last = job.get("last_completed_at") or "never"
        hours = job.get("hours_since_completion")
        ago = f"{hours:.1f}h ago" if hours is not None else "no completed run"
        lines.append(
            f"  {job['name']:<10} last completed {last} ({ago}), "
            f"status={job.get('last_status')}, "
            f"{job.get('last_work_done')} {job['work_label']}, "
            f"{job.get('runs_in_window')} run(s) in the last "
            f"{job.get('window_hours')}h "
            f"({job.get('failed_in_window')} failed, "
            f"{job.get('degraded_in_window')} degraded)"
        )

    budget = status.get("budget", {})
    lines.append(
        f"  budget     ${budget.get('spent_usd', 0):.4f} of "
        f"${budget.get('ceiling_usd', 0):.2f} used in the last "
        f"{budget.get('window_days')} days "
        f"(${budget.get('remaining_usd', 0):.4f} left)"
    )
    lines.append(f"  tracking   {status.get('tracked_conditions')} condition(s)")
    return "\n".join(lines)


def format_alerts(alerts) -> str:
    if not alerts:
        return "  No alerts."
    return "\n".join(
        f"  [{a['severity'].upper()}] {a['title']}\n      {a['detail']}"
        for a in alerts
    )


def main() -> int:
    try:
        status = api_client.get("/ops/status")
    except api_client.ApiError as exc:
        # Unreachable is itself a critical result. A health check that
        # returns "fine, I couldn't check" is worse than none — it is a
        # green tick attached to no evidence.
        print(f"CRITICAL: could not read /ops/status — {exc}", flush=True)
        return 1

    print(f"Ops status at {status.get('checked_at')}:", flush=True)
    print(format_status(status), flush=True)
    print("\nAlerts:", flush=True)
    print(format_alerts(status.get("alerts", [])), flush=True)

    critical = [a for a in status.get("alerts", []) if a["severity"] == CRITICAL]
    if critical:
        print(
            f"\nFAILING this job: {len(critical)} critical alert(s). "
            "This is the escalation — the workflow going red is how a human "
            "finds out.",
            flush=True,
        )
        return 1

    warnings = [a for a in status.get("alerts", []) if a["severity"] != CRITICAL]
    if warnings:
        print(
            f"\n{len(warnings)} warning(s), no critical alerts. Not failing "
            "the job: a red build for something nobody must act on today is "
            "how red builds stop meaning anything.",
            flush=True,
        )
    else:
        print("\nHealthy.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
