"""The Explore graph against the live database — does it faithfully mirror
what the registry actually said?

The extraction in scripts/backfill_graph_entities.py has exactly two ways to
be wrong, and they are opposites:

  - It can INVENT — an organization, site, person or term in the graph that
    no stored record contains. Then Explore shows a researcher a connection
    that does not exist (CLAUDE.md sec. 2).
  - It can LOSE — a source value with no row, or an edge pointing nowhere.
    Then "who else works in this space?" quietly returns a short answer, and
    a short answer looks exactly like a complete one.

Both are judged against LIVE edges (`withdrawn_at IS NULL`). An edge the
current record no longer justifies is stamped, not deleted, so a site a trial
dropped stays visible as a finding — see the withdrawn-edges block in
db/schema.sql. "Traces to nothing" is therefore only a fault when the edge
still claims to be live.

Every test here is one of those two, plus a third thing worth its own name:
the graph is a snapshot, and ingestion keeps moving. test_the_graph_is_not_
behind_the_studies_it_describes is not a correctness test — it is the
freshness signal that says the backfill needs re-running (or that keeping it
in sync needs to stop being a manual step).

Deliberately NOT asserted: that similar values were merged. Nothing is
merged at this stage on purpose — 381 Madrid facility strings are 381 rows.
See docs/decisions.md, 2026-09-02, and the schema comment.

Free — read-only, no model, no network beyond Neon. Skipped cleanly when
DATABASE_URL_READONLY isn't set, so CI without credentials stays green.

Run: PYTHONPATH=. python3 -m pytest tests/test_graph_entities_real_data.py -v
"""
import os

import psycopg2
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

OFFICIALS = "raw_json->'protocolSection'->'contactsLocationsModule'->'overallOfficials'"
COLLABORATORS = "raw_json->'protocolSection'->'sponsorCollaboratorsModule'->'collaborators'"
# The raw array, not the normalized `locations` column — the parser kept only
# facility/city/country and dropped geoPoint, zip, state and status, so the
# enrichment checks have to read the record those came from.
RAW_LOCATIONS = "raw_json->'protocolSection'->'contactsLocationsModule'->'locations'"


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as c:
            yield c
    finally:
        conn.close()


def scalar(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def test_the_graph_has_actually_been_populated(cur):
    """Guards the failure every other test in this file would hide: an empty
    table satisfies "invented nothing" perfectly. Concepts #45 — a table that
    was never filled and one with nothing to fill it look identical."""
    for table in ("organizations", "trial_organizations", "sites", "trial_sites",
                  "investigators", "trial_investigators", "intervention_terms",
                  "trial_interventions"):
        assert scalar(cur, f"SELECT count(*) FROM {table}") > 0, (
            f"{table} is empty — scripts/backfill_graph_entities.py has not run "
            "against this database, and the assertions below would all pass "
            "vacuously"
        )


def test_no_organization_was_invented(cur):
    """Every organization name must appear in a stored record as either a
    lead sponsor or a collaborator. A name here that is in neither means the
    extraction fabricated a node."""
    invented = scalar(cur, f"""
        SELECT count(*) FROM organizations o
        WHERE NOT EXISTS (SELECT 1 FROM studies s WHERE s.lead_sponsor = o.name)
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.{COLLABORATORS}) col
            WHERE s.{COLLABORATORS} IS NOT NULL AND col->>'name' = o.name)
    """)
    assert invented == 0, f"{invented} organizations trace to no stored record"


def test_no_site_was_invented(cur):
    """Scoped to sites that still hold a LIVE edge.

    A site reachable only through withdrawn edges is *supposed* to trace to no
    current location — that is what withdrawn means. Before `withdrawn_at`
    existed this test read every site and went red on 7 real ones that trials
    had simply dropped, calling them inventions. They were reported once and
    later removed, which is a different thing and worth keeping.
    """
    invented = scalar(cur, """
        SELECT count(*) FROM sites si
        WHERE EXISTS (
            SELECT 1 FROM trial_sites ts
            WHERE ts.site_id = si.id AND ts.withdrawn_at IS NULL)
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.locations) loc
            WHERE s.locations IS NOT NULL
              AND coalesce(loc->>'facility','') = coalesce(si.facility,'')
              AND coalesce(loc->>'city','')     = coalesce(si.city,'')
              AND coalesce(loc->>'country','')  = coalesce(si.country,''))
    """)
    assert invented == 0, f"{invented} live-edged sites trace to no stored location"


def test_no_intervention_term_was_invented(cur):
    invented = scalar(cur, """
        SELECT count(*) FROM intervention_terms t WHERE NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.interventions) iv
            WHERE s.interventions IS NOT NULL
              AND iv->>'name' = t.name AND iv->>'type' = t.type)
    """)
    assert invented == 0, f"{invented} terms trace to no stored intervention"


def test_every_lead_sponsor_on_file_reached_the_graph(cur):
    """The losing direction. A trial whose sponsor never became an edge is
    invisible to "who else does this sponsor run?" — and the answer that
    comes back looks complete."""
    missing = scalar(cur, """
        SELECT count(*) FROM studies s
        WHERE s.lead_sponsor IS NOT NULL AND btrim(s.lead_sponsor) <> ''
          AND NOT EXISTS (
            SELECT 1 FROM trial_organizations t
            WHERE t.nct_id = s.nct_id AND t.role = 'LEAD')
    """)
    assert missing == 0, f"{missing} trials have a lead sponsor but no LEAD edge"


def test_every_stored_official_with_a_role_reached_the_graph(cur):
    """66% of trials carry overallOfficials and nothing read them until now.
    If the JSON path is wrong, this file's other tests still pass — invented
    nothing, lost nothing it knew about — while two thirds of the people in
    the graph are simply absent."""
    missing = scalar(cur, f"""
        SELECT count(*) FROM (
          SELECT DISTINCT s.nct_id, off->>'name' AS name,
                 coalesce(off->>'affiliation','') AS aff, off->>'role' AS role
          FROM studies s, jsonb_array_elements(s.{OFFICIALS}) off
          WHERE s.{OFFICIALS} IS NOT NULL AND off->>'role' IS NOT NULL
            AND off->>'name' IS NOT NULL AND btrim(off->>'name') <> '') src
        WHERE NOT EXISTS (
          SELECT 1 FROM trial_investigators ti JOIN investigators i ON i.id = ti.investigator_id
          WHERE ti.nct_id = src.nct_id AND i.name = src.name
            AND coalesce(i.affiliation,'') = src.aff AND ti.role = src.role)
    """)
    assert missing == 0, f"{missing} stored officials never became an edge"


def test_no_edge_points_at_a_trial_that_is_gone(cur):
    """Foreign keys enforce this, so a failure here means the constraint was
    dropped or the table was built without it — worth catching, because the
    symptom downstream is a query returning rows for a trial that no longer
    exists."""
    for table in ("trial_organizations", "trial_sites", "trial_investigators",
                  "trial_interventions"):
        orphans = scalar(cur, f"""
            SELECT count(*) FROM {table} t
            WHERE NOT EXISTS (SELECT 1 FROM studies s WHERE s.nct_id = t.nct_id)
        """)
        assert orphans == 0, f"{table} has {orphans} edges pointing at no trial"


def test_one_organization_can_hold_both_roles(cur):
    """The schema decision, checked on real data: lead sponsors and
    collaborators share one table because 887 names are both. If this returns
    zero, either the collaborator extraction is not running or the design
    argument was wrong — and each is worth knowing."""
    both = scalar(cur, """
        SELECT count(*) FROM (
          SELECT org_id FROM trial_organizations GROUP BY org_id
          HAVING count(DISTINCT role) > 1) s
    """)
    assert both > 0, (
        "no organization appears as both LEAD and COLLABORATOR — the one-table "
        "design rests on that overlap existing"
    )


def test_nothing_was_merged(cur):
    """The deliberate not-yet-done. If a later change starts collapsing
    surface forms, it must be a decision someone made on purpose, not a quiet
    side effect — so this fails loudly the first time it happens."""
    semaglutide_terms = scalar(cur, """
        SELECT count(*) FROM intervention_terms WHERE lower(name) LIKE 'semaglutide%'
    """)
    assert semaglutide_terms > 1, (
        "semaglutide collapsed to one term — merging is supposed to happen in "
        "its own reversible step, checked against this unmerged baseline"
    )


def test_every_live_edge_is_justified_by_the_current_record(cur):
    """The invariant the whole withdrawal mechanism exists to hold: if an edge
    says a trial connects to something, the trial's stored record says so too.

    This is the one that matters for CLAUDE.md sec. 2. A stale live edge is
    Explore telling a researcher a trial runs at a site it dropped — a
    connection the registry does not state, presented as if it does. One
    6-hour monitor run produced 15 of them before `withdrawn_at` existed.
    """
    stale_sites = scalar(cur, """
        SELECT count(*) FROM trial_sites ts JOIN sites si ON si.id = ts.site_id
        WHERE ts.withdrawn_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.locations) loc
            WHERE s.nct_id = ts.nct_id AND s.locations IS NOT NULL
              AND coalesce(loc->>'facility','') = coalesce(si.facility,'')
              AND coalesce(loc->>'city','')     = coalesce(si.city,'')
              AND coalesce(loc->>'country','')  = coalesce(si.country,''))
    """)
    assert stale_sites == 0, (
        f"{stale_sites} live trial_sites edges name a location the trial's "
        "record no longer lists — re-run scripts/backfill_graph_entities.py"
    )

    stale_terms = scalar(cur, """
        SELECT count(*) FROM trial_interventions ti
        JOIN intervention_terms t ON t.id = ti.term_id
        WHERE ti.withdrawn_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.interventions) iv
            WHERE s.nct_id = ti.nct_id AND s.interventions IS NOT NULL
              AND iv->>'name' = t.name AND iv->>'type' = t.type)
    """)
    assert stale_terms == 0, f"{stale_terms} live intervention edges are unsupported"

    stale_leads = scalar(cur, """
        SELECT count(*) FROM trial_organizations tor
        JOIN organizations o ON o.id = tor.org_id
        WHERE tor.role = 'LEAD' AND tor.withdrawn_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM studies s
            WHERE s.nct_id = tor.nct_id AND s.lead_sponsor = o.name)
    """)
    assert stale_leads == 0, f"{stale_leads} live LEAD edges name a different sponsor"


def test_a_dropped_connection_is_stamped_rather_than_deleted(cur):
    """The decision, checked on real data (2026-09-03).

    Withdrawal must be reversible and inspectable. If a later change starts
    DELETEing instead, live counts still reconcile perfectly and this is the
    only thing that notices the history is gone.

    Asserted as "the column works and nothing is in the future" rather than
    "> 0 rows are withdrawn": a database freshly backfilled from a quiet week
    legitimately has none, and a test that demands churn would fail on a
    correct system.
    """
    future = scalar(cur, """
        SELECT count(*) FROM trial_sites WHERE withdrawn_at > now()
    """)
    assert future == 0, f"{future} edges are withdrawn at a future date"

    # A withdrawn edge must still point at a real entity — the row is kept
    # precisely so the connection stays inspectable.
    dangling = scalar(cur, """
        SELECT count(*) FROM trial_sites ts
        WHERE ts.withdrawn_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM sites si WHERE si.id = ts.site_id)
    """)
    assert dangling == 0, f"{dangling} withdrawn edges lost their site"


def test_the_graph_is_not_behind_the_studies_it_describes(cur):
    """NOT a correctness test — a freshness signal.

    The backfill is a snapshot and ingestion keeps running, so a trial
    ingested after the last backfill has no edges at all. That is not a bug
    in the extraction; it is the absence of a sync step. This test names the
    gap so it stays visible instead of being discovered later as "Explore is
    missing recent trials".
    """
    unrepresented = scalar(cur, """
        SELECT count(*) FROM studies s
        WHERE s.active_in_scope
          AND NOT EXISTS (SELECT 1 FROM trial_organizations t WHERE t.nct_id = s.nct_id)
          AND NOT EXISTS (SELECT 1 FROM trial_sites t WHERE t.nct_id = s.nct_id)
          AND NOT EXISTS (SELECT 1 FROM trial_interventions t WHERE t.nct_id = s.nct_id)
    """)
    assert unrepresented == 0, (
        f"{unrepresented} in-scope trials have no edges of any kind — the graph "
        "is behind the studies table. Re-run scripts/backfill_graph_entities.py, "
        "and if this keeps recurring the backfill needs to become part of the "
        "monitor run rather than a manual step"
    )


# ---------------------------------------------------------------------------
# Site enrichment (2026-09-03): state, zip, coordinates and per-edge
# recruitment status, all backfilled from raw_json. These are the fields the
# evidence review put first — sites reach 93.8% of trials and answer the
# "is it still open here?" question clinicians currently phone sites about.
# ---------------------------------------------------------------------------


def test_the_enrichment_actually_ran(cur):
    """The #45 guard again, one layer down. Every assertion below is about
    values being correct; all of them pass vacuously against a column that
    was added and never populated."""
    with_geo = scalar(cur, "SELECT count(*) FROM sites WHERE lat IS NOT NULL")
    assert with_geo > 0, (
        "no site has coordinates — the enrichment step in "
        "scripts/backfill_graph_entities.py has not run against this database"
    )
    with_status = scalar(
        cur, "SELECT count(*) FROM trial_sites WHERE recruitment_status IS NOT NULL"
    )
    assert with_status > 0, "no edge carries a recruitment status"


def test_coordinates_are_on_the_planet(cur):
    """Catches the parse failure that a NOT NULL check cannot: a lat/lon
    swap, or a string that cast to something absurd. A site at lat 120 is not
    a slightly-wrong site, it is a broken one."""
    off_globe = scalar(cur, """
        SELECT count(*) FROM sites
        WHERE (lat IS NOT NULL AND (lat < -90 OR lat > 90))
           OR (lon IS NOT NULL AND (lon < -180 OR lon > 180))
    """)
    assert off_globe == 0, f"{off_globe} sites have impossible coordinates"

    half_a_point = scalar(cur, """
        SELECT count(*) FROM sites
        WHERE (lat IS NULL) <> (lon IS NULL)
    """)
    assert half_a_point == 0, (
        f"{half_a_point} sites have one coordinate but not the other — a point "
        "with half its pair is not a location"
    )


def test_latitude_and_longitude_were_not_swapped(cur):
    """A swap survives the range check, because most latitudes are also legal
    longitudes. Continental US sites are the cheap discriminator: they sit
    around lat 24..50, lon -125..-66. Swapped, every one of them lands at a
    longitude no US site has.
    """
    us_sane = scalar(cur, """
        SELECT count(*) FROM sites
        WHERE country = 'United States' AND lat IS NOT NULL
          AND lat BETWEEN 18 AND 72 AND lon BETWEEN -180 AND -65
    """)
    us_total = scalar(cur, """
        SELECT count(*) FROM sites
        WHERE country = 'United States' AND lat IS NOT NULL
    """)
    assert us_total > 0, "no US site has coordinates — cannot check orientation"
    assert us_sane / us_total > 0.95, (
        f"only {us_sane} of {us_total} US sites fall in US bounds — lat and lon "
        "look transposed"
    )


def test_no_coordinate_was_invented_where_the_records_disagree(cur):
    """The rule the schema promises, checked rather than trusted.

    109 site identities are reported at more than one geoPoint, and the
    disagreement is real — 103 are 5km or further apart. Those must hold NULL.
    A stored value there would be a guess presented as a location, and on a
    "trials near me" map a guess sends someone to the wrong country.
    """
    # Built as a CTE joined once, never a correlated subquery. The obvious
    # per-site EXISTS re-expands all 142,777 location objects for each of the
    # 51,272 sites and the backend is OOM-killed (exit 137) rather than
    # failing with anything readable.
    guessed = scalar(cur, f"""
        WITH disputed AS (
            SELECT loc->>'facility' f, loc->>'city' c, loc->>'country' k
            FROM studies, jsonb_array_elements({RAW_LOCATIONS}) loc
            WHERE {RAW_LOCATIONS} IS NOT NULL AND loc->'geoPoint' IS NOT NULL
            GROUP BY 1, 2, 3
            HAVING count(DISTINCT ((loc->'geoPoint'->>'lat'),
                                   (loc->'geoPoint'->>'lon'))) > 1)
        SELECT count(*) FROM sites si JOIN disputed d
          ON coalesce(si.facility,'') = coalesce(d.f,'')
         AND coalesce(si.city,'')     = coalesce(d.c,'')
         AND coalesce(si.country,'')  = coalesce(d.k,'')
        WHERE si.lat IS NOT NULL
    """)
    assert guessed == 0, (
        f"{guessed} sites hold coordinates their own records disagree about"
    )


def test_every_recruitment_status_is_one_the_record_states(cur):
    """The inventing direction, for the field a clinician would act on.

    A wrong RECRUITING here is worse than a missing one: it says a trial is
    open at a site when the registry never said so (CLAUDE.md sec. 2).
    """
    # Same shape as the coordinate check: expand the JSON once into a CTE,
    # then anti-join. Correlating it per edge expands 142,777 objects for each
    # of 140,022 edges.
    invented = scalar(cur, f"""
        WITH stated AS (
            SELECT DISTINCT s.nct_id nct, loc->>'facility' f, loc->>'city' c,
                   loc->>'country' k, loc->>'status' st
            FROM studies s, jsonb_array_elements(s.{RAW_LOCATIONS}) loc
            WHERE s.{RAW_LOCATIONS} IS NOT NULL AND loc->>'status' IS NOT NULL)
        SELECT count(*) FROM trial_sites ts
        JOIN sites si ON si.id = ts.site_id
        WHERE ts.recruitment_status IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM stated
            WHERE stated.nct = ts.nct_id
              AND coalesce(stated.f,'') = coalesce(si.facility,'')
              AND coalesce(stated.c,'') = coalesce(si.city,'')
              AND coalesce(stated.k,'') = coalesce(si.country,'')
              AND stated.st = ts.recruitment_status)
    """)
    assert invented == 0, (
        f"{invented} edges claim a recruitment status no stored record states"
    )


def test_recruitment_status_vocabulary_is_still_what_we_expect(cur):
    """Data drift, which is why this file runs in monitor.yml on the data's
    schedule. A new CT.gov status value is not a code bug — it is the registry
    changing under us, and anything rendering these needs to know.

    ENROLLING_BY_INVITATION was already a surprise: it appears 10 times and
    was absent from the first sample taken while designing the column.
    """
    known = {
        "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING",
        "SUSPENDED", "WITHDRAWN", "COMPLETED", "TERMINATED",
        "ENROLLING_BY_INVITATION", "AVAILABLE", "NO_LONGER_AVAILABLE",
        "TEMPORARILY_NOT_AVAILABLE", "APPROVED_FOR_MARKETING",
    }
    cur.execute("""
        SELECT DISTINCT recruitment_status FROM trial_sites
        WHERE recruitment_status IS NOT NULL
    """)
    seen = {r[0] for r in cur.fetchall()}
    assert seen <= known, f"unknown per-site status value(s): {sorted(seen - known)}"
