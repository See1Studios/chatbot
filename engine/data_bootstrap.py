#!/usr/bin/env python3
"""First-run bootstrap of the user-data folder (user-data-separation uds/D).

A new install starts with an empty data folder (default ~/.pe). Copy templates/workspace/ onto that root and record
what was copied. A workspace directory that already has files is left untouched (the flatten moves it). An empty
workspace directory is removed so it cannot hide the root. Never overwrite, and never fill in single files: a skill
or role the user deleted must not come back on the next start.

  python3 data_bootstrap.py [--data DIR] [--dry-run]    # chatbot-ctl.sh runs it with --data "$DATA"

The copy is staged next to the workspace and renamed into place, so a crash leaves either nothing or the whole
template. bootstrap.json (beside the workspace, not inside it) keeps each copied file's sha256: a later engine update
can tell which template files the user never changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List
import platform_compat
import repo_layout

ROOT = Path(__file__).resolve().parent
TEMPLATE = repo_layout.TEMPLATES / "workspace"
MARKER = "bootstrap.json"
SKELETON = ("sessions",)   # what the app expects beside the charter files


def _files(src: Path) -> List[Path]:
    return sorted(p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _occupied(data: Path) -> bool:
    """A non-empty real workspace, a workspace symlink, or a charter already on the root."""
    legacy = data / "workspace"
    if legacy.is_symlink():
        return True
    if legacy.is_dir() and any(legacy.iterdir()):
        return True
    return (data / "AGENTS.md").exists() or (data / "roles").is_dir()


def _install(data: Path, stage: Path) -> None:
    legacy = data / "workspace"
    if legacy.is_dir() and not legacy.is_symlink():
        legacy.rmdir()   # empty; a racing writer makes this fail loudly instead of merging
    for child in list(stage.iterdir()):
        dest = data / child.name
        if dest.exists():
            raise FileExistsError("bootstrap would overwrite %s" % dest.name)
        child.rename(dest)


def bootstrap(data: Path, template: Path = TEMPLATE, dry_run: bool = False) -> Dict:
    """{"created": bool, "files": [relative paths]}. Copies only when the data root has no charter yet."""
    data = Path(data)
    if _occupied(data):
        return {"created": False, "files": []}
    if not template.is_dir():
        raise FileNotFoundError("workspace template missing: %s" % template)
    files = _files(template)
    rels = [p.relative_to(template).as_posix() for p in files]
    if dry_run:
        return {"created": False, "files": rels, "dry_run": True}
    data.mkdir(parents=True, exist_ok=True)
    os.chmod(data, 0o700)   # personal data (memory, characters, sessions); a first run may find it made by others
    stage = data / (".workspace.bootstrap-%d" % os.getpid())
    shutil.rmtree(stage, ignore_errors=True)
    try:
        for src, rel in zip(files, rels):
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        _install(data, stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    for d in SKELETON:
        (data / d).mkdir(parents=True, exist_ok=True)
    marker = {"version": 1, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "template": "templates/workspace",
              "files": {rel: _sha(data / rel) for rel in rels}}
    tmp = data / (".%s.tmp" % MARKER)
    platform_compat.write_text(tmp, json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(data / MARKER)
    return {"created": True, "files": rels}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fill an empty user-data folder from templates/workspace")
    ap.add_argument("--data", default="", help="data folder (default: host_config.DATA)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be copied; write nothing")
    ap.add_argument("--quiet", action="store_true", help="print only when something was copied")
    args = ap.parse_args(argv)
    if args.data:
        data = Path(args.data)
    else:
        from host_config import DATA as data
    res = bootstrap(Path(data), dry_run=args.dry_run)
    if res.get("dry_run"):
        print("would copy %d template files into %s" % (len(res["files"]), Path(data)))
    elif res["created"]:
        print("bootstrap: new workspace in %s (%d template files)" % (Path(data), len(res["files"])))
    elif not args.quiet:
        print("bootstrap: %s already has a workspace; nothing copied" % data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
