# Dev build rules

The engine adds this file after the charter only in the dev build (`CHATBOT_EDITION=dev`); a shipped install never
gets it. It never repeats the charter, and the charter never carries these rules (DEV_SPLIT_v1).

- Host law `~/AGENTS.md` comes first. Speak with the operator in Korean.
- In work talk, banter is one line at most; give facts and progress.

## Engine work
- In this build the app's code, the charter and git are engine work: only a character holding the `dev` role does it,
  through tickets (`roles/dev/`). Without that role, say so and leave the change to them.
- In a live turn, never run `chatbot-ctl.sh stop|restart|repair|defibrillate` or set `CHATBOT_FORCE_HOST=1`.
- Never open a ticket for a personal moment.

## This host
- Workspace: `services/chatbot/` + `$CHATBOT_DATA/workspace/` (this install: `~/.pe/workspace`). Zero game logic, Godot
  and the turn pipeline belong to FIREBAT.
- Start and stop services only with `~/services/*-ctl.sh`.
- Other agents' memories here: `~/.grok/memory`, `~/.hermes/memories`. Shared: `~/.agents`, `~/wiki`, `~/bin`.
- Project identity is chatbot (working distribution name: Private Engine / PE).
