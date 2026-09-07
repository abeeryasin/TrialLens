"""GET /ops/status — is the unattended half of TrialLens doing its job?

Step 11 (autonomous-ops hardening). TrialLens has two processes nobody
watches: a 6-hourly monitor cron that ingests, diffs and pays for AI calls,
and a weekly synthesis agent that pays for more of them and files proposals
for review. Between them they hold a database credential, an API key, and a
budget. Until now the only place their health was visible was:

  * `GET /watch`, which sees the monitor's *completion timestamp* and
    nothing else — not its errors, not its spend, and not the synthesis
    agent, which it does not know exists; and
  * GitHub Actions logs, which expire, which nobody reads on a good day,
    and which say nothing at all about the failure mode this project has
    actually hit twice — a job that finishes green while a step inside it
    silently does nothing.

This endpoint is the operator's view: per-job run records, the shared spend
window, and a list of named alerts.

**Deterministic, per sec. 5.** Every question here has one correct answer
computable from two tables — no judgment, so no AI. **And no score, per
sec. 3**: alerts are a list of named conditions each carrying its own
measurement, never a summed health index. That is the same rule the review
queue follows and the same one the removed ranking layer broke.

The alert rules are not generic ops boilerplate — each one is a failure
this project has actually had:

  * `monitor_checked_nothing` and `no_tracked_conditions` exist because on
    2026-09-05 a `LIKE '__%%'` cleanup emptied the `tracked_conditions`
    registry. Had that gone unnoticed for a cycle, the cron would have run,
    checked zero trials, and closed a perfectly green run record.
  * `run_degraded` exists because step 7c's storage bug ran for a day
    inside a caught exception, spending real money and storing nothing,
    while every run reported 'completed'.
  * `run_stuck` exists because `scripts/run_monitor.py` deliberately does
    not mark a dying run 'failed' — a killed job leaves its row 'running'
    forever, which is honest but invisible.
  * `budget_exhausted` exists because a guard that silently stops working
    looks exactly like a guard that has nothing to do.
"""
from typing import List, Optional

import psycopg2.extras
from fastapi import APIRouter, Depends

from api.conditions import list_tracked_conditions
from api.cost_budget import (
    ROLLING_CEILING_USD,
    ROLLING_WINDOW_DAYS,
    rolling_spend,
)
from api.database import get_readonly_db
from api.safe_errors import scrub
from api.schemas import OpsAlert, OpsBudget, OpsJob, OpsStatus
from api.watch import CHECK_INTERVAL_HOURS, STALE_AFTER_HOURS

CRITICAL = "critical"
WARNING = "warning"

# No run in this system legitimately takes three hours — the monitor's full
# pass over ~11,500 trials is minutes, and a 10-turn agent run is under a
# minute. A row still marked 'running' after this long is a process that
# died without getting to write its outcome.
STUCK_AFTER_HOURS = 3

# How many recent runs to read for the consecutive-failure streak. The
# streak is counted in Python rather than SQL on purpose: a window function
# that finds "rows before the first non-failure" is harder to read and
# harder to test than a loop over ten rows, and ten rows is 2.5 days of
# monitor history — well past the point where a streak is already an alarm.
RECENT_RUNS = 10


class JobSpec:
    """One unattended job, and what counts as healthy for it.

    `table` and `work_column` are interpolated into SQL. They are module
    constants defined immediately below and no request value ever reaches
    them — every user-supplied value in this file is a bound parameter.
    """

    def __init__(self, name, table, work_column, work_label, cadence_hours,
                 stale_after_hours, stale_severity, zero_work_is_a_fault):
        self.name = name
        self.table = table
        self.work_column = work_column
        self.work_label = work_label
        self.cadence_hours = cadence_hours
        self.stale_after_hours = stale_after_hours
        self.stale_severity = stale_severity
        self.zero_work_is_a_fault = zero_work_is_a_fault
        # At least a week, and at least four scheduled slots — so the
        # weekly job's counts cover four runs rather than one.
        self.window_hours = max(168, cadence_hours * 4)


JOBS = [
    # Cadence and staleness are imported from api/watch.py, not restated:
    # the watch already had to decide when a missed check becomes an alarm
    # (one late run is a hiccup, two consecutive misses is a pattern), and
    # two modules disagreeing about that would be worse than either answer.
    JobSpec(
        name="monitor",
        table="monitor_runs",
        work_column="trials_checked",
        work_label="trials checked",
        cadence_hours=CHECK_INTERVAL_HOURS,
        stale_after_hours=STALE_AFTER_HOURS,
        # The monitor stopping means TrialLens's central claim — "we are
        # watching these trials" — has quietly stopped being true.
        stale_severity=CRITICAL,
        zero_work_is_a_fault=True,
    ),
    JobSpec(
        name="synthesis",
        table="synthesis_runs",
        work_column="proposals_created",
        work_label="proposals filed",
        cadence_hours=168,
        stale_after_hours=336,
        # A missed week of synthesis costs advisory output, not the watch.
        stale_severity=WARNING,
        # Zero proposals is a legitimate result, not a fault: the first real
        # run filed zero because there was only one week of history to
        # compare against (docs/decisions.md, 2026-09-05). An agent that
        # finds nothing and says so is working.
        zero_work_is_a_fault=False,
    ),
    JobSpec(
        name="digest",
        table="digest_runs",
        work_column="changes_reported",
        work_label="outcome changes mailed",
        # Weekdays only, so the gap Friday -> Monday is 72 hours by design.
        # Staleness has to clear that or the alarm fires every Monday
        # morning about a job that ran exactly as intended.
        cadence_hours=24,
        stale_after_hours=96,
        # A missed digest costs a notification. The watch itself is
        # unaffected, and every change it would have named is still on the
        # Monitor page — so this is a warning, not the alarm that fails the
        # workflow. Same rule the synthesis job follows.
        stale_severity=WARNING,
        # A day with no substantive outcome change is a real and common
        # result — 5 of the record's first 10 days had none — and the mail
        # still went out saying so. Counting that as a fault would fire an
        # alert on half of all correct runs.
        zero_work_is_a_fault=False,
    ),
]

router = APIRouter(tags=["ops"])


@router.get("/ops/status", response_model=OpsStatus)
def ops_status(conn=Depends(get_readonly_db)):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # One clock, the database's — same reason as api/watch.py: elapsed
        # time is measured against the clock that wrote the timestamps.
        cur.execute("SELECT now() AS now")
        now = cur.fetchone()["now"]

        jobs = [_read_job(cur, spec, now) for spec in JOBS]

    spent = rolling_spend(conn)
    budget = OpsBudget(
        window_days=ROLLING_WINDOW_DAYS,
        ceiling_usd=ROLLING_CEILING_USD,
        spent_usd=round(spent, 4),
        remaining_usd=round(max(0.0, ROLLING_CEILING_USD - spent), 4),
        share_used=round(spent / ROLLING_CEILING_USD, 4) if ROLLING_CEILING_USD else 0.0,
    )

    conditions = list_tracked_conditions(conn)
    alerts = build_alerts(jobs, budget, conditions)

    return OpsStatus(
        checked_at=now,
        # Healthy means "no critical alert". A warning is something to know
        # about, not something to wake up for — and folding the two into one
        # boolean is how a page ends up crying wolf until nobody reads it.
        is_healthy=not any(a.severity == CRITICAL for a in alerts),
        alerts=alerts,
        jobs=jobs,
        budget=budget,
        tracked_conditions=len(conditions),
    )


def _read_job(cur, spec: JobSpec, now) -> OpsJob:
    # Two queries rather than one clever one. The first is the recent
    # history (for the last run and the failure streak), the second the
    # counts over the observation window.
    cur.execute(
        f"""
        SELECT id, status, error, skipped_reason, started_at, completed_at,
               {spec.work_column} AS work_done
        FROM {spec.table}
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (RECENT_RUNS,),
    )
    recent = cur.fetchall()

    cur.execute(
        f"""
        SELECT
            (SELECT completed_at FROM {spec.table}
              WHERE status = 'completed'
              ORDER BY completed_at DESC LIMIT 1) AS last_completed_at,
            (SELECT min(started_at) FROM {spec.table}) AS first_started_at,
            (SELECT {spec.work_column} FROM {spec.table}
              WHERE status = 'completed'
              ORDER BY completed_at DESC LIMIT 1) AS last_work_done,
            count(*) FILTER (
                WHERE started_at > now() - make_interval(hours => %(window)s)
            ) AS runs_in_window,
            count(*) FILTER (
                WHERE started_at > now() - make_interval(hours => %(window)s)
                  AND status = 'failed'
            ) AS failed_in_window,
            count(*) FILTER (
                WHERE started_at > now() - make_interval(hours => %(window)s)
                  AND status = 'completed' AND error IS NOT NULL
            ) AS degraded_in_window,
            count(*) FILTER (
                WHERE status = 'running'
                  AND started_at < now() - make_interval(hours => %(stuck)s)
            ) AS stuck_runs
        FROM {spec.table}
        """,
        {"window": spec.window_hours, "stuck": STUCK_AFTER_HOURS},
    )
    counts = cur.fetchone()

    last = recent[0] if recent else None
    return OpsJob(
        name=spec.name,
        cadence_hours=spec.cadence_hours,
        stale_after_hours=spec.stale_after_hours,
        last_started_at=last["started_at"] if last else None,
        last_completed_at=counts["last_completed_at"],
        hours_since_completion=_hours_between(counts["last_completed_at"], now),
        last_status=last["status"] if last else None,
        # Scrubbed on the way out as well as on the way in. The write side
        # (api/safe_errors.py, used by both scheduled scripts) is the real
        # guard; this one covers rows written before that existed, or by
        # anything else that ever learns to write this column.
        last_error=scrub(last["error"]) if last and last["error"] else None,
        # Work the run declined to do because the paid-call ceiling was
        # spent. Distinct from `error` on purpose: nothing broke.
        last_skipped_reason=(
            scrub(last["skipped_reason"]) if last and last["skipped_reason"]
            else None
        ),
        last_work_done=counts["last_work_done"],
        work_label=spec.work_label,
        consecutive_failures=_failure_streak(recent),
        window_hours=spec.window_hours,
        runs_in_window=counts["runs_in_window"],
        expected_runs_in_window=_expected_runs(
            spec, counts["first_started_at"], now
        ),
        failed_in_window=counts["failed_in_window"],
        degraded_in_window=counts["degraded_in_window"],
        stuck_runs=counts["stuck_runs"],
    )


def _expected_runs(spec: JobSpec, first_started_at, now) -> int:
    """How many runs the schedule promised over the period actually observed.

    Reported beside `runs_in_window` so the cadence is a measurement rather
    than a claim. **The first real reading corrected an assumption**: 17
    monitor runs against 13 scheduled slots (2026-09-06). GitHub's scheduled
    workflows are best-effort and do skip, so the expected shape was fewer
    runs than slots — the record says otherwise, because `monitor_runs`
    cannot tell a `schedule` run from a `workflow_dispatch` one and this
    project dispatched several by hand while debugging. So `runs_in_window`
    exceeding this number is normal and not an error; the two are only ever
    read together, and neither is alerted on. Staleness is what catches a
    watch that has actually stopped.

    Measured from the job's FIRST run, not from the window's start. The
    synthesis agent is one week old against a 28-day window, and dividing
    the window by the cadence would have reported "1 of 4" — a 75% miss rate
    invented entirely out of history that never existed. `monitor_runs`
    itself only starts 2026-09-02 (step 7b seeded run #1), which is younger
    than its own 7-day window. Same rule as every capped list in this
    project: the denominator has to be real.
    """
    if first_started_at is None:
        return 0
    observed_hours = min(
        spec.window_hours, (now - first_started_at).total_seconds() / 3600
    )
    # max(1, ...) because a job younger than one full cadence has still had
    # exactly one due run — its first.
    return max(1, round(observed_hours / spec.cadence_hours))


def _failure_streak(recent) -> int:
    """How many of the most recent runs failed, back to the first that did
    not. A run still 'running' ends the streak rather than extending it —
    it has not failed yet, and counting an in-flight run as a failure would
    make every alert fire mid-run."""
    streak = 0
    for row in recent:
        if row["status"] != "failed":
            break
        streak += 1
    return streak


def _hours_between(then, now) -> Optional[float]:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600, 2)


def build_alerts(jobs: List[OpsJob], budget: OpsBudget,
                 conditions: List[str]) -> List[OpsAlert]:
    """Every named condition currently true, criticals first.

    Kept a plain function over plain values so the rules can be tested
    without a database — the SQL above is what needs a real connection, the
    judgment about what counts as broken is not.
    """
    alerts: List[OpsAlert] = []
    specs = {spec.name: spec for spec in JOBS}

    for job in jobs:
        spec = specs[job.name]

        if job.hours_since_completion is None:
            alerts.append(OpsAlert(
                code="job_never_completed",
                severity=spec.stale_severity,
                title=f"The {job.name} job has no completed run on record",
                detail=(
                    f"No row in {spec.table} has status 'completed'. Either it "
                    "has never run to the end, or its run record is not being "
                    "written — both mean this job cannot be shown to be working."
                ),
                job=job.name,
            ))
        elif job.hours_since_completion >= job.stale_after_hours:
            missed = int(job.hours_since_completion / job.cadence_hours)
            alerts.append(OpsAlert(
                code="job_stale",
                severity=spec.stale_severity,
                title=f"The {job.name} job is overdue",
                detail=(
                    f"Last completed {job.hours_since_completion:.1f}h ago; it "
                    f"runs every {job.cadence_hours}h, so {missed} scheduled "
                    f"slot(s) have passed with no completed run "
                    f"(overdue after {job.stale_after_hours}h)."
                ),
                job=job.name,
            ))

        if job.consecutive_failures > 0:
            alerts.append(OpsAlert(
                code="job_failing",
                severity=CRITICAL,
                title=(
                    f"The {job.name} job's last "
                    f"{job.consecutive_failures} run(s) failed"
                ),
                detail=(
                    f"Most recent error: {job.last_error or 'none recorded'}"
                ),
                job=job.name,
            ))

        if job.degraded_in_window > 0:
            alerts.append(OpsAlert(
                code="run_degraded",
                severity=WARNING,
                title=f"The {job.name} job finished with an error inside it",
                detail=(
                    f"{job.degraded_in_window} run(s) in the last "
                    f"{job.window_hours}h closed as 'completed' with an error "
                    f"recorded. The job did its main work; something inside it "
                    f"did not. Most recent: {job.last_error or 'see the run record'}"
                ),
                job=job.name,
            ))

        if job.stuck_runs > 0:
            alerts.append(OpsAlert(
                code="run_stuck",
                severity=WARNING,
                title=f"A {job.name} run never finished",
                detail=(
                    f"{job.stuck_runs} run(s) are still marked 'running' after "
                    f"more than {STUCK_AFTER_HOURS}h. The process died before it "
                    "could record an outcome; any money it spent is still counted "
                    "against the budget window, which is why the row is left "
                    "alone rather than tidied away."
                ),
                job=job.name,
            ))

        if job.last_skipped_reason:
            # CRITICAL, where a merely-exhausted budget is only a warning.
            # The difference is whether the guard is holding or has started
            # costing something: "no budget left" is the guard working, while
            # "no budget left AND a real week went unexamined" means the
            # system has quietly stopped doing what it claims. Only the second
            # is worth failing a build for.
            #
            # Self-clearing by construction — it reads the LATEST run, so the
            # first run that completes its work without skipping removes it.
            alerts.append(OpsAlert(
                code="work_skipped",
                severity=CRITICAL,
                title=f"The {job.name} job's last run could not do its work",
                detail=(
                    f"{job.last_skipped_reason}. The run itself completed and "
                    "nothing is broken — but the work did not happen, which "
                    "from the outside looks exactly like a quiet week."
                ),
                job=job.name,
            ))

        if spec.zero_work_is_a_fault and job.last_work_done == 0:
            alerts.append(OpsAlert(
                code="job_did_nothing",
                severity=CRITICAL,
                title=f"The last {job.name} run did no work",
                detail=(
                    f"It completed with 0 {job.work_label}. A run that checks "
                    "nothing and reports success is the failure that looks most "
                    "like health — it is what an empty tracked-conditions "
                    "registry produces."
                ),
                job=job.name,
            ))

    if not conditions:
        alerts.append(OpsAlert(
            code="no_tracked_conditions",
            severity=CRITICAL,
            title="Nothing is being tracked",
            detail=(
                "The tracked_conditions table is empty, so the monitor has "
                "nothing to check and will keep completing successfully while "
                "watching zero trials. This happened for real on 2026-09-05."
            ),
        ))

    if budget.remaining_usd <= 0:
        alerts.append(OpsAlert(
            code="budget_exhausted",
            severity=WARNING,
            title="The paid-call budget for this window is spent",
            detail=(
                f"${budget.spent_usd:.4f} of ${budget.ceiling_usd:.2f} used in "
                f"the last {budget.window_days} days. Paid calls are being "
                "skipped — the guard is working. On its own this is not an "
                "alarm; if it actually costs a run its work, that run records "
                "why and `work_skipped` escalates it."
            ),
        ))

    # Criticals first, then in the order found. Sorted, not scored: this is
    # about what a reader sees first, not about ranking the problems.
    return sorted(alerts, key=lambda a: 0 if a.severity == CRITICAL else 1)
