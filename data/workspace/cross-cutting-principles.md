# Cross-cutting principles (chatbot)

1. Paths match product names (`chatbot`, not character names).
2. Persona is swappable config; never bake character into project identity.
3. Lore/IP surfaces brand See1 only (no Zero).
4. Chat UI shows user/assistant only; system/tool go to the activity log view.
5. Prefer restoring the latest session over auto-creating a new one.
6. Product (host/UI/persona/self-modify) is independent of the session backend. Adapter contracts stay in `AgentAdapter` + ctl.
7. Do not copy `~/AGENTS.md` host-ops into workspace rule files.
8. All providers must guarantee identical capability, not just identical persona. A capability worth having on one provider goes in `nas_mcp` (or its `nas_mcp_host` plugin), not only in a skill doc — a shell-less API adapter (OmniRoute, any future one) could never reach it otherwise. A skill doc may additionally *tell* a CLI agent about it.
9. Rules reach every provider from the host, not from provider auto-discovery. `instructions.py` builds one bundle (AGENTS + PERSONA + skill index + memory snapshot) that `session.py` injects the same way for all providers. Native `AGENTS.md`/`CLAUDE.md`/skill discovery differs per CLI and per ancestor directory (measured 2026-09-19); nothing may depend on a CLI reading them.
10. Where an instruction lives (keep the always-injected bundle small):
    - **Charter** (`AGENTS.md`, + `PERSONA.md`): must hold every turn, and breaking it is costly or unrecoverable (live-restart ban, pre-approval, scope, memory trigger). One line each.
    - **On demand** (`PROJECT.md`, `SELF-MODIFY.md`, `docs/EMERGENCY.md`, skills): only relevant to one kind of task. The charter points at them; it does not repeat them.
    - **This file / DEVLOG / plans**: rationale and design for whoever edits the chatbot — never injected.
    - Say a rule once. If a guard, test or code already enforces it (`ctl guard`, unit tests), the prose keeps at most one line.
