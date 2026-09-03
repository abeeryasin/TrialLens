"""Interpret prose field changes in amendments.

This module interprets what changes to eligibility_criteria, brief_summary,
or primary_outcomes actually mean for a researcher. It runs only in the
scheduled job (scripts/run_monitor.py), never in the request path.

Cost management:
  - Calls claude-haiku-4-5 (~$0.004 per call)
  - Batch size limits + spend cap prevent runaway costs
  - Pre-filters: skip >90% similar text (formatting only) before API
  - Caches responses by (nct_id, field_name) to avoid re-running
  - Skips unclassified amendments (99) and single-field ones (38)
  - Focuses on prose changes (46) in scope

Design: each amendment's prose change is interpreted separately, so a trial
that touched both eligibility_criteria and brief_summary gets two
interpretations, one per field.
"""
import difflib
import json
import os
from typing import Optional

import psycopg2
import psycopg2.extras
from anthropic import Anthropic


PROSE_FIELDS = {"eligibility_criteria", "brief_summary", "primary_outcomes"}

# Used ONLY to decide whether there is room for another call before making it —
# you cannot know a call's cost until it returns. What gets recorded afterwards
# is the real figure from `response.usage`, never this. Until 2026-09-04 this
# constant was the recorded spend too, which made the rolling ceiling a
# multiplication rather than a measurement.
COST_ESTIMATE_PER_CALL = 0.004

# claude-haiku-4-5 list price, $ per million tokens (verified 2026-09-04).
# Output is 5x input, which is why the prompt asks for one line instead of two.
HAIKU_INPUT_USD_PER_MTOK = 1.00
HAIKU_OUTPUT_USD_PER_MTOK = 5.00


def _call_cost_usd(usage) -> float:
    """Real cost of one call, from the token counts the API reports.

    Cache fields are ignored on purpose: this call sends a unique diff every
    time and caches nothing, so counting them would imply a discount that was
    never earned.
    """
    return (
        usage.input_tokens * HAIKU_INPUT_USD_PER_MTOK
        + usage.output_tokens * HAIKU_OUTPUT_USD_PER_MTOK
    ) / 1_000_000


def get_prose_amendments(conn, hours_ago: int = 24) -> list[dict]:
    """Query study_changes for prose field changes in the last N hours.

    Returns list of {id, nct_id, field_name, old_value, new_value, detected_at}.

    `id` is carried so the interpretation can be written back to the exact row
    it describes. Matching on (nct_id, field_name) instead is ambiguous: a
    trial that amends the same prose field twice inside one window has two
    rows, and the interpretation of the older one would land on the newer —
    an inference attached to source text it was not drawn from (CLAUDE.md
    sec. 3).
    """
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    placeholders = ", ".join(["%s"] * len(PROSE_FIELDS))
    cursor.execute(
        f"""
        SELECT id, nct_id, field_name, old_value, new_value, detected_at
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


def _similarity_ratio(text1: str, text2: str) -> float:
    """Return 0.0-1.0 similarity between two texts (1.0 = identical).

    Uses SequenceMatcher which is O(n) and catches formatting-only changes.
    A ratio >0.90 means 90%+ of the text is the same (likely formatting only).
    """
    return difflib.SequenceMatcher(None, text1, text2).ratio()


def interpret_prose_change(
    nct_id: str,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
) -> tuple[Optional[dict], float]:
    """Interpret what a prose field change means for a researcher.

    Returns `(interpretation, cost_usd)`:
      - interpretation is {'summary': 'one line stating what changed'} when the
        model reports the substance changed, else None.
      - cost_usd is what the call actually cost, from `response.usage`. It is
        0.0 only when no call was made (a pre-filter caught it first).

    The cost is returned even when the interpretation is None, which is the
    whole point of the pair. Before 2026-09-04 a call that came back "no
    change" was recorded as $0.00 spent: real money, invisible to the budget
    ceiling that is supposed to bound it.

    Raises: ValueError if API key is not set.
    """
    if field_name not in PROSE_FIELDS:
        return None, 0.0

    # Skip if either value is effectively empty
    old_text = (old_value or "").strip()
    new_text = (new_value or "").strip()
    if not old_text or not new_text:
        return None, 0.0

    # Too small to interpret meaningfully
    if len(old_text) < 20 and len(new_text) < 20:
        return None, 0.0

    # Pre-filter: skip if texts are >90% similar (formatting changes only)
    # This catches punctuation fixes, whitespace changes, line breaks, etc.
    # without calling the API. Cheap O(n) check prevents wasteful $0.004 calls.
    similarity = _similarity_ratio(old_text, new_text)
    if similarity > 0.90:
        return None, 0.0

    prompt = f"""A clinical trial NCT{nct_id.replace("NCT", "")} has changed its {field_name}.

BEFORE:
{old_text}

AFTER:
{new_text}

Respond with exactly two lines:

SUMMARY: [One sentence stating what changed]
MEANINGFUL: [yes if the substance changed; no if only formatting, wording, ordering or presentation changed]

Example:
SUMMARY: Age eligibility narrowed from all adults to 65+
MEANINGFUL: yes

Be factual and reference specifics from the text. Do not explain why it
matters — the reader is a clinical researcher who will judge significance
themselves."""

    client = _client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    cost = _call_cost_usd(response.usage)

    text = response.content[0].text.strip()
    summary = None
    meaningful = None

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[8:].strip()
        elif line.startswith("MEANINGFUL:"):
            meaningful = line[11:].strip().lower()

    # Gate on the structured field, never on the prose.
    #
    # This used to be `summary.lower() != "no change"` — an exact string match
    # against a sentence the model writes freely. On 2026-09-03 it wrote "No
    # meaningful change—the criteria were reformatted for clarity...", which is
    # not the literal string "no change", so a paid call announcing that
    # nothing happened was stored as a finding. Matching prose will always lose
    # to rephrasing; a field the model has to fill in with yes or no will not.
    if summary and meaningful == "yes":
        return {"summary": summary}, cost

    return None, cost


def interpret_amendments_batch(
    amendments: list[dict],
    max_cost_usd: float = 0.25,
    max_calls: int = 50,
) -> tuple[list[dict], float]:
    """Process a batch of amendments with prose changes.

    Args:
        amendments: List of dicts with {nct_id, field_name, old_value, new_value}
        max_cost_usd: Stop before a call that COST_ESTIMATE_PER_CALL says would
            exceed this. The stop is predictive because a call's price is
            unknown until it returns; `spend` below is the measured total.
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
            interpretation, cost = interpret_prose_change(
                nct_id, field_name, old_value, new_value
            )
            # Bill on `cost > 0`, which means a call was actually made — not on
            # `interpretation is not None`, which only means the call produced
            # something worth storing. Those came apart on every call that
            # returned "no change": real money spent, recorded as zero, and
            # invisible to the rolling ceiling.
            spend += cost
            if cost > 0:
                calls_made += 1
                if interpretation is not None:
                    print(
                        f"  {nct_id} {field_name}: {interpretation['summary'][:60]}...",
                        flush=True,
                    )
                else:
                    print(
                        f"  {nct_id} {field_name}: no substantive change "
                        f"(${cost:.4f})",
                        flush=True,
                    )
            results.append({**amendment, "prose_interpretation": interpretation})
        except ValueError as e:
            print(f"  ERROR: {e}", flush=True)
            raise

    print(
        f"Processed {len(results)} amendments, {calls_made} API calls, "
        f"spend: ${spend:.4f}",
        flush=True,
    )
    return results, spend
