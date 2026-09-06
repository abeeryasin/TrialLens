"""Review: the human half of the weekly synthesis agent.

The agent proposes; a person decides. Until now only the first half of that
sentence existed anywhere a user could reach — the agent filed into
`review_queue` every Monday and nothing in the app read the table
(2026-09-06). The write route it needs
(POST /synthesis/proposals/{id}/review) was deferred on purpose while the
queue held zero rows, because designing a review screen against no real
proposals is the step-7 mistake. It is built now because the gap became
concrete: the first genuinely scheduled run is imminent, and it has
somewhere to file and nowhere to be read.

Three things this page refuses to do:

  - **Rank.** Proposals are listed newest first, never sorted by
    confidence. A confidence label is the agent's own statement about its
    evidence, not a priority score, and ordering by it would quietly turn
    it into one (sec. 3, and the removed step 7).
  - **Hide the evidence.** Every proposal shows what the agent read, one
    click away. A summary without its source is exactly what this project
    does not ship.
  - **Read an empty queue as a broken page.** Zero proposals is usually
    the correct answer, so the empty state states it as a finding, using
    the agent's own run record to say so — the same rule the watch's quiet
    week is built on.
"""
import streamlit as st

from api_client import ApiError, get, post
from labels import format_detected_at

st.set_page_config(page_title="Review — TrialLens", page_icon="🗂️", layout="wide")
st.title("Review")
st.caption(
    "What the weekly synthesis agent proposed, and what you decided about "
    "it. The agent never files a verdict — nothing here is acted on until "
    "you accept or dismiss it."
)

LOOKBACK_DAYS = 90

CONFIDENCE_NOTE = {
    "high": "consistent across several weeks, or a large move against the baseline",
    "medium": "real, but on fewer weeks of evidence",
    "low": "one week's number that could be chance",
}

try:
    proposals = get(
        "/synthesis/proposals",
        params={"days": LOOKBACK_DAYS, "include_evidence": True},
    )["proposals"]
except ApiError as exc:
    st.error(f"Couldn't reach the API, so the review queue can't be read. {exc}")
    st.stop()

# The agent's own run record, so an empty queue can explain itself with
# evidence rather than just being blank.
synthesis_job = None
try:
    for job in get("/ops/status")["jobs"]:
        if job["name"] == "synthesis":
            synthesis_job = job
except ApiError:
    pass

pending = [p for p in proposals if p["status"] == "pending"]
reviewed = [p for p in proposals if p["status"] != "pending"]


def decide(proposal_id, decision, note):
    try:
        post(
            f"/synthesis/proposals/{proposal_id}/review",
            json_data={"decision": decision, "note": note or None},
        )
    except ApiError as exc:
        st.error(f"Couldn't save that decision: {exc}")
        return
    st.rerun()


def render_proposal(proposal, decided=False):
    with st.container(border=True):
        head, meta = st.columns([4, 1])
        with head:
            st.markdown(f"**{proposal['finding_type'].replace('_', ' ')}**")
        with meta:
            label = proposal["confidence"]
            st.markdown(f"`{label} confidence`")
        st.write(proposal["summary"])
        st.caption(
            f"Window {format_detected_at(proposal['window_since'])} → "
            f"{format_detected_at(proposal['window_until'])} · filed "
            f"{format_detected_at(proposal['created_at'])} · "
            f"{label} = {CONFIDENCE_NOTE.get(label, 'the agent’s own label')}"
        )

        evidence = (proposal.get("evidence") or {}).get("evidence")
        if evidence:
            with st.expander("What the agent actually read"):
                st.write(evidence)
        else:
            st.caption("No evidence was stored with this proposal.")

        if decided:
            st.success(
                f"**{proposal['status'].capitalize()}** "
                f"{format_detected_at(proposal['reviewed_at'])}"
                + (f" — {proposal['reviewed_note']}" if proposal.get("reviewed_note") else "")
            )
            return

        note = st.text_input(
            "Note (optional)",
            key=f"note_{proposal['id']}",
            placeholder="Why you accepted or dismissed it — for the next reader, including you",
        )
        accept, dismiss, _ = st.columns([1, 1, 4])
        with accept:
            if st.button("Accept", key=f"accept_{proposal['id']}", type="primary"):
                decide(proposal["id"], "accepted", note)
        with dismiss:
            if st.button("Dismiss", key=f"dismiss_{proposal['id']}"):
                decide(proposal["id"], "dismissed", note)


st.subheader(f"Waiting for you ({len(pending)})")

if pending:
    for proposal in pending:
        render_proposal(proposal)
else:
    # Stated as a finding, not left blank. An empty queue almost always
    # means the agent looked and found nothing worth your attention, which
    # is a result — and the run record is what lets this page tell that
    # apart from "the agent never ran".
    st.info("**Nothing is waiting for review.**")
    if synthesis_job and synthesis_job.get("last_completed_at"):
        hours = synthesis_job.get("hours_since_completion")
        st.write(
            f"The agent last ran {hours:.0f} hours ago and filed "
            f"{synthesis_job.get('last_work_done', 0)} proposal(s). "
            f"{synthesis_job.get('runs_in_window', 0)} run(s) on record."
        )
        st.caption(
            "Filing nothing is a valid outcome and the common one. The agent "
            "is asked whether this week's movement is a pattern, and it needs "
            "several prior weeks to answer — it is instructed to say nothing "
            "rather than manufacture a finding to have something to report."
        )
    else:
        st.write(
            "No completed synthesis run is on record yet, so nothing has had "
            "the chance to be proposed. The System page shows the job's state."
        )

if reviewed:
    st.divider()
    st.subheader(f"Already decided ({len(reviewed)})")
    st.caption(
        "Kept in full, including what was dismissed. A dismissed proposal "
        "stays readable — the record is what the agent said and what you "
        "decided, not just the ones you agreed with."
    )
    for proposal in reviewed:
        render_proposal(proposal, decided=True)
