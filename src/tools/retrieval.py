"""Webpage retrieval: fetch a URL and extract readable text.

Only the fetched text may be cited. If a fetch fails, the tool reports the
failure and the executor must not cite that URL. Extracted text is capped
so a single page cannot flood the model's context.
"""
from __future__ import annotations

import html as html_lib
import re
import urllib.request

from ..security.permissions import Permission
from .base import Tool, ToolResult

_USER_AGENT = "Mozilla/5.0 (compatible; autonomous-research/1.0)"
_MAX_CHARS = 12000


def fetch_url(url: str) -> tuple[str, str]:
    """Return (title, text) for a URL, raising on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    title = html_lib.unescape(re.sub("<[^>]+>", "", title_match.group(1)).strip()) \
        if title_match else ""
    # Drop scripts/styles, then tags, then collapse whitespace.
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return title, text[:_MAX_CHARS]


def fetch_page_tool() -> Tool:
    def run(args: dict) -> ToolResult:
        url = str(args.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(ok=False, error="url must start with http:// or https://")
        try:
            title, text = fetch_url(url)
        except Exception as exc:
            return ToolResult(
                ok=False,
                error=f"fetch failed ({type(exc).__name__}: {exc}); "
                      "this URL must not be cited as retrieved")
        return ToolResult(ok=True, output=f"TITLE: {title}\n\n{text}",
                          provenance={"url": url, "title": title,
                                      "chars": len(text)})

    return Tool(
        name="fetch_page",
        description="Fetch a web page and return its readable text (capped).",
        permission=Permission.READ_ONLY,
        input_schema={"url": "string (required)"},
        timeout_s=30,
        run=run,
    )
