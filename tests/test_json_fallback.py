"""Regression tests for the live HTTP 400: json_object mode requires the
word "json" in the input messages.

The fake client below enforces the SAME rule the real Responses API
enforces, so these tests fail against the pre-fix implementation (which
sent the user message unchanged in json_object mode) and pass with the
fix (which appends an explicit json instruction to fallback inputs).
"""
from tests.conftest import ProtocolOnlyGuard

import pytest

from src.agents.common import AgentOutputError, call_agent
from src.llm.provider import LLMError, OpenAIProvider
from src.models.contracts import PromptEvaluation

EXACT_400 = ("Error code: 400 - Response input messages must contain the "
             "word 'json' in some form to use 'text.format' of type "
             "'json_object'.")


class _Usage:
    input_tokens = 100
    output_tokens = 50


class _Resp:
    def __init__(self, text):
        self.output_text = text
        self.usage = _Usage()
        self.id = "resp-test"


class _RuleResponses:
    """Mimics the Responses API's json_object rule exactly."""

    def __init__(self, strict_error=None, json_payload='{"decision": "APPROVE"}',
                 json_error=None):
        self.calls = []  # (model, format_type, input)
        self.strict_error = strict_error
        self.json_payload = json_payload
        self.json_error = json_error

    def create(self, **kwargs):
        fmt = kwargs["text"]["format"]
        ftype = fmt["type"]
        self.calls.append((kwargs["model"], ftype, kwargs["input"]))
        if ftype == "json_schema":
            if self.strict_error is not None:
                raise Exception(self.strict_error)
            return _Resp(self.json_payload)
        # json_object: the API rule.
        if "json" not in kwargs["input"].lower():
            raise Exception(EXACT_400)
        if self.json_error is not None:
            raise Exception(self.json_error)
        return _Resp(self.json_payload)


class _RuleClient:
    def __init__(self, **kwargs):
        self.responses = _RuleResponses(**kwargs)


def _provider(**kwargs):
    provider = object.__new__(OpenAIProvider)
    ProtocolOnlyGuard.attach(provider)
    provider.client = _RuleClient(**kwargs)
    return provider


def _schema():
    return PromptEvaluation.model_json_schema()


def test_old_style_request_reproduces_exact_400():
    """The pre-fix request shape (raw user message, json_object mode) is
    rejected by the API rule with the exact reported error."""
    provider = _provider()
    with pytest.raises(Exception, match="must contain the word 'json'"):
        provider._create("You are the Prompt Evaluator.", "USER OBJECTIVE: x",
                         "gpt-5.4-mini", {"type": "json_object"})


def test_fallback_appends_json_word_and_succeeds():
    provider = _provider(strict_error="400 schema rejected")
    payload, _, _ = provider.complete(
        "You are the Prompt Evaluator.", "USER OBJECTIVE: x", _schema(),
        "gpt-5.4-mini")
    assert payload["decision"] == "APPROVE"
    calls = provider.client.responses.calls
    assert calls[0][1] == "json_schema"
    assert calls[0][2] == "USER OBJECTIVE: x"  # strict input untouched
    assert calls[1][1] == "json_object"
    assert "json" in calls[1][2].lower()  # fallback input carries the word


def test_strict_success_uses_no_suffix():
    provider = _provider()
    payload, _, _ = provider.complete(
        "You are the Prompt Evaluator.", "USER OBJECTIVE: x", _schema(),
        "gpt-5.4-mini")
    assert payload["decision"] == "APPROVE"
    calls = provider.client.responses.calls
    assert len(calls) == 1
    assert calls[0][1] == "json_schema"
    assert calls[0][2] == "USER OBJECTIVE: x"


def test_fallback_still_validates_against_contract():
    """Fallback success does not bypass Pydantic validation: an invalid
    enum value fails validation twice and raises AgentOutputError."""
    provider = _provider(strict_error="400 schema rejected",
                         json_payload='{"decision": "NOPE"}')
    with pytest.raises(AgentOutputError, match="failed validation twice"):
        call_agent(provider, "gpt-5.4-mini", "You are the Prompt Evaluator.",
                   "USER OBJECTIVE: x", PromptEvaluation)
    # Both the initial and the repair call went through the json fallback.
    formats = [c[1] for c in provider.client.responses.calls]
    assert formats == ["json_schema", "json_object", "json_schema", "json_object"]


def test_malformed_json_in_fallback_raises():
    provider = _provider(strict_error="400 schema rejected",
                         json_payload="this is not json")
    with pytest.raises(LLMError, match="non-JSON"):
        provider.complete("system", "USER OBJECTIVE: x", _schema(), "gpt-5.4-mini")


def test_api_error_propagation_not_masked():
    """A non-schema API error (e.g. bad key) propagates immediately with
    no fallback attempt masking it."""
    provider = _provider(strict_error="Error code: 401 - Incorrect API key")
    with pytest.raises(LLMError, match="401"):
        provider.complete("system", "USER OBJECTIVE: x", _schema(), "gpt-5.4-mini")
    assert len(provider.client.responses.calls) == 1


def test_strict_error_preserved_when_fallback_also_fails():
    provider = _provider(strict_error="schema rejected: additionalProperties",
                         json_error="500 internal server error")
    with pytest.raises(LLMError) as excinfo:
        provider.complete("system", "USER OBJECTIVE: x", _schema(), "gpt-5.4-mini")
    assert "additionalProperties" in str(excinfo.value)
    assert "500" in str(excinfo.value)
