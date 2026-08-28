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
"""
from typing import Optional

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_readonly_db
from api.schemas import DiscoverResponse, DiscoverResult
from ctgov_client import ACTIVE_STATUSES, extract_fields, fetch_pages

router = APIRouter(tags=["discover"])

LOCAL_MATCH_SQL = """
    SELECT nct_id, brief_title, overall_status, phase, last_update_post_date
    FROM studies
    WHERE nct_id IN (SELECT nct_id FROM study_conditions WHERE condition ILIKE %s)
    ORDER BY last_update_post_date DESC
    LIMIT %s
"""


@router.get("/discover", response_model=DiscoverResponse)
def discover(
    condition: str = Query(..., description="Condition/therapeutic area, matched loosely"),
    limit: int = Query(25, ge=1, le=100),
    conn=Depends(get_readonly_db),
):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(LOCAL_MATCH_SQL, (f"%{condition}%", limit))
        local_rows = cur.fetchall()

    if local_rows:
        return DiscoverResponse(
            condition=condition,
            source="tracked",
            total=len(local_rows),
            results=[DiscoverResult(**row) for row in local_rows],
            note=(
                "Served from our own tracked data — this topic has been fetched "
                "before. See GET /studies for the full list and GET "
                "/studies/{nct_id}/changes for its change history."
            ),
        )

    try:
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
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"live ClinicalTrials.gov lookup failed: {exc}",
        )

    return DiscoverResponse(
        condition=condition,
        source="live",
        total=len(live_studies),
        results=[DiscoverResult(**s) for s in live_studies],
        note=(
            "Not in our tracked data — fetched live from ClinicalTrials.gov just "
            "now, not stored. No change-detection applies to these results; "
            "tracking this condition going forward is a separate action "
            "(add it to config/tracked_conditions.json)."
        ),
    )
