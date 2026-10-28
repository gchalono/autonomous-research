"""Orchestrator tests: happy path, revision/correction limits, budget,
invalid transitions, and the critical-defect approval guard."""
import os

import pytest

from src.llm.provider import StubProvider, default_stub_behavior
from src.orchestration.engine import Orchestrator
from src.orchestration.states import State, validate_transition, InvalidTransitionError
from tests.conftest import fake_fetch, fake_registry


def _base_audit():
    return {
        "decision": "APPROVE", "issues": [],
        "rationale": "ok", "verified_sources": [], "unverified_sources": [],
    }


def test_happy_path_completes(orch):
    pid = orch.create_project("Stub objective")
    status = orch.run(pid)
    assert status["state"] == "COMPLETED"
    assert status["prompt_revisions"] == 0
    assert status["corrections"] == 0
    assert os.path.exists(os.path.join(status["artifact_dir"], "final_report.md"))


def test_prompt_revise_then_approve(settings, store):
    behavior = default_stub_behavior()
    calls = {"n": 0}

    def evaluator(call_no, user):
        calls["n"] += 1
        if call_no == 1:
            return {"decision": "REVISE", "critical_issues": [], "major_issues": ["vague"],
                    "minor_issues": [], "required_revisions": ["tighten scope"],
                    "accepted_criteria": [], "rationale": "needs work"}
        return _base_audit() | {"decision": "APPROVE"}

    behavior["evaluator"] = evaluator
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    assert status["prompt_revisions"] == 1
    assert os.path.exists(os.path.join(status["artifact_dir"], "prompt_v2.md"))


def test_prompt_revision_limit_exhaustion(settings, store):
    behavior = default_stub_behavior()
    behavior["evaluator"] = lambda call_no, user: {
        "decision": "REVISE", "critical_issues": [], "major_issues": ["always vague"],
        "minor_issues": [], "required_revisions": ["tighten scope"],
        "accepted_criteria": [], "rationale": "never good enough"}
    settings.max_prompt_revisions = 1
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "FAILED"
    assert "revision limit" in (status["failure_reason"] or "")


def test_prompt_blocked_fails(settings, store):
    behavior = default_stub_behavior()
    behavior["evaluator"] = lambda call_no, user: {
        "decision": "BLOCKED", "critical_issues": ["unsafe"],
        "major_issues": [], "minor_issues": [], "required_revisions": [],
        "accepted_criteria": [], "rationale": "blocked"}
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    assert engine.run(pid)["state"] == "FAILED"


def test_correction_then_approve(settings, store):
    behavior = default_stub_behavior()

    def auditor(call_no, user):
        if call_no == 1:
            return {"decision": "CORRECTIONS_REQUIRED",
                    "issues": [{"id": "A1", "severity": "MAJOR",
                                "affected_claim_or_section": "F1",
                                "description": "claim unsupported",
                                "evidence": "", "required_correction": "add source",
                                "verification_method": "re-fetch", "status": "OPEN"}],
                    "rationale": "fix it", "verified_sources": [],
                    "unverified_sources": []}
        result = _base_audit()
        import json
        prior = json.loads(user.split("PREVIOUS AUDIT ISSUES:\n")[1].split("\nReassess")[0])
        result["issues"] = [{**i, "status": "RESOLVED"} for i in prior]
        return result

    behavior["auditor"] = auditor
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    assert status["corrections"] == 1


def test_correction_limit_yields_limitations_not_success(settings, store):
    behavior = default_stub_behavior()
    behavior["auditor"] = lambda call_no, user: {
        "decision": "CORRECTIONS_REQUIRED",
        "issues": [{"id": "A1", "severity": "MAJOR", "affected_claim_or_section": "F1",
                    "description": "still bad", "evidence": "",
                    "required_correction": "fix", "verification_method": "re-fetch",
                    "status": "OPEN"}],
        "rationale": "never fixed", "verified_sources": [], "unverified_sources": []}
    settings.max_corrections = 1
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["state"] != "COMPLETED"


def test_critical_defect_cannot_be_silently_approved(settings, store):
    """An APPROVE verdict that still lists an OPEN CRITICAL issue must not
    produce a clean COMPLETED -- the orchestrator downgrades it."""
    behavior = default_stub_behavior()
    behavior["auditor"] = lambda call_no, user: {
        "decision": "APPROVE",
        "issues": [{"id": "C1", "severity": "CRITICAL", "affected_claim_or_section": "F1",
                    "description": "fabricated citation", "evidence": "",
                    "required_correction": "remove claim",
                    "verification_method": "re-fetch", "status": "OPEN"}],
        "rationale": "looks fine", "verified_sources": [], "unverified_sources": []}
    settings.max_corrections = 0
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["open_critical_issues"] == 1


def test_budget_exhaustion_preserves_intermediate_work(settings, store):
    settings.budget_usd = 0.0001  # less than one stub gpt-5-mini call
    engine = Orchestrator(settings, store,
                          client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("Stub objective")
    status = engine.run(pid)
    assert status["state"] == "BUDGET_EXHAUSTED"
    # Even the first request must respect a tiny budget.
    assert engine.client.calls == {}
    assert status["spent_usd"] == 0


def test_invalid_transitions_rejected():
    with pytest.raises(InvalidTransitionError):
        validate_transition(State.COMPLETED, State.EXECUTING, "start")
    with pytest.raises(InvalidTransitionError):
        validate_transition(State.PROMPT_REVIEW, State.FINALIZING, "audit_approved")
    # Software events are allowed from any non-terminal state.
    validate_transition(State.EXECUTING, State.CANCELLED, "cancel")
    validate_transition(State.PROMPT_REVIEW, State.BUDGET_EXHAUSTED, "budget_exhausted")


def test_cancel_marks_project(orch):
    pid = orch.create_project("Stub objective")
    orch.cancel(pid)
    status = orch.run(pid)
    assert status["state"] == "CANCELLED"


def test_terminal_run_is_noop(orch):
    pid = orch.create_project("Stub objective")
    orch.run(pid)
    calls_before = dict(orch._stub.calls)
    orch.run(pid)
    assert orch._stub.calls == calls_before
