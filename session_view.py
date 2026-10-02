"""What a session shows (monolith-split split/C, moved from session.py as a mixin of AgentSession, like
turn_watchdog.py): its public view, the tool activity lines, the activity log, the artifacts gallery and the handover
summary. The paths and helpers that tests point elsewhere (SESSIONS, WORKSPACE, DATA, ...) are read from `session` on
every call, never copied at import."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Union

from session_weights import _billed_tokens, _current_context_tokens
from tool_format import _format_tool_call, _format_tool_result


def _session():
    import session
    return session


class SessionView:
    def _tool_summary(self, obj: dict) -> Union[dict, List[dict], None]:
        """Surface tool activity with detailed arguments and results."""
        SKIP_TOOL_NOISE = {"", "tool", "step", "step_update", "unknown", "agent_response"}
        if not hasattr(self, "_last_tool_sig"):
            self._last_tool_sig = None

        # 1. Antigravity PLANNER_RESPONSE with tool_calls
        tool_calls = obj.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            events = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = str(tc.get("name") or "").strip()
                    args = tc.get("args") or tc.get("input") or {}
                    if not isinstance(args, dict):
                        args = {}
                    text = _format_tool_call(name, args)
                    if text and text != self._last_tool_sig:
                        self._last_tool_sig = text
                        detail_str = json.dumps(args, ensure_ascii=False, indent=2) if args else ""
                        ev_item = {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "calling"}
                        if detail_str and len(detail_str) > 2:
                            ev_item["detail"] = detail_str[:4000]
                        events.append(ev_item)
            if events:
                return events

        # 2. Antigravity GENERIC tool execution result
        if obj.get("type") == "GENERIC" and isinstance(obj.get("content"), str) and obj.get("content").strip():
            raw_content = obj["content"].strip()
            res_summary = _format_tool_result(raw_content)
            if res_summary and res_summary != self._last_tool_sig:
                self._last_tool_sig = res_summary
                ev_res = {"event": "tool", "text": res_summary[:600], "title": "result", "kind": "result", "status": "done"}
                if len(raw_content) > len(res_summary) or "\n" in raw_content:
                    ev_res["detail"] = raw_content[:4000]
                return ev_res

        # 3. step_update format
        step = obj.get("step_update")
        if isinstance(step, dict):
            stype = str(step.get("step_type") or step.get("type") or "").strip()
            if stype in ("agent_response",):
                return None
            title = (
                step.get("title")
                or step.get("name")
                or step.get("tool")
                or step.get("tool_name")
                or step.get("function")
                or ""
            )
            step_args = {}
            for nest in (step.get("tool_call"), step.get("toolUse"), step.get("args"), step.get("input")):
                if isinstance(nest, dict):
                    title = title or nest.get("name") or nest.get("tool") or nest.get("Name") or ""
                    tc = nest.get("toolCall")
                    if not title and isinstance(tc, dict):
                        title = tc.get("name") or ""
                    step_args.update(nest)
            title = str(title or "").strip()
            status = str(step.get("status") or step.get("state") or "").strip()

            blob = json.dumps(step, ensure_ascii=False)
            if "generate_image" in blob.lower() or "image" in title.lower():
                for src in self._collect_new_images(self.turn_started_at or None):
                    url = self._stage_image(src)
                    if url and url not in self.pending_images:
                        self.pending_images.append(url)
                        self._emit({"event": "image", "text": url, "url": url, "name": src.name})

            if title and title.lower() not in SKIP_TOOL_NOISE:
                args_dict = step_args if step_args else step
                text = _format_tool_call(title, args_dict)
            else:
                args_dict = {}
                text = ""
                for k in ("command", "CommandLine", "path", "query", "text", "summary", "description"):
                    val = step.get(k)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()[:400]
                        break
                if not text and stype and stype.lower() not in SKIP_TOOL_NOISE:
                    text = stype
            if not text or text == self._last_tool_sig:
                return None
            self._last_tool_sig = text
            ev_step = {"event": "tool", "text": text[:600], "step_type": stype[:80], "title": title[:200] or stype[:80], "kind": "call", "status": status[:80]}
            if args_dict:
                d_str = json.dumps(args_dict, ensure_ascii=False, indent=2)
                if len(d_str) > 2:
                    ev_step["detail"] = d_str[:4000]
            # QUOTA_FAILFAST_v1: agy often parks for ~2min after error_message
            if stype == "error_message":
                hint = ""
                for k in ("error", "message", "text", "summary", "description", "detail"):
                    val = step.get(k)
                    if isinstance(val, str) and val.strip():
                        hint = val.strip()[:500]
                        break
                if not hint:
                    for nest in (step.get("result"), step.get("output"), step.get("content"), args_dict):
                        if isinstance(nest, dict):
                            for k in ("error", "message", "text"):
                                val = nest.get(k)
                                if isinstance(val, str) and val.strip():
                                    hint = val.strip()[:500]
                                    break
                        if hint:
                            break
                if hint:
                    ev_step["detail"] = hint
                    self._err_msg_hint = hint
                self._arm_error_message_failfast()
            return ev_step

        # 4. classic tool_use / tool_call / tool_result / tool_error
        ev = obj.get("event") or obj.get("type")
        if ev in ("tool_use", "tool_call"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            args = obj.get("args") or obj.get("input") or obj.get("parameters") or {}
            if not isinstance(args, dict):
                args = {}
            text = _format_tool_call(name, args) if args else f"{name}"
            if not text or text.lower() in SKIP_TOOL_NOISE:
                return None
            if text == self._last_tool_sig:
                return None
            self._last_tool_sig = text
            ev_call = {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": str(ev)}
            if args:
                d_str = json.dumps(args, ensure_ascii=False, indent=2)
                if len(d_str) > 2:
                    ev_call["detail"] = d_str[:4000]
            return ev_call

        if ev in ("tool_result", "tool_error"):
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            content = obj.get("output") or obj.get("content") or obj.get("result") or ""
            raw_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
            res_text = _format_tool_result(raw_str) if raw_str else f"{ev}: {name or 'done'}"
            if res_text == self._last_tool_sig:
                return None
            self._last_tool_sig = res_text
            ev_res = {"event": "tool", "text": res_text[:600], "title": name[:200] or "result", "kind": "result", "status": str(ev)}
            if raw_str and (len(raw_str) > len(res_text) or "\n" in raw_str):
                ev_res["detail"] = raw_str[:4000]
            return ev_res

        # 5. nested message tool_use / tool_result blocks
        msg = obj.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                events = []
                for part in content:
                    if isinstance(part, dict):
                        ptype = part.get("type")
                        if ptype == "tool_use":
                            name = str(part.get("name") or "").strip()
                            args = part.get("input") or {}
                            text = _format_tool_call(name, args if isinstance(args, dict) else {})
                            if text and text != self._last_tool_sig:
                                self._last_tool_sig = text
                                ev_tu = {"event": "tool", "text": text[:600], "title": name[:200], "kind": "call", "status": "tool_use"}
                                if isinstance(args, dict) and args:
                                    ev_tu["detail"] = json.dumps(args, ensure_ascii=False, indent=2)[:4000]
                                events.append(ev_tu)
                        elif ptype == "tool_result":
                            res = str(part.get("content") or part.get("output") or "")
                            text = _format_tool_result(res) if res else "↳ tool_result: 완료"
                            if text and text != self._last_tool_sig:
                                self._last_tool_sig = text
                                ev_tr = {"event": "tool", "text": text[:600], "title": "result", "kind": "result", "status": "tool_result"}
                                if res and (len(res) > len(text) or "\n" in res):
                                    ev_tr["detail"] = res[:4000]
                                events.append(ev_tr)
                if events:
                    return events
        return None

    def get_handover_summary(self, max_turns: int = 8, use_cache: bool = True, native: bool = True) -> str:
        """Extract a lean handoff memo for the next session.

        Prefers agy's own native `/compact`, resumed against this session's
        real conversation_id via --conversation -- it sees the full
        history/tool state (not just the last N text turns) and empirically
        produces more detailed, accurate summaries than the custom prompt
        below (2026-09-16: verified it recalls exact figures/decisions
        correctly). Confirmed safe to run while this session's own
        persistent agy process is still alive on the same conversation_id
        (isolated concurrent-access test: no hang, no corruption, live
        process stayed healthy afterward) -- note this does NOT reduce the
        conversation's actual resent-context cost (verified separately),
        it's used here purely as a better summary source. Falls back to the
        lightweight custom-prompt dialogue summary when there's no
        conversation_id yet, or the native call fails/times out (a heavy
        session's full history can take a while for agy to compact).
        `native=False` makes no model call at all: the visible history, trimmed
        (instant; for a caller that must not block, e.g. an in-place provider
        swap, which refines it in the background -- _refine_swap_handoff).
        """
        if use_cache and getattr(self, "_cached_summary", ""):
            return self._cached_summary
        if not native:
            return self._host_history_digest(header="(제공자가 바뀌었습니다. 아래는 화면 기록의 최근 대화입니다. 이어서 진행하세요.)")

        base = ""
        cid = getattr(self, "conversation_id", None)
        # agy's own /compact is agy-specific -- a claude/grok/codex session's
        # conversation_id is that CLI's own id space, not one of agy's
        # conversation dbs. Calling agy with it doesn't error (agy just
        # creates a fresh, empty conversation at that path and "compacts"
        # nothing), it just wastes up to the 45s timeout before falling
        # through to the dialogue-summary fallback below anyway -- caught
        # while wiring up the frontend selector, skip straight to the
        # fallback for any provider that isn't agy instead of wasting the
        # attempt.
        if cid:
            base = self._native_compact(self.provider, cid)

        if not base:
            base = self._dialogue_summary_fallback(max_turns)

        # Append the last real exchange verbatim alongside the compacted
        # summary above -- a summary can lose exact wording/details from
        # what was *just* discussed right before a handoff; the raw last
        # turn gives the new session a high-fidelity anchor on top of the
        # compressed long-range context (operator 제안, 2026-09-17).
        full = self._with_last_exchange(base)
        if use_cache:
            self._cached_summary = full
        return full

    def to_public(self) -> dict:
        _redact_line, ADD_DIRS = _session()._redact_line, _session().ADD_DIRS
        billed_tokens = _billed_tokens(self.history)
        context_tokens = _current_context_tokens(self.history)
        output_tokens = 0
        thinking_tokens = 0
        cache_read_tokens = 0
        for h in self.history:
            u = h.get("usage")
            if isinstance(u, dict):
                output_tokens += int(u.get("output_tokens") or 0)
                thinking_tokens += int(u.get("thinking_tokens") or 0)
                cache_read_tokens += int(u.get("cache_read_tokens") or 0)

        really_busy = bool(self.busy and self._proc_alive())
        draft = (self.current_text or "") if really_busy else ""
        if len(draft) > 120000:
            draft = draft[-120000:]
        out = {
            "id": self.sid,
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "conversation_id": self.conversation_id,
            "character": getattr(self, "character", "") or "",
            "mode": getattr(self, "mode", "work") or "work",
            "busy": really_busy,
            "queue_len": len(getattr(self, "msg_queue", [])),
            "alive": self._proc_alive(),
            "current_text": draft,
            "turn_started_at": float(self.turn_started_at or 0) if really_busy else 0,
            "last_progress": (getattr(self, "last_progress", "") or "") if really_busy else "",
            "history": self.history[-40:],
            "updated_at": self.meta_path.stat().st_mtime if self.meta_path.exists() else self.last_activity,
            "class": "NAS agent (VibeCat-class)",
            "weight": self.weight(),
            "add_dirs": [d for d in ADD_DIRS if Path(d).exists()],
            "usage": {
                "context_tokens": context_tokens,
                "billed_tokens": billed_tokens,
                "total_tokens": billed_tokens,
                "input_tokens": context_tokens,
                "output_tokens": output_tokens,
                "thinking_tokens": thinking_tokens,
                "cache_read_tokens": cache_read_tokens,
            },
        }
        if not out["alive"] and self._stderr_tail:
            out["debug_stderr_tail"] = [l for l in self._stderr_tail[-15:] if not _redact_line(l)]
        w = out.get("weight") or {}
        succ = getattr(self, "successor_session_id", "") or ""
        if succ:
            out["successor_session_id"] = succ
            if (w.get("level") or "") == "hard":
                out["redirect_session_id"] = succ
        pred = getattr(self, "predecessor_session_id", "") or ""
        if pred:
            out["predecessor_session_id"] = pred
            out["has_handover"] = bool(getattr(self, "handoff_summary", ""))
            out["handoff_summary"] = getattr(self, "handoff_summary", "")
        return out

    def get_log(self) -> List[dict]:
        """Durable per-session activity log (see PERSISTED_LOG_KINDS/_emit),
        newest first -- same shape/pagination story as get_artifacts()."""
        path = self.meta_path.parent / "events.jsonl"
        if not path.exists():
            return []
        out = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            return []
        out.sort(key=lambda e: e.get("ts") or 0, reverse=True)
        return out

    def get_artifacts(self) -> List[dict]:
        SESSIONS = _session().SESSIONS
        exts_img = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        exts_doc = {".md", ".txt", ".json", ".pdf", ".html", ".csv", ".yaml", ".yml"}
        exts_code = {".py", ".js", ".ts", ".gd", ".sh", ".sql", ".css"}

        provider_dirs = list(self._artifact_dirs())
        roots = list(provider_dirs)

        session_artifact_roots: Dict[Path, str] = {}
        # First cut (2026-09-18) only walked self.sid + predecessor_session_id. operator: "아티팩트 탭은 모든
        # 디바이스 모든 세션 공통인데" -> ticket #575: 1:1 세션 및 단체방별 고유 격리로 분리.
        my_adir = self.meta_path.parent / "artifacts"
        session_artifact_roots[my_adir] = self.sid
        roots.append(my_adir)

        curr_pred = getattr(self, "predecessor_session_id", "") or ""
        seen_sids = {self.sid}
        while curr_pred and curr_pred not in seen_sids:
            seen_sids.add(curr_pred)
            p_dir = SESSIONS / curr_pred / "artifacts"
            session_artifact_roots[p_dir] = curr_pred
            roots.append(p_dir)
            p_meta = SESSIONS / curr_pred / "meta.json"
            curr_pred = ""
            if p_meta.is_file():
                try:
                    data = json.loads(p_meta.read_text(encoding="utf-8"))
                    curr_pred = str(data.get("predecessor_session_id") or "")
                except Exception:
                    break

        found = []
        seen_sizes = set()
        seen_names = set()
        brain_source_roots = set(provider_dirs)

        for root in roots:
            if not root or not Path(root).exists():
                continue
            try:
                for fp in Path(root).rglob("*"):
                    if not fp.is_file() or fp.name.startswith("."):
                        continue
                    if any(part.startswith(".") for part in fp.parts[:-1]):
                        continue
                    suffix = fp.suffix.lower()
                    if suffix not in exts_img and suffix not in exts_doc and suffix not in exts_code:
                        continue
                    try:
                        sz = fp.stat().st_size
                    except OSError:
                        continue
                    if sz in seen_sizes and sz > 5000:
                        continue
                    if fp.name in seen_names:
                        continue
                    seen_sizes.add(sz)
                    seen_names.add(fp.name)

                    kind = "image" if suffix in exts_img else ("document" if suffix in exts_doc else "code")
                    if kind == "image" and root in brain_source_roots:
                        url = self._stage_image(fp)
                    elif root in session_artifact_roots:
                        owner_sid = session_artifact_roots[root]
                        url = f"/artifacts/{owner_sid}/{fp.relative_to(root).as_posix()}"
                    else:
                        url = f"/artifacts/{fp.name}"

                    if sz >= 1024 * 1024:
                        sz_str = f"{sz / (1024 * 1024):.1f} MB"
                    elif sz >= 1024:
                        sz_str = f"{sz / 1024:.0f} KB"
                    else:
                        sz_str = f"{sz} B"

                    mtime = fp.stat().st_mtime
                    found.append({
                        "name": fp.name,
                        "stem": fp.stem,
                        "kind": kind,
                        "ext": suffix.lstrip("."),
                        "size": sz,
                        "size_human": sz_str,
                        "url": url or f"/artifacts/{fp.name}",
                        "mtime": mtime,
                        "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                    })
            except Exception:
                continue

        found.sort(key=lambda x: x["mtime"], reverse=True)
        return found
