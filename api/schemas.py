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
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
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
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
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
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
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
