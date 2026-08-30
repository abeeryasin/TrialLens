"""What actually reaches the model — asserted without calling it.

This is the free half of evaluating an LLM feature, and it is the half that
would have caught the bug that really happened: `prior_treatment_compatible`
carried 15% of the scoring weight while `eligibility_criteria` was never
placed in the prompt payload, so the signal could only ever return
`unknown`. No amount of paid eval running distinguishes "the model judged
this and couldn't tell" from "the model was never shown the data" — but a
free assertion on the payload does, instantly.

Run: PYTHONPATH=. python3 -m pytest tests/test_ranking_prompt_payload.py -v
"""
import json
from datetime import date, datetime

import pytest

from api.ranking import (
    ELIGIBILITY_CHAR_LIMIT,
    SEMANTIC_SCHEMA,
    SEMANTIC_SIGNAL_NAMES,
    SEMANTIC_SYSTEM,
    INTEREST_PARSE_SCHEMA,
    _trial_context,
    build_semantic_user_content,
)
from api.ranking_deterministic import ResearcherPreferences
from api.schemas import Intervention, StudyDetail, TrialLocation

CRITERIA = (
    "Inclusion Criteria:\n"
    "* Histologically confirmed metastatic breast cancer\n"
    "* Disease progression following at least 2 lines of therapy\n"
    "Exclusion Criteria:\n"
    "* Prior treatment with a checkpoint inhibitor\n"
)


def make_trial(**overrides) -> StudyDetail:
    base = dict(
        nct_id="NCT99999999",
        brief_title="Checkpoint Inhibitor in Metastatic Breast Cancer",
        official_title="A Phase 2 Study of Pembrolizumab in Metastatic Breast Cancer",
        overall_status="RECRUITING",
        phase="PHASE2",
        study_type="INTERVENTIONAL",
        last_update_post_date=date(2026, 8, 1),
        active_in_scope=True,
        enrollment_count=150,
        enrollment_type="ESTIMATED",
        minimum_age="18 Years",
        maximum_age="75 Years",
        eligibility_criteria=CRITERIA,
        fetched_at=datetime(2026, 8, 30),
        last_matched_at=datetime(2026, 8, 30),
        conditions=["Breast Neoplasms", "Metastatic Breast Cancer"],
        brief_summary="A study of pembrolizumab combined with chemotherapy.",
        lead_sponsor="Example Cancer Center",
        interventions=[Intervention(type="DRUG", name="Pembrolizumab", description="anti-PD-1")],
        locations=[TrialLocation(facility="Site", city="Boston", country="United States")],
    )
    base.update(overrides)
    return StudyDetail(**base)


PREFS = ResearcherPreferences(
    condition_terms=["breast cancer", "immunotherapy"],
    prior_treatment_context="patients who have failed at least two prior lines of chemotherapy",
    raw_interest="breast cancer immunotherapy after two prior lines",
)


# ============================================================================
# The regression that actually happened
# ============================================================================


class TestEligibilityCriteriaReachTheModel:
    def test_criteria_text_is_in_the_payload(self):
        """The exact bug: 15% of scoring weight judged on data never sent."""
        payload = _trial_context(make_trial())
        assert "2 lines of therapy" in payload
        assert "checkpoint inhibitor" in payload.lower()

    def test_criteria_survive_into_the_full_user_content(self):
        """Not just in the trial blob — in what is actually sent."""
        content = build_semantic_user_content(make_trial(), PREFS)
        assert "2 lines of therapy" in content

    def test_researcher_prior_treatment_context_is_sent(self):
        """The other half of the comparison. Without it the signal is blind
        even when the trial's criteria are present."""
        content = build_semantic_user_content(make_trial(), PREFS)
        assert "two prior lines of chemotherapy" in content

    def test_absent_prior_context_is_stated_explicitly_not_omitted(self):
        """A silently missing field reads to the model as an empty string.
        Saying 'the researcher said nothing' is a different instruction from
        saying nothing at all."""
        content = build_semantic_user_content(make_trial(), ResearcherPreferences())
        assert "said nothing about prior therapy" in content

    def test_missing_criteria_are_marked_null_not_empty_string(self):
        payload = json.loads(_trial_context(make_trial(eligibility_criteria=None)))
        assert payload["eligibility_criteria"] is None
        assert payload["eligibility_criteria_truncated"] is False


# ============================================================================
# Truncation must be visible, not silent
# ============================================================================


class TestTruncation:
    def test_long_criteria_are_truncated(self):
        long_text = "x" * (ELIGIBILITY_CHAR_LIMIT + 5000)
        payload = json.loads(_trial_context(make_trial(eligibility_criteria=long_text)))
        assert len(payload["eligibility_criteria"]) < len(long_text)

    def test_truncation_is_flagged_so_the_model_knows(self):
        """A silent cut looks to the model like the whole document — it could
        then report 'the criteria say nothing about prior therapy' when the
        relevant line was simply removed."""
        long_text = "x" * (ELIGIBILITY_CHAR_LIMIT + 5000)
        payload = json.loads(_trial_context(make_trial(eligibility_criteria=long_text)))
        assert payload["eligibility_criteria_truncated"] is True
        assert "truncated" in payload["eligibility_criteria"]

    def test_short_criteria_are_not_flagged(self):
        payload = json.loads(_trial_context(make_trial()))
        assert payload["eligibility_criteria_truncated"] is False
        assert "truncated" not in payload["eligibility_criteria"]


# ============================================================================
# The rest of the evidence the two signals rest on
# ============================================================================


class TestSemanticEvidenceIsPresent:
    def test_fields_the_condition_signal_needs(self):
        """condition_match must distinguish subject from incidental mention,
        which needs the title and summary — not just the condition tags."""
        payload = json.loads(_trial_context(make_trial()))
        for field in ("brief_title", "official_title", "brief_summary",
                      "registered_conditions", "interventions"):
            assert payload.get(field), f"{field} missing from the payload"

    def test_interventions_carry_names(self):
        """Mechanism matching ('is this immunotherapy?') rests on these."""
        payload = json.loads(_trial_context(make_trial()))
        assert payload["interventions"][0]["name"] == "Pembrolizumab"

    def test_payload_is_valid_json(self):
        json.loads(_trial_context(make_trial()))

    def test_no_deterministic_fields_leak_into_the_semantic_payload(self):
        """Status, phase, ages, sites and enrollment are scored in code. Sending
        them invites the model to re-judge what is already settled, and to
        contradict the deterministic evidence shown beside it."""
        payload = json.loads(_trial_context(make_trial()))
        for field in ("overall_status", "phase", "minimum_age", "maximum_age",
                      "locations", "locations_count", "enrollment_count"):
            assert field not in payload, f"{field} should not be sent to the model"


# ============================================================================
# Prompt/schema agreement — a mismatch here fails at runtime, per trial
# ============================================================================


class TestPromptAndSchemaAgree:
    def test_schema_asks_for_exactly_the_semantic_signals(self):
        """The mechanical five must never appear here — they are scored in code."""
        prefixes = {k.rsplit("_", 1)[0] for k in SEMANTIC_SCHEMA["properties"]}
        assert prefixes == set(SEMANTIC_SIGNAL_NAMES)
        assert prefixes == {"condition_is_subject", "approach_match", "prior_treatment"}

    def test_every_schema_field_is_required(self):
        """An optional field means the model may omit it, and the KeyError
        surfaces as a failed trial mid-search."""
        assert set(SEMANTIC_SCHEMA["required"]) == set(SEMANTIC_SCHEMA["properties"])

    def test_schemas_forbid_extra_properties(self):
        for schema in (SEMANTIC_SCHEMA, INTEREST_PARSE_SCHEMA):
            assert schema["additionalProperties"] is False

    def test_interest_parse_schema_allows_null_for_every_preference(self):
        """'Not stated' must be expressible. A non-nullable field forces the
        model to invent a preference the researcher never expressed."""
        props = INTEREST_PARSE_SCHEMA["properties"]
        for field in ("phases", "require_recruiting", "min_age_years",
                      "max_age_years", "prior_treatment_context"):
            assert "null" in props[field]["type"], f"{field} cannot express 'not stated'"

    def test_prompt_tells_the_model_not_to_claim_eligibility(self):
        """CLAUDE.md sec. 2 — never assert a patient is eligible for a trial."""
        assert "eligible" in SEMANTIC_SYSTEM.lower()

    def test_prompt_prefers_unknown_over_guessing(self):
        assert "unknown" in SEMANTIC_SYSTEM.lower()
        assert "guess" in SEMANTIC_SYSTEM.lower()
