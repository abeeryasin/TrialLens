"""Pydantic models: FastAPI's input validation and response typing.

A Pydantic model isn't just documentation — FastAPI actually checks
incoming JSON against it before your route code runs (wrong type, missing
required field -> 422 response, route code never executes), and uses it
to build the response JSON on the way out.

Uses typing.Optional/List/Dict rather than the `X | None` syntax: this
project's venv is Python 3.9, and Pydantic evaluates annotations at
runtime, which the newer union syntax doesn't support there.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Intervention(BaseModel):
    """What's actually being done to participants — a drug, device, or
    procedure. The single most-requested field after title/condition in a
    real study of what researchers find helpful in a results list (see
    docs/decisions.md, 2026-08-29)."""

    type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class OutcomeMeasure(BaseModel):
    """What defines success for the trial — e.g. "Alpha diversity of the
    periodontal microbiota using Chao-1 index" (a real primary outcome,
    not an abstraction)."""

    measure: Optional[str] = None
    description: Optional[str] = None
    time_frame: Optional[str] = None


class TrialLocation(BaseModel):
    facility: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class StudySummary(BaseModel):
    """One row in a GET /studies list — enough to identify and triage a trial."""

    nct_id: str
    brief_title: str
    overall_status: str
    phase: Optional[str] = None
    last_update_post_date: date
    active_in_scope: bool


class StudyDetail(StudySummary):
    """Everything for GET /studies/{nct_id} — full normalized record + conditions."""

    official_title: Optional[str] = None
    study_type: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED — see ctgov_client.py
    has_results: Optional[bool] = None  # CT.gov has posted results for this trial
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    fetched_at: datetime
    last_matched_at: datetime
    conditions: List[str] = []
    brief_summary: Optional[str] = None
    lead_sponsor: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    interventions: List[Intervention] = []
    primary_outcomes: List[OutcomeMeasure] = []
    locations: List[TrialLocation] = []


# Every column a StudyDetail (or TrialDetail — same DB-backed field set)
# needs, and nothing else. Use this instead of `SELECT *`.
#
# `SELECT *` also fetches raw_json, the untouched CT.gov response. Nothing
# reads it — Pydantic silently drops the extra key — but it is 8.7 KB per
# row and 95 MB of the table's 137 MB (measured 2026-08-31, 11,469 active
# trials), so every full-table read spent 69% of its bytes on a column that
# was thrown away on arrival. That is billable egress on Neon's free tier,
# which is 5 GB/month; see docs/decisions.md.
#
# Derived from the model rather than typed out, so a new field can't drift
# out of sync with the query that has to fetch it.
STUDY_DETAIL_COLUMNS = ", ".join(
    name for name in StudyDetail.model_fields if name != "conditions"
)


class StudyList(BaseModel):
    total: int
    limit: int
    offset: int
    results: List[StudySummary]


class StudyUpsert(BaseModel):
    """One study as written by ingest.py, matching extract_fields() in ctgov_client.py."""

    nct_id: str
    brief_title: str
    official_title: Optional[str] = None
    overall_status: str
    study_type: Optional[str] = None
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED — see ctgov_client.py
    has_results: Optional[bool] = None  # CT.gov has posted results for this trial
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    last_update_post_date: date
    conditions: List[str] = []
    raw_json: Dict[str, Any]
    brief_summary: Optional[str] = None
    lead_sponsor: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    interventions: List[Intervention] = []
    primary_outcomes: List[OutcomeMeasure] = []
    locations: List[TrialLocation] = []


class BatchUpsertResult(BaseModel):
    studies_written: int
    condition_tags_written: int
    changes_detected: int


class StudyChange(BaseModel):
    """One detected field-level change — the real Monitor changelog entry."""

    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detected_at: datetime
    # "Trial content" or "Tracking" — see api/tracking.py. Set by the route,
    # not stored; it's a property of the field, not of the row.
    category: Optional[str] = None


class StudyChangeList(BaseModel):
    nct_id: str
    changes: List[StudyChange]


class AmendedField(StudyChange):
    """One field that moved inside an amendment, with what code can say
    about it — never what a model thinks it means."""

    aspect: Optional[str] = None
    # "Scientific" | "Operational" | "Administrative", from api/amendments.py.
    # None means the field is not yet classified, and the UI shows it as
    # uncategorised rather than filing it under the least alarming bucket.

    effect: Optional[str] = None
    # A plain-language, arithmetic-only effect: "pushed about 12 months
    # later", "6 sites added", "the recruitment target was replaced by a
    # real enrolled count". None whenever no honest computation exists —
    # which is always the case for prose fields, where saying what a
    # rewrite MEANS would be a reading of clinical text, not a calculation.


class Amendment(BaseModel):
    """One amendment ClinicalTrials.gov posted to a trial, and what moved.

    Dated by the registry's own version stamp (`posted_on`), not by when
    TrialLens noticed. Those differ — the cron runs every 6 hours, and a
    trial first seen after a long gap can carry a stamp weeks older than
    our detection. The registry's date is the fact about the trial; ours is
    a fact about our scheduler.
    """

    posted_on: date
    # CT.gov's last_update_post_date AFTER this amendment.

    previously_posted_on: Optional[date] = None
    # ...and before it. Together these say "this record went from the
    # version posted on X to the version posted on Y".

    detected_at: datetime
    # When TrialLens saw it. Always >= posted_on, often by hours or more.

    changes: List[AmendedField] = []
    # The trial-content fields that moved in this amendment. Empty is a
    # real and common answer — see content_is_visible.

    aspects: List[str] = []
    # Which aspects this amendment touched ("Scientific", "Operational",
    # "Administrative"), most consequential first. Lets a reader see that a
    # primary outcome was rewritten without reading every row.

    content_is_visible: bool = True
    # False when CT.gov posted an amendment but every field it touched is
    # one TrialLens does not store (47% of amendments, measured 2026-09-01).
    # The UI MUST render this as "amended, but we can't see what" and never
    # as "no changes" — the latter is a false claim about a study fact
    # (CLAUDE.md sec. 2). Absence of visible changes is not absence of
    # change.


class AmendmentHistory(BaseModel):
    """A trial's amendments, newest first — the thing ClinicalTrials.gov
    structurally cannot show, because it holds only the current version."""

    nct_id: str
    amendments: List[Amendment] = []
    total_amendments: int = 0

    invisible_amendment_count: int = 0
    # How many of the above touched only untracked fields. Surfaced as a
    # number so the page can be honest about its own blind spot rather than
    # leaving the reader to count flagged rows.

    recording_since: Optional[datetime] = None
    # When TrialLens began recording changes AT ALL — the earliest
    # detected_at in the whole table, not this trial's own start date.
    # Deliberately a global fact: no per-trial "first observed" column
    # exists, so claiming this trial was watched from that date would
    # overstate what is known about it (sec. 2). Every count here means
    # "since we started watching", never "since the trial was registered":
    # a trial amended eleven times before this date shows none of them.

    unattributed_changes: List[StudyChange] = []
    # Content changes belonging to no amendment. Should always be empty:
    # every content change is written in the same transaction as the
    # last_update_post_date change that explains it, so they share an exact
    # detected_at (0 exceptions in 195 changes, measured 2026-09-01).
    # Returned rather than dropped because if that ever stops being true,
    # silently discarding real recorded changes would be the worst possible
    # failure — a trial would look quieter than it was.


class WatchDay(BaseModel):
    """One day on the watch's 7-day record, including the empty ones.

    A zero here is a finding, not missing data: "we checked and nothing was
    amended" is a different statement from "we have no record of that day",
    and the day rows are generated from a date series rather than from the
    changes themselves specifically so a quiet day still appears.
    """

    day: date
    amendments: int


class WatchAmendment(BaseModel):
    """The most recent amendment across every watched trial — the "last
    thing that happened" card, so the screen is never blank.

    Same shape as one Amendment from a trial's history, plus the trial it
    belongs to, since this one spans all of them.
    """

    nct_id: str
    brief_title: str
    posted_on: date
    previously_posted_on: Optional[date] = None
    detected_at: datetime
    changes: List[AmendedField] = []
    aspects: List[str] = []
    content_is_visible: bool = True


class WatchRecent(BaseModel):
    """The last 24 hours, counted by what it MEANS rather than by rows.

    "63 amendments" is a row count, and a row count is exactly the kind of
    number the removed ranking layer was good at and useless for. "One trial
    published its results, three others changed something scientific" is the
    same 63 rows read as a finding. Both are here: the headline needs the
    finding, the honesty needs the total.
    """

    window_hours: int
    amendments: int
    trials: int
    scientific: int
    # Amendments touching at least one field api/amendments.py classifies as
    # Scientific — what the trial studies, and in whom.
    results_posted: int
    # Amendments where has_results went false -> true. A SUBSET of
    # scientific, not a separate bucket: the UI subtracts when it says
    # "N others". The single most consequential amendment a trial carries,
    # and one TrialLens could not see at all before 2026-09-02.


class WatchStatus(BaseModel):
    """Everything the front page states about the watch itself.

    One endpoint rather than five, because these numbers are read together
    and only make sense together — "11,427 watched" is a different claim
    depending on whether the last check was 2 hours or 3 days ago.
    """

    trials_watched: int
    conditions: List[str]

    # ---- Is the watch alive? ----
    last_checked_at: Optional[datetime] = None
    # PROXY, and it must be labelled as one wherever it is shown. There is
    # no record of when a scheduled run happened (that is direction 3,
    # `monitor_runs`). This is max(studies.last_matched_at), which
    # POST /studies/reconcile-scope stamps on every in-scope trial at the
    # end of every run — so it does report a check on a day when nothing
    # changed, which max(detected_at) would not. What it cannot do is count
    # runs or distinguish a run that failed after reconciling.

    last_checked_source: str = "last_matched_at"
    hours_since_check: Optional[float] = None
    check_interval_hours: int
    checks_missed: int = 0
    # Derived from elapsed time and the cron interval, not from a run log:
    # how many scheduled checks should have happened since the last one we
    # can see evidence of. 0 while healthy.

    is_healthy: bool
    # False means SHOW THE ALARM INSTEAD OF THE PAGE, not a banner above a
    # normal-looking feed — a stale feed under a small warning still reads
    # as current, which is the failure being designed out (design/README.md).

    # ---- What has been happening ----
    daily: List[WatchDay] = []
    recent: WatchRecent
    hours_since_last_amendment: Optional[float] = None
    last_amendment: Optional[WatchAmendment] = None

    # ---- Something to do on a quiet day ----
    trials_with_results: int
    completed_with_results: int

    # ---- The record: what a fresh clone does not have ----
    recording_since: Optional[datetime] = None
    changes_recorded: int
    amendments_seen: int


class ChangeFeedEntry(StudyChange):
    """One row in the aggregate Monitor feed (GET /changes) — same shape as
    StudyChange plus which trial it belongs to, since the feed spans every
    tracked trial, not one nct_id."""

    nct_id: str
    brief_title: str
    # Only set on a "no longer tracked" change, and only when the stored
    # data actually explains it — None means "we can't tell", which the UI
    # shows honestly rather than filling in (see api/tracking.py).
    tracking_note: Optional[str] = None


class ChangedField(BaseModel):
    """One filterable field on the Monitor feed, with which kind of change
    it represents (see api/tracking.py)."""

    name: str
    category: str


class ChangeFeedResponse(BaseModel):
    total: int
    distinct_trials: int
    limit: int
    offset: int
    results: List[ChangeFeedEntry]


class ReconcileScopeRequest(BaseModel):
    """Sent once per condition at the end of an ingest run: the full set of
    nct_ids this run's cheap-filter fetch actually matched, so anything
    previously tracked under this condition but not in that set gets
    flagged (never deleted), and everything still in it gets confirmed."""

    condition: str
    current_nct_ids: List[str]


class ReconcileScopeResult(BaseModel):
    confirmed_in_scope: int
    dropped_out_of_scope: int


class KnownDatesRequest(BaseModel):
    """Cheap-filter support: which last_update_post_date do we already have
    stored for these nct_ids? Missing keys in the response mean "never seen
    before" — always worth the expensive re-fetch."""

    nct_ids: List[str]


class KnownDatesResponse(BaseModel):
    known_dates: Dict[str, date]


class DiscoverResult(BaseModel):
    """One trial in a GET /discover response, tagged with where it actually
    came from — "tracked" (already in our DB, kept fresh by Monitor) or
    "live" (fetched from CT.gov for this request only, not stored). Lives
    on each result, not the response, because a response can mix both: an
    untracked condition's local rows are only ever incidental, never proof
    of a complete picture on their own."""

    nct_id: str
    brief_title: str
    overall_status: str
    phase: Optional[str] = None
    last_update_post_date: Optional[date] = None
    source: str  # "tracked" or "live"


class DiscoverResponse(BaseModel):
    condition: str
    total: int
    results: List[DiscoverResult]
    note: str


class TrialDetail(BaseModel):
    """Full detail for one trial, tracked or not — Understand's real
    response shape. The tracked-only fields (fetched_at, last_matched_at,
    active_in_scope) are None for a live result, since those concepts —
    "when did we last fetch/confirm this" — don't apply to a trial we
    don't actually store."""

    nct_id: str
    brief_title: str
    official_title: Optional[str] = None
    overall_status: str
    study_type: Optional[str] = None
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED — see ctgov_client.py
    has_results: Optional[bool] = None  # CT.gov has posted results for this trial
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    last_update_post_date: Optional[date] = None
    conditions: List[str] = []
    source: str  # "tracked" or "live"
    fetched_at: Optional[datetime] = None
    last_matched_at: Optional[datetime] = None
    active_in_scope: Optional[bool] = None
    # Why this trial is no longer tracked, when the stored data explains it
    # — None (shown honestly as "we can't tell") otherwise. See api/tracking.py.
    tracking_note: Optional[str] = None
    brief_summary: Optional[str] = None
    lead_sponsor: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    interventions: List[Intervention] = []
    primary_outcomes: List[OutcomeMeasure] = []
    locations: List[TrialLocation] = []
