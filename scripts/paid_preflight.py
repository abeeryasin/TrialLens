"""Gate in front of every paid model run. Free to run; refuses to be skipped.

Implements two rules that were written down after real money was wasted on
2026-08-31 (docs/decisions.md, "Unit 4 verified; two more bugs"):

  1. **No paid call until a free test of the same path passes.** Bug #9 —
     `POST /rank` returning a 500 on every request — was findable for $0 by
     an HTTP-level test with the model stubbed. That test was written
     *after* a $0.13 live run found it, not before. The whole 21-call run
     was billed and its result thrown away.

  2. **Batch the paid verification.** Several pending questions each cost
     ~$0.13 to answer alone, but nearly nothing extra when folded into a run
     that is happening anyway. The checklist below exists so they are asked
     together instead of one at a time.

Run before spending anything:

    PYTHONPATH=. .venv/bin/python scripts/paid_preflight.py

Exit code 0 means the free half is green and it is reasonable to spend.
Non-zero means fix that first — the bug you are about to pay to discover
may already be sitting in a failing free test.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The free suite. Deliberately excludes the paid harness — running the thing
# you are gating on would defeat the point.
FREE_SUITE = [
    sys.executable, "-m", "pytest", "tests/", "-q",
    "--ignore=tests/test_ranking_integration.py",
]

# Everything still awaiting a paid answer. Add to this rather than making a
# one-off run: the marginal cost of one more question inside an existing run
# is roughly zero, and a separate run costs another ~$0.13.
#
# Each entry: (what it would establish, why free tests cannot establish it).
PENDING_PAID_CHECKS = [
    (
        "approach_match actually scores instead of returning unknown 20/20",
        "Free tests prove the approach reaches the payload (bug #10's guard). "
        "Whether the model then uses it is a fact about the model, not the "
        "plumbing, so only a real call shows it.",
    ),
    (
        "The prior-treatment eval case against real criteria text",
        "Designed but never built. 3,407 trials carry prior-therapy language; "
        "the signal carries 15% weight and has never been checked on real text.",
    ),
    (
        "Whether effort=high changes ranking order enough to justify the cost",
        "--sweep-effort. A judgement about model behaviour, not about code.",
    ),
]

COST_PER_CALL = 0.006  # measured, effort=low, claude-opus-5, prompt caching on


def free_suite_is_green() -> bool:
    print("Running the free suite before allowing any spend...\n")
    result = subprocess.run(FREE_SUITE, cwd=ROOT)
    return result.returncode == 0


def main() -> int:
    if not free_suite_is_green():
        print(
            "\nREFUSING to green-light a paid run: the free tests are red.\n"
            "Fix them first. A failing free test is the cheapest possible "
            "version of the bug you would otherwise pay to find — that is "
            "exactly how bug #9 cost $0.13.",
        )
        return 1

    print("\nFree suite is green. Spending is reasonable.\n")

    if not PENDING_PAID_CHECKS:
        print("No paid checks pending.")
        return 0

    print(
        f"{len(PENDING_PAID_CHECKS)} question(s) are waiting on a paid run. "
        f"Ask them together — a separate run for each costs ~"
        f"${COST_PER_CALL * 21:.2f} every time, and folding one into a run "
        f"that is already happening costs almost nothing:\n"
    )
    for i, (question, why) in enumerate(PENDING_PAID_CHECKS, 1):
        print(f"  {i}. {question}")
        print(f"     why it can't be free: {why}\n")

    print(
        "Cached responses replay for $0.00, so re-running after a scoring, "
        "weighting or display change is free. Only a real prompt, model or "
        "effort change forces new spend."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
