"""Tracked conditions: the real registry of what Monitor watches.

Step 10 (2026-09-05): moved off config/tracked_conditions.json into the
tracked_conditions table so adding a condition is a UI action, not a file
edit + redeploy. GET is read-only (get_readonly_db, same role every other
GET route uses); POST is the one write this table needs, so it uses get_db
like /studies/batch does — no edit/delete endpoint yet, since the roadmap's
actual ask was adding through the UI, not full CRUD.

list_tracked_conditions() is a plain function, not a route, so
api/discover.py and api/watch.py can call it with their own already-open
connection instead of importing this module's route function directly
(which would need a live FastAPI request to resolve its Depends()).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api.database import get_db, get_readonly_db
from api.schemas import AddConditionRequest, AddConditionResponse

router = APIRouter(tags=["conditions"])


def list_tracked_conditions(conn) -> List[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT condition FROM tracked_conditions ORDER BY condition")
        return [row[0] for row in cur.fetchall()]


@router.get("/tracked-conditions", response_model=List[str])
def tracked_conditions(conn=Depends(get_readonly_db)):
    """The real registry Monitor comprehensively tracks — same table
    api/discover.py checks. Exposed as its own read so the frontend can
    show what's actually being watched without touching Postgres directly
    (frontend goes through FastAPI only, same rule as everywhere else)."""
    return list_tracked_conditions(conn)


@router.post("/tracked-conditions", response_model=AddConditionResponse, status_code=201)
def add_tracked_condition(payload: AddConditionRequest, conn=Depends(get_db)):
    condition = payload.condition.strip()
    if not condition:
        raise HTTPException(status_code=400, detail="condition cannot be empty")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM tracked_conditions WHERE lower(condition) = lower(%s)",
            (condition,),
        )
        if cur.fetchone() is not None:
            raise HTTPException(
                status_code=409, detail=f"'{condition}' is already tracked"
            )
        cur.execute(
            "INSERT INTO tracked_conditions (condition) VALUES (%s)", (condition,)
        )

    return AddConditionResponse(condition=condition)
