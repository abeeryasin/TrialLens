import json
from typing import List, Optional

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.database import get_db, get_readonly_db
from api.tracking import field_category
from api.schemas import (
    STUDY_DETAIL_COLUMNS,
    BatchUpsertResult,
    KnownDatesRequest,
    KnownDatesResponse,
    ReconcileScopeRequest,
    ReconcileScopeResult,
    StudyChange,
    StudyChangeList,
    StudyDetail,
    StudyList,
    StudySummary,
    StudyUpsert,
)

router = APIRouter(prefix="/studies", tags=["studies"])

# The "expensive diff" fields: whenever a re-ingested record's value for one
# of these differs from what's already stored, it's a real, reportable
# change (see docs/decisions.md, 2026-08-28, cheap-filter/expensive-diff).
# The narrative/design fields (2026-08-29) are included too — a changed
# outcome measure or intervention is exactly the kind of real change
# last_update_post_date alone couldn't previously explain.
DIFF_FIELDS = [
    "brief_title", "official_title", "overall_status", "study_type", "phase",
    "enrollment_count", "enrollment_type", "sex", "minimum_age", "maximum_age", "healthy_volunteers",
    "eligibility_criteria", "last_update_post_date",
    "brief_summary", "lead_sponsor", "start_date", "primary_completion_date",
    "completion_date", "interventions", "primary_outcomes", "locations",
]

UPSERT_STUDIES = """
    INSERT INTO studies (
        nct_id, brief_title, official_title, overall_status, study_type,
        phase, enrollment_count, enrollment_type, sex, minimum_age, maximum_age, healthy_volunteers,
        eligibility_criteria, last_update_post_date, raw_json,
        brief_summary, lead_sponsor, start_date, primary_completion_date,
        completion_date, interventions, primary_outcomes, locations,
        fetched_at, active_in_scope, last_matched_at
    ) VALUES %s
    ON CONFLICT (nct_id) DO UPDATE SET
        brief_title = EXCLUDED.brief_title,
        official_title = EXCLUDED.official_title,
        overall_status = EXCLUDED.overall_status,
        study_type = EXCLUDED.study_type,
        phase = EXCLUDED.phase,
        enrollment_count = EXCLUDED.enrollment_count,
        enrollment_type = EXCLUDED.enrollment_type,
        sex = EXCLUDED.sex,
        minimum_age = EXCLUDED.minimum_age,
        maximum_age = EXCLUDED.maximum_age,
        healthy_volunteers = EXCLUDED.healthy_volunteers,
        eligibility_criteria = EXCLUDED.eligibility_criteria,
        last_update_post_date = EXCLUDED.last_update_post_date,
        raw_json = EXCLUDED.raw_json,
        brief_summary = EXCLUDED.brief_summary,
        lead_sponsor = EXCLUDED.lead_sponsor,
        start_date = EXCLUDED.start_date,
        primary_completion_date = EXCLUDED.primary_completion_date,
        completion_date = EXCLUDED.completion_date,
        interventions = EXCLUDED.interventions,
        primary_outcomes = EXCLUDED.primary_outcomes,
        locations = EXCLUDED.locations,
        fetched_at = now(),
        active_in_scope = true,
        last_matched_at = now();
"""

INSERT_CHANGES = """
    INSERT INTO study_changes (nct_id, field_name, old_value, new_value) VALUES %s
"""


@router.get("", response_model=StudyList)
def list_studies(
    condition: Optional[str] = Query(None, description="Condition name, matched loosely"),
    status: Optional[str] = Query(None, description="Comma-separated overall_status values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(get_readonly_db),
):
    where = []
    params: list = []

    if condition:
        where.append(
            "nct_id IN (SELECT nct_id FROM study_conditions WHERE condition ILIKE %s)"
        )
        params.append(f"%{condition}%")
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        where.append("overall_status = ANY(%s)")
        params.append(statuses)

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT count(*) AS n FROM studies {where_clause}", params)
        total = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT nct_id, brief_title, overall_status, phase, last_update_post_date, active_in_scope
            FROM studies {where_clause}
            ORDER BY last_update_post_date DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return StudyList(
        total=total,
        limit=limit,
        offset=offset,
        results=[StudySummary(**row) for row in rows],
    )


@router.get("/{nct_id}", response_model=StudyDetail)
def get_study(nct_id: str, conn=Depends(get_readonly_db)):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT {STUDY_DETAIL_COLUMNS} FROM studies WHERE nct_id = %s", (nct_id,))
        study = cur.fetchone()
        if study is None:
            raise HTTPException(status_code=404, detail=f"No study with nct_id {nct_id}")

        cur.execute(
            "SELECT condition FROM study_conditions WHERE nct_id = %s ORDER BY condition",
            (nct_id,),
        )
        conditions = [r["condition"] for r in cur.fetchall()]

    return StudyDetail(**study, conditions=conditions)


@router.post("/batch", response_model=BatchUpsertResult)
def upsert_studies(records: List[StudyUpsert], conn=Depends(get_db)):
    """Upsert a batch of studies + their condition tags. Used by scripts/ingest.py.

    Before writing, diffs each incoming record against whatever's already
    stored (the "expensive diff" — ingest.py only sends records here after
    its own cheap-filter step decided they're new or their
    lastUpdatePostDate moved) and records any real field-level change to
    study_changes, so Monitor has an actual answer to "what changed," not
    just a silently refreshed row.
    """
    if not records:
        return BatchUpsertResult(studies_written=0, condition_tags_written=0, changes_detected=0)

    nct_ids = [r.nct_id for r in records]

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Only the columns the diff below actually compares. raw_json is not
        # one of them and never has been, so `SELECT *` was pulling the whole
        # stored CT.gov response across the wire on every cron write just to
        # drop it — see STUDY_DETAIL_COLUMNS in api/schemas.py.
        cur.execute(
            f"SELECT nct_id, {', '.join(DIFF_FIELDS)} FROM studies WHERE nct_id = ANY(%s)",
            (nct_ids,),
        )
        existing = {row["nct_id"]: row for row in cur.fetchall()}

    def normalize(value):
        """A list field holds Pydantic sub-models (Intervention, etc.) on
        the incoming record but plain dicts on the stored DB row (JSONB
        decoded by psycopg2) — dump to plain dicts so the two sides can
        actually compare equal when nothing really changed."""
        if isinstance(value, list) and value and isinstance(value[0], BaseModel):
            return [item.model_dump() for item in value]
        return value

    def stringify(value):
        if value is None:
            return None
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        return str(value)

    change_rows = []
    for r in records:
        old = existing.get(r.nct_id)
        if old is None:
            continue  # first time we've ever seen this trial — nothing to diff against
        for field in DIFF_FIELDS:
            old_value = old[field]
            new_value = normalize(getattr(r, field))
            if old_value != new_value:
                change_rows.append((
                    r.nct_id, field,
                    stringify(old_value),
                    stringify(new_value),
                ))

    study_rows = [
        (
            r.nct_id, r.brief_title, r.official_title, r.overall_status,
            r.study_type, r.phase, r.enrollment_count, r.enrollment_type, r.sex,
            r.minimum_age, r.maximum_age, r.healthy_volunteers, r.eligibility_criteria,
            r.last_update_post_date, psycopg2.extras.Json(r.raw_json),
            r.brief_summary, r.lead_sponsor, r.start_date,
            r.primary_completion_date, r.completion_date,
            psycopg2.extras.Json(normalize(r.interventions)),
            psycopg2.extras.Json(normalize(r.primary_outcomes)),
            psycopg2.extras.Json(normalize(r.locations)),
        )
        for r in records
    ]

    with conn.cursor() as cur:
        template = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),true,now())"
        psycopg2.extras.execute_values(cur, UPSERT_STUDIES, study_rows, template=template)

        if change_rows:
            psycopg2.extras.execute_values(cur, INSERT_CHANGES, change_rows)

        cur.execute("DELETE FROM study_conditions WHERE nct_id = ANY(%s)", (nct_ids,))

        condition_rows = [
            (r.nct_id, condition_name) for r in records for condition_name in r.conditions
        ]
        if condition_rows:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO study_conditions (nct_id, condition) VALUES %s",
                condition_rows,
            )

    return BatchUpsertResult(
        studies_written=len(records),
        condition_tags_written=len(condition_rows),
        changes_detected=len(change_rows),
    )


@router.get("/{nct_id}/changes", response_model=StudyChangeList)
def get_study_changes(nct_id: str, conn=Depends(get_readonly_db)):
    """The real Monitor changelog for one trial — every field-level change
    the expensive-diff step has ever detected for it, newest first."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT field_name, old_value, new_value, detected_at
            FROM study_changes WHERE nct_id = %s
            ORDER BY detected_at DESC
            """,
            (nct_id,),
        )
        changes = cur.fetchall()

    return StudyChangeList(
        nct_id=nct_id,
        changes=[StudyChange(**c, category=field_category(c["field_name"])) for c in changes],
    )


@router.post("/known-dates", response_model=KnownDatesResponse)
def known_dates(body: KnownDatesRequest, conn=Depends(get_readonly_db)):
    """The cheap-filter step's other half. ingest.py already did a lightweight
    CT.gov fetch (fields=NCTId,LastUpdatePostDate — no full record) for every
    trial currently matching a tracked condition; this returns what we
    already have stored for those same nct_ids so ingest.py can compare the
    two dates locally and only pull full records (the expensive part) for
    ones that actually moved, or that we've never seen before.
    """
    if not body.nct_ids:
        return KnownDatesResponse(known_dates={})
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT nct_id, last_update_post_date FROM studies WHERE nct_id = ANY(%s)",
            (body.nct_ids,),
        )
        rows = cur.fetchall()
    return KnownDatesResponse(known_dates={r["nct_id"]: r["last_update_post_date"] for r in rows})


@router.post("/reconcile-scope", response_model=ReconcileScopeResult)
def reconcile_scope(body: ReconcileScopeRequest, conn=Depends(get_db)):
    """Called once per condition at the end of an ingest run, with the full
    set of nct_ids the cheap-filter fetch matched (changed and unchanged
    alike). Two things happen, both non-destructive:
      1. Every nct_id in that set is confirmed: active_in_scope=true,
         last_matched_at=now() — including trials whose content didn't
         change and so were never sent to /studies/batch at all.
      2. Anything tagged with this condition that was previously
         active_in_scope but ISN'T in that set gets flagged false — e.g. it
         aged out of the recency window, or its status moved outside what
         we track. The row and its full history stay; only the flag moves,
         matching how ClinicalTrials.gov itself never removes a record
         either (see docs/decisions.md, 2026-08-28).
    """
    if not body.current_nct_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "refusing to reconcile scope against an empty nct_id set - that "
                "would flag every currently-tracked study for this condition as "
                "out of scope in one shot, almost certainly an upstream fetch "
                "failure rather than a real result"
            ),
        )

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE studies SET active_in_scope = true, last_matched_at = now() "
            "WHERE nct_id = ANY(%s)",
            (body.current_nct_ids,),
        )
        confirmed = cur.rowcount

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT s.nct_id FROM studies s
            JOIN study_conditions sc ON sc.nct_id = s.nct_id
            WHERE sc.condition ILIKE %s AND s.active_in_scope = true
              AND NOT (s.nct_id = ANY(%s))
            """,
            (f"%{body.condition}%", body.current_nct_ids),
        )
        dropped = [row["nct_id"] for row in cur.fetchall()]

    if not dropped:
        return ReconcileScopeResult(confirmed_in_scope=confirmed, dropped_out_of_scope=0)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE studies SET active_in_scope = false WHERE nct_id = ANY(%s)",
            (dropped,),
        )
        change_rows = [(nct_id, "active_in_scope", "true", "false") for nct_id in dropped]
        psycopg2.extras.execute_values(cur, INSERT_CHANGES, change_rows)

    return ReconcileScopeResult(confirmed_in_scope=confirmed, dropped_out_of_scope=len(dropped))
