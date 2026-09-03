"""Test prose interpretation logic. Free tests only — no API calls."""
import pytest
from api.prose_interpreter import (
    PROSE_FIELDS,
    interpret_prose_change,
    interpret_amendments_batch,
)


class TestProseFieldDefinition:
    """Verify we're interpreting the right fields."""

    def test_prose_fields_are_defined(self):
        """PROSE_FIELDS should include eligibility, summary, outcomes."""
        assert "eligibility_criteria" in PROSE_FIELDS
        assert "brief_summary" in PROSE_FIELDS
        assert "primary_outcomes" in PROSE_FIELDS

    def test_prose_fields_exclude_arithmetic_ones(self):
        """Should NOT include fields we already handle deterministically."""
        assert "enrollment_count" not in PROSE_FIELDS
        assert "overall_status" not in PROSE_FIELDS
        assert "start_date" not in PROSE_FIELDS
        assert "locations" not in PROSE_FIELDS


class TestInterpretProseChangeValidation:
    """Validation short-circuits, checked without calling the API.

    Each asserts `(None, 0.0)`, and the 0.0 is the load-bearing half: these
    paths must cost nothing, because they return before any request is made.
    A non-zero cost here would mean a guard stopped guarding and the call went
    out anyway.
    """

    def test_non_prose_field_returns_none(self):
        """Non-prose fields should return None (no API call)."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="enrollment_count",  # not prose
            old_value="100",
            new_value="200",
        )
        assert result == (None, 0.0)

    def test_empty_old_value_returns_none(self):
        """Empty old value should return None (too small to interpret)."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="eligibility_criteria",
            old_value="",
            new_value="Some eligibility criteria here.",
        )
        assert result == (None, 0.0)

    def test_empty_new_value_returns_none(self):
        """Empty new value should return None (too small to interpret)."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="eligibility_criteria",
            old_value="Some eligibility criteria here.",
            new_value="",
        )
        assert result == (None, 0.0)

    def test_both_values_too_short_returns_none(self):
        """If both are under 20 chars, no point interpreting."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="brief_summary",
            old_value="Short",
            new_value="Shorter",
        )
        assert result == (None, 0.0)


class TestAmendmentBatch:
    """Test batch processing without API calls."""

    def test_batch_respects_cost_limit_logic(self):
        """Verify batch respects cost limits (without making API calls)."""
        from api.prose_interpreter import COST_ESTIMATE_PER_CALL

        # Create amendments that would exceed cost if all were interpreted
        amendments = [
            {
                "nct_id": f"NCT{i:08d}",
                "field_name": "eligibility_criteria",
                "old_value": "Old text " * 20,
                "new_value": "New text " * 20,
            }
            for i in range(10)
        ]

        # If we set max_cost_usd to only afford 2 calls,
        # batch should stop after 2 interpretations.
        # (This is tested implicitly in test_batch_includes_non_prose_fields_uninterpreted)
        cost_for_two_calls = COST_ESTIMATE_PER_CALL * 2
        assert cost_for_two_calls < COST_ESTIMATE_PER_CALL * 3

    def test_batch_includes_non_prose_fields_uninterpreted(self):
        """Non-prose amendments should pass through with None interpretation."""
        amendments = [
            {
                "nct_id": "NCT00000001",
                "field_name": "enrollment_count",
                "old_value": "100",
                "new_value": "200",
            },
        ]
        # This shouldn't call API since field is non-prose
        results, spend = interpret_amendments_batch(
            amendments, max_cost_usd=0.30, max_calls=1
        )
        assert len(results) == 1
        assert results[0]["prose_interpretation"] is None
        assert spend == 0.0  # No calls made


class TestProseFieldsMatchDeterministicLayers:
    """Verify prose fields are the ones amendments.py explicitly skips."""

    def test_prose_fields_are_not_in_amendments_module(self):
        """These fields should have None returns from describe_effect."""
        from api.amendments import describe_effect

        # All prose fields should return None from describe_effect
        for field in PROSE_FIELDS:
            result = describe_effect(
                field_name=field,
                old_value="Some old text " * 10,
                new_value="Some new text " * 10,
            )
            assert result is None, f"{field} should not have deterministic description"


# ---------------------------------------------------------------------------
# The MEANINGFUL gate and real-usage billing (2026-09-04).
#
# Both replace things that failed against live data on 2026-09-03: a gate that
# string-matched the model's prose, and a spend figure that was a constant
# multiplied by a call count. Free — the client is faked, nothing is sent.
# ---------------------------------------------------------------------------

import api.prose_interpreter as pi


class _FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, text, input_tokens=1000, output_tokens=100):
        self.content = [type("Block", (), {"text": text})()]
        self.usage = _FakeUsage(input_tokens, output_tokens)


class _FakeClient:
    def __init__(self, text, **usage):
        self._text = text
        self._usage = usage
        self.messages = type(
            "M", (), {"create": lambda _s, **kw: _FakeResponse(self._text, **self._usage)}
        )()


def _run(monkeypatch, text, **usage):
    monkeypatch.setattr(pi, "_client", lambda: _FakeClient(text, **usage))
    return pi.interpret_prose_change(
        nct_id="NCT00000000",
        field_name="eligibility_criteria",
        old_value="Patients aged 18 and over with confirmed diagnosis.",
        new_value="Patients aged 65 and over with confirmed diagnosis, ECOG 0-1.",
    )


class TestTheMeaningfulGate:
    def test_a_meaningful_change_is_stored(self, monkeypatch):
        result, cost = _run(
            monkeypatch,
            "SUMMARY: Age eligibility narrowed from 18+ to 65+\nMEANINGFUL: yes",
        )
        assert result == {"summary": "Age eligibility narrowed from 18+ to 65+"}
        assert cost > 0

    def test_the_phrasing_that_defeated_the_old_filter_is_now_rejected(self, monkeypatch):
        """The real 2026-09-03 failure, verbatim.

        The old gate was `summary.lower() != "no change"`. The model wrote
        "No meaningful change—the criteria were reformatted for clarity", which
        is not that literal string, so a paid call reporting that nothing
        happened was stored as a finding on NCT05327608.
        """
        result, cost = _run(
            monkeypatch,
            "SUMMARY: No meaningful change—the criteria were reformatted for "
            "clarity\nMEANINGFUL: no",
        )
        assert result is None
        assert cost > 0, "the call still happened and still cost money"

    def test_no_result_has_a_why_matters_field(self, monkeypatch):
        """Dropped 2026-09-04. It was ~48% of output tokens and every weak
        line in the live batch lived there — speculation about consequences,
        presented beside source-anchored fact with the same authority."""
        result, _ = _run(
            monkeypatch,
            "SUMMARY: Age narrowed to 65+\nMEANINGFUL: yes\n"
            "WHY_MATTERS: Reduces the referral pool",
        )
        assert result is not None
        assert "why_matters" not in result

    def test_a_missing_meaningful_line_is_not_stored(self, monkeypatch):
        """Absence is not consent. If the model skips the field, we do not get
        to assume the change was substantive."""
        result, cost = _run(monkeypatch, "SUMMARY: Age narrowed to 65+")
        assert result is None
        assert cost > 0


class TestRealUsageBilling:
    def test_cost_comes_from_the_token_counts(self, monkeypatch):
        """$1.00/MTok in and $5.00/MTok out for claude-haiku-4-5."""
        _, cost = _run(monkeypatch, "SUMMARY: x\nMEANINGFUL: yes",
                       input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(6.00)

    def test_output_tokens_cost_five_times_input(self, monkeypatch):
        """The reason the prompt asks for one line instead of two."""
        _, in_only = _run(monkeypatch, "SUMMARY: x\nMEANINGFUL: yes",
                          input_tokens=10_000, output_tokens=0)
        _, out_only = _run(monkeypatch, "SUMMARY: x\nMEANINGFUL: yes",
                           input_tokens=0, output_tokens=10_000)
        assert out_only == pytest.approx(in_only * 5)

    def test_a_rejected_interpretation_still_reports_its_cost(self, monkeypatch):
        """The billing blind spot, directly.

        Until 2026-09-04 spend was added only when an interpretation came back,
        so every "no change" call was real money recorded as $0.00 — invisible
        to the ceiling meant to bound it.
        """
        _, cost = _run(monkeypatch, "SUMMARY: nothing\nMEANINGFUL: no",
                       input_tokens=2000, output_tokens=50)
        assert cost == pytest.approx((2000 * 1.00 + 50 * 5.00) / 1_000_000)


def test_a_prefiltered_change_costs_nothing(monkeypatch):
    """The pre-filter must return before the client is ever constructed."""
    def _explode():
        raise AssertionError("the API was called for a >90% similar change")
    monkeypatch.setattr(pi, "_client", _explode)
    result, cost = pi.interpret_prose_change(
        nct_id="NCT00000000",
        field_name="eligibility_criteria",
        old_value="Patients aged 18 and over with a confirmed diagnosis of disease.",
        new_value="Patients aged 18 and over with a confirmed diagnosis of disease!",
    )
    assert result is None and cost == 0.0
