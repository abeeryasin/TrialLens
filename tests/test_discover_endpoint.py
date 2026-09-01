"""GET /discover — the tracked-vs-live split, over HTTP.

Untested until 2026-09-02, despite already having produced a real,
user-visible bug: on 2026-08-28 an untracked condition with a few
incidental local rows (a comorbid tag on a trial tracked under something
else) was reported as if it were the complete picture. The fix — merge
local and live, tag each result with where it came from — is branch 3
below, and nothing has been holding it in place since.

The three branches answer genuinely different questions, and the `note` on
each is the only thing telling a researcher which one they got. A branch
that silently returns the wrong note is a false claim about completeness
(CLAUDE.md sec. 2), not a cosmetic problem.

Free: the live CT.gov call is stubbed, so no network. See tests/conftest.py.
"""
from datetime import date

import pytest

import api.discover as discover_module

TRACKED = "breast cancer"       # in config/tracked_conditions.json
UNTRACKED = "sarcoidosis"


def local_row(nct_id="NCT00000001", updated=date(2026, 8, 30)):
    return {
        "nct_id": nct_id,
        "brief_title": "A Stored Trial",
        "overall_status": "RECRUITING",
        "phase": "PHASE2",
        "last_update_post_date": updated,
    }


def live_study(nct_id="NCT00000002", updated=date(2026, 9, 1)):
    return {
        "nct_id": nct_id,
        "brief_title": "A Live Trial",
        "overall_status": "RECRUITING",
        "phase": "PHASE3",
        "last_update_post_date": updated,
    }


@pytest.fixture
def stub_live(monkeypatch):
    """Replace the live CT.gov lookup. Returns a recorder so a test can
    assert whether the network would have been touched at all."""
    calls = []

    def _install(studies=None, fail_with=None):
        def fake(condition, limit):
            calls.append((condition, limit))
            if fail_with:
                raise fail_with
            return list(studies or [])
        monkeypatch.setattr(discover_module, "_fetch_live", fake)
        return calls

    return _install


class TestBranchOneNothingStoredLocally:
    def test_an_unknown_condition_is_answered_live_and_says_so(self, api, stub_live):
        stub_live([live_study()])
        body = api([[]]).get(f"/discover?condition={UNTRACKED}").json()

        assert body["total"] == 1
        assert body["results"][0]["source"] == "live"
        assert "don't track this condition" in body["note"]
        assert "won't reflect future changes" in body["note"], (
            "a live result is a snapshot, and the note is the only thing "
            "that tells the researcher it will not be monitored"
        )

    def test_a_failed_live_lookup_is_a_502_not_an_empty_result_list(self, api, stub_live):
        """An empty list would render as "no trials match", which is a claim
        about ClinicalTrials.gov. "We couldn't reach it" is a claim about
        us, and they are not interchangeable."""
        stub_live(fail_with=RuntimeError("connection refused"))
        response = api([[]]).get(f"/discover?condition={UNTRACKED}")
        assert response.status_code == 502
        assert "live" in response.json()["detail"].lower()


class TestBranchTwoAComprehensivelyTrackedCondition:
    def test_a_tracked_condition_answers_locally_and_never_calls_out(self, api, stub_live):
        """The whole point of tracking: our own data IS the current answer,
        so a live call would be latency and load for nothing."""
        calls = stub_live([live_study()])
        body = api([[local_row()]]).get(f"/discover?condition={TRACKED}").json()

        assert calls == [], "a tracked condition must not trigger a live lookup"
        assert body["results"][0]["source"] == "tracked"
        assert "actively track" in body["note"]


class TestBranchThreeIncidentalLocalRows:
    """The branch that exists because of a real bug (2026-08-28)."""

    def test_incidental_local_rows_are_merged_with_live_not_reported_as_complete(
        self, api, stub_live
    ):
        stub_live([live_study()])
        body = api([[local_row()]]).get(f"/discover?condition={UNTRACKED}").json()

        sources = {r["nct_id"]: r["source"] for r in body["results"]}
        assert sources == {"NCT00000001": "tracked", "NCT00000002": "live"}
        assert "may not be complete" in body["note"], (
            "the exact claim the 2026-08-28 bug got wrong"
        )

    def test_a_trial_in_both_places_is_reported_once_as_tracked(self, api, stub_live):
        """Stored wins: we hold its history, and showing it twice would
        double-count the result total."""
        stub_live([live_study(nct_id="NCT00000001")])
        body = api([[local_row(nct_id="NCT00000001")]]).get(
            f"/discover?condition={UNTRACKED}"
        ).json()

        assert body["total"] == 1
        assert body["results"][0]["source"] == "tracked"

    def test_merged_results_are_newest_first(self, api, stub_live):
        stub_live([live_study(nct_id="NEW", updated=date(2026, 9, 1))])
        body = api([[local_row(nct_id="OLD", updated=date(2020, 1, 1))]]).get(
            f"/discover?condition={UNTRACKED}"
        ).json()
        assert [r["nct_id"] for r in body["results"]] == ["NEW", "OLD"]

    def test_a_failed_live_lookup_degrades_to_local_and_warns_it_is_incomplete(
        self, api, stub_live
    ):
        """Unlike branch 1, there IS something to show — so showing it beats
        a 502. But it must not be presented as the whole picture."""
        stub_live(fail_with=RuntimeError("timeout"))
        response = api([[local_row()]]).get(f"/discover?condition={UNTRACKED}")

        assert response.status_code == 200
        body = response.json()
        assert body["results"][0]["source"] == "tracked"
        assert "just failed" in body["note"]
        assert "possibly incomplete" in body["note"]


class TestRequestValidation:
    def test_condition_is_required(self, api):
        assert api([[]]).get("/discover").status_code == 422

    def test_limit_above_the_cap_is_rejected(self, api):
        assert api([[]]).get("/discover?condition=x&limit=101").status_code == 422

    def test_limit_reaches_the_query(self, api, stub_live):
        holder = []
        stub_live([])
        api([[local_row()]], keep=holder).get(f"/discover?condition={TRACKED}&limit=7")
        assert any(7 in params for _, params in holder[0].cursor_obj.executed if params)


class TestEveryBranchSaysWhichItIs:
    def test_no_two_branches_share_a_note(self, api, stub_live):
        """The note is the researcher's only signal of how complete the
        answer is. Two branches with the same wording would make a live
        snapshot indistinguishable from monitored data."""
        stub_live([live_study()])
        untracked_live = api([[]]).get(f"/discover?condition={UNTRACKED}").json()["note"]

        stub_live([live_study()])
        tracked = api([[local_row()]]).get(f"/discover?condition={TRACKED}").json()["note"]

        stub_live([live_study()])
        merged = api([[local_row()]]).get(f"/discover?condition={UNTRACKED}").json()["note"]

        assert len({untracked_live, tracked, merged}) == 3
        assert all(note.strip() for note in (untracked_live, tracked, merged))
