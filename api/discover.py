"""Discover: ad-hoc query for a therapeutic area, tracked or not.

Implements the split decided in docs/decisions.md (2026-08-26, "Discover
vs. Monitor"): a plain read of our own DB looks identical to "no trials
exist" whether the topic was never fetched or genuinely has none. So this
route checks our own DB first (exactly the same condition match GET
/studies uses) and only falls through to a one-time, live ClinicalTrials.gov
call when that comes back empty. A live result is never written to the
DB — tracking a topic going forward is its own explicit action
(config/tracked_conditions.json + the Monitor job), not something a
read-only ad-hoc question should trigger as a side effect.

Also implements the fix decided 2026-08-28 ("/discover can silently
under-report an untracked condition"): local rows alone are only proof of
completeness when the condition is itself one Monitor comprehensively
tracks. A substring hit — e.g. searching "psoriasis" and getting a
comorbid-tag row on a trial tracked under "breast cancer" — is real data,
but not the whole picture, so it gets merged with a live lookup and each
result is tagged with where it actually came from.
"""
import json
from datetime import date
from pathlib import Path

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_readonly_db
from api.schemas import DiscoverResponse, DiscoverResult, TrialDetail
from ctgov_client import ACTIVE_STATUSES, extract_fields, fetch_pages, fetch_single_study

router = APIRouter(tags=["discover"])

TRACKED_CONDITIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "tracked_conditions.json"

LOCAL_MATCH_SQL = """
    SELECT nct_id, brief_title, overall_status, phase, last_update_post_date
    FROM studies
    WHERE nct_id IN (SELECT nct_id FROM study_conditions WHERE condition ILIKE %s)
    ORDER BY last_update_post_date DESC
    LIMIT %s
"""


def _is_comprehensively_tracked(condition: str) -> bool:
    """True only for an exact match against config/tracked_conditions.json.
    A substring hit does NOT count — that's exactly the incidental-match
    case this route has to stay honest about."""
    tracked = json.loads(TRACKED_CONDITIONS_PATH.read_text())
    return condition.strip().lower() in {c.lower() for c in tracked}


def _fetch_live(condition: str, limit: int) -> list:
    params = {
        "query.cond": condition,
        "filter.overallStatus": ACTIVE_STATUSES,
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,LastUpdatePostDate",
        "pageSize": limit,
    }
    live_studies = []
    for study in fetch_pages(params):
        live_studies.append(extract_fields(study))
        if len(live_studies) >= limit:
            break
    return live_studies


@router.get("/discover", response_model=DiscoverResponse)
def discover(
    condition: str = Query(..., description="Condition/therapeutic area, matched loosely"),
    limit: int = Query(25, ge=1, le=100),
    conn=Depends(get_readonly_db),
):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(LOCAL_MATCH_SQL, (f"%{condition}%", limit))
        local_rows = cur.fetchall()

    # Case 1: nothing stored locally at all -> a live lookup is the only
    # real answer there is.
    if not local_rows:
        try:
            live_studies = _fetch_live(condition, limit)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"live ClinicalTrials.gov lookup failed: {exc}",
            )
        return DiscoverResponse(
            condition=condition,
            total=len(live_studies),
            results=[DiscoverResult(**s, source="live") for s in live_studies],
            note=(
                "We don't track this condition yet, so these results are "
                "fetched live from ClinicalTrials.gov just now rather than "
                "from our own data. They won't reflect future changes unless "
                "this condition starts being tracked."
            ),
        )

    # Case 2: locally stored, and this condition is one Monitor
    # comprehensively tracks -> the local data really is the complete,
    # current answer. No live call needed.
    if _is_comprehensively_tracked(condition):
        return DiscoverResponse(
            condition=condition,
            total=len(local_rows),
            results=[DiscoverResult(**row, source="tracked") for row in local_rows],
            note="This condition is one we actively track, so these results come from our own regularly-updated data.",
        )

    # Case 3: local rows exist but only incidentally (e.g. a comorbid
    # condition tag on a trial tracked under a different condition) — not
    # proof this is the complete picture. Merge with a live lookup and tag
    # each result with where it actually came from.
    try:
        live_studies = _fetch_live(condition, limit)
    except Exception as exc:
        print(f"  /discover: live lookup for '{condition}' failed ({exc}), falling back to local-only", flush=True)
        return DiscoverResponse(
            condition=condition,
            total=len(local_rows),
            results=[DiscoverResult(**row, source="tracked") for row in local_rows],
            note=(
                "We don't specifically track this condition, and a live "
                "lookup to check for more trials just failed. The results "
                "below are only what's already in our database from other "
                "tracked conditions — treat this as possibly incomplete."
            ),
        )

    merged = {row["nct_id"]: DiscoverResult(**row, source="tracked") for row in local_rows}
    for study in live_studies:
        if study["nct_id"] not in merged:
            merged[study["nct_id"]] = DiscoverResult(**study, source="live")

    results = sorted(
        merged.values(),
        key=lambda r: r.last_update_post_date or date.min,
        reverse=True,
    )[:limit]

    return DiscoverResponse(
        condition=condition,
        total=len(results),
        results=results,
        note=(
            "We don't specifically track this condition, so these results "
            "are a mix: some are already in our database (found via other "
            "tracked conditions), and some are looked up live from "
            "ClinicalTrials.gov just now. This list may not be complete."
        ),
    )


@router.get("/discover/{nct_id}", response_model=TrialDetail)
def discover_trial(nct_id: str, conn=Depends(get_readonly_db)):
    """Understand's real lookup: our own DB first, then a live single-trial
    fetch from ClinicalTrials.gov if we don't have it stored. A trial
    clicked into from a live Discover result is exactly the case this
    exists for — it's a real, current trial, just not one we track."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM studies WHERE nct_id = %s", (nct_id,))
        study = cur.fetchone()
        if study is not None:
            cur.execute(
                "SELECT condition FROM study_conditions WHERE nct_id = %s ORDER BY condition",
                (nct_id,),
            )
            conditions = [r["condition"] for r in cur.fetchall()]
            return TrialDetail(**study, conditions=conditions, source="tracked")

    try:
        live_study = fetch_single_study(nct_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"live ClinicalTrials.gov lookup failed: {exc}")

    if live_study is None:
        raise HTTPException(
            status_code=404,
            detail=f"No trial found for {nct_id}, locally or on ClinicalTrials.gov",
        )

    fields = extract_fields(live_study)
    return TrialDetail(**fields, source="live")
