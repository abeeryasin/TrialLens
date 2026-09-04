"""frontend/pages/5_Investigate.py — what a researcher actually sees.

AppTest runs the real script and returns its element tree, so these assert
the rendered page rather than the code's intent. The API is stubbed;
GET /investigate and /investigate/landscape have their own tests.

Every state below is one the page reaches with real data, and most are
invisible while developing against a busy window:

  - **A quiet window.** Real: 2026-08-29 and 08-30 had zero amendments
    between them. Silence must read as a finding, not a broken query — the
    same rule Home's quiet week was rebuilt around.
  - **A window longer than the record.** The record begins 2026-08-28, so
    every 90-day view is mostly days nobody was watching. Reporting those
    as quiet is the step-4 under-reporting bug wearing a new hat.
  - **An outcome change that is only reformatting.** 9 of 17 in the live
    record. The page must never let one of these reach the reader as a
    changed endpoint, because this finding is phrased around research
    integrity and a false positive is the expensive kind of wrong.
  - **An outcome change with no stored AI reading.** The common case, and
    absence means three different things the column cannot separate — so
    it must never render as "nothing important changed".
  - **A phase chart missing half its trials.** 52% of breast-cancer trials
    state NA or nothing, and a chart that drops them silently describes a
    tidier field than the one that exists.

Free: no database, no network, no model.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_investigate_page.py -v
"""
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit not installed"
).AppTest

PAGE = str(FRONTEND / "pages" / "5_Investigate.py")


def window(**overrides):
    body = {
        "days": 14, "since": "2026-08-21T00:00:00Z", "until": "2026-09-04T00:00:00Z",
        "recording_since": "2026-08-28T12:55:52Z", "covers_full_window": True,
        "condition": None, "trials_tracked": 11444, "trials_changed": 286,
        "amendments": 355, "field_changes": 456,
    }
    body.update(overrides)
    return body


def outcome(**overrides):
    body = {
        "nct_id": "NCT04276493", "brief_title": "A real trial",
        "measures_added": ["Adverse Events and Serious Adverse Events"],
        "measures_removed": ["Adverse Events"],
        "count_before": 3, "count_after": 2, "wording_only": False,
        "flags": [], "flag_labels": [], "interpretation": None,
        "detected_at": "2026-09-02T20:10:24Z",
    }
    body.update(overrides)
    return body


def investigate(**overrides):
    body = {
        "window": window(),
        "dates": [], "lifecycle": [],
        "enrollment": {
            "became_actual": [], "became_actual_total": 0, "under_target": 0,
            "switched_back": [], "switched_back_total": 0,
            "target_raised": [], "target_raised_total": 0,
            "target_lowered": [], "target_lowered_total": 0,
        },
        "outcomes": {
            "changes": [], "total": 0, "substantive": 0, "wording_only": 0,
            "after_primary_completion": 0, "unreadable": 0,
        },
        "scope_exits": [], "scope_exits_total": 0,
    }
    body.update(overrides)
    return body


def landscape(**overrides):
    body = {
        "condition": None, "trials": 5377,
        "started_per_year": [
            {"label": "2025", "count": 899, "note": None},
            {"label": "2026", "count": 756, "note": "part year so far"},
            {"label": "2027", "count": 18, "note": "planned start"},
        ],
        "phases": {
            "buckets": [{"label": "PHASE2", "count": 1099, "note": None}],
            "stated": 2539, "unstated": 2838,
            "unstated_label": "no phase stated, or not a phased study",
        },
        "statuses": {
            "buckets": [{"label": "RECRUITING", "count": 2053, "note": None}],
            "stated": 2053, "unstated": 0, "unstated_label": None,
        },
        "enrollment_bands": [{"label": "1-49", "count": 1536, "note": None}],
        "enrollment_stated": 5375,
        "interventions": [{"name": "Paclitaxel", "type": "DRUG", "trials": 163}],
        "interventions_denominator": 4938,
        "sponsors": [{"name": "Fudan University", "trials": 138}],
        "results_posted": 532,
    }
    body.update(overrides)
    return body


@pytest.fixture
def render(monkeypatch):
    """Run the page against a stubbed API and return everything it says."""
    import api_client

    def _render(changed=None, field=None, conditions=("Breast Cancer", "Obesity")):
        bodies = {
            "/tracked-conditions": list(conditions),
            "/investigate": changed if changed is not None else investigate(),
            "/investigate/landscape": field if field is not None else landscape(),
        }

        def fake_get(path, params=None):
            return bodies[path]

        monkeypatch.setattr(api_client, "get", fake_get)

        app = AppTest.from_file(PAGE, default_timeout=60)
        app.run()
        assert not app.exception, [e.value for e in app.exception]

        seen = []
        for kind in (
            "title", "header", "subheader", "markdown", "caption",
            "info", "warning", "error", "success", "metric", "expander", "tabs",
        ):
            try:
                elements = getattr(app, kind)
            except (AttributeError, KeyError):
                continue
            for element in elements:
                # st.metric carries its heading on .label and its figure on
                # .value — read both or half the page is invisible here.
                for attr in ("label", "value"):
                    text = getattr(element, attr, None)
                    if isinstance(text, str):
                        seen.append(text)
        return "\n".join(seen), app

    return _render


class TestDenominators:
    def test_the_header_states_what_every_number_is_measured_against(self, render):
        page, _ = render()
        assert "355 amendments" in page
        assert "286 trials" in page
        assert "456 individual field changes" in page
        assert "11,444 trials" in page

    def test_a_quiet_window_is_a_finding_not_a_blank_page(self, render):
        """Real: 2026-08-29 and 08-30 had zero amendments between them."""
        page, _ = render(investigate(window=window(amendments=0, trials_changed=0,
                                                  field_changes=0)))
        assert "Nothing was amended in this window" in page
        assert "That is a finding, not a" in page

    def test_a_window_reaching_past_the_record_says_it_is_not_covered(self, render):
        """82 of 90 days nobody was watching must not read as 82 quiet days."""
        page, _ = render(investigate(window=window(days=90, covers_full_window=False)))
        assert "The change record begins" in page
        assert "2026-08-28" in page
        assert "not a quiet period" in page

    def test_a_covered_window_does_not_warn(self, render):
        page, _ = render()
        assert "not a quiet period" not in page


class TestPrimaryOutcomes:
    def test_a_post_completion_change_asks_for_review_and_does_not_accuse(self, render):
        page, _ = render(investigate(outcomes={
            "changes": [outcome(
                flags=["after_primary_completion", "results_posted"],
                flag_labels=["changed after the trial's primary completion date",
                             "the trial has already posted results"],
            )],
            "total": 1, "substantive": 1, "wording_only": 0,
            "after_primary_completion": 1, "unreadable": 0,
        }))
        assert "Requires review" in page
        assert "the outcome data could already be seen" in page
        # The vocabulary sec. 2 forbids.
        for forbidden in ("outcome switching detected", "misconduct", "fraud",
                          "manipulated", "suspicious"):
            assert forbidden not in page.lower()

    def test_the_page_says_a_change_is_not_a_verdict(self, render):
        page, _ = render(investigate(outcomes={
            "changes": [outcome()], "total": 1, "substantive": 1,
            "wording_only": 0, "after_primary_completion": 0, "unreadable": 0,
        }))
        assert "innocent explanations" in page
        assert "nothing below is" in page

    def test_a_reformatting_change_never_reaches_the_reader_as_a_changed_endpoint(self, render):
        """9 of 17 in the live record are wording. If one rendered as a
        substantive change on a completed trial, the page would have made an
        accusation the record does not support."""
        page, _ = render(investigate(outcomes={
            "changes": [outcome(wording_only=True, measures_added=[], measures_removed=[],
                                flags=["after_primary_completion"],
                                flag_labels=["changed after the trial's primary completion date"])],
            "total": 1, "substantive": 0, "wording_only": 1,
            "after_primary_completion": 0, "unreadable": 0,
        }))
        assert "Requires review" not in page
        assert "No longer listed" not in page

    def test_the_narrowing_is_shown_because_it_is_the_argument(self, render):
        page, _ = render(investigate(outcomes={
            "changes": [outcome()], "total": 17, "substantive": 8,
            "wording_only": 9, "after_primary_completion": 5, "unreadable": 0,
        }))
        assert "Reformatting only" in page
        assert "list numbering removed" in page
        assert "narrowed 17" in page

    def test_a_missing_ai_reading_is_not_reported_as_nothing_important(self, render):
        """Absence means three things the column cannot separate."""
        page, _ = render(investigate(outcomes={
            "changes": [outcome(interpretation=None)], "total": 1, "substantive": 1,
            "wording_only": 0, "after_primary_completion": 0, "unreadable": 0,
        }))
        assert "does not" in page and "unimportant" in page

    def test_a_stored_reading_is_labelled_as_the_model_not_the_registry(self, render):
        page, _ = render(investigate(outcomes={
            "changes": [outcome(interpretation="the endpoint was narrowed")],
            "total": 1, "substantive": 1, "wording_only": 0,
            "after_primary_completion": 0, "unreadable": 0,
        }))
        assert "not from ClinicalTrials.gov" in page
        assert "the endpoint was narrowed" in page

    def test_no_outcome_change_is_stated_in_words(self, render):
        page, _ = render()
        assert "No trial changed a registered primary outcome" in page

    def test_unreadable_values_are_reported(self, render):
        page, _ = render(investigate(outcomes={
            "changes": [], "total": 0, "substantive": 0, "wording_only": 0,
            "after_primary_completion": 0, "unreadable": 2,
        }))
        assert "could not be read" in page
        assert "rather than dropped" in page


class TestTimelines:
    def test_a_benchmark_is_offered_as_context_not_a_like_for_like_claim(self, render):
        page, _ = render(investigate(dates=[{
            "field_name": "primary_completion_date", "label": "Primary completion",
            "pushed": 54, "pulled": 18, "median_push_days": 193, "median_pull_days": 342,
            "imprecise_moves": 19, "precision_only": 1, "no_move": 0, "unreadable": 0,
            "rows_seen": 73, "biggest": [], "biggest_total": 0,
        }]))
        assert "12.2 months" in page
        assert "not a like-for-like comparison" in page
        assert "different denominator" in page

    def test_month_precision_is_disclosed_so_a_median_cannot_pose_as_exact(self, render):
        page, _ = render(investigate(dates=[{
            "field_name": "completion_date", "label": "Study completion",
            "pushed": 45, "pulled": 0, "median_push_days": 157, "median_pull_days": None,
            "imprecise_moves": 16, "precision_only": 0, "no_move": 0, "unreadable": 0,
            "rows_seen": 61, "biggest": [], "biggest_total": 0,
        }]))
        assert "month-precision" in page
        assert "approximate" in page

    def test_no_date_movement_is_stated(self, render):
        page, _ = render()
        assert "No trial moved a start or completion date" in page


class TestEnrollment:
    def test_a_backwards_switch_is_surfaced_not_dropped(self, render):
        page, _ = render(investigate(enrollment={
            "became_actual": [], "became_actual_total": 1, "under_target": 0,
            "switched_back": [{"nct_id": "NCT06904365", "brief_title": "T",
                               "old_type": "ACTUAL", "new_type": "ESTIMATED",
                               "count_before": 10, "count_after": 11,
                               "count_moved": True, "later_count_change": False,
                               "detected_at": "2026-09-02T20:10:24Z"}],
            "switched_back_total": 1, "target_raised": [], "target_raised_total": 0,
            "target_lowered": [], "target_lowered_total": 0,
        }))
        assert "went the other" in page
        assert "NCT06904365" in page

    def test_the_accrual_threshold_is_explained_with_its_source(self, render):
        page, _ = render(investigate(enrollment={
            "became_actual": [{"nct_id": "NCT03402139", "brief_title": "T",
                               "old_type": "ESTIMATED", "new_type": "ACTUAL",
                               "count_before": 400, "count_after": 163,
                               "count_moved": True, "later_count_change": False,
                               "detected_at": "2026-08-31T18:02:47Z"}],
            "became_actual_total": 1, "under_target": 1,
            "switched_back": [], "switched_back_total": 0,
            "target_raised": [], "target_raised_total": 0,
            "target_lowered": [], "target_lowered_total": 0,
        }))
        assert "85% of target" in page
        assert "55% of terminated trials stop for low accrual" in page

    def test_an_unattributable_count_is_declared_not_silently_omitted(self, render):
        page, _ = render(investigate(enrollment={
            "became_actual": [{"nct_id": "NCT8", "brief_title": "T",
                               "old_type": "ESTIMATED", "new_type": "ACTUAL",
                               "count_before": None, "count_after": None,
                               "count_moved": False, "later_count_change": True,
                               "detected_at": "2026-09-02T20:10:24Z"}],
            "became_actual_total": 1, "under_target": 0,
            "switched_back": [], "switched_back_total": 0,
            "target_raised": [], "target_raised_total": 0,
            "target_lowered": [], "target_lowered_total": 0,
        }))
        assert "not plotted" in page
        assert "cannot honestly be" in page


class TestLifecycle:
    def test_an_anomaly_leads_even_at_a_count_of_one(self, render):
        page, _ = render(investigate(lifecycle=[
            {"kind": "reopened_after_finishing",
             "label": "Reopened after being marked complete", "count": 1,
             "anomaly": True, "trials": [{"nct_id": "NCT06904365", "brief_title": "T",
                                          "old_value": "COMPLETED", "new_value": "RECRUITING",
                                          "detected_at": "2026-09-02T20:10:24Z"}]},
            {"kind": "finished", "label": "Finished", "count": 21,
             "anomaly": False, "trials": []},
        ]))
        assert "Reopened after being marked complete" in page
        assert "regardless of how few" in page
        assert "NCT06904365" in page


class TestScopeExits:
    def test_a_departure_is_our_bookkeeping_not_a_sponsor_action(self, render):
        page, _ = render(investigate(
            scope_exits=[{"nct_id": "NCT1", "brief_title": "T",
                          "overall_status": "COMPLETED", "reason": None,
                          "detected_at": "2026-09-02T20:10:24Z"}],
            scope_exits_total=100,
        ))
        assert "Nobody amended these" in page
        assert "not something a sponsor did" in page

    def test_no_departures_means_no_section(self, render):
        page, _ = render()
        assert "Trials that left the watch" not in page


class TestTheField:
    def test_the_unstated_phase_share_is_named_on_the_page(self, render):
        """2,838 of 5,377 are not on the phase chart. A caption that omits
        this describes a tidier field than the one that exists."""
        page, _ = render()
        assert "2,838 of 5,377" in page
        assert "not on this chart" in page
        assert "tidier field than the one that exists" in page

    def test_the_incomplete_year_is_explained_rather_than_drawn_as_a_decline(self, render):
        page, _ = render()
        assert "Faded bars are not comparable" in page
        assert "the current year" in page and "is not over" in page

    def test_intervention_reach_carries_the_right_denominator(self, render):
        """4,938 trials list an intervention, not 5,377. The wrong total
        understates every drug on the chart."""
        page, _ = render()
        assert "4,938 trials that list any intervention" in page
        assert "of 5,377 tracked" in page

    def test_the_enrollment_band_denominator_is_stated(self, render):
        page, _ = render()
        assert "5,375 of 5,377 state an enrollment figure" in page

    def test_sponsors_are_lead_only_and_say_so(self, render):
        page, _ = render()
        assert "Lead sponsors only" in page

    def test_an_empty_area_says_so(self, render):
        page, _ = render(field=landscape(trials=0))
        assert "Nothing tracked in this area yet" in page
