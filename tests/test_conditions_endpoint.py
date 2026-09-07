"""GET/POST /tracked-conditions — the real registry, over HTTP.

Step 10 (2026-09-05): replaces config/tracked_conditions.json. GET lists
what Monitor watches; POST is the one write this table needs so a
condition can be added through the UI instead of a file edit + redeploy.

Free: the fake connection ignores SQL (tests/conftest.py) — this covers
routing, request/response validation, and the add/dedup logic, not
whether the SQL is correct against real Postgres.
"""


class TestListingTrackedConditions:
    def test_returns_the_conditions_alphabetically_as_a_plain_list(self, api):
        body = api([[["breast cancer"], ["obesity"]]]).get("/tracked-conditions").json()
        assert body == ["breast cancer", "obesity"]


class TestAddingATrackedCondition:
    def test_a_new_condition_is_added_and_echoed_back(self, api):
        response = api([[]]).post(
            "/tracked-conditions", json={"condition": "sarcoidosis"}
        )
        assert response.status_code == 201
        assert response.json() == {"condition": "sarcoidosis"}

    def test_an_already_tracked_condition_is_rejected_not_duplicated(self, api):
        """A case-insensitive match — 'Sarcoidosis' must collide with an
        existing 'sarcoidosis' row, not silently create a second one."""
        response = api([[[1]]]).post(
            "/tracked-conditions", json={"condition": "Sarcoidosis"}
        )
        assert response.status_code == 409
        assert "already tracked" in response.json()["detail"]

    def test_blank_condition_is_rejected(self, api):
        response = api([[]]).post("/tracked-conditions", json={"condition": "   "})
        assert response.status_code == 400

    def test_condition_field_is_required(self, api):
        assert api([[]]).post("/tracked-conditions", json={}).status_code == 422


class TestRemovingATrackedCondition:
    """DELETE /tracked-conditions/{condition} (2026-09-08).

    Untrack, never delete: the trials only this condition brought in get
    active_in_scope = false and a logged flip, and their history stays. The
    interesting parts are the two refusals and the arithmetic — a trial that
    another watched condition also brings in must NOT stop being watched.

    Query order the fake is fed against: stored spelling, registry count,
    "any attribution at all", the untrack list, the kept count, the
    unattributed count.
    """

    @staticmethod
    def results(stored="obesity", registry=2, attributed=True, untrack=(), kept=0, unattributed=0):
        return [
            [[stored]],
            [[registry]],
            [[attributed]],
            [[nct] for nct in untrack],
            [[kept]],
            [[unattributed]],
        ]

    def test_it_untracks_only_the_trials_nothing_else_brings_in(self, api):
        response = api(
            self.results(untrack=("NCT01", "NCT02"), kept=14, unattributed=0)
        ).delete("/tracked-conditions/obesity")
        assert response.status_code == 200
        assert response.json() == {
            "condition": "obesity",
            "trials_untracked": 2,
            "trials_kept_for_another_condition": 14,
            "trials_unattributed": 0,
        }

    def test_it_logs_the_flip_as_a_tracking_change(self, api):
        """The same field, values and reader as a scope drop from the
        scheduled run — otherwise a trial leaves the watch with no record
        that it did."""
        seen = []
        api(self.results(untrack=("NCT01",)), keep=seen).delete("/tracked-conditions/obesity")
        sql = " ".join(s for s, _ in seen[0].cursor_obj.executed)
        assert "study_changes" in sql
        assert "active_in_scope = false" in sql

    def test_it_writes_no_change_row_when_nothing_is_untracked(self, api):
        """Every trial also matched another watched condition. A change row
        here would be a false statement: nothing stopped being watched."""
        seen = []
        api(self.results(untrack=(), kept=31), keep=seen).delete("/tracked-conditions/obesity")
        sql = " ".join(s for s, _ in seen[0].cursor_obj.executed)
        assert "study_changes" not in sql

    def test_it_echoes_the_stored_spelling_not_the_url(self, api):
        """POST matches case-insensitively, so 'Obesity' addresses the
        'obesity' row — and the answer must name the row, not the request."""
        body = api(self.results(stored="obesity")).delete("/tracked-conditions/Obesity").json()
        assert body["condition"] == "obesity"

    def test_a_condition_containing_a_slash_still_addresses_its_row(self, api):
        """'Obesity/Overweight' is a real CT.gov string; the path converter
        exists so it does not 404 on its own name."""
        response = api(self.results(stored="Obesity/Overweight")).delete(
            "/tracked-conditions/Obesity/Overweight"
        )
        assert response.status_code == 200
        assert response.json()["condition"] == "Obesity/Overweight"

    def test_an_untracked_condition_is_404_not_a_silent_success(self, api):
        response = api([[]]).delete("/tracked-conditions/sarcoidosis")
        assert response.status_code == 404
        assert "not tracked" in response.json()["detail"]

    def test_the_last_condition_cannot_be_removed(self, api):
        """An empty registry is a monitor that watches nothing while still
        reporting a healthy watch — the state /ops/status raises
        no_tracked_conditions for. Not available in one click."""
        response = api([[["obesity"]], [[1]]]).delete("/tracked-conditions/obesity")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "only condition" in detail
        assert "Add the replacement" in detail

    def test_removal_is_refused_before_any_attribution_exists(self, api):
        """Without a record of which trials a condition brought in, removing
        it strands them: active_in_scope = true, counted in the watch
        headline, with no query left that returns them."""
        response = api([[["obesity"]], [[2]], [[False]]]).delete("/tracked-conditions/obesity")
        assert response.status_code == 409
        assert "no monitor run has recorded" in response.json()["detail"]

    def test_a_blank_condition_is_rejected(self, api):
        response = api([[]]).delete("/tracked-conditions/%20")
        assert response.status_code == 400

    def test_it_reports_trials_no_watched_condition_accounts_for(self, api):
        """Evidence about the record itself: a non-zero count here says the
        attribution is incomplete and the answer above it is narrower than it
        looks. Reported rather than hidden (sec. 3)."""
        body = api(self.results(untrack=("NCT01",), unattributed=2173)).delete(
            "/tracked-conditions/obesity"
        ).json()
        assert body["trials_unattributed"] == 2173
