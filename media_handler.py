"""Session media staging, image harvesting, and markdown path rewriting.

Extracts local/generated brain, workspace artifacts, and Grok media files
and maps them to web-servable /artifacts/... endpoints.
Extracted from session.py during modular refactoring.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import host_config as HC


def _cfg(name: str):
    try:
        import session
        if hasattr(session, name):
            return getattr(session, name)
    except Exception:
        pass
    return getattr(HC, name)


def _conversation_brain_dir(conversation_id: Optional[str]) -> Optional[Path]:
    if not conversation_id:
        return None
    brain = _cfg("BRAIN")
    d = brain / conversation_id
    return d if d.is_dir() else None


def _newest_grok_dir_with_images(parent: Path) -> Optional[Path]:
    newest = None
    newest_mtime = -1.0
    try:
        for d in parent.iterdir():
            if not d.is_dir():
                continue
            img = d / "images"
            try:
                if not img.is_dir():
                    continue
                mt = img.stat().st_mtime
            except OSError:
                continue
            if mt > newest_mtime:
                newest_mtime = mt
                newest = d
    except OSError:
        pass
    return newest


def _grok_media_dir(conversation_id: Optional[str]) -> Optional[Path]:
    """Grok Imagine writes to ~/.grok/sessions/<urlencoded cwd>/<cid>/images/.

    conversation_id is often still empty on the first grok turn because the
    CLI reports sessionId only on the `end` event — after we used to rewrite
    markdown. If cid is missing or does not match a folder, fall back to the
    newest session under this workspace that actually has an images/ dir.
    """
    home = _cfg("HOME")
    workspace = _cfg("WORKSPACE")
    root = home / ".grok" / "sessions"
    if not root.is_dir():
        return None
    ws_enc = root / quote(str(workspace), safe="")
    cid = str(conversation_id or "").strip()
    if cid:
        exact = ws_enc / cid
        if exact.is_dir():
            return exact
        try:
            for enc in root.iterdir():
                d = enc / cid
                if d.is_dir():
                    return d
        except OSError:
            pass
    if ws_enc.is_dir():
        return _newest_grok_dir_with_images(ws_enc)
    return None


def _stage_image(sid: str, src: Path) -> Optional[str]:
    try:
        sessions = _cfg("SESSIONS")
        dest_dir = sessions / sid / "artifacts" / "brain"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dest)
        return f"/artifacts/{sid}/brain/{src.name}"
    except Exception:
        return None
        return None


def _stage_grok_rel_media(sid: str, conversation_id: Optional[str], rel: str) -> Optional[str]:
    name = Path(rel or "").name
    if not name or name in (".", ".."):
        return None
    if Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".svg"}:
        return None
    gdir = _grok_media_dir(conversation_id)
    candidates = []
    if gdir:
        candidates.append(gdir / rel)
        candidates.append(gdir / "images" / name)
        candidates.append(gdir / "videos" / name)
    sessions = _cfg("SESSIONS")
    staged = sessions / sid / "artifacts" / "brain" / name
    candidates.append(staged)
    for src in candidates:
        try:
            if not src.is_file():
                continue
            if src == staged:
                return f"/artifacts/{sid}/brain/{name}"
            return _stage_image(sid, src)
        except OSError:
            continue
    return None


def _collect_new_images(conversation_id: Optional[str], last_activity: float, since_ts: Optional[float] = None) -> List[Path]:
    """Find recent image files for this conversation / workspace."""
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    found: List[Path] = []
    roots = []
    bdir = _conversation_brain_dir(conversation_id)
    if bdir:
        roots.append(bdir)
        roots.append(bdir / ".tempmediaStorage")
        roots.append(bdir / ".system_generated")
    workspace = _cfg("WORKSPACE")
    artifacts_cache = _cfg("ARTIFACTS_CACHE")
    brain = _cfg("BRAIN")
    roots.append(workspace / "artifacts")
    roots.append(artifacts_cache)
    gdir = _grok_media_dir(conversation_id)
    if gdir:
        roots.append(gdir / "images")
        roots.append(gdir / "videos")
        roots.append(gdir)
    cutoff = since_ts or (last_activity - 600)
    try:
        if brain.exists():
            for sub in brain.iterdir():
                if sub == bdir or not sub.is_dir():
                    continue
                try:
                    if sub.stat().st_mtime >= cutoff - 5:
                        roots.append(sub)
                except OSError:
                    continue
    except Exception:
        pass
    for root in roots:
        if not root or not Path(root).exists():
            continue
        try:
            for fp in Path(root).rglob("*"):
                if not fp.is_file():
                    continue
                if fp.suffix.lower() not in exts:
                    continue
                try:
                    if fp.stat().st_mtime >= cutoff - 5:
                        found.append(fp)
                except OSError:
                    continue
        except Exception:
            continue
    found.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    uniq = []
    seen_names = set()
    seen_sizes = set()
    for fp in found:
        if fp.name in seen_names:
            continue
        try:
            sz = fp.stat().st_size
            if sz in seen_sizes and sz > 5000:
                continue
            seen_sizes.add(sz)
        except OSError:
            pass
        seen_names.add(fp.name)
        uniq.append(fp)
    return uniq[:8]


def _rewrite_artifact_paths(sid: str, conversation_id: Optional[str], text: str) -> str:
    if not text:
        return text

    brain = _cfg("BRAIN")
    workspace = _cfg("WORKSPACE")
    artifacts_cache = _cfg("ARTIFACTS_CACHE")
    sessions = _cfg("SESSIONS")
    data = _cfg("DATA")

    def repl_path(m: re.Match) -> str:
        raw = m.group(0)
        for prefix, label in (
            (str(brain) + "/", "brain/"),
            (str(workspace / "artifacts") + "/", ""),
            (str(artifacts_cache) + "/", ""),
            (str(workspace) + "/", ""),
        ):
            if raw.startswith(prefix):
                rel = label + raw[len(prefix):] if label.startswith("brain") else raw[len(prefix):]
                try:
                    src = Path(raw)
                    if src.is_file() and label.startswith("brain"):
                        dest = sessions / sid / "artifacts" / "brain" / src.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
                            shutil.copy2(src, dest)
                        return f"/artifacts/{sid}/brain/{src.name}"
                except Exception:
                    pass
                return "/artifacts/" + rel.lstrip("/")
        return raw

    text = re.sub(
        r"(?:file://)?(" + re.escape(str(brain)) + r"/[^\s\)\"']+\.(?:png|jpe?g|gif|webp|svg|mp4|webm))",
        repl_path,
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(?:file://)?(" + re.escape(str(data)) + r"/(?:workspace/)?artifacts/[^\s\)\"']+)",
        repl_path,
        text,
        flags=re.I,
    )

    def repl_rel(m: re.Match) -> str:
        url = _stage_grok_rel_media(sid, conversation_id, m.group(2))
        return (m.group(1) + url) if url else m.group(0)

    text = re.sub(
        r'(!\[[^\]]*\]\()(?:\./)?((?:images|videos)/[^\s\)\"\']+)',
        repl_rel,
        text,
        flags=re.I,
    )
    return text


def _append_images_markdown(sid: str, conversation_id: Optional[str], last_activity: float, text: str, since_ts: Optional[float] = None) -> str:
    # Rel `images/1.jpg` in the model text is not a served URL. Rewrite first
    # so a later stem-dedupe does not skip staging (live 2026-09-21: history
    # kept `images/1.jpg`, brain/ was empty, chat 404).
    text = _rewrite_artifact_paths(sid, conversation_id, text or "")
    imgs = _collect_new_images(conversation_id, last_activity, since_ts)
    if not imgs:
        return text
    existing_imgs = re.findall(r"!\[.*?\]\((.*?)\)", text)
    existing_stems = set()
    for u in existing_imgs:
        u0 = (u.split("?")[0] or "").strip()
        if re.match(r"^(?:\./)?(?:images|videos)/", u0, re.I):
            continue
        stem = Path(u0).stem.lower()
        if stem:
            existing_stems.add(stem)
    lines = []
    for src in imgs:
        if src.stem.lower() in existing_stems:
            continue
        url = _stage_image(sid, src)
        if not url or url in text:
            continue
        existing_stems.add(src.stem.lower())
        lines.append(f"![{src.stem}]({url})")
    if not lines:
        return text
    sep = "\n\n" if text.strip() else ""
    return text.rstrip() + sep + "\n".join(lines) + "\n"
