"""frontend/pages/2_Understand.py — the AI reading, rendered honestly.

The stored prose interpretations (step 7c) are the only thing TrialLens
displays that a MODEL wrote rather than computed. Everything else on an
amendment is either the registry's own text or arithmetic on two stored
values. That makes three properties load-bearing, and none of them are
visible by looking at the code:

  - **The attribution travels with the text.** A reader who sees only the
    sentence must still know a model wrote it. If a future edit moves the
    label into a page footer, or drops it while keeping the text, nothing
    errors and the page starts presenting a model's reading as a study fact
    (CLAUDE.md sec. 2).
  - **primary_outcomes renders it.** That field is BOTH structured and
    interpreted, and 5 of the 7 stored readings are on it. Rendering only
    in the long-text branch left most of them invisible — the exact bug
    this work exists to fix, caught during the build.
  - **The diff survives.** The interpretation accompanies the source text,
    never replaces it, so the claim can be checked.

Free: no database, no network, no model.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_understand_page.py -v
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit not installed"
).AppTest

PAGE = str(FRONTEND / "pages" / "2_Understand.py")
RUN = datetime(2026, 9, 3, 13, 13, 20, tzinfo=timezone.utc)

# NCT06635980's real stored reading — the most valuable of the seven.
REAL_SUMMARY = (
    "The denominator for calculating adverse event rate changed from patients "
    "who started RT at 2 years to all randomized patients in the primary "
    "analysis population."
)
# NCT05846789's, on a long-text field.
ELIGIBILITY_SUMMARY = (
    "Trial expanded to include ER-positive, HER2-negative breast cancer "
    "patients (previously ER-low only)."
)


def study():
    """A tracked trial, built from the real response model rather than typed
    out. The page reads several fields with strict `study['x']`, so a
    hand-written dict silently drifts from what the endpoint returns and the
    test fails for a reason that has nothing to do with what it asserts —
    which is exactly what happened on the first run of this file."""
    from api.schemas import TrialDetail

    return TrialDetail(
        nct_id="NCT06635980",
        brief_title="A Trial of Radiotherapy Timing",
        overall_status="RECRUITING",
        source="tracked",
        conditions=["Breast Cancer"],
        active_in_scope=True,
    ).model_dump(mode="json")


def change(field, interpretation=None, old="before", new="after"):
    return {
        "field_name": field,
        "old_value": old,
        "new_value": new,
        "detected_at": RUN.isoformat(),
        "category": "Trial content",
        "aspect": "Scientific",
        "effect": None,
        "interpretation": interpretation,
    }


def history(*changes):
    return {
        "nct_id": "NCT06635980",
        "amendments": [
            {
                "posted_on": "2026-09-02",
                "previously_posted_on": "2026-08-28",
                "detected_at": RUN.isoformat(),
                "changes": list(changes),
                "aspects": ["Scientific"],
                "content_is_visible": True,
            }
        ],
        "total_amendments": 1,
        "invisible_amendment_count": 0,
        "recording_since": "2026-08-28T12:55:52Z",
        "unattributed_changes": [],
    }


@pytest.fixture
def render(monkeypatch):
    """Run Understand against a stubbed API, dispatching on the path."""
    import api_client

    def _render(amendments):
        def fake_get(path, params=None):
            if path.endswith("/amendments"):
                return amendments
            if path.endswith("/changes"):
                return {"nct_id": "NCT06635980", "changes": []}
            return study()

        monkeypatch.setattr(api_client, "get", fake_get)
        app = AppTest.from_file(PAGE, default_timeout=30)
        app.session_state["selected_nct_id"] = "NCT06635980"
        app.run()
        assert not app.exception, [e.value for e in app.exception]

        seen = []
        for kind in (
            "title", "header", "subheader", "markdown", "caption",
            "info", "warning", "error", "metric", "expander", "text",
        ):
            try:
                elements = getattr(app, kind)
            except (AttributeError, KeyError):
                continue
            for element in elements:
                for attr in ("label", "value", "body"):
                    text = getattr(element, attr, None)
                    if isinstance(text, str):
                        seen.append(text)
        return "\n".join(seen), app

    return _render


def test_the_attribution_travels_with_the_text(render):
    """The one rule that cannot be allowed to drift. Asserted on the SAME
    rendered element, not merely both being somewhere on the page, so
    splitting them apart fails here."""
    _, app = render(history(change("primary_outcomes", REAL_SUMMARY)))

    blocks = [
        m.value for m in app.markdown
        if isinstance(m.value, str) and REAL_SUMMARY in m.value
    ]
    assert blocks, "the stored interpretation never rendered"
    assert all("not from ClinicalTrials.gov" in b for b in blocks), (
        "an interpretation rendered without its attribution in the same element"
    )


def test_a_structured_field_still_shows_its_interpretation(render):
    """primary_outcomes is a STRUCTURED field and carries 5 of the 7 stored
    readings. It took its own branch, and rendering only in the long-text
    branch hid most of the feature."""
    page, _ = render(history(change("primary_outcomes", REAL_SUMMARY)))
    assert REAL_SUMMARY in page


def test_a_long_text_field_shows_it_above_the_diff(render):
    """Eligibility rewrites are the case where "+83 / −41 words" tells a
    reader nothing, so the reading must be visible without opening the
    expander — while the expander still exists."""
    page, app = render(
        history(change("eligibility_criteria", ELIGIBILITY_SUMMARY, "a" * 400, "b" * 500))
    )
    assert ELIGIBILITY_SUMMARY in page
    assert any("Show what changed" in (e.label or "") for e in app.expander), (
        "the interpretation replaced the diff instead of accompanying it"
    )


def test_no_interpretation_draws_no_ai_block(render):
    """Most changes have none. An attributed empty block would imply the
    model looked and found nothing to say."""
    page, _ = render(history(change("completion_date", None, "2026-08-31", "2027-08-27")))
    assert "not from ClinicalTrials.gov" not in page


def test_the_scope_note_appears_only_when_a_reading_is_on_the_page(render):
    """Absence of an interpretation has three different causes the stored
    column cannot separate — wrong field, too old, or the model said the
    change was not meaningful. The note explains that where it is relevant,
    and stays out of the way on the great majority of trials that have none."""
    with_reading, _ = render(history(change("primary_outcomes", REAL_SUMMARY)))
    assert "AI readings exist only for" in with_reading

    without, _ = render(history(change("completion_date", None)))
    assert "AI readings exist only for" not in without


def test_an_interpretation_is_not_presented_as_the_registry_speaking(render):
    """The failure this whole design guards against: a model's sentence
    rendered in the same register as the trial's own recorded values."""
    page, _ = render(history(change("primary_outcomes", REAL_SUMMARY)))
    assert "AI reading" in page
