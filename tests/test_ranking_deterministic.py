"""Unit tests for the deterministic fit signals.

Every value used here was observed in the real `dev` database on
2026-08-30 (11,490 studies) — see api/ranking_deterministic.py for the
frequency tables. These tests cost nothing to run and must stay in CI:
they are the half of the evaluation story that doesn't need the API.

Run: PYTHONPATH=. python3 -m pytest tests/test_ranking_deterministic.py -v
"""
from datetime import date, datetime

import pytest

from api.ranking_deterministic import (
    INTERVENTION_TYPES,
    ResearcherPreferences,
    parse_age_to_years,
    parse_phases,
    score_age_range_fit,
    score_approach_category,
    score_enrollment_feasibility,
    score_phase_fit,
    score_sites_active,
    score_status_recruiting,
)
from api.schemas import Intervention, StudyDetail, TrialLocation

W = 0.20  # arbitrary weight; scorers must pass it through unchanged


def make_trial(**overrides) -> StudyDetail:
    """A StudyDetail with realistic defaults, overridable per test."""
    base = dict(
        nct_id="NCT00000000",
        brief_title="Test trial",
        overall_status="RECRUITING",
        phase="PHASE2",
        study_type="INTERVENTIONAL",
        last_update_post_date=date(2026, 8, 1),
        active_in_scope=True,
        enrollment_count=120,
        enrollment_type="ACTUAL",
        minimum_age="18 Years",
        maximum_age="75 Years",
        fetched_at=datetime(2026, 8, 30),
        last_matched_at=datetime(2026, 8, 30),
        conditions=["Breast Cancer"],
        locations=[TrialLocation(facility="Site", city="Boston", country="United States")],
    )
    base.update(overrides)
    return StudyDetail(**base)


# ============================================================================
# parse_age_to_years
# ============================================================================


class TestParseAge:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("18 Years", 18.0),
            ("0 Years", 0.0),
            ("130 Years", 130.0),   # real maximum_age value (39 studies)
            ("1 Year", 1.0),        # singular form occurs (6 studies)
        ],
    )
    def test_years(self, value, expected):
        assert parse_age_to_years(value) == pytest.approx(expected)

    def test_months_are_not_years(self):
        """'18 Months' is 1.5 years, not 18. Real value: 10 studies."""
        assert parse_age_to_years("18 Months") == pytest.approx(1.5)

    def test_one_day_is_not_one_year(self):
        """The 365x error a naive int(split()[0]) parser would make.

        '1 Day' is a real minimum_age (12 studies) — neonatal enrollment.
        """
        result = parse_age_to_years("1 Day")
        assert result == pytest.approx(1 / 365.25)
        assert result < 0.01

    @pytest.mark.parametrize(
        "value", ["6 Months", "4 Weeks", "2 Hours", "1 Minutes", "8 Days"]
    )
    def test_all_observed_units_parse(self, value):
        """Every unit seen in the database must parse to a real number."""
        result = parse_age_to_years(value)
        assert result is not None and result >= 0

    @pytest.mark.parametrize("value", [None, "", "N/A", "eighteen", "Years", "18"])
    def test_unparseable_returns_none_not_a_guess(self, value):
        """Absent or malformed input must yield None — never a default (sec. 2)."""
        assert parse_age_to_years(value) is None


# ============================================================================
# parse_phases
# ============================================================================


class TestParsePhases:
    def test_single_phase(self):
        assert parse_phases("PHASE2") == {"PHASE2"}

    def test_multi_phase_is_comma_separated(self):
        """Real stored format for 461 studies."""
        assert parse_phases("PHASE1,PHASE2") == {"PHASE1", "PHASE2"}

    def test_early_phase1(self):
        assert parse_phases("EARLY_PHASE1") == {"EARLY_PHASE1"}

    def test_na_is_not_a_phase(self):
        """'NA' (4,869 studies) means 'no phase concept', not 'missing'.

        Either way it can't be compared, so it must not read as a match.
        """
        assert parse_phases("NA") is None

    def test_absent_phase(self):
        """2,442 studies store NULL."""
        assert parse_phases(None) is None
        assert parse_phases("") is None


# ============================================================================
# score_status_recruiting
# ============================================================================


class TestStatusRecruiting:
    WANTS_RECRUITING = ResearcherPreferences(require_recruiting=True)

    def test_recruiting_matches(self):
        signal = score_status_recruiting(
            make_trial(overall_status="RECRUITING"), self.WANTS_RECRUITING, W
        )
        assert signal.status == "match"
        assert signal.source_value == "RECRUITING"

    @pytest.mark.parametrize(
        "status", ["COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED", "ACTIVE_NOT_RECRUITING"]
    )
    def test_non_enrolling_statuses_are_no_match(self, status):
        """All five were unguided by the prompt this replaces."""
        signal = score_status_recruiting(
            make_trial(overall_status=status), self.WANTS_RECRUITING, W
        )
        assert signal.status == "no_match"

    @pytest.mark.parametrize(
        "status", ["ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"]
    )
    def test_restricted_enrollment_is_partial_not_binary(self, status):
        """1,680 studies. Neither 'open' nor 'closed' — the honest answer is partial."""
        signal = score_status_recruiting(
            make_trial(overall_status=status), self.WANTS_RECRUITING, W
        )
        assert signal.status == "partial"

    def test_unstated_preference_is_unknown_not_no_match(self):
        """The scoring bug this rework fixes.

        A preference the researcher never expressed must not count against
        the trial. `unknown` is excluded from the score denominator;
        `no_match` would drag the score down for a question nobody asked.
        """
        signal = score_status_recruiting(
            make_trial(overall_status="COMPLETED"), ResearcherPreferences(), W
        )
        assert signal.status == "unknown"

    def test_unrecognised_status_says_so(self):
        """A new upstream value must surface as 'requires review', not a guess."""
        signal = score_status_recruiting(
            make_trial(overall_status="SOME_NEW_STATUS"), self.WANTS_RECRUITING, W
        )
        assert signal.status == "unknown"
        assert signal.confidence == "low"

    def test_every_real_status_is_handled(self):
        """No status observed in the database may fall through to the unknown branch."""
        real_statuses = [
            "RECRUITING", "COMPLETED", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING",
            "TERMINATED", "ENROLLING_BY_INVITATION", "WITHDRAWN", "SUSPENDED",
        ]
        for status in real_statuses:
            signal = score_status_recruiting(
                make_trial(overall_status=status), self.WANTS_RECRUITING, W
            )
            assert signal.status in {"match", "partial", "no_match"}, (
                f"{status} fell through to an unknown branch"
            )


# ============================================================================
# score_sites_active
# ============================================================================


class TestSitesActive:
    def test_no_sites(self):
        """707 studies list zero locations."""
        signal = score_sites_active(make_trial(locations=[]), W)
        assert signal.status == "no_match"
        assert signal.source_value == "0 sites"

    def test_single_site_is_partial(self):
        signal = score_sites_active(
            make_trial(locations=[TrialLocation(facility="A", city="X", country="US")]), W
        )
        assert signal.status == "partial"

    def test_multi_site_matches_and_counts_countries(self):
        locations = [
            TrialLocation(facility="A", city="Boston", country="United States"),
            TrialLocation(facility="B", city="Toronto", country="Canada"),
            TrialLocation(facility="C", city="Paris", country="France"),
        ]
        signal = score_sites_active(make_trial(locations=locations), W)
        assert signal.status == "match"
        assert signal.source_value == "3 sites"
        assert "3 countries" in signal.evidence


# ============================================================================
# score_enrollment_feasibility
# ============================================================================


class TestEnrollmentFeasibility:
    def test_estimated_is_labelled_as_a_target(self):
        """6,577 studies report ESTIMATED — a target, not a headcount (step 6b)."""
        signal = score_enrollment_feasibility(
            make_trial(enrollment_count=500, enrollment_type="ESTIMATED"), W
        )
        assert "target" in signal.evidence.lower()
        assert "ESTIMATED" in signal.source_value

    def test_actual_is_labelled_as_enrolled(self):
        signal = score_enrollment_feasibility(
            make_trial(enrollment_count=500, enrollment_type="ACTUAL"), W
        )
        assert "actual" in signal.evidence.lower()

    def test_absent_count_is_unknown(self):
        signal = score_enrollment_feasibility(make_trial(enrollment_count=None), W)
        assert signal.status == "unknown"

    def test_untyped_count_admits_it_cannot_tell(self):
        """8 studies have a count but no type — don't silently assume either."""
        signal = score_enrollment_feasibility(
            make_trial(enrollment_count=200, enrollment_type=None), W
        )
        assert signal.confidence == "medium"
        assert "can't tell" in signal.evidence.lower()


# ============================================================================
# score_age_range_fit
# ============================================================================


class TestAgeRangeFit:
    def test_unstated_preference_is_unknown(self):
        signal = score_age_range_fit(make_trial(), ResearcherPreferences(), W)
        assert signal.status == "unknown"

    def test_trial_covering_whole_range_matches(self):
        prefs = ResearcherPreferences(min_age_years=40, max_age_years=60)
        signal = score_age_range_fit(
            make_trial(minimum_age="18 Years", maximum_age="75 Years"), prefs, W
        )
        assert signal.status == "match"

    def test_partial_overlap(self):
        prefs = ResearcherPreferences(min_age_years=60, max_age_years=90)
        signal = score_age_range_fit(
            make_trial(minimum_age="18 Years", maximum_age="75 Years"), prefs, W
        )
        assert signal.status == "partial"

    def test_no_overlap(self):
        prefs = ResearcherPreferences(min_age_years=5, max_age_years=12)
        signal = score_age_range_fit(
            make_trial(minimum_age="18 Years", maximum_age="75 Years"), prefs, W
        )
        assert signal.status == "no_match"

    def test_absent_maximum_age_means_unbounded_above(self):
        """5,778 studies have no maximum_age — that means no upper limit."""
        prefs = ResearcherPreferences(min_age_years=70, max_age_years=95)
        signal = score_age_range_fit(
            make_trial(minimum_age="18 Years", maximum_age=None), prefs, W
        )
        assert signal.status == "match"

    def test_trial_with_no_bounds_at_all_is_unknown(self):
        prefs = ResearcherPreferences(min_age_years=40, max_age_years=60)
        signal = score_age_range_fit(
            make_trial(minimum_age=None, maximum_age=None), prefs, W
        )
        assert signal.status == "unknown"

    def test_paediatric_bound_in_days_is_not_read_as_years(self):
        """A neonatal band ('1 Day' to '6 Months') against an infant question.

        Correct parse: 0.003–0.5 years overlaps part of 0–1 year -> partial.
        Misparsing the units as years gives 1–0.5, an inverted band that
        overlaps nothing -> no_match. The two outcomes differ, so this test
        actually discriminates a unit bug rather than merely passing.
        """
        prefs = ResearcherPreferences(min_age_years=0, max_age_years=1)
        signal = score_age_range_fit(
            make_trial(minimum_age="1 Day", maximum_age="6 Months"), prefs, W
        )
        assert signal.status == "partial"


# ============================================================================
# score_phase_fit
# ============================================================================


class TestPhaseFit:
    def test_unstated_preference_is_unknown(self):
        signal = score_phase_fit(make_trial(phase="PHASE2"), ResearcherPreferences(), W)
        assert signal.status == "unknown"

    def test_exact_match(self):
        prefs = ResearcherPreferences(phases=["PHASE2", "PHASE3"])
        signal = score_phase_fit(make_trial(phase="PHASE2"), prefs, W)
        assert signal.status == "match"

    def test_multi_phase_trial_partially_inside_preference(self):
        """PHASE1,PHASE2 against a Phase 2-only interest is partial, not a match."""
        prefs = ResearcherPreferences(phases=["PHASE2"])
        signal = score_phase_fit(make_trial(phase="PHASE1,PHASE2"), prefs, W)
        assert signal.status == "partial"

    def test_outside_preference(self):
        prefs = ResearcherPreferences(phases=["PHASE3"])
        signal = score_phase_fit(make_trial(phase="PHASE1"), prefs, W)
        assert signal.status == "no_match"

    def test_interventional_na_phase_is_unknown(self):
        """4,869 studies: a real interventional trial that isn't phase-classified
        (common for behavioural, device and procedure trials). We genuinely
        can't compare it, so it must not count against the trial."""
        prefs = ResearcherPreferences(phases=["PHASE2"])
        signal = score_phase_fit(
            make_trial(phase="NA", study_type="INTERVENTIONAL"), prefs, W
        )
        assert signal.status == "unknown"
        assert "interventional" in signal.evidence.lower()

    def test_observational_study_cannot_match_a_phase_request(self):
        """2,440 studies. An observational study has no phase by definition —
        that is a fact, not an ambiguity.

        Scoring it `unknown` excluded it from the denominator, so it cost the
        trial nothing and an observational cohort could rank alongside genuine
        Phase II trials for a researcher who explicitly asked for Phase II.
        """
        prefs = ResearcherPreferences(phases=["PHASE2"])
        signal = score_phase_fit(
            make_trial(phase=None, study_type="OBSERVATIONAL"), prefs, W
        )
        assert signal.status == "no_match"
        assert signal.confidence == "high"
        assert "observational" in signal.evidence.lower()

    def test_no_phase_and_no_study_type_stays_unknown(self):
        """With neither field we genuinely cannot tell — don't guess either way."""
        prefs = ResearcherPreferences(phases=["PHASE2"])
        signal = score_phase_fit(
            make_trial(phase=None, study_type=None), prefs, W
        )
        assert signal.status == "unknown"

    def test_absent_phase_is_unknown(self):
        prefs = ResearcherPreferences(phases=["PHASE2"])
        signal = score_phase_fit(make_trial(phase=None), prefs, W)
        assert signal.status == "unknown"


# ============================================================================
# Cross-cutting guarantees
# ============================================================================


class TestEvidenceContract:
    """Sec. 3: every signal preserves source field, source value, and uncertainty."""

    def _all_signals(self):
        prefs = ResearcherPreferences(
            phases=["PHASE2"], require_recruiting=True,
            min_age_years=40, max_age_years=60,
        )
        trial = make_trial()
        return [
            score_status_recruiting(trial, prefs, W),
            score_sites_active(trial, W),
            score_enrollment_feasibility(trial, W),
            score_age_range_fit(trial, prefs, W),
            score_phase_fit(trial, prefs, W),
        ]

    def test_every_signal_names_its_source_field_and_value(self):
        for signal in self._all_signals():
            assert signal.source_field, f"{signal.name} has no source_field"
            assert signal.source_value, f"{signal.name} has no source_value"

    def test_every_signal_carries_readable_evidence(self):
        for signal in self._all_signals():
            assert len(signal.evidence) > 20, f"{signal.name} evidence is too thin"

    def test_weight_is_passed_through_unchanged(self):
        for signal in self._all_signals():
            assert signal.weight == W

    def test_scorers_are_reproducible(self):
        """The property the LLM version could not offer: identical input,
        identical output, every time."""
        first = [(s.name, s.status, s.evidence) for s in self._all_signals()]
        for _ in range(5):
            assert [(s.name, s.status, s.evidence) for s in self._all_signals()] == first


class TestApproachCategory:
    """The free half of the approach question, from CT.gov's structured
    interventionType. Catches the obvious category mismatch for $0; returns
    None (defer to the model) for everything that needs judgment.
    """

    def _trial(self, types):
        return make_trial(interventions=[
            Intervention(type=t, name=f"{t.lower()} thing") for t in types
        ])

    def test_disjoint_categories_are_a_deterministic_no_match(self):
        signal = score_approach_category(
            self._trial(["DRUG"]),
            ResearcherPreferences(approach_types=["PROCEDURE"]),
            0.10,
        )
        assert signal is not None
        assert signal.status == "no_match"
        assert signal.name == "approach_match"
        assert signal.confidence == "high"
        # sec. 3: the stored value, not a paraphrase — and both sides of the
        # comparison, since only one of them is registry fact.
        assert "DRUG" in signal.source_value
        assert "interventions[].type" in signal.source_field

    def test_overlapping_categories_defer_to_the_model(self):
        """DRUG vs DRUG cannot separate a GLP-1 from an SGLT2. That is
        exactly the judgment the paid call exists for — answering it here
        would be guessing with a confident face."""
        assert score_approach_category(
            self._trial(["DRUG"]),
            ResearcherPreferences(approach_types=["DRUG", "BIOLOGICAL"]),
            0.10,
        ) is None

    def test_a_trial_with_no_interventions_is_never_ruled_out(self):
        """985 of 11,420 active trials record no interventions. Absent data
        is not evidence against a trial (sec. 2) — it must defer, never
        return no_match."""
        assert score_approach_category(
            self._trial([]),
            ResearcherPreferences(approach_types=["PROCEDURE"]),
            0.10,
        ) is None

    def test_other_never_produces_a_mismatch(self):
        """OTHER appears on 3,939 interventions and carries no category
        information. Letting it conflict would manufacture false no_matches
        across a third of the database."""
        assert score_approach_category(
            self._trial(["OTHER"]),
            ResearcherPreferences(approach_types=["PROCEDURE"]),
            0.10,
        ) is None

    def test_no_stated_approach_defers(self):
        assert score_approach_category(
            self._trial(["DRUG"]), ResearcherPreferences(), 0.10
        ) is None

    def test_mixed_trial_matching_one_wanted_type_defers(self):
        """A trial that is part DRUG part PROCEDURE is not a category
        mismatch for a surgical researcher — 1,732 trials carry more than
        one type."""
        assert score_approach_category(
            self._trial(["DRUG", "PROCEDURE"]),
            ResearcherPreferences(approach_types=["PROCEDURE"]),
            0.10,
        ) is None

    def test_case_and_whitespace_do_not_break_the_comparison(self):
        assert score_approach_category(
            self._trial([" drug "]),
            ResearcherPreferences(approach_types=["drug"]),
            0.10,
        ) is None

    def test_every_type_the_parse_may_emit_is_a_real_ctgov_value(self):
        """The parse's enum and the database's vocabulary must be the same
        list. A type the parse can emit but the data never uses would
        silently never match anything."""
        from api.ranking import INTEREST_PARSE_SCHEMA

        allowed = set(INTEREST_PARSE_SCHEMA["properties"]["approach_types"]["items"]["enum"])
        assert allowed == set(INTERVENTION_TYPES)

    def test_the_mismatch_discloses_that_the_researcher_side_was_inferred(self):
        """The third honesty guard.

        The trial's intervention types come from the registry. The
        researcher's come from a model reading their prose. A deterministic
        `no_match` that removes thousands of trials rests on both, so the
        evidence must not present the whole comparison as registry fact —
        an earlier version said "not inferred", which was half true and
        therefore misleading (sec. 3).
        """
        signal = score_approach_category(
            self._trial(["DRUG"]),
            ResearcherPreferences(approach_types=["PROCEDURE"]),
            0.10,
        )
        # Both sides named, and which is which is stated.
        assert "drug" in signal.evidence.lower()
        assert "procedure" in signal.evidence.lower()
        assert "interpreted" in signal.evidence.lower()
        assert "registry" in signal.evidence.lower()
        # The source value carries both halves, not just the certain one.
        assert "DRUG" in signal.source_value and "PROCEDURE" in signal.source_value
        assert "not inferred" not in signal.evidence.lower()
