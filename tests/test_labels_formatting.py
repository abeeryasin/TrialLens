"""is_formatting_only() — the four cases its docstring says were checked.

The function decides whether TrialLens tells a researcher that a trial's
wording changed. Its docstring claims: "All four of those cases were checked
and correctly return False." Nothing checked them. Until now the claim was
true only of whoever wrote it, on the day they wrote it.

It is reached from both Monitor and Understand via summarize_text_change()
and render_text_diff() (frontend/labels.py), and amendment history depends
on it: a false positive prints "Reformatted only — same wording" over a
change that moved a real clinical threshold, which is a false statement
about a study fact (CLAUDE.md sec. 2). A false negative merely shows a diff
nobody needed. The function is deliberately biased toward the harmless
error, and these tests hold it to that bias.

Free — no database, no network, no Streamlit rendering.
"""
import pytest

from frontend.labels import (
    format_posted_on,
    format_posted_on_list,
    format_recording_since,
    is_formatting_only,
)


class TestTheFourClinicalCasesTheDocstringClaims:
    """Each of these MUST be reported as a real change."""

    def test_a_bmi_cutoff_moving_is_not_formatting(self):
        assert not is_formatting_only(
            "Patients with BMI greater than 35 kg/m2",
            "Patients with BMI greater than 45 kg/m2",
        )

    def test_an_egfr_threshold_tightening_is_not_formatting(self):
        assert not is_formatting_only(
            "Exclusion: eGFR < 60 mL/min/1.73m2",
            "Exclusion: eGFR < 30 mL/min/1.73m2",
        )

    def test_a_dropped_negation_is_not_formatting(self):
        """The most dangerous edit in the set: one short word, and the
        criterion now means the opposite."""
        assert not is_formatting_only(
            "Patients with no prior systemic therapy",
            "Patients with prior systemic therapy",
        )

    def test_a_changed_number_anywhere_is_not_formatting(self):
        assert not is_formatting_only(
            "Age 18 to 75 years", "Age 18 to 85 years"
        )


class TestWhatItIsAllowedToCallCosmetic:
    def test_pure_whitespace_reflow(self):
        assert is_formatting_only(
            "Inclusion: adults with type 2 diabetes",
            "Inclusion:    adults  with type 2 diabetes",
        )

    def test_a_run_on_list_rewritten_as_bullets(self):
        """The case the docstring names as the motivating example."""
        assert is_formatting_only(
            "Inclusion: adults; ECOG 0-1; measurable disease",
            "Inclusion:\n- adults\n- ECOG 0-1\n- measurable disease",
        )

    def test_capitalisation_only(self):
        assert is_formatting_only("ECOG performance status", "ECOG Performance Status")

    def test_punctuation_only(self):
        assert is_formatting_only("Age 18-75 years.", "Age 18-75 years")


class TestTheBiasIsDeliberate:
    """It must resolve doubt toward "this is a real change"."""

    def test_identical_text_is_not_a_formatting_change(self):
        """Nothing changed at all, so there is no change to describe. This
        matters because summarize_text_change would otherwise print
        "Reformatted only" for a no-op diff."""
        assert not is_formatting_only("Age 18-75 years", "Age 18-75 years")

    @pytest.mark.parametrize("old,new", [
        (None, "Age 18-75 years"),
        ("Age 18-75 years", None),
        (None, None),
    ])
    def test_a_missing_side_is_never_called_cosmetic(self, old, new):
        """A criterion appearing or disappearing is a real change, and a
        None is not something to compare punctuation on."""
        assert not is_formatting_only(old, new)

    def test_a_word_removed_is_real_even_when_punctuation_also_moved(self):
        assert not is_formatting_only(
            "Inclusion: adults; ECOG 0-1; measurable disease",
            "Inclusion:\n- adults\n- ECOG 0-1",
        )

    def test_units_changing_is_real_even_though_the_number_is_identical(self):
        """"6 Months" and "6 Years" differ by one word, and CT.gov genuinely
        stores ages in units other than years."""
        assert not is_formatting_only("Minimum age 6 Months", "Minimum age 6 Years")


class TestPostedOn:
    """format_posted_on — one CT.gov version stamp.

    Pinned 2026-09-02 after the single-date and multi-date formatters were
    found to disagree: this one padded the day and format_posted_on_list
    stripped it, so "1 September 2026" and "01 September 2026" could appear
    on the same page for the same date depending on how many were shown.
    """

    def test_the_day_carries_no_leading_zero(self):
        assert format_posted_on("2026-09-01") == "1 September 2026"

    def test_a_two_digit_day_is_unchanged(self):
        assert format_posted_on("2026-08-31") == "31 August 2026"

    def test_it_agrees_with_the_list_formatter_on_the_same_date(self):
        """The bug this class exists for. Neither is more correct than the
        other; disagreeing is what was wrong."""
        for value in ("2026-09-01", "2026-08-08", "2026-08-31"):
            assert format_posted_on(value) == format_posted_on_list([value])

    def test_an_unparseable_value_comes_back_raw_not_as_a_crash(self):
        assert format_posted_on("sometime in June") == "sometime in June"

    def test_nothing_is_an_em_dash_not_an_empty_string(self):
        assert format_posted_on(None) == "—"


class TestRecordingSince:
    """format_recording_since — "watching since X", from a timestamp."""

    def test_it_drops_the_time_and_the_leading_zero(self):
        assert format_recording_since("2026-09-01T18:03:16+00:00") == "1 September 2026"

    def test_it_matches_how_the_same_day_reads_elsewhere(self):
        assert format_recording_since("2026-08-28T12:55:52+00:00") == format_posted_on(
            "2026-08-28"
        )

    def test_no_record_reads_as_a_phrase_not_a_blank(self):
        """It is interpolated mid-sentence ("...amended before {X} cannot be
        shown"), so an empty string would leave a broken sentence."""
        assert format_recording_since(None) == "we began tracking"


class TestPostedOnList:
    """format_posted_on_list — the dates of amendments with nothing to show.

    They are named once in a summary sentence rather than each getting a
    line whose only real content was its date. No trial carries more than
    three (measured 2026-09-02; 79 of 88 have exactly one).
    """

    def test_one_date_reads_plainly(self):
        assert format_posted_on_list(["2026-08-28"]) == "28 August 2026"

    def test_a_leading_zero_is_dropped(self):
        """"08 August" is not how anyone writes a date in a sentence."""
        assert format_posted_on_list(["2026-08-08"]) == "8 August 2026"

    def test_two_dates_in_the_same_year_state_the_year_once(self):
        assert format_posted_on_list(["2026-08-28", "2026-08-31"]) == "28 and 31 August 2026"

    def test_three_dates_in_one_month_collapse_to_days(self):
        assert format_posted_on_list(
            ["2026-08-28", "2026-08-30", "2026-08-31"]
        ) == "28, 30 and 31 August 2026"

    def test_dates_across_months_keep_each_month(self):
        assert format_posted_on_list(
            ["2026-08-28", "2026-08-31", "2026-09-01"]
        ) == "28 August, 31 August and 1 September 2026"

    def test_dates_spanning_years_keep_every_year(self):
        result = format_posted_on_list(["2025-12-30", "2026-01-02"])
        assert result == "30 December 2025 and 2 January 2026"

    def test_input_order_does_not_matter(self):
        assert (format_posted_on_list(["2026-08-31", "2026-08-28"])
                == format_posted_on_list(["2026-08-28", "2026-08-31"]))

    def test_unparseable_dates_are_skipped_not_rendered_raw(self):
        assert format_posted_on_list(["not a date", "2026-08-28"]) == "28 August 2026"

    def test_nothing_parseable_returns_empty_rather_than_a_stray_dash(self):
        assert format_posted_on_list(["not a date", None]) == ""

    def test_it_accepts_a_generator(self):
        """The page passes a genexp, which a naive len() would exhaust."""
        assert format_posted_on_list(d for d in ["2026-08-28"]) == "28 August 2026"
