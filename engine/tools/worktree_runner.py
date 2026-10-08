#!/usr/bin/env python3
"""worktree_runner.py: hand one ticket to an external CLI agent in an isolated git worktree, and fast-forward onto
main only what passed the gates and the PD character's confirmation
(docs/plans/multi-agent-worktree-delegation.md milestone 2, §8 paired review).

Usage:
  python3 tools/worktree_runner.py run --provider claude --title "title" \\
      --paths "tickets.py,tests/test_tickets.py" --prompt "brief..." \\
      [--gate "./run-tests.sh test_tickets"] [--evidence log:fp:<fp>] [--timeout 1200] \\
      [--reviewer claude] [--reviewer-model haiku] [--rounds 2] [--no-review] [--stop-before-merge] [--keep] [--json]

  # Tier 2: land a ticket stopped by --stop-before-merge on the operator's word
  # (relays merge-go -> rebase and rerun the gates if needed -> ff merge)
  python3 tools/worktree_runner.py merge --ticket 61 [--token <token from merge_go>] [--keep] [--json]

  # remove a worktree/branch left by an abnormal exit
  python3 tools/worktree_runner.py cleanup --ticket 61

Flow (run):
  0. Tier (evolution.delegation_tier): Tier 3 is refused, Tier 2 forces --stop-before-merge, others merge on pass.
     Files changed are checked every round.
  1. ticket-quick start -> TICKET_ID, CLAIM_TOKEN (approve + claim; the target paths must be clean on main)
  2. git worktree add -b worktree/ticket-<ID> ~/.worktrees/chatbot/ticket-<ID> <main HEAD>
  3. Rounds (at most --rounds):
     a. The expert (a character in data/workspace/characters/<id>/, found by role) works headless, commits and
        leaves one in-character line (the runner commits leftovers; the author is the provider's identity)
     b. Machine gates: a commit exists -> scope (nothing outside --paths) -> lease renewed -> rebase on main
        -> guard tests (run-tests.sh FAST) + smoke + tests related to the changed files (DEFAULT_GATES,
        related_gate) + the --gate commands
     c. The PD (the character holding the pd role) reads the diff (or the gate failure) and confirms:
        VERDICT + a line + requested fixes
     d. Gates green and PASS ends it; otherwise the next round carries the requested fixes
  4. Pass: git merge --ff-only on main -> ticket-quick done -> worktree/branch removed
     --stop-before-merge (Tier 2): ticket-quick await-merge instead of merging (lease released); worktree/branch stay
     Fail: no merge -> ticket-quick fail (gate_failed | failed) -> worktree/branch removed (kept with --keep)
       Branch head kept at refs/attic/ticket-<ID>; next run --from-attic starts there. Dropped once merged.
     PD cannot confirm (every PD brain at its limit or timed out): the branch stays, and the next --plan-from-state
     run skips the tasks that passed and resumes the stopped task's gates and confirmation.
  5. Only the ticket record (tickets/<ID>.json) is committed on main (chore(tickets): close #ID | #ID <outcome>)
  The two characters' exchange is kept in ~/.worktrees/chatbot/transcripts/.
  Run state (step, round, lines, the settings a merge needs) is written atomically to
  ~/.worktrees/chatbot/runs/ticket-<ID>.json.

The live host is never restarted. When a host module changed, deploy with `chatbot-ctl.sh repair` once idle.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tools/
import run_usage  # noqa: E402  -- each CLI call's tokens (token-economy T6)
from worker_output import LEARNED_RULE, LINE_RULE, learned, report, said  # noqa: E402
from brain_limits import brain_label, mark, resolve_provider_model, unavailable, usable  # noqa: E402
from review_checklist import (  # noqa: E402
    DIFF_LIMIT, DISPLAY_NOTE, deleted_lines, doc_review_prompt, is_display_task, is_doc_task, once_note,
    parse_review, review_prompt, with_code_checklist,
)

CODE_DIR = Path(__file__).resolve().parents[1]      # where the host modules this tool imports live
sys.path.insert(0, str(CODE_DIR))
import repo_layout  # noqa: E402
CHATBOT_REPO = repo_layout.repo_of(CODE_DIR)         # the repository it works on
WORKTREE_BASE = Path.home() / ".worktrees" / "chatbot"
TICKET_QUICK = [sys.executable, str(CODE_DIR / "tools" / "ticket_quick.py")]   # pew/K: the repo copy
# smoke plus the repo-wide guards (design doc §7-9, NAME_NEUTRAL_v1); a few seconds each
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


DEFAULT_GATES = [g for g in (guard_gate(CHATBOT_REPO),) if g] + ["python3 tests/smoke.py", "python3 tests/test_identity_wiring.py"]
LEASE_TTL_SEC = 1800          # tickets.LEASE_TTL_SEC: renewed before and after each agent run
MAX_AGENT_TIMEOUT = 1500
REVIEW_TIMEOUT = 300
GATE_TIMEOUT = 600
TAIL_LINES = 30
# An argv prompt is capped by Linux at 128 KiB (MAX_ARG_STRLEN; DIFF_LIMIT, review_checklist.py); a CLI reading the
# prompt from stdin (`stdin_prompt`) gets the diff up to DIFF_LIMIT_STDIN (DELEGATION_HARDENING_v1).
DIFF_LIMIT_STDIN = 200000
TICKETS_REL = "data/workspace/skill-observations/tickets"   # tickets.tickets_dir(), repo-relative

# Each CLI headless: worker (`argv`), worker resumed by directory (`continue_argv`), tool-less reviewer
# (`review_argv`), default models, role id and git author. The prompt comes last; where it is `-p`'s value (agy,
# grok) `-p` stays last. `workdir_flag`: agy writes to its own scratch folder unless the worktree is added.
PROVIDERS: Dict[str, Dict] = {
    "claude": {"argv": ["claude", "--dangerously-skip-permissions", "-p"], "stdin_prompt": [],
               "continue_argv": ["claude", "-c", "--dangerously-skip-permissions", "-p"],
               "review_argv": ["claude", "--tools", "", "-p"], "model_flag": "--model", "review_model": "sonnet",
               "actor": "claude-code", "author": ("Claude Code", "noreply@anthropic.com")},
    "codex": {"argv": ["codex", "exec", "-s", "workspace-write"], "stdin_prompt": ["-"],
              "review_argv": ["codex", "exec", "-s", "read-only"], "model_flag": "-m",
              "actor": "codex", "author": ("Codex", "codex@localhost")},
    "agy": {"argv": ["agy", "--dangerously-skip-permissions", "-p"], "workdir_flag": "--add-dir",
            "work_model": "gemini-3.1-pro-high", "review_model": "gemini-3.1-pro-high",
            "review_argv": ["agy", "--dangerously-skip-permissions", "-p"], "model_flag": "--model",
            "actor": "agy", "author": ("agy", "agy@localhost")},
    "grok": {"argv": ["grok", "--always-approve", "-p"],
             "review_argv": ["grok", "-p"], "model_flag": "-m",
             "actor": "grok", "author": ("Grok", "grok@localhost")},
}


class Failure(Exception):
    """The attempt stops here. outcome is the ticket release outcome: gate_failed | failed | unavailable (no brain
    answered at all: quota, limit, timeout, missing CLI -- the ticket gives the attempt back) | paused (the worker
    asked for files outside its scope, NEED_PATH_v1: the work is kept, the attempt given back) | base_broken (a gate
    fails on the task's base too, BASE_CHECK_v1: not the work's fault; kept, the ticket told `unavailable`).
    retryable: another round with the writer could fix it. keep: the work is sound but could not be confirmed
    (no PD brain answered); the branch stays so the next run resumes it."""

    def __init__(self, outcome: str, reason: str, detail: str = "", retryable: bool = False, keep: bool = False):
        super().__init__(reason)
        self.outcome, self.reason, self.detail, self.retryable, self.keep = outcome, reason, detail, retryable, keep


def log(msg: str) -> None:
    print("[*] " + msg, file=sys.stderr, flush=True)


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 120,
            env: Optional[Dict[str, str]] = None, stdin: Optional[str] = None) -> tuple:
    try:
        res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, errors="replace", timeout=timeout, check=False,
                             input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timed out after %ds" % timeout
    except OSError as e:
        return -1, "", str(e)


def git(repo: Path, *args: str, timeout: int = 120) -> tuple:
    return run_cmd(["git", *args], cwd=repo, timeout=timeout)


def tail(text: str, n: int = TAIL_LINES) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-n:])


def names(ticket_id: int) -> tuple:
    return "worktree/ticket-%d" % ticket_id, WORKTREE_BASE / ("ticket-%d" % ticket_id)


def in_scope(path: str, paths: List[str]) -> bool:
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in paths)


def host_module(name: str):
    if str(CODE_DIR) not in sys.path:
        sys.path.insert(0, str(CODE_DIR))
    return __import__(name)


# -------------------------------------------------------------------- tiers

def gate_files(repo: Path, gates: List[str]) -> List[str]:
    """Repo files the gate commands run: a delegated agent must not be able to change its own pass condition."""
    out = []
    for cmd in gates:
        try:
            words = shlex.split(cmd)
        except ValueError:
            continue
        for w in words:
            rel = w[2:] if w.startswith("./") else w   # `./run-tests.sh` is the file run-tests.sh (pew/F)
            if not w.startswith("-") and "/" in w and (repo / rel).is_file() and rel not in out:
                out.append(rel)
    return out


def tier_of(repo: Path, path: str, gated: List[str]) -> tuple:
    """(tier, why): 3 refused, 2 lands on the operator's word, 0 lands on its gates."""
    covered = [g for g in gated if in_scope(g, [path])]
    if covered:
        return 3, "gate file %s" % covered[0]
    return host_module("evolution").delegation_tier(repo, path)


def check_tiers(repo: Path, files: List[str], gated: List[str], retryable: bool) -> int:
    """Highest tier among `files`; a Tier 3 file fails."""
    tiers = {f: tier_of(repo, f, gated) for f in files}
    t3 = ["%s (%s)" % (f, why) for f, (t, why) in tiers.items() if t >= 3]
    if t3:
        raise Failure("gate_failed", "Tier 3 paths are not delegated; only the operator changes them: %s"
                      % ", ".join(t3[:5]), retryable=retryable)
    return max([t for t, _ in tiers.values()] or [0])


# ----------------------------------------------------------------- personas

def persona(role: str = "") -> Dict[str, str]:
    """{name, label, voice, body} of the chatbot's own persona ("") or a second character (role id).
    Names are display values from the instance's identity files, never ids."""
    try:
        identity = host_module("identity")
        ident = identity.get_identity(role)
        return {"name": ident["name"], "label": identity.self_label(role), "voice": ident["voice"],
                "body": identity.persona_body(role)}
    except Exception:
        return {"name": role or "worker", "label": role or "worker", "voice": "", "body": ""}


def character_block(me: Dict[str, str], partner: Dict[str, str], relation: str) -> str:
    lines = ["You are %s. %s You two talk to each other like a comedy duo." % (me["label"], relation % partner["name"])]
    if me["voice"]:
        lines.append("Tone: %s." % me["voice"])
    if me["body"]:
        lines += ["Your character:", me["body"]]
    return "\n".join(lines)


# ------------------------------------------------------------------ tickets

DONE_TIMEOUT = 420   # done runs the guard tests (300 s), maybe after another test run; 60 s left #456 open


def ticket_call(*args: str) -> Dict[str, str]:
    """Run ticket-quick and return its KEY=VALUE lines. Raises RuntimeError with its stderr."""
    code, out, err = run_cmd(TICKET_QUICK + list(args), timeout=DONE_TIMEOUT if args[0] == "done" else 60)
    if code != 0:
        raise RuntimeError(err or out or "ticket-quick %s failed" % args[0])
    vals = {}
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if sep and k.isupper():
            vals[k] = v
    return vals


def commit_ticket_record(repo: Path, tid: int, provider: str, subject: str, extra: Tuple[str, ...] = ()) -> Optional[str]:
    """Commit the diary lines a merge wrote (`extra`, tools/history_entry.py) and the ticket's own record when it
    lives in the repository, so main is left clean without an operator step. Since the data moved out (~/.pe) the
    record is not here, and the diary line was left uncommitted on main (#620): it goes alone, as docs(history).
    The short sha, or None."""
    rel = "%s/%04d.json" % (TICKETS_REL, tid)
    paths = [p for p in ((rel,) if (repo / rel).exists() else ()) + tuple(extra)
             if git(repo, "status", "--porcelain", "--", p)[1]]
    if not paths:
        return None
    if rel not in paths:
        subject = subject.replace("chore(tickets):", "docs(history):", 1)
    name, email = PROVIDERS[provider]["author"]
    git(repo, "add", "--", *paths)
    code, _, err = git(repo, "-c", "user.name=" + name, "-c", "user.email=" + email,
                       "commit", "-m", subject, "--", *paths)
    if code != 0:
        print("[!] ticket record not committed: %s" % tail(err, 5), file=sys.stderr)
        return None
    return git(repo, "rev-parse", "--short", "HEAD")[1]


# ----------------------------------------------------------------- worktree

def attic_ref(ticket_id: int) -> str:
    return "refs/attic/ticket-%d" % ticket_id


def cleanup_worktree(repo: Path, branch: str, wt_dir: Path, attic: str = "") -> None:
    """attic: keep the branch head under this ref before the branch goes, so the work is not left to git gc."""
    if wt_dir.exists():
        git(repo, "worktree", "remove", "--force", str(wt_dir))
        if wt_dir.exists():
            shutil.rmtree(wt_dir, ignore_errors=True)
    git(repo, "worktree", "prune")
    if attic and git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0:
        git(repo, "update-ref", attic, "refs/heads/" + branch)
    git(repo, "branch", "-D", branch)


def drop_attic(repo: Path, ticket_id: int) -> None:
    git(repo, "update-ref", "-d", attic_ref(ticket_id))


STAFF_RELATION = "You are one of the experts; %s delegated this work to you and confirms it before it ships."
PD_RELATION = "You delegated this work; %s is the expert who did it. You confirm it or send it back."


_NEED_PATH = re.compile(r"^\s*NEED_PATH:\s*(\S+)\s*(?:--|—|-|:)?\s*(.*)$", re.M)


def need_paths(text: str, paths: List[str]) -> List[Dict[str, str]]:
    """The files a worker asked for (NEED_PATH_v1) that its scope does not already cover."""
    out = []
    for m in _NEED_PATH.finditer(text or ""):
        path = m.group(1).strip("`'\"").replace("\\", "/")
        if path.startswith("/") or ".." in path.split("/") or in_scope(path, paths):
            continue
        if path not in [x["path"] for x in out]:
            out.append({"path": path[:200], "why": m.group(2).strip()[:300]})
    return out[:10]


def writer_prompt(tid: int, title: str, branch: str, wt_dir: Path, paths: List[str], gates: List[str],
                  instruction: str, character: str, memory: str = "", reads: Optional[List[str]] = None) -> str:
    remembered = ["What you remember from earlier work (yours alone):", memory, ""] if memory.strip() else []
    return "\n".join(remembered + [
        "You are working on ticket #%d (%s) in an isolated git worktree of the services/chatbot repository." % (tid, title),
        "Working directory: %s (branch %s). Stay inside it: do not modify %s or any other path, "
        "do not push, do not restart or deploy services." % (wt_dir, branch, CHATBOT_REPO),
        "Change only these repo-relative paths: %s. Changes anywhere else fail the scope gate." % ", ".join(paths),
    ] + (["Read these for reference only; do not change them: %s." % ", ".join(reads)] if reads else []) + [
        "If the task truly needs a file outside them, do not touch it: end your answer with one line per file "
        "`NEED_PATH: <repo-relative path> -- <why>` and stop; the operator can allow it and you will continue.",
        "A gate or test that fails for a reason your change did not cause is not yours to fix: do not ask for guard, "
        "gate or test files to get around it; say what fails and why in your final message.",
        "When done, commit your work on this branch (git add <files> && git commit -m '<type>(<scope>): <summary>'); "
        "the subject must be Conventional Commits (feat, fix, docs, test, refactor, chore, ...). The author identity "
        "is already set. The repo's commit hooks run guard tests: fix what they report, never use --no-verify. "
        "If your change alters a behaviour or a decision written in docs/plans/, name the plan and the decision in your final message.",
        "Afterwards the runner runs: %s; then your producer confirms the diff. Only a branch that passes both is merged."
        % "; ".join(gates),
        "",
        character,
        LINE_RULE,
        LEARNED_RULE,
        "",
        "Task:",
        instruction,
    ])


# ------------------------------------------------------------ expert memory
# Each expert keeps a short memory (characters/<id>/memory.md, plan doc §11 step 4): it reads it before a task and may
# end its output with LEARNED lines (worker_output.learned); the lessons of a task are kept only when the PD confirmed it (PASS).

MEMORY_CAP = 2048
MEMORY_HEAD = "# Memory\n"


def character_id(role: str) -> Optional[str]:
    """The character playing `role` (or the id itself) in this workspace, or None."""
    try:
        return host_module("characters").resolve(role, workspace_dir())
    except Exception:  # noqa: BLE001
        return None


def memory_path(role: str) -> Path:
    cid = character_id(role)
    if not cid:
        return workspace_dir() / "characters" / "_none" / "memory.md"     # no such character: nothing is kept
    return host_module("characters").memory_path(cid, workspace_dir())


def read_memory(role: str) -> str:
    try:
        return memory_path(role).read_text(encoding="utf-8")[:MEMORY_CAP * 2]
    except OSError:
        return ""


def remember(role: str, lessons: List[str], today: Optional[str] = None) -> int:
    """Add lessons to the expert's memory: no duplicates, oldest lines dropped past MEMORY_CAP. Returns lines added."""
    path = memory_path(role)
    if not lessons or not path.parent.is_dir():
        return 0
    lines = [ln for ln in read_memory(role).splitlines() if ln.startswith("- ")]
    known = {re.sub(r"^- \[[0-9-]+\] ", "", ln).lower() for ln in lines}
    stamp = today or time.strftime("%Y-%m-%d")
    added = 0
    for lesson in lessons:
        if lesson.lower() not in known:
            lines.append("- [%s] %s" % (stamp, lesson))
            known.add(lesson.lower())
            added += 1
    while lines and len((MEMORY_HEAD + "\n".join(lines) + "\n").encode("utf-8")) > MEMORY_CAP:
        lines.pop(0)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(MEMORY_HEAD + "\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return added


def retry_prompt(feedback: str, full: Optional[str]) -> str:
    """Next round: the partner's requests. `full` repeats the whole brief when the CLI cannot resume."""
    parts = [full, "", "--- next round ---"] if full else []
    parts += ["Your producer sent the branch back. Fix it, commit again, same rules as before.",
              feedback, LINE_RULE, LEARNED_RULE]
    return "\n".join(parts)


# What a delegated agent inherits from this process: the basics a CLI needs, never the host's secrets
# (the chat server's environment holds API keys; each CLI keeps its own login under HOME).
ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR")


def clean_env(**extra: str) -> Dict[str, str]:
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env.update(extra)
    return env


def agent_env(provider: str) -> Dict[str, str]:
    name, email = PROVIDERS[provider]["author"]
    return clean_env(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)


def prompt_args(provider: str, prompt: str) -> tuple:
    """(extra argv, stdin text): the prompt on stdin where the CLI reads it there, else as the last argument."""
    spec = PROVIDERS[provider]
    if "stdin_prompt" in spec:
        return list(spec["stdin_prompt"]), prompt
    return [prompt], None


def diff_limit(provider: str) -> int:
    return DIFF_LIMIT_STDIN if "stdin_prompt" in PROVIDERS.get(provider, {}) else DIFF_LIMIT


def run_as_login(provider: str, cmd: List[str], **kw) -> tuple:
    """run_cmd under a stall watch (delegation_watch, WORKER_STALL_v1), again when the login changed under it
    (accounts.rerun_on_switch, ACCOUNT_SWITCH_v1). The CLI answers in JSON; its tokens go to runs/usage.jsonl."""
    cmd, t0 = run_usage.machine(provider, cmd), time.time()
    try:
        watch, accounts = host_module("delegation_watch"), host_module("providers.accounts").accounts
    except Exception:  # noqa: BLE001
        watch = None
    code, out, err = (accounts.rerun_on_switch(provider, lambda: watch.run(cmd, activity=watch.activity_of(provider), **kw), log)
                      if watch else run_cmd(cmd, **kw))
    out, used = run_usage.split(provider, out)
    if used:
        run_usage.record(WORKTREE_BASE, provider, kw.get("cwd"), used, time.time() - t0)
    return code, out, err


def run_agent(provider: str, wt_dir: Path, prompt: str, timeout: int, resume: bool = False, model: str = "") -> Dict:
    argv = work_command(provider, wt_dir, model, resume)
    if not shutil.which(argv[0]):
        return {"ok": False, "returncode": None, "elapsed_sec": 0, "stdout": "", "stderr": "%s CLI not installed" % argv[0]}
    t0 = time.time()
    extra, stdin = prompt_args(provider, prompt)
    code, out, err = run_as_login(provider, argv + extra, cwd=wt_dir, timeout=timeout, env=agent_env(provider), stdin=stdin)
    return {"ok": code == 0, "returncode": code, "elapsed_sec": round(time.time() - t0, 1), "stdout": out, "stderr": err}


def commit_leftovers(wt_dir: Path, provider: str, tid: int) -> bool:
    """Commit what the agent changed but did not commit (e.g. a sandbox kept it out of the git dir)."""
    _, status, _ = git(wt_dir, "status", "--porcelain")
    if not status:
        return False
    name, email = PROVIDERS[provider]["author"]
    git(wt_dir, "add", "-A")
    code, _, err = git(wt_dir, "-c", "user.name=" + name, "-c", "user.email=" + email,
                       "commit", "-m", "chore(ticket #%d): changes the agent left uncommitted" % tid)
    if code != 0:
        raise Failure("failed", "could not commit the agent's leftover changes", err)
    return True


def gate_env(tree: Path) -> Dict[str, str]:
    """The tree's own data/, never ~/.pe (a gate once wrote into the live chat)."""
    return clean_env(CHATBOT_DATA=str(Path(tree).resolve() / "data"))


def run_gates(wt_dir: Path, gates: List[str]) -> None:
    for cmd in gates:
        log("gate: %s" % cmd)
        code, out, err = run_cmd(["sh", "-c", cmd], cwd=wt_dir, timeout=GATE_TIMEOUT, env=gate_env(wt_dir))
        if code != 0:
            f = Failure("gate_failed", "gate failed: %s (exit %s)" % (cmd, code), tail(out + "\n" + err),
                        retryable=True)
            f.gate = cmd
            raise f


def base_fails(repo: Path, base: str, cmd: str, tid: int) -> Optional[str]:
    """BASE_CHECK_v1 (plan dlg/C): run one failed gate on the task's base, in a throwaway detached worktree. The
    output tail when it fails there too -- the failure is not the work's, so no writer round is spent on it -- else
    None (also when the check itself cannot run: then the failure stays the work's)."""
    d = WORKTREE_BASE / ("base-check-%d" % tid)
    cleanup = lambda: (git(repo, "worktree", "remove", "--force", str(d)), shutil.rmtree(d, ignore_errors=True),
                       git(repo, "worktree", "prune"))
    cleanup()
    if git(repo, "worktree", "add", "--detach", str(d), base)[0] != 0:
        return None
    try:
        code, out, err = run_cmd(["sh", "-c", cmd], cwd=d, timeout=GATE_TIMEOUT, env=gate_env(d))
        return None if code == 0 else tail(out + "\n" + err)
    finally:
        cleanup()


# ------------------------------------------------------------------- review

def with_flags(argv: List[str], flags: List[str]) -> List[str]:
    """`argv` plus `flags`, placed before a trailing `-p` (whose value is the prompt appended last)."""
    argv = list(argv)
    at = len(argv) - 1 if argv and argv[-1] == "-p" else len(argv)
    argv[at:at] = flags
    return argv


def review_command(provider: str, model: str) -> List[str]:
    """The reviewer's command line, the prompt still to be appended."""
    spec = PROVIDERS[provider]
    model = resolve_provider_model(provider, model or spec.get("review_model") or "")
    return with_flags(spec["review_argv"], [spec["model_flag"], model] if model else [])


def work_command(provider: str, wt_dir: Path, model: str, resume: bool = False) -> List[str]:
    """The worker's command line in `wt_dir`, the prompt still to be appended."""
    spec = PROVIDERS[provider]
    argv = spec["continue_argv"] if resume and spec.get("continue_argv") else spec["argv"]
    flags = [spec["workdir_flag"], str(wt_dir)] if spec.get("workdir_flag") else []
    model = resolve_provider_model(provider, model or spec.get("work_model") or "")
    if model and spec.get("model_flag"):
        flags += [spec["model_flag"], model]
    return with_flags(argv, flags)


def run_review(provider: str, model: str, wt_dir: Path, prompt: str, timeout: int = 0) -> Dict[str, str]:
    argv = review_command(provider, model)
    if not shutil.which(argv[0]):
        raise Failure("failed", "reviewer CLI %s not installed" % argv[0])
    # The reviewer gets the diff in its prompt and no files: it runs in an empty directory, never the worktree
    # (a CLI without a tools-off switch could otherwise change the work it judges; agy's plan mode waits for a "go").
    empty = WORKTREE_BASE / "review-room"          # one fixed room, emptied each time
    shutil.rmtree(empty, ignore_errors=True)
    empty.mkdir(parents=True, exist_ok=True)
    extra, stdin = prompt_args(provider, prompt)
    code, out, err = run_as_login(provider, argv + extra, cwd=empty, timeout=timeout or REVIEW_TIMEOUT, env=clean_env(),
                                  stdin=stdin)
    if code == -1 and err.startswith("timed out"):
        raise Failure("failed", "reviewer %s %s" % (provider, err), tail(out))
    if code != 0:
        raise Failure("failed", "reviewer %s exited with %s" % (provider, code), tail(err or out))
    return parse_review(out)


# ------------------------------------------------------------------- brains
# Each character has an ordered list of brains (its card: extensions.chatbot.brains.work), the PD's confirmation
# included. A brain that is out of quota, rate-limited, missing or silent past its timeout hands the turn to
# the next one (docs/plans/multi-agent-worktree-delegation.md §11). The operator sets the lists; the PD cannot.

LIMITS = "brain_limits.json"   # BRAIN_LIMITS_v1 (tools/brain_limits.py): resting brains


def fresh(chain: List[Dict], strict: bool = True) -> List[Dict]:
    """The brains not resting; when all are, fail at once (strict) instead of spending a try, else keep `chain`."""
    ok, resting = usable(WORKTREE_BASE / LIMITS, chain)
    if ok or not strict:
        return ok or chain
    raise Failure("unavailable", "every brain is resting: %s" % ", ".join(resting))


def review_with_chain(chain: List[Dict], wt_dir: Path, prompt, renew) -> tuple:
    """The PD's confirmation on the first brain that can give it. Returns (review, brain, skipped labels).
    `prompt` is the text, or a function of the provider (each brain may take a different diff size).
    When none can (quota, timeout), the work is kept for the next run (Failure.keep)."""
    skipped = []
    for i, b in enumerate(chain):
        try:
            text = prompt(b["provider"]) if callable(prompt) else prompt
            return run_review(b["provider"], b["model"], wt_dir, text, b["timeout"]), b, skipped
        except Failure as f:
            if not unavailable(f.reason + "\n" + f.detail, 0):
                raise
            mark(WORKTREE_BASE / LIMITS, b, f.reason + "\n" + f.detail)
            if i + 1 == len(chain):
                raise Failure("unavailable", "no PD brain could confirm the work (%s); it is kept for the next run"
                              % f.reason, f.detail, keep=True)
            skipped.append(brain_label(b))
            log("PD brain %s unavailable; next %s" % (brain_label(b), brain_label(chain[i + 1])))
            renew()
    raise Failure("failed", "no PD brain configured")


def cross_chain(chain: List[Dict], writer: Dict, others: List[str] = ()) -> List[Dict]:
    """REVIEW_CROSS_v1 (plan dlg/B): the work is confirmed by another provider than the one that wrote it -- the same
    model checking its own diff shares its blind spots (1 FAIL in ~89 reviews, 2026-09-23..29). The PD's own brains of
    another provider come first; when it has none, `others` (providers, their default review model); the PD's
    same-provider brains stay last, used only when no other can confirm (the transcript says so)."""
    wp = writer.get("provider")
    other = [x for x in chain if x["provider"] != wp]
    if not other:
        other = [{"provider": p, "model": "", "timeout": 0} for p in others if p != wp]
    return other + [x for x in chain if x["provider"] == wp]


def review_providers() -> List[str]:
    """Registered providers whose review CLI is installed here, in registry order (--cross-review)."""
    return [p for p, spec in PROVIDERS.items() if spec.get("review_argv") and shutil.which(spec["review_argv"][0])]


def workspace_dir() -> Path:
    """This instance's workspace (host_config), where characters/ live."""
    try:
        return host_module("host_config").WORKSPACE
    except Exception:  # noqa: BLE001
        return CODE_DIR / "data" / "workspace"


def expert_chain(role: str, default: List[Dict]) -> List[Dict]:
    """The character's brain list from its card (brains.work), known providers only; `default` when none."""
    cid = character_id(role)
    if not cid:
        return default
    try:
        C = host_module("characters")
        raw = C.brains(C.load(cid, workspace_dir()), "work")
    except Exception:  # noqa: BLE001
        return default
    chain = [{"provider": b["provider"], "model": str(b.get("model") or ""), "timeout": int(b.get("timeout") or 0)}
             for b in raw if isinstance(b, dict) and b.get("provider") in PROVIDERS]
    return chain or default


# --------------------------------------------------------------- transcript

def save_transcript(tid: int, title: str, lines: List[Dict]) -> Optional[Path]:
    if not lines:
        return None
    out_dir = WORKTREE_BASE / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / ("ticket-%d-%s" % (tid, time.strftime("%Y%m%d-%H%M%S")))
    md = ["# #%d %s" % (tid, title), ""]
    for ln in lines:
        head = "**%s**" % ln["name"] + (" `%s`" % ln["verdict"] if ln.get("verdict") else "")
        md += ["%s (round %d): %s" % (head, ln["round"], ln["text"] or "…"), ""]
    stem.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(lines, ensure_ascii=False, indent=1), encoding="utf-8")
    return stem.with_suffix(".md")


# ------------------------------------------------------------ run state

def state_path(tid: int) -> Path:
    return WORKTREE_BASE / "runs" / ("ticket-%d.json" % tid)


def read_state(tid: int) -> Dict:
    try:
        return json.loads(state_path(tid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def path_bytes(repo: Path, paths: List[str]) -> Dict[str, int]:
    """Each target file's size as the run starts. With `started` and `ended_<outcome>` in the state file, this is the
    record monolith-split D1 ③ asked for: set the size caps from how delegations went, not by judgement."""
    return {p: (repo / p).stat().st_size for p in paths if (repo / p).is_file()}


def write_state(tid: int, **fields) -> None:
    """Merge `fields` into the run's state file (atomic replace): what a watcher shows, what `merge` needs."""
    path = state_path(tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    st = read_state(tid)
    st.update(fields, ticket=tid, updated=time.strftime("%Y-%m-%d %H:%M:%S"), rev=int(st.get("rev", 0)) + 1)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------- landing

def check_scope(wt_dir: Path, base: str, paths: List[str]) -> List[str]:
    """Files the branch changed since `base`; any outside the ticket's paths fails the gate."""
    _, changed, _ = git(wt_dir, "diff", "--name-only", base + "..HEAD")
    files = changed.splitlines()
    outside = [f for f in files if not in_scope(f, paths)]
    if outside:
        raise Failure("gate_failed", "changes outside the ticket's paths: %s" % ", ".join(outside[:10]), retryable=True)
    return files


def sync_onto_main(repo: Path, wt_dir: Path, main_branch: str, base: str) -> str:
    """Rebase the branch onto main if main moved. Returns the new base."""
    _, main_head, _ = git(repo, "rev-parse", main_branch)
    _, merge_base, _ = git(wt_dir, "merge-base", "HEAD", main_head)
    if merge_base == main_head:
        return base
    log("%s moved to %s; rebasing the branch" % (main_branch, main_head[:8]))
    code, _, err = git(wt_dir, "rebase", main_head)
    if code != 0:
        git(wt_dir, "rebase", "--abort")
        raise Failure("gate_failed", "branch does not rebase cleanly onto %s" % main_branch, tail(err))
    return main_head


LAND_TRIES = 3


def land(repo: Path, wt_dir: Path, main_branch: str, branch: str, base: str, gates: List[str],
         on_rebase=None) -> Tuple[str, str]:
    """Bring the branch onto main, check it there when main moved, and fast-forward main to it; (base, head).
    LAND_RETRY_v1: other agents commit on main too. #406 was rebased, then a commit landed on main while its gates
    ran, and the fast-forward was refused -- so when main moved again, rebase and check again (LAND_TRIES times)."""
    for attempt in range(1, LAND_TRIES + 1):
        new_base = sync_onto_main(repo, wt_dir, main_branch, base)
        if new_base != base:
            base = new_base
            if on_rebase:
                on_rebase(base)
            run_gates(wt_dir, gates)
        try:
            return base, ff_merge(repo, main_branch, branch)
        except Failure:
            moved = git(repo, "rev-parse", main_branch)[1] != git(wt_dir, "merge-base", "HEAD", main_branch)[1]
            if not moved or attempt == LAND_TRIES:
                raise
            log("%s moved while the gates ran; landing again (%d/%d)" % (main_branch, attempt + 1, LAND_TRIES))
    raise Failure("failed", "could not land")   # not reached


def ff_merge(repo: Path, main_branch: str, branch: str) -> str:
    code, cur, _ = git(repo, "symbolic-ref", "--short", "HEAD")
    if cur != main_branch:
        raise Failure("failed", "main repository is on %s, not %s" % (cur, main_branch))
    code, _, err = git(repo, "merge", "--ff-only", branch)
    if code != 0:
        raise Failure("failed", "fast-forward merge into %s refused (it moved or local changes are in the way)"
                      % main_branch, tail(err))
    head = git(repo, "rev-parse", "HEAD")[1]
    log("merged into %s at %s" % (main_branch, head[:8]))
    return head


TICKET_OUTCOME = {"base_broken": "unavailable"}   # runner outcomes the ticket store does not know: the attempt is given back


def release_failed(tid: int, token: str, f: Failure, provider: str, actor: str, result: Dict) -> None:
    result.update(outcome=f.outcome, reason=f.reason, detail=f.detail)
    print("[!] %s" % f.reason, file=sys.stderr)
    if f.detail:
        print(f.detail, file=sys.stderr)
    try:
        vals = ticket_call("fail", "--id", str(tid), "--token", token, "--outcome", TICKET_OUTCOME.get(f.outcome, f.outcome),
                           "--note", "worktree %s: %s" % (provider, f.reason), "--actor", actor)
        if vals.get("ADVICE"):
            result["advice"] = vals["ADVICE"]
            print("[!] ticket: %s" % vals["ADVICE"], file=sys.stderr)
    except RuntimeError as e:
        print("[!] ticket release failed: %s" % e, file=sys.stderr)


def close_done(tid: int, token: str, actor: str, note: str, result: Dict) -> None:
    try:
        ticket_call("done", "--id", str(tid), "--token", token, "--actor", actor, "--note", note)
        result["outcome"] = "done"
        log("ticket #%d done" % tid)
    except RuntimeError as e:
        result.update(outcome="merged-ticket-open", reason=tail(str(e), 1))   # the card shows it
        print("[!] merged, but the ticket could not be closed: %s" % e, file=sys.stderr)
    log("the live host was not restarted; deploy host-module changes with `chatbot-ctl.sh repair` once idle")


def record_and_report(repo: Path, tid: int, provider: str, title: str, result: Dict, as_json: bool,
                      transcript: Optional[List[Dict]] = None) -> int:
    outcome = result.get("outcome") or "open"
    subject = ("chore(tickets): close #%d" if outcome == "done" else "chore(tickets): #%d " + outcome) % tid
    extra: Tuple[str, ...] = ()
    if result.get("merged"):   # the landed change gets its line in the diary (tools/history_entry.py)
        import history_entry
        extra = tuple(history_entry.record_merge(repo, tid, title, provider, result["base"], result.get("head")))
    record = commit_ticket_record(repo, tid, provider, "%s -- %s" % (subject, title[:80]), extra)
    if record:
        result["ticket_commit"] = record
        log("ticket record committed (%s)" % record)
    write_state(tid, phase=outcome, reason=result.get("reason", ""), head=result.get("head", ""),
                **{"ended_" + outcome: time.time()})
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for ln in transcript or []:
            print("%s%s: %s" % (ln["name"], " [%s]" % ln["verdict"] if ln.get("verdict") else "", ln["text"] or "…"))
        print("RESULT=%s TICKET_ID=%d MERGED=%s" % (outcome, tid, "yes" if result.get("merged") else "no"))
    return 0 if outcome in ("done", "awaiting_merge") else 1


# ---------------------------------------------------------------------- run

MAX_TASKS = 8


def roster(fn: str, fallback):
    """characters.<fn>(workspace): the team as data -- the engine knows no role by name. `fallback` if unreadable."""
    try:
        return getattr(host_module("characters"), fn)(workspace_dir())
    except Exception:  # noqa: BLE001
        return fallback


def worker_role() -> str:   # a task without a role goes to the first expert role; "" when there is none
    return (roster("expert_roles", []) or [""])[0]


def plan_tasks(args, st: Dict, paths: List[str]) -> List[Dict]:
    """The tasks of this run: the plan kept in the run's state (--plan-from-state), a rework of the waiting
    branch (--resume: the operator's comment as one task), or the single task given on the command line."""
    if args.resume:
        roles = [t.get("role") for t in (st.get("plan") or {}).get("tasks", []) if t.get("role")]
        return [{"role": roles[-1] if roles else worker_role(), "title": "rework: " + args.title, "paths": paths,
                 "instruction": "The operator sent the finished work back. Their comment:\n" + args.prompt}]
    if args.plan_from_state:
        tasks = (st.get("plan") or {}).get("tasks") or []
        if not tasks or len(tasks) > MAX_TASKS:
            raise Failure("failed", "the ticket's plan has %d task(s); 1-%d expected" % (len(tasks), MAX_TASKS))
        out = []
        for t in tasks:
            tp = [x for x in (t.get("paths") or []) if x]
            if not tp or not all(any(in_scope(x, [p]) for p in paths) for x in tp):
                raise Failure("failed", "task %r names paths outside the plan's" % t.get("title", "")[:40])
            out.append({"role": t.get("role") or worker_role(), "title": t.get("title") or args.title,
                        "instruction": t.get("instruction") or "", "paths": tp,
                        "reads": [x for x in (t.get("reads") or []) if x and x not in tp]})
        return out
    return [{"role": worker_role(), "title": args.title, "instruction": args.prompt, "paths": paths}]


# ------------------------------------------------------------------ content

def dirty_paths(repo: Path) -> set:
    """Changed or new files git sees in `repo` (the scope check of content work)."""
    _, out, _ = git(repo, "status", "--porcelain", "-uall")
    found = set()
    for ln in out.splitlines():
        parts = ln.strip().split(None, 1)          # "XY path": the output may come with its first space trimmed
        if len(parts) == 2:
            found.add(parts[1].split(" -> ")[-1].strip('"'))
    return found


def keep_old(repo: Path, paths: List[str]) -> List[str]:
    """Copy each existing file in `paths` to `<its folder>/_old/<name>.<time>` before content work may overwrite it."""
    kept, stamp = [], time.strftime("%Y%m%d-%H%M%S")
    for p in paths:
        f = repo / p
        if f.is_file():
            dst = f.parent / "_old" / ("%s.%s" % (f.name, stamp))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(f), str(dst))
            kept.append(dst.relative_to(repo).as_posix())
    return kept


def content_prompt(tid: int, title: str, repo: Path, paths: List[str], instruction: str, character: str,
                   memory: str = "") -> str:
    remembered = ["What you remember from earlier work (yours alone):", memory, ""] if memory.strip() else []
    return "\n".join(remembered + [
        "You are working on ticket #%d (%s): user content, not code." % (tid, title),
        "Working directory: %s. Write only these repo-relative paths: %s. Do not touch any other file, do not commit, "
        "do not run tests, do not restart anything. Files you overwrite were copied to _old/ first." % (repo, ", ".join(paths)),
        "The operator looks at the result and decides; nobody reviews it before that.",
        "", instruction, "", character, LINE_RULE])


def run_content(args, repo: Path, provider: str, paths: List[str], tid: int, token: str, actor: str,
                result: Dict) -> int:
    """CONTENT_WORK_v1 (plan dlg/E): work whose paths are all user data (tickets.is_content) is written in place --
    no worktree, commit, gates, PD review or merge (#371: one picture went through all of them and its close failed
    four times). The operator's eyes are the check (a gallery picture waits there until placed). Files it would
    overwrite are kept in _old/; a change outside the paths fails the run and is reported, not undone."""
    transcript: List[Dict] = []
    try:
        st = read_state(tid)
        tasks = plan_tasks(args, st, paths)
        before = dirty_paths(repo)
        kept = keep_old(repo, paths)
        write_state(tid, phase="running", content=True, round=0, task=0, tasks_total=len(tasks), started=time.time(),
                    phase_since=time.time(), title=args.title, provider=provider, reviewer=None, paths=paths,
                    transcript=transcript, reason="", kept=False, tasks_done=0, target_bytes=path_bytes(repo, paths))
        for tno, task in enumerate(tasks, 1):
            writer_p = persona(task["role"])
            chain = fresh(expert_chain(task["role"], [{"provider": provider, "model": args.model, "timeout": 0}]))
            brief = content_prompt(tid, task["title"], repo, task["paths"], task["instruction"],
                                   character_block(writer_p, persona(), STAFF_RELATION), read_memory(task["role"]))
            skipped, res, b = [], None, chain[0]
            for bi, b in enumerate(chain):
                timeout = b["timeout"] or args.timeout
                write_state(tid, phase="writing", task=tno, round=1, brain=brain_label(b), phase_since=time.time(),
                            timeout_sec=timeout)
                res = run_agent(b["provider"], repo, brief, timeout, model=b["model"])
                if res["ok"]:
                    break
                why = tail(res["stderr"] or res["stdout"], 5)
                if unavailable(why, res["returncode"]):
                    mark(WORKTREE_BASE / LIMITS, b, why)
                if unavailable(why, res["returncode"]) and bi + 1 < len(chain):
                    skipped.append(brain_label(b))
                    continue
                raise Failure("unavailable" if unavailable(why, res["returncode"]) else "failed",
                              "agent %s: %s" % (brain_label(b), why[:200]), tail(res["stdout"]))
            line = {"task": tno, "round": 1, "role": "writer", "name": writer_p["name"], "text": said(res["stdout"]),
                    "brain": brain_label(b)}
            if skipped:
                line["skipped"] = skipped
            transcript.append(line)
            write_state(tid, transcript=transcript, tasks_done=tno)
        outside = sorted(p for p in dirty_paths(repo) - before if not in_scope(p, paths) and "/_old/" not in "/" + p)
        if outside:
            raise Failure("failed", "content work changed files outside its paths: %s" % ", ".join(outside[:5]))
        made = [p for p in paths if (repo / p).exists()]
        if not made:
            raise Failure("failed", "content work wrote none of %s" % ", ".join(paths[:5]))
        close_done(tid, token, actor, "content written in place: %s%s" % (
            ", ".join(made[:5]), "; kept in _old/: %d" % len(kept) if kept else ""), result)
    except Failure as f:
        release_failed(tid, token, f, provider, actor, result)
    result["transcript"] = transcript
    return record_and_report(repo, tid, provider, args.title, result, args.json, transcript)


def arg_error(args, paths: List[str]) -> str:
    """Why `run` cannot start with these arguments; "" when it can."""
    if not paths:
        return "--paths is required (the scope gate and the ticket's ship gate use it)"
    if args.timeout > MAX_AGENT_TIMEOUT:
        return "--timeout above %ds would outlive the %ds author lease" % (MAX_AGENT_TIMEOUT, LEASE_TTL_SEC)
    if args.rounds < 1:
        return "--rounds must be at least 1"
    if (args.resume or args.plan_from_state or args.from_attic) and not args.ticket:
        return "--resume, --plan-from-state and --from-attic work on a --ticket"
    if not args.plan_from_state and not args.prompt.strip():
        return "--prompt is required (unless the tasks come from the ticket's plan)"
    return ""


def claim_ticket(args, paths: List[str], actor: str):
    """(ticket, token): the caller's claimed ticket, or a new one started now. An int is the exit code of a refusal."""
    if args.ticket and args.token:
        return args.ticket, args.token
    if args.ticket or args.token:
        print("Error: --ticket and --token go together (a ticket the caller has claimed)", file=sys.stderr)
        return 2
    try:
        vals = ticket_call("start", "--title", args.title, "--paths", ",".join(paths),
                           "--actor", actor, *sum((["--evidence", e] for e in args.evidence), []))
        return int(vals["TICKET_ID"]), vals["CLAIM_TOKEN"]
    except (RuntimeError, KeyError, ValueError) as e:
        print("Error: ticket start failed: %s" % e, file=sys.stderr)
        return 1


def new_worktree(args, repo: Path, tid: int, branch: str, wt_dir: Path) -> Tuple[str, bool]:
    """A fresh worktree for the ticket; (base, from_attic). Raises Failure, the worktree not made, when it cannot."""
    if wt_dir.exists() or git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0:
        raise Failure("failed", "%s or %s is left over from an earlier run; "
                      "inspect it, then `worktree_runner.py cleanup --ticket %d`" % (branch, wt_dir, tid))
    _, base, _ = git(repo, "rev-parse", "HEAD")
    start = base
    from_attic = False
    if args.from_attic:   # go on from the head a failed attempt left; base is where that work forked
        code, start, _ = git(repo, "rev-parse", "--verify", "--quiet", attic_ref(tid))
        if code != 0:
            raise Failure("failed", "no %s to start from" % attic_ref(tid))
        base = git(repo, "merge-base", base, start)[1]
        from_attic = True
    WORKTREE_BASE.mkdir(parents=True, exist_ok=True)
    code, _, err = git(repo, "worktree", "add", "-b", branch, str(wt_dir), start)
    if code != 0:
        raise Failure("failed", "git worktree add failed", err)
    log("worktree %s on %s (base %s%s)" % (wt_dir, branch, base[:8],
                                           ", from %s %s" % (attic_ref(tid), start[:8]) if from_attic else ""))
    return base, from_attic


def run_setup(args):
    """Check the request and claim its ticket: the run's shared state (`r`), or an exit code."""
    repo = CHATBOT_REPO
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    r = SimpleNamespace(args=args, repo=repo, provider=args.provider, paths=paths, transcript=[], rnd=0,
                        reviewer=None if args.no_review else (args.reviewer or args.provider), doc_advice="",
                        created=False, from_attic=False)
    r.gates = DEFAULT_GATES + [g for g in (related_gate(repo, paths),) if g] + list(args.gate or [])
    r.result = {"provider": r.provider, "reviewer": r.reviewer, "paths": paths, "merged": False}
    bad = arg_error(args, paths)
    if bad:
        print("Error: " + bad, file=sys.stderr)
        return 2
    code, r.main_branch, _ = git(repo, "symbolic-ref", "--short", "HEAD")
    if code != 0:
        print("Error: main repository is on a detached HEAD", file=sys.stderr)
        return 2
    r.gated = gate_files(repo, r.gates)
    try:
        tier = check_tiers(repo, paths, r.gated, retryable=False)
    except Failure as f:
        print("Error: %s" % f.reason, file=sys.stderr)
        return 2
    if tier >= 2 and not args.stop_before_merge:
        log("Tier 2 paths: the change will wait for the operator's merge (--stop-before-merge)")
        args.stop_before_merge = True
    r.result["tier"] = tier
    r.doc_lane = args.stop_before_merge and is_doc_task(paths, tier)   # DOC_LANE_v1
    r.display_lane = args.stop_before_merge and is_display_task(paths, tier)   # DISPLAY_LANE_v1
    r.reviewer_p = persona()   # the reviewer is the default character, whatever roles it holds (TEAM_ROLES_v1)
    r.actor = PROVIDERS[r.provider]["actor"]
    # 1. ticket: one the caller already claimed (--ticket/--token), or a new one on the operator's instruction
    claimed = claim_ticket(args, paths, r.actor)
    if isinstance(claimed, int):
        return claimed
    r.tid, r.token = claimed
    r.branch, r.wt_dir = names(r.tid)
    r.result.update(ticket=r.tid, branch=r.branch, worktree=str(r.wt_dir))
    log("ticket #%d claimed (paths: %s)" % (r.tid, ", ".join(paths)))
    return r


def run_open(r) -> List[Dict]:
    """2. The worktree: a new one, or (--resume, a rework, a plan picked up) the one this ticket's last run kept.
    Sets the run's base and where its plan starts; returns the plan's tasks."""
    args, repo, wt_dir = r.args, r.repo, r.wt_dir
    st = read_state(r.tid)
    # a plan whose confirmation found no PD brain last time: go on from the kept branch
    pick_up = (args.plan_from_state and st.get("kept") and st.get("base") and wt_dir.exists()
               and git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + r.branch)[0] == 0)
    r.done_tasks = int(st.get("tasks_done") or 0) if pick_up else 0
    r.pending = (int(st.get("pending_task") or 0), st.get("pending_base") or "") if pick_up else (0, "")
    # the task that paused for more paths: worked again, but reviewed from its own base so pre-pause commits count
    r.paused = (int(st.get("need_task") or 0), st.get("need_base") or "") if pick_up else (0, "")
    if args.resume or pick_up:
        if not wt_dir.exists() or not st.get("base"):
            raise Failure("failed", "nothing to rework: the waiting worktree of ticket %d is gone" % r.tid)
        r.base = st["base"]
        r.created = True
        log("%s in %s (branch %s)" % ("picking up after task %d" % r.done_tasks if pick_up else "reworking",
                                      wt_dir, r.branch))
        if pick_up and st.get("base_broken") and r.pending[1] in ("", r.base):
            # BASE_CHECK_v1: the stop was main's own failure, fixed there since: the kept work goes on from main
            new = sync_onto_main(repo, wt_dir, r.main_branch, r.base)
            r.pending, r.base = (r.pending[0], new if r.pending[1] else ""), new
    else:
        r.base, r.from_attic = new_worktree(args, repo, r.tid, r.branch, wt_dir)
        r.created = True
    r.result["base"] = r.base
    tasks = plan_tasks(args, st, r.paths)
    if args.resume or pick_up:
        r.transcript = list(st.get("transcript") or [])
    write_state(r.tid, phase="running", round=0, task=0, tasks_total=len(tasks), started=time.time(),
                phase_since=time.time(), title=args.title, provider=r.provider, reviewer=r.reviewer,
                paths=r.paths, gates=r.gates, main_branch=r.main_branch, base=r.base, branch=r.branch,
                worktree=str(wt_dir), transcript=r.transcript, reason="", kept=False, tasks_done=r.done_tasks,
                base_broken=False, target_bytes=path_bytes(repo, r.paths))
    r.pd_chain = fresh(expert_chain(roster("default_character", ""), [{"provider": r.reviewer, "timeout": 0,
                                                                       "model": args.reviewer_model}]), False) if r.reviewer else []
    return tasks


def renew(r) -> None:
    try:
        ticket_call("renew", "--id", str(r.tid), "--token", r.token, "--actor", r.actor)
    except RuntimeError as e:
        raise Failure("failed", "author lease lost during the run", str(e))


def run_task(r, tno: int, n_tasks: int, task: Dict) -> None:
    """3. One task of the plan: the expert works -> gates -> the PD confirms, up to --rounds."""
    args = r.args
    k = SimpleNamespace(tno=tno, task=task, writer_p=persona(task["role"]), lessons=[], feedback="", bi=0,
                        last_brain=None, partner_report="", base_checked=set(), reviewed="")   # BASE_CHECK_v1: once per gate
    # the task whose work waited for a confirmation: straight to its gates and review, on its own base
    k.confirm_only = tno == r.pending[0] and bool(r.pending[1])
    if k.confirm_only:
        k.base = r.pending[1]
    elif tno == r.paused[0] and r.paused[1]:
        k.base = r.paused[1]
    elif tno == 1 and r.from_attic:   # the carried-over work is reviewed with this task
        k.base = r.base
    else:
        k.base = git(r.wt_dir, "rev-parse", "HEAD")[1]
    write_state(r.tid, pending_task=tno, pending_base=k.base)
    head_line = ("This is task %d of %d in the plan \"%s\". Do only this task.\n" % (tno, n_tasks, args.title)
                 if n_tasks > 1 else "")
    k.brief = writer_prompt(r.tid, task["title"], r.branch, r.wt_dir, task["paths"], r.gates,
                            head_line + task["instruction"], character_block(k.writer_p, r.reviewer_p, STAFF_RELATION),
                            read_memory(task["role"]), task.get("reads"))
    k.chain = fresh(expert_chain(task["role"], [{"provider": r.provider, "model": args.model, "timeout": 0}]),
                    not k.confirm_only)
    k.n_tasks = n_tasks
    for rnd in range(1, args.rounds + 1):
        r.rnd = rnd
        if rnd > 1 or tno > 1:
            renew(r)
        first_confirm = k.confirm_only and rnd == 1
        res, b = (None, k.chain[k.bi]) if first_confirm else task_work(r, k, rnd)
        if not first_confirm:
            task_record(r, k, rnd, res, b)
        asked = [] if first_confirm else need_paths(res["stdout"], task["paths"])
        if asked:   # the worker needs files outside its scope: keep the work, wait for the operator
            commit_leftovers(r.wt_dir, b["provider"], r.tid)
            write_state(r.tid, phase="needs_path", need_paths=asked, need_task=tno, need_base=k.base,
                        tasks_done=tno - 1, pending_task=0, pending_base="", transcript=r.transcript,
                        phase_since=time.time())
            raise Failure("paused", "task %d needs %s" % (tno, ", ".join(x["path"] for x in asked)), keep=True)
        gate_error = task_gates(r, k, rnd, b)
        no_review = not r.reviewer or r.display_lane or k.reviewed   # DISPLAY_LANE_v1, REVIEW_ONCE_v1
        if no_review and gate_error is None:
            if r.reviewer:
                r.doc_advice = DISPLAY_NOTE if r.display_lane else once_note(k.reviewed)
                r.args.stop_before_merge = True
                write_state(r.tid, tasks_done=tno, need_base="", doc_advice=r.doc_advice)
            if remember(task["role"], k.lessons):
                log("task %d: %d lesson(s) kept in %s's memory" % (tno, len(k.lessons), task["role"]))
            return
        if no_review:
            if rnd == args.rounds:
                raise gate_error
            k.feedback = "Gate failure: %s\n%s" % (gate_error.reason, gate_error.detail[-2000:])
            continue
        if task_review(r, k, rnd, b, gate_error):
            return


def task_work(r, k, rnd: int):
    """The expert's turn: its brain chain in order until one works. Returns (its output, the brain)."""
    skipped = []
    while True:
        b = k.chain[k.bi]
        resume = rnd > 1 and b == k.last_brain and bool(PROVIDERS[b["provider"]].get("continue_argv"))
        prompt = k.brief if rnd == 1 else retry_prompt(k.feedback, None if resume else k.brief)
        timeout = b["timeout"] or r.args.timeout
        write_state(r.tid, phase="writing", task=k.tno, round=rnd, brain=brain_label(b), phase_since=time.time(),
                    timeout_sec=timeout)
        log("task %d/%d round %d: running %s (timeout %ds)..." % (k.tno, k.n_tasks, rnd, brain_label(b), timeout))
        res = run_agent(b["provider"], r.wt_dir, prompt, timeout, resume=resume, model=b["model"])
        r.result["agent"] = {x: res[x] for x in ("ok", "returncode", "elapsed_sec")}
        log("%s finished in %ss (exit %s)" % (brain_label(b), res["elapsed_sec"], res["returncode"]))
        if res["ok"]:
            res["skipped"] = skipped
            return res, b
        why = tail(res["stderr"] or res["stdout"], 5)
        if unavailable(why, res["returncode"]):
            mark(WORKTREE_BASE / LIMITS, b, why)
        if unavailable(why, res["returncode"]) and k.bi + 1 < len(k.chain):
            skipped.append(brain_label(b))
            log("%s unavailable; next brain %s" % (brain_label(b), brain_label(k.chain[k.bi + 1])))
            k.bi += 1
            renew(r)
            continue
        if res["returncode"] == -1 and str(res["stderr"]).startswith("timed out"):
            raise Failure("unavailable", "agent %s timed out after %ds" % (brain_label(b), timeout),
                          tail(res["stdout"]))
        if unavailable(why, res["returncode"]):      # the last brain could not work either: not a try
            raise Failure("unavailable", "no brain could work (%s): %s" % (brain_label(b), why[:200]))
        raise Failure("failed", "agent %s exited with %s" % (brain_label(b), res["returncode"]),
                      tail(res["stderr"] or res["stdout"]))


def task_record(r, k, rnd: int, res: Dict, b: Dict) -> None:
    """The expert's report, its line to the PD and its lessons, kept for the review and the transcript."""
    k.last_brain = b
    k.partner_report = report(res["stdout"])
    line = {"task": k.tno, "round": rnd, "role": "writer", "name": k.writer_p["name"],
            "text": said(res["stdout"]), "brain": brain_label(b)}
    round_lessons = learned(res["stdout"])
    if round_lessons:
        line["learned"] = round_lessons
        k.lessons += [x for x in round_lessons if x not in k.lessons]
    if res.get("skipped"):
        line["skipped"] = res["skipped"]
    r.transcript.append(line)


def task_gates(r, k, rnd: int, b: Dict) -> Optional[Failure]:
    """The machine gates on the task's commits. A retryable failure is returned for the PD to send back; a gate that
    fails on the base too stops the run (BASE_CHECK_v1); anything else is raised."""
    write_state(r.tid, phase="gates", transcript=r.transcript, phase_since=time.time())
    if commit_leftovers(r.wt_dir, b["provider"], r.tid):
        log("committed changes the agent left uncommitted")
    try:
        if not git(r.wt_dir, "rev-list", k.base + "..HEAD")[1]:
            raise Failure("failed", "task %d made no change" % k.tno)
        changed = check_scope(r.wt_dir, k.base, k.task["paths"])
        if check_tiers(r.repo, changed, r.gated, retryable=True) >= 2 and not r.args.stop_before_merge:
            log("the change touches Tier 2 paths: it will wait for the operator's merge")
            r.args.stop_before_merge = True
            r.result["tier"] = 2
        renew(r)
        run_gates(r.wt_dir, r.gates)
    except Failure as f:
        gate = getattr(f, "gate", None)
        if gate and gate not in k.base_checked:
            k.base_checked.add(gate)
            broken = base_fails(r.repo, k.base, gate, r.tid)
            if broken is not None:
                write_state(r.tid, base_broken=True)
                raise Failure("base_broken", "gate fails without this work too: %s -- fix the base, then "
                              "run again; the work is kept" % gate, broken, keep=True)
        if not (f.retryable and r.reviewer):
            raise
        log("task %d round %d: %s" % (k.tno, rnd, f.reason))
        return f
    return None


def task_review(r, k, rnd: int, b: Dict, gate_error: Optional[Failure]) -> bool:
    """The PD confirms the task's diff (or reads its gate failure). True when the task is through; otherwise the
    requested fixes wait in `k.feedback` for the next round, or the last round raises."""
    tno, task, doc_lane = k.tno, k.task, r.doc_lane
    write_state(r.tid, phase="review", phase_since=time.time())
    _, diff, _ = git(r.wt_dir, "diff", k.base + "..HEAD")
    pd_block = character_block(r.reviewer_p, k.writer_p, PD_RELATION)
    partner_said = next((ln["text"] for ln in reversed(r.transcript)
                         if ln.get("task") == tno and ln.get("role") == "writer"), "")
    rv, rb, rskipped = review_with_chain(
        cross_chain(r.pd_chain, b, review_providers() if r.args.cross_review else []), r.wt_dir,
        lambda prov: (doc_review_prompt if doc_lane else (lambda b, d: with_code_checklist(b)))(
            review_prompt(r.tid, task["title"], task["instruction"], partner_said, diff, gate_error,
                          pd_block, diff_limit(prov), k.partner_report), diff),
        lambda: renew(r))
    verdict = "FAIL" if gate_error else rv["verdict"]
    advisory = doc_lane and gate_error is None
    r.transcript.append({"task": tno, "round": rnd, "role": "reviewer", "name": r.reviewer_p["name"],
                         **({"advisory": True, "deleted": deleted_lines(diff)} if advisory else {}),
                         "brain": brain_label(rb), **({"skipped": rskipped} if rskipped else {}),
                         **({"same_provider": True} if rb["provider"] == b["provider"] else {}),
                         "text": rv["say"], "verdict": verdict, "fix": rv["fix"], "raw": rv["raw"]})
    log("task %d round %d: review %s" % (tno, rnd, verdict))
    write_state(r.tid, transcript=r.transcript)
    if advisory and verdict != "PASS":
        # DOC_LANE_v1: the review is advice; the operator decides with it on the card
        r.doc_advice = "doc review %s (advice: %s)" % (verdict, (rv["fix"] or rv["say"])[:300])
        log("task %d: %s" % (tno, r.doc_advice))
        write_state(r.tid, tasks_done=tno, need_base="", doc_advice=r.doc_advice)
        return True
    if verdict == "PASS":
        if remember(task["role"], k.lessons):
            log("task %d: lesson(s) kept in %s's memory" % (tno, task["role"]))
        write_state(r.tid, tasks_done=tno, need_base="")
        return True
    if rnd == r.args.rounds:
        if gate_error:
            raise gate_error
        raise Failure("gate_failed", "task %d: review FAIL after %d round(s)" % (tno, rnd), rv["fix"])
    if not gate_error:
        k.reviewed = rv["fix"] or rv["say"] or "FAIL"   # REVIEW_ONCE_v1
    k.feedback = "\n".join(x for x in (
        "Gate failure: %s\n%s" % (gate_error.reason, gate_error.detail[-2000:]) if gate_error else "",
        "Your producer says: %s" % rv["say"] if rv["say"] else "",
        "Requested fixes:\n%s" % rv["fix"] if rv["fix"] else "") if x)
    return False


def run_land(r) -> None:
    """4. Land on main, or (--stop-before-merge) hand the ticket in to wait for the operator."""
    if r.args.stop_before_merge:
        head = git(r.wt_dir, "rev-parse", "HEAD")[1]
        try:
            ticket_call("await-merge", "--id", str(r.tid), "--token", r.token, "--actor", r.actor, "--note",
                        "branch %s at %s (%s,%s round %d)" % (r.branch, head[:7], r.provider, r.verdict, r.rnd))
        except RuntimeError as e:
            raise Failure("failed", "could not hand the ticket in for merge", str(e))
        r.result.update(outcome="awaiting_merge", head=head)
        log("ticket #%d awaits the operator's merge: worktree_runner.py merge --ticket %d" % (r.tid, r.tid))
    else:   # landing now: onto main, checked there once more when main moved (LAND_RETRY_v1)
        base, head = land(r.repo, r.wt_dir, r.main_branch, r.branch, r.base, r.gates,
                          on_rebase=lambda b: write_state(r.tid, base=b))
        r.result.update(merged=True, head=head, base=base)


def run_cleanup(r) -> None:
    """The worktree goes unless the work waits (kept, --keep, awaiting the operator); a dropped branch's head stays
    in the attic for the next --from-attic run."""
    result = r.result
    keep = r.created and not result["merged"] and (r.args.keep or result.get("kept")
                                                   or result.get("outcome") == "awaiting_merge")
    if r.created and not keep:
        cleanup_worktree(r.repo, r.branch, r.wt_dir, attic="" if result["merged"] else attic_ref(r.tid))
        log("worktree and branch removed" if result["merged"] else "worktree removed; branch head kept at %s"
            % attic_ref(r.tid))
    if result["merged"]:
        drop_attic(r.repo, r.tid)
    elif keep:
        log("kept %s (branch %s)" % (r.wt_dir, r.branch))


def cmd_run(args) -> int:
    r = run_setup(args)
    if isinstance(r, int):
        return r
    result = r.result
    if args.content:
        return run_content(args, r.repo, r.provider, r.paths, r.tid, r.token, r.actor, result)
    r.verdict = ""
    try:
        tasks = run_open(r)
        for tno, task in enumerate(tasks, 1):
            if tno > r.done_tasks:
                run_task(r, tno, len(tasks), task)
        result["rounds"] = r.rnd
        result["changed"] = check_scope(r.wt_dir, r.base, r.paths)
        r.verdict = (" " + r.doc_advice if r.doc_advice else " review PASS") if r.reviewer else ""
        run_land(r)
    except Failure as f:
        release_failed(r.tid, r.token, f, r.provider, r.actor, result)
        if f.keep and r.created:
            result["kept"] = True
            write_state(r.tid, kept=True)
    finally:
        run_cleanup(r)
    if result["merged"]:
        close_done(r.tid, r.token, r.actor, "merged %s via worktree (%s,%s round %d)"
                   % (result["head"][:7], r.provider, r.verdict, result["rounds"]), result)
    saved = save_transcript(r.tid, args.title, r.transcript)
    result["transcript"] = r.transcript
    result["transcript_file"] = str(saved) if saved else None
    return record_and_report(r.repo, r.tid, r.provider, args.title, result, args.json, r.transcript)


def cmd_merge(args) -> int:
    """Land a ticket that `run --stop-before-merge` left awaiting the operator. Running this is the operator's
    word (relayed to the ticket with merge-go) unless --token says it was already given."""
    repo, tid = CHATBOT_REPO, args.ticket
    run_usage.CONTEXT["ticket"] = tid
    st = read_state(tid)
    # "merging": the page marks the run before it starts this process (the operator's word is already given)
    if not st.get("provider") or st.get("phase") not in ("awaiting_merge", "merging"):
        print("Error: no run of ticket #%d is awaiting a merge (%s)" % (tid, state_path(tid)), file=sys.stderr)
        return 2
    provider, branch, wt_dir = st["provider"], *names(tid)
    actor = PROVIDERS[provider]["actor"]
    title = st.get("title", "")
    result: Dict = {"ticket": tid, "provider": provider, "branch": branch, "merged": False}
    token = args.token
    if not token:
        try:
            token = ticket_call("merge-go", "--id", str(tid))["CLAIM_TOKEN"]
        except (RuntimeError, KeyError) as e:
            print("Error: merge-go failed: %s" % e, file=sys.stderr)
            return 1
    write_state(tid, phase="merging")
    try:
        if not wt_dir.exists() or git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] != 0:
            raise Failure("failed", "the waiting worktree or branch %s is gone" % branch)
        # the reviewed change now sits on a different main: its scope and tiers are checked again, then its gates
        base, head = land(repo, wt_dir, st["main_branch"], branch, st["base"], st["gates"],
                       on_rebase=lambda b: check_tiers(repo, check_scope(wt_dir, b, st["paths"]),
                                                       gate_files(repo, st["gates"]), retryable=False))
        result.update(merged=True, head=head, base=base)
    except Failure as f:
        release_failed(tid, token, f, provider, actor, result)
    finally:
        if result["merged"] or not args.keep:
            cleanup_worktree(repo, branch, wt_dir, attic="" if result["merged"] else attic_ref(tid))
            log("worktree and branch removed")
        if result["merged"]:
            drop_attic(repo, tid)
    if result["merged"]:
        close_done(tid, token, actor, "merged %s on the operator's word (%s)" % (result["head"][:7], provider), result)
    return record_and_report(repo, tid, provider, title, result, args.json)


def cmd_cleanup(args) -> int:
    branch, wt_dir = names(args.ticket)
    cleanup_worktree(CHATBOT_REPO, branch, wt_dir, attic=attic_ref(args.ticket))
    print("removed %s and branch %s (if they existed; its head is kept at %s)" % (wt_dir, branch, attic_ref(args.ticket)))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ticketed git-worktree delegation to a CLI agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="ticket -> worktree -> rounds of agent, gates, review -> ff-merge")
    p.add_argument("--provider", default="claude", choices=sorted(PROVIDERS))
    p.add_argument("--title", required=True, help="Ticket title")
    p.add_argument("--paths", required=True, help="Comma-separated repo-relative paths the agent may change")
    p.add_argument("--prompt", default="", help="Instruction for the agent (the comment, with --resume)")
    p.add_argument("--gate", action="append", default=[], help="Extra gate command run in the worktree (repeatable); "
                                                               "the DEFAULT_GATES always run first")
    p.add_argument("--evidence", action="append", default=[], help="Evidence ref passed to ticket-quick (repeatable)")
    p.add_argument("--ticket", type=int, default=0, help="Work on this ticket, already claimed by the caller (with --token)")
    p.add_argument("--plan-from-state", action="store_true",
                   help="Take the tasks from the ticket's run state (the PD's plan; with --ticket)")
    p.add_argument("--resume", action="store_true",
                   help="Rework the ticket's waiting branch with --prompt as the operator's comment (with --ticket)")
    p.add_argument("--from-attic", action="store_true",
                   help="Start a new worktree from the head a failed attempt of --ticket left at refs/attic/ticket-<ID>")
    p.add_argument("--token", default="", help="The caller's claim token for --ticket")
    p.add_argument("--timeout", type=int, default=1200, help="Agent timeout per round in seconds (max %d)" % MAX_AGENT_TIMEOUT)
    p.add_argument("--reviewer", choices=sorted(PROVIDERS), help="Provider for the PD's confirmation (default: --provider)")
    p.add_argument("--model", default="", help="Worker model (default: the provider's work model, else its CLI default)")
    p.add_argument("--content", action="store_true",
                   help="User-data work (CONTENT_WORK_v1): write in place, no worktree, gates, review or merge")
    p.add_argument("--cross-review", action="store_true",
                   help="When the PD has no brain of another provider than the writer's, confirm with another installed "
                        "provider first (REVIEW_CROSS_v1)")
    p.add_argument("--reviewer-model", default="", help="Model for the PD's confirmation (default: the provider's review model)")
    p.add_argument("--rounds", type=int, default=2, help="Staff/PD rounds before giving up (default 2)")
    p.add_argument("--no-review", action="store_true", help="Merge on the mechanical gates alone")
    p.add_argument("--stop-before-merge", action="store_true",
                   help="After a pass, wait for the operator (ticket awaiting_merge) instead of merging (Tier 2)")
    p.add_argument("--keep", action="store_true", help="Keep the worktree and branch when the attempt fails")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")

    m = sub.add_parser("merge", help="Land a ticket that awaits the operator's merge")
    m.add_argument("--ticket", type=int, required=True)
    m.add_argument("--token", default="", help="Lease token from merge_go, when the operator's word was relayed already")
    m.add_argument("--keep", action="store_true", help="Keep the worktree and branch when the merge fails")
    m.add_argument("--json", action="store_true", help="Print the result as JSON")

    c = sub.add_parser("cleanup", help="Remove a leftover worktree and branch of a ticket")
    c.add_argument("--ticket", type=int, required=True)

    args = parser.parse_args(argv)
    return {"run": cmd_run, "merge": cmd_merge, "cleanup": cmd_cleanup}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
