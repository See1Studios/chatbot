#!/usr/bin/env python3
"""Optional DiskStation host-plugin for mcp_server.py -- Sphere/Hermes/NamuWatcher
sibling-service awareness that only makes sense on THIS NAS's specific
directory layout (~/wiki, ~/.hermes, ~/projects, /volume1/web/sphere-*).

mcp_server.py imports this module by name (`import nas_mcp_host`) if present and
not disabled via NAS_MCP_HOST_PLUGIN=0. A different deployment simply doesn't
ship this file (or unsets the env var) and gets the generic core tool set
only -- see docs/plans/chatbot-host-portability.md Phase 1.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, List, Optional

import mcp_server as _srv  # attributes are read at call time, so a test that replaces _srv._run reaches these tools too
from mcp_server import HOME, SERVICES, WEB_ROOT, envelope, _scrub_text

CENTRAL_HOST_MCP_URL = os.environ.get("CENTRAL_HOST_MCP_URL", "http://127.0.0.1:3015/mcp")

WEB = WEB_ROOT
HERMES = HOME / ".hermes"
WIKI = HOME / "wiki"
PROJECTS = HOME / "projects"

EXTRA_ALLOW_ROOTS: List[Path] = [
    WIKI.resolve(),
    (WEB / "art").resolve(),
    (WEB / "lore").resolve(),
    (WEB / "sound").resolve(),
    (WEB / "tech").resolve(),
]

EXTRA_READ_ROOTS: List[Path] = EXTRA_ALLOW_ROOTS + [
    PROJECTS.resolve(),
    WEB.resolve(),
]

EXTRA_CMD_PREFIXES = (
    str(SERVICES / "namuwatcher-ctl.sh"),
    "namuwatcher-ctl.sh",
    str(HERMES / "scripts" / "hermes-lifecycle.sh"),
    str(HOME / ".local" / "bin" / "hermes"),
    "hermes status",
    "hermes --version",
)

PORT_CHAT_HINT = int(os.environ.get("AGY_CHAT_PORT", "3011"))  # informational only (list_services)
PORT_HOST_MCP = int(os.environ.get("NAS_HOST_MCP_PORT", "3015"))

# What service_ctl and list_services know about. The chatbot itself may only be asked for `status`: its lifecycle
# is for a person (chatbot-ctl.sh repair), never for a tool. nas-mcp is the central Host MCP (:3015).
SERVICE_CTLS = {
    "chatbot": str(SERVICES / "chatbot-ctl.sh"),
    "nas-mcp": str(SERVICES / "nas-mcp-ctl.sh"),
}

EXTRA_SERVICE_CTLS = {
    "namuwatcher": str(SERVICES / "namuwatcher-ctl.sh"),
}

EXTRA_SERVICE_LIST_ITEMS = [
    {"name": "namuwatcher", "port": 3010},
]

EXTRA_TOOL_DEFS = [
    {"name": "ping_nas", "description": "Health ping for chatbot MCP (:3012)", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "list_services",
        "description": "List known Sphere/NAS service ctl scripts and ports",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "service_ctl",
        "description": "Run ctl script action: start|stop|restart|status (chatbot: status only)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {"type": "string", "enum": ["start", "stop", "restart", "status"]},
            },
            "required": ["name", "action"],
        },
    },
    {
        "name": "sphere_hub_status",
        "description": "Check Sphere hub / web + chat health endpoints",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "factory_status",
        "description": "Summarize Hermes factory runs directory",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "hermes_status",
        "description": "Hermes lifecycle / process status summary",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "wiki",
        "description": "Wiki SSOT (~/wiki) plus tech catalog, not MEMORY.md. search lists compact hits; get returns one digest; sources lists the vault and feeds. Call only when judging a topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "get", "sources"]},
                "query": {"type": "string"},
                "id": {"type": "string"},
                "limit": {"type": "integer"},
                "source": {"type": "string"},
                "kind": {"type": "string"},
            },
            "required": ["action"],
        },
    },
]

# Vault is ~/wiki (tests patch WIKI). /tech catalog is an intake source on the same tool.
TECH_ROOT = WEB / "tech"
_SEARCH_LIMIT_DEFAULT = 8
_SEARCH_LIMIT_MAX = 20
_QUERY_MIN = 2
_DIGEST_MAX = 600
_WIKI_HEAD = 8192
_WIKI_SKIP = {"raw", "public", ".obsidian", ".git", "@eaDir", "node_modules"}
_index_cache: dict = {"mtime": None, "cards": []}
_wiki_cache: dict = {"stamp": None, "pages": []}


def _tech_index_path() -> Path:
    return TECH_ROOT / "data" / "index.json"


def _tech_card_path(card_id: str) -> Path:
    return TECH_ROOT / "data" / "cards" / (card_id + ".json")


def _tech_registry_path() -> Path:
    return TECH_ROOT / "data" / "sources" / "registry.json"


def _load_index() -> List[dict]:
    p = _tech_index_path()
    try:
        st = p.stat()
    except OSError:
        return []
    if _index_cache["mtime"] == st.st_mtime_ns and _index_cache["cards"]:
        return _index_cache["cards"]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cards = list(raw.get("cards") or [])
    _index_cache["mtime"] = st.st_mtime_ns
    _index_cache["cards"] = cards
    return cards


def _compact_hit(row: dict) -> dict:
    tags = [t for t in (row.get("tags") or []) if isinstance(t, str)][:8]
    return {
        "id": row.get("id") or "",
        "title": row.get("title") or row.get("title_kr") or "",
        "kind": row.get("kind") or "",
        "source": row.get("source") or "",
        "url": row.get("url") or "",
        "tags": tags,
    }


def _haystack(row: dict) -> str:
    tags = " ".join(t for t in (row.get("tags") or []) if isinstance(t, str))
    extra = str(row.get("hay") or "")
    return " ".join(
        str(row.get(k) or "") for k in ("id", "title", "title_kr", "kind", "source")
    ) + " " + tags + " " + extra


def _fm_fields(block: str) -> dict:
    meta: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if key == "tags":
            tags: List[str] = []
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1].strip()
                if inner:
                    tags = [t.strip().strip("\"'") for t in inner.split(",") if t.strip()]
            elif raw:
                tags = [raw.strip("\"'")]
            else:
                while i < len(lines) and lines[i].lstrip().startswith("-"):
                    tags.append(lines[i].lstrip()[1:].strip().strip("\"'"))
                    i += 1
            meta["tags"] = [t for t in tags if t]
        elif key in ("title", "description", "type"):
            meta[key] = raw.strip("\"'")
    return meta


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _first_para(body: str, limit: int) -> str:
    chunks: List[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">") or s.startswith("```") or s.startswith("!["):
            if chunks:
                break
            continue
        chunks.append(s)
        text = " ".join(chunks)
        if len(text) >= limit:
            return text[:limit]
    return " ".join(chunks)[:limit]


def _page_kind(rel: str) -> str:
    parts = rel.split("/")
    top = parts[0] if parts else ""
    if top == "articles":
        return "article"
    if top == "concepts":
        return "concept"
    if top == "comparisons":
        return "comparison"
    if top == "entities":
        return "entity"
    if top == "trends":
        return "trend"
    if len(parts) >= 2 and parts[1] == "articles":
        return "series_article"
    if len(parts) >= 2 and parts[1] == "wiki":
        return "series_wiki"
    stem = Path(rel).stem.lower()
    if stem == "index":
        return "index"
    if stem in ("schema", "readme", "log", "book"):
        return "meta"
    return "page"


def _wiki_stamp() -> Optional[tuple]:
    if not WIKI.is_dir():
        return None
    n = 0
    mx = 0
    for root, dirs, files in os.walk(WIKI):
        dirs[:] = [d for d in dirs if d not in _WIKI_SKIP]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            n += 1
            try:
                mx = max(mx, (Path(root) / fn).stat().st_mtime_ns)
            except OSError:
                pass
    return (n, mx)


def _parse_page(path: Path, rel: str) -> Optional[dict]:
    try:
        text = path.read_bytes()[:_WIKI_HEAD].decode("utf-8", errors="replace")
    except OSError:
        return None
    meta: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            meta = _fm_fields(text[3:end])
            body = text[end + 4 :]
    title = meta.get("title") or _first_heading(body) or Path(rel).stem.replace("-", " ")
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    digest = (meta.get("description") or _first_para(body, _DIGEST_MAX))[:_DIGEST_MAX]
    pid = rel[:-3] if rel.endswith(".md") else rel
    return {
        "id": pid,
        "title": title,
        "kind": meta.get("type") or _page_kind(rel),
        "source": "wiki",
        "url": rel,
        "tags": tags,
        "digest": digest,
        "hay": digest,
        "path": rel,
        "_corpus": "wiki",
    }


def _load_pages() -> List[dict]:
    stamp = _wiki_stamp()
    if _wiki_cache["stamp"] == stamp:
        return _wiki_cache["pages"]
    pages: List[dict] = []
    if stamp is not None:
        root = WIKI.resolve()
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _WIKI_SKIP]
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                path = Path(dirpath) / fn
                rel = path.relative_to(root).as_posix()
                row = _parse_page(path, rel)
                if row:
                    pages.append(row)
    _wiki_cache["stamp"] = stamp
    _wiki_cache["pages"] = pages
    return pages


def _wiki_file(page_id: str) -> Optional[Path]:
    rel = (page_id or "").strip().lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return None
    if not rel.endswith(".md"):
        rel += ".md"
    root = WIKI.resolve()
    path = (WIKI / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _source_ok(src: str, corpus: str, source_val: str, tags: List[str]) -> bool:
    if src == "wiki":
        return corpus == "wiki"
    if src == "catalog":
        return corpus == "catalog"
    if src:
        blob = (source_val + " " + " ".join(tags)).lower()
        return src in blob
    return True


def _wiki_search(query: str, limit: int, source: str, kind: str) -> dict:
    q = (query or "").strip().lower()
    if len(q) < _QUERY_MIN:
        return envelope(False, "query must be at least %d characters" % _QUERY_MIN, None)
    tokens = [t for t in re.split(r"\s+", q) if t]
    pages = _load_pages()
    cards = _load_index()
    if not pages and not cards and not WIKI.is_dir() and not _tech_index_path().exists():
        return envelope(False, "wiki vault is missing", None)
    src = (source or "").strip().lower()
    kn = (kind or "").strip().lower()
    hits = []
    rows: List[dict] = []
    if src != "catalog":
        rows.extend(pages)
    if src != "wiki":
        for card in cards:
            row = dict(card)
            row["_corpus"] = "catalog"
            rows.append(row)
    for row in rows:
        corpus = str(row.get("_corpus") or "catalog")
        tags = [t for t in (row.get("tags") or []) if isinstance(t, str)]
        if not _source_ok(src, corpus, str(row.get("source") or ""), tags):
            continue
        if kn and kn != str(row.get("kind") or "").lower():
            continue
        if all(tok in _haystack(row).lower() for tok in tokens):
            hits.append(_compact_hit(row))
            if len(hits) >= limit:
                break
    return envelope(True, "ok", {"hits": hits, "count": len(hits)})


def _catalog_get(cid: str) -> Optional[dict]:
    p = _tech_card_path(cid)
    card = None
    if p.is_file():
        try:
            card = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            card = None
    if not isinstance(card, dict):
        for row in _load_index():
            if row.get("id") == cid:
                card = row
                break
    if not isinstance(card, dict):
        return None
    judge = card.get("judge") if isinstance(card.get("judge"), dict) else {}
    out = _compact_hit(card)
    out["title_kr"] = card.get("title_kr") or ""
    out["origin_ref"] = card.get("origin_ref") or ""
    out["digest"] = (card.get("digest") or "")[:_DIGEST_MAX]
    out["judge"] = judge.get("status") or ""
    return out


def _page_get(page_id: str) -> Optional[dict]:
    path = _wiki_file(page_id)
    if path is None or not path.is_file():
        for row in _load_pages():
            if row.get("id") == page_id:
                out = _compact_hit(row)
                out["digest"] = (row.get("digest") or "")[:_DIGEST_MAX]
                out["path"] = row.get("path") or ""
                return out
        return None
    rel = path.relative_to(WIKI.resolve()).as_posix()
    row = _parse_page(path, rel)
    if not row:
        return None
    out = _compact_hit(row)
    out["digest"] = (row.get("digest") or "")[:_DIGEST_MAX]
    out["path"] = rel
    return out


def _wiki_get(item_id: str) -> dict:
    cid = (item_id or "").strip()
    if not cid:
        return envelope(False, "id is required", None)
    item = _page_get(cid)
    if item is None:
        item = _catalog_get(cid)
    if item is None:
        return envelope(False, "unknown id: " + cid, None)
    return envelope(True, "ok", {"item": item})


def _wiki_sources() -> dict:
    items = [
        {
            "id": "wiki",
            "name": "wiki vault",
            "kind": "vault",
            "status": "active" if WIKI.is_dir() else "missing",
            "quality": "ssot",
        },
        {
            "id": "catalog",
            "name": "tech catalog",
            "kind": "catalog",
            "status": "active" if _tech_index_path().is_file() else "missing",
            "quality": "intake",
        },
    ]
    p = _tech_registry_path()
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        for s in raw.get("sources") or []:
            if not isinstance(s, dict):
                continue
            items.append({
                "id": s.get("id") or "",
                "name": s.get("name") or "",
                "kind": s.get("kind") or "",
                "status": s.get("status") or "",
                "quality": s.get("quality") or "",
            })
    return envelope(True, "ok", {"sources": items, "count": len(items)})


def _wiki(args: dict) -> dict:
    action = str(args.get("action") or "").strip()
    if action == "search":
        try:
            limit = int(args.get("limit") or _SEARCH_LIMIT_DEFAULT)
        except (TypeError, ValueError):
            limit = _SEARCH_LIMIT_DEFAULT
        limit = max(1, min(_SEARCH_LIMIT_MAX, limit))
        return _wiki_search(
            str(args.get("query") or ""),
            limit,
            str(args.get("source") or ""),
            str(args.get("kind") or ""),
        )
    if action == "get":
        return _wiki_get(str(args.get("id") or ""))
    if action == "sources":
        return _wiki_sources()
    return envelope(False, "unknown action (search, get, sources)", None)


def _service_ctls() -> dict:
    ctls = dict(SERVICE_CTLS)
    ctls.update(EXTRA_SERVICE_CTLS)
    return ctls


def _call_central_host_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> Optional[str]:
    """Attempts to delegate tool execution to central Host MCP (:3015/mcp).
    Returns text result string if successful, or None if unavailable/failed."""
    try:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1000000,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            CENTRAL_HOST_MCP_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # Parse SSE or raw JSON-RPC
            lines = raw.strip().splitlines()
            data_line = ""
            for line in lines:
                if line.startswith("data:"):
                    data_line = line[5:].strip()
                    break
            if not data_line and raw.strip().startswith("{"):
                data_line = raw.strip()
            if data_line:
                parsed = json.loads(data_line)
                res = parsed.get("result") or {}
                if not res and parsed.get("error"):
                    return f"Error from central MCP: {parsed.get('error')}"
                contents = res.get("content") or []
                texts = [c.get("text") for c in contents if isinstance(c, dict) and c.get("text")]
                if texts:
                    return "\n".join(texts)
                if "structuredContent" in res:
                    return str(res["structuredContent"])
    except Exception:
        pass
    return None


def call_tool(name: str, args: dict) -> Optional[dict]:
    """Returns None for a tool name this plugin doesn't own (core keeps
    looking / falls through to "unknown tool"), or an envelope dict."""
    if name == "ping_nas":
        return envelope(True, "pong", {"host": _srv.HOST, "port": _srv.PORT, "ts": time.time()})

    if name == "list_services":
        items = []
        for n, ctl in _service_ctls().items():
            items.append({"name": n, "ctl": ctl})
        items.append({"name": "chat", "port": PORT_CHAT_HINT, "url": f"http://127.0.0.1:{PORT_CHAT_HINT}/healthz"})
        items.append({"name": "chatbot-mcp", "port": _srv.PORT, "url": f"http://127.0.0.1:{_srv.PORT}/healthz"})
        items.append({"name": "nas-mcp", "port": PORT_HOST_MCP, "url": f"http://127.0.0.1:{PORT_HOST_MCP}/healthz"})
        items += list(EXTRA_SERVICE_LIST_ITEMS)
        return envelope(True, "ok", {"services": items})

    if name == "service_ctl":
        svc = str(args.get("name") or "").strip()
        action = str(args.get("action") or "").strip()
        if action not in ("start", "stop", "restart", "status"):
            return envelope(False, "invalid action", None)
        if svc == "chatbot" and action != "status":
            return envelope(False, "chatbot lifecycle is not available to tools (status only)", None)
        ctl = _service_ctls().get(svc)
        if not ctl or not Path(ctl).exists():
            return envelope(False, f"unknown service: {svc}", None)
        if action != "status" and Path(ctl).resolve().name == "chatbot-ctl.sh":
            return envelope(False, "chatbot lifecycle is not available to tools (status only)", None)
        code, out, err = _srv._run([ctl, action], timeout=60)
        return envelope(code == 0, "ran" if code == 0 else "failed", {"code": code, "stdout": out, "stderr": err})

    if name == "sphere_hub_status":
        remote = _call_central_host_mcp("sphere_hub_status", {})
        if remote is not None:
            return envelope(True, "ok", {"central_mcp": True, "output": remote})
        checks: dict = {}
        for label, url in (
            ("chat", "http://127.0.0.1:3011/healthz"),
            ("chatbot_mcp", "http://127.0.0.1:3012/healthz"),
            ("nas_mcp", f"http://127.0.0.1:{PORT_HOST_MCP}/healthz"),
            ("namuwatcher", "http://127.0.0.1:3010/"),
        ):
            code, out, err = _srv._run(["curl", "-fsS", "-m", "3", url], timeout=5)
            checks[label] = {"ok": code == 0, "body": (out or err)[:500]}
        hub = WEB / "index.html"
        checks["hub_index"] = {"exists": hub.exists(), "path": str(hub)}
        return envelope(True, "ok", checks)

    if name == "factory_status":
        remote = _call_central_host_mcp("factory_status", {})
        if remote is not None:
            return envelope(True, "ok", {"central_mcp": True, "output": remote})
        factory = HERMES / "factory"
        runs = factory / "runs"
        data: dict = {"factory": str(factory), "exists": factory.exists()}
        if runs.exists():
            kids = sorted(runs.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
            data["recent_runs"] = [
                {"name": k.name, "mtime": k.stat().st_mtime, "type": "dir" if k.is_dir() else "file"}
                for k in kids
            ]
        log = factory / "factory-log.jsonl"
        if log.exists():
            data["log_tail"] = _scrub_text(log.read_text(encoding="utf-8", errors="replace")[-4000:])
        return envelope(True, "ok", data)

    if name == "wiki":
        return _wiki(args)

    if name == "hermes_status":
        remote = _call_central_host_mcp("hermes_status", {})
        if remote is not None:
            return envelope(True, "ok", {"central_mcp": True, "output": remote})
        life = HERMES / "scripts" / "hermes-lifecycle.sh"
        info: dict = {"hermes_home": str(HERMES), "lifecycle_script": str(life), "exists": life.exists()}
        hermes_bin = HOME / ".local" / "bin" / "hermes"
        if hermes_bin.exists():
            code, out, err = _srv._run([str(hermes_bin), "status"], timeout=25)
            info["hermes_status"] = {"code": code, "stdout": out[-4000:], "stderr": err[-2000:]}
        elif life.exists():
            code, out, err = _srv._run([str(life), "status"], timeout=25)
            info["lifecycle"] = {"code": code, "stdout": out[-4000:], "stderr": err[-2000:]}
        else:
            code, out, err = _srv._run(["bash", "-lc", "ps aux | head -1; ps aux | grep -i hermes | grep -v grep | head -20"], timeout=10)
            info["ps"] = out
        return envelope(True, "ok", info)

    return None
