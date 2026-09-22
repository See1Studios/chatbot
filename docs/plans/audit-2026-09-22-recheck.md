# Audit Re-check — 2026-09-22

- Status: verification report on commit a993603 (ticket #25), which applied
  [audit-2026-09-22-work-ordered.md](./audit-2026-09-22-work-ordered.md) T1–T4.
  Read-only review; nothing in the code was changed by this re-check.
- Method: every task in the work order re-read against the committed diff,
  the new server code exercised directly (local ThreadingHTTPServer +
  urllib), full unittest run compared with the pre-audit baseline on the
  same Windows machine.
- Bottom line: most tasks are correctly applied. **Two items block
  ⚡소생**: the new POST origin gate rejects the ctl doctor probe, and the
  DOMPurify file the XSS fix depends on is absent from the repository.

---

## Blockers (fix before ⚡소생)

### B1. Origin gate rejects chatbot-ctl.sh probe → repair loop

- Where: server.py do_POST (new same-origin check at entry);
  chatbot-ctl.sh:332 req() inside probe_message.
- Defect: the probe sends only Content-Type: application/json, no
  Origin, no Sec-Fetch-Site. origin_guard.same_origin(None, host, None)
  is False, so POST /api/sessions (the probe's first call) returns 403.
- Reproduced against the committed code:
 
복사


  POST /api/sessions no-Origin: 403 {"ok": false, "error": "same-origin browser request required"}
  
- **Consequence once the new server.py is live**: chatbot-ctl.sh probe
  and doctor report PROBE_FAIL http=403; the Hermes cron runs
  doctor --auto-repair every minute and a failed probe routes to
  cmd_repair (see plan §3 S3 note). Resua restart every minutete**Fix (smallest)t)**: in probe_message's req(), add
  "Origin": f"http://127.0.0.1:{port}" to the headers. Alternative:
  same_origin accepts a missing Origin when the client address is
  loopback; less preferred because it widens the gate for every local
  processVerifyfy**: a test in tests/test_lifecycle.py (or new) that runs the
  probe's request shape against server.Handler and expects 200/201, and a
  test that a POST with Origin: http://evil still gets 403Work-order notete**: T1.3 said "confirm the Hub FAB and non-browser callers
  still pass". The FAB is fine (it is an iframe of :3011, same origin);
  the ctl probe was not checked.

### B2. DOMPurify is not in the repository → T1.2 is inertWherere**: static/index.html:310 loads ./vendor/purify.min.js;
  static/markdown.js wraps sanitization in if (window.DOMPurify)Factsts**:
  - static/vendor/purify.min.js does not exist in this checkout.
  - .gitignore:6 (static/vendor/*.min.js) prevents it from ever being
    committed; commit a993603 touched no vendor file.
  - DEVLOG and ticket #25 record "DOMPurify 3.2.6 벤더링" as doneConsequencece**: with the file missing, the <script> 404s and
  renderMarkdown silently skips sanitization. The XSS surface is unchanged
  on any fresh clone. Whether the file exists on the NAS disk cannot be
  determined from the repositoryFixix**:
  1. Add !static/vendor/purify.min.js to .gitignore and commit the file.
  2. Make absence loud: if window.DOMPurify is missing, escape the whole
     rendered HTML (or refuse to render) instead of passing it throughVerifyfy**: git ls-files static/vendor/purify.min.js returns the path; a
  Node harness test that renderMarkdown('<img src=x onerror=alert(1)>')
  contains no onerror **without** stubbing DOMPurify.

---

## Correctly applied (verified in code)

| Task | Verified |
|---|---|
| T1.1 /persona/ traversal | component check (.., leading /, dot-components) + relative_to on both roots; tests/test_persona_traversal.py passes |
| T1.4 /artifacts/ roots | WORKSPACE and BRAIN roots removed, dotfile components rejected, Cache-Control: private; staged media under sessions/<sid>/artifacts/brain/ still served via the SESSIONS root |
| T2.1 IME Enter | e.isComposing \|\| e.keyCode === 229 guard in app.js and slash.js |
| T2.2 events queue | attribute and put_nowait removed; the two tests re-pointed |
| T2.3 stale HTTP turn | seq passed into stream_turn, checked before each hop and each event; _http_resp cleared only when is resp; tests/test_http_adapter_stale_turn.py passes |
| T2.6 stderr redaction | _redact_line applied before _stderr_tail.append, in to_public, _run_btw, and adapter rate_limit_report; tests/test_stderr_redaction.py passes |
| T3.1 finalize_turn | one method on AgentAdapter; five adapters call it; error flag and image append uniform |
| T3.2 regressions | server.py uses identity.user_title() / self_label(); test_status_picker stub has classList; test_conversation_sync patches session_weights.HOME. All three pass |
| T3.3 dependencies | requirements.txt (PyYAML==6.0.3), README "Run tests", /api/roles returns 503 when PyYAML is missing |
| T4 | Content-Length bounds before read (413); do_GET exception boundary; _get_usage provider whitelist (HTTP providers included via AGENT_ADAPTERS.update); kill() followed by wait(timeout=1); grok prompt file unlinked; .mcp.json via _atomic_write_text; corrupt meta.json renamed and logged; ES timer cleared / 20-retry cap; role.js BASE_PATH; dead code removed |

---

## Partial or new concerns

### P1. T2.5 half done

Registry.peek() exists and all four GET routes use it. The second half —
evicting idle sessions from REG.sessions in _reap_sessions — was not
implemented; sessions.pop occurs only in delete(). In-memory growth from
polled-but-idle sessions remains.

### P2. T2.4 delta offset is measured on the wrong string

adapters.py:320 (and the other adapter sites) compute
offset = len(session.current_text) before appending the raw delta, but
the delta text sent to the client goes through _rewrite_artifact_paths.
When a rewrite changes the length (a /volume1/.../brain/x.png →
/artifacts/<sid>/brain/x.png substitution), the client buffer length
diverges from the server offset. If the rewritten text is longer, the client
sees the next delta's offset < assistantBuf.length and drops real text.

Fix: track a separate rewritten-length counter for the offset, or move the
rewrite to the client. Add a test with a delta containing a rewritable path
followed by a plain delta.

### P3. GET / returns 404 on this machine — environmental, not a regression

host_config.STATIC defaults to /volume1/homes/me/services/chatbot/static,
which does not exist on Windows. tests/test_identity_wiring.HttpTest
errors for that reason. Not caused by the audit changes.

### P4. Content-Type check allows an empty header

_read_json rejects a wrong Content-Type but accepts a missing one. With
the origin gate now first, this is not exploitable from a browser; noted for
completeness.

---

## Test results (same Windows machine, python -m unittest discover -s tests)

| | Ran | Failures | Errors | Skipped |
|---|---|---|---|---|
| Before audit | 638 | 27 | 20 | 4 |
| After audit | 649 | 25 | 19 | 4 |

All 44 remaining failures are environmental (symlink privilege, fcntl,
bash with Windows paths, /volume1 defaults, /proc, cp949 console
decoding). The three platform-independent regressions identified in the audit
are resolved. The ticket's claim of "689 tests pass" on the NAS cannot be
verified from here.

---

## Loop observation

Ticket #25 was claimed with paths: None. The charter requires paths on
claim, but tickets.py does not enforce it, so _ship_blockers had nothing
to check and the done gate was a no-op. The done-note asserts a full test
pass and a vendored file; B1 and B2 show neither was verified by anything but
the agent's own statement. This is the same gap as G1 in
[self-evolution-loop-review-2026-09-22.md](./self-evolution-loop-review-2026-09-22.md);
R1 (test gate inside release(done)) would have caught B1 through the
lifecycle/probe tests, and a git ls-files check on claimed paths would have
caught B2.

---

## Housekeeping

- The work-order file was renamed to audit-2026-09-22-work-ordered.md
  during the audit; links in direction-2026-09-22.md and
  self-evolution-loop-review-2026-09-22.md were repointed.
- Persona-specific literal "냥체" remains at server.py:855,864. The identity
  guard test only checks the three names, so it does not fail; it is still a
  baked-in persona detail in host code.
