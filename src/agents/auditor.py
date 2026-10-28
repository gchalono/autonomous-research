"""Agent 4 -- Independent Execution Auditor.

The auditor does NOT merely summarize the executor's report. It receives
the original objective, the approved specification, the report, the source
register, and the results of independent verification performed in code
(re-fetching sources and checking passages, recomputing nothing by trust).
Critical defects block approval; major defects must be corrected or have
their claims removed/qualified; minor issues may remain.

Independent verification in code (``verify_sources``) is deliberately kept
out of the LLM: whether a passage appears in a freshly fetched page is a
fact a program can check, and the auditor's judgement is applied on top of
those facts, not instead of them.
"""
from __future__ import annotations

import re
from typing import Callable

from ..llm.provider import LLMClient
from ..models.contracts import (AuditReport, ExecutionReport, PromptSpec,
                                VerificationStatus)
from .common import call_agent

SYSTEM = """You are the Independent Execution Auditor in a four-agent research
system. Your job is to determine whether the executor's report satisfies
the original objective and the approved acceptance criteria -- not to
summarize it.
Evaluate: factual accuracy, source relevance, citation integrity,
mathematical correctness, methodological validity, logical consistency,
completeness, unsupported conclusions, unresolved uncertainties, and
compliance with user constraints.
If sources contradict each other, say so explicitly and name the conflict;
never resolve a contradiction silently in favor of one side. If a claim's
cited passage exists on the page but does not actually support the claim,
that is a citation-integrity defect even though the passage check passed:
passage presence is necessary, never sufficient.
Use the independent verification results supplied: a source marked
CONFIRMED had its passage found in a fresh fetch; NOT_FOUND means the page
was fetched but the passage was absent; UNREACHABLE means it could not be
fetched at all. Treat claims resting on NOT_FOUND or UNREACHABLE sources as
unverified, not as verified.
Decide APPROVE, CORRECTIONS_REQUIRED, INCONCLUSIVE, or BLOCKED. Critical
defects must prevent approval. Every issue needs an id, severity, affected
claim or section, description, evidence, required correction, and a
verification method. Return ONLY a JSON document matching the schema."""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def verify_sources(report: ExecutionReport, fetch_fn: Callable[[str], tuple[str, str]],
                   max_sources: int = 8) -> dict[str, VerificationStatus]:
    """Independently re-fetch each source and check its passage.

    ``fetch_fn`` returns (title, text) and raises on failure. A passage
    counts as confirmed if a 60-character normalized sample of it appears
    in the freshly fetched text (full-passage matching is too brittle for
    pages that reflow). Sources beyond ``max_sources`` stay UNCHECKED.
    """
    results: dict[str, VerificationStatus] = {}
    for source in report.sources[:max_sources]:
        try:
            _title, text = fetch_fn(source.url)
        except Exception:
            results[source.id] = VerificationStatus.UNREACHABLE
            continue
        passage = _normalize(source.passage)
        if not passage:
            results[source.id] = VerificationStatus.UNCHECKED
            continue
        sample = passage[:60]
        results[source.id] = (VerificationStatus.CONFIRMED
                              if sample in _normalize(text)
                              else VerificationStatus.NOT_FOUND)
    for source in report.sources[max_sources:]:
        results[source.id] = VerificationStatus.UNCHECKED
    return results


def audit_execution(client: LLMClient, model: str, objective: str,
                    spec: PromptSpec, report: ExecutionReport,
                    verification: dict[str, VerificationStatus],
                    cost_cb=None, estimated_output_tokens: int = 1500) -> AuditReport:
    verified = [sid for sid, st in verification.items()
                if st == VerificationStatus.CONFIRMED]
    unverified = [sid for sid, st in verification.items()
                  if st != VerificationStatus.CONFIRMED]
    user = (
        f"ORIGINAL OBJECTIVE:\n{objective}\n\n"
        f"APPROVED EXECUTION PROMPT:\n{spec.execution_prompt}\n"
        f"ACCEPTANCE CRITERIA: {spec.acceptance_criteria}\n\n"
        f"EXECUTOR REPORT:\n{report.model_dump_json(indent=2)}\n\n"
        f"INDEPENDENT VERIFICATION: verified sources {verified}; "
        f"unverified sources {unverified}."
    )
    return call_agent(client, model, SYSTEM, user, AuditReport, cost_cb=cost_cb,
                      estimated_output_tokens=estimated_output_tokens)
