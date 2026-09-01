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
    ASPECT_CAPTIONS,
    CATEGORY_TRACKING,
    ENROLLMENT_TYPE_CAPTIONS,
    FIELD_LABELS,
    format_age_range,
    STRUCTURED_FIELDS,
    format_detected_at,
    format_posted_on,
    format_recording_since,
    humanize_value,
    is_long_text,
    render_structured_diff,
    render_text_diff,
    summarize_text_change,
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

status_col, phase_col, type_col, results_col = st.columns(4)
status_col.markdown(f"**Status**\n\n{study['overall_status']}")
phase_col.markdown(f"**Phase**\n\n{study['phase'] or '—'}")
type_col.markdown(f"**Study type**\n\n{study['study_type'] or '—'}")

# Whether the findings are published — the thing a researcher following a
# trial is ultimately waiting for. Three states, not two: None means we
# have no record of it (a live snapshot from before this was stored), which
# is different from knowing there are none (sec. 2).
has_results = study.get("has_results")
if has_results is None:
    results_col.markdown("**Results**\n\nNot recorded")
elif has_results:
    results_col.markdown("**Results**\n\n✅ Posted")
else:
    results_col.markdown("**Results**\n\nNot yet posted")

if not is_live and study["active_in_scope"] is False:
    reason = study.get("tracking_note") or (
        "We can't tell from the data we've stored exactly why it stopped being tracked."
    )
    st.warning(
        f"We're no longer tracking this trial for updates — its record is kept "
        f"for history, not deleted, so treat the details below as possibly out "
        f"of date. {reason}"
    )

# Amendment history leads the page, deliberately (docs/plan_after_ranking.md):
# a trial's changes are its headline, not a footnote. ClinicalTrials.gov can
# show you what a trial says today; only this section can show what it used
# to say. The static detail below is the same in every registry.

if not is_live:
    st.subheader("Amendment history")

    def render_change(change, show_detected_at=False):
        """One changed field. The amendment above it carries the date, so
        the per-field detected_at is off by default — repeating the same
        timestamp on every line was noise once these are grouped."""
        label = FIELD_LABELS.get(change["field_name"], change["field_name"])
        suffix = f" ({format_detected_at(change['detected_at'])})" if show_detected_at else ""
        effect = change.get("effect")

        if change["field_name"] in STRUCTURED_FIELDS:
            # A structured field's effect line ("6 sites added, 1 removed")
            # replaces the diff rather than accompanying it: one real
            # amendment stores 252,041 characters of locations JSON, and
            # rendering that is neither readable nor useful.
            if effect:
                st.markdown(f"**{label}** — {effect}{suffix}")
            else:
                st.markdown(f"**{label}** changed{suffix}")
                render_structured_diff(change["old_value"], change["new_value"])
        elif is_long_text(change["old_value"], change["new_value"]):
            summary = summarize_text_change(change["old_value"], change["new_value"])
            st.markdown(f"**{label}** — {summary}{suffix}")
            with st.expander("Show what changed"):
                render_text_diff(change["old_value"], change["new_value"])
        else:
            old_display = humanize_value(change["field_name"], change["old_value"])
            new_display = humanize_value(change["field_name"], change["new_value"])
            line = f"**{label}** — {old_display} → {new_display}"
            # The effect is a deterministic restatement of the two values
            # beside it, never an interpretation of them. Shown inline so
            # the reader can check it against the values in the same glance.
            if effect:
                line += f"  ·  *{effect}*"
            st.write(line + suffix)

    try:
        history = get(f"/studies/{nct_id}/amendments")
    except ApiError as exc:
        st.caption(f"Could not load amendment history: {exc}")
    else:
        amendments = history["amendments"]
        recording_since = format_recording_since(history.get("recording_since"))

        # The window is stated on every path, including the empty one. A
        # count of amendments means nothing without it: this history starts
        # when TrialLens started watching, not when the trial was
        # registered, and a trial amended eleven times before that shows
        # none of them here (CLAUDE.md sec. 2 — never imply a completeness
        # the data doesn't have).
        if not amendments:
            st.caption(
                f"No amendments recorded. TrialLens has been watching for "
                f"changes since {recording_since}; ClinicalTrials.gov does not "
                f"publish a record's earlier versions, so anything amended "
                f"before then cannot be shown here."
            )
        else:
            n = len(amendments)
            times = {1: "once", 2: "twice", 3: "three times"}.get(n, f"{n} times")
            st.markdown(
                f"**Amended {times}** since TrialLens started watching "
                f"on {recording_since}."
            )
            if history.get("invisible_amendment_count"):
                st.caption(
                    f"{history['invisible_amendment_count']} of these changed only "
                    f"fields TrialLens doesn't store — marked below."
                )

            for position, amendment in enumerate(amendments):
                posted = format_posted_on(amendment["posted_on"])

                # An amendment we can't see gets ONE line, not a heading, a
                # caption and an info box. It was previously given more
                # visual weight than an amendment with four real field
                # changes — which inverts the hierarchy, since the whole
                # point of this page is what actually moved. Still never
                # silent: CT.gov posted a version, so something changed, and
                # rendering that as nothing would be a false claim (sec. 2).
                if not amendment["content_is_visible"]:
                    st.caption(
                        f"**{posted}** — amended, but only in fields TrialLens "
                        f"doesn't store. The record changed; we can't show what."
                    )
                    continue

                st.markdown(f"##### Posted {posted}")
                if amendment["previously_posted_on"]:
                    st.caption(
                        f"Previous version posted "
                        f"{format_posted_on(amendment['previously_posted_on'])} · "
                        f"TrialLens saw this on "
                        f"{format_detected_at(amendment['detected_at'])}"
                    )
                # Grouped by which aspect of the trial moved, most
                # consequential first, so a rewritten primary outcome is read
                # before a retitle. The grouping is a field-name lookup in
                # api/amendments.py — deterministic, not a judgement.
                for aspect in amendment["aspects"]:
                    in_aspect = [
                        c for c in amendment["changes"]
                        if (c.get("aspect") or "Uncategorised") == aspect
                    ]
                    st.caption(ASPECT_CAPTIONS.get(aspect, aspect))
                    for change in in_aspect:
                        render_change(change)

                # Between amendments only. A rule after the last one closes a
                # section that has already ended, and reads as something
                # missing below it.
                if position < len(amendments) - 1:
                    st.divider()

        if history.get("unattributed_changes"):
            # Should never happen; shown rather than dropped, because a
            # silently discarded change makes a trial look quieter than it
            # was. See AmendmentHistory.unattributed_changes.
            st.warning(
                "These recorded changes could not be matched to an amendment. "
                "That shouldn't happen — please report it."
            )
            for change in history["unattributed_changes"]:
                render_change(change, show_detected_at=True)

    # Our own bookkeeping — deliberately below the amendments and visually
    # separate. Whether we're still checking a trial is not something the
    # sponsor did, and burying it among real amendments blurs that line.
    try:
        change_log = get(f"/studies/{nct_id}/changes")
    except ApiError:
        pass
    else:
        tracking_changes = [
            c for c in change_log["changes"] if c.get("category") == CATEGORY_TRACKING
        ]
        if tracking_changes:
            st.subheader("Our tracking of this trial")
            st.caption(
                "Not changes to the trial itself — whether we're still "
                "checking it for updates."
            )
            for change in tracking_changes:
                render_change(change, show_detected_at=True)


st.divider()

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
    # No explanatory caption here on purpose: "primary outcome" is standard
    # vocabulary for the clinical researcher this is built for (CLAUDE.md
    # sec. 1), so defining it on every trial is repetition, not help. The
    # eligibility caption below is a different thing entirely — a safety
    # disclaimer required by sec. 2, not a definition — and stays.
    st.subheader("Primary outcome" + ("s" if len(study["primary_outcomes"]) > 1 else ""))
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
age_col.write(f"**Age:** {format_age_range(study.get('minimum_age'), study.get('maximum_age'))}")
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
