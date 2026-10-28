"""Deterministic claim-to-evidence verification.

Why this module exists: checking that a quoted passage *appears on a
re-fetched page* establishes that the passage exists. It does NOT establish
that the passage supports the claim that cites it, nor that the claim
deserves its classification. A VERIFIED claim citing an unreachable source,
a source that was never retrieved, or a source id that does not exist is
a defect no matter what the passage check says.

This analyzer enforces the structural side of claim support in code, so
it holds even if the auditor LLM misses it:

- VERIFIED requires at least one cited source independently CONFIRMED.
- Every cited source id must exist in the report's source register.
- INFERRED/ESTIMATED claims need at least one cited source; a derivation
  with no evidence at all is not an inference, it is an assertion.
- Sources need a non-empty passage, otherwise nothing can be checked.
- A source the executor never fetched (no successful fetch_page call in
  tool history) is a provenance gap, even if the auditor's re-fetch
  later confirmed the passage.
- Tool failures with no recorded limitation mean the report is hiding
  a gap in its own evidence base.

What this module deliberately does NOT claim: semantic support. Whether a
real passage's *meaning* entails a claim still requires judgement -- that
is the auditor LLM's job, and the auditor prompt instructs it to check
exactly that. Passage presence is necessary, never sufficient, and this
module makes sure the necessary conditions are actually enforced.
"""
from __future__ import annotations

import hashlib

from ..models.contracts import (AuditIssue, ClaimClassification,
                                ExecutionReport, IssueSeverity, IssueStatus,
                                VerificationStatus)


def analyze_claim_support(report: ExecutionReport,
                          verification: dict[str, VerificationStatus],
                          tool_calls: list[dict]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    sources = {s.id: s for s in report.sources}
    fetched_urls = {
        (t.get("arguments_json") or "") for t in tool_calls
        if t.get("tool") == "fetch_page" and t.get("ok")
    }
    # Tool-call arguments are stored as JSON; extract the URL field loosely.
    import json as _json
    fetched: set[str] = set()
    for raw in fetched_urls:
        try:
            fetched.add(_json.loads(raw).get("url", ""))
        except Exception:
            continue
    calculated = set()
    for call in tool_calls:
        if call.get('tool') == 'calculate' and call.get('ok'):
            calculated.add(_json.loads(call['arguments_json']).get('expression', ''))

    def issue(severity: IssueSeverity, target: str, desc: str,
              correction: str) -> AuditIssue:
        stable_id = hashlib.sha256((target + "|" + desc.split(":")[0]).encode()).hexdigest()[:16]
        return AuditIssue(
            id="CC-" + stable_id, severity=severity, affected_claim_or_section=target,
            description=desc, evidence="",
            required_correction=correction,
            verification_method="Re-run claim-support analysis after correction; "
                                "auditor re-verifies.",
            status=IssueStatus.OPEN)

    for kind, records in (("source", report.sources), ("claim", report.claims),
                          ("finding", report.findings)):
        seen = set()
        for record in records:
            if not record.id.strip() or record.id in seen:
                issues.append(issue(IssueSeverity.MAJOR, kind + ":" + record.id,
                                    f"Empty or duplicate {kind} id.", "Use unique nonempty ids."))
            seen.add(record.id)
    known_claims = {c.id for c in report.claims}
    for finding in report.findings:
        if any(cid not in known_claims for cid in finding.claim_ids):
            issues.append(issue(IssueSeverity.MAJOR, finding.id,
                                "Finding references a missing claim.",
                                "Cite only claims present in the report."))
    for claim in report.claims:
        if not claim.text.strip():
            issues.append(issue(IssueSeverity.MAJOR, claim.id,
                                "Claim text is empty.",
                                "Remove the claim or supply its text."))
            continue
        dangling = [sid for sid in claim.source_ids if sid not in sources]
        if dangling:
            issues.append(issue(IssueSeverity.MAJOR, claim.id,
                                f"Claim cites source id(s) that do not exist "
                                f"in the source register: {dangling}.",
                                "Cite only sources present in the register, "
                                "or add the missing sources with passages."))
        confirmed = [sid for sid in claim.source_ids
                     if verification.get(sid) == VerificationStatus.CONFIRMED]
        missing_calculations = set(claim.calculation_expressions) - calculated
        if missing_calculations:
            issues.append(issue(IssueSeverity.MAJOR, claim.id,
                                "Claim references calculations absent from successful tool history.",
                                "Run each referenced expression with calculate or remove the reference."))
        pure_calculation = (claim.classification == ClaimClassification.ESTIMATED
                            and bool(claim.calculation_expressions)
                            and not missing_calculations and not claim.source_ids)
        if claim.classification == ClaimClassification.VERIFIED:
            if not claim.source_ids:
                issues.append(issue(IssueSeverity.CRITICAL, claim.id,
                                    "Claim is classified VERIFIED but cites no source.",
                                    "Downgrade the classification or cite a "
                                    "retrieved, confirmed source."))
            elif not confirmed:
                statuses = {sid: verification.get(sid, VerificationStatus.UNCHECKED).value
                            for sid in claim.source_ids}
                issues.append(issue(IssueSeverity.CRITICAL, claim.id,
                                    "Claim is classified VERIFIED but none of its "
                                    f"cited sources was independently confirmed: {statuses}.",
                                    "Downgrade the claim to INFERRED/UNKNOWN, "
                                    "or replace its evidence with a source whose "
                                    "passage was confirmed on re-fetch."))
        elif claim.classification in (ClaimClassification.INFERRED,
                                      ClaimClassification.ESTIMATED,
                                      ClaimClassification.PARTIALLY_SUPPORTED,
                                      ClaimClassification.CONTRADICTED):
            if pure_calculation:
                continue
            if not claim.source_ids:
                issues.append(issue(IssueSeverity.MAJOR, claim.id,
                                    f"Claim is classified {claim.classification.value} "
                                    "but cites no source at all.",
                                    "Cite the evidence the claim derives from "
                                    "(or, for CONTRADICTED, the contradicting "
                                    "evidence), or reclassify as "
                                    "HYPOTHETICAL/UNKNOWN."))
            elif not confirmed:
                issues.append(issue(IssueSeverity.MAJOR, claim.id,
                                    "Derived or evidence-based claim has no independently confirmed source.",
                                    "Retrieve and confirm its evidence, remove the claim, or explicitly "
                                    "reclassify it as HYPOTHETICAL/UNKNOWN with limitations."))
        elif claim.classification == ClaimClassification.UNSUPPORTED:
            if not claim.source_ids:
                issues.append(issue(IssueSeverity.MINOR, claim.id,
                                    "Unsupported claim cites no sources; the "
                                    "evidence examined should be recorded for "
                                    "auditability.",
                                    "Cite the sources examined, or record the "
                                    "failed searches in the limitations."))

    for source in report.sources:
        if not source.passage.strip():
            issues.append(issue(IssueSeverity.MINOR, source.id,
                                "Source has no passage, so its content cannot "
                                "be checked against any claim.",
                                "Supply the supporting passage or remove the source."))
        elif source.url not in fetched and verification.get(source.id) \
                == VerificationStatus.CONFIRMED:
            # The auditor's re-fetch found the passage, but the executor
            # never retrieved this URL during its own tool loop: the
            # citation's provenance is the auditor's, not the executor's.
            issues.append(issue(IssueSeverity.MAJOR, source.id,
                                "Source was confirmed by the auditor's re-fetch "
                                "but does not appear in the executor's successful "
                                "fetch history.",
                                "Have the executor re-retrieve the source in a "
                                "correction pass, or remove the citation."))

    failed_tools = [t for t in tool_calls if not t.get("ok")]
    if failed_tools and not report.limitations:
        issues.append(issue(IssueSeverity.MINOR, "limitations",
                            f"{len(failed_tools)} tool call(s) failed during "
                            "execution, but the report records no limitations.",
                            "Record the failed tools and the conclusions they "
                            "affect in the report's limitations."))
    return issues
