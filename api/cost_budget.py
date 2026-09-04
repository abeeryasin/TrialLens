"""One rolling spend ceiling, shared by every paid AI call TrialLens makes.

Two callers exist: step 7c's prose interpreter (scripts/run_monitor.py,
every 6 hours) and the weekly synthesis agent (scripts/run_synthesis.py).
They draw from the SAME $1.00/30-day ceiling rather than one each — a
researcher reading a monthly bill does not care which feature spent the
dollar, and capping them separately would let the two together spend $2.00
while each guard reports itself under budget.

Spend is read from where each caller records it
(monitor_runs.prose_spend_usd, synthesis_runs.spend_usd), summed by
`started_at` so a run that spent money and then crashed before finishing is
still counted — the same reasoning as the original single-table version in
scripts/run_monitor.py (docs/decisions.md, 2026-09-03).
"""
ROLLING_CEILING_USD = 1.00
ROLLING_WINDOW_DAYS = 30


def rolling_spend(conn) -> float:
    """Every dollar any paid call has spent in the trailing window."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                coalesce((SELECT sum(prose_spend_usd) FROM monitor_runs
                          WHERE started_at > now() - interval '{ROLLING_WINDOW_DAYS} days'), 0)
              + coalesce((SELECT sum(spend_usd) FROM synthesis_runs
                          WHERE started_at > now() - interval '{ROLLING_WINDOW_DAYS} days'), 0)
            """
        )
        return float(cur.fetchone()[0])


def rolling_budget_remaining(conn) -> float:
    """Dollars left in the shared window before ANY paid call must stop."""
    return max(0.0, ROLLING_CEILING_USD - rolling_spend(conn))
