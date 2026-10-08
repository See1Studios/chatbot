# Architecture

How the engine (Private Engine, PE) is built, for agents that change it. Read on demand; the entry is `AGENTS.md`.
Code names are relative to `engine/`. Rules and their enforcers are in `RULES.md`, the file-by-file map is
`CODEMAP.md`, what the product is for is `VISION.md`. Each part below says whether it is **built** or
**planned**; a plan's design and order live in `docs/plans/` (start with `docs/plans/plugin-architecture.md`).

- Design rule: every outside dependency sits behind an adapter interface. The core knows no vendor or library.
- SillyTavern rule: what SillyTavern (ST) already does, the engine uses as ST defines it. PE designs its own format
  or feature only for what ST lacks.

## 1. Layers

```
+--------------------------------------------------------------+
|  Community / user: UI themes, voice packs, cards, extensions  |
+--------------------------------------------------------------+
|  Plugin layer: theme, voice pack, extension        (planned)  |
+--------------------------------------------------------------+
|  PE core: sessions, memory, instructions, lorebook, routing   |
+--------------------------------------------------------------+
|  Adapter layer: LLM | visual | TTS | STT | memory | storage   |
|                 | session | media | tools                     |
+--------------------------------------------------------------+
|  Infrastructure: the user's PC or server (dev install: a NAS),|
|  file system, outside APIs                                    |
+--------------------------------------------------------------+
```

In the code the layers are: core (tickets, protection, memory files, OS differences, repo layout:
standard library and each other only, `core_modules.json`), providers (`providers/`), sessions and turns
(`session*.py`, `turn_watchdog.py`, `instructions.py`), HTTP (`server.py`, `route_*.py`), tools (`mcp_server.py`,
`mcp_core.py`, the host plugin `nas_mcp_host.py`) and the page (`static/`, no build step). Upper layers know lower
ones; the core knows none above it; no import cycles.

Repo layout: the engine's code, settings and scripts are in `engine/`; the repo root holds the entry files, this
guidance and folders. Only `repo_layout.py` (code) and `tests/_paths.py` (tests) decide either path.

## 2. SillyTavern and PE

| Feature | Owner | Note |
|---|---|---|
| Character card editing | ST | PNG V2/V3 as specified; PE imports and exports (`tools/st_import.py`, `tools/st_export.py`) |
| Expression sprites (28 labels) | ST | ST's flat label set; PE stores them per framing (3.2) |
| Lorebook / World Info | ST | ST's JSON as is |
| Extensions, basics | ST | ST's extension spec is the reference |
| Many LLM providers | PE | runs locally (3.1) |
| Multi-framing sprites | PE | bust / full / avatar (ST has none) |
| 2.5D / VRM / 3D renderers | PE | planned (3.2) |
| Host control (e.g. a NAS) | PE environment plugin | optional per install, not the product's identity |
| Session continuity and handover | PE | ST has none |
| Self-development of skills, memory, instructions | PE | shipped build; user approval, undo |
| Code self-evolution (tickets, delegation) | PE dev build | not in the shipped build |
| Several characters, each in its own session | PE | ST has none |
| Provider layer packs (refusal mitigation, style, speed) | PE | per model family, grown by A/B (`private_engine.py`, `engine_data/private_tension_*.json`) |
| Mode lock, local chat encryption, keychain | PE | private protection, planned (`docs/plans/release-pipeline.md` Pre-Steam) |
| Office and private modes | PE | one character lives the day with the user |

## 3. Adapters

### 3.1 LLM provider (built)

Purpose: no vendor lock-in. Common code talks to `providers/adapter_base.py::AgentAdapter` only: spawn arguments and
environment, line normalizing, usage and quota, interrupt, compaction. The registry is
`providers/adapters.py::AGENT_ADAPTERS`; a session restores its provider from `meta.json`.

| Implementation | State |
|---|---|
| agy (Google Gemini) | built, default |
| Claude (Anthropic CLI) | built |
| Grok (CLI) | built |
| Codex (OpenAI CLI) | built |
| OpenAI-dialect HTTP brains (OpenRouter, OmniRoute, any from `providers.json`) | built |
| Local (Ollama / LM Studio) | planned (an OpenAI-dialect entry may already work) |

### 3.2 Visual (character renderer)

Purpose: swap how a character is drawn at run time. ST's flat sprite set stays ST's; PE adds framings.

Interface (built, `static/visual-adapter.js`): `VisualAdapter` with `load(character)`, `setEmotion(label)`,
`speak(text, audio)`, `destroy()`; `AdapterRegistry` registers and creates renderers by name.

| Implementation | Description | State |
|---|---|---|
| Sprite renderer | standing sprites per framing (`static/visual-sprite-adapter.js`) | built |
| AnimeLayer | 2.5D interactive layers | planned |
| VRM | 3D VRM models (Three.js / @pixiv/three-vrm) | planned |
| Spine | Spine 2D skeletal animation | planned |
| Live2D | Live2D Cubism SDK | planned |

Art layout (built; next to the card, `characters/<id>/`; the format is enforced by `characters.py` and
`tools/check_character_art.py`):

```
avatar.webp                    512x512 badge: the base look, face centred, readable as a 56px circle
avatar/<provider>.webp         512x512 optional per-brain "wig": same face, only hair and outfit change
stage.webp, stage/<provider>.webp   1024x1024 optional chat background
sprites/bust/<label>.webp      1024x1024 shoulder shot, transparent, one anchor for every label
sprites/full/<label>.webp      1024x2048 full body, feet on one line
```

Labels are ST's expression labels; `neutral` is required once a framing exists. A missing file falls back to the
engine's neutral placeholder (`static/placeholders/`). Framing by view (design rule): narrow or mobile view uses
`bust`, the desktop character view uses `full`, a chat badge uses `avatar`.

### 3.3 TTS

Purpose: swap the speech engine. Today the page uses the browser's Web Speech API; no server-side adapter yet.

| Implementation | Description | State |
|---|---|---|
| Browser | Web Speech API (fallback) | built (page) |
| ElevenLabs | cloud, high quality | planned |
| XTTS-v2 | local | planned |
| Coqui | local | planned |

Planned interface: `synthesize(text, voice_id) -> bytes`, `stream(text, voice_id) -> Iterator[bytes]`. Plan:
`docs/plans/voice-and-audio-interaction.md`.

### 3.4 STT

| Implementation | Description | State |
|---|---|---|
| Browser | Web Speech API (`static/app-speech.js`) | built (page) |
| Whisper | local | planned |
| Google Speech-to-Text | cloud API | planned |

### 3.5 Memory

| Implementation | Description | State |
|---|---|---|
| Files | house memory (`memory_store.py`), per-character and relationship memory (`memory_relationship.py`) | built |
| Vector DB | ChromaDB / Qdrant semantic search | planned (`docs/plans/character-memory-adapter.md`) |
| Redis | in memory with persistence | planned |

### 3.6 Storage

| Implementation | Description | State |
|---|---|---|
| Local file system | user data in `~/.pe` (paths only through `host_config.py`) | built |
| S3 or compatible | object storage | planned |

### 3.7 Session

| Implementation | Description | State |
|---|---|---|
| JSON files | `~/.pe/sessions/<id>/meta.json` and the session's events | built |
| SQLite / PostgreSQL | database sessions | planned |

### 3.8 Media and tools (built)

- Media a brain made: `media_handler.py::MediaSource`, one per CLI that writes files.
- Tools: MCP (`tools/list`, `tools/call`): core tools (`mcp_core.py`), the host plugin's tools, parity tools for HTTP
  brains (`mcp_parity.py`, `web_tool.py`).
- Tool and skill layering:
  - **Base baseline (engine-owned)**: Every character unconditionally holds base tools (`choices`, `dialog`, `memory`, `web`)
    and base skills (`handoff-brief`). Built into the engine (`characters.BASE_TOOLS`, `instructions.BASE_SKILLS`); zero gardening.
  - **Roles (user-owned)**: Professional roles (`dev`, `art`, `lead`, custom) grant specialized tools (`run_command`, `write_file`,
    `delegate`) and skills on top of the base baseline.

## 4. Plugin layer (planned)

Design, order and decisions: `docs/plans/plugin-architecture.md` (content vs code plugins, manifest, loading,
isolation, ratings, Workshop). Built today: CSS skins in `static/` (`static/theme.js`), not loaded from user data.

- UI theme: PE's own theme system (ST has none). Loads from `$CHATBOT_DATA/workspace/themes/<name>/theme.css`
  (shipped default `~/.pe`); hot swap without a page reload.
- Voice pack: a per-character voice bundle for local TTS. Loads from
  `$CHATBOT_DATA/workspace/voices/<name>/pack.json`: `{"tts_adapter": "...", "voice_id": "...", "params": {}}`.
- Extension: follows ST's extension spec and adds a PE backend hook. Loads from
  `$CHATBOT_DATA/workspace/extensions/<name>/`; entry points `index.js` (page) and `hook.py` (backend, PE only).

## 5. Roadmap

| Phase | What | State |
|---|---|---|
| 1 | ST PNG card importer | done |
| 2 | Lorebook engine | done |
| 3 | Visual adapter interface + sprite renderer (multi-framing) | done |
| 4 | AnimeLayer (2.5D) | planned |
| 5 | VRM (3D) | planned |
| 6 | TTS adapter + voice packs | planned |
| 7 | UI theme plugins | planned |
| 8 | Extension plugins (backend hooks) | planned |

## 6. Principles

1. Adapters first: the core knows interfaces, not implementations.
2. ST first: what ST has, use ST's. No second implementation.
3. PE only where ST has nothing: multi-framing, VRM, continuity, self-development of skills, memory, instructions.
4. Local first: the default implementation always runs on the user's machine.
5. Open to the community: anyone who keeps an adapter's contract can contribute.
6. Step by step: each adapter can be swapped or upgraded on its own.
7. One direction: upper layers know lower ones; the core knows none above it; no import cycles.
8. The shipped build never changes engine code; Tier 3 governance and pass conditions change only with the
   operator's approval.
9. The engine decides what code can settle; the model keeps the character's words and acts. Results never depend
   on language or on the model's wording.

## 7. Governance

### Builds

- Edition: `host_config.EDITION` only (`CHATBOT_EDITION`, default `shipped`). The shipped build has no `run_command`,
  `ticket` or `delegate`, and writes only user data (`test_edition_boundary`).
- Instructions never mix: both builds read the shipped charter (`templates/workspace/AGENTS.md`); the dev build adds
  `templates/dev-workspace/DEV-CHARTER.md` as its own layer (`test_edition_instructions`).
- Planned: a package exclusion list so the shipped build carries no dev machinery or dev guidance
  (`docs/plans/edition-boundary.md` edition/E, edition/F).

### Protection tiers

`protected_paths.json` (beside the engine's settings; patterns are repo-relative) decides them.

| Tier | What | Who changes it |
|---|---|---|
| 0 | paths this install exempts (today `static/`) | anyone with a ticket |
| 1 | user data (`~/.pe`) | the user, by approval |
| 2 | engine code | a ticket; a delegated change lands on the operator's word |
| 3 | governance: guards, hooks, the runner, charters, every rule enforcer | the operator only |

### Where checks run

- Commit hook (`.githooks/`): secrets and forbidden files, author, the FAST guards on the staged snapshot, commit
  message, ticket and plan trailers, test pairing; a live chat session cannot land a worker's branch.
- Ticket `done`: refused while the FAST guards fail.
- Delegation runner: FAST guards, smoke, related tests, then the PD's review.
- CI: `.github/workflows/tests.yml` runs `engine/tools/run_modules.py` on Linux for every push to `main`, and once a
  day on Linux, Windows and macOS. It runs only when this repo is pushed.
