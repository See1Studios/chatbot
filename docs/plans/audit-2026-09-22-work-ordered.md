# Audit 2026-09-22 — Work Orders

Self-contained tasks for an executing agent. Each task is independent unless
stated. Pick one, do only that, verify, log, stop.

## Ground rules (read once)

- Read docs/concept.md and data/workspace/SELF-MODIFY.md first.
- Python host modules (server.py, session.py, adapters.py, ...) are edited
  on disk only. Never run chatbot-ctl.sh stop|restart|repair. Finish with
  "needs ⚡소생" in your report.
- Static files (static/): edit + bump the ?v=N cache-buster in
  static/index.html for every file you touched. No restart.
- AgySession.lock stays threading.RLock (ctl guard checks this by AST).
- Do not split static/app.js into more files (docs/plans/monolith-split.md).
- Surgical diffs. No adjacent cleanup, no renames, no new abstractions beyond
  what the task names.
- Verify: python3 -m py_compile <files> and/or node --check static/app.js,
  then python3 -m unittest discover -s tests -p "test_*.py" (on the NAS; on
  Windows ~47 tests fail for environment reasons — compare against baseline,
  not against zero). ~/services/chatbot-ctl.sh guard when Python changed.
- Done = one docs/DEVLOG.md block (date, background, change, tests) and one
  line in data/workspace/skill-observations/observation-log/.

---

## Tier 1 — Security (do these first, any order)

### T1.1 /persona/ path traversal

- File: server.py:594-602 (do_GET, /chat/persona/ + /persona/ branch).
- Defect: rel_p is joined to DATA / "persona" with no .. check;
  http.server does not normalize ... GET /persona/../../../../.gemini/...
  reads any file the process can read.
- Change: after computing rel_p, reject if ".." in rel_p.split("/"),
  rel_p.startswith(("/", "\\")), or any component starts with .. After
  .resolve(), require fp_p.is_relative_to((DATA / "persona").resolve())
  (and the same for the WEB_ROOT / "chat" / "persona" fallback). Return 404
  otherwise. Mirror the existing check at server.py:606.
- Verify: add tests/test_persona_traversal.py — one test that
  GET /persona/../server.py (send the raw path via http.client, not
  urllib, so .. is not normalized client-side) returns 404, one that an
  existing avatar still returns 200.

### T1.2 Sanitize rendered markdown (XSS)

- Files: static/markdown.js:242-280 (renderMarkdown), :18-23
  (ensureMermaidLoaded); sinks at static/app.js:1112,1144,1169,
  static/artifacts.js:270.
- Defect: marked.parse output goes to innerHTML unsanitized. javascript:
  hrefs pass through the <a> rewrite. Mermaid uses securityLevel: 'loose'.
  The non-marked fallback (:269-278) does not escape < and injects alt
  unescaped.
- Change:
  1. Vendor DOMPurify into static/vendor/purify.min.js; load it in
     static/index.html before markdown.js.
  2. In renderMarkdown, after all string rewrites, return
     DOMPurify.sanitize(html, { ADD_ATTR: ['target','loading'], ALLOWED_URI_REGEXP: /^(?:https?|mailto|\/|\.\/|#)/i }).
     Keep class="local-file-link" and class="mermaid" working (check
     DOMPurify does not strip them; extend config if it does).
  3. securityLevel: 'strict' for mermaid.
  4. Fallback branch: escape <, >, &, " in text and in alt.
- Verify: Node harness test (pattern: tests/test_choice_chips.py) that
  renderMarkdown('<img src=x onerror=alert(1)>') contains no onerror, that
  [x](javascript:alert(1)) yields no javascript: href, and that a normal
  image/link/code block/mermaid block still renders the same tags as before.
  Bump markdown.js and index.html cache-busters.

### T1.3 Same-origin gate on every mutating POST

- Files: server.py:633-638 (_read_json), :650-856 (do_POST),
  origin_guard.py.
- Defect: only /api/observations|tickets (:703) and
  /api/host/defibrillate (:714) call origin_guard.same_origin.
  /api/sessions/<sid>/message, /api/mcp, /api/skills/*/toggle,
  /api/roles, /api/sessions, /api/accounts/recycle, /stop, /discard
  accept cross-site no-cors POSTs (no preflight because Content-Type is not
  checked).
- Change: at the top of do_POST, before routing, one guard:
  if not origin_guard.same_origin(Origin, Host, Sec-Fetch-Site): 403.
  Keep the two existing call sites (harmless). Also in _read_json, require
  Content-Type to start with application/json (return 415 otherwise) —
  this alone forces a CORS preflight for every JSON body. Confirm the Hub FAB
  (<web root>/index.html, outside this repo) and static/live.html send
  Content-Type: application/json and a same-origin Origin; if the FAB is
  served from http://diskstation/ and the API from :3011,
  origin_guard.same_origin must keep treating same-hostname/different-port as
  allowed (read the origin_guard.py docstring; do not weaken beyond that).
- Verify: tests/test_origin_guard*.py (extend or add): POST
  /api/sessions/x/message with Origin: http://evil → 403; with matching
  Origin → not 403; with no Origin and Sec-Fetch-Site: cross-site → 403;
  curl with no Origin at all (scripts/probe) → allowed if that is the current
  same_origin contract.

### T1.4 Restrict /artifacts/ to artifact directories

- Files: artifact_manager.py:44-90 (_safe_artifact_rel), :124-137
  (basename fallback); server.py:585-592.
- Defect: candidate roots include the whole WORKSPACE and whole BRAIN,
  dotfiles included, served with Cache-Control: public. Basename fallback
  rglobs BRAIN on every miss.
- Change:
  1. Reject any path component starting with ..
  2. Replace the WORKSPACE root with WORKSPACE / "artifacts" (verify by grep
     which subdirs the UI actually links: grep -rn "artifacts/" static/*.js
     session.py media_handler.py; include only those).
  3. For BRAIN, allow only the per-conversation media subtree that
     media_handler.py stages (find the exact dir it writes to and allow that
     root, nothing wider).
  4. Basename fallback: restrict rglob roots to ARTIFACTS_CACHE and
     DATA / "persona"; drop BRAIN and WORKSPACE from the walk.
  5. server.py:592: Cache-Control: private, max-age=3600.
- Verify: add to tests/test_artifact*.py: /artifacts/.gemini/config/mcp_config.json
  → 404, /artifacts/PRIVATE.md → 404, an existing session image → 200,
  persona gallery image → 200. Open a real past session with images in the
  browser and confirm they still load.

---

## Tier 2 — User-visible bugs

### T2.1 Enter during IME composition

- Files: static/app.js:4597-4598, static/slash.js:224-229.
- Defect: Enter sends while a Hangul syllable is still composing; last jamo
  remains in the cleared textarea.
- Change: in both keydown handlers, first line:
  if (e.isComposing || e.keyCode === 229) return;.
- Verify: node --check; manual: type 안녕하세요, press Enter without a
  pause — no stray character remains, one message sent. Bump app.js,
  slash.js cache-busters.

### T2.2 Remove the unconsumed events queue

- Files: session.py:144, :250; tests tests/test_session_swap.py,
  tests/test_turn_observation.py (they read sess.events).
- Defect: unbounded queue.Queue receives every event for the process
  lifetime; production has no consumer.
- Change: delete the attribute and the put_nowait. Update the two tests
  to subscribe via the same path the server uses (subscribers list; see
  server.py:987) — add a 5-line helper in the test, not in session.py.
- Verify: full unittest run; the two test files pass.

### T2.3 Stale HTTP turn hijacks the next turn
- Files: session.py:852-868 (_run_http_turn), :1492 (_send_direct
  resets _stop_requested), adapters.py:2010-2113 (stream_turn), :2003
  (_stream_once finally), :1542 (_mcp_call_tool).
- Defect: stop during an MCP tool call does not cancel the thread; when
  it resumes it writes into the next turn's current_text/history and clears
  busy. _stream_once unconditionally nulls session._http_resp.
- Change:
  1. Capture seq = self._turn_seq when _run_http_turn starts; pass it to
     stream_turn. Before each hop (each urlopen, each tool call) and before
     handling each yielded event: if session._turn_seq != seq: return.
  2. _stream_once finally: if session._http_resp is resp: session._http_resp = None.
  3. Ensure _send_direct increments _turn_seq before starting the new
     thread (check; it may already for the watchdog).
- Verify: new test in tests/test_http_adapter*.py: fake adapter whose
  first hop blocks on an Event; call stop(), send a second message, release
  the event; assert history has exactly one assistant entry for turn 2 and
  busy is False only after turn 2's result.

### T2.4 Delta duplication between SSE and poll

- Files: static/app.js:3141-3149 (resyncFromServer), :2653
  (bindEvents delta), :2662 (result).
- Defect: poll may deliver draft including delta N before SSE delivers
  delta N; client then appends N again.
- Change (smallest): server emits delta with a cumulative offset
  (length of current_text before append; adapters adapters.py:250,271,495
  already have the value). Client: on delta, if (offset < assistantBuf.length)
  return; else append. On resync, keep the existing
  draft.length >= assistantBuf.length rule. If adding a field to five
  adapter sites is too wide, do T3.1 first and add it once.
- Verify: Node harness test feeding delta(offset 0,"ab"), resync draft
  "abc", delta(offset 2,"c") → buffer "abc". Manual: long reply on a phone
  shows no repeated fragments.

### T2.5 Registry.get must not create sessions on read

- Files: session.py:1995-2002, callers server.py:365,391,418,576,751,972,
  session.py:2136 (_reap_sessions).
- Change: add Registry.peek(sid) returning None when neither in memory
  nor meta.json on disk. Use peek for all GET routes → 404. Keep get
  (create) only for POST /api/sessions and the message route if that route
  is meant to auto-create (check tests/ for that contract first). In
  _reap_sessions, after killing an idle process, del self.sessions[sid] if
  no subscribers.
- Verify: GET /api/sessions/nonexistent → 404 and REG.sessions length
  unchanged (unit test); existing session tests pass.

### T2.6 Filter stderr before storing

- Files: session.py:895-911, :1035 (_run_btw stderr), :1780
  (to_public debug_stderr_tail), adapters.py:358,687
  (rate_limit_report proc.stderr[:400]).
- Change: move the token/authorization/bearer/api_key/refresh check to
  before _stderr_tail.append; apply the same one-line filter (extract a
  module-level _redact_line(s) in session.py) at the other three sites.
- Verify: test: feed a stderr line containing Bearer abc → not in
  to_public()["debug_stderr_tail"].

---

## Tier 3 — Structure (do T3.1 before T2.4 if both are planned)

### T3.1 One finalize_turn for all adapters

- Files: adapters.py:289-332 (agy), :569-596 (claude), :1097-1128
  (grok), :1382-1403 (codex), :2087-2112 (http).
- Defect: end-of-turn block is copied five times and has drifted
  (agy/grok append pending images; claude/grok write text: "" on error;
  codex/http never flag errors on the hist item).
- Change: `AgentAdapter.finalize_turn(session, text, raw_usage, is_err,
error, served_model, images=None) doing: artifact path rewrite → usage
  normalize → duration → hist item → stamp_served_model → append + save_meta
  → clear current_text → build result. Behaviour must be the union that is
  correct: images appended when present, error flagged on hist for all five.
  Replace the five blocks with calls. Do not touch anything else in those
  methods.
- **Verify**: full unittest; diff events.jsonl of a probe turn before/after
  for each provider (chatbot-ctl.sh probe) — same keys.

### T3.2 Fix the three real test regressions

1. tests/test_identity_wiring.py — server.py:769,775 hardcode "실장님".
   Build the string from identity.user_title() (see identity.py). Keep the
   Korean sentence, substitute the title.
2. tests/test_status_picker.py:26 — harness button() stub lacks
   classList; static/app.js:2055 uses it. Add classList: {add(){},remove(){},toggle(){}}
   to the stub (test-only change).
3. tests/test_conversation_sync.py — patches session.HOME but
   _conversation_db_path moved to session_weights.py:25-28. Patch
   session_weights.HOME (or both). Then **run it and read the result**: if it
   still fails, the resume path is genuinely broken — stop and report, do not
   paper over.

### T3.3 Dependency manifest

- Add requirements.txt with PyYAML (pin to the version installed on the
  NAS: python3 -c "import yaml; print(yaml.version)"), and a
  README.md "Run tests" section: Python version on the NAS, node needed
  for tests/test_*_ui*.py, and the ../nas-mcp sibling expectation from
  tests/test_nas_mcp_host.py:15. Wrap the three lazy import yaml in
  server.py:479,521,651 so /api/roles returns a 503 with a clear message
  instead of a traceback when PyYAML is missing.

---

## Tier 4 — Small, independent, low risk

- server.py:633-638 _read_json: check Content-Length bounds (0 <= n <=
  200_000) **before** rfile.read; 413 otherwise.
- server.py:243 do_GET: wrap the body in the same try/except that
  do_POST uses; ValueError from REG.get → 400, OSError → 404/500.
- server.py:89-102 _get_usage: validate provider in AGENT_ADAPTERS
  (or providers.json ids) → 400 otherwise; never cache unknown keys.
- session.py:1712-1718, :1663-1671, :2159-2167, standby_pool.py:78-80:
  every proc.kill() followed by proc.wait(timeout=1) in a try/except.
- adapters.py:989 grok prompt file: delete it in the one-shot reader's
  finally (session.py:736 region) once the process has exited.
- adapters.py:407 _write_mcp_config: write via _atomic_write_text
  (artifact_manager.py:30) and only when content differs.
- session.py:187-209 _load_meta: on parse failure log and rename to
  meta.json.corrupt-<ts> before starting empty.
- static/app.js:2621 bindEvents: clearTimeout(window.__agyEsTimer) at
  the top; give up reconnecting after 20 consecutive failures with a visible
  notice.
- static/role.js:34-38,290: use BASE_PATH from app.js (api() helper)
  instead of absolute /api/roles and /?role=.
- Dead code (grep-verified zero callers): effort_levels (adapters.py:127,
  692,1192,1450,1776), OpenAIDialectAdapter.meta (:1677),
  _grok_media_dir/_stage_grok_rel_media (session.py:718,721), unused
  imports session.py:30-49 (HARD_*, SOFT_*, BRAIN). Delete only after
  re-running the grep yourself.

---

## Tier 5 — Repo hygiene (operator decision; do not execute without approval)

- data/workspace/memory/MEMORY.md lines 7-8 contain a family member's name
  and birth date. Suggest: move to a gitignored file, rewrite the 7-commit
  history, force-push.
- Runtime state tracked in git: data/workspace/skill-observations/tickets/,
  observation-log/, last-review-date.txt, log.md.migrated`,
.impeccable/hook.cache.json,
  data/workspace/.agents/skills/character-chat/sessions/*.json. Suggest
  .gitignore entries + git rm --cached.
- ~50 MB of images with byte-identical copies under data/persona/,
  data/persona/gallery/, data/sessions/_shared/brain/, plus a .psd.
  Suggest: keep one copy, or move originals to a release asset.
- Personal emails at docs/DEVLOG.md:787, docs/providers/codex.md:29; public
  Tailscale hostname at observation-log/0041-*.md:16.

---

## Reporting template (append to docs/DEVLOG.md)


```
## <YYYY-MM-DD> — <task id> <one-line title>
- Background: <defect, file:line>
- Change: <what, where>
- Tests: <added/updated test names>, <unittest summary line>, guard OK
- Deploy: static → hard refresh | python → needs ⚡소생
- Not done / open: <anything left>
- ```
