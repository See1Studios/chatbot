# Logging (OBSLOG_v1)

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

## Investigating (agent runbook)

1. `chatbot-ctl.sh logs --since 24h --json` and read `findings` (sorted error → warn). Each finding
   has `code`, `title`, `hint` (the next command to run) and `evidence`.
2. An error group: `chatbot-ctl.sh logs --fp <fp>` prints every occurrence and the last trace.
3. A conversation: `chatbot-ctl.sh logs --sid <sid>` is the merged timeline (HTTP requests, turn
   start/end with outcome and stderr tail, agent spawn/exit, reaping, the session's own events).
4. A request the UI reported: the response header `X-Request-Id` is the `rid`; `--rid <rid>` shows
   the request and everything the server logged while serving it.
5. Around a restart: `--evt repair` / `--evt proc` / `--evt doctor` and compare timestamps with the
   `turn.end` and `http.error` lines just before.

## Line format

```json
{"ts":"2026-09-23T10:44:31.123+09:00","lvl":"error","src":"chat","evt":"http.error","pid":4242,
 "rid":"a1b2c3d4e5f6","sid":"20260922-180815-864823","route":"POST /api/sessions/:sid/provider",
 "status":500,"dur_ms":132.4,"path":"/api/sessions/20260922-180815-864823/provider",
 "err":{"type":"KeyError","msg":"'omniroute'","fp":"3f9c01aa2b","where":"session.py:1720:maybe_swap_provider","trace":"..."}}
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

## Event dictionary

### Process (`src` chat / mcp)
| evt | lvl | fields |
|---|---|---|
| `proc.start` | info | `git`, `python`, `argv`, `ppid`, `caller`, `host`, `port`, defaults |
| `proc.heartbeat` | info | every 5 min: `uptime_s`, `rss_mb`, `threads`, `fds`, `cpu_s`, `log_write_errors`; chat adds `sessions`, `busy`, `subscribers`, `agent_procs`, `auto_recycle_total` |
| `proc.exit` | info | clean shutdown (SIGTERM / atexit), `reason` |
| `proc.crash` / `thread.crash` | error | uncaught exception in the main thread / a worker thread, `err` |

A `proc.start` with no `proc.exit` from the previous pid means the process was killed (-9, OOM) or crashed.

### HTTP (`src` chat / mcp)
| evt | lvl | when |
|---|---|---|
| `http.summary` | info | every 5 min: `routes` → `{n, codes{2xx..}, p50, p95, max}` for every request, including those not written one by one |
| `http.error` | error | status ≥ 500 or an unhandled exception; `err` with trace |
| `http.client_error` | warn | status 4xx; deduped per route+status for 5 min (`repeat`). 404s on `/.well-known/` (MCP clients' OAuth discovery on every connect) are counted in `http.summary` only |
| `http.slow` | warn | ≥ 3 s, streams (`/events`) excluded |
| `http.request` | info | successful POST/PUT/DELETE on chat (MCP traffic is summarised only) |
| `http.client_gone` | info | client hung up mid-response (BrokenPipe/reset); deduped per route for 10 min |

Routes collapse ids: `/api/sessions/:sid/log`, `/persona/*.webp`, `/api/tickets/:n`.

### Turns and sessions (`src` chat)
| evt | lvl | fields |
|---|---|---|
| `turn.start` | info | `provider`, `model`, `notice`, `chars`, `resume`, `queued` |
| `turn.end` | info/warn | `outcome` (`result`, `error`, `stopped`, `interrupted`, `process_died`, `auto_stop`), `dur_s`, `standby`; on failure `stderr_tail`, `error_hint` |
| `turn.loop_notice` / `turn.quiet_close` | warn | loop guard warning / unfinished turn closed quietly |
| `turn.failfast_failed`, `turn.post_result_stop_failed` | error/warn | `err` |
| `session.error` | warn | the error the user saw (`msg`) |
| `session.stopped`, `session.interrupted`, `session.steer_queued` | info | `reason`, `queue_len` |
| `session.session_heavy`, `session.session_rotate` | warn/info | `level`, `weight`, `new_session_id` |
| `session.meta_corrupt`, `session.save_meta_failed`, `session.stdout_line_failed` | warn/error | `err` |
| `agent.spawn` | info | `agent_pid`, `standby` |
| `agent.exit` | info/warn | `agent_pid`, `rc`, `died_mid_turn`, `requested` |
| `agent.recycle` | warn | idle processes restarted after an agy login change |
| `workspace.seeded` | info | files created from templates at start |

### MCP (`src` mcp)
| evt | lvl | fields |
|---|---|---|
| `mcp.call` | info/warn | `tool`, `ok`, `dur_ms`, `args` (values ≤300 chars, redacted), `msg` on refusal/failure |
| `mcp.tool_exception` | error | `tool`, `err` |

### Operations (`src` ctl)
| evt | lvl | fields |
|---|---|---|
| `ctl.spawn` | info | `proc` (chat/mcp), `pid` |
| `ctl.start_failed` | error | last lines of chatbot.log |
| `repair.begin` / `repair.end` | warn / info-error | `caller`; end: `ok`, `dur_s`, `orphans`, `pruned` |
| `repair.busy_timeout` | warn | repair went ahead while a turn was still running |
| `host.defibrillate` | warn | (`src` chat) repair requested over HTTP |
| `doctor.probe` | info/error | hourly message probe, `ok`, `msg` on failure |
| `doctor.fail`, `doctor.chat_down`, `doctor.mcp_down`, `doctor.maintenance` | error/info | `check` |
| `agent.reaped` | warn | a CLI agent process killed by ctl: `agent_pid`, `reason` (`ppid1`, `no-conversation`, `unprotected-flash-low`, `stale-session`, …), `age_s`, `cmd` |
| `manifest.drift` | warn | protected files differ from the manifest; logged only when the difference changes |

## Findings (logdigest.py)

Thresholds live at the top of `logdigest.py`.

| code | severity | rule |
|---|---|---|
| `silent_process` | error | no event from chat/mcp for 2.5× heartbeat and no `proc.exit` |
| `unclean_restart` | error | `proc.start` without a `proc.exit` from the previous pid |
| `proc_crash` / `thread_crash` | error | uncaught exception |
| `error_fp` | error (new fp) / warn (seen before) | error-level exceptions grouped by fingerprint |
| `http_5xx` | error | a route with ≥3 5xx or ≥1% 5xx |
| `http_slow` | warn | p95 > 2 s (≥10 requests, streams excluded) |
| `client_error_repeat` | warn | the same route+4xx ≥ 50 times |
| `turn_failures` | error | a provider's failed-turn rate ≥ 20% (≥5 turns) |
| `agent_died_mid_turn` | warn | `agent.exit` with `died_mid_turn` |
| `repair_frequent` | warn | ≥ 6 repairs a day |
| `repair_failed`, `probe_fail` | error | repair/doctor probe still failing |
| `heartbeat_gap` | warn | a > 2.5× heartbeat hole while the process lived (stall) |
| `rss_growth` | warn | > 150 MB growth within one process lifetime |
| `log_write_errors` | warn | the logger itself could not write |

## Storage

Lines are written only where `CHATBOT_OBSLOG_PATH` points; `chatbot-ctl.sh` exports it
(`logs/events.jsonl`) for everything it starts. Tests and hand-started servers leave it unset, so
their events stay in memory (`obslog.RECENT`) and warn/error still reach stderr: a test server can
never write fake restarts into the production log.

`events.jsonl` rotates at 10 MB, keeping 5 files (`.1` … `.5`), under an flock on
`events.jsonl.lock`; every write opens, appends and closes, so all processes (and the shell)
share it safely. Expected volume is a few MB a week: successful polling is summarised, not listed.

## Adding events

Use `obslog.event("area.name", lvl=..., **fields)` / `obslog.exception("area.name")`, or from the shell
`obs area.name warn key=value`. Pick a dotted, stable `evt`, put variable text in `msg` or fields,
use `dedup=` for anything that can repeat in a loop, and add the event to the dictionary above.
