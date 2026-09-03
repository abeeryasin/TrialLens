"""Populate the Explore graph tables from records already on file
(step 8 unit 2, 2026-09-03).

No CT.gov calls. Every value here is either a normalized column or already
sitting in `studies.raw_json` — investigators (7,645 trials) and
collaborators (4,309) have been stored since ingestion and never read, the
same way `has_results` was. CLAUDE.md sec. 4's keep-the-raw-record rule
paying for itself a third time.

NOTHING IS MERGED HERE. Each distinct source value becomes one row, so the
381 Madrid facility strings become 381 sites and the 55 semaglutide names
become 55 terms. That is the point: the unmerged extraction is the baseline
any later merge gets checked against, and it is the only record of what the
registry actually said (CLAUDE.md sec. 3).

Idempotent. Entity inserts are ON CONFLICT DO NOTHING and edge inserts are
ON CONFLICT DO UPDATE that only clears a withdrawal stamp, so re-running
writes only what actually changed. Safe to run again after an ingest — and it
needs to be: the graph is a snapshot, and a trial ingested since the last run
has no edges until this runs again.

Edges are never deleted. An edge the current record no longer justifies gets
`withdrawn_at` stamped instead, because a trial dropping a site is a finding
in a watch-over-time product rather than a row to tidy away. See the
withdrawn-edges block in db/schema.sql.

One of sec. 5's one-time administrative scripts, so it holds DATABASE_URL
directly rather than going through FastAPI.

Run:
    .venv/bin/python scripts/backfill_graph_entities.py
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

OFFICIALS = "raw_json->'protocolSection'->'contactsLocationsModule'->'overallOfficials'"
COLLABORATORS = "raw_json->'protocolSection'->'sponsorCollaboratorsModule'->'collaborators'"
LEAD_CLASS = "raw_json->'protocolSection'->'sponsorCollaboratorsModule'->'leadSponsor'->>'class'"

# The raw locations array, NOT the normalized `locations` column. The parser
# reduced that column to facility/city/country and dropped geoPoint, zip,
# state, status and contacts, so the enrichment below has to read the record
# it came from. Entity and edge identity still comes from the column, which
# carries the same three fields — this only adds attributes to rows that
# already exist.
RAW_LOCATIONS = "raw_json->'protocolSection'->'contactsLocationsModule'->'locations'"

# Site identity, spelled once. Every join below matches on the same coalesced
# triple the idx_sites_identity index uses; writing it out per query is how
# the two drift apart.
SITE_MATCH = """
       coalesce(si.facility,'') = coalesce(loc->>'facility','')
   AND coalesce(si.city,'')     = coalesce(loc->>'city','')
   AND coalesce(si.country,'')  = coalesce(loc->>'country','')
"""

# Order matters: an entity table must be filled before the edge table that
# joins against it, or the join finds nothing and the edge is silently
# dropped. Each step is (label, SQL) and every write is ON CONFLICT DO
# NOTHING so the whole script can be re-run.
STEPS = [
    ("organizations from lead sponsors", f"""
        INSERT INTO organizations (name)
        SELECT DISTINCT lead_sponsor FROM studies
        WHERE lead_sponsor IS NOT NULL AND btrim(lead_sponsor) <> ''
        ON CONFLICT (name) DO NOTHING
    """),
    ("organizations from collaborators", f"""
        INSERT INTO organizations (name)
        SELECT DISTINCT col->>'name' FROM studies, jsonb_array_elements({COLLABORATORS}) col
        WHERE {COLLABORATORS} IS NOT NULL
          AND col->>'name' IS NOT NULL AND btrim(col->>'name') <> ''
        ON CONFLICT (name) DO NOTHING
    """),
    # Edge inserts un-withdraw on conflict: a site that comes back, or a
    # collaborator re-listed after being dropped, is live again and must lose
    # its stamp. The WHERE on the conflict action keeps this from rewriting
    # every live row on every run — without it each pass would dirty all
    # 140,000 edges to set NULL where NULL already was.
    ("edges: trial -> lead organization", f"""
        INSERT INTO trial_organizations (nct_id, org_id, role, org_class)
        SELECT DISTINCT s.nct_id, o.id, 'LEAD', s.{LEAD_CLASS}
        FROM studies s JOIN organizations o ON o.name = s.lead_sponsor
        WHERE s.lead_sponsor IS NOT NULL
        ON CONFLICT (nct_id, org_id, role) DO UPDATE SET withdrawn_at = NULL
        WHERE trial_organizations.withdrawn_at IS NOT NULL
    """),
    ("edges: trial -> collaborator organizations", f"""
        INSERT INTO trial_organizations (nct_id, org_id, role, org_class)
        SELECT DISTINCT s.nct_id, o.id, 'COLLABORATOR', col->>'class'
        FROM studies s, jsonb_array_elements(s.{COLLABORATORS}) col
        JOIN organizations o ON o.name = col->>'name'
        WHERE s.{COLLABORATORS} IS NOT NULL
        ON CONFLICT (nct_id, org_id, role) DO UPDATE SET withdrawn_at = NULL
        WHERE trial_organizations.withdrawn_at IS NOT NULL
    """),
    ("sites", """
        INSERT INTO sites (facility, city, country)
        SELECT DISTINCT loc->>'facility', loc->>'city', loc->>'country'
        FROM studies, jsonb_array_elements(locations) loc
        WHERE locations IS NOT NULL
        ON CONFLICT (coalesce(facility,''), coalesce(city,''), coalesce(country,''))
        DO NOTHING
    """),
    ("edges: trial -> sites", """
        INSERT INTO trial_sites (nct_id, site_id)
        SELECT DISTINCT s.nct_id, si.id
        FROM studies s, jsonb_array_elements(s.locations) loc
        JOIN sites si
          ON coalesce(si.facility,'') = coalesce(loc->>'facility','')
         AND coalesce(si.city,'')     = coalesce(loc->>'city','')
         AND coalesce(si.country,'')  = coalesce(loc->>'country','')
        WHERE s.locations IS NOT NULL
        ON CONFLICT (nct_id, site_id) DO UPDATE SET withdrawn_at = NULL
        WHERE trial_sites.withdrawn_at IS NOT NULL
    """),
    ("investigators", f"""
        INSERT INTO investigators (name, affiliation)
        SELECT DISTINCT off->>'name', off->>'affiliation'
        FROM studies, jsonb_array_elements({OFFICIALS}) off
        WHERE {OFFICIALS} IS NOT NULL
          AND off->>'name' IS NOT NULL AND btrim(off->>'name') <> ''
        ON CONFLICT (name, coalesce(affiliation,'')) DO NOTHING
    """),
    ("edges: trial -> investigators", f"""
        INSERT INTO trial_investigators (nct_id, investigator_id, role)
        SELECT DISTINCT s.nct_id, i.id, off->>'role'
        FROM studies s, jsonb_array_elements(s.{OFFICIALS}) off
        JOIN investigators i
          ON i.name = off->>'name'
         AND coalesce(i.affiliation,'') = coalesce(off->>'affiliation','')
        WHERE s.{OFFICIALS} IS NOT NULL AND off->>'role' IS NOT NULL
        ON CONFLICT (nct_id, investigator_id, role) DO UPDATE SET withdrawn_at = NULL
        WHERE trial_investigators.withdrawn_at IS NOT NULL
    """),
    ("intervention terms", """
        INSERT INTO intervention_terms (name, type)
        SELECT DISTINCT iv->>'name', iv->>'type'
        FROM studies, jsonb_array_elements(interventions) iv
        WHERE interventions IS NOT NULL
          AND iv->>'name' IS NOT NULL AND btrim(iv->>'name') <> ''
          AND iv->>'type' IS NOT NULL
        ON CONFLICT (name, type) DO NOTHING
    """),
    ("edges: trial -> intervention terms", """
        INSERT INTO trial_interventions (nct_id, term_id)
        SELECT DISTINCT s.nct_id, t.id
        FROM studies s, jsonb_array_elements(s.interventions) iv
        JOIN intervention_terms t ON t.name = iv->>'name' AND t.type = iv->>'type'
        WHERE s.interventions IS NOT NULL
        ON CONFLICT (nct_id, term_id) DO UPDATE SET withdrawn_at = NULL
        WHERE trial_interventions.withdrawn_at IS NOT NULL
    """),
]

# Run AFTER every insert above, never before: an edge is only withdrawn if the
# current record does not justify it, and the inserts are what establish what
# the current record says.
#
# `withdrawn_at IS NULL` in each WHERE makes these idempotent — an edge keeps
# the date it was FIRST seen missing, so re-running the backfill does not keep
# moving the stamp forward and destroying the one piece of timing information
# it has.
#
# Watch the printed counts. These are UPDATEs against the whole edge table,
# and a partial ingest that left `locations` empty on many trials would show
# up here as a mass withdrawal rather than the handful a normal run produces.
WITHDRAWALS = [
    ("withdrawn: lead organization", """
        UPDATE trial_organizations tor SET withdrawn_at = now()
        FROM organizations o
        WHERE o.id = tor.org_id AND tor.role = 'LEAD' AND tor.withdrawn_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM studies s
            WHERE s.nct_id = tor.nct_id AND s.lead_sponsor = o.name)
    """),
    ("withdrawn: collaborator organizations", f"""
        UPDATE trial_organizations tor SET withdrawn_at = now()
        FROM organizations o
        WHERE o.id = tor.org_id AND tor.role = 'COLLABORATOR' AND tor.withdrawn_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.{COLLABORATORS}) col
            WHERE s.nct_id = tor.nct_id AND s.{COLLABORATORS} IS NOT NULL
              AND col->>'name' = o.name)
    """),
    ("withdrawn: sites", """
        UPDATE trial_sites ts SET withdrawn_at = now()
        FROM sites si
        WHERE si.id = ts.site_id AND ts.withdrawn_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.locations) loc
            WHERE s.nct_id = ts.nct_id AND s.locations IS NOT NULL
              AND coalesce(loc->>'facility','') = coalesce(si.facility,'')
              AND coalesce(loc->>'city','')     = coalesce(si.city,'')
              AND coalesce(loc->>'country','')  = coalesce(si.country,''))
    """),
    ("withdrawn: investigators", f"""
        UPDATE trial_investigators ti SET withdrawn_at = now()
        FROM investigators i
        WHERE i.id = ti.investigator_id AND ti.withdrawn_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.{OFFICIALS}) off
            WHERE s.nct_id = ti.nct_id AND s.{OFFICIALS} IS NOT NULL
              AND off->>'name' = i.name
              AND coalesce(off->>'affiliation','') = coalesce(i.affiliation,'')
              AND off->>'role' = ti.role)
    """),
    ("withdrawn: intervention terms", """
        UPDATE trial_interventions ti SET withdrawn_at = now()
        FROM intervention_terms t
        WHERE t.id = ti.term_id AND ti.withdrawn_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.interventions) iv
            WHERE s.nct_id = ti.nct_id AND s.interventions IS NOT NULL
              AND iv->>'name' = t.name AND iv->>'type' = t.type)
    """),
]

# Attributes read from raw_json onto rows the steps above already created.
# These run last: they UPDATE sites and edges, so the rows have to exist.
#
# Each carries `IS DISTINCT FROM` in its WHERE so a re-run rewrites only what
# actually changed, which keeps the printed counts meaningful instead of
# reporting all 51,272 sites touched every time.
ENRICHMENTS = [
    ("sites: state, zip, coordinates (only where records agree)", f"""
        WITH agreed AS (
            SELECT loc->>'facility' f, loc->>'city' c, loc->>'country' k,
                   CASE WHEN count(DISTINCT loc->>'state') = 1
                        THEN min(loc->>'state') END st,
                   CASE WHEN count(DISTINCT loc->>'zip') = 1
                        THEN min(loc->>'zip') END zp,
                   CASE WHEN count(DISTINCT ((loc->'geoPoint'->>'lat'),
                                             (loc->'geoPoint'->>'lon'))) = 1
                        THEN min((loc->'geoPoint'->>'lat')::float8) END la,
                   CASE WHEN count(DISTINCT ((loc->'geoPoint'->>'lat'),
                                             (loc->'geoPoint'->>'lon'))) = 1
                        THEN min((loc->'geoPoint'->>'lon')::float8) END lo
            FROM studies, jsonb_array_elements({RAW_LOCATIONS}) loc
            WHERE {RAW_LOCATIONS} IS NOT NULL
            GROUP BY 1, 2, 3)
        UPDATE sites si
        SET state = a.st, zip = a.zp, lat = a.la, lon = a.lo
        FROM agreed a
        WHERE coalesce(si.facility,'') = coalesce(a.f,'')
          AND coalesce(si.city,'')     = coalesce(a.c,'')
          AND coalesce(si.country,'')  = coalesce(a.k,'')
          AND (si.state IS DISTINCT FROM a.st OR si.zip IS DISTINCT FROM a.zp
            OR si.lat IS DISTINCT FROM a.la OR si.lon IS DISTINCT FROM a.lo)
    """),
    # A CASE returning NULL on disagreement, not a pick. 172 (trial, site)
    # pairs state two statuses at once — a trial listing one facility twice —
    # and "we can't tell" is the only honest value for those.
    ("trial_sites: recruitment status per edge", f"""
        WITH stated AS (
            SELECT s.nct_id nct, loc->>'facility' f, loc->>'city' c,
                   loc->>'country' k,
                   CASE WHEN count(DISTINCT loc->>'status') = 1
                        THEN min(loc->>'status') END st
            FROM studies s, jsonb_array_elements(s.{RAW_LOCATIONS}) loc
            WHERE s.{RAW_LOCATIONS} IS NOT NULL AND loc->>'status' IS NOT NULL
            GROUP BY 1, 2, 3, 4)
        UPDATE trial_sites ts
        SET recruitment_status = stated.st
        FROM stated, sites si
        WHERE ts.nct_id = stated.nct AND ts.site_id = si.id
          AND coalesce(si.facility,'') = coalesce(stated.f,'')
          AND coalesce(si.city,'')     = coalesce(stated.c,'')
          AND coalesce(si.country,'')  = coalesce(stated.k,'')
          AND ts.recruitment_status IS DISTINCT FROM stated.st
    """),
    # The mirror of the withdrawal pass. If a record stops stating a status,
    # the stored one is stale, and leaving it would keep asserting a
    # recruiting state the registry no longer claims.
    ("trial_sites: clear statuses the record no longer states", f"""
        UPDATE trial_sites ts SET recruitment_status = NULL
        FROM sites si
        WHERE ts.site_id = si.id AND ts.recruitment_status IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM studies s, jsonb_array_elements(s.{RAW_LOCATIONS}) loc
            WHERE s.nct_id = ts.nct_id AND s.{RAW_LOCATIONS} IS NOT NULL
              AND {SITE_MATCH} AND loc->>'status' IS NOT NULL)
    """),
]

# Values the extraction cannot represent, counted rather than passed over in
# silence. A row dropped without a number beside it is indistinguishable from
# one that was never there (CLAUDE.md sec. 2).
SKIPPED = [
    ("locations with no facility name", """
        SELECT count(*) FROM studies, jsonb_array_elements(locations) loc
        WHERE locations IS NOT NULL AND loc->>'facility' IS NULL"""),
    ("interventions with no name or no type", """
        SELECT count(*) FROM studies, jsonb_array_elements(interventions) iv
        WHERE interventions IS NOT NULL
          AND (iv->>'name' IS NULL OR btrim(iv->>'name') = '' OR iv->>'type' IS NULL)"""),
    ("officials with no name", f"""
        SELECT count(*) FROM studies, jsonb_array_elements({OFFICIALS}) off
        WHERE {OFFICIALS} IS NOT NULL
          AND (off->>'name' IS NULL OR btrim(off->>'name') = '')"""),
    ("officials with no role (edge not written)", f"""
        SELECT count(*) FROM studies, jsonb_array_elements({OFFICIALS}) off
        WHERE {OFFICIALS} IS NOT NULL AND off->>'role' IS NULL"""),
    # Left NULL because the registry contradicts itself, not because the value
    # is absent. Counted so "no coordinates" never silently means "we picked
    # one and hoped" (CLAUDE.md sec. 2).
    ("sites whose records disagree on coordinates (left NULL)", f"""
        SELECT count(*) FROM (
          SELECT 1 FROM studies, jsonb_array_elements({RAW_LOCATIONS}) loc
          WHERE {RAW_LOCATIONS} IS NOT NULL AND loc->'geoPoint' IS NOT NULL
          GROUP BY loc->>'facility', loc->>'city', loc->>'country'
          HAVING count(DISTINCT ((loc->'geoPoint'->>'lat'),
                                 (loc->'geoPoint'->>'lon'))) > 1) x"""),
    ("sites whose records disagree on zip (left NULL)", f"""
        SELECT count(*) FROM (
          SELECT 1 FROM studies, jsonb_array_elements({RAW_LOCATIONS}) loc
          WHERE {RAW_LOCATIONS} IS NOT NULL AND loc->>'zip' IS NOT NULL
          GROUP BY loc->>'facility', loc->>'city', loc->>'country'
          HAVING count(DISTINCT loc->>'zip') > 1) x"""),
    ("trial/site pairs stating two statuses at once (left NULL)", f"""
        SELECT count(*) FROM (
          SELECT 1 FROM studies s, jsonb_array_elements(s.{RAW_LOCATIONS}) loc
          WHERE s.{RAW_LOCATIONS} IS NOT NULL AND loc->>'status' IS NOT NULL
          GROUP BY s.nct_id, loc->>'facility', loc->>'city', loc->>'country'
          HAVING count(DISTINCT loc->>'status') > 1) x"""),
]

COUNTS = [
    "organizations", "trial_organizations", "sites", "trial_sites",
    "investigators", "trial_investigators", "intervention_terms",
    "trial_interventions",
]


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        # One commit per step, never one transaction around the whole run:
        # an all-or-nothing wrap hides progress and loses everything on a
        # late failure (docs/decisions.md, 2026-08-26).
        for label, sql in STEPS:
            with conn.cursor() as cur:
                cur.execute(sql)
                print(f"  {label}: {cur.rowcount:,} row(s) written", flush=True)
            conn.commit()

        print("\nWithdrawn (in the graph, not in the current record):", flush=True)
        for label, sql in WITHDRAWALS:
            with conn.cursor() as cur:
                cur.execute(sql)
                print(f"  {label}: {cur.rowcount:,} newly stamped", flush=True)
            conn.commit()

        print("\nEnriched from raw_json (no network call):", flush=True)
        for label, sql in ENRICHMENTS:
            with conn.cursor() as cur:
                cur.execute(sql)
                print(f"  {label}: {cur.rowcount:,} row(s) changed", flush=True)
            conn.commit()

        print("\nSkipped, and why:", flush=True)
        with conn.cursor() as cur:
            for label, sql in SKIPPED:
                cur.execute(sql)
                print(f"  {label}: {cur.fetchone()[0]:,}", flush=True)

            print("\nTable totals now:", flush=True)
            for table in COUNTS:
                if table.startswith("trial_"):
                    # Live and withdrawn separately: a single total would hide
                    # the withdrawals inside a number that only ever grows.
                    cur.execute(
                        f"SELECT count(*) FILTER (WHERE withdrawn_at IS NULL),"
                        f" count(*) FILTER (WHERE withdrawn_at IS NOT NULL) FROM {table}"
                    )
                    live, gone = cur.fetchone()
                    print(f"  {table}: {live:,} live, {gone:,} withdrawn", flush=True)
                else:
                    cur.execute(f"SELECT count(*) FROM {table}")
                    print(f"  {table}: {cur.fetchone()[0]:,}", flush=True)

            # Coverage, not just totals: a column that exists and a column
            # that is populated look identical from a row count.
            print("\nSite enrichment coverage:", flush=True)
            cur.execute("""
                SELECT count(*), count(lat), count(state), count(zip) FROM sites
            """)
            total, geo, state, zipc = cur.fetchone()
            for label, n in (("coordinates", geo), ("state", state), ("zip", zipc)):
                print(f"  sites with {label}: {n:,} of {total:,} "
                      f"({100.0 * n / total:.1f}%)", flush=True)
            cur.execute("""
                SELECT count(*) FILTER (WHERE withdrawn_at IS NULL),
                       count(recruitment_status) FILTER (WHERE withdrawn_at IS NULL)
                FROM trial_sites
            """)
            live, with_status = cur.fetchone()
            print(f"  live edges stating a recruitment status: {with_status:,} "
                  f"of {live:,} ({100.0 * with_status / live:.1f}%)", flush=True)
            cur.execute("""
                SELECT recruitment_status, count(*) FROM trial_sites
                WHERE recruitment_status IS NOT NULL AND withdrawn_at IS NULL
                GROUP BY 1 ORDER BY 2 DESC
            """)
            for status, n in cur.fetchall():
                print(f"    {status}: {n:,}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
