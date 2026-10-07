# Architecture

How the engine is built, for agents that change it. Read on demand; the entry is `AGENTS.md`. Code names are
relative to `engine/`. Rules and their enforcers are in `RULES.md`, the file-by-file map is `CODEMAP.md`. What the
product is for is `docs/CONCEPT.md`; this file says only what exists, and marks what is planned.

## Principles

1. Adapters first: common code knows an interface, never a vendor. Provider differences live only in
   `providers/adapter_<name>.py`.
2. SillyTavern first: what SillyTavern already defines (character cards PNG V2/V3, lorebooks, flat sprites), the
   engine reads and writes as is. It builds only what SillyTavern lacks.
3. Local first: the engine runs on the user's own machine; user data lives in `~/.pe`.
4. One direction: upper layers know lower ones; the core knows no layer above it. No import cycles.
5. The engine decides what code can settle; the model keeps the character's words and acts. Results never depend
   on language or on the model's wording.
6. Two builds, one code base: the shipped build never changes engine code; the dev build does, through tickets.

## Layers

| Layer | What | Where |
|---|---|---|
| Core | tickets, observations, protection, memory files, OS differences, repo layout. Standard library and each other only | `core_modules.json` lists them |
| Providers | one adapter per brain (CLI or HTTP) behind `AgentAdapter` | `providers/` |
| Sessions and turns | session life, a turn, what a session shows, watchdogs, the instruction bundle | `session*.py`, `turn_watchdog.py`, `instructions.py` |
| HTTP | routes in match order, handlers by domain | `server.py`, `route_*.py` |
| Tools | the MCP tool server, core tools, the host plugin | `mcp_server.py`, `mcp_core.py`, `nas_mcp_host.py` |
| Page | the chat UI (no build step) | `static/` |

Repo layout: the engine's code, settings and scripts are in `engine/`; the repo root holds the entry files, this
guidance and folders. Only `repo_layout.py` (code) and `tests/_paths.py` (tests) decide either path.

## Adapters that exist

| Kind | Interface | Implementations |
|---|---|---|
| Brain | `providers/adapter_base.py::AgentAdapter` (spawn args, line normalizing, usage, quota, interrupt) | agy, claude, grok, codex (CLI); OpenAI-dialect HTTP brains from `providers.json` |
| Character renderer | `static/visual-adapter.js` (`VisualAdapter`, `AdapterRegistry`) | sprites: `static/visual-sprite-adapter.js` (bust / full / avatar framing) |
| Media a brain made | `media_handler.py::MediaSource` | one per CLI that writes files |
| Tools | MCP (`tools/list`, `tools/call`) | core tools, host plugin tools, parity tools for HTTP brains |

Planned, not built (see `docs/plans/plugin-architecture.md`, `docs/plans/voice-and-audio-interaction.md`): server-side
speech (today the page uses the browser's Web Speech), 2.5D / VRM renderers, a memory backend interface, user
plugins (themes, voice packs, extensions) loaded from `~/.pe`.

## SillyTavern and the engine

| SillyTavern defines | The engine adds |
|---|---|
| Character cards, lorebooks, flat sprites, extensions | Multi-framing sprites, sessions that carry over between brains, character memory, work and private modes in one character, rooms where each character speaks from its own session, provider layer packs (refusal, style), self-development of skills, memory and instructions |

## Builds

- Edition: `host_config.EDITION` only (`CHATBOT_EDITION`, default `shipped`). The shipped build has no `run_command`,
  `ticket` or `delegate`, and writes only user data (`test_edition_boundary`).
- Instructions never mix: both builds read the shipped charter (`templates/workspace/AGENTS.md`); the dev build adds
  `templates/dev-workspace/DEV-CHARTER.md` as its own layer (`test_edition_instructions`).
- Planned: a package exclusion list so the shipped build carries no dev machinery or dev guidance
  (`docs/plans/edition-boundary.md` edition/E, edition/F).

## Protection tiers

`protected_paths.json` (beside the engine's settings; patterns are repo-relative) decides them.

| Tier | What | Who changes it |
|---|---|---|
| 0 | paths this install exempts (today `static/`) | anyone with a ticket |
| 1 | user data (`~/.pe`) | the user, by approval |
| 2 | engine code | a ticket; a delegated change lands on the operator's word |
| 3 | governance: guards, hooks, the runner, charters, every rule enforcer | the operator only |

## Where checks run

- Commit hook (`.githooks/`): secrets and forbidden files, author, the FAST guards on the staged snapshot, commit
  message, ticket and plan trailers, test pairing; a live chat session cannot land a worker's branch.
- Ticket `done`: refused while the FAST guards fail.
- Delegation runner: FAST guards, smoke, related tests, then the PD's review.
- CI: `.github/workflows/tests.yml` runs `engine/tools/run_modules.py` on Linux for every push to `main`, and once a
  day on Linux, Windows and macOS. It runs only when this repo is pushed.
