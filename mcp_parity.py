"""Tools that let an HTTP brain work like a CLI brain (PARITY_TOOLS_v1, docs/plans/api-adapter-parity.md): a CLI
brain brings Edit, Glob and Skill of its own; an HTTP brain (OpenRouter, omniroute ...) has only what the host hands
it. Kept beside mcp_server.py like web_tool.py; every path and write rule is the server's own (it is passed in), so
edit_file refuses exactly what write_file refuses.

  edit_file   {path, old_string, new_string, replace_all?}   Claude's Edit contract: old_string occurs exactly once,
                                                              or replace_all; the result must pass write_file's rules
  find_files  {path, pattern}                                 glob under an allowlisted directory, secret names skipped
  skill       {action: list | load, name?}                    the workspace's skills (.agents/skills/<name>/SKILL.md)
"""
from __future__ import annotations

import re
from pathlib import Path

NAMES = ("edit_file", "find_files", "skill")
TOOL_DEFS = [
    {
        "name": "edit_file",
        "description": "Replace text in a file under the write allowlist: old_string must occur exactly once (or "
                       "set replace_all). Same rules as write_file. Prefer this to rewriting a whole file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "find_files",
        "description": "Find files by glob pattern (e.g. **/*.md) under an allowlisted directory (capped)",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}},
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "skill",
        "description": "The workspace's skills: action=list (names and what each is for), action=load (one "
                       "skill's instructions by name). Load a skill before doing the kind of work it covers.",
        "inputSchema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["list", "load"]}, "name": {"type": "string"}},
            "required": ["action"],
        },
    },
]
FIND_CAP = 200
SKILL_CHARS = 40_000
_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DESCRIPTION = re.compile(r"(?ms)^description:\s*([|>][-+]?\s*\n(.*?)(?=^\S)|(.*?)$)")


def _skills_dir(srv) -> Path:
    return Path(srv.DATA) / "workspace" / ".agents" / "skills"


def call(name: str, args: dict, srv) -> dict:
    env = srv.envelope
    args = args or {}
    if name == "edit_file":
        return _edit(args, srv, env)
    if name == "find_files":
        return _find(args, srv, env)
    if name == "skill":
        return _skill(args, srv, env)
    return env(False, "unknown tool: %s" % name, None)


def _edit(args: dict, srv, env) -> dict:
    path = srv._resolve_target_path(args.get("path"))
    old = str(args.get("old_string") or "")
    new = str(args.get("new_string") if args.get("new_string") is not None else "")
    if not old:
        return env(False, "old_string is empty", None)
    if old == new:
        return env(False, "old_string and new_string are the same", None)
    if not path.is_file():
        return env(False, "not a file", None)
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    every = args.get("replace_all") is True
    if count == 0:
        return env(False, "old_string not found", None)
    if count > 1 and not every:
        return env(False, "old_string occurs %d times; add context to make it unique or set replace_all" % count, None)
    updated = text.replace(old, new) if every else text.replace(old, new, 1)
    refused = srv._write_refusal(path, updated)
    if refused:
        return env(False, refused[0], refused[1])
    srv._atomic_write(path, updated)
    return env(True, "edited", {"path": str(path.resolve()), "replacements": count if every else 1})


def _find(args: dict, srv, env) -> dict:
    path = srv._resolve_target_path(args.get("path"))
    pattern = str(args.get("pattern") or "").strip()
    if not pattern or pattern.startswith("/") or ".." in Path(pattern).parts:
        return env(False, "pattern must be relative, without ..", None)
    if not srv._is_under(path, srv._read_roots()):
        return env(False, "path not allowlisted", None)
    if not path.is_dir():
        return env(False, "not a directory", None)
    found = []
    for p in path.glob(pattern):
        rel = p.relative_to(path).parts
        if any(srv.SECRET_NAME_RE.search(x) or x in (".git", "node_modules", "@eaDir") for x in rel):
            continue
        if p.is_file():
            found.append(str(p))
            if len(found) >= FIND_CAP:
                return env(True, "capped", {"files": found, "capped": True})
    return env(True, "ok", {"files": sorted(found), "capped": False})


def _skill(args: dict, srv, env) -> dict:
    root = _skills_dir(srv)
    action = str(args.get("action") or "")
    if action == "list":
        out = []
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            f = d / "SKILL.md"
            if d.is_dir() and f.is_file():
                m = _DESCRIPTION.search(f.read_text(encoding="utf-8", errors="replace")[:4000])
                desc = re.sub(r"\s+", " ", ((m.group(2) or m.group(3)) if m else "")).strip()[:300]
                out.append({"name": d.name, "description": desc})
        return env(True, "ok", {"skills": out})
    if action == "load":
        name = str(args.get("name") or "")
        if not _SKILL_NAME.match(name):
            return env(False, "bad skill name", None)
        f = root / name / "SKILL.md"
        if not f.is_file():
            return env(False, "no such skill: %s" % name, None)
        text = f.read_text(encoding="utf-8", errors="replace")
        refs = sorted(p.relative_to(f.parent).as_posix() for p in f.parent.rglob("*") if p.is_file() and p != f)[:50]
        return env(True, "ok", {"name": name, "path": str(f), "content": srv._scrub_text(text[:SKILL_CHARS]),
                                "truncated": len(text) > SKILL_CHARS, "files": refs})
    return env(False, "action must be list or load", None)
