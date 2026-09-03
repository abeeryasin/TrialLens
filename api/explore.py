"""Explore: who else works in this space?

The fifth capability, and the first one whose answer is not written down
anywhere. Discover reads a field, Understand reads a record, Monitor reads
a diff — but "who else runs trials at these hospitals" is a connection the
registry never states. It exists only as a repeated string: `lead_sponsor`
holding 'Mayo Clinic' on 134 rows IS 134 edges. Step 8 units 1-2 made those
edges walkable; this router is the first thing that walks them.

**Its own top-level router**, same reasoning as api/changes.py and
api/discover.py: nesting it as /studies/explore would collide with
/studies/{nct_id}, which FastAPI resolves by registration order — a
constraint that has to hold forever and silently breaks when someone
reorders two lines.

Three rules this file exists to keep, all of them from
docs/plan_explore_nodes.md sec. 4b, and all of them a way of not repeating
the step-4 under-reporting bug:

  1. A capped list says it is capped, and says what it was capped from.
     The median trial has 1 site; the largest has 1,568. A page that shows
     50 of them without saying so has made a false claim about the trial.
  2. NULL status means the registry did not say — never "not recruiting".
     71.4% of live site edges are in that state, so this is the common
     case, not an edge case.
  3. Sites that cannot be placed on a map are counted, not dropped. 1,659
     of them have no coordinates, and a map that quietly excludes them
     reports a smaller trial than the one that exists.
"""
from typing import List

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_readonly_db
from api.schemas import (
    ExploreIntervention,
    ExploreInvestigator,
    ExploreNeighbour,
    ExploreNeighbours,
    ExploreOrganization,
    ExplorePlace,
    ExploreResponse,
    ExploreSite,
    ExploreSites,
)

router = APIRouter(tags=["explore"])

# How many individual sites the response will name. p90 is 14 sites and p99
# is 249 (measured 2026-09-04), so this returns every site for the large
# majority of trials and a labelled sample for the rest. Deliberately not a
# query parameter: a caller raising it to 2,000 would move 1,568 rows to
# render a list nobody reads, and the honest answer for a trial that size
# is the city rollup, not a longer wall.
SITE_LIST_CAP = 50

# Cities named individually before the response falls back to countries
# alone. 899 is the real maximum for one trial.
CITY_CAP = 40

# Neighbours named per list. Ten, because this is a reading list rather than
# a result set: the mega-trial reaches 1,497 trials through shared sites and
# no researcher reads past the first screen of those. The real total is
# always returned alongside, so a short list never reads as a complete one.
NEIGHBOUR_CAP = 10

# Condition tags shown per neighbour. Enough to recognise the subject —
# these are the evidence a reader judges relevance from — without turning a
# ten-row list into a wall. The busiest trials carry 9.
NEIGHBOUR_CONDITION_CAP = 6

# The one place the "did the registry state a status?" rule is written in
# SQL. nullif(trim(...), '') rather than IS NULL so it agrees exactly with
# frontend/labels.site_status_is_stated, which treats an empty string as
# unstated too — two definitions that disagree on blank-vs-NULL would put
# the same site in different buckets on the same page.
_STATED = "nullif(trim(ts.recruitment_status), '') IS NOT NULL"
_RECRUITING = "ts.recruitment_status = 'RECRUITING'"

_STATUS_COUNTS = f"""
    count(*) FILTER (WHERE {_RECRUITING}) AS recruiting,
    count(*) FILTER (WHERE {_STATED} AND NOT ({_RECRUITING})) AS other_stated,
    count(*) FILTER (WHERE NOT ({_STATED})) AS not_stated
"""


@router.get("/explore/{nct_id}", response_model=ExploreResponse)
def explore_trial(
    nct_id: str,
    site_limit: int = Query(
        SITE_LIST_CAP,
        ge=1,
        le=SITE_LIST_CAP,
        description="How many individual sites to name. Capped; the response says when it truncated.",
    ),
    conn=Depends(get_readonly_db),
):
    """One trial's relationships: where it runs, and who runs it."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Named columns, never SELECT * (raw_json is 52% of this table).
        # This doubles as the 404 check: "we have no record of this trial"
        # and "we have a record and it lists no sites" are different
        # answers and must not render identically (CLAUDE.md sec. 2).
        cur.execute(
            "SELECT nct_id, brief_title, overall_status FROM studies WHERE nct_id = %s",
            (nct_id,),
        )
        head = cur.fetchone()
        if head is None:
            raise HTTPException(status_code=404, detail=f"No study with nct_id {nct_id}")

        cur.execute(
            "SELECT condition FROM study_conditions WHERE nct_id = %s ORDER BY condition",
            (nct_id,),
        )
        conditions = [row["condition"] for row in cur.fetchall()]

        sites = _sites(cur, nct_id, site_limit)
        organizations = _organizations(cur, nct_id)
        investigators = _investigators(cur, nct_id)
        interventions = _interventions(cur, nct_id)
        neighbours = _all_neighbours(cur, nct_id, NEIGHBOUR_CAP)

    return ExploreResponse(
        nct_id=head["nct_id"],
        brief_title=head["brief_title"],
        overall_status=head["overall_status"],
        conditions=conditions,
        sites=sites,
        organizations=organizations,
        investigators=investigators,
        interventions=interventions,
        neighbours=neighbours,
    )


# One row per CANONICAL site this trial runs at, which is the unit every
# rollup below counts. Written once and prefixed onto each query rather than
# repeated, so the four zoom levels cannot disagree about what a site is.
#
# Step 8 unit 3 (2026-09-04) made this necessary. Before the merge, 11
# spellings of one Guangzhou hospital were 11 sites, and 54 (trial, site)
# pairs listed the same hospital twice inside a single trial — visible on
# the page as a duplicated row and an inflated count.
#
# `s` is the row the edge points at; `c` is the row that represents it.
# Display comes from `c`, so the trial shows the spelling the registry uses
# most, and counting is DISTINCT on `c.id`.
#
# STATUS IS ONLY KEPT WHEN THE COLLAPSED EDGES AGREE. Two rows for one
# hospital can carry different recruitment statuses (172 such pairs existed
# before any merging), and picking one would invent a fact. Disagreement
# resolves to NULL — "not stated" — which is the same answer the site
# enrichment gives a disputed geoPoint, and which the page already renders
# honestly.
_CANONICAL_SITES = """
    WITH live AS (
        SELECT c.id AS site_id,
               min(c.facility) AS facility,
               min(c.city)     AS city,
               min(c.country)  AS country,
               bool_and(c.lat IS NOT NULL AND c.lon IS NOT NULL) AS placeable,
               CASE WHEN count(DISTINCT nullif(trim(ts.recruitment_status), '')) = 1
                     AND count(*) FILTER (
                             WHERE nullif(trim(ts.recruitment_status), '') IS NULL) = 0
                    THEN max(nullif(trim(ts.recruitment_status), ''))
                    ELSE NULL END AS status
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        JOIN sites c ON c.id = coalesce(s.canonical_id, s.id)
        WHERE ts.nct_id = %(nct)s AND ts.delisted_at IS NULL
        GROUP BY c.id
    )
"""

# The three status buckets, over the collapsed rows.
_LIVE_STATUS_COUNTS = """
    count(*) FILTER (WHERE status = 'RECRUITING') AS recruiting,
    count(*) FILTER (WHERE status IS NOT NULL AND status <> 'RECRUITING') AS other_stated,
    count(*) FILTER (WHERE status IS NULL) AS not_stated
"""

# City names are NOT part of what the merge collapses — two different
# hospitals in 'Heraklion - Crete' and 'Heraklion, Crete' are two real
# sites, and merging them would be wrong. But they are one city, and the
# rollup counted them as two. Grouping on the normalised name and DISPLAYING
# the most common spelling fixes the rollup without touching the sites.
#
# Same normalisation as scripts/merge_entities.py, deliberately: two
# definitions of "the same string" that disagreed would put a city in one
# bucket here and another there.
_NORM_CITY = "btrim(regexp_replace(lower(coalesce(city, '')), '[^a-z0-9]+', ' ', 'g'))"
_NORM_COUNTRY = "btrim(regexp_replace(lower(coalesce(country, '')), '[^a-z0-9]+', ' ', 'g'))"


def _sites(cur, nct_id: str, site_limit: int) -> ExploreSites:
    """Where the trial runs, at three zoom levels.

    Every query filters `delisted_at IS NULL` except the last: a delisted
    edge is a location the record stopped listing, and counting it among the
    live ones would say the trial still runs somewhere it does not. Kept in
    its own list rather than dropped, because "this trial dropped three
    sites" is a result.
    """
    params = {"nct": nct_id}

    cur.execute(
        _CANONICAL_SITES + f"""
        SELECT count(*) AS total, {_LIVE_STATUS_COUNTS},
               count(*) FILTER (WHERE NOT placeable) AS unplaceable
        FROM live
        """,
        params,
    )
    summary = cur.fetchone()

    cur.execute(
        _CANONICAL_SITES + f"""
        SELECT country, count(*) AS sites, {_LIVE_STATUS_COUNTS}
        FROM live GROUP BY country ORDER BY sites DESC, country
        """,
        params,
    )
    countries = [ExplorePlace(**row) for row in cur.fetchall()]

    cur.execute(
        _CANONICAL_SITES + f"""
        SELECT mode() WITHIN GROUP (ORDER BY country) AS country,
               mode() WITHIN GROUP (ORDER BY city) AS city,
               count(*) AS sites, {_LIVE_STATUS_COUNTS},
               count(*) OVER () AS cities_total
        FROM live
        GROUP BY {_NORM_COUNTRY}, {_NORM_CITY}
        ORDER BY sites DESC, 1, 2
        LIMIT %(limit)s
        """,
        {**params, "limit": CITY_CAP},
    )
    city_rows = cur.fetchall()
    # count(*) OVER () counts the GROUPED rows, so it is the number of
    # distinct cities BEFORE the LIMIT — the honest denominator the page
    # prints beside a capped list, at no extra round trip.
    cities_total = city_rows[0]["cities_total"] if city_rows else 0
    cities = [
        ExplorePlace(**{k: v for k, v in row.items() if k != "cities_total"})
        for row in city_rows
    ]

    # Recruiting first, then alphabetically. A truncated list therefore
    # over-represents recruiting sites — the useful bias for the documented
    # workflow (find a trial, phone a site that is open), and safe only
    # because the page states both the ordering and the cap.
    cur.execute(
        _CANONICAL_SITES + """
        SELECT facility, city, country, status, placeable
        FROM live
        ORDER BY (status = 'RECRUITING') DESC NULLS LAST, country, city, facility
        LIMIT %(limit)s
        """,
        {**params, "limit": site_limit},
    )
    listed = [ExploreSite(**row) for row in cur.fetchall()]

    # Delisted edges are NOT collapsed. Each one is a specific location the
    # record stopped listing, and merging two of them would report one
    # dropped site where two were dropped.
    cur.execute(
        """
        SELECT s.facility, s.city, s.country,
               nullif(trim(ts.recruitment_status), '') AS status,
               (s.lat IS NOT NULL AND s.lon IS NOT NULL) AS placeable,
               ts.delisted_at
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %(nct)s AND ts.delisted_at IS NOT NULL
        ORDER BY ts.delisted_at DESC, s.country, s.city, s.facility
        """,
        params,
    )
    delisted_sites = [ExploreSite(**row) for row in cur.fetchall()]

    return ExploreSites(
        total=summary["total"],
        recruiting=summary["recruiting"],
        other_stated=summary["other_stated"],
        not_stated=summary["not_stated"],
        unplaceable=summary["unplaceable"],
        countries=countries,
        cities=cities,
        cities_total=cities_total,
        listed=listed,
        listed_truncated=len(listed) < summary["total"],
        delisted=len(delisted_sites),
        delisted_sites=delisted_sites,
    )


# Each entry is (edge table, its key column, the entity table). Module
# constants, never request data — they are interpolated into SQL below, and
# a caller-supplied table name here would be an injection. Every value a
# request supplies is still a bound parameter.
#
# All three entity tables carry canonical_id since step 8 unit 3, so every
# hop resolves identity the same way: coalesce(canonical_id, id). Before
# that, two trials at one hospital spelled differently did not register as
# sharing it at all — the neighbour list silently missed real overlaps.
_NEIGHBOUR_HOPS = {
    "site": ("trial_sites", "site_id", "sites", False),
    "investigator": ("trial_investigators", "investigator_id", "investigators", True),
    "intervention": ("trial_interventions", "term_id", "intervention_terms", True),
}


def _neighbours(cur, nct_id: str, via: str, limit: int) -> tuple:
    """Trials reachable from this one in two hops through `via`.

    The whole capability in one query, and the only genuinely multi-hop code
    in TrialLens:

        hop 1  this trial  -> its sites / people / terms   (`mine`)
        hop 2  those       -> every other trial using them (`nb`)

    The same edge table is read twice, forwards then backwards. Backwards is
    the direction the PRIMARY KEY cannot serve — it sorts by nct_id first —
    which is exactly what idx_trial_sites_site and its siblings exist for
    (db/schema.sql).

    Hop 2 is where the cost lives, and it does not scale with the trial: it
    scales with how popular the trial's entities are across the whole
    database. RxPONDER's 1,568 sites reach ~1,500 distinct trials because
    one hospital alone carries 210. That is why the count is aggregated in
    Postgres and the list is capped here rather than in the page.

    Live edges on BOTH hops. A delisted edge is a connection the record no
    longer states, and a neighbour reached through one would be a
    relationship TrialLens invented (CLAUDE.md sec. 2).

    `shared` counts DISTINCT canonical entities, not edges: a trial that
    lists the same hospital under two spellings shares it once.
    """
    edge, key, entity, nameable = _NEIGHBOUR_HOPS[via]
    canonical = f"coalesce(n.canonical_id, n.id)"

    if nameable:
        # Name the shared people or terms, in the canonical spelling — with
        # only a handful each, naming them IS the evidence. Sites get a
        # count instead: the real answer for the mega-trial runs to over a
        # thousand facility strings.
        names = ", array_agg(DISTINCT cn.name ORDER BY cn.name) AS shared_names"
        name_join = f"JOIN {entity} cn ON cn.id = {canonical}"
    else:
        names = ", NULL::text[] AS shared_names"
        name_join = ""

    cur.execute(
        f"""
        WITH mine AS (
            SELECT DISTINCT {canonical} AS k
            FROM {edge} e JOIN {entity} n ON n.id = e.{key}
            WHERE e.nct_id = %(nct)s AND e.delisted_at IS NULL
        ),
        nb AS (
            SELECT e.nct_id, count(DISTINCT {canonical}) AS shared{names}
            FROM {edge} e
            JOIN {entity} n ON n.id = e.{key}
            JOIN mine ON mine.k = {canonical}
            {name_join}
            WHERE e.delisted_at IS NULL AND e.nct_id <> %(nct)s
            GROUP BY e.nct_id
        ),
        ranked AS (
            -- count(*) OVER () runs before the LIMIT, so `total` is how many
            -- neighbours really exist, not how many survived the cap.
            SELECT nct_id, shared, shared_names, count(*) OVER () AS total
            FROM nb ORDER BY shared DESC, nct_id LIMIT %(limit)s
        )
        SELECT r.nct_id, r.shared, r.shared_names, r.total,
               s.brief_title, s.overall_status,
               (SELECT array_agg(c.condition)
                  FROM (SELECT condition FROM study_conditions
                         WHERE nct_id = r.nct_id
                         ORDER BY condition LIMIT %(conditions)s) c) AS conditions
        FROM ranked r
        JOIN studies s ON s.nct_id = r.nct_id
        ORDER BY r.shared DESC, r.nct_id
        """,
        {"nct": nct_id, "limit": limit, "conditions": NEIGHBOUR_CONDITION_CAP},
    )
    rows = cur.fetchall()
    total = rows[0]["total"] if rows else 0
    neighbours = [
        ExploreNeighbour(
            nct_id=row["nct_id"],
            brief_title=row["brief_title"],
            overall_status=row["overall_status"],
            shared=row["shared"],
            shared_names=row["shared_names"] or [],
            conditions=row["conditions"] or [],
        )
        for row in rows
    ]
    return neighbours, total


def _all_neighbours(cur, nct_id: str, limit: int) -> ExploreNeighbours:
    by_site, by_site_total = _neighbours(cur, nct_id, "site", limit)
    by_investigator, by_investigator_total = _neighbours(cur, nct_id, "investigator", limit)
    by_intervention, by_intervention_total = _neighbours(cur, nct_id, "intervention", limit)
    return ExploreNeighbours(
        by_site=by_site,
        by_site_total=by_site_total,
        by_investigator=by_investigator,
        by_investigator_total=by_investigator_total,
        by_intervention=by_intervention,
        by_intervention_total=by_intervention_total,
    )


def _organizations(cur, nct_id: str) -> List[ExploreOrganization]:
    """Sponsor and collaborators, lead first.

    `other_trials` is the two-hop count — trial -> organization -> trials —
    and excludes this trial, so it reads as "also on N others" rather than
    a total the reader has to subtract from. Live edges only on the far
    side: an organization's connection to some other trial that ended is
    not evidence of its reach today.
    """
    cur.execute(
        """
        SELECT o.name, tro.role, tro.org_class, tro.delisted_at,
               (SELECT count(DISTINCT x.nct_id)
                  FROM trial_organizations x
                 WHERE x.org_id = o.id
                   AND x.delisted_at IS NULL
                   AND x.nct_id <> tro.nct_id) AS other_trials
        FROM trial_organizations tro
        JOIN organizations o ON o.id = tro.org_id
        WHERE tro.nct_id = %s
        ORDER BY (tro.role = 'LEAD') DESC, other_trials DESC, o.name
        """,
        (nct_id,),
    )
    return [ExploreOrganization(**row) for row in cur.fetchall()]


def _investigators(cur, nct_id: str) -> List[ExploreInvestigator]:
    """The trial's named officials, principal investigators first.

    Ordered by role then name, deliberately NOT by other_trials: the
    highest-degree names in this table are pharma contact desks reused
    across a hundred trials, so a most-connected ordering would put
    'Pfizer CT.gov Call Center' above every actual investigator.

    Grouped by canonical identity (step 8 unit 3), so one person spelled two
    ways is one row and `other_trials` counts every variant of them.
    """
    cur.execute(
        """
        SELECT c.name, c.affiliation, ti.role,
               CASE WHEN bool_or(ti.delisted_at IS NULL) THEN NULL
                    ELSE max(ti.delisted_at) END AS delisted_at,
               (SELECT count(DISTINCT x.nct_id)
                  FROM trial_investigators x
                  JOIN investigators xi ON xi.id = x.investigator_id
                 WHERE coalesce(xi.canonical_id, xi.id) = c.id
                   AND x.delisted_at IS NULL
                   AND x.nct_id <> %(nct)s) AS other_trials
        FROM trial_investigators ti
        JOIN investigators i ON i.id = ti.investigator_id
        JOIN investigators c ON c.id = coalesce(i.canonical_id, i.id)
        WHERE ti.nct_id = %(nct)s
        GROUP BY c.id, c.name, c.affiliation, ti.role
        ORDER BY (ti.role = 'PRINCIPAL_INVESTIGATOR') DESC, c.name
        """,
        {"nct": nct_id},
    )
    return [ExploreInvestigator(**row) for row in cur.fetchall()]


def _interventions(cur, nct_id: str) -> List[ExploreIntervention]:
    """What the trial administers, by term as the registry received it.

    Grouped by canonical identity, which is where the merge is most visible:
    'Semaglutide' (90 trials) and 'semaglutide' (12) were two rows carrying
    two counts, and are now one. It still under-counts a real drug — the
    merge is casefold-and-punctuation only, so 'Semaglutide 2.4 mg' and
    'Placebo semaglutide' stay separate, correctly. The page says so.
    """
    cur.execute(
        """
        SELECT c.name, c.type,
               CASE WHEN bool_or(tri.delisted_at IS NULL) THEN NULL
                    ELSE max(tri.delisted_at) END AS delisted_at,
               (SELECT count(DISTINCT x.nct_id)
                  FROM trial_interventions x
                  JOIN intervention_terms xt ON xt.id = x.term_id
                 WHERE coalesce(xt.canonical_id, xt.id) = c.id
                   AND x.delisted_at IS NULL
                   AND x.nct_id <> %(nct)s) AS other_trials
        FROM trial_interventions tri
        JOIN intervention_terms t ON t.id = tri.term_id
        JOIN intervention_terms c ON c.id = coalesce(t.canonical_id, t.id)
        WHERE tri.nct_id = %(nct)s
        GROUP BY c.id, c.name, c.type
        ORDER BY c.type, c.name
        """,
        {"nct": nct_id},
    )
    return [ExploreIntervention(**row) for row in cur.fetchall()]
