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


def _sites(cur, nct_id: str, site_limit: int) -> ExploreSites:
    """Where the trial runs, at three zoom levels.

    Every query here filters `delisted_at IS NULL` except the last: a
    delisted edge is a location the record stopped listing, and counting it
    among the live ones would say the trial still runs somewhere it does
    not. Kept in its own list rather than dropped, because "this trial
    dropped three sites" is a result.
    """
    cur.execute(
        f"""
        SELECT count(*) AS total,
               {_STATUS_COUNTS},
               count(*) FILTER (WHERE s.lat IS NULL OR s.lon IS NULL) AS unplaceable
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
        """,
        (nct_id,),
    )
    summary = cur.fetchone()

    cur.execute(
        f"""
        SELECT s.country, count(*) AS sites, {_STATUS_COUNTS}
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
        GROUP BY s.country
        ORDER BY sites DESC, s.country
        """,
        (nct_id,),
    )
    countries = [ExplorePlace(**row) for row in cur.fetchall()]

    cur.execute(
        f"""
        SELECT s.country, s.city, count(*) AS sites, {_STATUS_COUNTS},
               count(*) OVER () AS cities_total
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
        GROUP BY s.country, s.city
        ORDER BY sites DESC, s.country, s.city
        LIMIT %s
        """,
        (nct_id, CITY_CAP),
    )
    city_rows = cur.fetchall()
    # count(*) OVER () counts the GROUPED rows, so it is the number of
    # distinct cities BEFORE the LIMIT — the honest denominator the page
    # prints beside a capped list. A second COUNT query would be one more
    # round trip for a number this window function already has.
    cities_total = city_rows[0]["cities_total"] if city_rows else 0
    cities = [ExplorePlace(**{k: v for k, v in row.items() if k != "cities_total"}) for row in city_rows]

    cur.execute(
        f"""
        SELECT s.facility, s.city, s.country,
               nullif(trim(ts.recruitment_status), '') AS status,
               (s.lat IS NOT NULL AND s.lon IS NOT NULL) AS placeable
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NULL
        ORDER BY ({_RECRUITING}) DESC NULLS LAST, s.country, s.city, s.facility
        LIMIT %s
        """,
        (nct_id, site_limit),
    )
    # Recruiting first, then alphabetically. A truncated list therefore
    # over-represents recruiting sites — which is the useful bias for the
    # documented workflow (find a trial, phone a site that is open) and is
    # safe only because the page states both the ordering and the cap.
    listed = [ExploreSite(**row) for row in cur.fetchall()]

    cur.execute(
        f"""
        SELECT s.facility, s.city, s.country,
               nullif(trim(ts.recruitment_status), '') AS status,
               (s.lat IS NOT NULL AND s.lon IS NOT NULL) AS placeable,
               ts.delisted_at
        FROM trial_sites ts
        JOIN sites s ON s.id = ts.site_id
        WHERE ts.nct_id = %s AND ts.delisted_at IS NOT NULL
        ORDER BY ts.delisted_at DESC, s.country, s.city, s.facility
        """,
        (nct_id,),
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


# Each entry is (edge table, its key column, the entity table to name, its
# join column). Module constants, never request data — they are interpolated
# into SQL below, and a caller-supplied table name here would be an
# injection. Every value a request supplies is still a bound parameter.
_NEIGHBOUR_HOPS = {
    "site": ("trial_sites", "site_id", None, None),
    "investigator": ("trial_investigators", "investigator_id", "investigators", "id"),
    "intervention": ("trial_interventions", "term_id", "intervention_terms", "id"),
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
    database. RxPONDER's 1,568 sites reach 1,497 distinct trials because one
    hospital alone carries 210. That is why the count is aggregated in
    Postgres and the list is capped here rather than in the page.

    Live edges on BOTH hops. A delisted edge is a connection the record no
    longer states, and a neighbour reached through one would be a
    relationship TrialLens invented (CLAUDE.md sec. 2).
    """
    edge, key, entity, entity_key = _NEIGHBOUR_HOPS[via]

    if entity:
        # Name the shared people or terms — with only a handful each, naming
        # them IS the evidence. Sites get a count instead: the real answer
        # for the mega-trial runs to 1,047 facility strings.
        names = ", array_agg(DISTINCT n.name ORDER BY n.name) AS shared_names"
        name_join = f"JOIN {entity} n ON n.{entity_key} = e.{key}"
    else:
        names = ", NULL::text[] AS shared_names"
        name_join = ""

    cur.execute(
        f"""
        WITH mine AS (
            SELECT {key} AS k FROM {edge}
            WHERE nct_id = %(nct)s AND delisted_at IS NULL
        ),
        nb AS (
            SELECT e.nct_id, count(*) AS shared{names}
            FROM {edge} e
            JOIN mine ON mine.k = e.{key}
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
    """
    cur.execute(
        """
        SELECT i.name, i.affiliation, ti.role, ti.delisted_at,
               (SELECT count(DISTINCT x.nct_id)
                  FROM trial_investigators x
                 WHERE x.investigator_id = i.id
                   AND x.delisted_at IS NULL
                   AND x.nct_id <> ti.nct_id) AS other_trials
        FROM trial_investigators ti
        JOIN investigators i ON i.id = ti.investigator_id
        WHERE ti.nct_id = %s
        ORDER BY (ti.role = 'PRINCIPAL_INVESTIGATOR') DESC, i.name
        """,
        (nct_id,),
    )
    return [ExploreInvestigator(**row) for row in cur.fetchall()]


def _interventions(cur, nct_id: str) -> List[ExploreIntervention]:
    """What the trial administers, by term as the registry received it."""
    cur.execute(
        """
        SELECT it.name, it.type, tri.delisted_at,
               (SELECT count(DISTINCT x.nct_id)
                  FROM trial_interventions x
                 WHERE x.term_id = it.id
                   AND x.delisted_at IS NULL
                   AND x.nct_id <> tri.nct_id) AS other_trials
        FROM trial_interventions tri
        JOIN intervention_terms it ON it.id = tri.term_id
        WHERE tri.nct_id = %s
        ORDER BY it.type, it.name
        """,
        (nct_id,),
    )
    return [ExploreIntervention(**row) for row in cur.fetchall()]
