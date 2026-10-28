"""Agent 1 -- Prompt Creator.

Transforms the user's objective into a rigorous execution specification.
It must preserve the original objective: it may clarify scope and method,
but it must not silently introduce new business requirements.
"""
from __future__ import annotations

from typing import Optional

from ..llm.provider import LLMClient
from ..models.contracts import PromptSpec
from .common import call_agent

SYSTEM = """You are the Prompt Creator in a four-agent research system.
Transform the user's objective into a rigorous, actionable execution
specification for a research executor. Identify the actual research
question, scope, constraints, evidence requirements, methodology, tools,
deliverables, success criteria, failure conditions and unresolved
assumptions. Keep the prompt as short as the complexity allows.
CRITICAL: preserve the user's original objective exactly in spirit. Do not
add new business requirements, products, or goals the user did not ask for.
Return ONLY a JSON document matching the required schema."""


def create_prompt(client: LLMClient, model: str, objective: str,
                  previous: Optional[PromptSpec] = None,
                  required_revisions: Optional[list[str]] = None,
                  cost_cb=None, estimated_output_tokens: int = 1500) -> PromptSpec:
    user = f"USER OBJECTIVE:\n{objective}"
    if previous is not None:
        user += ("\n\nPREVIOUS PROMPT (revision "
                 f"{previous.revision_number}):\n{previous.execution_prompt}"
                 "\n\nREQUIRED REVISIONS (address every one; do not drop "
                 "anything that was previously accepted):\n"
                 + "\n".join(f"- {r}" for r in (required_revisions or [])))
    spec = call_agent(client, model, SYSTEM, user, PromptSpec, cost_cb=cost_cb,
                      estimated_output_tokens=estimated_output_tokens)
    if previous is not None:
        spec.revision_number = previous.revision_number + 1
    return spec
