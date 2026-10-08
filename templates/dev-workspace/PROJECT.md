# chatbot (dev build)

Where things are, for a character doing engine work. Read on demand. Rules: `DEV-CHARTER.md` and
`roles/dev/PROCEDURE.md`, live outage `OPERATIONS.md`, product direction `VISION.md` (open it before changing code).

## Paths

- Engine: the repo `services/chatbot/` (its own git). Entry and commit procedure: repo-root `AGENTS.md`; rules
  `RULES.md`; code map `CODEMAP.md` -- kept there only; do not copy them here.
- User data: `$CHATBOT_DATA` (this install `~/.pe`): `workspace/` (memory `workspace/memory/MEMORY.md`), engine tickets
  `dev/tickets/` (dev build only), `sessions/<id>/meta.json` + `artifacts/`, shared `sessions/_shared/`,
  published art `persona/`. Per-install settings (web root, edition, host plugin): `$CHATBOT_DATA/host.env`.
- Delegation state: `~/.worktrees/chatbot/runs/ticket-<id>.json` (written by the runner, served at
  `/api/delegations`); what the operator has seen: `$CHATBOT_DATA/delegation_seen.json`.
- Start and stop only through `chatbot-ctl.sh`. Ports: 3011 chat (`CHATBOT_PORT`), 3012 tool server (`NAS_MCP_PORT`).

## How to change things

- Start only from the operator's words or an approved ticket. "Why does it not work?" -- first tell a provider
  outage, a misunderstanding and a bug apart.
- Before building anything new, find what exists (open source, products, plugins), compare two or three with links,
  and recommend adopt, adapt or build. Build from scratch only when nothing fits, and say why.
- Follow the role packs you hold (`roles/<role>/ROLE.md`; the default character's planning, delegation and reports:
  `roles/lead/PROCEDURE.md`).
- Order: concept, the code map, HISTORY, then the files. Minimal patch. When you fix one code path, grep its sister
  paths (adapter pairs, symmetric UI events and gates) and check them too.
- Tests: the guards and the modules for your files (`roles/dev/PROCEDURE.md`); core changes also
  `chatbot-ctl.sh guard`, then `doctor` or `probe`.
- Finish with a HISTORY block and a short summary for the operator in Korean.
