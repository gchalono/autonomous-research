"""Integration tests: full artifact set, CLI end-to-end, and the optional
live-API test (skipped unless explicitly enabled with a real key)."""
import json
import os
import subprocess
import sys

import pytest

REQUIRED_ARTIFACTS = [
    "objective.md", "prompt_v1.md", "approved_prompt.md",
    "prompt_evaluation.json", "execution_report.md", "sources.json",
    "audit_report.json", "final_report.md", "run_metadata.json",
]

FINAL_SECTIONS = [
    "## 1. Executive summary", "## 2. Research findings",
    "## 3. Evidence and citations", "## 4. Analysis",
    "## 5. Conclusions", "## 6. Important limitations",
    "## 7. Audit outcome", "## 8. Unresolved issues",
    "## 9. Recommended next actions",
]


def test_full_run_produces_all_artifacts(orch):
    pid = orch.create_project("Stub objective")
    status = orch.run(pid)
    assert status["state"] == "COMPLETED"
    for name in REQUIRED_ARTIFACTS:
        assert os.path.exists(os.path.join(status["artifact_dir"], name)), name
    final = open(os.path.join(status["artifact_dir"], "final_report.md")).read()
    for section in FINAL_SECTIONS:
        assert section in final, section
    metadata = json.load(open(os.path.join(status["artifact_dir"], "run_metadata.json")))
    assert metadata["state"] == "COMPLETED"
    assert metadata["events"], "transition history must be recorded"


def test_cli_run_status_report_cancel(tmp_path, monkeypatch):
    env = dict(os.environ)
    env["AR_PROJECTS_ROOT"] = str(tmp_path / "projects")
    main = os.path.join(os.path.dirname(__file__), "..", "main.py")
    run = subprocess.run(
        [sys.executable, main, "--provider", "stub", "run", "Research stub things"],
        capture_output=True, text=True, env=env, timeout=120)
    assert run.returncode == 0, run.stderr
    assert "COMPLETED" in run.stdout
    pid = [line for line in run.stdout.splitlines() if line.startswith("Created project")][0].split()[-1]
    for cmd in (["status", pid], ["report", pid]):
        out = subprocess.run([sys.executable, main, *cmd],
                             capture_output=True, text=True, env=env, timeout=60)
        assert out.returncode == 0, out.stderr
    cancel = subprocess.run([sys.executable, main, "cancel", pid],
                            capture_output=True, text=True, env=env, timeout=60)
    assert cancel.returncode == 0
    # Cancelling a terminal project is a no-op, not an error.
    assert "COMPLETED" in cancel.stdout


@pytest.mark.skipif(
    not (os.environ.get("AR_RUN_LIVE") == "1" and os.environ.get("OPENAI_API_KEY")),
    reason="live API test requires AR_RUN_LIVE=1 and OPENAI_API_KEY")
def test_live_end_to_end(tmp_path):
    """Real end-to-end run against the OpenAI Responses API. Only runs when
    explicitly enabled; it spends real money (small objective, mini models)."""
    from src.config import Settings
    from src.llm.provider import OpenAIProvider
    from src.orchestration.engine import Orchestrator
    from src.storage.database import Store
    from src.tools.base import default_registry

    settings = Settings.from_env()
    settings.projects_root = str(tmp_path / "projects")
    settings.models = {k: "gpt-5-mini" for k in settings.models}
    store = Store(os.path.join(settings.projects_root, "research.db"))
    engine = Orchestrator(settings, store, client=OpenAIProvider(),
                          registry=default_registry())
    pid = engine.create_project(
        "What is the capital of France and what river runs through it? "
        "Answer with sources.")
    status = engine.run(pid)
    assert status["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    assert os.path.exists(os.path.join(status["artifact_dir"], "final_report.md"))
