#!/usr/bin/env python3
"""Move workspace/ up onto the data root and leave workspace -> . (flat/D).

Dry-run unless --apply. A workspace that already points at `.` is left as it is.
The only overlap this accepts is an empty artifacts/ directory at the data root:
that directory is removed and the workspace artifacts take its place. Any other
name that exists at both levels is a collision and nothing is moved.

Sessions, logs, backups, and secrets stay where they are. This tool does not
read the data-path environment. Pass --data.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


class FlattenError(Exception):
    pass


def rename(src: Path, dst: Path) -> None:
    os.rename(src, dst)


def _empty_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and not any(path.iterdir())


def plan(data: Path) -> list:
    """Steps that make `data / "workspace"` a symlink to `.`. Empty when it already is."""
    data = Path(data)
    ws = data / "workspace"
    if ws.is_symlink():
        if os.readlink(ws) == ".":
            return []
        raise FlattenError("workspace symlink points at %s" % os.readlink(ws))
    if not ws.is_dir():
        raise FlattenError("no workspace directory")
    steps = []
    for child in sorted(ws.iterdir(), key=lambda p: p.name):
        dest = data / child.name
        if not dest.exists() and not dest.is_symlink():
            steps.append(("rename", child, dest))
            continue
        if child.name == "artifacts" and _empty_dir(dest) and child.is_dir() and not child.is_symlink():
            steps.append(("rmdir", dest))
            steps.append(("rename", child, dest))
            continue
        raise FlattenError("collision: %s" % child.name)
    steps.append(("symlink", ws))
    return steps


def _symlink(ws: Path) -> None:
    ws.rmdir()
    try:
        ws.symlink_to(".", target_is_directory=True)
    except Exception:
        ws.mkdir()
        raise


def _run(step) -> None:
    kind = step[0]
    if kind == "rename":
        rename(step[1], step[2])
    elif kind == "rmdir":
        step[1].rmdir()
    elif kind == "symlink":
        _symlink(step[1])
    else:
        raise FlattenError("unknown step %s" % kind)


def _undo(step) -> None:
    kind = step[0]
    if kind == "rename":
        rename(step[2], step[1])
    elif kind == "rmdir":
        step[1].mkdir()
    elif kind == "symlink":
        step[1].unlink()
        step[1].mkdir()
    else:
        raise FlattenError("unknown step %s" % kind)


def apply(data: Path) -> list:
    """Run `plan`. On failure, put back what already moved and raise."""
    steps = plan(data)
    done = []
    try:
        for step in steps:
            _run(step)
            done.append(step)
    except Exception:
        for step in reversed(done):
            _undo(step)
        raise
    return steps


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Flatten workspace/ onto the data root")
    parser.add_argument("--data", required=True, help="Data directory (the install root, not workspace/)")
    parser.add_argument("--apply", action="store_true", help="Move files. Without this, print the plan only.")
    args = parser.parse_args(argv)
    data = Path(args.data)
    try:
        steps = apply(data) if args.apply else plan(data)
    except FlattenError as exc:
        print("flatten: %s" % exc, file=sys.stderr)
        return 2
    if not steps:
        print("already flat: %s" % data)
        return 0
    for step in steps:
        print(" ".join(str(part) for part in step))
    print("applied" if args.apply else "dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
