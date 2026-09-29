#!/usr/bin/env python3
"""ticket-quick: one-line ticket open/claim/release for agents working outside the live chat (plan pew/K).

  python3 tools/ticket_quick.py start --title "[<plan id>] ..." --paths a,b [--evidence log:fp:<fp> ...]
  python3 tools/ticket_quick.py done --id <N> [--token <T>] [--note "..."]
  python3 tools/ticket_quick.py fail --id <N> [--token <T>] --outcome gate_failed --note "..."
  python3 tools/ticket_quick.py renew --id <N> [--token <T>]
  python3 tools/ticket_quick.py widen --id <N> --paths c,d [--token <T>]   # add files to the ticket you hold
  python3 tools/ticket_quick.py claim --id <N> [--paths a,b]           # an approved ticket whose files were held
  python3 tools/ticket_quick.py await-merge --id <N> [--token <T>] --note "branch ..."   # Tier 2
  python3 tools/ticket_quick.py merge-go --id <N>                      # relays the operator's word; new token

`~/bin/ticket-quick` is only a pointer to this file. The data directory comes from host_config.DATA.
The claim token is also kept in a 0600 file (CLAIMS_DIR) so a lost terminal line does not strand the lease;
commands that need it read that file when --token is left out, and done/fail/await-merge delete it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import evolution  # noqa: E402
import tickets  # noqa: E402
from host_config import DATA as DATA_DIR  # noqa: E402

# Per-user, outside the data folder (spawned agents see the repo and data; they must not find others' tokens).
CLAIMS_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "chatbot-claims"


# --- claim token file -------------------------------------------------------------------------------------

def _token_path(tid) -> Path:
    tag = hashlib.sha1(str(Path(DATA_DIR).resolve()).encode()).hexdigest()[:8]   # one install's ids only
    return CLAIMS_DIR / ("%s-%d.token" % (tag, int(tid)))


def save_token(tid, token) -> Path:
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CLAIMS_DIR, 0o700)
    p = _token_path(tid)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.chmod(p, 0o600)
    return p


def load_token(tid) -> str:
    try:
        return _token_path(tid).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def forget_token(tid):
    try:
        _token_path(tid).unlink()
    except OSError:
        pass


def _token(args) -> str:
    tok = (getattr(args, "token", "") or "").strip() or load_token(args.id)
    if not tok:
        print("Error: no claim token for ticket #%d: pass --token, or claim it from this user account "
              "(the token file is %s)" % (args.id, _token_path(args.id)), file=sys.stderr)
        sys.exit(1)
    return tok


# --- actor ------------------------------------------------------------------------------------------------

def _ensure_candidate_evidence() -> str:
    """Record a 'manual' candidate row and return its evidence ref (only when no real evidence was given)."""
    candidates_file = Path(DATA_DIR) / "workspace" / "skill-observations" / evolution.CANDIDATES_NAME
    candidates_file.parent.mkdir(parents=True, exist_ok=True)
    epoch = round(time.time(), 3)
    entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "epoch": epoch, "sid": "quick-ticket-cli",
             "provider": "external", "signal": "manual", "detail": {"user": "quick-ticket CLI invocation"}}
    with open(candidates_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return "candidate:%s" % epoch


# ACTOR_ATTRIBUTION_v1: who runs this, from the process ancestry (OS facts), unless --actor says.
# Only executable names count (argv[0] and the script an interpreter runs), never the rest of a command
# line: a `bash -c "<script>"` parent carries arbitrary text.
_ACTOR_EXECS = {"claude": "claude-code", "grok": "grok", "codex": "codex", "hermes": "hermes",
                "agy": "agy", "gemini": "gemini-cli", "cursor-agent": "cursor",
                "opencode": "opencode", ".opencode": "opencode"}
_INTERPRETERS = ("python", "python3", "node", "bash", "sh")


def _exec_names(argv):
    names = []
    if argv:
        names.append(os.path.basename(argv[0]))
        if names[0].split(".")[0] in _INTERPRETERS or names[0].startswith("python"):
            rest = [a for a in argv[1:] if not a.startswith("-")]
            if rest:
                names.append(os.path.basename(rest[0]))
    return names


def _is_chat_server(pid, argv, names) -> bool:
    if "server.py" not in names:
        return False
    if any("services/chatbot" in a or str(ROOT) in a for a in argv):
        return True
    try:
        return Path(os.readlink("/proc/%d/cwd" % pid)).resolve() == ROOT
    except OSError:
        return False


def detect_actor(max_hops: int = 16) -> str:
    pid, agent = os.getppid(), None
    for _ in range(max_hops):
        if pid <= 1:
            break
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            with open("/proc/%d/stat" % pid, encoding="utf-8") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        names = _exec_names(argv)
        if agent is None:
            for n in names:
                if n in _ACTOR_EXECS:
                    agent = _ACTOR_EXECS[n]
                    break
        if _is_chat_server(pid, argv, names):
            return "chat-agent:%s" % (agent or "?")   # the chat's live agent using its shell (role id)
        pid = ppid
    return agent or "unknown-cli"


def _actor(args) -> str:
    return (getattr(args, "actor", "") or "").strip() or detect_actor()


# --- commands ---------------------------------------------------------------------------------------------

def _paths(text):
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def cmd_start(args):
    title = args.title.strip()
    paths = _paths(args.paths)
    target = args.target.strip() if args.target else (", ".join(paths) if paths else "external-task")
    if not title:
        print("Error: --title is required", file=sys.stderr)
        sys.exit(1)
    # Real evidence first (event:<sid>#<line>, candidate:<epoch>, log:fp:<fp>, log:rid:<rid> --
    # see `chatbot-ctl.sh logs`); only without it fall back to a manual candidate marker.
    evidence_refs = [e.strip() for e in (args.evidence or []) if e.strip()] or [_ensure_candidate_evidence()]
    actor = _actor(args)
    try:
        t, merged = tickets.propose(DATA_DIR, title, target, evidence_refs, actor=actor)
        tid = t["id"]
        print("[1/3] Ticket #%d proposed (%s)." % (tid, "merged" if merged else "new"))
    except Exception as e:
        print("Error proposing ticket: %s" % e, file=sys.stderr)
        sys.exit(1)
    # LEASE_SCOPE_v1: the ticket is the caller's own; the chat does not pick it up
    try:
        t = tickets.set_owner(DATA_DIR, tid, actor)
    except Exception as e:
        print("Note: ticket #%d not marked as yours (%s)." % (tid, e), file=sys.stderr)
    try:
        if t["status"] == "proposed":
            t = tickets.approve(DATA_DIR, tid, operator=tickets.OPERATOR_CONFIRMED,
                                on_behalf="%s ticket-quick (operator's instruction)" % actor)
            print("[2/3] Ticket #%d approved." % tid)
        else:
            print("[2/3] Ticket #%d already in state: %s." % (tid, t["status"]))
    except Exception as e:
        print("Error approving ticket: %s" % e, file=sys.stderr)
        sys.exit(1)
    _claim(tid, paths, actor, "[3/3] ")


def _claim(tid, paths, actor, step=""):
    try:
        claim_res = tickets.claim(DATA_DIR, tid, paths=paths, actor=actor)
    except Exception as e:
        print("Error claiming ticket: %s" % e, file=sys.stderr)
        if "author lock is held" in str(e):
            print("Ticket #%d stays yours and waits (approved). When those files are free:\n"
                  "  ticket-quick claim --id %d%s" % (tid, tid, (" --paths " + ",".join(paths)) if paths else ""),
                  file=sys.stderr)
        sys.exit(1)
    token = claim_res["token"]
    paths = claim_res["ticket"].get("paths") or paths
    saved = save_token(tid, token)
    print("%sTicket #%d claimed successfully!" % (step, tid))
    print("-" * 50)
    print("TICKET_ID=%d" % tid)
    print("ACTOR=%s" % actor)
    print("CLAIM_TOKEN=%s" % token)
    print("TOKEN_FILE=%s" % saved)
    print("PATHS=%s" % ",".join(paths))
    print("-" * 50)
    print("To finish when git is clean (the token is read from TOKEN_FILE):")
    print("  ticket-quick done --id %d" % tid)


def cmd_claim(args):
    """Claim an approved ticket again (e.g. one `start` opened while its files were held)."""
    paths = _paths(args.paths)
    if not paths:
        try:
            paths = tickets.get(DATA_DIR, args.id).get("paths") or []
        except Exception:
            paths = []
    _claim(args.id, paths, _actor(args))


def cmd_done(args):
    try:
        tickets.release(DATA_DIR, args.id, _token(args), outcome="done", text=args.note or "completed",
                        actor=_actor(args))
    except Exception as e:
        print("Error releasing ticket as done: %s" % e, file=sys.stderr)
        sys.exit(1)
    forget_token(args.id)
    print("Ticket #%d marked DONE successfully!" % args.id)


def cmd_fail(args):
    try:
        res = tickets.release(DATA_DIR, args.id, _token(args), outcome=args.outcome,
                              text=args.note or args.outcome, actor=_actor(args))
    except Exception as e:
        print("Error releasing ticket as %s: %s" % (args.outcome, e), file=sys.stderr)
        sys.exit(1)
    forget_token(args.id)
    print("Ticket #%d released as %s (now %s)." % (args.id, args.outcome.upper(), res["ticket"]["status"]))
    if res.get("advice"):
        print("ADVICE=%s" % res["advice"])


def cmd_renew(args):
    """Extend the author lease the caller already holds (no new attempt is counted)."""
    token = _token(args)
    # claim() with a lost lease would start a new attempt; renewing must not do that.
    if not tickets.holds(DATA_DIR, args.id, token):
        print("Error renewing lease: you do not hold the author lease for ticket %d "
              "(missing, wrong or expired token)" % args.id, file=sys.stderr)
        sys.exit(1)
    try:
        res = tickets.claim(DATA_DIR, args.id, token=token, actor=_actor(args))
    except Exception as e:
        print("Error renewing lease: %s" % e, file=sys.stderr)
        sys.exit(1)
    print("Ticket #%d lease renewed for %ss." % (args.id, res["expires_in_sec"]))


def cmd_widen(args):
    """Add files to the ticket the caller holds, instead of giving it up and opening another (TICKET_WIDEN_v1)."""
    try:
        res = tickets.widen(DATA_DIR, args.id, _token(args), _paths(args.paths), actor=_actor(args))
    except Exception as e:
        print("Error widening ticket: %s" % e, file=sys.stderr)
        sys.exit(1)
    print("Ticket #%d paths: %s" % (args.id, ", ".join(res["ticket"].get("paths") or [])))
    print("ADDED=%s" % ",".join(res["added"]))


def cmd_await_merge(args):
    try:
        tickets.await_merge(DATA_DIR, args.id, _token(args), text=args.note, actor=_actor(args))
    except Exception as e:
        print("Error handing in for merge: %s" % e, file=sys.stderr)
        sys.exit(1)
    forget_token(args.id)
    print("Ticket #%d is AWAITING_MERGE (lease released)." % args.id)


def cmd_merge_go(args):
    actor = _actor(args)
    try:
        res = tickets.merge_go(DATA_DIR, args.id, operator=tickets.OPERATOR_CONFIRMED,
                               on_behalf="%s ticket-quick (operator's instruction)" % actor, actor=actor)
    except Exception as e:
        print("Error letting ticket #%d land: %s" % (args.id, e), file=sys.stderr)
        sys.exit(1)
    saved = save_token(args.id, res["token"])
    print("Ticket #%d may land; lease handed back." % args.id)
    print("CLAIM_TOKEN=%s" % res["token"])
    print("TOKEN_FILE=%s" % saved)


# LIVE_AGENT_NO_TICKET_QUICK: this wrapper approves on the operator's behalf, which is for agents the
# operator runs by hand (Claude Code, codex ...). The chat's live agent asks through its own tools instead:
# `delegate` for file changes, `ticket` (propose -> the operator approves -> claim) for the rest. Told
# from the process ancestry, not from --actor, so a flag cannot opt out.
def _refuse_live_chat_agent(command):
    if command in ("start", "claim", "merge-go") and detect_actor().startswith("chat-agent"):
        print("Error: ticket-quick is for agents outside the live chat. From the chat, use the `delegate` tool "
              "for file changes (Tier 0 starts at once; Tier 2 waits for the operator's approval), or the "
              "`ticket` tool to propose work for the operator to approve.", file=sys.stderr)
        sys.exit(3)


def build_parser():
    parser = argparse.ArgumentParser(prog="ticket-quick", description="Quick ticket helper for external agents & CLI")
    sub = parser.add_subparsers(dest="command")
    actor_help = "Who does the work (default: detected from the parent processes)"
    token_help = "Claim token (default: the token file written at claim)"

    p = sub.add_parser("start", help="Propose, approve, and claim a ticket in 1 step")
    p.add_argument("--title", required=True, help="Ticket title")
    p.add_argument("--paths", default="", help="Comma-separated repo-relative paths (e.g. server.py,session.py)")
    p.add_argument("--target", default="", help="Ticket target (defaults to paths or external-task)")
    p.add_argument("--actor", default="", help=actor_help)
    p.add_argument("--evidence", action="append", default=[],
                   help="Evidence ref, repeatable: event:<sid>#<line> | candidate:<epoch> | log:fp:<fp> | log:rid:<rid>. "
                        "Without it a 'manual' candidate is recorded as a placeholder.")

    p = sub.add_parser("claim", help="Claim an approved ticket (one start opened while its files were held)")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--paths", default="", help="Comma-separated repo-relative paths (default: the ticket's)")
    p.add_argument("--actor", default="", help=actor_help)

    p = sub.add_parser("done", help="Release a claimed ticket as done")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--token", default="", help=token_help)
    p.add_argument("--note", default="completed", help="Completion note")
    p.add_argument("--actor", default="", help=actor_help)

    p = sub.add_parser("fail", help="Release a claimed ticket as gate_failed, failed or abandoned")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--token", default="", help=token_help)
    p.add_argument("--outcome", default="failed", choices=["gate_failed", "failed", "abandoned", "unavailable", "paused"])
    p.add_argument("--note", default="", help="Why it failed")
    p.add_argument("--actor", default="", help=actor_help)

    p = sub.add_parser("renew", help="Extend the author lease you hold")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--token", default="", help=token_help)
    p.add_argument("--actor", default="", help=actor_help)

    p = sub.add_parser("widen", help="Add files to the ticket you hold (not: give it up and open another)")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--paths", required=True, help="Comma-separated repo-relative files to add")
    p.add_argument("--token", default="", help=token_help)
    p.add_argument("--actor", default="", help=actor_help)

    p = sub.add_parser("await-merge", help="Hand reviewed work in to wait for the operator's merge")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--token", default="", help=token_help)
    p.add_argument("--note", default="", help="Where the work waits (e.g. the branch)")
    p.add_argument("--actor", default="", help=actor_help)

    p = sub.add_parser("merge-go", help="Relay the operator's word to let an awaiting_merge ticket land")
    p.add_argument("--id", type=int, required=True, help="Ticket ID")
    p.add_argument("--actor", default="", help=actor_help)
    return parser


COMMANDS = {"start": cmd_start, "claim": cmd_claim, "done": cmd_done, "fail": cmd_fail, "renew": cmd_renew,
            "widen": cmd_widen,
            "await-merge": cmd_await_merge, "merge-go": cmd_merge_go}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in COMMANDS:
        parser.print_help()
        sys.exit(1)
    _refuse_live_chat_agent(args.command)
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
