# Product

<!-- impeccable:product-schema 1 -->

[`CONCEPT.md`](CONCEPT.md) is the canonical baseline for maximum value, moat, and primary objectives. This document translates that baseline into concrete product decisions (for whom, what, and by what principles). In case of conflict, the concept wins.

## Platform

web — Local Python engine + browser UI. Packaged for distribution via a thin desktop shell (such as Tauri) for Steam ([release-pipeline.md](docs/plans/release-pipeline.md) Pre-Steam).

## Users

**End users installing on their own PC or server.** Users who already subscribe to AI providers (Google, xAI, Anthropic, OpenAI, etc.) or CLI tools, looking for a **companion tailored to their taste** by their side rather than a cold productivity chat interface.

- Core audience: Power users in the SillyTavern, character card, and AI companion scene who value deep lore and immersion.
- Entry audience: Casual users trying out the product using free Google account quotas.
- Use cases: Kept open beside the desktop throughout the day — office tone during working hours, private relationship when desired. Seamlessly continued via mobile browsers.

The current deployment is on a developer NAS (DiskStation). Host-specific utilities are detailed strictly under "Development Deployment".

## Product Purpose

**A pre-made personalization harness with zero barriers to entry.** Ships complete with characters, visuals, and rules ready for instant conversation, gradually shaped by the user over time.

Success criteria:
- First conversation starts with zero initial configuration (pre-made packs, BYOK login).
- The companion remembers the user and the relationship across sessions (continuity).
- Users can effortlessly modify characters, memories, visuals, voice, and rules with agent assistance.
- Accumulated personalization remains intact across provider switches and engine upgrades.

## Positioning

**Occupying the space of Wallpaper Engine — customizing companions instead of wallpapers.** Low-price one-time Steam purchase + BYOK (sell engine and UX, user brings models) + Steam Workshop.

We do not compete against provider work harnesses on raw work throughput. We compete on the **deeply accumulated personalization layer** and the **ecosystem of plugins and Workshop creations**.

The public-facing surface is a **customizable agent harness and desktop companion**. Relational dynamics are optional layers for the user to explore. Immersive framing (Video Girl Ai, Joi, the Video Shop) serves as an internal immersion device and is not marketed on store frontlines.

## Operating Context

**Shipped Product**
- Runs locally on the user machine. User data resides in `~/.pe` (Windows `%USERPROFILE%\.pe`), decoupled from engine source code ([user-data-separation.md](docs/plans/user-data-separation.md)).
- Thin client browser UI connects to the local engine, supporting both desktop and mobile layouts.
- LLM CLI and API processes spawn locally on the user device.

**Development Deployment (Single Operator)**
- Synology DiskStation daemon (`chatbot-ctl.sh`), port 3011 (chat) and 3012 (MCP).
- Plaintext HTTP via internal LAN.
- Web surface serves full-window chat via `static/index.html`.
- NAS service control (`nas_mcp_host.py`) is an environment plugin, enabled via `data/host.env`.

## Capabilities and Constraints

**Implemented Features**
- **Multi-Provider BYOK**: agy (default), claude, grok, codex CLIs, plus HTTP OpenAI-compatible providers (`providers/adapters.py`).
- **Characters**: Canonical V2 character cards (`characters/<id>/card.json`), `visual.md` appearance specs, SillyTavern PNG card import, lorebooks.
- **Memory**: Common `memory/MEMORY.md`, per-character `memory.md`, and excluded `private-memory.md`. Short-slot relational memory active.
- **Visuals & Staging**: Sprite multi-framing (Visual Adapter), expression tags, emotion events (`emotion.py`).
- **Private Mode**: Action inputs, choice branches, tension levels, provider refusal mitigation layers (`private_engine.py`).
- **Continuity**: Token-aware handovers, session resumes, timeout and quota watchdog guards (`turn_watchdog.py`).
- **Self-Development**: Agents refine skills, memories, and instructions under user approval.
- **Tools**: Integrated MCP server (`mcp_server.py`) and core memory/ticket/observation tools.

**Boundaries & Constraints**
- Shipped agents **never modify engine code**. Self-evolution gates, worktrees, and commit hooks exist only in the dev build.
- Live chat sessions cannot restart their host daemon.
- Pending roadmap items: Desktop launcher, mode encryption, keychain integration, i18n localization, 2.5D/3D renderers.

## Brand Commitments

- **Working Name**: Private Engine (PE) prior to trademark clearance ([private-engine-brand.md](docs/plans/private-engine-brand.md)).
- **Characters**: Identity, voice, and appearance reside strictly in cards and `visual.md`. No hardcoded persona strings in engine code.
- **Theme System**: 7 selectable CSS themes (`lime`, `amber`, `cyan`, `emerald`, `violet`, `mono`, `spark`).
