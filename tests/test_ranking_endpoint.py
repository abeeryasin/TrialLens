"""POST /rank over real HTTP, with the model layer stubbed out.

Free — no API key, no model call, no database. Every other ranking test
calls the scoring functions directly, and that is exactly the gap this
fills. Two real bugs have now escaped through it:

  - #1 (2026-08-31): `researcher_interest` was bound as a *query* parameter,
    because a bare `str` argument is a query param to FastAPI. The
    integration tests passed because they called the function directly and
    never went through HTTP at all.
  - #9 (2026-08-31): the endpoint passed a `ResearcherPreferences` into a
    field typed `ResearcherPreferencesOut`. FastAPI validates the *outgoing*
    response against `response_model`, so this raised on every request —
    after all N model calls had already been paid for. It was found by
    spending $0.13 on a live 20-trial run that then threw the whole result
    away. This file is what should have caught it for $0.

The rule both share: a test that calls the endpoint function directly is
not testing the endpoint. Request binding and response-model validation
are the parts FastAPI does, and only an HTTP-level call exercises them.
"""
from datetime import date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from api import ranking
from api.database import get_readonly_db
from api.main import app
from api.ranking_deterministic import ResearcherPreferences
from api.ranking_schemas import FitRanking, FitSignal
from api.schemas import StudyDetail, TrialLocation


def make_trial(nct_id="NCT00000001") -> StudyDetail:
    return StudyDetail(
        nct_id=nct_id,
        brief_title="Test trial",
        overall_status="RECRUITING",
        phase="PHASE2",
        study_type="INTERVENTIONAL",
        last_update_post_date=date(2026, 8, 1),
        active_in_scope=True,
        fetched_at=datetime(2026, 8, 30),
        last_matched_at=datetime(2026, 8, 30),
        conditions=["Breast Cancer"],
        locations=[TrialLocation(facility="Site", city="Boston", country="United States")],
    )


@pytest.fixture
def client(monkeypatch):
    """A TestClient with the database and the model layer both stubbed.

    The point is to exercise FastAPI's own request binding and response
    validation, not the scoring — so everything below the endpoint is
    replaced with something free and predictable.
    """
    app.dependency_overrides[get_readonly_db] = lambda: None

    monkeypatch.setattr(ranking, "_client", lambda: object())
    monkeypatch.setattr(ranking, "count_candidates", lambda conn, condition: 5401)
    monkeypatch.setattr(
        ranking, "select_ranking_candidates",
        # (shortlist, size of the pool it was drawn from)
        lambda conn, condition, prefs, limit: (
            [make_trial(), make_trial("NCT00000002")], 5401,
        ),
    )
    monkeypatch.setattr(
        ranking, "parse_researcher_interest",
        lambda client, interest, spend: ResearcherPreferences(
            condition_terms=["breast cancer"], phases=["PHASE2"], raw_interest=interest
        ),
    )
    monkeypatch.setattr(
        ranking, "rank_one_trial",
        lambda client, trial, prefs, spend: FitRanking(
            nct_id=trial.nct_id, brief_title=trial.brief_title, score=0.8,
            confidence="medium", summary="stub", caveats=[], source="tracked",
            evaluated_weight_fraction=0.5,
            last_update_post_date=trial.last_update_post_date,
            signals=[FitSignal(name="phase_fit", status="match", evidence="stub",
                               source_field="phase", source_value="PHASE2",
                               weight=0.15, confidence="high")],
        ),
    )

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_rank_returns_200_and_a_valid_response(client):
    """The whole round trip: body parsed in, response_model validated out.

    Bug #9 failed precisely here — a 500 from response validation, with
    every model call already billed.
    """
    response = client.post("/rank", json={
        "researcher_interest": "recruiting phase II breast cancer trials",
        "condition": "breast cancer",
        "limit": 20,
    })
    assert response.status_code == 200, response.text

    body = response.json()
    assert len(body["ranked_trials"]) == 2
    assert body["preferences"]["phases"] == ["PHASE2"]
    assert body["preferences"]["condition_terms"] == ["breast cancer"]


def test_notes_disclose_the_pool_the_shortlist_came_from(client):
    """The shortlist is chosen on 55% of the criteria, so the researcher has
    to be told both that a pool existed and how it was narrowed. Silently
    showing 20 of 5,401 as though they were all of them is the kind of
    hidden narrowing sec. 3 exists to prevent."""
    notes = client.post("/rank", json={
        "researcher_interest": "recruiting phase II breast cancer trials",
        "condition": "breast cancer",
    }).json()["notes"]
    assert "5,401" in notes
    assert "55%" in notes


def test_researcher_interest_is_a_body_field_not_a_query_param(client):
    """Bug #1's regression guard.

    A body missing `researcher_interest` must be a 422 from the body
    schema. If the field ever drifts back to being a query parameter, this
    request would instead be accepted or fail differently.
    """
    response = client.post("/rank", json={"condition": "breast cancer"})
    assert response.status_code == 422
    missing = [e["loc"] for e in response.json()["detail"]]
    assert ["body", "researcher_interest"] in missing


@pytest.mark.parametrize("body,expected", [
    ({"researcher_interest": "   ", "condition": "breast cancer"}, 400),
    ({"researcher_interest": "breast cancer trials", "condition": "  "}, 400),
])
def test_blank_inputs_are_rejected_before_any_model_call(client, body, expected):
    """Blank input must never reach the model — that would be paying to
    rank against nothing."""
    assert client.post("/rank", json=body).status_code == expected


def test_shortlist_order_survives_the_full_record_fetch():
    """`= ANY(...)` returns rows in Postgres's order, not the list's.

    The shortlist arrives already ranked by the free deterministic stage.
    Found by reading real output: ten trials tied at 1.00 came back with
    their recency tiebreak scrambled, because the second query reordered
    them. Silent, and invisible in any test that only counts rows.
    """
    from api.ranking import fetch_trials_by_id

    wanted = ["NCT03", "NCT01", "NCT02"]
    rows = [dict(nct_id=n, brief_title="t", overall_status="RECRUITING",
                 last_update_post_date=date(2026, 8, 1), active_in_scope=True,
                 fetched_at=datetime(2026, 8, 30), last_matched_at=datetime(2026, 8, 30))
            # deliberately yielded in a different order, as Postgres may
            for n in ["NCT01", "NCT02", "NCT03"]]

    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params): self._conditions = "study_conditions" in sql
        def fetchall(self): return [] if self._conditions else rows

    class FakeConn:
        def cursor(self, **kw): return FakeCursor()

    assert [t.nct_id for t in fetch_trials_by_id(FakeConn(), wanted)] == wanted


@pytest.mark.parametrize("model,expected", [
    ("claude-opus-5", True),
    ("claude-sonnet-5", True),
    ("claude-fable-5", True),
    ("claude-haiku-4-5", False),      # effort is rejected on Haiku 4.5
])
def test_effort_is_only_sent_to_models_that_accept_it(model, expected):
    """`output_config.effort` is an Opus-tier parameter.

    Sending it to Haiku 4.5 is rejected, so a cost-comparison run would have
    failed on every call. Checked against the Anthropic API reference before
    spending rather than discovered mid-run. Structured output
    (`output_config.format`) is fine on all current models — only effort is
    gated.
    """
    from api.ranking import supports_effort

    assert supports_effort(model) is expected


def test_exhausted_credits_return_503_not_a_500(monkeypatch, client):
    """An API key that exists but can't be used must fail honestly.

    Real event, 2026-09-01: the account ran out of credits. The interest
    parse sits before the per-trial loop and outside its try block, so the
    error escaped as a raw 500 with a stack trace. A researcher needs to be
    told that nothing was scored — not shown a crash, and certainly not an
    empty result list that reads as "no trials matched".
    """
    import anthropic

    def out_of_credits(*a, **kw):
        raise anthropic.APIStatusError(
            "credit balance is too low",
            response=httpx.Response(400, request=httpx.Request("POST", "/")),
            body=None,
        )

    monkeypatch.setattr(ranking, "parse_researcher_interest", out_of_credits)
    response = client.post("/rank", json={
        "researcher_interest": "breast cancer immunotherapy",
        "condition": "breast cancer",
    })
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Nothing was scored" in detail
    assert "not a problem with the trials" in detail


def test_every_trial_failing_is_a_503_not_an_empty_success(monkeypatch, client):
    """All-trials-failed is an outage, not a ranking with no results.

    Returning 200 with `ranked_trials: []` renders as "no trials matched",
    which is a false statement about the data (sec. 2)."""
    import anthropic

    def always_fails(*a, **kw):
        raise anthropic.APIStatusError(
            "credit balance is too low",
            response=httpx.Response(400, request=httpx.Request("POST", "/")),
            body=None,
        )

    monkeypatch.setattr(ranking, "rank_one_trial", always_fails)
    response = client.post("/rank", json={
        "researcher_interest": "breast cancer immunotherapy",
        "condition": "breast cancer",
    })
    assert response.status_code == 503
    assert "not a statement about fit" in response.json()["detail"]
