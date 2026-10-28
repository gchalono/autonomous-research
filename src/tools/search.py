"""Web search: Tavily API when TAVILY_API_KEY is set, otherwise the keyless
DuckDuckGo HTML endpoint.

This is a genuine retrieval tool, not a mock: it issues real HTTP requests
and returns real result titles/URLs/snippets. Keyless DuckDuckGo scraping is
brittle -- many networks get a bot-guard page with no results -- so when a
Tavily key is present it is used first. If every backend fails or returns
nothing, the tool returns a failure/empty result and the executor must
record the limitation instead of inventing results.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import urllib.parse
import urllib.request

from ..security.permissions import Permission
from .base import Tool, ToolResult

_USER_AGENT = "Mozilla/5.0 (compatible; autonomous-research/1.0)"


def _search_duckduckgo(query: str, max_results: int = 8) -> list[dict]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    results = []
    # Each result block: <a class="result__a" href="...">title</a> ... snippet
    for match in re.finditer(
            r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            page, re.S):
        href, title, snippet = match.groups()
        title = html_lib.unescape(re.sub("<[^>]+>", "", title)).strip()
        snippet = html_lib.unescape(re.sub("<[^>]+>", "", snippet)).strip()
        # DuckDuckGo wraps outbound links in /l/?uddg=<encoded>
        if href.startswith("/l/?"):
            href = urllib.parse.unquote(
                urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                .get("uddg", [href])[0])
        if href.startswith("http"):
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _search_tavily(query: str, max_results: int) -> list[dict]:
    key = os.environ["TAVILY_API_KEY"]
    body = json.dumps({"query": query, "max_results": max_results,
                       "search_depth": "basic"}).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("content", "") or "")[:500]}
            for r in data.get("results", []) if r.get("url", "").startswith("http")]


def web_search_tool() -> Tool:
    def run(args: dict) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="query is required")
        max_results = int(args.get("max_results", 8))
        errors = []
        results: list[dict] = []
        if os.environ.get("TAVILY_API_KEY"):
            try:
                results = _search_tavily(query, max_results)
            except Exception as exc:
                errors.append(f"Tavily: {exc}")
        if not results:
            try:
                results = _search_duckduckgo(query, max_results)
            except Exception as exc:
                errors.append(f"DuckDuckGo: {exc}")
        if not results:
            detail = "; ".join(errors) if errors else "backends returned no results"
            return ToolResult(
                ok=False,
                error=f"search unavailable ({detail}); no results were fabricated. "
                      "Set TAVILY_API_KEY for a reliable search backend.")
        lines = [f"{i+1}. {r['title']} -- {r['url']}\n   {r['snippet']}"
                 for i, r in enumerate(results)]
        return ToolResult(ok=True, output="\n".join(lines),
                          provenance={"result_count": len(results),
                                      "result_urls": [r["url"] for r in results]})

    return Tool(
        name="web_search",
        description="Search the web and return titles, URLs and snippets.",
        permission=Permission.READ_ONLY,
        input_schema={"query": "string (required)", "max_results": "int, default 8"},
        timeout_s=30,
        run=run,
    )
