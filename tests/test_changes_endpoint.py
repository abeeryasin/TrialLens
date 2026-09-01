"""GET /changes and /changes/fields — the Monitor feed's API, over HTTP.

Untested until 2026-09-02. This is the endpoint behind the page a
researcher actually looks at to answer "what happened", and its filters
decide what they are shown — a filter that silently stops applying doesn't
error, it just quietly returns a different, wrong answer.

Free: no database, no network. See tests/conftest.py for why the fake
connection ignores SQL.
"""
from datetime import date, datetime, timezone

from api.tracking import CATEGORY_TRACKING, CATEGORY_TRIAL_CONTENT, TRACKING_FIELDS

WHEN = datetime(2026, 8, 31, 18, 2, 40, tzinfo=timezone.utc)


def feed_row(**overrides):
    row = {
        "nct_id": "NCT02954874",
        "brief_title": "A Real Trial",
        "field_name": "enrollment_count",
        "old_value": "1155",
        "new_value": "1195",
        "detected_at": WHEN,
        "overall_status": "RECRUITING",
        "last_update_post_date": date(2026, 8, 31),
    }
    row.update(overrides)
    return row


# Query order in api/changes.recent_changes: total, distinct_trials, rows.
def results(rows, total=None, distinct=None):
    rows = list(rows)
    return [
        [{"n": total if total is not None else len(rows)}],
        [{"n": distinct if distinct is not None else len({r["nct_id"] for r in rows})}],
        rows,
    ]


class TestTheFeedItself:
    def test_a_change_comes_back_with_its_trial_and_category(self, api):
        body = api(results([feed_row()])).get("/changes").json()
        assert body["total"] == 1
        assert body["distinct_trials"] == 1
        entry = body["results"][0]
        assert entry["nct_id"] == "NCT02954874"
        assert entry["brief_title"] == "A Real Trial"
        assert entry["category"] == CATEGORY_TRIAL_CONTENT

    def test_total_is_the_count_query_not_the_page_length(self, api):
        """Paging depends on this. If total ever became len(results), the UI
        would say "1 change" on a feed with 500 and stop offering page 2."""
        body = api(results([feed_row()], total=498, distinct=262)).get("/changes").json()
        assert body["total"] == 498
        assert body["distinct_trials"] == 262
        assert len(body["results"]) == 1

    def test_tracking_fields_are_categorised_apart_from_trial_content(self, api):
        """Whether WE are still watching a trial is not something the
        sponsor did. Merging the two would present our own bookkeeping as a
        change to the study."""
        row = feed_row(field_name="active_in_scope", old_value="true", new_value="false")
        entry = api(results([row])).get("/changes").json()["results"][0]
        assert entry["category"] == CATEGORY_TRACKING


class TestTheDropExplanation:
    def test_a_dropped_trial_carries_an_explanation_when_one_is_honest(self, api):
        """api/tracking.drop_reason explains a drop from stored facts."""
        row = feed_row(
            field_name="active_in_scope", old_value="true", new_value="false",
            overall_status="COMPLETED", last_update_post_date=date(2020, 1, 1),
        )
        entry = api(results([row])).get("/changes").json()["results"][0]
        assert entry["tracking_note"], "a long-completed trial's drop is explainable"
        assert "completed" in entry["tracking_note"].lower()

    def test_an_unexplainable_drop_gets_no_note_rather_than_a_guess(self, api):
        """A trial that is still recruiting should not have dropped. The
        honest answer is "we can't tell from what we stored" — sec. 2
        forbids inventing one, and None is what the UI renders as silence."""
        row = feed_row(
            field_name="active_in_scope", old_value="true", new_value="false",
            overall_status="RECRUITING", last_update_post_date=date(2026, 8, 31),
        )
        entry = api(results([row])).get("/changes").json()["results"][0]
        assert entry["tracking_note"] is None

    def test_an_ordinary_change_never_carries_a_drop_note(self, api):
        entry = api(results([feed_row()])).get("/changes").json()["results"][0]
        assert entry["tracking_note"] is None


class TestFiltersReachTheDatabase:
    """Each filter must end up in the SQL parameters.

    A filter quietly dropped from the query returns MORE rows than asked
    for, which looks like data rather than a bug — nothing errors and the
    page renders fine.
    """

    def _params_for(self, api, query):
        holder = []
        api(results([feed_row()]), keep=holder).get(f"/changes{query}")
        return [p for _, p in holder[0].cursor_obj.executed if p]

    def test_condition_filter_is_passed(self, api):
        params = self._params_for(api, "?condition=breast%20cancer")
        assert any("%breast cancer%" in str(p) for p in params)

    def test_field_name_filter_is_passed(self, api):
        params = self._params_for(api, "?field_name=overall_status")
        assert any("overall_status" in str(p) for p in params)

    def test_category_filter_uses_the_shared_tracking_field_list(self, api):
        """Not a hardcoded string — api/tracking.TRACKING_FIELDS is the one
        definition, so the frontend and API cannot disagree about it."""
        params = self._params_for(api, f"?category={CATEGORY_TRACKING}")
        # Each entry is the whole params list for one query, so the shared
        # field list arrives nested inside it.
        assert any(sorted(TRACKING_FIELDS) in p for p in params)

    def test_detected_within_days_is_passed(self, api):
        assert any(7 in p for p in self._params_for(api, "?detected_within_days=7"))

    def test_trial_updated_within_days_is_passed(self, api):
        assert any(30 in p for p in self._params_for(api, "?trial_updated_within_days=30"))

    def test_every_filter_applies_to_the_count_queries_too(self, api):
        """The count and the rows must be filtered identically. If only the
        row query narrowed, the feed would show 3 results and claim 498 —
        and offer 20 empty pages."""
        holder = []
        api(results([feed_row()]), keep=holder).get("/changes?condition=obesity")
        executed = holder[0].cursor_obj.executed
        assert len(executed) == 3, "expected count, distinct-count, then rows"
        assert all("obesity" in str(params) for _, params in executed)


class TestRequestValidation:
    """FastAPI's job, which is exactly why it needs an HTTP-level test."""

    def test_limit_above_the_cap_is_rejected(self, api):
        assert api(results([])).get("/changes?limit=201").status_code == 422

    def test_a_negative_offset_is_rejected(self, api):
        assert api(results([])).get("/changes?offset=-1").status_code == 422

    def test_a_non_numeric_limit_is_rejected(self, api):
        assert api(results([])).get("/changes?limit=all").status_code == 422

    def test_detected_within_days_must_be_at_least_one(self, api):
        assert api(results([])).get("/changes?detected_within_days=0").status_code == 422

    def test_defaults_are_returned_when_nothing_is_passed(self, api):
        body = api(results([feed_row()])).get("/changes").json()
        assert body["limit"] == 50 and body["offset"] == 0


class TestChangedFields:
    def test_each_field_comes_back_with_its_category(self, api):
        rows = [("overall_status",), ("active_in_scope",)]
        body = api([rows]).get("/changes/fields").json()
        by_name = {f["name"]: f["category"] for f in body}
        assert by_name["overall_status"] == CATEGORY_TRIAL_CONTENT
        assert by_name["active_in_scope"] == CATEGORY_TRACKING

    def test_an_empty_database_returns_an_empty_list_not_an_error(self, api):
        assert api([[]]).get("/changes/fields").json() == []
