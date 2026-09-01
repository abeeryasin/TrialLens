"""Ranking: score tracked trials against a stated research interest.

Two rules shape this page, both decided with the user before it was built
(docs/STEP7_SESSION_SUMMARY.md, "Next: Unit 4"):

1. **A score never appears without its coverage.** `POST /rank` returns a
   conditional score — "of the criteria we could assess, what fraction
   matched?" — so a 1.00 assessed on 30% of the criteria and a 1.00
   assessed on all of them are different claims. Showing the number alone
   would hide that, and the researcher has no way to recover it.
2. **Elicit, don't penalise.** A signal goes unscored because the
   researcher didn't mention something, not because the trial failed. The
   honest response is to ask, so the unstated preferences appear as
   questions with what each one would recover — never as a silent
   deduction, never as an error.

This is also the only page in TrialLens that spends real money: one model
call to read the interest, then one per trial. So it fires a request on an
explicit click and nowhere else, and the response lives in session_state —
otherwise every expander toggle would re-rank, and Streamlit reruns the
whole script on every interaction.
"""
import streamlit as st

from api_client import ApiError, get, post

st.set_page_config(page_title="Ranking — TrialLens", page_icon="⭐", layout="wide")
st.title("Ranking")
st.caption(
    "Describe what you're tracking, and see which trials fit — with the "
    "evidence behind every score, not just the number. Covers trials we "
    "already track; use Discover for anything else."
)

# Measured at ~$0.006 per model call (effort=low, claude-opus-5, prompt
# caching on). One call reads the interest, then one per trial.
COST_PER_CALL = 0.006

INTEREST_KEY = "ranking_interest"
if INTEREST_KEY not in st.session_state:
    st.session_state[INTEREST_KEY] = ""


def add_to_interest(text: str) -> None:
    """Append an elicited answer to the interest box.

    Runs as an on_click callback, which is the only safe place to write to
    a key a widget already owns — assigning to it during the script body
    raises StreamlitAPIException instead.
    """
    current = st.session_state.get(INTEREST_KEY, "").strip()
    st.session_state[INTEREST_KEY] = f"{current} {text}".strip() if current else text


st.text_area(
    "What are you tracking?",
    key=INTEREST_KEY,
    height=90,
    placeholder=(
        "e.g. Recruiting Phase II-III breast cancer trials in adults 18-75 "
        "who've had at least one prior line of therapy"
    ),
    help=(
        "The more you say, the more of the fit criteria can be scored. "
        "Anything you leave out is reported below as a question, not "
        "counted against the trials."
    ),
)

try:
    tracked_conditions = get("/tracked-conditions")
except ApiError as exc:
    st.error(str(exc))
    st.stop()

col_condition, col_limit = st.columns([2, 3])
with col_condition:
    condition = st.selectbox(
        "Condition",
        tracked_conditions,
        help="Only actively tracked conditions — ranking reads our stored trials.",
    )
with col_limit:
    # 50 is MAX_TRIALS_PER_REQUEST in api/ranking.py; the endpoint clamps
    # anything higher, so offering more would be offering a lie.
    limit = st.slider("Trials to rank", min_value=5, max_value=50, value=20, step=5)

st.caption(
    f"Ranking {limit} trials costs about **${COST_PER_CALL * (limit + 1):.2f}** — "
    f"one model call to read your interest, then one per trial. Nothing is "
    f"spent until you click below."
)

if st.button("Rank trials", type="primary"):
    if not st.session_state[INTEREST_KEY].strip():
        st.warning("Describe what you're tracking first — there's nothing to score against.")
        st.session_state.pop("ranking_response", None)
    else:
        with st.spinner(f"Scoring {limit} trials…"):
            try:
                st.session_state["ranking_response"] = post(
                    "/rank",
                    json_data={
                        "researcher_interest": st.session_state[INTEREST_KEY],
                        "condition": condition,
                        "limit": limit,
                    },
                )
            except ApiError as exc:
                st.session_state.pop("ranking_response", None)
                if exc.status_code == 503:
                    # The endpoint raises 503 when it has no API key. It
                    # deliberately does not fall back to invented scores —
                    # api/ranking_mock.py was deleted for exactly that reason.
                    st.error(
                        "Ranking is unavailable — the API has no model credentials "
                        "configured, and it will not show made-up scores in place "
                        "of real ones."
                    )
                    st.caption(str(exc))
                else:
                    st.error(str(exc))

response = st.session_state.get("ranking_response")

if response:
    ranked = response["ranked_trials"]
    unspecified = response.get("unspecified", [])
    unscored_weight = response.get("unscored_weight", 0.0)

    if not ranked:
        st.warning(response["notes"])
        st.stop()

    st.divider()

    # Rule 1, at the level of the whole search: the headline says what
    # fraction of the fit criteria the researcher's own statement made
    # scoreable at all, right next to the count of what was ranked.
    st.subheader(
        f"Ranked {len(ranked)} trials · scored on "
        f"{(1 - unscored_weight):.0%} of the fit criteria"
    )
    # How these 20 were chosen out of thousands. The endpoint spells out that
    # the shortlist came from the deterministic signals only, so the model
    # never saw the rest — that is a real recall limit and belongs at the top,
    # not in small print under the last result.
    st.caption(response["notes"])

    # Rule 2. Ordered by how much coverage each answer recovers, which
    # find_unspecified() already does — the most valuable question first.
    if unspecified:
        count = len(unspecified)
        st.info(
            f"**{count} thing{'' if count == 1 else 's'} you didn't specify "
            f"{'is' if count == 1 else 'are'} going unscored.** They aren't "
            f"counted against any trial — but answering one scores more of "
            f"what you actually care about."
        )
        for item in unspecified:
            q_col, gain_col, add_col = st.columns([5, 2, 2])
            q_col.markdown(f"**{item['question']}**")
            q_col.caption(f"e.g. {item['example_answer']}")
            gain_col.markdown(f"would score **{item['weight_unscored']:.0%}** more")
            add_col.button(
                "＋ add",
                key=f"elicit_{item['field']}",
                on_click=add_to_interest,
                args=(item["example_answer"],),
                help="Adds this example to your interest above — edit it, then rank again.",
            )
        st.caption(
            "Adding an answer edits the box above; ranking again is a new "
            "request, and costs again."
        )

    prefs = response.get("preferences")
    if prefs:
        # Surfaced so a misreading is visible and correctable. This parse
        # happens once per search, so one wrong reading skews every result.
        with st.expander("How your interest was read"):
            readings = [
                ("Conditions", ", ".join(prefs.get("condition_terms") or []) or None),
                ("Phases", ", ".join(prefs.get("phases") or []) if prefs.get("phases") else None),
                (
                    "Recruiting only",
                    None if prefs.get("require_recruiting") is None
                    else ("yes" if prefs["require_recruiting"] else "no"),
                ),
                (
                    "Age range",
                    None if prefs.get("min_age_years") is None and prefs.get("max_age_years") is None
                    else f"{prefs.get('min_age_years', '—')} to {prefs.get('max_age_years', 'no upper limit')}",
                ),
                ("Prior treatment", prefs.get("prior_treatment_context")),
                ("Approach", prefs.get("approach_context")),
            ]
            NOT_STATED = "_you didn't say — see the questions above_"
            for label, value in readings:
                st.markdown(f"- **{label}:** {value if value else NOT_STATED}")

            # Shown because trials are ruled out on it. A trial whose
            # intervention categories don't overlap these is scored no_match
            # in code — so if the mapping is wrong, real trials disappear and
            # this panel is the only place that would reveal it.
            if prefs.get("approach_types"):
                st.markdown(
                    f"- **Approach read as intervention types:** "
                    f"`{'`, `'.join(prefs['approach_types'])}`"
                )
                st.caption(
                    "⚠️ Trials with none of these intervention types are ruled "
                    "out automatically. If a category is missing here, trials "
                    "you wanted were dropped — say the approach differently "
                    "and search again."
                )

            st.caption(
                "If any of this misreads what you meant, rewording the interest "
                "above will change every result."
            )

    if response.get("failures"):
        st.warning(
            f"**{len(response['failures'])} trial(s) could not be scored, so this "
            f"list is incomplete.** They are not missing because they ranked "
            f"badly — they were never scored at all."
        )
        for failure in response["failures"]:
            st.caption(f"· {failure}")

    st.divider()

    STATUS_MARK = {
        "match": "✅",
        "no_match": "❌",
        "partial": "🟡",
        "unknown": "⚪",
        "not_applicable": "➖",
    }

    # An unscored signal has two very different causes, and they look
    # identical unless the page separates them:
    #
    #   "you didn't say"          — you can fix this in one sentence
    #   "the registry lacks it"   — nobody can fix it; 64% of trials have no
    #                               phase, and no answer of yours changes that
    #
    # Both arrive as `unknown`. The API already knows which is which — the
    # elicitation list names exactly the signals that went unscored because
    # the researcher didn't state something — so no schema change is needed,
    # only reading what's already there. Telling a researcher to "answer a
    # question" about a gap no answer can close wastes the one attention
    # this page is asking for.
    ANSWERABLE_SIGNALS = {
        name for item in unspecified for name in item["signals_unscored"]
    }

    for position, trial in enumerate(ranked, start=1):
        coverage = trial["evaluated_weight_fraction"]

        st.markdown(f"#### {position}. {trial['brief_title']}")

        # Rule 1, per trial and non-negotiable: the score and what it was
        # assessed on are one sentence, not a number with a footnote.
        if coverage == 0.0:
            st.markdown(f"**No score** · none of the fit criteria could be assessed")
        else:
            # Recency is shown because it is a real tiebreak in the ordering
            # (api.ranking.ranking_sort_key) — a disclosed one, per sec. 3.
            # Two trials tied on fit are separated by this date, so hiding it
            # would make the order look arbitrary when it isn't.
            st.markdown(
                f"**{trial['score']:.2f}** · assessed on **{coverage:.0%}** of "
                f"your criteria · {trial['confidence']} confidence · "
                f"updated {trial['last_update_post_date']}"
            )
        st.caption(f"{trial['nct_id']} — {trial['summary']}")

        with st.expander("Why — the evidence behind this score"):
            # Heaviest signals first: the evidence that moved the score most
            # is the evidence worth reading first.
            for signal in sorted(trial["signals"], key=lambda s: -s["weight"]):
                mark = STATUS_MARK.get(signal["status"], "•")
                name = signal["name"].replace("_", " ")
                if signal["status"] == "unknown":
                    # Only claim what the page actually knows. The elicitation
                    # list proves an answer from the researcher would recover
                    # this signal; its absence proves only that no answer
                    # would — NOT that the trial's record is the culprit,
                    # which is a fact about the record the page hasn't
                    # checked. The evidence line directly below states the
                    # real reason; asserting one here would be inventing it.
                    why = (
                        "unscored — answering below would recover it"
                        if signal["name"] in ANSWERABLE_SIGNALS
                        else "unscored — nothing you could add would change it"
                    )
                    name = f"{name} — {why}"
                elif signal["status"] == "not_applicable":
                    name = f"{name} — doesn't apply to this trial"
                st.markdown(
                    f"{mark} **{name}** · {signal['weight']:.0%} of the score · "
                    f"{signal['confidence']} confidence"
                )
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{signal['evidence']}", unsafe_allow_html=True)
                # Section 3: source study, source field, source value, and the
                # interpretation all stay visible — never just the conclusion.
                st.caption(
                    f"　source: `{signal['source_field']}` = "
                    f"{signal['source_value'] or '_not recorded_'}"
                )

            if trial["caveats"]:
                st.markdown("**Caveats**")
                for caveat in trial["caveats"]:
                    st.caption(f"· {caveat}")

        if st.button(f"Open {trial['nct_id']} in Understand →", key=f"open_{trial['nct_id']}"):
            st.session_state["selected_nct_id"] = trial["nct_id"]
            st.switch_page("pages/2_Understand.py")

        st.divider()

    # `notes` is shown once, under the headline — repeating it here would
    # just be noise at the end of a long page.
    if response.get("spend_note"):
        st.caption(f"💵 {response['spend_note']}")
