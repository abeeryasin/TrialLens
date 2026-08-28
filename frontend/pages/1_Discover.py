"""Discover: search a therapeutic area, tracked or not.

Uses st.form so typing in the search box doesn't trigger a rerun on
every keystroke — only the "Search" click does. The response is stashed
in st.session_state because a later rerun (e.g. clicking "View" on a
result row below) would otherwise throw the results away, same as any
other Streamlit rerun.
"""
import pandas as pd
import streamlit as st

from api_client import ApiError, get

st.set_page_config(page_title="Discover — TrialLens", page_icon="🔎", layout="wide")
st.title("Discover")
st.caption(
    "Search any condition or therapeutic area. Ones we're actively "
    "tracking show our own regularly-updated data; anything else is "
    "looked up live from ClinicalTrials.gov."
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
        results = response["results"]
        table = pd.DataFrame(results)
        table["phase"] = table["phase"].fillna("—")
        table["last_update_post_date"] = table["last_update_post_date"].fillna("—")
        table["source"] = table["source"].map({"tracked": "📋 tracked", "live": "🌐 live"})
        table = table[["nct_id", "brief_title", "overall_status", "phase", "last_update_post_date", "source"]]
        table.columns = ["NCT ID", "Title", "Status", "Phase", "Last updated", "Source"]

        # A real data grid, not a hand-rolled st.columns layout: it sizes
        # columns to their actual content instead of forcing short values
        # like "PHASE1" or an NCT ID to wrap onto two lines just because a
        # fixed-ratio column happened to be too narrow.
        event = st.dataframe(
            table,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="discover_results_table",
        )

        selected_rows = event.selection.rows if event and event.selection else []
        if selected_rows:
            selected_nct_id = results[selected_rows[0]]["nct_id"]
            if st.button(f"View {selected_nct_id} →"):
                st.session_state["selected_nct_id"] = selected_nct_id
                st.switch_page("pages/2_Understand.py")
        else:
            st.caption("Click a row to select a trial, then View.")
