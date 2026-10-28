"""Correction engine: turn audit findings into a targeted correction task.

The orchestrator builds the task; the executor carries it out; only the
auditor may mark an issue RESOLVED. Targeted correction (fix listed
defects) is preferred; full re-execution is reserved for methodology
failure, systematically unreliable evidence, or a misunderstood question.
"""
from __future__ import annotations

from ..models.contracts import AuditIssue, AuditReport, CorrectionTask, IssueSeverity


def build_correction_task(audit: AuditReport) -> CorrectionTask:
    open_issues = [i for i in audit.issues if i.severity in
                   (IssueSeverity.CRITICAL, IssueSeverity.MAJOR)]
    return CorrectionTask(
        issue_ids=[i.id for i in open_issues],
        required_changes=[f"[{i.id}] {i.required_correction}" for i in open_issues],
        evidence_needed=[i.evidence for i in open_issues if i.evidence],
        affected_artifacts=sorted({i.affected_claim_or_section for i in open_issues}),
        acceptance_criteria=[
            "Every CRITICAL and MAJOR issue is fixed, or its claim is removed/qualified",
            "Corrections are backed by newly retrieved sources where evidence was missing",
        ],
    )


def needs_full_reexecution(audit: AuditReport) -> bool:
    """Heuristic, applied by code: full re-execution only when the audit
    says the method or evidence base itself is invalid."""
    text = " ".join((i.description + " " + i.required_correction)
                    for i in audit.issues).lower()
    triggers = ("methodolog", "systematically unreliable", "misunderstood",
                "fundamentally invalid", "wrong research question")
    return any(t in text for t in triggers)


def apply_audit_to_issues(audit: AuditReport, previous: list[AuditIssue]) -> list[AuditIssue]:
    """Merge a new audit into the running issue list.

    New verdicts win for issues they mention. Issues from earlier audits
    that the new audit does not mention keep their previous status: the
    executor can never close its own issues, and silence from the auditor
    is not a resolution. An issue becomes RESOLVED only when a later
    audit explicitly lists it with status RESOLVED.
    """
    merged: dict[str, AuditIssue] = {i.id: i for i in previous}
    for issue in audit.issues:
        merged[issue.id] = issue
    return list(merged.values())
