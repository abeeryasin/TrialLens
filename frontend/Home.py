"""TrialLens — entry point. Landing page + a live check that the API
(the only door to the database) is actually reachable before any page
tries to use it."""
import streamlit as st

from api_client import ApiError, get

st.set_page_config(page_title="TrialLens", page_icon="🔬")

st.title("TrialLens")
st.caption("Clinical-trial intelligence for a therapeutic area, tracked over time.")

try:
    health = get("/health")
    st.success(f"Connected to the API — status: {health.get('status')}")
except ApiError as exc:
    st.error(str(exc))

st.markdown(
    "Use the sidebar to **Discover** trials for a condition, or open "
    "**Understand** for a specific trial's full detail."
)
