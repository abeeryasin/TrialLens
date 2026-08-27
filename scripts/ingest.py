"""Fetch studies for a condition from ClinicalTrials.gov and store them
via the FastAPI layer — this script no longer talks to Postgres
directly (see docs/decisions.md, "FastAPI as only door").

Usage (FastAPI must be running, e.g. `.venv/bin/uvicorn api.main:app`):
    .venv/bin/python scripts/ingest.py "breast cancer"
    .venv/bin/python scripts/ingest.py obesity

Two groups are fetched per condition (see docs/decisions.md, 2026-08-26,
"Ingestion scope" and its recency-window follow-up):
  - Active trials (recruiting / not yet recruiting / active-not-recruiting /
    enrolling-by-invitation): all of them, no date limit.
  - Recently-closed trials (completed / terminated / suspended / withdrawn):
    only if last updated within RECENCY_DAYS, so we get "what just
    happened in this space" context without the full historical archive.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

CT_API_URL = "https://clinicaltrials.gov/api/v2/studies"
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
ACTIVE_STATUSES = "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION"
CLOSED_STATUSES = "COMPLETED,TERMINATED,SUSPENDED,WITHDRAWN"
RECENCY_DAYS = 730  # ~24 months


def extract_fields(study: dict) -> dict:
    """Pull the normalized fields out of one raw study record, matching
    api.schemas.StudyUpsert.

    Uses .get() with defaults throughout because not every study has
    every field (e.g. observational studies have no phase).
    """
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    conditions = protocol.get("conditionsModule", {})

    phases = design.get("phases", [])

    return {
        "nct_id": identification["nctId"],
        "brief_title": identification.get("briefTitle", ""),
        "official_title": identification.get("officialTitle"),
        "overall_status": status.get("overallStatus", "UNKNOWN"),
        "study_type": design.get("studyType"),
        "phase": ",".join(phases) if phases else None,
        "enrollment_count": design.get("enrollmentInfo", {}).get("count"),
        "sex": eligibility.get("sex"),
        "minimum_age": eligibility.get("minimumAge"),
        "healthy_volunteers": eligibility.get("healthyVolunteers"),
        "eligibility_criteria": eligibility.get("eligibilityCriteria"),
        "last_update_post_date": status.get("lastUpdatePostDateStruct", {}).get("date"),
        "conditions": conditions.get("conditions", []),
        "raw_json": study,
    }


def fetch_studies(condition: str, statuses: str, advanced_filter: str = None):
    """Yield every study matching `condition` + `statuses`, paging through results."""
    params = {
        "query.cond": condition,
        "filter.overallStatus": statuses,
        "pageSize": 1000,
    }
    if advanced_filter:
        params["filter.advanced"] = advanced_filter

    page_token = None
    fetched = 0
    while True:
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(CT_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        studies = data.get("studies", [])
        fetched += len(studies)
        print(f"  fetched {fetched} so far...", flush=True)
        for study in studies:
            yield study
        page_token = data.get("nextPageToken")
        if not page_token:
            break


def write_batch(records: list[dict]) -> int:
    if not records:
        return 0
    response = requests.post(f"{API_BASE_URL}/studies/batch", json=records, timeout=60)
    response.raise_for_status()
    return response.json()["studies_written"]


def main():
    if len(sys.argv) != 2:
        print("Usage: ingest.py <condition>")
        sys.exit(1)
    condition = sys.argv[1]
    recency_cutoff = (date.today() - timedelta(days=RECENCY_DAYS)).isoformat()

    total = 0

    def flush_batch(batch):
        nonlocal total
        if not batch:
            return
        written = write_batch(batch)
        total += written
        print(f"  written {total} studies so far", flush=True)

    print(f"Fetching active trials for: {condition}", flush=True)
    batch = []
    for study in fetch_studies(condition, ACTIVE_STATUSES):
        batch.append(extract_fields(study))
        if len(batch) >= 200:
            flush_batch(batch)
            batch = []
    flush_batch(batch)

    print(f"Fetching closed trials updated since {recency_cutoff} for: {condition}", flush=True)
    batch = []
    advanced = f"AREA[LastUpdatePostDate]RANGE[{recency_cutoff},MAX]"
    for study in fetch_studies(condition, CLOSED_STATUSES, advanced):
        batch.append(extract_fields(study))
        if len(batch) >= 200:
            flush_batch(batch)
            batch = []
    flush_batch(batch)

    print(f"Ingested {total} studies for condition: {condition}", flush=True)


if __name__ == "__main__":
    main()
