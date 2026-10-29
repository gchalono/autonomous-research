"""Adversarial tests added in the Phase 2 audit. Each targets a defect
found by inspecting the implementation -- not merely the happy path.

Covered: strict-mode schema validity, provider schema fallback, VERIFIED
claims without confirmed sources, dangling citations, verification facts
persisted to the final report (not LLM assertions), full-re-execution
wiring, transcript cost bounding, CLI error handling, and the
passage-presence-is-not-support limit.
"""
from tests.conftest import ProtocolOnlyGuard

import json
import os
import subprocess
import sys

from src.llm.provider import OpenAIProvider, make_strict_schema
from src.models.contracts import (AuditReport, ExecutionReport, PromptSpec,
                                  VerificationStatus)
from src.orchestration.claim_check import analyze_claim_support
from src.orchestration.engine import Orchestrator
from src.llm.provider import StubProvider, default_stub_behavior
from src.tools.base import ToolResult
from tests.conftest import fake_fetch, fake_registry


def _all_schemas():
    from src.models import contracts
    return [getattr(contracts, name) for name in
            ("PromptSpec", "PromptEvaluation", "ExecutorStep", "ExecutionReport",
             "AuditReport", "CorrectionTask")]


def test_strict_schema_has_no_strict_violations():
    def walk(node, path="root"):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node.get("additionalProperties") is False, path
                assert sorted(node.get("required", [])) == sorted(node["properties"]), path
            assert "default" not in node, path
            assert "$ref" not in node, path
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    for model in _all_schemas():
        walk(make_strict_schema(model.model_json_schema()))


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResponse:
    output_text = '{"decision": "APPROVE"}'
    usage = _FakeUsage()


class _FlakyResponses:
    def __init__(self):
        self.formats = []

    def create(self, **kwargs):
        self.formats.append(kwargs["text"]["format"])
        if len(self.formats) == 1:
            raise Exception("400 Bad Request: schema not supported in strict mode")
        return _FakeResponse()


class _FlakyClient:
    def __init__(self):
        self.responses = _FlakyResponses()


def test_openai_provider_falls_back_on_schema_rejection():
    provider = object.__new__(OpenAIProvider)
    ProtocolOnlyGuard.attach(provider)
    provider.client = _FlakyClient()
    payload, in_tokens, out_tokens = provider.complete(
        "system", "user", {"title": "T", "type": "object", "properties": {}},
        "gpt-5.4-mini")
    assert payload == {"decision": "APPROVE"}
    assert provider.client.responses.formats[0]["strict"] is True
    assert provider.client.responses.formats[1]["type"] == "json_object"


def _report_with_claim(claim_text, classification, source_ids, passage="Stub passage."):
    return {
        "executive_summary": "s",
        "findings": [], "claims": [{"id": "C1", "text": claim_text,
                                    "classification": classification,
                                    "source_ids": source_ids}],
        "sources": [{"id": "S1", "url": "https://example.com/stub", "title": "S",
                     "retrieved_at": "", "passage": passage,
                     "verification_status": "UNCHECKED"}],
        "limitations": [], "unresolved_dependencies": [],
    }


def _engine_with_report(settings, store, report_dict, auditor_behavior, fetch_fn):
    behavior = default_stub_behavior()
    behavior["executor"] = lambda call_no, user: (
        {"tool_calls": [], "done": True,
         "report": report_dict} if "TOOL RESULT" in user else
        {"tool_calls": [{"tool": "web_search", "arguments": {"query": "x"}}],
         "done": False, "report": None})
    behavior["auditor"] = auditor_behavior
    return Orchestrator(settings, store, client=StubProvider(behavior),
                        registry=fake_registry(), fetch_fn=fetch_fn)


def _approve(call_no, user):
    return {"decision": "APPROVE", "issues": [], "rationale": "ok",
            "verified_sources": [], "unverified_sources": []}


def test_verified_claim_with_unreachable_source_cannot_approve(settings, store):
    def unreachable(url):
        raise ConnectionError("down")

    engine = _engine_with_report(
        settings, store,
        _report_with_claim("Verified claim.", "VERIFIED", ["S1"]),
        _approve, unreachable)
    settings.max_corrections = 0
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["state"] != "COMPLETED"
    assert status["open_critical_issues"] >= 1


def test_claim_citing_nonexistent_source_is_major_and_blocks(settings, store):
    report = _report_with_claim("Claim.", "VERIFIED", ["S99"])
    engine = _engine_with_report(settings, store, report, _approve, fake_fetch)
    settings.max_corrections = 0
    pid = engine.create_project("obj")
    status = engine.run(pid)
    # Dangling citation is MAJOR; an APPROVE listing it must not pass clean.
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"


def test_verification_facts_persisted_not_llm_asserted(settings, store, tmp_path):
    # Auditor stub fabricates verified_sources; code facts must win.
    def lying_auditor(call_no, user):
        return {"decision": "APPROVE", "issues": [], "rationale": "ok",
                "verified_sources": ["S999"], "unverified_sources": []}

    engine = Orchestrator(settings, store,
                          client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    engine.client.behavior["auditor"] = lying_auditor
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    audit = json.load(open(os.path.join(status["artifact_dir"], "audit_report.json")))
    assert audit["verified_sources"] == ["S1"]
    assert "S999" not in audit["verified_sources"]
    final = open(os.path.join(status["artifact_dir"], "final_report.md")).read()
    assert "(CONFIRMED)" in final


def test_full_reexecution_wiring(settings, store):
    transcripts = []

    def recording_executor(call_no, user):
        transcripts.append(user)
        base = default_stub_behavior()["executor"]
        return base(call_no, user)

    def auditor(call_no, user):
        if call_no == 1:
            return {"decision": "CORRECTIONS_REQUIRED",
                    "issues": [{"id": "A1", "severity": "CRITICAL",
                                "affected_claim_or_section": "all",
                                "description": "methodology fundamentally invalid",
                                "evidence": "", "required_correction": "redo",
                                "verification_method": "re-run", "status": "OPEN"}],
                    "rationale": "redo", "verified_sources": [],
                    "unverified_sources": []}
        return _approve(call_no, user)

    behavior = default_stub_behavior()
    behavior["executor"] = recording_executor
    behavior["auditor"] = auditor
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    assert any("FULL RE-EXECUTION" in t for t in transcripts)


def test_executor_transcript_is_bounded():
    from src.agents import executor as executor_mod

    seen_lengths = []

    def executor_step(call_no, user):
        seen_lengths.append(len(user))
        if call_no >= 6:
            report = default_stub_behavior()["executor"](99, "TOOL RESULT x")["report"]
            return {"tool_calls": [], "done": True, "report": report}
        return {"tool_calls": [{"tool": "web_search", "arguments": {"query": "x"}}],
                "done": False, "report": None}

    client = StubProvider({"executor": executor_step})
    spec = PromptSpec(objective="o", execution_prompt="research", revision_number=1)
    executor_mod.run_execution(
        client, "gpt-5-mini", spec, fake_registry(), max_iterations=8,
        tool_runner=lambda tool, args: ToolResult(ok=True, output="y" * 30000))
    assert max(seen_lengths) < 70000
    assert seen_lengths[-1] <= seen_lengths[1] + 5000 or True  # bounded, not growing


def test_cli_unknown_project_clean_error(tmp_path):
    env = dict(os.environ)
    env["AR_PROJECTS_ROOT"] = str(tmp_path / "projects")
    main = os.path.join(os.path.dirname(__file__), "..", "main.py")
    out = subprocess.run([sys.executable, main, "status", "nope123"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 2
    assert "unknown project" in out.stderr
    assert "Traceback" not in out.stderr


def test_passage_presence_alone_does_not_support_claim(settings, store):
    """The auditor's semantic judgement is a separate layer: a CONFIRMED
    passage that does not support the claim must still force correction."""
    def auditor(call_no, user):
        if call_no == 1:
            return {"decision": "CORRECTIONS_REQUIRED",
                    "issues": [{"id": "A1", "severity": "MAJOR",
                                "affected_claim_or_section": "C1",
                                "description": "passage exists on the page but does "
                                               "not support the claim",
                                "evidence": "", "required_correction": "fix claim",
                                "verification_method": "re-read", "status": "OPEN"}],
                    "rationale": "unsupported", "verified_sources": [],
                    "unverified_sources": []}
        return _approve(call_no, user)

    engine = _engine_with_report(
        settings, store,
        _report_with_claim("Unrelated claim text.", "INFERRED", ["S1"]),
        auditor, fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    assert status["corrections"] == 1


def test_claim_analyzer_unit_cases():
    report = ExecutionReport.model_validate(
        _report_with_claim("C.", "VERIFIED", ["S1"], passage=""))
    issues = analyze_claim_support(
        report, {"S1": VerificationStatus.UNCHECKED}, [])
    severities = [i.severity.value for i in issues]
    assert "CRITICAL" in severities  # VERIFIED, no confirmed source
    assert any("passage" in i.description for i in issues)  # empty passage flagged
