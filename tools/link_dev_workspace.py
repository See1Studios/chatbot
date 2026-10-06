#!/usr/bin/env python3
"""Point a dev install's workspace at the engine's own instructions (user-data-separation §0.1).

The dev build's charter, PROJECT, SELF-MODIFY, engine skills, docs and engine role packs live once, in
templates/dev-workspace/ of this repo. Agents open them by paths relative to their workspace, so each one is a
link there to the repo file -- never a copy. Role packs that exist only in the live workspace (for example a
shipped `art` pack customized on this install) are not under templates/dev-workspace/ and are never touched.

Dry run unless --apply. For each file under templates/dev-workspace/:
  ok       the workspace path already links to the repo file
  link     missing, or a copy byte-equal to the repo file: becomes the link
  backup   a copy that differs: it moves to <data>/backups/dev-workspace-<stamp>/ first, then becomes the link
  relink   a link that points elsewhere: becomes the link
Nothing else in the workspace is touched. Pass --data (default: the install's data dir from host_config).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "templates" / "dev-workspace"


def plan(data: Path, dev: Path = DEV) -> List[Tuple[str, str]]:
    """[(action, path relative to the workspace)] in a stable order."""
    ws = data / "workspace"
    out = []
    for src in sorted(p for p in dev.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rel = src.relative_to(dev).as_posix()
        dst = ws / rel
        if dst.is_symlink():
            out.append(("ok" if dst.resolve() == src.resolve() else "relink", rel))
        elif not dst.exists():
            out.append(("link", rel))
        elif dst.is_file() and dst.read_bytes() == src.read_bytes():
            out.append(("link", rel))
        else:
            out.append(("backup", rel))
    return out


def apply(data: Path, steps: List[Tuple[str, str]], dev: Path = DEV, stamp: str = "") -> Path:
    """Carry out `steps`; returns the backup folder (created only when something was backed up)."""
    ws = data / "workspace"
    backup = data / "backups" / ("dev-workspace-" + (stamp or time.strftime("%Y%m%d-%H%M%S")))
    for action, rel in steps:
        if action == "ok":
            continue
        src, dst = (dev / rel).resolve(), ws / rel
        if action == "backup":
            keep = backup / rel
            keep.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(dst), str(keep))
        elif dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
    return backup


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", help="the install's data dir (default: host_config.DATA)")
    ap.add_argument("--apply", action="store_true", help="make the links (default: only print the plan)")
    a = ap.parse_args(argv)
    if a.data:
        data = Path(a.data).expanduser()
    else:
        sys.path.insert(0, str(ROOT))
        from host_config import DATA as data
    if not (data / "workspace").is_dir():
        print("no workspace at %s" % (data / "workspace"), file=sys.stderr)
        return 2
    steps = plan(data)
    for action, rel in steps:
        print("%-7s %s" % (action, rel))
    if not a.apply:
        print("dry run: nothing changed (--apply to make the links)")
        return 0
    backup = apply(data, steps)
    if backup.is_dir():
        print("differing copies kept in %s" % backup)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

