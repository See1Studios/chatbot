# Developer procedure

Read before engine work. The every-turn part is `ROLE.md`. The engine entry is the
repo-root `AGENTS.md` (`services/chatbot/AGENTS.md`), with `RULES.md` and `CODEMAP.md` beside it; this file does not
repeat them.

## Where to look
- Code, paths, sessions: `PROJECT.md`. Product direction: `VISION.md` (before changing or building).
- Plans: read `docs/plans/INDEX.md` before touching `docs/plans/` (status, archive, new plans).

## Tickets and changes
- Tickets exist only through the `ticket` tool. Evidence is data (an event line, a log fingerprint or request id), never an opinion.
- Only the user decides tickets. Say in your reply when you open or close one.
- Disk and git changes only after claiming an approved ticket, even on the user's word; name the paths in the claim.
- The loop covers instructions and pipelines too: an approved Tier 3 ticket may change the charter, design docs and guards.
- Before committing run `engine/run-tests.sh --fast` and the modules for your files (`engine/run-tests.sh test_x`), never the whole
  suite (it takes minutes; the commit hook adds the related tests). A feat/fix commit carries its test or a `No-Test: <why>`
  line. Never `--no-verify`.
- After the claim: static UI (`static/`, persona) takes effect on refresh; Python host modules need the user's **⚡소생**.
  Never restart the host yourself; if the connection dies mid-change, stop, write down what is done on disk, and ask for
  ⚡소생. A port change or deleting sessions or characters in bulk needs the user's approval first.
- `AgentSession.lock` stays a `threading.RLock` (`chatbot-ctl.sh guard` checks it); `healthz` alone is not health (it
  misses a deadlock): `probe` the message path (`OPERATIONS.md`).
- A procedure failure: open a protocol ticket with its evidence (the event line or log reference). Minimal patch; the file's tests are the merge contract.
- A delegated change that alters a decision written in a plan (the chat page's are `docs/plans/ux-shell-roadmap.md`
  4.2.3 and its decision table) takes that plan into the ticket's paths and updates it in the same change. A merge
  writes its own diary line (`tools/history_entry.py`); a worker's final message names any plan it touched.
