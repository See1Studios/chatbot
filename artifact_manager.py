"""Artifact resolution, safe session IDs, and atomic file operations.

Extracted from session.py during monolith-split / modular refactor.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from host_config import (
    ARTIFACTS_CACHE,
    BRAIN,
    DATA,
    HOME,
    SESSIONS,
    WORKSPACE,
)


def _safe_session_id(sid: str) -> str:
    sid = (sid or "").strip()
    if not sid or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in sid):
        raise ValueError("invalid session id")
    return sid


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` without ever leaving a torn/partial file for
    a concurrent reader: write to a per-call-unique tmp sibling, then
    replace() (atomic on the same filesystem). Raises on failure; a caller
    that wants a soft-fail (e.g. AgySession.save_meta) catches around this
    itself instead of this helper swallowing errors silently."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise


def _safe_artifact_rel(rel: str) -> Optional[Path]:
    rel = unquote(rel or "").lstrip("/")
    if not rel:
        return None
    parts = rel.split("/")
    # Reject path traversal and dotfile components.
    if any(p == ".." or p.startswith(".") for p in parts):
        return None
    if rel.startswith("\\"):
        return None
    candidates = [
        ARTIFACTS_CACHE / rel,
        WORKSPACE / "artifacts" / rel,
        DATA / "persona" / rel,
        DATA / "persona" / "gallery" / rel,
    ]
    # /artifacts/<session_id>/... -> sessions/<session_id>/artifacts/...
    # (session-owned generated media lives inside that session's own folder now)
    if "/" in rel:
        sid_part, rest = rel.split("/", 1)
        candidates.append(SESSIONS / sid_part / "artifacts" / rest)
    for fp in candidates:
        try:
            rp = fp.resolve()
        except Exception:
            continue
        allowed_roots = [
            ARTIFACTS_CACHE.resolve(),
            (WORKSPACE / "artifacts").resolve() if (WORKSPACE / "artifacts").exists() else None,
            SESSIONS.resolve(),
            (DATA / "persona").resolve(),
        ]
        for root in allowed_roots:
            if root is None:
                continue
            try:
                rp.relative_to(root)
                if rp.is_file():
                    return rp
            except ValueError:
                continue
    # Basename fallback: gallery/persona files used to be listed as
    # /artifacts/<filename> (no subdir), which 404'd. Also covers old
    # chat-history markdown that still points at those URLs.
    base = Path(rel).name
    if base and re.search(r"\.(png|jpe?g|gif|webp|svg|mp4|webm|wav|mp3|md|txt|json|pdf|html|csv|yaml|yml|py|js|ts|gd|sh|css)$", base, re.I):
        extra_roots = [
            DATA / "persona" / "gallery",
            DATA / "persona",
            WORKSPACE / "artifacts",
            ARTIFACTS_CACHE,
        ]
        allowed = []
        for r in extra_roots:
            try:
                if r.exists():
                    allowed.append(r.resolve())
            except Exception:
                continue

        def _within(hit: Path) -> Optional[Path]:
            try:
                rp = hit.resolve()
            except Exception:
                return None
            if not rp.is_file():
                return None
            for root in allowed:
                try:
                    rp.relative_to(root)
                    return rp
                except ValueError:
                    continue
            return None

        for root in extra_roots:
            if not root.exists():
                continue
            found = _within(root / base)
            if found:
                return found
            try:
                for hit in root.rglob(base):
                    if hit.name != base:
                        continue
                    found = _within(hit)
                    if found:
                        return found
            except Exception:
                continue
    return None
