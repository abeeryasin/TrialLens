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

from frontend.labels import is_formatting_only


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
