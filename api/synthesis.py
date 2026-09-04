"""The review queue's one read door: GET /synthesis/proposals.

Read-only, same role as every other GET route (CLAUDE.md sec. 5 — FastAPI
is the only door to the database). Two callers:

  1. The synthesis agent itself (api/synthesis_agent.py's get_recent_proposals
     tool), checking recent weeks before filing something so a genuine
     pattern reads as "still true, third week running" in its own evidence
     text rather than as five unrelated-looking rows.
  2. Whatever review UI gets built once there is real proposal data to
     design it against (deferred — see docs/decisions.md, 2026-09-05).

There is deliberately no write route here yet: review_queue rows are
written by scripts/run_synthesis.py directly, the same split
api/prose_interpreter.py's writes take from scripts/run_monitor.py.
Accept/dismiss is a human action through a page that does not exist yet.
"""
from datetime import datetime, timedelta, timezone

import psycopg2.extras
from fastapi import APIRouter, Depends, Query

from api.database import get_readonly_db
from api.schemas import ProposalList

router = APIRouter(tags=["synthesis"])

DEFAULT_LOOKBACK_DAYS = 28
MAX_LOOKBACK_DAYS = 180


@router.get("/synthesis/proposals", response_model=ProposalList)
def recent_proposals(
    days: int = Query(
        DEFAULT_LOOKBACK_DAYS,
        ge=1,
        le=MAX_LOOKBACK_DAYS,
        description="How many days of review_queue history to return, newest first.",
    ),
    limit: int = Query(50, ge=1, le=200),
    conn=Depends(get_readonly_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, created_at, window_since, window_until,
                   finding_type, summary, confidence, status
            FROM review_queue
            WHERE created_at > %(since)s
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            {"since": since, "limit": limit},
        )
        rows = cur.fetchall()
    return ProposalList(proposals=[dict(row) for row in rows])
