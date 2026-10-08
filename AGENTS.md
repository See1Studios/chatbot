# AGENTS.md — engine development (dev build only)

This file is for agents that change the engine code in this repo: an external CLI (Claude Code, Codex, Gemini,
Grok, …), a delegated worker in a worktree, or the PE chat agent doing engine work. It is not part of the shipped
product. How the chat agent talks to users is the shipped charter (`templates/workspace/AGENTS.md`), not this file.

Talk to the operator in Korean. Write agent-facing documents in plain English.

The code lives in `engine/`. Paths in tickets and commits are repo-relative (`engine/session.py`); names in
`CODEMAP.md` and `RULES.md` are relative to `engine/` (`session.py`).

## Your role

You own the architecture. The operator is the client and may ask without development context.

- Check each request against the goals (`VISION.md`, `docs/plans/INDEX.md`). If it fits, build it.
- If it does not fit, or bends the architecture, do not build it as asked. Say why in plain Korean and offer an
  aligned alternative or a change to the goal. The operator decides. Never comply or refuse silently.
- If the goal is unclear, ask.
- Look for prior art before you build anything.

## Start here

1. `~/AGENTS.md`: host law. It wins over this file.
2. This file.
3. `CODEMAP.md`: which files to change.
4. `docs/plans/INDEX.md`: plan status. Open only the plans you need.
5. `HISTORY.md`, the top: recent work.
6. When needed: `RULES.md` (conventions, rules, release, the propagation ledger), `ARCHITECTURE.md`, `OPERATIONS.md`
   (repair, restart, logs).

## How to make a change

1. Start from the operator's words or an approved ticket. Claim the paths:
   `python3 engine/tools/ticket_quick.py start --title "[<plan id>] ..." --paths a,b --actor <your role id>`.
   The actor is a role id such as `claude-code`, never a character's name.
2. An external CLI works in a git worktree, not in the shared main tree: restarts and other agents use the main tree.
3. Change only the claimed paths. Need another file: `ticket-quick widen --id <n> --paths <file>`.
4. Run `engine/run-tests.sh` and read the result before you commit. A live chat agent runs `--fast` and the modules for
   its files instead of the whole suite.
5. Commit only your paths. Conventional Commits. Trailers: `Plan: <plan>/<item>` when `docs/plans/` changes,
   `Ticket: #<n>`. A feat/fix/refactor/perf commit carries its test, or a `No-Test: <why>` line. Author: a live chat
   session commits as `PE`; an external CLI names itself (`git -c user.name="Claude Code" ...`).
6. Land with `git merge --ff-only`, check the commit is on main, then `ticket-quick done --id <n>`. Chain these
   with `&&`.
7. A Python module changed: the server needs a restart through `engine/chatbot-ctl.sh`, only when the operator is idle or
   agrees. A `static/` change needs only a browser reload.
8. Notable work: one block at the top of `HISTORY.md`.

## Rules you must not break

The full list, each with the test that enforces it, is `RULES.md`.

- Never `--no-verify`. Install the hooks once per clone: `git config core.hooksPath .githooks`.
- Data paths only through `host_config.py`. Tests never touch an install's data.
- No provider names in common code. Provider rules live in `providers/adapter_<name>.py` only.
- Character names are display values, never ids, keys or rule subjects.
- The engine decides what code can settle. Results never depend on language or on the model's wording.
- Dev and shipped instructions never mix. The shipped build never touches engine code.
- Every code file has a row in `CODEMAP.md` before it lands.
- A new rule lands with its enforcer in `RULES.md`, or says `manual` and why.
- Push and deploy: `~/AGENTS.md`. No `.bak-*` files.

## Where facts live

One home per fact; everywhere else, link to it.

| Fact | Home |
|---|---|
| Host law | `~/AGENTS.md` |
| Engine rules, conventions, numbers | this file, `RULES.md` |
| Code map | `CODEMAP.md` |
| Architecture, protection tiers | `ARCHITECTURE.md`, `protected_paths.json` |
| Running, repair, logs | `OPERATIONS.md` |
| Chat agent behaviour | `templates/workspace/AGENTS.md` (both builds); dev build adds `templates/dev-workspace/DEV-CHARTER.md` and `roles/dev/` |
| Data paths, ports, env | `engine/host_config.py` |
| What a new install starts with | `templates/workspace/`, `templates/workspace-manifest.json` |
| Per-install settings | `$CHATBOT_DATA/host.env` (options: `templates/host.env.example`) |
| Plan status / item progress | `docs/plans/INDEX.md` / tickets (`python3 engine/tickets.py list`) |
| Base baseline tools and skills | `engine/characters.py` (`BASE_TOOLS`), `engine/instructions.py` (`BASE_SKILLS`) |
| Role packs and team arrangements | `workspace/roles/`, `workspace/team.json` |
| Change record | git; `HISTORY.md` is the work diary |
| Provider contracts | `engine/providers/adapter_<name>.py` |

Agent memories hold preferences only, never facts this repo records.
