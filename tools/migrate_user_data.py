#!/usr/bin/env python3
"""Copy a Private Engine data directory to a new home (user-data-separation).

Dry-run unless --apply. The source is never deleted unless --remove-source
is set, and then only after every file to be removed matches the destination
byte for byte. If any of those files differ or are missing at the destination,
nothing is deleted.

A destination that already contains a file is refused unless --force.
--force still does not overwrite a destination file whose bytes differ.

This tool does not read the data-path environment variables or the checkout
pin (uds/B). Pass --source and, if needed, --dest. The default destination
is ~/.pe.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan(source):
    files = []
    unsupported = []
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        kept = []
        for name in dirnames:
            full = Path(dirpath) / name
            if full.is_symlink():
                unsupported.append(full.relative_to(source).as_posix())
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(source).as_posix()
            if full.is_symlink() or full.is_file():
                files.append(rel)
            else:
                unsupported.append(rel)
    return files, unsupported


def _same(src, dst):
    if src.is_symlink() or dst.is_symlink():
        return src.is_symlink() and dst.is_symlink() and os.readlink(src) == os.readlink(dst)
    if not src.is_file() or not dst.is_file():
        return False
    if src.stat().st_size != dst.stat().st_size:
        return False
    return _sha256(src) == _sha256(dst)


def _has_files(dest):
    if not dest.exists():
        return False
    if not dest.is_dir():
        return True
    for dirpath, dirnames, filenames in os.walk(dest, followlinks=False):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        if filenames:
            return True
    return False


def _tracked(source):
    top = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=30,
    )
    if top.returncode != 0:
        return None
    root = Path(top.stdout.strip())
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", str(source)],
        capture_output=True, timeout=60,
    )
    if listed.returncode != 0:
        return None
    found = set()
    base = source.resolve()
    for raw in listed.stdout.split(b"\0"):
        if not raw:
            continue
        path = Path(os.fsdecode(raw))
        if not path.is_absolute():
            path = root / path
        try:
            found.add(path.resolve().relative_to(base).as_posix())
        except ValueError:
            continue
    return found


def _copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        os.symlink(os.readlink(src), dst)
        return
    tmp = dst.with_name(dst.name + ".migrate-tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    shutil.copy2(str(src), str(tmp))
    os.replace(str(tmp), str(dst))


def _remove_empty_dirs(source, keep):
    protected = set()
    for rel in keep:
        parent = Path(rel).parent
        while str(parent) not in ("", "."):
            protected.add(parent.as_posix())
            parent = parent.parent
    for dirpath, dirnames, filenames in os.walk(source, topdown=False, followlinks=False):
        current = Path(dirpath)
        if current.resolve() == source.resolve():
            continue
        rel = current.relative_to(source).as_posix()
        if rel in protected or filenames or dirnames:
            continue
        try:
            current.rmdir()
        except OSError:
            pass


def migrate(source, dest, apply, force, remove_source, keep_tracked):
    source = source.resolve()
    if not source.is_dir():
        print("source is not a directory: %s" % source, file=sys.stderr)
        return 1
    dest_resolved = dest.resolve() if dest.exists() else dest.absolute()
    if source == dest_resolved or source in dest_resolved.parents or dest_resolved in source.parents:
        print("source and dest must be separate directories", file=sys.stderr)
        return 2
    files, unsupported = _scan(source)
    if unsupported:
        print("unsupported files (nothing was copied or deleted): %d" % len(unsupported), file=sys.stderr)
        for rel in unsupported[:20]:
            print("  %s" % rel, file=sys.stderr)
        return 1
    nonempty = _has_files(dest) if dest.exists() else False
    conflicts = []
    if dest.exists() and dest.is_dir():
        for rel in files:
            target = dest / rel
            if target.exists() or target.is_symlink():
                if not _same(source / rel, target):
                    conflicts.append(rel)
    total = 0
    for rel in files:
        path = source / rel
        if not path.is_symlink():
            total += path.stat().st_size
    print("source: %s" % source)
    print("dest: %s" % dest)
    print("files: %d" % len(files))
    print("bytes: %d" % total)
    print("mode: %s" % ("apply" if apply else "dry-run"))
    print("dest_has_files: %s" % ("yes" if nonempty else "no"))
    print("conflicts: %d" % len(conflicts))
    if nonempty and not force:
        print("refusing nonempty destination without --force", file=sys.stderr)
        return 2
    if conflicts:
        print("refusing to overwrite %d destination files that differ" % len(conflicts), file=sys.stderr)
        return 3
    if not apply:
        return 0
    created = not dest.exists()
    dest.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(dest, 0o700)
    copied = 0
    for rel in files:
        target = dest / rel
        origin = source / rel
        if (target.exists() or target.is_symlink()) and _same(origin, target):
            continue
        _copy_file(origin, target)
        copied += 1
    print("copied: %d" % copied)
    if not remove_source:
        return 0
    tracked = set()
    if keep_tracked:
        tracked = _tracked(source)
        if tracked is None:
            print("refusing to delete source: --keep-tracked needs a git checkout", file=sys.stderr)
            return 4
    doomed = [rel for rel in files if rel not in tracked]
    mismatched = [rel for rel in doomed if not _same(source / rel, dest / rel)]
    if mismatched:
        print("refusing to delete source: %d files do not match dest" % len(mismatched), file=sys.stderr)
        for rel in mismatched[:20]:
            print("  %s" % rel, file=sys.stderr)
        return 4
    for rel in doomed:
        path = source / rel
        if path.is_symlink() or path.is_file():
            path.unlink()
    _remove_empty_dirs(source, tracked)
    print("removed_from_source: %d" % len(doomed))
    print("kept_tracked: %d" % len(tracked & set(files)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Copy a data directory to ~/.pe (dry-run by default).")
    parser.add_argument("--source", required=True, type=Path, help="Existing data directory to read")
    parser.add_argument("--dest", type=Path, default=None, help="Destination (default: ~/.pe)")
    parser.add_argument("--apply", action="store_true", help="Actually copy. Without this, only print the plan.")
    parser.add_argument("--force", action="store_true", help="Allow a destination that already has files. Never overwrites differing bytes.")
    parser.add_argument("--remove-source", action="store_true", help="After a verified copy, delete matching source files. Requires --apply.")
    parser.add_argument("--keep-tracked", action="store_true", help="With --remove-source, leave git-tracked files in the source tree.")
    args = parser.parse_args(argv)
    if args.remove_source and not args.apply:
        print("--remove-source requires --apply", file=sys.stderr)
        return 1
    dest = args.dest if args.dest is not None else Path.home() / ".pe"
    return migrate(args.source, dest, args.apply, args.force, args.remove_source, args.keep_tracked)


if __name__ == "__main__":
    sys.exit(main())
