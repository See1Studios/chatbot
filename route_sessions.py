"""Sessions and characters over HTTP (monolith-split split/B, moved from server.py): list, open, create, send a
message, switch rooms, stop, continue, delete, and the live event stream (SSE). Routes are listed in server.py's
tables; a handler gets the session id as `req.arg` where its pattern has one."""
from __future__ import annotations

import json
import queue
import threading
import i18n
from typing import Any, Dict

import chat_upload
import content_guard
import emotion
import items
import personal_turn  # PERSONAL_TURN_v1: the busy listing says which turn runs
import threshold  # THRESHOLD_v1: entering the private room hands one note across
from host_config import DEFAULT_MODEL, DEFAULT_PROVIDER, _now
from route_table import Req
from session import REG, _safe_session_id

_digest_private_later = threshold.digest_later   # private talk -> the character's private memory (SESSION_SPLIT_v1)


def _session_character(ref: str):
    """The character id a session is for: the id itself, "" for the team's default; None when there is no such
    character. Every character alike (TEAM_ROLES_v2)."""
    import characters
    if not ref:
        return characters.default_character() or None
    return ref if characters.ID_RE.match(ref) and characters.card_path(ref).is_file() else None


def _new_session_kind(body: dict):
    """(mode, character) for a new session from a POST /api/sessions body, so /new stays in the open session's
    mode and character; None when the character is unknown."""
    ref = str(body.get("character") or "")
    who = _session_character(ref) if ref else ""       # "" = the default, resolved by REG.create
    if who is None:
        return None
    return ("private" if body.get("mode") == "private" else "work"), who


def _character_list() -> list:
    """The characters for the picker: the team's default first, then the rest, oldest first. Roles are shown,
    never used to tell characters apart (TEAM_ROLES_v2)."""
    import characters
    default = characters.default_character()
    out = []
    for c in characters.listing():
        disp = (characters.ext(c["card"]).get("display") or {})
        name = ((c["card"].get("data") or {}).get("name") or "").strip()
        base = characters.card_path(c["id"]).parent
        art_v = {}
        for kind in ("avatar", "stage"):
            files = [f for f in [base / (kind + ".webp"), base / (kind + ".png")] + sorted((base / kind).glob("*.*"))
                     if f.is_file()] if base.is_dir() else []
            art_v[kind] = int(max(f.stat().st_mtime for f in files)) if files else 0
        out.append({"id": c["id"], "session_character": c["id"], "roles": c["roles"], "role": c["role"],
                    "default": c["id"] == default, "name": name, "title": disp.get("title") or name,
                    # a version for the picture URLs: new art shows at once; 0 = no picture yet (the route
                    # serves the engine placeholder, ART_PLACEHOLDER_v1)
                    "avatar_v": art_v["avatar"], "stage_v": art_v["stage"]})
    out.sort(key=lambda x: not x["default"])
    return out


def _public(sess) -> dict:
    pub = sess.to_public()
    pub["is_private"] = sess.is_private
    return pub


def _page(rows: list, qs: dict, key, cursor) -> dict:
    """One page of newest-first rows: ?limit (1-200, default 60) and ?before=<key value>; next_before (the last row's
    cursor) when more."""
    try:
        limit = max(1, min(200, int(qs.get("limit", ["60"])[0])))
    except ValueError:
        limit = 60
    before_raw = qs.get("before", [""])[0]
    page = rows
    if before_raw:
        try:
            before = float(before_raw)
            page = [r for r in rows if key(r) < before]
        except ValueError:
            pass
    page = page[:limit]
    next_before = cursor(page[-1]) if len(page) == limit and len(page) < len(rows) else None
    return {"page": page, "total": len(rows), "next_before": next_before}


# ------------------------------------------------------------------------------------------------ GET

def listing(req: Req):
    return req.json({"sessions": REG.list(), "talks": REG.talks()})   # talks: the talk list (ux/S1)


def characters_list(req: Req):
    return req.json({"characters": _character_list()})


def busy(req: Req):
    # which sessions are running a turn, and in which mode: the MCP server refuses work tools while a
    # private session is busy (SESSION_SPLIT_v1)
    import characters
    with REG.lock:
        live = list(REG.sessions.values())
    busy = [{"id": x.sid, "mode": x.mode, "turn": personal_turn.running_turn(x.history), "character": x.character,
             "provider": x.provider, "tools": characters.tools_of(x.character) if x.character else []}
            for x in live if x.busy and x._proc_alive()]
    return req.json({"sessions": busy})


def active(req: Req):
    sess = REG.get_active()
    pub = sess.to_public()
    pub["is_private"] = bool(getattr(sess, "is_private", False))
    return req.json(pub)


def caller(req: Req):
    """GET /api/sessions/caller?port=&server=[&claim=]: the session behind a tool call's connection (inbox/0)."""
    import session
    try:
        port, server = int(req.q("port")), int(req.q("server"))
    except (TypeError, ValueError):
        return req.send(400, b"port and server required", "text/plain")
    sid, proc = session.caller_session(port, server, str(req.q("claim") or ""))
    sess = REG.peek(sid) if sid else None
    return req.json({"id": sid, "proc": proc, "character": getattr(sess, "character", "") or "",
                     "mode": getattr(sess, "mode", "") or "", "private": bool(getattr(sess, "is_private", False))})

def _office_view(m: Dict, cid: str) -> Dict:
    """One dm message as `cid`'s window draws it (inbox/E): a coworker's turn, or its own line to them."""
    import character_names
    import characters
    import dialog_log
    to = m["other"] if m["who"] == cid else cid
    return {"dialog_id": m["dialog_id"], "n": m["n"], "ts": m["ts"], "who": m["who"], "kind": m.get("kind") or "say",
            "text": character_names.as_of(m["text"], m["ts"]), "mine": m["who"] == cid, "who_name": characters.name(m["who"]) or m["who"],
            "to_name": characters.name(to) or to, "how": dialog_log.how(m, m["dialog_id"])}


def office(req: Req):
    """GET /api/office?character=: a character's dms with its coworkers, for its work window (inbox/E, D8)."""
    import characters
    import dialog_log
    cid = str(req.q("character") or "")
    if not characters.ID_RE.match(cid):
        return req.send(400, b"character required", "text/plain")
    return req.json({"messages": [_office_view(m, cid) for m in dialog_log.feed(cid)]})


def office_opened(req: Req):
    """GET /api/office/opened?character=: the page opened that character's work window; a coworker's turn it has not
    heard yet gets its reaction now (event_react.react_on_open, D11)."""
    import characters
    import event_react
    cid = str(req.q("character") or "")
    if not characters.ID_RE.match(cid):
        return req.send(400, b"character required", "text/plain")
    threading.Thread(target=event_react.react_on_open, args=(REG, cid), name="office-open-check", daemon=True).start()
    return req.json({"ok": True})


def office_notify(req: Req):
    """GET /api/office/notify?dialog=&n=&only=: the tool server says a dm was sent. Both coworkers' work
    windows show it now (or one, if `only` limits it: a handoff task already shows as the sender's own
    turn, live 2026-10-05) and the one it went to may react (event_react, D11). The record is read here; the query
    only points at it."""
    import dialog_log
    import event_react
    did = str(req.q("dialog") or "")
    try:
        n = int(req.q("n"))
    except (TypeError, ValueError):
        return req.send(400, b"dialog and n required", "text/plain")
    msg = next((m for m in dialog_log.history(did, n - 1) if m["n"] == n), None) if dialog_log.is_dm(did) else None
    if msg is None:
        return req.send(404, b"no such message", "text/plain")
    only = str(req.q("only") or "")
    for cid in dialog_log.members(did):
        if only and cid != only:
            continue
        sess = REG._newest(mode="work", character=cid)
        if sess is not None:
            other = next(x for x in dialog_log.members(did) if x != cid)
            sess._emit({"event": "office", "msg": _office_view(dict(msg, dialog_id=did, other=other), cid)})
    threading.Thread(target=event_react.react_once, args=(REG,), name="office-react", daemon=True).start()
    return req.json({"ok": True})


def artifacts(req: Req):
    sess = REG.peek(req.arg)
    if sess is None:
        return req.send(404, b"session not found", "text/plain")
    p = _page(sess.get_artifacts(), req.qs(), lambda a: a["mtime"], lambda a: a["mtime"])   # already sorted newest-mtime-first
    return req.json({"artifacts": p["page"], "total": p["total"], "next_before": p["next_before"]})


def log(req: Req):
    sess = REG.peek(req.arg)
    if sess is None:
        return req.send(404, b"session not found", "text/plain")
    p = _page(sess.get_log(), req.qs(), lambda e: e.get("ts") or 0, lambda e: e.get("ts"))   # already sorted newest-ts-first
    return req.json({"events": p["page"], "total": p["total"], "next_before": p["next_before"]})


def context(req: Req):
    """GET /api/sessions/<sid>/context: what went into this conversation's agent, newest last (CONTEXT_PANEL_v1) --
    each record's time, why (first, rules_changed, refresh, lore), size and layers."""
    sess = REG.peek(req.arg)
    if sess is None:
        return req.send(404, b"session not found", "text/plain")
    return req.json({"ok": True, "mode": getattr(sess, "mode", "work"), "records": list(getattr(sess, "context_log", []) or [])})


def summary(req: Req):
    # Read-only handover-style summary of an arbitrary (often archived) session,
    # for the "bring in" scrollback/session-list action — never touches the
    # target session's own state, and never injected automatically anywhere.
    sid = req.arg
    sess = REG.peek(sid)
    if sess is None:
        return req.send(404, b"session not found", "text/plain")
    return req.json({"id": sid, "summary": sess.get_handover_summary()})


def detail(req: Req):
    sid = req.path.split("/")[3]
    sess = REG.peek(sid)
    if sess is None:
        return req.json({"ok": False, "error": "session not found"}, 404)
    full = req.q("full", "0") == "1"
    out = sess.to_public()
    out["is_private"] = bool(getattr(sess, "is_private", False))
    if full:
        with sess.lock:
            out["history"] = list(sess.history)
    out["history"] = [_named_now(h) for h in out.get("history") or []]
    return req.json(out)


def _named_now(h: Dict) -> Dict:
    """A history entry as shown: talk from before a rename with today's names (NAME_CHANGE_v1). A copy -- the session's
    own record keeps what was said."""
    import character_names
    if not isinstance(h, dict) or not h.get("text"):
        return h
    text = character_names.as_of(h["text"], h.get("ts"))
    return h if text == h["text"] else dict(h, text=text)


def events(req: Req) -> None:
    """The session's live event stream (SSE)."""
    h, sid = req.h, req.arg
    if REG.is_probe(sid):  # a health probe's turn never streams to the UI
        return h._send(404, b"probe session", "text/plain")
    try:
        sess = REG.get(sid)
    except Exception as e:
        return req.json({"ok": False, "error": str(e)}, 400)
    h.send_response(200)
    h._cors()
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("Connection", "keep-alive")
    h.end_headers()
    try:
        h.wfile.write(b"event: hello\ndata: {\"ok\":true}\n\n")
        h.wfile.flush()
    except Exception:
        return
    sub_queue: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
    with sess.lock:
        sess.subscribers.append(sub_queue)
    try:
        _stream(h, sess, sub_queue)
    finally:
        with sess.lock:
            if sub_queue in sess.subscribers:
                sess.subscribers.remove(sub_queue)


def _stream(h, sess, sub_queue) -> None:
    # Recycle idle SSE sockets after 15 min so leaked mobile
    # connections die. Do NOT cut a busy turn — a tablet sitting
    # on a long job used to hit this wall, show "disconnected",
    # and leave the other phone with no live stream at all.
    idle_until = _now() + 900
    emotions = emotion.Tracker()
    while True:
        if not sess.busy and _now() > idle_until:
            break
        try:
            ev = sub_queue.get(timeout=15)
        except queue.Empty:
            try:
                h.wfile.write(b": ping\n\n")
                h.wfile.flush()
            except Exception:
                break
            if sess.busy:
                idle_until = _now() + 900
            continue
        if sess.busy:
            idle_until = _now() + 900

        try:
            label = emotions.feed(ev)
        except Exception:  # noqa: BLE001
            label = None
        if label:
            try:
                h.wfile.write(("data: %s\n\n" % json.dumps({"type": "emotion", "label": label},
                                                             separators=(",", ":"))).encode("utf-8"))
                h.wfile.flush()
            except Exception:
                break

        safe = {k: v for k, v in ev.items()}
        if "payload" in safe and isinstance(safe["payload"], dict):
            safe["payload"] = {k: safe["payload"].get(k) for k in list(safe["payload"])[:8]}
        line = "data: " + json.dumps(safe, ensure_ascii=False) + "\n\n"
        try:
            h.wfile.write(line.encode("utf-8"))
            h.wfile.flush()
        except Exception:
            break


# ------------------------------------------------------------------------------------------------ POST

def create(req: Req):
    body = req.body
    provider = str(body.get("provider") or DEFAULT_PROVIDER)
    # DEFAULT_MODEL names an agy/Gemini model -- meaningless as a
    # fallback for any other provider, whose own adapter already
    # treats an empty model as "let the CLI use its own default"
    # (verified live for claude: omitting --model just used its
    # account default, claude-sonnet-5).
    default_model = DEFAULT_MODEL if provider == DEFAULT_PROVIDER else ""
    kind = _new_session_kind(body)
    if kind is None:
        return req.json({"ok": False, "error": "unknown character"}, 404)
    sess = REG.create(
        model=str(body.get("model") or default_model),
        effort=str(body.get("effort") or ""),
        provider=provider,
        mode=kind[0],
        character=kind[1],
        probe=req.headers.get("X-Chatbot-Caller") == "doctor-probe",
    )
    return req.json({"ok": True, "session": sess.to_public()})


def character_session(req: Req):
    # CHARACTER_PICKER_v1: the character's own work (or private) session; its newest one carries the
    # brain last used with it
    body = req.body
    who = _session_character(req.arg)
    if who is None:
        return req.json({"ok": False, "error": "unknown character"}, 404)
    threshold.left_private(REG.peek(str(body.get("from") or "")) if body.get("from") else None)
    target = REG.get_active(who)
    if body.get("mode") == "private":
        target = REG.get_private(who, like=target, fresh=True)
    return req.json({"ok": True, "session": _public(target)})


def _switch_room(req: Req, sess, sid: str, text: str, client_mid: str):
    # SESSION_SPLIT_v1 (plan doc §12): private talk has its own session. /private opens the
    # character's private session, /private off goes back to the work session; a bare /private toggles
    # and /work is an old alias of off. Nothing is sent to the agent.
    stripped = " ".join(text.split()).lower()
    if stripped.startswith("/private on") or (stripped == "/private" and not sess.is_private):
        target = sess if sess.is_private else threshold.enter(sess, REG.get_private(sess.character, like=sess, fresh=True), text)
    else:   # back to work: digest the private talk, leave the return scene (THRESHOLD_v1)
        target = threshold.leave(sess, REG.get_active(sess.character), _digest_private_later) if sess.is_private else sess
    threshold.announce(sess, target, client_mid)   # ROOM_SYNC_v1: other windows follow
    return req.json({"ok": True, "switched": target.sid != sid, "old_session_id": sid,
                     "session": _public(target), **threshold.scene_field(target if target.sid != sid else None)})


def _action_text(body: dict, text: str):
    """(text, event_type). Structured action from the page (/act → type=action + action_text).
    Keep wire text as "(…)" for history/UI; pass event_type so tension_step
    and any future action formatting see an explicit action even if parens
    are missing or malformed."""
    event_type = str(body.get("type") or "").strip().lower()
    if event_type != "action":
        return text, ""
    from private_engine import strip_outer_parens as _strip_outer_parens
    action_text = str(body.get("action_text") or "").strip()
    if action_text:
        bare = _strip_outer_parens(action_text)
        if bare:
            text = "(" + bare + ")"
    elif text.startswith("/act ") or text.startswith("/me ") or text.startswith("/action "):
        bare = _strip_outer_parens(text.split(None, 1)[1].strip())
        if bare:
            text = "(" + bare + ")"
    return text, event_type


def message(req: Req):
    body, sid = req.body, req.arg
    sess = REG.get(sid)
    sess.maybe_swap_provider(str(body.get("provider") or ""))
    sess.maybe_swap_model(str(body.get("model") or ""))
    text = str(body.get("text") or body.get("message") or "")
    client_mid = str(body.get("client_mid") or "")
    client_ctx = body.get("client_context")
    if not isinstance(client_ctx, dict):
        client_ctx = None
    stripped = " ".join(text.split()).lower()
    if stripped in ("/private", "/private on", "/work", "/private off") or stripped.startswith("/private on "):
        return _switch_room(req, sess, sid, text, client_mid)

    # CONTENT_GUARD_v1: a message the provider would refuse never leaves the host (0 tokens)
    blocked, notice_text = content_guard.check_preflight(sess.provider, text)
    if blocked:
        item, ev = content_guard.notice_item(notice_text)
        sess.history.append(item)
        sess.save_meta()
        sess._emit(ev)
        return req.json({"ok": True, "blocked": True, "notice": item, "session": _public(sess)})

    text, event_type = _action_text(body, text)
    text = items.take_pending(sid, chat_upload.take_pending(sid, text))   # plus/C files, plus/F item note
    try:
        rotated = sess.send(text, client_mid, client_context=client_ctx, event_type=event_type)
    except Exception as e:
        # skill-observations 0011 (2026-09-17): this route intermittently 500'd on a brand-new session's first
        # message with no traceback anywhere to root-cause from. Like /stop already does via to_public()'s
        # debug_stderr_tail, surface the spawned process's own recent stderr in the error body itself so the next
        # occurrence is diagnosable without a second round-trip to GET the session. (OBSLOG_v1: the traceback is
        # recorded as http.error in logs/events.jsonl by HTTPLogMixin.send_response.)
        err: Dict[str, Any] = {"ok": False, "error": str(e)}
        tail = getattr(sess, "_stderr_tail", None)
        if tail:
            err["debug_stderr_tail"] = tail[-15:]
        return req.json(err, 500)

    pub = _public(rotated or sess)
    if rotated is not None:
        return req.json({
            "ok": True,
            "rotated": True,
            "old_session_id": sid,
            "session": pub,
            "handoff_summary": getattr(rotated, "handoff_summary", ""),
        })
    return req.json({"ok": True, "session": pub})


def provider(req: Req):
    body = req.body
    sess = REG.get(req.arg)
    new_p = str(body.get("provider") or "").strip()
    if new_p:
        sess.maybe_swap_provider(new_p)
    new_m = str(body.get("model") or "").strip()
    if new_m:
        sess.maybe_swap_model(new_m)
    return req.json({"ok": True, "session": sess.to_public()})


def continue_(req: Req):
    sid = req.arg
    sess = REG.get(sid)
    result = sess.continue_to_successor(str(req.body.get("model") or ""), bool(req.body.get("sticky")))
    return req.json({
        "ok": True,
        "session": result["new_sess"].to_public(),
        "old_session_id": sid,
        "summary": result["summary"],
        "reused": result["reused"],
    })


def stop(req: Req):
    sess = REG.get(req.arg)
    sess.stop()
    return req.json({"ok": True, "session": sess.to_public()})


def discard(req: Req):
    # Doctor/probe throwaway: stop the agent and drop from in-memory registry (meta kept).
    sid = req.arg
    sess = REG.get(sid)
    sess.stop(notify=False)
    with REG.lock:
        REG.sessions.pop(sid, None)
    return req.json({"ok": True, "discarded": sid})


# ------------------------------------------------------------------------------------------------ DELETE

def delete(req: Req):
    sid = req.arg
    existing = REG.sessions.get(_safe_session_id(sid))
    # A stale busy=True (e.g. its agy process got reaped by
    # reap_orphan_agents mid-turn without ever emitting a
    # result/error event) must not block deletion forever --
    # only a genuinely still-running process counts as busy.
    really_busy = bool(
        existing is not None and existing.busy
        and existing.proc is not None and existing.proc.poll() is None
    )
    if really_busy:
        return req.json({"ok": False, **i18n.field("error", 'sessions.busy_no_delete')}, 409)
    ok = REG.delete(sid)
    return req.json({"ok": ok} if ok else {"ok": False, "error": "not found"}, 200 if ok else 404)
