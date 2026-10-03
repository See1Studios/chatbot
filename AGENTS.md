# AGENTS.md — engine development (services/chatbot, Private Engine)

The one entry for **any agent that changes this repository**: an external CLI (Claude Code, Grok, Gemini, Codex …), a
worker the delegation runner starts in a worktree, or the PE chat agent when it works on code. `CLAUDE.md` and
`GEMINI.md` here only point to this file. Reply to the user in Korean unless told otherwise.

Not in scope here: how the PE chat agent talks and behaves at runtime. That charter is `data/workspace/AGENTS.md`
(injected into the chat agent). Its conventions — e.g. ending replies with `<!--choices: … -->` button lines — are
**for the PE chat UI only**; do not adopt them elsewhere.

## Your role: architecture owner, not a yes-man

The operator is the client and may ask without development context. You own the architecture and the fit with the
project's goals (`docs/CONCEPT.md` direction, active plans in `docs/plans/INDEX.md`, the rules below).

- Before building, check the request against those goals. If it fits, go ahead.
- If it does not fit, or would bend the architecture (SSOT, core/layer boundaries, provider neutrality, plan order),
  do not build it as asked. Say why in plain Korean, then offer one of: (a) an aligned alternative that meets the
  need behind the request, or (b) a proposal to change the goal or plan, which the operator decides. Never comply
  silently and never refuse silently.
- When the goal behind a request is unclear, ask for it instead of guessing.
- A shortcut that breaks a rule needs an explicit operator decision, recorded in the plan's decision table (later
  `docs/decisions/`).

## Start order

1. `~/AGENTS.md` — host law (DiskStation). It wins over this file.
2. This file — SSOT map, code map, rules.
3. `docs/plans/INDEX.md` — plan status; open only the plans you need. Procedure: `docs/plans/plan-execution-workflow.md`.
4. `docs/DEVLOG.md` top — recent work.
5. The target files. Minimal patch.

## SSOT map (one home per fact; elsewhere, link)

| Fact | Home |
|---|---|
| Host operations law | `~/AGENTS.md` |
| Engine development rules, code map | this file |
| PE chat agent behaviour | `data/workspace/AGENTS.md` (+ role packs `data/workspace/roles/<role>/`; engine-work rules only in `roles/dev/`) |
| Architecture: layers, adapters, plugin layer, ST split | `docs/ARCHITECTURE.md` |
| Data paths, ports, env | `host_config.py` |
| Shipped workspace defaults (charter, roles, tools, skills a new install starts with) | `templates/workspace/` + `templates/workspace-manifest.json` (what ships, what stays dev-only) |
| Per-install settings (edition, host plugin on/off, web root, ports) | `$CHATBOT_DATA/host.env`, read by `chatbot-ctl.sh` (options: `templates/host.env.example`) |
| Plan status | `docs/plans/INDEX.md` |
| Plan item progress | tickets (`tickets.py`, `python3 tickets.py list`) |
| Decisions | `docs/decisions/` (planned, pew/H); until then the plan's decision table |
| Change record | git + `CHANGELOG.md` (planned); `docs/DEVLOG.md` is the work diary |
| Protected paths, tiers | `protected_paths.json`, `evolution.py` |
| Provider contracts | `providers/adapter_<name>.py` only — never copied into docs, charters or cards |

Agent-private memories (Claude memory, Hermes, …) hold preferences only, not facts this repo already records.

## Code map (where to edit)

Fix the row before adding a file. New module names take a group prefix (`session_`, `adapter_`, …). A new code folder
goes into `protected_paths.json`.

| Task | Files |
|---|---|
| Paths, ports, env, token thresholds | `host_config.py` |
| Providers (CLI/HTTP), accounts | `providers/`: `adapters.py` (registry, `get_adapter`), `adapter_base.py`, `adapter_<agy\|claude\|grok\|codex\|openai>.py`, `accounts.py`, `account_login.py`; config `data/providers.json` |
| Session life, spawn, lock | `session.py`; running a turn (send, steer, the turn, `/btw`, interrupt, successor) `session_turn.py`; what a session shows (public view, tool lines, log, artifacts, handover summary) `session_view.py` (both mixins of `AgentSession`) |
| Turn watchdogs (QUOTA_FAILFAST, SILENT_HANG) | `turn_watchdog.py` (mixin of `AgentSession`) |
| Session lookup / weights, `/btw` / standby pool | `session_registry.py` / `session_weights.py` / `standby_pool.py` |
| HTTP routes | `server.py` (route tables `GET_ROUTES`…`DELETE_ROUTES`: one row per endpoint, in match order; host routes), handlers by domain `route_sessions.py` / `route_accounts.py` / `route_files.py`, matching `route_table.py`; route helpers `card_upload.py` (card import), `character_art.py` (avatar/stage/sprites, placeholder fallback), `chat_upload.py` (files attached to a message), `emotion.py` (emotion SSE), `preview_guard.py`, `origin_guard.py` |
| Artifacts / media | `artifact_manager.py` / `media_handler.py` |
| Workspace status / tool log format | `workspace_status.py` / `tool_format.py` |
| MCP server / core tools (memory, observation, ticket) / NAS host plugin | `mcp_server.py` / `mcp_core.py` / `nas_mcp_host.py`; a call's arguments in the shape the tool reads (names, wrappers, text arrays, actions) `mcp_args.py` (server name `nas` is a provider config key: do not rename); which session made a tool call `mcp_caller.py` (host side `session.caller_session`: the connection's process ancestry, never a model argument) |
| Instruction bundle | `instructions.py` (+ `session.py::AgentSession._send_direct`) |
| Characters, cards, lorebook | name changes carried to cards, sheets, lorebooks and older talk `character_names.py`; `characters.py` (art resolution `art_file`, placeholders `static/placeholders/`), `identity.py`; card import `tools/st_import.py`, export `tools/st_export.py`; data `data/workspace/characters/<id>/`; summon wizard `summon_api.py` (`GET /api/summon`, `POST /api/characters/summon`, `POST /api/characters/*/regenerate`), steps `engine_data/summon_steps.json`, page `static/app-summon.js` |
| Relationship memory | `memory_relationship.py` (private-bundle slots; `characters/<id>/relationship.md`) |
| Private mode | `private_engine.py` (`RENDER_PROTOCOL`, Grok overlay, tension) + `engine_data/private_tension_{defaults,gemini,grok}.json`; items (given or used) and affection `items.py` + `engine_data/affection.json` (catalog `<workspace>/items.json`, pictures `<workspace>/items/<id>.webp` else `static/placeholders/item.webp`, state `characters/<id>/state.json`) |
| Safety guards | `content_guard.py` + `engine_data/content_guards.json` |
| Event mailbox (work/system/private events to characters, rooms, schedules) | `events.py` (publish, per-session cursors); delivery before a turn `server._turn_notices`; work phases `delegation.publish_work_changes`; characters speaking first `event_react.py` (settings `<workspace>/events.json`, team tab); group rooms `room_chat.py` (`/api/rooms`, members speak from hidden `room` sessions); dialog records (a room's, two characters' `dm:<a>:<b>`), read positions, the turn's unread line `dialog_log.py`; the characters' `dialog` tool (list, read, send) `dialog_tool.py` — plan `docs/plans/character-events-and-rooms.md` |
| Delegation | `delegation.py`, `mcp_server.py` `delegate`, `tools/worktree_runner.py` (review prompt, checklists and verdict reading `tools/review_checklist.py`); a stalled worker is cut early `delegation_watch.py` (activity probe: `AgentAdapter.last_activity`) |
| Self-evolution core | `evolution.py`, `tickets.py`, `observations.py`, `memory_store.py` (core: stdlib + each other only) |
| Loop / write guards | `loop_guard.py`, `write_guard.py` |
| Logs | `obslog.py` (writes `logs/events.jsonl`), `logdigest.py` (reads it) |
| Service control | `chatbot-ctl.sh`, `ctl_proc.py`; first-run data folder `data_bootstrap.py` (from `templates/workspace/`) |
| UI | `static/`: `app.js` (globals, send, boot; only code that runs at load) + parts loaded first `app-{api,device,messages,turn,activity,evolution,status,sessions-tab,team,sse,session,characters,viewport}.js`; a coworker's turn in a work window `app-office.js` (inbox/E); `markdown.js` `artifacts.js` `slash.js` `model-picker.js` `theme.js` `index.html`; styles `chat-{base,log,composer,panes,responsive,features}.css` (cascade order) |
| Visual system | `DESIGN.md` + `.impeccable/design.json` |
| Tests | `tests/`; run with `./run-tests.sh` |

Python module change → restart (⚡소생) through `chatbot-ctl.sh` only. `static/` → browser reload.

## Naming

- Standing documents (one copy, always current, found by name) are UPPERCASE: repo root, `docs/` itself and `data/workspace/` itself — `README.md`, `AGENTS.md`, `docs/CONCEPT.md`, `docs/ARCHITECTURE.md`, `SKILL.md`, …
- Documents that accumulate are lower-kebab: `docs/plans/*.md` (`INDEX.md` excepted), `docs/devlog/YYYY-MM-DD.md`, observation logs.
- No snake_case document names. Pack files are UPPERCASE like their format's name: `SKILL.md`, `ROLE.md`, `PROCEDURE.md` (`characters.pack_file` still reads a pack's old lower-case names).
- Renaming a document: update every live link in the same change; leave history (DEVLOG, devlog/, archive/, ticket records) as written.

## Harness

- Default provider `agy`. Adapter registry `providers/adapters.py::AGENT_ADAPTERS`; a session restores its provider from `meta.json`. Provider- or harness-specific rules live in the adapter or `chatbot-ctl.sh`, nowhere else.
- Spawned agents see only `services/chatbot` and `<web root>/chat` (`host_config.py::ADD_DIRS`). Never add the home dir, `.hermes`, the whole web root or `services`; widen minimally and say why in DEVLOG.

## Work procedure

1. Start only from the operator's words or an approved ticket. External CLI: `python3 tools/ticket_quick.py start --title "[<plan id>] …" --paths a,b --actor <you>` (`~/bin/ticket-quick` points here). Always pass `--actor`: without it the actor is guessed from the parent process and every ticket lands as `unknown-cli`, so the ledger cannot say who did the work. The claim token cannot be recovered from the ticket store; it is kept in a private token file (`TOKEN_FILE=`), so `done`/`fail`/`renew` work without `--token`.
2. Change only the claimed paths. Need another file: `ticket-quick widen --id <n> --paths <file>` (checked like a claim, no new attempt). Never give the ticket up to open a new one: the old one stays open and only the operator can close it.
3. `./run-tests.sh` (all) or `./run-tests.sh test_x …`; green before commit. The commit hooks (`.githooks/`, install once per clone: `git config core.hooksPath .githooks`) rerun the guard tests and check the message.
4. Commit only your paths. Author = your agent (e.g. `git -c user.name="Claude Code" …`); Conventional Commits; trailers:
   ```
   Plan: <plan>/<item>
   Ticket: #<n>
   ```
5. Release the ticket (`ticket-quick done --id <n>`), note the commit. Host module changed → tell the operator ⚡ is needed; restart only when the operator is idle or agrees.
6. Notable work → one block at the top of `docs/DEVLOG.md`.

Push/deploy: `~/AGENTS.md`. Remote `See1Studios/chatbot` (private). No `.bak-*` files.

## Rule registry

Audience: **all** = every agent changing this repo (including the PE chat agent doing code work).
Enforcer: the test or gate that fails when the rule is broken; `manual` = none yet (planned one in brackets).

| Rule | Audience | Enforcer |
|---|---|---|
| Work starts from the operator's words or an approved, claimed ticket; claim names the paths | all | `test_tickets` (release refuses dirty paths); `test_unticketed_write` (PE sessions) |
| A delegated worker cannot change its own pass condition (guard tests, `run-tests.sh`) | all | `test_worktree_runner` |
| The shipped build never touches engine code: no `run_command`/`ticket`/`delegate`, file tools reach user data only; the edition is decided only by `host_config.EDITION` | all | `test_edition_boundary` |
| Guard tests green before commit (`./run-tests.sh --fast`); full suite before release | all | `.githooks/check_staged.py` (pre-commit); `test_worktree_runner` (runner gates: guards + related tests); `test_tickets` (done refused while guards fail) |
| Conventional Commits subject; `Plan:` trailer when `docs/plans/` changes | all | `test_githooks` (commit-msg hook) |
| `Ticket:` trailer, own author name | all | `test_githooks` (commit-msg: a feat/fix/refactor/perf commit without `Ticket: #n` is refused; on a `worktree/ticket-n` branch it is written in); author name: `test_githooks` (pre-commit: never a character's name; a live chat session commits as its brain) |
| A live chat session never lands a worker's branch on main, and ticket records keep role-id actors (landing is the operator's; records change only through `tickets.py`) | all | `test_githooks` (`.githooks/reference-transaction`; pre-commit refuses a staged ticket record with a persona actor) |
| A merged delegation leaves its line in `docs/DEVLOG.md` | all | `test_devlog_entry` (the runner writes it with the ticket record, `tools/devlog_entry.py`) |
| A ticket names the agent doing the work (`--actor`), never left to process detection | all | manual (nothing fails on a missing actor; the natural enforcer is a `test_tickets` ratchet refusing a new `unknown-cli` actor, with a baseline for the 290 existing tickets) |
| No secrets, `.env`, private memory or style references in commits | all | `test_githooks` (pre-commit hook) |
| Never `--no-verify`; hooks installed (`core.hooksPath=.githooks`) and executable | all | manual (run-tests.sh warns); backstops `test_worktree_runner`, `test_tickets` |
| Data paths only through `host_config` (`DATA_ENV` order; `tickets.py` mirrors it) | all | `test_data_paths` |
| Python module ≤ 80,000 bytes; Python function ≤ 80 lines; listed ceilings only go down | all | `test_file_sizes` |
| Page script or stylesheet ≤ 43,000 bytes; listed ceilings only go down | all | `test_page_scripts` |
| New code folder is protected | all | `test_code_layout` |
| Core modules import stdlib + each other only | all | `test_core_standalone` |
| No new pair of modules that import each other (top or inside a function); the known pairs only go away | all | `test_import_cycles` |
| No provider names in common code | all | `test_provider_neutrality` |
| Persona names/titles are display values, never ids or keys | all | `test_identity_wiring` |
| Injected instruction bundles within `bundle_budget.json` | all | `test_bundle_budget` |
| Every plan file has one INDEX row with a valid status | all | `test_plans_index` |
| DEVLOG stays small; old dates in `docs/devlog/` | all | `test_docs_budget` |
| Docs cite code as `path` or `path::symbol`, never line numbers; links resolve | all | `test_doc_refs` |
| `CLAUDE.md` / `GEMINI.md` only point here | all | `test_entrypoints` |
| Document names: standing UPPERCASE, accumulating lower-kebab, no snake_case | all | `test_doc_names` |
| Every registry row names an audience and a real enforcer | all | `test_rule_registry` |
| No new hardcoded Korean in engine/page code (i18n catalogs instead); mark intended lines `l10n-ok` | all | `test_ratchets` (`ratchet_baseline.json`) |
| No new host/persona identity (DiskStation, `/volume1`, Sphere, 실장님, 냥) in engine code outside the host plugin | all | `test_ratchets` |
| A tracked `data/workspace` file is classified in `templates/workspace-manifest.json`; `same` pairs stay byte-equal; the template names no host and no engine work | all | `test_workspace_template` |
| Observations only via `observations.add` / the `observation` tool | all | `test_observations` (shape) |
| Agent-facing text in English; human docs Korean | all | manual |
| Check each request against project goals; reject or propose re-scoping when it does not fit | all | manual (plan gate G2, DoR) |
| Look for prior art before building (`~/AGENTS.md` §0) | all | manual |
| Spawn-visible dirs stay minimal (`ADD_DIRS`) | all | manual |
| Engine-work rules for the chat agent live in the `dev` role pack, never the shared charter or another role's `role.md` | PE chat agent only | `test_dev_role` |
| Chat UI conventions (`<!--choices-->`, persona voice) | PE chat agent only | `templates/workspace/AGENTS.md` |

Add a rule here in the same change that adds its enforcer; a rule without one says `manual` and why.
