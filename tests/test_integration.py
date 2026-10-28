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
    # Mock transports in the child process too: the offline CLI test must
    # never scrape DuckDuckGo or resolve external hosts.
    harness = (
        "import main; from tests.conftest import fake_registry, fake_fetch; "
        "from src.orchestration.engine import Orchestrator; "
        "main.Orchestrator=lambda settings, store, client: Orchestrator("
        "settings, store, client=client, registry=fake_registry(), "
        "fetch_fn=lambda url: (_ for _ in ()).throw(ConnectionError('offline'))); "
        "raise SystemExit(main.main())"
    )
    run = subprocess.run(
        [sys.executable, "-c", harness, "--provider", "stub", "run", "Research stub things"],
        capture_output=True, text=True, env=env, timeout=120)
    assert run.returncode == 1, run.stderr
    assert "COMPLETED_WITH_LIMITATIONS" in run.stdout
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


LIVE_REQUIREMENTS = (
    "OPENAI_API_KEY", "TAVILY_API_KEY", "AR_LIVE_MODEL",
    "AR_LIVE_INPUT_PRICE", "AR_LIVE_OUTPUT_PRICE", "AR_LIVE_SEARCH_PRICE",
)


@pytest.mark.skipif(
    not (os.environ.get("AR_RUN_LIVE") == "1" and
         all(os.environ.get(name) for name in LIVE_REQUIREMENTS)),
    reason="live API test requires explicit opt-in, credentials, model and verified prices")
def test_live_end_to_end():
    """Paid opt-in only: same bounded full-workflow command as the handoff.

    Use the existing projects root/ledger; a test temp directory must not reset
    the cumulative cap across repeated live validation attempts.
    """
    from scripts.validate_live import main as validate_live
    assert validate_live([
        "--authorize-paid-run", "--model", os.environ["AR_LIVE_MODEL"],
        "--input-usd-per-million", os.environ["AR_LIVE_INPUT_PRICE"],
        "--output-usd-per-million", os.environ["AR_LIVE_OUTPUT_PRICE"],
        "--search-usd-per-call", os.environ["AR_LIVE_SEARCH_PRICE"],
        "--budget", "1", "--total-budget", "2",
    ]) == 0
