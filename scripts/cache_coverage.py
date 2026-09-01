"""Would this query be free? Answers without calling anything.

The on-disk cache keys on sha256(model + effort + system prompt + user
content). A query replays for $0.00 only if *every* call it makes was
recorded before — the one interest parse, plus one per trial.

This walks the real pipeline (real database, real candidate selection, real
payload construction) and, instead of calling the model, asks the cache
whether that exact call is already on disk. So it reports exactly how much a
query would cost before you commit to it. Free, and safe to run with no
credits at all.

Run:
    PYTHONPATH=. .venv/bin/python scripts/cache_coverage.py \
        "<researcher interest>" "<condition>" <limit>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from api import ranking  # noqa: E402
from api.main import app  # noqa: E402

COST_PER_CALL = 0.019  # measured 2026-09-01 on real trial records, not fixtures

hits, misses = [], []


def cache_probe(client, system, user_content, schema, spend):
    """Stands in for the paid call: reports hit/miss, never spends."""
    key = ranking._cache_key(system, user_content)
    cached = ranking._cache_read(key)
    label = "parse" if "approach_types" in schema["properties"] else "trial"
    if cached is not None:
        hits.append(label)
        spend.record_cache_hit()
        return cached
    misses.append(label)
    # Return a well-formed stub so the pipeline continues and we can count
    # every call the query would make, not just the ones before the first miss.
    if label == "parse":
        return {k: None for k in schema["properties"]} | {"condition_terms": ["x"]}
    return {
        f: ("unknown" if f.endswith("_status")
            else "low" if f.endswith("_confidence")
            else "[cache probe]")
        for f in schema["properties"]
    }


def main() -> int:
    interest = sys.argv[1] if len(sys.argv) > 1 else "breast cancer immunotherapy"
    condition = sys.argv[2] if len(sys.argv) > 2 else "breast cancer"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    ranking._structured_call = cache_probe
    ranking._client = lambda: object()

    TestClient(app).post("/rank", json={
        "researcher_interest": interest, "condition": condition, "limit": limit,
    })

    total = len(hits) + len(misses)
    cost = len(misses) * COST_PER_CALL
    print(f"interest : {interest[:70]}")
    print(f"condition: {condition}   limit: {limit}\n")
    print(f"  calls needed : {total}")
    print(f"  already cached: {len(hits)}  (free)")
    print(f"  NOT cached    : {len(misses)}  -> would cost ~${cost:.2f}")
    if misses:
        print(f"    of which {misses.count('parse')} parse, {misses.count('trial')} per-trial")
    print()
    print("VERDICT: entirely free." if not misses
          else f"VERDICT: needs ~${cost:.2f} of credit. Not free.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
