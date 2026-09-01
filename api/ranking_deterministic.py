"""Deterministic fit signals — the ones that need no language model.

CLAUDE.md sec. 5 is "deterministic first, AI second". These are lookups or
arithmetic over stored CT.gov fields, and a model asked to evaluate them
can only lose: it can misread, drift between runs, or improvise on a value
nobody told it about. Code gets them right every time and carries the
literal stored value as evidence (sec. 3), not a paraphrase of it.

**Nothing in the running app imports this file as of 2026-09-01.** The
ranking layer that combined these signals into a score was deleted that
day — measuring it showed four of the five were filters wearing a score's
costume. They survive here to become filter predicates on `/discover` and
`/changes` (docs/plan_after_ranking.md, item 4), and because the real value
vocabularies below are hard-won: they were read off the live database, not
the CT.gov docs, and tests/test_ranking_real_data.py holds them to it. If
that filter work is dropped, delete this file rather than letting it sit —
git holds it either way.

Every threshold and vocabulary here comes from the real `dev` database
(11,490 studies, inspected 2026-08-30), not from the CT.gov docs — see the
value tables in the docstrings below. That matters: the LLM prompt this
replaces was written against assumed formats (`Phase 2`, a `CLOSED`
status) that do not occur in the data at all.
"""
from typing import List, Literal, Optional, Set

from pydantic import BaseModel

from api.schemas import StudyDetail


class FitSignal(BaseModel):
    """One piece of evidence for or against a trial's fit.

    Moved here from `api/ranking_schemas.py` when the ranking layer was
    deleted (see docs/decisions.md). It stays because the scorers below
    still produce it, and because `evidence`/`source_field`/`source_value`
    are what CLAUDE.md sec. 3 requires of any substantive claim — the
    conclusion never travels without the stored value it came from.
    """

    name: str

    status: Literal["match", "no_match", "unknown", "partial", "not_applicable"]
    # match: signal is positive
    # no_match: signal is negative (trial doesn't fit)
    # partial: signal is mixed
    # unknown: not enough information — either the researcher didn't say, or
    #          the trial's record doesn't carry it. A gap that could be filled.
    # not_applicable: the criterion has no meaning for this trial — phase for
    #          an observational study, say. NOT a gap; no answer exists to find.
    # The last two are kept apart deliberately: they read very differently,
    # and only `unknown` is ever worth chasing.

    evidence: str
    # Plain language explaining this signal. For researchers, not devs.

    source_field: str
    # Which CT.gov field this came from ("overall_status", "minimum_age", ...)

    source_value: str
    # The actual stored value from CT.gov

    weight: float
    # How much this signal contributes, when something is combining them.

    confidence: Literal["high", "medium", "low"]

# ============================================================================
# Real value vocabularies (from the live database, 2026-08-30)
# ============================================================================

# overall_status, all 8 values that actually occur, with counts at the time
# of inspection. The replaced prompt named only RECRUITING/ACTIVE_NOT_RECRUITING
# and a "CLOSED" that does not exist, leaving ~20% of trials unguided.
STATUS_ENROLLING = {
    "RECRUITING": 3982,             # open, actively enrolling
}
STATUS_ENROLLING_RESTRICTED = {
    "ENROLLING_BY_INVITATION": 233,  # enrolling, but not open to referral
    "NOT_YET_RECRUITING": 1447,      # will enroll, hasn't started
}
STATUS_NOT_ENROLLING = {
    "ACTIVE_NOT_RECRUITING": 1841,   # running, closed to enrollment
    "COMPLETED": 3413,
    "TERMINATED": 385,
    "WITHDRAWN": 149,
    "SUSPENDED": 40,
}

# Age strings are "<number> <unit>". Units observed, both bounds:
# Years/Year, Months/Month, Weeks/Week, Days/Day, Hours/Hour, Minutes.
# Years dominates (11,099 of 11,175 minimum_age values) but the others are
# real — reading "1 Day" as 1 year is a 365x error, so parse the unit.
_AGE_UNIT_YEARS = {
    "minute": 1 / (365.25 * 24 * 60),
    "hour": 1 / (365.25 * 24),
    "day": 1 / 365.25,
    "week": 7 / 365.25,
    "month": 1 / 12,
    "year": 1.0,
}

# phase is stored uppercase and underscore-joined, comma-separated when a
# trial spans phases. "NA" (4,869) means the trial has no phase concept —
# it is not a missing value, and must not be treated as one.
PHASE_NOT_APPLICABLE = "NA"


# ============================================================================
# Parsed researcher preferences (filled by the one-per-search LLM parse)
# ============================================================================


class ResearcherPreferences(BaseModel):
    """What the researcher actually asked for, extracted once per search.

    Every field is Optional and means "not stated" when None. That
    distinction is load-bearing: a preference the researcher never
    expressed must produce an `unknown` signal, which is excluded from
    scoring entirely — never a `no_match`, which counts against the trial.
    """

    condition_terms: List[str] = []
    phases: Optional[List[str]] = None          # e.g. ["PHASE2", "PHASE3"]
    require_recruiting: Optional[bool] = None
    min_age_years: Optional[float] = None       # the patient population's age floor
    max_age_years: Optional[float] = None
    prior_treatment_context: Optional[str] = None
    approach_context: Optional[str] = None   # mechanism/modality, e.g. "checkpoint inhibitors"
    approach_types: Optional[List[str]] = None
    # The same approach expressed as CT.gov interventionType tokens, so the
    # obvious category mismatch ("surgical" vs a 100%-DRUG trial) can be
    # settled in code for $0. See score_approach_category.
    raw_interest: str = ""


# Every column the five scorers in this module read, plus the ones
# StudyDetail needs to construct at all. One definition, used by both the
# candidate query in api/ranking.py (which reads thousands of rows per
# search) and the real-data test (which reads all of them) — a second copy
# would drift, and drifting silently means a scorer reading None.
#
# tests/test_ranking_real_data.py asserts by AST that this list covers every
# `trial.<field>` any scorer here touches.
SCORER_COLUMNS = [
    # required to build a StudyDetail
    "nct_id", "brief_title", "overall_status", "last_update_post_date",
    "active_in_scope", "fetched_at", "last_matched_at",
    # read by the scorers themselves
    "phase", "study_type",                  # score_phase_fit
    "minimum_age", "maximum_age",           # score_age_range_fit
    "enrollment_count", "enrollment_type",  # score_enrollment_feasibility
    "locations",                            # score_sites_active
    "interventions",                        # score_approach_category
]                                           # overall_status also feeds score_status_recruiting


# ============================================================================
# Field parsers
# ============================================================================


def parse_age_to_years(value: Optional[str]) -> Optional[float]:
    """Convert a CT.gov age string ("18 Years", "6 Months", "1 Day") to years.

    Returns None for absent or unparseable values — never a guess. 315 of
    11,490 studies have no minimum_age and 5,778 have no maximum_age, so
    None is a common, expected answer, not an error.
    """
    if not value:
        return None

    parts = value.strip().split()
    if len(parts) < 2:
        return None

    try:
        magnitude = float(parts[0])
    except ValueError:
        return None

    # "Years" -> "year", "Day" -> "day"; singular and plural both occur.
    unit = parts[1].lower().rstrip("s")
    factor = _AGE_UNIT_YEARS.get(unit)
    if factor is None:
        return None

    return magnitude * factor


def parse_phases(value: Optional[str]) -> Optional[Set[str]]:
    """Split the stored phase field into a set of phase tokens.

    Returns None when the trial has no usable phase — either absent (2,442
    studies) or the literal "NA" (4,869 studies, meaning the trial has no
    phase concept, e.g. observational studies). Callers must treat None as
    "cannot evaluate", not as "does not match".
    """
    if not value:
        return None

    tokens = {t.strip().upper() for t in value.split(",") if t.strip()}
    if not tokens or tokens == {PHASE_NOT_APPLICABLE}:
        return None

    return tokens - {PHASE_NOT_APPLICABLE}


# ============================================================================
# Deterministic signal scorers
# ============================================================================


def _signal(
    name: str,
    status: str,
    evidence: str,
    source_field: str,
    source_value: str,
    weight: float,
    confidence: str = "high",
) -> FitSignal:
    return FitSignal(
        name=name,
        status=status,
        evidence=evidence,
        source_field=source_field,
        source_value=source_value,
        weight=weight,
        confidence=confidence,
    )


def score_status_recruiting(
    trial: StudyDetail, prefs: ResearcherPreferences, weight: float
) -> FitSignal:
    """Is the trial enrolling? A lookup over 8 known values, not a judgment."""
    status = trial.overall_status
    source_value = status or "(absent)"

    if prefs.require_recruiting is None:
        return _signal(
            "status_recruiting",
            "unknown",
            f"Trial status is {source_value}. You didn't state a recruitment "
            f"preference, so this isn't counted for or against the trial.",
            "overall_status",
            source_value,
            weight,
            confidence="high",  # we are certain the preference is absent
        )

    if not prefs.require_recruiting:
        return _signal(
            "status_recruiting",
            "unknown",
            f"Trial status is {source_value}. You didn't restrict by "
            f"recruitment status, so this isn't scored.",
            "overall_status",
            source_value,
            weight,
        )

    if status in STATUS_ENROLLING:
        return _signal(
            "status_recruiting",
            "match",
            f"overall_status is {status} — open and actively enrolling.",
            "overall_status",
            source_value,
            weight,
        )

    if status in STATUS_ENROLLING_RESTRICTED:
        detail = (
            "enrolling by invitation only, so it isn't open to general referral"
            if status == "ENROLLING_BY_INVITATION"
            else "approved but not yet open to enrollment"
        )
        return _signal(
            "status_recruiting",
            "partial",
            f"overall_status is {status} — {detail}.",
            "overall_status",
            source_value,
            weight,
        )

    if status in STATUS_NOT_ENROLLING:
        detail = {
            "ACTIVE_NOT_RECRUITING": "still running but closed to new enrollment",
            "COMPLETED": "finished",
            "TERMINATED": "stopped early and will not enrol",
            "WITHDRAWN": "withdrawn before enrolling anyone",
            "SUSPENDED": "temporarily halted",
        }[status]
        return _signal(
            "status_recruiting",
            "no_match",
            f"overall_status is {status} — {detail}.",
            "overall_status",
            source_value,
            weight,
        )

    # An unrecognised status is a real "we can't tell", not a no_match. New
    # values can appear upstream; guessing at one would violate sec. 2.
    return _signal(
        "status_recruiting",
        "unknown",
        f"overall_status is {source_value}, which this system doesn't have a "
        f"rule for. Requires review.",
        "overall_status",
        source_value,
        weight,
        confidence="low",
    )


def score_sites_active(trial: StudyDetail, weight: float) -> FitSignal:
    """How many listed sites? len(locations) — 707 studies list none."""
    count = len(trial.locations or [])

    if count == 0:
        return _signal(
            "sites_active",
            "no_match",
            "No study sites are listed on the registry record.",
            "locations",
            "0 sites",
            weight,
        )

    if count == 1:
        return _signal(
            "sites_active",
            "partial",
            "Single-site study — geographically limited.",
            "locations",
            "1 site",
            weight,
        )

    countries = {loc.country for loc in trial.locations if loc.country}
    country_note = (
        f" across {len(countries)} countries" if len(countries) > 1 else ""
    )
    return _signal(
        "sites_active",
        "match",
        f"{count} listed study sites{country_note}.",
        "locations",
        f"{count} sites",
        weight,
    )


def score_enrollment_feasibility(trial: StudyDetail, weight: float) -> FitSignal:
    """Enrollment size, honest about ACTUAL vs ESTIMATED.

    6,577 of 11,490 studies report ESTIMATED — a target, not a headcount
    (found in step 6b). Reporting a target as though it were an enrolled
    count would misrepresent the source, so the distinction is stated.
    """
    count = trial.enrollment_count
    kind = trial.enrollment_type

    if count is None:
        return _signal(
            "enrollment_feasibility",
            "unknown",
            "No enrollment figure is recorded for this trial.",
            "enrollment_count",
            "(absent)",
            weight,
            confidence="high",
        )

    source_value = f"{count} ({kind or 'unspecified type'})"

    if kind == "ESTIMATED":
        qualifier = "a target, not a confirmed headcount"
    elif kind == "ACTUAL":
        qualifier = "an actual enrolled count"
    else:
        qualifier = "of unstated type — can't tell target from actual"

    if count >= 100:
        status, note = "match", "a substantial cohort"
    elif count >= 30:
        status, note = "partial", "a modest cohort"
    else:
        status, note = "partial", "a small cohort"

    confidence = "medium" if kind not in ("ACTUAL", "ESTIMATED") else "high"
    return _signal(
        "enrollment_feasibility",
        status,
        f"Enrollment of {count} — {note}. This figure is {qualifier}.",
        "enrollment_count",
        source_value,
        weight,
        confidence=confidence,
    )


def score_age_range_fit(
    trial: StudyDetail, prefs: ResearcherPreferences, weight: float
) -> FitSignal:
    """Does the trial's eligible age band overlap the population asked about?"""
    if prefs.min_age_years is None and prefs.max_age_years is None:
        return _signal(
            "age_range_fit",
            "unknown",
            "You didn't specify an age range, so this isn't scored.",
            "minimum_age / maximum_age",
            f"{trial.minimum_age or '(absent)'} – {trial.maximum_age or '(absent)'}",
            weight,
            confidence="high",
        )

    trial_min = parse_age_to_years(trial.minimum_age)
    trial_max = parse_age_to_years(trial.maximum_age)
    source_value = (
        f"{trial.minimum_age or '(no lower bound)'} – "
        f"{trial.maximum_age or '(no upper bound)'}"
    )

    if trial_min is None and trial_max is None:
        return _signal(
            "age_range_fit",
            "unknown",
            "The trial records no age bounds, so overlap can't be determined.",
            "minimum_age / maximum_age",
            source_value,
            weight,
            confidence="high",
        )

    # Treat an absent bound as unbounded on that side — that is what an
    # absent bound means on the registry, and half of all records have no
    # maximum_age.
    t_lo = trial_min if trial_min is not None else float("-inf")
    t_hi = trial_max if trial_max is not None else float("inf")
    r_lo = prefs.min_age_years if prefs.min_age_years is not None else float("-inf")
    r_hi = prefs.max_age_years if prefs.max_age_years is not None else float("inf")

    overlap_lo, overlap_hi = max(t_lo, r_lo), min(t_hi, r_hi)

    if overlap_lo > overlap_hi:
        return _signal(
            "age_range_fit",
            "no_match",
            f"Trial eligibility ({source_value}) doesn't overlap the age range "
            f"you described.",
            "minimum_age / maximum_age",
            source_value,
            weight,
        )

    fully_contains = t_lo <= r_lo and t_hi >= r_hi
    if fully_contains:
        return _signal(
            "age_range_fit",
            "match",
            f"Trial eligibility ({source_value}) covers the whole age range "
            f"you described.",
            "minimum_age / maximum_age",
            source_value,
            weight,
        )

    return _signal(
        "age_range_fit",
        "partial",
        f"Trial eligibility ({source_value}) overlaps only part of the age "
        f"range you described.",
        "minimum_age / maximum_age",
        source_value,
        weight,
    )


def score_phase_fit(
    trial: StudyDetail, prefs: ResearcherPreferences, weight: float
) -> FitSignal:
    """Phase overlap. 64% of trials have no usable phase, so `unknown` is common."""
    source_value = trial.phase or "(absent)"

    if prefs.phases is None:
        return _signal(
            "phase_fit",
            "unknown",
            f"Trial phase is {source_value}. You didn't state a phase "
            f"preference, so this isn't scored.",
            "phase",
            source_value,
            weight,
            confidence="high",
        )

    trial_phases = parse_phases(trial.phase)
    if trial_phases is None:
        # "No phase recorded" is two different facts, and the database
        # separates them almost perfectly (inspected 2026-08-31):
        #   2,440  OBSERVATIONAL  phase NULL  — no phase concept exists
        #   4,869  INTERVENTIONAL phase NA    — a real trial, not phase-classified
        # Collapsing both to `unknown` let an observational cohort study rank
        # alongside genuine Phase II trials for a researcher who asked for
        # Phase II, because `unknown` is excluded from scoring and so costs
        # the trial nothing. An observational study having no phase is a
        # fact, not an ambiguity — stating it is not the kind of guess sec. 2
        # forbids.
        study_type = (trial.study_type or "").strip().upper()

        if study_type == "OBSERVATIONAL":
            return _signal(
                "phase_fit",
                "no_match",
                "This is an observational study, which has no trial phase at "
                "all — it can't match the phases you asked for.",
                "study_type / phase",
                f"{trial.study_type} / {source_value}",
                weight,
                confidence="high",
            )

        if study_type == "INTERVENTIONAL":
            return _signal(
                "phase_fit",
                "unknown",
                "This is an interventional trial, but the registry records no "
                "phase for it (common for behavioural, device and procedure "
                "trials). It can't be compared to the phases you asked for.",
                "study_type / phase",
                f"{trial.study_type} / {source_value}",
                weight,
                confidence="high",
            )

        return _signal(
            "phase_fit",
            "unknown",
            "Neither a phase nor a study type is recorded, so this can't be "
            "compared to the phases you asked for.",
            "study_type / phase",
            f"{trial.study_type or '(absent)'} / {source_value}",
            weight,
            confidence="high",
        )

    wanted = {p.strip().upper() for p in prefs.phases}
    overlap = trial_phases & wanted

    if overlap == trial_phases:
        return _signal(
            "phase_fit",
            "match",
            f"Trial phase ({'/'.join(sorted(trial_phases))}) is within the "
            f"phases you asked for.",
            "phase",
            source_value,
            weight,
        )

    if overlap:
        return _signal(
            "phase_fit",
            "partial",
            f"Trial spans {'/'.join(sorted(trial_phases))}; only "
            f"{'/'.join(sorted(overlap))} matches your stated preference.",
            "phase",
            source_value,
            weight,
        )

    return _signal(
        "phase_fit",
        "no_match",
        f"Trial phase ({'/'.join(sorted(trial_phases))}) is outside the "
        f"phases you asked for.",
        "phase",
        source_value,
        weight,
    )


# ============================================================================
# Intervention category — the free half of the approach question
# ============================================================================

# Every interventionType CT.gov actually uses in this database, with counts
# (11,420 active trials, measured 2026-08-31). Queried, not taken from the
# docs — sec. 6. An earlier six-value shortlist (DRUG, BEHAVIORAL, PROCEDURE,
# DEVICE, DIETARY_SUPPLEMENT, OTHER) would have left 2,022 trials' worth of
# interventions unclassifiable: DIAGNOSTIC_TEST, RADIATION, BIOLOGICAL,
# COMBINATION_PRODUCT and GENETIC are all real and all missing from it.
INTERVENTION_TYPES = {
    "DRUG": 9433, "OTHER": 3939, "BEHAVIORAL": 3475, "PROCEDURE": 2031,
    "DEVICE": 1037, "DIETARY_SUPPLEMENT": 763, "DIAGNOSTIC_TEST": 625,
    "RADIATION": 618, "BIOLOGICAL": 575, "COMBINATION_PRODUCT": 136,
    "GENETIC": 68,
}

# OTHER is 3,939 interventions and means nothing in particular. Treating it as
# a category that can *conflict* with a researcher's stated approach would
# manufacture false no_matches on a third of the database, so a trial carrying
# it is never ruled out on category grounds.
_UNINFORMATIVE_TYPES = {"OTHER"}


def trial_intervention_types(trial: StudyDetail) -> Set[str]:
    """The distinct interventionType values recorded for this trial."""
    return {
        (i.type or "").strip().upper()
        for i in (trial.interventions or [])
        if (i.type or "").strip()
    }


def score_approach_category(
    trial: StudyDetail, prefs: ResearcherPreferences, weight: float
) -> Optional[FitSignal]:
    """A `no_match` on approach when the *categories* cannot possibly agree.

    Returns None when the answer needs judgment — that is the model's job,
    and this deliberately does not attempt it.

    CT.gov records `interventionType` as structured data, so "the researcher
    follows surgical approaches, this trial is 100% DRUG" is a fact, not an
    interpretation, and costs nothing to establish. What it cannot do is tell
    a GLP-1 agonist from an SGLT2 inhibitor — both are DRUG. So this catches
    the obvious category mismatch for $0 and leaves the fine distinction to
    the paid call, exactly as five of the eight signals were already moved
    into code.

    Two honesty constraints, both from the real distribution:
      - **985 of 11,420 trials record no interventions at all.** Those must
        return None (ask the model), never `no_match` — absent data is not
        evidence against a trial (sec. 2).
      - A trial tagged OTHER is never ruled out, because OTHER carries no
        category information and appears on 3,939 interventions.
    """
    if not prefs.approach_types:
        return None                      # researcher named no approach category

    trial_types = trial_intervention_types(trial)
    if not trial_types:
        return None                      # 985 trials — a data gap, not a mismatch

    wanted = {t.strip().upper() for t in prefs.approach_types}
    if trial_types & wanted:
        return None                      # compatible category; the model refines
    if trial_types & _UNINFORMATIVE_TYPES:
        return None                      # OTHER tells us nothing either way

    # Disjoint, and both sides are informative.
    #
    # Only ONE side of this comparison is a fact. The trial's types come from
    # the registry; the researcher's come from a model reading their prose,
    # so a wrong or under-listed mapping silently rules trials out. The
    # evidence therefore names both sides and says which is which — a
    # deterministic verdict resting on an inferred input must disclose the
    # inference, or it claims more certainty than it has (sec. 3). The
    # mapping is also surfaced in the response's `preferences`, so the
    # researcher can see it and correct it.
    return _signal(
        "approach_match",
        "no_match",
        f"This trial's interventions are registered as "
        f"{', '.join(sorted(trial_types)).lower()} — no overlap with the "
        f"{', '.join(sorted(wanted)).lower()} categories your interest was "
        f"read as. The trial's side is the registry's own value; your side "
        f"was interpreted from what you wrote, so check it under "
        f"“how your interest was read” if this looks wrong.",
        "interventions[].type vs interpreted approach_types",
        f"{', '.join(sorted(trial_types))} vs {', '.join(sorted(wanted))}",
        weight,
        confidence="high",
    )
