"""Understand: full detail for one trial, tracked or not.

Reading comprehension, not eligibility determination — CLAUDE.md sec. 2
is explicit that this system never decides whether a real person
qualifies for a trial. Every field here is exactly what's stored (source:
ClinicalTrials.gov, via our own DB or a live single-trial fetch), shown
as source text with its own uncertainty made explicit, never an
inference dressed up as a fact.

GET /discover/{nct_id} checks our DB first, then falls back to a live
CT.gov lookup — the same tracked-or-live split as Discover's search,
applied to a single trial. A live result has no fetched_at/last_matched_at
or change history, since those describe a trial we actually track.
"""
import streamlit as st

from api_client import ApiError, get

st.set_page_config(page_title="Understand — TrialLens", page_icon="📄")
st.title("Understand")

default_nct_id = st.session_state.get("selected_nct_id", "")
nct_id = st.text_input("NCT ID", value=default_nct_id, placeholder="e.g. NCT00070564").strip().upper()

if not nct_id:
    st.caption("Pick a trial from Discover, or paste an NCT ID above.")
    st.stop()

try:
    study = get(f"/discover/{nct_id}")
except ApiError as exc:
    if exc.status_code == 404:
        st.warning(f"{nct_id} doesn't match any trial, locally or on ClinicalTrials.gov — check the ID.")
    else:
        st.error(str(exc))
    st.stop()

is_live = study["source"] == "live"

st.header(study["brief_title"])
if study.get("official_title") and study["official_title"] != study["brief_title"]:
    st.caption(study["official_title"])

if is_live:
    st.info(
        "This trial isn't in our tracked database — showing a live "
        "snapshot fetched from ClinicalTrials.gov just now. No change "
        "history is available since we don't track it."
    )

status_col, phase_col, type_col = st.columns(3)
status_col.metric("Status", study["overall_status"])
phase_col.metric("Phase", study["phase"] or "—")
type_col.metric("Study type", study["study_type"] or "—")

if not is_live and study["active_in_scope"] is False:
    st.warning(
        "This trial no longer matches its tracked condition's active/recency "
        "filter — kept for history, not deleted. Treat its status as "
        "possibly stale until re-checked."
    )

st.subheader("Conditions")
st.write(", ".join(study["conditions"]) or "—")

st.subheader("Eligibility — source text, not an assessment")
st.caption(
    "This is ClinicalTrials.gov's own eligibility criteria text for this "
    "trial. TrialLens never determines whether a specific person qualifies "
    "— that requires review against the full protocol."
)
sex_col, age_col, hv_col = st.columns(3)
sex_col.write(f"**Sex:** {study['sex'] or '—'}")
age_col.write(f"**Minimum age:** {study['minimum_age'] or '—'}")
hv = study["healthy_volunteers"]
hv_col.write(f"**Healthy volunteers:** {'—' if hv is None else ('Yes' if hv else 'No')}")

if study.get("eligibility_criteria"):
    with st.expander("Full eligibility criteria (source text)"):
        st.text(study["eligibility_criteria"])
else:
    st.caption("No eligibility criteria text on file — insufficient information, not zero criteria.")

st.subheader("Enrollment")
st.write(study["enrollment_count"] if study["enrollment_count"] is not None else "—")

if is_live:
    st.caption("Fetched just now, live · source: ClinicalTrials.gov")
else:
    st.caption(
        f"Fetched {study['fetched_at']} · last matched tracking criteria "
        f"{study['last_matched_at']} · source: ClinicalTrials.gov"
    )
st.markdown(f"[View {nct_id} on ClinicalTrials.gov ↗](https://clinicaltrials.gov/study/{nct_id})")

if not is_live:
    st.subheader("Change history")
    try:
        change_log = get(f"/studies/{nct_id}/changes")
    except ApiError as exc:
        st.caption(f"Could not load change history: {exc}")
    else:
        if not change_log["changes"]:
            st.caption("No changes detected yet for this trial.")
        else:
            for change in change_log["changes"]:
                st.write(
                    f"**{change['field_name']}** — "
                    f"{change['old_value'] or '—'} → {change['new_value'] or '—'} "
                    f"({change['detected_at']})"
                )
