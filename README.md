# chatbot (냥피디 / NyangPD)

Sphere DiskStation NAS chat agent — self-evolving, all-around content-creator persona ("냥피디").

This repo is a **published mirror** combining two repos that live on the NAS and stay authoritative for local development:

- `code/` — mirrors `/volume1/homes/me/services/chatbot` (the running service: `server.py`, `nas_mcp.py`, `static/`, `config/`, `docs/`)
- `workspace/` — mirrors `/volume1/homes/me/services/chatbot-data/workspace` (AGENTS.md/PERSONA.md/SELF-MODIFY.md rules, project skills, task-observer's observation log)

Both were merged in via `git subtree`, so their prior commit history is preserved under each prefix.

## Where things actually run

- Ports: 3011 (chat), 3012 (NAS MCP)
- Ops: `~/services/chatbot-ctl.sh status|start|stop|restart|doctor|repair|guard`
- Full development history/story: `code/docs/DEVLOG.md`
- Self-modification safety rules: `workspace/SELF-MODIFY.md`

## Syncing

The NAS-side repos (`code-src` = `/volume1/homes/me/services/chatbot`, `workspace-src` = `/volume1/homes/me/services/chatbot-data/workspace`) are the ones actually edited day to day. Pull new changes into this publish repo with:

```bash
git subtree pull --prefix=code /volume1/homes/me/services/chatbot main
git subtree pull --prefix=workspace /volume1/homes/me/services/chatbot-data/workspace main
git push origin main
```
