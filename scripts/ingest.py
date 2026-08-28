"""Fetch studies for a condition from ClinicalTrials.gov and store them
via the FastAPI layer — this script no longer talks to Postgres
directly (see docs/decisions.md, "FastAPI as only door").

Usage (FastAPI must be running, e.g. `.venv/bin/uvicorn api.main:app`):
    .venv/bin/python scripts/ingest.py "breast cancer"
    .venv/bin/python scripts/ingest.py obesity

Two groups are searched per condition (see docs/decisions.md, 2026-08-26,
"Ingestion scope" and its recency-window follow-up):
  - Active trials (recruiting / not yet recruiting / active-not-recruiting /
    enrolling-by-invitation): all of them, no date limit.
  - Recently-closed trials (completed / terminated / suspended / withdrawn):
    only if last updated within RECENCY_DAYS, so we get "what just
    happened in this space" context without the full historical archive.

Real cheap-filter/expensive-diff (see docs/decisions.md, 2026-08-28): for
both groups, the first fetch only asks CT.gov for NCTId + LastUpdatePostDate
(fields=...) — a few bytes per trial instead of a full multi-KB record. Only
trials that are new or whose date moved get a second, full-record fetch
(filter.ids=...), which is what actually gets diffed field-by-field and
written to study_changes by api/studies.py.

Also called by scripts/run_monitor.py, the real scheduled Monitor job: after
both groups' cheap fetch, the complete set of nct_ids seen this run
(changed and unchanged) is reported to POST /studies/reconcile-scope, which
confirms them and flags (never deletes) anything that dropped out.
"""
import os
import sys
import time
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
REFETCH_CHUNK_SIZE = 100  # NCT IDs per filter.ids= request, keeps the URL a sane length


def request_with_retry(method, url, **kwargs):
    """One retry on a network/HTTP failure, then let it raise for real.

    This is the scheduler's whole failure guardrail for transient issues:
    a real unattended run (see .github/workflows/monitor.yml) should
    tolerate one flaky call, but a second failure in a row is treated as
    real and surfaced — the workflow fails, and GitHub emails the run's
    owner automatically (verified, see docs/decisions.md, 2026-08-28).
    """
    for attempt in range(2):
        try:
            response = method(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if attempt == 0:
                print(f"  request to {url} failed ({exc}), retrying once...", flush=True)
                time.sleep(5)
            else:
                raise


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


def fetch_pages(params: dict):
    """Yield every study dict matching `params`, paging through results."""
    params = dict(params)
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        response = request_with_retry(requests.get, CT_API_URL, params=params, timeout=30)
        data = response.json()
        studies = data.get("studies", [])
        for study in studies:
            yield study
        page_token = data.get("nextPageToken")
        if not page_token:
            break


def cheap_fetch_dates(condition: str, statuses: str, advanced_filter: str = None) -> dict:
    """The cheap filter: NCTId + LastUpdatePostDate only, no full record."""
    params = {
        "query.cond": condition,
        "filter.overallStatus": statuses,
        "fields": "NCTId,LastUpdatePostDate",
        "pageSize": 1000,
    }
    if advanced_filter:
        params["filter.advanced"] = advanced_filter

    remote_dates = {}
    for study in fetch_pages(params):
        nct_id = study["protocolSection"]["identificationModule"]["nctId"]
        remote_dates[nct_id] = (
            study["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"]
        )
    print(f"  cheap-filter matched {len(remote_dates)} studies", flush=True)
    return remote_dates


def expensive_fetch_full(nct_ids: list[str]):
    """The expensive diff's input: full records, but only for the nct_ids
    the cheap filter flagged as new or changed."""
    for i in range(0, len(nct_ids), REFETCH_CHUNK_SIZE):
        chunk = nct_ids[i:i + REFETCH_CHUNK_SIZE]
        params = {"filter.ids": ",".join(chunk), "pageSize": 1000}
        yield from fetch_pages(params)


def get_known_dates(nct_ids: list[str]) -> dict:
    if not nct_ids:
        return {}
    response = request_with_retry(
        requests.post,
        f"{API_BASE_URL}/studies/known-dates",
        json={"nct_ids": nct_ids},
        timeout=60,
    )
    return response.json()["known_dates"]


def write_batch(records: list[dict]) -> dict:
    if not records:
        return {"studies_written": 0, "condition_tags_written": 0, "changes_detected": 0}
    response = request_with_retry(
        requests.post, f"{API_BASE_URL}/studies/batch", json=records, timeout=60
    )
    return response.json()


def reconcile_scope(condition: str, current_nct_ids: set[str]):
    if not current_nct_ids:
        print(
            f"  WARNING: zero studies matched '{condition}' this run — skipping "
            "scope reconciliation rather than risk flagging everything as dropped",
            flush=True,
        )
        return
    response = request_with_retry(
        requests.post,
        f"{API_BASE_URL}/studies/reconcile-scope",
        json={"condition": condition, "current_nct_ids": list(current_nct_ids)},
        timeout=60,
    )
    result = response.json()
    print(
        f"  scope reconciled: {result['confirmed_in_scope']} confirmed, "
        f"{result['dropped_out_of_scope']} dropped out of scope",
        flush=True,
    )


def sync_group(condition: str, statuses: str, advanced_filter: str = None) -> set:
    """Cheap-filter then expensive-diff for one status group. Returns every
    nct_id the cheap filter matched (used for scope reconciliation)."""
    remote_dates = cheap_fetch_dates(condition, statuses, advanced_filter)
    if not remote_dates:
        return set()

    all_nct_ids = list(remote_dates.keys())
    known_dates = get_known_dates(all_nct_ids)
    to_refetch = [
        nct_id for nct_id, remote_date in remote_dates.items()
        if known_dates.get(nct_id) != remote_date
    ]
    print(
        f"  {len(to_refetch)} of {len(all_nct_ids)} are new or changed — "
        "fetching full records for those only",
        flush=True,
    )

    total_written = 0
    total_changed = 0
    batch = []
    for study in expensive_fetch_full(to_refetch):
        batch.append(extract_fields(study))
        if len(batch) >= 200:
            result = write_batch(batch)
            total_written += result["studies_written"]
            total_changed += result["changes_detected"]
            batch = []
    if batch:
        result = write_batch(batch)
        total_written += result["studies_written"]
        total_changed += result["changes_detected"]

    print(
        f"  wrote {total_written} studies, {total_changed} field changes detected",
        flush=True,
    )
    return set(all_nct_ids)


def run_ingest(condition: str) -> set:
    """Sync both status groups for one condition, then reconcile scope.
    Returns the full set of nct_ids matched this run."""
    recency_cutoff = (date.today() - timedelta(days=RECENCY_DAYS)).isoformat()

    print(f"Syncing active trials for: {condition}", flush=True)
    active_ids = sync_group(condition, ACTIVE_STATUSES)

    print(f"Syncing closed trials updated since {recency_cutoff} for: {condition}", flush=True)
    advanced = f"AREA[LastUpdatePostDate]RANGE[{recency_cutoff},MAX]"
    closed_ids = sync_group(condition, CLOSED_STATUSES, advanced)

    seen_nct_ids = active_ids | closed_ids
    print(f"Done with condition: {condition} ({len(seen_nct_ids)} total matched)", flush=True)
    reconcile_scope(condition, seen_nct_ids)
    return seen_nct_ids


def main():
    if len(sys.argv) != 2:
        print("Usage: ingest.py <condition>")
        sys.exit(1)
    run_ingest(sys.argv[1])


if __name__ == "__main__":
    main()
