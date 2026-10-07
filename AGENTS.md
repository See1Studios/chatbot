# AGENTS.md — engine development (services/chatbot, Private Engine)

The one entry for **any agent that changes this repository**: an external CLI (Claude Code, Grok, Gemini, Codex …), a
worker the delegation runner starts in a worktree, or the PE chat agent when it works on code. Tool-named entry files that
exist here (`CLAUDE.md`, `GEMINI.md`) only point to this file — do not invent new ones; keep them as short pointers.
**Speak with the developer (operator) in Korean. Agent-facing documents in English; operator-facing ones may be Korean.** (Chat-agent runtime voice and UI
conventions stay in `$CHATBOT_DATA/workspace/`; do not mix them into this map.)

Not in scope here: how the PE chat agent talks and behaves at runtime. That charter is `$CHATBOT_DATA/workspace/AGENTS.md`
(injected into the chat agent; this install symlinks it from `templates/dev-workspace/`). Its conventions — e.g. ending replies with `<!--choices: … -->` button lines — are
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
2. This file — SSOT map, code map, rule registry.
3. `docs/plans/INDEX.md` — plan status; open only the plans you need. Procedure: `docs/plans/plan-execution-workflow.md`.
4. `docs/DEVLOG.md` top — recent work.
5. On demand (not every turn): `docs/ARCHITECTURE.md`, `docs/CONVENTION.md`, `docs/STATE.md`.
6. The target files. Minimal patch.

## SSOT map (one home per fact; elsewhere, link)

| Fact | Home |
|---|---|
| Host operations law | `~/AGENTS.md` |
| Engine development rules, code map | this file |
| PE chat agent behaviour | `$CHATBOT_DATA/workspace/AGENTS.md`, one charter for both builds (source `templates/workspace/AGENTS.md`) + role packs `$CHATBOT_DATA/workspace/roles/<role>/`; dev build only: `DEV-CHARTER.md` (source `templates/dev-workspace/`), engine-work rules only in `roles/dev/` |
| Architecture: layers, adapters, plugin layer, ST split, module tiers | `docs/ARCHITECTURE.md` (governance section 7) |
| Engineering conventions (test pairing, size ceilings, timeouts, work banter) | `docs/CONVENTION.md` — numbers and detail live there; this file only registers them |
| Governance propagation ledger (active queue, drift backlog) | `docs/STATE.md` |
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
| Providers (CLI/HTTP), accounts | `providers/`: `adapters.py` (registry, `get_adapter`), `adapter_base.py`, `adapter_{agy,claude,grok,codex,openai}.py`, `accounts.py`, `account_login.py`; config `data/providers.json`; swap a saved agy login `tools/switch_account.py` |
| Session life, spawn, lock | `session.py`; running a turn (send, steer, the turn, `/btw`, interrupt, successor) `session_turn.py`; what a session shows (public view, tool lines, log, artifacts, handover summary) `session_view.py` (both mixins of `AgentSession`) |
| Turn watchdogs (QUOTA_FAILFAST, SILENT_HANG) | `turn_watchdog.py` (mixin of `AgentSession`) |
| Session lookup / weights, `/btw` / standby pool | `session_registry.py` / `session_weights.py` / `standby_pool.py` |
| HTTP routes | `server.py` (route tables `GET_ROUTES`…`DELETE_ROUTES`: one row per endpoint, in match order; host routes), handlers by domain `route_sessions.py` / `route_accounts.py` / `route_files.py`, matching `route_table.py`; route helpers `card_upload.py` (card import), `static_delivery.py` (revalidation, compression), `client_errors.py` (page errors to the host log), `push_manager.py` (Web Push keys, subscriptions), `character_art.py` (avatar/stage/sprites, placeholder fallback), `chat_upload.py` (files attached to a message), `emotion.py` (emotion SSE), `preview_guard.py`, `origin_guard.py` |
| Artifacts / media | `artifact_manager.py` / `media_handler.py` |
| Workspace status / tool log format | `workspace_status.py` / `tool_format.py` |
| MCP server / core tools (memory, observation, ticket) / NAS host plugin | `mcp_server.py` / `mcp_core.py` / `nas_mcp_host.py`; a call's arguments in the shape the tool reads (names, wrappers, text arrays, actions) `mcp_args.py` (server name `nas` is a provider config key: do not rename); tools an HTTP brain lacks: `web_tool.py` (`web`: read, search), `mcp_parity.py` (edit_file, find_files, skill); which session made a tool call `mcp_caller.py` (host side `session.caller_session`: the connection's process ancestry, never a model argument) |
| Instruction bundle | `instructions.py` (one layer list `LAYERS` -> `layer_texts` -> `build_instruction_bundle`, CONTEXT_LAYERS_v1; + `session.py::AgentSession._send_direct`) — plan `docs/plans/layered-context-architecture.md` |
| Characters, cards, lorebook | name changes carried to cards, sheets, lorebooks and older talk `character_names.py`; `characters.py` (art resolution `art_file`, placeholders `static/placeholders/`), `identity.py`; card import `tools/st_import.py`, export `tools/st_export.py`; card generation `card_prompt.py` (prompts), `card_parse.py` (reading the answer), `tools/card_gen.py`; art manager (slots, gallery, the one way a picture gets in) `art_manager.py`, art format check `tools/check_character_art.py`; data `$CHATBOT_DATA/workspace/characters/<id>/`; summon wizard `summon_api.py` (`GET /api/summon`, `POST /api/characters/summon`, `POST /api/characters/*/regenerate`), steps `engine_data/summon_steps.json`, page `static/app-summon.js` |
| Relationship memory | `memory_relationship.py` (private-bundle slots; `characters/<id>/relationship.md`) |
| Private mode | `private_engine.py` (`RENDER_PROTOCOL`, Grok overlay, tension); a work-room turn marked personal never becomes work material `personal_turn.py`; the note carried into the private room `threshold.py` + `engine_data/private_tension_{defaults,gemini,grok}.json`; items (given or used) and affection `items.py` + `engine_data/affection.json` (catalog `<workspace>/items.json`, pictures `<workspace>/items/<id>.webp` else `static/placeholders/item.webp`, state `characters/<id>/state.json`) |
| Safety guards | `content_guard.py` + `engine_data/content_guards.json` |
| Event mailbox (work/system/private events to characters, rooms, schedules) | `events.py` (publish, per-session cursors); delivery before a turn `server._turn_notices`; work phases `delegation.publish_work_changes`; characters speaking first `event_react.py` (settings `<workspace>/events.json`, team tab); group rooms `room_chat.py` (`/api/rooms`, members speak from hidden `room` sessions); dialog records (a room's, two characters' `dm:<a>:<b>`), read positions, the turn's unread line `dialog_log.py`; the characters' `dialog` tool (list, read, send, handoff) `dialog_tool.py`; a director's work handed to the director that owns it, started at the receiver's desk and reported back `dialog_handoff.py` (HANDOFF_v1, run by `event_react.loop`; a cut turn is sent again once, HANDOFF_RESTART_v1; cancelled by its directors with the tool or by the operator with `POST /api/handoffs/<id>/cancel`, HANDOFF_CANCEL_v1), its scenario drill on a sandbox host `tools/handoff_drill.py` (HANDOFF_DRILL_v1), the page's handoff cards `static/app-handoffs.js` (GET /api/handoffs, HANDOFF_BOARD_v1) — plan `docs/plans/character-events-and-rooms.md` |
| Delegation | `delegation.py`, `mcp_server.py` `delegate`, `tools/worktree_runner.py` (review prompt, checklists and verdict reading `tools/review_checklist.py`; a worker's report, line and LEARNED lessons `tools/worker_output.py`; each call's tokens `tools/run_usage.py`; a brain that cannot work, and one resting until its reset `tools/brain_limits.py` (BRAIN_LIMITS_v1); the merged run's DEVLOG line `tools/devlog_entry.py`); the run's talk goes into the expert and PD's dm, the card keeps the verdict `delegation.py::mirror_work_talk` (WORK_TALK_v1); a stalled worker is cut early `delegation_watch.py` (activity probe: `AgentAdapter.last_activity`) |
| Self-evolution core | `evolution.py`, `tickets.py`, `observations.py`, `memory_store.py`, `platform_compat.py` (OS differences in one place) — core: stdlib + each other only (`core_modules.json`); agents outside the chat open tickets with `tools/ticket_quick.py` |
| Loop / write / role guards | `loop_guard.py`; `write_guard.py` (an unticketed write stops the turn; TREE_WATCH_v1: the working tree compared at each turn's start and end, holds); `role_guard.py` (the tool server's per-caller scope and edition boundary; roles are equipped with skills, not fenced) |
| Logs | `obslog.py` (writes `logs/events.jsonl`), `logdigest.py` (reads it) |
| Service control | `chatbot-ctl.sh`, `ctl_proc.py`; first-run data folder `data_bootstrap.py` (from `templates/workspace/`); move a data folder `tools/migrate_user_data.py`; dev workspace link `tools/link_dev_workspace.py` |
| UI | `static/`: page words by key `app-i18n.js` (loaded before every part; catalogs `static/i18n/<lang>.json`, I18N_v1; the server's user-facing words go by key through `i18n.py`); `app.js` (globals, send, boot; only code that runs at load) + parts loaded first `app-{api,device,messages,turn,activity,evolution,status,sessions-tab,team,sse,session,characters,viewport}.js` (the status tab's usage report and quota `app-status-usage.js`, what went into the open conversation `app-status-context.js`); messenger shell `app-shell.js` (profile brains `app-shell-brain.js`, profile quota `app-shell-quota.js`, message menu `app-msgmenu.js`); how an answer reads `app-{blocks,stage,think,flow}.js`; composer extras `app-{attach,item,act-key,recall,retry,speech}.js`; group rooms `app-rooms.js`; art manager `app-art.js`; dev mode only `app-dev-delete.js`; a coworker's turn in a work window `app-office.js` (inbox/E); `markdown.js` (maps `markdown-map.js`) `artifacts.js` `slash.js` `model-picker.js` `theme.js` `service-log.js` (log tab) `sw.js` (PWA) `index.html`; character renderers `visual-adapter.js` + `visual-sprite-adapter.js`; styles `sphere-theme.css` then `chat-{base,log,composer,panes,responsive,features}.css` `art-manager.css` `rooms.css` `shell.css` (cascade order) |
| Visual system | `DESIGN.md` + `.impeccable/design.json` |
| Tests | `tests/`; run with `./run-tests.sh` (without bash: `tools/run_modules.py`) |

Python module change → restart (⚡소생) through `chatbot-ctl.sh` only. `static/` → browser reload.

## Naming

- Standing documents (one copy, always current, found by name) are UPPERCASE: repo root, `docs/` itself and `$CHATBOT_DATA/workspace/` itself — `README.md`, `AGENTS.md`, `docs/CONCEPT.md`, `docs/ARCHITECTURE.md`, `SKILL.md`, …
- Documents that accumulate are lower-kebab: `docs/plans/*.md` (`INDEX.md` excepted), `docs/devlog/YYYY-MM-DD.md`, observation logs.
- No snake_case document names. Pack files are UPPERCASE like their format's name: `SKILL.md`, `ROLE.md`, `PROCEDURE.md` (`characters.pack_file` still reads a pack's old lower-case names).
- Renaming a document: update every live link in the same change; leave history (DEVLOG, devlog/, archive/, ticket records) as written.

## Harness

- Default provider `agy`. Adapter registry `providers/adapters.py::AGENT_ADAPTERS`; a session restores its provider from `meta.json`. Provider- or harness-specific rules live in the adapter or `chatbot-ctl.sh`, nowhere else.
- Spawned agents see only `services/chatbot` and `<web root>/chat` (`host_config.py::ADD_DIRS`). Never add the home dir, `.hermes`, the whole web root or `services`; widen minimally and say why in DEVLOG.

## Work procedure

1. Start only from the operator's words or an approved ticket. External CLI: `python3 tools/ticket_quick.py start --title "[<plan id>] …" --paths a,b --actor <you>` (`~/bin/ticket-quick` points here). Always pass `--actor` (your role id, never a character's name): without it the actor is guessed from the parent processes, and when they name no agent the command records nothing. The claim token cannot be recovered from the ticket store; it is kept in a private token file (`TOKEN_FILE=`), so `done`/`fail`/`renew` work without `--token`.
2. Change only the claimed paths. Need another file: `ticket-quick widen --id <n> --paths <file>` (checked like a claim, no new attempt). Never give the ticket up to open a new one: the old one stays open and only the operator can close it.
3. `./run-tests.sh` (all) or `./run-tests.sh test_x …`; green before commit. A feat/fix/refactor/perf commit carries its test, or a `No-Test: <why>` trailer. The commit hooks (`.githooks/`, install once per clone: `git config core.hooksPath .githooks`) rerun the guard tests and check the message.
4. Commit only your paths. Author = the app: `PE` for a live chat session, whatever brain it runs on (the repo default; the brain goes in the `Co-Authored-By` trailer); an external CLI outside the chat names itself (e.g. `git -c user.name="Claude Code" …`); Conventional Commits; trailers:
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
| Work starts from the operator's words or an approved, claimed ticket; claim names the paths | all | `test_tickets` (release refuses dirty paths); `test_unticketed_write` (PE sessions: a visible unticketed write stops the turn, any other change to the tree is held) |
| A live chat agent and its subagents run the guards or named test modules, never the whole suite | PE chat agent only | `test_live_agent_suite` (`run-tests.sh` refuses when `CHATBOT_LIVE_AGENT` is set; unittest/pytest around the script is refused too) |
| A test run never gets an install's data: outside `run-tests.sh` a unittest/pytest process is pointed at the repo's `data/` | all | `test_live_agent_suite` (`host_config.test_run_outside_runner`, `tickets.py::_data_dir`) |
| A handoff chain from one request is at most two hops; a director has one open handoff at a time | PE chat agent only | `test_dialog_handoff` |
| A delegated worker cannot change its own pass condition (guard tests, `run-tests.sh`) | all | `test_worktree_runner` |
| The shipped build never touches engine code: no `run_command`/`ticket`/`delegate`, file tools reach user data only; the edition is decided only by `host_config.EDITION` | all | `test_edition_boundary` |
| Guard tests green before commit (`./run-tests.sh --fast`); full suite before release | all | `.githooks/check_staged.py` (pre-commit); `test_worktree_runner` (runner gates: guards + related tests); `test_tickets` (done refused while guards fail) |
| Conventional Commits subject; `Plan:` trailer when `docs/plans/` changes | all | `test_githooks` (commit-msg hook) |
| `Ticket:` trailer, own author name | all | `test_githooks` (commit-msg: a feat/fix/refactor/perf commit without `Ticket: #n` is refused; on a `worktree/ticket-n` branch it is written in); author name: `test_githooks` (pre-commit: never a character's name; a live chat session commits as the app `PE`) |
| A live chat session never lands a worker's branch on main (landing is the operator's) | all | `test_githooks` (`.githooks/reference-transaction`) |
| A merged delegation leaves its line in `docs/DEVLOG.md` | all | `test_devlog_entry` (the runner writes it with the ticket record, `tools/devlog_entry.py`) |
| A ticket names the agent doing the work (`--actor`), never `unknown-cli`; who-fields hold role ids, not persona names | all | `test_ticket_quick` (ticket-quick records nothing when neither `--actor` nor the parent processes name the agent); `test_tickets` (`tickets.py` refuses a non-role-id actor at write time). A romanized nickname (`nono`) passes the role-id shape: manual |
| No secrets, `.env`, private memory or style references in commits | all | `test_githooks` (pre-commit hook) |
| Never `--no-verify`; hooks installed (`core.hooksPath=.githooks`) and executable | all | manual (run-tests.sh warns); backstops `test_worktree_runner`, `test_tickets` |
| Data paths only through `host_config` (`DATA_ENV` order; `tickets.py` mirrors it) | all | `test_data_paths` |
| Python module ≤ 80,000 bytes; Python function ≤ 80 lines; listed ceilings only go down | all | `test_file_sizes` (numbers SSOT: `docs/CONVENTION.md`) |
| Size numbers in `docs/CONVENTION.md` match the size guard (80 lines, 80,000 bytes) | all | `test_conventions` |
| Blocking `subprocess` calls (`run`, `check_output`, `check_call`, `call`) name an explicit `timeout` (legacy allowlist in the test) | all | `test_conventions` |
| Test pairing: a feat/fix/refactor/perf commit that changes code carries `tests/`, or a `No-Test: <why>` trailer says why not | all | `test_githooks` (commit-msg hook, TEST_PAIRING_v1; code/test definition `tools/review_checklist.py`, which also warns in the delegation review) |
| Work banter in delegation / handoff / commit reports ≤ 1-2 sentences (detail: `docs/CONVENTION.md`) | all | manual (a check would have to match words or sentences, which the language rule below bars) |
| Page script or stylesheet ≤ 43,000 bytes; listed ceilings only go down | all | `test_page_scripts` |
| New code folder is protected (`tools/` too: the delegation gate's verdict reader is governance) | all | `test_code_layout` |
| Every code file (root, `providers/`, `tools/`, `static/`) has a code-map row before it lands | all | `test_code_map` |
| Core modules import stdlib + each other only | all | `test_core_standalone` |
| No new pair of modules that import each other (top or inside a function); the known pairs only go away | all | `test_import_cycles` |
| No provider names in common code | all | `test_provider_neutrality` |
| Persona names/titles are display values, never ids or keys | all | `test_identity_wiring` |
| Injected instruction bundles within `bundle_budget.json` | all | `test_bundle_budget` |
| Every plan file has one INDEX row with a valid status | all | `test_plans_index` |
| DEVLOG stays small; old dates in `docs/devlog/` | all | `test_docs_budget` |
| Docs cite code as `path` or `path::symbol`, never line numbers; links resolve | all | `test_doc_refs` |
| Tool-named entry files (`CLAUDE.md`, `GEMINI.md`) only point here; no new invented entry files | all | `test_entrypoints` |
| Document names: standing UPPERCASE, accumulating lower-kebab, no snake_case | all | `test_doc_names` |
| Every registry row names an audience and a real enforcer | all | `test_rule_registry` |
| Every enforcer is Tier 3 (`protected_paths.json` governance) and runs on each commit (`run-tests.sh` FAST), or is listed slow with where it runs instead | all | `test_rule_registry` |
| No new hardcoded Korean in engine/page code (i18n catalogs instead); mark intended lines `l10n-ok` | all | `test_ratchets` (`ratchet_baseline.json`) |
| No new host/persona identity (DiskStation, `/volume1`, Sphere, 실장님, 냥) in engine code outside the host plugin | all | `test_ratchets` |
| Tracked workspace template twins (repo `data/workspace` when present) are classified in `templates/workspace-manifest.json`; `same` pairs stay byte-equal; the template names no host and no engine work | all | `test_workspace_template` |
| Observations only via `observations.add` / the `observation` tool | all | `test_observations` (shape) |
| Speak with the developer in Korean. Agent-facing documents (this file, `docs/CONVENTION.md`, `docs/STATE.md`, charters, role packs, skills) in English; operator-facing ones (`docs/CONCEPT.md`, `docs/ARCHITECTURE.md`, plans, DEVLOG) may be Korean | all | manual (chat-agent runtime voice stays in workspace charter, not here) |
| Agent-facing machine text (prompts, tool strings, LEARNED lines) in English | all | manual |
| Check each request against project goals; reject or propose re-scoping when it does not fit | all | manual (plan gate G2, DoR) |
| Look for prior art before building (`~/AGENTS.md` §0) | all | manual |
| The engine decides what code can settle (tool choice, argument shape, format, classification); the model keeps only the character's words and acts | all | manual (plan `docs/plans/engine-decides.md`; failure rates from `logs/events.jsonl`) |
| Results never depend on language or the model's wording: no word or phrase matching, no guessing at model text; show engine facts and the text as is | all | manual (review; the l10n ratchet in `test_ratchets` catches hardcoded Korean only) |
| Spawn-visible dirs stay minimal (`ADD_DIRS`) | all | manual |
| Engine-work rules for the chat agent live in the `dev` role pack, never the shared charter or another role's `role.md` | PE chat agent only | `test_dev_role` |
| Dev and shipped instructions never mix: one shipped charter for both builds; dev-build rules only in `DEV-CHARTER.md`, injected only when `host_config.EDITION` is dev; neither file repeats the other; a shipped bundle names no dev tool; a shipped role pack names only skills that ship | all | `test_edition_instructions`, `test_workspace_template` |
| Chat UI conventions (`<!--choices-->`, persona voice); not for external CLIs | PE chat agent only | `templates/workspace/AGENTS.md` |

Add a rule here in the same change that adds its enforcer; a rule without one says `manual` and why.
