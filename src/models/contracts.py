"""Structured contracts between agents and the orchestrator.

Every workflow decision is taken from one of these validated models, never
from parsing an agent's narrative Markdown. Human-readable reports are
stored separately from these machine-readable decisions.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict


class ClaimClassification(str, Enum):
    """Auditor outcome vocabulary (spec section 9.1).

    VERIFIED: at least one cited source independently confirmed.
    PARTIALLY_SUPPORTED: evidence supports part of the claim (same
        structural rules as INFERRED).
    INFERRED / ESTIMATED: derived from cited evidence, not directly stated.
    UNSUPPORTED: examined evidence does not support the claim (used for
        rejected opportunities; needs no confirmed source, but missing
        attribution is still flagged as MINOR).
    CONTRADICTED: cited evidence contradicts the claim; must cite the
        contradicting source(s).
    HYPOTHETICAL / UNKNOWN: speculation or no evidence either way.
    """
    VERIFIED = "VERIFIED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INFERRED = "INFERRED"
    ESTIMATED = "ESTIMATED"
    HYPOTHETICAL = "HYPOTHETICAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class VerificationStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    CONFIRMED = "CONFIRMED"      # passage found in an independent fetch
    NOT_FOUND = "NOT_FOUND"      # source fetched, passage not found
    UNREACHABLE = "UNREACHABLE"  # source could not be fetched at all


class EvaluationDecision(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    BLOCKED = "BLOCKED"


class AuditDecision(str, Enum):
    APPROVE = "APPROVE"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"


class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFORMATIONAL = "INFORMATIONAL"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------- prompts
class PromptSpec(BaseModel):
    objective: str
    execution_prompt: str
    scope: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    research_requirements: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    revision_number: int = 1


class PromptEvaluation(BaseModel):
    decision: EvaluationDecision
    critical_issues: List[str] = Field(default_factory=list)
    major_issues: List[str] = Field(default_factory=list)
    minor_issues: List[str] = Field(default_factory=list)
    required_revisions: List[str] = Field(default_factory=list)
    accepted_criteria: List[str] = Field(default_factory=list)
    rationale: str = ""


# ---------------------------------------------------------------- evidence
class SourceRecord(BaseModel):
    id: str
    url: str
    title: str = ""
    retrieved_at: str = ""
    passage: str = ""
    verification_status: VerificationStatus = VerificationStatus.UNCHECKED


class Claim(BaseModel):
    id: str
    text: str
    classification: ClaimClassification
    source_ids: List[str] = Field(default_factory=list)
    calculation_expressions: List[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    title: str
    text: str
    claim_ids: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- execution
class ExecutorToolCall(BaseModel):
    """One tool invocation requested by the executor agent."""
    tool: str
    arguments: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- native
# tool-call arguments (Responses API function calling)
#
# The native executor protocol validates every model-generated action
# against one of these models BEFORE dispatch. Raw argument dicts are
# never executed: unknown tools, unparseable arguments, and arguments
# failing these models all become an error output fed back to the model,
# never a tool invocation.

class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WebSearchArgs(ToolArgs):
    query: str = Field(min_length=1)
    max_results: int = Field(default=8, ge=1, le=50)


class FetchPageArgs(ToolArgs):
    url: str = Field(min_length=1)


class CalculateArgs(ToolArgs):
    expression: str = Field(min_length=1)


# Registry tool name -> argument model for the native protocol.
NATIVE_TOOL_ARGS: dict[str, type[BaseModel]] = {
    "web_search": WebSearchArgs,
    "fetch_page": FetchPageArgs,
    "calculate": CalculateArgs,
}


class ExecutorStep(BaseModel):
    """One turn of the executor's tool loop.

    Either ``tool_calls`` is non-empty (keep researching) or ``done`` is
    true and ``report`` is present. Both at once is a contract violation
    and the orchestrator rejects the step.
    """
    tool_calls: List[ExecutorToolCall] = Field(default_factory=list)
    done: bool = False
    report: Optional["ExecutionReport"] = None


class ExecutionReport(BaseModel):
    executive_summary: str
    findings: List[Finding] = Field(default_factory=list)
    claims: List[Claim] = Field(default_factory=list)
    sources: List[SourceRecord] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    unresolved_dependencies: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- audit
class AuditIssue(BaseModel):
    id: str
    severity: IssueSeverity
    affected_claim_or_section: str
    description: str
    evidence: str = ""
    required_correction: str
    verification_method: str = ""
    status: IssueStatus = IssueStatus.OPEN


class AuditReport(BaseModel):
    decision: AuditDecision
    issues: List[AuditIssue] = Field(default_factory=list)
    rationale: str = ""
    verified_sources: List[str] = Field(default_factory=list)
    unverified_sources: List[str] = Field(default_factory=list)


class CorrectionTask(BaseModel):
    issue_ids: List[str] = Field(default_factory=list)
    required_changes: List[str] = Field(default_factory=list)
    evidence_needed: List[str] = Field(default_factory=list)
    affected_artifacts: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


ExecutorStep.model_rebuild()
