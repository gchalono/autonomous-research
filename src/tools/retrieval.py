"""Webpage retrieval: fetch a URL and extract readable text.

Only the fetched text may be cited. If a fetch fails, the tool reports the
failure and the executor must not cite that URL. Extracted text is capped
so a single page cannot flood the model's context.
"""
from __future__ import annotations

import html as html_lib
import re
import urllib.request
import urllib.parse
import ipaddress
import socket

from ..security.permissions import Permission
from .base import Tool, ToolResult

_USER_AGENT = "Mozilla/5.0 (compatible; autonomous-research/1.0)"
_MAX_CHARS = 12000
_MAX_BYTES = 2_000_000


def validate_public_url(url: str) -> None:
    """Reject local/file targets before executor and independent audit fetches.

    A network egress policy remains necessary against DNS rebinding: application
    DNS checks cannot pin urllib's subsequent connection through arbitrary proxies.
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    if (parsed.scheme not in ("http", "https") or not host or parsed.username
            or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError("only public HTTP(S) URLs on ports 80/443 are allowed")
    if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
        raise ValueError("local network targets are not allowed")
    addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("non-public network targets are not allowed")


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str) -> tuple[str, str]:
    """Return (title, text) for a URL, raising on failure."""
    validate_public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    opener = urllib.request.build_opener(PublicRedirectHandler())
    with opener.open(req, timeout=30) as resp:
        raw_bytes = resp.read(_MAX_BYTES + 1)
        if len(raw_bytes) > _MAX_BYTES:
            raise ValueError("page exceeds retrieval size limit")
        raw = raw_bytes.decode("utf-8", errors="replace")
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
