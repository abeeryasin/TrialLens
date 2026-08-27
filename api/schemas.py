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
