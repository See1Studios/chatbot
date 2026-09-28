#!/usr/bin/env python3
"""First-run bootstrap of the user-data folder (user-data-separation uds/D).

A new install starts with an empty data folder (default ~/.pe once uds/F flips it). If its workspace is missing or
empty, copy templates/workspace/ into it and record what was copied; otherwise do nothing. It never overwrites and
never fills in single files: a skill or role the user deleted must not come back on the next start.

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

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "templates" / "workspace"
MARKER = "bootstrap.json"
SKELETON = ("sessions", "artifacts", "persona", "workspace/memory")   # what the app expects beside the workspace


def _is_fresh(ws: Path) -> bool:
    return not ws.exists() or (ws.is_dir() and not any(ws.iterdir()))


def _files(src: Path) -> List[Path]:
    return sorted(p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bootstrap(data: Path, template: Path = TEMPLATE, dry_run: bool = False) -> Dict:
    """{"created": bool, "files": [relative paths]}. Copies only when data/workspace is missing or empty."""
    data = Path(data)
    ws = data / "workspace"
    if not _is_fresh(ws):
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
        if ws.exists():
            ws.rmdir()   # empty (checked above); a racing writer makes this fail loudly instead of merging
        stage.rename(ws)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    for d in SKELETON:
        (data / d).mkdir(parents=True, exist_ok=True)
    marker = {"version": 1, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "template": "templates/workspace",
              "files": {rel: _sha(ws / rel) for rel in rels}}
    tmp = data / (".%s.tmp" % MARKER)
    tmp.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        print("would copy %d template files into %s" % (len(res["files"]), Path(data) / "workspace"))
    elif res["created"]:
        print("bootstrap: new workspace in %s (%d template files)" % (Path(data) / "workspace", len(res["files"])))
    elif not args.quiet:
        print("bootstrap: %s already has a workspace; nothing copied" % data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
