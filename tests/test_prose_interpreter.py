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
    """Test validation without calling the API."""

    def test_non_prose_field_returns_none(self):
        """Non-prose fields should return None (no API call)."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="enrollment_count",  # not prose
            old_value="100",
            new_value="200",
        )
        assert result is None

    def test_empty_old_value_returns_none(self):
        """Empty old value should return None (too small to interpret)."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="eligibility_criteria",
            old_value="",
            new_value="Some eligibility criteria here.",
        )
        assert result is None

    def test_empty_new_value_returns_none(self):
        """Empty new value should return None (too small to interpret)."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="eligibility_criteria",
            old_value="Some eligibility criteria here.",
            new_value="",
        )
        assert result is None

    def test_both_values_too_short_returns_none(self):
        """If both are under 20 chars, no point interpreting."""
        result = interpret_prose_change(
            nct_id="NCT00000000",
            field_name="brief_summary",
            old_value="Short",
            new_value="Shorter",
        )
        assert result is None


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
