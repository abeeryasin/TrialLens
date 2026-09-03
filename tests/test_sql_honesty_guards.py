"""Regression canaries for claims the fast test suite structurally cannot check.

**Why this file exists.** On 2026-09-04 a mutation rewrote the Explore site
query to `coalesce(ts.recruitment_status, 'NOT_RECRUITING')` — turning "the
registry published no status for this site" into "this site is not
recruiting", the single most damaging false claim these pages can make
(CLAUDE.md sec. 2). It passed **all 11** fake-connection tests, because
tests/conftest.py's fake ignores SQL on purpose. It was caught only by
tests/test_explore_real_data.py.

That is the right division of labour, but it leaves a real gap in *when*
the guarantee is enforced. `.github/workflows/tests.yml` runs on every push
with no secrets, so every real-data test skips. The suite that catches this
runs in `monitor.yml`, on the data's 6-hour schedule. So between a bad push
and the next cron there is a window where CI is green and the claim is
wrong.

These tests close that window. They read source text rather than behaviour,
which is a weak kind of test and is not pretending otherwise — a canary,
not the guarantee. The guarantee is the real-data suite. What this adds is
that the specific regression already known to be silent, catastrophic and
invisible to CI cannot land unnoticed on a push.

Deliberately narrow. A file that banned patterns liberally would become
something people route around, and a test nobody trusts is worse than no
test.

Free: no database, no network, no model.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = (ROOT / "api", ROOT / "frontend")


def source_files():
    for directory in SOURCE_DIRS:
        for path in sorted(directory.rglob("*.py")):
            yield path, path.read_text()


# CT.gov's real per-location vocabulary contains NOT_YET_RECRUITING and
# ACTIVE_NOT_RECRUITING. It does NOT contain a bare NOT_RECRUITING — see
# frontend/labels.SITE_STATUS_LABELS, which lists every value the registry
# actually uses. So a bare one can only have been invented by us, and the
# lookbehind keeps the two legitimate values from matching.
INVENTED_STATUS = re.compile(r"(?<![A-Z_])NOT_RECRUITING")

# Any SQL that supplies a default for a missing recruitment status. NULL
# means "the registry did not say" and must survive to the page, where
# frontend/labels.format_site_status renders it as a sentence.
COALESCED_STATUS = re.compile(r"coalesce\s*\([^)]*recruitment_status", re.IGNORECASE)


def test_no_default_is_substituted_for_a_missing_site_status():
    """The exact mutation that passed every fake-connection test.

    71.4% of live site edges carry no status. Filling that in — with
    anything — converts registry silence into a claim about whether a
    hospital is open, which a researcher may act on by not phoning.
    """
    offenders = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for path, text in source_files()
        for match in [COALESCED_STATUS.search(text)]
        if match
    ]
    assert not offenders, (
        "a recruitment_status is being given a default value: "
        + "; ".join(offenders)
        + ". NULL means the registry did not state one, never 'not "
        "recruiting' — see docs/plan_explore_nodes.md sec. 4b."
    )


def test_no_invented_recruitment_status_value():
    """`NOT_RECRUITING` is not a value ClinicalTrials.gov publishes.

    Its appearance anywhere in api/ or frontend/ means a status was
    manufactured rather than read, whether in SQL, a mapping, or a label.
    """
    offenders = []
    for path, text in source_files():
        for line_no, line in enumerate(text.splitlines(), start=1):
            if INVENTED_STATUS.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, (
        "'NOT_RECRUITING' is not a ClinicalTrials.gov status value and was "
        "invented at: " + "; ".join(offenders)
    )


def test_the_status_rule_is_written_once_in_sql():
    """`nullif(trim(...), '')` and frontend/labels.site_status_is_stated must
    agree on whether an empty string counts as stated.

    They are two definitions of one rule — unavoidable, since one is an
    aggregate in Postgres and the other renders a single row — so this
    pins the SQL half to the shape that matches the Python half. Plain
    `IS NULL` would put a blank-string site in a different bucket on the
    same page depending on which code path saw it.
    """
    explore = (ROOT / "api" / "explore.py").read_text()
    assert "nullif(trim(ts.recruitment_status), '')" in explore, (
        "api/explore.py no longer normalises blank statuses the way "
        "frontend/labels.site_status_is_stated does"
    )


def test_the_real_data_suite_still_guards_what_the_fake_cannot():
    """The honest backstop for this whole file.

    These canaries read source text; the actual guarantee is a real query
    against real rows. If that test is deleted or renamed, the canaries
    remain green while the property they stand in for stops being checked
    anywhere — so its existence is asserted here rather than assumed.
    """
    real_data = ROOT / "tests" / "test_explore_real_data.py"
    assert real_data.exists(), "the real-data Explore suite is gone"
    assert "test_an_unstated_status_reaches_the_page_as_nothing" in real_data.read_text(), (
        "the test that actually proves an unstated status survives the query "
        "has been removed or renamed; these source-text canaries are not a "
        "substitute for it"
    )


@pytest.mark.parametrize("workflow", ["tests.yml", "monitor.yml"])
def test_ci_still_runs_the_suite(workflow):
    """These canaries are only worth anything if CI runs them.

    tests.yml runs on every push without secrets (real-data tests skip);
    monitor.yml runs with credentials on the cron, which is where the
    real-data half actually executes. Both must keep invoking pytest.
    """
    path = ROOT / ".github" / "workflows" / workflow
    assert path.exists(), f"{workflow} is missing"
    assert "pytest" in path.read_text(), f"{workflow} no longer runs the test suite"
