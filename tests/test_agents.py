"""Agent-level tests: malformed output repair, tool-loop bounds, and
independent source verification done in code (not by the LLM)."""
import pytest

from src.agents import auditor as auditor_mod
from src.agents import evaluator as evaluator_mod
from src.agents import executor as executor_mod
from src.agents.common import AgentOutputError
from src.llm.provider import StubProvider, default_stub_behavior
from src.models.contracts import ExecutionReport, VerificationStatus
from tests.conftest import fake_registry


def _report():
    return ExecutionReport.model_validate({
        "executive_summary": "s",
        "findings": [], "claims": [],
        "sources": [{"id": "S1", "url": "https://example.com/a", "title": "A",
                    "passage": "the quick brown fox jumps over the lazy dog and then some more text here",
                    "verification_status": "UNCHECKED"},
                   {"id": "S2", "url": "https://example.com/b", "title": "B",
                    "passage": "a passage that appears nowhere",
                    "verification_status": "UNCHECKED"},
                   {"id": "S3", "url": "https://example.com/c", "title": "C",
                    "passage": "unreachable passage text",
                    "verification_status": "UNCHECKED"}],
        "limitations": [], "unresolved_dependencies": [],
    })


def test_verify_sources_confirmed_not_found_unreachable():
    def fetch(url):
        if url.endswith("/a"):
            return "A", "prefix the quick brown fox jumps over the lazy dog and then some more text here suffix"
        if url.endswith("/b"):
            return "B", "completely different page content"
        raise ConnectionError("down")

    result = auditor_mod.verify_sources(_report(), fetch, max_sources=8)
    assert result["S1"] == VerificationStatus.CONFIRMED
    assert result["S2"] == VerificationStatus.NOT_FOUND
    assert result["S3"] == VerificationStatus.UNREACHABLE


def test_verify_sources_respects_cap():
    def fetch(url):
        return "T", "the quick brown fox jumps over the lazy dog and then some more text here"

    result = auditor_mod.verify_sources(_report(), fetch, max_sources=1)
    assert result["S1"] == VerificationStatus.CONFIRMED
    assert result["S2"] == VerificationStatus.UNCHECKED


def test_malformed_output_gets_one_repair_then_succeeds():
    def evaluator(call_no, user):
        if call_no == 1:
            return {"decision": "NOPE"}  # invalid enum -> validation error
        return {"decision": "APPROVE", "critical_issues": [], "major_issues": [],
                "minor_issues": [], "required_revisions": [],
                "accepted_criteria": [], "rationale": "repaired"}

    client = StubProvider({"evaluator": evaluator})
    spec = _spec()
    result = evaluator_mod.evaluate_prompt(client, "gpt-5-mini", "obj", spec)
    assert result.decision.value == "APPROVE"
    assert client.calls["evaluator"] == 2


def _spec():
    from src.models.contracts import PromptSpec
    return PromptSpec(objective="o", execution_prompt="do research", revision_number=1)


def test_malformed_output_twice_fails():
    client = StubProvider({"evaluator": lambda c, u: {"decision": "NOPE"}})
    with pytest.raises(AgentOutputError):
        evaluator_mod.evaluate_prompt(client, "gpt-5-mini", "obj", _spec())


def test_executor_loop_bound_enforced():
    def executor_step(call_no, user):
        return {"tool_calls": [{"tool": "web_search", "arguments": {"query": "x"}}],
                "done": False, "report": None}

    client = StubProvider({"executor": executor_step})
    with pytest.raises(AgentOutputError, match="did not finish"):
        executor_mod.run_execution(client, "gpt-5-mini", _spec(), fake_registry(),
                                   max_iterations=3)


def test_executor_done_with_tool_calls_rejected():
    def executor_step(call_no, user):
        return {"tool_calls": [{"tool": "web_search", "arguments": {"query": "x"}}],
                "done": True, "report": None}

    client = StubProvider({"executor": executor_step})
    with pytest.raises(AgentOutputError):
        executor_mod.run_execution(client, "gpt-5-mini", _spec(), fake_registry(),
                                   max_iterations=3)


def test_executor_unknown_tool_reported_not_crash():
    def executor_step(call_no, user):
        report = default_stub_behavior()["executor"](99, "TOOL RESULT x")["report"]
        if "TOOL RESULT" in user:
            return {"tool_calls": [], "done": True, "report": report}
        return {"tool_calls": [{"tool": "nonexistent_tool", "arguments": {}}],
                "done": False, "report": None}

    client = StubProvider({"executor": executor_step})
    report = executor_mod.run_execution(client, "gpt-5-mini", _spec(), fake_registry(),
                                        max_iterations=5)
    assert report.executive_summary
