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

# The real ingestion scope, in one place. These live here rather than in
# scripts/ingest.py because they're no longer only the fetcher's business:
# explaining *why* a trial is no longer tracked (api/tracking.py) has to
# reason against the exact same rules the fetcher applied, and two copies
# would let the explanation quietly start lying if either changed.
ACTIVE_STATUSES = "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION"
CLOSED_STATUSES = "COMPLETED,TERMINATED,SUSPENDED,WITHDRAWN"
RECENCY_DAYS = 730  # ~24 months; closed trials are only tracked this far back


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

    The narrative/design fields (brief_summary, interventions,
    primary_outcomes, lead_sponsor, real dates, locations) were added
    2026-08-29 — see docs/decisions.md for why "title + eligibility +
    status" alone doesn't answer "why does this trial matter." Trimmed to
    just the sub-fields actually displayed, not stored verbatim — the full
    structure is still preserved untouched in raw_json regardless.
    """
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    conditions = protocol.get("conditionsModule", {})
    description = protocol.get("descriptionModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    outcomes = protocol.get("outcomesModule", {})
    contacts_locations = protocol.get("contactsLocationsModule", {})

    phases = design.get("phases", [])

    interventions = [
        {
            "type": i.get("type"),
            "name": i.get("name"),
            "description": i.get("description"),
        }
        for i in arms.get("interventions", [])
    ]
    primary_outcomes = [
        {
            "measure": o.get("measure"),
            "description": o.get("description"),
            "time_frame": o.get("timeFrame"),
        }
        for o in outcomes.get("primaryOutcomes", [])
    ]
    locations = [
        {
            "facility": loc.get("facility"),
            "city": loc.get("city"),
            "country": loc.get("country"),
        }
        for loc in contacts_locations.get("locations", [])
    ]

    return {
        "nct_id": identification["nctId"],
        "brief_title": identification.get("briefTitle", ""),
        "official_title": identification.get("officialTitle"),
        "overall_status": status.get("overallStatus", "UNKNOWN"),
        "study_type": design.get("studyType"),
        "phase": ",".join(phases) if phases else None,
        "enrollment_count": design.get("enrollmentInfo", {}).get("count"),
        # ACTUAL (people who really enrolled) vs ESTIMATED (the sponsor's
        # target). The bare count is genuinely ambiguous without it — most
        # records are ESTIMATED — and dropping it would be exactly the kind
        # of discarded uncertainty CLAUDE.md sec. 3 forbids.
        "enrollment_type": design.get("enrollmentInfo", {}).get("type"),
        "sex": eligibility.get("sex"),
        "minimum_age": eligibility.get("minimumAge"),
        "healthy_volunteers": eligibility.get("healthyVolunteers"),
        "eligibility_criteria": eligibility.get("eligibilityCriteria"),
        "last_update_post_date": status.get("lastUpdatePostDateStruct", {}).get("date"),
        "conditions": conditions.get("conditions", []),
        "brief_summary": description.get("briefSummary"),
        "lead_sponsor": sponsor.get("leadSponsor", {}).get("name"),
        "start_date": status.get("startDateStruct", {}).get("date"),
        "primary_completion_date": status.get("primaryCompletionDateStruct", {}).get("date"),
        "completion_date": status.get("completionDateStruct", {}).get("date"),
        "interventions": interventions,
        "primary_outcomes": primary_outcomes,
        "locations": locations,
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
