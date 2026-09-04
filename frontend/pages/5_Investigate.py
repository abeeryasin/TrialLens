"""Investigate: what's happened across everything tracked?

The fifth capability, and the only screen that asks a question about the
corpus rather than about a trial. Discover reads a field, Understand reads
a record, Monitor reads a diff one row at a time, Explore reads one
trial's neighbourhood. None of them can say "54 trials pushed a primary
completion date, median six months, and one reopened after being marked
complete" — those numbers are not stored anywhere.

Two tabs, because two genuinely different questions were being run
together:

  1. **What changed** — the watch window. Primary outcomes lead, not
     because they are the commonest finding (they are the rarest) but
     because they are the one thing a researcher cannot get from the
     registry itself, and outside evidence says they matter: 31.7% of
     registered studies have had a primary outcome changed, and the
     changed ones overstate effect size by 16% (docs/decisions.md).
  2. **The field** — what has been done in this area at all. Added
     2026-09-04 after the honest observation that Explore answers "who
     else works on THIS trial" and nothing answered "what does breast
     cancer research look like".

What this page must keep saying out loud:

  - **Every figure carries its denominator.** 54 slips means nothing
    without 355 amendments over 11,444 tracked trials.
  - **The record starts 2026-08-28.** A 90-day window is mostly days
    nobody was watching, and reporting those as quiet is the step-4
    under-reporting bug wearing a new hat.
  - **An outcome change is never an accusation.** The page says what
    changed, when it changed relative to the trial's own milestones, and
    that it requires review — CLAUDE.md sec. 2's vocabulary, the same one
    used for eligibility.
  - **Zero is a finding, stated in words.** An empty box reads as a bug.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import charts
from api_client import ApiError, get

st.set_page_config(page_title="Investigate — TrialLens", page_icon="🧭", layout="wide")
st.title("Investigate")
st.caption(
    "What's happened across everything tracked — patterns across trials, "
    "not inside one."
)

WHOLE_WATCH = "Everything tracked"

try:
    tracked_conditions = get("/tracked-conditions")
except ApiError:
    tracked_conditions = []

# How far back the change record actually goes. Asked BEFORE the window
# selector is drawn, because offering "last 90 days" over a 7-day record
# invites a question the page cannot answer honestly — "how can you show
# what changed in 30 days when you weren't watching?" was the first thing
# real use produced (2026-09-04). The options are now bounded by the record.
try:
    watch = get("/watch")
    recording_since = watch.get("recording_since")
except ApiError:
    recording_since = None

days_of_record = None
if recording_since:
    started = datetime.fromisoformat(recording_since.replace("Z", "+00:00"))
    days_of_record = max(1, (datetime.now(timezone.utc) - started).days + 1)

if days_of_record:
    window_options = [d for d in (1, 3, 7, 14, 30, 90) if d < days_of_record]
    window_options.append(days_of_record)
else:
    window_options = [7, 14, 30]


def window_label(days):
    if days_of_record and days == days_of_record:
        return f"The whole record ({days} days)"
    return f"Last {days} day{'s' if days != 1 else ''}"


controls = st.columns([3, 2])
with controls[0]:
    condition_choice = st.selectbox(
        "Area", [WHOLE_WATCH] + sorted(tracked_conditions), index=0
    )
with controls[1]:
    window_days = st.selectbox(
        "Window", window_options, index=len(window_options) - 1,
        format_func=window_label,
    )

if days_of_record:
    st.caption(
        f"TrialLens started recording changes on "
        f"{recording_since[:10]} — {days_of_record} days ago. Nothing before "
        "that was watched, so no window reaches further back than this."
    )

condition = None if condition_choice == WHOLE_WATCH else condition_choice
params = {"days": window_days}
if condition:
    params["condition"] = condition

changed_tab, field_tab = st.tabs(["What changed", "The field"])


def plural(n, singular, plural_word=None):
    return singular if n == 1 else (plural_word or singular + "s")


# ============================================================================
# Tab 1 — what changed in the window
# ============================================================================

with changed_tab:
    try:
        data = get("/investigate", params=params)
    except ApiError as exc:
        st.error(f"Couldn't load the analysis: {exc}")
        st.stop()

    window = data["window"]

    # The denominators, in a sentence, before any chart. A reader who stops
    # here has still been told what the numbers below are measured against.
    st.markdown(
        f"**{window['amendments']:,} {plural(window['amendments'], 'amendment')}** "
        f"to **{window['trials_changed']:,} {plural(window['trials_changed'], 'trial')}**, "
        f"carrying **{window['field_changes']:,} individual field "
        f"{plural(window['field_changes'], 'change')}** — out of "
        f"**{window['trials_tracked']:,} trials** currently tracked"
        + (f" in {condition}." if condition else ".")
    )

    if not window["covers_full_window"]:
        since = (window.get("recording_since") or "")[:10]
        st.info(
            f"The change record begins **{since or 'later than this window'}**. "
            f"A {window_days}-day window reaches further back than TrialLens was "
            "watching, so the earlier part of it is not a quiet period — it is "
            "not covered at all."
        )

    if window["amendments"] == 0:
        st.success(
            "**Nothing was amended in this window.** That is a finding, not a "
            "gap — the watch ran and found no sponsor changed anything here."
        )
        st.stop()

    # ---- Primary outcomes, leading -----------------------------------------
    outcomes = data["outcomes"]
    st.subheader("Registered primary outcomes")

    if outcomes["total"] == 0 and outcomes["unreadable"] == 0:
        st.write(
            "**No trial changed a registered primary outcome in this window.** "
            "Nothing to review."
        )
    elif outcomes["total"] == 0:
        # Changes existed and none of them could be read. Saying "no trial
        # changed an outcome" here would be false, and it is exactly the
        # claim rule 2 exists to prevent — an unreadable row is not an
        # absent one.
        st.warning(
            f"**{outcomes['unreadable']} outcome change(s) could not be read** "
            "from the stored value, so nothing can be said about them. This is "
            "not the same as no outcome having changed."
        )
    else:
        st.caption(
            "Changing a registered endpoint has innocent explanations — a "
            "regulator asked, a typo was fixed, wording was standardised. "
            "TrialLens cannot tell which from the record, so nothing below is "
            "a verdict. It says what changed, when, and what the trial's own "
            "milestones were at the time."
        )
        stats = st.columns(4)
        stats[0].metric("Outcome changes", f"{outcomes['total']:,}")
        stats[1].metric("Reformatting only", f"{outcomes['wording_only']:,}")
        stats[2].metric("Substantive", f"{outcomes['substantive']:,}")
        stats[3].metric(
            "…after primary completion", f"{outcomes['after_primary_completion']:,}"
        )

        split = charts.stacked_split([
            {"part": "Substantive", "count": outcomes["substantive"]},
            {"part": "Reformatting only", "count": outcomes["wording_only"]},
        ])
        if split is not None:
            st.altair_chart(split, use_container_width=True)
        st.caption(
            f"Measure names are compared with capitalisation, punctuation and "
            f"list numbering removed, so a retitled endpoint is not reported as "
            f"a changed one. That narrowed {outcomes['total']} "
            f"{plural(outcomes['total'], 'change')} to "
            f"{outcomes['substantive']}."
        )
        if outcomes["unreadable"]:
            st.caption(
                f"{outcomes['unreadable']} stored value(s) could not be read as a "
                "list of outcomes and are counted here rather than dropped."
            )

        for change in outcomes["changes"]:
            if change["wording_only"]:
                continue
            with st.container(border=True):
                # The NCT ID was a dead end: the page names the trial that
                # needs review and gave no way to go read it. Reported
                # 2026-09-04 from real use. Same session_state + switch_page
                # mechanism Monitor and Explore already use.
                head, action = st.columns([6, 1])
                head.markdown(f"**{change['nct_id']}** — {change['brief_title']}")
                if action.button("Open →", key=f"open_{change['nct_id']}",
                                 help="Read this trial in Understand"):
                    st.session_state["selected_nct_id"] = change["nct_id"]
                    st.switch_page("pages/2_Understand.py")
                if change["flags"]:
                    st.markdown(
                        " ".join(f"`{label}`" for label in change["flag_labels"])
                    )
                    if "after_primary_completion" in change["flags"]:
                        st.warning(
                            "The endpoint moved after this trial's own primary "
                            "completion date — the point past which the outcome "
                            "data could already be seen. **Requires review.**"
                        )
                else:
                    st.caption("No milestone flags — the record states nothing unusual here.")

                st.caption(
                    f"{change['count_before']} → {change['count_after']} primary "
                    f"{plural(change['count_after'], 'outcome')}"
                )
                if change["measures_removed"]:
                    st.markdown("**No longer listed**")
                    for measure in change["measures_removed"]:
                        st.markdown(f"- {measure}")
                if change["measures_added"]:
                    st.markdown("**Now listed**")
                    for measure in change["measures_added"]:
                        st.markdown(f"- {measure}")

                if change["interpretation"]:
                    st.info(
                        f"**AI reading · not from ClinicalTrials.gov** — "
                        f"{change['interpretation']}"
                    )
                else:
                    # Absence means three things the column cannot separate.
                    # Saying "nothing important changed" would pick one.
                    st.caption(
                        "No AI reading stored for this change — which does not "
                        "mean it is unimportant; readings only exist for changes "
                        "seen since 2026-09-03."
                    )

    st.divider()

    # ---- Timeline drift ----------------------------------------------------
    st.subheader("Timeline drift")
    dates = data["dates"]
    if not dates:
        st.write("**No trial moved a start or completion date in this window.**")
    else:
        rows, table_rows = [], []
        for finding in dates:
            for direction, count, median in (
                ("Pushed later", finding["pushed"], finding["median_push_days"]),
                ("Pulled earlier", finding["pulled"], finding["median_pull_days"]),
            ):
                if not count:
                    continue
                rows.append({
                    "field": finding["label"], "direction": direction, "count": count,
                    "median_days": median or 0,
                    "median_months": round((median or 0) / 30.44, 1),
                })
            table_rows.append({
                "Date": finding["label"],
                "Pushed later": finding["pushed"],
                "Median push (months)": round((finding["median_push_days"] or 0) / 30.44, 1),
                "Pulled earlier": finding["pulled"],
                "Median pull (months)": round((finding["median_pull_days"] or 0) / 30.44, 1),
                "Month-precision moves": finding["imprecise_moves"],
                "Reformatting / no move": finding["precision_only"] + finding["no_move"],
                "Unreadable": finding["unreadable"],
                "Rows seen": finding["rows_seen"],
            })

        chart = charts.diverging_dates(rows)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)

        primary = next(
            (f for f in dates if f["field_name"] == "primary_completion_date"), None
        )
        if primary and primary["median_push_days"]:
            months = primary["median_push_days"] / 30.44
            st.caption(
                f"Median push on primary completion is **{months:.1f} months** "
                f"across {primary['pushed']} trials. For scale, a cohort of 2,542 "
                "registered RCTs found a median delay of 12.2 months, with about "
                "1 in 5 finishing on time — a different denominator (completed "
                "trials, not a window of amendments), so it is context, not a "
                "like-for-like comparison."
            )
        if any(f["imprecise_moves"] for f in dates):
            st.caption(
                "Some of these dates are month-precision in the registry, so the "
                "medians above are approximate — the per-date table says how many."
            )

        with st.expander("Every date bucket, including what could not be read"):
            st.dataframe(pd.DataFrame(table_rows), hide_index=True, width="stretch")

        biggest = [m for f in dates for m in f["biggest"]]
        biggest.sort(key=lambda m: abs(m["delta_days"]), reverse=True)
        if biggest:
            st.markdown("**Largest moves**")
            st.dataframe(
                pd.DataFrame([{
                    "Trial": m["nct_id"],
                    "Title": m["brief_title"],
                    "Was": m["old_value"],
                    "Now": m["new_value"],
                    "Effect": m["effect"],
                    "Month-precision": "yes" if m["imprecise"] else "no",
                } for m in biggest[:10]]),
                hide_index=True, width="stretch",
            )

    st.divider()

    # ---- Enrollment --------------------------------------------------------
    st.subheader("Enrollment against plan")
    enrollment = data["enrollment"]
    if enrollment["became_actual_total"] == 0:
        st.write(
            "**No trial replaced a recruitment target with a real headcount in "
            "this window.**"
        )
    else:
        st.caption(
            "When a trial switches its enrollment from a target to an actual "
            "count, it is reporting what it really recruited. This is the only "
            "place TrialLens can state a trial's recruitment against its own plan."
        )
        cols = st.columns(3)
        cols[0].metric("Targets became real counts", enrollment["became_actual_total"])
        cols[1].metric("Enrolled fewer than planned", enrollment["under_target"])
        cols[2].metric(
            "Targets revised while still targets",
            enrollment["target_raised_total"] + enrollment["target_lowered_total"],
        )

        dumbbell = []
        for move in enrollment["became_actual"]:
            if not move["count_before"] or move["count_after"] is None:
                continue
            ratio = move["count_after"] / move["count_before"]
            dumbbell.append({
                "label": move["nct_id"],
                "target": move["count_before"],
                "actual": move["count_after"],
                "ratio": ratio,
                "pct": f"{ratio * 100:.0f}% of target",
                "max_x": max(move["count_before"], move["count_after"]),
                "shortfall": "Below 85% of target" if ratio < 0.85 else "At or above",
            })
        chart = charts.target_vs_actual(dumbbell)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
            st.caption(
                "Grey marks the target, coloured marks what was enrolled. 85% of "
                "target is the threshold accrual studies count a shortfall "
                "against; roughly 19% of trials in one published cohort fell "
                "below it, and 55% of terminated trials stop for low accrual."
            )

        unattributable = [m for m in enrollment["became_actual"] if m["later_count_change"]]
        if unattributable:
            st.caption(
                f"{len(unattributable)} switch(es) are not plotted: the count "
                "moved again later, so today's figure cannot honestly be "
                "attributed to that amendment."
            )

        if enrollment["switched_back_total"]:
            st.warning(
                f"**{enrollment['switched_back_total']} trial(s) went the other "
                "way** — a real enrolled count reverted to a target. That is "
                "backwards, and worth a look: "
                + ", ".join(m["nct_id"] for m in enrollment["switched_back"])
            )

    st.divider()

    # ---- Lifecycle ---------------------------------------------------------
    st.subheader("Where trials moved in their lifecycle")
    lifecycle = data["lifecycle"]
    if not lifecycle:
        st.write("**No trial changed status in this window.**")
    else:
        anomalies = [f for f in lifecycle if f["anomaly"]]
        for finding in anomalies:
            st.warning(
                f"**{finding['label']} — {finding['count']} "
                f"{plural(finding['count'], 'trial')}.** Unusual enough to lead "
                "with regardless of how few: "
                + ", ".join(t["nct_id"] for t in finding["trials"])
            )
        # Anomalies stay IN the chart. Pulling them out left the bars
        # silently missing a category the reader had just been warned
        # about, so the counts added up to nothing stated — "this graph
        # isn't making sense" (reported 2026-09-04).
        chart = charts.lifecycle_bars([{
            "movement": f["label"],
            "count": f["count"],
            "kind": "Unusual — worth a look" if f["anomaly"] else "Ordinary",
            "examples": ", ".join(
                f"{t['old_value']} → {t['new_value']}" for t in f["trials"][:3]
            ) or "—",
        } for f in lifecycle])
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        st.caption(
            "Each bar is a move a trial made between two registered statuses "
            "in this window — hover to see the actual was → now pairs. A trial "
            "that did not change status is not here at all."
        )
        with st.expander("Which trials moved"):
            st.dataframe(
                pd.DataFrame([{
                    "Transition": f["label"], "Trial": t["nct_id"],
                    "Was": t["old_value"], "Now": t["new_value"],
                } for f in lifecycle for t in f["trials"]]),
                hide_index=True, width="stretch",
            )

    # ---- Scope departures --------------------------------------------------
    if data["scope_exits_total"]:
        st.divider()
        st.subheader("Trials that left the watch")
        st.caption(
            "**Nobody amended these.** They stopped matching what TrialLens "
            "tracks — our own bookkeeping, not something a sponsor did."
        )
        st.write(
            f"**{data['scope_exits_total']:,} "
            f"{plural(data['scope_exits_total'], 'trial')}** left scope in this window."
        )
        st.dataframe(
            pd.DataFrame([{
                "Trial": e["nct_id"], "Title": e["brief_title"],
                "Status": e["overall_status"] or "—",
                "Why": e["reason"] or "We can't tell from the stored record",
            } for e in data["scope_exits"]]),
            hide_index=True, width="stretch",
        )


# ============================================================================
# Tab 2 — the field
# ============================================================================

with field_tab:
    try:
        land = get(
            "/investigate/landscape",
            params={"condition": condition} if condition else None,
        )
    except ApiError as exc:
        st.error(f"Couldn't load the landscape: {exc}")
        st.stop()

    scope_name = condition or "everything tracked"
    st.markdown(
        f"**{land['trials']:,} trials** currently tracked in {scope_name}."
    )

    if land["trials"] == 0:
        st.info("Nothing tracked in this area yet.")
        st.stop()

    top = st.columns(3)
    top[0].metric("Trials tracked", f"{land['trials']:,}")
    recruiting = next(
        (b["count"] for b in land["statuses"]["buckets"] if b["label"] == "RECRUITING"), 0
    )
    top[1].metric("Currently recruiting", f"{recruiting:,}")
    top[2].metric(
        "Have posted results",
        f"{land['results_posted']:,}",
        help=f"{land['results_posted']} of {land['trials']} tracked trials",
    )

    st.subheader("How much of this field is new")
    # The earlier version cut the axis at 2010 and dropped everything before
    # it, so the first bar looked like the beginning of the field. It isn't:
    # 153 tracked breast-cancer trials started before 2010, the oldest in
    # 1989. Those are now one labelled bucket. Reported 2026-09-04.
    kinds = {"part year so far": "Part year so far", "planned start": "Planned start"}
    year_rows = []
    for b in land["started_per_year"]:
        kind = kinds.get(b["note"], "Complete year")
        if b["label"].startswith("Before"):
            kind = "Rolled-up earlier years"
        year_rows.append({
            "year": b["label"], "count": b["count"], "kind": kind,
            "detail": b["note"] or "a full calendar year",
        })
    chart = charts.year_bars(year_rows)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True)
        earlier = next(
            (b for b in land["started_per_year"] if b["label"].startswith("Before")), None
        )
        st.caption(
            "How many trials began enrolling each year — the growth curve of "
            "the field, and whether it is still accelerating. "
            + (f"The first bar rolls up {earlier['note']}, so the axis does not "
               "imply the field began at the cut-off. " if earlier else "")
            + "Faded bars are not comparable to the solid ones: the current "
            "year is not over, and later years are start dates trials have "
            "*planned*, not history."
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Phase")
        phases = land["phases"]
        chart = charts.ranked_bars(
            [{"Phase": b["label"], "Trials": b["count"]} for b in phases["buckets"]],
            "Phase", "Trials", "Trials", color=charts.SERIES[2],
        )
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        share = phases["unstated"] * 100 // land["trials"] if land["trials"] else 0
        st.caption(
            f"**{phases['unstated']:,} of {land['trials']:,} ({share}%) are not "
            f"on this chart** — {phases['unstated_label']}. They are counted here "
            "rather than dropped, because a phase chart without them describes a "
            "tidier field than the one that exists."
        )

    with right:
        st.subheader("Status")
        chart = charts.ranked_bars(
            [{"Status": b["label"].replace("_", " ").title(), "Trials": b["count"]}
             for b in land["statuses"]["buckets"]],
            "Status", "Trials", "Trials", color=charts.SERIES[0],
        )
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)

    st.subheader("What is being tested")
    intervention_rows = [
        {"Intervention": f"{i['name']} ({i['type'].title()})", "Trials": i["trials"]}
        for i in land["interventions"]
    ]
    by_label = {row["Intervention"]: term
                for row, term in zip(intervention_rows, land["interventions"])}
    chart = charts.ranked_bars(
        intervention_rows, "Intervention", "Trials", "Trials",
        color=charts.SERIES[1], select_field="Intervention",
    )
    picked = None
    if chart is not None:
        # Click-to-drill. The bar said 163 trials test Paclitaxel and there
        # was no way to ask which ones, which makes a chart a dead end
        # (reported 2026-09-04). The selectbox below is not redundancy for
        # its own sake — chart selection depends on the browser, and the
        # feature must not be silently dead if a click does not register.
        event = st.altair_chart(
            chart, use_container_width=True, on_select="rerun", key="intervention_pick"
        )
        selected = (event.selection or {}).get("pick") if event else None
        if selected:
            picked = selected[0].get("Intervention")
        st.caption(
            f"Out of **{land['interventions_denominator']:,} trials that list any "
            f"intervention** (of {land['trials']:,} tracked). Spelling variants are "
            "merged, so one drug is one bar. **Click a bar** — or pick below — to "
            "see the trials behind it."
        )
        choice = st.selectbox(
            "Show the trials testing", ["—"] + [r["Intervention"] for r in intervention_rows],
            index=0, key="intervention_choice", label_visibility="collapsed",
        )
        if choice != "—":
            picked = choice

    if picked and picked in by_label:
        term = by_label[picked]
        try:
            # name AND type: the chart groups by both, and matching the name
            # alone returned 164 trials for a bar reading 163 ("Paclitaxel"
            # is a DRUG on 163 and a COMBINATION_PRODUCT on 1).
            found = get("/investigate/trials", params={
                "intervention": term["name"],
                "intervention_type": term["type"],
                **({"condition": condition} if condition else {}),
            })
        except ApiError as exc:
            st.error(f"Couldn't load those trials: {exc}")
        else:
            shown = len(found["trials"])
            st.markdown(
                f"**{found['total']:,} tracked trial"
                f"{'s' if found['total'] != 1 else ''} test {term['name']}**"
                + (f" in {condition}" if condition else "")
                + (f" — showing the first {shown}." if shown < found["total"] else ".")
            )
            st.dataframe(
                pd.DataFrame([{
                    "Trial": t["nct_id"],
                    "Title": t["brief_title"],
                    "Status": t["overall_status"].replace("_", " ").title(),
                    "Phase": t["phase"] or "not stated",
                    "Participants": t["enrollment_count"],
                    "Started": t["start_date"] or "—",
                    "Results": "posted" if t["has_results"] else "—",
                } for t in found["trials"]]),
                hide_index=True, width="stretch",
            )

    left, right = st.columns(2)
    with left:
        st.subheader("How many participants these trials enrol")
        # Vertical and left-to-right, not a horizontal ranking. Sorted by
        # length, this read as a league table and invited "why is 1-49
        # winning?" — the shape of the distribution is the finding.
        # Reported 2026-09-04.
        chart = charts.ordered_columns(
            [{"Participants": b["label"], "Trials": b["count"]}
             for b in land["enrollment_bands"]],
            "Participants", "Trials", "Participants per trial",
            color=charts.SERIES[3],
        )
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        st.caption(
            f"How the field's trials are sized: each column is a band, and its "
            f"height is how many trials enrol that many people. "
            f"{land['enrollment_stated']:,} of {land['trials']:,} state a figure. "
            "Bands rather than a histogram — enrollment runs from single digits "
            "to five figures, and a linear axis renders the whole field as one bar."
        )

    with right:
        st.subheader("Who runs them")
        chart = charts.ranked_bars(
            [{"Sponsor": s["name"], "Trials": s["trials"]} for s in land["sponsors"]],
            "Sponsor", "Trials", "Trials", color=charts.SERIES[4],
        )
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        st.caption("Lead sponsors only — collaborators are a separate question, in Explore.")
