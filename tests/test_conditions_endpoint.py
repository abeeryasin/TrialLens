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
