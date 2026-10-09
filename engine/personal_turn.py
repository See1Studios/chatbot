"""PERSONAL_TURN_v1 (docs/plans/private-mode.md §8.3, W1; engine-decides D1): a work-room turn marked personal
(flirting, affection, private feelings) stays in the chat but never becomes work material. The engine marks it
as the turn starts; the `personal_turn` tool can still mark one the engine left as work.

Core module: standard library only; every path derives from the `sessions` argument (<data>/sessions).
One file per session, `<sid>/personal-turns.jsonl`, one line per marked turn: {"turn": <user message ts>, "ts": ...}.
A turn is keyed by its user message's ts.

Readers (each closes one path into work material):
- mcp_server `_live_scope`: the memory and ticket tools are closed for the rest of a marked turn.
- workspace tool recall_memory.py: marked turns and their replies are not searchable from work.
- the page (`api`, GET /api/sessions/<sid>/personal-turns): a small lock on marked bubbles in the advanced density.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Set

FILE = "personal-turns.jsonl"
NAMES = ("personal_turn",)
TOOL_DEFS = [{
    "name": "personal_turn",
    "description": ("Call once, before replying, when the user's current message in a work session is personal rather "
                    "than work: flirting, affection, private feelings. The turn stays in the chat, but it is kept out "
                    "of work memory and tickets, and the work tools (memory, ticket, "
                    "delegate, web) close until the turn ends (PERSONAL_TURN_v1)."),
    "inputSchema": {"type": "object", "properties": {}},
}]


def key(turn) -> str:
    """The mark key of a user message ts ("" when it has none)."""
    try:
        return "%.3f" % float(turn)
    except (TypeError, ValueError):
        return ""


_mark_lock = threading.Lock()


def mark(sessions, sid: str, turn) -> bool:
    """Record that the turn started by the user message stamped `turn` is personal. False when it cannot be keyed.
    Marking a turn that is already marked writes nothing, so the tool's overwrite does not count twice."""
    k = key(turn)
    if not k or not sid or "/" in sid or "\\" in sid or sid.startswith("."):
        return False
    d = Path(sessions) / sid
    if not d.is_dir():
        return False
    with _mark_lock:
        if k in marked(sessions, sid):
            return True
        with open(d / FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"turn": float(k), "ts": time.time()}) + "\n")
    return True


def marked(sessions, sid: str) -> Set[str]:
    """Keys of the marked turns of session `sid` (compare with `key`)."""
    out: Set[str] = set()
    try:
        lines = (Path(sessions) / sid / FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            k = key(json.loads(line).get("turn"))
        except (ValueError, AttributeError):
            continue
        if k:
            out.add(k)
    return out


def is_marked(sessions, sid: str, turn) -> bool:
    k = key(turn)
    return bool(k) and k in marked(sessions, sid)


# The engine's judgment (engine-decides D1). One per work turn, started beside the turn and awaited before a work
# tool or a move chip. Overtime, silence, and any word other than personal or work count as work.
JUDGE_SEC = 2.0
_LINE_MAX = 400
_PROMPT = (
    "Classify this message as personal or work. "
    "personal means flirting, affection, or private feelings. "
    "work means anything else. "
    "Reply with exactly one word: personal or work.\n"
    "Message: %s"
)
_lock = threading.Lock()
_inflight: Dict[str, Any] = {}
_pending: Dict[tuple, Any] = {}


def _one_line(text: str) -> str:
    """The user's message collapsed to one line. The classifier sees this and nothing before it."""
    return " ".join(str(text or "").split())[:_LINE_MAX]


def _verdict(text: str) -> str:
    """personal or work when that is the first word; silence and every other word are work."""
    raw = str(text or "").strip().lower()
    if not raw:
        return "work"
    word = raw.split(None, 1)[0].strip(".,:;!?'\"`()[]")
    return word if word in ("personal", "work") else "work"


def _default_ask(line: str) -> str:
    """One shot on the configured provider. Under the test runner this stays empty: tests pass `ask`."""
    if os.environ.get("CHATBOT_TEST_RUNNER") == "1":
        return ""
    import session
    out = session._oneshot(_PROMPT % line, JUDGE_SEC)
    if not isinstance(out, dict):
        return ""
    return str(out.get("text") or "")


class _Job:
    def __init__(self, sessions, sid: str, line: str, ask):
        self.sessions, self.sid, self.line, self.ask = sessions, str(sid), line, ask
        self.turn = self.word = ""
        self.applied = False
        self.thread = None
        self.done = threading.Event()
        self.deadline = time.monotonic() + JUDGE_SEC

    def run(self) -> None:
        try:
            self.word = _verdict(self.ask(self.line))
        except Exception:
            self.word = "work"
        finally:
            self.done.set()
            _apply(self)


def _apply(job: "_Job") -> None:
    with _lock:
        if job.applied or not job.turn or not job.done.is_set():
            return
        job.applied = True
        personal = job.word == "personal"
        _pending.pop((job.sid, job.turn), None)
        if _inflight.get(job.sid) is job:
            _inflight.pop(job.sid, None)
    if personal:
        mark(job.sessions, job.sid, job.turn)


def start_judgment(sessions, sid: str, text: str, event_type: str = "", ask=None):
    """Start this work turn's judgment beside the turn. None for a scene line or an empty message.
    A work-room `/act` (`event_type` action) is personal with no model call. Anything else is one
    background classification; a reply after JUDGE_SEC counts as work."""
    if not sid or event_type == "scene":
        return None
    line = _one_line(text)
    if not line:
        return None
    job = _Job(sessions, sid, line, ask or _default_ask)
    if event_type == "action":
        job.word = "personal"
        job.done.set()
    else:
        job.thread = threading.Thread(target=job.run, daemon=True)
        job.thread.start()
    with _lock:
        _inflight[job.sid] = job
    return job


def bind_judgment(job, turn) -> None:
    """Attach the user-message ts. A judgment that already finished marks now."""
    if job is None:
        return
    k = key(turn)
    if not k:
        return
    with _lock:
        if job.applied or (job.turn and job.turn != k):
            return
        job.turn = k
        _pending[(job.sid, k)] = job
        if _inflight.get(job.sid) is job:
            _inflight.pop(job.sid, None)
    _apply(job)


def await_judgment(sessions, sid: str, turn) -> None:
    """Wait out this turn's judgment, then mark when it said personal. No-op when none is pending."""
    try:
        _await_judgment(sessions, sid, turn)
    except Exception:
        return


def _await_judgment(sessions, sid: str, turn) -> None:
    k = key(turn)
    sid = str(sid or "")
    if not k or not sid:
        return
    with _lock:
        job = _pending.get((sid, k))
        if job is None:
            job = _inflight.get(sid)
            if job is None or job.applied or (job.turn and job.turn != k):
                return
            job.turn = k
            _pending[(sid, k)] = job
            if _inflight.get(sid) is job:
                _inflight.pop(sid, None)
    remain = job.deadline - time.monotonic()
    if remain > 0:
        job.done.wait(remain)
    with _lock:
        if job.applied:
            return
        if not job.done.is_set():
            job.applied = True
            job.word = "work"
            _pending.pop((sid, k), None)
            if _inflight.get(sid) is job:
                _inflight.pop(sid, None)
            return
    _apply(job)


def running_turn(history):
    """The ts of the newest sent user message: the key of the turn a busy session is running."""
    for h in reversed(history or []):
        if h.get("role") == "user" and not h.get("queued"):
            return h.get("ts")
    return None


OFFER_WINDOW_SEC = 1800   # declined moves count within this window
OFFER_MAX = 2             # personal turns in a row that may offer a move; after that, stay quiet


def moved(sessions, sid: str) -> None:
    """Record that the user left this work session for the private room (threshold.py): the move offers reset."""
    d = Path(sessions) / sid
    if d.is_dir():
        with open(d / FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"moved": time.time()}) + "\n")


def offers_left(sessions, sid: str, now: float = 0.0) -> bool:
    """W2b cool-down: may this personal turn offer a move? Not after OFFER_MAX marks with no move in between
    (the user stayed at work each time), within OFFER_WINDOW_SEC."""
    now = now or time.time()
    try:
        rows = [json.loads(x) for x in (Path(sessions) / sid / FILE).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return True
    since = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        if "moved" in r:
            since = 0
        elif "turn" in r and now - float(r.get("ts") or 0) < OFFER_WINDOW_SEC:   # marks only, not offers
            since += 1
    return since <= OFFER_MAX


PLACES_PATH = Path(__file__).resolve().parent / "engine_data" / "places.json"


def places(state_path=None) -> List[Dict[str, str]]:
    """MOVE_CHOICE_v1 (ed/B2, D3): the places a move may go to -- the character's own (`places` in its state.json:
    names, or {id, name}), else the engine's defaults. [{id, name}]; a place of the character's has no catalog line."""
    try:
        own = json.loads(Path(state_path).read_text(encoding="utf-8")).get("places") if state_path else None
    except (OSError, ValueError, AttributeError, TypeError):
        own = None
    if isinstance(own, list) and own:
        out = [{"id": "", "name": str(p)} if isinstance(p, str) else {"id": "", "name": str(p.get("name") or "")}
               for p in own if isinstance(p, (str, dict))]
        return [p for p in out if p["name"].strip()]
    try:
        return [p for p in json.loads(PLACES_PATH.read_text(encoding="utf-8"))["places"] if p.get("name")]
    except (OSError, ValueError, KeyError, TypeError):
        return []


OFFICE = "office"   # PLACE_MOVE_v1: the one public place, the work room (private-mode.md §8.8)


def move_target(dest: str, state_path=None) -> str:
    """PLACE_MOVE_v1 (private-mode.md §8.8, W6): the room switch a `/move <dest>` means, as the room command the switch
    route takes: the work room for `office`, else the private room with the place as its first scene. A place given
    by its id is named by its catalog name (the scene line names the place)."""
    d = " ".join(str(dest or "").split())
    if d.lower() == OFFICE:
        return "/private off"
    hit = next((p for p in places(state_path) if p.get("id") and p["id"].lower() == d.lower()), None)
    return "/private on " + (hit["name"] if hit else d)


def _rows(sessions, sid: str) -> List[dict]:
    try:
        rows = [json.loads(x) for x in (Path(sessions) / sid / FILE).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def move_choices(sessions, sid: str, turn, state_path=None) -> List[Dict[str, Any]]:
    """The choices the engine adds to a marked personal turn's answer (ed/B2): a move to a place and "back to work",
    as page chips by catalog key; [] when the turn is not marked, the cool-down is on, or this turn got them already.
    The place is the one offered longest ago (never offered first), so the user is not asked the same twice.
    Back to work is the page command /stay: the chips close and the label is not said. Not a model command."""
    k = key(turn)
    if not k or not is_marked(sessions, sid, turn) or not offers_left(sessions, sid):
        return []
    rows = _rows(sessions, sid)
    if any(r.get("offer_for") == k for r in rows):
        return []
    options = places(state_path)
    if not options:
        return []
    last = {r.get("offer"): i for i, r in enumerate(rows) if "offer" in r}
    place = min(options, key=lambda p: last.get(p["name"], -1))
    with open(Path(sessions) / sid / FILE, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"offer": place["name"], "offer_for": k, "ts": time.time()}) + "\n")
    shown = {"key": "place." + place["id"]} if place.get("id") else place["name"]
    return [{"label": "A quick word in %s..." % place["name"], "label_key": "choice.move", "label_vars": {"place": shown},
             "kind": "command", "payload": "/move " + (place.get("id") or place["name"])},
            {"label": "Back to work", "label_key": "choice.back_to_work", "kind": "command", "payload": "/stay"}]


def tool_call(sessions, busy, active_sid) -> tuple:
    """(ok, message) for the `personal_turn` tool. `busy`: the host's running sessions ({id, mode, turn});
    the running work turn is marked -- the active one when several run."""
    work = [x for x in busy if x.get("mode") != "private"]
    if len(work) > 1:
        work = [x for x in work if x.get("id") == active_sid] or work[:1]
    if not work:
        return False, "no work turn is running"
    sid = str(work[0].get("id") or "")
    if not mark(sessions, sid, work[0].get("turn")):
        return False, "this turn cannot be marked"
    offer = ("The engine adds a move choice to your reply; do not write one." if offers_left(sessions, sid)
             else "No move is offered now: the user stayed at work the last times.")
    return True, "marked personal: this turn stays out of work memory and tickets. " + offer


_ROUTE = re.compile(r"^/api/sessions/([A-Za-z0-9._-]{1,80})/personal-turns$")


def api(method: str, path: str, body, sessions=None):
    """The page's read of one session's marks: (200, {"turns": [keys]}), or None for another route."""
    m = _ROUTE.match(path or "")
    if method != "GET" or not m:
        return None
    if sessions is None:
        from host_config import SESSIONS as sessions
    return 200, {"turns": sorted(marked(sessions, m.group(1)))}
