from typing import List, Optional

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_db, get_readonly_db
from api.schemas import BatchUpsertResult, StudyDetail, StudyList, StudySummary, StudyUpsert

router = APIRouter(prefix="/studies", tags=["studies"])

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
            SELECT nct_id, brief_title, overall_status, phase, last_update_post_date
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
        cur.execute("SELECT * FROM studies WHERE nct_id = %s", (nct_id,))
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
    """Upsert a batch of studies + their condition tags. Used by scripts/ingest.py."""
    if not records:
        return BatchUpsertResult(studies_written=0, condition_tags_written=0)

    study_rows = [
        (
            r.nct_id, r.brief_title, r.official_title, r.overall_status,
            r.study_type, r.phase, r.enrollment_count, r.sex,
            r.minimum_age, r.healthy_volunteers, r.eligibility_criteria,
            r.last_update_post_date, psycopg2.extras.Json(r.raw_json),
        )
        for r in records
    ]

    with conn.cursor() as cur:
        template = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())"
        psycopg2.extras.execute_values(cur, UPSERT_STUDIES, study_rows, template=template)

        nct_ids = [r.nct_id for r in records]
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
        studies_written=len(records), condition_tags_written=len(condition_rows)
    )
