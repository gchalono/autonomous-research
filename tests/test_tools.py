from tests.policy_fixtures import reviewed_fixture
"""Tool tests: Tavily search path (mocked HTTP), DuckDuckGo fallback
behaviour, and fetch-page extraction."""
import io
import json
import os
import urllib.request

from src.tools.base import default_registry
from src.tools.retrieval import fetch_url


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_tavily_search_used_when_key_set(monkeypatch, tmp_path):
    from src.storage.spending import SpendingGuard
    guard = SpendingGuard(tmp_path / "budget.db", reviewed_fixture({"currency": "USD", "expires_at": "2099-01-01T00:00:00+00:00", "evidence": "synthetic test pricing",
        "tavily": {"basic_search_max_usd": .01, "usd_per_credit": .01}}))
    guard.initialize()
    import src.storage.spending as module
    policy_path = tmp_path / 'policy.json'
    policy_path.write_text(json.dumps(guard.policy))
    monkeypatch.setattr(module, 'LEDGER_PATH', guard.path)
    monkeypatch.setattr(module, 'POLICY_PATH', policy_path)
    monkeypatch.setattr(SpendingGuard, "default", classmethod(lambda cls: guard))
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def fake_urlopen(req, timeout=30):
        assert "tavily" in req.full_url
        payload = {"usage": {"credits": 1}, "results": [
            {"title": "T1", "url": "https://example.com/1", "content": "snippet one"},
            {"title": "T2", "url": "https://example.com/2", "content": "snippet two"},
        ]}
        return _FakeResponse(json.dumps(payload))

    monkeypatch.setattr("src.tools.search._open_tavily", fake_urlopen)
    tool = default_registry().get("web_search")
    result = tool.invoke({"query": "arbitrage"})
    assert result.ok
    assert "https://example.com/1" in result.output
    assert result.provenance["result_urls"] == [
        "https://example.com/1", "https://example.com/2"]


def test_search_reports_failure_honestly_when_backends_empty(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def fake_urlopen(req, timeout=30):
        return _FakeResponse("<html><body>bot guard, no results</body></html>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    tool = default_registry().get("web_search")
    result = tool.invoke({"query": "arbitrage"})
    assert not result.ok
    assert "no results were fabricated" in result.error


def test_fetch_page_extracts_text(monkeypatch):
    html = ("<html><head><title>Example Title</title></head>"
            "<body><script>var x = 1;</script><p>Hello world</p></body></html>")

    def fake_urlopen(req, timeout=30):
        return _FakeResponse(html)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    title, text = fetch_url("https://example.com")
    assert title == "Example Title"
    assert "Hello world" in text
    assert "var x" not in text
