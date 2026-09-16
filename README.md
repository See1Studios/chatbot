# chatbot (냥피디 / NyangPD)

Sphere DiskStation NAS chat agent — self-evolving, all-around content-creator persona ("냥피디").

This repo is a **private, full backup mirror** combining five repos that live on the NAS and stay authoritative for local development:

- `code/` — mirrors `/volume1/homes/me/services/chatbot` (the running service: `server.py`, `nas_mcp.py`, `static/`, `config/`, `docs/`, `chatbot-ctl.sh`)
- `workspace/` — mirrors `/volume1/homes/me/services/chatbot-data/workspace` (AGENTS.md/PERSONA.md/SELF-MODIFY.md rules, project skills, task-observer's observation log)
- `data/sessions/` — mirrors `/volume1/homes/me/services/chatbot-data/sessions` (chat session records)
- `data/artifacts/` — mirrors `/volume1/homes/me/services/chatbot-data/artifacts` (generated images/files from conversations)
- `data/persona/` — mirrors `/volume1/homes/me/services/chatbot-data/persona` (generated persona artwork)

All five were merged in via `git subtree`, so their prior commit history is preserved under each prefix. Because this includes actual conversation records and generated content, **this repo must stay private.**

## Where things actually run

- Ports: 3011 (chat), 3012 (NAS MCP)
- Ops: `~/services/chatbot-ctl.sh status|start|stop|restart|doctor|repair|guard` (symlink to `code/chatbot-ctl.sh`)
- Full development history/story: `code/docs/DEVLOG.md`
- Self-modification safety rules: `workspace/SELF-MODIFY.md`

## Syncing

The NAS-side repos are the ones actually edited day to day. Pull new changes into this publish repo with:

```bash
git subtree pull --prefix=code /volume1/homes/me/services/chatbot main
git subtree pull --prefix=workspace /volume1/homes/me/services/chatbot-data/workspace main
git subtree pull --prefix=data/sessions /volume1/homes/me/services/chatbot-data/sessions main
git subtree pull --prefix=data/artifacts /volume1/homes/me/services/chatbot-data/artifacts main
git subtree pull --prefix=data/persona /volume1/homes/me/services/chatbot-data/persona main
git push origin main
```

Each NAS-side repo needs its own commit before a `subtree pull` picks up new content (e.g. `cd chatbot-data/sessions && git add -A && git commit -m "..."`).
