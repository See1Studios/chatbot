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
| PE chat agent behaviour | `data/workspace/AGENTS.md` (+ role packs `data/workspace/roles/<role>/`) |
| Architecture: layers, adapters, plugin layer, ST split | `docs/ARCHITECTURE.md` |
| Data paths, ports, env | `host_config.py` |
| Per-install settings (host plugin on/off, web root, ports) | `$CHATBOT_DATA/host.env`, read by `chatbot-ctl.sh` (options: `templates/host.env.example`) |
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
| Session life, spawn, lock | `session.py` |
| Turn watchdogs (QUOTA_FAILFAST, SILENT_HANG) | `turn_watchdog.py` (mixin of `AgentSession`) |
| Session lookup / weights, `/btw` / standby pool | `session_registry.py` / `session_weights.py` / `standby_pool.py` |
| HTTP routes | `server.py`; route helpers `card_upload.py` (card import), `emotion.py` (emotion SSE), `preview_guard.py`, `origin_guard.py` |
| Artifacts / media | `artifact_manager.py` / `media_handler.py` |
| Workspace status / tool log format | `workspace_status.py` / `tool_format.py` |
| MCP server / core tools (memory, observation, ticket) / NAS host plugin | `mcp_server.py` / `mcp_core.py` / `nas_mcp_host.py` (server name `nas` is a provider config key: do not rename) |
| Instruction bundle | `instructions.py` (+ `session.py::AgentSession._send_direct`) |
| Characters, cards, lorebook | `characters.py`, `identity.py`; card import `tools/st_import.py`; data `data/workspace/characters/<id>/` |
| Private mode | `private_engine.py` (`RENDER_PROTOCOL`, Grok overlay, tension) + `data/private_tension_{defaults,gemini,grok}.json` |
| Safety guards | `content_guard.py` + `data/content_guards.json` |
| Delegation | `delegation.py`, `mcp_server.py` `delegate`, `tools/worktree_runner.py` |
| Self-evolution core | `evolution.py`, `tickets.py`, `observations.py`, `memory_store.py` (core: stdlib + each other only) |
| Loop / write guards | `loop_guard.py`, `write_guard.py` |
| Logs | `obslog.py` (writes `logs/events.jsonl`), `logdigest.py` (reads it) |
| Service control | `chatbot-ctl.sh`, `ctl_proc.py` |
| UI | `static/`: `app.js` (globals, send, boot; only code that runs at load) + parts loaded first `app-{api,device,messages,turn,activity,evolution,status,sessions-tab,team,sse,session,characters,viewport}.js`; `markdown.js` `artifacts.js` `slash.js` `model-picker.js` `theme.js` `index.html`; styles `chat-{base,log,composer,panes,responsive,features}.css` (cascade order) |
| Visual system | `DESIGN.md` + `.impeccable/design.json` |
| Tests | `tests/`; run with `./run-tests.sh` |

Python module change → restart (⚡소생) through `chatbot-ctl.sh` only. `static/` → browser reload.

## Naming

- Standing documents (one copy, always current, found by name) are UPPERCASE: repo root, `docs/` itself and `data/workspace/` itself — `README.md`, `AGENTS.md`, `docs/CONCEPT.md`, `docs/ARCHITECTURE.md`, `SKILL.md`, …
- Documents that accumulate are lower-kebab: `docs/plans/*.md` (`INDEX.md` excepted), `docs/devlog/YYYY-MM-DD.md`, observation logs.
- No snake_case document names. Pack-format files keep their format's name (`SKILL.md`; `role.md` until pew/L).
- Renaming a document: update every live link in the same change; leave history (DEVLOG, devlog/, archive/, ticket records) as written.

## Harness

- Default provider `agy`. Adapter registry `providers/adapters.py::AGENT_ADAPTERS`; a session restores its provider from `meta.json`. Provider- or harness-specific rules live in the adapter or `chatbot-ctl.sh`, nowhere else.
- Spawned agents see only `services/chatbot` and `<web root>/chat` (`host_config.py::ADD_DIRS`). Never add the home dir, `.hermes`, the whole web root or `services`; widen minimally and say why in DEVLOG.

## Work procedure

1. Start only from the operator's words or an approved ticket. External CLI: `python3 ~/bin/ticket-quick start --title "[<plan id>] …" --paths a,b`. Keep the claim token (it cannot be recovered).
2. Change only the claimed paths.
3. `./run-tests.sh` (all) or `./run-tests.sh test_x …`; green before commit. The commit hooks (`.githooks/`, install once per clone: `git config core.hooksPath .githooks`) rerun the guard tests and check the message.
4. Commit only your paths. Author = your agent (e.g. `git -c user.name="Claude Code" …`); Conventional Commits; trailers:
   ```
   Plan: <plan>/<item>
   Ticket: #<n>
   ```
5. Release the ticket (`ticket-quick done`), note the commit. Host module changed → tell the operator ⚡ is needed; restart only when the operator is idle or agrees.
6. Notable work → one block at the top of `docs/DEVLOG.md`.

Push/deploy: `~/AGENTS.md`. Remote `See1Studios/chatbot` (private). No `.bak-*` files.

## Rule registry

Audience: **all** = every agent changing this repo (including the PE chat agent doing code work).
Enforcer: the test or gate that fails when the rule is broken; `manual` = none yet (planned one in brackets).

| Rule | Audience | Enforcer |
|---|---|---|
| Work starts from the operator's words or an approved, claimed ticket; claim names the paths | all | `test_tickets` (release refuses dirty paths); `test_unticketed_write` (PE sessions) |
| A delegated worker cannot change its own pass condition (guard tests, `run-tests.sh`) | all | `test_worktree_runner` |
| Guard tests green before commit (`./run-tests.sh --fast`); full suite before release | all | `.githooks/check_staged.py` (pre-commit); `test_worktree_runner` (runner gates: guards + related tests); `test_tickets` (done refused while guards fail) |
| Conventional Commits subject; `Plan:` trailer when `docs/plans/` changes | all | `test_githooks` (commit-msg hook) |
| `Ticket:` trailer, own author name | all | manual |
| No secrets, `.env`, private memory or style references in commits | all | `test_githooks` (pre-commit hook) |
| Never `--no-verify`; hooks installed (`core.hooksPath=.githooks`) and executable | all | manual (run-tests.sh warns); backstops `test_worktree_runner`, `test_tickets` |
| Data paths only through `host_config` | all | manual (`test_data_paths`, uds/B) |
| Python module ≤ 1,500 lines; listed ceilings only go down | all | `test_file_sizes` |
| Page script < 1,000 lines | all | `test_page_scripts` |
| New code folder is protected | all | `test_code_layout` |
| Core modules import stdlib + each other only | all | `test_core_standalone` |
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
| Observations only via `observations.add` / the `observation` tool | all | `test_observations` (shape) |
| Agent-facing text in English; human docs Korean | all | manual |
| Check each request against project goals; reject or propose re-scoping when it does not fit | all | manual (plan gate G2, DoR) |
| Look for prior art before building (`~/AGENTS.md` §0) | all | manual |
| Spawn-visible dirs stay minimal (`ADD_DIRS`) | all | manual |
| Chat UI conventions (`<!--choices-->`, persona voice) | PE chat agent only | `data/workspace/AGENTS.md` |

Add a rule here in the same change that adds its enforcer; a rule without one says `manual` and why.
