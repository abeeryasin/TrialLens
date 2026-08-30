"""Is the target region (score in [0.75,0.95] AND confidence 'high') reachable
under the rewritten scoring, for the interests these test cases actually use?

Uses the response cache, so this costs nothing.
"""
import api.ranking as ranking
from api.ranking import (
    SIGNAL_WEIGHTS, SpendTracker, parse_researcher_interest,
    rank_one_trial, score_signals,
)
from api.ranking_schemas import FitSignal
from tests.test_ranking_integration import to_study_detail, INPUT_STYLES
from tests.test_data_synthetic_trials import ALL_TEST_CASES

ranking.EFFORT = "low"
client = ranking._client()
spend = SpendTracker(ranking.MODEL)

# --- 1. The confidence rule, restated from score_signals() -------------------
print("=" * 78)
print("CONFIDENCE RULE (api/ranking.py score_signals)")
print("=" * 78)
print("  high   <- every evaluated signal is 'high' AND evaluated_fraction >= 0.80")
print("  medium <- every evaluated signal is 'high' or 'medium'")
print("  low    <- otherwise, or evaluated_fraction < 0.50")
print()

# --- 2. Which weight is preference-gated? -----------------------------------
GATED = {
    "status_recruiting": "require_recruiting",
    "phase_fit": "phases",
    "prior_treatment_compatible": "prior_treatment_context",
    "age_range_fit": "age band",
    "approach_match": "a named approach",
}
always = {k: v for k, v in SIGNAL_WEIGHTS.items() if k not in GATED}
print("=" * 78)
print("WEIGHT THAT ONLY SCORES IF THE RESEARCHER SAYS SOMETHING")
print("=" * 78)
for name, need in GATED.items():
    print(f"  {SIGNAL_WEIGHTS[name]:>5.0%}  {name:<28} needs: {need}")
print(f"  {sum(SIGNAL_WEIGHTS[n] for n in GATED):>5.0%}  TOTAL preference-gated")
print(f"  {sum(always.values()):>5.0%}  always evaluated ({', '.join(always)})")
print()
print(f"  -> evaluated_fraction >= 0.80 requires the researcher to state at least")
print(f"     {0.80 - sum(always.values()):.0%} of the {sum(SIGNAL_WEIGHTS[n] for n in GATED):.0%} gated weight.")
print()

# --- 3. What each real test interest actually unlocks ------------------------
print("=" * 78)
print("PER-SCENARIO CEILING (from the real cached interest parses)")
print("=" * 78)
print(f"{'case':<34}{'style':<12}{'max D':>7}{'high?':>8}  unstated")
print("-" * 78)

any_high_possible = False
rows = []
for tc in ALL_TEST_CASES:
    for style in INPUT_STYLES:
        interest = next(r for r in tc.researcher_interests if r.style == style).text
        prefs = parse_researcher_interest(client, interest, spend)
        stated = {
            "status_recruiting": prefs.require_recruiting is not None,
            "phase_fit": prefs.phases is not None,
            "prior_treatment_compatible": prefs.prior_treatment_context is not None,
            "age_range_fit": prefs.min_age_years is not None or prefs.max_age_years is not None,
            "approach_match": ranking._mentions_an_approach(prefs.raw_interest),
        }
        max_D = sum(always.values()) + sum(
            SIGNAL_WEIGHTS[n] for n, ok in stated.items() if ok
        )
        high_possible = max_D >= 0.80
        any_high_possible |= high_possible
        missing = [n.replace("_", " ") for n, ok in stated.items() if not ok]
        rows.append((tc.name, style, max_D, high_possible))
        print(f"{tc.name[:33]:<34}{style:<12}{max_D:>6.0%}{'YES' if high_possible else 'NO':>8}  "
              f"{', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}")

print()
print(f"  scenarios where confidence='high' is even POSSIBLE: "
      f"{sum(1 for *_, h in rows if h)}/{len(rows)}")
print()

# --- 4. Is [0.75, 0.95] reachable for the declared top-1 trial? --------------
print("=" * 78)
print("SCORE REACHABILITY for the trial each case declares should rank #1")
print("=" * 78)
print("A trial that matches everything the researcher asked about scores exactly")
print("1.00 by construction, because unknowns are excluded. Landing inside")
print("[0.75, 0.95] therefore requires the top trial to FAIL something.")
print()

for tc in ALL_TEST_CASES:
    lo, hi = tc.expected_top_1_score_range
    want = tc.expected_ranking_order[0][0]
    interest = next(r for r in tc.researcher_interests if r.style == "structured").text
    prefs = parse_researcher_interest(client, interest, spend)
    trial = next(t for t in tc.test_trials if t.nct_id == want)
    r = rank_one_trial(client, to_study_detail(trial), prefs, spend)
    statuses = {s.name: s.status for s in r.signals if s.status != "unknown"}
    verdict = "in range" if lo <= r.score <= hi else "OUT"
    print(f"{tc.name[:44]:<46} expects [{lo},{hi}]")
    print(f"   actual {want}: score={r.score:.2f} conf={r.confidence} "
          f"assessed={r.evaluated_weight_fraction:.0%}  -> {verdict}")
    print(f"   evaluated: {statuses}")
    print()

print(f"cost of this analysis: {spend.summary()}")
