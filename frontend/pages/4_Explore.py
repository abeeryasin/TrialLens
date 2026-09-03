"""Explore: who else works in this space?

The first screen that reads the knowledge graph. Until now its 191,864
edges were entirely invisible — built across three days, reachable from
nothing (docs/roadmap.md, step 8).

The page answers in two halves, and the order is the evidence review's
(docs/plan_explore_nodes.md), not the registry's:

  1. **Where does this trial run, and who runs it** — sites lead at 93.8%
     coverage, because the documented clinician workflow ends in a phone
     call to a named hospital. Collaborators come last and as an attribute,
     never a network: CT.gov's own definition merges funders with
     co-designers and excludes individuals outright.
  2. **What else is reachable from here** — two hops, in three separate
     lists that are never fused into one "related trials" ranking.

Three things this page must keep saying out loud, all of them ways of not
reporting a smaller, quieter trial than the one on file:

  - A capped list says what it was capped from.
  - A site with no stated status is "not reported", never "not recruiting".
  - Zero is a finding, stated in words — an empty box reads as a bug.

Explore has no live-CT.gov fallback, unlike Understand. The graph is built
from stored records only, so an untracked trial genuinely has no answer
here, and the page says that rather than showing an empty skeleton.
"""
import pandas as pd
import streamlit as st

from api_client import ApiError, get
from labels import format_site_status, site_status_is_stated

st.set_page_config(page_title="Explore — TrialLens", page_icon="🕸️", layout="wide")
st.title("Explore")
st.caption(
    "Who else works in this space? Sites, sponsors, investigators and "
    "interventions, and the other tracked trials they connect to."
)

# An explicit key, unlike Understand's `value=`: this page can navigate to
# ANOTHER trial from its own neighbour list, and a widget created with
# `value=` keeps whatever the user typed no matter what session_state says.
# Seeding the widget's own key is the only thing that actually moves the box.
if "explore_nct_input" not in st.session_state:
    st.session_state["explore_nct_input"] = st.session_state.get("selected_nct_id", "")

nct_id = (
    st.text_input("NCT ID", key="explore_nct_input", placeholder="e.g. NCT01272037")
    .strip()
    .upper()
)

if not nct_id:
    st.caption("Pick a trial from Discover or Monitor, or paste an NCT ID above.")
    st.stop()

try:
    data = get(f"/explore/{nct_id}")
except ApiError as exc:
    if exc.status_code == 404:
        # Deliberately not the same message Understand shows. There, a
        # missing trial may still exist on ClinicalTrials.gov and gets
        # fetched live. Here it genuinely cannot be answered, and saying
        # "no such trial" would blame the ID for our own scope.
        st.warning(
            f"{nct_id} isn't one of the trials TrialLens tracks, so there's no "
            "graph to explore for it. Explore is built from stored records "
            "only — try Understand, which falls back to a live lookup."
        )
    else:
        st.error(str(exc))
    st.stop()

sites = data["sites"]
neighbours = data["neighbours"]

st.header(data["brief_title"])
st.caption(f"{data['nct_id']} · {data['overall_status'].replace('_', ' ').title()}")
if data["conditions"]:
    st.caption("Conditions on file: " + " · ".join(data["conditions"]))


# ---------------------------------------------------------------------------
# Where it runs
# ---------------------------------------------------------------------------
st.subheader("Where it runs")

if sites["total"] == 0:
    # A real answer for 686 tracked trials, and it must not look like a
    # failed query.
    st.info(
        "ClinicalTrials.gov lists no locations for this trial. That's the "
        "registry's own record, not a gap in what we fetched."
    )
else:
    country_count = len(sites["countries"])
    st.markdown(
        f"**{sites['total']:,} site(s)** across **{country_count} "
        f"{'country' if country_count == 1 else 'countries'}** "
        f"and **{sites['cities_total']:,} cit{'y' if sites['cities_total'] == 1 else 'ies'}**."
    )

    stat_cols = st.columns(3)
    stat_cols[0].metric("Recruiting here", f"{sites['recruiting']:,}")
    stat_cols[1].metric("Another stated status", f"{sites['other_stated']:,}")
    stat_cols[2].metric("Status not reported", f"{sites['not_stated']:,}")
    st.caption(
        "“Status not reported” means ClinicalTrials.gov published no per-site "
        "status for this trial — it does **not** mean the site is closed. "
        "Only 28.6% of site records carry one at all. “Another stated status” "
        "includes *not yet recruiting*, which is also not closed; the exact "
        "wording is on each site below."
    )

    if sites["unplaceable"]:
        st.caption(
            f"⚠️ {sites['unplaceable']:,} of these sites have no coordinates in "
            "the registry. Any map of this trial would silently leave them out, "
            "which is why the breakdown below is by name rather than by pin."
        )

    place_tab, city_tab, site_tab = st.tabs(
        ["By country", "By city", f"Individual sites ({sites['total']:,})"]
    )

    with place_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Country": p["country"] or "Not stated",
                        "Sites": p["sites"],
                        "Recruiting": p["recruiting"],
                        "Other stated status": p["other_stated"],
                        "Status not reported": p["not_stated"],
                    }
                    for p in sites["countries"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    with city_tab:
        shown = len(sites["cities"])
        if shown < sites["cities_total"]:
            st.caption(
                f"Showing the {shown} cities with the most sites, out of "
                f"{sites['cities_total']:,} this trial runs in."
            )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "City": p["city"] or "Not stated",
                        "Country": p["country"] or "Not stated",
                        "Sites": p["sites"],
                        "Recruiting": p["recruiting"],
                        "Other stated status": p["other_stated"],
                        "Status not reported": p["not_stated"],
                    }
                    for p in sites["cities"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    with site_tab:
        if sites["listed_truncated"]:
            st.caption(
                f"Showing {len(sites['listed'])} of {sites['total']:,} sites, "
                "recruiting ones first, then alphabetically. Too many to list "
                "in full — use the city breakdown for the whole picture."
            )
        unstated = [s for s in sites["listed"] if not site_status_is_stated(s["status"])]
        if unstated:
            st.caption(
                f"{len(unstated)} of the sites shown have no published status. "
                "Contact the site to confirm before relying on it."
            )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Facility": s["facility"] or "Not named",
                        "City": s["city"] or "—",
                        "Country": s["country"] or "—",
                        "Status": format_site_status(s["status"]),
                        "Mappable": "Yes" if s["placeable"] else "No coordinates",
                    }
                    for s in sites["listed"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    if sites["delisted"]:
        # The finding delisted edges were invented to preserve. Never
        # rendered as an error — a trial dropping sites is a real event in a
        # watch-over-time product.
        with st.expander(
            f"🔻 {sites['delisted']} location(s) this trial has dropped since we started watching"
        ):
            st.caption(
                "These were on the record and no longer are. The date is when "
                "TrialLens first noticed — not when the sponsor made the "
                "change, which the registry doesn't tell us."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Facility": s["facility"] or "Not named",
                            "City": s["city"] or "—",
                            "Country": s["country"] or "—",
                            "Last status on record": format_site_status(s["status"]),
                            "Noticed gone": (s["delisted_at"] or "")[:10],
                        }
                        for s in sites["delisted_sites"]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )


# ---------------------------------------------------------------------------
# Who runs it
# ---------------------------------------------------------------------------
st.subheader("Who runs it")

org_col, people_col = st.columns(2)

with org_col:
    st.markdown("**Sponsor and collaborators**")
    if not data["organizations"]:
        st.caption("No sponsor recorded for this trial.")
    for org in data["organizations"]:
        role = "Lead sponsor" if org["role"] == "LEAD" else "Collaborator"
        suffix = ""
        if org["other_trials"]:
            suffix = f" · also on {org['other_trials']:,} other tracked trial(s)"
        st.markdown(f"**{org['name']}**")
        st.caption(
            f"{role}"
            + (f" · {org['org_class'].replace('_', ' ').title()}" if org["org_class"] else "")
            + suffix
        )
    if any(o["role"] == "COLLABORATOR" for o in data["organizations"]):
        st.caption(
            "ClinicalTrials.gov's “collaborator” field covers funders *and* "
            "scientific co-designers with no way to tell them apart, so read it "
            "as an attribute of the trial rather than a research partnership."
        )

with people_col:
    st.markdown("**Named investigators**")
    if not data["investigators"]:
        st.caption(
            "The registry names no overall official for this trial — common on "
            "industry-run studies, and not a sign nobody is running it."
        )
    for person in data["investigators"]:
        st.markdown(f"**{person['name']}**")
        detail = person["role"].replace("_", " ").title()
        if person["affiliation"]:
            detail += f" · {person['affiliation']}"
        if person["other_trials"]:
            detail += f" · also on {person['other_trials']:,} other tracked trial(s)"
        st.caption(detail)

if data["interventions"]:
    st.markdown("**Interventions**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Term": i["name"],
                    "Type": i["type"].replace("_", " ").title(),
                    "Other tracked trials using this exact term": i["other_trials"],
                }
                for i in data["interventions"]
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Terms are the exact wording the sponsor registered, unmerged — 55 "
        "spellings of semaglutide are 55 different terms here. So the count is "
        "trials using *this spelling*, not every trial using the drug."
    )


# ---------------------------------------------------------------------------
# Two hops out
# ---------------------------------------------------------------------------
st.subheader("Who else works in this space")
st.caption(
    "Other tracked trials reachable from this one. Kept in three separate "
    "lists on purpose: sharing a hospital and sharing an investigator are "
    "different claims, and blending them into one “relevance” number would "
    "hide which is which."
)

# The anchor trial's own tags, repeated here rather than only at the top of
# the page. The "Its conditions" column is the evidence a reader judges a
# neighbour by, and judging it means comparing against THIS trial's tags —
# which were a full screen away. Repeating four words beats scrolling.
#
# It also makes the mismatch legible rather than mysterious: RxPONDER is
# tagged by tumour morphology and its nearest neighbour by AJCC stage, so
# the two lists share no string while both being breast cancer. Nothing is
# merged here, exactly as with site names.
if data["conditions"]:
    st.markdown(
        "**This trial is tagged:** " + " · ".join(data["conditions"])
    )
    st.caption(
        "Compare against the “Its conditions” column below. Tags are free "
        "text the sponsor wrote and nothing is merged, so two trials can "
        "study the same disease and share no tag at all."
    )

ROUTES = [
    (
        "by_site",
        "Same hospitals",
        "Trials running at sites this one also uses. A large overlap can mean a "
        "shared hospital network rather than a shared subject — read the "
        "conditions column before drawing a conclusion.",
    ),
    (
        "by_investigator",
        "Same investigator",
        "Trials sharing a named official with this one. The strongest people-level "
        "link the registry supports, since the collaborator field excludes individuals.",
    ),
    (
        "by_intervention",
        "Same intervention term",
        "Trials registering the same intervention wording. Unmerged, so this "
        "under-counts a drug that appears under several names.",
    ),
]

tabs = st.tabs([label for _, label, _ in ROUTES])
for tab, (key, label, explanation) in zip(tabs, ROUTES):
    with tab:
        st.caption(explanation)
        rows = neighbours[key]
        total = neighbours[f"{key}_total"]

        if not rows:
            st.info(
                f"No other tracked trial connects to this one that way. That's a "
                f"real answer, not a missing one — nothing else we track shares "
                f"{'a site' if key == 'by_site' else 'an investigator' if key == 'by_investigator' else 'an intervention term'} "
                "with it."
            )
            continue

        if len(rows) < total:
            st.caption(f"Showing the top {len(rows)} of **{total:,}**, most shared first.")
        else:
            st.caption(f"All {total:,}, most shared first.")

        table = pd.DataFrame(
            [
                {
                    "NCT ID": n["nct_id"],
                    "Trial": n["brief_title"],
                    "Shared": n["shared"],
                    "Which": ", ".join(n["shared_names"]) if n["shared_names"] else "—",
                    "Its conditions": " · ".join(n["conditions"]) or "None on file",
                    "Status": n["overall_status"].replace("_", " ").title(),
                }
                for n in rows
            ]
        )
        event = st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key=f"explore_neighbours_{key}",
        )
        selected = event.selection.rows if event and event.selection else []
        if selected:
            chosen = rows[selected[0]]["nct_id"]
            open_col, explore_col = st.columns(2)
            if open_col.button(f"Open {chosen} in Understand →", key=f"understand_{key}"):
                st.session_state["selected_nct_id"] = chosen
                st.switch_page("pages/2_Understand.py")
            if explore_col.button(f"Explore {chosen} →", key=f"explore_{key}"):
                st.session_state["selected_nct_id"] = chosen
                # The widget's own key, not just selected_nct_id — see the
                # comment on the text input. Walking the graph one hop at a
                # time is the whole point of the page, and it silently did
                # nothing until this line existed.
                st.session_state["explore_nct_input"] = chosen
                st.rerun()
