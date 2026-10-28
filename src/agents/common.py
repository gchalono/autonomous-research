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
    # Pre-call gate with a cost ESTIMATE (input tokens approximated from
    # text length + assumed output tokens), so the orchestrator can refuse
    # a call that would breach the budget before any tokens are spent.
    # The preflight call never records spend; only completed calls do.
    if cost_cb:
        est_in = max(1, len(system) + len(user)) // 4
        cost_cb(model, est_in, estimated_output_tokens, preflight=True)
    try:
        payload, in_tokens, out_tokens = client.complete(system, user, schema, model)
    except LLMError as exc:
        if is_transient_message(str(exc)):
            raise  # transient: let the orchestrator resume later, not fail
        if "non-json" not in str(exc).lower():
            raise AgentOutputError(str(exc)) from exc
        # One repair attempt for malformed (non-JSON) output, mirroring
        # the validation repair below. No splitting, regex, or multi-
        # object parsing: the model must return one single document.
        repair_user = (user + "\n\nYour previous response was not a single valid "
                       "JSON document. Return ONLY one JSON document matching the "
                       "required schema. Do not emit multiple JSON objects, "
                       "bare tool-call objects, or any text outside the document.")
        if cost_cb:
            est_in = max(1, len(system) + len(repair_user)) // 4
            cost_cb(model, est_in, estimated_output_tokens, preflight=True)
        try:
            payload, in_tokens, out_tokens = client.complete(system, repair_user, schema, model)
        except LLMError as exc2:
            if is_transient_message(str(exc2)):
                raise
            raise AgentOutputError(str(exc2)) from exc2
    if cost_cb:
        cost_cb(model, in_tokens, out_tokens)
    try:
        return schema_model.model_validate(payload)
    except ValidationError as exc:
        # One repair attempt: show the model its own validation errors.
        repair_user = (user + "\n\nYour previous response failed schema validation:\n"
                       + str(exc) + "\nReturn ONLY a corrected JSON document.")
        if cost_cb:
            est_in = max(1, len(system) + len(repair_user)) // 4
            cost_cb(model, est_in, estimated_output_tokens, preflight=True)
        try:
            payload, in_tokens, out_tokens = client.complete(system, repair_user, schema, model)
        except LLMError as exc2:
            if is_transient_message(str(exc2)):
                raise
            raise AgentOutputError(str(exc2)) from exc2
        if cost_cb:
            cost_cb(model, in_tokens, out_tokens)
        try:
            return schema_model.model_validate(payload)
        except ValidationError as exc2:
            raise AgentOutputError(f"agent output failed validation twice: {exc2}") from exc2
