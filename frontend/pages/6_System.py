"""System: is the unattended half of TrialLens actually running?

Step 11 (2026-09-06). Two processes do the work nobody watches — a 6-hourly
monitor cron and a weekly synthesis agent — and between them they hold a
database credential, an API key, and a budget. Until this page, the only
place their state was visible was a GitHub Actions log.

Written as sentences with the real numbers in them, not a wall of green
tiles. A dashboard of tiles reading OK is exactly what a system in the
failure mode this page exists for would also show: the monitor completing
every six hours, successfully, having checked zero trials. So the page
leads with what the last run actually DID, and states any alert in full —
title and evidence — rather than as a coloured dot.

Reads GET /ops/status through api_client like every other page (CLAUDE.md
sec. 5). It holds no database credential of its own.
"""
import streamlit as st

from api_client import ApiError, get
from labels import format_detected_at

st.set_page_config(page_title="System — TrialLens", page_icon="⚙️", layout="wide")
st.title("System")
st.caption(
    "The scheduled jobs behind Monitor and Investigate — when they last ran, "
    "what they did, and what they have spent."
)

try:
    status = get("/ops/status")
except ApiError as exc:
    # Same rule as every other page: "couldn't reach the API" is a different,
    # honest state from "everything is fine", and the two must never look
    # the same. Especially here, where looking fine is the whole risk.
    st.error(f"Couldn't reach the API, so this page cannot say whether the "
             f"system is healthy. {exc}")
    st.stop()


def hours_phrase(hours):
    if hours is None:
        return "never"
    if hours < 1:
        return f"{int(hours * 60)} minutes ago"
    if hours < 48:
        return f"{hours:.1f} hours ago"
    return f"{hours / 24:.1f} days ago"


# ---------------------------------------------------------------------------
# The verdict, first and in words.
# ---------------------------------------------------------------------------
alerts = status.get("alerts", [])
critical = [a for a in alerts if a["severity"] == "critical"]
warnings = [a for a in alerts if a["severity"] != "critical"]

if critical:
    st.error(f"**{len(critical)} thing(s) need attention.**")
elif warnings:
    st.warning(f"Running, with {len(warnings)} thing(s) worth knowing about.")
else:
    st.success("Both scheduled jobs are running on time, inside budget.")

# Every alert in full — title AND the measurement behind it. An alert
# rendered as a badge is a conclusion without its evidence (sec. 3).
for alert in alerts:
    box = st.error if alert["severity"] == "critical" else st.warning
    box(f"**{alert['title']}**  \n{alert['detail']}")

st.divider()

# ---------------------------------------------------------------------------
# What each job actually did.
# ---------------------------------------------------------------------------
JOB_BLURBS = {
    "monitor": (
        "Fetches every tracked trial from ClinicalTrials.gov, diffs it "
        "against the stored snapshot, and records what moved. This is the "
        "watch."
    ),
    "synthesis": (
        "Reads the week's findings and proposes patterns for a human to "
        "review. Never files a verdict — every proposal waits in the "
        "review queue."
    ),
}

for job in status.get("jobs", []):
    st.subheader(job["name"].capitalize())
    st.caption(JOB_BLURBS.get(job["name"], ""))

    work = job.get("last_work_done")
    ran = hours_phrase(job.get("hours_since_completion"))
    if job.get("last_completed_at") is None:
        st.write("**No completed run on record.**")
    else:
        # The headline is what it DID, not that it finished. "Completed
        # successfully" is true of a run that checked nothing.
        st.write(
            f"Last completed **{ran}**, {work:,} {job['work_label']}."
            if work is not None
            else f"Last completed **{ran}**."
        )

    st.write(
        f"{job['runs_in_window']} run(s) in the last "
        f"{job['window_hours'] // 24} days, against "
        f"{job['expected_runs_in_window']} scheduled slot(s) at one every "
        f"{job['cadence_hours']}h. "
        f"{job['failed_in_window']} failed, {job['degraded_in_window']} "
        f"finished with an error inside."
    )
    if job["runs_in_window"] > job["expected_runs_in_window"]:
        st.caption(
            "More runs than slots is normal — the run record cannot tell a "
            "scheduled run from one started by hand."
        )

    if job.get("last_error"):
        with st.expander("The last error this job recorded"):
            st.code(job["last_error"])

st.divider()

# ---------------------------------------------------------------------------
# Money.
# ---------------------------------------------------------------------------
budget = status.get("budget", {})
st.subheader("Paid calls")
st.write(
    f"**${budget.get('spent_usd', 0):.4f}** of the "
    f"${budget.get('ceiling_usd', 0):.2f} ceiling used in the last "
    f"{budget.get('window_days')} days — ${budget.get('remaining_usd', 0):.4f} "
    "left."
)
st.progress(min(1.0, budget.get("share_used", 0.0)))
st.caption(
    "One ceiling, shared by both jobs. A researcher reading a bill does not "
    "care which feature spent the dollar, and two separate caps would let "
    "the pair spend double while each reported itself under budget. When it "
    "runs out, paid calls stop — that is the guard working, not a fault."
)

st.caption(
    f"{status.get('tracked_conditions')} condition(s) tracked · read from "
    f"GET /ops/status at {format_detected_at(status.get('checked_at'))}"
)
