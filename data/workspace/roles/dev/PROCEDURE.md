# Developer procedure

Read before engine work. The every-turn part is `ROLE.md`. The engine rules, code map and rule registry are the
repo-root `AGENTS.md` (`services/chatbot/AGENTS.md`); this file does not repeat them.

## Where to look
- Code, paths, sessions: `PROJECT.md`. Product direction: `docs/CONCEPT.md` (before changing or building).
- Core boundary: `SELF-MODIFY.md`, only when actually touching the core.
- Plans: read `docs/plans/INDEX.md` before touching `docs/plans/` (status, archive, new plans).

## Tickets and changes
- Tickets exist only through the `ticket` tool (it states the evidence forms). The observation badge is not a work order.
- Only the user decides tickets. Say in your reply when you open or close one.
- Disk and git changes only after claiming an approved ticket, even on the user's word; name the paths in the claim.
- The loop covers instructions and pipelines too: an approved Tier 3 ticket may change the charter, design docs and guards.
- Run `./run-tests.sh` before committing; never `--no-verify`.
- After the claim: static UI (`static/`, persona) takes effect on refresh; Python host modules need the user's **⚡소생**.
- A procedure failure: leave an observation and open a protocol ticket. Minimal patch; the file's tests are the merge contract.
