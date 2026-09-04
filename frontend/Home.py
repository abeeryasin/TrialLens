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

from api_client import ApiError, get, post
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

# A record has numbers that must be read exactly, not felt at a glance — a
# monospace face on every count keeps a 6 from ever leaning on a 1 and keeps
# columns of figures aligned by digit. This is the one typographic choice on
# the page that departs from Streamlit's own font, applied only to numbers
# and the condition tags (never to prose, which stays the platform default —
# a lab report's body text is typeset plainly; only its figures are precise).
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&display=swap');
    .tl-num {
        font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace;
        font-variant-numeric: tabular-nums;
    }
    /* Flatten Streamlit's own button chrome to match this page's stated
       depth strategy (none — see .interface-design/system.md): a plain
       bordered rectangle, no shadow, no colour until hovered. */
    .stButton > button {
        border-radius: 6px;
        border: 1px solid #e6eaf1;
        background: #ffffff;
        color: #31333f;
        font-weight: 600;
        box-shadow: none;
    }
    .stButton > button:hover {
        border-color: #8b8fa3;
        color: #31333f;
        background: #f0f2f6;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def tag(text):
    """A tracked condition, shown as a specimen label rather than joined
    into a sentence — 'Watching Obesity, Breast Cancer' reads as prose about
    the watch; a row of tags reads as what is actually on file."""
    return (
        f'<span class="tl-num" style="display:inline-block;font-size:11px;'
        f'font-weight:600;color:{MUTED};background:{SURFACE};'
        f"border:1px solid {RULE};border-radius:4px;padding:3px 9px;"
        f'letter-spacing:0.01em">{text}</span>'
    )


def stat(label, value):
    """One entry in the record strip — eyebrow label over a tabular value,
    the same two-tier system the headline numbers use. Replaces st.metric,
    whose boxed icon-and-delta look is the single most recognisable stock
    Streamlit component in the app; this page never uses it anywhere else."""
    st.markdown(
        f'<div style="font-size:11px;font-weight:600;color:{MUTED};'
        f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">'
        f'{label}</div>'
        f'<div class="tl-num" style="font-size:23px;font-weight:600;'
        f'letter-spacing:-0.01em;color:{INK}">{value}</div>',
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
chips = "".join(tag(c) for c in conditions) if conditions else tag("nothing yet")
header_row, add_control = st.columns([8, 1])
with header_row:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
        f'margin-bottom:20px">'
        f'<span style="font-size:20px;font-weight:700;letter-spacing:-0.01em;'
        f'color:{INK}">TrialLens</span>'
        f'<span style="width:1px;height:14px;background:{RULE}"></span>'
        f'<span style="font-size:11px;font-weight:600;color:{FAINT};'
        f'text-transform:uppercase;letter-spacing:0.06em">Watching</span>'
        f"{chips}</div>",
        unsafe_allow_html=True,
    )
with add_control:
    # Step 10 (2026-09-05): tracked_conditions moved off a config file into
    # its own table specifically so this could be a form instead of an edit
    # + redeploy. A popover keeps it out of the headline's way — this is a
    # rare action, not something the page should spend visual weight on.
    with st.popover("+ Add"):
        new_condition = st.text_input(
            "Condition", key="new_condition_input",
            label_visibility="collapsed", placeholder="e.g. melanoma",
        )
        if st.button("Track it", key="add_condition_submit"):
            stripped = new_condition.strip()
            if not stripped:
                st.warning("Enter a condition first.")
            else:
                try:
                    post("/tracked-conditions", json_data={"condition": stripped})
                    st.success(
                        f"Now tracking ‘{stripped}’. The next Monitor "
                        "run picks it up — see the schedule in "
                        "`.github/workflows/monitor.yml`."
                    )
                    st.rerun()
                except ApiError as exc:
                    if exc.status_code == 409:
                        st.warning(f"‘{stripped}’ is already tracked.")
                    else:
                        st.error(str(exc))

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
        f'<span class="tl-num">{watch["trials_watched"]:,}</span> trials</div>'
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
        # "Most weeks look like this" was here until 2026-09-02 and was not
        # true: of the six days on record, the four weekdays carried 63-79
        # amendments each and only the Saturday and Sunday were silent.
        #
        # The replacement is computed rather than written, so it cannot rot
        # the way that sentence did. It states the weekend pattern only
        # while the data still shows it, and stops on the first quiet
        # weekday. Today is excluded from the test because it is not a
        # finished day — it has zero amendments most mornings.
        today = date.today()
        finished = [
            d for d in watch["daily"] if date.fromisoformat(d["day"]) < today
        ]
        silent = [d for d in finished if d["amendments"] == 0]
        silent_on_a_weekday = [
            d for d in silent if date.fromisoformat(d["day"]).weekday() < 5
        ]
        rhythm = (
            " Every silent day on record here has fallen on a weekend —"
            " ClinicalTrials.gov posts updates on business days."
            if silent and not silent_on_a_weekday
            else ""
        )
        st.markdown(
            f'<div style="background:{SURFACE};border-radius:10px;padding:24px 28px">'
            f'<div style="font-size:26px;font-weight:700;letter-spacing:-0.01em;'
            f'color:{INK}">{headline}</div>'
            f'<div style="font-size:16px;color:{BODY};margin-top:10px;'
            f'max-width:68ch;line-height:1.55">All '
            f'{watch["trials_watched"]:,} trials were checked and none of them '
            f"was amended — a quiet day is the watch working, not the watch "
            f"broken.{rhythm}</div></div>",
            unsafe_allow_html=True,
        )
    else:
        # STATE 2 — news. Led by what changed the science, with the total
        # stated rather than hidden: "63 amendments" is a row count, and a
        # row count is what the removed ranking layer was good at.
        posted, scientific = recent["results_posted"], recent["scientific"]
        others = scientific - posted
        # Clauses without terminal punctuation, joined into ONE sentence.
        # Two full stops mid-headline read as a stutter — "1 trial published
        # its results. 10 others changed something scientific." Reported
        # 2026-09-04 from real use.
        clauses = []
        if posted:
            clauses.append(
                f"{posted} trial{'s' if posted != 1 else ''} published "
                f"{'its' if posted == 1 else 'their'} results"
            )
        if others:
            word = "others" if posted else f"trial{'s' if others != 1 else ''}"
            clauses.append(f"{others} {word} changed something scientific")
        headline = ", and ".join(clauses) if clauses else "Nothing scientific moved"
        lines = [f"{headline}."]

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
    #
    # The heading goes ABOVE the row, not as a trailing note beside it. Read
    # 2026-09-02 by someone who had not built it: a bare "79" over a date,
    # with the only explanation at the far right of the row, does not say
    # what 79 counts.
    #
    # The weekday is shown because the pattern is real and otherwise
    # invisible: the only two silent days on record so far, 29 and 30
    # August, were a Saturday and a Sunday. ClinicalTrials.gov posts on
    # business days.
    # -----------------------------------------------------------------------
    st.write("")
    eyebrow(f"Amendments detected per day · last {len(watch['daily'])} days")
    tiles = []
    for entry in watch["daily"]:
        n = entry["amendments"]
        # "1 Sep", not format_posted_on's "01 September 2026" — seven of
        # these sit side by side, and the year is the same on all of them.
        parsed = date.fromisoformat(entry["day"])
        weekend = parsed.weekday() >= 5
        fill = (
            f"background:{FILLED_DAY};color:{INK};font-weight:600"
            if n
            else f"background:#ffffff;border:1px solid {RULE};color:#a3a8b8"
        )
        tiles.append(
            f'<div style="display:flex;flex-direction:column;gap:5px;'
            f'align-items:center">'
            f'<div class="tl-num" style="width:48px;height:48px;border-radius:6px;'
            f'{fill};display:flex;align-items:center;justify-content:center;'
            f'font-size:16px">{n}</div>'
            f'<div style="font-size:12px;color:{FAINT if weekend else MUTED};'
            f'white-space:nowrap">{parsed.strftime("%a")}</div>'
            f'<div style="font-size:12px;color:{MUTED};white-space:nowrap">'
            f'{parsed.day} {parsed.strftime("%b")}</div></div>'
        )
    st.markdown(
        '<div style="display:flex;gap:10px;align-items:flex-start;'
        'flex-wrap:wrap">' + "".join(tiles) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Counted on the day TrialLens **detected** the amendment, which is "
        "usually but not always the day ClinicalTrials.gov posted it — one "
        "amendment posted on 28 August wasn't seen until the 31st."
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
        # Both halves of this sentence used to say "posted results", so it
        # read as a circular claim: "751 completed trials have posted
        # results — out of 1,054 with results published." The real
        # distinction is status, and it has to be the thing the sentence
        # says. Reported 2026-09-04 from real use.
        offer.markdown(
            f"**{watch['trials_with_results']:,} tracked trials have published "
            f"results** — {completed:,} of them are marked completed.{invitation}"
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
with since:
    stat("Watching since", format_recording_since(watch["recording_since"]))
with changes:
    stat("Changes recorded", f"{watch['changes_recorded']:,}")
with amendments:
    stat("Amendments seen", f"{watch['amendments_seen']:,}")
with checked:
    stat("Last check", relative_hours(hours_since) if last_checked else "never")

st.caption(
    f"**{watch['amendments_seen']:,} trial updates** · "
    f"{watch['changes_recorded']:,} individual field changes. "
    f"ClinicalTrials.gov publishes only a trial's current version, so anything "
    f"amended before {format_recording_since(watch['recording_since'])} cannot "
    "be shown here. Everything since has been recorded."
)
st.caption(
    "“Last check” is when the most recent scheduled run finished, read from "
    "the run record TrialLens keeps of every check."
)


# ---------------------------------------------------------------------------
# What TrialLens does. Below the watch now, not above it — the capabilities
# are how the watch is used, not the headline.
#
# Five real questions, not five icons — the framing is CLAUDE.md's own
# (sec. 1), so this list can't drift from what the product actually claims
# to answer. An icon is arbitrary; a question a researcher would actually
# ask is not, which is the whole difference between this strip and the
# five-card-with-emoji grid it replaced.
# ---------------------------------------------------------------------------
rule()
eyebrow("Five ways to ask")

capabilities = [
    {
        "q": "What matches this?",
        "name": "Discover",
        "desc": "Search any condition. Tracked ones show our own regularly-updated data; anything else is looked up live.",
        "page": "pages/1_Discover.py",
    },
    {
        "q": "Why does this trial matter?",
        "name": "Understand",
        "desc": "A trial's full detail — what it studies, who's eligible, and every amendment since we started watching.",
        "page": "pages/2_Understand.py",
    },
    {
        "q": "Tell me when something changes.",
        "name": "Monitor",
        "desc": "Every change across every tracked trial, in one filterable feed.",
        "page": "pages/3_Monitor.py",
    },
    {
        "q": "Who else works in this space?",
        "name": "Explore",
        "desc": "Where a trial runs, who runs it, and which other tracked trials share its sites, investigators or interventions.",
        "page": "pages/4_Explore.py",
    },
    {
        "q": "What's happened across everything tracked?",
        "name": "Investigate",
        "desc": "Patterns across every tracked trial — endpoints that moved, timelines that slipped, and what the field looks like.",
        "page": "pages/5_Investigate.py",
    },
]

for i, cap in enumerate(capabilities, start=1):
    row, action = st.columns([6, 1])
    row.markdown(
        f'<div style="display:flex;gap:18px;align-items:baseline;padding:16px 0 14px">'
        f'<span class="tl-num" style="font-size:12px;color:{FAINT};'
        f'min-width:18px">{i:02d}</span>'
        f"<div>"
        f'<div style="font-size:11px;font-weight:600;color:{MUTED};'
        f'text-transform:uppercase;letter-spacing:0.05em">{cap["q"]}</div>'
        f'<div style="font-size:17px;font-weight:700;letter-spacing:-0.01em;'
        f'color:{INK};margin-top:3px">{cap["name"]}</div>'
        f'<div style="font-size:13px;color:{BODY};margin-top:4px;'
        f'max-width:64ch;line-height:1.5">{cap["desc"]}</div>'
        f"</div></div>",
        unsafe_allow_html=True,
    )
    with action:
        st.write("")
        st.write("")
        if st.button("Open →", key=f"open_{cap['name']}"):
            st.switch_page(cap["page"])
    if i < len(capabilities):
        st.markdown(f'<div style="height:1px;background:{RULE}"></div>', unsafe_allow_html=True)
