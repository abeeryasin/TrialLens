"""Pydantic models for Step 7: AI Ranking/Evidence Layer.

Defines the fit-scoring schema, signals, and evaluation harness structures.
"""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel


class FitSignal(BaseModel):
    """One piece of evidence for or against a trial's fit."""

    name: str
    # Examples: "condition_match", "status_recruiting", "phase_fit",
    #           "prior_treatment_compatible", "age_range_fit", "sites_active"

    status: Literal["match", "no_match", "unknown", "partial"]
    # match: signal is positive
    # no_match: signal is negative (trial doesn't fit)
    # unknown: can't determine from available data
    # partial: signal is mixed

    evidence: str
    # Plain language explaining this signal. For researchers, not devs.

    source_field: str
    # Which CT.gov field this came from (e.g., "condition", "overall_status", "minimum_age")

    source_value: str
    # The actual value from CT.gov

    weight: float
    # How much this signal contributes (0.0-1.0). Sum of all weights = 1.0

    confidence: Literal["high", "medium", "low"]
    # How confident are we in this signal?


class FitRanking(BaseModel):
    """Complete ranking + evidence for one trial."""

    nct_id: str
    brief_title: str
    score: float  # 0.0 to 1.0; weighted average over the *evaluable* signals
    confidence: Literal["high", "medium", "low"]
    signals: List[FitSignal]
    summary: str
    caveats: List[str]
    source: Literal["tracked", "live"]

    evaluated_weight_fraction: float = 1.0
    # How much of the total signal weight could actually be assessed. A 0.9
    # scored on 40% of the criteria is a different claim from a 0.9 scored on
    # all of them, and the researcher has to be able to tell them apart —
    # the score alone would hide it.


class FitRankingResponse(BaseModel):
    """Response from the ranking endpoint."""

    researcher_interest: str
    ranked_trials: List[FitRanking]
    total_trials: int
    notes: str

    preferences: Optional["ResearcherPreferencesOut"] = None
    # How the interest statement was interpreted. Surfaced so the researcher
    # can see — and correct — a misreading, rather than silently receiving
    # results filtered by a preference they never expressed. This parse
    # happens once per search, so one misreading would affect every result.

    failures: List[str] = []
    # Trials that could not be scored. Never silently dropped: a short list
    # is honest, a missing row looks like a trial that didn't rank.

    unspecified: List["UnspecifiedPreference"] = []
    # Preferences the researcher didn't state, and what each cost in scoring
    # coverage. The point is to ask rather than to penalise: a signal going
    # unscored is a fact about the question, not about the trial, and the one
    # person who can fix it is the researcher. Silently docking points for
    # vagueness — or silently narrowing what the score means — both hide a
    # gap the researcher could close in one sentence.

    unscored_weight: float = 0.0
    # Total signal weight left unscored because of the above. Lets the page
    # say "40% of the fit criteria are unscored" instead of showing a bare
    # number that looks complete.

    spend_note: str = ""
    # Real token usage and cost from this request, as reported by the API.


class UnspecifiedPreference(BaseModel):
    """One thing the researcher didn't say, and the question that would fix it."""

    field: str
    # Internal key, e.g. "phases", "require_recruiting".

    signals_unscored: List[str]
    # Which fit signals could not be scored as a result.

    weight_unscored: float
    # How much of the total scoring weight those signals carry.

    question: str
    # Plain-language question to put to the researcher.

    example_answer: str
    # A concrete example, so the question doesn't read as an interrogation.


class ResearcherPreferencesOut(BaseModel):
    """The parsed interest, as shown back to the researcher.

    Mirrors api.ranking_deterministic.ResearcherPreferences; kept here so the
    response schema doesn't depend on the scoring module.
    """

    condition_terms: List[str] = []
    phases: Optional[List[str]] = None
    require_recruiting: Optional[bool] = None
    min_age_years: Optional[float] = None
    max_age_years: Optional[float] = None
    prior_treatment_context: Optional[str] = None
    raw_interest: str = ""


class RankRequest(BaseModel):
    """Request body for POST /rank.

    Names a condition rather than shipping trial records: ranking costs one
    LLM call per trial, so the API picks the subset itself (most recently
    matched first) and caps it, instead of trusting a caller-supplied list.
    """

    researcher_interest: str
    condition: str
    limit: int = 20


# ============================================================================
# Test & Evaluation Models
# ============================================================================


class TestResearcherInterest(BaseModel):
    """One researcher interest input style for testing."""

    style: Literal["simple", "structured", "narrative"]
    # simple: keyword-only ("I track breast cancer trials")
    # structured: with explicit preferences ("Phase II+, recruiting only, <2 prior treatments")
    # narrative: unstructured prose ("I'm interested in...")

    text: str
    # The actual interest statement


class ExpectedSignalOutcome(BaseModel):
    """What we expect for one signal in a test case."""

    name: str
    expected_status: Literal["match", "no_match", "unknown", "partial"]
    # What status should we see?

    confidence_requirement: Literal["high", "medium", "low"]
    # How confident should we be?


class SyntheticTestTrial(BaseModel):
    """A synthetic trial for controlled testing."""

    nct_id: str
    brief_title: str
    condition: str
    overall_status: str
    phase: Optional[str] = None
    study_type: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED
    lead_sponsor: Optional[str] = None
    brief_summary: Optional[str] = None
    locations_count: Optional[int] = None
    is_recruiting: bool  # Convenience field


class TestCase(BaseModel):
    """Complete test case definition."""

    name: str
    # E.g., "Exact match: tracked condition, recruiting, phase II"

    description: str

    researcher_interests: List[TestResearcherInterest]
    # Three input styles: simple, structured, narrative

    test_trials: List[SyntheticTestTrial]
    # The trials to rank

    expected_ranking_order: List[tuple[str, Literal["high", "medium", "low"]]]
    # [(nct_id, expected_score_tier), ...]

    expected_top_1_score_range: tuple[float, float]
    # (min, max) for the highest-scoring trial

    notes: str


class EvaluationResult(BaseModel):
    """Results from running one test case."""

    test_case_name: str
    researcher_interest_style: str
    passed: bool
    metrics: dict
    # {
    #   "precision_at_1": float,
    #   "precision_at_3": float,
    #   "ranking_order_correct": bool,
    #   "top_1_score": float,
    #   "in_expected_range": bool,
    #   "errors": [list of errors if any]
    # }
    timestamp: datetime


class EvaluationReport(BaseModel):
    """Summary report from running the full test suite."""

    total_tests: int
    passed: int
    failed: int
    pass_rate: float
    metrics_summary: dict
    # Aggregated: mean precision_at_1, precision_at_3, etc.
    timestamp: datetime
