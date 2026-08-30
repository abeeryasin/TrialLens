# Step 7 Implementation Guide: AI Ranking/Evidence Layer

> **STALE AS OF 2026-08-31 — read `docs/STEP7_SESSION_SUMMARY.md` instead.**
>
> This document describes the 2026-08-30 architecture, which was rebuilt the
> following day after eight real bugs surfaced. Specifically, the following
> claims below are now **wrong**:
>
> - "Single LLM call per trial evaluating 7 signals" — five of the eight
>   signals now run in plain code; the model judges three.
> - "Few-shot with 3 examples" — all examples were removed; both prompts use
>   schema-constrained output (`output_config.format`).
> - The signal weights table — `condition_match` (30%) was split into
>   `condition_is_subject` (20%) and `approach_match` (10%).
> - "unknown/no_match -> 0.0" — `unknown` is now excluded from the score
>   denominator entirely; conflating the two was the bug that capped scores
>   near 0.65.
> - The `api/ranking_mock.py` references — that file was deleted.
> - The Unit 4/5/6 plans below are still broadly valid, but the two design
>   decisions agreed with the user (score never shown without coverage;
>   elicit missing preferences rather than penalise them) are recorded only
>   in the session summary.
>
> Retained for the research findings near the bottom, which are still
> useful — in particular the note that real trial-matching tools report
> precision/recall around 0.32-0.45.

**Current Date:** 2026-08-30  
**Current Status:** Unit 1 ✓ & Unit 2 ✓ & Unit 3 ✓ Complete; Unit 4 Ready to Start

## Checklist

### Unit 1: Fit Scoring Schema ✓ COMPLETE

**What was built:**
- `api/ranking_schemas.py`: Pydantic models defining the ranking structure
  - `FitSignal`: One piece of evidence (name, status, evidence, source_field, source_value, weight, confidence)
  - `FitRanking`: Complete score + evidence for one trial
  - `FitRankingResponse`: API response shape

**Key design decisions:**
- Score: 0.0-1.0 (weighted average of signals)
- Confidence: high/medium/low (reflects data quality, not score magnitude)
- Signals: deterministic (condition match, status, phase) + LLM-assisted (prior treatment compatibility, nuanced fit)
- Evidence: traceable to actual CT.gov fields, never invented
- Weights: condition_match (0.30), status_recruiting (0.20), phase_fit (0.15), prior_treatment_compatible (0.15), age_range_fit (0.10), sites_active (0.05), enrollment_feasibility (0.05)

**Why this schema:**
- No black-box scoring; every score has visible evidence
- Uncertainty is explicit (high/medium/low confidence, not all 1.0)
- Per CLAUDE.md §3: "Every substantive trial claim preserves source study, source field, relevant source text/value, interpretation, and uncertainty"

---

### Unit 2: Evaluation Harness & Test Cases ✓ COMPLETE

**What was built:**
- `tests/test_data_synthetic_trials.py`: 5 synthetic test cases covering:
  1. **Exact match** (condition + status + phase all align)
  2. **Boundary condition** (status change: recruiting vs. completed)
  3. **Confidence calibration** (data quality drives uncertainty, not score)
  4. **Comorbidity edge case** (incidental mention vs. primary topic)
  5. **Phase preference** (early-phase vs. late-stage)

- `tests/test_ranking_harness.py`: Evaluation framework
  - `RankingEvaluator` class: runs rankings, compares to expected outcomes
  - Metrics: precision@1, precision@3, ranking_order_correct, confidence_calibration, score_variance
  - Baseline expectations set (before LLM implementation)

**Each test case includes:**
- 3 researcher interest input styles: simple, structured, narrative
- Expected ranking order (which trial should rank first, second, etc.)
- Expected score range for top result
- Confidence requirements
- Detailed notes on what should happen

**Why this harness:**
- Per CLAUDE.md §7: "For AI behavior: explicit evaluation cases... built from the start"
- Catches mistakes before researchers see them
- Provides measurable quality metrics (not subjective "it feels right")
- Real trial-matching tools have precision/recall ~0.32-0.45; we'll measure against baseline

**How to run:**
```bash
cd "/Users/abeeryasin/Documents/Portfolio project"
PYTHONPATH=. python3 tests/test_ranking_harness.py
# Once Unit 3 is implemented:
# python3 -m pytest tests/test_ranking_harness.py -v
```

---

## Unit 3: Ranking Endpoint ✓ COMPLETE

**What was built:**
- `api/ranking.py`: FastAPI endpoint + logic for trial ranking
  - `POST /rank` endpoint (registered in `api/main.py`)
  - Input: researcher_interest (string) + list of StudyDetail trials
  - Output: List[FitRanking] sorted by score (highest first)
  - **Key implementation:** Single LLM call per trial (Claude Opus) + deterministic scoring

**How it works:**

1. **LLM Phase (one call per trial):**
   - Claude evaluates 7 signals (condition_match, status_recruiting, phase_fit, prior_treatment_compatible, age_range_fit, sites_active, enrollment_feasibility)
   - Prompt is few-shot with 3 detailed examples (match, partial, mismatch)
   - Output: structured JSON with status + evidence + confidence for each signal
   - Grounding: uses only trial fields from CT.gov, never invents facts

2. **Deterministic Scoring Phase:**
   - Maps signal status (match→1.0, partial→0.5, unknown/no_match→0.0) to weighted contribution
   - Weights: condition (30%), status (20%), phase (15%), prior_treatment (15%), age (10%), sites (5%), enrollment (5%)
   - Overall score: weighted average of all signals
   - Confidence: "high" if all signals high-confidence, "medium" if all in [high,medium], "low" otherwise

3. **Output:**
   - FitRanking object per trial with score, confidence, all signals + evidence, summary, caveats
   - Sorted by score (highest first)

**Prompt Strategy (Structured + Few-Shot):**
- Few-shot examples teach the LLM what good signal judgments look like
- Grounding rules explicitly forbid inventing trial facts
- Structured JSON output ensures parseable results
- Examples cover: clear match, partial/unknown match, clear mismatch

**Files Created:**
- `api/ranking.py` — Endpoint + core ranking logic
- `tests/test_ranking_integration.py` — Integration tests against 5 synthetic cases × 3 input styles
- Updated `requirements.txt` — Added `anthropic` dependency
- Updated `api/main.py` — Registered ranking router

**Testing:**
```bash
# Set API key first:
export ANTHROPIC_API_KEY="sk-..."

# Run integration tests:
cd "/Users/abeeryasin/Documents/Portfolio project"
PYTHONPATH=. python3 tests/test_ranking_integration.py
```

**What works:**
- ✓ Endpoint structure complete
- ✓ LLM prompt designed with few-shot examples
- ✓ Scoring logic deterministic and reproducible
- ✓ Test harness ready to validate

**What needs:**
- ANTHROPIC_API_KEY environment variable set to run real tests
- Once key is set, run integration tests to validate against synthetic cases

---

## Concepts Implemented in Unit 3

**Deterministic vs. AI Scoring:**
- ✓ Deterministic: status check, phase check, age range comparison → fast, cheap, reproducible
- ✓ LLM-assisted: researcher intent grounding, nuanced fit judgment → one call only per trial
- ✓ Per CLAUDE.md §5: "Deterministic first, AI second, agents third"

**Evidence Attachment:**
- ✓ LLM output is structured JSON (not prose)
- ✓ Each signal ties back to actual CT.gov field + actual value
- ✓ Confidence reflects data quality, not score magnitude

**Prompt Design:**
- ✓ Few-shot examples teach expected behavior
- ✓ Grounding rules forbid invention
- ✓ Structured output ensures parseable results
- ✓ Uncertainty (unknown) preferred over guessing

---

## Frontend Preview (Unit 4)

Once Unit 3 is complete, Unit 4 will display rankings:
- Table: sorted by score (highest first)
- Each row: score + top signal + confidence badge
- Click to expand: full signal list + evidence + caveats
- Researcher can re-sort by confidence, status, phase, etc.

**Aesthetic note:** Frontend will be redesigned after Unit 4 to match clinical research tools (to be detailed in Unit 5).

---

## Curated Trial Subset (for measurement)

Instead of measuring against all 11,490 tracked trials (slow), we'll use:
- **Curated subset:** 50-100 most recently updated trials per condition
- **Rationale:** Represents "actively recruiting" + "most likely to enroll"
- **Measurement:** Precision/recall/ranking quality on this subset

Query to generate:
```sql
SELECT nct_id FROM studies
WHERE active_in_scope = true
ORDER BY last_matched_at DESC
LIMIT 50 OFFSET 0;
-- Run per condition; union results to ~100-150 trials total
```

---

## Research Findings (Informing Design)

From web research on clinical researcher workflows:

1. **Hybrid approach wins:** Automated pre-screening + clinician judgment
2. **Evidence matters:** Clinicians want to see *why*, not just scores
3. **Uncertainty is honest:** "Unknown" is better than confident guess
4. **Timeline pressure:** Decisions needed within ~2 weeks
5. **Key signals:** condition, status, phase, prior-treatment requirements, age, sites, biomarkers
6. **Interface:** filters, sortable results, evidence visible, link to full data

---

## Files Created

- `api/ranking_schemas.py` — Schema models (FitSignal, FitRanking, test models)
- `tests/test_data_synthetic_trials.py` — 5 test cases × 3 input styles each
- `tests/test_ranking_harness.py` — Evaluation framework + baseline metrics
- `tests/__init__.py` — Package marker

---

## Summary: What Works Right Now

✓ Schema is clear; no ambiguity on what output should look like  
✓ Test cases are defined; we know what "good" looks like  
✓ Baseline metrics are set; we can measure improvement  
✓ Evaluation framework is ready to run (once Unit 3 endpoint exists)  

Next session: Build Unit 3 (ranking endpoint) and watch these tests pass.
