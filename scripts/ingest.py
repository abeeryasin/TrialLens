"""Fetch studies for a condition from ClinicalTrials.gov and store them.

Usage:
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

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

API_URL = "https://clinicaltrials.gov/api/v2/studies"
ACTIVE_STATUSES = "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION"
CLOSED_STATUSES = "COMPLETED,TERMINATED,SUSPENDED,WITHDRAWN"
RECENCY_DAYS = 730  # ~24 months

UPSERT_STUDIES = """
    INSERT INTO studies (
        nct_id, brief_title, official_title, overall_status, study_type,
        phase, enrollment_count, sex, minimum_age, healthy_volunteers,
        eligibility_criteria, last_update_post_date, raw_json, fetched_at
    ) VALUES %s
    ON CONFLICT (nct_id) DO UPDATE SET
        brief_title = EXCLUDED.brief_title,
        official_title = EXCLUDED.official_title,
        overall_status = EXCLUDED.overall_status,
        study_type = EXCLUDED.study_type,
        phase = EXCLUDED.phase,
        enrollment_count = EXCLUDED.enrollment_count,
        sex = EXCLUDED.sex,
        minimum_age = EXCLUDED.minimum_age,
        healthy_volunteers = EXCLUDED.healthy_volunteers,
        eligibility_criteria = EXCLUDED.eligibility_criteria,
        last_update_post_date = EXCLUDED.last_update_post_date,
        raw_json = EXCLUDED.raw_json,
        fetched_at = now();
"""

def extract_fields(study: dict) -> dict:
    """Pull the normalized columns out of one raw study record.

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
        response = requests.get(API_URL, params=params, timeout=30)
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


def write_batch(cur, records: list[dict]):
    if not records:
        return

    study_rows = [
        (
            r["nct_id"], r["brief_title"], r["official_title"], r["overall_status"],
            r["study_type"], r["phase"], r["enrollment_count"], r["sex"],
            r["minimum_age"], r["healthy_volunteers"], r["eligibility_criteria"],
            r["last_update_post_date"], psycopg2.extras.Json(r["raw_json"]),
        )
        for r in records
    ]
    template = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())"
    psycopg2.extras.execute_values(cur, UPSERT_STUDIES, study_rows, template=template)

    nct_ids = [r["nct_id"] for r in records]
    cur.execute("DELETE FROM study_conditions WHERE nct_id = ANY(%s)", (nct_ids,))

    condition_rows = [
        (r["nct_id"], condition_name)
        for r in records
        for condition_name in r["conditions"]
    ]
    if condition_rows:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO study_conditions (nct_id, condition) VALUES %s",
            condition_rows,
        )


def main():
    if len(sys.argv) != 2:
        print("Usage: ingest.py <condition>")
        sys.exit(1)
    condition = sys.argv[1]
    recency_cutoff = (date.today() - timedelta(days=RECENCY_DAYS)).isoformat()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    total = 0

    def flush_batch(cur, batch):
        nonlocal total
        if not batch:
            return
        write_batch(cur, batch)
        conn.commit()  # commit per batch: real incremental progress, not one giant transaction
        total += len(batch)
        print(f"  committed {total} studies so far", flush=True)

    try:
        with conn.cursor() as cur:
            print(f"Fetching active trials for: {condition}", flush=True)
            batch = []
            for study in fetch_studies(condition, ACTIVE_STATUSES):
                batch.append(extract_fields(study))
                if len(batch) >= 200:
                    flush_batch(cur, batch)
                    batch = []
            flush_batch(cur, batch)

            print(f"Fetching closed trials updated since {recency_cutoff} for: {condition}", flush=True)
            batch = []
            advanced = f"AREA[LastUpdatePostDate]RANGE[{recency_cutoff},MAX]"
            for study in fetch_studies(condition, CLOSED_STATUSES, advanced):
                batch.append(extract_fields(study))
                if len(batch) >= 200:
                    flush_batch(cur, batch)
                    batch = []
            flush_batch(cur, batch)
    finally:
        conn.close()

    print(f"Ingested {total} studies for condition: {condition}", flush=True)


if __name__ == "__main__":
    main()
