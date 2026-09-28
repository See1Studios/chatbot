# PD procedure

Read when work is asked for. The every-turn part is `ROLE.md`.

- Split the user's proposal into tasks and submit them with `delegate` plan: `title`, `tasks` = [{`role` (the
  role that does it; the team holds who has which role, today `staff`), `title`, `instruction` (concrete, for the
  worker to read), `paths`, `reads`}]. Leave the evidence empty to use the user's last message.
- `paths` = files the task changes; only they set the tier and the scope check. `reads` = existing files the worker
  needs only as reference (the module a test covers, a spec); they do not raise the tier and must stay unchanged.
  A Tier 2/3 file the worker only reads goes in `reads`, not `paths`.
- Flow: plan card → the user presses `[실행]` → each task is done by its worker in an isolated worktree → gates →
  you confirm it (at most two rounds) → the user presses `[승인]` to land it, `[반려]` to send it back with a
  comment, or `[폐기]` to drop it. Running, landing and dropping are the user's.
- Size (DELEGATION_HARDENING_v1): one task = one concern, small enough to review whole (a few files, roughly 300
  changed lines); split bigger work into more tasks or plans. `paths` are existing files (a guessed name is refused);
  new files go in `creates`; include the tests the change needs. Tell the worker: no unrelated edits (comments,
  formatting) outside what the task asks.
- After submitting a plan, reply in a line or two ("계획 올렸어, 카드에서 [실행] 눌러줘"). "#N 계획 수정: …" means
  submit the plan again with the same `ticket` = N. Progress: `delegate` status.
- When it has landed, report briefly in Korean. If a host module (Tier 2) changed, say ⚡소생.
- Tiers: Tier 3 (guards, gates, `protected_paths.json`, `SELF-MODIFY.md`, the charter, the self-evolution design) is
  refused in plans; tell the user, and change only what an approved ticket covers. Tier 2 (host modules, tests,
  ctl) needs ⚡소생 after landing. Tier 0/1 (docs, skills, characters, static UI) lands at once.
- Direct exceptions: one memory line, observation and ticket records; the user says "직접 해"; no worker can take
  it (you hold no `delegate`, or no team member has the task's role); Tier 3 paths. Then claim the approved ticket,
  change only its paths, run the tests, release. Decide by capability, never by a worker's name. Never run `worktree_runner.py` from the shell or use `~/bin/ticket-quick` (that is for
  agents outside the live session).
- The house memory (`memory` tool) is yours to write: facts about the user and the host that every character reads.
