#!/usr/bin/env python3
"""Commit hooks for this repo (plan-execution-workflow pew/E). Installed with `git config core.hooksPath .githooks`
(run-tests.sh warns when it is not); worktrees share the setting, so delegated workers get the same checks.

  check_staged.py pre-commit        forbidden files, secrets in added lines, then ./run-tests.sh --fast on the
                                    staged snapshot (a throwaway worktree; others' unstaged work does not count)
  check_staged.py commit-msg FILE   Conventional Commits subject; `Plan:` trailer when docs/plans/ changes
  check_staged.py reference-transaction prepared   (ref lines on stdin) a live chat session does not land a
                                    delegated worker's branch on main -- landing is the operator's

Never bypass with --no-verify (root AGENTS.md). Messages name the file and the rule, never a secret's value.
"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
    (re.compile(r"(^|/)relationship\.md$"), "relationship memory"),
    (re.compile(r"^data/workspace/characters/[^/]+/references/"), "style references (other artists' work)"),
]
RECORDS = ("data/workspace/skill-observations/",)   # ticket/observation records: no test run needed


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def staged():
    return [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]


def _clean_git_env():
    """git hands hooks GIT_INDEX_FILE (a temp index for `commit -a` / `commit <paths>`) and may set GIT_DIR: a new
    worktree and the guards must not inherit them, or they would read or write that index."""
    return {k: v for k, v in os.environ.items()
            if k not in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY",
                         "CHATBOT_ROOT", "AGY_CHAT_ROOT", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                         "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE")}


def run_guards_on_snapshot(root):
    """Run ./run-tests.sh --fast on what is being committed, not on the shared working tree (pew/Q): agents that share
    one tree must not block each other's commits with their own unstaged work. The snapshot is a throwaway worktree at
    HEAD with the staged diff applied. Returns None when there is no runner. Falls back to the working tree only when
    there is no HEAD yet (a repository's first commit) or the diff will not apply."""
    diff = subprocess.run(["git", "diff", "--cached", "--binary"], cwd=str(root), capture_output=True).stdout  # this commit's index
    env = _clean_git_env()
    base = Path.home() / ".cache" / "chatbot-hook-snapshot"   # /tmp is noexec on this host
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=str(base)))
    tree = tmp / "tree"
    added = subprocess.run(["git", "worktree", "add", "--detach", "--quiet", str(tree), "HEAD"], cwd=str(root),
                           env=env, capture_output=True, text=True)
    try:
        where = tree if added.returncode == 0 else root
        if added.returncode == 0 and diff:
            ap = subprocess.run(["git", "apply", "--index", "--whitespace=nowarn"], cwd=str(tree), env=env,
                                input=diff, capture_output=True)
            if ap.returncode != 0:
                print("[pre-commit] could not rebuild the staged snapshot; checking the working tree instead")
                where = root
        runner = where / "run-tests.sh"
        if not runner.is_file():
            return None
        return subprocess.run(["bash", str(runner), "--fast"], cwd=str(where), env=env, capture_output=True, text=True)
    finally:
        if added.returncode == 0:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(root), env=env, capture_output=True)
        shutil.rmtree(str(tmp), ignore_errors=True)


# ENGINE_DECIDES_A5 (docs/plans/engine-decides.md ed/A5): who commits and who lands comes from the process ancestry
# (tools/ticket_quick.py::detect_actor), never from a name the agent typed. 2026-10-03: a live chat agent landed #583
# itself with `git merge --ff-only`, committed as "Coco" and rewrote the ticket record by hand.
MAIN_REF = "refs/heads/main"
WORKER_REFS = "refs/heads/worktree/"
TICKET_RECORD = re.compile(r"^data/workspace/skill-observations/tickets/\d+\.json$")


def _repo_module(root, name):
    """A module of this repository (root or tools/), or None -- a throwaway test repo holds only .githooks."""
    root = Path(root)
    if not any((d / (name + ".py")).is_file() for d in (root, root / "tools")):
        return None
    for d in (str(root / "tools"), str(root)):
        if d not in sys.path:
            sys.path.insert(0, d)
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 -- a broken module must not make every commit fail here
        return None


def caller(root):
    """The actor id of whoever runs this git command ("" when it cannot be told)."""
    tq = _repo_module(root, "ticket_quick")
    return tq.detect_actor() if tq else ""


def live_chat_agent(actor):
    """A chat session's own agent using its shell -- not the host itself or a runner it started (chat-agent:?)."""
    return actor.startswith("chat-agent:") and not actor.endswith(":?")


def ref_refusal(updates, who, on_worker_branch):
    """Why a ref transaction must stop, or "". `updates`: (old, new, ref); `who()`: the caller's actor id;
    `on_worker_branch(sha)`: whether a delegated worker's branch holds that commit."""
    for _old, new, ref in updates:
        if ref == MAIN_REF and set(new) != {"0"} and on_worker_branch(new) and live_chat_agent(who()):
            return ("a live chat session cannot land a worker's branch on main: landing is the operator's ([승인] "
                    "on the work card runs the runner's merge). Leave the branch and tell the operator it waits.")
    return ""


def reference_transaction(state, lines):
    if state != "prepared":
        return 0
    root = git("rev-parse", "--show-toplevel").strip()
    updates = [tuple(l.split()[:3]) for l in lines if len(l.split()) >= 3]
    why = ref_refusal(updates, lambda: caller(root),
                      lambda sha: bool(git("for-each-ref", "--contains", sha, WORKER_REFS, "--format=%(refname)").strip()))
    if why:
        print("[reference-transaction] " + why)
        return 1
    return 0


def record_refusals(root, files):
    """Staged ticket records whose stored actors are not role ids (the record was written around tickets.py)."""
    ev = _repo_module(root, "evolution")
    out = []
    for f in files if ev else []:
        if not TICKET_RECORD.match(f):
            continue
        try:
            t = json.loads(git("show", ":" + f) or "{}")
        except ValueError:
            continue
        bad = [k for k in ("actor", "worked_by", "closed_by") if t.get(k) and not ev.ROLE_ID_RE.match(str(t[k]))]
        bad += ["note by %r" % n.get("by") for n in t.get("notes") or [] if isinstance(n, dict)
                and str(n.get("by", "")).startswith("agent:") and not ev.ROLE_ID_RE.match(str(n["by"])[6:])]
        if bad:
            out.append("%s: %s must be a role id like agy or chat-agent:agy, not a persona name -- change tickets "
                       "only through tickets.py or the ticket tool" % (f, ", ".join(bad)))
    return out


def _persona_names(root):
    names = set()
    for card in (Path(root) / "data" / "workspace" / "characters").glob("*/card.json"):
        try:
            d = json.loads(card.read_text(encoding="utf-8")).get("data") or {}
        except (OSError, ValueError, AttributeError):
            continue
        names.add(str(d.get("name") or "").strip())
    return names - {""}


def author_refusal(root, who, author_of):
    """Why this commit's author is wrong, or "". A persona name is never an author; a live chat session commits
    as its brain (`author_of(actor)`, the runner's provider table)."""
    name = git("var", "GIT_AUTHOR_IDENT").rsplit("<", 1)[0].strip()
    if name in _persona_names(root):
        return "author %r is a character's name (a display value): commit as your agent, e.g. git -c user.name=agy" % name
    actor = who()
    want = author_of(actor.split(":", 1)[1]) if live_chat_agent(actor) else ""
    if want and name != want:
        return "author %r: a live chat session commits as its brain %r (drop the -c user.name)" % (name, want)
    return ""


def _runner_author(root, actor):
    wr = _repo_module(root, "worktree_runner")
    return next((v["author"][0] for v in getattr(wr, "PROVIDERS", {}).values() if v.get("actor") == actor), "")


def pre_commit():
    root = Path(git("rev-parse", "--show-toplevel").strip())
    files = staged()
    errors = record_refusals(root, files)
    who = author_refusal(root, lambda: caller(root), lambda a: _runner_author(root, a))
    if who:
        errors.append(who)
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
    r = run_guards_on_snapshot(root)
    if r is None:
        return 0
    if r.returncode != 0:
        tail = "\n".join(r.stdout.strip().splitlines()[-25:])
        print("[pre-commit] guard tests failed; fix them before committing (never --no-verify):\n" + tail)
        return 1
    return 0


# A change to code names the ticket it belongs to (AGENTS.md rule registry; the review of #505-#525 found 27 of 29
# delegated commits without one). A delegated worker on its ticket's branch gets the trailer written for it.
TICKET_TYPES = re.compile(r"^(?:feat|fix|refactor|perf)(?:\([^)]+\))?!?: ")
TICKET_LINE = re.compile(r"^Ticket: #\d+")
WORKTREE_BRANCH = re.compile(r"^worktree/ticket-(\d+)$")


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
    if TICKET_TYPES.match(subject) and not any(TICKET_LINE.match(l) for l in lines):
        m = WORKTREE_BRANCH.match(git("symbolic-ref", "--short", "-q", "HEAD").strip())
        if not m:
            print("[commit-msg] a feat/fix/refactor/perf commit names its ticket: add a trailer line `Ticket: #<n>` "
                  "(start one: python3 tools/ticket_quick.py start --title ... --paths ... --actor <you>)")
            return 1
        text = Path(path).read_text(encoding="utf-8")
        Path(path).write_text(text.rstrip("\n") + "\n\nTicket: #%s\n" % m.group(1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["pre-commit"]:
        sys.exit(pre_commit())
    if sys.argv[1:2] == ["commit-msg"] and len(sys.argv) > 2:
        sys.exit(commit_msg(sys.argv[2]))
    if sys.argv[1:2] == ["reference-transaction"] and len(sys.argv) > 2:
        sys.exit(reference_transaction(sys.argv[2], sys.stdin.read().splitlines()))
    print(__doc__)
    sys.exit(2)
