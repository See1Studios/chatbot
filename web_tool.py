"""The `web` tool (WEB_TOOL_v1): read a page and search the web, for brains that bring no web of their own. A CLI
brain (claude, agy, codex, grok) has web tools built in; an HTTP-route brain (OpenRouter, omniroute ...) has only the
tools the host hands it. Provider-neutral: one MCP tool, whichever model calls it.

  web {"action": "read", "url": "https://...", "max_chars": 20000}   the page as text: title + readable body, capped
  web {"action": "search", "query": "...", "limit": 5}               results [{title, url, snippet}]

Backends borrow what agent-reach (this host's research router, the best web user here) settled on, as keyless
services rather than its CLI, so a shipped engine has them too:
  read    CHATBOT_WEB_READER  "jina" (default: Jina Reader, clean text even for script-drawn pages, then the host's
                              own fetch if it fails) or "direct" (the host's fetch only)
  search  CHATBOT_WEB_SEARCH  "auto" (default: Exa's hosted MCP search, then DuckDuckGo's no-key lite page), "exa",
                              "duckduckgo" or "off"

Public internet only. A URL whose host resolves to a loopback, private, link-local, tailnet (100.64/10) or any other
non-global address is refused -- before connecting and again at every redirect -- so a model cannot read the host's
own services (the chat's sessions, private ones included) through this tool.
Closed in a private session: its queries and addresses would carry private talk to outside servers
(docs/plans/private-security.md).
Standard library only.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple

NAMES = ("web",)
TOOL_DEFS = [{
    "name": "web",
    "description": "The web, for facts you do not have. action=read: a public page as text (url). action=search: "
                   "result links (query, limit<=10). Public internet only; closed in private sessions.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "search"]},
            "url": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "max_chars": {"type": "integer"},
        },
        "required": ["action"],
    },
}]

PRIVATE_CLOSED = "private session: the web is closed here, so private talk never leaves in a query or an address."
USER_AGENT = "Mozilla/5.0 (compatible; PrivateEngine-web/1)"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
READ_CHARS = 20_000
SEARCH_URL = "https://lite.duckduckgo.com/lite/?q=%s"   # the html/ page answers this host with a captcha (2026-09-29)
EXA_MCP = "https://mcp.exa.ai/mcp"
JINA = "https://r.jina.ai/"
_TAILNET = ipaddress.ip_network("100.64.0.0/10")


class WebError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- public addresses

def _resolve(host: str) -> List[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def check_public(url: str, resolve: Callable[[str], List[str]] = None) -> str:
    """The URL if it is http(s) to a host whose every address is global; WebError otherwise."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError("only http(s) addresses")
    host = parts.hostname
    try:
        addrs = (resolve or _resolve)(host)
    except OSError:
        raise WebError("cannot resolve %s" % host)
    if not addrs:
        raise WebError("cannot resolve %s" % host)
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%", 1)[0])
        if not ip.is_global or ip in _TAILNET or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise WebError("not a public address: %s" % host)
    return url


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, resolve):
        super().__init__()
        self.resolve = resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        check_public(newurl, self.resolve)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, resolve=None, opener=None, data: Optional[bytes] = None, headers: Optional[Dict] = None) -> Tuple[bytes, str, str]:
    """(body up to MAX_BYTES, content type, final url) of a public page; a POST when `data` is given."""
    check_public(url, resolve)
    opener = opener or urllib.request.build_opener(_CheckedRedirects(resolve))
    h = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*;q=0.5"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.read(MAX_BYTES), r.headers.get("Content-Type", ""), r.geturl()
    except WebError:
        raise
    except urllib.error.HTTPError as e:
        raise WebError("HTTP %d" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise WebError("unreachable: %s" % getattr(e, "reason", e))


# ---------------------------------------------------------------------------------------------- page -> text

_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head"}
_BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header",
          "footer", "blockquote", "pre", "table", "ul", "ol", "dd", "dt", "hr"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_text(html: str) -> Tuple[str, str]:
    """(title, readable text) of an HTML page: scripts and styles dropped, blocks as lines, blank runs collapsed."""
    p = _Text()
    p.feed(html)
    lines = [re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in "".join(p.parts).split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return re.sub(r"\s+", " ", p.title).strip(), text


def _decode(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def read_jina(url: str, resolve=None, opener=None) -> Dict:
    """Jina Reader: the page as clean text, script-drawn pages included. The target is checked first, so no house
    address is ever handed to a third party either."""
    check_public(url, resolve)
    body, _, _ = fetch(JINA + url, resolve, opener, headers={"X-No-Cache": "true", "Accept": "text/plain"})
    text = body.decode("utf-8", errors="replace")
    title = (re.search(r"^Title:\s*(.*)$", text, re.M) or [None, ""])[1].strip()
    m = re.search(r"^Markdown Content:\s*\n", text, re.M)
    content = text[m.end():].strip() if m else text.strip()
    if not content:
        raise WebError("empty page")
    return {"url": url, "title": title, "text": content, "via": "jina"}


def read(url: str, max_chars: int = READ_CHARS, resolve=None, opener=None) -> Dict:
    cap = max(1000, min(int(max_chars or READ_CHARS), 50_000))
    if (os.environ.get("CHATBOT_WEB_READER") or "jina").strip().lower() == "jina":
        try:
            r = read_jina(url, resolve, opener)
            return dict(r, text=r["text"][:cap], truncated=len(r["text"]) > cap)
        except WebError as e:
            if str(e).startswith(("not a public", "only http", "cannot resolve")):
                raise   # the address itself is refused; the direct fetch would refuse it too
    return read_direct(url, cap, resolve, opener)


def read_direct(url: str, max_chars: int = READ_CHARS, resolve=None, opener=None) -> Dict:
    body, ctype, final = fetch(url, resolve, opener)
    kind = (ctype or "").split(";")[0].strip().lower()
    if kind in ("text/html", "application/xhtml+xml", ""):
        title, text = html_text(_decode(body, ctype))
    elif kind.startswith("text/") or kind in ("application/json", "application/xml"):
        title, text = "", _decode(body, ctype)
    else:
        raise WebError("not a text page (%s)" % kind)
    cap = max(1000, min(int(max_chars or READ_CHARS), 50_000))
    return {"url": final, "title": title, "text": text[:cap], "truncated": len(text) > cap, "via": "direct"}


# ---------------------------------------------------------------------------------------------- search

class _DuckResults(HTMLParser):
    """Results of DuckDuckGo's no-key pages: a.result-link / a.result__a (title + link), .result-snippet /
    .result__snippet (text) -- the lite page and the html page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: List[Dict] = []
        self._field = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and ("result-link" in cls or "result__a" in cls):
            self.results.append({"title": "", "url": _undirect(a.get("href") or ""), "snippet": ""})
            self._field = "title"
        elif ("result-snippet" in cls or "result__snippet" in cls) and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "td", "div"):
            self._field = ""

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _undirect(href: str) -> str:
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<the real one>."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
    return q["uddg"][0] if "uddg" in q else href


def parse_duckduckgo(html: str, limit: int) -> List[Dict]:
    p = _DuckResults()
    p.feed(html)
    out = []
    for r in p.results:
        r = {k: re.sub(r"\s+", " ", v).strip() for k, v in r.items()}
        if r["url"].startswith(("http://", "https://")) and r not in out:
            out.append(r)
    return out[:limit]


def parse_exa(text: str, limit: int) -> List[Dict]:
    """Exa's search text -- blocks of "Title: / URL: / ... Highlights:" -- as results."""
    out = []
    for block in re.split(r"(?m)^(?=Title: )", text or ""):
        url = re.search(r"(?m)^URL:\s*(\S+)", block)
        if not url:
            continue
        title = (re.search(r"(?m)^Title:\s*(.*)$", block) or [None, ""])[1].strip()
        hl = block.split("Highlights:", 1)[1] if "Highlights:" in block else ""
        snippet = re.sub(r"\s+", " ", hl.replace("...", " ")).strip()[:300]
        out.append({"title": title, "url": url.group(1), "snippet": snippet})
    return out[:limit]


def search_exa(q: str, limit: int, resolve=None, opener=None) -> List[Dict]:
    """Exa's hosted MCP search (keyless), one JSON-RPC tools/call; the answer may come as an SSE message."""
    import json
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "web_search_exa", "arguments": {"query": q, "numResults": limit}}}
    body, _, _ = fetch(EXA_MCP, resolve, opener, data=json.dumps(rpc).encode("utf-8"),
                       headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    raw = body.decode("utf-8", errors="replace")
    payload = next((ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")), raw.strip())
    try:
        msg = json.loads(payload)
    except ValueError:
        raise WebError("search answered in a form it does not read")
    if msg.get("error"):
        raise WebError("search refused: %s" % (msg["error"].get("message") or msg["error"]))
    text = "\n".join(c.get("text", "") for c in (msg.get("result") or {}).get("content") or [] if c.get("type") == "text")
    return parse_exa(text, limit)


def search(query: str, limit: int = 5, resolve=None, opener=None) -> Dict:
    backend = (os.environ.get("CHATBOT_WEB_SEARCH") or "auto").strip().lower()
    if backend == "off":
        raise WebError("search is off on this host (CHATBOT_WEB_SEARCH=off)")
    chain = {"auto": ["exa", "duckduckgo"], "exa": ["exa"], "duckduckgo": ["duckduckgo"]}.get(backend)
    if not chain:
        raise WebError("unknown search backend: %s" % backend)
    q = (query or "").strip()
    if not q:
        raise WebError("empty query")
    limit = max(1, min(int(limit or 5), 10))
    last = None
    for name in chain:
        try:
            if name == "exa":
                results = search_exa(q, limit, resolve, opener)
            else:
                body, ctype, _ = fetch(SEARCH_URL % urllib.parse.quote_plus(q), resolve, opener)
                results = parse_duckduckgo(_decode(body, ctype), limit)
            if results:
                return {"query": q, "backend": name, "results": results}
            last = WebError("no results")
        except WebError as e:
            last = e
    raise last or WebError("no results")


# ---------------------------------------------------------------------------------------------- the tool

def call(args: Dict, envelope, private: bool = False) -> Dict:
    if private:
        return envelope(False, PRIVATE_CLOSED, None)
    args = args or {}
    action = str(args.get("action") or "")
    try:
        if action == "read":
            return envelope(True, "ok", read(str(args.get("url") or ""), args.get("max_chars") or READ_CHARS))
        if action == "search":
            return envelope(True, "ok", search(str(args.get("query") or ""), args.get("limit") or 5))
        return envelope(False, "action must be read or search", None)
    except WebError as e:
        return envelope(False, str(e), None)
