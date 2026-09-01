"""The Monitor page's aggregate feed: recent changes across ALL tracked
trials, not one nct_id at a time like GET /studies/{nct_id}/changes.

Its own top-level router, same reasoning as api/discover.py: this doesn't
belong to one resource under /studies, and nesting it as /studies/changes
would collide with /studies/{nct_id} (FastAPI would need it registered
first, in that exact order, forever — fragile). A separate top-level path
avoids that entirely.
"""
from typing import List, Optional

import psycopg2.extras
from fastapi import APIRouter, Depends, Query

from api.database import get_readonly_db
from api.schemas import ChangedField, ChangeFeedEntry, ChangeFeedResponse
from api.tracking import (
    CATEGORY_TRACKING,
    CATEGORY_TRIAL_CONTENT,
    TRACKING_FIELDS,
    drop_reason,
    field_category,
)

router = APIRouter(tags=["changes"])


@router.get("/changes", response_model=ChangeFeedResponse)
def recent_changes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    condition: Optional[str] = Query(None, description="Restrict to trials tagged with this tracked condition"),
    field_name: Optional[str] = Query(None, description="Restrict to changes to this one field"),
    category: Optional[str] = Query(
        None, description=f'"{CATEGORY_TRIAL_CONTENT}" or "{CATEGORY_TRACKING}"'
    ),
    detected_within_days: Optional[int] = Query(
        None, ge=1, description="Only changes WE detected within this many days"
    ),
    trial_updated_within_days: Optional[int] = Query(
        None, ge=1, description="Only changes on trials ClinicalTrials.gov updated within this many days"
    ),
    conn=Depends(get_readonly_db),
):
    where = []
    params: list = []
    if condition:
        where.append("sc.nct_id IN (SELECT nct_id FROM study_conditions WHERE condition ILIKE %s)")
        params.append(f"%{condition}%")
    if field_name:
        where.append("sc.field_name = %s")
        params.append(field_name)
    if category == CATEGORY_TRACKING:
        where.append("sc.field_name = ANY(%s)")
        params.append(sorted(TRACKING_FIELDS))
    elif category == CATEGORY_TRIAL_CONTENT:
        where.append("NOT (sc.field_name = ANY(%s))")
        params.append(sorted(TRACKING_FIELDS))
    if detected_within_days:
        where.append("sc.detected_at >= now() - make_interval(days => %s)")
        params.append(detected_within_days)
    if trial_updated_within_days:
        # A subquery, not a JOIN: the two count queries below run against
        # study_changes alone, and keeping this a subquery means all three
        # queries can share one WHERE clause unchanged. Same shape the
        # condition filter above already uses.
        where.append(
            "sc.nct_id IN (SELECT nct_id FROM studies "
            "WHERE last_update_post_date >= current_date - %s)"
        )
        params.append(trial_updated_within_days)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS n FROM study_changes sc {where_clause}", params)
        total = cur.fetchone()["n"]

        cur.execute(f"SELECT count(DISTINCT sc.nct_id) AS n FROM study_changes sc {where_clause}", params)
        distinct_trials = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT sc.nct_id, s.brief_title, sc.field_name, sc.old_value, sc.new_value,
                   sc.detected_at, s.overall_status, s.last_update_post_date
            FROM study_changes sc
            JOIN studies s ON s.nct_id = sc.nct_id
            {where_clause}
            ORDER BY sc.detected_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        # overall_status/last_update_post_date are joined in only to explain a
        # drop — they aren't part of the change itself, so they don't go on
        # the response model.
        status = row.pop("overall_status")
        last_update = row.pop("last_update_post_date")
        note = None
        if row["field_name"] == "active_in_scope" and row["new_value"] == "false":
            note = drop_reason(status, last_update)
        # Set here for the same reason GET /studies/{nct_id}/changes sets
        # it: category is a property of the field, not a stored column, and
        # api/tracking.py is its one definition. It was missing until
        # 2026-09-02, so every row of this feed reported category=null while
        # the per-trial endpoint reported it correctly — the Monitor page
        # happened not to notice, because it reads categories from
        # /changes/fields and filters server-side.
        results.append(
            ChangeFeedEntry(**row, tracking_note=note, category=field_category(row["field_name"]))
        )

    return ChangeFeedResponse(
        total=total,
        distinct_trials=distinct_trials,
        limit=limit,
        offset=offset,
        results=results,
    )


@router.get("/changes/fields", response_model=List[ChangedField])
def changed_fields(conn=Depends(get_readonly_db)):
    """Which fields actually have a change on record right now, each with
    its category — powers the Monitor page's filters with only real,
    non-empty options, and without the frontend needing its own copy of
    the trial-content-vs-tracking rule."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT field_name FROM study_changes ORDER BY field_name")
        return [
            ChangedField(name=row[0], category=field_category(row[0]))
            for row in cur.fetchall()
        ]
