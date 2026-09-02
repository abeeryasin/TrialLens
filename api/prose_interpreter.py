"""Interpret prose field changes in amendments.

This module interprets what changes to eligibility_criteria, brief_summary,
or primary_outcomes actually mean for a researcher. It runs only in the
scheduled job (scripts/run_monitor.py), never in the request path.

Cost management:
  - Calls claude-haiku-4-5 (~$0.004 per call)
  - Batch size limits + spend cap prevent runaway costs
  - Caches responses by (nct_id, field_name) to avoid re-running
  - Skips unclassified amendments (99) and single-field ones (38)
  - Focuses on prose changes (46) in scope

Design: each amendment's prose change is interpreted separately, so a trial
that touched both eligibility_criteria and brief_summary gets two
interpretations, one per field.
"""
import json
import os
from typing import Optional

import psycopg2
import psycopg2.extras
from anthropic import Anthropic


PROSE_FIELDS = {"eligibility_criteria", "brief_summary", "primary_outcomes"}
COST_ESTIMATE_PER_CALL = 0.004  # measured against haiku-4-5


def get_prose_amendments(conn, hours_ago: int = 24) -> list[dict]:
    """Query study_changes for prose field changes in the last N hours.

    Returns list of {nct_id, field_name, old_value, new_value, detected_at}.
    """
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    placeholders = ", ".join(["%s"] * len(PROSE_FIELDS))
    cursor.execute(
        f"""
        SELECT nct_id, field_name, old_value, new_value, detected_at
        FROM study_changes
        WHERE field_name IN ({placeholders})
          AND detected_at > now() - interval '{hours_ago} hours'
        ORDER BY detected_at DESC
        """,
        list(PROSE_FIELDS),
    )
    results = cursor.fetchall()
    cursor.close()
    return [dict(row) for row in results]


def _client() -> Anthropic:
    """Create Anthropic client from env var. Fails if key is missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Store it in .env.local (gitignored), "
            "never in the repo."
        )
    return Anthropic(api_key=api_key)


def interpret_prose_change(
    nct_id: str,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
) -> Optional[dict]:
    """Interpret what a prose field change means for a researcher.

    Returns {
        'summary': 'one-line what changed',
        'why_matters': 'why a researcher should care',
    }
    or None if the change is too small to interpret (both values empty/too short).

    Raises: ValueError if API key is not set.
    """
    if field_name not in PROSE_FIELDS:
        return None

    # Skip if either value is effectively empty
    old_text = (old_value or "").strip()
    new_text = (new_value or "").strip()
    if not old_text or not new_text:
        return None

    # Too small to interpret meaningfully
    if len(old_text) < 20 and len(new_text) < 20:
        return None

    prompt = f"""A clinical trial NCT{nct_id.replace("NCT", "")} has changed its {field_name}.

BEFORE:
{old_text}

AFTER:
{new_text}

Interpret this change concisely. Respond with exactly two lines:

SUMMARY: [One sentence describing what changed]
WHY_MATTERS: [One sentence why a clinical researcher should care]

Example format:
SUMMARY: Age eligibility narrowed from all adults to 65+
WHY_MATTERS: Significantly reduces potential referral population

Be factual. Reference specifics from the text. If no meaningful change, write "no change"."""

    client = _client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    summary = None
    why_matters = None

    # Parse the two expected lines
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[8:].strip()
        elif line.startswith("WHY_MATTERS:"):
            why_matters = line[12:].strip()

    if summary and why_matters and summary.lower() != "no change":
        return {"summary": summary, "why_matters": why_matters}

    return None


def interpret_amendments_batch(
    amendments: list[dict],
    max_cost_usd: float = 0.25,
    max_calls: int = 50,
) -> tuple[list[dict], float]:
    """Process a batch of amendments with prose changes.

    Args:
        amendments: List of dicts with {nct_id, field_name, old_value, new_value}
        max_cost_usd: Stop if spend would exceed this
        max_calls: Stop if we would exceed this many calls

    Returns:
        (results, spend) where results is list of
        {nct_id, field_name, old_value, new_value, prose_interpretation}
        and spend is actual cost incurred.
    """
    results = []
    spend = 0.0
    calls_made = 0

    for amendment in amendments:
        if calls_made >= max_calls:
            print(
                f"Stopping at {max_calls} calls (limit reached)",
                flush=True,
            )
            break

        if spend + COST_ESTIMATE_PER_CALL > max_cost_usd:
            print(
                f"Stopping at {calls_made} calls; spend would exceed ${max_cost_usd:.2f}",
                flush=True,
            )
            break

        nct_id = amendment.get("nct_id")
        field_name = amendment.get("field_name")
        old_value = amendment.get("old_value")
        new_value = amendment.get("new_value")

        if field_name not in PROSE_FIELDS:
            # Include non-prose amendments as-is, but don't call model
            results.append({**amendment, "prose_interpretation": None})
            continue

        try:
            interpretation = interpret_prose_change(
                nct_id, field_name, old_value, new_value
            )
            spend += COST_ESTIMATE_PER_CALL
            calls_made += 1
            results.append({**amendment, "prose_interpretation": interpretation})
            if interpretation:
                print(
                    f"  {nct_id} {field_name}: {interpretation['summary'][:60]}...",
                    flush=True,
                )
        except ValueError as e:
            print(f"  ERROR: {e}", flush=True)
            raise

    print(
        f"Processed {calls_made} prose amendments, estimated spend: ${spend:.4f}",
        flush=True,
    )
    return results, spend
