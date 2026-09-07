"""Tracked conditions: the real registry of what Monitor watches.

Step 10 (2026-09-05): moved off config/tracked_conditions.json into the
tracked_conditions table so adding a condition is a UI action, not a file
edit + redeploy. GET is read-only (get_readonly_db, same role every other
GET route uses); POST is the one write this table needs, so it uses get_db
like /studies/batch does. DELETE was added 2026-09-08, when the obvious
question after "+ Add" turned out to have a non-obvious answer: see
remove_tracked_condition below, and db/schema.sql on why it needed an
attribution table first.

list_tracked_conditions() is a plain function, not a route, so
api/discover.py and api/watch.py can call it with their own already-open
connection instead of importing this module's route function directly
(which would need a live FastAPI request to resolve its Depends()).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api.database import get_db, get_readonly_db
from api.schemas import (
    AddConditionRequest,
    AddConditionResponse,
    RemoveConditionResponse,
)

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


@router.delete("/tracked-conditions/{condition:path}", response_model=RemoveConditionResponse)
def remove_tracked_condition(condition: str, conn=Depends(get_db)):
    """Stop watching a condition, and stop watching the trials only it
    brought in.

    Untrack, never delete. `active_in_scope` moves to false and the flip is
    logged in study_changes, exactly as the scheduled scope reconciliation
    does — the row and its full history stay (docs/decisions.md, 2026-08-28).
    Ongoing cost goes to zero either way: nothing queries CT.gov for a removed
    condition, so those trials are never refetched, never diffed, and never
    reach a paid interpretation call. What a delete would additionally buy is
    disk, at the price of the amendment record the digest and Investigate are
    computed from.

    The path converter is `:path` so a condition containing a slash
    ("Obesity/Overweight" is a real CT.gov string) still addresses its own row.

    Two refusals, both deliberate:

      * **The last condition.** An empty registry is a monitor that watches
        nothing while still reporting a healthy watch — the exact state
        /ops/status raises `no_tracked_conditions` for. Add the replacement
        first; this endpoint will not hand you that state in one click.
      * **Before any attribution exists.** Removing a condition when nothing
        records which trials it brought in would silently strand them:
        active_in_scope = true, counted in the watch headline, with no query
        left that returns them. Better to wait for the next monitor run than
        to leave the record lying.
    """
    condition = condition.strip()
    if not condition:
        raise HTTPException(status_code=400, detail="condition cannot be empty")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT condition FROM tracked_conditions WHERE lower(condition) = lower(%s)",
            (condition,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"'{condition}' is not tracked")
        stored = row[0]

        cur.execute("SELECT count(*) FROM tracked_conditions")
        if cur.fetchone()[0] <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"refusing to remove '{stored}' because it is the only condition "
                    "on the watch list - an empty list is a monitor that watches "
                    "nothing while still reporting a healthy watch. Add the "
                    "replacement condition first, then remove this one."
                ),
            )

        # Global, not per-condition: a condition with no attribution rows may
        # genuinely have matched nothing (a typo someone wants to remove), and
        # that must stay removable. What is not safe is removing anything
        # before ANY run has recorded attribution at all.
        cur.execute("SELECT EXISTS (SELECT 1 FROM study_tracked_conditions)")
        if not cur.fetchone()[0]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "no monitor run has recorded which trials each condition brings "
                    "in yet, so removing one now would leave its trials watched by "
                    "nothing. The next scheduled run writes that record; retry "
                    "after it completes."
                ),
            )

        # Stamp, don't delete (the delisted_at precedent): these rows are the
        # record of why a trial stopped being watched, and re-adding the
        # condition clears the stamp on the next run.
        cur.execute(
            """
            UPDATE study_tracked_conditions SET untracked_at = now()
            WHERE lower(condition) = lower(%s) AND untracked_at IS NULL
            """,
            (stored,),
        )

        # Everything the removed condition brought in that no OTHER condition
        # still on the list also brings in. The join against tracked_conditions
        # is what makes "still watched" mean the live registry rather than any
        # attribution row that happens to be unstamped.
        cur.execute(
            """
            SELECT s.nct_id FROM studies s
            WHERE s.active_in_scope
              AND EXISTS (
                SELECT 1 FROM study_tracked_conditions st
                WHERE st.nct_id = s.nct_id AND lower(st.condition) = lower(%s)
              )
              AND NOT EXISTS (
                SELECT 1 FROM study_tracked_conditions live
                JOIN tracked_conditions tc ON lower(tc.condition) = lower(live.condition)
                WHERE live.nct_id = s.nct_id AND live.untracked_at IS NULL
              )
            """,
            (stored,),
        )
        untrack = [r[0] for r in cur.fetchall()]

        kept = 0
        cur.execute(
            """
            SELECT count(DISTINCT st.nct_id) FROM study_tracked_conditions st
            JOIN studies s ON s.nct_id = st.nct_id
            WHERE lower(st.condition) = lower(%s) AND s.active_in_scope
              AND EXISTS (
                SELECT 1 FROM study_tracked_conditions live
                JOIN tracked_conditions tc ON lower(tc.condition) = lower(live.condition)
                WHERE live.nct_id = st.nct_id AND live.untracked_at IS NULL
              )
            """,
            (stored,),
        )
        kept = cur.fetchone()[0]

        if untrack:
            cur.execute(
                "UPDATE studies SET active_in_scope = false WHERE nct_id = ANY(%s)",
                (untrack,),
            )
            # Same field, same values, same reader as a scope drop from the
            # scheduled run: this IS a tracking change, and the Monitor feed
            # already knows how to render one.
            cur.execute(
                """
                INSERT INTO study_changes (nct_id, field_name, old_value, new_value)
                SELECT nct_id, 'active_in_scope', 'true', 'false'
                FROM unnest(%s::text[]) AS t(nct_id)
                """,
                (untrack,),
            )

        cur.execute(
            "DELETE FROM tracked_conditions WHERE lower(condition) = lower(%s)", (stored,)
        )

        # Evidence about the record itself, not about this condition: trials
        # still in scope that no watched condition accounts for. 0 after a
        # full monitor run; anything else says the attribution is incomplete
        # and this answer is narrower than it looks.
        cur.execute(
            """
            SELECT count(*) FROM studies s
            WHERE s.active_in_scope
              AND NOT EXISTS (
                SELECT 1 FROM study_tracked_conditions live
                JOIN tracked_conditions tc ON lower(tc.condition) = lower(live.condition)
                WHERE live.nct_id = s.nct_id AND live.untracked_at IS NULL
              )
            """
        )
        unattributed = cur.fetchone()[0]

    return RemoveConditionResponse(
        condition=stored,
        trials_untracked=len(untrack),
        trials_kept_for_another_condition=kept,
        trials_unattributed=unattributed,
    )
