"""Evaluation harness for the ranking layer — the half that costs money.

Deliberately NOT part of the CI suite. Every run makes real API calls, so
it is invoked by hand at decision points: after a prompt change, a model
change, or before claiming a quality number. The free half of the
evaluation story lives in test_ranking_deterministic.py and
test_ranking_scoring.py and should run on every commit.

    # single run at the configured effort
    PYTHONPATH=. python3 tests/test_ranking_integration.py

    # sweep effort to measure whether reasoning depth changes results
    PYTHONPATH=. python3 tests/test_ranking_integration.py --sweep-effort

    # estimate spend without calling the API
    PYTHONPATH=. python3 tests/test_ranking_integration.py --dry-run
"""
import argparse
import os
import sys
from datetime import date, datetime
from typing import List

try:
    # .env.local is gitignored and holds the key; load it so the harness
    # doesn't depend on the key being exported into every shell.
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

import api.ranking as ranking
from api.ranking import (
    SpendTracker,
    parse_researcher_interest,
    rank_one_trial,
)
from api.schemas import StudyDetail, TrialLocation
from tests.test_data_synthetic_trials import ALL_TEST_CASES

INPUT_STYLES = ["simple", "structured", "narrative"]


def to_study_detail(synthetic) -> StudyDetail:
    """Synthetic fixture -> the real StudyDetail the scorers consume."""
    return StudyDetail(
        nct_id=synthetic.nct_id,
        brief_title=synthetic.brief_title,
        official_title=synthetic.brief_title,
        overall_status=synthetic.overall_status,
        phase=synthetic.phase,
        study_type=synthetic.study_type,
        last_update_post_date=date.today(),
        active_in_scope=True,
        enrollment_count=synthetic.enrollment_count,
        enrollment_type=synthetic.enrollment_type,
        minimum_age=synthetic.minimum_age,
        maximum_age=synthetic.maximum_age,
        eligibility_criteria=None,
        fetched_at=datetime.utcnow(),
        last_matched_at=datetime.utcnow(),
        conditions=[synthetic.condition],
        brief_summary=synthetic.brief_summary,
        lead_sponsor=synthetic.lead_sponsor,
        interventions=[],
        primary_outcomes=[],
        locations=[
            TrialLocation(facility=f"Site {i}", city="City", country="United States")
            for i in range(synthetic.locations_count or 0)
        ],
    )


def run_scenario(client, test_case, style: str, spend: SpendTracker) -> dict:
    interest_obj = next(
        (r for r in test_case.researcher_interests if r.style == style), None
    )
    if interest_obj is None:
        return {"passed": False, "error": f"no {style} interest defined"}

    trials = [to_study_detail(t) for t in test_case.test_trials]

    try:
        prefs = parse_researcher_interest(client, interest_obj.text, spend)
        rankings = [rank_one_trial(client, t, prefs, spend) for t in trials]
    except Exception as exc:  # harness reports, never hides
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}

    rankings.sort(key=lambda r: r.score, reverse=True)

    expected_order = [nct for nct, _ in test_case.expected_ranking_order]
    actual_order = [r.nct_id for r in rankings]
    order_correct = actual_order == expected_order

    top_score = rankings[0].score if rankings else 0.0
    lo, hi = test_case.expected_top_1_score_range
    in_range = lo <= top_score <= hi

    return {
        "passed": order_correct and in_range,
        "order_correct": order_correct,
        "in_range": in_range,
        "top_score": top_score,
        "expected_range": (lo, hi),
        "expected_order": expected_order,
        "actual_order": actual_order,
        "top_confidence": rankings[0].confidence if rankings else None,
        "top_evaluated": rankings[0].evaluated_weight_fraction if rankings else 0.0,
        "prefs": prefs,
        "rankings": rankings,
    }


def print_scenario(test_case, style: str, result: dict) -> None:
    header = f"{test_case.name}  [{style}]"
    print(f"\n{'=' * 74}\n{header}\n{'=' * 74}")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    prefs = result["prefs"]
    print("  Interest parsed as:")
    print(f"    conditions      : {prefs.condition_terms}")
    print(f"    phases          : {prefs.phases if prefs.phases else '(not stated)'}")
    print(f"    recruiting only : {prefs.require_recruiting if prefs.require_recruiting is not None else '(not stated)'}")
    age = (
        f"{prefs.min_age_years}–{prefs.max_age_years}"
        if (prefs.min_age_years is not None or prefs.max_age_years is not None)
        else "(not stated)"
    )
    print(f"    age band        : {age}")

    print("  Ranking:")
    for i, r in enumerate(result["rankings"], 1):
        print(
            f"    {i}. {r.nct_id}  score={r.score:.2f}  "
            f"conf={r.confidence:<6} assessed={r.evaluated_weight_fraction:.0%}"
        )

    lo, hi = result["expected_range"]
    print(f"  Order  : {'OK' if result['order_correct'] else 'WRONG'}", end="")
    if not result["order_correct"]:
        print(f"  expected {result['expected_order']}, got {result['actual_order']}", end="")
    print()
    print(
        f"  Top-1  : {result['top_score']:.2f} vs expected [{lo}, {hi}] "
        f"{'OK' if result['in_range'] else 'OUT OF RANGE'}"
    )
    print(f"  RESULT : {'PASS' if result['passed'] else 'FAIL'}")


def run_suite(effort: str) -> dict:
    ranking.EFFORT = effort
    client = ranking._client()
    spend = SpendTracker(ranking.MODEL)

    results = []
    for test_case in ALL_TEST_CASES:
        for style in INPUT_STYLES:
            result = run_scenario(client, test_case, style, spend)
            print_scenario(test_case, style, result)
            results.append({"case": test_case.name, "style": style, **result})

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)

    print(f"\n{'=' * 74}\nSUMMARY — effort={effort}, model={ranking.MODEL}\n{'=' * 74}")
    print(f"  Passed : {passed}/{total} ({100 * passed // total if total else 0}%)")
    print(f"  Spend  : {spend.summary()}")

    by_style = {}
    for style in INPUT_STYLES:
        rows = [r for r in results if r["style"] == style]
        by_style[style] = sum(1 for r in rows if r.get("passed"))
        print(f"    {style:<11}: {by_style[style]}/{len(rows)}")

    errors = [r for r in results if "error" in r]
    if errors:
        print(f"  Errors : {len(errors)}")
        for r in errors:
            print(f"    {r['case']} [{r['style']}]: {r['error']}")

    return {
        "effort": effort,
        "passed": passed,
        "total": total,
        "by_style": by_style,
        "spend_usd": spend.usd,
        "spend_note": spend.summary(),
    }


def dry_run() -> None:
    """Scenario and call accounting, with no API calls and no spend."""
    scenarios = len(ALL_TEST_CASES) * len(INPUT_STYLES)
    trial_calls = sum(
        len(tc.test_trials) for tc in ALL_TEST_CASES for _ in INPUT_STYLES
    )
    total_calls = scenarios + trial_calls  # one interest parse per scenario

    print(f"Test cases        : {len(ALL_TEST_CASES)}")
    print(f"Input styles      : {len(INPUT_STYLES)}")
    print(f"Scenarios         : {scenarios}")
    print(f"Interest parses   : {scenarios}")
    print(f"Per-trial calls   : {trial_calls}")
    print(f"Total model calls : {total_calls}")
    print(
        "\nNo API calls were made. Run without --dry-run to execute and get "
        "real token counts and cost."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-effort", action="store_true",
                        help="run the suite at low and high effort and compare")
    parser.add_argument("--dry-run", action="store_true",
                        help="report call counts without calling the API")
    parser.add_argument("--effort", default=None, help="single effort level to run")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
        return 0

    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        print("ANTHROPIC_API_KEY is not set. This harness makes real API calls.")
        print("Run with --dry-run to see the call count without spending anything.")
        return 2

    if args.sweep_effort:
        summaries = [run_suite("low"), run_suite("high")]
        print(f"\n{'=' * 74}\nEFFORT COMPARISON\n{'=' * 74}")
        for s in summaries:
            cost = f"${s['spend_usd']:.4f}" if s["spend_usd"] is not None else "n/a"
            print(f"  effort={s['effort']:<5} {s['passed']}/{s['total']}  cost={cost}")
        low, high = summaries
        if low["passed"] >= high["passed"]:
            print("\n  Higher effort did not improve results. Low effort is the")
            print("  better setting here — same quality, lower cost.")
        else:
            print(f"\n  Higher effort scored {high['passed'] - low['passed']} more.")
            print("  Weigh that against the cost difference above.")
        return 0

    summary = run_suite(args.effort or ranking.EFFORT)
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
