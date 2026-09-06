"""The review queue's one read door: GET /synthesis/proposals.

Read-only, same role as every other GET route (CLAUDE.md sec. 5 — FastAPI
is the only door to the database). Two callers:

  1. The synthesis agent itself (api/synthesis_agent.py's get_recent_proposals
     tool), checking recent weeks before filing something so a genuine
     pattern reads as "still true, third week running" in its own evidence
     text rather than as five unrelated-looking rows.
  2. Whatever review UI gets built once there is real proposal data to
     design it against (deferred — see docs/decisions.md, 2026-09-05).

review_queue rows are *created* by scripts/run_synthesis.py directly, the
same split api/prose_interpreter.py's writes take from
scripts/run_monitor.py. The one write route here is the other half:
**accept/dismiss, which only a human does** (2026-09-06). It was deferred
while the queue held zero rows — designing a review screen against nothing
is the step-7 mistake — and built once the first scheduled weekly run was
imminent and the gap was concrete: the agent had somewhere to file and
nobody had anywhere to read.
"""
from datetime import datetime, timedelta, timezone

import psycopg2.extras
from fastapi import APIRouter, Depends, Query

from fastapi import HTTPException

from api.database import get_db, get_readonly_db
from api.schemas import Proposal, ProposalList, ReviewDecision

router = APIRouter(tags=["synthesis"])

DEFAULT_LOOKBACK_DAYS = 28
MAX_LOOKBACK_DAYS = 180

# What a person is allowed to decide. 'pending' is not here: a proposal
# starts pending and a review is the act of leaving that state, so
# "un-review" would be a different operation with a different meaning, not
# a third choice on this one.
DECISIONS = ("accepted", "dismissed")


@router.get("/synthesis/proposals", response_model=ProposalList)
def recent_proposals(
    days: int = Query(
        DEFAULT_LOOKBACK_DAYS,
        ge=1,
        le=MAX_LOOKBACK_DAYS,
        description="How many days of review_queue history to return, newest first.",
    ),
    limit: int = Query(50, ge=1, le=200),
    include_evidence: bool = Query(
        False,
        description=(
            "Include each proposal's full evidence. Off by default because "
            "the agent reads this endpoint every week and pays by the token; "
            "the review page asks for it, the agent does not."
        ),
    ),
    conn=Depends(get_readonly_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    evidence_column = ", evidence" if include_evidence else ""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, created_at, window_since, window_until,
                   finding_type, summary, confidence, status,
                   reviewed_at, reviewed_note{evidence_column}
            FROM review_queue
            WHERE created_at > %(since)s
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            {"since": since, "limit": limit},
        )
        rows = cur.fetchall()
    return ProposalList(proposals=[dict(row) for row in rows])


@router.post("/synthesis/proposals/{proposal_id}/review", response_model=Proposal)
def review_proposal(
    proposal_id: int, payload: ReviewDecision, conn=Depends(get_db)
):
    """A person accepts or dismisses one proposal.

    Uses the full-privilege connection, like POST /studies/batch and
    POST /tracked-conditions — the only three writes the API door opens.

    **The proposal itself is never edited.** Only the review fields move:
    what the agent said, the evidence it read, and the confidence it
    claimed all stay exactly as filed, so a dismissed proposal remains
    fully readable afterwards rather than becoming a row that says only
    that someone disagreed with it (sec. 3).

    A decision can be changed — a researcher who dismisses something on
    Monday and reconsiders on Friday is doing their job, not corrupting a
    record — and `reviewed_at` moves with it so the row always says when
    the standing decision was made.
    """
    decision = payload.decision.strip().lower()
    if decision not in DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"decision must be one of {list(DECISIONS)}, got '{payload.decision}'",
        )

    note = (payload.note or "").strip() or None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE review_queue
            SET status = %(status)s, reviewed_at = now(), reviewed_note = %(note)s
            WHERE id = %(id)s
            RETURNING id, created_at, window_since, window_until, finding_type,
                      summary, confidence, status, reviewed_at, reviewed_note,
                      evidence
            """,
            {"status": decision, "note": note, "id": proposal_id},
        )
        row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no proposal with id {proposal_id}"
        )
    return Proposal(**dict(row))
