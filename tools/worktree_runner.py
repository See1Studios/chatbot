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
     a. 스태프(PERSONA-staff.md 캐릭터)가 헤드리스로 작업·커밋하고 캐릭터 대사 한마디를 남긴다
        (미커밋 변경은 러너가 대신 커밋, 커밋 author는 제공자 신원)
     b. 기계 게이트: 커밋 존재 -> 범위(--paths 밖 변경 금지) -> 리스 연장 -> 메인 최신화(rebase)
        -> smoke + 중립성 가드 테스트 (DEFAULT_GATES) + --gate 명령들
     c. PD(PERSONA.md 캐릭터, 챗봇 자신)가 diff(또는 게이트 실패)를 보고 확인: VERDICT + 대사 + 수정 요청
     d. 게이트 통과 + PASS면 종료, 아니면 수정 요청을 들고 다음 라운드
  4. 통과: 메인에서 git merge --ff-only -> ticket-quick done -> worktree/브랜치 정리
     --stop-before-merge(Tier 2): 병합 대신 ticket-quick await-merge (리스 해제), worktree/브랜치는 남긴다
     탈락: 병합 없음 -> ticket-quick fail (gate_failed | failed) -> worktree/브랜치 정리 (--keep이면 보존)
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
from typing import Dict, List, Optional

CODE_DIR = Path(__file__).resolve().parents[1]      # where the host modules this tool imports live
CHATBOT_REPO = CODE_DIR                              # the repository it works on
WORKTREE_BASE = Path.home() / ".worktrees" / "chatbot"
TICKET_QUICK = [sys.executable, str(Path.home() / "bin" / "ticket-quick")]
# smoke plus the repo-wide guards (design doc §7-9, NAME_NEUTRAL_v1); a few seconds each
DEFAULT_GATES = ["python3 tests/smoke.py", "python3 tests/test_provider_neutrality.py", "python3 tests/test_identity_wiring.py"]
LEASE_TTL_SEC = 1800          # tickets.LEASE_TTL_SEC: renewed before and after each agent run
MAX_AGENT_TIMEOUT = 1500
REVIEW_TIMEOUT = 300
GATE_TIMEOUT = 600
TAIL_LINES = 30
DIFF_LIMIT = 15000
WORKER_ROLE = "staff"          # PERSONA-staff.md does the work; the chatbot's own persona (the PD) confirms it
TICKETS_REL = "data/workspace/skill-observations/tickets"   # tickets.tickets_dir(), repo-relative

# Provider registry: how to run each CLI headless as the worker (`argv`), as the worker again in the same
# conversation (`continue_argv`, only where it resumes by directory), as a tool-less reviewer (`review_argv`,
# the prompt follows `model_flag <model>` when a model is given), who it is on the ticket (role id) and in git.
PROVIDERS: Dict[str, Dict] = {
    "claude": {"argv": ["claude", "-p", "--dangerously-skip-permissions"],
               "continue_argv": ["claude", "-p", "-c", "--dangerously-skip-permissions"],
               "review_argv": ["claude", "-p", "--tools", ""], "model_flag": "--model", "review_model": "sonnet",
               "actor": "claude-code", "author": ("Claude Code", "noreply@anthropic.com")},
    "codex": {"argv": ["codex", "exec", "-s", "workspace-write"],
              "review_argv": ["codex", "exec", "-s", "read-only"], "model_flag": "-m",
              "actor": "codex", "author": ("Codex", "codex@localhost")},
    "agy": {"argv": ["agy", "-p", "--dangerously-skip-permissions"],
            "review_argv": ["agy", "-p", "--mode", "plan"], "model_flag": "--model",
            "actor": "agy", "author": ("agy", "agy@localhost")},
    "grok": {"argv": ["grok", "--always-approve", "-p"],
             "review_argv": ["grok", "-p"], "model_flag": "-m",
             "actor": "grok", "author": ("Grok", "grok@localhost")},
}


class Failure(Exception):
    """The attempt stops here. outcome is the ticket release outcome: gate_failed | failed.
    retryable: another round with the writer could fix it."""

    def __init__(self, outcome: str, reason: str, detail: str = "", retryable: bool = False):
        super().__init__(reason)
        self.outcome, self.reason, self.detail, self.retryable = outcome, reason, detail, retryable


def log(msg: str) -> None:
    print("[*] " + msg, file=sys.stderr, flush=True)


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 120,
            env: Optional[Dict[str, str]] = None) -> tuple:
    try:
        res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, errors="replace", timeout=timeout, check=False)
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
        out += [w for w in words if not w.startswith("-") and "/" in w and (repo / w).is_file() and w not in out]
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


def commit_ticket_record(repo: Path, tid: int, provider: str, subject: str) -> Optional[str]:
    """Commit the ticket's own record in the main repository, and only it, so main is left clean
    without an operator step. Returns the short sha, or None when there is nothing to commit."""
    rel = "%s/%04d.json" % (TICKETS_REL, tid)
    if not (repo / rel).exists() or not git(repo, "status", "--porcelain", "--", rel)[1]:
        return None
    name, email = PROVIDERS[provider]["author"]
    git(repo, "add", "--", rel)
    code, _, err = git(repo, "-c", "user.name=" + name, "-c", "user.email=" + email,
                       "commit", "-m", subject, "--", rel)
    if code != 0:
        print("[!] ticket record not committed: %s" % tail(err, 5), file=sys.stderr)
        return None
    return git(repo, "rev-parse", "--short", "HEAD")[1]


# ----------------------------------------------------------------- worktree

def cleanup_worktree(repo: Path, branch: str, wt_dir: Path) -> None:
    if wt_dir.exists():
        git(repo, "worktree", "remove", "--force", str(wt_dir))
        if wt_dir.exists():
            shutil.rmtree(wt_dir, ignore_errors=True)
    git(repo, "worktree", "prune")
    git(repo, "branch", "-D", branch)


STAFF_RELATION = "You are a staff member; %s is your producer (PD), who confirms your work before it ships."
PD_RELATION = "You are the producer (PD); %s is your staff member, who did this work. You confirm it or send it back."

LINE_RULE = ("At the very end of your final message, write a line containing only `---`, then one or two short "
             "sentences in character, spoken to your partner, about what you did.")


def writer_prompt(tid: int, title: str, branch: str, wt_dir: Path, paths: List[str], gates: List[str],
                  instruction: str, character: str) -> str:
    return "\n".join([
        "You are working on ticket #%d (%s) in an isolated git worktree of the services/chatbot repository." % (tid, title),
        "Working directory: %s (branch %s). Stay inside it: do not modify %s or any other path, "
        "do not push, do not restart or deploy services." % (wt_dir, branch, CHATBOT_REPO),
        "Change only these repo-relative paths: %s. Changes anywhere else fail the scope gate." % ", ".join(paths),
        "When done, commit your work on this branch (git add <files> && git commit -m '...'); "
        "the author identity is already set.",
        "Afterwards the runner runs: %s; then your producer confirms the diff. Only a branch that passes both is merged."
        % "; ".join(gates),
        "",
        character,
        LINE_RULE,
        "",
        "Task:",
        instruction,
    ])


def retry_prompt(feedback: str, full: Optional[str]) -> str:
    """Next round: the partner's requests. `full` repeats the whole brief when the CLI cannot resume."""
    parts = [full, "", "--- next round ---"] if full else []
    parts += ["Your producer sent the branch back. Fix it, commit again, same rules as before.",
              feedback, LINE_RULE]
    return "\n".join(parts)


def said(text: str) -> str:
    """The in-character line after the last `---` of an agent's output (or its last lines)."""
    lines = (text or "").strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).strip()[:500]
    return "\n".join(lines[-2:]).strip()[:500]


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


def run_agent(provider: str, wt_dir: Path, prompt: str, timeout: int, resume: bool = False) -> Dict:
    spec = PROVIDERS[provider]
    argv = spec["continue_argv"] if resume and spec.get("continue_argv") else spec["argv"]
    if not shutil.which(argv[0]):
        return {"ok": False, "returncode": None, "elapsed_sec": 0, "stdout": "", "stderr": "%s CLI not installed" % argv[0]}
    t0 = time.time()
    code, out, err = run_cmd(argv + [prompt], cwd=wt_dir, timeout=timeout, env=agent_env(provider))
    return {"ok": code == 0, "returncode": code, "elapsed_sec": round(time.time() - t0, 1), "stdout": out, "stderr": err}


def commit_leftovers(wt_dir: Path, provider: str, tid: int) -> bool:
    """Commit what the agent changed but did not commit (e.g. a sandbox kept it out of the git dir)."""
    _, status, _ = git(wt_dir, "status", "--porcelain")
    if not status:
        return False
    name, email = PROVIDERS[provider]["author"]
    git(wt_dir, "add", "-A")
    code, _, err = git(wt_dir, "-c", "user.name=" + name, "-c", "user.email=" + email,
                       "commit", "-m", "ticket #%d: changes the agent left uncommitted" % tid)
    if code != 0:
        raise Failure("failed", "could not commit the agent's leftover changes", err)
    return True


def run_gates(wt_dir: Path, gates: List[str]) -> None:
    for cmd in gates:
        log("gate: %s" % cmd)
        code, out, err = run_cmd(["sh", "-c", cmd], cwd=wt_dir, timeout=GATE_TIMEOUT, env=clean_env())  # runs the agent's code
        if code != 0:
            raise Failure("gate_failed", "gate failed: %s (exit %s)" % (cmd, code), tail(out + "\n" + err),
                          retryable=True)


# ------------------------------------------------------------------- review

_VERDICT = re.compile(r"^\s*\**VERDICT\**\s*:\s*\**\s*(PASS|FAIL)\b", re.M | re.I)
_SECTION = re.compile(r"^\s*\**(SAY|FIX)\**\s*:\s*", re.M | re.I)


def parse_review(text: str) -> Dict[str, str]:
    """VERDICT / SAY / FIX out of the reviewer's reply. No readable verdict counts as FAIL (fail closed)."""
    m = _VERDICT.search(text or "")
    out = {"verdict": m.group(1).upper() if m else "FAIL", "say": "", "fix": ""}
    marks = list(_SECTION.finditer(text or ""))
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[mk.group(1).lower()] = text[mk.end():end].strip()[:3000]
    if not out["say"] and text:
        # No SAY label (a small model often drops it): the prose after the verdict line, before any FIX.
        body = text[m.end():] if m else text
        fix = _SECTION.search(body)
        body = body[:fix.start()] if fix and fix.group(1).upper() == "FIX" else body
        lines = [ln.strip().strip("*").strip() for ln in body.splitlines()]
        out["say"] = " ".join(ln for ln in lines if ln)[:500]
    if not m:
        out["fix"] = out["fix"] or "The review had no readable VERDICT line."
    out["raw"] = (text or "")[:1500]
    return out


def review_prompt(tid: int, title: str, instruction: str, partner_said: str, diff: str,
                  gate_error: Optional[Failure], character: str) -> str:
    parts = [character, "",
             "Your staff member just worked on ticket #%d (%s). The task was:" % (tid, title), instruction[:2000], "",
             "Your staff member said: %s" % (partner_said or "(nothing)"), ""]
    if gate_error:
        parts += ["The automatic gate FAILED, so the verdict is FAIL: %s" % gate_error.reason,
                  gate_error.detail[-3000:], ""]
    else:
        parts += ["The automatic gates (tests, scope) passed."]
    if len(diff) > DIFF_LIMIT:
        diff = diff[:DIFF_LIMIT] + "\n... (diff truncated)"
    parts += ["Diff of the branch:", "```diff", diff or "(empty)", "```", "",
              "As the producer, confirm the work: does the change do the task correctly and safely within its scope? "
              "Reply in exactly this form:",
              "VERDICT: PASS or VERDICT: FAIL",
              "SAY: one to three short sentences in character, spoken to your staff member",
              "FIX: only when FAIL, concrete numbered fixes (file, function, what)"]
    return "\n".join(parts)


def run_review(provider: str, model: str, wt_dir: Path, prompt: str) -> Dict[str, str]:
    spec = PROVIDERS[provider]
    argv = list(spec["review_argv"])
    model = model or spec.get("review_model") or ""
    if model:
        argv += [spec["model_flag"], model]
    if not shutil.which(argv[0]):
        raise Failure("failed", "reviewer CLI %s not installed" % argv[0])
    code, out, err = run_cmd(argv + [prompt], cwd=wt_dir, timeout=REVIEW_TIMEOUT, env=clean_env())
    if code != 0:
        raise Failure("failed", "reviewer %s exited with %s" % (provider, code), tail(err or out))
    return parse_review(out)


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


def release_failed(tid: int, token: str, f: Failure, provider: str, actor: str, result: Dict) -> None:
    result.update(outcome=f.outcome, reason=f.reason, detail=f.detail)
    print("[!] %s" % f.reason, file=sys.stderr)
    if f.detail:
        print(f.detail, file=sys.stderr)
    try:
        vals = ticket_call("fail", "--id", str(tid), "--token", token, "--outcome", f.outcome,
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
    record = commit_ticket_record(repo, tid, provider, "%s -- %s" % (subject, title[:80]))
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

def cmd_run(args) -> int:
    repo = CHATBOT_REPO
    provider = args.provider
    reviewer = None if args.no_review else (args.reviewer or provider)
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    gates = DEFAULT_GATES + list(args.gate or [])
    result: Dict = {"provider": provider, "reviewer": reviewer, "paths": paths, "merged": False}
    transcript: List[Dict] = []

    if not paths:
        print("Error: --paths is required (the scope gate and the ticket's ship gate use it)", file=sys.stderr)
        return 2
    if args.timeout > MAX_AGENT_TIMEOUT:
        print("Error: --timeout above %ds would outlive the %ds author lease" % (MAX_AGENT_TIMEOUT, LEASE_TTL_SEC),
              file=sys.stderr)
        return 2
    if args.rounds < 1:
        print("Error: --rounds must be at least 1", file=sys.stderr)
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
    writer_p, reviewer_p = persona(WORKER_ROLE), persona()
    actor = PROVIDERS[provider]["actor"]

    # 1. ticket: one the caller already claimed (--ticket/--token), or a new one on the operator's instruction
    if args.ticket and args.token:
        tid, token = args.ticket, args.token
    elif args.ticket or args.token:
        print("Error: --ticket and --token go together (a ticket the caller has claimed)", file=sys.stderr)
        return 2
    else:
        try:
            vals = ticket_call("start", "--title", args.title, "--paths", ",".join(paths),
                               "--actor", actor, *sum((["--evidence", e] for e in args.evidence), []))
            tid, token = int(vals["TICKET_ID"]), vals["CLAIM_TOKEN"]
        except (RuntimeError, KeyError, ValueError) as e:
            print("Error: ticket start failed: %s" % e, file=sys.stderr)
            return 1
    branch, wt_dir = names(tid)
    result.update(ticket=tid, branch=branch, worktree=str(wt_dir))
    log("ticket #%d claimed (paths: %s)" % (tid, ", ".join(paths)))

    created = False
    try:
        # 2. worktree
        if wt_dir.exists() or git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0:
            raise Failure("failed", "%s or %s is left over from an earlier run; "
                          "inspect it, then `worktree_runner.py cleanup --ticket %d`" % (branch, wt_dir, tid))
        _, base, _ = git(repo, "rev-parse", "HEAD")
        WORKTREE_BASE.mkdir(parents=True, exist_ok=True)
        code, _, err = git(repo, "worktree", "add", "-b", branch, str(wt_dir), base)
        if code != 0:
            raise Failure("failed", "git worktree add failed", err)
        created = True
        result["base"] = base
        log("worktree %s on %s (base %s)" % (wt_dir, branch, base[:8]))
        write_state(tid, phase="running", round=0, started=time.time(), phase_since=time.time(),
                    title=args.title, provider=provider, reviewer=reviewer,
                    paths=paths, gates=gates, main_branch=main_branch, base=base, branch=branch,
                    worktree=str(wt_dir), transcript=[])

        # 3. rounds: writer -> gates -> reviewer
        brief = writer_prompt(tid, args.title, branch, wt_dir, paths, gates, args.prompt,
                              character_block(writer_p, reviewer_p, STAFF_RELATION))
        can_resume = bool(PROVIDERS[provider].get("continue_argv"))
        feedback = ""
        def renew() -> None:
            try:
                ticket_call("renew", "--id", str(tid), "--token", token, "--actor", actor)
            except RuntimeError as e:
                raise Failure("failed", "author lease lost during the run", str(e))

        for rnd in range(1, args.rounds + 1):
            if rnd > 1:
                renew()
            prompt = brief if rnd == 1 else retry_prompt(feedback, None if can_resume else brief)
            write_state(tid, phase="writing", round=rnd, phase_since=time.time())
            log("round %d: running %s (timeout %ds)..." % (rnd, provider, args.timeout))
            res = run_agent(provider, wt_dir, prompt, args.timeout, resume=rnd > 1)
            result["agent"] = {k: res[k] for k in ("ok", "returncode", "elapsed_sec")}
            log("%s finished in %ss (exit %s)" % (provider, res["elapsed_sec"], res["returncode"]))
            if not res["ok"]:
                raise Failure("failed", "agent %s exited with %s" % (provider, res["returncode"]),
                              tail(res["stderr"] or res["stdout"]))
            transcript.append({"round": rnd, "role": "writer", "name": writer_p["name"], "text": said(res["stdout"])})

            write_state(tid, phase="gates", transcript=transcript, phase_since=time.time())
            if commit_leftovers(wt_dir, provider, tid):
                log("committed changes the agent left uncommitted")
            gate_error = None
            try:
                _, commits, _ = git(wt_dir, "rev-list", base + "..HEAD")
                if not commits:
                    raise Failure("failed", "the agent made no change")
                result["changed"] = check_scope(wt_dir, base, paths)
                if check_tiers(repo, result["changed"], gated, retryable=True) >= 2 and not args.stop_before_merge:
                    log("the change touches Tier 2 paths: it will wait for the operator's merge")
                    args.stop_before_merge = True
                    result["tier"] = 2
                renew()
                base = sync_onto_main(repo, wt_dir, main_branch, base)
                write_state(tid, base=base)
                run_gates(wt_dir, gates)
            except Failure as f:
                if not (f.retryable and reviewer):
                    raise
                gate_error = f
                log("round %d: %s" % (rnd, f.reason))

            if not reviewer:
                break
            write_state(tid, phase="review", phase_since=time.time())
            _, diff, _ = git(wt_dir, "diff", base + "..HEAD")
            rv = run_review(reviewer, args.reviewer_model, wt_dir,
                            review_prompt(tid, args.title, args.prompt, transcript[-1]["text"], diff, gate_error,
                                          character_block(reviewer_p, writer_p, PD_RELATION)))
            verdict = "FAIL" if gate_error else rv["verdict"]
            transcript.append({"round": rnd, "role": "reviewer", "name": reviewer_p["name"], "text": rv["say"],
                               "verdict": verdict, "fix": rv["fix"], "raw": rv["raw"]})
            log("round %d: review %s" % (rnd, verdict))
            write_state(tid, transcript=transcript)
            if verdict == "PASS":
                break
            if rnd == args.rounds:
                if gate_error:
                    raise gate_error
                raise Failure("gate_failed", "review FAIL after %d round(s)" % rnd, rv["fix"])
            feedback = "\n".join(x for x in (
                "Gate failure: %s\n%s" % (gate_error.reason, gate_error.detail[-2000:]) if gate_error else "",
                "Your partner says: %s" % rv["say"] if rv["say"] else "",
                "Requested fixes:\n%s" % rv["fix"] if rv["fix"] else "") if x)
        result["rounds"] = rnd

        # 4. land, or wait for the operator
        verdict = " review PASS" if reviewer else ""
        if args.stop_before_merge:
            head = git(wt_dir, "rev-parse", "HEAD")[1]
            try:
                ticket_call("await-merge", "--id", str(tid), "--token", token, "--actor", actor, "--note",
                            "branch %s at %s (%s,%s round %d)" % (branch, head[:7], provider, verdict, rnd))
            except RuntimeError as e:
                raise Failure("failed", "could not hand the ticket in for merge", str(e))
            result.update(outcome="awaiting_merge", head=head)
            log("ticket #%d awaits the operator's merge: worktree_runner.py merge --ticket %d" % (tid, tid))
        else:
            result.update(merged=True, head=ff_merge(repo, main_branch, branch))
    except Failure as f:
        release_failed(tid, token, f, provider, actor, result)
    finally:
        keep = created and not result["merged"] and (args.keep or result.get("outcome") == "awaiting_merge")
        if created and not keep:
            cleanup_worktree(repo, branch, wt_dir)
            log("worktree and branch removed")
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
    if not st.get("provider") or st.get("phase") != "awaiting_merge":
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
        base = st["base"]
        new_base = sync_onto_main(repo, wt_dir, st["main_branch"], base)
        if new_base != base:  # the reviewed change now sits on a different main: check it again
            check_tiers(repo, check_scope(wt_dir, new_base, st["paths"]), gate_files(repo, st["gates"]), retryable=False)
            run_gates(wt_dir, st["gates"])
        result.update(merged=True, head=ff_merge(repo, st["main_branch"], branch))
    except Failure as f:
        release_failed(tid, token, f, provider, actor, result)
    finally:
        if result["merged"] or not args.keep:
            cleanup_worktree(repo, branch, wt_dir)
            log("worktree and branch removed")
    if result["merged"]:
        close_done(tid, token, actor, "merged %s on the operator's word (%s)" % (result["head"][:7], provider), result)
    return record_and_report(repo, tid, provider, title, result, args.json)


def cmd_cleanup(args) -> int:
    branch, wt_dir = names(args.ticket)
    cleanup_worktree(CHATBOT_REPO, branch, wt_dir)
    print("removed %s and branch %s (if they existed)" % (wt_dir, branch))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ticketed git-worktree delegation to a CLI agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="ticket -> worktree -> rounds of agent, gates, review -> ff-merge")
    p.add_argument("--provider", default="claude", choices=sorted(PROVIDERS))
    p.add_argument("--title", required=True, help="Ticket title")
    p.add_argument("--paths", required=True, help="Comma-separated repo-relative paths the agent may change")
    p.add_argument("--prompt", required=True, help="Instruction for the agent")
    p.add_argument("--gate", action="append", default=[], help="Extra gate command run in the worktree (repeatable); "
                                                               "the DEFAULT_GATES always run first")
    p.add_argument("--evidence", action="append", default=[], help="Evidence ref passed to ticket-quick (repeatable)")
    p.add_argument("--ticket", type=int, default=0, help="Work on this ticket, already claimed by the caller (with --token)")
    p.add_argument("--token", default="", help="The caller's claim token for --ticket")
    p.add_argument("--timeout", type=int, default=1200, help="Agent timeout per round in seconds (max %d)" % MAX_AGENT_TIMEOUT)
    p.add_argument("--reviewer", choices=sorted(PROVIDERS), help="Provider for the PD's confirmation (default: --provider)")
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
