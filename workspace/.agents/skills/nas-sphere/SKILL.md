---
name: nas-sphere
description: Operate Sphere hub, Hermes factory, and DiskStation services via NAS MCP and ctl scripts. Domain=NAS (not Unreal/Zero).
---

# NAS Sphere skill

## When to use
Any request about DiskStation Sphere sites, Hermes status, service start/stop, web deploys under `/volume1/web`, or workspace files under `chatbot-data`.

## Workflow
1. Prefer **MCP `nas`** tools for status and allowlisted FS.
2. For lifecycle: `service_ctl` with name `chatbot` / `namuwatcher` and action `status|restart|...`.
3. For shell: MCP `run_command` allowlisted prefixes, or direct terminal with skip-permissions (already enabled in chat spawn).
4. Hub health: `sphere_hub_status`. Hermes: `hermes_status`. Factory: `factory_status`.
5. Image asks → native `generate_image`, then reference `/artifacts/...` in replies.

## Branding
See1 / Sphere only on Lore and public faces. No Zero branding on Lore.

## Do not
- Touch NamuWatcher port **3010** unless explicitly asked.
- Print secrets / oauth / `.env`.
- Treat this host as an Unreal or Zero build machine.
