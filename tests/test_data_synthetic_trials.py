"""Synthetic test trials for Step 7 ranking/evidence harness.

Five controlled test cases covering: exact matches, boundary conditions,
confidence calibration, comorbidity edge cases, and phase preferences.

Each case has three researcher interest input styles: simple, structured, narrative.
"""
from api.ranking_schemas import (
    SyntheticTestTrial,
    TestCase,
    TestResearcherInterest,
)

# ============================================================================
# Synthetic Test Trials
# ============================================================================

TRIAL_BREAST_CANCER_PHASE2_RECRUITING = SyntheticTestTrial(
    nct_id="SYNTH001",
    brief_title="Immunotherapy for Advanced Breast Cancer",
    condition="Breast Cancer",
    overall_status="RECRUITING",
    phase="PHASE2",
    study_type="INTERVENTIONAL",
    minimum_age="18 Years",
    maximum_age="75 Years",
    enrollment_count=150,
    enrollment_type="ESTIMATED",
    lead_sponsor="University Medical Center",
    brief_summary="A randomized trial of checkpoint inhibitor combined with chemotherapy in HER2-negative advanced breast cancer.",
    locations_count=12,
    is_recruiting=True,
)

TRIAL_BREAST_CANCER_COMPLETED = SyntheticTestTrial(
    nct_id="SYNTH002",
    brief_title="Adjuvant Therapy for Early Breast Cancer",
    condition="Breast Cancer",
    overall_status="COMPLETED",
    phase="PHASE3",
    study_type="INTERVENTIONAL",
    minimum_age="21 Years",
    maximum_age="70 Years",
    enrollment_count=450,
    enrollment_type="ACTUAL",
    lead_sponsor="National Cancer Institute",
    brief_summary="Long-term follow-up study of adjuvant radiotherapy plus endocrine therapy in early-stage breast cancer.",
    locations_count=28,
    is_recruiting=False,
)

TRIAL_OBESITY_PHASE1_RECRUITING = SyntheticTestTrial(
    nct_id="SYNTH003",
    brief_title="Novel GLP-1 Analog in Obesity",
    condition="Obesity",
    overall_status="RECRUITING",
    phase="PHASE1",
    study_type="INTERVENTIONAL",
    minimum_age="18 Years",
    maximum_age="65 Years",
    enrollment_count=50,
    enrollment_type="ESTIMATED",
    lead_sponsor="Biotech Pharma Inc.",
    brief_summary="First-in-human study of a novel GLP-1 receptor agonist in patients with moderate-to-severe obesity.",
    locations_count=3,
    is_recruiting=True,
)

TRIAL_MIGRAINE_PHASE1_CLOSED = SyntheticTestTrial(
    nct_id="SYNTH004",
    brief_title="Novel CGRP Antagonist in Acute Migraine",
    condition="Migraine",
    overall_status="TERMINATED",
    phase="PHASE1",
    study_type="INTERVENTIONAL",
    minimum_age="18 Years",
    maximum_age="55 Years",
    enrollment_count=40,
    enrollment_type="ACTUAL",
    lead_sponsor="Neurology Research Inc.",
    brief_summary="Safety and efficacy of a new CGRP antagonist administered intravenously for acute migraine treatment.",
    locations_count=2,
    is_recruiting=False,
)

TRIAL_MELANOMA_CHECKPOINT_PHASE3 = SyntheticTestTrial(
    nct_id="SYNTH005",
    brief_title="Checkpoint Inhibitor in Advanced Melanoma",
    condition="Melanoma",
    overall_status="ACTIVE_NOT_RECRUITING",
    phase="PHASE3",
    study_type="INTERVENTIONAL",
    minimum_age="18 Years",
    maximum_age=None,
    enrollment_count=600,
    enrollment_type="ACTUAL",
    lead_sponsor="Global Oncology Consortium",
    brief_summary="Randomized trial comparing PD-1 inhibitor monotherapy vs combination with CTLA-4 inhibitor in advanced melanoma.",
    locations_count=42,
    is_recruiting=False,
)

# ============================================================================
# Test Case 1: Exact Match
# ============================================================================

TEST_CASE_1_EXACT_MATCH = TestCase(
    name="Exact match: tracked condition, recruiting, phase II",
    description="Researcher interested in breast cancer trials. SYNTH001 is exact match (condition, status, phase). SYNTH002 is same condition but closed. SYNTH003 has wrong condition.",
    researcher_interests=[
        TestResearcherInterest(
            style="simple",
            text="I track breast cancer trials",
        ),
        TestResearcherInterest(
            style="structured",
            text="Phase II+, actively recruiting, breast cancer only, interventional studies",
        ),
        TestResearcherInterest(
            style="narrative",
            text="I'm interested in newer therapeutic approaches for advanced breast cancer, particularly immunotherapy-based combinations that are currently being tested in patients.",
        ),
    ],
    test_trials=[
        TRIAL_BREAST_CANCER_PHASE2_RECRUITING,
        TRIAL_BREAST_CANCER_COMPLETED,
        TRIAL_OBESITY_PHASE1_RECRUITING,
    ],
    expected_ranking_order=[
        ("SYNTH001", "high"),  # Exact match
        ("SYNTH002", "medium"),  # Same condition, phase III but closed
        ("SYNTH003", "low"),  # Wrong condition
    ],
    expected_top_1_score_range=(0.75, 0.95),
    notes="All three input styles should rank SYNTH001 highest. Confidence should be high because all signals are deterministic (exact condition match, recruiting status, phase).",
)

# ============================================================================
# Test Case 2: Boundary Condition (Status Change)
# ============================================================================

TEST_CASE_2_STATUS_MATTERS = TestCase(
    name="Boundary condition: status drives feasibility",
    description="SYNTH001 (recruiting) vs SYNTH002 (completed) are the same condition and topic. Status is critical: one can enroll, one cannot.",
    researcher_interests=[
        TestResearcherInterest(
            style="simple",
            text="Breast cancer trials actively recruiting",
        ),
        TestResearcherInterest(
            style="structured",
            text="RECRUITING only, breast cancer, any phase",
        ),
        TestResearcherInterest(
            style="narrative",
            text="I want to track ongoing breast cancer studies where I could potentially enroll patients. Closed trials are less useful unless they're recent completions with published results.",
        ),
    ],
    test_trials=[
        TRIAL_BREAST_CANCER_PHASE2_RECRUITING,
        TRIAL_BREAST_CANCER_COMPLETED,
    ],
    expected_ranking_order=[
        ("SYNTH001", "high"),  # Recruiting
        ("SYNTH002", "medium"),  # Completed (useful for landscape, not enrollment)
    ],
    expected_top_1_score_range=(0.75, 0.95),
    notes="Status is the differentiator. Confidence should remain high (status is deterministic), but SYNTH002's score should carry a caution flag: 'Trial is closed; data may be useful for literature review but enrollment is not possible.'",
)

# ============================================================================
# Test Case 3: Confidence Calibration
# ============================================================================

TEST_CASE_3_CONFIDENCE_CALIBRATION = TestCase(
    name="Confidence calibration: data quality drives uncertainty",
    description="SYNTH001 has full details (summary, interventions, locations). Test that higher data completeness yields higher confidence, not higher score necessarily.",
    researcher_interests=[
        TestResearcherInterest(
            style="simple",
            text="Breast cancer immunotherapy trials",
        ),
        TestResearcherInterest(
            style="structured",
            text="Breast cancer, Phase II-III, immunotherapy focus",
        ),
        TestResearcherInterest(
            style="narrative",
            text="I'm specifically looking for trials testing novel immunotherapies in breast cancer. I want strong evidence that the trial's approach matches what I'm investigating.",
        ),
    ],
    test_trials=[
        TRIAL_BREAST_CANCER_PHASE2_RECRUITING,  # Full details
        TRIAL_MIGRAINE_PHASE1_CLOSED,  # Different condition, sparse data
    ],
    expected_ranking_order=[
        ("SYNTH001", "high"),  # Full data = high confidence
        ("SYNTH004", "low"),  # Wrong condition = low score
    ],
    expected_top_1_score_range=(0.75, 0.95),
    notes="Test that confidence levels reflect data quality, not just score magnitude. SYNTH001 should show high confidence across signals. SYNTH004 should show low confidence or unknown for irrelevant signals.",
)

# ============================================================================
# Test Case 4: Comorbidity / Off-Topic Match
# ============================================================================

TEST_CASE_4_COMORBIDITY_EDGE_CASE = TestCase(
    name="Comorbidity edge case: incidental mention vs. primary topic",
    description="SYNTH005 (melanoma trial) with checkpoint inhibitor. SYNTH001 (breast cancer with immunotherapy). Researcher interested in 'immunotherapy' broadly. Both should match, but ranking should reflect primary topic match.",
    researcher_interests=[
        TestResearcherInterest(
            style="simple",
            text="Immunotherapy cancer trials",
        ),
        TestResearcherInterest(
            style="structured",
            text="Any cancer type, Phase II+, immunotherapy interventions",
        ),
        TestResearcherInterest(
            style="narrative",
            text="I'm interested in the latest checkpoint inhibitor and combination immunotherapy approaches across different cancer types to understand mechanism of action and patient selection.",
        ),
    ],
    test_trials=[
        TRIAL_BREAST_CANCER_PHASE2_RECRUITING,  # Primary: breast cancer
        TRIAL_MELANOMA_CHECKPOINT_PHASE3,  # Primary: melanoma, but also immunotherapy
    ],
    expected_ranking_order=[
        ("SYNTH001", "high"),  # Primary condition match + immunotherapy
        ("SYNTH005", "medium"),  # Different cancer type, but strong immunotherapy signal
    ],
    expected_top_1_score_range=(0.70, 0.90),
    notes="Both should score well on immunotherapy signal. However, SYNTH001 is recruiting (actionable) while SYNTH005 is active but not recruiting (landscape only). SYNTH001 should rank higher. Confidence medium for both because 'immunotherapy interest' is parsed by LLM.",
)

# ============================================================================
# Test Case 5: Phase Preference
# ============================================================================

TEST_CASE_5_PHASE_PREFERENCE = TestCase(
    name="Phase preference: early-phase vs. late-stage trials",
    description="SYNTH003 (Phase 1, novel intervention) vs SYNTH001 (Phase 2, more mature). Researcher explicitly prefers early-phase.",
    researcher_interests=[
        TestResearcherInterest(
            style="simple",
            text="Early-phase obesity trials",
        ),
        TestResearcherInterest(
            style="structured",
            text="Phase I-II only, obesity, interventional, novel mechanisms",
        ),
        TestResearcherInterest(
            style="narrative",
            text="I'm interested in first-in-human and early clinical trials of novel obesity treatments. I want to follow emerging mechanistic approaches before they reach late-stage confirmation.",
        ),
    ],
    test_trials=[
        TRIAL_OBESITY_PHASE1_RECRUITING,  # Phase 1, novel, matches stated preference
        TRIAL_BREAST_CANCER_PHASE2_RECRUITING,  # Phase 2, but wrong condition
    ],
    expected_ranking_order=[
        ("SYNTH003", "medium"),  # Early phase, obesity, recruiting, but very small trial (50 patients)
        ("SYNTH001", "low"),  # Wrong condition (breast cancer, not obesity)
    ],
    expected_top_1_score_range=(0.50, 0.75),
    notes="SYNTH003 should rank first because condition+phase+status all match stated preference. However, confidence should be medium: trial is very early (50 patients, Phase 1, only 3 sites). This is 'promising signal but high uncertainty'. SYNTH001 scores low because condition is wrong.",
)

# ============================================================================
# Test Suite Collection
# ============================================================================

ALL_TEST_CASES = [
    TEST_CASE_1_EXACT_MATCH,
    TEST_CASE_2_STATUS_MATTERS,
    TEST_CASE_3_CONFIDENCE_CALIBRATION,
    TEST_CASE_4_COMORBIDITY_EDGE_CASE,
    TEST_CASE_5_PHASE_PREFERENCE,
]
