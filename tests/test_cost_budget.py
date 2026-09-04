"""The shared $1.00/30-day ceiling (2026-09-05).

Two callers spend against ONE window: step 7c's prose interpreter
(monitor_runs.prose_spend_usd) and the weekly synthesis agent
(synthesis_runs.spend_usd). A guard that summed only one table would let
the two features spend $2.00 together while each reported itself under
budget — the same failure class as the original single-table ceiling
before it existed at all (docs/decisions.md, 2026-09-03).

Free: no database, no network, no model. The connection is a stub.
"""
import pytest

from api import cost_budget


class StubCursor:
    """Returns one scalar, the way the combined SUM query is read."""

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
    return cost_budget.rolling_budget_remaining(StubConn(spent))


def test_a_clean_window_leaves_the_whole_ceiling():
    assert remaining_after(0) == pytest.approx(cost_budget.ROLLING_CEILING_USD)


def test_combined_spend_is_subtracted():
    """The stub returns one number for the whole query, standing in for
    prose_spend_usd + spend_usd already summed together server-side."""
    ceiling = cost_budget.ROLLING_CEILING_USD
    assert remaining_after(0.68) == pytest.approx(ceiling - 0.68)


def test_an_exhausted_window_returns_zero_not_a_negative():
    ceiling = cost_budget.ROLLING_CEILING_USD
    assert remaining_after(ceiling + 5) == 0
    assert remaining_after(ceiling) == 0


def test_the_query_reads_both_tables():
    """Guards against a regression back to a single-table sum — the whole
    point of moving this out of run_monitor.py."""
    conn = StubConn(0)
    cost_budget.rolling_budget_remaining(conn)
    sql = " ".join(conn.cur.executed).lower()
    assert "monitor_runs" in sql
    assert "synthesis_runs" in sql
    assert "prose_spend_usd" in sql
    assert "spend_usd" in sql


def test_the_window_is_summed_by_started_at_not_completed_at():
    """A run that spends and then crashes never gets a completed_at.
    Summing on that column would make its spend invisible to the ceiling —
    the exact case the guard is for, in either table."""
    conn = StubConn(0)
    cost_budget.rolling_budget_remaining(conn)
    sql = " ".join(conn.cur.executed).lower()
    assert "started_at" in sql
    assert "completed_at" not in sql
    assert sql.count("coalesce") == 2, "each table's subtotal must default to 0, not NULL"
