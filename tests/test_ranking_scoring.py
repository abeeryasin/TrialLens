"""Unit tests for score aggregation — the arithmetic, with no model involved.

These lock in the fix for the scoring bug found on 2026-08-31: `unknown`
signals were scored 0.0 while still counting toward the denominator, which
made "the researcher didn't ask about this" arithmetically identical to
"this trial fails on this". Free to run; belongs in CI.

Run: PYTHONPATH=. python3 -m pytest tests/test_ranking_scoring.py -v
"""
import pytest

from api.ranking import SIGNAL_WEIGHTS, SpendTracker, score_signals
from api.ranking_schemas import FitSignal


def signal(name, status, confidence="high", weight=None) -> FitSignal:
    return FitSignal(
        name=name,
        status=status,
        evidence="evidence text long enough to be meaningful",
        source_field="field",
        source_value="value",
        weight=SIGNAL_WEIGHTS[name] if weight is None else weight,
        confidence=confidence,
    )


class TestUnknownHandling:
    """The core regression: unknown must not behave like no_match."""

    def test_unknown_is_excluded_from_the_denominator(self):
        """A perfect trial with unasked-about signals still scores 1.0.

        Under the old arithmetic this returned 0.50 — the two matching
        signals' weight divided by the full 1.0 of signal weight.
        """
        signals = [
            signal("condition_is_subject", "match"),     # 0.20
            signal("approach_match", "match"),           # 0.10
            signal("status_recruiting", "match"),        # 0.20
            signal("phase_fit", "unknown"),              # 0.15 — not asked
            signal("prior_treatment_compatible", "unknown"),  # 0.15 — not asked
            signal("age_range_fit", "unknown"),          # 0.10 — not asked
            signal("sites_active", "unknown"),           # 0.05 — not asked
            signal("enrollment_feasibility", "unknown"), # 0.05 — not asked
        ]
        score, _, evaluated = score_signals(signals)
        assert score == pytest.approx(1.0)
        assert evaluated == pytest.approx(0.50)

    def test_unknown_and_no_match_are_not_the_same(self):
        """The distinction the old implementation collapsed."""
        base = [signal("condition_is_subject", "match")]

        with_unknown = base + [signal("status_recruiting", "unknown")]
        with_no_match = base + [signal("status_recruiting", "no_match")]

        score_unknown, _, _ = score_signals(with_unknown)
        score_no_match, _, _ = score_signals(with_no_match)

        subject_w = SIGNAL_WEIGHTS["condition_is_subject"]
        status_w = SIGNAL_WEIGHTS["status_recruiting"]

        # unknown: excluded entirely, so the denominator is the subject weight alone
        assert score_unknown == pytest.approx(1.0)
        # no_match: contributes nothing but still counts in the denominator
        assert score_no_match == pytest.approx(subject_w / (subject_w + status_w))
        assert score_unknown > score_no_match

    def test_simple_interest_is_not_capped_near_065(self):
        """Reproduces the recorded symptom: 'scores 0.60 when expecting 0.75+'.

        A bare interest ("I track breast cancer trials") leaves most signals
        unasked. A trial that matches everything askable must score high.
        """
        signals = [
            signal("condition_is_subject", "match"),
            signal("status_recruiting", "unknown"),
            signal("phase_fit", "unknown"),
            signal("prior_treatment_compatible", "unknown"),
            signal("age_range_fit", "unknown"),
            signal("sites_active", "match"),
            signal("enrollment_feasibility", "match"),
        ]
        score, _, _ = score_signals(signals)
        assert score > 0.75, "a fully-matching trial must not be dragged down by unasked criteria"

    def test_all_unknown_reports_zero_evaluated_not_a_bad_score(self):
        """Nothing assessable must be distinguishable from 'assessed, scored 0'."""
        signals = [signal(name, "unknown") for name in SIGNAL_WEIGHTS]
        score, confidence, evaluated = score_signals(signals)
        assert evaluated == 0.0
        assert confidence == "low"
        assert score == 0.0  # callers must read evaluated_fraction, not score alone


class TestScoreArithmetic:
    def test_partial_counts_half(self):
        subject_w = SIGNAL_WEIGHTS["condition_is_subject"]
        status_w = SIGNAL_WEIGHTS["status_recruiting"]
        signals = [
            signal("condition_is_subject", "partial"),   # half credit
            signal("status_recruiting", "match"),        # full credit
        ]
        score, _, _ = score_signals(signals)
        expected = (subject_w * 0.5 + status_w) / (subject_w + status_w)
        assert score == pytest.approx(expected)

    def test_no_match_contributes_nothing_but_counts_against(self):
        subject_w = SIGNAL_WEIGHTS["condition_is_subject"]
        status_w = SIGNAL_WEIGHTS["status_recruiting"]
        signals = [
            signal("condition_is_subject", "match"),
            signal("status_recruiting", "no_match"),  # counted, contributes 0
        ]
        score, _, _ = score_signals(signals)
        assert score == pytest.approx(subject_w / (subject_w + status_w))

    def test_score_is_bounded(self):
        for status in ("match", "partial", "no_match"):
            signals = [signal(n, status) for n in SIGNAL_WEIGHTS]
            score, _, _ = score_signals(signals)
            assert 0.0 <= score <= 1.0


class TestConfidenceCalibration:
    def test_thin_coverage_forces_low_confidence(self):
        """High confidence on each of two signals is not high confidence overall
        when 70% of the criteria went unassessed."""
        signals = [
            signal("condition_is_subject", "match", "high"),
            signal("status_recruiting", "unknown", "high"),
            signal("phase_fit", "unknown", "high"),
            signal("prior_treatment_compatible", "unknown", "high"),
            signal("age_range_fit", "unknown", "high"),
            signal("sites_active", "match", "high"),
            signal("enrollment_feasibility", "unknown", "high"),
        ]
        _, confidence, evaluated = score_signals(signals)
        assert evaluated < 0.5
        assert confidence == "low"

    def test_broad_coverage_and_sure_signals_gives_high(self):
        signals = [
            signal("condition_is_subject", "match", "high"),
            signal("status_recruiting", "match", "high"),
            signal("phase_fit", "match", "high"),
            signal("prior_treatment_compatible", "match", "high"),
            signal("age_range_fit", "match", "high"),
            signal("sites_active", "match", "high"),
            signal("enrollment_feasibility", "match", "high"),
        ]
        _, confidence, evaluated = score_signals(signals)
        assert evaluated == pytest.approx(1.0)
        assert confidence == "high"

    def test_one_low_confidence_signal_drops_overall(self):
        signals = [
            signal("condition_is_subject", "match", "low"),
            signal("status_recruiting", "match", "high"),
            signal("phase_fit", "match", "high"),
            signal("prior_treatment_compatible", "match", "high"),
            signal("age_range_fit", "match", "high"),
            signal("sites_active", "match", "high"),
            signal("enrollment_feasibility", "match", "high"),
        ]
        _, confidence, _ = score_signals(signals)
        assert confidence == "low"


class TestSpendTracker:
    def test_reports_real_cost_from_usage(self):
        class Usage:
            input_tokens = 1000
            cache_read_input_tokens = 5000
            cache_creation_input_tokens = 2000
            output_tokens = 500

        tracker = SpendTracker("claude-opus-5")
        tracker.record(Usage())

        # 1000*5 + 5000*0.5 + 2000*6.25 + 500*25 per million
        expected = (1000 * 5 + 5000 * 0.5 + 2000 * 6.25 + 500 * 25) / 1_000_000
        assert tracker.usd == pytest.approx(expected)
        assert tracker.calls == 1
        assert "claude-opus-5" in tracker.summary()

    def test_unknown_model_does_not_invent_a_price(self):
        tracker = SpendTracker("some-future-model")
        assert tracker.usd is None
        assert "cost unknown" in tracker.summary()


# ============================================================================
# Eliciting what wasn't said
# ============================================================================


class TestElicitation:
    """Missing information is a fact about the question, not the trial.

    The system's job when a preference is absent is to ask for it, not to
    quietly narrow what the score means and print a number anyway.
    """

    def test_every_elicitable_field_names_real_signals(self):
        """A typo here would silently mis-report how much weight is unscored,
        and no other test would notice."""
        from api.ranking import _ELICITABLE

        for field, spec in _ELICITABLE.items():
            for name in spec["signals"]:
                assert name in SIGNAL_WEIGHTS, f"{field} names unknown signal {name!r}"
            assert spec["question"].endswith("?"), f"{field} question isn't a question"
            assert spec["example"], f"{field} has no example answer"

    def test_bare_interest_elicits_everything(self):
        from api.ranking import find_unspecified
        from api.ranking_deterministic import ResearcherPreferences

        prefs = ResearcherPreferences(
            condition_terms=["breast cancer"],
            raw_interest="I track breast cancer trials",
        )
        unspecified = find_unspecified(prefs)
        assert len(unspecified) == 5
        assert sum(u.weight_unscored for u in unspecified) == pytest.approx(0.70)

    def test_fully_specified_interest_elicits_nothing(self):
        from api.ranking import find_unspecified
        from api.ranking_deterministic import ResearcherPreferences

        prefs = ResearcherPreferences(
            condition_terms=["breast cancer"],
            phases=["PHASE2"],
            require_recruiting=True,
            min_age_years=18,
            max_age_years=75,
            prior_treatment_context="two prior lines",
            raw_interest="breast cancer immunotherapy, phase II, recruiting, adults 18-75, after two prior lines",
        )
        assert find_unspecified(prefs) == []

    def test_only_the_missing_fields_are_asked_about(self):
        from api.ranking import find_unspecified
        from api.ranking_deterministic import ResearcherPreferences

        prefs = ResearcherPreferences(
            condition_terms=["obesity"],
            require_recruiting=True,          # stated
            raw_interest="obesity trials currently recruiting",
        )
        fields = {u.field for u in find_unspecified(prefs)}
        assert "require_recruiting" not in fields
        assert {"phases", "age_band", "prior_treatment_context", "approach"} == fields

    def test_questions_are_ordered_by_what_they_would_recover(self):
        """The researcher's attention is finite — ask for the most valuable first."""
        from api.ranking import find_unspecified
        from api.ranking_deterministic import ResearcherPreferences

        unspecified = find_unspecified(
            ResearcherPreferences(condition_terms=["x"], raw_interest="x trials")
        )
        weights = [u.weight_unscored for u in unspecified]
        assert weights == sorted(weights, reverse=True)

    def test_a_named_mechanism_is_recognised(self):
        """If they said 'immunotherapy', don't ask them for a modality."""
        from api.ranking import find_unspecified
        from api.ranking_deterministic import ResearcherPreferences

        for interest in (
            "breast cancer immunotherapy trials",
            "trials using checkpoint inhibitors",
            "GLP-1 agonists for obesity",
            "CAR-T in lymphoma",
        ):
            prefs = ResearcherPreferences(condition_terms=["x"], raw_interest=interest)
            fields = {u.field for u in find_unspecified(prefs)}
            assert "approach" not in fields, f"should not re-ask for: {interest!r}"

    def test_no_mechanism_named_is_asked_about(self):
        from api.ranking import find_unspecified
        from api.ranking_deterministic import ResearcherPreferences

        prefs = ResearcherPreferences(
            condition_terms=["breast cancer"], raw_interest="breast cancer trials"
        )
        assert "approach" in {u.field for u in find_unspecified(prefs)}
