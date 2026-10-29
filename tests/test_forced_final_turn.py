"""Step 3 tests: forced final turn for the native executor (F-A2-1),
plus the transcript-note wording fix (F-A2-2 wording only).

Forced tool_choice shape, confirmed from the installed SDK types
(openai/types/responses/tool_choice_function_param.py,
ToolChoiceFunctionParam: {"name": <str>, "type": "function"}):
{"type": "function", "name": "submit_report"}.
"""

import json

import pytest

from src.agents.common import AgentOutputError
from src.agents.executor import SUBMIT_REPORT_NAME, run_execution_native
from src.llm.provider import StubProvider, default_stub_behavior
from src.orchestration.engine import Orchestrator
from src.storage.database import Store
from src.tools.base import ToolRegistry
from tests.conftest import fake_fetch, fake_registry

VALID_REPORT = {
    "executive_summary": "Summary.",
    "findings": [],
    "claims": [],
    "sources": [],
    "limitations": [],
    "unresolved_dependencies": [],
}


def _msg(text):
    return {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}


def _submit(report):
    return {"type": "function_call", "call_id": "c-submit",
            "name": SUBMIT_REPORT_NAME,
            "arguments": json.dumps(report)}


class ObedientClient:
    """Prose normally; obeys a forced tool_choice with a valid report."""
    supports_native_tools = True

    def __init__(self):
        self.choices = []

    def create_tool_response(self, instructions, input_items, tools, model,
                             tool_choice="auto"):
        self.choices.append(tool_choice)
        if isinstance(tool_choice, dict):
            return [_submit(VALID_REPORT)], 100, 50
        return [_msg("still thinking")], 100, 50


class StubbornClient:
    """Ignores forcing entirely: prose on every turn."""
    supports_native_tools = True

    def __init__(self):
        self.choices = []

    def create_tool_response(self, instructions, input_items, tools, model,
                             tool_choice="auto"):
        self.choices.append(tool_choice)
        return [_msg("still thinking")], 100, 50


class OldShapeClient:
    """Pre-Step-3 4-argument shape: must keep working untouched."""
    supports_native_tools = True

    def __init__(self):
        self.calls = 0

    def create_tool_response(self, instructions, input_items, tools, model):
        self.calls += 1
        return [_msg("still thinking")], 100, 50


def _run(client, max_iterations=3):
    return run_execution_native(client, "gpt-5.4-mini", ["SPEC"],
                                ToolRegistry(),
                                max_iterations=max_iterations)


def test_forced_turn_yields_report_and_carries_forced_choice():
    from functools import wraps

    client = ObedientClient()
    original = client.create_tool_response
    invocations = []

    @wraps(original)
    def recorded(*args, **kwargs):
        invocations.append((args, kwargs))
        return original(*args, **kwargs)

    client.create_tool_response = recorded
    report = _run(client, max_iterations=3)
    assert report.executive_summary == "Summary."
    assert client.choices[0] == "auto"
    assert client.choices[1] == "auto"
    assert client.choices[2] == {"type": "function",
                                 "name": SUBMIT_REPORT_NAME}
    assert len(invocations) == 3
    assert all(len(args) == 4 for args, _ in invocations)
    assert invocations[0][1] == invocations[1][1] == {}
    assert invocations[2][1] == {"tool_choice": client.choices[2]}


def test_stubborn_after_forcing_still_fails_exactly_as_before():
    client = StubbornClient()
    with pytest.raises(AgentOutputError, match="did not finish within 3"):
        _run(client, max_iterations=3)
    assert client.choices[2] == {"type": "function",
                                 "name": SUBMIT_REPORT_NAME}


def test_old_shape_client_unaffected_at_cap():
    client = OldShapeClient()
    with pytest.raises(AgentOutputError, match="did not finish within 3"):
        _run(client, max_iterations=3)
    assert client.calls == 3


def test_engine_stubborn_after_forcing_is_failed_execution(settings, store):
    """Engine-level (b): stubborn prose after forcing ends FAILED_EXECUTION."""
    class EngineClient(StubProvider):
        supports_native_tools = True

        def __init__(self, behavior):
            super().__init__(behavior)
            self.native = StubbornClient()

        def create_tool_response(self, instructions, input_items, tools,
                                 model, tool_choice="auto"):
            return self.native.create_tool_response(
                instructions, input_items, tools, model,
                tool_choice=tool_choice)

    engine = Orchestrator(settings, store,
                          client=EngineClient(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("probe objective")
    status = engine.run(pid)
    assert status["state"] == "FAILED"
    assert status["terminal_status"] == "FAILED_EXECUTION"


def test_truncation_note_no_longer_claims_completeness():
    from src.agents.executor import _capped_items
    spec = {"role": "user", "content": "SPEC"}
    rounds = [[{"type": "function_call_output", "call_id": "c1",
                "output": "x" * 200}]]
    capped = _capped_items(spec, rounds, max_chars=50)
    note = json.dumps(capped)
    assert "complete" not in note
    assert "may have been dropped" in note


def test_C01_positional_only_choice_is_forced_positionally():
    class PositionalOnlyClient:
        def __init__(self):
            self.choices = []

        def create_tool_response(self, instructions, input_items, tools, model,
                                 tool_choice="auto", /):
            self.choices.append(tool_choice)
            if isinstance(tool_choice, dict):
                return [_submit(VALID_REPORT)], 100, 50
            return [_msg("still thinking")], 100, 50

    client = PositionalOnlyClient()
    try:
        report = _run(client, max_iterations=1)
    finally:
        # In the red state argument binding fails before this client runs.
        print("client invocations:", len(client.choices))
    assert report.executive_summary == "Summary."
    assert client.choices == [{"type": "function", "name": SUBMIT_REPORT_NAME}]


@pytest.mark.parametrize("style", ["keyword_only", "kwargs"])
def test_C03_C05_keyword_capability_uses_keyword(style):
    from functools import wraps

    invocations = []
    if style == "keyword_only":
        def method(self, instructions, input_items, tools, model, *,
                   tool_choice="auto"):
            return [_submit(VALID_REPORT)], 100, 50
    else:
        def method(self, instructions, input_items, tools, model, **kwargs):
            return [_submit(VALID_REPORT)], 100, 50

    @wraps(method)
    def recorded(self, *args, **kwargs):
        invocations.append((args, kwargs))
        return method(self, *args, **kwargs)

    class Client:
        create_tool_response = recorded

    assert _run(Client(), max_iterations=1).executive_summary == "Summary."
    assert len(invocations) == 1
    assert len(invocations[0][0]) == 4
    assert invocations[0][1] == {
        "tool_choice": {"type": "function", "name": SUBMIT_REPORT_NAME}}


@pytest.mark.parametrize("error", [TypeError("internal provider error"),
                                   RuntimeError("internal provider error")])
def test_C06_C07_provider_errors_never_retry(error):
    class Client:
        calls = 0

        def create_tool_response(self, instructions, input_items, tools, model,
                                 tool_choice="auto"):
            self.calls += 1
            raise error

    client = Client()
    with pytest.raises(type(error)) as caught:
        _run(client, max_iterations=1)
    assert caught.value is error
    assert client.calls == 1


def test_C10_malformed_forced_report_keeps_validation():
    class Client:
        calls = 0

        def create_tool_response(self, instructions, input_items, tools, model,
                                 tool_choice="auto"):
            self.calls += 1
            assert tool_choice == {"type": "function", "name": SUBMIT_REPORT_NAME}
            return [_submit({"executive_summary": []})], 100, 50

    client = Client()
    with pytest.raises(AgentOutputError, match="did not finish within 1"):
        _run(client, max_iterations=1)
    assert client.calls == 1


def test_positional_choice_preserves_intervening_default():
    default = object()

    class Client:
        def __init__(self):
            self.calls = []

        def create_tool_response(self, instructions, input_items, tools, model,
                                 padding=default, tool_choice="auto", /):
            self.calls.append((padding, tool_choice))
            if isinstance(tool_choice, dict):
                return [_submit(VALID_REPORT)], 100, 50
            return [_msg("still thinking")], 100, 50

    client = Client()
    assert _run(client, max_iterations=2).executive_summary == "Summary."
    assert len(client.calls) == 2
    assert all(padding is default for padding, _ in client.calls)
    assert client.calls[0][1] == "auto"
    assert client.calls[1][1] == {"type": "function", "name": SUBMIT_REPORT_NAME}


def test_required_intervening_argument_is_not_guessed():
    class Client:
        calls = 0

        def create_tool_response(self, instructions, input_items, tools, model,
                                 required_padding, tool_choice="auto", /):
            self.calls += 1
            return [_submit(VALID_REPORT)], 100, 50

    client = Client()
    with pytest.raises(TypeError):
        _run(client, max_iterations=1)
    assert client.calls == 0


def test_uninspectable_signature_keeps_four_argument_call():
    class Client:
        calls = 0

        def create_tool_response(self, instructions, input_items, tools, model):
            self.calls += 1
            return [_submit(VALID_REPORT)], 100, 50

    Client.create_tool_response.__signature__ = "uninspectable"
    client = Client()
    assert _run(client, max_iterations=1).executive_summary == "Summary."
    assert client.calls == 1


def test_choice_name_already_filled_by_legacy_argument_is_not_overridden():
    class Client:
        def __init__(self):
            self.models = []

        def create_tool_response(self, instructions, input_items, tools,
                                 tool_choice):
            self.models.append(tool_choice)  # fourth legacy argument is the model
            return [_submit(VALID_REPORT)], 100, 50

    client = Client()
    assert _run(client, max_iterations=1).executive_summary == "Summary."
    assert client.models == ["gpt-5.4-mini"]
