#!/usr/bin/env python3
"""Commit hooks for this repo (plan-execution-workflow pew/E). Installed with `git config core.hooksPath .githooks`
(run-tests.sh warns when it is not); worktrees share the setting, so delegated workers get the same checks.

  check_staged.py pre-commit        forbidden files, secrets in added lines, then ./run-tests.sh --fast
  check_staged.py commit-msg FILE   Conventional Commits subject; `Plan:` trailer when docs/plans/ changes

Never bypass with --no-verify (root AGENTS.md). Messages name the file and the rule, never a secret's value.
"""
import re
import subprocess
import sys
from pathlib import Path

TYPES = "feat|fix|docs|test|refactor|chore|perf|style|build|ci|revert"
SUBJECT = re.compile(r"^(?:%s)(?:\([^)]+\))?!?: \S" % TYPES)
PASS_SUBJECT = re.compile(r"^(?:Merge |Revert \"|fixup! |squash! )")
SECRETS = {
    "openai/anthropic key": r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}",
    "google key": r"AIza[0-9A-Za-z_-]{35}",
    "xai key": r"xai-[A-Za-z0-9]{20,}",
    "github token": r"gh[pousr]_[A-Za-z0-9]{36}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "assigned secret": r"(?i)(?:api[_-]?key|secret|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{24,}['\"]",
}
ALLOW = "pragma: allowlist secret"
FORBIDDEN = [
    (re.compile(r"(^|/)secrets\.env$"), "secrets file"),
    (re.compile(r"(^|/)[^/]*\.env$"), "env file (commit a .env.example instead)"),
    (re.compile(r"(^|/)private-memory\.md$"), "private memory"),
    (re.compile(r"^data/workspace/characters/[^/]+/references/"), "style references (other artists' work)"),
]
RECORDS = ("data/workspace/skill-observations/",)   # ticket/observation records: no test run needed


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def staged():
    return [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]


def pre_commit():
    root = Path(git("rev-parse", "--show-toplevel").strip())
    files = staged()
    errors = []
    for f in files:
        for rx, what in FORBIDDEN:
            if rx.search(f) and not f.endswith(".example"):
                errors.append("%s: %s must not be committed (unstage it: git restore --staged %s)" % (f, what, f))
    current = None
    for line in git("diff", "--cached", "-U0", "--no-color").splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("+") and current and ALLOW not in line:
            for name, rx in SECRETS.items():
                if re.search(rx, line):
                    errors.append("%s: added line looks like a %s (remove it; a fake test value takes `%s`)"
                                  % (current, name, ALLOW))
    untracked = [p for p in git("ls-files", "--others", "--exclude-standard", "docs/plans").splitlines() if p.endswith(".md")]
    for p in untracked:
        print("[pre-commit] warning: %s is not committed; an untracked plan blocks ticket claims (#213)" % p)
    if errors:
        print("\n".join("[pre-commit] " + e for e in sorted(set(errors))))
        return 1
    if files and all(f.startswith(RECORDS) for f in files):
        return 0
    runner = root / "run-tests.sh"
    if not runner.exists():
        return 0
    r = subprocess.run([str(runner), "--fast"], cwd=str(root), capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stdout.strip().splitlines()[-25:])
        print("[pre-commit] guard tests failed; fix them before committing (never --no-verify):\n" + tail)
        return 1
    return 0


def commit_msg(path):
    lines = [l for l in Path(path).read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    subject = next((l for l in lines if l.strip()), "")
    if not PASS_SUBJECT.match(subject) and not SUBJECT.match(subject):
        print("[commit-msg] subject must be Conventional Commits: <type>(<scope>)?: <summary>\n"
              "  types: %s   e.g. fix(session): keep the current brain\n  got: %s" % (TYPES.replace("|", " "), subject))
        return 1
    if any(f.startswith("docs/plans/") for f in staged()) and not any(re.match(r"^Plan: \S+", l) for l in lines):
        print("[commit-msg] this commit changes docs/plans/: add a trailer line `Plan: <plan>/<item>` (e.g. Plan: pew/A)")
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["pre-commit"]:
        sys.exit(pre_commit())
    if sys.argv[1:2] == ["commit-msg"] and len(sys.argv) > 2:
        sys.exit(commit_msg(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
