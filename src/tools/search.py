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
from .safe_http import read_public_url
from ..storage.spending import SpendingGuard, SpendingBlocked

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpendingBlocked('Tavily redirect refused; no additional request authorized')


def _open_tavily(req, timeout=30):
    return urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout)


_USER_AGENT = "Mozilla/5.0 (compatible; autonomous-research/1.0)"


# Reuse only the audited bounded lexical primitives, not the page-text extractor.
from .retrieval import _tag, _RAW_END
from .safe_http import MAX_DECODED_BYTES

_DDG_ENTITY = re.compile(r'&(?:#[xX][0-9a-fA-F]{1,8};?|#[0-9]{1,10};?|[A-Za-z][A-Za-z0-9]{0,31};?)')
_DDG_MARK = re.compile('<')
_DDG_NONSPACE = re.compile(r'[^ \t\r\n\f]')
_DDG_SPACE = ' \t\r\n\f'
_DDG_VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'))
_DDG_DEPTH = 128
_DDG_HREF = 4096
_DDG_TITLE = 1024
_DDG_SNIPPET = 500


class _DDGText:
    """Bounded entity-decoded text; inline nodes join without invented spaces."""
    def __init__(self, cap):
        self.cap, self.size, self.parts = cap, 0, []

    def append(self, text, start=0, end=None):
        end = len(text) if end is None else end
        take = min(end - start, self.cap - self.size)
        if take > 0:
            self.parts.append(text[start:start + take])
            self.size += take

    def add(self, text, start, end):
        while start < end and self.size < self.cap:
            match = _DDG_ENTITY.search(text, start, end)
            stop = match.start() if match else end
            self.append(text, start, stop)
            if not match or self.size >= self.cap:
                return
            after = match.end()
            if text[after - 1] != ';' and after < end and text[after].isascii() and text[after].isalnum():
                self.append('&')
                start = match.start() + 1
            else:
                self.append(html_lib.unescape(match.group()))
                start = after

    def value(self, strip=True):
        value = ''.join(self.parts)
        return value.strip() if strip else value


def _ddg_attrs(page, start, end):
    """Second forward pass over an already validated <=8192-character tag."""
    i = start + 1
    while i < end and page[i] not in _DDG_SPACE + '/>':
        i += 1
    fields = {}
    while i < end - 1:
        while i < end - 1 and page[i] in _DDG_SPACE:
            i += 1
        if i == end - 1 or page[i] == '/':
            break
        begin = i
        while i < end - 1 and page[i] not in _DDG_SPACE + '=/>':
            i += 1
        if i == begin or i - begin > 64:
            raise ValueError('invalid or oversized search attribute name')
        name = page[begin:i].lower()
        while i < end - 1 and page[i] in _DDG_SPACE:
            i += 1
        a = b = i
        if i < end - 1 and page[i] == '=':
            i += 1
            while i < end - 1 and page[i] in _DDG_SPACE:
                i += 1
            quote = page[i] if i < end - 1 and page[i] in '\"\'' else None
            if quote:
                i += 1
                a = i
                while i < end - 1 and page[i] != quote:
                    i += 1
                if i == end - 1:
                    raise ValueError('unclosed search attribute')
                b = i
                i += 1
            else:
                a = i
                while i < end - 1 and page[i] not in _DDG_SPACE + '>':
                    i += 1
                b = i
        if name in ('class', 'href'):
            if name in fields:
                raise ValueError('ambiguous duplicate search attribute')
            value = _DDGText(8192)
            value.add(page, a, b)
            fields[name] = value.value(strip=False)
    classes = fields.get('class', '').split()
    if len(classes) > 64:
        raise ValueError('too many search classes')
    return frozenset(classes), fields.get('href', '')


def _ddg_tokens(page):
    """Forward lexical events; comments/raw script/style content never surface."""
    i, n = 0, len(page)
    while i < n:
        mark = _DDG_MARK.search(page, i)
        stop = mark.start() if mark else n
        if stop > i:
            yield ('data', '', None, i, stop)
        if stop == n:
            return
        i = stop
        if page.startswith('<!--', i):
            stop = page.find('-->', i + 4)
            if stop < 0:
                return
            i = stop + 3
            continue
        char = page[i + 1:i + 2]
        if not (char in ('/', '!', '?') or (char.isascii() and char.isalpha())):
            yield ('data', '', None, i, i + 1)
            i += 1
            continue
        end, name, closing, empty = _tag(page, i)
        if name in _RAW_END and not closing:
            cursor = end
            while True:
                match = _RAW_END[name].search(page, cursor)
                if not match:
                    end = n
                    break
                end, close_name, is_close, unused = _tag(page, match.start())
                if is_close and close_name == name:
                    break
                cursor = end
            yield ('barrier', name, None, i, end)
        elif not name:
            yield ('barrier', '', None, i, end)
        elif closing:
            yield ('end', name, None, i, end)
        else:
            yield ('empty' if empty or name in _DDG_VOID else 'start', name,
                   _ddg_attrs(page, i, end), i, end)
        i = end


def _ddg_url(href):
    if len(href) > _DDG_HREF:
        return None
    # Keep legacy relative-link unwrapping, double unquote, case-sensitive
    # prefix filtering and duplicates. Discovery strings are not fetch approval.
    if href.startswith('/l/?'):
        href = urllib.parse.unquote(urllib.parse.parse_qs(
            urllib.parse.urlparse(href).query, max_num_fields=64).get('uddg', [href])[0])
    return href if href.startswith('http') and len(href) <= _DDG_HREF else None


class _DDGParser:
    """One candidate, bounded structure stack; complete records only."""
    def __init__(self, page, maximum):
        self.page, self.maximum = page, maximum
        self.stack, self.results = [], []
        self.serial = 0
        self.candidate = None
        self.state = 'outside'
        self.anchor = None
        self.record_titles = set()  # At most the bounded active record ancestors.

    def reset(self):
        self.candidate, self.anchor, self.state = None, None, 'outside'

    def scope(self):
        return next((entry[1] for entry in reversed(self.stack) if entry[2]), None)

    def parent(self, title=False):
        for tag, identity, record, wrapper in reversed(self.stack):
            if title and wrapper:
                continue
            return identity
        return 0

    def run(self):
        for kind, name, attrs, start, end in _ddg_tokens(self.page):
            if kind == 'data':
                if self.candidate and self.state in ('title', 'snippet'):
                    self.candidate[self.state].add(self.page, start, end)
                elif self.candidate and self.candidate['scope'] is None and self.state == 'awaiting':
                    # Only whitespace/comments may separate a legacy flat pair.
                    if _DDG_NONSPACE.search(self.page, start, end):
                        self.reset()
                continue
            if kind == 'barrier':
                if self.candidate and self.candidate['scope'] is None:
                    self.reset()
                continue
            if kind == 'end':
                at = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == name), None)
                if at is None:
                    if self.candidate and self.candidate['scope'] is None:
                        self.reset()
                    continue
                popped = self.stack[at:]
                ids = {entry[1] for entry in popped}
                was_anchor = self.anchor in ids
                if was_anchor and self.candidate:
                    if name != 'a' or self.stack[at][1] != self.anchor:
                        self.reset()
                    elif self.state == 'title':
                        self.state, self.anchor = 'awaiting', None
                    elif self.state == 'snippet':
                        c = self.candidate
                        self.results.append({'title': c['title'].value(), 'url': c['url'], 'snippet': c['snippet'].value()})
                        self.reset()
                        del c  # Do not retain completed candidate buffers in loop locals.
                        if len(self.results) == self.maximum:
                            return self.results
                if self.candidate and self.candidate['scope'] is None and self.state == 'awaiting' and not was_anchor and not all(entry[3] for entry in popped):
                    self.reset()
                if self.candidate and (self.candidate['parent'] in ids or self.candidate['scope'] in ids):
                    self.reset()
                self.record_titles.difference_update(ids)
                del self.stack[at:]
                continue
            classes, href = attrs
            is_record = name in ('div', 'article', 'li', 'tr') and 'result' in classes
            is_title = name == 'a' and 'result__a' in classes
            is_snippet = name == 'a' and 'result__snippet' in classes
            if is_title and is_snippet:
                self.reset()
                is_title = is_snippet = False
            if is_record:
                self.reset()
            if self.candidate and self.candidate['scope'] is None and self.state == 'awaiting' and not (is_title or is_snippet):
                self.reset()
            if name == 'a' and self.anchor is not None:
                self.reset()  # Nested/missing anchor closure cannot inherit text/URL.
                previous = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == 'a'), None)
                if previous is not None:
                    del self.stack[previous:]
            parent, scope = self.parent(title=is_title), self.scope()
            if is_title:
                self.reset()
                ambiguous = scope is not None and scope in self.record_titles
                if scope is not None:
                    self.record_titles.add(scope)
                url = _ddg_url(href)
                if not ambiguous and url is not None and kind != 'empty':
                    self.candidate = {'url': url, 'title': _DDGText(_DDG_TITLE),
                                      'snippet': _DDGText(_DDG_SNIPPET), 'parent': parent, 'scope': scope}
                    self.state = 'title'
            elif is_snippet:
                if not (self.candidate and self.state == 'awaiting' and self.candidate['parent'] == parent and self.candidate['scope'] == scope and kind != 'empty'):
                    self.reset()
                else:
                    self.state = 'snippet'
            self.serial += 1
            if kind == 'start':
                if len(self.stack) >= _DDG_DEPTH:
                    raise ValueError('search markup nesting limit exceeded')
                self.stack.append((name, self.serial, is_record, name in ('h2', 'h3') and 'result__title' in classes))
                if self.candidate and self.state in ('title', 'snippet') and (is_title or is_snippet):
                    self.anchor = self.serial
        return self.results


def _parse_ddg(page, max_results):
    if type(max_results) is not int or not 1 <= max_results <= 50:
        raise ValueError('search result limit must be between 1 and 50')
    if len(page) > MAX_DECODED_BYTES:
        raise ValueError('search response exceeds decoded input limit')
    return _DDGParser(page, max_results).run()


def _search_duckduckgo(query: str, max_results: int = 8) -> list[dict]:
    if type(max_results) is not int or not 1 <= max_results <= 50:
        raise ValueError('search result limit must be between 1 and 50')
    url = 'https://html.duckduckgo.com/html/?' + urllib.parse.urlencode({'q': query})
    page = read_public_url(url).decode('utf-8', errors='replace')
    return _parse_ddg(page, max_results)


def _search_tavily(query: str, max_results: int) -> list[dict]:
    if type(max_results) is not int or not 1 <= max_results <= 20:
        raise SpendingBlocked("Tavily request exceeds bounded result envelope")
    key = os.environ["TAVILY_API_KEY"]
    body = json.dumps({"query": query, "max_results": max_results,
                       "search_depth": "basic", "include_usage": True}).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    def send():
        with _open_tavily(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    guard = SpendingGuard.default()
    guard.require_canonical()
    data = guard.invoke_tavily(send)
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
            except SpendingBlocked:
                raise
            except Exception as exc:
                errors.append(f"Tavily: {exc}")
        if not results and not os.environ.get("TAVILY_API_KEY"):
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
