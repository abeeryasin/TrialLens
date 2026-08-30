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
from labels import (
    CATEGORY_TRACKING,
    ENROLLMENT_TYPE_CAPTIONS,
    FIELD_LABELS,
    STRUCTURED_FIELDS,
    format_detected_at,
    humanize_value,
    render_structured_diff,
)

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
status_col.markdown(f"**Status**\n\n{study['overall_status']}")
phase_col.markdown(f"**Phase**\n\n{study['phase'] or '—'}")
type_col.markdown(f"**Study type**\n\n{study['study_type'] or '—'}")

if not is_live and study["active_in_scope"] is False:
    reason = study.get("tracking_note") or (
        "We can't tell from the data we've stored exactly why it stopped being tracked."
    )
    st.warning(
        f"We're no longer tracking this trial for updates — its record is kept "
        f"for history, not deleted, so treat the details below as possibly out "
        f"of date. {reason}"
    )

st.subheader("Conditions")
st.write(", ".join(study["conditions"]) or "—")

if study.get("brief_summary"):
    st.subheader("What this trial is studying")
    st.write(study["brief_summary"])

if study.get("interventions"):
    st.subheader("Intervention" + ("s" if len(study["interventions"]) > 1 else ""))
    for iv in study["interventions"]:
        label = iv.get("name") or "—"
        if iv.get("type"):
            label = f"{label} ({iv['type']})"
        st.markdown(f"**{label}**")
        if iv.get("description"):
            st.caption(iv["description"])

if study.get("primary_outcomes"):
    st.subheader("Primary outcome" + ("s" if len(study["primary_outcomes"]) > 1 else ""))
    st.caption("What defines success for this trial.")
    for o in study["primary_outcomes"]:
        st.markdown(f"**{o.get('measure') or '—'}**")
        details = []
        if o.get("time_frame"):
            details.append(f"Time frame: {o['time_frame']}")
        if o.get("description"):
            details.append(o["description"])
        if details:
            st.caption(" · ".join(details))

detail_cols = st.columns(4)
detail_cols[0].markdown(f"**Sponsor**\n\n{study.get('lead_sponsor') or '—'}")
detail_cols[1].markdown(f"**Start date**\n\n{study.get('start_date') or '—'}")
detail_cols[2].markdown(f"**Primary completion**\n\n{study.get('primary_completion_date') or '—'}")
detail_cols[3].markdown(f"**Completion**\n\n{study.get('completion_date') or '—'}")

if study.get("locations"):
    locs = study["locations"]
    st.subheader("Locations")
    countries = sorted({loc["country"] for loc in locs if loc.get("country")})
    st.caption(f"{len(locs)} site(s)" + (f" across {', '.join(countries)}" if countries else ""))
    with st.expander(f"All {len(locs)} location(s)"):
        for loc in locs:
            parts = [p for p in (loc.get("facility"), loc.get("city"), loc.get("country")) if p]
            st.write(", ".join(parts) or "—")

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
if study["enrollment_count"] is None:
    st.write("—")
else:
    st.write(f"{study['enrollment_count']:,} participants")
    # The bare number is ambiguous on its own: most CT.gov records report a
    # recruitment target, not a real headcount. Say which — and say so
    # honestly when CT.gov didn't specify.
    st.caption(ENROLLMENT_TYPE_CAPTIONS.get(
        study.get("enrollment_type"),
        "ClinicalTrials.gov doesn't say whether this is an actual count or a target.",
    ))

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
            changes = change_log["changes"]
            if len(changes) == 1 and changes[0]["field_name"] == "last_update_post_date":
                st.caption(
                    "ClinicalTrials.gov marked this record as updated, but none "
                    "of the other fields we track changed value — the real "
                    "change may be in something we don't parse yet (e.g. "
                    "contacts, oversight)."
                )

            def render_change(change):
                label = FIELD_LABELS.get(change["field_name"], change["field_name"])
                detected_at = format_detected_at(change["detected_at"])
                if change["field_name"] in STRUCTURED_FIELDS:
                    st.markdown(f"**{label}** changed ({detected_at})")
                    render_structured_diff(change["old_value"], change["new_value"])
                else:
                    old_display = humanize_value(change["field_name"], change["old_value"])
                    new_display = humanize_value(change["field_name"], change["new_value"])
                    st.write(f"**{label}** — {old_display} → {new_display} ({detected_at})")

            # Split by kind: a real registry change (status, eligibility,
            # outcomes) shouldn't get buried between our own tracking
            # bookkeeping lines — they answer different questions.
            content_changes = [c for c in changes if c.get("category") != CATEGORY_TRACKING]
            tracking_changes = [c for c in changes if c.get("category") == CATEGORY_TRACKING]

            if content_changes:
                st.markdown("**What ClinicalTrials.gov changed**")
                for change in content_changes:
                    render_change(change)
            if tracking_changes:
                st.markdown("**Our tracking of this trial**")
                st.caption(
                    "Not changes to the trial itself — whether we're still "
                    "checking it for updates."
                )
                for change in tracking_changes:
                    render_change(change)
