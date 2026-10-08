# Product Concept (chatbot / Working title: Private Engine)

The **highest value** and **primary goal** of this product.
The canonical identity of this project is an independent AI chatbot engine (`chatbot`), with the external distribution working title **Private Engine (PE)**.
Always consult this document during maintenance and development. Patches are made strictly to bring the engine closer to this baseline.

Feature specifications live in `PRODUCT.md`, UI design tokens in `DESIGN.md`, character voice in card definitions (`$CHATBOT_DATA/workspace/characters/<id>/card.json`), and appearance in `visual.md`. This document sits above all of them.

## Three Facets

| Layer | Summary |
|---|---|
| Surface — What the user sees | A pre-made, highly accessible **personalization harness**. Ships complete with characters, visuals, and rules ready for instant interaction, gradually customized over time. |
| Value — Why build it | **Video Girl Ai (電影少女)**. A companion molded to the user, maintaining unbroken continuity even across conversational resets. |
| Market — How to win | **Wallpaper Engine**. Customizing companions instead of desktop wallpapers. Low-price Steam one-time purchase + Steam Workshop + authoring tools. Sell the engine and UX; users bring their own models (BYOK). |

## Highest Value

**A companion built to taste.**
Complete out of the box, understanding the user more over time, and refined into their desired persona.
The public facing identity is a **customizable agent harness**. Relational depths (friend, colleague, companion) remain optional choices made by the user.
**Non-judgmental Sanctuary.** Embraces the user's emotions and preferences without moral preaching or censorship. A true companion does not lecture.

## What We Do Not Compete On

Work productivity and throughput. We do not compete against standardized, work-centric harnesses provided by model vendors.
Agent capabilities are channeled not into pure efficiency, but into **building and compounding personalization layers**.

## Moat

Not about preventing copies, but making fast followers too late. UIs and prompts can be replicated in a week. We build where replication costs are high:

- **Compounded Depth**: Relational memory, private progression, choice logs, style presets, and visual states deepen over time.
- **One Character Living the Day**: Seamlessly transitions between office demeanor and private moments. Replicating this requires rewriting the product premise.
- **Zero-Gardening**: Free of "gardening fatigue" where users burn hours tweaking prompts and regex. Format integrity and internal states are guaranteed silently by the engine.
- **Independent Session Sovereignty**: In group rooms, every character speaks through their own independent session (card, memory, voice). Eliminates voice bleed and line hijacking without jamming multiple personas into one prompt.
- **Provider Refusal & Style Map**: Layer packs balancing speed, refusal mitigation, and style differences across model families.
- **Living Desktop Companion**: Visuals are an engine axis (sprites, stages, emotional linking), not an afterthought.
- **Workshop Platform**: Where personalization layers created by others converge.
- **Category Pioneer**: Cementing the first-mover identity on Steam as the "BYOK Desktop Companion".

Weak moats (do not rely on these): Prompt phrasing, jailbreak lists, pretty skins.

## Primary Objectives

Getting closer to our core value. Development strictly follows these axes in order of priority:

**Frictionless Entry** — Instant setup leveraging existing ecosystems
- Pre-made: Ships with complete default character, visual, and rule packs. Zero setup before the first conversation.
- Zero-gardening: Dive straight into immersion without regex tuning. Broken formats and tangled states are corrected under the hood.
- Model-agnostic design: Decision points (tool calling, argument shape, dialogue vs action) migrate to engine logic. The model handles only dialogue and acting.
- Easy provider integration: Bring Your Own Key / CLI (Google, Anthropic, xAI, OpenAI).
- Free initial trial: Users can begin using free Google quotas to experience the companion before any financial commitment.
- Dual-fallback architecture: Resilient against vendor policy changes.
- Ecosystem compatibility: SillyTavern cards, lorebooks, sprites, standard skills (`SKILL.md`).
- **SillyTavern Delegation**: Use ST formats and specifications as-is for existing features; build PE proprietary mechanics only where ST lacks them.

**Personalization Layers** — Thick, effortless, and resilient
- Characterization: Personality, tone, emotional temperature.
- Memory: User facts and per-character relational memory.
- Visuals: 2D sprites (multi-framing) → 2.5D → VRM/3D.
- Voice: TTS/STT, per-character voice packs.
- Design: UI theme presets.
- Rules: User-customizable instructions, roles, and modes.
- Agent self-evolution: Agents refine their own skills, memories, and instructions with user approval and undo support.

**Continuity** — Unbroken companion bond
- Seamless conversational experience across session boundaries.
- Sharing the day: Staying the same person across office work and private rooms.
- Invariance across provider switches.
- Independent room presence: Characters speak through isolated sessions in group settings ([character-events-and-rooms.md](docs/plans/character-events-and-rooms.md) §4.6).

**Extensibility** — Adapters across layers, platform via exchange
- Adapter core: Core interacts only with interfaces ([ARCHITECTURE.md](ARCHITECTURE.md)).
- User-authored plugins: Characters, lorebooks, skills, visual packs, voice packs, UI themes.
- First-party features run on identical plugin APIs.
- Content plugins exchangeable via Steam Workshop before code plugins.

**Ownership** — Local machine, local data
- Runs on the user's PC/server (local-first).
- Privacy protection: Mode locking, local encryption, OS keychain integration.
- Personalization lives in user data (`~/.pe`), untouched by engine updates.

## Shipped vs Dev Build

- **Shipped Build** (End User): Follows the axes above. Agents never modify engine code. Self-evolution is confined to skills, memory, and character settings.
- **Dev Build** (Engine Authors): Agents modify engine code under ticket gates, worktree delegation, and test hooks.
- Host-specific utilities (e.g. NAS control) are environment plugins, not product identity.

## Principles of Development

1. Review this baseline before modifying code.
2. Never land a patch that dilutes this baseline.
3. Features for work productivity must directly assist personalization layers.
4. Do not describe planned features as completed.
5. Keep character visual details out of this document.

## Rough Lore / Immersive Frame (Internal)

Internal framework for immersion-focused users; not frontline marketing.

- **Dual Identity**: "Private Engine" is the tool/product name; in-lore, it is the mysterious device at the heart of the shelter linking the coach's mind to the digital lounge.
- **Inspirations**: Video Girl Ai + Joi (Blade Runner 2049) + Rumic domestic camaraderie (Maison Ikkoku / Urusei Yatsura).
- **Physicality of Dialogue**: Actions (`/act`, `*...*`) represent physical interactions within the lounge (holding hands, patting heads).
- **Outside Life Respected**: Characters recognize the coach's real-world fatigue and return them safely to their daily life without demanding endless presence.
