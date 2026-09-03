"""GET /explore/{nct_id} against the live database — is the SQL right?

tests/test_explore_endpoint.py runs the route against a fake connection
that ignores SQL, so it can prove the assembly and the response model are
right and nothing at all about the queries. A real mutation demonstrated
the gap on 2026-09-04: rewriting the site query to
`coalesce(ts.recruitment_status, 'NOT_RECRUITING')` — turning "the registry
said nothing" into "not recruiting", the single claim
docs/plan_explore_nodes.md sec. 4b most wants to prevent — passed all 11
fake-connection tests. These are the tests that catch it.

Everything here goes through HTTP against the real reader role, so a query
that is subtly wrong shows up as a wrong answer rather than a wrong row.
Read-only, no model, no CT.gov call. Skipped cleanly when
DATABASE_URL_READONLY is unset, so CI without credentials stays green — the
suite these belong to runs in monitor.yml, on the data's schedule.

Trials are chosen by PROPERTY, never hardcoded: "the trial with the most
sites" survives re-ingestion, NCT01272037 might not.

Run: PYTHONPATH=. python3 -m pytest tests/test_explore_real_data.py -v
"""
import os

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from api.main import app

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
def cur():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    # No dependency_overrides: this must hit the real reader role. Each
    # request opens its own connection and costs ~4s against Neon, so every
    # fixture below is module-scoped and fetched once.
    return TestClient(app)


def one(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


@pytest.fixture(scope="module")
def busiest(cur, client):
    """The trial with the most live sites — guaranteed to exercise both caps
    and, at 1,568 sites, the case a truncation bug hides in."""
    row = one(
        cur,
        """
        SELECT nct_id, count(*) AS sites
        FROM trial_sites WHERE delisted_at IS NULL
        GROUP BY 1 ORDER BY sites DESC, nct_id LIMIT 1
        """,
    )
    response = client.get(f"/explore/{row['nct_id']}")
    assert response.status_code == 200
    return row["nct_id"], response.json()


@pytest.fixture(scope="module")
def with_dropped_sites(cur, client):
    """A trial that has quietly dropped a location. Rare — 23 trials on
    2026-09-04 — and the whole reason delisted edges are stamped instead of
    deleted."""
    row = one(
        cur,
        """
        SELECT nct_id, count(*) AS dropped
        FROM trial_sites WHERE delisted_at IS NOT NULL
        GROUP BY 1 ORDER BY dropped DESC, nct_id LIMIT 1
        """,
    )
    if row is None:
        pytest.skip("no trial has dropped a site yet")
    response = client.get(f"/explore/{row['nct_id']}")
    assert response.status_code == 200
    return row["nct_id"], response.json()


def test_the_status_buckets_partition_every_live_site(busiest):
    """recruiting + other_stated + not_stated must equal the total exactly.

    An overlap double-counts a site; a gap loses one. Both leave a total
    that still looks plausible, which is why this is asserted rather than
    eyeballed."""
    nct_id, body = busiest
    sites = body["sites"]
    assert sites["recruiting"] + sites["other_stated"] + sites["not_stated"] == sites["total"], (
        f"{nct_id}: the three status buckets do not add up to the site total"
    )


def test_an_unstated_status_reaches_the_page_as_nothing(cur, busiest):
    """The mutation this file exists for.

    Every site the registry gave no status for must arrive as null. Anything
    else — 'NOT_RECRUITING', 'UNKNOWN', an empty string — is TrialLens
    quoting ClinicalTrials.gov saying something it never said (CLAUDE.md
    sec. 2), and it renders as a closed site to a researcher deciding
    whether to phone."""
    nct_id, body = busiest
    stated_in_db = one(
        cur,
        """
        SELECT count(*) AS stated
        FROM trial_sites
        WHERE nct_id = %s AND delisted_at IS NULL
          AND nullif(trim(recruitment_status), '') IS NOT NULL
        """,
        (nct_id,),
    )["stated"]

    listed = body["sites"]["listed"]
    assert listed, f"{nct_id} returned no sites to check"
    with_a_status = [s for s in listed if s["status"] is not None]
    assert len(with_a_status) <= stated_in_db, (
        f"{nct_id}: the response reports {len(with_a_status)} sites with a status "
        f"among {len(listed)} listed, but only {stated_in_db} of its sites have one "
        "on file — an unstated status is being filled in"
    )
    if stated_in_db == 0:
        assert all(s["status"] is None for s in listed), (
            f"{nct_id}: no site on file has a stated status, yet the response "
            "supplied one"
        )


def test_the_status_counts_match_the_database(cur, busiest):
    """The buckets adding up is not the same as their being right — 0/0/N
    adds up perfectly while reporting every site as unstated."""
    nct_id, body = busiest
    # Collapsed to canonical sites first, the way the endpoint counts since
    # the merge. Comparing against raw edges passed only because this
    # particular trial happens to have no duplicate spellings — an
    # invariant that is true by luck is not an invariant.
    real = one(
        cur,
        """
        WITH live AS (
            SELECT CASE WHEN count(DISTINCT nullif(trim(ts.recruitment_status), '')) = 1
                         AND count(*) FILTER (
                                 WHERE nullif(trim(ts.recruitment_status), '') IS NULL) = 0
                        THEN max(nullif(trim(ts.recruitment_status), ''))
                        ELSE NULL END AS status
            FROM trial_sites ts
            JOIN sites s ON s.id = ts.site_id
            WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
            GROUP BY coalesce(s.canonical_id, s.id)
        )
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status = 'RECRUITING') AS recruiting,
               count(*) FILTER (WHERE status IS NOT NULL AND status <> 'RECRUITING')
                   AS other_stated,
               count(*) FILTER (WHERE status IS NULL) AS not_stated
        FROM live
        """,
        (nct_id,),
    )
    sites = body["sites"]
    for field in ("total", "recruiting", "other_stated", "not_stated"):
        assert sites[field] == real[field], (
            f"{nct_id}: {field} is {sites[field]} but the database says {real[field]}"
        )


def test_the_country_rollup_accounts_for_every_site(busiest):
    """Countries are returned uncapped, so their sites must sum to the
    total. A rollup that quietly loses a country reports a trial running in
    fewer places than it does."""
    nct_id, body = busiest
    sites = body["sites"]
    assert sum(place["sites"] for place in sites["countries"]) == sites["total"], (
        f"{nct_id}: the per-country counts do not sum to the site total"
    )


def test_cities_total_is_the_real_denominator_not_the_capped_list(cur, busiest):
    """The cap applies to the rows returned, never to the count reported."""
    nct_id, body = busiest
    real = one(
        cur,
        """
        -- Normalised, as the rollup groups: 'Heraklion - Crete' and
        -- 'Heraklion, Crete' are one city, and counting them as two
        -- reported a trial running in more places than it does.
        SELECT count(*) AS cities FROM (
            SELECT btrim(regexp_replace(lower(coalesce(s.country, '')),
                                        '[^a-z0-9]+', ' ', 'g')) AS k,
                   btrim(regexp_replace(lower(coalesce(s.city, '')),
                                        '[^a-z0-9]+', ' ', 'g')) AS c
            FROM trial_sites ts JOIN sites s ON s.id = ts.site_id
            WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
            GROUP BY 1, 2
        ) grouped
        """,
        (nct_id,),
    )["cities"]

    sites = body["sites"]
    assert sites["cities_total"] == real
    assert len(sites["cities"]) <= real
    if len(sites["cities"]) < real:
        assert sites["cities_total"] > len(sites["cities"]), (
            f"{nct_id}: the city list is capped but reports its own length as the total"
        )


def test_the_unplaceable_count_matches_the_sites_with_no_coordinates(cur, busiest):
    """1,659 sites have no geoPoint. A map drawn without saying so shows a
    smaller trial than the one on file — the step-4 under-reporting bug."""
    nct_id, body = busiest
    real = one(
        cur,
        """
        SELECT count(*) AS unplaceable
        FROM trial_sites ts JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
          AND (s.lat IS NULL OR s.lon IS NULL)
        """,
        (nct_id,),
    )["unplaceable"]
    assert body["sites"]["unplaceable"] == real


def test_a_truncated_list_says_so_against_the_real_total(busiest):
    """The busiest trial is far past the cap by construction, so this is the
    one trial where truncation must never report False."""
    nct_id, body = busiest
    sites = body["sites"]
    assert sites["total"] > len(sites["listed"])
    assert sites["listed_truncated"] is True, (
        f"{nct_id} returned {len(sites['listed'])} of {sites['total']} sites "
        "without flagging the list as a sample"
    )


def test_no_live_site_list_contains_a_dropped_location(cur, with_dropped_sites):
    """A delisted edge is a location the record stopped listing. Counting it
    among the live ones says the trial still runs there."""
    nct_id, body = with_dropped_sites
    sites = body["sites"]

    real = one(
        cur,
        """
        SELECT count(*) FILTER (WHERE delisted_at IS NULL) AS live,
               count(*) FILTER (WHERE delisted_at IS NOT NULL) AS dropped
        FROM trial_sites WHERE nct_id = %s
        """,
        (nct_id,),
    )
    assert sites["total"] == real["live"]
    assert sites["delisted"] == real["dropped"] > 0
    assert all(s["delisted_at"] is None for s in sites["listed"])
    assert all(s["delisted_at"] is not None for s in sites["delisted_sites"])


def test_other_trials_excludes_the_trial_being_explored(cur, busiest):
    """"Also on 578 others" must not silently include this one. Off by one
    here is invisible on screen and wrong on every row."""
    nct_id, body = busiest
    if not body["organizations"]:
        pytest.skip(f"{nct_id} has no organization edges")

    org = body["organizations"][0]
    real = one(
        cur,
        """
        SELECT count(DISTINCT x.nct_id) AS others
        FROM trial_organizations x JOIN organizations o ON o.id = x.org_id
        WHERE o.name = %s AND x.delisted_at IS NULL AND x.nct_id <> %s
        """,
        (org["name"], nct_id),
    )["others"]
    assert org["other_trials"] == real, (
        f"{org['name']}: response says {org['other_trials']} other trials, "
        f"database says {real}"
    )


def test_the_neighbour_total_is_the_real_two_hop_count(cur, busiest):
    """The whole capability, checked against the database that answers it.

    A cap that also caps the denominator is the failure mode: ten of 1,497
    reported as ten. That reads as a small, quiet trial and is the step-4
    under-reporting bug wearing Explore's clothes."""
    nct_id, body = busiest
    real = one(
        cur,
        """
        -- Through canonical identity, as the endpoint hops since the merge.
        -- Two trials at one hospital spelled differently did not register as
        -- sharing it before, so this total legitimately GREW (1,497 -> 1,624
        -- for the busiest trial on 2026-09-04). A test still asserting the
        -- raw-edge number would be pinning the bug in place.
        WITH mine AS (
            SELECT DISTINCT coalesce(s.canonical_id, s.id) AS k
            FROM trial_sites ts JOIN sites s ON s.id = ts.site_id
            WHERE ts.nct_id = %(nct)s AND ts.delisted_at IS NULL
        )
        SELECT count(DISTINCT ts.nct_id) AS neighbours
        FROM trial_sites ts
        JOIN sites s2 ON s2.id = ts.site_id
        JOIN mine ON mine.k = coalesce(s2.canonical_id, s2.id)
        WHERE ts.delisted_at IS NULL AND ts.nct_id <> %(nct)s
        """,
        {"nct": nct_id},
    )["neighbours"]

    neighbours = body["neighbours"]
    assert neighbours["by_site_total"] == real
    assert len(neighbours["by_site"]) <= real


def test_a_neighbour_is_never_the_trial_itself(busiest):
    """Every trial shares every one of its own sites with itself. Without the
    exclusion the anchor trial tops its own neighbour list, which looks
    plausible and is meaningless."""
    nct_id, body = busiest
    for via in ("by_site", "by_investigator", "by_intervention"):
        assert all(n["nct_id"] != nct_id for n in body["neighbours"][via]), (
            f"{nct_id} appears in its own {via} list"
        )


def test_neighbours_are_ordered_by_shared_count(busiest):
    """The ordering IS the ranking, and it is a plain count of source facts
    rather than a score. If it were unsorted, the cap would return ten
    arbitrary trials while implying they were the strongest links."""
    nct_id, body = busiest
    for via in ("by_site", "by_investigator", "by_intervention"):
        shared = [n["shared"] for n in body["neighbours"][via]]
        assert shared == sorted(shared, reverse=True), f"{nct_id}: {via} is not ordered"


def test_a_site_neighbour_reports_conditions_rather_than_a_match_count(cur, busiest):
    """The tags shown must be the neighbour's own, straight from
    study_conditions — not a count, and not the anchor trial's."""
    nct_id, body = busiest
    site_neighbours = body["neighbours"]["by_site"]
    if not site_neighbours:
        pytest.skip(f"{nct_id} reaches no other trial through a shared site")

    neighbour = site_neighbours[0]
    cur.execute(
        "SELECT condition FROM study_conditions WHERE nct_id = %s ORDER BY condition",
        (neighbour["nct_id"],),
    )
    real = [row["condition"] for row in cur.fetchall()]
    assert neighbour["conditions"] == real[: len(neighbour["conditions"])]
    assert len(neighbour["conditions"]) <= len(real)


def test_an_unknown_trial_is_404_against_the_real_database(client):
    """The fake-connection suite proves the route raises 404 when its query
    returns nothing. This proves the query really does return nothing for an
    nct_id that does not exist, rather than matching some row."""
    response = client.get("/explore/NCT00000000")
    assert response.status_code == 404


def test_the_site_total_counts_canonical_sites_not_raw_edges(cur, busiest):
    """Step 8 unit 3, seen through the endpoint.

    Before the merge, 11 spellings of one Guangzhou hospital were 11 sites,
    and 54 (trial, site) pairs listed the same hospital twice in one trial —
    an inflated count and a visibly duplicated row. The endpoint must report
    the collapsed number, or the merge is another layer nobody can see."""
    nct_id, body = busiest
    real = one(
        cur,
        """
        SELECT count(*) AS raw_edges,
               count(DISTINCT coalesce(s.canonical_id, s.id)) AS canonical_sites
        FROM trial_sites ts JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
        """,
        (nct_id,),
    )
    assert body["sites"]["total"] == real["canonical_sites"], (
        f"{nct_id}: the endpoint reports {body['sites']['total']} sites but "
        f"{real['canonical_sites']} distinct canonical sites exist"
    )


def test_a_collapsed_site_with_conflicting_statuses_reports_none(cur, busiest):
    """Two rows for one hospital can carry different recruitment statuses.
    Picking one would invent a fact, so disagreement resolves to "not
    stated" — the same answer a disputed geoPoint gets."""
    nct_id, body = busiest
    cur.execute(
        """
        SELECT count(*) AS conflicted FROM (
            SELECT coalesce(s.canonical_id, s.id) AS cid
            FROM trial_sites ts JOIN sites s ON s.id = ts.site_id
            WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
            GROUP BY 1
            HAVING count(DISTINCT nullif(trim(ts.recruitment_status), '')) > 1
        ) c
        """,
        (nct_id,),
    )
    conflicted = cur.fetchone()["conflicted"]
    stated = body["sites"]["recruiting"] + body["sites"]["other_stated"]
    total = body["sites"]["total"]
    assert stated + body["sites"]["not_stated"] == total
    if conflicted:
        assert body["sites"]["not_stated"] >= conflicted, (
            f"{nct_id}: {conflicted} collapsed site(s) have conflicting statuses "
            "but were not reported as unstated"
        )


@pytest.fixture(scope="module")
def with_duplicate_sites(cur, client):
    """A trial whose raw site edges outnumber its canonical sites.

    The busiest trial does NOT have this property, so every merge assertion
    written against it passed whether or not the endpoint read through
    canonical_id at all — a mutation removing that join was caught by
    nothing. An invariant that holds by luck is not an invariant, so this
    fixture picks a trial where the two numbers genuinely differ."""
    row = one(
        cur,
        """
        SELECT ts.nct_id,
               count(*) AS raw_edges,
               count(DISTINCT coalesce(s.canonical_id, s.id)) AS canonical_sites
        FROM trial_sites ts JOIN sites s ON s.id = ts.site_id
        WHERE ts.delisted_at IS NULL
        GROUP BY 1
        HAVING count(*) <> count(DISTINCT coalesce(s.canonical_id, s.id))
        ORDER BY count(*) - count(DISTINCT coalesce(s.canonical_id, s.id)) DESC,
                 ts.nct_id
        LIMIT 1
        """,
    )
    if row is None:
        pytest.skip("no trial currently lists the same site under two spellings")
    response = client.get(f"/explore/{row['nct_id']}")
    assert response.status_code == 200
    return row, response.json()


def test_a_duplicated_site_is_counted_once(cur, with_duplicate_sites):
    """The merge, where it actually changes a number a researcher reads.

    Real case on 2026-09-04: NCT01740427 held 299 site edges for 292 real
    places. Before the merge the page said 299 and showed seven duplicated
    rows."""
    row, body = with_duplicate_sites
    assert row["raw_edges"] > row["canonical_sites"], "fixture picked a trial with no duplicates"
    assert body["sites"]["total"] == row["canonical_sites"], (
        f"{row['nct_id']}: endpoint reports {body['sites']['total']} sites but "
        f"{row['canonical_sites']} distinct places exist among "
        f"{row['raw_edges']} edges — the read is not going through canonical_id"
    )


def test_a_duplicated_site_appears_once_in_the_listed_sites(with_duplicate_sites):
    """Not just the count: the visible list must not repeat the hospital
    either, which is what a researcher scanning for somewhere to phone
    actually sees."""
    row, body = with_duplicate_sites
    listed = body["sites"]["listed"]
    identities = [(s["facility"], s["city"], s["country"]) for s in listed]
    assert len(identities) == len(set(identities)), (
        f"{row['nct_id']}: the site list repeats a place"
    )
