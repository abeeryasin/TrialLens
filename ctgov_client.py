"""Shared ClinicalTrials.gov v2 API client — the actual HTTP/parsing logic,
used by both scripts/ingest.py (the scheduled Monitor) and api/discover.py
(the ad-hoc live-fallback query). Kept as its own top-level module rather
than living inside either scripts/ or api/: it talks to CT.gov only, never
to the database, so it isn't part of the "FastAPI is the only door to the
DB" boundary either side of it, and both sides need the exact same parsing
so a CT.gov field-name change only has to be fixed in one place.
"""
import time

import requests

CT_API_URL = "https://clinicaltrials.gov/api/v2/studies"
ACTIVE_STATUSES = "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION"


def request_with_retry(method, url, **kwargs):
    """One retry on a network/5xx failure, then let it raise for real.

    A 4xx (bad request, not found) is never retried — the request itself
    is wrong, so trying again wastes a 5-second sleep without changing
    the outcome (e.g. looking up a bad NCT ID would otherwise hang before
    correctly reporting "not found")."""
    for attempt in range(2):
        try:
            response = method(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.HTTPError as exc:
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                raise
            if attempt == 0:
                print(f"  request to {url} failed ({exc}), retrying once...", flush=True)
                time.sleep(5)
            else:
                raise
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


def fetch_single_study(nct_id: str):
    """Full single-study record direct from CT.gov, or None if CT.gov has
    no such trial. Verified live: CT.gov returns 404 for a well-formed but
    nonexistent NCT ID, and 400 for a malformed one — different reasons,
    but neither is a trial to show, so both mean "not found" here. Used by
    Understand's live fallback: a trial not in our own DB may still be a
    real, current trial worth showing (e.g. a Discover live result), or
    may just be a bad ID."""
    try:
        response = request_with_retry(requests.get, f"{CT_API_URL}/{nct_id}", timeout=30)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (400, 404):
            return None
        raise
    return response.json()


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
