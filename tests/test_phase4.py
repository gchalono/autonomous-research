"""Phase 4 tests: .env loading, cumulative validation ledger, and
cumulative-cap preflight enforcement."""
import json
import os

import pytest

from src.config import Settings, load_dotenv
from src.llm.provider import StubProvider, default_stub_behavior
from src.orchestration.engine import BudgetExhausted, Orchestrator
from src.storage.ledger import ValidationLedger
from tests.conftest import fake_fetch, fake_registry


def test_dotenv_loading_no_overwrite(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nOPENAI_API_KEY=test-from-file\n"
        "QUOTED='hello world'\nEMPTY=\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    assert load_dotenv(str(env_file)) == str(env_file)
    assert os.environ["OPENAI_API_KEY"] == "test-from-file"
    assert os.environ["QUOTED"] == "hello world"
    # Real environment wins over the file.
    monkeypatch.setenv("OPENAI_API_KEY", "real-env")
    load_dotenv(str(env_file))
    assert os.environ["OPENAI_API_KEY"] == "real-env"
    # Missing file is not an error.
    assert load_dotenv(str(tmp_path / "nope.env")) is None


def test_ledger_records_and_persists(tmp_path):
    path = str(tmp_path / "validation_ledger.json")
    ledger = ValidationLedger(path, 30.0)
    assert ledger.total_spent == 0
    ledger.record("p1", "openai", "gpt-5.4-mini", 1.25, "llm_call")
    ledger.record("p1", "tavily", "web_search", 0.05, "search_call")
    assert ledger.total_spent == 1.30
    assert ledger.remaining == 28.70
    # A new instance over the same file sees the same total: failures and
    # restarts cannot reset the cumulative budget.
    ledger2 = ValidationLedger(path, 30.0)
    assert ledger2.total_spent == 1.30
    assert ledger2.summary()["entries"] == 2


def test_cumulative_cap_blocks_new_project_first_call(settings, store):
    settings.total_validation_budget_usd = 0.005
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    # Spend the cumulative budget via the ledger directly (as a prior
    # project's calls would have), then a new project's first call must
    # refuse even though its own project budget is untouched.
    engine.ledger.record("old-project", "openai", "gpt-5.4-mini", 0.005, "llm_call")
    pid = engine.create_project("obj")
    cb = engine._cost_cb(pid)
    with pytest.raises(BudgetExhausted, match="cumulative"):
        cb("gpt-5.4-mini", 100, 1500, preflight=True)


def test_engine_calls_land_in_ledger(settings, store):
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project("obj")
    status = engine.run(pid)
    assert status["state"] == "COMPLETED"
    assert engine.ledger.total_spent > 0
    assert abs(engine.ledger.total_spent - status["spent_usd"]) < 0.001
    # A second engine instance over the same projects root sees it.
    engine2 = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                           registry=fake_registry(), fetch_fn=fake_fetch)
    assert engine2.ledger.total_spent == engine.ledger.total_spent


def test_ledger_cli(tmp_path):
    import subprocess
    import sys
    env = dict(os.environ)
    env["AR_PROJECTS_ROOT"] = str(tmp_path / "projects")
    env["AR_TOTAL_VALIDATION_BUDGET"] = "30"
    main = os.path.join(os.path.dirname(__file__), "..", "main.py")
    out = subprocess.run([sys.executable, main, "ledger"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "Cumulative validation spending" in out.stdout
    assert "$0.0000 of $30.00" in out.stdout
