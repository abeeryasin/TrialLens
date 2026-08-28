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
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    fetched_at: datetime
    last_matched_at: datetime
    conditions: List[str] = []


class StudyList(BaseModel):
    total: int
    limit: int
    offset: int
    results: List[StudySummary]


class StudyUpsert(BaseModel):
    """One study as written by ingest.py, matching extract_fields() in scripts/ingest.py."""

    nct_id: str
    brief_title: str
    official_title: Optional[str] = None
    overall_status: str
    study_type: Optional[str] = None
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    last_update_post_date: date
    conditions: List[str] = []
    raw_json: Dict[str, Any]


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


class StudyChangeList(BaseModel):
    nct_id: str
    changes: List[StudyChange]


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
