"""What an amendment actually did — decided in code, not by a model.

CLAUDE.md sec. 5 is "deterministic first, AI second". Everything here is a
lookup or arithmetic over values ClinicalTrials.gov already stated, so a
model asked to produce it could only be slower, dearer, and occasionally
wrong. It carries the literal stored values as its evidence (sec. 3).

Two jobs:

  1. **Which aspect of the trial an amendment touched** — scientific,
     operational, or administrative. This is a field-name lookup. It was
     briefly considered as a model call; the data said otherwise (14
     distinct content fields, all of them mappable), and paying a model for
     a verdict code produces exactly is the mistake step 7 already made.

  2. **A plain-language effect for the field kinds where arithmetic has a
     real answer** — a date that slipped, a headcount that moved, a target
     that became an actual, sites added or removed.

Every function here returns None rather than guessing. A description that
cannot be computed honestly is not produced at all, and the UI falls back
to showing the stored values — never to an invented summary (sec. 2).

**What is deliberately NOT here:** any claim about what a *prose* change
means. "The eligibility criteria changed by +40/-12 words" is arithmetic;
"the trial narrowed its population" is a reading of clinical text, and this
module does not attempt it. That is the one place a model would genuinely
earn its cost, and it is not built yet.
"""
import json
from datetime import date
from typing import Optional

# ============================================================================
# Which aspect of the trial did this touch?
# ============================================================================
#
# Counts are real, from the live database on 2026-09-01, and are here so the
# mapping can be judged against how often each field actually moves rather
# than against how important it sounds.

ASPECT_SCIENTIFIC = "Scientific"
ASPECT_OPERATIONAL = "Operational"
ASPECT_ADMINISTRATIVE = "Administrative"

FIELD_ASPECTS = {
    # What the trial is studying, and on whom. A change here can change what
    # the trial means — these are the ones worth a researcher's attention.
    "primary_outcomes": ASPECT_SCIENTIFIC,      # 9 changes / 9 trials
    "eligibility_criteria": ASPECT_SCIENTIFIC,  # 14 / 14
    "brief_summary": ASPECT_SCIENTIFIC,         # 19 / 16
    "interventions": ASPECT_SCIENTIFIC,         # 5 / 5
    "healthy_volunteers": ASPECT_SCIENTIFIC,    # 1 / 1
    "has_results": ASPECT_SCIENTIFIC,           # tracked from 2026-09-02

    # How the trial is running: is it recruiting, how many, when, where.
    # Real but rarely a change in the science.
    "overall_status": ASPECT_OPERATIONAL,           # 24 / 24
    "enrollment_count": ASPECT_OPERATIONAL,         # 10 / 10
    "enrollment_type": ASPECT_OPERATIONAL,          # 8 / 8
    "start_date": ASPECT_OPERATIONAL,               # 18 / 12
    "primary_completion_date": ASPECT_OPERATIONAL,  # 25 / 25
    "completion_date": ASPECT_OPERATIONAL,          # 25 / 25
    "locations": ASPECT_OPERATIONAL,                # 20 / 19

    # How the record describes itself. A retitle is not a protocol change.
    # Kept separate rather than called "minor": an official title rewrite
    # can accompany a real change, and the amendment's other fields will
    # say so — this only claims the title itself isn't the science.
    "brief_title": ASPECT_ADMINISTRATIVE,     # 7 / 7
    "official_title": ASPECT_ADMINISTRATIVE,  # 10 / 10
}

# Ordered most-consequential first: a researcher scanning an amendment
# should meet a rewritten primary outcome before a retitle.
ASPECT_ORDER = [ASPECT_SCIENTIFIC, ASPECT_OPERATIONAL, ASPECT_ADMINISTRATIVE]


def field_aspect(field_name: str) -> Optional[str]:
    """Which aspect of the trial a field belongs to, or None if unmapped.

    None is deliberate and must stay visible in the UI: a field CT.gov
    starts reporting that nobody has classified should appear as
    "uncategorised", not get silently filed under Administrative, which
    would quietly downgrade something nobody has looked at yet.
    """
    return FIELD_ASPECTS.get(field_name)


# ============================================================================
# What did it actually do? Arithmetic only.
# ============================================================================

def _parse_partial_date(value: Optional[str]):
    """A CT.gov date, which may be month-precision only.

    Returns (date, is_month_only) or None. ~23% of trials report these as
    "2027-06" with no day (verified 2026-08-29, which is why these columns
    are TEXT). A month-only value is anchored to the 1st for arithmetic —
    never displayed as a day, and never treated as precise.
    """
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 7:  # "2027-06"
            year, month = text.split("-")
            return date(int(year), int(month), 1), True
        return date.fromisoformat(text), False
    except (ValueError, TypeError):
        return None


def describe_date_shift(old_value, new_value) -> Optional[str]:
    """"Slipped by about 11 months", or None when it can't be said honestly.

    Reported in months or weeks rather than exact days whenever either side
    is month-precision: saying "slipped 361 days" about a date CT.gov only
    gave to the month would invent precision the registry never stated
    (sec. 2).
    """
    old = _parse_partial_date(old_value)
    new = _parse_partial_date(new_value)
    if old is None or new is None:
        return None

    (old_date, old_partial), (new_date, new_partial) = old, new
    delta_days = (new_date - old_date).days
    if delta_days == 0:
        return None

    direction = "later" if delta_days > 0 else "earlier"
    magnitude = abs(delta_days)
    imprecise = old_partial or new_partial

    if magnitude >= 60:
        months = round(magnitude / 30.44)
        unit = f"{months} month{'s' if months != 1 else ''}"
    elif magnitude >= 14:
        weeks = round(magnitude / 7)
        unit = f"{weeks} week{'s' if weeks != 1 else ''}"
    elif imprecise:
        # Under two weeks, with month-only input, the difference is an
        # artefact of anchoring to the 1st — not a real shift worth stating.
        return None
    else:
        unit = f"{magnitude} day{'s' if magnitude != 1 else ''}"

    about = "about " if imprecise or magnitude >= 14 else ""
    verb = "pushed" if delta_days > 0 else "pulled"
    return f"{verb} {about}{unit} {direction}"


def describe_count_shift(old_value, new_value) -> Optional[str]:
    """"Increased by 40" for a headcount. None if either side isn't a number."""
    try:
        old_n, new_n = int(old_value), int(new_value)
    except (TypeError, ValueError):
        return None
    if old_n == new_n:
        return None
    delta = new_n - old_n
    word = "increased" if delta > 0 else "reduced"
    return f"{word} by {abs(delta):,}"


def describe_enrollment_type(
    old_value, new_value, count_before=None, count_after=None
) -> Optional[str]:
    """ESTIMATED -> ACTUAL is a genuinely meaningful switch, and it reads as
    noise unless it's spelled out: the number stopped being a recruitment
    target and became a real headcount. See docs/decisions.md, 2026-08-30 —
    6,577 of 11,482 records report a target rather than a count.

    **The numbers are the story, and until 2026-09-02 this sentence had
    none.** One real amendment (NCT03402139, 31 August) switched a target of
    400 to an actual count of 163 — a trial that enrolled 59% fewer people
    than it planned — and the page said only "the recruitment target was
    replaced by a real enrolled count". The most consequential fact in the
    amendment was the one clause that omitted it.

    Both counts are optional and the sentence degrades honestly without
    them, because the caller cannot always establish which number was true
    at this amendment (see the callers in api/studies.py and api/watch.py).
    A number that cannot be tied to THIS amendment is not stated at all
    rather than borrowed from the trial's present (CLAUDE.md sec. 2).
    """
    if old_value == "ESTIMATED" and new_value == "ACTUAL":
        if count_before is not None and count_after is not None:
            if count_before != count_after:
                return (
                    f"the target of {count_before:,} was replaced by a real "
                    f"count of {count_after:,}"
                )
            # The count itself never moved — the sponsor confirmed the number
            # they had projected. "Replaced by" would be wrong here: nothing
            # was replaced except the number's status.
            return f"the target of {count_after:,} was confirmed as the real enrolled count"
        if count_after is not None:
            return f"the real enrolled count is {count_after:,}"
        return "the recruitment target was replaced by a real enrolled count"
    if old_value == "ACTUAL" and new_value == "ESTIMATED":
        return "a real enrolled count was replaced by a target — unusual; worth a look"
    return None


def _json_list(value):
    try:
        parsed = json.loads(value) if value else []
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def describe_list_shift(old_value, new_value, noun: str) -> Optional[str]:
    """"6 sites added, 1 removed" for locations/interventions.

    Also the reason these fields never reach a prompt or a diff view: one
    real amendment carries 265,612 characters of locations JSON, and the
    honest summary of it is two numbers. Compares whole entries, so a
    facility that merely changed city counts as one removed and one added —
    a slight over-count, and the safer direction: it says "something moved
    here" rather than silently reporting no change.
    """
    old_items, new_items = _json_list(old_value), _json_list(new_value)
    if old_items is None or new_items is None:
        return None

    old_keys = {json.dumps(i, sort_keys=True) for i in old_items}
    new_keys = {json.dumps(i, sort_keys=True) for i in new_items}
    added, removed = len(new_keys - old_keys), len(old_keys - new_keys)
    if not added and not removed:
        return None

    parts = []
    if added:
        parts.append(f"{added} {noun}{'s' if added != 1 else ''} added")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts)


# The eight statuses that actually occur in the database (queried
# 2026-09-01), not the longer list the CT.gov docs imply — and note
# "CLOSED", which an earlier prompt taught a model, is not among them.
# Grouped by what a change between them means for a researcher who wants to
# know whether they can still refer a patient.
_STATUS_OPEN = {"RECRUITING", "ENROLLING_BY_INVITATION"}
_STATUS_UNDERWAY_CLOSED = {"ACTIVE_NOT_RECRUITING"}
_STATUS_FINISHED = {"COMPLETED"}
_STATUS_STOPPED = {"TERMINATED", "SUSPENDED", "WITHDRAWN"}
_STATUS_PENDING = {"NOT_YET_RECRUITING"}


def describe_results_posting(old_value, new_value) -> Optional[str]:
    """false -> true means the trial's findings are published.

    This is the most consequential amendment a researcher can receive, and
    until 2026-09-02 TrialLens did not store the field at all — every one of
    these was reported as "amended, but we can't see what". 1,056 of 11,518
    stored trials already had results posted when the column was added.

    Values arrive stringified from study_changes ("true"/"false"), so both
    forms are accepted rather than assuming one.
    """
    def truthy(value):
        return str(value).strip().lower() in {"true", "t", "1"}

    if old_value is None or new_value is None or old_value == new_value:
        return None
    if not truthy(old_value) and truthy(new_value):
        return "results have been posted — the trial's findings are now published"
    if truthy(old_value) and not truthy(new_value):
        return "posted results were withdrawn — unusual; worth a look"
    return None


def describe_status_change(old_value, new_value) -> Optional[str]:
    """What a status transition means in practice.

    Every transition below is one that actually occurs in the data — the
    five observed on 2026-09-01 are RECRUITING->COMPLETED (7),
    NOT_YET_RECRUITING->RECRUITING (7), RECRUITING->ACTIVE_NOT_RECRUITING
    (5), ACTIVE_NOT_RECRUITING->COMPLETED (4), ACTIVE_NOT_RECRUITING->
    RECRUITING (1). The rules are written over status *groups* rather than
    that observed list, so a transition nobody has seen yet still gets a
    correct answer instead of falling through to None.

    Says nothing about whether any individual could join a trial — that is
    an eligibility claim, and sec. 2 forbids it. "Open to new participants"
    is a statement about the trial's own registered status.
    """
    if not old_value or not new_value or old_value == new_value:
        return None

    if old_value in _STATUS_PENDING and new_value in _STATUS_OPEN:
        return "opened to enrolment"
    if new_value in _STATUS_STOPPED:
        return f"stopped early ({new_value.lower()}) — worth reading why"
    if new_value in _STATUS_FINISHED:
        return "finished — results may start appearing"
    if old_value in _STATUS_OPEN and new_value in _STATUS_UNDERWAY_CLOSED:
        return "closed to new participants, still running"
    if old_value in _STATUS_UNDERWAY_CLOSED and new_value in _STATUS_OPEN:
        return "reopened to new participants"
    if new_value in _STATUS_OPEN:
        return "now open to new participants"
    return None


_DATE_FIELDS = {"start_date", "primary_completion_date", "completion_date"}
_LIST_FIELDS = {"locations": "site", "interventions": "intervention"}


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def enrollment_context(changes, count_after):
    """The two enrollment numbers belonging to ONE amendment.

    `changes` are that amendment's own field changes (anything with
    `.field_name` / `.old_value` / `.new_value`). `count_after` is the count
    in force immediately AFTER this amendment, which only the caller can
    know — it is the trial's current count for the newest amendment, and
    something older for anything before it.

    Returns `(context, count_before)`. The second value is the count in
    force before this amendment, which is exactly what a caller walking
    backwards through a trial's history needs for the next-older one.

    Why this is not simply "read the trial's enrollment_count": that is the
    count as of *today*, and attributing today's number to an amendment from
    three weeks ago would state a fact about the trial that was not true
    when it happened (CLAUDE.md sec. 2). Only two situations give an honest
    answer — the amendment moved the count itself (the row says both
    numbers), or nothing has moved it since (today's number was also that
    day's). The caller establishes which.
    """
    for change in changes:
        if getattr(change, "field_name", None) != "enrollment_count":
            continue
        before = _as_int(getattr(change, "old_value", None))
        after = _as_int(getattr(change, "new_value", None))
        if after is not None:
            # The row is authoritative: it states both sides of this exact
            # amendment, so it overrides whatever the caller passed in.
            return (
                {"enrollment_count_before": before, "enrollment_count_after": after},
                before,
            )

    # The count did not move in this amendment, so whatever was true after
    # it was also true before it.
    return (
        {"enrollment_count_before": count_after, "enrollment_count_after": count_after},
        count_after,
    )


def describe_effect(field_name: str, old_value, new_value, context=None) -> Optional[str]:
    """The one entry point: a plain-language effect, or None.

    None is the common and correct answer — for prose fields it is the ONLY
    answer this module will give, because summarising what a rewritten
    eligibility criterion now means is a reading of clinical text, not
    arithmetic.

    `context` carries facts about the amendment that are NOT in this row.
    Only enrollment_type reads it today, and only for the two counts, which
    live on a sibling row (or on no row at all, when the number did not
    change). Optional everywhere: an endpoint that cannot establish the
    context honestly passes nothing and gets the numberless sentence, which
    is still true.
    """
    context = context or {}
    if field_name in _DATE_FIELDS:
        return describe_date_shift(old_value, new_value)
    if field_name == "has_results":
        return describe_results_posting(old_value, new_value)
    if field_name == "overall_status":
        return describe_status_change(old_value, new_value)
    if field_name == "enrollment_count":
        return describe_count_shift(old_value, new_value)
    if field_name == "enrollment_type":
        return describe_enrollment_type(
            old_value,
            new_value,
            count_before=context.get("enrollment_count_before"),
            count_after=context.get("enrollment_count_after"),
        )
    if field_name in _LIST_FIELDS:
        return describe_list_shift(old_value, new_value, _LIST_FIELDS[field_name])
    return None
