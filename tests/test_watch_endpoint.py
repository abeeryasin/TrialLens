"""GET /watch — the front page's whole argument, over HTTP.

This endpoint decides which of three screens a researcher sees, and two of
its three verdicts are the kind that fail silently:

  - **is_healthy** wrong in one direction shows a confident watch over data
    nobody has refreshed for days; wrong in the other shows "the watch has
    stopped" to someone whose watch is fine. Neither errors.
  - **content_is_visible** false must never render as "no changes". The
    amendment happened; TrialLens just does not store the fields it touched
    (47% of amendments, measured 2026-09-01). Claiming otherwise is a false
    claim about a study fact (CLAUDE.md sec. 2).

Free: no database, no network, no model. The fake connection ignores SQL —
see tests/conftest.py — so what is covered here is routing, the arithmetic
between the query and the response, and the response model. Whether the SQL
is *right* is tests/test_watch_real_data.py's job.
"""
from datetime import date, datetime, timedelta, timezone

from api.amendments import ASPECT_OPERATIONAL, ASPECT_SCIENTIFIC
from api.watch import CHECK_INTERVAL_HOURS, RECORD_DAYS, STALE_AFTER_HOURS

NOW = datetime(2026, 9, 2, 11, 36, 58, tzinfo=timezone.utc)


def studies_row(**overrides):
    row = {
        "trials_watched": 11427,
        "last_checked_at": NOW - timedelta(hours=5, minutes=33),
        "trials_with_results": 1050,
        "completed_with_results": 747,
    }
    row.update(overrides)
    return row


def record_row(**overrides):
    row = {
        "changes_recorded": 498,
        "recording_since": datetime(2026, 8, 28, 12, 55, 52, tzinfo=timezone.utc),
        "amendments_seen": 212,
        "last_amendment_at": datetime(2026, 9, 1, 18, 3, 16, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def quiet_week():
    """Seven days ending today, all zero — the state this screen exists for."""
    return [
        {"day": date(2026, 9, 2) - timedelta(days=n), "amendments": 0}
        for n in reversed(range(RECORD_DAYS))
    ]


def recent_row(**overrides):
    row = {"amendments": 0, "trials": 0, "scientific": 0, "results_posted": 0}
    row.update(overrides)
    return row


def amendment_head(**overrides):
    row = {
        "nct_id": "NCT02954874",
        "brief_title": "A Real Trial",
        "posted_on": "2026-08-31",
        "previously_posted_on": "2026-08-14",
        "detected_at": datetime(2026, 8, 31, 18, 2, 40, tzinfo=timezone.utc),
        "visible_fields": 3,
    }
    row.update(overrides)
    return row


def field_row(**overrides):
    row = {
        "field_name": "completion_date",
        "old_value": "2026-08-31",
        "new_value": "2027-08-27",
        "detected_at": datetime(2026, 8, 31, 18, 2, 40, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


# Query order in api.watch.watch_status: now, studies, record, daily, recent,
# then _latest_amendment's head and its fields.
def results(
    studies=None, record=None, daily=None, recent=None, head=None, fields=(),
    enrollment=None,
):
    queued = [
        [{"now": NOW}],
        [studies if studies is not None else studies_row()],
        [record if record is not None else record_row()],
        list(daily) if daily is not None else quiet_week(),
        [recent if recent is not None else recent_row()],
        [head] if head is not None else [],
    ]
    if head is not None:
        # ...then the amendment's fields, then the enrollment count in force
        # just after it (see _latest_amendment).
        queued.append(list(fields))
        queued.append([{"count_after": enrollment}])
    return queued


class TestIsTheWatchAlive:
    def test_a_recent_check_is_healthy_and_misses_nothing(self, api):
        body = api(results()).get("/watch").json()
        assert body["is_healthy"] is True
        assert body["checks_missed"] == 0
        assert body["hours_since_check"] == 5.55
        assert body["check_interval_hours"] == CHECK_INTERVAL_HOURS

    def test_one_late_run_is_reported_but_does_not_raise_the_alarm(self, api):
        """A single skipped run is a hiccup — GitHub's scheduled workflows
        are explicitly best-effort. Alarming on one would train the reader
        to ignore the alarm, which is the only thing that makes it useless."""
        late = studies_row(last_checked_at=NOW - timedelta(hours=7))
        body = api(results(studies=late)).get("/watch").json()
        assert body["is_healthy"] is True
        assert body["checks_missed"] == 1

    def test_a_long_silence_stops_the_watch(self, api):
        """3 days 4 hours, the case drawn in design/Alarm.dc.html. is_healthy
        false means the alarm REPLACES the page — a stale feed under a small
        warning still reads as current."""
        dead = studies_row(last_checked_at=NOW - timedelta(days=3, hours=4))
        body = api(results(studies=dead)).get("/watch").json()
        assert body["is_healthy"] is False
        assert body["checks_missed"] == 12  # 76h elapsed / 6h slots

    def test_the_alarm_starts_exactly_at_two_missed_intervals(self, api):
        just_inside = studies_row(
            last_checked_at=NOW - timedelta(hours=STALE_AFTER_HOURS, minutes=-1)
        )
        just_outside = studies_row(
            last_checked_at=NOW - timedelta(hours=STALE_AFTER_HOURS, minutes=1)
        )
        assert api(results(studies=just_inside)).get("/watch").json()["is_healthy"] is True
        assert api(results(studies=just_outside)).get("/watch").json()["is_healthy"] is False

    def test_never_having_checked_is_not_healthy(self, api):
        """An empty database has no evidence a check ever ran. Reporting a
        healthy watch it cannot see is the exact failure this endpoint is
        written to avoid — and it is the state a fresh clone starts in."""
        virgin = studies_row(last_checked_at=None, trials_watched=0)
        body = api(results(studies=virgin)).get("/watch").json()
        assert body["is_healthy"] is False
        assert body["last_checked_at"] is None
        assert body["hours_since_check"] is None
        assert body["checks_missed"] == 0

    def test_the_proxy_names_itself(self, api):
        """last_checked_at is max(studies.last_matched_at), not a run log —
        there is no run log yet (direction 3). The source travels with the
        value so the UI cannot present a proxy as a record."""
        body = api(results()).get("/watch").json()
        assert body["last_checked_source"] == "last_matched_at"


class TestTheQuietWeek:
    def test_days_with_nothing_come_back_as_zeros_not_as_absence(self, api):
        """The whole design rests on this. If empty days were omitted, a
        quiet week would arrive as an empty list and render as a broken app
        — which is the state the watch screen was drawn to replace."""
        body = api(results()).get("/watch").json()
        assert len(body["daily"]) == RECORD_DAYS
        assert [d["amendments"] for d in body["daily"]] == [0] * RECORD_DAYS

    def test_a_busy_week_carries_its_real_counts(self, api):
        """Real recorded data: 79 amendments on 28 Aug, nothing on the 29th
        and 30th, 70 on the 31st, 63 on 1 Sep."""
        busy = quiet_week()
        for day, n in zip(busy[-6:], [0, 79, 0, 0, 70, 63]):
            day["amendments"] = n
        body = api(results(daily=busy)).get("/watch").json()
        assert [d["amendments"] for d in body["daily"]][-6:] == [0, 79, 0, 0, 70, 63]

    def test_the_gap_since_the_last_amendment_is_reported_in_hours(self, api):
        body = api(results()).get("/watch").json()
        assert body["hours_since_last_amendment"] == 17.56

    def test_a_watch_that_has_seen_nothing_yet_says_so_rather_than_zero(self, api):
        """None, not 0.0. "It has been 0 hours since the last amendment"
        would claim one just happened."""
        body = api(results(record=record_row(last_amendment_at=None))).get("/watch").json()
        assert body["hours_since_last_amendment"] is None
        assert body["last_amendment"] is None


class TestWhatTheHeadlineCanClaim:
    """The recent window exists so the page can say what happened, not how
    many rows moved. These assert the numbers a headline is built from
    arrive intact and keep their relationship to each other."""

    def test_a_quiet_window_is_all_zeros_not_a_missing_object(self, api):
        body = api(results()).get("/watch").json()
        assert body["recent"]["window_hours"] == 24
        assert body["recent"]["amendments"] == 0
        assert body["recent"]["scientific"] == 0

    def test_a_real_busy_day_carries_its_finding_and_its_total(self, api):
        """1 September 2026: 63 amendments recorded in one run. A page that
        can only say "63" has said nothing a researcher can act on."""
        busy = recent_row(amendments=63, trials=62, scientific=4, results_posted=1)
        body = api(results(recent=busy)).get("/watch").json()
        assert body["recent"]["amendments"] == 63
        assert body["recent"]["scientific"] == 4
        assert body["recent"]["results_posted"] == 1

    def test_results_posted_is_counted_inside_scientific_not_beside_it(self, api):
        """has_results IS a scientific field, so a posted-results amendment
        is already in `scientific`. If the UI added them instead of
        subtracting, it would report one amendment as two."""
        busy = recent_row(amendments=63, trials=62, scientific=4, results_posted=1)
        body = api(results(recent=busy)).get("/watch").json()
        assert body["recent"]["results_posted"] <= body["recent"]["scientific"]
        assert body["recent"]["scientific"] <= body["recent"]["amendments"]


class TestTheLastThingThatHappened:
    def test_it_comes_back_with_what_moved_and_what_that_did(self, api):
        body = api(
            results(head=amendment_head(), fields=[field_row()])
        ).get("/watch").json()
        last = body["last_amendment"]
        assert last["nct_id"] == "NCT02954874"
        assert last["brief_title"] == "A Real Trial"
        assert last["posted_on"] == "2026-08-31"
        assert last["previously_posted_on"] == "2026-08-14"
        assert last["content_is_visible"] is True
        change = last["changes"][0]
        assert change["aspect"] == ASPECT_OPERATIONAL
        assert change["effect"] == "pushed about 12 months later"

    def test_aspects_lead_with_the_most_consequential(self, api):
        """A rewritten primary outcome must be readable before a date slip,
        without reading every row."""
        fields = [field_row(), field_row(field_name="primary_outcomes")]
        body = api(results(head=amendment_head(), fields=fields)).get("/watch").json()
        assert body["last_amendment"]["aspects"] == [ASPECT_SCIENTIFIC, ASPECT_OPERATIONAL]

    def test_an_unclassified_field_stays_visibly_unclassified(self, api):
        """A field CT.gov starts reporting that nobody has mapped must not
        get filed under the least alarming bucket."""
        fields = [field_row(field_name="something_new_ctgov_started_sending")]
        body = api(results(head=amendment_head(), fields=fields)).get("/watch").json()
        assert body["last_amendment"]["aspects"] == ["Uncategorised"]

    def test_an_amendment_we_cannot_see_into_is_flagged_not_emptied(self, api):
        """47% of amendments touch only fields TrialLens does not store. The
        flag is what stops the UI saying "no changes" about an amendment
        that definitely changed something."""
        body = api(
            results(head=amendment_head(visible_fields=0), fields=[])
        ).get("/watch").json()
        last = body["last_amendment"]
        assert last["content_is_visible"] is False
        assert last["changes"] == []
        assert last["aspects"] == []

    def test_no_amendments_on_record_is_a_valid_response_not_an_error(self, api):
        response = api(results(record=record_row(last_amendment_at=None))).get("/watch")
        assert response.status_code == 200
        assert response.json()["last_amendment"] is None


class TestTheRecord:
    def test_the_figures_a_fresh_clone_does_not_have(self, api):
        """Elapsed time is the moat: these are the numbers that only exist
        because the watch has been running, and none of them ship with the
        code."""
        body = api(results()).get("/watch").json()
        assert body["trials_watched"] == 11427
        assert body["changes_recorded"] == 498
        assert body["amendments_seen"] == 212
        assert body["recording_since"].startswith("2026-08-28T12:55:52")

    def test_the_quiet_day_offer_counts_only_watched_trials(self, api):
        body = api(results()).get("/watch").json()
        assert body["completed_with_results"] == 747
        assert body["trials_with_results"] == 1050

    def test_the_conditions_being_watched_are_named(self, api):
        """"Watching 11,427 trials" is meaningless without "of what". Read
        from the same registry /tracked-conditions serves, not a second copy."""
        body = api(results()).get("/watch").json()
        assert body["conditions"]
        assert all(isinstance(c, str) for c in body["conditions"])
