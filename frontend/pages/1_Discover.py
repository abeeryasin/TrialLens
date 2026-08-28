"""Discover: search a therapeutic area, tracked or not.

Uses st.form so typing in the search box doesn't trigger a rerun on
every keystroke — only the "Search" click does. The response is stashed
in st.session_state because a later rerun (e.g. clicking "View" on a
result row below) would otherwise throw the results away, same as any
other Streamlit rerun.
"""
import streamlit as st

from api_client import ApiError, get

st.set_page_config(page_title="Discover — TrialLens", page_icon="🔎")
st.title("Discover")
st.caption(
    "Search a therapeutic area. A condition Monitor comprehensively tracks "
    "is served from our own data; anything else falls back to a live "
    "ClinicalTrials.gov lookup, or a mix of both — see the note below "
    "each search for which applies."
)

with st.form("discover_search"):
    condition = st.text_input("Condition / therapeutic area", placeholder="e.g. breast cancer, psoriasis")
    limit = st.slider("Max results", min_value=5, max_value=100, value=25, step=5)
    submitted = st.form_submit_button("Search")

if submitted:
    if not condition.strip():
        st.warning("Enter a condition to search.")
        st.session_state.pop("discover_response", None)
    else:
        try:
            st.session_state["discover_response"] = get(
                "/discover", {"condition": condition, "limit": limit}
            )
        except ApiError as exc:
            st.session_state.pop("discover_response", None)
            st.error(str(exc))

response = st.session_state.get("discover_response")
if response:
    st.info(response["note"])
    st.caption(f"{response['total']} result(s) for \"{response['condition']}\"")

    if not response["results"]:
        st.warning("No trials found for this condition.")
    else:
        widths = [1.4, 3.6, 1.3, 0.9, 1.3, 1.1, 0.9]
        header_cols = st.columns(widths)
        for col, label in zip(header_cols, ["NCT ID", "Title", "Status", "Phase", "Last updated", "Source", ""]):
            if label:
                col.markdown(f"**{label}**")

        for result in response["results"]:
            cols = st.columns(widths)
            cols[0].write(result["nct_id"])
            cols[1].write(result["brief_title"])
            cols[2].write(result["overall_status"])
            cols[3].write(result["phase"] or "—")
            cols[4].write(str(result["last_update_post_date"] or "—"))
            cols[5].write("📋 tracked" if result["source"] == "tracked" else "🌐 live")
            if cols[6].button("View →", key=f"view_{result['nct_id']}"):
                st.session_state["selected_nct_id"] = result["nct_id"]
                st.switch_page("pages/2_Understand.py")
