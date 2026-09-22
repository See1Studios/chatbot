---
target: static/index.html
total_score: 30
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/volume1/homes/me/services/chatbot/static/index.html"
target_fingerprint: "sha256:6a4113b8326b5f82bdfc02fcea340e8188a645bca328e5a174044119331e209b"
target_path: /volume1/homes/me/services/chatbot/static/index.html
timestamp: 2026-09-17T02-13-50Z
slug: static-index-html
closed: true
---
# Critique: static/index.html (냥피디 chatbot UI)
Method: dual-agent (A: design review · B: detector+browser evidence). No browser automation tool was available in this environment; both assessments are static-analysis only (no rendered screenshots, no console logs).

## Design Health Score — 30/40 (Good)

| # | Heuristic | Score | Key Finding |
|---|---|---|---|
| 1 | Visibility of System Status | 3/4 | #progress visible regardless of tab; hard-session redirect only logged to 로그 tab, not surfaced in 대화 |
| 2 | Match System/Real World | 4/4 | Korean-native labels, mascot voice, domain terms map to real mental models |
| 3 | User Control and Freedom | 2/4 | No undo after session-delete confirm; no back navigation outside 세션 tab |
| 4 | Consistency and Standards | 3/4 | Button classes consistent; native confirm()/alert() breaks from the custom modal system |
| 5 | Error Prevention | 2/4 | Good delete-confirm copy; session switch wipes an unsent composer draft with no warning |
| 6 | Recognition Rather Than Recall | 3/4 | Slash menu shows name+description; token badges are hover-only tooltips |
| 7 | Flexibility and Efficiency | 1/4 | Only Enter/Escape shortcuts exist app-wide; thin for a daily power-user tool |
| 8 | Aesthetic and Minimalist Design | 3/4 | Coherent dark theme; header bar packs 8 top-level controls (own code comment admits past crowding) |
| 9 | Error Recovery | 3/4 | Errors get a distinct prefix/color; many caught errors route only to the non-default 로그 tab |
| 10 | Help and Documentation | 1/4 | No help affordance or onboarding anywhere |

## Design Specificity Verdict
Grounded, not generic: 9-layer Live2D-style cat mascot with breathing/blink/talk animation, Korean persona voice, NAS-specific "⚡소생" defibrillate action, and dashboard-specific tab set (아티팩트/로그/상태/세션). Shared sphere-theme.css tokens across the host are appropriate reuse.

Deterministic scan (`impeccable detect` on index.html): 6 findings / 3 rules.
- `layout-transition` (1): .mascot-overlay transitions width/height/left/right alongside opacity/transform — real layout-thrash risk.
- `clipped-overflow-container` (3): html/body flags are likely false positives (fixed-position viewport propagation); `div.wrap clips a positioned child` is likely real — #slashMenu (position:absolute) sits inside overflow:hidden .wrap and can be clipped.
- `gpt-thin-border-wide-shadow` (2): slash-menu and mascot-bubble both pair a 1px border with a wide shadow blur — advisory/stylistic, not a functional bug.

## Overall Impression
Character and tone are genuinely present, and real engineering judgment shows (SSE reconnect resilience, compact-mode reuse discipline). The biggest gap is that a tool positioned as a daily power-user surface has almost no keyboard/accessibility support and no help affordance, and several session-transition moments erode trust by happening silently.

## What's Working
1. Mascot as a real status affordance, not decoration — talk/blink/breathing animations are wired to actual interaction state.
2. SSE reconnection is genuinely production-grade: exponential backoff, visible "연결 끊김 · 재연결 중…", and resyncFromServer on reconnect to recover missed messages.
3. Compact mode reuses the same page instead of forking a second FAB implementation — avoids drift between two UIs.

## Priority Issues

**[P0] Silent hard-session redirect has no in-chat explanation**
- What: maybeRedirectHardSession can move the user to a different session's content with the explanation only logged to the non-default 로그 tab.
- Why it matters: user can't tell whether their earlier conversation is lost.
- Fix: surface the existing showSessionHeavyBanner('hard', …) treatment on this redirect-on-open path too, in the 대화 tab itself.
- Suggested command: /impeccable clarify

**[P1] Native confirm()/alert() break the custom modal system**
- What: session delete, MCP delete, and defibrillate all use native browser dialogs while everything else is a styled dark modal (#artModal).
- Why it matters: jarring tone break and inconsistent with the app's own Escape-key model.
- Fix: route these through the existing modal pattern with a styled confirm card.
- Suggested command: /impeccable harden

**[P1] Near-zero keyboard support for a daily power-user tool**
- What: only Enter-to-send and Escape exist app-wide; no tab-switch shortcut, no focus-composer shortcut, no new-session shortcut.
- Why it matters: directly underserves the tool's own stated daily operator.
- Fix: add a small shortcut layer (Cmd/Ctrl+1..5 for tabs, global focus-composer).
- Suggested command: /impeccable optimize

**[P2] Header decision density (8 top-level controls before typing anything)**
- What: 5 tabs + mascot toggle + 소생 + 새 세션 all in one bar; the CSS's own comment admits this was a prior crowding problem only half-fixed.
- Fix: collapse 소생/session-management into an overflow/kebab menu.
- Suggested command: /impeccable distill

**[P3] No visible help/onboarding affordance**
- What: no /help-style command, no tab explainer for a first-time or returning-after-months user.
- Fix: add a lightweight /help slash entry and/or first-visit tooltip pass.
- Suggested command: /impeccable document

## Persona Red Flags

**Alex (Power User)**: Tab buttons have no role="tab"/aria-selected (only the container has role="tablist") — keyboard tab navigation isn't semantically wired. Session-delete confirm can't be dismissed with the same Escape reflex that works everywhere else.

**Sam (Accessibility-Dependent)**: Tab panels have no aria-controls/role="tabpanel" — a screen reader announces five generic buttons with no indication of what they control. Token info is title-tooltip only, unreachable by keyboard/screen reader. Zero custom :focus styling anywhere in index.html or sphere-theme.css — focus visibility on the dark custom backgrounds relies entirely on browser defaults, unverified.

## Minor Observations
- `compact-mode` CSS class is added by JS but has no matching selector anywhere — dead code (compact mode actually works via inline style.display toggles).
- Queued-message state ("(대기열 대기 중)") is communicated via CSS ::after content only — invisible to screen readers.
- The session-heavy banner's "완전 새 세션" (drops all continuity) and "맥락 이어 새 대화" read as equally weighted — the higher-consequence option has no visual de-emphasis.
- .mascot-overlay transitions width/height/left/right alongside transform (detector-confirmed) — real layout-thrash risk; prefer transform-only.
- #slashMenu sits inside overflow:hidden .wrap and may get clipped (detector-confirmed) — worth fixing alongside the slash menu's own 17-item chunking overload.

## Questions to Consider
- What if the hard-session rotation became a visible, reassuring moment (mascot explains + links back) instead of a silent background hop?
- What if 상태/세션 collapsed into one "Host" menu and the primary tab bar shrank to 대화/아티팩트/로그 — would anything actually be missed?
- What if the 17-command slash menu were ordered by actual usage frequency instead of static category?
