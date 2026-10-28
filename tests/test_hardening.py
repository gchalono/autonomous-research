"""Phase 3 hardening tests: preflight budget estimation, runtime limit,
transient-error recovery, model fallback recording, cancellation and
budget terminal no-ops, structured run log, terminal-status mapping, and
the extended claim-outcome vocabulary."""
import json
import os

import pytest

from src.llm.provider import LLMError, OpenAIProvider
from src.models.contracts import ClaimClassification, ExecutionReport
from src.orchestration.claim_check import analyze_claim_support
from src.orchestration.engine import BudgetExhausted, Orchestrator
from src.llm.provider import StubProvider, default_stub_behavior
from tests.conftest import fake_fetch, fake_registry


def test_preflight_blocks_call_that_would_breach_budget(settings, store):
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    cb = engine._cost_cb(pid)
    # A first call with sufficient budget passes without recording spend.
    cb("gpt-5.4-mini", 100, 1500, preflight=True)
    # Spend nearly the whole budget, then a new estimated call must refuse.
    engine.store.add_spend(pid, 9.999)
    with pytest.raises(BudgetExhausted, match="preflight"):
        cb("gpt-5.4-mini", 100, 1500, preflight=True)


def test_preflight_does_not_record_spend(settings, store):
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    cb = engine._cost_cb(pid)
    cb("gpt-5.4-mini", 100, 1500, preflight=True)
    assert engine.store.get_project(pid)["spent_usd"] == 0


def test_runtime_limit_fails_run_with_reason(settings, store):
    settings.max_runtime_s = 0  # any elapsed time exceeds it
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "FAILED"
    assert "runtime" in (status["failure_reason"] or "")
    assert status["terminal_status"] == "FAILED_EXECUTION"


def test_transient_error_keeps_project_resumable(settings, store):
    calls = {"n": 0}

    def flaky_creator(call_no, user):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("rate limit 429: try again later")
        return default_stub_behavior()["creator"]  # static prompt dict

    behavior = default_stub_behavior()
    behavior["creator"] = flaky_creator
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "PROMPT_DRAFTING"  # not FAILED
    assert "transient_error" in status
    assert "rate limit" in status["transient_error"]
    # Resume with the condition cleared completes the run.
    status2 = engine.run(pid)
    assert status2["state"] == "COMPLETED"


def test_non_transient_llm_error_still_fails(settings, store):
    def bad_creator(call_no, user):
        raise LLMError("authentication failed: invalid api key")

    behavior = default_stub_behavior()
    behavior["creator"] = bad_creator
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "FAILED"


def test_model_fallback_used_and_recorded():
    class Resp:
        output_text = '{"decision": "APPROVE"}'
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
        id = "resp-123"

    class FlakyResponses:
        def __init__(self):
            self.models = []

        def create(self, **kwargs):
            self.models.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.6-terra":
                raise Exception("model gpt-5.6-terra not found")
            return Resp()

    class FlakyClient:
        def __init__(self):
            self.responses = FlakyResponses()

    provider = object.__new__(OpenAIProvider)
    provider.client = FlakyClient()
    provider.fallback_model = "gpt-5.4-mini"
    payload, _, _ = provider.complete("s", "u", {"title": "T"}, "gpt-5.6-terra")
    assert payload == {"decision": "APPROVE"}
    assert provider.models_used == {"gpt-5.4-mini"}
    assert provider.last_response_id == "resp-123"
    assert provider.client.responses.models[0] == "gpt-5.6-terra"


def test_cancel_prevents_subsequent_paid_calls(settings, store):
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    from src.models.contracts import PromptSpec
    spec = PromptSpec(objective="obj", execution_prompt="do it", revision_number=1)
    engine.store.save_output(pid, "prompt_v1", spec.model_dump(mode="json"))
    engine.store.transition(pid, "CREATED", "PROMPT_REVIEW", "prompt_drafted")
    calls_before = dict(engine.client.calls)
    engine.cancel(pid)
    status = engine.run(pid)
    assert status["state"] == "CANCELLED"
    assert engine.client.calls == calls_before
    assert status["terminal_status"] == "CANCELLED"


def test_budget_exhausted_terminal_noop(settings, store):
    settings.budget_usd = 0.0001
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "BUDGET_EXHAUSTED"
    assert status["terminal_status"] == "BUDGET_EXHAUSTED"
    calls_before = dict(engine.client.calls)
    status2 = engine.run(pid)
    assert status2["state"] == "BUDGET_EXHAUSTED"
    assert engine.client.calls == calls_before


def test_run_log_written_without_secrets(settings, store):
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    log_path = os.path.join(status["artifact_dir"], "run_log.jsonl")
    assert os.path.exists(log_path)
    entries = [json.loads(line) for line in open(log_path)]
    types = {e["type"] for e in entries}
    assert "transition" in types and "llm_call" in types
    assert all(e["project_id"] == pid for e in entries)
    blob = open(log_path).read()
    assert "sk-" not in blob and "OPENAI_API_KEY" not in blob
    metadata = json.load(open(os.path.join(status["artifact_dir"], "run_metadata.json")))
    assert metadata["terminal_status"] == "COMPLETED_APPROVED"


def test_terminal_status_mapping():
    fn = Orchestrator.terminal_status
    assert fn("COMPLETED", None) == "COMPLETED_APPROVED"
    assert fn("COMPLETED_WITH_LIMITATIONS", None) == "COMPLETED_WITH_LIMITATIONS"
    assert fn("FAILED", "prompt evaluator blocked: x") == "FAILED_VALIDATION"
    assert fn("FAILED", "execution failed") == "FAILED_EXECUTION"
    assert fn("CANCELLED", None) == "CANCELLED"
    assert fn("EXECUTING", None) is None


def _report(claims):
    return ExecutionReport.model_validate({
        "executive_summary": "s", "findings": [], "claims": claims,
        "sources": [{"id": "S1", "url": "https://example.com", "title": "S",
                     "passage": "p", "verification_status": "CONFIRMED"}],
        "limitations": [], "unresolved_dependencies": [],
    })


def test_new_claim_outcomes_analyzer_rules():
    from src.models.contracts import VerificationStatus
    # PARTIALLY_SUPPORTED behaves like INFERRED: needs a source.
    r = _report([{"id": "C1", "text": "partial", "classification": "PARTIALLY_SUPPORTED",
                  "source_ids": []}])
    issues = analyze_claim_support(r, {"S1": VerificationStatus.CONFIRMED}, [])
    assert any(i.severity.value == "MAJOR" for i in issues)
    # CONTRADICTED without contradicting evidence is MAJOR.
    r = _report([{"id": "C1", "text": "contra", "classification": "CONTRADICTED",
                  "source_ids": []}])
    issues = analyze_claim_support(r, {"S1": VerificationStatus.CONFIRMED}, [])
    assert any(i.severity.value == "MAJOR" for i in issues)
    # UNSUPPORTED without sources is only MINOR (honest rejection, flagged).
    r = _report([{"id": "C1", "text": "rejected", "classification": "UNSUPPORTED",
                  "source_ids": []}])
    issues = analyze_claim_support(r, {"S1": VerificationStatus.CONFIRMED}, [])
    assert any(i.severity.value == "MINOR" and i.affected_claim_or_section == "C1" for i in issues)
    # UNSUPPORTED with a source the executor actually fetched is clean.
    import json as _json
    fetched = [{"tool": "fetch_page",
                "arguments_json": _json.dumps({"url": "https://example.com"}),
                "ok": True}]
    r = _report([{"id": "C1", "text": "rejected", "classification": "UNSUPPORTED",
                  "source_ids": ["S1"]}])
    assert analyze_claim_support(r, {"S1": VerificationStatus.CONFIRMED},
                                 fetched) == []


def test_final_report_claim_verification_appendix(settings, store):
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    final = open(os.path.join(status["artifact_dir"], "final_report.md")).read()
    assert "## 10. Claim verification detail" in final
    assert "C1" in final
    assert "CONFIRMED" in final
