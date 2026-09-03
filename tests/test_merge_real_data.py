"""Step 8 unit 3, the merge — checked against the database it changed.

The merge writes a judgement: "these two strings are one thing." It is
applied to 3,033 sites, 783 intervention terms and 111 investigators with
nobody reviewing them individually, which is only defensible because the
rule is deterministic and narrow. These tests are what hold it to that.

Two opposite failures, the same pair the extraction tests guard:

  - **Merging too much.** Two hospitals in different cities collapsed into
    one puts a trial somewhere it does not run (CLAUDE.md sec. 2). A DRUG
    and an OTHER sharing a name collapsed into one invents an intervention.
    These are the dangerous direction, and they are silent — the page looks
    fine and says something false.
  - **Merging too little** is safe but pointless, so the fixture asserts
    real groups exist rather than letting an empty column pass everything.

Plus one property the whole design rests on: **nothing was destroyed.**
Every original row is still present with its original text, and setting
canonical_id back to NULL restores the unmerged extraction exactly.

Read-only, no model, no network beyond Neon. Skipped cleanly when
DATABASE_URL_READONLY is unset; runs in monitor.yml on the data's schedule.

Run: PYTHONPATH=. python3 -m pytest tests/test_merge_real_data.py -v
"""
import os

import psycopg2
import psycopg2.extras
import pytest

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
except ImportError:
    pass

DSN = os.getenv("DATABASE_URL_READONLY")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_READONLY not set; real-data checks skipped"
)

# The same normalisation scripts/merge_entities.py applies. Repeated here on
# purpose rather than imported: a test that reuses the implementation's own
# definition of "the same string" cannot catch that definition changing.
def norm(column):
    return f"btrim(regexp_replace(lower(coalesce({column}, '')), '[^a-z0-9]+', ' ', 'g'))"


MERGED_TABLES = ("sites", "intervention_terms", "investigators")


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.close()


def scalar(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()["v"]


@pytest.mark.parametrize("table", MERGED_TABLES)
def test_the_merge_has_actually_run(cur, table):
    """Guards the failure every other test here would hide: a column of all
    NULLs satisfies "merged nothing wrong" perfectly."""
    merged = scalar(cur, f"SELECT count(canonical_id) AS v FROM {table}")
    assert merged > 0, (
        f"{table}.canonical_id is entirely NULL — scripts/merge_entities.py "
        "has not run against this database, and the assertions below would "
        "all pass vacuously"
    )


@pytest.mark.parametrize("table", MERGED_TABLES)
def test_no_row_points_at_itself(cur, table):
    """NULL means "I am canonical". A self-pointer means the same thing by a
    second route, and `coalesce(canonical_id, id)` would still work — which
    is exactly why it would go unnoticed while making every "is this row
    merged?" query wrong."""
    assert scalar(cur, f"SELECT count(*) AS v FROM {table} WHERE canonical_id = id") == 0


@pytest.mark.parametrize("table", MERGED_TABLES)
def test_no_pointer_chains(cur, table):
    """A canonical row must never itself point somewhere else, or identity
    depends on how many times you follow the pointer. One hop, always."""
    chained = scalar(
        cur,
        f"""
        SELECT count(*) AS v FROM {table} a JOIN {table} b ON b.id = a.canonical_id
        WHERE b.canonical_id IS NOT NULL
        """,
    )
    assert chained == 0, f"{table} has {chained} rows resolving through two hops"


@pytest.mark.parametrize("table", MERGED_TABLES)
def test_every_pointer_resolves(cur, table):
    """A dangling canonical_id would make a row vanish from every grouped
    read while still existing."""
    assert scalar(
        cur,
        f"""
        SELECT count(*) AS v FROM {table} a
        WHERE a.canonical_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM {table} b WHERE b.id = a.canonical_id)
        """,
    ) == 0


def test_no_site_merged_across_a_city_or_country(cur):
    """The one merge that would be a lie about a trial.

    'Mayo Clinic' is a real facility string in more than one city. Merging
    on the name alone would report a trial as running on another continent,
    and the page would render it without a flicker."""
    crossed = scalar(
        cur,
        f"""
        SELECT count(*) AS v FROM sites s JOIN sites c ON c.id = s.canonical_id
        WHERE {norm('s.city')}    IS DISTINCT FROM {norm('c.city')}
           OR {norm('s.country')} IS DISTINCT FROM {norm('c.country')}
        """,
    )
    assert crossed == 0, f"{crossed} site(s) were merged across a place boundary"


def test_no_intervention_merged_across_a_type(cur):
    """A DRUG called X is not the OTHER called X — the same rule the unique
    index encodes. Real case: 'semaglutide' exists as DRUG, BIOLOGICAL and
    OTHER, and only the DRUG pair may merge."""
    crossed = scalar(
        cur,
        """
        SELECT count(*) AS v FROM intervention_terms t
        JOIN intervention_terms c ON c.id = t.canonical_id
        WHERE t.type IS DISTINCT FROM c.type
        """,
    )
    assert crossed == 0, f"{crossed} term(s) were merged across an intervention type"


def test_no_investigator_merged_across_an_affiliation(cur):
    """286 investigator names appear under more than one affiliation, and
    they may be different people. Merging on name alone is the Procrustean
    cut unit 2 was written to avoid."""
    crossed = scalar(
        cur,
        f"""
        SELECT count(*) AS v FROM investigators i
        JOIN investigators c ON c.id = i.canonical_id
        WHERE {norm('i.affiliation')} IS DISTINCT FROM {norm('c.affiliation')}
        """,
    )
    assert crossed == 0, f"{crossed} investigator(s) merged across an affiliation"


def test_merged_rows_are_normalisation_equal_to_their_canonical(cur):
    """The rule, stated as a property rather than trusted from the script.

    Anything merged must differ from its canonical ONLY in case and
    punctuation. If a pair ever differs by a real word, the rule has been
    widened — deliberately or not — and that is a decision that needs a
    human, not a passing test."""
    mismatched = scalar(
        cur,
        f"""
        SELECT count(*) AS v FROM sites s JOIN sites c ON c.id = s.canonical_id
        WHERE {norm('s.facility')} IS DISTINCT FROM {norm('c.facility')}
        """,
    )
    assert mismatched == 0, (
        f"{mismatched} site(s) were merged with a canonical they do not "
        "normalise to — the merge rule is no longer casefold-and-punctuation"
    )


def test_the_unmerged_baseline_still_exists(cur):
    """Nothing was destroyed, which is the whole design.

    Every variant is still a row with its own original text, so setting
    canonical_id back to NULL restores the unmerged extraction exactly. A
    merge that deleted the losers would look identical on every page and be
    irreversible."""
    cur.execute(
        """
        SELECT c.id, count(*) AS members, count(DISTINCT s.facility) AS distinct_spellings
        FROM sites s JOIN sites c ON c.id = coalesce(s.canonical_id, s.id)
        WHERE s.canonical_id IS NOT NULL
        GROUP BY c.id ORDER BY members DESC LIMIT 1
        """
    )
    biggest = cur.fetchone()
    assert biggest is not None, "no merged group exists to check"
    # The members are the pointing rows; each still holds its own spelling.
    assert biggest["distinct_spellings"] == biggest["members"], (
        "a merged group has fewer surviving spellings than members — original "
        "rows have been overwritten or removed"
    )


def test_the_stored_assignment_matches_a_fresh_computation(cur):
    """Idempotence, checked read-only.

    Re-derives the winner for every site group by the script's own rule —
    most live edges, lowest id as tie-break — and compares it to what is
    stored. A drift here means the merge is not reproducible, so a re-run
    would silently reshuffle which spelling every page displays."""
    disagreements = scalar(
        cur,
        f"""
        WITH keyed AS (
            SELECT e.id, {norm('facility')} AS f, {norm('city')} AS c, {norm('country')} AS k,
                   (SELECT count(*) FROM trial_sites x
                     WHERE x.site_id = e.id AND x.delisted_at IS NULL) AS live_edges
            FROM sites e
        ),
        winners AS (
            SELECT DISTINCT ON (f, c, k) f, c, k, id AS canonical
            FROM keyed ORDER BY f, c, k, live_edges DESC, id
        ),
        expected AS (
            SELECT k2.id,
                   CASE WHEN w.canonical = k2.id THEN NULL ELSE w.canonical END AS canonical_id
            FROM keyed k2 JOIN winners w USING (f, c, k)
        )
        SELECT count(*) AS v FROM expected e
        JOIN sites s ON s.id = e.id
        WHERE s.canonical_id IS DISTINCT FROM e.canonical_id
        """,
    )
    assert disagreements == 0, (
        f"{disagreements} site(s) would be assigned differently by a fresh run "
        "— the merge is not reproducible"
    )
