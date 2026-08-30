"""Evaluation harness for Step 7: Trial ranking/evidence layer.

Runs test cases, compares results to expected outcomes, measures:
- Precision@1, Precision@3, Recall
- Ranking order correctness
- Score calibration
- Confidence calibration

Run with: python -m pytest tests/test_ranking_harness.py -v
Or standalone: python tests/test_ranking_harness.py
"""
from datetime import datetime
from typing import List, Tuple

from api.ranking_schemas import EvaluationResult, EvaluationReport, FitRanking
from tests.test_data_synthetic_trials import ALL_TEST_CASES


class RankingEvaluator:
    """Evaluate ranking results against test cases."""

    def __init__(self):
        self.results: List[EvaluationResult] = []

    def evaluate_test_case(
        self,
        test_case,
        ranked_results: List[FitRanking],
        researcher_interest_style: str,
    ) -> EvaluationResult:
        """
        Evaluate one test case result.

        Args:
            test_case: TestCase object defining expected outcomes
            ranked_results: List of FitRanking results from the endpoint (should be sorted by score desc)
            researcher_interest_style: "simple", "structured", or "narrative"

        Returns:
            EvaluationResult with pass/fail and metrics
        """
        errors = []
        metrics = {}

        # ====================================================================
        # Check 1: Ranking order correctness
        # ====================================================================
        actual_ranking = [r.nct_id for r in ranked_results]
        expected_ranking = [nct_id for nct_id, _ in test_case.expected_ranking_order]

        ranking_correct = actual_ranking == expected_ranking
        metrics["ranking_order_correct"] = ranking_correct
        if not ranking_correct:
            errors.append(
                f"Ranking order mismatch. Expected: {expected_ranking}, Got: {actual_ranking}"
            )

        # ====================================================================
        # Check 2: Top-1 score in expected range
        # ====================================================================
        if ranked_results:
            top_1_score = ranked_results[0].score
            min_expected, max_expected = test_case.expected_top_1_score_range
            in_range = min_expected <= top_1_score <= max_expected
            metrics["top_1_score"] = top_1_score
            metrics["in_expected_range"] = in_range
            if not in_range:
                errors.append(
                    f"Top-1 score {top_1_score:.2f} outside range [{min_expected}, {max_expected}]"
                )
        else:
            errors.append("No results returned")
            metrics["top_1_score"] = None
            metrics["in_expected_range"] = False

        # ====================================================================
        # Check 3: Precision@1 (is top result a "high" or "medium" score?)
        # ====================================================================
        if ranked_results:
            top_1_nct = ranked_results[0].nct_id
            top_1_expected_tier = next(
                (tier for nct, tier in test_case.expected_ranking_order if nct == top_1_nct),
                None,
            )
            precision_at_1 = 1.0 if top_1_expected_tier in ["high", "medium"] else 0.0
            metrics["precision_at_1"] = precision_at_1
        else:
            metrics["precision_at_1"] = 0.0

        # ====================================================================
        # Check 4: Precision@3 (of top 3, how many are "high" or "medium"?)
        # ====================================================================
        if len(ranked_results) >= 3:
            top_3_ncts = [r.nct_id for r in ranked_results[:3]]
            correct_count = 0
            for nct in top_3_ncts:
                expected_tier = next(
                    (tier for n, tier in test_case.expected_ranking_order if n == nct),
                    None,
                )
                if expected_tier in ["high", "medium"]:
                    correct_count += 1
            precision_at_3 = correct_count / 3.0
            metrics["precision_at_3"] = precision_at_3
        elif len(ranked_results) > 0:
            # Fewer than 3 results; score based on what's available
            correct_count = 0
            for r in ranked_results:
                expected_tier = next(
                    (tier for n, tier in test_case.expected_ranking_order if n == r.nct_id),
                    None,
                )
                if expected_tier in ["high", "medium"]:
                    correct_count += 1
            metrics["precision_at_3"] = correct_count / len(ranked_results) if ranked_results else 0.0
        else:
            metrics["precision_at_3"] = 0.0

        # ====================================================================
        # Check 5: Confidence calibration (high-confidence scores should be stable)
        # ====================================================================
        high_confidence_scores = [r.score for r in ranked_results if r.confidence == "high"]
        medium_confidence_scores = [r.score for r in ranked_results if r.confidence == "medium"]

        if high_confidence_scores:
            high_conf_variance = (
                max(high_confidence_scores) - min(high_confidence_scores)
                if len(high_confidence_scores) > 1
                else 0.0
            )
            metrics["high_confidence_variance"] = high_conf_variance
            # Variance should be small; if it's >0.20, something's wrong
            if high_conf_variance > 0.20:
                errors.append(
                    f"High-confidence scores have high variance: {high_conf_variance:.2f}"
                )

        # ====================================================================
        # Decision: Pass or Fail
        # ====================================================================
        passed = (
            len(errors) == 0
            and metrics.get("ranking_order_correct", False)
            and metrics.get("in_expected_range", False)
        )

        metrics["errors"] = errors

        result = EvaluationResult(
            test_case_name=test_case.name,
            researcher_interest_style=researcher_interest_style,
            passed=passed,
            metrics=metrics,
            timestamp=datetime.utcnow(),
        )
        self.results.append(result)
        return result

    def generate_report(self) -> EvaluationReport:
        """Generate summary report from all results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        pass_rate = (passed / total) if total > 0 else 0.0

        # Aggregate metrics
        metrics_summary = {
            "mean_precision_at_1": sum(r.metrics.get("precision_at_1", 0) for r in self.results)
            / total
            if total > 0
            else 0.0,
            "mean_precision_at_3": sum(r.metrics.get("precision_at_3", 0) for r in self.results)
            / total
            if total > 0
            else 0.0,
            "mean_top_1_score": sum(r.metrics.get("top_1_score", 0) for r in self.results)
            / total
            if total > 0
            else 0.0,
            "ranking_order_correct_count": sum(
                1 for r in self.results if r.metrics.get("ranking_order_correct", False)
            ),
            "total_tests": total,
        }

        return EvaluationReport(
            total_tests=total,
            passed=passed,
            failed=failed,
            pass_rate=pass_rate,
            metrics_summary=metrics_summary,
            timestamp=datetime.utcnow(),
        )


# ============================================================================
# Baseline Evaluation (Before LLM Implementation)
# ============================================================================
# This represents what we expect from deterministic-only signals
# (condition match, status, phase). LLM will improve on this.

EXPECTED_BASELINE_METRICS = {
    "mean_precision_at_1": 0.87,  # Most test cases have clear best match
    "mean_precision_at_3": 0.82,  # At least 2 of 3 top results are relevant
    "mean_top_1_score": 0.72,  # Deterministic signals yield moderate-high scores
    "ranking_order_correct_count": 4,  # Out of 5 test cases (1 may be ambiguous)
}


def print_evaluation_report(report: EvaluationReport):
    """Pretty-print an evaluation report."""
    print("\n" + "=" * 70)
    print("EVALUATION REPORT")
    print("=" * 70)
    print(f"Timestamp: {report.timestamp}")
    print(f"\nResults: {report.passed}/{report.total_tests} passed ({report.pass_rate:.1%})")
    print(f"Failed: {report.failed}")
    print("\n" + "-" * 70)
    print("Metrics Summary:")
    print("-" * 70)
    for key, value in report.metrics_summary.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.3f}")
        else:
            print(f"  {key}: {value}")
    print("=" * 70 + "\n")


# ============================================================================
# Stub: Once Unit 3 (Ranking Endpoint) is implemented, this will be replaced
# with a real call to the endpoint.
# ============================================================================

def stub_ranking_function(
    researcher_interest: str, trials: list
) -> List[FitRanking]:
    """
    STUB: Will be replaced by actual ranking endpoint.

    For now, returns an empty list. Once Unit 3 is implemented, this will call:
      POST /rank
        {
          "researcher_interest": "...",
          "trials": [...]
        }

    And return FitRanking objects.
    """
    # TODO: Implement this in Unit 3
    return []


if __name__ == "__main__":
    # This is a test harness framework. Real tests need Unit 3 (ranking endpoint) to be implemented.
    print("\n" + "=" * 70)
    print("TRIAL RANKING EVALUATION HARNESS")
    print("=" * 70)
    print(f"\nTest Suite Loaded: {len(ALL_TEST_CASES)} test cases")
    for i, case in enumerate(ALL_TEST_CASES, 1):
        print(f"  {i}. {case.name}")
    print("\nStatus: FRAMEWORK READY")
    print("  - Test cases defined: ✓")
    print("  - Evaluation metrics defined: ✓")
    print("  - Baseline expectations set: ✓")
    print("  - Ranking endpoint (Unit 3): NOT YET IMPLEMENTED")
    print("\nNext Step: Unit 3 will implement the ranking endpoint.")
    print("Once implemented, run: python tests/test_ranking_harness.py")
    print("Or: python -m pytest tests/test_ranking_harness.py -v")
    print("=" * 70 + "\n")
