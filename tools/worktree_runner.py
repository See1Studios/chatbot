#!/usr/bin/env python3
"""worktree_runner.py: 티켓 하나를 Git Worktree 격리 환경에서 외부 CLI 에이전트에게 외주 주고,
검증 게이트와 리뷰어 캐릭터의 판정을 통과한 결과만 메인 브랜치에 fast-forward 병합한다
(docs/plans/multi-agent-worktree-delegation.md 마일스톤 2, §8 콤비 리뷰).

사용법:
  python3 tools/worktree_runner.py run --provider claude --title "작업 제목" \\
      --paths "tickets.py,tests/test_tickets.py" --prompt "지시문..." \\
      [--gate "python3 tests/test_tickets.py"] [--evidence log:fp:<fp>] [--timeout 1200] \\
      [--reviewer claude] [--reviewer-model haiku] [--rounds 2] [--no-review] [--keep] [--json]

  # 비정상 종료로 남은 worktree/브랜치 정리
  python3 tools/worktree_runner.py cleanup --ticket 61

흐름 (run):
  1. ticket-quick start  -> TICKET_ID, CLAIM_TOKEN (승인 + 클레임, 대상 경로가 메인에서 clean해야 함)
  2. git worktree add -b worktree/ticket-<ID> ~/.worktrees/chatbot/ticket-<ID> <main HEAD>
  3. 라운드 (최대 --rounds):
     a. 작성자(PERSONA.md 캐릭터)가 헤드리스로 작업·커밋하고 캐릭터 대사 한마디를 남긴다
        (미커밋 변경은 러너가 대신 커밋, 커밋 author는 제공자 신원)
     b. 기계 게이트: 커밋 존재 -> 범위(--paths 밖 변경 금지) -> 리스 연장 -> 메인 최신화(rebase)
        -> smoke + 중립성 가드 테스트 (DEFAULT_GATES) + --gate 명령들
     c. 리뷰어(PERSONA-reviewer.md 캐릭터)가 diff(또는 게이트 실패)를 보고 VERDICT + 대사 + 수정 요청
     d. 게이트 통과 + PASS면 종료, 아니면 수정 요청을 들고 다음 라운드
  4. 통과: 메인에서 git merge --ff-only -> ticket-quick done -> worktree/브랜치 정리
     탈락: 병합 없음 -> ticket-quick fail (gate_failed | failed) -> worktree/브랜치 정리 (--keep이면 보존)
  두 캐릭터의 주고받은 대사는 ~/.worktrees/chatbot/transcripts/에 남는다.

라이브 호스트는 재시작하지 않는다. 호스트 모듈이 바뀌었으면 유휴 확인 후 `chatbot-ctl.sh repair`로 배포한다.
표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

CHATBOT_REPO = Path(__file__).resolve().parents[1]
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
REVIEWER_ROLE = "reviewer"

# Provider registry: how to run each CLI headless as the worker (`argv`), as the worker again in the same
# conversation (`continue_argv`, only where it resumes by directory), as a tool-less reviewer (`review_argv`,
# the prompt follows `model_flag <model>` when a model is given), who it is on the ticket (role id) and in git.
PROVIDERS: Dict[str, Dict] = {
    "claude": {"argv": ["claude", "-p", "--dangerously-skip-permissions"],
               "continue_argv": ["claude", "-p", "-c", "--dangerously-skip-permissions"],
               "review_argv": ["claude", "-p", "--tools", ""], "model_flag": "--model", "review_model": "haiku",
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


# ----------------------------------------------------------------- personas

def persona(role: str = "") -> Dict[str, str]:
    """{name, label, voice, body} of the chatbot's own persona ("") or a second character (role id).
    Names are display values from the instance's identity files, never ids."""
    if str(CHATBOT_REPO) not in sys.path:
        sys.path.insert(0, str(CHATBOT_REPO))
    try:
        import identity
        ident = identity.get_identity(role)
        return {"name": ident["name"], "label": identity.self_label(role), "voice": ident["voice"],
                "body": identity.persona_body(role)}
    except Exception:
        return {"name": role or "worker", "label": role or "worker", "voice": "", "body": ""}


def character_block(me: Dict[str, str], partner: Dict[str, str]) -> str:
    lines = ["You are %s. Your partner is %s; you work as a comedy duo and talk to each other." % (me["label"], partner["name"])]
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


# ----------------------------------------------------------------- worktree

def cleanup_worktree(repo: Path, branch: str, wt_dir: Path) -> None:
    if wt_dir.exists():
        git(repo, "worktree", "remove", "--force", str(wt_dir))
        if wt_dir.exists():
            shutil.rmtree(wt_dir, ignore_errors=True)
    git(repo, "worktree", "prune")
    git(repo, "branch", "-D", branch)


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
        "Afterwards the runner runs: %s; then your partner reviews the diff. Only a branch that passes both is merged."
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
    parts += ["Your partner sent the branch back. Fix it, commit again, same rules as before.",
              feedback, LINE_RULE]
    return "\n".join(parts)


def said(text: str) -> str:
    """The in-character line after the last `---` of an agent's output (or its last lines)."""
    lines = (text or "").strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).strip()[:500]
    return "\n".join(lines[-2:]).strip()[:500]


def agent_env(provider: str) -> Dict[str, str]:
    name, email = PROVIDERS[provider]["author"]
    return dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)


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
        code, out, err = run_cmd(["sh", "-c", cmd], cwd=wt_dir, timeout=GATE_TIMEOUT)
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
    if not m:
        out["fix"] = out["fix"] or "The review had no readable VERDICT line."
    return out


def review_prompt(tid: int, title: str, instruction: str, partner_said: str, diff: str,
                  gate_error: Optional[Failure], character: str) -> str:
    parts = [character, "",
             "Your partner just worked on ticket #%d (%s). The task was:" % (tid, title), instruction[:2000], "",
             "Your partner said: %s" % (partner_said or "(nothing)"), ""]
    if gate_error:
        parts += ["The automatic gate FAILED, so the verdict is FAIL: %s" % gate_error.reason,
                  gate_error.detail[-3000:], ""]
    else:
        parts += ["The automatic gates (tests, scope) passed."]
    if len(diff) > DIFF_LIMIT:
        diff = diff[:DIFF_LIMIT] + "\n... (diff truncated)"
    parts += ["Diff of the branch:", "```diff", diff or "(empty)", "```", "",
              "Judge whether the change does the task correctly and safely within its scope. Reply in exactly this form:",
              "VERDICT: PASS or VERDICT: FAIL",
              "SAY: one to three short sentences in character, spoken to your partner",
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
    code, out, err = run_cmd(argv + [prompt], cwd=wt_dir, timeout=REVIEW_TIMEOUT)
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
    writer_p, reviewer_p = persona(), persona(REVIEWER_ROLE)
    actor = PROVIDERS[provider]["actor"]

    # 1. ticket
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

        # 3. rounds: writer -> gates -> reviewer
        brief = writer_prompt(tid, args.title, branch, wt_dir, paths, gates, args.prompt,
                              character_block(writer_p, reviewer_p))
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
            log("round %d: running %s (timeout %ds)..." % (rnd, provider, args.timeout))
            res = run_agent(provider, wt_dir, prompt, args.timeout, resume=rnd > 1)
            result["agent"] = {k: res[k] for k in ("ok", "returncode", "elapsed_sec")}
            log("%s finished in %ss (exit %s)" % (provider, res["elapsed_sec"], res["returncode"]))
            if not res["ok"]:
                raise Failure("failed", "agent %s exited with %s" % (provider, res["returncode"]),
                              tail(res["stderr"] or res["stdout"]))
            transcript.append({"round": rnd, "role": "writer", "name": writer_p["name"], "text": said(res["stdout"])})

            if commit_leftovers(wt_dir, provider, tid):
                log("committed changes the agent left uncommitted")
            gate_error = None
            try:
                _, commits, _ = git(wt_dir, "rev-list", base + "..HEAD")
                if not commits:
                    raise Failure("failed", "the agent made no change")
                _, changed, _ = git(wt_dir, "diff", "--name-only", base + "..HEAD")
                result["changed"] = changed.splitlines()
                outside = [f for f in result["changed"] if not in_scope(f, paths)]
                if outside:
                    raise Failure("gate_failed", "changes outside the ticket's paths: %s" % ", ".join(outside[:10]),
                                  retryable=True)
                renew()
                _, main_head, _ = git(repo, "rev-parse", main_branch)
                _, merge_base, _ = git(wt_dir, "merge-base", "HEAD", main_head)
                if merge_base != main_head:
                    log("%s moved to %s; rebasing the branch before the gates" % (main_branch, main_head[:8]))
                    code, _, err = git(wt_dir, "rebase", main_head)
                    if code != 0:
                        git(wt_dir, "rebase", "--abort")
                        raise Failure("gate_failed", "branch does not rebase cleanly onto %s" % main_branch, tail(err))
                    base = main_head
                run_gates(wt_dir, gates)
            except Failure as f:
                if not (f.retryable and reviewer):
                    raise
                gate_error = f
                log("round %d: %s" % (rnd, f.reason))

            if not reviewer:
                break
            _, diff, _ = git(wt_dir, "diff", base + "..HEAD")
            rv = run_review(reviewer, args.reviewer_model, wt_dir,
                            review_prompt(tid, args.title, args.prompt, transcript[-1]["text"], diff, gate_error,
                                          character_block(reviewer_p, writer_p)))
            verdict = "FAIL" if gate_error else rv["verdict"]
            transcript.append({"round": rnd, "role": REVIEWER_ROLE, "name": reviewer_p["name"], "text": rv["say"],
                               "verdict": verdict, "fix": rv["fix"]})
            log("round %d: review %s" % (rnd, verdict))
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

        # 4. merge
        code, cur, _ = git(repo, "symbolic-ref", "--short", "HEAD")
        if cur != main_branch:
            raise Failure("failed", "main repository switched from %s to %s during the run" % (main_branch, cur))
        code, _, err = git(repo, "merge", "--ff-only", branch)
        if code != 0:
            raise Failure("failed", "fast-forward merge into %s refused (it moved or local changes are in the way)"
                          % main_branch, tail(err))
        _, head, _ = git(repo, "rev-parse", "HEAD")
        result.update(merged=True, head=head)
        log("merged into %s at %s" % (main_branch, head[:8]))
    except Failure as f:
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
    finally:
        if created and not (args.keep and not result["merged"]):
            cleanup_worktree(repo, branch, wt_dir)
            log("worktree and branch removed")
        elif created:
            log("kept %s (branch %s) for inspection" % (wt_dir, branch))

    if result["merged"]:
        verdict = " review PASS" if reviewer else ""
        try:
            ticket_call("done", "--id", str(tid), "--token", token, "--actor", actor,
                        "--note", "merged %s via worktree (%s,%s round %d)" % (result["head"][:7], provider, verdict,
                                                                               result["rounds"]))
            result["outcome"] = "done"
            log("ticket #%d done" % tid)
        except RuntimeError as e:
            result["outcome"] = "merged-ticket-open"
            print("[!] merged, but the ticket could not be closed: %s" % e, file=sys.stderr)
        log("the live host was not restarted; deploy host-module changes with `chatbot-ctl.sh repair` once idle")

    saved = save_transcript(tid, args.title, transcript)
    result["transcript"] = transcript
    result["transcript_file"] = str(saved) if saved else None
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for ln in transcript:
            print("%s%s: %s" % (ln["name"], " [%s]" % ln["verdict"] if ln.get("verdict") else "", ln["text"] or "…"))
        print("RESULT=%s TICKET_ID=%d MERGED=%s" % (result.get("outcome"), tid, "yes" if result["merged"] else "no"))
    return 0 if result.get("outcome") == "done" else 1


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
    p.add_argument("--timeout", type=int, default=1200, help="Agent timeout per round in seconds (max %d)" % MAX_AGENT_TIMEOUT)
    p.add_argument("--reviewer", choices=sorted(PROVIDERS), help="Provider for the reviewer character (default: --provider)")
    p.add_argument("--reviewer-model", default="", help="Reviewer model (default: the provider's cheap review model)")
    p.add_argument("--rounds", type=int, default=2, help="Writer/reviewer rounds before giving up (default 2)")
    p.add_argument("--no-review", action="store_true", help="Merge on the mechanical gates alone")
    p.add_argument("--keep", action="store_true", help="Keep the worktree and branch when the attempt fails")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")

    c = sub.add_parser("cleanup", help="Remove a leftover worktree and branch of a ticket")
    c.add_argument("--ticket", type=int, required=True)

    args = parser.parse_args(argv)
    return cmd_run(args) if args.command == "run" else cmd_cleanup(args)


if __name__ == "__main__":
    sys.exit(main())
