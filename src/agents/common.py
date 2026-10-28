"""Shared agent-call helper: structured output, validation, one repair retry.

A malformed model response is never silently accepted and never parsed as
Markdown. On a validation failure the model gets exactly one repair attempt
with the validation error quoted; a non-JSON response (e.g. concatenated
JSON objects, which json.loads rejects) gets exactly one repair attempt
with the same discipline -- previously it failed the run immediately with
zero repair attempts, which is how the second live failure became fatal.
If the repair also fails, the orchestrator sees an AgentOutputError and
fails the run safely instead of proceeding on bad data.
"""
from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..llm.provider import LLMClient, LLMError

T = TypeVar("T", bound=BaseModel)


class AgentOutputError(Exception):
    pass


# Provider errors that are transient (timeout, rate limit, temporary
# overload). These are NOT agent-output failures: the orchestrator must be
# able to distinguish them so a run can be resumed after the condition
# clears instead of failing permanently.
TRANSIENT_MARKERS = ("timeout", "timed out", "rate limit", "rate_limit",
                     "429", "502", "503", "overloaded",
                     "temporarily unavailable", "try again later")


def is_transient_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


def call_agent(client: LLMClient, model: str, system: str, user: str,
               schema_model: Type[T], cost_cb=None,
               estimated_output_tokens: int = 1500) -> T:
    schema = schema_model.model_json_schema()
    message = user
    account_here = not getattr(client, "manages_costs", False)
    for attempt in range(2):
        if cost_cb and account_here:
            cost_cb(model, max(1, (len(system) + len(message)) // 4),
                    estimated_output_tokens, preflight=True)
        try:
            payload, in_tokens, out_tokens = client.complete(system, message, schema, model)
        except LLMError as exc:
            if is_transient_message(str(exc)):
                raise
            if attempt or "non-json" not in str(exc).lower():
                raise AgentOutputError(str(exc)) from exc
            message = (user + "\nYour previous response was not a single valid JSON "
                       "document. Return ONLY one JSON document matching the required schema.")
            continue
        if cost_cb and account_here:
            cost_cb(model, in_tokens, out_tokens)
        try:
            return schema_model.model_validate(payload)
        except ValidationError as exc:
            if attempt:
                raise AgentOutputError("agent output failed validation twice") from exc
            # Do not echo invalid model content or secrets from validation errors.
            errors = [{"loc": e["loc"], "type": e["type"]} for e in exc.errors()]
            message = (user + "\nYour previous response failed schema validation: "
                       + str(errors) + "\nReturn ONLY a corrected JSON document.")
    raise AgentOutputError("agent output failed after one repair attempt")
