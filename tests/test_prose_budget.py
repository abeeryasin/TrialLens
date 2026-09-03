"""The rolling spend ceiling on step 7c (2026-09-03).

`PROSE_BUDGET_USD` only ever bounded ONE run. The monitor cron fires every
six hours, so 120 runs a month at that cap is ~$30 against a project whose
standing budget is a few dollars. `rolling_budget_remaining()` is the cap
that actually binds, and these tests exist because a budget guard that is
wrong in the permissive direction is worse than none — it reads as safety
while spending.

Free: no database, no network, no model. The connection is a stub.

Run: PYTHONPATH=. python3 -m pytest tests/test_prose_budget.py -v
"""
import pytest

from scripts import run_monitor


class StubCursor:
    """Returns one scalar, the way the SUM query is read."""

    def __init__(self, value):
        self.value = value
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchone(self):
        return (self.value,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StubConn:
    def __init__(self, spent):
        self.cur = StubCursor(spent)

    def cursor(self):
        return self.cur


def remaining_after(spent):
    return run_monitor.rolling_budget_remaining(StubConn(spent))


def test_a_clean_window_leaves_the_whole_ceiling():
    assert remaining_after(0) == pytest.approx(run_monitor.PROSE_ROLLING_CEILING_USD)


def test_spend_is_subtracted():
    ceiling = run_monitor.PROSE_ROLLING_CEILING_USD
    assert remaining_after(0.25) == pytest.approx(ceiling - 0.25)


def test_an_exhausted_window_returns_zero_not_a_negative():
    """A negative remaining would pass `min(PROSE_BUDGET_USD, remaining)`
    straight into the batch as a negative budget. Whether that spends nothing
    or everything depends on a comparison in someone else's code, and the
    guard must not depend on that."""
    ceiling = run_monitor.PROSE_ROLLING_CEILING_USD
    assert remaining_after(ceiling + 5) == 0
    assert remaining_after(ceiling) == 0


def test_the_window_is_summed_by_started_at_not_completed_at():
    """A run that spends and then crashes never gets a completed_at. Summing
    on that column would make its spend invisible to the ceiling — the exact
    case the guard is for."""
    conn = StubConn(0)
    run_monitor.rolling_budget_remaining(conn)
    sql = " ".join(conn.cur.executed).lower()
    assert "started_at" in sql
    assert "completed_at" not in sql
    assert "coalesce" in sql, "a window with no rows must sum to 0, not NULL"


def test_the_ceiling_is_lower_than_an_unbounded_cron_month():
    """Guards the constant itself. If someone raises the ceiling above what
    the per-run cap could spend in a month, it has stopped being a ceiling."""
    runs_per_month = 4 * 30
    unbounded = run_monitor.PROSE_BUDGET_USD * runs_per_month
    assert run_monitor.PROSE_ROLLING_CEILING_USD < unbounded
    assert run_monitor.PROSE_ROLLING_CEILING_USD > 0


def test_the_run_budget_never_exceeds_what_the_window_has_left():
    """The min() in run_prose_interpretation, stated as an invariant. Without
    it a single run spends its full per-run budget through a ceiling that had
    cents remaining."""
    for spent in (0, 0.5, 0.99, 1.0, 99.0):
        remaining = remaining_after(spent)
        budget = min(run_monitor.PROSE_BUDGET_USD, remaining)
        assert budget <= remaining
        assert budget <= run_monitor.PROSE_BUDGET_USD
        assert budget >= 0


def test_spend_survives_a_failure_after_the_money_is_gone(monkeypatch):
    """The accounting hole this closed.

    The except clause used to `return 0.0`, so a run that paid for
    interpretations and then failed while storing them reported no spend, and
    the rolling window never learned about it — a guard fed by its own blind
    spot. Whatever was actually spent must come back even on the error path.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://stub/stub")
    monkeypatch.setattr(run_monitor.psycopg2, "connect", lambda *a, **k: StubConn(0))
    monkeypatch.setattr(run_monitor, "rolling_budget_remaining", lambda conn: 1.0)
    monkeypatch.setattr(
        run_monitor, "get_prose_amendments",
        lambda conn, hours_ago: [{"id": 1, "nct_id": "NCT1", "field_name": "brief_summary"}],
    )
    # Money is spent, then storage explodes: StubConn has no .commit().
    monkeypatch.setattr(
        run_monitor, "interpret_amendments_batch",
        lambda amendments, max_cost_usd, max_calls: (
            [{"id": 1, "prose_interpretation": {"summary": "x", "why_matters": "y"}}],
            0.42,
        ),
    )

    spend = run_monitor.run_prose_interpretation()
    assert spend == pytest.approx(0.42), (
        "spend was lost on the error path — the rolling ceiling would never "
        "see this money"
    )


def test_nothing_is_called_once_the_ceiling_is_reached(monkeypatch):
    """The refusal itself: no amendments are even fetched, so no call can be
    made by accident further down."""
    called = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://stub/stub")
    monkeypatch.setattr(run_monitor.psycopg2, "connect", lambda *a, **k: StubConn(0))
    monkeypatch.setattr(run_monitor, "rolling_budget_remaining", lambda conn: 0.0)
    monkeypatch.setattr(
        run_monitor, "get_prose_amendments",
        lambda conn, hours_ago: called.append("fetched") or [],
    )
    monkeypatch.setattr(
        run_monitor, "interpret_amendments_batch",
        lambda *a, **k: called.append("PAID CALL") or ([], 0.0),
    )

    assert run_monitor.run_prose_interpretation() == 0.0
    assert called == [], f"work happened past an exhausted ceiling: {called}"
