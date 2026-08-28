"""TrialLens — entry point. A quiet connectivity check runs on load; it
only speaks up if the API (the only door to the database) is actually
unreachable, matching how every other page here only surfaces problems,
not confirmations that things are fine."""
import streamlit as st

from api_client import ApiError, get

st.set_page_config(page_title="TrialLens", page_icon="🔬", layout="wide")

st.title("TrialLens")
st.caption(
    "Search clinical trials by condition, and see each trial's full "
    "detail — including how it's changed since we started tracking it. "
    "Built for following a therapeutic area over time, not just a "
    "one-off search."
)

try:
    get("/health")
except ApiError as exc:
    st.error(str(exc))

st.markdown(
    "Use the sidebar to **Discover** trials for a condition, or open "
    "**Understand** for a specific trial's full detail."
)
