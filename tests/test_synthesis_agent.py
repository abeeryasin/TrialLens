"""api/synthesis_agent.py's tool-use loop. Free — the Anthropic client and
every HTTP call are faked; nothing here reaches the network.

The loop mechanics matter more than any one tool's plumbing: does the
budget guard stop BEFORE a call it can't afford (never after), does
MAX_TURNS actually cap a model that keeps asking for tools, are all tool_use
blocks in one turn executed (Anthropic allows several per response), and
does propose_finding land in the returned list without ever going over
HTTP — it is the one "tool" that is really just a way for the model to hand
back a result.
"""
import pytest

import api.synthesis_agent as sa


class _FakeUsage:
    def __init__(self, input_tokens=1000, output_tokens=100):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _ToolUse:
    type = "tool_use"

    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, content, stop_reason, usage=None):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage or _FakeUsage()


class _FakeMessages:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.calls.append(kwargs)
        if not self._outer.script:
            raise AssertionError("the script ran out — the loop made more calls than expected")
        return self._outer.script.pop(0)


class _ScriptedClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = _FakeMessages(self)


def _install(monkeypatch, script):
    client = _ScriptedClient(script)
    monkeypatch.setattr(sa, "_client", lambda: client)
    return client


def _install_get(monkeypatch, handler):
    """handler(path, params) -> dict, records calls on the returned list."""
    calls = []

    def fake_get(api_base_url, path, params=None):
        calls.append((path, params))
        return handler(path, params)

    monkeypatch.setattr(sa, "_get", fake_get)
    return calls


ENDS_TURN = _FakeResponse([_Text("Nothing stood out this week.")], "end_turn")


class TestAQuietWeek:
    def test_no_proposals_is_a_valid_outcome(self, monkeypatch):
        _install(monkeypatch, [ENDS_TURN])
        _install_get(monkeypatch, lambda path, params: {})
        proposals, spend = sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert proposals == []
        assert spend > 0


class TestProposeFinding:
    def test_is_recorded_without_an_http_call(self, monkeypatch):
        tool_call = _FakeResponse(
            [
                _ToolUse(
                    "t1",
                    "propose_finding",
                    {
                        "finding_type": "outcome_change_cluster",
                        "summary": "3 trials changed a primary outcome this week vs 0-1 in the prior 3.",
                        "confidence": "medium",
                        "evidence": "get_window weeks_ago=0..3: outcomes.changes = 3,1,0,1",
                    },
                )
            ],
            "tool_use",
        )
        _install(monkeypatch, [tool_call, ENDS_TURN])
        get_calls = _install_get(monkeypatch, lambda path, params: {})

        proposals, spend = sa.run_synthesis("http://x", max_cost_usd=1.0)

        assert proposals == [
            {
                "finding_type": "outcome_change_cluster",
                "summary": "3 trials changed a primary outcome this week vs 0-1 in the prior 3.",
                "confidence": "medium",
                "evidence": "get_window weeks_ago=0..3: outcomes.changes = 3,1,0,1",
            }
        ]
        assert get_calls == [], "propose_finding must never make an HTTP call"

    def test_can_be_called_more_than_once_in_a_run(self, monkeypatch):
        two_findings = _FakeResponse(
            [
                _ToolUse("t1", "propose_finding", {
                    "finding_type": "a", "summary": "s1", "confidence": "low", "evidence": "e1",
                }),
                _ToolUse("t2", "propose_finding", {
                    "finding_type": "b", "summary": "s2", "confidence": "high", "evidence": "e2",
                }),
            ],
            "tool_use",
        )
        _install(monkeypatch, [two_findings, ENDS_TURN])
        _install_get(monkeypatch, lambda path, params: {})

        proposals, _ = sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert len(proposals) == 2
        assert {p["finding_type"] for p in proposals} == {"a", "b"}


class TestToolRouting:
    def test_get_window_computes_as_of_from_weeks_ago(self, monkeypatch):
        call = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 2})], "tool_use"
        )
        _install(monkeypatch, [call, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {"window": {}})

        sa.run_synthesis("http://x", days=7, max_cost_usd=1.0)

        assert len(calls) == 1
        path, params = calls[0]
        assert path == "/investigate"
        assert params["days"] == 7
        # weeks_ago=2 -> as_of is ~14 days back, not "now".
        from datetime import datetime, timezone
        as_of = datetime.fromisoformat(params["as_of"])
        age_days = (datetime.now(timezone.utc) - as_of).days
        assert 13 <= age_days <= 14

    def test_get_window_passes_condition_through_when_given(self, monkeypatch):
        call = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0, "condition": "Obesity"})],
            "tool_use",
        )
        _install(monkeypatch, [call, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {})
        sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert calls[0][1]["condition"] == "Obesity"

    def test_get_landscape_hits_the_landscape_route(self, monkeypatch):
        call = _FakeResponse([_ToolUse("t1", "get_landscape", {})], "tool_use")
        _install(monkeypatch, [call, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {})
        sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert calls[0][0] == "/investigate/landscape"

    def test_get_trial_amendments_hits_the_studies_route(self, monkeypatch):
        call = _FakeResponse(
            [_ToolUse("t1", "get_trial_amendments", {"nct_id": "NCT04837586"})],
            "tool_use",
        )
        _install(monkeypatch, [call, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {})
        sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert calls[0][0] == "/studies/NCT04837586/amendments"

    def test_get_recent_proposals_hits_the_synthesis_route(self, monkeypatch):
        call = _FakeResponse(
            [_ToolUse("t1", "get_recent_proposals", {"days": 14})], "tool_use"
        )
        _install(monkeypatch, [call, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {})
        sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert calls[0][0] == "/synthesis/proposals"
        assert calls[0][1]["days"] == 14

    def test_multiple_tool_use_blocks_in_one_turn_are_all_executed(self, monkeypatch):
        """Anthropic's API can return several tool_use blocks in one
        response — this is how the agent compares several weeks without
        spending a whole turn per week."""
        parallel = _FakeResponse(
            [
                _ToolUse("t1", "get_window", {"weeks_ago": 0}),
                _ToolUse("t2", "get_window", {"weeks_ago": 1}),
                _ToolUse("t3", "get_window", {"weeks_ago": 2}),
            ],
            "tool_use",
        )
        _install(monkeypatch, [parallel, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {})
        sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert len(calls) == 3


class TestBudgetAndTurnCaps:
    def test_the_first_turn_never_happens_once_the_budget_cannot_cover_it(self, monkeypatch):
        client = _install(monkeypatch, [ENDS_TURN])
        _install_get(monkeypatch, lambda path, params: {})

        proposals, spend = sa.run_synthesis(
            "http://x", max_cost_usd=sa.COST_ESTIMATE_PER_TURN_USD / 2
        )

        assert client.calls == [], "no call should have been made past the ceiling"
        assert proposals == []
        assert spend == 0.0

    def test_max_turns_caps_the_loop_even_if_the_model_keeps_asking_for_tools(self, monkeypatch):
        keeps_going = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0})], "tool_use"
        )
        # More scripted turns than max_turns allows — if the cap didn't
        # work, _FakeMessages.create would run out and raise.
        client = _install(monkeypatch, [keeps_going, keeps_going, keeps_going, keeps_going])
        _install_get(monkeypatch, lambda path, params: {})

        sa.run_synthesis("http://x", max_cost_usd=1.0, max_turns=2)

        assert len(client.calls) == 2


class TestBilling:
    def test_cost_comes_from_real_token_counts(self, monkeypatch):
        """$1.00/MTok in, $5.00/MTok out — same rate as api/prose_interpreter.py."""
        response = _FakeResponse(
            [_Text("done")], "end_turn",
            usage=_FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        )
        _install(monkeypatch, [response])
        _install_get(monkeypatch, lambda path, params: {})
        _, spend = sa.run_synthesis("http://x", max_cost_usd=100.0)
        assert spend == pytest.approx(6.00)

    def test_spend_accumulates_across_turns(self, monkeypatch):
        cheap = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0})], "tool_use",
            usage=_FakeUsage(input_tokens=1000, output_tokens=100),
        )
        _install(monkeypatch, [cheap, ENDS_TURN])
        _install_get(monkeypatch, lambda path, params: {})
        _, spend = sa.run_synthesis("http://x", max_cost_usd=1.0)
        per_call = (1000 * 1.00 + 100 * 5.00) / 1_000_000
        assert spend == pytest.approx(per_call * 2)


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError):
        sa.run_synthesis("http://x")
