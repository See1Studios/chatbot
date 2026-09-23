"""Session media staging, image harvesting, and markdown path rewriting.

Finds media the agents generated -- workspace artifacts plus whatever each provider's registered
MediaSource points at -- and maps it to web-servable /artifacts/... endpoints.
Extracted from session.py during modular refactoring.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Optional

import host_config as HC


def _cfg(name: str):
    try:
        import session
        if hasattr(session, name):
            return getattr(session, name)
    except Exception:
        pass
    return getattr(HC, name)


class MediaSource:
    """Where one CLI keeps media it generated (PROVIDER_NEUTRAL_v1). This module knows no provider;
    provider modules register one of these (adapters.py) and every function below asks all of them."""

    def artifact_dirs(self, conversation_id: Optional[str]) -> List[Path]:
        """This conversation's own folders, listed in the artifacts tab."""
        return []

    def scan_dirs(self, conversation_id: Optional[str], cutoff: float) -> List[Path]:
        """Folders to search for images made during the turn (files newer than `cutoff`)."""
        return []

    def text_roots(self) -> List[Path]:
        """Absolute folders the model's text may point into; such paths are staged and served."""
        return []

    def rel_bases(self, conversation_id: Optional[str]) -> List[Path]:
        """Where a relative `images/x.png` in the model's text resolves."""
        return []


_SOURCES: List[MediaSource] = []


def register_media_source(source: MediaSource) -> None:
    if not any(type(s) is type(source) for s in _SOURCES):
        _SOURCES.append(source)


def _gather(method: str, *args) -> List[Path]:
    out: List[Path] = []
    for src in list(_SOURCES):
        try:
            for p in getattr(src, method)(*args) or []:
                if p and p not in out:
                    out.append(Path(p))
        except Exception:
            continue
    return out


def _artifact_dirs(conversation_id: Optional[str]) -> List[Path]:
    return [d for d in _gather("artifact_dirs", conversation_id) if d.is_dir()]


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


def _stage_rel_media(sid: str, conversation_id: Optional[str], rel: str) -> Optional[str]:
    name = Path(rel or "").name
    if not name or name in (".", ".."):
        return None
    if Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".svg"}:
        return None
    candidates = []
    for base in _gather("rel_bases", conversation_id):
        candidates.append(base / rel)
        candidates.append(base / "images" / name)
        candidates.append(base / "videos" / name)
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
    cutoff = since_ts or (last_activity - 600)
    workspace = _cfg("WORKSPACE")
    artifacts_cache = _cfg("ARTIFACTS_CACHE")
    roots = [workspace / "artifacts", artifacts_cache] + _gather("scan_dirs", conversation_id, cutoff)
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

    text_roots = _gather("text_roots")
    workspace = _cfg("WORKSPACE")
    artifacts_cache = _cfg("ARTIFACTS_CACHE")
    sessions = _cfg("SESSIONS")
    data = _cfg("DATA")

    def repl_path(m: re.Match) -> str:
        raw = m.group(0)
        for prefix, label in [(str(r) + "/", "brain/") for r in text_roots] + [
            (str(workspace / "artifacts") + "/", ""),
            (str(artifacts_cache) + "/", ""),
            (str(workspace) + "/", ""),
        ]:
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

    for root in text_roots:
        text = re.sub(
            r"(?:file://)?(" + re.escape(str(root)) + r"/[^\s\)\"']+\.(?:png|jpe?g|gif|webp|svg|mp4|webm))",
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
        url = _stage_rel_media(sid, conversation_id, m.group(2))
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
