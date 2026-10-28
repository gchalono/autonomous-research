"""Shared fixtures: temp project root, fake tools, stub clients."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import Settings
from src.llm.provider import StubProvider, default_stub_behavior
from src.orchestration.engine import Orchestrator
from src.security.permissions import Permission
from src.storage.database import Store
from src.tools.base import Tool, ToolRegistry, ToolResult


def fake_registry() -> ToolRegistry:
    """Deterministic tools: search returns one canned result, fetch returns text."""
    registry = ToolRegistry()
    registry.register(Tool(
        name="web_search", description="fake search", permission=Permission.READ_ONLY,
        input_schema={}, timeout_s=10,
        run=lambda args: ToolResult(
            ok=True, output="1. Stub source -- https://example.com/stub\n   Stub passage.",
            provenance={"result_urls": ["https://example.com/stub"]})))
    registry.register(Tool(
        name="fetch_page", description="fake fetch", permission=Permission.READ_ONLY,
        input_schema={}, timeout_s=10,
        run=lambda args: ToolResult(
            ok=True, output="TITLE: Stub source\n\nStub passage. extra text",
            provenance={"url": args.get("url", "")})))
    registry.register(Tool(
        name="calculate", description="fake calc", permission=Permission.READ_ONLY,
        input_schema={}, timeout_s=10,
        run=lambda args: ToolResult(ok=True, output="2 + 2 = 4")))
    return registry


def fake_fetch(url: str):
    return "Stub source", "Stub passage. extra text"


@pytest.fixture
def settings(tmp_path):
    s = Settings.from_env()
    s.projects_root = str(tmp_path / "projects")
    return s


@pytest.fixture
def store(settings):
    return Store(os.path.join(settings.projects_root, "research.db"))


@pytest.fixture
def orch(settings, store):
    client = StubProvider(default_stub_behavior())
    engine = Orchestrator(settings, store, client=client,
                          registry=fake_registry(), fetch_fn=fake_fetch)
    engine._stub = client  # tests inspect call counts
    return engine
