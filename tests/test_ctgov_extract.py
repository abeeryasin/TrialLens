"""ctgov_client.extract_fields — the parser every stored value passes through.

This runs every 6 hours against ~11,500 trials and had no test of any kind
until 2026-09-02. Everything the database holds is whatever this function
returned, so a silent parsing change is a silent data change: no error, no
failed run, just a column that quietly starts arriving empty. Bug #7 in
docs/decisions.md was exactly that shape — eligibility_criteria never
reaching a prompt, passing every test that existed.

The fixtures are **real stored API responses**, pulled out of the live
database's raw_json and committed unmodified: NCT00002644 (interventional,
phased, with sites) and NCT00026754 (observational, no phase). Written
against real records rather than hand-built JSON because the whole class of
bug here is "the real shape isn't what we assumed" — a fixture invented from
the API docs would encode the same assumption twice and prove nothing
(CLAUDE.md sec. 6).

Free: no network, no database, no model. Runs in CI.
"""
import json
from pathlib import Path

import pytest

from api.schemas import StudyUpsert
from ctgov_client import ACTIVE_STATUSES, CLOSED_STATUSES, extract_fields

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"ctgov_{name}.json").read_text())


@pytest.fixture
def interventional():
    return load("interventional_with_phase")


@pytest.fixture
def observational():
    return load("observational_no_phase")


class TestItProducesWhatTheDatabaseExpects:
    def test_the_result_validates_as_a_StudyUpsert(self, interventional):
        """The real contract. extract_fields feeds POST /studies/batch, so
        if the parser and the schema drift apart, ingestion fails at 3am on
        a runner nobody is watching — or worse, silently drops a field the
        schema treats as optional."""
        record = extract_fields(interventional)
        model = StudyUpsert(**{k: v for k, v in record.items() if k in StudyUpsert.model_fields})
        assert model.nct_id == record["nct_id"]

    def test_every_schema_field_is_supplied(self, interventional):
        """A field the parser stops emitting becomes None on every future
        record, which looks identical to 'CT.gov stopped reporting it'."""
        record = extract_fields(interventional)
        missing = set(StudyUpsert.model_fields) - set(record)
        assert not missing, f"extract_fields no longer emits {sorted(missing)}"

    def test_every_value_actually_arrives_from_the_source_record(self, interventional):
        """The bug #7 guard, and the reason it exists.

        Asserting a key is PRESENT is not the same as asserting its value
        arrived: `"eligibility_criteria": None` satisfies "the key exists",
        the schema (it's Optional), and every shape test in this file —
        while silently emptying a column across 11,500 trials on the next
        cron run. That is exactly bug #7, where eligibility_criteria never
        reached a prompt and every test in existence still passed.

        So each field is checked against the path it should have come from,
        rather than against a hand-copied expected value that would drift.
        """
        protocol = interventional["protocolSection"]
        record = extract_fields(interventional)

        expected = {
            "nct_id": protocol["identificationModule"]["nctId"],
            "brief_title": protocol["identificationModule"].get("briefTitle", ""),
            "official_title": protocol["identificationModule"].get("officialTitle"),
            "overall_status": protocol["statusModule"].get("overallStatus"),
            "study_type": protocol.get("designModule", {}).get("studyType"),
            "eligibility_criteria": protocol.get("eligibilityModule", {}).get("eligibilityCriteria"),
            "minimum_age": protocol.get("eligibilityModule", {}).get("minimumAge"),
            "sex": protocol.get("eligibilityModule", {}).get("sex"),
            "brief_summary": protocol.get("descriptionModule", {}).get("briefSummary"),
            "lead_sponsor": protocol.get("sponsorCollaboratorsModule", {})
                                    .get("leadSponsor", {}).get("name"),
            "enrollment_count": protocol.get("designModule", {})
                                        .get("enrollmentInfo", {}).get("count"),
            "enrollment_type": protocol.get("designModule", {})
                                       .get("enrollmentInfo", {}).get("type"),
            "last_update_post_date": protocol["statusModule"]
                                             .get("lastUpdatePostDateStruct", {}).get("date"),
            "conditions": protocol.get("conditionsModule", {}).get("conditions", []),
        }

        for field, want in expected.items():
            assert record[field] == want, (
                f"{field} did not come through from the source record: "
                f"got {record[field]!r}, source has {want!r}"
            )

        # And the fields that matter most must not be empty in a fixture
        # chosen precisely because it populates them — otherwise the loop
        # above passes by comparing None to None.
        for field in ("eligibility_criteria", "brief_summary", "brief_title",
                      "overall_status", "last_update_post_date", "conditions"):
            assert record[field], f"{field} is empty in a fixture that should populate it"

        assert record["interventions"] and record["locations"], (
            "this fixture was chosen for having interventions and sites"
        )

    def test_raw_json_is_the_untouched_input(self, interventional):
        """Sec. 4 requires the raw record be stored as received, so a
        parsing decision made today can be revisited against the original."""
        record = extract_fields(interventional)
        assert record["raw_json"] is interventional


class TestTheRealValueFormats:
    def test_phase_is_stored_ctgov_style_not_docs_style(self, interventional):
        """"PHASE2", never "Phase 2" — and comma-joined when a trial spans
        phases. A prompt written against the docs' format taught a model a
        value the column never stores (docs/decisions.md, 2026-08-31)."""
        phase = extract_fields(interventional)["phase"]
        assert phase is not None, "this fixture was chosen because it HAS a phase"
        # The eight real tokens, from the live database (2026-08-30). "NA"
        # means the trial has no phase concept — not a missing value.
        real_tokens = {"EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"}
        for token in phase.split(","):
            assert token in real_tokens, (
                f"{token!r} is not a phase value the database stores. "
                f"Docs-style 'Phase 2' is the classic wrong shape here."
            )

    def test_a_trial_with_no_phase_gets_None_not_an_empty_string(self, observational):
        """64% of trials have no usable phase. None and "" are different
        answers to a SQL query, and the wrong one silently changes counts."""
        assert extract_fields(observational)["phase"] is None

    def test_status_is_one_of_the_real_values(self, interventional, observational):
        real = set(ACTIVE_STATUSES.split(",")) | set(CLOSED_STATUSES.split(","))
        for study in (interventional, observational):
            assert extract_fields(study)["overall_status"] in real

    def test_ages_keep_their_units(self, interventional):
        """CT.gov reports "18 Years" / "6 Months" and the unit genuinely
        varies. Stripping to a number here would silently turn 6 months
        into 6 years."""
        for field in ("minimum_age", "maximum_age"):
            value = extract_fields(interventional).get(field)
            if value is not None:
                assert not str(value).isdigit(), f"{field}={value!r} lost its unit"


class TestMissingDataNeverBecomesInventedData:
    def test_an_empty_record_does_not_crash_on_optional_fields(self):
        """Not every study has every module. The only thing a record cannot
        lack is its ID."""
        record = extract_fields({"protocolSection": {
            "identificationModule": {"nctId": "NCT00000000"}}})
        assert record["nct_id"] == "NCT00000000"
        assert record["phase"] is None
        assert record["interventions"] == []
        assert record["primary_outcomes"] == []
        assert record["locations"] == []

    def test_a_record_with_no_nct_id_raises_rather_than_inventing_one(self):
        """Deliberate: nct_id is the primary key and indexed with [] not
        .get(). A record without one is unusable, and failing loudly beats
        writing a row keyed on None."""
        with pytest.raises(KeyError):
            extract_fields({"protocolSection": {"identificationModule": {}}})

    def test_a_status_free_record_is_marked_UNKNOWN_which_is_not_a_real_status(self):
        """Documents a real inconsistency rather than asserting it's fine.

        The parser defaults overall_status to "UNKNOWN", which is NOT one of
        the eight values CT.gov actually uses. No stored row has it today,
        so nothing downstream has ever met it — but api/tracking.py would
        read it as "not an active status" and tell a researcher the trial's
        status "isn't one of the statuses tracked", which is a statement
        about CT.gov's data rather than about our parse failing.

        Kept as a test so the behaviour is visible and deliberate. If a real
        record ever arrives without a status, this is where to look.
        """
        record = extract_fields({"protocolSection": {
            "identificationModule": {"nctId": "NCT00000000"}}})
        assert record["overall_status"] == "UNKNOWN"
        assert "UNKNOWN" not in set(ACTIVE_STATUSES.split(",")) | set(CLOSED_STATUSES.split(","))

    def test_nested_list_entries_keep_only_the_stored_subfields(self, interventional):
        """Trimmed on purpose — the full structure stays in raw_json. If
        these grow silently, the diff in api/studies.py starts reporting
        changes to fields nothing displays."""
        record = extract_fields(interventional)
        for item in record["interventions"]:
            assert set(item) == {"type", "name", "description"}
        for item in record["primary_outcomes"]:
            assert set(item) == {"measure", "description", "time_frame"}
        for item in record["locations"]:
            assert set(item) == {"facility", "city", "country"}

    def test_dates_are_passed_through_as_written_not_normalized(self, interventional):
        """~23% of trials report month-only dates ("2027-06"). Coercing them
        to a real date would invent a day CT.gov never specified (sec. 2) —
        which is why these columns are TEXT."""
        record = extract_fields(interventional)
        for field in ("start_date", "primary_completion_date", "completion_date"):
            value = record[field]
            if value is not None:
                assert isinstance(value, str)
                assert len(value) in (7, 10), f"{field}={value!r} is an unexpected shape"
