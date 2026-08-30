"""Monitor: what's changed, across every tracked trial, in one place.

Understand already shows a per-trial change history, but that requires
already knowing which nct_id to look at. This page answers the actual
question a researcher tracking a therapeutic area over time would ask:
"what changed recently, anywhere I'm tracking?" (docs/decisions.md,
2026-08-29, "Monitor gets its own roadmap step").

Same st.dataframe + on_select="rerun" + session-state click-through
pattern as Discover, reused rather than reinvented.
"""
import pandas as pd
import streamlit as st

from api_client import ApiError, get
from labels import (
    CATEGORY_TRACKING,
    CATEGORY_TRIAL_CONTENT,
    FIELD_LABELS,
    STRUCTURED_FIELDS,
    format_detected_at,
    humanize_value,
    is_long_text,
    render_structured_diff,
    render_text_diff,
    summarize_text_change,
)

st.set_page_config(page_title="Monitor — TrialLens", page_icon="🛰️", layout="wide")
st.title("Monitor")
st.caption(
    "Recent changes ClinicalTrials.gov made to trials we track, newest "
    "first. Runs automatically every 6 hours — this page just shows what "
    "it's found."
)

PAGE_SIZE = 25

# The whole script reruns on every click, so the current page has to be
# remembered in session_state the same way selected_nct_id already is —
# otherwise "Next" would always land back on page 0.
if "monitor_page" not in st.session_state:
    st.session_state["monitor_page"] = 0

filter_col1, filter_col2, filter_col3 = st.columns(3)
with filter_col1:
    try:
        tracked_conditions = get("/tracked-conditions")
    except ApiError:
        tracked_conditions = []
    condition_choice = st.selectbox("Condition", ["All"] + tracked_conditions)
with filter_col2:
    category_choice = st.selectbox(
        "Change type",
        ["All", CATEGORY_TRIAL_CONTENT, CATEGORY_TRACKING],
        help=(
            "Trial content = something ClinicalTrials.gov reports about the trial "
            "itself. Tracking = whether we're still watching it for updates."
        ),
    )
with filter_col3:
    try:
        all_fields = get("/changes/fields")
    except ApiError:
        all_fields = []
    # Only offer fields belonging to the chosen change type, so the two
    # filters can never combine into a guaranteed-empty result. The
    # category comes from the API, not a second copy of the rule here.
    available_fields = [
        f["name"] for f in all_fields
        if category_choice == "All" or f["category"] == category_choice
    ]
    # With only one field to choose from, "All" and that field are the same
    # query — offering both is a choice that isn't really a choice. Not
    # hardcoded to the Tracking category: it holds for any category that
    # currently has exactly one field with real changes on record.
    field_options = available_fields if len(available_fields) == 1 else ["All"] + available_fields
    field_choice = st.selectbox(
        "Field changed", field_options, format_func=lambda f: "All" if f == "All" else FIELD_LABELS.get(f, f)
    )

# Two read-only time filters. Neither changes what's tracked — they only
# narrow what this page displays (deliberately not the ingest recency
# window, which decides what gets monitored at all; see docs/decisions.md,
# 2026-08-30, on why that window stays at 24 months).
time_col1, time_col2, _ = st.columns(3)
with time_col1:
    detected_choice = st.selectbox(
        "Detected",
        ["Any time", "Last 24 hours", "Last 7 days", "Last 30 days", "Last 90 days"],
        help="When TrialLens noticed the change.",
    )
with time_col2:
    freshness_choice = st.selectbox(
        "Trial last updated",
        ["Any", "Within 30 days", "Within 90 days", "Within a year"],
        help="How recently ClinicalTrials.gov itself updated the trial — hides changes on long-dormant records.",
    )

DETECTED_DAYS = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}
FRESHNESS_DAYS = {"Within 30 days": 30, "Within 90 days": 90, "Within a year": 365}

# A changed filter means the previous page number may no longer make
# sense against the new, smaller result set — reset to page 1 rather
# than risk landing past the end.
filter_key = (condition_choice, category_choice, field_choice, detected_choice, freshness_choice)
if st.session_state.get("monitor_last_filter") != filter_key:
    st.session_state["monitor_page"] = 0
    st.session_state["monitor_last_filter"] = filter_key

params = {"limit": PAGE_SIZE, "offset": st.session_state["monitor_page"] * PAGE_SIZE}
if condition_choice != "All":
    params["condition"] = condition_choice
if category_choice != "All":
    params["category"] = category_choice
if field_choice != "All":
    params["field_name"] = field_choice
if detected_choice in DETECTED_DAYS:
    params["detected_within_days"] = DETECTED_DAYS[detected_choice]
if freshness_choice in FRESHNESS_DAYS:
    params["trial_updated_within_days"] = FRESHNESS_DAYS[freshness_choice]

try:
    response = get("/changes", params)
except ApiError as exc:
    st.error(str(exc))
    st.stop()

total = response["total"]
total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
current_page = st.session_state["monitor_page"]

distinct_trials = response["distinct_trials"]
st.caption(f"{total} change(s) detected across {distinct_trials} distinct trial(s).")

nav_prev, nav_label, nav_next = st.columns([1, 2, 1])
with nav_prev:
    if st.button("◀ Previous", disabled=current_page <= 0):
        st.session_state["monitor_page"] -= 1
        st.rerun()
with nav_label:
    st.markdown(f"<div style='text-align:center'>Page {current_page + 1} of {total_pages}</div>", unsafe_allow_html=True)
with nav_next:
    if st.button("Next ▶", disabled=current_page + 1 >= total_pages):
        st.session_state["monitor_page"] += 1
        st.rerun()

results = response["results"]
if not results:
    st.info("No changes detected yet.")
else:
    table = pd.DataFrame(results)
    table["field_name"] = table["field_name"].map(lambda f: FIELD_LABELS.get(f, f))

    def display_value(row, col):
        if row["field_name_raw"] in STRUCTURED_FIELDS:
            return "(changed — select the row for detail)"
        # A long text field (eligibility criteria runs ~4,000 characters)
        # dumped into both cells makes the table unreadable and buries what
        # actually moved. Show a short preview here; the real word-level
        # diff renders below when the row is selected.
        if is_long_text(row["old_value"], row["new_value"]):
            text = row[col] or "—"
            return text[:70].rstrip() + "…" if len(text) > 70 else text
        return humanize_value(row["field_name_raw"], row[col])

    table["field_name_raw"] = [r["field_name"] for r in results]
    table["old_value"] = table.apply(lambda r: display_value(r, "old_value"), axis=1)
    table["new_value"] = table.apply(lambda r: display_value(r, "new_value"), axis=1)
    table["detected_at"] = table["detected_at"].map(format_detected_at)

    table = table[["nct_id", "brief_title", "field_name", "old_value", "new_value", "detected_at"]]
    table.columns = ["NCT ID", "Trial", "Field changed", "Before", "After", "Detected"]

    event = st.dataframe(
        table,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"monitor_changes_table_{current_page}",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        selected = results[selected_rows[0]]
        selected_nct_id = selected["nct_id"]
        if st.button(f"View {selected_nct_id} →"):
            st.session_state["selected_nct_id"] = selected_nct_id
            st.switch_page("pages/2_Understand.py")

        if selected.get("tracking_note"):
            st.info(selected["tracking_note"])
        elif selected["field_name"] == "active_in_scope" and selected["new_value"] == "false":
            st.caption(
                "We can't tell from the data we've stored why this trial stopped "
                "being tracked."
            )

        selected_label = FIELD_LABELS.get(selected["field_name"], selected["field_name"])
        if selected["field_name"] in STRUCTURED_FIELDS:
            with st.expander(f"Show full before/after — {selected_label}"):
                render_structured_diff(selected["old_value"], selected["new_value"])
        elif is_long_text(selected["old_value"], selected["new_value"]):
            summary = summarize_text_change(selected["old_value"], selected["new_value"])
            with st.expander(f"{selected_label} — {summary}"):
                render_text_diff(selected["old_value"], selected["new_value"])
    else:
        st.caption("Click a row to select a trial, then View.")
