"""Self-status, workspace rules, project skills, and MCP configuration helpers.

Extracted from server.py during modular refactoring.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote

from artifact_manager import _atomic_write_text
from host_config import HOME, ROOT, WORKSPACE
from instructions import extract_yaml_desc

try:  # the candidate count and last review come from the core; the tab still loads without it
    import observations
except Exception:  # noqa: BLE001
    observations = None

try:  # which instruction files the operator may edit from the status tab: the protected-path registry decides
    import evolution
except Exception:  # noqa: BLE001
    evolution = None

try:  # long-term memory is saved under its own lock and size cap
    import memory_store
except Exception:  # noqa: BLE001
    memory_store = None

try:  # ticket decisions from the status tab; the core holds every rule
    import tickets
except Exception:  # noqa: BLE001
    tickets = None

RULE_FILES = ["AGENTS.md", "PERSONA.md", "PROJECT.md", "SELF-MODIFY.md"]
WS_SKILLS_DIR = WORKSPACE / ".agents" / "skills"
_SKILLS_CACHE = {"ts": 0.0, "data": []}
_extract_yaml_desc = extract_yaml_desc


def _get_available_skills() -> list:
    now = time.time()
    if now - _SKILLS_CACHE["ts"] < 60 and _SKILLS_CACHE["data"]:
        return _SKILLS_CACHE["data"]
    skills_dir = HOME / ".agents" / "skills"
    results = []
    if skills_dir.exists():
        for p in sorted(skills_dir.iterdir()):
            if p.name.startswith((".", "_")):
                continue
            if p.is_dir() or p.is_symlink():
                sm = p / "SKILL.md"
                desc = ""
                if sm.exists():
                    try:
                        desc = _extract_yaml_desc(sm.read_text(encoding="utf-8", errors="replace")[:2000])
                    except Exception:
                        pass
                results.append({"name": p.name, "desc": desc, "template": f"/skill {p.name} "})
    _SKILLS_CACHE["ts"] = now
    _SKILLS_CACHE["data"] = results
    return results


def _rule_path(name: str) -> Optional[Path]:
    if name not in RULE_FILES:
        return None
    return WORKSPACE / name


def _skill_desc(skill_md: Path) -> str:
    try:
        return _extract_yaml_desc(skill_md.read_text(encoding="utf-8", errors="replace")[:2000])
    except Exception:
        return ""


def _get_workspace_skills() -> list:
    """Project-scoped skills (nas-sphere, ...).
    Disabled skills are stored with a leading underscore (mirrors _get_available_skills' own skip rule)."""
    results = []
    if WS_SKILLS_DIR.exists():
        for p in sorted(WS_SKILLS_DIR.iterdir()):
            if not p.is_dir():
                continue
            enabled = not p.name.startswith("_")
            name = p.name[1:] if not enabled else p.name
            results.append({"name": name, "enabled": enabled, "desc": _skill_desc(p / "SKILL.md")})
    return results


_POPULAR_DESC_MAX = 80


def _popular_slash_skills() -> list:
    """Slash-menu pin list: enabled workspace skills only. The host library (~/.agents) is search-only."""
    out = []
    for s in _get_workspace_skills():
        if not s.get("enabled"):
            continue
        name = s["name"]
        desc = re.sub(r"\s+", " ", (s.get("desc") or "").strip())
        if len(desc) > _POPULAR_DESC_MAX:
            desc = desc[: _POPULAR_DESC_MAX - 1].rstrip() + "…"
        out.append({
            "name": "/skill " + name,
            "skill": name,
            "label": name,
            "desc": desc or name,
            "template": "/skill " + name + " ",
        })
    return out


def _hooks_config_path() -> Path:
    return WORKSPACE / ".agents" / "hooks.json"


def _read_hooks_config() -> dict:
    p = _hooks_config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
    return {}


def _mcp_config_path() -> Path:
    return WORKSPACE / ".gemini" / "config" / "mcp_config.json"


def _read_mcp_config() -> dict:
    p = _mcp_config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and isinstance(cfg.get("mcpServers"), dict):
                return cfg
        except Exception:
            pass
    return {"mcpServers": {}}


def _write_mcp_config(cfg: dict) -> None:
    _atomic_write_text(_mcp_config_path(), json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def _observation_summary() -> dict:
    """Counts for the status tab: open and total observations, candidates since the last review, last review."""
    obs_root = WORKSPACE / "skill-observations"
    obs_dir = obs_root / "observation-log"
    n_open = 0
    n_total = 0
    if obs_dir.exists():
        for f in obs_dir.glob("*.md"):
            n_total += 1
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:400]
                if re.search(r"status:\s*open", head):
                    n_open += 1
            except Exception:
                pass
    n_cand = 0
    last_review = "never"
    if observations is not None:
        try:
            n_cand = len(observations.unreviewed_candidates(obs_root))
            last_review = observations.last_review(obs_root)
        except Exception:
            pass
    return {"open_observations": n_open, "total_observations": n_total, "unreviewed_candidates": n_cand,
            "last_review_date": last_review}


_CANDIDATE_ROWS = 20


def _observation_overview(obs_root) -> dict:
    """Everything the status tab needs to manage observations: the items in the log (open, parked, and those
    resolved today that are waiting to be archived) and the host's candidates since the last review."""
    entries = observations.scan(obs_root)
    cands = observations.unreviewed_candidates(obs_root)
    recent = [{"ref": "candidate:%s" % c.get("epoch"), "ts": c.get("ts"), "signal": c.get("signal"),
               "provider": c.get("provider"), "user": (c.get("detail") or {}).get("user", ""),
               "summary": (c.get("detail") or {}).get("summary", "")}
              for c in cands[-_CANDIDATE_ROWS:]][::-1]
    return {"ok": True, "last_review": observations.last_review(obs_root), "observations": entries,
            "unreviewed_candidates": len(cands), "candidates": recent}


def observation_api(method: str, path: str, body: Optional[dict]) -> Optional[Tuple[int, dict]]:
    """The /api/observations routes. Returns None when `path` is not one of ours, else (status code, JSON).
    Changing anything (POST) is the caller's to gate; this only routes to the core, which holds the rules."""
    if not (path == "/api/observations" or path.startswith("/api/observations/")):
        return None
    if observations is None:
        return 503, {"ok": False, "error": "observation core unavailable"}
    obs_root = WORKSPACE / "skill-observations"
    rest = path[len("/api/observations"):].strip("/")
    b = body or {}
    try:
        if method == "GET":
            if rest == "":
                return 200, _observation_overview(obs_root)
            if rest.isdigit():
                return 200, {"ok": True, "observation": observations.get(obs_root, int(rest))}
        elif method == "POST":
            if rest == "reviewed":
                return 200, {"ok": True, "last_review": observations.mark_reviewed(obs_root, b.get("summary"))}
            m = re.fullmatch(r"(\d+)/resolve", rest)
            if m:
                done = observations.resolve(obs_root, int(m.group(1)), str(b.get("status") or ""), b.get("resolution"),
                                            str(b.get("until") or ""), by="operator")  # the page's own buttons: the user
                return 200, {"ok": True, "observation": done}
    except observations.ScanBroken as e:
        return 500, {"ok": False, "error": str(e)}
    except observations.ObservationError as e:
        return (404 if str(e).startswith("no such observation") else 400), {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}


# -------------------------------------------- agent instructions (STATUS_INSTRUCTIONS_v1)
# Everything the chat agent reads as instructions is shown in the status tab, whole. The operator may edit what the
# protected-path registry (protected_paths.json) leaves unprotected; the rest is read-only, and says why.

INSTRUCTION_FILES = [  # (id, title, path relative to the workspace, layer)
    ("AGENTS.md", "헌장", "AGENTS.md", "always"),
    ("PERSONA.md", "페르소나", "PERSONA.md", "always"),
    ("MEMORY.md", "장기 기억", "memory/MEMORY.md", "always"),
    ("PROJECT.md", "작업 절차", "PROJECT.md", "on_demand"),
    ("SELF-MODIFY.md", "자기수정 경계", "SELF-MODIFY.md", "on_demand"),
    ("PRIVATE.md", "사적 모드", "PRIVATE.md", "on_demand"),
]
_LAYER_ORDER = {"always": 0, "on_demand": 1, "private": 2}   # private: read only in a private session


def _instruction_files() -> list:
    items = [(i, t, WORKSPACE / rel, layer) for i, t, rel, layer in INSTRUCTION_FILES]
    for c in _characters():
        label = c["name"] or c["id"]
        pd = c["role"] == "pd"                       # the chatbot's own card is read every turn
        items.append(("characters/%s/card.json" % c["id"], ("페르소나 카드 (%s)" if pd else "캐릭터 카드 (%s)") % label,
                      WORKSPACE / "characters" / c["id"] / "card.json", "always" if pd else "on_demand"))
        if not pd:                                   # the chatbot's memory is still memory/MEMORY.md
            items.append(("characters/%s/memory.md" % c["id"], "캐릭터 기억 (%s)" % label,
                          WORKSPACE / "characters" / c["id"] / "memory.md", "on_demand"))
        items.append(("characters/%s/visual.md" % c["id"], "외형 락 (%s)" % label,
                      WORKSPACE / "characters" / c["id"] / "visual.md", "on_demand"))
        items.append(("characters/%s/private-memory.md" % c["id"], "사적 기억 (%s)" % label,
                      WORKSPACE / "characters" / c["id"] / "private-memory.md", "private"))
    return items


def _characters() -> list:
    try:
        import characters
        return characters.listing(WORKSPACE)
    except Exception:  # noqa: BLE001
        return []


def _protected_why(path: Path) -> Optional[str]:
    if evolution is None:
        return "보호 목록을 읽을 수 없음"
    return evolution.match_protected(ROOT, path)


def agent_instructions() -> list:
    """Every instruction the chat agent reads: files (editable unless protected) and generated layers (read-only)."""
    out = []
    for iid, title, path, layer in _instruction_files():
        if not path.is_file():
            continue
        try:
            st = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        why = _protected_why(path)
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:
            rel = str(path)
        out.append({"id": iid, "title": title, "path": rel, "layer": layer, "kind": "file", "editable": why is None,
                    "reason": "보호 경로(%s): 터미널이나 승인된 티켓으로만 바꿉니다" % why if why else "",
                    "size": st.st_size, "mtime": st.st_mtime, "content": text})
    try:
        import instructions as I
        generated = [("skills-index", "스킬 목록", I._skills_text(), "워크스페이스 스킬 폴더에서 자동으로 만듭니다"),
                     ("status-badge", "상태 배지", I._status_text(), "열린 관찰과 최근 점검에서 자동으로 만듭니다")]
    except Exception:  # noqa: BLE001
        generated = []
    for iid, title, text, why in generated:
        out.append({"id": iid, "title": title, "path": "", "layer": "always", "kind": "generated", "editable": False,
                    "reason": why, "size": len((text or "").encode("utf-8")), "mtime": 0, "content": text or ""})
    out.sort(key=lambda x: _LAYER_ORDER[x["layer"]])
    return out


def instructions_api(method: str, path: str, body: Optional[dict]) -> Optional[Tuple[int, dict]]:
    """/api/instructions: GET lists everything; PUT /api/instructions/<id> saves an editable file. A PUT is the
    operator editing from the status tab, so the caller must have checked that it came from this server's own page."""
    if not (path == "/api/instructions" or path.startswith("/api/instructions/")):
        return None
    rest = unquote(path[len("/api/instructions"):]).strip("/")   # ids like experts/staff/expert.md arrive encoded
    if method == "GET" and rest == "":
        return 200, {"ok": True, "items": agent_instructions()}
    if method != "PUT" or not rest:
        return 404, {"ok": False, "error": "not found"}
    found = [x for x in _instruction_files() if x[0] == rest]
    if not found:
        return 404, {"ok": False, "error": "no such instruction file (generated layers are read-only)"}
    _, _, fp, _ = found[0]
    why = _protected_why(fp)
    if why:
        return 403, {"ok": False, "error": "read-only: protected (%s)" % why}
    content = (body or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        return 400, {"ok": False, "error": "content required"}
    if fp.name == "card.json":       # a character card must stay a Character Card V2
        try:
            card = json.loads(content)
            ok = isinstance(card, dict) and card.get("spec") == "chara_card_v2" and isinstance(card.get("data"), dict)
        except ValueError:
            ok = False
        if not ok:
            return 400, {"ok": False, "error": "a character card must be Character Card V2 JSON (spec chara_card_v2)"}
    if fp == WORKSPACE / "memory" / "MEMORY.md":
        if memory_store is None:
            return 503, {"ok": False, "error": "memory core unavailable"}
        if len(content.encode("utf-8")) > memory_store.MAX_BYTES:
            return 400, {"ok": False, "error": "MEMORY.md is limited to %d bytes" % memory_store.MAX_BYTES}
        try:
            with memory_store._Locked(fp.parent):
                memory_store._write(fp.parent, content)
        except memory_store.MemoryRefused as e:
            return 409, {"ok": False, "error": str(e)}
    else:
        if fp.exists():
            try:
                fp.with_name("%s.bak-selfstatus-%s" % (fp.name, time.strftime("%Y%m%d%H%M%S"))).write_text(
                    fp.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            except OSError:
                pass
        _atomic_write_text(fp, content)
    return 200, {"ok": True, "id": rest, "bytes": len(content.encode("utf-8"))}


# ------------------------------------------------------------ team (EXPERTS_STATUS_v1, CHARACTERS_v1)
# The 팀 tab: the PD's confirmation brain list (pd-brain.json) and each character's work brains (its card,
# extensions.chatbot.brains.work), docs/plans/multi-agent-worktree-delegation.md §11-12. The operator edits them here;
# the PD cannot. Which providers a brain may name comes from the delegation runner's registry.

_MAX_BRAINS = 6
_CHAR_ID = re.compile(r"^char_[0-7][0-9a-hjkmnp-tv-z]{25}$")


def _runner_providers() -> list:
    try:
        from delegation import runner
        return sorted(runner().PROVIDERS)
    except Exception:  # noqa: BLE001
        return []


def _read_chain(path: Path) -> list:
    try:
        chain = json.loads(path.read_text(encoding="utf-8")).get("chain")
        return chain if isinstance(chain, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def experts_overview() -> dict:
    try:
        import identity
        pd = identity.get_identity("")
    except Exception:  # noqa: BLE001
        pd = {"name": "PD"}
    providers = _runner_providers()
    models = {}
    try:
        from adapters import AGENT_ADAPTERS
        for pid in providers:
            if pid in AGENT_ADAPTERS:
                models[pid] = list(AGENT_ADAPTERS[pid].known_models())[:40]
    except Exception:  # noqa: BLE001
        pass
    chars = _characters()
    out = [] if any(c["role"] == "pd" for c in chars) else [   # before the move: the PD's list in pd-brain.json
        {"id": "pd", "role": "pd", "name": pd["name"], "title": "PD 확인",
         "chain": _read_chain(WORKSPACE / "pd-brain.json"), "path": "data/workspace/pd-brain.json",
         "editable": _protected_why(WORKSPACE / "pd-brain.json") is None}]
    try:
        import characters
    except Exception:  # noqa: BLE001
        characters = None
    for c in sorted(chars, key=lambda c: c["role"] != "pd"):     # the PD first
        cp = WORKSPACE / "characters" / c["id"] / "card.json"
        disp = characters.ext(c["card"]).get("display") or {} if characters else {}
        title = "PD 확인" if c["role"] == "pd" else disp.get("title", "")
        out.append({"id": c["id"], "role": c["role"], "name": c["name"], "title": title,
                    "chain": characters.brains(c["card"], "work") if characters else [],
                    "path": "data/workspace/characters/%s/card.json" % c["id"], "editable": _protected_why(cp) is None})
    return {"ok": True, "experts": out, "providers": providers, "models": models}


def _clean_chain(raw) -> Tuple[Optional[list], str]:
    providers = _runner_providers()
    if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_BRAINS:
        return None, "a brain list has 1-%d entries" % _MAX_BRAINS
    chain = []
    for n, b in enumerate(raw, 1):
        if not isinstance(b, dict) or b.get("provider") not in providers:
            return None, "brain %d: provider must be one of %s" % (n, ", ".join(providers))
        model = str(b.get("model") or "").strip()
        try:
            timeout = int(b.get("timeout") or 0)
        except (TypeError, ValueError):
            timeout = -1
        if len(model) > 80 or not re.fullmatch(r"[A-Za-z0-9._:/-]*", model) or not 0 <= timeout <= 3600:
            return None, "brain %d: model (letters, digits, ._:/-) or timeout (0-3600 s) is off" % n
        entry = {"provider": b["provider"], "model": model}
        if timeout:
            entry["timeout"] = timeout
        chain.append(entry)
    return chain, ""


def experts_api(method: str, path: str, body: Optional[dict]) -> Optional[Tuple[int, dict]]:
    """GET /api/experts; PUT /api/experts/<id>/brain {chain} (`pd` = the PD's confirmation, else a character id).
    A PUT is the operator editing from the team tab, so the caller must have checked that it came from this
    server's own page."""
    if not (path == "/api/experts" or path.startswith("/api/experts/")):
        return None
    rest = path[len("/api/experts"):].strip("/")
    if method == "GET" and rest == "":
        return 200, experts_overview()
    m = re.fullmatch(r"(pd|char_[0-9a-z]{26})/brain", rest)
    if method != "PUT" or not m:
        return 404, {"ok": False, "error": "not found"}
    who = m.group(1)
    target = WORKSPACE / "pd-brain.json" if who == "pd" else WORKSPACE / "characters" / who / "card.json"
    if who != "pd" and (not _CHAR_ID.match(who) or not target.is_file()):
        return 404, {"ok": False, "error": "no such character"}
    why = _protected_why(target)
    if why:
        return 403, {"ok": False, "error": "read-only: protected (%s)" % why}
    chain, err = _clean_chain((body or {}).get("chain"))
    if chain is None:
        return 400, {"ok": False, "error": err}
    if who == "pd":
        _atomic_write_text(target, json.dumps({"chain": chain}, ensure_ascii=False, indent=2) + "\n")
    else:
        import characters
        card = characters.load(who, WORKSPACE)
        characters.ext(card) or card["data"].setdefault("extensions", {}).setdefault(characters.EXT, {})
        characters.ext(card).setdefault("brains", {})["work"] = chain
        characters.save(who, card, WORKSPACE)
    return 200, {"ok": True, "id": who, "chain": chain}


def ticket_api(method: str, path: str, body: Optional[dict]) -> Optional[Tuple[int, dict]]:
    """The /api/tickets routes: list, detail, and the operator's decisions (approve, decline, reopen).
    Returns None when `path` is not one of ours. A POST is the operator deciding (the chat page's
    `/ticket ...` command), so the caller must have checked that it came from this server's own page;
    the core still refuses anything but those three decisions and applies its own state rules."""
    if not (path == "/api/tickets" or path.startswith("/api/tickets/")):
        return None
    if tickets is None:
        return 503, {"ok": False, "error": "ticket core unavailable"}
    data = WORKSPACE.parent
    rest = path[len("/api/tickets"):].strip("/")
    try:
        if method == "GET":
            if rest == "":
                return 200, {"ok": True, "tickets": [tickets.get(data, r["id"]) for r in tickets.list_tickets(data)]}
            if rest.isdigit():
                return 200, {"ok": True, "ticket": tickets.get(data, int(rest))}
        elif method == "POST":
            m = re.fullmatch(r"(\d+)/(approve|decline|reopen)", rest)
            if m:
                done = getattr(tickets, m.group(2))(data, int(m.group(1)), operator=tickets.OPERATOR_UI)
                return 200, {"ok": True, "ticket": done}
    except tickets.TicketError as e:
        return (404 if str(e).startswith("no such ticket") else 400), {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}



def _mcp_tool_summaries(entry: dict) -> list:
    """Best-effort tool list for Status tab (name + short description only)."""
    name = str(entry.get("name") or "")
    url = str(entry.get("serverUrl") or "").rstrip("/")
    # Local chatbot MCP (:3012 / name nas) — in-process, authoritative.
    if name == "nas" or ":3012/" in (url + "/") or url.endswith(":3012") or url.endswith(":3012/mcp"):
        try:
            import mcp_server
            return [
                {"name": t.get("name") or "", "description": (t.get("description") or "").strip()}
                for t in (mcp_server.tool_defs() or [])
                if t.get("name")
            ]
        except Exception as e:  # noqa: BLE001
            return [{"name": "(조회 실패)", "description": f"{type(e).__name__}: {e}"}]
    if not url.startswith("http"):
        return []
    # Remote HTTP MCP — short tools/list probe (never blocks Status long).
    try:
        import urllib.error
        import urllib.request
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        tools = ((data.get("result") or {}).get("tools")) or []
        out = []
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            out.append({
                "name": str(t.get("name")),
                "description": str(t.get("description") or "").strip(),
            })
        return out
    except Exception:
        return []


def _self_status() -> dict:
    rules = []
    for name in RULE_FILES:
        fp = WORKSPACE / name
        if not fp.exists():
            continue
        try:
            st = fp.stat()
            text = fp.read_text(encoding="utf-8", errors="replace")
            preview = "\n".join(text.splitlines()[:3])
        except Exception:
            st = None
            preview = ""
        rules.append({
            "name": name,
            "size": st.st_size if st else 0,
            "mtime": st.st_mtime if st else 0,
            "preview": preview,
        })
    mcp_cfg = _read_mcp_config()
    mcp_list = [dict(v, name=k) for k, v in mcp_cfg.get("mcpServers", {}).items()]
    mem_fp = WORKSPACE / "memory" / "MEMORY.md"
    mem_info = None
    if mem_fp.exists():
        try:
            st = mem_fp.stat()
            text = mem_fp.read_text(encoding="utf-8", errors="replace")
            mem_info = {
                "name": "MEMORY.md",
                "size": st.st_size,
                "mtime": st.st_mtime,
                "content": text,
            }
        except Exception:
            pass
    for entry in mcp_list:
        tools = _mcp_tool_summaries(entry)
        entry["tools"] = tools
        entry["tool_count"] = len(tools)
    hooks_cfg = _read_hooks_config()
    return {
        "ok": True,
        "memory": mem_info,
        "rules": rules,
        "skills": _get_workspace_skills(),
        "host_skill_library_count": len(_get_available_skills()),
        "mcp": mcp_list,
        "hooks": {
            "supported": True,
            "supported_events": [
                "PreToolUse",
                "PostToolUse",
                "PreInvocation",
                "PostInvocation",
                "Stop",
            ],
            "path": str(_hooks_config_path()),
            "configured": [
                {
                    "name": name,
                    "enabled": bool(cfg.get("enabled", True)),
                    "events": [k for k in cfg.keys() if k != "enabled"],
                }
                for name, cfg in hooks_cfg.items()
            ],
            "note": "Antigravity는 PreToolUse/PostToolUse/PreInvocation/PostInvocation/Stop 5종 훅을 지원하지만, 이 워크스페이스는 관찰을 호스트가 직접 수집하므로 프로바이더 훅을 설정하지 않습니다.",
        },
        "plugins": {
            "note": "이 스택에서 '플러그인'은 별도 개념이 아니라 스킬(.agents/skills) + MCP로 표현됨.",
        },
        "observation": _observation_summary(),
    }
