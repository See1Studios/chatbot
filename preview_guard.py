"""File preview security guard and resolution.

Allow-list based safe path resolver for /api/file/preview and /api/file/raw.
Extracted from server.py during modular refactoring.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

import host_config

# Allow-list, not block-list: a preview link may only reach the project trees
# (services/projects/wiki, the shared .agents skills, the static web root) or a
# top-level doc in HOME. Anything else -- ~/.ssh, shell history, other dotdirs --
# is refused no matter what its name looks like. Hidden components *inside* an
# allowed tree are refused too (except .agents skill dirs).
_HOME_R = host_config.HOME.resolve()
_PREVIEW_ALLOWED_ROOTS = [
    (_HOME_R / "services"),
    (_HOME_R / "projects"),
    (_HOME_R / "wiki"),
    (_HOME_R / ".agents"),
    host_config.WEB_ROOT.resolve(),
]
_PREVIEW_HOME_DOC_SUFFIXES = {".md", ".txt"}
_SECRET_NAME_RE = re.compile(
    r"(?i)(^\.env($|\.)|oauth|token|secret|credential|passwd|password|api[_-]?key|auth\.json"
    r"|^id_(rsa|dsa|ecdsa|ed25519)|_history$|\.(pem|key|p12|pfx)$|^\.git-credentials$|^\.netrc$)"
)


def _preview_allowed(rp: Path) -> bool:
    import server
    home_r = getattr(server, "_HOME_R", _HOME_R)
    allowed_roots = getattr(server, "_PREVIEW_ALLOWED_ROOTS", _PREVIEW_ALLOWED_ROOTS)
    if rp.parent == home_r and rp.suffix.lower() in _PREVIEW_HOME_DOC_SUFFIXES:
        return not rp.name.startswith(".")
    for root in allowed_roots:
        try:
            rel = rp.relative_to(root)
        except ValueError:
            continue
        return not any(part.startswith(".") and part != ".agents" for part in rel.parts)
    return False


def _resolve_safe_preview_file(raw_path: str) -> Tuple[Optional[Path], Optional[str]]:
    import server
    home = getattr(server, "HOME", host_config.HOME)
    workspace = getattr(server, "WORKSPACE", host_config.WORKSPACE)
    if not raw_path:
        return None, "경로가 지정되지 않았습니다"
    raw = raw_path.strip()
    if raw.startswith("file://"):
        raw = raw[7:]
    if "#" in raw:
        raw = raw.split("#", 1)[0].strip()
    if raw.startswith("~/"):
        p = home / raw[2:]
    elif raw.startswith("/"):
        p = Path(raw)
    else:
        p1 = (workspace / raw).resolve()
        p = p1 if (p1.exists() and p1.is_file()) else (home / raw).resolve()
    try:
        rp = p.resolve()
    except Exception as e:
        return None, f"경로 해석 실패: {e}"
    if not rp.exists():
        return None, "디스크에 파일이 존재하지 않습니다"
    if not rp.is_file():
        return None, "디렉터리이거나 일반 파일이 아닙니다"
    if not _preview_allowed(rp):
        return None, "허용된 프로젝트 디렉터리 범위를 벗어난 경로입니다"
    for part in rp.parts:
        if _SECRET_NAME_RE.search(part):
            return None, "보안상 조회가 제한된 민감한 파일/경로입니다"
    return rp, None
