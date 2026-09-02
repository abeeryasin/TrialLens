"""The watch itself — what the front page leads with, instead of a search box.

Step 7b direction 2 (`docs/plan_after_ranking.md`). The argument, in one
line: TrialLens's real claim is not "we can search trials", it is "we have
been watching 11,427 trials since 28 August and we will tell you when one
moves". A search box says nothing about that; a statement of the watch says
all of it.

The screen this feeds has three states, and the least eventful one is the
one that matters most:

  1. **Quiet** — nothing was amended recently. This is the COMMON case (29
     and 30 August 2026 had zero amendments across all 11,427 trials, real
     recorded data) and today it renders as an empty table, which reads as
     a broken app rather than a working watch. Stated as a finding, with
     the empty days shown as zeros rather than omitted, it reads as what it
     is.
  2. **News** — something was amended. Lead with it.
  3. **Stopped** — no evidence of a recent check. Then the alarm REPLACES
     the page (see WatchStatus.is_healthy), because a stale feed under a
     small warning still reads as current.

**`last_checked_at` reads from the `monitor_runs` table** (step 7b direction 3,
2026-09-02). Every scheduled run records when it started and completed, so the
watch knows a run happened even on a quiet day (no amendments). This table
replaced the proxy `max(studies.last_matched_at)`, which couldn't distinguish
"nothing has changed recently" from "nothing has been checked recently".
"""
from typing import List, Optional

import psycopg2.extras
from fastapi import APIRouter, Depends

from api.amendments import (
    ASPECT_ORDER,
    ASPECT_SCIENTIFIC,
    FIELD_ASPECTS,
    describe_effect,
    enrollment_context,
    field_aspect,
)
from api.database import get_readonly_db
from api.schemas import AmendedField, WatchAmendment, WatchDay, WatchRecent, WatchStatus
from api.tracking import TRACKING_FIELDS, field_category

router = APIRouter(tags=["watch"])

# Must match the cron in .github/workflows/monitor.yml ("0 */6 * * *").
# Not read from that file: the workflow is the schedule GitHub honours, and
# a YAML parse here would imply this process could change it.
CHECK_INTERVAL_HOURS = 6

# A check is late long before the watch is dead — GitHub's scheduled
# workflows are explicitly best-effort and routinely start minutes late,
# and one skipped run is a hiccup, not a failure. Two consecutive misses is
# a pattern, so that is where the alarm starts.
STALE_AFTER_HOURS = CHECK_INTERVAL_HOURS * 2

# How many days the record strip shows. Seven so a week of the watch fits
# on one line, including the days nothing happened.
RECORD_DAYS = 7

# The window the headline speaks about ("in the last 24 hours"). Fixed, not
# a query parameter: this endpoint feeds one screen that makes one claim,
# and a tunable window would let the same page report a quiet day or a busy
# one depending on a number nobody chose deliberately.
RECENT_WINDOW_HOURS = 24

# Derived from the one aspect mapping in api/amendments.py rather than
# re-listed, so a field reclassified there cannot silently stop counting
# as scientific here.
SCIENTIFIC_FIELDS = sorted(
    name for name, aspect in FIELD_ASPECTS.items() if aspect == ASPECT_SCIENTIFIC
)


@router.get("/watch", response_model=WatchStatus)
def watch_status(conn=Depends(get_readonly_db)):
    tracking_fields = sorted(TRACKING_FIELDS)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # One clock for every elapsed-time figure below. Taken from the
        # database rather than this process so "2 hours ago" is measured
        # against the same clock that wrote the timestamps it is compared
        # to — the API and Postgres are not the same machine.
        cur.execute("SELECT now() AS now")
        now = cur.fetchone()["now"]

        # Named columns, never SELECT * — raw_json is 52% of this table and
        # nothing here reads it (CLAUDE.md, standing gotchas).
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE active_in_scope) AS trials_watched,
                   count(*) FILTER (WHERE active_in_scope AND has_results)
                       AS trials_with_results,
                   count(*) FILTER (WHERE active_in_scope AND has_results
                                      AND overall_status = 'COMPLETED')
                       AS completed_with_results
            FROM studies
            """
        )
        studies = cur.fetchone()

        # Get the most recent completed run for last_checked_at.
        # The run record is authoritative — it exists even on quiet weeks.
        cur.execute(
            """
            SELECT completed_at AS last_checked_at
            FROM monitor_runs
            WHERE status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        )
        run_result = cur.fetchone()
        last_checked_at = run_result["last_checked_at"] if run_result else None
        studies["last_checked_at"] = last_checked_at

        cur.execute(
            """
            SELECT count(*) AS changes_recorded,
                   min(detected_at) AS recording_since,
                   count(*) FILTER (WHERE field_name = 'last_update_post_date')
                       AS amendments_seen,
                   max(detected_at) FILTER (WHERE field_name = 'last_update_post_date')
                       AS last_amendment_at
            FROM study_changes
            """
        )
        record = cur.fetchone()

        # generate_series, not GROUP BY over the changes: a day with no
        # amendments has no rows to group, and the whole point of the strip
        # is that those days are visible as zeros. Grouping alone would
        # silently drop exactly the days this screen exists to show.
        cur.execute(
            """
            SELECT d::date AS day, count(sc.id) AS amendments
            FROM generate_series(
                     current_date - %s, current_date, interval '1 day'
                 ) AS d
            LEFT JOIN study_changes sc
                   ON sc.field_name = 'last_update_post_date'
                  AND sc.detected_at::date = d::date
            GROUP BY 1
            ORDER BY 1
            """,
            (RECORD_DAYS - 1,),
        )
        daily = [WatchDay(**row) for row in cur.fetchall()]

        # The amendment is the unit, not the changed row — an amendment that
        # moved four dates is one thing that happened, and counting its rows
        # would report it as four. `recent` names each amendment by
        # (nct_id, detected_at), the same key GET /studies/{id}/amendments
        # groups on.
        cur.execute(
            """
            WITH recent AS (
                SELECT nct_id, detected_at
                FROM study_changes
                WHERE field_name = 'last_update_post_date'
                  AND detected_at >= now() - make_interval(hours => %s)
            )
            SELECT (SELECT count(*) FROM recent) AS amendments,
                   (SELECT count(DISTINCT nct_id) FROM recent) AS trials,
                   (SELECT count(*) FROM recent r WHERE EXISTS (
                        SELECT 1 FROM study_changes c
                        WHERE c.nct_id = r.nct_id
                          AND c.detected_at = r.detected_at
                          AND c.field_name = ANY(%s)
                    )) AS scientific,
                   (SELECT count(*) FROM recent r WHERE EXISTS (
                        SELECT 1 FROM study_changes c
                        WHERE c.nct_id = r.nct_id
                          AND c.detected_at = r.detected_at
                          AND c.field_name = 'has_results'
                          AND lower(c.new_value) IN ('true', 't')
                    )) AS results_posted
            """,
            (RECENT_WINDOW_HOURS, SCIENTIFIC_FIELDS),
        )
        recent = WatchRecent(window_hours=RECENT_WINDOW_HOURS, **cur.fetchone())

        last_amendment = _latest_amendment(cur, tracking_fields)

    hours_since_check = _hours_between(studies["last_checked_at"], now)
    if hours_since_check is None:
        # Nothing has ever reconciled scope, so there is no evidence a check
        # has EVER run. Unhealthy is the honest answer — a page that reports
        # a healthy watch it cannot see is the exact failure being avoided.
        is_healthy, checks_missed = False, 0
    else:
        is_healthy = hours_since_check < STALE_AFTER_HOURS
        # Whole scheduled slots that have elapsed with no evidence of a run.
        # int(), not round(): a check is not missed until its slot has fully
        # passed, and overstating an outage is still misreporting it. Can be
        # 1 while still healthy — one late run is a hiccup worth showing,
        # not an alarm.
        checks_missed = int(hours_since_check / CHECK_INTERVAL_HOURS)

    return WatchStatus(
        trials_watched=studies["trials_watched"],
        conditions=_tracked_conditions(),
        last_checked_at=studies["last_checked_at"],
        hours_since_check=hours_since_check,
        check_interval_hours=CHECK_INTERVAL_HOURS,
        checks_missed=checks_missed,
        is_healthy=is_healthy,
        daily=daily,
        recent=recent,
        hours_since_last_amendment=_hours_between(record["last_amendment_at"], now),
        last_amendment=last_amendment,
        trials_with_results=studies["trials_with_results"],
        completed_with_results=studies["completed_with_results"],
        recording_since=record["recording_since"],
        changes_recorded=record["changes_recorded"],
        amendments_seen=record["amendments_seen"],
    )


def _tracked_conditions() -> List[str]:
    # Imported here rather than at module scope to avoid a circular import:
    # api.main imports this router, and the conditions file is read there.
    from api.main import tracked_conditions

    return tracked_conditions()


def _hours_between(then, now) -> Optional[float]:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600, 2)


def _latest_amendment(cur, tracking_fields) -> Optional[WatchAmendment]:
    """The newest amendment across every watched trial, with what moved.

    **Ties are the normal case, not an edge case.** One cron run posts
    dozens of amendments sharing an exact detected_at (63 on 2026-09-01),
    so "the last one" is genuinely ambiguous among them. The tie-break
    prefers an amendment whose fields TrialLens actually stores, because
    47% of amendments touch only fields it does not, and rendering "the
    last thing that happened" as "amended, but we can't see what" wastes
    the one card on this screen that is supposed to show something real.
    Any of the tied rows is equally the latest, so choosing the legible one
    costs no accuracy — the card still states its own posted_on date.
    """
    cur.execute(
        """
        SELECT a.nct_id, s.brief_title,
               a.new_value AS posted_on,
               a.old_value AS previously_posted_on,
               a.detected_at,
               count(c.id) AS visible_fields
        FROM study_changes a
        JOIN studies s ON s.nct_id = a.nct_id
        LEFT JOIN study_changes c
               ON c.nct_id = a.nct_id
              AND c.detected_at = a.detected_at
              AND c.field_name <> 'last_update_post_date'
              AND NOT (c.field_name = ANY(%s))
        WHERE a.field_name = 'last_update_post_date'
          AND a.new_value IS NOT NULL
        GROUP BY a.nct_id, s.brief_title, a.new_value, a.old_value, a.detected_at
        ORDER BY a.new_value DESC, a.detected_at DESC, count(c.id) DESC, a.nct_id
        LIMIT 1
        """,
        (tracking_fields,),
    )
    head = cur.fetchone()
    if head is None:
        return None

    # The fields that moved in that one amendment. Equality on detected_at,
    # not a time window: one trial's whole diff is written in a single
    # transaction and Postgres now() is transaction-start time, so every
    # row of an amendment shares an exact timestamp (verified over 195
    # changes, 2026-09-01 — see GET /studies/{nct_id}/amendments).
    cur.execute(
        """
        SELECT field_name, old_value, new_value, detected_at
        FROM study_changes
        WHERE nct_id = %s
          AND detected_at = %s
          AND field_name <> 'last_update_post_date'
          AND NOT (field_name = ANY(%s))
        ORDER BY field_name
        """,
        (head["nct_id"], head["detected_at"], tracking_fields),
    )
    changes = [
        AmendedField(
            field_name=row["field_name"],
            old_value=row["old_value"],
            new_value=row["new_value"],
            detected_at=row["detected_at"],
            category=field_category(row["field_name"]),
            aspect=field_aspect(row["field_name"]),
        )
        for row in cur.fetchall()
    ]

    # The enrollment count in force just after THIS amendment, so an
    # enrollment_type switch can name the number instead of gesturing at it.
    # The trial's current count is only that number if nothing has moved it
    # since; if something has, the oldest later move's old_value is what was
    # true here. Stating today's count against an older amendment would
    # attribute a fact to a date on which it was not true (sec. 2).
    cur.execute(
        """
        SELECT COALESCE(
                 (SELECT c.old_value FROM study_changes c
                   WHERE c.nct_id = %(nct)s
                     AND c.field_name = 'enrollment_count'
                     AND c.detected_at > %(at)s
                   ORDER BY c.detected_at ASC LIMIT 1),
                 (SELECT s.enrollment_count::text FROM studies s
                   WHERE s.nct_id = %(nct)s)
               ) AS count_after
        """,
        {"nct": head["nct_id"], "at": head["detected_at"]},
    )
    try:
        count_after = int(cur.fetchone()["count_after"])
    except (TypeError, ValueError):
        count_after = None

    context, _ = enrollment_context(changes, count_after)
    for change in changes:
        change.effect = describe_effect(
            change.field_name, change.old_value, change.new_value, context
        )

    present = {c.aspect for c in changes}
    aspects = [a for a in ASPECT_ORDER if a in present]
    if None in present:
        # Never filed under the least alarming bucket — a field nobody has
        # classified must stay visibly unclassified (api/amendments.py).
        aspects.append("Uncategorised")

    return WatchAmendment(
        nct_id=head["nct_id"],
        brief_title=head["brief_title"],
        posted_on=head["posted_on"],
        previously_posted_on=head["previously_posted_on"],
        detected_at=head["detected_at"],
        changes=changes,
        aspects=aspects,
        content_is_visible=bool(changes),
    )
