"""Self-status, workspace rules, project skills, and MCP configuration helpers.

Extracted from server.py during modular refactoring.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from artifact_manager import _atomic_write_text
from host_config import HOME, WORKSPACE
from instructions import extract_yaml_desc

try:  # the candidate count and last review come from the core; the tab still loads without it
    import observations
except Exception:  # noqa: BLE001
    observations = None

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
               "provider": c.get("provider"), "user": (c.get("detail") or {}).get("user", "")}
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
                                            str(b.get("until") or ""))
                return 200, {"ok": True, "observation": done}
    except observations.ScanBroken as e:
        return 500, {"ok": False, "error": str(e)}
    except observations.ObservationError as e:
        return (404 if str(e).startswith("no such observation") else 400), {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}


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
    return {
        "ok": True,
        "memory": mem_info,
        "rules": rules,
        "skills": _get_workspace_skills(),
        "host_skill_library_count": len(_get_available_skills()),
        "mcp": mcp_list,
        "hooks": {
            "supported": True,
            "configured": [
                {"name": name, "enabled": bool(cfg.get("enabled", True)), "events": [k for k in cfg.keys() if k != "enabled"]}
                for name, cfg in _read_hooks_config().items()
            ],
            "note": "Antigravity는 PreToolUse/PostToolUse/PreInvocation/PostInvocation/Stop 5종 훅을 지원하지만, 이 워크스페이스는 관찰을 호스트가 직접 수집하므로 프로바이더 훅을 설정하지 않습니다.",
        },
        "plugins": {
            "note": "이 스택에서 '플러그인'은 별도 개념이 아니라 스킬(.agents/skills) + MCP로 표현됨.",
        },
        "observation": _observation_summary(),
    }
