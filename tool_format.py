"""Tool-call/result log formatting. No session state.

Mirrored (by necessity, not shared code -- different language) by
static/app.js's formatToolCallClient/formatToolResultClient.
"""
from __future__ import annotations

from typing import Any

from host_config import HOME, WEB_ROOT


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s

def _short_path(p: str) -> str:
    if not p:
        return ""
    p = p.replace(str(HOME) + "/", "")
    p = p.replace(str(WEB_ROOT) + "/", "web/")
    return p

def _format_tool_call(name: str, args: dict) -> str:
    if not isinstance(args, dict):
        return name
    action = _clean_str(args.get("toolAction") or args.get("action"))
    summary = _clean_str(args.get("toolSummary") or args.get("summary") or args.get("description"))

    if name == "run_command":
        cmd = _clean_str(args.get("CommandLine") or args.get("command") or args.get("cmd"))
        if not cmd:
            return ""  # args not populated yet (streaming) — wait for the complete call, don't dedup-block it
        parts = [f"run_command: {cmd}"]
        if summary and summary.lower() != cmd.lower():
            parts.append(f"({summary})")
        elif action and action.lower() != cmd.lower():
            parts.append(f"({action})")
        return " ".join(parts)

    if name in ("view_file", "read_file"):
        raw_path = _clean_str(args.get("AbsolutePath") or args.get("TargetFile") or args.get("path") or args.get("file"))
        if not raw_path:
            return ""
        path = _short_path(raw_path)
        start = args.get("StartLine")
        end = args.get("EndLine")
        line_info = f" [L{start}-{end}]" if (start or end) else ""
        parts = [f"view_file: {path}{line_info}"]
        if summary:
            parts.append(f"({summary})")
        elif action:
            parts.append(f"({action})")
        return " ".join(parts)

    if name == "grep_search":
        q = _clean_str(args.get("Query") or args.get("query") or args.get("pattern"))
        if not q:
            return ""
        sp = _short_path(_clean_str(args.get("SearchPath") or args.get("path")))
        parts = [f"grep_search: '{q}' in {sp or '.'}"]
        if summary:
            parts.append(f"({summary})")
        return " ".join(parts)

    if name == "find_by_name":
        p = _clean_str(args.get("Pattern") or args.get("pattern"))
        if not p:
            return ""
        sd = _short_path(_clean_str(args.get("SearchDirectory") or args.get("directory") or args.get("path")))
        parts = [f"find_by_name: '{p}' in {sd or '.'}"]
        if summary:
            parts.append(f"({summary})")
        return " ".join(parts)

    if name == "list_dir":
        dp = _short_path(_clean_str(args.get("DirectoryPath") or args.get("path") or args.get("dir")))
        if not dp:
            return ""
        parts = [f"list_dir: {dp}"]
        if summary:
            parts.append(f"({summary})")
        return " ".join(parts)

    if name in ("replace_file_content", "edit_file"):
        raw_path = _clean_str(args.get("TargetFile") or args.get("path") or args.get("file"))
        if not raw_path:
            return ""
        tf = _short_path(raw_path)
        inst = _clean_str(args.get("Instruction") or summary or action)
        parts = [f"replace_file_content: {tf}"]
        if inst:
            parts.append(f"({inst})")
        return " ".join(parts)

    if name in ("write_to_file", "write_file"):
        raw_path = _clean_str(args.get("TargetFile") or args.get("path") or args.get("file"))
        if not raw_path:
            return ""
        tf = _short_path(raw_path)
        desc = _clean_str(args.get("Description") or summary or action)
        parts = [f"write_to_file: {tf}"]
        if desc:
            parts.append(f"({desc})")
        return " ".join(parts)

    if name in ("read_url_content", "fetch_url"):
        url = _clean_str(args.get("Url") or args.get("url"))
        if not url:
            return ""
        return f"read_url: {url}"

    if name in ("search_web", "web_search"):
        q = _clean_str(args.get("query") or args.get("Query"))
        if not q:
            return ""
        return f"search_web: '{q}'"

    if name == "call_mcp_tool":
        server = _clean_str(args.get("ServerName"))
        tool = _clean_str(args.get("ToolName"))
        if not server and not tool:
            return ""
        mcp_args = args.get("Arguments")
        mcp_desc = ""
        if isinstance(mcp_args, dict):
            for k in ("path", "command", "query", "action"):
                if k in mcp_args:
                    mcp_desc = f"{k}={mcp_args[k]}"
                    break
        return f"mcp: {server}/{tool}" + (f" ({mcp_desc})" if mcp_desc else "")

    target = ""
    for k in ("path", "file", "AbsolutePath", "TargetFile", "command", "CommandLine", "query", "Query", "pattern", "url", "Url", "DirectoryPath"):
        if k in args:
            target = _short_path(_clean_str(args[k]))
            break
    desc = summary or action
    res = f"{name}"
    if target:
        res += f": {target}"
    if desc and desc.lower() != target.lower():
        res += f" ({desc})"
    return res

def _format_tool_result(content: str) -> str:
    if not content:
        return ""
    lines = [l.strip() for l in str(content).splitlines() if l.strip()]
    filtered = [l for l in lines if not l.startswith("Created At:") and not l.startswith("Completed At:")]
    if not filtered:
        return "↳ 완료"
    first = filtered[0]
    if len(first) > 120:
        first = first[:117] + "..."
    if len(filtered) > 1:
        return f"↳ {first} (외 {len(filtered)-1}줄)"
    return f"↳ {first}"
