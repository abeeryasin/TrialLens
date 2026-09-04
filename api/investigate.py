"""Investigate: what has happened across everything tracked?

The fifth capability, and the only one that asks a question about the
*corpus* rather than about a trial. Discover reads a field, Understand
reads a record, Monitor reads a diff one row at a time, Explore reads one
trial's neighbourhood. None of them can answer "23 trials slipped this
week, by a median of six months, and one of them reopened after
completing" — that sentence is not stored anywhere. It is arithmetic over
study_changes, and this module is where it is done.

**Everything here is deterministic** (CLAUDE.md sec. 5). Every question it
answers has exactly one correct answer that plain code produces and a
model could only get occasionally wrong:

    2027-05-31 -> 2026-03-19   is 14 months earlier.   Subtraction.
    RECRUITING -> ACTIVE_NOT_RECRUITING, 13 rows.      Counting.
    400 -> 163                 missed target by 237.   Subtraction.

The judgment question — "is this week's movement a pattern or a
coincidence?" — is genuinely multi-step and is NOT answered here. This
module produces the checkable numbers that such an analysis would have to
reason over.

Four honesty rules, each one a bug this project has already paid for:

  1. **A finding carries its denominator.** "23 trials slipped" means
     nothing without "of 386 that changed, out of 11,444 tracked, over 8
     days". The step-4 bug was a list reporting its own length as the
     total; the step-8 rule was every capped list naming what it was
     capped from. Same rule, third time.

  2. **Rows that cannot be read are counted, not dropped.** A date this
     module cannot parse is reported as unreadable. Silently skipping it
     would shrink the denominator and overstate the confidence of
     everything else — the same reason Explore counts sites it cannot
     place on a map instead of omitting them.

  3. **"Is this a real move?" has ONE definition.** ~23% of CT.gov dates
     are month-precision, so "2026-03" -> "2026-03-15" looks like a
     15-day slip and is really an artefact of anchoring both sides to the
     1st. api/amendments.describe_date_shift already draws that line for
     the per-trial view; this module calls that exact function rather
     than re-deriving the threshold, so the aggregate and the trial page
     can never disagree about whether a date moved.

  4. **A sponsor's amendment and TrialLens's own bookkeeping are
     different events.** active_in_scope is in TRACKING_FIELDS: when a
     trial leaves scope, nobody amended anything, our filter stopped
     matching. It is reported, in its own section, in those words — the
     same line api/tracking.py draws for the Monitor feed.

The amendment grouping is the one already verified in
api/studies.get_study_amendments: an amendment is a last_update_post_date
row, and its content changes share an EXACT detected_at because one
trial's whole diff is written in one transaction and Postgres now() is
transaction-start time. Grouping by minute splits one amendment in two.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Dict, List, Optional, Tuple

import psycopg2.extras
from fastapi import APIRouter, Depends, Query

from api.amendments import (
    STATUS_FINISHED,
    STATUS_OPEN,
    STATUS_PENDING,
    STATUS_STOPPED,
    STATUS_UNDERWAY_CLOSED,
    describe_date_shift,
    parse_partial_date,
)
from api.database import get_readonly_db
from api.schemas import (
    DateMove,
    DateMovement,
    EnrollmentFinding,
    EnrollmentMove,
    InvestigateResponse,
    InvestigateWindow,
    InterventionUse,
    LandscapeBucket,
    LandscapeCategory,
    LandscapeResponse,
    LandscapeTrial,
    LandscapeTrials,
    LifecycleFinding,
    OutcomeFinding,
    SponsorActivity,
    StatusTransitionCount,
    ScopeExit,
    StatusMove,
)
from api.tracking import TRACKING_FIELDS, drop_reason

router = APIRouter(tags=["investigate"])

# The three date fields CT.gov moves. Ordered as a researcher reads them:
# when the science lands first, when the paperwork closes last.
DATE_FIELDS = ("primary_completion_date", "completion_date", "start_date")

DATE_FIELD_LABELS = {
    "primary_completion_date": "Primary completion",
    "completion_date": "Study completion",
    "start_date": "Study start",
}

# How many trials each finding names individually. A finding is a reading
# list, not a result set — the full count is always reported alongside, so
# a short list never reads as a complete one (rule 1).
NAMED_CAP = 8

# Longest window the endpoint will look back over. The change record began
# 2026-08-28, so anything past that is answered by "we were not watching",
# which the response says explicitly rather than returning a quiet zero.
MAX_WINDOW_DAYS = 365
DEFAULT_WINDOW_DAYS = 7


# ============================================================================
# Date movement — pure
# ============================================================================

MOVE_PUSHED = "pushed"          # the date got later
MOVE_PULLED = "pulled"          # the date got earlier
MOVE_NONE = "no_move"           # both sides parse to the same day
MOVE_PRECISION = "precision_only"  # a month-anchoring artefact, not a slip
MOVE_UNREADABLE = "unreadable"  # one side is not a date we can parse


def classify_date_move(old_value, new_value) -> Tuple[str, Optional[int], bool]:
    """(kind, delta_days, imprecise) for one date change.

    `delta_days` is None only when a side could not be parsed. `imprecise`
    means at least one side was month-precision, which is true of ~23% of
    CT.gov dates and must travel with the number — a median built from
    month-anchored values is not accurate to the day and must not be
    printed as though it were.

    Whether a change counts as a real move is decided by calling
    describe_date_shift, not by re-deriving its threshold here. That is
    rule 3: one definition, so this aggregate and the amendment view on
    Understand cannot disagree about the same row.
    """
    old = parse_partial_date(old_value)
    new = parse_partial_date(new_value)
    if old is None or new is None:
        return MOVE_UNREADABLE, None, False

    (old_date, old_partial), (new_date, new_partial) = old, new
    delta = (new_date - old_date).days
    imprecise = old_partial or new_partial

    if describe_date_shift(old_value, new_value) is None:
        return (MOVE_NONE if delta == 0 else MOVE_PRECISION), delta, imprecise
    return (MOVE_PUSHED if delta > 0 else MOVE_PULLED), delta, imprecise


def analyse_date_moves(rows) -> List[DateMovement]:
    """One DateMovement per date field that actually moved in the window.

    Fields with no rows at all are omitted; a field with rows that were all
    artefacts is KEPT, reporting zero real moves alongside the artefact
    count. Those are different facts and CLAUDE.md sec. 2 forbids rendering
    them identically: "nothing moved" and "things changed but none of it
    was a real shift" are not the same answer.
    """
    by_field: Dict[str, list] = defaultdict(list)
    for row in rows:
        if row["field_name"] in DATE_FIELDS:
            by_field[row["field_name"]].append(row)

    findings: List[DateMovement] = []
    for field_name in DATE_FIELDS:
        field_rows = by_field.get(field_name)
        if not field_rows:
            continue

        pushed: List[DateMove] = []
        pulled: List[DateMove] = []
        counts = {MOVE_NONE: 0, MOVE_PRECISION: 0, MOVE_UNREADABLE: 0}
        imprecise_moves = 0

        for row in field_rows:
            kind, delta, imprecise = classify_date_move(row["old_value"], row["new_value"])
            if kind in counts:
                counts[kind] += 1
                continue
            if imprecise:
                imprecise_moves += 1
            move = DateMove(
                nct_id=row["nct_id"],
                brief_title=row["brief_title"],
                field_name=field_name,
                old_value=row["old_value"],
                new_value=row["new_value"],
                delta_days=delta,
                imprecise=imprecise,
                # The same sentence Understand shows for this row.
                effect=describe_date_shift(row["old_value"], row["new_value"]),
                detected_at=row["detected_at"],
            )
            (pushed if kind == MOVE_PUSHED else pulled).append(move)

        def _median(moves):
            return int(median([abs(m.delta_days) for m in moves])) if moves else None

        # Biggest movers in either direction, largest magnitude first. Both
        # directions in one list on purpose: a trial pulling its completion
        # date 14 months forward is as newsworthy as one slipping 12 back,
        # and splitting them buries whichever a given week happens to have
        # fewer of.
        biggest = sorted(pushed + pulled, key=lambda m: abs(m.delta_days), reverse=True)

        findings.append(
            DateMovement(
                field_name=field_name,
                label=DATE_FIELD_LABELS[field_name],
                pushed=len(pushed),
                pulled=len(pulled),
                median_push_days=_median(pushed),
                median_pull_days=_median(pulled),
                imprecise_moves=imprecise_moves,
                precision_only=counts[MOVE_PRECISION],
                no_move=counts[MOVE_NONE],
                unreadable=counts[MOVE_UNREADABLE],
                rows_seen=len(field_rows),
                biggest=biggest[:NAMED_CAP],
                biggest_total=len(biggest),
            )
        )
    return findings


# ============================================================================
# Lifecycle transitions — pure
# ============================================================================
#
# Written over the status GROUPS in api/amendments.py rather than over the
# eight transitions observed on 2026-09-04, so a transition nobody has seen
# yet still lands somewhere truthful instead of vanishing.

TRANSITIONS = [
    # (key, label, predicate over (old, new))
    (
        "reopened_after_finishing",
        "Reopened after being marked complete",
        lambda old, new: old in STATUS_FINISHED and new in STATUS_OPEN,
    ),
    (
        "restarted_after_stopping",
        "Restarted after being stopped",
        lambda old, new: old in STATUS_STOPPED and new not in STATUS_STOPPED,
    ),
    (
        "stopped_early",
        "Stopped early",
        lambda old, new: new in STATUS_STOPPED,
    ),
    (
        "finished",
        "Finished",
        lambda old, new: new in STATUS_FINISHED,
    ),
    (
        "opened",
        "Opened to enrolment",
        lambda old, new: old in STATUS_PENDING and new in STATUS_OPEN,
    ),
    (
        "closed_to_new",
        "Closed to new participants, still running",
        lambda old, new: old in STATUS_OPEN and new in STATUS_UNDERWAY_CLOSED,
    ),
    (
        "reopened",
        "Reopened to new participants",
        lambda old, new: old in STATUS_UNDERWAY_CLOSED and new in STATUS_OPEN,
    ),
]

# Deliberately last, and deliberately not called "minor". A transition that
# matches nothing above is one nobody has classified, and it stays visible
# under its own literal old -> new wording so it can be noticed and mapped,
# rather than being filed under a bucket that quietly implies it was
# understood. Same reasoning as amendments.field_aspect returning None.
TRANSITION_OTHER = "other"


def transition_kind(old_value, new_value) -> Optional[Tuple[str, str]]:
    """(key, label) for a status transition, or None when it isn't one.

    The first two entries are anomalies and are matched BEFORE the general
    rules on purpose. COMPLETED -> RECRUITING occurred once in the first
    eight days of watching; under the general rules it would read as
    "now open to new participants", which is true and useless. A trial
    reopening after it reported completion is the single most surprising
    row in the record, and a synthesis that averages it away has failed at
    the one job it has.
    """
    if not old_value or not new_value or old_value == new_value:
        return None
    for key, label, matches in TRANSITIONS:
        if matches(old_value, new_value):
            return key, label
    return TRANSITION_OTHER, f"{old_value} to {new_value}"


def analyse_status_moves(rows) -> List[LifecycleFinding]:
    """Status transitions grouped by what they mean, commonest first."""
    grouped: Dict[Tuple[str, str], List[StatusMove]] = defaultdict(list)
    for row in rows:
        if row["field_name"] != "overall_status":
            continue
        kind = transition_kind(row["old_value"], row["new_value"])
        if kind is None:
            continue
        grouped[kind].append(
            StatusMove(
                nct_id=row["nct_id"],
                brief_title=row["brief_title"],
                old_value=row["old_value"],
                new_value=row["new_value"],
                detected_at=row["detected_at"],
            )
        )

    # Anomalies first regardless of count — that is the whole point of
    # separating them — then everything else by how often it happened.
    anomalies = {"reopened_after_finishing", "restarted_after_stopping"}
    ordered = sorted(
        grouped.items(),
        key=lambda item: (item[0][0] not in anomalies, -len(item[1]), item[0][1]),
    )
    findings = []
    for (key, label), moves in ordered:
        # The literal was -> now counts inside this bucket, commonest
        # first. Built from every move, not from the capped `trials` list,
        # so a transition can never be dropped for sorting late.
        pairs: Dict[Tuple[str, str], int] = defaultdict(int)
        for move in moves:
            pairs[(move.old_value, move.new_value)] += 1
        findings.append(
            LifecycleFinding(
                kind=key,
                label=label,
                count=len(moves),
                anomaly=key in anomalies,
                trials=moves[:NAMED_CAP],
                transitions=[
                    StatusTransitionCount(old_value=old, new_value=new, count=n)
                    for (old, new), n in sorted(
                        pairs.items(), key=lambda kv: (-kv[1], kv[0])
                    )
                ],
            )
        )
    return findings


# ============================================================================
# Enrollment reality — pure
# ============================================================================


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def analyse_enrollment(rows, current_counts=None) -> EnrollmentFinding:
    """What the window says about how many people trials actually enrolled.

    Two different events, kept apart because they mean different things:

      - **A target became a real count** (enrollment_type ESTIMATED ->
        ACTUAL, 20 of 21 such switches in the first eight days). This is
        the only place TrialLens can state a trial's real recruitment
        against its own plan, and it is the most consequential number in
        the window.
      - **A target was revised** while still a target. A trial raising its
        plan from 150 to 350 has not enrolled anybody.

    The two numbers for a switch come from the enrollment_count row in the
    SAME amendment, paired on (nct_id, detected_at) — the grouping key
    verified in api/studies.get_study_amendments.

    **8 of the 20 switches in the first eight days had no such row**, and
    what to say about those is the whole difficulty. The count did not move
    in that amendment, so the target and the actual are the same number —
    but WHICH number is only knowable if nothing has moved the count since.
    That is precisely the reasoning already written down in
    amendments.enrollment_context: `studies.enrollment_count` is today's
    figure, and attributing today's figure to an amendment that something
    later changed would state a fact about the trial that was not true when
    it happened (CLAUDE.md sec. 2).

    So `current_counts` is used only when this trial has no LATER
    enrollment_count change, and `later_count_change` carries which case
    applied. Both numbers present with `count_moved` False means "enrolled
    exactly its target, N"; both absent means "the record does not let us
    attribute a number here" — two different statements that must never
    render identically.
    """
    current_counts = current_counts or {}
    counts_by_amendment: Dict[Tuple[str, datetime], dict] = {}
    # The newest amendment that moved each trial's count, so a switch can
    # ask "has anything changed this number since?" before borrowing
    # today's figure.
    latest_count_move: Dict[str, datetime] = {}
    for row in rows:
        if row["field_name"] == "enrollment_count":
            counts_by_amendment[(row["nct_id"], row["detected_at"])] = row
            seen = latest_count_move.get(row["nct_id"])
            if seen is None or row["detected_at"] > seen:
                latest_count_move[row["nct_id"]] = row["detected_at"]

    became_actual: List[EnrollmentMove] = []
    switched_back: List[EnrollmentMove] = []
    target_raised: List[EnrollmentMove] = []
    target_lowered: List[EnrollmentMove] = []
    paired_counts = set()

    for row in rows:
        if row["field_name"] != "enrollment_type":
            continue
        old_type, new_type = row["old_value"], row["new_value"]
        key = (row["nct_id"], row["detected_at"])
        count_row = counts_by_amendment.get(key)
        later_count_change = False
        if count_row is not None:
            paired_counts.add(key)
            before = _as_int(count_row["old_value"])
            after = _as_int(count_row["new_value"])
        else:
            # Nothing moved the count in this amendment. Today's stored
            # figure was also that day's figure ONLY if nothing has moved
            # it since; otherwise there is no honest number to give.
            moved_at = latest_count_move.get(row["nct_id"])
            later_count_change = moved_at is not None and moved_at > row["detected_at"]
            unchanged = None if later_count_change else current_counts.get(row["nct_id"])
            before = after = unchanged

        move = EnrollmentMove(
            nct_id=row["nct_id"],
            brief_title=row["brief_title"],
            old_type=old_type,
            new_type=new_type,
            count_before=before,
            count_after=after,
            count_moved=count_row is not None,
            later_count_change=later_count_change,
            detected_at=row["detected_at"],
        )
        if old_type == "ESTIMATED" and new_type == "ACTUAL":
            became_actual.append(move)
        else:
            # ACTUAL -> ESTIMATED happened once in eight days. A real
            # headcount reverting to a plan is backwards and is surfaced
            # rather than dropped for not fitting the expected direction.
            switched_back.append(move)

    for row in rows:
        if row["field_name"] != "enrollment_count":
            continue
        key = (row["nct_id"], row["detected_at"])
        if key in paired_counts:
            continue  # already told as part of a target-became-actual switch
        before, after = _as_int(row["old_value"]), _as_int(row["new_value"])
        if before is None or after is None or before == after:
            continue
        move = EnrollmentMove(
            nct_id=row["nct_id"],
            brief_title=row["brief_title"],
            old_type=None,
            new_type=None,
            count_before=before,
            count_after=after,
            count_moved=True,
            detected_at=row["detected_at"],
        )
        (target_raised if after > before else target_lowered).append(move)

    def _by_gap(moves):
        return sorted(
            moves,
            key=lambda m: abs((m.count_after or 0) - (m.count_before or 0)),
            reverse=True,
        )

    shortfalls = [
        m for m in became_actual
        if m.count_before is not None and m.count_after is not None and m.count_after < m.count_before
    ]
    return EnrollmentFinding(
        became_actual=_by_gap(became_actual)[:NAMED_CAP],
        became_actual_total=len(became_actual),
        under_target=len(shortfalls),
        switched_back=switched_back[:NAMED_CAP],
        switched_back_total=len(switched_back),
        target_raised=_by_gap(target_raised)[:NAMED_CAP],
        target_raised_total=len(target_raised),
        target_lowered=_by_gap(target_lowered)[:NAMED_CAP],
        target_lowered_total=len(target_lowered),
    )


# ============================================================================
# Scope departures — pure
# ============================================================================


def analyse_scope_exits(rows) -> List[ScopeExit]:
    """Trials that left the watch during the window.

    **Nobody amended these trials.** active_in_scope is TrialLens's own
    bookkeeping (TRACKING_FIELDS), so a true -> false row means our filter
    stopped matching, not that a sponsor did something. It is reported in
    its own section, in those words, for the same reason api/tracking.py
    keeps the Monitor feed's two categories apart — a researcher reading
    "100 trials changed" would otherwise count our own filter as news.

    The reason comes from api.tracking.drop_reason, which returns None when
    the stored data does not actually explain the departure. None stays
    None and renders as "we can't tell" (sec. 2) rather than being filled
    with a plausible guess.
    """
    exits: List[ScopeExit] = []
    for row in rows:
        if row["field_name"] != "active_in_scope":
            continue
        if str(row["new_value"]).strip().lower() not in {"false", "f", "0"}:
            continue
        exits.append(
            ScopeExit(
                nct_id=row["nct_id"],
                brief_title=row["brief_title"],
                overall_status=row.get("overall_status"),
                reason=drop_reason(row.get("overall_status"), row.get("last_update_post_date")),
                detected_at=row["detected_at"],
            )
        )
    return exits


# ============================================================================
# The endpoint
# ============================================================================
#
# Its own top-level router, same reasoning as api/changes.py, api/discover.py
# and api/explore.py: nesting it under /studies would collide with
# /studies/{nct_id}, which FastAPI resolves by registration order — a
# constraint that has to hold forever and breaks silently when two lines
# get reordered.

# One row per (amendment, changed field). LEFT JOIN so an amendment whose
# only changes were prose still counts toward the amendment total — an
# INNER JOIN here would report a quieter week than the one that happened.
# The condition filter is EXISTS rather than a JOIN on study_conditions
# deliberately: that table has 32,701 rows over 11,544 trials and one trial
# carries up to 19 tags for the same condition, so joining it multiplies
# every change row by its tag count. That exact mistake logged 19 copies of
# one change in step 6b.
_AMENDMENT_SQL = """
    SELECT a.nct_id,
           s.brief_title,
           a.detected_at,
           a.new_value AS posted_on,
           c.field_name,
           c.old_value,
           c.new_value,
           -- The stored model reading of a prose diff (step 7c). Read here
           -- for outcome changes, where 5 of the record's 7 readings live.
           c.prose_interpretation,
           -- Today's count, used only for a type switch whose amendment
           -- did not move the number AND which nothing has moved since.
           s.enrollment_count AS current_enrollment_count,
           -- The trial's own milestones, which is what makes an outcome
           -- change interesting or ordinary: before primary completion
           -- nobody has seen the endpoint data.
           s.primary_completion_date,
           s.start_date,
           s.has_results,
           -- Lead sponsor class. The literature associates post-completion
           -- outcome changes with funding source (PMC5829948, OR 1.82),
           -- and CT.gov states this, so it needs no model to establish.
           lead.org_class
    FROM study_changes a
    JOIN studies s ON s.nct_id = a.nct_id
    LEFT JOIN LATERAL (
        SELECT o.org_class FROM trial_organizations o
        WHERE o.nct_id = a.nct_id AND o.role = 'LEAD'
        LIMIT 1
    ) lead ON true
    LEFT JOIN study_changes c
           ON c.nct_id = a.nct_id
          AND c.detected_at = a.detected_at
          AND c.field_name <> 'last_update_post_date'
          AND NOT (c.field_name = ANY(%(tracking_fields)s))
    WHERE a.field_name = 'last_update_post_date'
      AND a.new_value IS NOT NULL
      AND a.detected_at >= %(since)s
      {condition_clause}
    ORDER BY a.detected_at DESC, c.field_name
"""

_SCOPE_EXIT_SQL = """
    SELECT c.nct_id,
           s.brief_title,
           s.overall_status,
           s.last_update_post_date,
           c.field_name,
           c.old_value,
           c.new_value,
           c.detected_at
    FROM study_changes c
    JOIN studies s ON s.nct_id = c.nct_id
    WHERE c.field_name = 'active_in_scope'
      AND c.detected_at >= %(since)s
      {condition_clause}
    ORDER BY c.detected_at DESC
"""

_CONDITION_EXISTS = """
      AND EXISTS (
          SELECT 1 FROM study_conditions sc
          WHERE sc.nct_id = {alias}.nct_id
            AND sc.condition ILIKE %(condition)s
      )
"""


@router.get("/investigate", response_model=InvestigateResponse)
def investigate(
    days: int = Query(
        DEFAULT_WINDOW_DAYS,
        ge=1,
        le=MAX_WINDOW_DAYS,
        description="How many days back to analyse. The record starts 2026-08-28; the response reports how far back it actually reaches.",
    ),
    condition: Optional[str] = Query(
        None,
        description="Restrict to trials tagged with a condition (substring match). Omit for everything tracked.",
    ),
    conn=Depends(get_readonly_db),
):
    """Cross-trial synthesis over the watch window.

    One response for one screen, the same shape /watch and /explore take:
    these findings are read together, and a slip count means something
    different depending on how many trials changed at all.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    params = {
        "since": since,
        "tracking_fields": sorted(TRACKING_FIELDS),
        "condition": f"%{condition}%" if condition else None,
    }

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            _AMENDMENT_SQL.format(
                condition_clause=_CONDITION_EXISTS.format(alias="a") if condition else ""
            ),
            params,
        )
        amendment_rows = cur.fetchall()

        cur.execute(
            _SCOPE_EXIT_SQL.format(
                condition_clause=_CONDITION_EXISTS.format(alias="c") if condition else ""
            ),
            params,
        )
        scope_rows = cur.fetchall()

        # The denominators (rule 1). Counted against the same condition
        # filter as the findings, or the whole watch when there is none.
        if condition:
            cur.execute(
                """
                SELECT count(*) AS tracked
                FROM studies s
                WHERE s.active_in_scope
                  AND EXISTS (
                      SELECT 1 FROM study_conditions sc
                      WHERE sc.nct_id = s.nct_id AND sc.condition ILIKE %(condition)s
                  )
                """,
                params,
            )
        else:
            cur.execute("SELECT count(*) AS tracked FROM studies WHERE active_in_scope")
        trials_tracked = cur.fetchone()["tracked"]

        # How far back the record actually reaches. A 90-day window over an
        # 8-day record must not report 82 quiet days it was never watching
        # (sec. 2) — the response carries this so the page can say so.
        cur.execute("SELECT min(detected_at) AS since FROM study_changes")
        recording_since = cur.fetchone()["since"]

    content_rows = [row for row in amendment_rows if row["field_name"] is not None]
    current_counts = {
        row["nct_id"]: row["current_enrollment_count"] for row in amendment_rows
    }
    trial_facts = {
        row["nct_id"]: {
            "primary_completion_date": row["primary_completion_date"],
            "start_date": row["start_date"],
            "has_results": row["has_results"],
            "org_class": row["org_class"],
        }
        for row in amendment_rows
    }
    outcome_changes, outcome_summary = analyse_outcome_changes(content_rows, trial_facts)
    amendments = {(row["nct_id"], row["detected_at"]) for row in amendment_rows}

    window = InvestigateWindow(
        days=days,
        since=since,
        until=datetime.now(timezone.utc),
        recording_since=recording_since,
        covers_full_window=recording_since is not None and recording_since <= since,
        condition=condition,
        trials_tracked=trials_tracked,
        trials_changed=len({row["nct_id"] for row in amendment_rows}),
        amendments=len(amendments),
        field_changes=len(content_rows),
    )

    return InvestigateResponse(
        window=window,
        dates=analyse_date_moves(content_rows),
        lifecycle=analyse_status_moves(content_rows),
        enrollment=analyse_enrollment(content_rows, current_counts),
        outcomes=OutcomeFinding(changes=outcome_changes[:NAMED_CAP], **outcome_summary),
        scope_exits=analyse_scope_exits(scope_rows)[:NAMED_CAP],
        scope_exits_total=len([r for r in scope_rows if str(r["new_value"]).strip().lower() in {"false", "f", "0"}]),
    )


# ============================================================================
# Primary-outcome changes — pure
# ============================================================================
#
# The one finding here that comes from outside evidence rather than from
# what the columns happened to allow (docs/decisions.md, 2026-09-04).
#
# Changing a trial's registered primary outcome after the data can be seen
# is a named, measured problem in the literature: 31.7% of registered
# ClinicalTrials.gov studies have had a primary outcome change
# (PMC4032105), the change is associated with funding source at OR 1.82
# (PMC5829948), and among 389 trials the 130 with an outcome change
# overstated their effect size by 16% (PMC6646984). The registry records
# every one of these and surfaces none of them.
#
# **This module never accuses anybody.** A changed endpoint has innocent
# explanations — a regulator asked, a typo was fixed, the wording was
# standardised — and TrialLens cannot tell which from the record alone.
# So every output here is phrased as CLAUDE.md sec. 2 requires: what
# changed, when it changed relative to the trial's own milestones, and
# that it requires review. Never a verdict, never a score.
#
# The deterministic half exists to STOP false alarms, not to raise them.
# NCT03674567 in the live record has results posted and changed its
# primary outcome after its primary completion date — the strongest flag
# combination available — and the change is "Safety and tolerability" to
# "Safety and Tolerability". Comparing normalised measure names catches
# that as wording, which is exactly why the normalisation runs before any
# flag is reported.

import json
import re

# Same rule as scripts/merge_entities.py: casefold plus punctuation only.
# Deliberately timid — it must never merge two genuinely different
# endpoints, because the cost of that is calling a real outcome change
# "wording".
_PUNCT = re.compile(r"[^\w\s]+")
_SPACE = re.compile(r"\s+")

# A leading list marker: "1. ", "2) ", "(3) ", "- ", "* ", "• ".
# Stripped BEFORE punctuation, because punctuation removal alone leaves
# the bare digit behind and "1 proportion of patients..." then reads as a
# different endpoint from "proportion of patients...". That is not
# hypothetical: NCT05327608 in the live record renumbered its only
# primary outcome and was reported as a substantive change until this
# ran. On a finding phrased around research integrity, a false positive
# is the expensive kind of wrong.
#
# The digit must be followed by "." or ")" AND whitespace, so a real
# measure beginning with a number survives — "6-minute walk distance" and
# "30 day mortality" are endpoints, not list items.
_LIST_MARKER = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|[-*\u2022])\s+")


def normalise_measure(text) -> str:
    """An outcome name reduced to what a rename cannot change."""
    if text is None:
        return ""
    stripped = _LIST_MARKER.sub("", str(text).casefold())
    return _SPACE.sub(" ", _PUNCT.sub(" ", stripped)).strip()


def outcome_measures(value):
    """The measure names in a stored primary_outcomes value, or None.

    None means the value could not be read as a list of outcomes, and is
    counted rather than treated as an empty list — an unreadable side
    silently becoming [] would report every measure as removed.
    """
    if value is None:
        return None
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (ValueError, TypeError):
            return None
    if not isinstance(parsed, list):
        return None
    measures = []
    for item in parsed:
        if isinstance(item, dict):
            measures.append(str(item.get("measure") or ""))
        else:
            measures.append(str(item))
    return measures


# Each flag is a fact the record states, paired with the sentence a reader
# sees. No weights, no total, no score — sec. 3 forbids a ranking whose
# reasoning is invisible, and step 7 was removed for exactly that.
FLAG_LABELS = {
    "after_primary_completion": "changed after the trial's primary completion date",
    "after_start": "changed after the trial started",
    "results_posted": "the trial has already posted results",
    "industry_sponsored": "industry-sponsored lead",
}

# Ordered strongest first. "After primary completion" is the one the
# literature treats as the real signal: before that date nobody has seen
# the endpoint data, so a change is ordinary protocol maintenance.
FLAG_ORDER = ["after_primary_completion", "results_posted", "after_start", "industry_sponsored"]


def outcome_flags(detected_at, facts) -> List[str]:
    """Which red flags the record states for one outcome change.

    `facts` carries the trial's own milestones. A missing milestone yields
    no flag rather than a default — "the registry did not say when this
    trial finishes" is not evidence of anything, and treating a NULL as
    "before" would flag every trial with an unstated date.
    """
    facts = facts or {}
    flags = []
    changed_on = detected_at.date() if hasattr(detected_at, "date") else detected_at

    for key, field in (
        ("after_primary_completion", "primary_completion_date"),
        ("after_start", "start_date"),
    ):
        milestone = parse_partial_date(facts.get(field))
        if milestone is None:
            continue
        milestone_date, month_only = milestone
        if month_only:
            # A month-precision milestone is only passed once the whole
            # month is over. Anchoring to the 1st and comparing directly
            # would flag a change made mid-month as "after".
            if (changed_on.year, changed_on.month) <= (milestone_date.year, milestone_date.month):
                continue
        elif changed_on <= milestone_date:
            continue
        flags.append(key)

    if facts.get("has_results"):
        flags.append("results_posted")
    if facts.get("org_class") == "INDUSTRY":
        flags.append("industry_sponsored")
    return [f for f in FLAG_ORDER if f in flags]


def analyse_outcome_changes(rows, trial_facts=None):
    """Primary-outcome changes, with reformatting separated from real ones.

    Returns (changes, summary_counts). Wording-only changes are KEPT and
    counted, never dropped: "8 outcome changes, 5 of them reformatting" is
    a much more useful sentence than "3 outcome changes", and dropping the
    five would also hide the fact that the normalisation is doing work.
    """
    from api.schemas import OutcomeChange  # local: avoids a schema import cycle

    trial_facts = trial_facts or {}
    changes: List[OutcomeChange] = []
    unreadable = 0

    for row in rows:
        if row["field_name"] != "primary_outcomes":
            continue
        before = outcome_measures(row["old_value"])
        after = outcome_measures(row["new_value"])
        if before is None or after is None:
            unreadable += 1
            continue

        before_map = {normalise_measure(m): m for m in before}
        after_map = {normalise_measure(m): m for m in after}
        added = [after_map[k] for k in after_map if k and k not in before_map]
        removed = [before_map[k] for k in before_map if k and k not in after_map]
        wording_only = not added and not removed

        interpretation = row.get("prose_interpretation")
        if isinstance(interpretation, dict):
            interpretation = interpretation.get("summary")

        flags = outcome_flags(row["detected_at"], trial_facts.get(row["nct_id"]))
        changes.append(
            OutcomeChange(
                nct_id=row["nct_id"],
                brief_title=row["brief_title"],
                measures_added=added,
                measures_removed=removed,
                count_before=len(before),
                count_after=len(after),
                wording_only=wording_only,
                flags=flags,
                flag_labels=[FLAG_LABELS[f] for f in flags],
                interpretation=interpretation,
                detected_at=row["detected_at"],
            )
        )

    # Substantive changes first, then by how much the record has to say
    # about them. Within that, the strongest flag decides — never a summed
    # score, which is the invisible ranking sec. 3 forbids.
    changes.sort(
        key=lambda c: (
            c.wording_only,
            -len(c.flags),
            FLAG_ORDER.index(c.flags[0]) if c.flags else len(FLAG_ORDER),
        )
    )
    summary = {
        "total": len(changes),
        "wording_only": sum(1 for c in changes if c.wording_only),
        "substantive": sum(1 for c in changes if not c.wording_only),
        "after_primary_completion": sum(
            1 for c in changes if not c.wording_only and "after_primary_completion" in c.flags
        ),
        "unreadable": unreadable,
    }
    return changes, summary


# ============================================================================
# The landscape — what has been done in this area
# ============================================================================
#
# A different question from everything above, and the reason this endpoint
# exists separately: "what changed this week" is answered from
# study_changes, "what has been done in breast cancer" is answered from
# studies. Nothing in TrialLens answered the second one — Explore answers
# it per trial, Monitor per change.
#
# Three honesty rules, each one a way of not describing a tidier field
# than the one that exists:
#
#   1. **The unstated share stays in the picture.** 2,838 of 5,377
#      breast-cancer trials report a phase of NA or nothing (53%). A phase
#      chart that drops them is describing a different corpus.
#   2. **The current year is not a data point yet.** 2025 started 899
#      trials and 2026 shows 756 in September — drawn side by side that is
#      a decline, and it is the calendar. Future years are *planned*
#      starts, which is a third thing again. Both are labelled.
#   3. **A term's reach is measured against trials that list any
#      intervention**, not against the slice. 4,938 of 5,377 do.

# Enough to see the shape of a field without turning a chart into a list.
LANDSCAPE_TERM_CAP = 15
LANDSCAPE_SPONSOR_CAP = 10
# Years before this are a long tail of a few rows each. They are rolled
# into ONE bucket rather than dropped: cutting them made the first bar look
# like the beginning of the field, and breast cancer research did not start
# in 2010 — 153 tracked breast-cancer trials began earlier, the oldest in
# 1989. Reported 2026-09-04 from real use.
LANDSCAPE_FIRST_YEAR = 2010
EARLIER_LABEL = f"Before {LANDSCAPE_FIRST_YEAR}"

_SLICE = """
    EXISTS (SELECT 1 FROM study_conditions sc
            WHERE sc.nct_id = s.nct_id AND sc.condition ILIKE %(condition)s)
"""

# Phase values that are not a phase. 'NA' is CT.gov's own marker for a
# trial that does not use phases at all (most behavioural and device
# studies) — a real answer, but not a rung on the phase ladder, so it is
# counted with the unstated rather than plotted beside PHASE3.
_NON_PHASES = ("NA",)


@router.get("/investigate/landscape", response_model=LandscapeResponse)
def landscape(
    condition: Optional[str] = Query(
        None, description="Restrict to trials tagged with a condition (substring match). Omit for the whole watch."
    ),
    conn=Depends(get_readonly_db),
):
    """What the tracked corpus looks like — the field, not the week."""
    where = "s.active_in_scope" + (f" AND {_SLICE}" if condition else "")
    params = {"condition": f"%{condition}%" if condition else None}
    this_year = datetime.now(timezone.utc).year

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

        def rows(sql):
            cur.execute(sql, params)
            return cur.fetchall()

        trials = rows(f"SELECT count(*) AS n FROM studies s WHERE {where}")[0]["n"]

        # Year of first enrolment. left(start_date, 4) rather than a cast:
        # the column is TEXT precisely because ~23% of these are
        # month-precision, and a cast would reject them.
        year_rows = rows(f"""
            SELECT left(s.start_date, 4) AS yr, count(*) AS n
            FROM studies s
            WHERE {where} AND s.start_date IS NOT NULL
              AND left(s.start_date, 4) ~ '^[0-9]{{4}}$'
            GROUP BY 1 ORDER BY 1
        """)
        started_per_year = []
        earlier = 0
        earliest_year = None
        for row in year_rows:
            year = int(row["yr"])
            if year < LANDSCAPE_FIRST_YEAR:
                # Rolled up, not discarded. The bucket's note names the real
                # earliest year so the chart cannot imply the field began at
                # the cut-off.
                earlier += row["n"]
                earliest_year = row["yr"] if earliest_year is None else earliest_year
                continue
            note = None
            if year > this_year:
                note = "planned start"
            elif year == this_year:
                note = "part year so far"
            started_per_year.append(
                LandscapeBucket(label=row["yr"], count=row["n"], note=note)
            )
        if earlier:
            started_per_year.insert(
                0,
                LandscapeBucket(
                    label=EARLIER_LABEL,
                    count=earlier,
                    note=f"{earlier:,} trials, earliest {earliest_year}",
                ),
            )

        phase_rows = rows(f"""
            SELECT coalesce(s.phase, '(not stated)') AS label, count(*) AS n
            FROM studies s WHERE {where} GROUP BY 1 ORDER BY 2 DESC
        """)
        phases = LandscapeCategory(
            buckets=[
                LandscapeBucket(label=r["label"], count=r["n"])
                for r in phase_rows
                if r["label"] not in _NON_PHASES and r["label"] != "(not stated)"
            ],
            stated=sum(
                r["n"] for r in phase_rows
                if r["label"] not in _NON_PHASES and r["label"] != "(not stated)"
            ),
            unstated=sum(
                r["n"] for r in phase_rows
                if r["label"] in _NON_PHASES or r["label"] == "(not stated)"
            ),
            unstated_label="no phase stated, or not a phased study",
        )

        status_rows = rows(f"""
            SELECT s.overall_status AS label, count(*) AS n
            FROM studies s WHERE {where} GROUP BY 1 ORDER BY 2 DESC
        """)
        statuses = LandscapeCategory(
            buckets=[LandscapeBucket(label=r["label"], count=r["n"]) for r in status_rows],
            stated=sum(r["n"] for r in status_rows),
        )

        # Bands rather than a histogram: enrollment spans 1 to five figures
        # and a linear axis renders the whole field as one bar at zero.
        band_rows = rows(f"""
            SELECT CASE
                     WHEN s.enrollment_count < 50   THEN '1-49'
                     WHEN s.enrollment_count < 100  THEN '50-99'
                     WHEN s.enrollment_count < 250  THEN '100-249'
                     WHEN s.enrollment_count < 500  THEN '250-499'
                     WHEN s.enrollment_count < 1000 THEN '500-999'
                     ELSE '1000+'
                   END AS label,
                   count(*) AS n
            FROM studies s WHERE {where} AND s.enrollment_count IS NOT NULL
            GROUP BY 1
        """)
        order = ["1-49", "50-99", "100-249", "250-499", "500-999", "1000+"]
        by_label = {r["label"]: r["n"] for r in band_rows}
        enrollment_bands = [
            LandscapeBucket(label=label, count=by_label.get(label, 0)) for label in order
        ]

        # canonical_id resolves the merged spellings (step 8 unit 3), read
        # as coalesce(canonical_id, id) — NULL means the row IS canonical.
        # Two aliases, never a self-join: joining intervention_terms to
        # itself on coalesce(canonical_id, id) cross-products the table and
        # reports every term with the same count.
        term_rows = rows(f"""
            SELECT canon.name AS name, canon.type AS type,
                   count(DISTINCT ti.nct_id) AS trials
            FROM trial_interventions ti
            JOIN intervention_terms raw   ON raw.id = ti.term_id
            JOIN intervention_terms canon ON canon.id = coalesce(raw.canonical_id, raw.id)
            JOIN studies s ON s.nct_id = ti.nct_id
            WHERE {where}
            GROUP BY 1, 2 ORDER BY trials DESC, name
            LIMIT {LANDSCAPE_TERM_CAP}
        """)
        interventions_denominator = rows(f"""
            SELECT count(DISTINCT ti.nct_id) AS n
            FROM trial_interventions ti JOIN studies s ON s.nct_id = ti.nct_id
            WHERE {where}
        """)[0]["n"]

        sponsor_rows = rows(f"""
            SELECT o.name AS name, count(DISTINCT tо.nct_id) AS trials
            FROM trial_organizations tо
            JOIN organizations o ON o.id = tо.org_id
            JOIN studies s ON s.nct_id = tо.nct_id
            WHERE tо.role = 'LEAD' AND {where}
            GROUP BY 1 ORDER BY trials DESC, name
            LIMIT {LANDSCAPE_SPONSOR_CAP}
        """)

        results_posted = rows(f"""
            SELECT count(*) AS n FROM studies s WHERE {where} AND s.has_results
        """)[0]["n"]

    return LandscapeResponse(
        condition=condition,
        trials=trials,
        started_per_year=started_per_year,
        phases=phases,
        statuses=statuses,
        enrollment_bands=enrollment_bands,
        enrollment_stated=sum(b.count for b in enrollment_bands),
        interventions=[InterventionUse(**r) for r in term_rows],
        interventions_denominator=interventions_denominator,
        sponsors=[SponsorActivity(**r) for r in sponsor_rows],
        results_posted=results_posted,
    )


# How many trials come back behind one landscape bar. Paclitaxel reaches
# 163 breast-cancer trials and nobody reads past the first screen; the real
# total travels with the list, so a cap never reads as the whole answer.
LANDSCAPE_TRIALS_CAP = 50


@router.get("/investigate/trials", response_model=LandscapeTrials)
def landscape_trials(
    intervention: str = Query(..., description="Canonical intervention term name."),
    intervention_type: str = Query(
        ..., description="The term's type (DRUG, DEVICE, BEHAVIORAL, ...). Required: see below."
    ),
    condition: Optional[str] = Query(None, description="Restrict to a tracked condition."),
    conn=Depends(get_readonly_db),
):
    """The trials behind one bar of the 'what is being tested' chart.

    Added 2026-09-04: the chart said 163 breast-cancer trials test
    Paclitaxel and there was no way to ask which ones, which makes the bar
    a dead end. Reported from real use.

    Matched on the CANONICAL term, so a click on one bar returns the trials
    filed under every spelling that merged into it (step 8 unit 3) — the
    same `coalesce(canonical_id, id)` the chart itself counts through.

    **`intervention_type` is required, not optional, because the chart
    groups by (name, type) and a name alone is not a bar.** "Paclitaxel"
    exists as a DRUG on 163 breast-cancer trials and as a
    COMBINATION_PRODUCT on 1; matching the name alone returned 164 for a
    bar that said 163. A drill-down that disagrees with the chart it came
    from is worse than no drill-down. Caught before shipping, 2026-09-04.
    """
    where = "s.active_in_scope" + (f" AND {_SLICE}" if condition else "")
    params = {
        "condition": f"%{condition}%" if condition else None,
        "intervention": intervention,
        "intervention_type": intervention_type,
        "cap": LANDSCAPE_TRIALS_CAP,
    }
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT DISTINCT
                   s.nct_id, s.brief_title, s.overall_status, s.phase,
                   s.enrollment_count, s.start_date, s.has_results,
                   count(*) OVER () AS total
            FROM studies s
            JOIN trial_interventions ti ON ti.nct_id = s.nct_id
            JOIN intervention_terms raw ON raw.id = ti.term_id
            JOIN intervention_terms canon
                 ON canon.id = coalesce(raw.canonical_id, raw.id)
            WHERE {where} AND canon.name = %(intervention)s
              AND canon.type = %(intervention_type)s
            ORDER BY s.overall_status, s.nct_id
            LIMIT %(cap)s
            """,
            params,
        )
        rows = cur.fetchall()

    return LandscapeTrials(
        intervention=intervention,
        condition=condition,
        trials=[
            LandscapeTrial(**{k: v for k, v in row.items() if k != "total"}) for row in rows
        ],
        total=rows[0]["total"] if rows else 0,
    )
