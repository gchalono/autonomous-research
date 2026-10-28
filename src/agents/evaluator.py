"""Agent 2 -- Prompt Evaluator.

Independently assesses the creator's prompt against ten criteria. Only
specific, named defects may demand a revision; stylistic preferences alone
must not. A long prompt is not automatically a good prompt.
"""
from __future__ import annotations

from ..llm.provider import LLMClient
from ..models.contracts import PromptEvaluation, PromptSpec
from .common import call_agent

SYSTEM = """You are the Prompt Evaluator in a four-agent research system.
Independently assess the execution prompt below against: (1) alignment with
the user's objective, (2) clarity, (3) completeness, (4) feasibility,
(5) methodological rigor, (6) evidence requirements, (7) tool availability,
(8) hallucination risk, (9) unnecessary complexity, (10) measurable
acceptance criteria.
Decide APPROVE, REVISE, or BLOCKED. REVISE only for specific defects, each
named in required_revisions with the exact fix needed; never demand a
revision for style alone. BLOCKED only if the prompt cannot be executed
safely or at all. Do not approve a prompt merely because it is long or
detailed. Return ONLY a JSON document matching the required schema."""


def evaluate_prompt(client: LLMClient, model: str, objective: str,
                    spec: PromptSpec, cost_cb=None,
                    estimated_output_tokens: int = 1500) -> PromptEvaluation:
    user = (f"USER OBJECTIVE:\n{objective}\n\n"
            f"EXECUTION PROMPT (revision {spec.revision_number}):\n{spec.execution_prompt}\n\n"
            f"SCOPE: {spec.scope}\nCONSTRAINTS: {spec.constraints}\n"
            f"RESEARCH REQUIREMENTS: {spec.research_requirements}\n"
            f"ACCEPTANCE CRITERIA: {spec.acceptance_criteria}\n"
            f"ASSUMPTIONS: {spec.assumptions}\nOPEN QUESTIONS: {spec.open_questions}")
    return call_agent(client, model, SYSTEM, user, PromptEvaluation, cost_cb=cost_cb,
                      estimated_output_tokens=estimated_output_tokens)
