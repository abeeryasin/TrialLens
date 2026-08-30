"""Deterministic scorers against every real trial in the database.

Free — no model calls. The unit tests use values chosen by hand; this uses
every value that actually exists, which is the only way to find the ones
nobody thought to write a test for. Read-only throughout (sec. 5: the
read-only role is the door), so it cannot affect the cron or ingest.

Skipped automatically when DATABASE_URL_READONLY isn't set, so CI without
database credentials stays green.

Run: PYTHONPATH=. python3 -m pytest tests/test_ranking_real_data.py -v -s
"""
import os
from collections import Counter

import psycopg2
import psycopg2.extras
import pytest

from api.ranking_deterministic import (
    ResearcherPreferences,
    parse_age_to_years,
    parse_phases,
    score_age_range_fit,
    score_enrollment_feasibility,
    score_phase_fit,
    score_sites_active,
    score_status_recruiting,
)
from api.ranking import SIGNAL_WEIGHTS, score_signals
from api.schemas import StudyDetail

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

DSN = os.getenv("DATABASE_URL_READONLY")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set; real-data checks skipped"
)


@pytest.fixture(scope="module")
def trials():
    """Every active trial, as StudyDetail. Read-only."""
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM studies WHERE active_in_scope = true")
            rows = cur.fetchall()
    finally:
        conn.close()

    return [StudyDetail(**row, conditions=[]) for row in rows]


# A preference object that exercises every deterministic scorer's live path,
# rather than short-circuiting on "not stated".
FULL_PREFS = ResearcherPreferences(
    condition_terms=["breast cancer"],
    phases=["PHASE2", "PHASE3"],
    require_recruiting=True,
    min_age_years=18,
    max_age_years=75,
)


def test_every_stored_age_parses_or_is_explicitly_absent(trials):
    """No age string may parse to a wrong number. Unparseable must be None."""
    unparsed = Counter()
    for trial in trials:
        for field, value in (("minimum_age", trial.minimum_age),
                             ("maximum_age", trial.maximum_age)):
            if value and parse_age_to_years(value) is None:
                unparsed[f"{field}={value!r}"] += 1

    if unparsed:
        print("\nAge strings that did not parse:")
        for item, n in unparsed.most_common(20):
            print(f"  {n:>5}  {item}")
    assert not unparsed, f"{sum(unparsed.values())} stored age values failed to parse"


def test_all_parsed_ages_are_plausible(trials):
    """A unit bug shows up as an implausible magnitude, not an exception."""
    implausible = []
    for trial in trials:
        for field, value in (("minimum_age", trial.minimum_age),
                             ("maximum_age", trial.maximum_age)):
            years = parse_age_to_years(value)
            if years is not None and not (0 <= years <= 150):
                implausible.append((trial.nct_id, field, value, years))

    if implausible:
        print("\nImplausible parsed ages:")
        for row in implausible[:20]:
            print(f"  {row}")
    assert not implausible, f"{len(implausible)} ages parsed outside 0-150 years"


def test_no_status_falls_through_to_unknown(trials):
    """Every status present in the data must have an explicit rule.

    A fallthrough means an upstream value appeared that the scorer doesn't
    know about — which must be found here, not in front of a researcher.
    """
    fell_through = Counter()
    for trial in trials:
        signal = score_status_recruiting(trial, FULL_PREFS, SIGNAL_WEIGHTS["status_recruiting"])
        if signal.status == "unknown" and signal.confidence == "low":
            fell_through[trial.overall_status] += 1

    if fell_through:
        print("\nUnhandled statuses:")
        for status, n in fell_through.most_common():
            print(f"  {n:>5}  {status!r}")
    assert not fell_through, f"unhandled statuses: {dict(fell_through)}"


def test_every_phase_value_is_handled(trials):
    """parse_phases must return either None or a non-empty set of tokens."""
    bad = Counter()
    for trial in trials:
        result = parse_phases(trial.phase)
        if result is not None and not result:
            bad[trial.phase] += 1

    assert not bad, f"phase values producing an empty set: {dict(bad)}"


def test_no_scorer_raises_on_any_real_trial(trials):
    """The whole deterministic set, against every real record."""
    failures = []
    for trial in trials:
        try:
            score_status_recruiting(trial, FULL_PREFS, SIGNAL_WEIGHTS["status_recruiting"])
            score_phase_fit(trial, FULL_PREFS, SIGNAL_WEIGHTS["phase_fit"])
            score_age_range_fit(trial, FULL_PREFS, SIGNAL_WEIGHTS["age_range_fit"])
            score_sites_active(trial, SIGNAL_WEIGHTS["sites_active"])
            score_enrollment_feasibility(trial, SIGNAL_WEIGHTS["enrollment_feasibility"])
        except Exception as exc:
            failures.append((trial.nct_id, type(exc).__name__, str(exc)))

    if failures:
        print("\nScorer exceptions:")
        for row in failures[:20]:
            print(f"  {row}")
    assert not failures, f"{len(failures)} trials raised in a deterministic scorer"


def test_scores_stay_in_range_across_the_whole_database(trials):
    """No real record may produce a score outside 0..1."""
    out_of_range = []
    for trial in trials:
        signals = [
            score_status_recruiting(trial, FULL_PREFS, SIGNAL_WEIGHTS["status_recruiting"]),
            score_phase_fit(trial, FULL_PREFS, SIGNAL_WEIGHTS["phase_fit"]),
            score_age_range_fit(trial, FULL_PREFS, SIGNAL_WEIGHTS["age_range_fit"]),
            score_sites_active(trial, SIGNAL_WEIGHTS["sites_active"]),
            score_enrollment_feasibility(trial, SIGNAL_WEIGHTS["enrollment_feasibility"]),
        ]
        score, _, evaluated = score_signals(signals)
        if not (0.0 <= score <= 1.0) or not (0.0 <= evaluated <= 1.0):
            out_of_range.append((trial.nct_id, score, evaluated))

    assert not out_of_range, f"{len(out_of_range)} trials scored out of range"


def test_report_coverage_across_real_data(trials):
    """Not an assertion — a printed profile of how the scorers behave at scale.

    Shows what fraction of trials each signal can actually assess, which is
    the honest answer to 'how much of this system's judgment is real?'
    """
    per_signal = {name: Counter() for name in
                  ("status_recruiting", "phase_fit", "age_range_fit",
                   "sites_active", "enrollment_feasibility")}
    evaluated_fractions = []

    for trial in trials:
        results = {
            "status_recruiting": score_status_recruiting(trial, FULL_PREFS, SIGNAL_WEIGHTS["status_recruiting"]),
            "phase_fit": score_phase_fit(trial, FULL_PREFS, SIGNAL_WEIGHTS["phase_fit"]),
            "age_range_fit": score_age_range_fit(trial, FULL_PREFS, SIGNAL_WEIGHTS["age_range_fit"]),
            "sites_active": score_sites_active(trial, SIGNAL_WEIGHTS["sites_active"]),
            "enrollment_feasibility": score_enrollment_feasibility(trial, SIGNAL_WEIGHTS["enrollment_feasibility"]),
        }
        for name, signal in results.items():
            per_signal[name][signal.status] += 1
        _, _, evaluated = score_signals(list(results.values()))
        evaluated_fractions.append(evaluated)

    total = len(trials)
    print(f"\n{'=' * 70}\nDeterministic signal coverage over {total:,} real trials\n{'=' * 70}")
    for name, counts in per_signal.items():
        assessable = total - counts.get("unknown", 0)
        print(f"\n  {name}  — assessable on {assessable:,}/{total:,} ({100*assessable//total}%)")
        for status, n in counts.most_common():
            print(f"      {status:<10} {n:>6,}  ({100*n//total:>3}%)")

    mean_evaluated = sum(evaluated_fractions) / len(evaluated_fractions)
    print(f"\n  Mean deterministic weight assessable per trial: {mean_evaluated:.1%}")
    print(f"  (the remaining weight is the two signals the model judges)\n")
