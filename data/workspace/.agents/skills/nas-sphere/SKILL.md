---
name: nas-sphere
description: Operate Sphere hub, Hermes factory, and DiskStation services via NAS MCP and ctl scripts. Domain=NAS (not Unreal/Zero).
---

# NAS Sphere skill

## When to use
Any request about DiskStation Sphere sites, Hermes status, service start/stop, web deploys under `/volume1/web`, or workspace files under `chatbot/data`.

## Workflow
1. Prefer **MCP `nas`** tools for status and allowlisted FS.
2. Lifecycle: `service_ctl` with name `chatbot` / `namuwatcher` and action `status|restart|...`. (Restarting `chatbot` from a live chat turn is forbidden — see `SELF-MODIFY.md`.)
3. Shell: MCP `run_command` allowlisted prefixes, or the terminal directly (skip-permissions is already on in the chat spawn).
4. Hub health `sphere_hub_status`, Hermes `hermes_status`, factory `factory_status`.
5. Image requests → native `generate_image`, then reference `/artifacts/...` in the reply.

## Do not
- Touch NamuWatcher port **3010** unless explicitly asked.
- Print secrets / oauth / `.env`.
