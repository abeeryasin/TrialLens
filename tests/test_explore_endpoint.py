"""GET /explore/{nct_id} — the shape of the answer, over HTTP.

Explore's failure mode is not an exception, it is a confident short answer.
Four ways that happens, and each has a test here:

  - A trial we have never seen answers "no sites, no sponsors, no
    investigators" instead of 404, and an unknown trial reads as a quiet
    one (CLAUDE.md sec. 2).
  - A capped list forgets to say it was capped, so 50 of 1,568 sites reads
    as the whole trial.
  - A site whose status the registry never stated arrives as something
    other than None, and silence becomes a claim about recruitment.
  - A location the trial dropped is counted among the live ones, so
    Explore says the trial still runs where it does not.

Free: no database, no network, no model. The fake connection ignores SQL
(tests/conftest.py), so what is covered is routing, request binding, the
assembly between query and response, and the response model. Whether the
SQL is right is tests/test_explore_real_data.py's job.
"""
from datetime import datetime, timezone

from api.explore import CITY_CAP, SITE_LIST_CAP

DELISTED_AT = datetime(2026, 9, 3, 4, 15, 0, tzinfo=timezone.utc)


def head_row(**overrides):
    row = {
        "nct_id": "NCT01272037",
        "brief_title": "Tamoxifen Citrate, Letrozole, Anastrozole, or Exemestane",
        "overall_status": "ACTIVE_NOT_RECRUITING",
    }
    row.update(overrides)
    return row


def summary_row(**overrides):
    row = {
        "total": 0,
        "recruiting": 0,
        "other_stated": 0,
        "not_stated": 0,
        "unplaceable": 0,
    }
    row.update(overrides)
    return row


def site_row(**overrides):
    row = {
        "facility": "Memorial Sloan Kettering Cancer Center",
        "city": "New York",
        "country": "United States",
        "status": None,
        "placeable": True,
    }
    row.update(overrides)
    return row


def city_row(cities_total, **overrides):
    row = {
        "country": "United States",
        "city": "New York",
        "sites": 3,
        "recruiting": 1,
        "other_stated": 0,
        "not_stated": 2,
        "cities_total": cities_total,
    }
    row.update(overrides)
    return row


def neighbour_row(total, **overrides):
    row = {
        "nct_id": "NCT01275677",
        "brief_title": "Chemotherapy With or Without Trastuzumab After Surgery",
        "overall_status": "COMPLETED",
        "shared": 1047,
        "shared_names": None,
        "conditions": ["Recurrent Breast Carcinoma", "Stage IA Breast Cancer AJCC v7"],
        "total": total,
    }
    row.update(overrides)
    return row


def results(
    head=None,
    conditions=(),
    summary=None,
    countries=(),
    cities=(),
    listed=(),
    delisted=(),
    organizations=(),
    investigators=(),
    interventions=(),
    by_site=(),
    by_investigator=(),
    by_intervention=(),
):
    """The thirteen result sets the route reads, in the order it reads them."""
    return [
        [head] if head is not None else [],
        [{"condition": c} for c in conditions],
        [summary if summary is not None else summary_row()],
        list(countries),
        list(cities),
        list(listed),
        list(delisted),
        list(organizations),
        list(investigators),
        list(interventions),
        list(by_site),
        list(by_investigator),
        list(by_intervention),
    ]


def test_unknown_trial_is_404_not_an_empty_explore(api):
    """"We have no record of this trial" and "we have a record and it lists
    nothing" are different answers. Returning an empty Explore for an
    unknown nct_id makes an unheard-of trial look like a quiet one."""
    response = api(results(head=None)).get("/explore/NCT00000000")

    assert response.status_code == 404
    assert "NCT00000000" in response.json()["detail"]


def test_a_tracked_trial_with_no_graph_rows_is_200_and_says_zero(api):
    """The other half of the same distinction. 686 tracked trials have no
    site edges at all, and each must answer 200 with real zeros rather than
    404 — the trial exists, the registry just listed no locations."""
    response = api(results(head=head_row())).get("/explore/NCT01272037")

    assert response.status_code == 200
    body = response.json()
    assert body["sites"]["total"] == 0
    assert body["sites"]["listed"] == []
    assert body["sites"]["listed_truncated"] is False
    assert body["organizations"] == []
    assert body["investigators"] == []


def test_a_capped_site_list_says_it_was_capped(api):
    """50 rows returned against a total of 1,568 is a sample, and a sample
    that does not announce itself is a false claim about the trial."""
    response = api(
        results(
            head=head_row(),
            summary=summary_row(total=1568, not_stated=1568, unplaceable=8),
            listed=[site_row(facility=f"Site {i}") for i in range(SITE_LIST_CAP)],
        )
    ).get("/explore/NCT01272037")

    sites = response.json()["sites"]
    assert sites["total"] == 1568
    assert len(sites["listed"]) == SITE_LIST_CAP
    assert sites["listed_truncated"] is True


def test_a_complete_site_list_does_not_claim_truncation(api):
    """The median trial has one site. Flagging that as truncated would send
    the page hunting for sites that do not exist."""
    response = api(
        results(
            head=head_row(),
            summary=summary_row(total=1, not_stated=1),
            listed=[site_row()],
        )
    ).get("/explore/NCT01272037")

    sites = response.json()["sites"]
    assert len(sites["listed"]) == sites["total"] == 1
    assert sites["listed_truncated"] is False


def test_cities_total_survives_the_cap(api):
    """The cap applies to the rows, never to the denominator. A page that
    prints "40 cities" for a trial running in 899 has shrunk the trial."""
    response = api(
        results(
            head=head_row(),
            summary=summary_row(total=1568, not_stated=1568),
            cities=[city_row(899, city=f"City {i}") for i in range(CITY_CAP)],
        )
    ).get("/explore/NCT01272037")

    sites = response.json()["sites"]
    assert len(sites["cities"]) == CITY_CAP
    assert sites["cities_total"] == 899
    # The window-function column is scaffolding for that denominator, not
    # part of the answer — it must not leak into the response.
    assert "cities_total" not in sites["cities"][0]


def test_an_unstated_site_status_stays_none(api):
    """71.4% of live site edges carry no status. None must survive the whole
    round trip: any substitute value is the registry being quoted saying
    something it never said."""
    response = api(
        results(
            head=head_row(),
            summary=summary_row(total=2, recruiting=1, not_stated=1),
            listed=[site_row(status="RECRUITING"), site_row(status=None)],
        )
    ).get("/explore/NCT01272037")

    listed = response.json()["sites"]["listed"]
    assert listed[0]["status"] == "RECRUITING"
    assert listed[1]["status"] is None


def test_delisted_sites_are_reported_separately_from_live_ones(api):
    """A dropped location must not be counted among the live sites — that
    would say the trial still runs there. It also must not vanish: "this
    trial dropped three sites" is a finding this product exists to show."""
    response = api(
        results(
            head=head_row(),
            summary=summary_row(total=54, recruiting=34, other_stated=20, unplaceable=3),
            listed=[site_row()],
            delisted=[
                site_row(facility="Samsung Medical Center", delisted_at=DELISTED_AT),
                site_row(facility="Princess Margaret Cancer Centre", delisted_at=DELISTED_AT),
            ],
        )
    ).get("/explore/NCT06760819")

    sites = response.json()["sites"]
    assert sites["total"] == 54
    assert sites["delisted"] == 2
    assert [s["facility"] for s in sites["delisted_sites"]] == [
        "Samsung Medical Center",
        "Princess Margaret Cancer Centre",
    ]
    assert sites["listed"][0]["delisted_at"] is None


def test_unplaceable_sites_are_counted_not_dropped(api):
    """1,659 sites have no coordinates. The count has to reach the page, or
    a map silently shows a smaller trial than the one on file."""
    response = api(
        results(
            head=head_row(),
            summary=summary_row(total=54, not_stated=54, unplaceable=3),
            listed=[site_row(placeable=False)],
        )
    ).get("/explore/NCT06760819")

    sites = response.json()["sites"]
    assert sites["unplaceable"] == 3
    assert sites["listed"][0]["placeable"] is False


def test_entities_carry_their_two_hop_counts(api):
    """other_trials is the second hop — trial -> organization -> trials —
    and is what makes this Explore rather than another detail page."""
    response = api(
        results(
            head=head_row(),
            organizations=[
                {
                    "name": "National Cancer Institute (NCI)",
                    "role": "LEAD",
                    "org_class": "NIH",
                    "other_trials": 578,
                    "delisted_at": None,
                }
            ],
            investigators=[
                {
                    "name": "Kevin M Kalinsky",
                    "affiliation": "ECOG-ACRIN Cancer Research Group",
                    "role": "PRINCIPAL_INVESTIGATOR",
                    "other_trials": 0,
                    "delisted_at": None,
                }
            ],
            interventions=[
                {"name": "Letrozole", "type": "DRUG", "other_trials": 114, "delisted_at": None}
            ],
        )
    ).get("/explore/NCT01272037")

    body = response.json()
    assert body["organizations"][0]["other_trials"] == 578
    assert body["organizations"][0]["org_class"] == "NIH"
    assert body["investigators"][0]["other_trials"] == 0
    assert body["interventions"][0]["other_trials"] == 114


def test_a_capped_neighbour_list_keeps_the_real_total(api):
    """Ten neighbours shown out of 1,497 must report 1,497. A list that
    reports its own length as the total tells a researcher this trial has
    ten neighbours when it has fifteen hundred."""
    response = api(
        results(
            head=head_row(),
            by_site=[neighbour_row(1497, nct_id=f"NCT{i:08d}") for i in range(10)],
        )
    ).get("/explore/NCT01272037")

    neighbours = response.json()["neighbours"]
    assert len(neighbours["by_site"]) == 10
    assert neighbours["by_site_total"] == 1497
    # Scaffolding for the denominator, not part of the answer.
    assert "total" not in neighbours["by_site"][0]


def test_no_neighbours_reports_zero_rather_than_a_missing_answer(api):
    """A trial at a hospital no other tracked trial uses genuinely has no
    site neighbours. Zero is the finding — the page says so out loud rather
    than rendering an empty box that reads as a broken query."""
    response = api(results(head=head_row())).get("/explore/NCT03402139")

    neighbours = response.json()["neighbours"]
    assert neighbours["by_site"] == []
    assert neighbours["by_site_total"] == 0
    assert neighbours["by_investigator_total"] == 0
    assert neighbours["by_intervention_total"] == 0


def test_a_neighbour_carries_its_own_conditions_not_a_match_count(api):
    """The correction of 2026-09-04. RxPONDER and its top site-neighbour
    share zero condition STRINGS while both being breast cancer trials, so a
    match count would have printed "0 in common" under two breast cancer
    trials. The tags themselves are what let a reader judge."""
    response = api(
        results(head=head_row(), by_site=[neighbour_row(1497)])
    ).get("/explore/NCT01272037")

    neighbour = response.json()["neighbours"]["by_site"][0]
    assert neighbour["conditions"] == [
        "Recurrent Breast Carcinoma",
        "Stage IA Breast Cancer AJCC v7",
    ]
    assert neighbour["shared"] == 1047


def test_the_three_neighbour_routes_stay_separate(api):
    """Sharing a hospital and sharing a principal investigator are different
    claims. Merging them into one ranked list would rebuild the
    unexplainable score /rank was deleted for."""
    response = api(
        results(
            head=head_row(),
            by_site=[neighbour_row(40, nct_id="NCT00000001", shared=6)],
            by_investigator=[
                neighbour_row(
                    2,
                    nct_id="NCT00000002",
                    shared=1,
                    shared_names=["Kevin M Kalinsky"],
                )
            ],
            by_intervention=[
                neighbour_row(
                    282, nct_id="NCT00000003", shared=3, shared_names=["Letrozole"]
                )
            ],
        )
    ).get("/explore/NCT01272037")

    neighbours = response.json()["neighbours"]
    assert neighbours["by_site"][0]["nct_id"] == "NCT00000001"
    assert neighbours["by_investigator"][0]["shared_names"] == ["Kevin M Kalinsky"]
    assert neighbours["by_intervention"][0]["shared_names"] == ["Letrozole"]
    # Sites name nothing — the honest answer runs to 1,047 facility strings,
    # so the count and the conditions carry the evidence there.
    assert neighbours["by_site"][0]["shared_names"] == []


def test_site_limit_above_the_cap_is_rejected(api):
    """Request binding is FastAPI's job and only an HTTP call exercises it.
    The cap exists so no caller can ask for 2,000 site rows; a route that
    accepted the parameter and ignored it would pass a direct-call test."""
    response = api(results(head=head_row())).get(
        f"/explore/NCT01272037?site_limit={SITE_LIST_CAP + 1}"
    )

    assert response.status_code == 422


def test_site_limit_is_passed_through_to_the_query(api):
    """A limit the route accepts but does not apply is worse than no limit:
    the response would then claim a cap it never enforced."""
    holder = []
    api(
        results(head=head_row(), summary=summary_row(total=54)),
        keep=holder,
    ).get("/explore/NCT06760819?site_limit=5")

    listed_query = [
        (sql, params) for sql, params in holder[0].cursor_obj.executed if "ORDER BY" in sql and "LIMIT" in sql
    ]
    assert any(params and params[-1] == 5 for _, params in listed_query)
