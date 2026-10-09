# Operations

Running, repairing and reading the logs of the engine, for agents and the operator. Read on demand; the entry is
`AGENTS.md`. Paths are relative to `engine/` (`chatbot-ctl.sh` is `engine/chatbot-ctl.sh`; the host link
`~/services/chatbot-ctl.sh` points to it).

## Repair

When the operator says the chat is broken. `healthz` alone misses a deadlock.

```bash
~/services/chatbot-ctl.sh repair
```

| Command | What it does |
|---|---|
| `doctor` | healthz, the RLock source guard, and every hour (`CHATBOT_PROBE_EVERY_SEC`) a message probe |
| `doctor --auto-repair` | `repair` when the probe fails (the watchdog runs this) |
| `probe` | a POST `/message` timeout check now |
| `repair` | stop, reap orphan agents, start, forced probe |
| `guard` | only the AST check that `AgentSession.lock` is an `RLock` |
| `logs` | the log digest (below) |

Restart only when the operator is idle or agrees. In a live turn, never run `stop`, `restart` or `repair`.

Known failure modes:

1. Message deadlock (2026-09-16): `ensure` held the session lock while `_spawn` -> `stop` took it again. Symptom:
   healthz OK, sending waits forever. Fix: the session lock is an `RLock`; `guard` checks it.
2. Orphan agents: our agent processes that are no longer children of the live chat server (every provider).
   `repair` and `doctor` reap them (`ctl_proc.py`, OS facts only) and leave the server's children and other tools'
   processes alone.
3. Server down: the watchdog runs `doctor --auto-repair` every minute.

## Logging (OBSLOG_v1)

One structured stream, `logs/events.jsonl`, is the source for "what happened on this host".
The chat server, the MCP server, `chatbot-ctl.sh` (start/doctor/repair) and every session turn
write to it. People and agents read the same lines through different views, so what a person
sees and what an agent sees cannot drift apart.

| Reader | Start here |
|---|---|
| Agent | `chatbot-ctl.sh logs --json` (findings first), then drill down with `--fp` / `--sid` / `--rid` |
| Person | 채팅 UI 로그 탭 → **서비스** (findings, process/ops/turn cards, recent warn/error/ops events; 1h/24h/7d; "이 세션만" = merged session timeline), or `chatbot-ctl.sh logs` / `logs -f` in a terminal |
| UI / scripts | `GET /api/service-log?since=24h[&sid=ID]` → `{digest, events}` (events newest first, ≤200, traces ≤2000 chars) |
| Live agent via MCP `run_command` | `chatbot-ctl.sh logs [--since 6h] [--sid ID] [--fp FP] [--rid RID] [--evt PREFIX] [--json]` (follow is refused) |

Other files:

- `logs/chatbot.log`, `logs/chatbot-mcp.log`: stdout/stderr of the two servers. Holds startup lines,
  a one-line copy of every warn/error event, and anything a library prints. No more access lines.
- `logs/chatbot-doctor.log`: human doctor/repair diary (kept; repair lines now carry `caller=`).
- `data/sessions/<sid>/events.jsonl`: the conversation's own log (UI 로그 tab). `logdigest --sid`
  merges it with the global stream by time.

### Where the log lives (LOG_PATH_v1)

One resolver, `host_config.py`: `LOG_DIR` (the directory) and `EVENTS_LOG` (the stream).
`telemetry/obslog.py`, `telemetry/logdigest.py` and `chatbot-ctl.sh` all read it and none of them composes a path of
its own, so they cannot drift apart. `CHATBOT_LOG_DIR` moves the directory, `CHATBOT_OBSLOG_PATH`
moves the stream and still wins over both — where lines are actually written is decided by
`obslog.configure()`, never by the default.

The default is the install's data folder: `$CHATBOT_DATA/logs`, i.e. `~/.pe/logs`, in the dev build and the shipped
one alike (2026-10-09; before, the dev build kept it in the repo). A log belongs to the install it describes and must
outlive an engine update or a fresh checkout (`docs/plans/user-data-separation.md` §2); the daily rollups under it are
kept forever. ctl's `chatbot.pid` / `chatbot-mcp.pid` live there too (`ctl_proc.py` gets the folder from ctl), and
ticket evidence (`log:fp` / `log:rid`) is looked up in `<data>/logs`, the archive included.

### What is not in this log

The global stream is host metadata: event, `sid`, provider/model, outcome, durations, error class
and hint, counts. A turn's words are **not** here — the question goes nowhere (`turn.start` logs
`chars`, its length) and neither does the answer. They live in `data/sessions/<sid>/events.jsonl`,
which is user data and is encrypted in the shipped build. Private sessions are must-not-be-seen
data, so nothing is copied out of them.

`tests/test_log_no_content.py` guards this: it drives a real private-mode turn, proves the words
reached the session log, then proves neither is anywhere in `logs/events.jsonl`. If you add a kind
to `_OBS_FORWARD` (`session.py`) that carries text, that test fails.

A tool's words are not here either (tl/E, 2026-10-09): `mcp.call` keeps ids and kinds and the size of everything else,
so a memory line, a search, a dialog line between characters or a delegated instruction never reaches the log
(`ToolArgumentsHaveNoWords` in the same test file). Before that date the log kept arguments up to 300 characters.

Known exceptions, still open (they are host notices, not conversation content, but they are
persona-flavoured and belong to the tone work — `align/G`·`l10n/D`):

- `session.stopped` / `session.interrupted` / `session.session_rotate` / `session.steer_queued` and
  `turn.loop_notice` / `turn.quiet_close` log the notice text, which is written in the persona's
  voice in the engine strings.
- `mcp.call` logs `msg` on refusal or failure, and a tool can answer in prose.

### Events, reactions and rooms (evt/B–E)

The event mailbox (`data/events/`, `events.py`) and this log are one record seen twice: every write to the
mailbox is mirrored here, so "what the app was told" and "what the log says" cannot drift apart. The mailbox is
the app's working data (delivery, cursors); this log is for reading what happened. Metadata only, like the rest:

| evt | fields |
|---|---|
| `events.publish` | `type`, `channel`, `id`, `to` (count or `*`), `subject` (left out for a private event) |
| `events.deliver` | `sid`, `character`, `channel`, `n`, `types`, `lag_s` (how long the oldest of them waited since it was published) — what a session was told before a turn |
| `events.prune` | `removed`, `kept` — the retention rule (30 days, 10 MB, private 7 days) |
| `react.turn` / `react.failed` | `sid` — a character speaking first, or why it could not |
| `react.defer` / `react.skip` | `reason` (`quiet_hours`, `conversation_running`, `per_hour`, `no_work_session`), deduplicated |
| `room.create` / `room.say` | `room`, `members`, `strategy` / `n`, `chars`, `mentions` |
| `room.turn` / `room.chain` / `room.done` / `room.failed` | `room`, `character`, `sid`, `secs`, `chars`, `ok` / `from`, `to` / `replies`, `chain` |

`tests/test_events.py` (`Logged`) proves a payload's words and a private event's subject never reach this log.

### Investigating (agent runbook)

1. `chatbot-ctl.sh logs --since 24h --json` and read `findings` (sorted error → warn). Each finding
   has `code`, `title`, `hint` (the next command to run) and `evidence`.
2. An error group: `chatbot-ctl.sh logs --fp <fp>` prints every occurrence and the last trace.
3. A conversation: `chatbot-ctl.sh logs --sid <sid>` is the merged timeline (HTTP requests, turn
   start/end with outcome and stderr tail, agent spawn/exit, reaping, the session's own events).
4. A request the UI reported: the response header `X-Request-Id` is the `rid`; `--rid <rid>` shows
   the request and everything the server logged while serving it.
5. Around a restart: `--evt repair` / `--evt proc` / `--evt doctor` and compare timestamps with the
   `turn.end` and `http.error` lines just before.

### Line format

```json
{"ts":"2026-09-23T10:44:31.123+09:00","lvl":"error","src":"chat","evt":"http.error","pid":4242,
 "rid":"a1b2c3d4e5f6","sid":"20260922-180815-864823","route":"POST /api/sessions/:sid/provider",
 "status":500,"dur_ms":132.4,"path":"/api/sessions/20260922-180815-864823/provider",
 "err":{"type":"KeyError","msg":"'omniroute'","fp":"3f9c01aa2b","where":"session.py:<line>:maybe_swap_provider","trace":"..."}}
```

| Key | Always | Meaning |
|---|---|---|
| `ts` | yes | local time, ISO 8601 with offset and milliseconds |
| `lvl` | yes | `info` / `warn` / `error` (`debug` unused) |
| `src` | yes | writer: `chat`, `mcp`, `ctl` |
| `evt` | yes | event name from the dictionary below; grep and group by this, not by `msg` |
| `pid` | yes | writing process; a new `pid` for the same `src` = a restart |
| `rid` | HTTP | request id, also sent back as `X-Request-Id`; bound to the thread, so events logged while serving the request carry it |
| `sid` | sessions | session id |
| `caller` | ops | who triggered it: `api-defibrillate`, `doctor-auto<…>`, `cli-tty`, `ppid:<parent><grandparent>`, or the `X-Chatbot-Caller` header (`doctor-probe`) |
| `msg` | optional | human text (≤2000 chars) |
| `err` | exceptions | `type`, `msg`, `fp`, `where` (`file:line:function`), `trace` (5xx/crashes only, ≤6000 chars) |
| `repeat` | dedup | how many identical events were folded into this one |

`err.fp` is a fingerprint of the exception type plus the innermost project frames by
`file:function` (no line numbers), so one bug keeps one `fp` across restarts and unrelated edits.

Guarantees: logging never raises into the caller; secret-looking keys (`token`, `secret`,
`password`, `authorization`, `api_key`, `cookie`, …) and values (bearer tokens, `sk-…`, `ghp_…`,
JWTs, `token=…`) are redacted; strings are capped; query strings are never logged.

### Event dictionary

#### Process (`src` chat / mcp)
| evt | lvl | fields |
|---|---|---|
| `proc.start` | info | `git`, `python`, `argv`, `ppid`, `caller`, `host`, `port`, defaults |
| `proc.heartbeat` | info | every 5 min: `uptime_s`, `rss_mb`, `threads`, `fds`, `cpu_s`, `log_write_errors`; chat adds `sessions`, `busy`, `subscribers`, `agent_procs`, `auto_recycle_total` |
| `proc.exit` | info | clean shutdown (SIGTERM / atexit), `reason` |
| `proc.crash` / `thread.crash` | error | uncaught exception in the main thread / a worker thread, `err` |

A `proc.start` with no `proc.exit` from the previous pid means the process was killed (-9, OOM) or crashed.

#### HTTP (`src` chat / mcp)
| evt | lvl | when |
|---|---|---|
| `http.summary` | info | every 5 min: `routes` → `{n, codes{2xx..}, p50, p95, max}` for every request, including those not written one by one |
| `http.error` | error | status ≥ 500 or an unhandled exception; `err` with trace |
| `http.client_error` | warn | status 4xx; deduped per route+status for 5 min (`repeat`). 404s on `/.well-known/` (MCP clients' OAuth discovery on every connect) are counted in `http.summary` only |
| `http.slow` | warn | ≥ 3 s, streams (`/events`) excluded |
| `http.request` | info | successful POST/PUT/DELETE on chat (MCP traffic is summarised only) |
| `log.suppressed` | warn/error | storm guard settlement: `count` lines of `of_evt` with this `err.fp` were not written |
| `http.client_gone` | info | client hung up mid-response (BrokenPipe/reset); deduped per route for 10 min |

Routes collapse ids: `/api/sessions/:sid/log`, `/persona/*.webp`, `/api/tickets/:n`.

#### Turns and sessions (`src` chat)
| evt | lvl | fields |
|---|---|---|
| `turn.start` | info | `provider`, `model`, `notice`, `chars`, `resume`, `queued` |
| `turn.end` | info/warn | `outcome` (`result`, `error`, `stopped`, `interrupted`, `process_died`, `auto_stop`), `dur_s`, `ttft_ms`, `prep_ms` (message taken → agent told: bundle, spawn), `spawn_ms` (only when this turn started an agent), `first_tool_ms`, `standby`, `tool_calls`, `read_kb`, `tok_in`/`tok_out`/`tok_think`/`tok_cache_read`/`tok_total` (when the provider reports usage); on failure `stderr_tail`, `error_hint` |
| `turn.loop_notice` / `turn.quiet_close` | warn | loop guard warning / unfinished turn closed quietly |
| `turn.failfast_failed`, `turn.post_result_stop_failed` | error/warn | `err` |
| `session.error` | warn | the error the user saw (`msg`) |
| `session.stopped`, `session.interrupted`, `session.steer_queued` | info | `reason`, `queue_len` |
| `session.session_heavy`, `session.session_rotate` | warn/info | `level`, `weight`, `new_session_id` |
| `session.meta_corrupt`, `session.save_meta_failed`, `session.stdout_line_failed` | warn/error | `err` |
| `agent.spawn` | info | `agent_pid`, `standby` |
| `agent.exit` | info/warn | `agent_pid`, `rc`, `died_mid_turn`, `requested` |
| `agent.recycle` | warn | idle processes restarted after an agy login change |
| `agent.standby_spawn` | info | the warm standby pool started an agent (`agent_pid`) |
| `workspace.seeded` | info | files created from templates at start |

#### MCP (`src` mcp)
| evt | lvl | fields |
|---|---|---|
| `mcp.call` | info/warn | `tool`, `ok`, `dur_ms`, `args` as metadata (`obslog.arg_meta`: ids and kinds such as `action`/`id`/`path`, numbers, a command's program; any other text as `{"chars": n}`), `result` as counts (list lengths, a status word), `msg` on refusal/failure |
| `mcp.tool_exception` | error | `tool`, `err` |

#### Operations (`src` ctl)
| evt | lvl | fields |
|---|---|---|
| `ctl.spawn` | info | `proc` (chat/mcp), `pid` |
| `ctl.start_failed` | error | last lines of chatbot.log |
| `repair.begin` / `repair.end` | warn / info-error | `caller`; end: `ok`, `dur_s`, `orphans`, `pruned` |
| `repair.busy_timeout` | warn | repair went ahead while the server's agents were still working (measured by CPU/I-O, `ctl_proc.py busy`) |
| `host.defibrillate` | warn | (`src` chat) repair requested over HTTP |
| `doctor.probe` | info/error | hourly message probe, `ok`, `msg` on failure |
| `doctor.fail`, `doctor.chat_down`, `doctor.mcp_down`, `doctor.maintenance` | error/info | `check` |
| `agent.reaped` | warn | a CLI agent process killed by ctl: `agent_pid`, `ppid`, `parent_cmd`, `chat_pid` (the live server per ctl's pid file), `reason` (`ppid1` / `orphan`; before 2026-09-23 also `no-conversation`, `unprotected-flash-low`, `stale-session`), `age_s`, `cmd`. Only our agents (cwd = `data/workspace`) outside the live server's process tree are reaped (`ctl_proc.py`, OS facts only) |
| `main.check` | info/error | `src=watch`: the whole suite on main's commit after main moved (`tools/main_watch.py`, MAIN_WATCH_v1): `sha`, `subject`, `ok`, `failed`, `dur_s`; red is the digest's `main_red` finding until a green check |
| `manifest.drift` | warn | protected files differ from git HEAD — edited, deleted, or new and uncommitted (`evolution.py::protected_changes`, split/E; the name is kept from the hash manifest it replaced); logged only when the difference changes |

### Findings (telemetry/logdigest.py)

Thresholds live at the top of `telemetry/logdigest.py`.

| code | severity | rule |
|---|---|---|
| `silent_process` | error | no event from chat/mcp for 2.5× heartbeat and no `proc.exit` |
| `unclean_restart` | error | `proc.start` without a `proc.exit` from the previous pid |
| `proc_crash` / `thread_crash` | error | uncaught exception |
| `error_fp` | error (new fp) / warn (seen before) | error-level exceptions grouped by fingerprint |
| `http_5xx` | error | a route with ≥3 5xx or ≥1% 5xx |
| `http_slow` | warn | p95 > 2 s (≥10 requests, streams excluded) |
| `client_error_repeat` | warn | the same route+4xx ≥ 50 times |
| `context_over_budget` | warn | a bundle's static layers past `bundle_budget.json` (`context.alert`, CONTEXT_ALERT_v1) |
| `context_missing` | warn | a required layer (charter, card) empty in a bundle |
| `context_leak` | error | a private bundle holding a work-only layer's text |
| `turn_failures` | error | a provider's failed-turn rate ≥ 20% (≥5 turns) |
| `agent_died_mid_turn` | warn | `agent.exit` with `died_mid_turn` |
| `repair_frequent` | warn | ≥ 6 repairs a day |
| `repair_failed`, `probe_fail` | error | repair/doctor probe still failing |
| `heartbeat_gap` | warn | a > 2.5× heartbeat hole while the process lived (stall) |
| `agent_reaped_live` | warn | ctl reaped a child of the chat server while that server was alive (must not happen) |
| `rss_growth` | warn | > 150 MB growth within one process lifetime |
| `log_write_errors` | warn | the logger itself could not write |

### Ticket evidence from the log (LOG_EVIDENCE_v1, improvement-layers D2)

A ticket's `evidence` is data, checked when it is proposed: `log:fp:<10 hex>` (an error fingerprint), `log:rid:<12 hex>`
(a request id, e.g. from the UI's `X-Request-Id`), or `event:<session>#<line>`. `tickets.propose` accepts a log ref
only if that fingerprint/request is in `logs/events.jsonl` or a rotation right then. The operator's words are not
evidence: they go in `request` (`ticket-quick start … --request "<their words>"`). A ticket has one or both. The host
no longer turns findings into observation candidates (the HOST_SIGNALS loop went with the observation log, il/A);
findings stay in the digest, and a red main is its first one (`main_red`).

### Error storms

One bug hit in a loop (a UI poll against a failing route) must not rotate the history out of the
file. Per `err.fp`: the full `trace` is written at most once per 5 min (later lines carry
`err.trace_omitted`), and at most 20 lines are written per minute. Lines beyond that are counted and
settled every 5 min as one `log.suppressed` event (`count`, `of_evt`, `err.fp`); `logdigest` adds
them back into the group's count and marks the finding "폭주". `http.summary` still counts every
request, so 5xx rates stay exact.

### Storage

Lines are written only where `CHATBOT_OBSLOG_PATH` points; `chatbot-ctl.sh` exports it (the
resolver's `EVENTS_LOG`) for everything it starts. Tests and hand-started servers leave it unset, so
their events stay in memory (`obslog.RECENT`) and warn/error still reach stderr: a test server can
never write fake restarts into the production log. A started server removes `CHATBOT_OBSLOG_PATH`
and `CHATBOT_CALLER` from its own environment once configured, so the CLI agents it spawns (and any
tests they run) do not inherit them.

`events.jsonl` rotates at 10 MB, keeping 5 files (`.1` … `.5`), under an flock on
`events.jsonl.lock`; every write opens, appends and closes, so all processes (and the shell)
share it safely. Expected volume is about 1 MB a day: successful polling is summarised, not listed.

The file that falls off `.5` is not lost (tl/B, `telemetry/archive.py`): it moves to `logs/archive/` (a rename, the
writer is not held up), and the long-running processes' background thread, about once an hour, gzips it and drops
archives older than 90 days (`CHATBOT_OBSLOG_KEEP_DAYS`) or over 1 GB (`CHATBOT_OBSLOG_ARCHIVE_MAX_BYTES`), oldest
first; it logs `log.archive` when something changed. `logdigest` reads the archive for a long window
(`--since 30d`); the folder comes from `archive.dir_for(log)`, next to the log it belongs to.

Daily rollups (tl/C, `telemetry/rollup.py`): one summary per finished day in `logs/metrics/YYYY-MM-DD.json`, kept
forever (about 18 KB a day): turns by provider/model/mode/character (outcomes; duration, TTFT, tool calls, read KB
and input-token percentiles; token sums -- from turn.end since 2026-10-09, before that from the sessions' recorded
usage, a lower bound since deleted sessions are gone: `tokens_from`), HTTP
routes, error counts and top fingerprints, process starts and repairs, MCP calls, injected context size, the message
system (published by type, delivered, first-word reactions and why they waited), session rotations, main checks.
The background thread fills missing days about once an hour and logs `log.rollup`; by hand
`python3 engine/telemetry/rollup.py build`, and `rollup.py show [--days 7] [--json]` prints one line a day.

### Adding events

Use `from telemetry import obslog`, then `obslog.event("area.name", lvl=..., **fields)` / `obslog.exception("area.name")`, or from the shell
`obs area.name warn key=value`. Pick a dotted, stable `evt`, put variable text in `msg` or fields,
use `dedup=` for anything that can repeat in a loop, and add the event to the dictionary above.
Metadata only — see 「What is not in this log」 before you reach for a field that holds a message.
