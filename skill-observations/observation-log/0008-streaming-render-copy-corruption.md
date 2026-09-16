---
id: 8
title: "Copying text from a still-streaming/unrefreshed assistant bubble can yield garbled clipboard content"
status: superseded
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none (no skill-families.md registry in this workspace)
area: Web UI — streaming markdown re-render vs. text selection
date: 2026-09-16
session_context: 실장님 reported "응답이 이상하게 와" and pasted scrambled text that looked like assistant prose but was stored in the session JSON as role:"user" (session 20260916-143838-7efe85, message index 9). Investigated by reading the raw session JSON directly (server-stored history was intact/uncorrupted for all real assistant turns). 실장님 then clarified: "내가 붙여넣은 거야" — they had copy-pasted text out of an assistant bubble themselves, and a page refresh made the same bubble copy/read correctly again ("새로고침하니 정상으로 바뀌었어").
resolved: 2026-09-16
resolution: Superseded by 0007-sse-multiclient-delta-cannibalization.md, which the chatbot's own self-improvement loop found and applied independently (and correctly) in the same window: the real cause was multiple SSE subscribers sharing one `queue.Queue`, alternately stealing stream-delta events from each other (multi-tab / FAB+full-page / reconnect races), not a DOM re-render/copy-selection artifact. The exact drop pattern ("Google Imagen 3" -> "Goo ... ge`)") matches an alternating 50/50 event-loss partition, not a selection-boundary artifact. Filed here for the record since this hypothesis was investigated and reported to 실장님 before the correct root cause surfaced.
reference:
---

**Issue:** No server-side or model-side data corruption occurred — every stored assistant message in the session (verified via direct JSON read on disk) is well-formed, valid UTF-8, coherent prose. The corruption only appeared in text the user copy-pasted out of a message bubble in the live (not-yet-refreshed) page, and disappeared once the page was refreshed (which re-fetches `/api/sessions/:id` and renders `history` fresh in one pass). This strongly points to `renderMarkdown()`'s incremental re-render during SSE streaming (re-parsing the growing text buffer on every chunk, per observation 0001/0002's markdown+progress-bar work) leaving the message bubble's DOM in a state where a `document.getSelection()`-based copy grabs stale/duplicated/out-of-order text nodes, even though the visually-rendered final text looks correct on screen. 실장님's own working theory ("텍스트가 스트리밍되면서 생긴 문제가 아닐까") matches this.

**Suggested improvement:** After the stream's final chunk (`isFinal = true`), do one clean, complete re-render of the message bubble's innerHTML from the final accumulated text (fully replacing prior incremental DOM, not patching it) before the user can interact with it — or, cheaper: normalize text selection by keeping the source markdown string in a `data-raw` attribute and overriding `copy`/`cut` events on message bubbles to use that raw string instead of relying on `document.getSelection()` over live-mutated DOM. Either fix only needs to touch the assistant-bubble finalize path in `app.js`, not the storage/transport layer (which is already correct).

**Principle:** A DOM that is being incrementally rewritten to show streaming progress can render correctly to the eye while still being unsafe to copy from — native browser text selection walks the actual DOM tree, not the "logical" final string, so any UI that re-parses/re-renders markdown mid-stream needs an explicit "finalize" pass (full clean re-render, or a raw-text copy override) before treating the bubble as stable, or it needs to swap in the clean final render as an atomic replace rather than patching incrementally, especially for interactive elements like copy-paste that don't route through the app's own event handlers.
