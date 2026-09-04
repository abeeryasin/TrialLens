"""The Investigate engine's arithmetic, with no database in the way.

Every question this module answers has exactly one correct answer, which
is the whole argument for it being plain code (CLAUDE.md sec. 5). These
tests are that argument's evidence: they state the answer and check it.

**Several cases here cannot be reached by the live data**, and they are
the reason this file exists alongside the real-data suite. On 2026-09-04
no trial in the record had a type switch followed by a later count move,
so the guard that refuses to attribute today's headcount to an older
amendment never fires against real rows — a suite that only ran against
production would report it as covered while never executing it. That is
the fixture trap CLAUDE.md records twice: when testing a property only
some rows have, construct the row that has it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from api.amendments import describe_date_shift
from api.investigate import (
    MOVE_NONE,
    MOVE_PRECISION,
    MOVE_PULLED,
    MOVE_PUSHED,
    MOVE_UNREADABLE,
    TRANSITION_OTHER,
    analyse_date_moves,
    analyse_enrollment,
    analyse_scope_exits,
    analyse_status_moves,
    classify_date_move,
    transition_kind,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def row(field_name, old, new, nct_id="NCT00000001", at=T0, **extra):
    return {
        "nct_id": nct_id,
        "brief_title": f"Trial {nct_id}",
        "field_name": field_name,
        "old_value": old,
        "new_value": new,
        "detected_at": at,
        **extra,
    }


# ============================================================================
# Date arithmetic
# ============================================================================


@pytest.mark.parametrize(
    "old, new, kind, delta, imprecise",
    [
        # Real rows from the live database, 2026-09-04.
        ("2028-03", "2021-12-19", MOVE_PULLED, -2264, True),
        ("2037-11-15", "2032-05-15", MOVE_PULLED, -2010, False),
        ("2026-08", "2030-09-01", MOVE_PUSHED, 1492, True),
        ("2026-08-31", "2026-12-31", MOVE_PUSHED, 122, False),
        # Both sides month-precision and one month apart: a genuine move.
        ("2026-12", "2027-01", MOVE_PUSHED, 31, True),
    ],
)
def test_classify_real_date_moves(old, new, kind, delta, imprecise):
    assert classify_date_move(old, new) == (kind, delta, imprecise)


def test_month_precision_under_two_weeks_is_an_artefact_not_a_slip():
    """"2026-03" -> "2026-03-14" is not a 13-day slip.

    Both sides are anchored to the 1st for arithmetic, so the difference is
    an artefact of a date the registry only ever gave to the month. Counting
    it as a slip would inflate every slip count in the product by exactly
    the share of month-precision dates, which is ~23%.

    The cut-off is describe_date_shift's, not one chosen here: it reports
    in weeks from 14 days up, so exactly two weeks IS a move even when a
    side is imprecise, and 13 days is not. Asserted both ways below so the
    boundary itself is pinned rather than assumed.
    """
    kind, delta, imprecise = classify_date_move("2026-03", "2026-03-14")
    assert kind == MOVE_PRECISION
    assert delta == 13 and imprecise is True
    # One day further and the same rule calls it a move.
    assert classify_date_move("2026-03", "2026-03-15")[0] == MOVE_PUSHED


def test_same_date_is_no_move_not_a_slip():
    assert classify_date_move("2026-03", "2026-03-01")[0] == MOVE_NONE
    assert classify_date_move("2026-03-04", "2026-03-04")[0] == MOVE_NONE


def test_precise_short_move_is_real():
    """The artefact rule applies only when a side is month-precision. Two
    full dates three days apart really are three days apart."""
    assert classify_date_move("2026-03-04", "2026-03-07") == (MOVE_PUSHED, 3, False)


@pytest.mark.parametrize("bad", [None, "", "not a date", "2026", "2026-13-01"])
def test_unparseable_dates_are_unreadable_never_silently_zero(bad):
    kind, delta, _ = classify_date_move(bad, "2026-05-01")
    assert kind == MOVE_UNREADABLE
    assert delta is None


@pytest.mark.parametrize(
    "old, new",
    [
        ("2028-03", "2021-12-19"),
        ("2026-03", "2026-03-14"),
        ("2026-03", "2026-03-15"),
        ("2026-03-04", "2026-03-07"),
        ("2026-03", "2026-03-01"),
        ("2026-12", "2027-01"),
        ("junk", "2026-05-01"),
    ],
)
def test_move_definition_agrees_with_the_per_trial_view(old, new):
    """One definition of "did this date move", not two.

    Understand shows describe_date_shift's sentence for a single amendment;
    Investigate counts the same row in an aggregate. If these two ever
    disagreed, the same change would be a slip on one page and not on the
    other. classify_date_move calls describe_date_shift rather than
    re-deriving its threshold, and this is the test that keeps it so.
    """
    kind, _, _ = classify_date_move(old, new)
    counted_as_a_move = kind in {MOVE_PUSHED, MOVE_PULLED}
    assert counted_as_a_move is (describe_date_shift(old, new) is not None)


def test_date_movement_reports_every_denominator():
    rows = [
        row("primary_completion_date", "2026-01-01", "2026-07-01", nct_id="NCT1"),  # +181
        row("primary_completion_date", "2026-01-01", "2026-04-01", nct_id="NCT2"),  # +90
        row("primary_completion_date", "2027-01-01", "2026-01-01", nct_id="NCT3"),  # -365
        row("primary_completion_date", "2026-03", "2026-03-14", nct_id="NCT4"),     # artefact
        row("primary_completion_date", "2026-03", "2026-03-01", nct_id="NCT5"),     # no move
        row("primary_completion_date", "wat", "2026-03-01", nct_id="NCT6"),         # unreadable
    ]
    (finding,) = analyse_date_moves(rows)

    assert (finding.pushed, finding.pulled) == (2, 1)
    assert finding.median_push_days == 135  # median(181, 90)
    assert finding.median_pull_days == 365
    assert finding.precision_only == 1
    assert finding.no_move == 1
    assert finding.unreadable == 1
    # Every row is accounted for somewhere. A row that fell out of the
    # analysis silently would shrink the denominator and overstate the rest.
    assert finding.rows_seen == 6
    assert (
        finding.pushed
        + finding.pulled
        + finding.precision_only
        + finding.no_move
        + finding.unreadable
        == finding.rows_seen
    )


def test_a_field_whose_rows_were_all_artefacts_is_kept_not_omitted():
    """"Nothing moved" and "things changed, none of it a real shift" are
    different answers and sec. 2 forbids rendering them identically."""
    (finding,) = analyse_date_moves([row("completion_date", "2026-03", "2026-03-10")])
    assert finding.pushed == finding.pulled == 0
    assert finding.precision_only == 1
    assert finding.rows_seen == 1


def test_biggest_movers_span_both_directions_largest_first():
    rows = [
        row("completion_date", "2026-01-01", "2026-03-01", nct_id="NCT1"),   # +59
        row("completion_date", "2030-01-01", "2026-01-01", nct_id="NCT2"),   # -1461
        row("completion_date", "2026-01-01", "2027-01-01", nct_id="NCT3"),   # +365
    ]
    (finding,) = analyse_date_moves(rows)
    assert [m.nct_id for m in finding.biggest] == ["NCT2", "NCT3", "NCT1"]
    assert finding.biggest_total == 3


def test_imprecise_moves_are_counted_so_a_median_cannot_pose_as_exact():
    rows = [
        row("start_date", "2026-01", "2026-07-01", nct_id="NCT1"),
        row("start_date", "2026-01-01", "2026-07-01", nct_id="NCT2"),
    ]
    (finding,) = analyse_date_moves(rows)
    assert finding.imprecise_moves == 1
    assert finding.pushed == 2


def test_non_date_fields_are_ignored_by_the_date_analyser():
    assert analyse_date_moves([row("brief_title", "A", "B")]) == []


# ============================================================================
# Lifecycle transitions
# ============================================================================


def test_completed_to_recruiting_is_an_anomaly_not_merely_now_open():
    """The single most surprising row in the record.

    Under the general rules this reads as "now open to new participants",
    which is true and useless. It occurred once in the first eight days of
    watching, and a synthesis that averages it away has failed at the one
    job it has.
    """
    kind, label = transition_kind("COMPLETED", "RECRUITING")
    assert kind == "reopened_after_finishing"
    assert "complete" in label.lower()


@pytest.mark.parametrize(
    "old, new, kind",
    [
        ("RECRUITING", "ACTIVE_NOT_RECRUITING", "closed_to_new"),
        ("NOT_YET_RECRUITING", "RECRUITING", "opened"),
        ("RECRUITING", "COMPLETED", "finished"),
        ("ACTIVE_NOT_RECRUITING", "COMPLETED", "finished"),
        ("ENROLLING_BY_INVITATION", "COMPLETED", "finished"),
        ("ACTIVE_NOT_RECRUITING", "RECRUITING", "reopened"),
        ("RECRUITING", "TERMINATED", "stopped_early"),
        ("RECRUITING", "SUSPENDED", "stopped_early"),
        ("NOT_YET_RECRUITING", "WITHDRAWN", "stopped_early"),
        ("TERMINATED", "RECRUITING", "restarted_after_stopping"),
    ],
)
def test_transitions_land_in_the_bucket_that_matches_their_meaning(old, new, kind):
    assert transition_kind(old, new)[0] == kind


def test_a_status_nobody_has_classified_stays_visible_under_its_own_words():
    """Same reasoning as amendments.field_aspect returning None: a value
    CT.gov starts reporting must not be filed under a bucket that implies
    somebody understood it."""
    kind, label = transition_kind("RECRUITING", "SOME_NEW_STATUS")
    assert kind == TRANSITION_OTHER
    assert label == "RECRUITING to SOME_NEW_STATUS"


@pytest.mark.parametrize(
    "old, new", [("RECRUITING", "RECRUITING"), (None, "RECRUITING"), ("RECRUITING", "")]
)
def test_a_non_transition_is_not_a_transition(old, new):
    assert transition_kind(old, new) is None


def test_anomalies_sort_first_even_when_they_are_the_rarest_thing_in_the_window():
    rows = [row("overall_status", "RECRUITING", "COMPLETED", nct_id=f"NCT{i}") for i in range(21)]
    rows.append(row("overall_status", "COMPLETED", "RECRUITING", nct_id="NCTODD"))
    findings = analyse_status_moves(rows)

    assert findings[0].kind == "reopened_after_finishing"
    assert findings[0].count == 1 and findings[0].anomaly is True
    assert findings[1].kind == "finished"
    assert findings[1].count == 21 and findings[1].anomaly is False


def test_status_findings_name_trials_but_report_the_full_count():
    rows = [row("overall_status", "RECRUITING", "COMPLETED", nct_id=f"NCT{i}") for i in range(30)]
    (finding,) = analyse_status_moves(rows)
    assert finding.count == 30
    assert len(finding.trials) == 8  # NAMED_CAP — a reading list, not a result set


# ============================================================================
# Enrollment
# ============================================================================


def test_a_target_that_became_an_actual_carries_both_numbers():
    """NCT03402139, 31 August: a target of 400 replaced by a real count of
    163. The most consequential number the window produces."""
    at = T0
    rows = [
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT03402139", at=at),
        row("enrollment_count", "400", "163", nct_id="NCT03402139", at=at),
    ]
    finding = analyse_enrollment(rows)
    (move,) = finding.became_actual
    assert (move.count_before, move.count_after) == (400, 163)
    assert move.count_moved is True
    assert finding.under_target == 1
    # The count row was told as part of the switch, not a second time as a
    # revised target.
    assert finding.target_raised_total == finding.target_lowered_total == 0


def test_a_switch_with_no_count_move_states_the_unchanged_number():
    """8 of 20 switches in the first eight days had no count row. The
    trial enrolled exactly its target, and that is something the record
    states — not a blank."""
    rows = [row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT7")]
    (move,) = analyse_enrollment(rows, {"NCT7": 200}).became_actual
    assert (move.count_before, move.count_after) == (200, 200)
    assert move.count_moved is False
    assert move.later_count_change is False


def test_todays_count_is_refused_when_something_moved_it_after_the_switch():
    """The guard the live data cannot exercise (see this file's docstring).

    Attributing today's headcount to an older amendment would state a fact
    about the trial that was not true when it happened — the same reasoning
    written into amendments.enrollment_context.
    """
    later = T0 + timedelta(days=3)
    rows = [
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT8", at=T0),
        row("enrollment_count", "50", "80", nct_id="NCT8", at=later),
    ]
    finding = analyse_enrollment(rows, {"NCT8": 80})
    (move,) = finding.became_actual
    assert move.count_before is None and move.count_after is None
    assert move.later_count_change is True
    assert move.count_moved is False
    # The later count move is still reported — as a revised target, which
    # is what it was.
    assert finding.target_raised_total == 1


def test_actual_reverting_to_estimated_is_surfaced_not_dropped():
    """NCT06904365: a real headcount reverting to a plan. Backwards, and
    the same trial that reopened after being marked complete."""
    at = T0
    rows = [
        row("enrollment_type", "ACTUAL", "ESTIMATED", nct_id="NCT06904365", at=at),
        row("enrollment_count", "10", "11", nct_id="NCT06904365", at=at),
    ]
    finding = analyse_enrollment(rows)
    assert finding.became_actual_total == 0
    (move,) = finding.switched_back
    assert (move.old_type, move.new_type) == ("ACTUAL", "ESTIMATED")
    assert (move.count_before, move.count_after) == (10, 11)


def test_a_revised_target_is_not_an_enrolled_headcount():
    """A trial raising its plan from 150 to 350 has not enrolled anybody."""
    finding = analyse_enrollment([row("enrollment_count", "150", "350", nct_id="NCT9")])
    assert finding.became_actual_total == 0
    assert finding.target_raised_total == 1
    (move,) = finding.target_raised
    assert (move.count_before, move.count_after) == (150, 350)
    assert move.old_type is None  # nothing switched; the plan just changed


def test_revised_targets_split_by_direction():
    rows = [
        row("enrollment_count", "150", "350", nct_id="NCT1"),
        row("enrollment_count", "55", "31", nct_id="NCT2"),
    ]
    finding = analyse_enrollment(rows)
    assert finding.target_raised_total == 1
    assert finding.target_lowered_total == 1


@pytest.mark.parametrize("old, new", [("100", "100"), ("junk", "100"), ("100", None)])
def test_a_count_that_did_not_really_move_is_not_a_revision(old, new):
    finding = analyse_enrollment([row("enrollment_count", old, new)])
    assert finding.target_raised_total == finding.target_lowered_total == 0


def test_under_target_counts_only_switches_with_two_real_numbers():
    at = T0
    rows = [
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT1", at=at),
        row("enrollment_count", "400", "163", nct_id="NCT1", at=at),
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT2", at=at),
        row("enrollment_count", "100", "120", nct_id="NCT2", at=at),
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT3", at=at),  # no numbers
    ]
    finding = analyse_enrollment(rows)
    assert finding.became_actual_total == 3
    assert finding.under_target == 1


def test_an_observational_study_is_counted_but_not_compared():
    """A real 2026 record: NCT07627074 enrolled 237,211 of a stated 35,000
    "target" — an observational study pulling from existing records, not
    a trial recruiting patients. The 85%-of-target accrual benchmark the
    enrollment chart cites is about interventional-trial recruitment, so
    an observational switch must still count in the total (nothing here
    got dropped) but must not enter `became_actual`, the list the chart
    and its benchmark are built from. Reported from real use, 2026-09-05."""
    at = T0
    rows = [
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT_OBS", at=at,
            study_type="OBSERVATIONAL"),
        row("enrollment_count", "35000", "237211", nct_id="NCT_OBS", at=at),
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT_RCT", at=at,
            study_type="INTERVENTIONAL"),
        row("enrollment_count", "400", "163", nct_id="NCT_RCT", at=at),
    ]
    finding = analyse_enrollment(rows)
    assert finding.became_actual_total == 2, "the observational switch still counts"
    assert finding.became_actual_observational_total == 1
    (move,) = finding.became_actual
    assert move.nct_id == "NCT_RCT", "the observational trial must not reach the chart's list"


def test_a_missing_study_type_is_treated_as_comparable():
    """Blacklisting OBSERVATIONAL, rather than whitelisting INTERVENTIONAL,
    so a row with no study_type on file still reaches the chart instead of
    being assumed incomparable by default."""
    rows = [
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT_UNKNOWN", at=T0),
        row("enrollment_count", "400", "163", nct_id="NCT_UNKNOWN", at=T0),
    ]
    finding = analyse_enrollment(rows)
    assert finding.became_actual_observational_total == 0
    assert len(finding.became_actual) == 1


def test_the_same_amendment_pairs_by_exact_timestamp_not_by_trial_alone():
    """Two amendments to one trial must not borrow each other's numbers.

    Rows of one amendment share an EXACT detected_at because Postgres
    now() is transaction-start time — the grouping key verified in
    api/studies.get_study_amendments.
    """
    other_day = T0 + timedelta(days=2)
    rows = [
        row("enrollment_type", "ESTIMATED", "ACTUAL", nct_id="NCT1", at=T0),
        row("enrollment_count", "400", "163", nct_id="NCT1", at=other_day),
    ]
    (move,) = analyse_enrollment(rows, {"NCT1": 163}).became_actual
    assert move.count_moved is False
    assert move.later_count_change is True


# ============================================================================
# Scope departures
# ============================================================================


def test_only_departures_count_not_arrivals():
    rows = [
        row("active_in_scope", "true", "false", nct_id="NCT1", overall_status="COMPLETED",
            last_update_post_date=None),
        row("active_in_scope", "false", "true", nct_id="NCT2", overall_status="RECRUITING",
            last_update_post_date=None),
    ]
    exits = analyse_scope_exits(rows)
    assert [e.nct_id for e in exits] == ["NCT1"]


def test_an_unexplained_departure_stays_unexplained():
    """drop_reason returns None when the stored data doesn't explain it,
    and None must survive to the UI as "we can't tell" rather than being
    filled with a plausible guess (sec. 2)."""
    (exit_,) = analyse_scope_exits(
        [row("active_in_scope", "true", "false", overall_status=None, last_update_post_date=None)]
    )
    assert exit_.reason is None


# ============================================================================
# Primary-outcome changes
# ============================================================================
#
# The finding that must never over-claim. Everything below exists to keep
# a reformatted endpoint from being reported as a changed one, because on
# a finding phrased around research integrity a false positive is the
# expensive kind of wrong (CLAUDE.md sec. 2).

import json

from api.investigate import (
    analyse_outcome_changes,
    normalise_measure,
    outcome_flags,
    outcome_measures,
)


def outcomes(*measures):
    return json.dumps([{"measure": m, "time_frame": "x"} for m in measures])


def outcome_row(old, new, nct_id="NCT1", at=T0, interpretation=None):
    r = row("primary_outcomes", old, new, nct_id=nct_id, at=at)
    r["prose_interpretation"] = interpretation
    return r


@pytest.mark.parametrize(
    "a, b",
    [
        # Real pair from the record: NCT03674567 changed capitalisation only,
        # on a trial with results posted and past primary completion — the
        # strongest flag combination available, and not a switch.
        ("Safety and tolerability of FLX475", "Safety and Tolerability of FLX475"),
        # Real pair: NCT05327608 renumbered its only outcome. Punctuation
        # stripping alone leaves the bare "1" and reports a false change.
        ("1. Proportion of patients who adhere", "Proportion of patients who adhere"),
        ("2) Overall survival", "Overall survival"),
        ("• Adverse events", "Adverse events"),
        ("Overall Response Rate (ORR)", "Overall response rate  ORR"),
    ],
)
def test_renaming_is_not_changing(a, b):
    assert normalise_measure(a) == normalise_measure(b)


@pytest.mark.parametrize(
    "a, b",
    [
        # A number that is part of the endpoint, not a list marker.
        ("30 day mortality", "60 day mortality"),
        ("6-minute walk distance", "12-minute walk distance"),
        ("Progression-free survival", "Overall survival"),
    ],
)
def test_genuinely_different_endpoints_stay_different(a, b):
    assert normalise_measure(a) != normalise_measure(b)


def test_a_measure_beginning_with_a_number_is_not_treated_as_a_list_item():
    """The list-marker rule requires "." or ")" AND whitespace, so real
    endpoints starting with a figure survive it intact."""
    assert normalise_measure("6-minute walk distance") == "6 minute walk distance"
    assert normalise_measure("30 day mortality") == "30 day mortality"


def test_outcome_measures_reads_the_stored_shape():
    assert outcome_measures(outcomes("A", "B")) == ["A", "B"]
    assert outcome_measures([{"measure": "A"}]) == ["A"]


@pytest.mark.parametrize("bad", [None, "not json", '{"not": "a list"}', "42"])
def test_an_unreadable_outcome_value_is_not_an_empty_list(bad):
    """An unreadable side silently becoming [] would report every measure
    as removed — the loudest possible false alarm."""
    assert outcome_measures(bad) is None


def test_unreadable_rows_are_counted_not_dropped():
    _, summary = analyse_outcome_changes([outcome_row("junk", outcomes("A"))])
    assert summary == {
        "total": 0,
        "wording_only": 0,
        "substantive": 0,
        "after_primary_completion": 0,
        "unreadable": 1,
    }


def test_a_capitalisation_change_is_wording_not_a_switch():
    changes, summary = analyse_outcome_changes(
        [outcome_row(outcomes("Safety and tolerability"), outcomes("Safety and Tolerability"))]
    )
    (change,) = changes
    assert change.wording_only is True
    assert change.measures_added == [] and change.measures_removed == []
    assert summary["substantive"] == 0 and summary["wording_only"] == 1


def test_a_dropped_endpoint_is_substantive_and_names_what_went():
    changes, summary = analyse_outcome_changes(
        [outcome_row(outcomes("Overall survival", "Adverse events"), outcomes("Adverse events"))]
    )
    (change,) = changes
    assert change.wording_only is False
    assert change.measures_removed == ["Overall survival"]
    assert change.measures_added == []
    assert (change.count_before, change.count_after) == (2, 1)
    assert summary["substantive"] == 1


def test_the_evidence_is_the_registry_wording_not_the_normalised_form():
    """sec. 3: a reader judges relevance from the source text. Storing the
    casefolded key would show them something the registry never wrote."""
    (change,), _ = analyse_outcome_changes(
        [outcome_row(outcomes("Overall Survival (OS)"), outcomes("Adverse Events"))]
    )
    assert change.measures_removed == ["Overall Survival (OS)"]
    assert change.measures_added == ["Adverse Events"]


# ---- flags ----------------------------------------------------------------

AFTER = {"primary_completion_date": "2026-01-31", "start_date": "2025-01-01"}


def test_a_change_after_primary_completion_is_flagged():
    assert "after_primary_completion" in outcome_flags(T0, AFTER)


def test_a_change_before_primary_completion_is_not():
    """Before that date nobody has seen the endpoint data, so a change is
    ordinary protocol maintenance and must not be flagged as anything."""
    facts = {"primary_completion_date": "2027-12-31", "start_date": "2025-01-01"}
    flags = outcome_flags(T0, facts)
    assert "after_primary_completion" not in flags
    assert flags == ["after_start"]


def test_a_missing_milestone_yields_no_flag_rather_than_a_default():
    """"The registry did not say when this trial finishes" is not evidence
    of anything. Treating NULL as "before" would flag every trial with an
    unstated date."""
    assert outcome_flags(T0, {"primary_completion_date": None, "start_date": None}) == []
    assert outcome_flags(T0, None) == []


def test_a_month_precision_milestone_is_only_passed_once_the_month_is_over():
    """Anchoring "2026-09" to the 1st and comparing directly would flag a
    change made mid-September as "after completion"."""
    same_month = {"primary_completion_date": "2026-09"}
    assert outcome_flags(T0, same_month) == []  # T0 is 2026-09-01
    assert "after_primary_completion" in outcome_flags(T0, {"primary_completion_date": "2026-08"})


def test_industry_and_results_flags_come_from_stated_fields():
    flags = outcome_flags(T0, {"has_results": True, "org_class": "INDUSTRY"})
    assert flags == ["results_posted", "industry_sponsored"]


def test_flags_are_listed_never_summed_into_a_score():
    """sec. 3 forbids a ranking whose reasoning is invisible, which is what
    step 7 was removed for. The reader sees the facts, not a number."""
    (change,), _ = analyse_outcome_changes(
        [outcome_row(outcomes("A"), outcomes("B"))],
        {"NCT1": {**AFTER, "has_results": True, "org_class": "INDUSTRY"}},
    )
    assert change.flags == [
        "after_primary_completion",
        "results_posted",
        "after_start",
        "industry_sponsored",
    ]
    assert change.flag_labels[0] == "changed after the trial's primary completion date"
    assert not hasattr(change, "score")
    assert not hasattr(change, "confidence")


def test_substantive_changes_sort_above_wording_ones():
    rows = [
        outcome_row(outcomes("Safety"), outcomes("safety"), nct_id="NCTWORD"),
        outcome_row(outcomes("A"), outcomes("B"), nct_id="NCTREAL"),
    ]
    changes, _ = analyse_outcome_changes(rows, {"NCTREAL": AFTER})
    assert [c.nct_id for c in changes] == ["NCTREAL", "NCTWORD"]


def test_after_completion_count_ignores_wording_changes():
    """A reformatted endpoint on a finished trial is not an outcome change
    after completion, and counting it as one would be the accusation this
    module exists to avoid."""
    rows = [outcome_row(outcomes("Safety and tolerability"), outcomes("Safety and Tolerability"))]
    _, summary = analyse_outcome_changes(rows, {"NCT1": {**AFTER, "has_results": True}})
    assert summary["after_primary_completion"] == 0
    assert summary["wording_only"] == 1


def test_the_stored_model_reading_travels_with_the_change():
    (change,), _ = analyse_outcome_changes(
        [outcome_row(outcomes("A"), outcomes("B"), interpretation={"summary": "the endpoint moved"})]
    )
    assert change.interpretation == "the endpoint moved"


def test_no_stored_reading_is_none_not_a_reassuring_sentence():
    """Absence means three things the column cannot separate — the row
    predates 2026-09-03, the model said MEANINGFUL: no, or it was never
    selected. None must reach the UI so it can say which it cannot tell."""
    (change,), _ = analyse_outcome_changes([outcome_row(outcomes("A"), outcomes("B"))])
    assert change.interpretation is None


def test_a_finding_carries_the_literal_transitions_inside_it():
    """Bucket names are an abstraction; the chart draws the raw movements.
    They must be complete — a capped list would silently drop one."""
    rows = [row("overall_status", "RECRUITING", "COMPLETED", nct_id=f"NCT{i}")
            for i in range(11)]
    rows += [row("overall_status", "ACTIVE_NOT_RECRUITING", "COMPLETED",
                 nct_id=f"NCTB{i}") for i in range(7)]
    (finding,) = analyse_status_moves(rows)

    assert finding.count == 18
    assert [(t.old_value, t.new_value, t.count) for t in finding.transitions] == [
        ("RECRUITING", "COMPLETED", 11),
        ("ACTIVE_NOT_RECRUITING", "COMPLETED", 7),
    ]
    # Every trial is accounted for by the transitions, not just by the total.
    assert sum(t.count for t in finding.transitions) == finding.count


def test_transitions_are_not_capped_by_the_named_trial_list():
    """`trials` is a reading list capped at 8; `transitions` is the chart's
    data and must cover all of them."""
    rows = [row("overall_status", "RECRUITING", "COMPLETED", nct_id=f"NCT{i}")
            for i in range(30)]
    (finding,) = analyse_status_moves(rows)
    assert len(finding.trials) == 8
    assert sum(t.count for t in finding.transitions) == 30
