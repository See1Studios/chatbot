# Direction Recommendations — 2026-09-22

- Status: proposal. Not a work order; nothing here is approved for
  implementation. Concrete fixes live in
  [audit-2026-09-22-work-orders.md](./audit-2026-09-22-work-orders.md).
- Basis: full-repo audit on 2026-09-22 (server, session/adapters, static,
  tests/hygiene) read against docs/concept.md, PRODUCT.md,
  docs/plans/recursive-self-evolution.md (P1–P3), and the observation log.
- Frame: each direction is tied to one axis in docs/concept.md. Order is
  by what unlocks the others, not by effort.

---

## Summary

| # | Direction | Axis (concept.md) | Unlocks |
|---|-----------|---------------------|---------|
| 1 | HTTPS + single-operator auth as the base layer | 언제 어디서나 접속 | clipboard, PWA, push, passkeys; safe Funnel exposure |
| 2 | Machine-enforced verification in the self-evolution loop | 자기 진화 · 자체 개발 | trust to widen self-modification scope |
| 3 | One provider conformance suite | Provider가 바뀌어도 유지되는 Context · 쉬운 Provider 연동 | principle #8 becomes testable |
| 4 | Single source of truth for streaming state | 단절감 없는 대화 경험 | multi-device sync without multiplying bugs |
| 5 | Physically separate core from instance data | 범용화 (plan P1) | deployable to other machines/users |
| 6 | Mobile as a PWA | 디바이스별 지원 밀도 | install, notifications, offline read |

Recommended order: 1 → 2 (foundations); 3 and 4 in parallel; 5 can start any
time (a decision, not code); 6 after 1.

Do not: introduce a web framework or a database. The stdlib single-process
design is the project's real advantage for NAS deployment and for
self-modification legibility. All six directions fit inside it.

---

## 1. HTTPS + single-operator auth as the base layer

Axis: 언제 어디서나 접속 (currently an open axis: "LAN 평문").

Evidence
- The security model is one assumption: "only a browser on the LAN". origin_guard
  covers 2 of ~10 mutating POST routes; /persona/ has a path-traversal;
  /artifacts/ serves the whole workspace; rendered markdown is unsanitized.
- That assumption is already being crossed: chatbot-ctl.sh binds 0.0.0.0,
  observation 0041 documents a Tailscale Funnel experiment, tickets 19–21 made
  the UI work under a /chat mount for exactly that purpose.
- This agent controls the NAS (nas MCP: service_ctl, file write, command run)
  and edits its own code. A breach is not "someone read my chat"; it is host
  compromise.
- PRODUCT.md already records that plaintext HTTP forced a clipboard fallback.

Direction
- TLS is a feature unlock, not only a lock. A secure context enables the
  Clipboard API, PWA install, Web Push (phone notification when a long turn
  finishes), and WebAuthn passkeys. Tailscale Serve issues the certificate for
  free.
- One login for one operator: a passkey (WebAuthn) or, as a first step, a
  single long-lived token exchanged for an HttpOnly cookie. Stdlib is enough;
  no framework.
- Keep origin_guard as defence in depth; the cookie becomes the primary gate.

First steps
1. Work orders Tier 1 (T1.1–T1.4).
2. Tailscale Serve with TLS in front of :3011; drop the plain Funnel.
3. Cookie session + one login page; every /api/* route checks it.
4. Only then re-open the Funnel.

Measure: curl from outside the tailnet gets 401 on every /api/*; the
phone can paste from clipboard without the fallback path.

---

## 2. Machine-enforced verification in the self-evolution loop

Axis: 자기 진화, 자체 개발.

Evidence
- docs/DEVLOG.md (2026-09-21) reports "전체 653건 통과". The audit found 3
  failures that are platform-independent, including the project's own guard
  tests/test_identity_wiring.py (hardcoded "실장님" in server.py:769,775)
  and tests/test_conversation_sync.py whose monkeypatch stopped working after
  the monolith split, so the resume path may be silently broken.
- The loop therefore *reports* verification but does not *enforce* it. The
  three external reviews of recursive-self-evolution.md v2 agreed on the same
  point: the safeguards are not executed by code.
- ctl guard today is one AST check (AgySession.lock is an RLock).

Direction
- Extend chatbot-ctl.sh guard (thin) to call a Python module (per plan P1-4)
  that runs the test subset mapped to the changed files and refuses to accept a
  DEVLOG block when it fails.
- Self-modification output that touches core (server.py, session.py,
  adapters.py, static/) is recorded as unverified in the observation log
  until the suite passes on disk. Instance-layer output (data/workspace/)
  keeps the current lighter path, as plan P1-2 intends.
- Make the mapping data, not code: core_modules.json already exists; add a
  tests_for list per module.

First steps
1. Work orders T3.2 (fix the three regressions) so the suite is a signal again.
2. guard runs python3 -m unittest <mapped tests>; non-zero exit blocks the
   DEVLOG write helper (or the observation MCP tool's verified flag).
3. DEVLOG template gains a machine-written line: verified: <n> tests, <sha>.

Measure: a DEVLOG entry cannot claim a passing count that the guard did not
produce.

---

## 3. One provider conformance suite

Axis: Provider가 바뀌어도 유지되는 Context; 쉬운 Provider 연동;
cross-cutting-principles.md #8 ("identical capability, not just identical
persona").

Evidence
- End-of-turn finalization is copy-pasted in five adapters
  (adapters.py:289, 569, 1097, 1382, 2087) and has drifted: agy/grok append
  images, claude/grok store text: "" on error, codex/http never flag errors on
  the history item. build_env is duplicated four times.
- Principle #8 exists only as prose; no test exercises the same scenario across
  adapters.
- The HTTP adapter has a stale-turn hijack bug (stop during an MCP call) that
  the stdin adapters do not, because each adapter handles cancellation
  differently.

Direction
- One finalize_turn on AgentAdapter (work order T3.1) is the prerequisite.
- Then one conformance suite: a fake subprocess (NDJSON on stdout) and a fake
  HTTP server, driven through the same scenarios for every entry in
  AGENT_ADAPTERS: plain text, tool call + result, image artifact, provider
  error, user stop mid-turn, stop-then-resend, resume by conversation id.
  Assert on the canonical event stream and on history/meta.json, not on
  provider wire format.
- "Adding a provider" is then defined as: one adapter class + the suite passes.
  That is what makes the 쉬운 Provider 연동 axis closable.

First steps
1. T3.1, then T2.3 inside the shared code path.
2. tests/test_adapter_conformance.py parameterized over AGENT_ADAPTERS.

Measure: every adapter produces the same event kinds and history shape for
the same scenario; a new adapter cannot ship with a missing capability
unnoticed.

---

## 4. Single source of truth for streaming state

Axis: 단절감 없는 대화 경험; multi-device sync (observations 0020, 0035).

Evidence
- Three paths update the same turn state in the browser: the EventSource
  (app.js:2621), a 2.5 s session poll (app.js:3192), and a 3 s busy poll
  (app.js:740). They are separate connections with no ordering guarantee.
- Consequences found: delta duplication when a poll lands before its SSE delta;
  a stale reconnect timer tearing down a healthy stream; full markdown re-parse
  of the whole bubble on every delta (O(n²)) plus a full re-render every 2.5 s;
  N tabs × ~0.7 req/s of history JSON against a single Python process.
- Enter during Hangul IME composition sends mid-syllable (app.js:4598) — the
  primary input path of a Korean UI.

Direction
- Server assigns a per-session monotonic seq to every emitted event and
persists it in events.jsonl (the file already exists).
- Client keeps one lastSeq. Reconnect is GET /events?after=<seq>; the
  server replays from the log, then goes live. Deltas carry offset so a
  replayed or duplicated delta is idempotent.
- Polling is demoted to a fallback that runs only while the EventSource is
  CLOSED.
- Rendering: append-only for deltas with a coalesced (requestAnimationFrame)
  full parse; full re-render only on result.

First steps
1. T2.1 (IME) and T2.4 (offset) — small and immediate.
2. seq in _emit + after= replay in _sse.
3. Remove the busy poll; gate the session poll on SSE state.

Measure: a phone that sleeps mid-turn and wakes shows the exact final text
once, with no flicker; two devices on one session converge without either
polling.

---

## 5. Physically separate core from instance data

Axis: 범용화 — plan P1 ("deployable to other OSes and other users; value
generality over personalization").

Evidence
- Tracked in git alongside code: data/workspace/memory/MEMORY.md with a
  family member's name and birth date, a role-play session transcript, tickets,
  observation logs, .impeccable/hook.cache.json, ~50 MB of images with
  byte-identical copies in three directories, and a .psd.
- The test suite is NAS-bound: /volume1 defaults, fcntl, os.symlink,
  bash with POSIX paths, /proc. 44 of 47 failures on a Windows machine are
  environmental. P1-4 already names this ("new logic does not grow in the
  OS-bound shell; locks behind one function").

Direction
- Repo = core + templates/. Instance data (data/) lives outside the repo or
  is fully gitignored; first run copies templates (the PERSONA.md path
  already does this).
- Platform-dependent operations (file lock, process scan, symlink, ctl) behind
  one small module with a POSIX implementation now and a documented seam.
- Define P1's success metric as: **the full suite passes on one non-NAS
  machine**. Until then generality is a slogan.

First steps
1. Operator decision on work-orders Tier 5 (history rewrite for the PII).
2. .gitignore for runtime state; git rm --cached.
3. tests/ fixtures use tempfile + env overrides instead of /volume1
   defaults; symlink-dependent tests skip when the platform cannot symlink.

Measure: git ls-files data/ returns only templates and README; CI-style
run on a laptop is green.

---

## 6. Mobile as a PWA

Axis: 디바이스별 지원 밀도; 언제 어디서나 사용 중인 디바이스 기준으로 지원.

Evidence
- Mobile is a first-class surface (PRODUCT.md; separate composer layout;
  viewport code in app.js:4514+), but every visit is a browser tab with no
  install, no notification, no offline read.
- Everything needed is blocked only by the missing secure context (direction 1).

Direction
- manifest.json + a minimal service worker (cache static/, network-first for
  /api/). No offline write; offline = read the last session.
- Web Push for "turn finished" and "session rotated" while the app is in the
  background. The server already knows both moments (result event,
  _rotate_to_fresh_session).
- Nothing else: no native wrapper, no separate mobile bundle.

First steps (after direction 1)
1. Manifest + icons from data/persona/ (already have icon.webp).
2. Service worker with static cache only.
3. Push subscription endpoint + one notify() call at result.

Measure: install from Safari/Chrome on a phone; a long turn started at the
desk produces a phone notification.

---

## What this deliberately leaves out

- Web framework, ORM, database, build step for static/: not needed for any of
  the six; each would add a dependency the NAS and the self-modifying agent
  must then understand.
- Multi-user: P1 says structure for it, do not build it. Direction 1's
  single-operator auth is compatible with adding users later (cookie → user id).
- Further splitting static/app.js: docs/plans/monolith-split.md forbids it;
  direction 4 reduces its state without moving code between files.
