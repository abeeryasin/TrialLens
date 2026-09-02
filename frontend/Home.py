"""TrialLens — the watch.

Step 7b direction 2, built 2026-09-02 from design/Main.dc.html. What was
here before was a capability grid: five cards explaining what the app can
do. That is a brochure. The thing TrialLens actually has, and that a fresh
clone of this repo does not, is elapsed time — 11,427 trials watched since
28 August, every amendment since recorded. So the page leads with the
watch and the grid moves below it.

Three states, and the least eventful one is the one that matters most:

  1. **Quiet** — nothing amended recently. The COMMON case (29 and 30
     August had zero amendments across all 11,427 trials, real recorded
     data), and until now it rendered as an empty table, which reads as a
     broken app rather than a working watch. Stated as a finding, with the
     empty days shown as zeros, it reads as what it is.
  2. **News** — lead with what changed the science, not with a row count.
  3. **Stopped** — the alarm REPLACES the page rather than sitting above
     it. A stale feed under a small warning still reads as current, and
     that is the failure being designed out.

Every number here comes from GET /watch. None is hardcoded, including the
ones the artboards drew — those were real on the day they were drawn and
three of them had already drifted by the next morning, which is the whole
argument for reading them live.
"""
from datetime import date

import streamlit as st

from api_client import ApiError, get
from labels import (
    FIELD_LABELS,
    format_detected_at,
    format_posted_on,
    format_recording_since,
    humanize_value,
    is_long_text,
    render_aspect_caption,
    summarize_text_change,
)

st.set_page_config(page_title="TrialLens", page_icon="🔬", layout="wide")

# Design vocabulary, from design/*.dc.html — deliberately Streamlit's own
# palette rather than an identity Streamlit cannot render.
INK = "#31333f"
BODY = "#4a4c58"
MUTED = "#6c6e7b"
FAINT = "#8b8fa3"
RULE = "#e6eaf1"
SURFACE = "#f0f2f6"
FILLED_DAY = "#cfd6e4"
GOOD = "#0f8a3c"
BAD = "#7d353b"


def rule():
    st.markdown(
        f'<div style="height:1px;background:{RULE};margin:20px 0 22px"></div>',
        unsafe_allow_html=True,
    )


def eyebrow(text):
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:{MUTED};'
        f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">'
        f"{text}</div>",
        unsafe_allow_html=True,
    )


def relative_hours(hours):
    """"2 hours ago" / "3 days and 4 hours ago" — the same phrasing whether
    it is describing a healthy gap or a dead one, so the alarm's numbers
    read as the same measurement, not a different scale."""
    if hours is None:
        return "never"
    if hours < 1:
        minutes = max(1, int(hours * 60))
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if hours < 48:
        whole = int(hours)
        return f"{whole} hour{'s' if whole != 1 else ''} ago"
    days, rest = divmod(int(hours), 24)
    tail = f" and {rest} hour{'s' if rest != 1 else ''}" if rest else ""
    return f"{days} days{tail} ago"


try:
    watch = get("/watch")
except ApiError as exc:
    # The only door to the database is shut. Not the same state as a stopped
    # watch and must not look like one: the watch may be running perfectly
    # and this process simply cannot see it.
    st.error(str(exc))
    st.stop()


# ---------------------------------------------------------------------------
# The watch itself
# ---------------------------------------------------------------------------

conditions = watch["conditions"]
named = (
    ", ".join(conditions[:-1]) + " and " + conditions[-1]
    if len(conditions) > 1
    else (conditions[0] if conditions else "nothing yet")
)
st.markdown(
    f'<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:20px">'
    f'<span style="font-size:20px;font-weight:700;letter-spacing:-0.01em;'
    f'color:{INK}">TrialLens</span>'
    f'<span style="font-size:14px;color:{MUTED}">Watching {named}</span></div>',
    unsafe_allow_html=True,
)

healthy = watch["is_healthy"]
last_checked = watch["last_checked_at"]
hours_since = watch["hours_since_check"]

if not healthy:
    # STATE 3 — the alarm replaces the page. Everything below the record
    # footer is deliberately not rendered: a feed nobody has refreshed for
    # days, shown under a warning, still reads as current.
    st.markdown(
        f'<div style="background:rgba(255,43,43,0.09);border-radius:10px;'
        f'padding:28px 32px;margin-bottom:22px">'
        f'<div style="font-size:32px;font-weight:700;letter-spacing:-0.02em;'
        f'color:{BAD}">⚠ The watch has stopped.</div></div>',
        unsafe_allow_html=True,
    )
    if last_checked is None:
        st.markdown(
            "**No check has ever been recorded.** This database has no evidence "
            "that the scheduled job has run even once, so nothing on this page "
            "can be called current."
        )
    else:
        st.markdown(
            f"The last successful check ran **{format_detected_at(last_checked)}** — "
            f"{relative_hours(hours_since)}. It should run every "
            f"{watch['check_interval_hours']} hours, so "
            f"**{watch['checks_missed']} checks have not happened**."
        )
        st.markdown(
            "Nothing on this page is current. If a trial you are watching was "
            "amended since then, TrialLens does not know about it and is not "
            "showing it to you."
        )

    still_true, to_check = st.columns(2)
    with still_true:
        eyebrow("What is still true")
        st.markdown(
            f"- The {watch['changes_recorded']:,} changes already recorded are "
            f"real and unaffected.\n"
            f"- Every trial's amendment history up to that date is complete.\n"
            f"- No data has been lost — the watch stopped collecting, it did "
            f"not delete."
        )
    with to_check:
        eyebrow("What to check")
        st.markdown(
            "- The scheduled job's last run and its log "
            "(`.github/workflows/monitor.yml`).\n"
            "- Whether the database credentials still work.\n"
            "- Whether ClinicalTrials.gov is reachable."
        )

else:
    # The badge is deliberately quiet — a tick and a word. It is the only
    # element on this page that confirms rather than reports, and it earns
    # its place because the page's whole claim is "we are still watching".
    badge_text, badge_ink = (
        ("A check looks late", "#8a6d0f")
        if watch["checks_missed"]
        else ("Watch is healthy", GOOD)
    )
    badge_fill = "rgba(255,193,7,0.12)" if watch["checks_missed"] else "rgba(33,195,84,0.10)"
    headline, badge = st.columns([4, 1])
    headline.markdown(
        f'<div style="font-size:40px;font-weight:700;letter-spacing:-0.02em;'
        f'line-height:1.1;color:{INK}">Watching '
        f'{watch["trials_watched"]:,} trials</div>'
        f'<div style="font-size:17px;color:{MUTED};margin-top:8px">'
        f"Checked every {watch['check_interval_hours']} hours · "
        f"last checked {relative_hours(hours_since)}</div>",
        unsafe_allow_html=True,
    )
    badge.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:8px;'
        f'background:{badge_fill};border-radius:8px;padding:10px 14px;'
        f'white-space:nowrap;font-size:14px;font-weight:600;color:{badge_ink}">'
        f"✓ {badge_text}</div>",
        unsafe_allow_html=True,
    )
    if watch["checks_missed"]:
        # Healthy but late. Said out loud rather than smoothed over — the
        # gap between "fine" and "stopped" is where a dying cron lives.
        st.caption(
            f"One scheduled check appears to have been skipped. Not an outage "
            f"yet; the alarm raises at "
            f"{watch['check_interval_hours'] * 2} hours without one."
        )

    rule()

    # -----------------------------------------------------------------------
    # STATE 1 or 2 — quiet, or news
    # -----------------------------------------------------------------------
    recent = watch["recent"]
    window = recent["window_hours"]
    gap = watch["hours_since_last_amendment"]

    if recent["amendments"] == 0:
        # STATE 1 — the quiet week, stated as a finding rather than left as
        # an empty table. This is the screen a researcher sees most often.
        quiet_for = relative_hours(gap).replace(" ago", "") if gap else None
        headline = (
            f"Nothing has changed in {quiet_for}."
            if quiet_for
            else "Nothing has changed yet."
        )
        st.markdown(
            f'<div style="background:{SURFACE};border-radius:10px;padding:24px 28px">'
            f'<div style="font-size:26px;font-weight:700;letter-spacing:-0.01em;'
            f'color:{INK}">{headline}</div>'
            f'<div style="font-size:16px;color:{BODY};margin-top:10px;'
            f'max-width:68ch;line-height:1.55">All '
            f'{watch["trials_watched"]:,} trials were checked and none of them '
            f"was amended. Most weeks look like this — a quiet week is the "
            f"watch working, not the watch broken.</div></div>",
            unsafe_allow_html=True,
        )
    else:
        # STATE 2 — news. Led by what changed the science, with the total
        # stated rather than hidden: "63 amendments" is a row count, and a
        # row count is what the removed ranking layer was good at.
        posted, scientific = recent["results_posted"], recent["scientific"]
        others = scientific - posted
        lines = []
        if posted:
            lines.append(
                f"{posted} trial{'s' if posted != 1 else ''} published "
                f"{'its' if posted == 1 else 'their'} results."
            )
        if others:
            word = "others" if posted else f"trial{'s' if others != 1 else ''}"
            lines.append(f"{others} {word} changed something scientific.")
        if not lines:
            lines.append("Nothing scientific moved.")

        st.markdown(
            f'<div style="font-size:26px;font-weight:700;letter-spacing:-0.01em;'
            f'color:{INK}">{" ".join(lines)}</div>',
            unsafe_allow_html=True,
        )
        remainder = recent["amendments"] - scientific
        st.markdown(
            f'<div style="font-size:16px;color:{BODY};margin-top:6px;'
            f'max-width:68ch;line-height:1.55">Out of '
            f'{recent["amendments"]} amendments across '
            f'{recent["trials"]} trials in the last {window} hours. The '
            f"remaining {remainder} moved dates, sites, enrolment figures or "
            f"titles — below, not hidden.</div>",
            unsafe_allow_html=True,
        )
        if st.button("See every change →", key="open_monitor_feed"):
            st.switch_page("pages/3_Monitor.py")

    # -----------------------------------------------------------------------
    # The 7-day record. The zeros are the point: they are evidence the watch
    # ran and found nothing, not evidence of a missing day.
    # -----------------------------------------------------------------------
    st.write("")
    tiles = []
    for entry in watch["daily"]:
        n = entry["amendments"]
        # "1 Sep", not format_posted_on's "01 September 2026" — seven of
        # these sit side by side, and the year is the same on all of them.
        parsed = date.fromisoformat(entry["day"])
        label = f"{parsed.day} {parsed.strftime('%b')}"
        fill = (
            f"background:{FILLED_DAY};color:{INK};font-weight:600"
            if n
            else f"background:#ffffff;border:1px solid {RULE};color:#a3a8b8"
        )
        tiles.append(
            f'<div style="display:flex;flex-direction:column;gap:6px;'
            f'align-items:center">'
            f'<div style="width:44px;height:44px;border-radius:6px;{fill};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:15px">{n}</div>'
            f'<div style="font-size:12px;color:{MUTED};white-space:nowrap">'
            f"{label}</div></div>"
        )
    st.markdown(
        f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
        + "".join(tiles)
        + f'<span style="font-size:13px;color:{MUTED};margin-left:8px">'
        f"amendments per day</span></div>",
        unsafe_allow_html=True,
    )

    # -----------------------------------------------------------------------
    # A quiet screen should offer something to do. An absence stated and then
    # left there is still a dead end.
    # -----------------------------------------------------------------------
    st.write("")
    completed = watch["completed_with_results"]
    if completed:
        # The invitation only makes sense on a quiet screen. Told during a
        # week with real news it is just a non-sequitur competing with the
        # thing the researcher actually came for.
        invitation = (
            " A quiet week is when there is time to read them."
            if recent["amendments"] == 0
            else ""
        )
        offer, action = st.columns([5, 1])
        offer.markdown(
            f"**{completed:,} completed trials have posted results** — out of "
            f"{watch['trials_with_results']:,} with results published.{invitation}"
        )
        if action.button("Browse →", key="browse_results"):
            st.switch_page("pages/1_Discover.py")

    # -----------------------------------------------------------------------
    # Never an empty screen: the last real thing that happened.
    # -----------------------------------------------------------------------
    last = watch["last_amendment"]
    if last:
        rule()
        eyebrow("The last thing that happened")
        head, when = st.columns([4, 1])
        head.markdown(
            f"**{last['nct_id']} · Amended {format_posted_on(last['posted_on'])}**  \n"
            f"{last['brief_title']}"
        )
        when.caption(relative_hours(watch["hours_since_last_amendment"]))

        if not last["content_is_visible"]:
            # Never "no changes". ClinicalTrials.gov posted an amendment;
            # TrialLens does not store the fields it touched. Saying nothing
            # changed would be a false claim about a study fact.
            st.caption(
                "ClinicalTrials.gov posted this amendment, but every field it "
                "touched is one TrialLens doesn't store — so we can't show "
                "what moved. It is not a claim that nothing did."
            )
        for aspect in last["aspects"]:
            render_aspect_caption(aspect)
            for change in last["changes"]:
                if (change.get("aspect") or "Uncategorised") != aspect:
                    continue
                label = FIELD_LABELS.get(change["field_name"], change["field_name"])
                old, new = change["old_value"], change["new_value"]
                # A rewritten eligibility criterion is ~4,000 characters per
                # side. Summarised as a count of words moved — never as a
                # paraphrase of clinical text.
                if is_long_text(old, new):
                    body = summarize_text_change(old, new)
                else:
                    body = (
                        f"{humanize_value(change['field_name'], old)} → "
                        f"{humanize_value(change['field_name'], new)}"
                    )
                effect = f" · *{change['effect']}*" if change.get("effect") else ""
                st.markdown(f"**{label}** — {body}{effect}")

        if st.button(f"Open {last['nct_id']} in Understand →", key="open_last"):
            st.session_state["selected_nct_id"] = last["nct_id"]
            st.switch_page("pages/2_Understand.py")


# ---------------------------------------------------------------------------
# The record — shown in every state, including the alarm. A frozen figure is
# still a real one; it is labelled as frozen rather than quietly stale.
# ---------------------------------------------------------------------------
rule()
since, changes, amendments, checked = st.columns(4)
since.metric("Watching since", format_recording_since(watch["recording_since"]))
changes.metric("Changes recorded", f"{watch['changes_recorded']:,}")
amendments.metric("Amendments seen", f"{watch['amendments_seen']:,}")
checked.metric(
    "Last check",
    relative_hours(hours_since) if last_checked else "never",
)

st.caption(
    "ClinicalTrials.gov publishes only a trial's current version, so anything "
    f"amended before {format_recording_since(watch['recording_since'])} cannot "
    "be shown here. Everything since has been recorded."
)
# The honest footnote on the figure above it. "Last check" is inferred from
# when trials were last confirmed in scope, not from a log of runs — nothing
# records that a scheduled job happened. That is step 7b direction 3
# (`monitor_runs`), and until it exists this page must not imply otherwise.
st.caption(
    "“Last check” is inferred from when trials were last confirmed in scope, "
    "not from a record of scheduled runs — TrialLens doesn't keep one yet, so "
    "it can say when a check last happened but not how many have run."
)


# ---------------------------------------------------------------------------
# What TrialLens does. Below the watch now, not above it — the capabilities
# are how the watch is used, not the headline.
# ---------------------------------------------------------------------------
rule()
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
        "desc": "A trial's full detail — what it studies, who's eligible, and every amendment since we started watching.",
        "page": "pages/2_Understand.py",
        "status": "live",
    },
    {
        "icon": "🛰️",
        "name": "Monitor",
        "desc": "Every change across every tracked trial, in one filterable feed.",
        "page": "pages/3_Monitor.py",
        "status": "live",
    },
    # The Ranking card was removed 2026-09-01 along with the layer behind it.
    # It was genuinely live — POST /rank returned real scored trials over
    # HTTP — and it is gone anyway: four of its five scored signals were
    # filters wearing a score's costume, and the one real judgment scales
    # with volume in a product that sees ~17 changed trials a week. The
    # reasoning is in docs/decisions.md; what replaces it is step 7b.
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
        else:
            st.caption("⚪ Not built yet.")
