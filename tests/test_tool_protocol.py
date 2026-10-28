"""Adversarial tests for the tool-calling protocol (second live failure).

Live failure under repair: the executor emitted concatenated bare
tool-call objects --
  {"tool":"web_search","query":"site:shopgoodwill.com LEGO bulk auction used price","max_results":5}
  {"tool":"web_search","arguments":{"query":"site:shopgoodwill.com LEGO bulk auction used price", ...
-- which is not one JSON document, not the ExecutorStep envelope, and
not even valid JSON. The provider rejected it ("model returned non-JSON
output") and, because call_agent only repaired validation failures, the
run FAILED with zero tool calls dispatched.

The repair has two layers:
1. NATIVE protocol (preferred): Responses API function calling. Tool
   calls arrive as discrete API items and the report as a validated
   submit_report call; model JSON text is never parsed, so the
   concatenated-JSON class cannot occur.
2. LEGACY protocol: a non-JSON response now gets exactly one repair
   attempt instead of failing the run immediately, and concatenated
   output is never split, regexed, or partially parsed.
"""
import copy
import json
import os

import pytest

from src.agents.common import AgentOutputError, call_agent
from src.agents.executor import run_execution_native
from src.llm.provider import LLMError, OpenAIProvider, StubProvider, default_stub_behavior
from src.models.contracts import ExecutorStep
from src.orchestration.engine import BudgetExhausted, Orchestrator
from src.security.permissions import Permission
from src.tools.base import Tool, ToolRegistry, ToolResult
from tests.conftest import fake_fetch, fake_registry

# The exact reported failure shape: two bare tool objects concatenated,
# the first with a bare "query" field, the second with "arguments".
CONCATENATED = (
    '{"tool":"web_search","query":"site:shopgoodwill.com LEGO bulk auction '
    'used price","max_results":5}'
    '{"tool":"web_search","arguments":{"query":"site:shopgoodwill.com LEGO '
    'bulk auction used price","max_results":5}}'
)

VALID_REPORT = {
    "executive_summary": "Summary.",
    "findings": [{"id": "F1", "title": "Finding", "text": "Text.",
                  "claim_ids": ["C1"]}],
    "claims": [{"id": "C1", "text": "Claim.", "classification": "VERIFIED",
                "source_ids": ["S1"]}],
    "sources": [{"id": "S1", "url": "https://example.com/stub",
                "title": "Stub source", "retrieved_at": "2026-01-01T00:00:00Z",
                "passage": "Stub passage.",
                "verification_status": "UNCHECKED"}],
    "limitations": [],
    "unresolved_dependencies": [],
}

def fn_call(name, args, call_id="call_1"):
    return {"type": "function_call", "call_id": call_id, "name": name,
            "arguments": args if isinstance(args, str) else json.dumps(args)}


def msg(text):
    return {"type": "message",
            "content": [{"type": "output_text", "text": text}]}


def submit(report, call_id="call_sub"):
    return fn_call("submit_report", report, call_id)


class ScriptedNativeClient:
    """Scripted native tool-calling client: one list of output items per turn."""
    supports_native_tools = True

    def __init__(self, turns):
        self.turns = turns
        self.calls = []  # (instructions, input_items, tools, model)

    def create_tool_response(self, instructions, input_items, tools, model):
        self.calls.append((instructions, copy.deepcopy(input_items), tools, model))
        idx = len(self.calls) - 1
        assert idx < len(self.turns), "native client ran out of scripted turns"
        return self.turns[idx], 100, 50


def counting_registry(search=None, fetch=None, calc=None):
    """Registry whose runs record every validated execution."""
    registry = ToolRegistry()
    executed = {"web_search": [], "fetch_page": [], "calculate": []}

    def make(name, fn):
        def run(args):
            executed[name].append(args)
            return fn(args)
        return run

    registry.register(Tool(
        name="web_search", description="search", permission=Permission.READ_ONLY,
        input_schema={}, timeout_s=10,
        run=make("web_search", search or (lambda args: ToolResult(
            ok=True, output="1. Stub source -- https://example.com/stub\n   Stub passage.")))))
    registry.register(Tool(
        name="fetch_page", description="fetch", permission=Permission.READ_ONLY,
        input_schema={}, timeout_s=10,
        run=make("fetch_page", fetch or (lambda args: ToolResult(
            ok=True, output="TITLE: Stub source\n\nStub passage. extra text")))))
    registry.register(Tool(
        name="calculate", description="calc", permission=Permission.READ_ONLY,
        input_schema={}, timeout_s=10,
        run=make("calculate", calc or (lambda args: ToolResult(ok=True, output="4")))))
    registry.executed = executed
    return registry


def run_native(client, registry=None, **kwargs):
    return run_execution_native(client, "gpt-5.4-mini", ["SPEC"], registry or counting_registry(), **kwargs)


# ------------------------------------------------------- exact live failure

def test_concatenated_json_rejected_not_parsed():
    """The exact reported output is not valid JSON and is never split or
    partially parsed: the provider rejects it outright."""
    class Resp:
        output_text = CONCATENATED
        usage = None
        id = "resp-x"

    class SDK:
        class responses:
            @staticmethod
            def create(**kwargs):
                return Resp()

    provider = object.__new__(OpenAIProvider)
    provider.client = SDK()
    with pytest.raises(LLMError, match="non-JSON"):
        provider.complete("system", "USER OBJECTIVE: x", {}, "gpt-5.4-mini")


class FakeCompleteClient:
    """complete() that fails with non-JSON once, then succeeds (or not)."""

    def __init__(self, repair_payload=None):
        self.calls = 0
        self.repair_payload = repair_payload

    def complete(self, system, user, schema, model):
        self.calls += 1
        if self.calls == 1:
            raise LLMError(f"model returned non-JSON output: {CONCATENATED[:200]}")
        if self.repair_payload is None:
            raise LLMError(f"model returned non-JSON output: {CONCATENATED[:200]}")
        return self.repair_payload, 100, 50


def test_legacy_non_json_gets_one_repair_attempt():
    step = {"tool_calls": [], "done": True, "report": VALID_REPORT}
    client = FakeCompleteClient(repair_payload=step)
    result = call_agent(client, "gpt-5.4-mini", "system", "user",
                        ExecutorStep)
    assert result.done is True
    assert result.report.executive_summary == "Summary."
    assert client.calls == 2  # original + exactly one repair


def test_legacy_non_json_repair_failure_is_bounded():
    client = FakeCompleteClient(repair_payload=None)
    with pytest.raises(AgentOutputError, match="non-JSON"):
        call_agent(client, "gpt-5.4-mini", "system", "user", ExecutorStep)
    assert client.calls == 2  # no infinite repair loop


# ------------------------------------------------------- native happy paths

def test_valid_search_reaches_adapter_and_results_consumed():
    registry = counting_registry()
    client = ScriptedNativeClient([
        [fn_call("web_search", {"query": "LEGO bulk auction", "max_results": 5})],
        [submit(VALID_REPORT)],
    ])
    report = run_native(client, registry)
    assert report.executive_summary == "Summary."
    # Model-generated request -> validated execution: exactly one dispatch,
    # with Pydantic defaults filled, and the result fed into the next turn.
    assert registry.executed["web_search"] == [
        {"query": "LEGO bulk auction", "max_results": 5}]
    turn2_input = json.dumps(client.calls[1][1])
    assert "Stub passage." in turn2_input


def test_malformed_search_arguments_never_execute():
    registry = counting_registry()
    client = ScriptedNativeClient([
        [fn_call("web_search", {"query": ""})],  # fails min_length
        [fn_call("web_search", {"query": "LEGO bulk auction"})],
        [submit(VALID_REPORT)],
    ])
    report = run_native(client, registry)
    assert report.executive_summary == "Summary."
    # Two model-generated requests, one validated execution.
    assert registry.executed["web_search"] == [
        {"query": "LEGO bulk auction", "max_results": 8}]


def test_unknown_tool_name_never_executes():
    registry = counting_registry()
    client = ScriptedNativeClient([
        [fn_call("browse_web", {"query": "x"})],
        [submit(VALID_REPORT)],
    ])
    report = run_native(client, registry)
    assert report.executive_summary == "Summary."
    assert registry.executed == {"web_search": [], "fetch_page": [],
                                 "calculate": []}


def test_multiple_sequential_tool_calls():
    registry = counting_registry()
    client = ScriptedNativeClient([
        [fn_call("web_search", {"query": "LEGO"})],
        [fn_call("fetch_page", {"url": "https://example.com/stub"})],
        [fn_call("calculate", {"expression": "2 + 2"})],
        [submit(VALID_REPORT)],
    ])
    report = run_native(client, registry)
    assert report.executive_summary == "Summary."
    assert len(registry.executed["web_search"]) == 1
    assert registry.executed["fetch_page"] == [
        {"url": "https://example.com/stub"}]
    assert registry.executed["calculate"] == [{"expression": "2 + 2"}]


def test_empty_search_results_do_not_kill_run():
    def empty_search(args):
        return ToolResult(ok=False, error="search unavailable (backends returned no results)")
    registry = counting_registry(search=empty_search)
    limited = dict(VALID_REPORT)
    limited["limitations"] = ["Search returned no results; findings are limited."]
    client = ScriptedNativeClient([
        [fn_call("web_search", {"query": "obscure query"})],
        [submit(limited)],
    ])
    report = run_native(client, registry)
    assert "Search returned no results" in report.limitations[0]
    # The failed tool call was still fed back as an ERROR output.
    assert "ERROR" in json.dumps(client.calls[1][1])


def test_search_provider_failure_is_data_not_crash():
    def raising_search(args):
        raise RuntimeError("Tavily: connection reset")
    registry = counting_registry(search=raising_search)
    client = ScriptedNativeClient([
        [fn_call("web_search", {"query": "LEGO"})],
        [submit(VALID_REPORT)],
    ])
    report = run_native(client, registry)
    assert report.executive_summary == "Summary."
    assert "ERROR" in json.dumps(client.calls[1][1])


def test_prose_only_turn_gets_reminder_not_parse():
    registry = counting_registry()
    client = ScriptedNativeClient([
        [msg("Here is my report as plain text, not a tool call.")],
        [submit(VALID_REPORT)],
    ])
    report = run_native(client, registry)
    assert report.executive_summary == "Summary."
    assert "submit_report" in json.dumps(client.calls[1][1])


def test_invalid_final_report_is_bounded():
    registry = counting_registry()
    bad = {"executive_summary": 123}  # wrong type, missing required fields
    client = ScriptedNativeClient([[submit(bad)]] * 3)
    with pytest.raises(AgentOutputError, match="did not finish within 3"):
        run_native(client, registry, max_iterations=3)
    assert len(client.calls) == 3  # bounded: no infinite retry


def test_native_tool_budget_exhaustion_propagates():
    def budget_cb(model, in_tokens, out_tokens, preflight=False):
        raise BudgetExhausted("budget exhausted")
    client = ScriptedNativeClient([[submit(VALID_REPORT)]])
    with pytest.raises(BudgetExhausted):
        run_native(client, cost_cb=budget_cb)


# ------------------------------------------------------- native provider fallback

class _NativeUsage:
    input_tokens = 100
    output_tokens = 50


class _NativeResp:
    def __init__(self, items):
        self.output = items
        self.usage = _NativeUsage()
        self.id = "resp-n"


class _NativeRuleSDK:
    """responses.create: rejects strict tool definitions, accepts the rest."""
    def __init__(self, fail_models=()):
        from types import SimpleNamespace
        self.calls = []
        self.fail_models = set(fail_models)
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] in self.fail_models:
            raise Exception("model does not exist")
        if any(t.get("strict") for t in kwargs["tools"]):
            raise Exception("400 schema rejected for strict tools")
        return _NativeResp([fn_call("web_search", {"query": "x"})])


def _native_provider(sdk, fallback=None):
    provider = object.__new__(OpenAIProvider)
    provider.client = sdk
    provider.fallback_model = fallback
    return provider


def test_native_strict_rejection_falls_back_to_non_strict():
    sdk = _NativeRuleSDK()
    provider = _native_provider(sdk)
    tools = [{"type": "function", "name": "web_search",
              "description": "search",
              "parameters": {"type": "object", "properties": {}},
              "strict": True}]
    items, _, _ = provider.create_tool_response(
        "sys", [{"role": "user", "content": "hi"}], tools, "gpt-5.4-mini")
    assert items[0]["name"] == "web_search"
    assert len(sdk.calls) == 2
    assert sdk.calls[0]["tools"][0]["strict"] is True
    assert "strict" not in sdk.calls[1]["tools"][0]


def test_native_model_not_found_tries_fallback_model():
    sdk = _NativeRuleSDK(fail_models={"gpt-5.4-mini"})
    provider = _native_provider(sdk, fallback="gpt-5.4-mini-fallback")
    tools = [{"type": "function", "name": "web_search", "description": "s",
              "parameters": {"type": "object", "properties": {}}}]
    items, _, _ = provider.create_tool_response(
        "sys", [{"role": "user", "content": "hi"}], tools, "gpt-5.4-mini")
    assert items[0]["name"] == "web_search"
    assert sdk.calls[-1]["model"] == "gpt-5.4-mini-fallback"


# ------------------------------------------------------- acceptance: mocked e2e

class DualFakeClient:
    """complete() for creator/evaluator/auditor (stub), native turns for
    the executor. This is the client shape the engine sees live."""
    supports_native_tools = True

    def __init__(self, behavior, turns):
        self.stub = StubProvider(behavior)
        self.native = ScriptedNativeClient(turns)

    def complete(self, system, user, schema, model):
        return self.stub.complete(system, user, schema, model)

    def create_tool_response(self, instructions, input_items, tools, model):
        return self.native.create_tool_response(instructions, input_items,
                                                tools, model)


def test_mocked_end_to_end_executor_search_to_valid_report(settings, store):
    """Acceptance: executor requests a search, it is dispatched, results
    are consumed, and the run reaches a schema-valid report -- with no
    concatenated-JSON failure anywhere in the path."""
    client = DualFakeClient(default_stub_behavior(), [
        [fn_call("web_search", {"query": "LEGO bulk auction"})],
        [fn_call("fetch_page", {"url": "https://example.com/stub"})],
        [submit(VALID_REPORT)],
    ])
    engine = Orchestrator(settings, store, client=client,
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    assert status["terminal_status"] == "COMPLETED_APPROVED"
    # Distinguish the layers: one validated tool executed and recorded...
    assert status["tool_calls"] >= 1
    # ...the search result reached the executor's next turn...
    turn2_input = json.dumps(client.native.calls[1][1])
    assert "Stub passage." in turn2_input
    # ...and a schema-valid final report artifact exists.
    assert os.path.exists(os.path.join(status["artifact_dir"], "final_report.md"))
    # The native tool definitions offered a submit_report function.
    offered = [t["name"] for t in client.native.calls[0][2]]
    assert "submit_report" in offered and "web_search" in offered
