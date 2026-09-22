---
id: 11
title: Intermittent 500 on POST /api/sessions/:id/message
status: actioned
type: internal
skill: []
proposes_skill: []
siblings_checked: "none — chatbot-specific server behavior, no sibling skill family applies"
area: chatbot/server.py session send path
date: 2026-09-17
session_context: Fixing doctor-probe sessions accumulating forever (chatbot-ctl.sh probe_message now deletes the probe session in its finally block); while testing that fix, two consecutive `chatbot-ctl.sh probe` runs got "PROBE_FAIL HTTPError: HTTP Error 500" on the /message call, but a manual curl replication of the exact same POST /api/sessions -> POST .../message -> POST .../stop -> DELETE sequence immediately after succeeded (200) on the first try.
parked_until:
resolved: 2026-09-17
resolution: Added instrumentation exactly as suggested, not a fix for the underlying race (still unreproduced) -- server.py's /message route now wraps sess.send() in its own try/except that prints the full traceback (lands in logs/chatbot.log via the existing stdout/stderr redirect) and attaches sess._stderr_tail as debug_stderr_tail on the error response, same as /stop already surfaces. The do_POST catch-all also logs tracebacks now, for any other route. Next real occurrence will leave enough detail to actually root-cause instead of just a bare error string.
reference:
---

**Issue:** `POST /api/sessions/:id/message` intermittently returns HTTP 500 for a brand-new session's first message (a doctor-probe "[doctor-probe] ping"), roughly back-to-back, then succeeds again on the next attempt with no code change in between. The failure is server-side (urllib raised HTTPError, meaning the server itself returned non-2xx, not a client timeout) but the access log line for the failing request has no accompanying traceback, and the *next* request in the same probe's cleanup sequence (`/stop`) returned a body containing `"debug_stderr_tail": ["error: context canceled"]`, suggesting the underlying agy process/request was cancelled mid-flight rather than genuinely erroring.

**Suggested improvement:** Add exception logging (full traceback, not just the generic `{"ok": false, "error": str(e)}` body) specifically around the `/message` route's `sess.send(text)` call, and/or capture stderr from the freshly-spawned agy process on this path the same way `debug_stderr_tail` already does for `/stop`, so a future occurrence has enough detail to root-cause. Worth checking whether this correlates with `_StandbyPool` adoption timing (cold-spawn vs. standby-adopted) or with `kill_orphan_agy`'s periodic sweep racing a fresh spawn.

**Principle:** An intermittent 500 on a hot path that only shows an HTTPError string (no body, no traceback) at the call site is not enough to root-cause from outside — the fix effort should go into capturing the actual server-side exception detail before spending more time reproducing it live, per the bounded-debugging principle (this was noticed as a side effect of an unrelated fix, not something to chase down in the same session).
