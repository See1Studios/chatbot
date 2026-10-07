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
- Before committing run `./run-tests.sh --fast` and the modules for your files (`./run-tests.sh test_x`), never the whole
  suite (it takes minutes; the commit hook adds the related tests). A feat/fix commit carries its test or a `No-Test: <why>`
  line. Never `--no-verify`.
- After the claim: static UI (`static/`, persona) takes effect on refresh; Python host modules need the user's **⚡소생**.
- A procedure failure: leave an observation and open a protocol ticket. Minimal patch; the file's tests are the merge contract.
- A delegated change that alters a decision written in a plan (the chat page's are `docs/plans/ux-shell-roadmap.md`
  4.2.3 and its decision table) takes that plan into the ticket's paths and updates it in the same change. A merge
  writes its own diary line (`tools/devlog_entry.py`); a worker's final message names any plan it touched.
