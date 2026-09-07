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
        proposals, spend, _ = sa.run_synthesis("http://x", max_cost_usd=1.0)
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

        proposals, spend, _ = sa.run_synthesis("http://x", max_cost_usd=1.0)

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

        proposals, _, _ = sa.run_synthesis("http://x", max_cost_usd=1.0)
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
        assert path == "/investigate/summary"
        assert params["days"] == 7
        # weeks_ago=2 -> as_of is ~14 days back, not "now".
        from datetime import datetime, timezone
        as_of = datetime.fromisoformat(params["as_of"])
        age_days = (datetime.now(timezone.utc) - as_of).days
        assert 13 <= age_days <= 14

    def test_get_window_reads_the_summary_not_the_full_window(self, monkeypatch):
        """Measured 2026-09-07: /investigate is 39,972 characters, 99.3% of
        it per-trial reading lists built for a human to click, against 277
        characters of the numbers this agent actually reasons with. It reads
        4-6 windows and the Messages API is stateless, so window 1 is
        re-sent on every later turn — the loop paid for those cards five or
        six times over. The summary is 89.7% smaller and the same
        arithmetic."""
        call = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0})], "tool_use"
        )
        _install(monkeypatch, [call, ENDS_TURN])
        calls = _install_get(monkeypatch, lambda path, params: {})
        sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert calls[0][0] == "/investigate/summary"

    def test_the_agent_is_told_what_it_is_not_being_shown(self, monkeypatch):
        """A filter the reader cannot see is a filter taken on trust — the
        same rule the Investigate page's expander keeps for a human. It must
        also be told the detail is missing on purpose, and where to get it,
        or a summary reads as the whole picture."""
        (window_tool,) = [t for t in sa.TOOLS if t["name"] == "get_window"]
        text = window_tool["description"]
        assert "blind spots" in text
        assert "not shown to you" in text
        assert "get_trial_amendments" in text, (
            "an agent handed a summary with no route to the detail will "
            "either under-report or invent"
        )
        assert "trials_total" in text, (
            "computing a share against the capped `trials` list instead of "
            "the real total is rule 1's failure mode"
        )

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

        proposals, spend, _ = sa.run_synthesis(
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


class TestTheTwoBugsThatKilledARealRun:
    """Both from the scheduled run of 2026-09-07 (run #2), which failed on
    its sixth turn after five paid calls and recorded "$0.0000 spent"."""

    def test_a_tool_use_stop_with_no_tool_block_stops_instead_of_crashing(self, monkeypatch):
        """The live failure: `messages.8: user messages must have non-empty
        content`. stop_reason said tool_use and no tool_use block came with
        it, so the loop appended a user message whose content was [] — which
        the API rejects outright, and which cannot become valid later."""
        anomaly = _FakeResponse([_Text("thinking about it")], "tool_use")
        client = _install(monkeypatch, [anomaly])
        _install_get(monkeypatch, lambda path, params: {})

        proposals, spend, error = sa.run_synthesis("http://x", max_cost_usd=1.0)

        assert error and "no tool_use block" in error
        assert len(client.calls) == 1, "it must not send the invalid follow-up"
        for call in client.calls:
            for message in call["messages"]:
                assert message["content"] != [], "an empty user message is never valid"

    def test_the_anomaly_is_an_error_not_a_quiet_week(self, monkeypatch):
        """A run that stops here files nothing — which is indistinguishable
        from a week the agent examined and correctly found quiet, unless the
        reason is recorded. That ambiguity is what step 11 exists to remove."""
        _install(monkeypatch, [_FakeResponse([_Text("hm")], "tool_use")])
        _install_get(monkeypatch, lambda path, params: {})
        proposals, _, error = sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert proposals == []
        assert error is not None

    def test_spend_before_a_failure_is_returned_not_lost(self, monkeypatch):
        """The costlier bug. The caller's `except` logged `spend` from a
        tuple unpack that never happened, so a real spend was recorded as
        $0.0000 and the rolling 30-day ceiling could not see it — the exact
        accounting hole step 7c already paid for once."""
        paid = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0})], "tool_use",
            usage=_FakeUsage(input_tokens=40_000, output_tokens=1_000),
        )

        class _Exploding(_FakeMessages):
            def create(self, **kwargs):
                if self._outer.calls:
                    raise RuntimeError("upstream fell over")
                return super().create(**kwargs)

        client = _install(monkeypatch, [paid])
        client.messages = _Exploding(client)
        _install_get(monkeypatch, lambda path, params: {})

        _, spend, error = sa.run_synthesis("http://x", max_cost_usd=1.0)

        assert spend > 0, "the money spent before the failure must survive it"
        assert error and "upstream fell over" in error

    def test_a_failure_never_reports_zero_spend_after_a_paid_call(self, monkeypatch):
        """Stated as its own assertion because the log line that exposed
        this read 'ERROR after $0.0000 spent' — the number, not the
        exception, was the tell."""
        paid = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0})], "tool_use",
            usage=_FakeUsage(input_tokens=12_000, output_tokens=500),
        )

        class _Exploding(_FakeMessages):
            def create(self, **kwargs):
                if self._outer.calls:
                    raise RuntimeError("boom")
                return super().create(**kwargs)

        client = _install(monkeypatch, [paid])
        client.messages = _Exploding(client)
        _install_get(monkeypatch, lambda path, params: {})
        _, spend, _ = sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert f"{spend:.4f}" != "0.0000"

    def test_an_error_is_scrubbed_before_it_is_returned(self, monkeypatch):
        """It lands in a database column that GET /ops/status prints on a
        page, and this process holds an API key (api/safe_errors.py)."""
        class _Exploding(_FakeMessages):
            def create(self, **kwargs):
                raise RuntimeError(
                    "connection failed: postgresql://user:hunter2@db.example/x"
                )

        client = _install(monkeypatch, [])
        client.messages = _Exploding(client)
        _install_get(monkeypatch, lambda path, params: {})
        _, _, error = sa.run_synthesis("http://x", max_cost_usd=1.0)
        assert "hunter2" not in error


class TestBilling:
    def test_cost_comes_from_real_token_counts(self, monkeypatch):
        """$1.00/MTok in, $5.00/MTok out — same rate as api/prose_interpreter.py."""
        response = _FakeResponse(
            [_Text("done")], "end_turn",
            usage=_FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        )
        _install(monkeypatch, [response])
        _install_get(monkeypatch, lambda path, params: {})
        _, spend, _ = sa.run_synthesis("http://x", max_cost_usd=100.0)
        assert spend == pytest.approx(6.00)

    def test_spend_accumulates_across_turns(self, monkeypatch):
        cheap = _FakeResponse(
            [_ToolUse("t1", "get_window", {"weeks_ago": 0})], "tool_use",
            usage=_FakeUsage(input_tokens=1000, output_tokens=100),
        )
        _install(monkeypatch, [cheap, ENDS_TURN])
        _install_get(monkeypatch, lambda path, params: {})
        _, spend, _ = sa.run_synthesis("http://x", max_cost_usd=1.0)
        per_call = (1000 * 1.00 + 100 * 5.00) / 1_000_000
        assert spend == pytest.approx(per_call * 2)


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError):
        sa.run_synthesis("http://x")
