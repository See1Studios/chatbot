---
name: chatbot-self-improve
description: >
  Improve this NAS chatbot project itself (UI, session host, MCP, persona, hooks, skills).
  Use when siljangnim reports bugs in chat UI/FAB, sessions, tool log spam, persona, or asks
  the chatbot to upgrade itself.
---

## Boundary (mandatory)
Before any core/host change, read workspace `SELF-MODIFY.md`.
- OK: edit files on disk (design for next process), UI/persona, then restart + `chatbot-ctl.sh guard` + `doctor`/`probe`.
- Forbidden: treat a hung live turn as the place to brain-surgery the running lock/protocol; escalate to `repair` / EMERGENCY.md / 실장님.
- Never revert `AgySession.lock` from `RLock` to `Lock`.


# Chatbot self-improvement

Prefer fixing this project yourself over escalating to GameDeveloper.

## Map
- Code: `/volume1/homes/me/services/chatbot/`
- Data/workspace: `/volume1/homes/me/services/chatbot-data/`
- Hub FAB: `/volume1/web/index.html` (`AGY_CHAT_FAB_*`)
- Persona: `/volume1/web/chat/persona/`
- ctl: `/volume1/homes/me/services/chatbot-ctl.sh`
- Hooks: `.agents/hooks.json`
- Meta: `task-observer` + `skill-observations/`

## Workflow
1. Read PROJECT.md + docs/DEVLOG.md + target files
2. Smallest patch
3. Restart only if server/mcp changed
4. Smoke healthz
5. DEVLOG + OPEN observation
6. Korean summary; no tool spam in chat


## Never restart host during self-improve
- Editing live `server.py` does not require you to restart — ask for ⚡소생.
- Do not run ctl stop/restart/repair or set CHATBOT_FORCE_HOST.
