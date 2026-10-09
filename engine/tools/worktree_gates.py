"""Which tests a delegation's gates run (split from worktree_runner.py, #868): the repo-wide guards from
run-tests.sh's committed FAST list, and the test modules related to the changed files. Everything is read as
committed at HEAD -- what a worktree made from HEAD holds -- never from the main tree.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import repo_layout


def head_files(repo: Path, rels: List[str]) -> Dict[str, str]:
    """The text of each path as committed at HEAD -- what a worktree made from HEAD holds; a path not in HEAD is left
    out. The gates are read here, never from the main tree, so nothing uncommitted there reaches a delegation (#547:
    a guard listed in the main tree's run-tests.sh but not yet committed failed two delegations as MISSING)."""
    if not rels:
        return {}
    try:
        r = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], capture_output=True, timeout=60,
                           input="".join("HEAD:%s\n" % rel for rel in rels).encode("utf-8"))
    except (OSError, subprocess.SubprocessError):
        return {}
    out, data, i = {}, r.stdout, 0
    for rel in rels:
        end = data.find(b"\n", i)
        head = data[i:end].split()
        i = end + 1
        if len(head) == 3 and head[1] == b"blob":
            n = int(head[2])
            out[rel] = data[i:i + n].decode("utf-8", "replace")
            i += n + 1
    return out


def head_tests(repo: Path) -> List[str]:
    """tests/test_*.py committed at HEAD, as module names."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-tree", "--name-only", "HEAD", "tests/"], capture_output=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    names = r.stdout.decode("utf-8", "replace").split()
    return sorted(Path(n).stem for n in names if re.match(r"^tests/test_\w+\.py$", n))


def guard_gate(repo: Path) -> Optional[str]:
    """run-tests.sh over its committed FAST list, each guard named as a path so gate_files() protects it: a worker
    cannot change its own pass condition (pew/F)."""
    runner = repo_layout.engine_rel(repo, "run-tests.sh")
    text = head_files(repo, [runner]).get(runner)
    if text is None:
        return None
    m = re.search(r"^FAST=\((.*?)^\)", text, re.S | re.M)
    mods = [w for w in (m.group(1).split() if m else []) if re.match(r"^test_\w+$", w)]
    have = set(head_tests(repo))
    files = ["tests/%s.py" % w for w in mods if w in have]
    return "./%s %s" % (runner, " ".join(files)) if files else None


def _mentions(path: str) -> "re.Pattern":
    """How a test shows it depends on `path`: a .py module imported (`import x`, `from x import`, `from pkg import x`)
    or named as a file (`x.py`); any other file by its name (`protected_paths.json`). A bare word is not enough --
    `session` appears in half the tests."""
    name = Path(path).name
    if name.endswith(".py"):
        stem = re.escape(Path(path).stem)
        return re.compile(r"(?:^|\s)(?:import\s+(?:\w+\.)*%s\b|from\s+(?:\w+\.)*%s\s+import\b|from\s+[\w.]+\s+import\s+"
                          r"(?:[\w, ]*,\s*)?%s\b)|\b%s\b" % (stem, stem, stem, re.escape(name)), re.M)
    return re.compile(r"\b%s\b" % re.escape(name))


def related_gate(repo: Path, paths: List[str]) -> Optional[str]:
    """The test modules that belong to the changed files: tests/test_<stem>.py, a changed test itself, and every test
    that imports or names a changed file (pew/P: protected_paths.json -> test_lifecycle, missed on 2026-09-28).
    Guards already run in DEFAULT_GATES are left out. Named without a path on purpose: gate_files() must not lock a
    test the task is meant to update."""
    guard = guard_gate(repo) or ""
    have = head_tests(repo)
    texts = head_files(repo, ["tests/%s.py" % t for t in have])   # as committed, like the worktree's
    mods = []

    def add(name):
        if name not in mods and ("tests/%s.py" % name) not in guard:
            mods.append(name)
    for p in paths:
        stem = Path(p).stem
        name = stem if p.startswith("tests/test_") and p.endswith(".py") else "test_" + stem
        if name in have:
            add(name)
        rx = _mentions(p)
        # page code is read through tests/page_source.py (the whole bundle), so those tests never name the file
        page = re.compile(r"\bpage_source\b") if p.startswith("static/") else None
        for t in have:
            text = texts.get("tests/%s.py" % t, "")
            if rx.search(text) or (page and page.search(text)):
                add(t)
    return "./%s %s" % (repo_layout.engine_rel(repo, "run-tests.sh"), " ".join(mods)) if mods else None
