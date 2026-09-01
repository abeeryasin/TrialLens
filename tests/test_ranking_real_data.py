"""Deterministic scorers against every real trial in the database.

Free — no model calls. The unit tests use values chosen by hand; this uses
every value that actually exists, which is the only way to find the ones
nobody thought to write a test for. Read-only throughout (sec. 5: the
read-only role is the door), so it cannot affect the cron or ingest.

Skipped automatically when DATABASE_URL_READONLY isn't set, so CI without
database credentials stays green.

Run: PYTHONPATH=. python3 -m pytest tests/test_ranking_real_data.py -v -s
"""
import ast
import os
from collections import Counter
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

from api import ranking_deterministic
from api.ranking_deterministic import (
    INTERVENTION_TYPES,
    SCORER_COLUMNS,
    ResearcherPreferences,
    parse_age_to_years,
    parse_phases,
    score_age_range_fit,
    score_enrollment_feasibility,
    score_phase_fit,
    score_sites_active,
    score_status_recruiting,
    trial_intervention_types,
)
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


# Every column the five deterministic scorers read, plus the ones StudyDetail
# requires to construct at all. Deliberately not `SELECT *`, and not even the
# full StudyDetail column set.
#
# This fixture reads all 11,469 active rows, and it runs on every `pytest
# tests/`. `SELECT *` moved 137 MB per run — 95 MB of it raw_json, which
# StudyDetail drops on arrival. Naming the whole StudyDetail set would still
# move 42 MB, most of it eligibility_criteria (16 MB), brief_summary (7 MB),
# primary_outcomes (6 MB) and interventions (4.5 MB) — none of which any
# deterministic scorer looks at. This list moves roughly 8 MB (measured
# 2026-08-31), which matters against Neon's 5 GB/month egress allowance.
#
# test_fixture_fetches_every_column_the_scorers_read below fails if a scorer
# starts reading a field that isn't here, so the saving can't quietly become
# a lie.
#
# Imported, not redefined: SCORER_COLUMNS lives next to the scorers in
# api/ranking_deterministic.py, and a second copy here would drift from it.
# A drifted copy means a scorer silently reading None on every trial. It was
# also read by api/ranking.py's candidate-selection stage until that file was
# deleted (2026-09-01); this file is now its only consumer.


@pytest.fixture(scope="module")
def trials():
    """Every active trial, as StudyDetail. Read-only."""
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT {', '.join(SCORER_COLUMNS)} FROM studies "
                f"WHERE active_in_scope = true"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [StudyDetail(**row, conditions=[]) for row in rows]


def _attributes_read_from_trials(module) -> set:
    """Every `trial.<field>` / `study.<field>` the module reads, via AST.

    Deliberately not a grep for a hand-written list of field names. A list
    only catches the mistakes whoever wrote it already thought of, and the
    whole risk here is the field nobody anticipated. Walking the syntax tree
    finds every attribute access that exists, including ones added later by
    someone who never read this file.
    """
    source = Path(module.__file__).read_text()
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"trial", "study"}
    }


def test_fixture_fetches_every_column_the_scorers_read():
    """Guards the narrowed fixture query above.

    The fixture leaves most StudyDetail columns unfetched, so every trial it
    builds reports them as None. A scorer that started reading one would go
    on passing here while silently being tested against nothing at all —
    which is bug #7 (eligibility_criteria never reaching the prompt) in a new
    costume. Free: no database, no model, no network.
    """
    missing = _attributes_read_from_trials(ranking_deterministic) - set(SCORER_COLUMNS)
    assert not missing, (
        f"api/ranking_deterministic.py reads {sorted(missing)} off each trial, "
        f"but the fixture query in this file doesn't fetch it — every trial "
        f"would see None and these tests would pass while proving nothing. "
        f"Add it to SCORER_COLUMNS and accept the extra egress."
    )


# A preference object that exercises every deterministic scorer's live path,
# rather than short-circuiting on "not stated".
FULL_PREFS = ResearcherPreferences(
    condition_terms=["breast cancer"],
    phases=["PHASE2", "PHASE3"],
    require_recruiting=True,
    min_age_years=18,
    max_age_years=75,
)

# Every scorer takes a weight, which used to come from api/ranking.py's
# SIGNAL_WEIGHTS. That file is deleted and nothing combines these signals any
# more, so the value is arbitrary here — these tests are about whether a
# scorer handles every real stored value, never about what a score comes to.
ANY_WEIGHT = 0.10


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
        signal = score_status_recruiting(trial, FULL_PREFS, ANY_WEIGHT)
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
            score_status_recruiting(trial, FULL_PREFS, ANY_WEIGHT)
            score_phase_fit(trial, FULL_PREFS, ANY_WEIGHT)
            score_age_range_fit(trial, FULL_PREFS, ANY_WEIGHT)
            score_sites_active(trial, ANY_WEIGHT)
            score_enrollment_feasibility(trial, ANY_WEIGHT)
        except Exception as exc:
            failures.append((trial.nct_id, type(exc).__name__, str(exc)))

    if failures:
        print("\nScorer exceptions:")
        for row in failures[:20]:
            print(f"  {row}")
    assert not failures, f"{len(failures)} trials raised in a deterministic scorer"


def test_every_intervention_type_in_the_database_is_known(trials):
    """INTERVENTION_TYPES must still be the database's real vocabulary.

    Replaces test_every_type_the_parse_may_emit_is_a_real_ctgov_value, which
    was deleted with the ranking layer. That test compared this list against
    a hand-written enum in a prompt schema — two hand-written lists agreeing
    with each other, neither checked against the data. This asks the source
    instead (sec. 6).

    The failure it exists to catch is real and already happened once: an
    earlier six-value shortlist left 2,022 trials' interventions
    unclassifiable. If CT.gov introduces a twelfth type, that shows up here
    rather than as a category silently missing from every comparison.
    """
    unknown = Counter()
    for trial in trials:
        for kind in trial_intervention_types(trial) - set(INTERVENTION_TYPES):
            unknown[kind] += 1

    assert not unknown, (
        f"intervention types in the database that INTERVENTION_TYPES does not "
        f"list: {dict(unknown)}. Add them with their real counts — a missing "
        f"type is a category nothing can ever match on."
    )


def test_report_coverage_across_real_data(trials):
    """Not an assertion — a printed profile of how the scorers behave at scale.

    Shows what fraction of trials each signal can actually assess, which is
    the honest answer to 'how much of this system's judgment is real?'
    """
    per_signal = {name: Counter() for name in
                  ("status_recruiting", "phase_fit", "age_range_fit",
                   "sites_active", "enrollment_feasibility")}

    for trial in trials:
        results = {
            "status_recruiting": score_status_recruiting(trial, FULL_PREFS, ANY_WEIGHT),
            "phase_fit": score_phase_fit(trial, FULL_PREFS, ANY_WEIGHT),
            "age_range_fit": score_age_range_fit(trial, FULL_PREFS, ANY_WEIGHT),
            "sites_active": score_sites_active(trial, ANY_WEIGHT),
            "enrollment_feasibility": score_enrollment_feasibility(trial, ANY_WEIGHT),
        }
        for name, signal in results.items():
            per_signal[name][signal.status] += 1

    total = len(trials)
    print(f"\n{'=' * 70}\nDeterministic signal coverage over {total:,} real trials\n{'=' * 70}")
    for name, counts in per_signal.items():
        assessable = total - counts.get("unknown", 0)
        print(f"\n  {name}  — assessable on {assessable:,}/{total:,} ({100*assessable//total}%)")
        for status, n in counts.most_common():
            print(f"      {status:<10} {n:>6,}  ({100*n//total:>3}%)")

    # The mean-evaluated-weight line that used to close this report is gone
    # with score_signals: a weighted fraction only means something when the
    # signals are being combined into a score, and none of them are now.
    # These per-signal counts are the part that survives, and they answer a
    # question a filter still has — how many trials a filter can decide at
    # all, versus how many it would have to leave in for lack of a value.
    print()
