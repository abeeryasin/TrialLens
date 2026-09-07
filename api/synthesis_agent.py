"""The weekly synthesis agent (step 9 follow-on).

The one genuinely multi-step judgment in the product (CLAUDE.md sec. 5):
"is this week's movement a pattern or a coincidence?" Investigate's numbers
are exactly checkable — arithmetic over study_changes — but nothing compares
them across weeks or decides which of several true facts is worth a
researcher's attention. That comparison is what this module does.

Runs weekly, in the scheduled job (scripts/run_synthesis.py), never in the
request path — same rule as step 7c's prose interpreter
(api/prose_interpreter.py). Its only tools are TrialLens's own read
endpoints (GET /investigate, /investigate/landscape,
/studies/{id}/amendments, /synthesis/proposals), called over HTTP exactly
the way scripts/ingest.py's WRITES already go through the locally-started
FastAPI (CLAUDE.md sec. 5, "FastAPI is the only door to the database") —
this module never opens a database connection itself.

Design, from docs/decisions.md, 2026-09-04:
  - ONE specialist agent, not a crew. External evidence: a three-agent
    pipeline consumes ~2.9x a single agent's tokens, and the findings
    payload this agent reads is a few KB — nowhere near a context-window or
    adversarial-roles problem that would justify more than one agent.
  - A multi-turn tool-use loop (the model decides what to read), capped at
    MAX_TURNS=10. Each turn resends the growing conversation, which is why
    the costed per-run figure (~$0.145) is roughly 100x a single step-7c
    call rather than ~10x.
  - Every proposal carries its evidence (CLAUDE.md sec. 3 — no conclusion
    without the source it was drawn from) and a confidence LABEL, never a
    number (sec. 3's "no unexplained relevance scores" rule — the same one
    step 7's ranking layer was removed for).
  - The agent proposes; it never decides. Every output is written to
    review_queue as 'pending' by the caller — a human accepts or dismisses
    it. This module never writes to the database.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from anthropic import Anthropic

from api.safe_errors import describe

MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 10

# claude-haiku-4-5 list price, $ per million tokens — same figures as
# api/prose_interpreter.py, duplicated rather than imported: these two
# modules' pricing comments each stand on their own, and the constant is
# three lines, not worth a cross-module dependency for.
HAIKU_INPUT_USD_PER_MTOK = 1.00
HAIKU_OUTPUT_USD_PER_MTOK = 5.00

# Used ONLY to decide, before a turn, whether there is room for one more —
# the real per-turn cost varies with how much history has accumulated, and
# is only known after the call returns (from response.usage, summed into
# the `spend` this module actually reports). Deliberately generous: a guard
# that stops one turn early costs nothing; one that lets a turn through
# past the ceiling is the failure step 7c already had once
# (docs/decisions.md, 2026-09-03).
COST_ESTIMATE_PER_TURN_USD = 0.03

SYSTEM_PROMPT = """You are TrialLens's weekly synthesis agent.

Your one job: decide whether this week's movement across tracked clinical \
trials is a genuine pattern worth a researcher's attention, or ordinary \
noise. TrialLens's own deterministic analysis (the tools below) already \
computed every number correctly — subtraction, counting, date arithmetic. \
Your job is the comparison and the judgment those numbers cannot make of \
themselves.

Rules:
- Every fact you state must come from a tool call you actually made this \
run. Never state a number, a trial name, or a date you have not read from \
a tool result.
- Compare the current window (get_window weeks_ago=0) against at least 2-3 \
prior weeks before calling anything a pattern. One week's number alone is \
never enough to justify "high" confidence — that is exactly the kind of \
single-point noise this job exists to filter out.
- Before filing a proposal, call get_recent_proposals to see what earlier \
runs already flagged. If this week's finding is the same thing continuing, \
say so in the evidence field ("still true, third week running") instead of \
filing it as if it were new — a reviewer should not have to notice five \
differently-worded rows are one story.
- A quiet, unremarkable week is a normal and valid outcome. Do not \
manufacture a finding to have something to report — call propose_finding \
zero times if nothing stood out.
- Never make a clinical judgment, never say a trial is or is not a good \
fit for any patient, and never state something as certain that the record \
does not support. Say what changed, over what window, compared to what \
baseline — the same register TrialLens itself uses everywhere else \
(CLAUDE.md sec. 2).
- When you are done — whether you filed zero or several proposals — stop \
calling tools and write one short closing sentence summarising what you \
checked."""

TOOLS = [
    {
        "name": "get_window",
        "description": (
            "Read TrialLens's own deterministic weekly analysis (date "
            "slips, lifecycle transitions, enrollment misses, primary "
            "outcome changes, scope exits) for a 7-day window. "
            "weeks_ago=0 is this run's own current window; weeks_ago=1 is "
            "the 7 days before that, and so on. Use several calls with "
            "increasing weeks_ago to see whether this week's numbers are "
            "part of a trend or a one-off.\n"
            "Each finding gives you `counts` (compare these across weeks), "
            "`trials` (the NCT IDs behind it, strongest or largest first) "
            "and `trials_total` (how many there really were — always "
            "compute shares against this, never against len(trials), which "
            "is a capped reading list).\n"
            "This is a SUMMARY. Per-trial detail — titles, before/after "
            "values, diffs — is deliberately not here, because you read "
            "several windows and every earlier one is re-sent on every "
            "later turn. Call get_trial_amendments for any trial you want "
            "to look at properly.\n"
            "Outcome categories: `substantive` means a measure name, "
            "observation window or endpoint definition MOVED. "
            "`entry_completed` means a definition was filled in where the "
            "entry was previously silent — a more complete record, not "
            "evidence the endpoint changed. `reformatting` means "
            "capitalisation, punctuation or list numbering only; those "
            "trial IDs are not listed because they carry nothing, so read "
            "that count as 'changes not shown to you', never as 'changes "
            "that did not matter' — the comparison has known blind spots "
            "and cannot see a field it does not read."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks_ago": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 8,
                    "description": "0 = this run's own window, 1 = the week before that, etc.",
                },
                "condition": {
                    "type": "string",
                    "description": "Optional: restrict to one tracked condition (substring match). Omit for everything tracked.",
                },
            },
            "required": ["weeks_ago"],
        },
    },
    {
        "name": "get_landscape",
        "description": (
            "Read the corpus-level picture (trials started per year, "
            "phase mix, enrollment bands, status mix, what interventions "
            "are being tested, who runs them). Not time-windowed — this "
            "is the standing shape of everything tracked, useful for "
            "judging whether a weekly movement is large relative to the "
            "field it happened in."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "description": "Optional: restrict to one tracked condition.",
                }
            },
        },
    },
    {
        "name": "get_trial_amendments",
        "description": (
            "Read one trial's full amendment history — every dated "
            "change, grouped into the sponsor amendments that caused "
            "them. Use this to look closer at a specific trial a window "
            "finding named, before proposing something about it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nct_id": {"type": "string", "description": "e.g. NCT04837586"}
            },
            "required": ["nct_id"],
        },
    },
    {
        "name": "get_recent_proposals",
        "description": (
            "Read what earlier weekly runs already proposed. Call this "
            "before filing anything, so a pattern that has been true for "
            "several weeks running gets reported as continuing rather "
            "than as five separate 'new' findings that are really one "
            "story."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "How many days of history to check. Defaults to 28 (about a month of weekly runs).",
                }
            },
        },
    },
    {
        "name": "propose_finding",
        "description": (
            "File one proposal for a human researcher to review. Call "
            "this when you have found something genuinely worth their "
            "attention — a pattern across multiple weeks, a large move "
            "against the corpus baseline, or a specific trial worth "
            "flagging. Do NOT call this for a routine, unremarkable week. "
            "You may call it more than once if there are several distinct "
            "findings. Every claim must be traceable to a tool result you "
            "actually read."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding_type": {
                    "type": "string",
                    "description": "A short label, e.g. 'outcome_change_cluster', 'enrollment_trend', 'single_trial_flag'.",
                },
                "summary": {
                    "type": "string",
                    "description": "One or two sentences: what changed, over what window, compared to what. Never a verdict or a clinical judgment.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "high = consistent across multiple weeks or a large deviation from baseline. low = one week's number that could be chance.",
                },
                "evidence": {
                    "type": "string",
                    "description": "Which tool calls and which specific numbers support this — cite them concretely.",
                },
            },
            "required": ["finding_type", "summary", "confidence", "evidence"],
        },
    },
]


def _call_cost_usd(usage) -> float:
    """Real cost of one turn, from the token counts the API reports.
    Cache fields ignored — see api/prose_interpreter.py's identical note:
    this loop resends unique, growing history every turn, so there is no
    cache discount to account for."""
    return (
        usage.input_tokens * HAIKU_INPUT_USD_PER_MTOK
        + usage.output_tokens * HAIKU_OUTPUT_USD_PER_MTOK
    ) / 1_000_000


def _client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Store it in .env.local (gitignored), "
            "never in the repo."
        )
    return Anthropic(api_key=api_key)


def _get(api_base_url: str, path: str, params: Optional[dict] = None) -> dict:
    response = requests.get(f"{api_base_url}{path}", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _execute_tool(
    api_base_url: str, name: str, tool_input: dict, days: int, proposals: list
) -> dict:
    """Run one tool call the model asked for. Returns the JSON handed back
    to the model as the tool result — real API data for the three read
    tools, and a bare acknowledgement for propose_finding, whose actual
    effect is appending to `proposals` rather than returning information."""
    if name == "get_window":
        weeks_ago = tool_input.get("weeks_ago", 0)
        as_of = datetime.now(timezone.utc) - timedelta(days=7 * weeks_ago)
        # The SUMMARY route, not /investigate (2026-09-07). Measured, not
        # assumed: one /investigate response is 39,972 characters, of which
        # 99.3% is per-trial reading lists built for a human to click and
        # 277 characters are the numbers this agent reasons with. It reads
        # 4-6 windows and the Messages API is stateless, so window 1 is
        # re-sent on every turn after it — the loop was paying for those
        # cards five or six times over to answer a question about totals.
        # The summary is 4,113 characters, 89.7% smaller, same arithmetic.
        params = {"days": days, "as_of": as_of.isoformat()}
        if tool_input.get("condition"):
            params["condition"] = tool_input["condition"]
        return _get(api_base_url, "/investigate/summary", params)

    if name == "get_landscape":
        params = {}
        if tool_input.get("condition"):
            params["condition"] = tool_input["condition"]
        return _get(api_base_url, "/investigate/landscape", params)

    if name == "get_trial_amendments":
        nct_id = tool_input["nct_id"]
        return _get(api_base_url, f"/studies/{nct_id}/amendments")

    if name == "get_recent_proposals":
        params = {}
        if tool_input.get("days"):
            params["days"] = tool_input["days"]
        return _get(api_base_url, "/synthesis/proposals", params)

    if name == "propose_finding":
        proposals.append(
            {
                "finding_type": tool_input["finding_type"],
                "summary": tool_input["summary"],
                "confidence": tool_input["confidence"],
                "evidence": tool_input["evidence"],
            }
        )
        return {"recorded": True, "proposals_so_far": len(proposals)}

    raise ValueError(f"Unknown tool: {name}")


def run_synthesis(
    api_base_url: str,
    days: int = 7,
    condition: Optional[str] = None,
    max_cost_usd: float = 0.25,
    max_turns: int = MAX_TURNS,
) -> tuple[list[dict], float, Optional[str]]:
    """Run one weekly synthesis pass. Returns (proposals, spend_usd, error).

    Each proposal: {finding_type, summary, confidence, evidence}. This
    function never writes to the database — the caller
    (scripts/run_synthesis.py) attaches the run's window bounds and writes
    to review_queue, the same split api/prose_interpreter.py's
    interpret_amendments_batch takes from scripts/run_monitor.py's writes.

    **It returns its error instead of raising it, and that is the fix for a
    real incident** (2026-09-07). The caller's `except` was written to record
    partial spend on a failure and could not: `proposals, spend = ...` never
    binds when the callee raises, so `spend` stayed at its initialised 0.0.
    The scheduled run that day made five paid calls, died on the sixth, and
    recorded "$0.0000 spent" — money the rolling 30-day ceiling is supposed
    to bound, invisible to it. That is the exact accounting hole step 7c
    already paid for once (docs/decisions.md, 2026-09-03), reopened by a
    comment that described the intent while the code did the opposite.

    Returning `(spend, error)` is the shape `run_prose_interpretation()`
    already uses for the same reason, so the two paid paths now fail the
    same way. The caller still fails the workflow — GitHub's notification is
    the alarm — but it does so AFTER the spend is on file.

    Raises: ValueError if ANTHROPIC_API_KEY is not set. That one is a
    misconfiguration found before any call, so there is no spend to lose.
    """
    proposals: list = []
    spend = 0.0
    error: Optional[str] = None
    client = _client()

    task = f"Run this week's synthesis pass. The current window is the last {days} days"
    if condition:
        task += f", restricted to '{condition}'"
    task += (
        ". Start by reading the current window with get_window weeks_ago=0, "
        "then compare it against recent history before deciding whether "
        "anything is worth flagging."
    )
    messages = [{"role": "user", "content": task}]

    try:
        for _ in range(max_turns):
            if spend + COST_ESTIMATE_PER_TURN_USD > max_cost_usd:
                print(
                    f"  Stopping: another turn could exceed the ${max_cost_usd:.2f} "
                    "run budget.",
                    flush=True,
                )
                break

            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
            spend += _call_cost_usd(response.usage)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = _execute_tool(
                        api_base_url, block.name, block.input, days, proposals
                    )
                    content = json.dumps(result)
                except Exception as exc:  # noqa: BLE001 — reported to the model, not raised
                    content = json.dumps({"error": str(exc)})
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content}
                )

            # An empty list here would be sent as a user message with no
            # content, which the API rejects outright — and did, on
            # 2026-09-07: "messages.8: user messages must have non-empty
            # content" killed a scheduled run on its sixth turn after five
            # paid calls. stop_reason said tool_use and no tool_use block
            # came back with it.
            #
            # Stopping is the only correct move: there is nothing to reply
            # with, and appending an empty turn cannot become valid later.
            # Recorded as an error rather than a quiet break, because a run
            # that ends here and files nothing is otherwise indistinguishable
            # from a week the agent examined and correctly found quiet.
            if not tool_results:
                error = (
                    "the model returned stop_reason='tool_use' with no "
                    f"tool_use block (content types: "
                    f"{sorted({b.type for b in response.content}) or 'none'}); "
                    "stopped rather than send an empty message"
                )
                print(f"  ANOMALY: {error}", flush=True)
                break

            messages.append({"role": "user", "content": tool_results})
    except Exception as exc:  # noqa: BLE001 — returned, so the spend survives
        error = describe(exc)

    return proposals, spend, error
