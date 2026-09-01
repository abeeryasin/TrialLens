"""The whole /rank pipeline against the real database, with the model stubbed.

Free. No API key, no model call, no spend.

This is the guard that would have prevented bug #9 from costing $0.13. That
bug — the endpoint returning a `ResearcherPreferences` where the response
schema wanted `ResearcherPreferencesOut` — raised a 500 *after* all 21 model
calls had been billed, and threw the entire result away. Nothing caught it
because every test either called scoring functions directly or stubbed the
database as well.

So this stubs exactly one thing: `_structured_call`, the single function
that costs money. Everything else is real —

    real trials  ->  real candidate selection over thousands of rows
                 ->  real deterministic scorers
                 ->  real shortlist + full-record fetch
                 ->  real build_ranking / score_signals
                 ->  real FitRankingResponse validation
                 ->  real HTTP response

— so any crash, any Pydantic validation error, and any scorer that chokes on
a real trial's data surfaces here for $0 instead of after the bill.

The stub deliberately cycles through **every** status in the enum, including
`not_applicable` and `unknown`, because a status the real model returns and
the response schema rejects is precisely the failure mode being guarded
against.

Run:
    PYTHONPATH=. .venv/bin/python scripts/rank_dry_run.py [condition] [limit]
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from api import ranking  # noqa: E402
from api.main import app  # noqa: E402

# Every value the schema allows. If the real model returns one of these and
# anything downstream can't handle it, that must fail here, not after paying.
STATUSES = itertools.cycle(["match", "partial", "no_match", "unknown", "not_applicable"])
CONFIDENCES = itertools.cycle(["high", "medium", "low"])


def fake_structured_call(client, system, user_content, schema, spend):
    """Stands in for the only function that spends money.

    Returns whatever shape the requested schema asks for, so it serves both
    the interest parse and the per-trial semantic call without knowing which
    is which.
    """
    if "approach_types" in schema["properties"]:          # the interest parse
        return {
            "condition_terms": ["breast cancer"],
            "phases": ["PHASE2", "PHASE3"],
            "require_recruiting": True,
            "min_age_years": 18.0,
            "max_age_years": None,
            "prior_treatment_context": "at least one prior line",
            "approach_context": "immunotherapy or targeted agents",
            "approach_types": ["DRUG", "BIOLOGICAL"],
        }

    out = {}                                              # the semantic call
    for field in schema["properties"]:
        if field.endswith("_status"):
            out[field] = next(STATUSES)
        elif field.endswith("_confidence"):
            out[field] = next(CONFIDENCES)
        else:
            out[field] = "[dry run] stubbed evidence, no model was called."
    return out


def main() -> int:
    condition = sys.argv[1] if len(sys.argv) > 1 else "breast cancer"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    ranking._structured_call = fake_structured_call
    ranking._client = lambda: object()

    print(f"Dry run: /rank over the real database, model stubbed.")
    print(f"condition={condition!r} limit={limit}\n")

    response = TestClient(app).post("/rank", json={
        "researcher_interest": "dry run — no model was called",
        "condition": condition,
        "limit": limit,
    })

    if response.status_code != 200:
        print(f"FAILED: HTTP {response.status_code}\n{response.text[:2000]}")
        print(
            "\nThis is exactly the class of failure that cost $0.13 as bug #9. "
            "Do NOT run the paid version until this returns 200."
        )
        return 1

    body = response.json()
    print(f"HTTP 200 — response validated against FitRankingResponse.\n")
    print(f"  ranked      : {len(body['ranked_trials'])}")
    print(f"  failures    : {body['failures'] or 'none'}")
    print(f"  unspecified : {[u['field'] for u in body['unspecified']]}")
    print(f"  notes       : {body['notes'][:120]}...")

    statuses = {}
    for trial in body["ranked_trials"]:
        for signal in trial["signals"]:
            statuses[signal["status"]] = statuses.get(signal["status"], 0) + 1
    print(f"\n  every status survived the round trip: {statuses}")

    if body["failures"]:
        print(
            "\nWARNING: some trials failed to score even with a stubbed model. "
            "That is a real bug in scoring or validation — fix it before paying."
        )
        return 1

    print("\nPipeline is sound end to end. Paying for real output is reasonable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
