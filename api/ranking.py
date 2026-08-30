"""Step 7: trial ranking / evidence layer.

Deterministic first, AI second (CLAUDE.md sec. 5). Of the eight fit signals,
five are lookups or arithmetic over stored CT.gov fields and live in
`api/ranking_deterministic.py`; three need language understanding, and
the researcher's interest is interpreted once per search rather than once
per trial. That is a correctness decision before it is a cost one — a model
asked to evaluate `overall_status == "RECRUITING"` can drift between runs,
and code cannot.

LLM calls per search of N trials: 1 + N (was N, each ~4x larger).

Scoring note, and the reason the first implementation under-scored
everything: a signal the researcher never asked about is `unknown`, and
`unknown` is excluded from the score denominator entirely. Scoring it 0.0
while still counting its weight — as the first version did — makes "we
can't tell" arithmetically identical to "this doesn't fit", which both
under-scores good trials and quietly resolves an ambiguity the system is
required to surface (sec. 2).
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import anthropic
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException

from api.database import get_readonly_db
from api.ranking_deterministic import (
    ResearcherPreferences,
    score_age_range_fit,
    score_enrollment_feasibility,
    score_phase_fit,
    score_sites_active,
    score_status_recruiting,
)
from api.ranking_schemas import (
    FitRanking,
    FitRankingResponse,
    FitSignal,
    RankRequest,
    UnspecifiedPreference,
)
from api.schemas import StudyDetail

router = APIRouter()

# ============================================================================
# Configuration
# ============================================================================

MODEL = os.getenv("RANKING_MODEL", "claude-opus-5")

# Reasoning depth. Left configurable so the evaluation harness can sweep it
# and answer "does effort change ranking quality here?" with a measurement
# rather than an assumption — see docs/step7_implementation_guide.md.
EFFORT = os.getenv("RANKING_EFFORT", "low")

# Hard ceiling on trials per request. Ranking costs one model call per trial;
# this is the guard that keeps a single search from running away, independent
# of whatever the caller asks for.
MAX_TRIALS_PER_REQUEST = 50

SIGNAL_WEIGHTS = {
    # condition_match was one 30% signal, and in this endpoint it was a rubber
    # stamp: trials are fetched by `condition ILIKE`, so the tag already
    # matched before the model saw it, and 30% was granted automatically.
    # Split into the two things the tag genuinely cannot answer, so the
    # evidence shows which half failed (sec. 3).
    "condition_is_subject": 0.20,   # is the condition the trial's subject, or incidental?
    "approach_match": 0.10,         # does the mechanism/modality match what was described?
    "status_recruiting": 0.20,
    "phase_fit": 0.15,
    "prior_treatment_compatible": 0.15,
    "age_range_fit": 0.10,
    "sites_active": 0.05,
    "enrollment_feasibility": 0.05,
}

# Eligibility criteria are free text and occasionally very long. Truncate for
# the prompt, and say so in the evidence when it happens rather than letting
# a silent cut look like the whole document.
ELIGIBILITY_CHAR_LIMIT = 2500

_STATUS_ENUM = ["match", "partial", "no_match", "unknown"]
_CONFIDENCE_ENUM = ["high", "medium", "low"]


# ============================================================================
# Prompt 1 — interpret the researcher's interest (once per search)
# ============================================================================

INTEREST_PARSE_SYSTEM = """You extract structured search preferences from a clinical researcher's stated interest.

You are not judging any trial. You are only recording what the researcher did and did not ask for.

THE CRITICAL RULE: leave a field null when the researcher did not state it. Do not infer, do not fill in a sensible default, do not assume a typical value. "Not stated" is a real and common answer, and it is treated differently downstream from a stated preference — a field you invent will silently filter the researcher's own results.

Field notes:
- condition_terms: the disease/therapeutic area terms, as the researcher expressed them, plus obvious synonyms. Never empty.
- phases: use CT.gov tokens — EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4. "Phase II-III" becomes ["PHASE2","PHASE3"]. "early-phase" becomes ["EARLY_PHASE1","PHASE1"]. Null if no phase preference was expressed.
- require_recruiting: true only if the researcher asked for open/recruiting/enrolling trials. Null if they said nothing about trial status.
- min_age_years / max_age_years: the age band of the patient population described, in years (a 6-month-old is 0.5). Null unless an age or life-stage was actually described. "adults" implies min 18. "children"/"paediatric" implies max 17.
- prior_treatment_context: what the researcher said about prior lines of therapy or treatment-naive status, verbatim-ish. Null if unmentioned."""

INTEREST_PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "condition_terms": {"type": "array", "items": {"type": "string"}},
        "phases": {
            "type": ["array", "null"],
            "items": {
                "type": "string",
                "enum": ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"],
            },
        },
        "require_recruiting": {"type": ["boolean", "null"]},
        "min_age_years": {"type": ["number", "null"]},
        "max_age_years": {"type": ["number", "null"]},
        "prior_treatment_context": {"type": ["string", "null"]},
    },
    "required": [
        "condition_terms", "phases", "require_recruiting",
        "min_age_years", "max_age_years", "prior_treatment_context",
    ],
    "additionalProperties": False,
}


# ============================================================================
# Prompt 2 — the two genuinely semantic signals (once per trial)
# ============================================================================

SEMANTIC_SYSTEM = """You judge three fit signals for a clinical trial against a researcher's interest. Only three — the mechanical signals (recruitment status, phase, age bounds, site count, enrollment) are computed in code and are not your job.

IMPORTANT CONTEXT: this trial was already retrieved by a database filter on the researcher's condition term. That the condition matches is therefore ALREADY ESTABLISHED and is NOT evidence of fit. Do not credit the trial for it. Your job is the part the condition tag cannot answer.

SIGNAL 1 — condition_is_subject: is that condition what the trial is actually ABOUT?
- match: the condition is the trial's primary subject — what it is studying and treating.
- partial: present but secondary — a sub-population, a co-primary indication, or one arm of a broader study.
- no_match: the condition appears only incidentally — as a comorbidity of enrolled patients, an exclusion criterion, or background context.
- unknown: the title and summary carry too little to tell.

This is the distinction that matters most. A diabetes trial that enrolls obese patients is NOT an obesity trial, even though it is tagged with obesity. A trial excluding patients with prior breast cancer is NOT a breast cancer trial. Read the title, official title and summary to find the actual subject. The condition tags cannot tell you this, which is exactly why you are being asked.

SIGNAL 2 — approach_match: does the trial's approach match what the researcher described?
- The researcher may have named a mechanism, modality, drug class, or line of treatment ("immunotherapy", "checkpoint inhibitor", "GLP-1", "CAR-T", "surgical").
- match: the interventions or summary show that approach, including equivalents — a PD-1 or CTLA-4 inhibitor IS immunotherapy; semaglutide IS a GLP-1 agonist.
- partial: an adjacent or partially overlapping approach, or the trial combines the named approach with something quite different.
- no_match: a clearly different approach.
- unknown: the researcher named no particular approach, OR the record does not say what the intervention is. If the researcher named none, return unknown with confidence high — you are certain they did not ask, which is different from being unsure.

SIGNAL 3 — prior_treatment_compatible: do the trial's prior-therapy requirements fit the patient population the researcher described?
- If the researcher described no prior-treatment context, return unknown with confidence high — again, certain they did not ask.
- If they did, read the eligibility criteria for treatment-naive / prior-line requirements and judge overlap.
- If the criteria text is absent, or present but silent on prior therapy, return unknown. Note which of those two it is in your evidence — "no criteria recorded" and "criteria say nothing about prior therapy" are different facts.

RULES FOR ALL THREE:
- Use only what is in the trial record. Never state a fact about the trial that is not in the data given to you.
- Quote or name the specific field your judgment rests on in the evidence.
- Prefer unknown over a guess. An honest "we can't tell from this record" is a correct answer, not a failure.
- Evidence is read by a clinical researcher: one or two plain sentences, no hedging boilerplate.
- Never state or imply that a patient is eligible for a trial. You are assessing whether a trial is worth the researcher's attention, nothing more."""

def _signal_schema_fields(*names: str) -> dict:
    """status/evidence/confidence triple per signal, flat (no $refs)."""
    props = {}
    for name in names:
        props[f"{name}_status"] = {"type": "string", "enum": _STATUS_ENUM}
        props[f"{name}_evidence"] = {"type": "string"}
        props[f"{name}_confidence"] = {"type": "string", "enum": _CONFIDENCE_ENUM}
    return props


SEMANTIC_SIGNAL_NAMES = ("condition_is_subject", "approach_match", "prior_treatment")

SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": _signal_schema_fields(*SEMANTIC_SIGNAL_NAMES),
    "required": list(_signal_schema_fields(*SEMANTIC_SIGNAL_NAMES)),
    "additionalProperties": False,
}


# ============================================================================
# Spend accounting
# ============================================================================

# Published rates, USD per million tokens, for the models this endpoint may
# use. Cache reads bill at 10% of the input rate and cache writes at 125%.
_RATES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


class SpendTracker:
    """Accumulates real token usage so a search can report what it cost.

    An estimate in a design document is not evidence (sec. 7); this reports
    the figures the API actually returned.
    """

    def __init__(self, model: str):
        self.model = model
        self.calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.output_tokens = 0

    def record_cache_hit(self) -> None:
        """A replayed response: no request was made, nothing was billed."""
        self.cache_hits += 1

    def record(self, usage) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0

    @property
    def usd(self) -> Optional[float]:
        rates = _RATES.get(self.model)
        if rates is None:
            return None
        in_rate, out_rate = rates
        return (
            self.input_tokens * in_rate
            + self.cache_read_tokens * in_rate * 0.10
            + self.cache_write_tokens * in_rate * 1.25
            + self.output_tokens * out_rate
        ) / 1_000_000

    def summary(self) -> str:
        cost = self.usd
        cost_text = f"${cost:.4f}" if cost is not None else "cost unknown for this model"
        replayed = f", {self.cache_hits} replayed from cache (free)" if self.cache_hits else ""
        if self.calls == 0 and self.cache_hits:
            return (
                f"0 model calls — all {self.cache_hits} responses replayed from "
                f"cache; $0.0000"
            )
        if self.calls == 0:
            return f"No model calls were made ({cost_text})."
        return (
            f"{self.calls} model call(s) on {self.model}{replayed} — "
            f"{self.input_tokens:,} input, {self.cache_read_tokens:,} prompt-cached, "
            f"{self.output_tokens:,} output tokens; {cost_text}"
        )


# ============================================================================
# LLM calls
# ============================================================================


def _client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Ranking needs ANTHROPIC_API_KEY. Without it the deterministic "
                "signals could still be computed, but the condition match — the "
                "highest-weighted signal — cannot, so a score would be misleading."
            ),
        )
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Response cache — replays identical requests for free
# ---------------------------------------------------------------------------
#
# Most iteration on this feature is not on the model: it is on weights,
# thresholds, scoring and presentation. None of that needs a fresh judgment.
# Keying on the exact request means a re-run replays from disk at zero cost,
# and only a real prompt/model/effort change forces new spend.
#
# The key deliberately includes the system prompt, the user content, the model
# and the effort level. Change any of them and the cache misses, which is
# correct: the previous answer was to a different question.

CACHE_DIR = Path(os.getenv("RANKING_CACHE_DIR", ".ranking_cache"))
CACHE_ENABLED = os.getenv("RANKING_CACHE", "1") != "0"


def _cache_key(system: str, user_content: str) -> str:
    payload = json.dumps(
        {"model": MODEL, "effort": EFFORT, "system": system, "user": user_content},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_read(key: str) -> Optional[dict]:
    if not CACHE_ENABLED:
        return None
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())["response"]
    except (json.JSONDecodeError, KeyError, OSError):
        # A corrupt entry must not break a run — treat it as a miss.
        return None


def _cache_write(key: str, response: dict, system: str, user_content: str) -> None:
    if not CACHE_ENABLED:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(
            json.dumps(
                {
                    "model": MODEL,
                    "effort": EFFORT,
                    "recorded_at": datetime.utcnow().isoformat(),
                    # Stored for auditability: which exact question produced
                    # this answer. Without it a cache entry is unreviewable.
                    "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
                    "user_content": user_content,
                    "response": response,
                },
                indent=2,
            )
        )
    except OSError:
        pass  # a cache that can't be written is a slowdown, not a failure


def _structured_call(
    client: anthropic.Anthropic,
    system: str,
    user_content: str,
    schema: dict,
    spend: SpendTracker,
) -> dict:
    """One schema-constrained call. Returns parsed JSON.

    The system prompt is marked for prompt caching: it is byte-identical
    across every trial in a search, and re-sending it uncached would be the
    largest single cost in this endpoint. That is Anthropic-side caching,
    which cuts the price of a call; the on-disk cache above removes the call
    entirely when the request repeats exactly.
    """
    key = _cache_key(system, user_content)
    cached = _cache_read(key)
    if cached is not None:
        spend.record_cache_hit()
        return cached

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": schema}, "effort": EFFORT},
    )
    spend.record(response.usage)

    if response.stop_reason == "refusal":
        raise ValueError("The model declined to evaluate this record.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ValueError("Model returned no text block.")

    data = json.loads(text)
    _cache_write(key, data, system, user_content)
    return data


def parse_researcher_interest(
    client: anthropic.Anthropic, interest: str, spend: SpendTracker
) -> ResearcherPreferences:
    """Interpret the interest statement once, for the whole search.

    Because one misreading here would affect every trial ranked, the result
    is returned to the caller and shown in the UI — the researcher can see
    how their words were read and correct it, rather than silently receiving
    results filtered by a preference they never expressed.
    """
    data = _structured_call(
        client,
        INTEREST_PARSE_SYSTEM,
        f"Researcher's stated interest:\n\n{interest}",
        INTEREST_PARSE_SCHEMA,
        spend,
    )
    return ResearcherPreferences(
        condition_terms=data.get("condition_terms") or [],
        phases=data.get("phases"),
        require_recruiting=data.get("require_recruiting"),
        min_age_years=data.get("min_age_years"),
        max_age_years=data.get("max_age_years"),
        prior_treatment_context=data.get("prior_treatment_context"),
        raw_interest=interest,
    )


def _trial_context(trial: StudyDetail) -> str:
    """The trial facts the two semantic signals are allowed to rest on."""
    criteria = trial.eligibility_criteria or ""
    truncated = len(criteria) > ELIGIBILITY_CHAR_LIMIT
    if truncated:
        criteria = criteria[:ELIGIBILITY_CHAR_LIMIT] + "\n[...truncated...]"

    return json.dumps(
        {
            "nct_id": trial.nct_id,
            "brief_title": trial.brief_title,
            "official_title": trial.official_title,
            "registered_conditions": trial.conditions,
            "brief_summary": trial.brief_summary,
            "interventions": [
                {"type": i.type, "name": i.name} for i in (trial.interventions or [])
            ][:10],
            "eligibility_criteria": criteria or None,
            "eligibility_criteria_truncated": truncated,
        },
        indent=2,
    )


def build_semantic_user_content(
    trial: StudyDetail, prefs: ResearcherPreferences
) -> str:
    """The exact payload the model is asked to judge.

    Extracted as its own function so tests can assert what actually reaches
    the model without spending anything. The bug this guards against already
    happened once: `prior_treatment_compatible` carried 15% of the weight
    while `eligibility_criteria` was never put in the payload at all, so the
    signal could only ever return `unknown`. That is a plumbing failure, and
    plumbing is free to test.
    """
    prior_context = prefs.prior_treatment_context or "(the researcher said nothing about prior therapy)"
    return (
        f"Researcher is tracking: {', '.join(prefs.condition_terms) or prefs.raw_interest}\n"
        f"Researcher's patient population, re prior therapy: {prior_context}\n\n"
        f"Trial record:\n{_trial_context(trial)}"
    )


def evaluate_semantic_signals(
    client: anthropic.Anthropic,
    trial: StudyDetail,
    prefs: ResearcherPreferences,
    spend: SpendTracker,
) -> List[FitSignal]:
    """The three signals that genuinely need language understanding."""
    user_content = build_semantic_user_content(trial, prefs)

    data = _structured_call(client, SEMANTIC_SYSTEM, user_content, SEMANTIC_SCHEMA, spend)

    interventions = "; ".join(
        i.name for i in (trial.interventions or []) if i.name
    ) or "(no interventions recorded)"

    return [
        FitSignal(
            name="condition_is_subject",
            status=data["condition_is_subject_status"],
            evidence=data["condition_is_subject_evidence"],
            source_field="brief_title / official_title / brief_summary",
            source_value=trial.brief_title[:120],
            weight=SIGNAL_WEIGHTS["condition_is_subject"],
            confidence=data["condition_is_subject_confidence"],
        ),
        FitSignal(
            name="approach_match",
            status=data["approach_match_status"],
            evidence=data["approach_match_evidence"],
            source_field="interventions / brief_summary",
            source_value=interventions[:120],
            weight=SIGNAL_WEIGHTS["approach_match"],
            confidence=data["approach_match_confidence"],
        ),
        FitSignal(
            name="prior_treatment_compatible",
            status=data["prior_treatment_status"],
            evidence=data["prior_treatment_evidence"],
            source_field="eligibility_criteria",
            source_value=(
                "(no eligibility criteria recorded)"
                if not trial.eligibility_criteria
                else f"{len(trial.eligibility_criteria):,} characters of criteria text"
            ),
            weight=SIGNAL_WEIGHTS["prior_treatment_compatible"],
            confidence=data["prior_treatment_confidence"],
        ),
    ]


# ============================================================================
# Scoring
# ============================================================================

_CONTRIBUTION = {"match": 1.0, "partial": 0.5, "no_match": 0.0}


def score_signals(signals: List[FitSignal]) -> Tuple[float, str, float]:
    """Weighted score over the signals that could actually be evaluated.

    Returns (score, confidence, evaluated_weight_fraction).

    `unknown` signals are excluded from both numerator and denominator. The
    first implementation scored them 0.0 while keeping their weight, which
    made an unasked question mathematically indistinguishable from a failed
    one and capped scores near 0.65 for any plainly-worded interest.
    """
    numerator = 0.0
    denominator = 0.0
    evaluated_confidences = []

    for signal in signals:
        if signal.status == "unknown":
            continue
        denominator += signal.weight
        numerator += signal.weight * _CONTRIBUTION.get(signal.status, 0.0)
        evaluated_confidences.append(signal.confidence)

    total_weight = sum(s.weight for s in signals) or 1.0
    evaluated_fraction = denominator / total_weight

    if denominator == 0.0:
        # Nothing could be assessed. Say so rather than emitting a 0.0 that
        # reads as "bad fit" (sec. 2).
        return 0.0, "low", 0.0

    score = numerator / denominator

    # Confidence reflects two things: how much of the criteria could be
    # assessed at all, and how sure we were about what we did assess.
    if evaluated_fraction < 0.5:
        confidence = "low"
    elif all(c == "high" for c in evaluated_confidences) and evaluated_fraction >= 0.8:
        confidence = "high"
    elif all(c in ("high", "medium") for c in evaluated_confidences):
        confidence = "medium"
    else:
        confidence = "low"

    return score, confidence, evaluated_fraction


# ============================================================================
# Eliciting what wasn't said
# ============================================================================

# What each unstated preference costs, and how to ask for it. A signal going
# unscored because the researcher didn't mention something is a fact about
# the question, not about the trial — so the honest response is to ask,
# not to quietly narrow what the score means and show a number anyway.
#
# Only preferences the researcher can actually supply appear here. A signal
# unscored because the trial has no phase recorded (63% of them) is not
# fixable by any answer, and prompting for it would waste the researcher's
# attention on something no answer can change.
_ELICITABLE = {
    "phases": {
        "signals": ["phase_fit"],
        "question": "Which trial phases are you interested in?",
        "example": "Phase II-III, or early-phase only",
    },
    "require_recruiting": {
        "signals": ["status_recruiting"],
        "question": "Should this be limited to trials currently open to enrollment?",
        "example": "recruiting only, or include completed trials for landscape",
    },
    "age_band": {
        "signals": ["age_range_fit"],
        "question": "What patient age range are you tracking?",
        "example": "adults 18-75, or paediatric",
    },
    "prior_treatment_context": {
        "signals": ["prior_treatment_compatible"],
        "question": "What prior treatment have your patients had?",
        "example": "treatment-naive, or at least two prior lines",
    },
    "approach": {
        "signals": ["approach_match"],
        "question": "Is there a particular mechanism or modality you follow?",
        "example": "checkpoint inhibitors, GLP-1 agonists, CAR-T",
    },
}


def find_unspecified(prefs: ResearcherPreferences) -> List[UnspecifiedPreference]:
    """Which preferences went unstated, and what each one cost in coverage."""
    stated = {
        "phases": prefs.phases is not None,
        "require_recruiting": prefs.require_recruiting is not None,
        "age_band": prefs.min_age_years is not None or prefs.max_age_years is not None,
        "prior_treatment_context": prefs.prior_treatment_context is not None,
        # The parse doesn't extract a modality field; approach_match returns
        # unknown when the researcher named none. Inferred from the interest
        # text rather than guessed at.
        "approach": _mentions_an_approach(prefs.raw_interest),
    }

    out = []
    for key, was_stated in stated.items():
        if was_stated:
            continue
        spec = _ELICITABLE[key]
        out.append(
            UnspecifiedPreference(
                field=key,
                signals_unscored=spec["signals"],
                weight_unscored=sum(SIGNAL_WEIGHTS[s] for s in spec["signals"]),
                question=spec["question"],
                example_answer=spec["example"],
            )
        )
    return sorted(out, key=lambda u: u.weight_unscored, reverse=True)


# Vocabulary for "did the researcher already name an approach?" — used only to
# decide whether to ask, never to score. The signal itself is judged by the
# model and is not limited to this list.
#
# Weighted toward what the database actually contains rather than toward drug
# trials. Intervention types across 11,490 studies (2026-08-31): DRUG 9,455,
# OTHER 3,967, BEHAVIORAL 3,518, PROCEDURE 2,042, DEVICE 1,045,
# DIETARY_SUPPLEMENT 767, RADIATION 619, BIOLOGICAL 578. Non-drug is over half,
# and obesity — one of the two tracked conditions — is heavily behavioural. An
# earlier drug-only list would have asked a researcher who said "behavioural
# weight-loss interventions" what mechanism they follow.
#
# A miss costs a redundant question, never a wrong score, so erring toward
# more vocabulary is the safe direction.
_APPROACH_HINTS = (
    # drug / biologic
    "immunotherap", "checkpoint", "pd-1", "pd-l1", "ctla", "car-t", "car t",
    "glp-1", "glp1", "sglt2", "agonist", "antagonist", "inhibitor", "antibody",
    "monoclonal", "kinase", "biologic", "bispecific", "engager", "conjugate",
    "chemotherap", "hormone therap", "endocrine therap", "targeted therap",
    "gene therap", "cell therap", "vaccine", "peptide", "statin", "insulin",
    # procedure / device / radiation
    "surgical", "surgery", "bariatric", "radiotherap", "radiation", "ablation",
    "device", "implant", "stimulation", "endoscop", "catheter",
    # behavioural / lifestyle / dietary — over a third of interventions
    "behavio", "lifestyle", "diet", "nutrition", "exercise", "physical activity",
    "counsel", "psychotherap", "cognitive behavio", "cbt", "mindfulness",
    "education", "coaching", "supplement", "probiotic", "fasting",
    "physiotherap", "rehabilitation", "sleep",
    # digital / delivery
    "digital", "telehealth", "telemedicine", "app-based", "mobile health",
    "mhealth", "wearable", "remote monitoring", "screening",
)


def _mentions_an_approach(interest: str) -> bool:
    lowered = (interest or "").lower()
    return any(hint in lowered for hint in _APPROACH_HINTS)


def ranking_sort_key(r: FitRanking) -> Tuple[float, float]:
    """Sort by fit, then break ties toward the better-evidenced trial.

    `score` is conditional — it answers "of the criteria we could assess,
    what fraction matched?". Two trials can both score 1.00 while one was
    assessed on every signal and the other on two of seven. Those are not
    equally good answers to the researcher's question, and leaving the tie
    to database order would decide it arbitrarily.
    """
    return (r.score, r.evaluated_weight_fraction)


def build_ranking(
    trial: StudyDetail, signals: List[FitSignal]
) -> FitRanking:
    score, confidence, evaluated_fraction = score_signals(signals)

    matches = [s for s in signals if s.status == "match"]
    unknowns = [s for s in signals if s.status == "unknown"]
    against = [s for s in signals if s.status == "no_match"]

    if evaluated_fraction == 0.0:
        summary = (
            "None of the fit criteria could be assessed from this trial's "
            "record. This is a gap in the data, not a judgment about the trial."
        )
    else:
        parts = [
            f"{len(matches)} of {len(signals)} signals match"
            + (f", {len(against)} count against" if against else "")
            + "."
        ]
        if score >= 0.75:
            parts.append("Strong fit for your stated interest.")
        elif score >= 0.5:
            parts.append("Partial fit — worth a look at the details.")
        else:
            parts.append("Weak fit against what you asked for.")
        if evaluated_fraction < 1.0:
            parts.append(
                f"Scored on {evaluated_fraction:.0%} of the criteria; the rest "
                f"couldn't be assessed."
            )
        summary = " ".join(parts)

    caveats = []
    for signal in unknowns:
        caveats.append(f"{signal.name.replace('_', ' ')}: {signal.evidence}")
    for signal in signals:
        if signal.status != "unknown" and signal.confidence == "low":
            caveats.append(
                f"{signal.name.replace('_', ' ')}: low confidence — verify against "
                f"the trial record."
            )

    return FitRanking(
        nct_id=trial.nct_id,
        brief_title=trial.brief_title,
        score=score,
        confidence=confidence,
        signals=signals,
        summary=summary,
        caveats=caveats,
        source="tracked",
        evaluated_weight_fraction=evaluated_fraction,
    )


def rank_one_trial(
    client: anthropic.Anthropic,
    trial: StudyDetail,
    prefs: ResearcherPreferences,
    spend: SpendTracker,
) -> FitRanking:
    """Five deterministic signals plus three judged ones, for a single trial."""
    signals = evaluate_semantic_signals(client, trial, prefs, spend) + [
        score_status_recruiting(trial, prefs, SIGNAL_WEIGHTS["status_recruiting"]),
        score_phase_fit(trial, prefs, SIGNAL_WEIGHTS["phase_fit"]),
        score_age_range_fit(trial, prefs, SIGNAL_WEIGHTS["age_range_fit"]),
        score_sites_active(trial, SIGNAL_WEIGHTS["sites_active"]),
        score_enrollment_feasibility(trial, SIGNAL_WEIGHTS["enrollment_feasibility"]),
    ]
    return build_ranking(trial, signals)


# ============================================================================
# Data access
# ============================================================================


def fetch_trials_for_condition(conn, condition: str, limit: int) -> List[StudyDetail]:
    """Full trial records for a condition, most recently matched first.

    The subquery form (rather than a JOIN against study_conditions) is
    deliberate: a trial carrying several matching condition tags would
    otherwise appear once per tag — the duplication bug found in step 6b.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT * FROM studies
            WHERE nct_id IN (
                SELECT nct_id FROM study_conditions WHERE condition ILIKE %s
            )
            AND active_in_scope = true
            ORDER BY last_matched_at DESC
            LIMIT %s
            """,
            (f"%{condition}%", limit),
        )
        rows = cur.fetchall()
        if not rows:
            return []

        nct_ids = [r["nct_id"] for r in rows]
        cur.execute(
            "SELECT nct_id, condition FROM study_conditions WHERE nct_id = ANY(%s)",
            (nct_ids,),
        )
        by_trial: dict = {}
        for row in cur.fetchall():
            by_trial.setdefault(row["nct_id"], []).append(row["condition"])

    return [
        StudyDetail(**row, conditions=sorted(by_trial.get(row["nct_id"], [])))
        for row in rows
    ]


# ============================================================================
# Endpoint
# ============================================================================


@router.post("/rank", response_model=FitRankingResponse)
def rank_trials(body: RankRequest, conn=Depends(get_readonly_db)) -> FitRankingResponse:
    """Score a condition's tracked trials against a researcher's interest."""
    if not body.researcher_interest.strip():
        raise HTTPException(status_code=400, detail="researcher_interest cannot be empty")
    if not body.condition.strip():
        raise HTTPException(status_code=400, detail="condition cannot be empty")

    limit = max(1, min(body.limit, MAX_TRIALS_PER_REQUEST))

    trials = fetch_trials_for_condition(conn, body.condition, limit)
    if not trials:
        return FitRankingResponse(
            researcher_interest=body.researcher_interest,
            ranked_trials=[],
            total_trials=0,
            notes=(
                f"No tracked trials match the condition '{body.condition}'. "
                f"Try Discover first to see what's tracked."
            ),
            preferences=None,
            failures=[],
            spend_note="No model calls were made.",
        )

    client = _client()
    spend = SpendTracker(MODEL)

    prefs = parse_researcher_interest(client, body.researcher_interest, spend)
    unspecified = find_unspecified(prefs)

    rankings: List[FitRanking] = []
    failures: List[str] = []

    for trial in trials:
        try:
            rankings.append(rank_one_trial(client, trial, prefs, spend))
        except (anthropic.APIError, ValueError, KeyError) as exc:
            # Reported, never silently dropped. The first implementation
            # caught bare Exception and continued, so a trial that failed to
            # rank simply vanished from the results with no indication that
            # the list was incomplete.
            failures.append(f"{trial.nct_id}: {type(exc).__name__} — {exc}")

    rankings.sort(key=ranking_sort_key, reverse=True)

    notes = f"Ranked {len(rankings)} of {len(trials)} tracked trials for '{body.condition}'."
    if failures:
        notes += (
            f" {len(failures)} trial(s) could not be scored and are listed in "
            f"`failures` — this list is incomplete."
        )
    if len(trials) == limit:
        notes += f" Capped at {limit} most recently updated."

    return FitRankingResponse(
        researcher_interest=body.researcher_interest,
        ranked_trials=rankings,
        total_trials=len(trials),
        notes=notes,
        preferences=prefs,
        failures=failures,
        spend_note=spend.summary(),
        unspecified=unspecified,
        unscored_weight=sum(u.weight_unscored for u in unspecified),
    )
