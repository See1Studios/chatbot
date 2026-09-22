"""Chatbot identity, read from this instance's own instruction files
(docs/plans/chatbot-host-portability.md, Phase 3).

Every identity fact comes from the instructions the model itself is given, so
what the model reads and what the host shows/prompts can never disagree, and no
name is hardcoded here or in the UI:

  AGENTS.md   front matter  title       the chatbot's job/role (top-of-window title)
  PERSONA.md  front matter  persona     the character's name (optional)
                            user_title  how the user is addressed
                            voice       one-line tone hint for host-built prompts
  PERSONA.md  body                      the personality and tone themselves

Always read from `WORKSPACE` at call time (never a module constant), so a second
chatbot with its own workspace has its own identity. Anything missing or broken
falls back to neutral defaults. The files are editable user data, so every value
is length-capped and stripped of control characters before use.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path
from typing import Dict, Optional

from host_config import ROOT, WORKSPACE

DEFAULTS = {"title": "Assistant", "persona": "", "user_title": "사용자", "voice": ""}
_LIMITS = {"title": 60, "persona": 40, "user_title": 20, "voice": 120}
_SOURCES = {"title": "AGENTS.md", "persona": "PERSONA.md", "user_title": "PERSONA.md", "voice": "PERSONA.md"}

_FRONT = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")

_lock = threading.Lock()
_cache: Dict[str, tuple] = {}  # path -> ((mtime_ns, size), front matter dict)


def parse_frontmatter(text: str) -> Dict[str, str]:
    """`key: value` lines between two `---` fences at the very top of a file.
    Blank lines and `#` comment lines are skipped, a trailing ` # note` is cut,
    and one pair of matching quotes around a value is removed. No nesting."""
    m = _FRONT.match(text or "")
    if not m:
        return {}
    out: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key.strip()] = val
    return out


def _clean(value: str, limit: int) -> str:
    return _CTRL.sub(" ", value or "").strip()[:limit].strip()


def _front(path: Path) -> Dict[str, str]:
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _cache.get(str(path))
        if hit and hit[0] == key:
            return hit[1]
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        fm = {}
    with _lock:
        _cache[str(path)] = (key, fm)
    return fm


def get_identity() -> Dict[str, str]:
    """{title, persona, user_title, voice, name}. `name` is what to call the
    chatbot in running text: the persona if there is one, else the title."""
    ident: Dict[str, str] = {}
    for k, default in DEFAULTS.items():
        val = _clean(_front(WORKSPACE / _SOURCES[k]).get(k, ""), _LIMITS[k])
        ident[k] = val or default
    ident["name"] = ident["persona"] or ident["title"]
    return ident


def user_title() -> str:
    return get_identity()["user_title"]


def display_name() -> str:
    """The name to put on the chatbot's own lines: persona if any, else title."""
    return get_identity()["name"]


def self_label() -> str:
    """How a host-built prompt introduces the chatbot: '<title> <persona>' when
    both exist and differ (프로듀서 냥피디), else whichever there is."""
    i = get_identity()
    if i["persona"] and i["persona"] != i["title"]:
        return f"{i['title']} {i['persona']}"
    return i["name"]


def voice_phrase(suffix: str = "로") -> str:
    """The tone hint as a clause ('친근한 냥체(~냥, ✦)로'), or '' when none is set."""
    v = get_identity()["voice"]
    return f"{v}{suffix}" if v else ""


def script_json(ident: Optional[Dict[str, str]] = None) -> str:
    """Identity as JSON that is safe inside an inline <script> (the values come
    from editable files): `<`, `>`, `&` and the JS line separators are escaped."""
    raw = json.dumps(ident or get_identity(), ensure_ascii=False)
    return (raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def seed_workspace_files(templates_dir: Optional[Path] = None, workspace: Optional[Path] = None) -> list:
    """New install: copy a neutral PERSONA.md template into the workspace only if
    the workspace has none. An existing file is never touched."""
    src_dir = templates_dir or (ROOT / "templates")
    dst_dir = workspace or WORKSPACE
    seeded = []
    for name in ("PERSONA.md",):
        src, dst = src_dir / name, dst_dir / name
        if src.is_file() and not dst.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            seeded.append(name)
    return seeded
