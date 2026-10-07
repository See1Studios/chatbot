# Code map

Where to edit. Read on demand (the entry is the root `AGENTS.md`). Code names are relative to `engine/`; names that
start with `static/`, `templates/`, `tests/` or `docs/` are relative to the repo root. Detail lives in each module's docstring; this
map only says which file does what.

- Every code file has a row here before it lands (`tests/test_code_map.py`). Docs and plans live in `docs/`. Fix the row before adding a file.
- New module names take a group prefix (`session_`, `adapter_`, `route_`, ...). A new code folder goes into
  `protected_paths.json`.
- A Python module change needs a restart through `chatbot-ctl.sh`. A `static/` change needs a browser reload.

## Code map

### Core and host

| Area | Files |
|---|---|
| Paths, ports, env, token thresholds | `host_config.py`; where the repo root and the engine folder are `repo_layout.py` (tests: `tests/_paths.py`) |
| Self-evolution core (stdlib and each other only, `core_modules.json`) | `repo_layout.py`, `evolution.py`, `tickets.py`, `observations.py`, `memory_store.py`, `platform_compat.py` (OS differences); tickets from a CLI: `tools/ticket_quick.py` |
| Guards | loops `loop_guard.py`; unticketed writes, working-tree watch `write_guard.py`; per-caller tool scope and edition boundary `role_guard.py`; safety `content_guard.py` + `engine_data/content_guards.json` |
| Logs | `obslog.py` (writes `logs/events.jsonl`), `logdigest.py` (reads it) |
| Service control | `chatbot-ctl.sh`, `ctl_proc.py`; first-run data folder `data_bootstrap.py`; move a data folder `tools/migrate_user_data.py`; dev workspace links `tools/link_dev_workspace.py` |
| Server words by key | `i18n.py` (catalogs `static/i18n/<lang>.json`) |

### Providers

| Area | Files |
|---|---|
| Brains (CLI and HTTP), accounts | `providers/`: registry `adapters.py`, `adapter_base.py`, `adapter_{agy,claude,grok,codex,openai}.py`, `accounts.py`, `account_login.py`; swap a saved agy login `tools/switch_account.py` |

### Sessions and turns

| Area | Files |
|---|---|
| Session life, spawn, lock | `session.py`; a turn (send, steer, `/btw`, interrupt, successor) `session_turn.py`; what a session shows `session_view.py`; watchdogs `turn_watchdog.py` |
| Lookup, weights, standby | `session_registry.py`, `session_weights.py`, `standby_pool.py` |
| Instruction bundle | `instructions.py` (`LAYERS`, `build_instruction_bundle`) |
| Artifacts, media | `artifact_manager.py`, `media_handler.py` |
| Workspace status, tool log lines | `workspace_status.py`, `tool_format.py` |

### HTTP

| Area | Files |
|---|---|
| Routes | `server.py` (route tables, one row per endpoint, in match order), handlers `route_sessions.py`, `route_accounts.py`, `route_files.py`, matching `route_table.py` |
| Route helpers | card import `card_upload.py`, static delivery `static_delivery.py`, page errors `client_errors.py`, Web Push `push_manager.py`, character art `character_art.py`, message files `chat_upload.py`, emotion SSE `emotion.py`, `preview_guard.py`, `origin_guard.py` |

### Tools (MCP)

| Area | Files |
|---|---|
| Tool server | `mcp_server.py`; core tools (memory, observation, ticket) `mcp_core.py`; NAS host plugin `nas_mcp_host.py` |
| Tool calls | argument shapes `mcp_args.py`; tools an HTTP brain lacks `web_tool.py`, `mcp_parity.py`; which session called `mcp_caller.py` |

### Characters and personalization

| Area | Files |
|---|---|
| Cards, names, identity | `characters.py`, `character_names.py`, `identity.py`; placeholders `static/placeholders/` |
| Card import, export, generation | `tools/st_import.py`, `tools/st_export.py`, `card_prompt.py`, `card_parse.py`, `tools/card_gen.py` |
| Art | `art_manager.py` (the one way a picture gets in), format check `tools/check_character_art.py` |
| Summon wizard | `summon_api.py`, steps `engine_data/summon_steps.json`, page `static/app-summon.js` |
| Relationship memory | `memory_relationship.py` |
| Private mode | `private_engine.py` (Gemini refusal layer: `docs/providers/private-refusal-mitigation.md`); personal turns `personal_turn.py`; the note into the private room `threshold.py` + `engine_data/private_tension_{defaults,gemini,grok}.json`; items and affection `items.py` + `engine_data/affection.json` |

### Team, events, delegation

| Area | Files |
|---|---|
| Events and rooms | mailbox `events.py`; characters speaking first `event_react.py`; group rooms `room_chat.py`; dialog records `dialog_log.py`; the `dialog` tool `dialog_tool.py`; handoffs between directors `dialog_handoff.py`, drill `tools/handoff_drill.py`, page `static/app-handoffs.js` |
| Delegation (dev build) | `delegation.py`, stall watch `delegation_watch.py`, runner `tools/worktree_runner.py`; review `tools/review_checklist.py`; worker report `tools/worker_output.py`; tokens `tools/run_usage.py`; brain limits `tools/brain_limits.py`; diary line `tools/devlog_entry.py` |

### Page (`static/`)

| Area | Files |
|---|---|
| Boot and words | `app-i18n.js` (first), `app.js`, `index.html`, `sw.js` |
| Parts loaded first | `app-{api,device,messages,turn,activity,evolution,status,sessions-tab,team,sse,session,characters,viewport}.js`, `app-status-usage.js`, `app-status-context.js` |
| Messenger shell | `app-shell.js`, `app-shell-brain.js`, `app-shell-quota.js`, `app-msgmenu.js`, `app-office.js` |
| How an answer reads | `app-{blocks,stage,think,flow}.js`, `markdown.js`, `markdown-map.js`, `artifacts.js` |
| Composer | `app-{attach,item,act-key,recall,retry,speech}.js`, `slash.js`, `model-picker.js` |
| Other screens | rooms `app-rooms.js`, art manager `app-art.js`, dev only `app-dev-delete.js`, log tab `service-log.js`, `theme.js` |
| Character renderers | `visual-adapter.js`, `visual-sprite-adapter.js` |
| Styles (cascade order) | `sphere-theme.css`, `chat-{base,log,composer,panes,responsive,features}.css`, `art-manager.css`, `rooms.css`, `shell.css` |
| Visual system | `docs/DESIGN.md`, `.impeccable/design.json` |

### Tests

| Area | Files |
|---|---|
| Tests | `tests/`; run `engine/run-tests.sh` (without bash: `tools/run_modules.py`) |
