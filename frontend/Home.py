"""TrialLens — entry point. A quiet connectivity check runs on load; it
only speaks up if the API (the only door to the database) is actually
unreachable, matching how every other page here only surfaces problems,
not confirmations that things are fine.

Five real capabilities (CLAUDE.md sec. 1): Discover, Understand, Monitor,
Explore, Investigate. Discover/Understand/Monitor all have their own
pages now; Explore/Investigate aren't built yet. The grid below says
exactly which is which — never implies a capability is live when it
isn't.
"""
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
    st.stop()

col1, col2 = st.columns(2)
try:
    total_tracked = get("/studies", {"limit": 1})["total"]
    col1.metric("Trials tracked", f"{total_tracked:,}")
except ApiError:
    pass
try:
    conditions = get("/tracked-conditions")
    col2.metric("Conditions actively monitored", len(conditions))
    col2.caption(", ".join(conditions))
except ApiError:
    pass

st.divider()
st.subheader("What TrialLens does")

capabilities = [
    {
        "icon": "🔎",
        "name": "Discover",
        "desc": "Search any condition. Tracked ones show our own regularly-updated data; anything else is looked up live.",
        "page": "pages/1_Discover.py",
        "status": "live",
    },
    {
        "icon": "📄",
        "name": "Understand",
        "desc": "A trial's full detail — what it studies, who's eligible, what's changed — not just a fitness score.",
        "page": "pages/2_Understand.py",
        "status": "live",
    },
    {
        "icon": "🛰️",
        "name": "Monitor",
        "desc": "Runs on its own every 6 hours, checking every tracked trial for real changes — see what's changed across everything, in one feed.",
        "page": "pages/3_Monitor.py",
        "status": "live",
    },
    {
        "icon": "⭐",
        "name": "Ranking",
        "desc": "Score tracked trials by fit to your research interest — with visible evidence for every score, not a black box.",
        "page": None,
        # POST /rank works and is tested; nothing renders it yet, so this
        # stays "planned". Marking it live because the backend exists would
        # be exactly the thing this page's docstring forbids.
        "status": "planned",
    },
    {
        "icon": "🕸️",
        "name": "Explore",
        "desc": "How trials, sponsors, and interventions connect to each other.",
        "page": None,
        "status": "planned",
    },
    {
        "icon": "🧭",
        "name": "Investigate",
        "desc": "Synthesis across everything tracked — patterns across trials, not just within one.",
        "page": None,
        "status": "planned",
    },
]

cols = st.columns(len(capabilities))
for col, cap in zip(cols, capabilities):
    with col:
        st.markdown(f"#### {cap['icon']} {cap['name']}")
        st.caption(cap["desc"])
        if cap["status"] == "live":
            if st.button(f"Open {cap['name']} →", key=f"open_{cap['name']}", width="stretch"):
                st.switch_page(cap["page"])
        elif cap["status"] == "background":
            st.caption("🟢 Running now — see its results in Understand's change history.")
        else:
            st.caption("⚪ Not built yet.")
