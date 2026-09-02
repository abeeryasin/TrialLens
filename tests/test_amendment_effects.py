"""api/amendments.py — the deterministic half of change interpretation.

Every value used here is one that actually occurs in the database
(2026-09-01), not one invented to make a test pass. Free: no database, no
network, no model.

The through-line: each function must return None rather than guess. These
strings are shown to a clinical researcher as statements about a trial, so
a wrong one is a false claim about a study fact (CLAUDE.md sec. 2) — and
the failure mode that matters is a *confident* description of a change that
did not happen that way.
"""
import json
from datetime import datetime, timezone

import pytest

from api.amendments import (
    ASPECT_ADMINISTRATIVE,
    ASPECT_OPERATIONAL,
    ASPECT_SCIENTIFIC,
    describe_count_shift,
    describe_date_shift,
    describe_effect,
    describe_enrollment_type,
    describe_results_posting,
    describe_list_shift,
    describe_status_change,
    enrollment_context,
    field_aspect,
)
from api.schemas import AmendedField

WHEN = datetime(2026, 8, 31, 18, 2, 40, tzinfo=timezone.utc)


class TestAspectMapping:
    def test_the_fields_that_change_what_a_trial_means_are_scientific(self):
        for field in ("primary_outcomes", "eligibility_criteria", "brief_summary",
                      "interventions", "healthy_volunteers"):
            assert field_aspect(field) == ASPECT_SCIENTIFIC, field

    def test_the_fields_about_running_the_trial_are_operational(self):
        for field in ("overall_status", "enrollment_count", "enrollment_type",
                      "start_date", "primary_completion_date", "completion_date",
                      "locations"):
            assert field_aspect(field) == ASPECT_OPERATIONAL, field

    def test_titles_are_administrative(self):
        assert field_aspect("brief_title") == ASPECT_ADMINISTRATIVE
        assert field_aspect("official_title") == ASPECT_ADMINISTRATIVE

    def test_an_unmapped_field_is_none_not_quietly_administrative(self):
        """A field CT.gov starts reporting that nobody has classified must
        surface as uncategorised. Defaulting it to Administrative would
        silently downgrade something no human has looked at."""
        assert field_aspect("some_field_ctgov_adds_in_2027") is None

    def test_every_mapped_field_is_one_the_database_actually_stores(self):
        """Guards against classifying fields that don't exist, which reads
        as coverage while providing none."""
        from api.schemas import StudyUpsert
        real = set(StudyUpsert.model_fields) | {"locations", "interventions",
                                                "primary_outcomes", "brief_summary"}
        from api.amendments import FIELD_ASPECTS
        assert set(FIELD_ASPECTS) <= real, set(FIELD_ASPECTS) - real


class TestDateShift:
    def test_the_real_twelve_month_slip(self):
        """NCT02954874, 2026-08-31 amendment — the motivating case."""
        assert describe_date_shift("2026-08-31", "2027-08-27") == "pushed about 12 months later"

    def test_a_date_pulled_earlier(self):
        assert describe_date_shift("2026-08-31", "2026-08-03") == "pulled about 4 weeks earlier"

    def test_a_one_day_move_is_reported_exactly(self):
        assert describe_date_shift("2026-09-02", "2026-09-03") == "pushed 1 day later"

    def test_month_precision_input_never_produces_a_day_count(self):
        """~23% of trials report these to the month only. Saying "361 days"
        about "2027-06" invents precision CT.gov never gave (sec. 2)."""
        result = describe_date_shift("2026-06", "2027-06")
        assert result == "pushed about 12 months later"
        assert "day" not in result

    def test_a_sub_fortnight_move_between_month_only_dates_is_not_reported(self):
        """Anchoring "2026-06" to the 1st makes a few days of apparent
        movement that is purely an artefact of the anchor."""
        assert describe_date_shift("2026-06", "2026-06-05") is None

    def test_no_change_produces_nothing(self):
        assert describe_date_shift("2026-08-31", "2026-08-31") is None

    @pytest.mark.parametrize("old,new", [
        (None, "2026-08-31"), ("2026-08-31", None),
        ("not a date", "2026-08-31"), ("", ""), ("2026-13-45", "2026-08-31"),
    ])
    def test_anything_unparseable_is_none_never_a_guess(self, old, new):
        assert describe_date_shift(old, new) is None


class TestStatusChange:
    @pytest.mark.parametrize("old,new,expected_fragment", [
        ("NOT_YET_RECRUITING", "RECRUITING", "opened to enrolment"),
        ("RECRUITING", "COMPLETED", "finished"),
        ("RECRUITING", "ACTIVE_NOT_RECRUITING", "closed to new participants"),
        ("ACTIVE_NOT_RECRUITING", "COMPLETED", "finished"),
        ("ACTIVE_NOT_RECRUITING", "RECRUITING", "reopened"),
    ])
    def test_every_transition_observed_in_real_data_is_described(self, old, new, expected_fragment):
        result = describe_status_change(old, new)
        assert result is not None, f"{old} -> {new} fell through to None"
        assert expected_fragment in result

    def test_an_early_stop_is_flagged_as_worth_reading(self):
        for stopped in ("TERMINATED", "SUSPENDED", "WITHDRAWN"):
            result = describe_status_change("RECRUITING", stopped)
            assert "stopped early" in result

    def test_no_description_claims_anything_about_a_person(self):
        """Sec. 2: the system never says who may join a trial. "Open to new
        participants" is a fact about the trial's registered status; "you
        may be eligible" would not be."""
        forbidden = ("eligible", "you ", "qualify", "your ")
        for old in ("RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING"):
            for new in ("COMPLETED", "RECRUITING", "TERMINATED", "ACTIVE_NOT_RECRUITING"):
                result = describe_status_change(old, new) or ""
                assert not any(w in result.lower() for w in forbidden), result

    def test_an_unchanged_or_missing_status_is_none(self):
        assert describe_status_change("RECRUITING", "RECRUITING") is None
        assert describe_status_change(None, "RECRUITING") is None


class TestEnrollment:
    def test_the_real_count_increase(self):
        assert describe_count_shift("1155", "1195") == "increased by 40"

    def test_a_reduction_says_reduced(self):
        assert describe_count_shift("240", "100") == "reduced by 140"

    def test_a_non_numeric_value_is_none(self):
        assert describe_count_shift("many", "100") is None
        assert describe_count_shift(None, "100") is None

    def test_target_becoming_actual_is_spelled_out(self):
        """6,577 of 11,482 records report a target rather than a headcount,
        so this switch reads as noise unless it's said in words."""
        result = describe_enrollment_type("ESTIMATED", "ACTUAL")
        assert "target" in result and "real enrolled count" in result

    def test_the_reverse_is_flagged_as_unusual(self):
        assert "unusual" in describe_enrollment_type("ACTUAL", "ESTIMATED")

    def test_the_numbers_are_named_when_the_count_moved(self):
        """The real NCT03402139 amendment, 31 August: a trial that planned
        400 participants and enrolled 163. Without the numbers the sentence
        omits the only part a researcher would act on."""
        result = describe_enrollment_type("ESTIMATED", "ACTUAL", 400, 163)
        assert result == "the target of 400 was replaced by a real count of 163"

    def test_a_count_that_did_not_move_is_confirmed_not_replaced(self):
        """Nothing was replaced except the number's status. Saying "replaced
        by" would imply the figure changed when it did not."""
        result = describe_enrollment_type("ESTIMATED", "ACTUAL", 99, 99)
        assert result == "the target of 99 was confirmed as the real enrolled count"

    def test_large_numbers_are_grouped(self):
        assert "1,195" in describe_enrollment_type("ESTIMATED", "ACTUAL", 1155, 1195)

    def test_it_degrades_to_the_wordless_sentence_when_no_count_is_known(self):
        """Six of the eight real switches carry no same-amendment count row.
        The sentence has to stay true without one rather than inventing a
        number or disappearing."""
        result = describe_enrollment_type("ESTIMATED", "ACTUAL")
        assert result == "the recruitment target was replaced by a real enrolled count"


class TestEnrollmentContext:
    """Which enrollment number belongs to WHICH amendment.

    The tempting shortcut is to read `studies.enrollment_count` and put it
    in the sentence. That is the count as of today, and against an
    amendment from three weeks ago it states a fact about the trial that was
    not true when it happened (CLAUDE.md sec. 2). These pin the unwinding.
    """

    def field(self, name, old, new):
        return AmendedField(field_name=name, old_value=old, new_value=new, detected_at=WHEN)

    def test_a_count_row_in_the_amendment_overrides_whatever_was_passed_in(self):
        """The row states both sides of this exact amendment, so it is
        authoritative — the caller's running value cannot be more correct."""
        changes = [self.field("enrollment_count", "400", "163")]
        context, before = enrollment_context(changes, count_after=9999)
        assert context == {"enrollment_count_before": 400, "enrollment_count_after": 163}
        assert before == 400

    def test_without_a_count_row_the_number_is_unchanged_across_the_amendment(self):
        changes = [self.field("overall_status", "RECRUITING", "COMPLETED")]
        context, before = enrollment_context(changes, count_after=99)
        assert context == {"enrollment_count_before": 99, "enrollment_count_after": 99}
        assert before == 99

    def test_the_returned_before_value_is_what_unwinds_the_history(self):
        """Walking a trial's amendments newest-first, each one hands the
        next-older one the count that preceded it. Two count moves in a row
        must not leave the older amendment describing the newer number."""
        newer = [self.field("enrollment_count", "500", "600")]
        older = [self.field("enrollment_count", "120", "500")]

        _, before_newer = enrollment_context(newer, count_after=600)
        context_older, before_older = enrollment_context(older, count_after=before_newer)

        assert before_newer == 500
        assert context_older["enrollment_count_after"] == 500
        assert context_older["enrollment_count_before"] == 120
        assert before_older == 120

    def test_an_unknown_count_stays_unknown_rather_than_becoming_zero(self):
        changes = [self.field("overall_status", "RECRUITING", "COMPLETED")]
        context, before = enrollment_context(changes, count_after=None)
        assert context["enrollment_count_after"] is None
        assert before is None

    def test_an_unparseable_count_row_does_not_crash_the_amendment(self):
        """CT.gov has sent stranger things. A bad value must degrade to the
        numberless sentence, not a 500."""
        changes = [self.field("enrollment_count", "lots", "more")]
        context, before = enrollment_context(changes, count_after=42)
        assert context["enrollment_count_after"] == 42
        assert before == 42


class TestListShift:
    def _sites(self, names):
        return json.dumps([{"facility": n, "city": "X", "country": "Y"} for n in names])

    def test_sites_added_and_removed_are_counted(self):
        result = describe_list_shift(self._sites(["A", "B"]), self._sites(["B", "C", "D"]), "site")
        assert result == "2 sites added, 1 removed"

    def test_only_additions_reads_naturally(self):
        assert describe_list_shift(self._sites([]), self._sites(["A"]), "site") == "1 site added"

    def test_a_reordered_list_is_not_a_change(self):
        """CT.gov reorders these freely; reporting a reorder as movement
        would cry wolf on every refetch."""
        assert describe_list_shift(self._sites(["A", "B"]), self._sites(["B", "A"]), "site") is None

    def test_malformed_json_is_none_rather_than_an_exception(self):
        assert describe_list_shift("{not json", self._sites(["A"]), "site") is None

    def test_a_quarter_megabyte_of_locations_reduces_to_two_numbers(self):
        """One real amendment stores 252,041 characters of locations JSON.
        The honest summary is a count — which is also why this field never
        reaches a diff view or a prompt."""
        # Real facility strings look like "Headlands Research - Scottsdale
        # /ID# 282571" — ~43 characters, not "Site 7". Using the short form
        # made this fixture a third of the real size.
        def name(i):
            return f"Headlands Research - Facility {i} /ID# {282571 + i}"

        big_old = self._sites([name(i) for i in range(400)])
        big_new = self._sites([name(i) for i in range(3, 405)])
        assert len(big_old) > 30_000
        result = describe_list_shift(big_old, big_new, "site")
        assert result == "5 sites added, 3 removed"
        assert len(result) < 40


class TestDescribeEffectBoundary:
    """The single most important property in this module."""

    @pytest.mark.parametrize("field", [
        "brief_summary", "eligibility_criteria", "primary_outcomes",
        "brief_title", "official_title",
    ])
    def test_prose_fields_get_no_effect_at_all(self, field):
        """What a rewritten eligibility criterion now MEANS is a reading of
        clinical text, not arithmetic. This module must decline it — that
        boundary is the whole argument for where a model would earn its
        cost, and if this ever starts returning a string, something has
        begun paraphrasing clinical text deterministically."""
        assert describe_effect(field, "Adults with BMI over 35", "Adults with BMI over 45") is None

    def test_an_unknown_field_is_none(self):
        assert describe_effect("a_field_from_2027", "a", "b") is None

    def test_the_real_amendment_end_to_end(self):
        """NCT02954874's 31 August amendment, exactly as stored."""
        assert describe_effect("completion_date", "2026-08-31", "2027-08-27") == \
            "pushed about 12 months later"
        assert describe_effect("enrollment_count", "1155", "1195") == "increased by 40"
        assert "real enrolled count" in describe_effect("enrollment_type", "ESTIMATED", "ACTUAL")


class TestResultsPosting:
    """has_results, added 2026-09-02 after finding it was never stored.

    `hasResults` sits at the TOP level of the CT.gov response rather than
    inside protocolSection, so the original parser — which read every module
    one level down — never saw it. 1,056 of 11,518 stored trials already had
    results posted, and every one of those amendments had been reported as
    "amended, but we can't see what".
    """

    def test_false_to_true_is_stated_as_the_findings_being_published(self):
        result = describe_results_posting("false", "true")
        assert "results have been posted" in result
        assert "published" in result

    def test_stringified_booleans_from_study_changes_are_handled(self):
        """study_changes stores everything as TEXT, so the values arrive as
        "true"/"false" strings, not Python booleans."""
        assert describe_results_posting("false", "true") == describe_results_posting(False, True)

    def test_withdrawal_of_results_is_flagged_as_unusual(self):
        assert "unusual" in describe_results_posting("true", "false")

    def test_no_change_and_missing_values_produce_nothing(self):
        assert describe_results_posting("true", "true") is None
        assert describe_results_posting(None, "true") is None
        assert describe_results_posting("false", None) is None

    def test_it_is_classified_as_scientific_not_administrative(self):
        """Results appearing is the trial's whole point, not bookkeeping."""
        assert field_aspect("has_results") == ASPECT_SCIENTIFIC

    def test_it_routes_through_describe_effect(self):
        assert "results have been posted" in describe_effect("has_results", "false", "true")
