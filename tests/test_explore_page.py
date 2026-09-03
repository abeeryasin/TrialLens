"""frontend/pages/4_Explore.py — what a researcher actually sees.

AppTest runs the real script and returns its element tree, so these assert
the rendered page rather than the code's intent. The API is stubbed;
GET /explore has its own tests.

Every state here is one the page can reach with real data and none of them
are visible while developing against a convenient trial:

  - **Nothing to show.** 686 tracked trials list no locations at all, and a
    trial at an otherwise-unused hospital genuinely has no neighbours. Both
    must read as findings. An empty box reads as a broken query, which is
    the same mistake the watch's quiet week was rebuilt to avoid.
  - **A capped list.** The median trial has one site, so a developer's
    sample never truncates — but RxPONDER has 1,568, and a list that
    doesn't announce its own cap has misreported the trial.
  - **An unstated site status.** The common case at 71.4% of live edges,
    and the one thing this page must never render as "closed"
    (docs/plan_explore_nodes.md sec. 4b).
  - **A trial we don't track.** Explore has no live fallback, unlike
    Understand, so the message must blame our scope rather than the ID.

Free: no database, no network, no model.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_explore_page.py -v
"""
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit not installed"
).AppTest

PAGE = str(FRONTEND / "pages" / "4_Explore.py")


def sites(**overrides):
    body = {
        "total": 1,
        "recruiting": 0,
        "other_stated": 0,
        "not_stated": 1,
        "unplaceable": 0,
        "countries": [
            {
                "country": "United States",
                "city": None,
                "sites": 1,
                "recruiting": 0,
                "other_stated": 0,
                "not_stated": 1,
            }
        ],
        "cities": [
            {
                "country": "United States",
                "city": "The Bronx",
                "sites": 1,
                "recruiting": 0,
                "other_stated": 0,
                "not_stated": 1,
            }
        ],
        "cities_total": 1,
        "listed": [
            {
                "facility": "Jack D. Weiler Hospital",
                "city": "The Bronx",
                "country": "United States",
                "status": None,
                "placeable": True,
                "delisted_at": None,
            }
        ],
        "listed_truncated": False,
        "delisted": 0,
        "delisted_sites": [],
    }
    body.update(overrides)
    return body


def neighbours(**overrides):
    body = {
        "by_site": [],
        "by_site_total": 0,
        "by_investigator": [],
        "by_investigator_total": 0,
        "by_intervention": [],
        "by_intervention_total": 0,
    }
    body.update(overrides)
    return body


def neighbour(**overrides):
    row = {
        "nct_id": "NCT01275677",
        "brief_title": "Chemotherapy With or Without Trastuzumab After Surgery",
        "overall_status": "COMPLETED",
        "shared": 1047,
        "shared_names": [],
        "conditions": ["Recurrent Breast Carcinoma", "Stage IA Breast Cancer AJCC v7"],
    }
    row.update(overrides)
    return row


def payload(**overrides):
    body = {
        "nct_id": "NCT03402139",
        "brief_title": "Early Childhood Obesity Programming",
        "overall_status": "ACTIVE_NOT_RECRUITING",
        "conditions": ["Obesity", "Intrauterine Growth Restriction"],
        "sites": sites(),
        "organizations": [
            {
                "name": "Montefiore Medical Center",
                "role": "LEAD",
                "org_class": "OTHER",
                "other_trials": 4,
                "delisted_at": None,
            }
        ],
        "investigators": [],
        "interventions": [],
        "neighbours": neighbours(),
    }
    body.update(overrides)
    return body


@pytest.fixture
def render(monkeypatch):
    """Run the page against a stubbed API and return everything it says."""
    import api_client

    def _render(body, nct_id="NCT03402139", status_code=None):
        if status_code is not None:
            def boom(path, params=None):
                raise api_client.ApiError("stubbed", status_code=status_code)

            monkeypatch.setattr(api_client, "get", boom)
        else:
            monkeypatch.setattr(api_client, "get", lambda path, params=None: body)

        app = AppTest.from_file(PAGE, default_timeout=30)
        # Seeded before run, so the page's own "first visit" default does not
        # overwrite it — the same widget-key mechanism the neighbour
        # click-through depends on.
        app.session_state["explore_nct_input"] = nct_id
        app.run()
        assert not app.exception, [e.value for e in app.exception]

        seen = []
        for kind in (
            "title", "header", "subheader", "markdown", "caption",
            "info", "warning", "error", "metric",
            # Expander LABELS live on the container, not among its children —
            # without this the dropped-sites headline was unassertable, and a
            # test for it passed only because a caption inside it happened to
            # match.
            "expander", "tabs",
        ):
            try:
                elements = getattr(app, kind)
            except (AttributeError, KeyError):
                continue
            for element in elements:
                # Both label and value: st.metric carries its heading on one
                # and its figure on the other.
                for attr in ("label", "value"):
                    text = getattr(element, attr, None)
                    if isinstance(text, str):
                        seen.append(text)
        return "\n".join(seen), app

    return _render


class TestNothingToShow:
    def test_a_trial_with_no_locations_says_the_registry_lists_none(self, render):
        """686 tracked trials are in this state. "No locations on the record"
        and "we failed to load the locations" must not look the same."""
        page, _ = render(payload(sites=sites(total=0, countries=[], cities=[], cities_total=0, listed=[])))
        assert "lists no locations for this trial" in page
        assert "not a gap in what we fetched" in page

    def test_no_neighbours_is_stated_as_a_real_answer(self, render):
        """A trial at a hospital nothing else uses genuinely has zero
        neighbours. Silence here would read as a broken graph."""
        page, _ = render(payload())
        assert "No other tracked trial connects to this one that way" in page
        assert "That's a real answer, not a missing one" in page

    def test_an_untracked_trial_blames_our_scope_not_the_id(self, render):
        """Understand falls back to a live CT.gov lookup; Explore cannot,
        because the graph is built from stored records. Saying "no such
        trial" would be false about a trial that exists."""
        page, _ = render(None, status_code=404)
        assert "isn't one of the trials TrialLens tracks" in page
        assert "try Understand" in page.lower() or "try Understand" in page


class TestCappedLists:
    def test_a_truncated_site_list_states_what_it_was_capped_from(self, render):
        page, _ = render(
            payload(
                sites=sites(
                    total=1568,
                    not_stated=1568,
                    cities_total=899,
                    listed=[sites()["listed"][0] for _ in range(50)],
                    listed_truncated=True,
                )
            )
        )
        assert "Showing 50 of 1,568 sites" in page
        assert "899" in page

    def test_a_capped_neighbour_list_shows_the_real_total(self, render):
        """Ten of 1,497 reported as ten would say this trial has ten
        neighbours."""
        page, _ = render(
            payload(
                neighbours=neighbours(
                    by_site=[neighbour(nct_id=f"NCT{i:08d}") for i in range(10)],
                    by_site_total=1497,
                )
            )
        )
        assert "Showing the top 10 of **1,497**" in page

    def test_an_uncapped_list_does_not_imply_more_exist(self, render):
        page, _ = render(
            payload(neighbours=neighbours(by_site=[neighbour()], by_site_total=1))
        )
        assert "All 1, most shared first." in page


class TestSiteStatusHonesty:
    def test_an_unstated_status_is_never_rendered_as_closed(self, render):
        """The single claim this page must not make."""
        page, app = render(payload())
        assert "Status not reported" in page
        assert "does **not** mean the site is closed" in page

        table = [df.value for df in app.dataframe]
        statuses = [
            value
            for frame in table
            if "Status" in getattr(frame, "columns", [])
            for value in frame["Status"].tolist()
        ]
        assert statuses, "no site table was rendered"
        assert all("not reported" in s.lower() or "recruiting" in s.lower() for s in statuses)
        assert not any("closed" in s.lower() for s in statuses)

    def test_not_yet_recruiting_is_not_filed_under_closed(self, render):
        """"Another stated status" is a bucket, not a verdict — it holds
        NOT_YET_RECRUITING alongside SUSPENDED, and the page says so."""
        page, _ = render(payload(sites=sites(total=2, other_stated=1, not_stated=1)))
        assert "includes *not yet recruiting*, which is also not closed" in page

    def test_sites_with_no_coordinates_are_counted_out_loud(self, render):
        """1,659 sites cannot be placed. A map that drops them silently is
        the step-4 under-reporting bug."""
        page, _ = render(payload(sites=sites(total=54, not_stated=54, unplaceable=3)))
        assert "3 of these sites have no coordinates" in page


class TestDroppedSites:
    def test_a_dropped_location_is_surfaced_as_a_finding(self, render):
        """The reason delisted edges are stamped instead of deleted."""
        dropped = dict(sites()["listed"][0])
        dropped.update({"facility": "Samsung Medical Center", "delisted_at": "2026-09-03T04:15:00Z"})
        page, _ = render(payload(sites=sites(delisted=1, delisted_sites=[dropped])))
        assert "1 location(s) this trial has dropped since we started watching" in page

    def test_it_does_not_claim_to_know_when_the_sponsor_dropped_it(self, render):
        """delisted_at is when a backfill first could not find the edge.
        Presenting it as the amendment date would invent precision."""
        dropped = dict(sites()["listed"][0])
        dropped.update({"delisted_at": "2026-09-03T04:15:00Z"})
        page, _ = render(payload(sites=sites(delisted=1, delisted_sites=[dropped])))
        assert "not when the sponsor made the change" in page


class TestTheTwoHopEvidence:
    def test_a_neighbour_shows_its_own_conditions(self, render):
        """The 2026-09-04 correction: a shared-condition COUNT would have
        printed 0 under two breast cancer trials, because nothing is merged.
        The tags themselves are the evidence."""
        _, app = render(
            payload(neighbours=neighbours(by_site=[neighbour()], by_site_total=1))
        )
        frames = [df.value for df in app.dataframe]
        conditions = [
            value
            for frame in frames
            if "Its conditions" in getattr(frame, "columns", [])
            for value in frame["Its conditions"].tolist()
        ]
        assert conditions == ["Recurrent Breast Carcinoma · Stage IA Breast Cancer AJCC v7"]

    def test_the_anchor_trials_tags_sit_beside_the_neighbour_list(self, render):
        """The comparison only works if both halves are on screen together.
        The anchor's tags render at the top of the page, a full screen from
        the "Its conditions" column they are meant to be read against."""
        page, _ = render(
            payload(neighbours=neighbours(by_site=[neighbour()], by_site_total=1))
        )
        assert "**This trial is tagged:** Obesity · Intrauterine Growth Restriction" in page
        assert "study the same disease and share no tag at all" in page

    def test_it_warns_that_site_overlap_can_be_a_shared_network(self, render):
        """RxPONDER's top neighbour shares 1,047 sites. Presenting that as
        relatedness without the caveat overstates what a count can show."""
        page, _ = render(
            payload(neighbours=neighbours(by_site=[neighbour()], by_site_total=1))
        )
        assert "shared hospital network rather than a shared subject" in page

    def test_the_three_routes_are_never_merged_into_one_score(self, render):
        page, _ = render(payload())
        assert "different claims" in page
        assert "would hide which is which" in page


class TestAttributesNotNetworks:
    def test_the_collaborator_caveat_appears_when_there_is_one(self, render):
        """CT.gov's collaborator field merges funders with co-designers, so
        it is shown as an attribute rather than a research partnership."""
        page, _ = render(
            payload(
                organizations=[
                    {
                        "name": "National Institutes of Health (NIH)",
                        "role": "COLLABORATOR",
                        "org_class": "NIH",
                        "other_trials": 90,
                        "delisted_at": None,
                    }
                ]
            )
        )
        assert "covers funders" in page and "scientific co-designers" in page

    def test_no_named_investigator_is_explained_rather_than_left_blank(self, render):
        """Common on industry trials, and not evidence nobody runs it."""
        page, _ = render(payload())
        assert "names no overall official" in page

    def test_intervention_counts_admit_they_are_per_spelling(self, render):
        """55 spellings of semaglutide are 55 terms, so the count under-
        reports a drug's real reach."""
        page, _ = render(
            payload(
                interventions=[
                    {"name": "Letrozole", "type": "DRUG", "other_trials": 114, "delisted_at": None}
                ]
            )
        )
        assert "not every trial using the drug" in page
