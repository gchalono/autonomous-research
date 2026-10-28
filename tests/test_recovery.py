"""Persistence and resume tests: no duplicated LLM calls, no duplicated
artifacts, and recovery from a mid-workflow checkpoint."""
import os

from src.llm.provider import StubProvider, default_stub_behavior
from src.models.contracts import PromptSpec
from src.orchestration.engine import Orchestrator
from src.orchestration.states import State
from tests.conftest import fake_fetch, fake_registry


def test_resume_after_completion_makes_no_new_calls(orch):
    pid = orch.create_project("Stub objective")
    orch.run(pid)
    calls_before = dict(orch._stub.calls)
    # A brand-new orchestrator instance over the same store resumes cleanly.
    engine2 = Orchestrator(orch.settings, orch.store, client=orch._stub,
                           registry=fake_registry(), fetch_fn=fake_fetch)
    status = engine2.run(pid)
    assert status["state"] == "COMPLETED"
    assert orch._stub.calls == calls_before


def test_resume_from_prompt_review_skips_creator(orch):
    pid = orch.create_project("Stub objective")
    # Simulate a crash right after the prompt draft checkpointed.
    spec = PromptSpec(objective="Stub objective",
                      execution_prompt="Research it.", revision_number=1)
    orch.store.save_output(pid, "prompt_v1", spec.model_dump(mode="json"))
    orch.store.transition(pid, "CREATED", "PROMPT_REVIEW", "prompt_drafted")
    status = orch.run(pid)
    assert status["state"] == "COMPLETED"
    assert orch._stub.calls.get("creator", 0) == 0  # never re-invoked
    assert orch._stub.calls.get("evaluator", 0) == 1


def test_resume_from_execution_skips_executor(orch):
    pid = orch.create_project("Stub objective")
    spec = PromptSpec(objective="Stub objective",
                      execution_prompt="Research it.", revision_number=1)
    report = default_stub_behavior()["executor"](99, "TOOL RESULT x")["report"]
    orch.store.save_output(pid, "prompt_v1", spec.model_dump(mode="json"))
    orch.store.save_output(pid, "execution_0", report)
    orch.store.transition(pid, "CREATED", "EXECUTION_AUDIT", "execution_finished")
    status = orch.run(pid)
    assert status["state"] == "COMPLETED"
    assert orch._stub.calls.get("executor", 0) == 0
    assert orch._stub.calls.get("auditor", 0) == 1


def test_duplicate_operation_prevention(orch):
    """Saving the same step twice keeps one row; resume reuses it."""
    pid = orch.create_project("Stub objective")
    spec = PromptSpec(objective="Stub objective",
                      execution_prompt="Research it.", revision_number=1)
    orch.store.save_output(pid, "prompt_v1", spec.model_dump(mode="json"))
    orch.store.save_output(pid, "prompt_v1", spec.model_dump(mode="json"))
    rows = orch.store.conn.execute(
        "SELECT COUNT(*) FROM agent_outputs WHERE project_id = ? AND step_key = 'prompt_v1'",
        (pid,)).fetchone()[0]
    assert rows == 1
