#!/usr/bin/env python3
"""worktree_runner.py: 티켓 하나를 Git Worktree 격리 환경에서 외부 CLI 에이전트에게 외주 주고,
검증 게이트와 PD 캐릭터의 확인(Confirm)을 통과한 결과만 메인 브랜치에 fast-forward 병합한다
(docs/plans/multi-agent-worktree-delegation.md 마일스톤 2, §8 콤비 리뷰).

사용법:
  python3 tools/worktree_runner.py run --provider claude --title "작업 제목" \\
      --paths "tickets.py,tests/test_tickets.py" --prompt "지시문..." \\
      [--gate "python3 tests/test_tickets.py"] [--evidence log:fp:<fp>] [--timeout 1200] \\
      [--reviewer claude] [--reviewer-model haiku] [--rounds 2] [--no-review] [--stop-before-merge] [--keep] [--json]

  # Tier 2: --stop-before-merge로 멈춘 티켓을 사용자 말로 병합 (merge-go 전달 -> 필요 시 rebase + 게이트 재실행 -> ff 병합)
  python3 tools/worktree_runner.py merge --ticket 61 [--token <merge_go가 준 토큰>] [--keep] [--json]

  # 비정상 종료로 남은 worktree/브랜치 정리
  python3 tools/worktree_runner.py cleanup --ticket 61

흐름 (run):
  0. Tier 판정 (protected_paths.json via evolution.delegation_tier): Tier 3(governance, 이번 게이트가 돌리는 파일)은
     거부, Tier 2(protected)는 --stop-before-merge 강제, 그 외는 게이트·리뷰 통과 시 자동 병합.
     실제로 바뀐 파일도 매 라운드 같은 기준으로 다시 본다(디렉터리 경로로 Tier 3 파일을 끼워 넣지 못하게).
  1. ticket-quick start  -> TICKET_ID, CLAIM_TOKEN (승인 + 클레임, 대상 경로가 메인에서 clean해야 함)
  2. git worktree add -b worktree/ticket-<ID> ~/.worktrees/chatbot/ticket-<ID> <main HEAD>
  3. 라운드 (최대 --rounds):
     a. 전문가(data/workspace/characters/<id>/ 캐릭터, 역할로 찾음)가 헤드리스로 작업·커밋하고 캐릭터 대사 한마디를 남긴다
        (미커밋 변경은 러너가 대신 커밋, 커밋 author는 제공자 신원)
     b. 기계 게이트: 커밋 존재 -> 범위(--paths 밖 변경 금지) -> 리스 연장 -> 메인 최신화(rebase)
        -> 가드 테스트(run-tests.sh FAST) + smoke + 변경 파일 관련 테스트 (DEFAULT_GATES, related_gate) + --gate 명령들
     c. PD(pd 역할을 가진 캐릭터)가 diff(또는 게이트 실패)를 보고 확인: VERDICT + 대사 + 수정 요청
     d. 게이트 통과 + PASS면 종료, 아니면 수정 요청을 들고 다음 라운드
  4. 통과: 메인에서 git merge --ff-only -> ticket-quick done -> worktree/브랜치 정리
     --stop-before-merge(Tier 2): 병합 대신 ticket-quick await-merge (리스 해제), worktree/브랜치는 남긴다
     탈락: 병합 없음 -> ticket-quick fail (gate_failed | failed) -> worktree/브랜치 정리 (--keep이면 보존)
       정리 전 브랜치 헤드는 refs/attic/ticket-<ID>에 남는다; 같은 티켓의 다음 run --from-attic이 거기서 시작한다
       (첫 작업의 확인 diff는 그 작업 전체를 본다). 병합되면 attic 참조는 지운다.
     PD 확인 불가(모든 PD 두뇌가 한도·시간 초과): 브랜치를 남기고, 다음 --plan-from-state 실행이 통과한 작업은 건너뛰고
     멈춘 작업의 게이트·확인부터 이어 간다.
  5. 티켓 기록(tickets/<ID>.json)만 메인에 커밋한다 (chore(tickets): close #ID | #ID <outcome>)
  두 캐릭터의 주고받은 대사는 ~/.worktrees/chatbot/transcripts/에 남는다.
  실행 상태(단계·라운드·대사·병합에 필요한 설정)는 ~/.worktrees/chatbot/runs/ticket-<ID>.json에 원자적으로 쓴다.

라이브 호스트는 재시작하지 않는다. 호스트 모듈이 바뀌었으면 유휴 확인 후 `chatbot-ctl.sh repair`로 배포한다.
표준 라이브러리만 사용한다.
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
from typing import Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tools/: devlog_entry, review_checklist
from review_checklist import (  # noqa: E402
    DIFF_LIMIT, deleted_lines, doc_review_prompt, fit_diff, is_doc_task, parse_review, review_prompt, with_code_checklist,
)

CODE_DIR = Path(__file__).resolve().parents[1]      # where the host modules this tool imports live
CHATBOT_REPO = CODE_DIR                              # the repository it works on
WORKTREE_BASE = Path.home() / ".worktrees" / "chatbot"
TICKET_QUICK = [sys.executable, str(CODE_DIR / "tools" / "ticket_quick.py")]   # pew/K: the repo copy
# smoke plus the repo-wide guards (design doc §7-9, NAME_NEUTRAL_v1); a few seconds each
def guard_gate(repo: Path) -> Optional[str]:
    """`./run-tests.sh` over the FAST guard list in run-tests.sh (its SSOT), each module named as a path so that
    gate_files() protects every guard file: a worker must not be able to change its own pass condition (pew/F)."""
    try:
        text = (repo / "run-tests.sh").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^FAST=\((.*?)^\)", text, re.S | re.M)
    mods = [w for w in (m.group(1).split() if m else []) if re.match(r"^test_\w+$", w)]
    files = ["tests/%s.py" % w for w in mods if (repo / "tests" / (w + ".py")).is_file()]
    return "./run-tests.sh " + " ".join(files) if files else None


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
    tests = sorted((repo / "tests").glob("test_*.py"))
    mods = []

    def add(name):
        if name not in mods and ("tests/%s.py" % name) not in guard:
            mods.append(name)
    for p in paths:
        stem = Path(p).stem
        name = stem if p.startswith("tests/test_") and p.endswith(".py") else "test_" + stem
        if (repo / "tests" / (name + ".py")).is_file():
            add(name)
        rx = _mentions(p)
        # page code is read through tests/page_source.py (the whole bundle), so those tests never name the file
        page = re.compile(r"\bpage_source\b") if p.startswith("static/") else None
        for t in tests:
            try:
                text = t.read_text(encoding="utf-8")
            except OSError:
                continue
            if rx.search(text) or (page and page.search(text)):
                add(t.stem)
    return "./run-tests.sh " + " ".join(mods) if mods else None


DEFAULT_GATES = [g for g in (guard_gate(CHATBOT_REPO),) if g] + ["python3 tests/smoke.py", "python3 tests/test_identity_wiring.py"]
LEASE_TTL_SEC = 1800          # tickets.LEASE_TTL_SEC: renewed before and after each agent run
MAX_AGENT_TIMEOUT = 1500
REVIEW_TIMEOUT = 300
GATE_TIMEOUT = 600
TAIL_LINES = 30
# A prompt passed as one argv string is capped by Linux at 128 KiB (MAX_ARG_STRLEN); CLIs that read the prompt
# from stdin (`stdin_prompt`) have no such cap, so they get the whole diff up to DIFF_LIMIT_STDIN (DELEGATION_HARDENING_v1).
# DIFF_LIMIT (the argv cap) lives with the review prompt in review_checklist.py.
DIFF_LIMIT_STDIN = 200000
TICKETS_REL = "data/workspace/skill-observations/tickets"   # tickets.tickets_dir(), repo-relative

# Provider registry: how to run each CLI headless as the worker (`argv`), as the worker again in the same
# conversation (`continue_argv`, only where it resumes by directory), as a tool-less reviewer (`review_argv`,
# the prompt follows `model_flag <model>` when a model is given), who it is on the ticket (role id) and in git.
# The prompt is appended last. Where the prompt is the value of `-p` (agy, grok: `-p` takes the next argument),
# `-p` must be the last element, so every other flag goes before it. `work_model` / `review_model`: the models used
# when none is given; `workdir_flag`: how to let the CLI write in the worktree (agy writes to its own scratch
# folder unless the directory is added).
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

def ticket_call(*args: str) -> Dict[str, str]:
    """Run ticket-quick and return its KEY=VALUE lines. Raises RuntimeError with its stderr."""
    code, out, err = run_cmd(TICKET_QUICK + list(args), timeout=60)
    if code != 0:
        raise RuntimeError(err or out or "ticket-quick %s failed" % args[0])
    vals = {}
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if sep and k.isupper():
            vals[k] = v
    return vals


def commit_ticket_record(repo: Path, tid: int, provider: str, subject: str, extra: Tuple[str, ...] = ()) -> Optional[str]:
    """Commit the ticket's own record in the main repository -- and `extra`, the diary lines a merge wrote
    (tools/devlog_entry.py) -- so main is left clean without an operator step. The short sha, or None."""
    rel = "%s/%04d.json" % (TICKETS_REL, tid)
    if not (repo / rel).exists() or not git(repo, "status", "--porcelain", "--", rel)[1]:
        return None
    name, email = PROVIDERS[provider]["author"]
    git(repo, "add", "--", rel, *extra)
    code, _, err = git(repo, "-c", "user.name=" + name, "-c", "user.email=" + email,
                       "commit", "-m", subject, "--", rel, *extra)
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

LINE_RULE = ("At the very end of your final message, write a line containing only `---`, then one or two short "
             "sentences in character, spoken to your partner, about what you did.")


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
# end its output with LEARNED lines; the lessons of a task are kept only when the PD confirmed it (PASS).

LEARNED_RULE = ("If you learned something worth remembering for future work here (about this project, the user's "
                "preferences, or how to work in this repository), put one short line starting with `LEARNED:` just "
                "before the `---` line. Skip it when there is nothing new.")
_LEARNED = re.compile(r"^\s*\**LEARNED\**\s*:\s*\**\s*(.+?)\s*$", re.I)
_SECRETISH = re.compile(r"(api[_-]?key|secret|password|passwd|token|bearer|sk-[A-Za-z0-9]{8,}|-----BEGIN)", re.I)
MEMORY_CAP = 2048
MEMORY_HEAD = "# Memory\n"


def learned(text: str) -> List[str]:
    """The LEARNED lessons in an agent's output: short, not secret-looking."""
    out = []
    for ln in (text or "").splitlines():
        m = _LEARNED.match(ln)
        if m and not _SECRETISH.search(m.group(1)):
            lesson = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
            if lesson and lesson not in out:
                out.append(lesson)
    return out


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


def said(text: str) -> str:
    """The in-character line after the last `---` of an agent's output (or its last lines); LEARNED lines left out."""
    lines = [ln for ln in (text or "").strip().splitlines() if not _LEARNED.match(ln)]
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).strip()[:500]
    return "\n".join(lines[-2:]).strip()[:500]


REPORT_LIMIT = 4000


def report(text: str, limit: int = REPORT_LIMIT) -> str:
    """The worker's final message before its last `---` line (the report the PD reviews), its end kept; LEARNED
    lines left out. said() is only the short in-character line after it."""
    lines = [ln for ln in (text or "").strip().splitlines() if not _LEARNED.match(ln)]
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            lines = lines[:i]
            break
    body = "\n".join(lines).strip()
    return body if len(body) <= limit else "…" + body[-limit:]


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
    (accounts.rerun_on_switch, ACCOUNT_SWITCH_v1)."""
    try:
        watch, accounts = host_module("delegation_watch"), host_module("providers.accounts").accounts
    except Exception:  # noqa: BLE001
        return run_cmd(cmd, **kw)
    return accounts.rerun_on_switch(provider, lambda: watch.run(cmd, activity=watch.activity_of(provider), **kw), log)


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


def run_gates(wt_dir: Path, gates: List[str]) -> None:
    for cmd in gates:
        log("gate: %s" % cmd)
        code, out, err = run_cmd(["sh", "-c", cmd], cwd=wt_dir, timeout=GATE_TIMEOUT, env=clean_env())  # runs the agent's code
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
        code, out, err = run_cmd(["sh", "-c", cmd], cwd=d, timeout=GATE_TIMEOUT, env=clean_env())
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
    model = model or spec.get("review_model") or ""
    return with_flags(spec["review_argv"], [spec["model_flag"], model] if model else [])


def work_command(provider: str, wt_dir: Path, model: str, resume: bool = False) -> List[str]:
    """The worker's command line in `wt_dir`, the prompt still to be appended."""
    spec = PROVIDERS[provider]
    argv = spec["continue_argv"] if resume and spec.get("continue_argv") else spec["argv"]
    flags = [spec["workdir_flag"], str(wt_dir)] if spec.get("workdir_flag") else []
    model = model or spec.get("work_model") or ""
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

UNAVAILABLE_RE = re.compile(r"quota|rate.?limit|usage limit|session limit|limit reached|resets? (at|in)|\b429\b|"
                            r"exhausted|capacity|overloaded|too many requests|timed out|not installed", re.I)


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


def brain_label(b: Dict) -> str:
    return "%s/%s" % (b["provider"], b["model"] or "default")


def unavailable(text: str, returncode) -> bool:
    """A brain that could not work (quota, limit, missing CLI, timeout), as opposed to one that tried and failed."""
    return returncode in (None, -1) or bool(UNAVAILABLE_RE.search(text or ""))


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
        result["outcome"] = "merged-ticket-open"
        print("[!] merged, but the ticket could not be closed: %s" % e, file=sys.stderr)
    log("the live host was not restarted; deploy host-module changes with `chatbot-ctl.sh repair` once idle")


def record_and_report(repo: Path, tid: int, provider: str, title: str, result: Dict, as_json: bool,
                      transcript: Optional[List[Dict]] = None) -> int:
    outcome = result.get("outcome") or "open"
    subject = ("chore(tickets): close #%d" if outcome == "done" else "chore(tickets): #%d " + outcome) % tid
    extra: Tuple[str, ...] = ()
    if result.get("merged"):   # the landed change gets its line in the diary (tools/devlog_entry.py)
        import devlog_entry
        extra = tuple(devlog_entry.record_merge(repo, tid, title, provider, result["base"], result.get("head")))
    record = commit_ticket_record(repo, tid, provider, "%s -- %s" % (subject, title[:80]), extra)
    if record:
        result["ticket_commit"] = record
        log("ticket record committed (%s)" % record)
    write_state(tid, phase=outcome, reason=result.get("reason", ""), head=result.get("head", ""))
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
                    transcript=transcript, reason="", kept=False, tasks_done=0)
        for tno, task in enumerate(tasks, 1):
            writer_p = persona(task["role"])
            chain = expert_chain(task["role"], [{"provider": provider, "model": args.model, "timeout": 0}])
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


def cmd_run(args) -> int:
    repo = CHATBOT_REPO
    provider = args.provider
    reviewer = None if args.no_review else (args.reviewer or provider)
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    gates = DEFAULT_GATES + [g for g in (related_gate(repo, paths),) if g] + list(args.gate or [])
    result: Dict = {"provider": provider, "reviewer": reviewer, "paths": paths, "merged": False}
    transcript: List[Dict] = []

    bad = arg_error(args, paths)
    if bad:
        print("Error: " + bad, file=sys.stderr)
        return 2
    code, main_branch, _ = git(repo, "symbolic-ref", "--short", "HEAD")
    if code != 0:
        print("Error: main repository is on a detached HEAD", file=sys.stderr)
        return 2
    gated = gate_files(repo, gates)
    try:
        tier = check_tiers(repo, paths, gated, retryable=False)
    except Failure as f:
        print("Error: %s" % f.reason, file=sys.stderr)
        return 2
    if tier >= 2 and not args.stop_before_merge:
        log("Tier 2 paths: the change will wait for the operator's merge (--stop-before-merge)")
        args.stop_before_merge = True
    result["tier"] = tier
    doc_lane = args.stop_before_merge and is_doc_task(paths, tier)   # DOC_LANE_v1
    doc_advice = ""
    reviewer_p = persona()   # the reviewer is the default character, whatever roles it holds (TEAM_ROLES_v1)
    actor = PROVIDERS[provider]["actor"]

    # 1. ticket: one the caller already claimed (--ticket/--token), or a new one on the operator's instruction
    claimed = claim_ticket(args, paths, actor)
    if isinstance(claimed, int):
        return claimed
    tid, token = claimed
    branch, wt_dir = names(tid)
    result.update(ticket=tid, branch=branch, worktree=str(wt_dir))
    log("ticket #%d claimed (paths: %s)" % (tid, ", ".join(paths)))
    if args.content:
        return run_content(args, repo, provider, paths, tid, token, actor, result)

    created = False
    from_attic = False
    rnd = 0
    try:
        # 2. worktree: a new one, or (--resume, a rework) the one still waiting from this ticket's last run
        st = read_state(tid)
        # a plan whose confirmation found no PD brain last time: go on from the kept branch
        pick_up = (args.plan_from_state and st.get("kept") and st.get("base") and wt_dir.exists()
                   and git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0)
        done_tasks = int(st.get("tasks_done") or 0) if pick_up else 0
        pending = (int(st.get("pending_task") or 0), st.get("pending_base") or "") if pick_up else (0, "")
        # the task that paused for more paths: worked again, but reviewed from its own base so pre-pause commits count
        paused = (int(st.get("need_task") or 0), st.get("need_base") or "") if pick_up else (0, "")
        if args.resume or pick_up:
            if not wt_dir.exists() or not st.get("base"):
                raise Failure("failed", "nothing to rework: the waiting worktree of ticket %d is gone" % tid)
            base = st["base"]
            created = True
            log("%s in %s (branch %s)" % ("picking up after task %d" % done_tasks if pick_up else "reworking",
                                          wt_dir, branch))
            if pick_up and st.get("base_broken") and pending[1] in ("", base):
                # BASE_CHECK_v1: the stop was main's own failure, fixed there since: the kept work goes on from main
                new = sync_onto_main(repo, wt_dir, main_branch, base)
                pending, base = (pending[0], new if pending[1] else ""), new
        else:
            base, from_attic = new_worktree(args, repo, tid, branch, wt_dir)
            created = True
        result["base"] = base
        tasks = plan_tasks(args, st, paths)
        if args.resume or pick_up:
            transcript = list(st.get("transcript") or [])
        write_state(tid, phase="running", round=0, task=0, tasks_total=len(tasks), started=time.time(),
                    phase_since=time.time(), title=args.title, provider=provider, reviewer=reviewer,
                    paths=paths, gates=gates, main_branch=main_branch, base=base, branch=branch,
                    worktree=str(wt_dir), transcript=transcript, reason="", kept=False, tasks_done=done_tasks,
                    base_broken=False)

        def renew() -> None:
            try:
                ticket_call("renew", "--id", str(tid), "--token", token, "--actor", actor)
            except RuntimeError as e:
                raise Failure("failed", "author lease lost during the run", str(e))

        pd_chain = expert_chain(roster("default_character", ""), [{"provider": reviewer, "model": args.reviewer_model, "timeout": 0}]
                                ) if reviewer else []

        # 3. tasks in order; each: the expert works -> gates -> the PD confirms (up to --rounds)
        for tno, task in enumerate(tasks, 1):
            if tno <= done_tasks:
                continue
            writer_p = persona(task["role"])
            # the task whose work waited for a confirmation: straight to its gates and review, on its own base
            confirm_only = tno == pending[0] and bool(pending[1])
            if confirm_only:
                task_base = pending[1]
            elif tno == paused[0] and paused[1]:
                task_base = paused[1]
            elif tno == 1 and from_attic:   # the carried-over work is reviewed with this task
                task_base = base
            else:
                task_base = git(wt_dir, "rev-parse", "HEAD")[1]
            write_state(tid, pending_task=tno, pending_base=task_base)
            head_line = ("This is task %d of %d in the plan \"%s\". Do only this task.\n" % (tno, len(tasks), args.title)
                         if len(tasks) > 1 else "")
            brief = writer_prompt(tid, task["title"], branch, wt_dir, task["paths"], gates, head_line + task["instruction"],
                                  character_block(writer_p, reviewer_p, STAFF_RELATION), read_memory(task["role"]),
                                  task.get("reads"))
            lessons: List[str] = []
            feedback = ""
            chain = expert_chain(task["role"], [{"provider": provider, "model": args.model, "timeout": 0}])
            bi, last_brain = 0, None
            partner_report = ""
            base_checked: set = set()           # BASE_CHECK_v1: each failed gate is tried on the base once per task
            for rnd in range(1, args.rounds + 1):
                if rnd > 1 or tno > 1:
                    renew()
                skipped = []
                b = chain[bi]
                while not (confirm_only and rnd == 1):
                    b = chain[bi]
                    resume = rnd > 1 and b == last_brain and bool(PROVIDERS[b["provider"]].get("continue_argv"))
                    prompt = brief if rnd == 1 else retry_prompt(feedback, None if resume else brief)
                    timeout = b["timeout"] or args.timeout
                    write_state(tid, phase="writing", task=tno, round=rnd, brain=brain_label(b), phase_since=time.time(),
                                timeout_sec=timeout)
                    log("task %d/%d round %d: running %s (timeout %ds)..." % (tno, len(tasks), rnd, brain_label(b), timeout))
                    res = run_agent(b["provider"], wt_dir, prompt, timeout, resume=resume, model=b["model"])
                    result["agent"] = {k: res[k] for k in ("ok", "returncode", "elapsed_sec")}
                    log("%s finished in %ss (exit %s)" % (brain_label(b), res["elapsed_sec"], res["returncode"]))
                    if res["ok"]:
                        break
                    why = tail(res["stderr"] or res["stdout"], 5)
                    if unavailable(why, res["returncode"]) and bi + 1 < len(chain):
                        skipped.append(brain_label(b))
                        log("%s unavailable; next brain %s" % (brain_label(b), brain_label(chain[bi + 1])))
                        bi += 1
                        renew()
                        continue
                    if res["returncode"] == -1 and str(res["stderr"]).startswith("timed out"):
                        raise Failure("unavailable", "agent %s timed out after %ds" % (brain_label(b), timeout),
                                      tail(res["stdout"]))
                    if unavailable(why, res["returncode"]):      # the last brain could not work either: not a try
                        raise Failure("unavailable", "no brain could work (%s): %s" % (brain_label(b), why[:200]))
                    raise Failure("failed", "agent %s exited with %s" % (brain_label(b), res["returncode"]),
                                  tail(res["stderr"] or res["stdout"]))
                if not (confirm_only and rnd == 1):
                    last_brain = b
                    partner_report = report(res["stdout"])
                    line = {"task": tno, "round": rnd, "role": "writer", "name": writer_p["name"],
                            "text": said(res["stdout"]), "brain": brain_label(b)}
                    round_lessons = learned(res["stdout"])
                    if round_lessons:
                        line["learned"] = round_lessons
                        lessons += [x for x in round_lessons if x not in lessons]
                    if skipped:
                        line["skipped"] = skipped
                    transcript.append(line)
                partner_said = next((ln["text"] for ln in reversed(transcript)
                                     if ln.get("task") == tno and ln.get("role") == "writer"), "")
                asked = [] if confirm_only and rnd == 1 else need_paths(res["stdout"], task["paths"])
                if asked:   # the worker needs files outside its scope: keep the work, wait for the operator
                    commit_leftovers(wt_dir, b["provider"], tid)
                    write_state(tid, phase="needs_path", need_paths=asked, need_task=tno, need_base=task_base,
                                tasks_done=tno - 1, pending_task=0, pending_base="", transcript=transcript,
                                phase_since=time.time())
                    raise Failure("paused", "task %d needs %s" % (tno, ", ".join(x["path"] for x in asked)), keep=True)

                write_state(tid, phase="gates", transcript=transcript, phase_since=time.time())
                if commit_leftovers(wt_dir, b["provider"], tid):
                    log("committed changes the agent left uncommitted")
                gate_error = None
                try:
                    if not git(wt_dir, "rev-list", task_base + "..HEAD")[1]:
                        raise Failure("failed", "task %d made no change" % tno)
                    changed = check_scope(wt_dir, task_base, task["paths"])
                    if check_tiers(repo, changed, gated, retryable=True) >= 2 and not args.stop_before_merge:
                        log("the change touches Tier 2 paths: it will wait for the operator's merge")
                        args.stop_before_merge = True
                        result["tier"] = 2
                    renew()
                    run_gates(wt_dir, gates)
                except Failure as f:
                    gate = getattr(f, "gate", None)
                    if gate and gate not in base_checked:
                        base_checked.add(gate)
                        broken = base_fails(repo, task_base, gate, tid)
                        if broken is not None:
                            write_state(tid, base_broken=True)
                            raise Failure("base_broken", "gate fails without this work too: %s -- fix the base, then "
                                          "run again; the work is kept" % gate, broken, keep=True)
                    if not (f.retryable and reviewer):
                        raise
                    gate_error = f
                    log("task %d round %d: %s" % (tno, rnd, f.reason))

                if not reviewer:
                    if gate_error is None and remember(task["role"], lessons):
                        log("task %d: %d lesson(s) kept in %s's memory" % (tno, len(lessons), task["role"]))
                    break
                write_state(tid, phase="review", phase_since=time.time())
                _, diff, _ = git(wt_dir, "diff", task_base + "..HEAD")
                pd_block = character_block(reviewer_p, writer_p, PD_RELATION)
                rv, rb, rskipped = review_with_chain(
                    cross_chain(pd_chain, b, review_providers() if args.cross_review else []), wt_dir,
                    lambda prov: (doc_review_prompt if doc_lane else (lambda b, d: with_code_checklist(b)))(
                        review_prompt(tid, task["title"], task["instruction"], partner_said, diff, gate_error,
                                      pd_block, diff_limit(prov), partner_report), diff),
                    renew)
                verdict = "FAIL" if gate_error else rv["verdict"]
                advisory = doc_lane and gate_error is None
                transcript.append({"task": tno, "round": rnd, "role": "reviewer", "name": reviewer_p["name"],
                                   **({"advisory": True, "deleted": deleted_lines(diff)} if advisory else {}),
                                   "brain": brain_label(rb), **({"skipped": rskipped} if rskipped else {}),
                                   **({"same_provider": True} if rb["provider"] == b["provider"] else {}),
                                   "text": rv["say"], "verdict": verdict, "fix": rv["fix"], "raw": rv["raw"]})
                log("task %d round %d: review %s" % (tno, rnd, verdict))
                write_state(tid, transcript=transcript)
                if advisory and verdict != "PASS":
                    # DOC_LANE_v1: the review is advice; the operator decides with it on the card
                    doc_advice = "doc review %s (advice: %s)" % (verdict, (rv["fix"] or rv["say"])[:300])
                    log("task %d: %s" % (tno, doc_advice))
                    write_state(tid, tasks_done=tno, need_base="", doc_advice=doc_advice)
                    break
                if verdict == "PASS":
                    if remember(task["role"], lessons):
                        log("task %d: lesson(s) kept in %s's memory" % (tno, task["role"]))
                    write_state(tid, tasks_done=tno, need_base="")
                    break
                if rnd == args.rounds:
                    if gate_error:
                        raise gate_error
                    raise Failure("gate_failed", "task %d: review FAIL after %d round(s)" % (tno, rnd), rv["fix"])
                feedback = "\n".join(x for x in (
                    "Gate failure: %s\n%s" % (gate_error.reason, gate_error.detail[-2000:]) if gate_error else "",
                    "Your producer says: %s" % rv["say"] if rv["say"] else "",
                    "Requested fixes:\n%s" % rv["fix"] if rv["fix"] else "") if x)
        result["rounds"] = rnd
        result["changed"] = check_scope(wt_dir, base, paths)

        # 4. land, or wait for the operator
        verdict = (" " + doc_advice if doc_advice else " review PASS") if reviewer else ""
        if args.stop_before_merge:
            head = git(wt_dir, "rev-parse", "HEAD")[1]
            try:
                ticket_call("await-merge", "--id", str(tid), "--token", token, "--actor", actor, "--note",
                            "branch %s at %s (%s,%s round %d)" % (branch, head[:7], provider, verdict, rnd))
            except RuntimeError as e:
                raise Failure("failed", "could not hand the ticket in for merge", str(e))
            result.update(outcome="awaiting_merge", head=head)
            log("ticket #%d awaits the operator's merge: worktree_runner.py merge --ticket %d" % (tid, tid))
        else:   # landing now: onto main, checked there once more when main moved (LAND_RETRY_v1)
            base, head = land(repo, wt_dir, main_branch, branch, base, gates,
                              on_rebase=lambda b: write_state(tid, base=b))
            result.update(merged=True, head=head, base=base)
    except Failure as f:
        release_failed(tid, token, f, provider, actor, result)
        if f.keep and created:
            result["kept"] = True
            write_state(tid, kept=True)
    finally:
        keep = created and not result["merged"] and (args.keep or result.get("kept")
                                                     or result.get("outcome") == "awaiting_merge")
        if created and not keep:
            cleanup_worktree(repo, branch, wt_dir, attic="" if result["merged"] else attic_ref(tid))
            log("worktree and branch removed" if result["merged"] else "worktree removed; branch head kept at %s"
                % attic_ref(tid))
        if result["merged"]:
            drop_attic(repo, tid)
        elif keep:
            log("kept %s (branch %s)" % (wt_dir, branch))

    if result["merged"]:
        close_done(tid, token, actor, "merged %s via worktree (%s,%s round %d)"
                   % (result["head"][:7], provider, verdict, result["rounds"]), result)

    saved = save_transcript(tid, args.title, transcript)
    result["transcript"] = transcript
    result["transcript_file"] = str(saved) if saved else None
    return record_and_report(repo, tid, provider, args.title, result, args.json, transcript)


def cmd_merge(args) -> int:
    """Land a ticket that `run --stop-before-merge` left awaiting the operator. Running this is the operator's
    word (relayed to the ticket with merge-go) unless --token says it was already given."""
    repo, tid = CHATBOT_REPO, args.ticket
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
