"""The daily digest's composition and its window arithmetic (step 12).

Free: no network, no database, no Resend account, no email sent. That split
is the point of api/digest.py existing separately from the script that
sends — the same free-test-first rule sec. 7 states for paid model calls,
applied to a paid-ish external service.

Two things these tests care about more than formatting:

  - **The vocabulary.** An email is user-visible output and is read away
    from the page that explains itself, so sec. 2's register applies at
    least as strictly: what changed, when, requires review. Never a verdict.
  - **The window.** Each digest reports one whole weekday, and Monday
    reports Friday. Getting that wrong either double-reports a day or drops
    one silently, and the silent drop is the failure step 11 exists to
    prevent — so there is a test here asserting that across a run of
    weekdays every one is covered exactly once.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from api.digest import (
    CHANGE_LINE_CAP,
    CTGOV_STUDY_URL,
    compose,
    describe_outcome_change,
    subject_line,
)
from scripts.send_digest import previous_weekday, weekday_window, window_days

UNTIL = datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def change(**overrides):
    body = {
        "nct_id": "NCT04276493",
        "brief_title": "A real trial",
        "category": "substantive",
        "measures_added": ["Adverse Events and Serious Adverse Events"],
        "measures_removed": ["Adverse Events"],
        "count_before": 3, "count_after": 2,
        "window_changes": [], "description_changes": [],
        "flags": [], "flag_labels": [], "interpretation": None,
        "detected_at": "2026-09-06T20:10:24Z",
    }
    body.update(overrides)
    return body


def window(**overrides):
    body = {"days": 1, "since": None, "until": None, "recording_since": None,
            "covers_full_window": True, "condition": None,
            "trials_tracked": 11453, "trials_changed": 68,
            "amendments": 80, "field_changes": 115}
    body.update(overrides)
    return body


def investigate(changes=(), **overrides):
    changes = list(changes)
    body = {
        "window": window(),
        "dates": [], "lifecycle": [],
        "enrollment": {"became_actual": [], "became_actual_total": 0,
                       "became_actual_observational_total": 0, "under_target": 0,
                       "switched_back": [], "switched_back_total": 0,
                       "target_raised": [], "target_raised_total": 0,
                       "target_lowered": [], "target_lowered_total": 0},
        "outcomes": {
            "changes": changes, "reformatting_listed": True,
            "total": len(changes),
            "substantive": sum(1 for c in changes if c["category"] == "substantive"),
            "entry_completed": sum(1 for c in changes if c["category"] == "entry_completed"),
            "reformatting": sum(1 for c in changes if c["category"] == "reformatting"),
            "after_primary_completion": 0, "unreadable": 0,
        },
        "scope_exits": [], "scope_exits_total": 0,
    }
    body.update(overrides)
    return body


def mail(changes=(), since=UNTIL - DAY, until=UNTIL, **overrides):
    return compose(investigate(changes, **overrides), since, until)


# ---------------------------------------------------------------------------
# Sec. 2's vocabulary, in the place it is most likely to be read alone
# ---------------------------------------------------------------------------

class TestItNeverAccuses:
    def test_the_subject_states_what_is_waiting_not_a_verdict(self):
        subject = subject_line(window(), {"substantive": 3}, None, None)
        assert subject == "TrialLens: 3 primary-outcome changes to review"

    @pytest.mark.parametrize("forbidden", [
        "outcome switching", "misconduct", "fraud", "manipulated",
        "suspicious", "eligible", "eligibility",
    ])
    def test_no_forbidden_word_reaches_the_reader(self, forbidden):
        body = mail([change(
            flags=["after_primary_completion", "results_posted"],
            flag_labels=["changed after the trial's primary completion date",
                         "the trial has already posted results"],
        )])
        assert forbidden not in body["text"].lower()
        assert forbidden not in body["html"].lower()
        assert forbidden not in body["subject"].lower()

    def test_the_caveat_travels_with_every_mail(self):
        """The page explains itself in context. An email is read in an inbox,
        so it carries its own caveat or it carries none."""
        for body in (mail(), mail([change()])):
            assert "innocent explanations" in body["text"]
            assert "nothing above is a verdict" in body["text"]
            assert "innocent explanations" in body["html"]


class TestZeroIsStatedNotOmitted:
    def test_a_day_with_no_outcome_change_says_so(self):
        body = mail()
        assert "No trial changed a registered primary outcome" in body["text"]
        assert body["changes_reported"] == 0

    def test_a_completely_quiet_window_still_reads_as_an_answer(self):
        body = mail(window=window(trials_changed=0))
        assert body["subject"] == "TrialLens: nothing changed across the watch"
        assert "0 of 11,453 tracked trials" in body["text"]

    def test_a_quiet_outcome_day_still_reports_the_trials_that_moved(self):
        assert "no outcome changes, 68 trials updated" in mail()["subject"]


# ---------------------------------------------------------------------------
# What a change says
# ---------------------------------------------------------------------------

class TestDescribingAChange:
    def test_measures_are_the_registrys_own_words(self):
        lines = describe_outcome_change(change())
        assert "No longer listed: Adverse Events" in lines
        assert "Now listed: Adverse Events and Serious Adverse Events" in lines

    def test_a_moved_window_is_shown_as_written_with_no_direction(self):
        """'Week 39 → Week 33' is plain to a reader and a guess to a parser.
        Deriving 'shortened by six weeks' would be a computed claim about a
        study fact (sec. 3), which is why only the two strings appear."""
        lines = describe_outcome_change(change(
            measures_added=[], measures_removed=[],
            window_changes=[{"measure": "Body weight",
                             "before": "Week 39", "after": "Week 33"}],
        ))
        assert lines == ["Observation window moved on “Body weight”: Week 39 → Week 33"]
        assert not any("shorten" in line or "reduced" in line for line in lines)

    @pytest.mark.parametrize("kind,expected", [
        ("edited", "is defined changed"),
        ("removed", "was deleted"),
        ("added", "was previously silent"),
    ])
    def test_each_kind_of_description_move_reads_differently(self, kind, expected):
        (line,) = describe_outcome_change(change(
            measures_added=[], measures_removed=[],
            description_changes=[{"measure": "Adherence", "kind": kind,
                                  "before": "x", "after": "y"}],
        ))
        assert expected in line

    def test_a_long_list_is_capped_and_the_remainder_counted(self):
        """NCT06400472, real: one drug rename touched every registered
        endpoint and produced 12 bullets. Capped — but the withheld count is
        printed, because a silently truncated list is the cap fault of
        2026-09-07 in a new place."""
        lines = describe_outcome_change(change(
            measures_removed=[f"Old endpoint {i}" for i in range(6)],
            measures_added=[f"New endpoint {i}" for i in range(6)],
        ))
        assert len(lines) == CHANGE_LINE_CAP + 1
        assert "… and 6 further changes" in lines[-1]

    def test_a_change_with_nothing_itemisable_says_so(self):
        """An empty card reads as a bug and tells the reader nothing."""
        (line,) = describe_outcome_change(change(
            measures_added=[], measures_removed=[],
        ))
        assert "could not itemise" in line

    def test_the_flags_reach_the_reader(self):
        body = mail([change(
            flags=["after_primary_completion"],
            flag_labels=["changed after the trial's primary completion date"],
        )])
        assert "changed after the trial's primary completion date" in body["text"]


class TestOnlySubstantiveChangesAreNamed:
    def test_reformatting_is_counted_never_listed(self):
        body = mail([change(nct_id="NCTref", category="reformatting",
                            measures_added=[], measures_removed=[])])
        assert "NCTref" not in body["text"]
        assert "1 was reformatting only" in body["text"]

    def test_a_filled_in_definition_is_counted_under_its_own_name(self):
        """Not substantive, and not reformatting either — the third category
        exists because calling it reformatting was a false statement."""
        body = mail([change(nct_id="NCTfill", category="entry_completed",
                            measures_added=[], measures_removed=[])])
        assert "definition filled in under an unchanged endpoint" in body["text"]
        assert "reformatting" not in body["text"]

    def test_the_set_aside_line_is_grammatical_at_one(self):
        body = mail([change(category="reformatting",
                            measures_added=[], measures_removed=[])])
        assert "1 was reformatting only" in body["text"]
        assert "1 were" not in body["text"]


# ---------------------------------------------------------------------------
# Links — a wrong one cannot be corrected after the mail is sent
# ---------------------------------------------------------------------------

class TestLinks:
    def test_each_trial_links_to_the_source_of_its_facts(self):
        body = mail([change(nct_id="NCT04276493")])
        assert CTGOV_STUDY_URL.format(nct_id="NCT04276493") in body["text"]

    def test_the_html_link_lands_on_the_named_trial_not_a_search_box(self):
        """frontend/pages/2_Understand.py reads nct_id off the query string
        for exactly this. Without it every mail could only say 'go and search
        for this', which is most of a digest's value gone."""
        body = mail([change(nct_id="NCT04276493")])
        assert "/Understand?nct_id=NCT04276493" in body["html"]

    def test_the_aggregate_views_are_offered_too(self):
        body = mail()
        assert "/Investigate" in body["text"] and "/Monitor" in body["text"]


class TestTheHtmlIsSafeAndSelfContained:
    def test_a_title_with_markup_is_escaped(self):
        """Trial titles are registry text, not ours. One containing a bracket
        must not become markup in a mail client."""
        body = mail([change(brief_title='A <script>alert("x")</script> trial')])
        assert "<script>" not in body["html"]
        assert "&lt;script&gt;" in body["html"]

    def test_no_external_stylesheet_or_font_is_referenced(self):
        """Mail clients strip <style> blocks and block remote resources, so
        anything not inline is a rule that silently does not apply."""
        html = mail([change()])["html"]
        assert "<style" not in html
        assert "stylesheet" not in html
        assert "fonts.googleapis" not in html

    def test_a_plain_text_part_is_always_sent(self):
        """Not left for Resend to derive: the text part is what a screen
        reader and a plain-text client actually read."""
        body = mail([change()])
        assert body["text"].strip()
        assert "NCT04276493" in body["text"]


# ---------------------------------------------------------------------------
# The window, which is the part that can lose data
# ---------------------------------------------------------------------------

class TestTheWindowPhrase:
    def test_the_covered_day_is_named_not_described_as_yesterday(self):
        """Monday's mail is about Friday. "the last 24 hours" would send a
        reader looking for Sunday's changes, of which there are none by
        design — naming the day is what makes the skip visible."""
        since = datetime(2026, 9, 4, tzinfo=timezone.utc)
        body = mail(since=since, until=since + DAY)
        assert "Friday 4 September" in body["text"]
        assert "24 hours" not in body["text"]

    def test_a_catch_up_window_names_both_ends(self):
        body = mail(since=datetime(2026, 9, 7, tzinfo=timezone.utc),
                    until=datetime(2026, 9, 10, tzinfo=timezone.utc))
        assert "Monday 7 September to Wednesday 9 September" in body["text"]


# ---------------------------------------------------------------------------
# The weekend is dropped, and no working day goes with it (2026-09-07)
# ---------------------------------------------------------------------------

class TestWeekdayWindow:
    """Measured over the record's first ten days, Saturday and Sunday carry
    1-7 changed trials against a weekday's 65-136, and have never carried a
    single primary-outcome change."""

    @pytest.mark.parametrize("run_day,reports_on", [
        (8, 7),    # Tue reports Monday
        (9, 8),    # Wed reports Tuesday
        (10, 9),   # Thu reports Wednesday
        (11, 10),  # Fri reports Thursday
    ])
    def test_a_weekday_reports_the_previous_calendar_day(self, run_day, reports_on):
        now = datetime(2026, 9, run_day, 7, 0, tzinfo=timezone.utc)
        since, until = weekday_window(now)
        assert since == datetime(2026, 9, reports_on, tzinfo=timezone.utc)
        assert until - since == DAY

    def test_monday_reports_friday_and_skips_the_weekend(self):
        """The whole point. 7 September 2026 is a Monday."""
        since, until = weekday_window(
            datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc))
        assert since == datetime(2026, 9, 4, tzinfo=timezone.utc), "Friday"
        assert until == datetime(2026, 9, 5, tzinfo=timezone.utc), "Saturday 00:00"

    def test_no_weekday_is_lost_to_the_weekend_skip(self):
        """The failure a naive clip would cause: starting Monday's window at
        Monday 00:00 drops everything filed after Friday breakfast. Across a
        run of weekdays, every one must be covered exactly once."""
        covered = []
        for day in range(7, 12):  # Mon 7 Sep -> Fri 11 Sep
            since, _ = weekday_window(datetime(2026, 9, day, 7, tzinfo=timezone.utc))
            covered.append(since.date())
        assert covered == [
            date(2026, 9, 4), date(2026, 9, 7), date(2026, 9, 8),
            date(2026, 9, 9), date(2026, 9, 10),
        ]
        assert len(set(covered)) == len(covered), "no day covered twice"

    @pytest.mark.parametrize("weekend_day", [5, 6, 12, 13])
    def test_no_window_ever_starts_on_a_weekend(self, weekend_day):
        since, _ = weekday_window(
            datetime(2026, 9, weekend_day, 7, tzinfo=timezone.utc))
        assert since.weekday() < 5

    def test_a_healthy_week_never_spans_a_weekend(self):
        """**The test that was missing**, and the bug it now catches was
        real: Monday's digest covers Friday and so leaves covered_until at
        Saturday 00:00, which is always earlier than Tuesday's Monday 00:00.
        A naive `previous_until < since` therefore read the DELIBERATE
        weekend gap as a missed run and pulled Saturday and Sunday back into
        every single Tuesday — the exact thing the design exists to drop,
        reappearing weekly.

        Each window in isolation looked right. Only feeding each run's
        covered_until into the next exposes it, which is why this simulates
        a week rather than asserting on one call."""
        previous = None
        for day in (4, 7, 8, 9, 10, 11):  # Fri, Mon, Tue, Wed, Thu, Fri
            since, until = weekday_window(
                datetime(2026, 9, day, 7, tzinfo=timezone.utc), previous)
            assert until - since == DAY, (
                f"the run on {day} Sep covers {(until - since).days} days — a "
                "healthy cadence reports exactly one weekday"
            )
            assert since.weekday() < 5, "a window must never start on a weekend"
            previous = until

    def test_the_weekend_gap_is_not_mistaken_for_a_missed_run(self):
        """Stated on its own because it is the specific comparison that was
        wrong: against what a HEALTHY predecessor would have left, not
        against this window's own start."""
        since, _ = weekday_window(
            datetime(2026, 9, 8, 7, tzinfo=timezone.utc),      # Tuesday
            previous_until=datetime(2026, 9, 5, tzinfo=timezone.utc),  # Sat 00:00
        )
        assert since == datetime(2026, 9, 7, tzinfo=timezone.utc), (
            "Tuesday must report Monday only — Saturday 00:00 is where a "
            "correct Monday run leaves off, not evidence of a missed one"
        )

    def test_a_genuinely_missed_monday_is_still_caught_up(self):
        """The guard against over-correcting: tightening the comparison must
        not disable recovery. If Monday never ran, covered_until is still
        Friday 00:00 and Tuesday has to reach back for Friday."""
        since, until = weekday_window(
            datetime(2026, 9, 8, 7, tzinfo=timezone.utc),
            previous_until=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        assert since == datetime(2026, 9, 4, tzinfo=timezone.utc)
        assert until == datetime(2026, 9, 8, tzinfo=timezone.utc)

    def test_a_missed_run_is_caught_up_rather_than_mailed_to_nobody(self):
        """A failed run does not advance covered_until, so the next one
        reaches back. Two quiet weekend days in a catch-up mail cost far
        less than a working day that reached no inbox."""
        since, until = weekday_window(
            datetime(2026, 9, 9, 7, tzinfo=timezone.utc),
            previous_until=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        assert since == datetime(2026, 9, 5, tzinfo=timezone.utc)
        assert until == datetime(2026, 9, 9, tzinfo=timezone.utc)

    def test_a_stale_record_can_never_pull_the_window_forward(self):
        """previous_until only ever extends backwards. If it could move the
        start later, a clock skew would silently skip a day."""
        since, _ = weekday_window(
            datetime(2026, 9, 9, 7, tzinfo=timezone.utc),
            previous_until=datetime(2026, 9, 30, tzinfo=timezone.utc),
        )
        assert since == datetime(2026, 9, 8, tzinfo=timezone.utc)

    def test_previous_weekday_walks_back_over_both_weekend_days(self):
        assert previous_weekday(datetime(2026, 9, 7, tzinfo=timezone.utc)) == date(2026, 9, 4)


class TestNoEmptyEmail:
    """Asked for 2026-09-07. A mail that says "nothing happened" teaches the
    reader to skim, and then the one that matters is skimmed too — the same
    argument check_ops_health.py already makes about alarms."""

    def test_a_window_where_nothing_moved_has_no_content(self):
        assert mail(window=window(trials_changed=0))["has_content"] is False

    def test_a_named_outcome_change_is_content(self):
        assert mail([change()])["has_content"] is True

    def test_trials_moving_without_an_outcome_change_is_still_content(self):
        """Not the same as empty: 68 trials updated with timeline moves and
        status changes has plenty to say, it just has no endpoint change to
        lead with."""
        assert mail()["has_content"] is True

    def test_counts_alone_are_content(self):
        body = mail(window=window(trials_changed=0), scope_exits_total=3)
        assert body["has_content"] is True


class TestWindowDays:
    def test_a_day_apart_is_one_day(self):
        assert window_days(UNTIL - DAY, UNTIL) == 1

    def test_a_catch_up_gap_is_reported_in_whole_days(self):
        assert window_days(UNTIL - timedelta(days=4), UNTIL) == 4

    def test_scheduler_drift_does_not_re_report_a_day(self):
        """The cron will not fire to the second. Ceiling-rounding a 24h+2min
        gap to 2 days would re-mail everything yesterday's digest covered."""
        assert window_days(UNTIL - DAY - timedelta(minutes=2), UNTIL) == 1
        assert window_days(UNTIL - DAY + timedelta(minutes=2), UNTIL) == 1

    def test_it_never_returns_zero(self):
        """/investigate rejects days < 1, and a zero window would silently
        report nothing while the run recorded itself as completed."""
        assert window_days(UNTIL, UNTIL) == 1
        assert window_days(UNTIL + DAY, UNTIL) == 1
