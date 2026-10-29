"""Webpage retrieval: fetch a URL and extract readable text.

Only the fetched text may be cited. If a fetch fails, the tool reports the
failure and the executor must not cite that URL. Extracted text is capped
so a single page cannot flood the model's context.
"""
from __future__ import annotations

import html as html_lib
import re
from .safe_http import read_public_url, MAX_DECODED_BYTES

from ..security.permissions import Permission
from .base import Tool, ToolResult

_USER_AGENT = "Mozilla/5.0 (compatible; autonomous-research/1.0)"
_MAX_CHARS = 12000


# Fixed-grammar patterns only: no nested quantifiers or suffix-wide substitutions.
_EVENTS = re.compile(r'[<&]')
_WORDS = re.compile(r'\s+|[^\s]+')
_ENTITY = re.compile(r'&(?:#[xX][0-9a-fA-F]{1,8};?|#[0-9]{1,10};?|[A-Za-z][A-Za-z0-9]{0,31};?)')
_RAW_END = {name: re.compile('</' + name, re.I | re.A) for name in ('script', 'style')}
_MAX_TITLE = 1024
_MAX_TAG = 8192
_MAX_NAME = 64
_HTML_SPACE = ' \t\r\n\f'


class _Text:
    """Bounded normalized output, with whitespace deferred until a next word."""
    def __init__(self, cap):
        self.cap, self.size, self.parts, self.space = cap, 0, [], False

    def add(self, source, start=0, end=None):
        if self.size >= self.cap:
            return
        for match in _WORDS.finditer(source, start, len(source) if end is None else end):
            a, b = match.span()
            if source[a].isspace():
                self.space = self.size > 0
                continue
            if self.space and self.size < self.cap:
                self.parts.append(' ')
                self.size += 1
            self.space = False
            take = min(b - a, self.cap - self.size)
            if take:
                self.parts.append(source[a:a + take])
                self.size += take
            if self.size >= self.cap:
                break

    def value(self):
        return ''.join(self.parts).rstrip()


def _tag(raw, start):
    """Scan at most _MAX_TAG chars; ignore attributes without storing a list."""
    n = len(raw)
    i = start + 1
    closing = i < n and raw[i] == '/'
    if closing:
        i += 1
    begin = i
    while i < n and (raw[i].isascii() and (raw[i].isalnum() or raw[i] in '-_:')):
        i += 1
        if i - begin > _MAX_NAME:
            raise ValueError('HTML tag name exceeds extraction limit')
    name = raw[begin:i].lower()
    declaration = begin < n and raw[begin] in '!?' and not closing
    if not name and not declaration:
        raise ValueError('malformed HTML tag')
    if name and i < n and raw[i] not in _HTML_SPACE + '/>':
        raise ValueError('malformed HTML tag name')
    quote = None
    limit = min(n, start + _MAX_TAG)
    while i < limit:
        char = raw[i]
        if quote:
            if char == quote:
                quote = None
        elif char in '\"\'':
            if closing:
                raise ValueError('malformed HTML closing tag')
            quote = char
        elif char == '>':
            return i + 1, name, closing, i > start and raw[i - 1] == '/'
        elif char == '<' or (closing and char not in _HTML_SPACE):
            raise ValueError('malformed HTML tag')
        i += 1
    raise ValueError('incomplete or oversized HTML tag')


def _extract_html(raw):
    """Forward, bounded-state text scanner, not a browser DOM or HTML sanitizer.

    Raw script/style content is suppressed until its own closing tag or EOF.
    Incomplete/oversized ordinary tags fail, with no raw-text error fallback.
    """
    if len(raw) > MAX_DECODED_BYTES:
        raise ValueError('HTML input exceeds extraction limit')
    visible, title = _Text(_MAX_CHARS), _Text(_MAX_TITLE)
    title_seen = in_title = False
    suppressed = None
    i, n = 0, len(raw)
    # Preserve the existing parser-failure injection boundary. This first scan
    # is a fixed character class, not a backtracking tag/extraction grammar.
    first_event = re.search(r'[<&]', raw)
    while i < n:
        if suppressed:
            end = _RAW_END[suppressed].search(raw, i)
            if end is None:
                break
            after, name, closing, empty = _tag(raw, end.start())
            i = after
            if closing and name == suppressed:
                suppressed = None
                visible.add(' ')
            continue
        event = first_event if i == 0 else _EVENTS.search(raw, i)
        end = event.start() if event else n
        visible.add(raw, i, end)
        if in_title:
            title.add(raw, i, end)
        if end == n:
            break
        i = end
        if raw[i] == '&':
            entity = _ENTITY.match(raw, i)
            stop = entity.end() if entity else i + 1
            # Overlong/malformed references remain literal; never feed an
            # unbounded numeric string into html.unescape/int conversion.
            if entity and raw[stop - 1] != ';' and stop < n and raw[stop].isascii() and raw[stop].isalnum():
                stop = i + 1
            piece = html_lib.unescape(raw[i:stop]) if stop > i + 1 else '&'
            visible.add(piece)
            if in_title:
                title.add(piece)
            i = stop
            continue
        if raw.startswith('<!--', i):
            end = raw.find('-->', i + 4)
            if end < 0:
                break
            i = end + 3
            visible.add(' ')
            continue
        next_char = raw[i + 1:i + 2]
        is_tag = next_char in ('/', '!', '?') or (next_char.isascii() and next_char.isalpha())
        if not is_tag:
            visible.add('<')
            if in_title:
                title.add('<')
            i += 1
            continue
        after, name, closing, empty = _tag(raw, i)
        i = after
        visible.add(' ')
        if name in _RAW_END and not closing:
            suppressed = name  # Script/style self-closing syntax does not leak raw content.
        elif name == 'title':
            if closing:
                in_title = False
            elif not title_seen:
                title_seen, in_title = True, not empty
    return title.value(), visible.value()


def fetch_url(url: str) -> tuple[str, str]:
    """Return bounded (title, readable text); failed fetches never become evidence."""
    raw = read_public_url(url).decode('utf-8', errors='replace')
    return _extract_html(raw)


def fetch_page_tool() -> Tool:
    def run(args: dict) -> ToolResult:
        url = str(args.get("url", ""))
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
