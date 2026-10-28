"""LLM provider abstraction.

``LLMClient.complete`` returns (parsed_json_dict, input_tokens, output_tokens)
and raises ``LLMError`` on failure. The orchestrator -- not the provider --
owns retries, budgets and validation: a provider that returns malformed JSON
is a failed call, and the agent layer retries with a repair prompt.

Providers:
- OpenAIProvider: OpenAI Responses API with a JSON-schema response format,
  so the model must return a document matching the agent's Pydantic schema.
- StubProvider: deterministic canned outputs for tests and for offline demos.
  It is NOT a research engine: it returns fixed, clearly-labelled content
  and must never be presented as genuine research.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional


class LLMError(Exception):
    pass


class ProviderControlFlowError(Exception):
    """Software budget/cancellation gates; never reinterpret as API failures."""


def make_strict_schema(schema: dict) -> dict:
    """Rewrite a Pydantic JSON Schema into OpenAI strict-mode shape.

    Strict mode rejects schemas that fail loudly (400) when ANY of these
    hold: a property is missing from ``required``; an object lacks
    ``additionalProperties: false``; a ``default`` keyword is present.
    Pydantic emits all three violations by default (fields with defaults
    are not required; no additionalProperties flag; ``default: null`` on
    Optional fields), so a raw ``model_json_schema()`` can never be sent
    with ``strict: true``. This function also inlines ``$ref``/``$defs``
    references, since our schemas are non-recursive and inlining removes
    any doubt about reference support.
    """
    import copy

    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                # Pydantic often emits {"$ref": ..., "default": ...} siblings;
                # resolve the reference and drop the default (strict mode
                # rejects it); keep any other sibling metadata.
                ref = node["$ref"]
                assert ref.startswith("#/$defs/"), f"unsupported ref {ref}"
                target = resolve(defs[ref.split("/")[-1]])
                extras = {k: resolve(v) for k, v in node.items()
                          if k not in ("$ref", "default")}
                if isinstance(target, dict):
                    return {**target, **extras}
                return target
            out = {}
            for key, value in node.items():
                if key == "default":
                    continue  # strict mode rejects default keywords
                out[key] = resolve(value)
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = sorted(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


class LLMClient:
    # Native Responses API function calling (executor only). Clients that
    # do not implement create_tool_response leave this False and the
    # executor falls back to the structured-JSON step loop.
    supports_native_tools = False

    def complete(self, system: str, user: str, schema: dict, model: str) -> tuple[dict, int, int]:
        raise NotImplementedError

    def create_tool_response(self, instructions: str, input_items: list,
                             tools: list, model: str):
        """One native tool-calling turn. Returns (output_items, in_tokens,
        out_tokens); output items are plain dicts round-trippable as the
        next turn's input (reasoning items included verbatim)."""
        raise NotImplementedError(
            "this client does not support native tool calling")


def _strip_strict(tools: list) -> list:
    """Copy of function definitions with the strict flag removed (the
    non-strict fallback for tool calling)."""
    import copy
    stripped = copy.deepcopy(tools)
    for tool in stripped:
        tool.pop("strict", None)
    return stripped


def _response_items(resp) -> list[dict]:
    """Output items as plain dicts, round-trippable as the next turn's
    input. Reasoning items are preserved verbatim: dropping them would
    corrupt continuation for reasoning models."""
    items = []
    for item in getattr(resp, "output", []) or []:
        if isinstance(item, dict):
            items.append(item)
        elif callable(getattr(item, "model_dump", None)):
            items.append(item.model_dump())
        else:
            raise LLMError(f"unsupported Responses API output item: {type(item)}")
    return items


def _is_model_not_found(message: str) -> bool:
    lowered = message.lower()
    return "model" in lowered and (
        "not found" in lowered or "does not exist" in lowered
        or "unknown model" in lowered)


def _is_schema_rejection(message: str) -> bool:
    lowered = message.lower()
    return "schema" in lowered or "response_format" in lowered or "text.format" in lowered


# The Responses API requires input messages to contain the word "json" in
# some form when text.format.type is "json_object" (HTTP 400 otherwise).
# Agent SYSTEM prompts say "JSON", but the API checks the INPUT messages,
# and agent user messages (e.g. "USER OBJECTIVE: ...") contain no such
# word -- which is exactly how the first live run failed: strict mode was
# rejected, the fallback fired, and the fallback 400'd for lack of the
# word. So every json_object request gets this suffix appended to its
# input. Strict-mode requests are untouched.
JSON_MODE_SUFFIX = ("\n\nReturn your response as valid json only, matching "
                    "the requested schema.")


class OpenAIProvider(LLMClient):
    """OpenAI Responses API, structured-output mode."""

    manages_costs = True

    def __init__(self, api_key: Optional[str] = None, timeout_s: int = 120,
                 fallback_model: Optional[str] = None, max_output_tokens: int = 6000):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMError("openai package is not installed; run: pip install openai") from exc
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=key, timeout=timeout_s, max_retries=0)
        self.max_output_tokens = max_output_tokens
        self.request_cost_cb = None
        self.fallback_model = fallback_model
        # Models that actually executed (fallback included when used).
        self.models_used: set[str] = set()
        self.last_response_id: Optional[str] = None

    def complete(self, system: str, user: str, schema: dict, model: str) -> tuple[dict, int, int]:
        strict_schema = make_strict_schema(schema)
        strict_format = {
            "type": "json_schema",
            "name": schema.get("title", "AgentOutput"),
            "schema": strict_schema,
            "strict": True,
        }
        candidates = [model]
        fallback = getattr(self, "fallback_model", None)
        if fallback and fallback != model:
            candidates.append(fallback)
        last_error: Exception | None = None
        strict_error: Exception | None = None
        for candidate in candidates:
            for fmt, is_strict in ((strict_format, True), ({"type": "json_object"}, False)):
                # json_object mode REQUIRES the word "json" in the input
                # messages; strict mode does not, so only the fallback
                # input gets the suffix (strict stays the preferred path).
                effective_input = user if is_strict else (
                    user + JSON_MODE_SUFFIX + "\nRequired JSON schema:\n" + json.dumps(schema))
                try:
                    resp = self._create(system, effective_input, candidate, fmt)
                except Exception as exc:
                    if isinstance(exc, ProviderControlFlowError):
                        raise
                    last_error = exc
                    message = str(exc)
                    if (is_strict and getattr(exc, 'status_code', 400) == 400
                            and _is_schema_rejection(message)):
                        # Preserve the strict rejection: if the fallback
                        # also fails, the operator needs to see WHY strict
                        # failed, not just the fallback's error.
                        strict_error = exc
                        continue  # plain JSON mode on the same model
                    if getattr(exc, 'status_code', 400) in (400, 404) and _is_model_not_found(message):
                        break  # next candidate model
                    raise LLMError(
                        f"OpenAI Responses API call failed: {exc}"
                        + (f"; strict-mode error was: {strict_error}"
                           if strict_error else "")) from exc
                # Success: record exactly which model executed.
                used = getattr(self, "models_used", None)
                if used is None:
                    used = self.models_used = set()
                used.add(candidate)
                self.last_response_id = getattr(resp, "id", None)
                text = resp.output_text
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LLMError(
                        "model returned non-JSON output") from exc
                usage = getattr(resp, "usage", None)
                in_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                return payload, in_tokens, out_tokens
        raise LLMError(
            "OpenAI Responses API call failed (all models/formats exhausted): "
            f"last error: {last_error}"
            + (f"; strict-mode error was: {strict_error}" if strict_error else ""))

    def _create(self, system: str, user: str, model: str, fmt: dict):
        return self._request(
            model=model,
            instructions=system,
            input=user,
            text={"format": fmt},
        )

    def _request(self, **kwargs):
        """Gate each actual request (including fallbacks) and account before parsing.

        SDK retries are disabled: a timeout may still have been billed remotely,
        so it must never silently repeat a paid operation.
        """
        cb = getattr(self, "request_cost_cb", None)
        limit = getattr(self, "max_output_tokens", 6000)
        if cb:
            cb(kwargs["model"], max(1, len(json.dumps(kwargs)) // 4), limit,
               preflight=True)
        resp = self.client.responses.create(**kwargs, max_output_tokens=limit)
        self.last_response_id = getattr(resp, "id", None)
        self.models_used = getattr(self, "models_used", set()) | {kwargs["model"]}
        usage = getattr(resp, "usage", None)
        if usage is None:
            self.last_usage = None
        elif callable(getattr(usage, 'model_dump', None)):
            self.last_usage = usage.model_dump(mode='json')
        else:
            self.last_usage = {name: getattr(usage, name) for name in
                               ('input_tokens', 'output_tokens', 'total_tokens')
                               if hasattr(usage, name)}
        if cb:
            cb(kwargs["model"], int(getattr(usage, "input_tokens", 0) or 0),
               int(getattr(usage, "output_tokens", 0) or 0))
        if getattr(resp, "status", "completed") not in (None, "completed"):
            raise LLMError("OpenAI response incomplete; increase AR_MAX_OUTPUT_TOKENS "
                           "within the authorized budget")
        return resp

    # -- native function calling (executor) -------------------------------
    supports_native_tools = True

    def create_tool_response(self, instructions: str, input_items: list,
                             tools: list, model: str):
        """Native Responses API function calling, mirroring complete()'s
        fallback discipline: strict tool definitions first, non-strict on
        a schema rejection, next candidate model on model-not-found.
        Tool calls arrive as discrete API items, never as model-written
        JSON text, so the concatenated-JSON failure class cannot occur
        on this path at all."""
        candidates = [model]
        fallback = getattr(self, "fallback_model", None)
        if fallback and fallback != model:
            candidates.append(fallback)
        last_error: Exception | None = None
        strict_error: Exception | None = None
        for candidate in candidates:
            for tool_defs, is_strict in ((tools, True), (_strip_strict(tools), False)):
                try:
                    resp = self._request(
                        model=candidate,
                        instructions=instructions,
                        input=input_items,
                        tools=tool_defs,
                        tool_choice="auto",
                    )
                except Exception as exc:
                    if isinstance(exc, ProviderControlFlowError):
                        raise
                    last_error = exc
                    message = str(exc)
                    if (is_strict and getattr(exc, 'status_code', 400) == 400
                            and _is_schema_rejection(message)):
                        strict_error = exc
                        continue  # same model, non-strict tool definitions
                    if getattr(exc, 'status_code', 400) in (400, 404) and _is_model_not_found(message):
                        break  # next candidate model
                    raise LLMError(
                        f"OpenAI Responses API tool call failed: {exc}"
                        + (f"; strict-mode error was: {strict_error}"
                           if strict_error else "")) from exc
                used = getattr(self, "models_used", None)
                if used is None:
                    used = self.models_used = set()
                used.add(candidate)
                self.last_response_id = getattr(resp, "id", None)
                usage = getattr(resp, "usage", None)
                in_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                return _response_items(resp), in_tokens, out_tokens
        raise LLMError(
            "OpenAI Responses API tool call failed (all models/formats "
            f"exhausted): last error: {last_error}"
            + (f"; strict-mode error was: {strict_error}" if strict_error else ""))


class StubProvider(LLMClient):
    """Deterministic provider for tests and offline demos.

    ``behavior`` maps a role keyword (matched against the system prompt) to
    either a dict (returned verbatim) or a callable returning a dict. Each
    call is counted per role, so tests can assert idempotent resume
    (no extra calls on the second run).
    """

    def __init__(self, behavior: Optional[dict[str, Any]] = None):
        self.behavior = behavior or {}
        self.calls: dict[str, int] = {}

    def _role(self, system: str) -> str:
        # Match full role phrases, in an order that cannot be confused by
        # one agent's prompt mentioning another agent ("research executor"
        # appears in the creator's prompt, for example).
        lowered = system.lower()
        for phrase, role in (
            ("prompt creator", "creator"),
            ("prompt evaluator", "evaluator"),
            ("research executor", "executor"),
            ("execution auditor", "auditor"),
        ):
            if phrase in lowered:
                return role
        return "default"

    def complete(self, system: str, user: str, schema: dict, model: str) -> tuple[dict, int, int]:
        role = self._role(system)
        self.calls[role] = self.calls.get(role, 0) + 1
        handler = self.behavior.get(role)
        if handler is None:
            raise LLMError(f"stub has no behavior for role {role!r}")
        payload = handler(self.calls[role], user) if callable(handler) else handler
        return payload, 100, 50


def default_stub_behavior() -> dict[str, Any]:
    """A well-behaved stub: approve prompt, produce a sourced report, approve audit."""
    prompt = {
        "objective": "stub objective",
        "execution_prompt": "Research the objective using web_search and fetch_page; "
                            "cite every material claim with a retrieved source.",
        "scope": ["stub scope"],
        "constraints": ["cite retrieved sources only"],
        "research_requirements": ["use web_search", "use fetch_page"],
        "acceptance_criteria": ["report cites at least one retrieved source"],
        "assumptions": [],
        "open_questions": [],
        "revision_number": 1,
    }
    evaluation = {
        "decision": "APPROVE",
        "critical_issues": [], "major_issues": [], "minor_issues": [],
        "required_revisions": [],
        "accepted_criteria": ["report cites at least one retrieved source"],
        "rationale": "Prompt is aligned, feasible and measurable.",
    }
    report = {
        "executive_summary": "Stub research summary.",
        "findings": [{"id": "F1", "title": "Stub finding",
                      "text": "Stub finding text.", "claim_ids": ["C1"]}],
        "claims": [{"id": "C1", "text": "Stub claim.", "classification": "VERIFIED",
                    "source_ids": ["S1"]}],
        "sources": [{"id": "S1", "url": "https://example.com/stub",
                    "title": "Stub source", "retrieved_at": "2026-01-01T00:00:00Z",
                    "passage": "Stub passage.", "verification_status": "UNCHECKED"}],
        "limitations": [],
        "unresolved_dependencies": [],
    }
    audit = {
        "decision": "APPROVE", "issues": [],
        "rationale": "Report satisfies the acceptance criteria.",
        "verified_sources": [], "unverified_sources": [],
    }

    def executor_step(call_no: int, user: str) -> dict:
        # First turn: do one search, then finish. The tool loop feeds the
        # tool result back in the next user message; the stub finishes when
        # it sees a tool result marker.
        if "TOOL RESULT [fetch_page]" in user:
            return {"tool_calls": [], "done": True, "report": report}
        if "TOOL RESULT [web_search]" in user:
            return {"tool_calls": [{"tool": "fetch_page", "arguments": {
                "url": "https://example.com/stub"}}], "done": False, "report": None}
        return {"tool_calls": [{"tool": "web_search", "arguments": {"query": "stub query"}}],
                "done": False, "report": None}

    return {
        "creator": prompt,
        "evaluator": evaluation,
        "executor": executor_step,
        "auditor": audit,
    }
