"""Where sessions are found (REGISTRY_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5): the registry of live
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
import platform_compat
import threshold


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


PROBE_MARKER = ".probe"  # sessions/<sid>/.probe: created by a health probe (X-Chatbot-Caller: doctor-probe)


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
            "mode": meta.get("mode") if meta.get("mode") in ("private", "room") else "work",   # a room seat is never work
            "character": str(meta.get("character") or ""),
            "provider": str(meta.get("provider") or ""),
            "probe": _probe_meta(meta) or (p.parent / PROBE_MARKER).exists(),
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
        probe: bool = False,
    ) -> "AgentSession":
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        sess = _s().AgentSession(sid, model=model, effort=effort, provider=provider)
        if probe:  # before the first save, so no summary ever sees it unmarked
            sess.meta_path.parent.mkdir(parents=True, exist_ok=True)
            (sess.meta_path.parent / PROBE_MARKER).touch()
        sess.character = _character_id(character)
        sess.mode = mode if mode in ("private", "room") else "work"   # room: a member's seat in a group room (evt/E)
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
            raise RuntimeError(f"delete failed: {sess_dir} is still there")
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

    def is_probe(self, sid: str) -> bool:
        """True for a health-probe session (marker or probe-only history): never listed, active or streamed to the UI."""
        try:
            d = _s().SESSIONS / _s()._safe_session_id(sid)
        except ValueError:
            return False
        if (d / PROBE_MARKER).exists():
            return True
        try:
            return _probe_meta(json.loads((d / "meta.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return False

    def get(self, sid: str) -> "AgentSession":
        sid = _s()._safe_session_id(sid)
        with self.lock:
            if sid in self.sessions:
                return self.sessions[sid]
            sess = _s().AgentSession(sid)
            # an id with no meta (e.g. a deleted probe session) must not come back role-less
            sess.character = _character_id(sess.character)
            self.sessions[sid] = sess
            return sess

    def list(self) -> List[dict]:
        # updated_at is meta.json's mtime as epoch seconds, like AgentSession.to_public()'s (the client
        # compares the two)
        items = sorted((m for m in _meta_summaries() if not m["probe"] and m["mode"] != "room"),   # seats: the room view
                       key=lambda m: m["mtime"], reverse=True)[:40]
        names: Dict[str, str] = {}
        out = []
        for m in items:
            cid = m["character"]
            if cid not in names:
                names[cid] = character_name(cid)
            out.append({
                "id": m["id"], "model": m["model"], "updated_at": m["mtime"], "preview": m["preview"],
                "turns": m["turns"], "mode": m["mode"], "character": cid, "character_name": names[cid],
            })
        return out

    def talks(self) -> Dict[str, dict]:
        """The newest work talk of every character, for the talk list (ux/S1): {character id: {"at", "preview",
        "provider"}} -- the provider is the brain last used with the character, which its picture follows.
        list() stops at 40 sessions, which one busy character fills. Private and room sessions are never read
        here: the list is what someone beside the user sees. A session nobody has spoken in yet is no talk."""
        out: Dict[str, dict] = {}
        for m in _meta_summaries():
            if m["probe"] or m["mode"] != "work" or not m["turns"]:
                continue
            cid = _character_id(m["character"])
            if cid not in out or m["mtime"] > out[cid]["at"]:
                out[cid] = {"at": m["mtime"], "preview": m["preview"], "provider": m["provider"]}
        return out

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
        brain = _override_brain(character, "work") or _first_brain(character) or {}
        return self.create(model=brain.get("model") or "", effort=brain.get("effort") or "",
                           provider=brain.get("provider") or _s().DEFAULT_PROVIDER, character=character)

    def get_private(self, character: str = "", like: Optional["AgentSession"] = None,
                    fresh: bool = False) -> "AgentSession":
        """The character's private session (its successor-chain tip). A saved user override wins, else the
        card's `brains.private` first entry, else `like`'s provider and model (pew/N4).
        Private Grok (#240): prefer grok-4.7 (not 4.6 / not build-fast) and effort low.
        `fresh` (PRIVATE_VISIT_v1, operator 2026-09-29): every visit to the private room is a new session, so the
        last scene's place and talk never leak into the next; what carries over is the private memory digest.
        The last private session's brain is kept, and a last one that is still empty is reused, not multiplied."""
        character = _character_id(character)
        sess = self._newest(mode="private", character=character)
        if sess is not None and (not fresh or not any(h.get("role") in ("user", "assistant") for h in sess.history)
                                 or threshold.just_switched(sess, "visit_started")):
            return sess   # (fresh) a repeat of the switch that just opened it -- a re-tap or another tab -- stays
        like = sess or like or self.get_active(character)
        provider, model, effort = _private_brain(character, like)
        return self.create(model=model, effort=effort, provider=provider, character=character,
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


def character_name(character: str = "") -> str:
    """The character's display name dynamically resolved from its TypeID (via characters.py).
    Empty string if unresolvable."""
    cid = _character_id(character)
    if not cid:
        return ""
    try:
        import characters
        return characters.name(cid, _s().WORKSPACE)
    except Exception:  # noqa: BLE001
        return ""


def session_character(sid_or_meta: Any) -> str:
    """The character TypeID of a session, meta dict or session ID, resolving empty to the default character."""
    if isinstance(sid_or_meta, dict):
        cid = sid_or_meta.get("character") or ""
    elif isinstance(sid_or_meta, str):
        cid = ""
        try:
            sess = _s().REG.peek(sid_or_meta)
            if sess is not None:
                cid = getattr(sess, "character", "") or ""
        except Exception:  # noqa: BLE001
            pass
        if not cid:
            for m in _meta_summaries():
                if m.get("id") == sid_or_meta:
                    cid = m.get("character") or ""
                    break
    else:
        cid = getattr(sid_or_meta, "character", "") or ""
    return _character_id(cid)



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
            platform_compat.write_text(tmp, json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
            # keep the file's time: the sessions list and scrollback order sessions by it, so a rewrite that
            # stamps them all "now" stitches unrelated sessions together (seen live 2026-09-24)
            os.utime(p, (st.st_atime, st.st_mtime))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def _override_brain(character: str, mode: str) -> Dict[str, Any]:
    """The user's saved provider/model for this mode, or {} when they are on the card default."""
    try:
        import characters
        row = (characters.read_brain_overrides(character) or {}).get(mode)
    except Exception:  # noqa: BLE001
        return {}
    return row if isinstance(row, dict) and row.get("provider") else {}


def _fill_family_defaults(provider: str, model: str, effort: str, keep_model: bool):
    if (provider or "").lower() != "grok" and "grok" not in (model or "").lower():
        return provider, model, effort
    if not keep_model and (not model or model in ("default", "grok-4.6", "grok-4.7-build-fast")):
        model = "grok-4.7"
    elif keep_model and not model:
        model = "grok-4.7"
    if not effort or (not keep_model and effort == "default"):
        effort = "low"
    return provider, model, effort


def _private_brain(character: str, like):
    """Override, else the card, else the brain the caller was already on."""
    chosen = _override_brain(character, "private")
    card = _first_brain(character, "private") or {}
    brain = chosen or card
    if brain.get("provider"):
        provider = brain.get("provider") or ""
        model = brain.get("model") or ""
        effort = brain.get("effort") or ""
    else:
        provider = getattr(like, "provider", "") or ""
        model = getattr(like, "model", "") or ""
        effort = getattr(like, "effort", "") or ""
    return _fill_family_defaults(provider, model, effort, keep_model=bool(chosen))


def _first_brain(character: str, mode: str = "work") -> Dict[str, Any]:
    """The first entry of the character's brain list for `mode`, or {}. No fallback to `work`: a private
    session without a card-named private brain keeps the brain the user is on (get_private's `like`,
    operator decision 2026-09-27, pew/N4) instead of snapping back to the card's work default."""
    try:
        import characters
        card = characters.load(character, _s().WORKSPACE)
        chain = characters.brains(card, mode)
        return chain[0] if chain else {}
    except Exception:  # noqa: BLE001
        return {}
