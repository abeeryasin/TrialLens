"""frontend/Home.py — the watch screen's three states, rendered for real.

Streamlit's AppTest runs the actual script and returns the element tree, so
these assert what a researcher would see, not what the code intends. The
API is stubbed: this is about the page's reading of a payload, and
GET /watch has its own tests.

Two of the three states are effectively impossible to check by hand:

  - **The alarm** only appears when the cron has been dead for 12 hours,
    which is exactly when nobody is sitting in front of it. Its load-bearing
    property is that it REPLACES the page — a stale feed under a small
    warning still reads as current — and nothing but a test will notice if
    a future edit puts the feed back underneath it.
  - **The quiet week** is the screen a researcher sees most often (29 and 30
    August 2026 had zero amendments across 11,427 trials) and is the one
    state that never shows up while developing against live data on a busy
    day.

Free: no database, no network, no model.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_home_watch_page.py -v
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit not installed"
).AppTest

HOME = str(FRONTEND / "Home.py")
NOW = datetime.now(timezone.utc)


def payload(**overrides):
    """A healthy, quiet watch — the default, because it is the common case."""
    body = {
        "trials_watched": 11427,
        "conditions": ["breast cancer", "obesity"],
        "last_checked_at": (NOW - timedelta(hours=2)).isoformat(),
        "hours_since_check": 2.0,
        "check_interval_hours": 6,
        "checks_missed": 0,
        "is_healthy": True,
        "daily": [
            {"day": (date(2026, 9, 2) - timedelta(days=n)).isoformat(), "amendments": 0}
            for n in reversed(range(7))
        ],
        "recent": {
            "window_hours": 24,
            "amendments": 0,
            "trials": 0,
            "scientific": 0,
            "results_posted": 0,
        },
        "hours_since_last_amendment": 48.0,
        "last_amendment": None,
        "trials_with_results": 1050,
        "completed_with_results": 747,
        "recording_since": "2026-08-28T12:55:52+00:00",
        "changes_recorded": 498,
        "amendments_seen": 212,
    }
    body.update(overrides)
    return body


def amendment(**overrides):
    body = {
        "nct_id": "NCT04837586",
        "brief_title": "Self-Weighing for Adolescents Seeking Obesity Treatment",
        "posted_on": "2026-09-01",
        "previously_posted_on": "2026-05-20",
        "detected_at": "2026-09-01T18:03:16+00:00",
        "changes": [
            {
                "field_name": "overall_status",
                "old_value": "RECRUITING",
                "new_value": "COMPLETED",
                "detected_at": "2026-09-01T18:03:16+00:00",
                "category": "Trial content",
                "aspect": "Operational",
                "effect": "finished — results may start appearing",
            }
        ],
        "aspects": ["Operational"],
        "content_is_visible": True,
    }
    body.update(overrides)
    return body


@pytest.fixture
def render(monkeypatch):
    """Run Home.py against a stubbed /watch and return its visible text.

    Patches api_client.get rather than the network: Home does
    `from api_client import get` when the script runs, so the attribute is
    read fresh on every AppTest.run().
    """
    import api_client

    def _render(body):
        monkeypatch.setattr(api_client, "get", lambda path, params=None: body)
        app = AppTest.from_file(HOME, default_timeout=30).run()
        assert not app.exception, [e.value for e in app.exception]
        seen = []
        for element in app.main:
            # Both, not the first one found: st.metric carries its heading on
            # .label and its figure on .value, and taking only one of them
            # silently hides half the record footer from every assertion.
            for attr in ("label", "value"):
                text = getattr(element, attr, None)
                if isinstance(text, str):
                    seen.append(text)
        return "\n".join(seen)

    return _render


class TestTheQuietWeek:
    def test_it_states_the_silence_as_a_finding(self, render):
        """The whole point. An empty table reads as a broken app; "nothing
        has changed in 48 hours, and that is the watch working" reads as a
        report."""
        page = render(payload())
        # "2 days", not the artboard's "48 hours" — past two days the page
        # switches units, because "72 hours" is a number a reader has to
        # divide before it means anything.
        assert "Nothing has changed in 2 days." in page
        assert "a quiet day is the watch working, not the watch broken" in page

    def test_it_does_not_claim_most_weeks_are_quiet(self, render):
        """That sentence shipped on 2026-09-02 and was false: of the six days
        on record, the four weekdays carried 63-79 amendments each. It is
        pinned out rather than merely deleted, because it is the kind of
        plausible line that gets written again."""
        assert "Most weeks look like this" not in render(payload())

    def test_a_shorter_silence_is_still_counted_in_hours(self, render):
        page = render(payload(hours_since_last_amendment=18.0))
        assert "Nothing has changed in 18 hours." in page

    def test_it_offers_something_to_do(self, render):
        """An absence stated and then left there is still a dead end."""
        page = render(payload())
        # Both halves of this sentence used to say "posted results" —
        # "747 completed trials have posted results — out of 1,050 with
        # results published" is circular. The distinction it is drawing is
        # status, so status has to be what it says (reported 2026-09-04).
        assert "1,050 tracked trials have published results" in page
        assert "747 of them are marked completed" in page
        assert "completed trials have posted results" not in page
        assert "A quiet week is when there is time to read them." in page

    def test_the_empty_days_are_shown_as_zeros(self, render):
        """The zeros are evidence the watch ran and found nothing. Omitting
        them would delete the only proof a quiet day was watched at all."""
        page = render(payload())
        assert "Amendments detected per day" in page
        assert page.count(">0<") == 7

    def test_the_strip_says_what_the_numbers_count_before_showing_them(self, render):
        """Read by someone who hadn't built it: a bare "79" above a date,
        with the only explanation at the far right of the row, does not say
        what 79 counts. The heading now sits above the tiles."""
        page = render(payload())
        heading = page.index("Amendments detected per day")
        first_tile = page.index("border-radius:6px")
        assert heading < first_tile

    def test_it_says_these_are_detection_dates_not_posting_dates(self, render):
        """They differ: one amendment CT.gov posted on 28 August wasn't
        detected until the 31st. Labelling detection dates as posting dates
        would attribute our cron's timing to the registry."""
        assert "detected" in render(payload())

    def test_weekends_are_marked_so_the_pattern_is_visible(self, render):
        """The only two silent days on record were a Saturday and a Sunday.
        Without the weekday, that pattern is invisible and the zeros look
        arbitrary."""
        page = render(payload())
        for day in ("Sat", "Sun", "Mon"):
            assert f">{day}<" in page

    def test_the_weekend_claim_is_dropped_once_a_weekday_falls_silent(self, render):
        """A written claim rots; this one recomputes. The moment a Tuesday
        records zero amendments, the page must stop saying every silent day
        was a weekend."""
        days = [
            {"day": "2026-08-27", "amendments": 0},   # Thursday
            {"day": "2026-08-28", "amendments": 0},
            {"day": "2026-08-29", "amendments": 0},
            {"day": "2026-08-30", "amendments": 0},
            {"day": "2026-08-31", "amendments": 0},
            {"day": "2026-09-01", "amendments": 0},
            {"day": "2026-09-02", "amendments": 0},
        ]
        assert "fallen on a weekend" not in render(payload(daily=days))


class TestTheWeekWithNews:
    def test_it_leads_with_what_changed_the_science(self, render):
        """Not "63 amendments" — that is a row count, and a row count is
        what the removed ranking layer was good at and useless for."""
        page = render(
            payload(
                recent={
                    "window_hours": 24,
                    "amendments": 63,
                    "trials": 63,
                    "scientific": 14,
                    "results_posted": 1,
                },
                hours_since_last_amendment=18.0,
                last_amendment=amendment(),
            )
        )
        # ONE sentence, not two clauses each ending in a full stop. The
        # earlier "1 trial published its results. 13 others changed
        # something scientific." read as a stutter in a 26px headline
        # (reported 2026-09-04 from real use).
        assert "1 trial published its results, and 13 others changed something scientific." in page
        assert "results. 13 others" not in page
        assert "Out of 63 amendments across 63 trials in the last 24 hours" in page
        assert "The remaining 49 moved dates, sites, enrolment figures or titles" in page

    def test_results_posted_is_subtracted_from_scientific_not_added(self, render):
        """has_results IS a scientific field. Adding them would report one
        amendment twice and overstate what happened."""
        page = render(
            payload(
                recent={
                    "window_hours": 24,
                    "amendments": 10,
                    "trials": 10,
                    "scientific": 3,
                    "results_posted": 3,
                },
                last_amendment=amendment(),
            )
        )
        assert "3 trials published their results." in page
        assert "changed something scientific" not in page

    def test_the_quiet_day_invitation_does_not_intrude_on_a_busy_one(self, render):
        """Still shows the results count — it is a real standing fact — but
        drops "a quiet week is when there is time to read them", which is a
        non-sequitur beside real news."""
        page = render(
            payload(
                recent={
                    "window_hours": 24,
                    "amendments": 63,
                    "trials": 63,
                    "scientific": 14,
                    "results_posted": 0,
                },
                last_amendment=amendment(),
            )
        )
        # Both halves of this sentence used to say "posted results" —
        # "747 completed trials have posted results — out of 1,050 with
        # results published" is circular. The distinction it is drawing is
        # status, so status has to be what it says (reported 2026-09-04).
        assert "1,050 tracked trials have published results" in page
        assert "747 of them are marked completed" in page
        assert "completed trials have posted results" not in page
        assert "A quiet week is when there is time to read them." not in page


class TestTheLastThingThatHappened:
    def test_it_shows_what_moved_and_what_that_did(self, render):
        page = render(payload(last_amendment=amendment(), hours_since_last_amendment=18.0))
        assert "The last thing that happened" in page
        assert "NCT04837586" in page
        assert "Self-Weighing for Adolescents Seeking Obesity Treatment" in page
        assert "RECRUITING → COMPLETED" in page
        assert "finished — results may start appearing" in page

    def test_an_amendment_we_cannot_see_into_is_never_called_no_changes(self, render):
        """47% of amendments touch only fields TrialLens doesn't store.
        Rendering that as "no changes" would be a false claim about a study
        fact (CLAUDE.md sec. 2) — the amendment definitely changed
        something."""
        blind = amendment(changes=[], aspects=[], content_is_visible=False)
        page = render(payload(last_amendment=blind))
        assert "we can't show what moved" in page
        assert "It is not a claim that nothing did." in page


class TestTheAlarm:
    def test_it_replaces_the_page_rather_than_sitting_above_it(self, render):
        """The load-bearing design decision. A stale feed under a small
        warning still reads as current, so when the watch is stopped the
        feed, the day strip and the last-amendment card must all be GONE —
        not pushed down."""
        page = render(
            payload(
                is_healthy=False,
                hours_since_check=76.0,
                checks_missed=12,
                recent={
                    "window_hours": 24,
                    "amendments": 63,
                    "trials": 63,
                    "scientific": 14,
                    "results_posted": 1,
                },
                last_amendment=amendment(),
            )
        )
        assert "The watch has stopped." in page
        assert "12 checks have not happened" in page
        assert "3 days and 4 hours ago" in page

        assert "The last thing that happened" not in page
        assert "amendments per day" not in page
        assert "changed something scientific" not in page
        assert "NCT04837586" not in page

    def test_it_says_what_is_still_true_and_what_to_check(self, render):
        """Direction, not mood. An alarm that only alarms leaves the reader
        unable to tell whether their recorded history is also suspect."""
        page = render(payload(is_healthy=False, hours_since_check=76.0, checks_missed=12))
        assert "The 498 changes already recorded are real and unaffected." in page
        assert "the watch stopped collecting, it did not delete" in page
        assert "What to check" in page

    def test_a_watch_that_never_ran_says_exactly_that(self, render):
        """The state a fresh clone starts in. "0 checks have not happened"
        would be nonsense; "no check has ever been recorded" is the fact."""
        page = render(
            payload(
                is_healthy=False,
                last_checked_at=None,
                hours_since_check=None,
                checks_missed=0,
                trials_watched=0,
            )
        )
        assert "No check has ever been recorded." in page
        assert "checks have not happened" not in page

    def test_the_record_survives_the_alarm(self, render):
        """Frozen figures are still real ones. They are shown so the reader
        can see how far behind the record is."""
        page = render(payload(is_healthy=False, hours_since_check=76.0, checks_missed=12))
        assert "Watching since" in page
        assert "28 August 2026" in page
        assert "498" in page


class TestHonestyAboutItself:
    def test_the_page_says_where_last_check_comes_from(self, render):
        """Direction 3 replaced the proxy with a real run record, so the page
        now names its source rather than disclaiming one it didn't have."""
        page = render(payload())
        assert "the most recent scheduled run finished" in page
        assert "TrialLens doesn't keep one yet" not in page

    def test_a_late_check_is_reported_without_crying_wolf(self, render):
        """One skipped run is a hiccup — GitHub's scheduled workflows are
        best-effort. Alarming on it trains the reader to ignore the alarm."""
        page = render(payload(hours_since_check=7.0, checks_missed=1))
        assert "A check looks late" in page
        assert "The watch has stopped." not in page
        assert "Nothing has changed in" in page

    def test_an_unreachable_api_is_not_a_stopped_watch(self, render, monkeypatch):
        """Two different failures that must not look alike: the watch may be
        running perfectly and this process simply cannot see it."""
        import api_client

        def boom(path, params=None):
            raise api_client.ApiError("Could not reach the API at http://x")

        monkeypatch.setattr(api_client, "get", boom)
        app = AppTest.from_file(HOME, default_timeout=30).run()
        assert not app.exception
        assert any("Could not reach the API" in e.value for e in app.error)
        rendered = "\n".join(
            getattr(e, "value", "") for e in app.main if isinstance(getattr(e, "value", None), str)
        )
        assert "The watch has stopped." not in rendered
