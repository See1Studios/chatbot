"""Where sessions are found (REGISTRY_SPLIT_v1, docs/plans/monolith-split.md Phase 5): the registry of live
AgentSession objects, the newest-session lookup per character and mode, the session list, and the meta.json summary
cache behind them (SESSION_INDEX_v1). Split out of session.py, which re-exports every name here, so callers keep
`from session import REG, Registry`.

session.py's own values (SESSIONS, WORKSPACE, AgentSession, defaults) are read from that module at call time, not
copied at import: tests point `session.SESSIONS` at a temporary folder, and the registry must follow."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _s():
    """The session module (already loaded: it imports this one at its end)."""
    return sys.modules["session"]


_LIVE_SID_RE = re.compile(r"^\d{8}-\d{6}-")


def _live_sid(sid: str) -> bool:
    """Production session ids are YYYYMMDD-HHMMSS-xxxxxx. Leftover names like
    nonexistent-sid-test sort after those and must not become 'active'."""
    return bool(sid and _LIVE_SID_RE.match(sid))


def _probe_meta(meta: dict) -> bool:
    hist = meta.get("history") or []
    if len(hist) > 2:
        return False
    sample = " ".join(str(h.get("text") or "") for h in hist)
    return "[doctor-probe]" in sample or "[diag]" in sample


# SESSION_INDEX_v1: the page asks for the newest session every 2.5s. Reading every meta.json (history and all)
# each time cost ~170ms under REG.lock with ~320 sessions, and grew with every session. Each file is parsed
# once per change (mtime + size) and kept as a small summary; the whole scan is skipped while nothing changed:
# this process's own saves call _meta_touched(), a new or removed session folder changes the folder's mtime,
# and anything else (another process) is picked up within _META_RESCAN_SEC.
_META_INDEX: Dict[Path, tuple] = {}
_META_INDEX_LOCK = threading.Lock()
_META_RESCAN_SEC = 30.0
_meta_state = {"dirty": set(), "root": None, "dir_mtime": None, "at": 0.0, "list": []}


def _meta_touched(path: Path) -> None:
    with _META_INDEX_LOCK:
        _meta_state["dirty"].add(Path(path))


def _meta_summary(p: Path) -> Optional[dict]:
    """The cached summary of one meta.json, re-read only when its mtime or size changed; None when it is gone."""
    try:
        st = p.stat()
    except OSError:
        _META_INDEX.pop(p, None)
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _META_INDEX.get(p)
    if hit is None or hit[0] != key:
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        hist = meta.get("history") or []
        hit = (key, {
            "id": str(meta.get("id") or p.parent.name or ""),
            "model": meta.get("model"),
            "mode": "private" if meta.get("mode") == "private" else "work",
            "character": str(meta.get("character") or ""),
            "probe": _probe_meta(meta),
            "preview": (str(hist[-1].get("text", ""))[:80] if hist else ""),
            "turns": len(hist),
        })
        _META_INDEX[p] = hit
    return dict(hit[1], mtime=st.st_mtime, path=p)


def _meta_summaries() -> List[dict]:
    """One small summary per sessions/*/meta.json: id, mode, character, probe, model, preview, turns, mtime."""
    with _META_INDEX_LOCK:
        try:
            dir_mtime = _s().SESSIONS.stat().st_mtime_ns
        except OSError:
            return []
        st8 = _meta_state
        if (st8["root"] == _s().SESSIONS and st8["dir_mtime"] == dir_mtime
                and time.monotonic() - st8["at"] < _META_RESCAN_SEC):
            dirty, st8["dirty"] = st8["dirty"], set()
            if dirty:                                     # only the files this process saved
                kept = [m for m in st8["list"] if m["path"] not in dirty]
                st8["list"] = kept + [m for m in map(_meta_summary, dirty) if m is not None]
            return [dict(m) for m in st8["list"]]
        st8["dirty"] = set()
        with os.scandir(_s().SESSIONS) as it:
            entries = [Path(e.path) / "meta.json" for e in it if e.is_dir()]
        out = [m for m in map(_meta_summary, entries) if m is not None]
        live = {m["path"] for m in out}
        for gone in [k for k in _META_INDEX if k not in live]:
            del _META_INDEX[gone]
        st8.update(root=_s().SESSIONS, dir_mtime=dir_mtime, at=time.monotonic(), list=out)
        return [dict(m) for m in out]


class Registry:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sessions: Dict[str, "AgentSession"] = {}

    def create(
        self,
        model: str = _s().DEFAULT_MODEL,
        effort: str = "",
        predecessor_sid: str = "",
        handoff_summary: str = "",
        provider: str = _s().DEFAULT_PROVIDER,
        character: str = "",
        mode: str = "work",
    ) -> "AgentSession":
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        sess = _s().AgentSession(sid, model=model, effort=effort, provider=provider)
        sess.character = _character_id(character)
        sess.mode = "private" if mode == "private" else "work"
        sess.predecessor_session_id = predecessor_sid
        sess.handoff_summary = handoff_summary
        sess.handoff_injected = False
        sess.save_meta()
        with self.lock:
            self.sessions[sid] = sess
        return sess

    def delete(self, sid: str) -> bool:
        """Stops any live process, drops the in-memory session, and removes
        sessions/<sid>/ entirely -- meta.json AND artifacts/ together, since
        they live in one folder by design (see 2026-09-16/17 consolidation).
        Returns False if the session doesn't exist on disk. Raises if the
        directory is still there afterward -- ignore_errors=True previously
        made this silently report success even when removal failed."""
        sid = _s()._safe_session_id(sid)
        sess_dir = _s().SESSIONS / sid
        meta_path = sess_dir / "meta.json"
        if not meta_path.exists():
            return False
        with self.lock:
            sess = self.sessions.pop(sid, None)
        if sess is not None:
            try:
                sess.stop(notify=False)
            except Exception:
                pass
        shutil.rmtree(sess_dir, ignore_errors=True)
        if sess_dir.exists():
            raise RuntimeError(f"삭제 실패: {sess_dir} 디렉터리가 여전히 남아있습니다")
        return True

    def peek(self, sid: str) -> Optional["AgentSession"]:
        """Return the session if it exists in memory or on disk; None otherwise.
        Unlike get(), never creates a new session — safe for all GET routes."""
        try:
            sid = _s()._safe_session_id(sid)
        except ValueError:
            return None
        with self.lock:
            if sid in self.sessions:
                return self.sessions[sid]
        # Check disk: a session folder with a meta.json qualifies.
        if (_s().SESSIONS / sid / "meta.json").exists():
            return self.get(sid)
        return None

    def get(self, sid: str) -> "AgentSession":
        sid = _s()._safe_session_id(sid)
        with self.lock:
            if sid in self.sessions:
                return self.sessions[sid]
            sess = _s().AgentSession(sid)
            self.sessions[sid] = sess
            return sess

    def list(self) -> List[dict]:
        # updated_at is meta.json's mtime as epoch seconds, like AgentSession.to_public()'s (the client
        # compares the two)
        items = sorted(_meta_summaries(), key=lambda m: m["mtime"], reverse=True)[:40]
        return [{"id": m["id"], "model": m["model"], "updated_at": m["mtime"], "preview": m["preview"],
                 "turns": m["turns"], "mode": m["mode"], "character": m["character"]} for m in items]

    def get_active(self, character: str = "") -> "AgentSession":
        """Live conversation: the character's newest *work* session id, then the successor-chain tip ("" = the
        team's default character). A character without one gets a new session on its first brain
        (CHARACTER_PICKER_v1); after that its own newest session carries the brain last used with it.

        Session ids are YYYYMMDD-HHMMSS-xxxxxx so lexicographic max is
        chronological latest. list() is still mtime-sorted (recency for the
        sessions tab). Opening a past session must not steal 'active'.
        Private sessions and other characters' sessions never become active (SESSION_SPLIT_v1).
        """
        character = _character_id(character)
        sess = self._newest(mode="work", character=character)
        if sess is not None:
            return sess
        if not character:
            return self.create()
        brain = _first_brain(character)
        return self.create(model=brain.get("model") or "", provider=brain.get("provider") or _s().DEFAULT_PROVIDER,
                           character=character)

    def get_private(self, character: str = "", like: Optional["AgentSession"] = None) -> "AgentSession":
        """The character's private session (its successor-chain tip), created on first use with `like`'s
        provider and model."""
        character = _character_id(character)
        sess = self._newest(mode="private", character=character)
        if sess is not None:
            return sess
        like = like or self.get_active(character)
        return self.create(model=like.model, effort=like.effort, provider=like.provider, character=character,
                           mode="private")

    def _newest(self, mode: str, character: str) -> Optional["AgentSession"]:
        default = None
        best_id = ""
        for m in _meta_summaries():
            if m["probe"] or m["mode"] != mode or not _live_sid(m["id"]):
                continue
            if not m["character"]:                        # "" in a not-yet-migrated session = the default
                default = _character_id("") if default is None else default
            if (m["character"] or default) != character:
                continue
            if m["id"] > best_id:
                best_id = m["id"]
        with self.lock:
            if not best_id:
                return None
            sess = self.get(best_id)
            seen = {best_id}
            for _ in range(40):
                succ = getattr(sess, "successor_session_id", "") or ""
                if not succ or succ in seen or not sess._successor_usable(succ):
                    return sess
                seen.add(succ)
                sess = self.get(succ)
            return sess


def _character_id(character: str = "") -> str:
    """Sessions always name their character (TEAM_ROLES_v2): "" means the team's default character."""
    if character:
        return character
    try:
        import characters
        return characters.default_character(_s().WORKSPACE)
    except Exception:  # noqa: BLE001
        return ""


def migrate_session_characters() -> int:
    """Sessions from before TEAM_ROLES_v2 stored "" for the chatbot itself; they become the default character's.
    Returns how many were rewritten."""
    cid = _character_id("")
    if not cid or not _s().SESSIONS.is_dir():
        return 0
    n = 0
    for p in _s().SESSIONS.glob("*/meta.json"):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
            if meta.get("character"):
                continue
            meta["character"] = cid
            st = p.stat()
            tmp = p.with_name(".meta.migrate.tmp")
            tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
            # keep the file's time: the sessions list and scrollback order sessions by it, so a rewrite that
            # stamps them all "now" stitches unrelated sessions together (seen live 2026-09-24)
            os.utime(p, (st.st_atime, st.st_mtime))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def _first_brain(character: str) -> Dict[str, Any]:
    """The first entry of the character's work brain list, or {}."""
    try:
        import characters
        chain = characters.brains(characters.load(character, _s().WORKSPACE))
        return chain[0] if chain else {}
    except Exception:  # noqa: BLE001
        return {}
