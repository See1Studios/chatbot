---
id: 1
title: Sphere Chatbot UI Markdown Engine & Mermaid Diagram Rendering Support
status: actioned
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none
area: Web UI & Markdown Rendering
date: 2026-09-16
session_context: Self-improvement workflow discussion in Sphere Chatbot UI (migrated from legacy log.md, Observation 1)
resolved: 2026-09-16
resolution: Vendored marked.min.js + mermaid.min.js locally, upgraded markdown CSS, wired renderMermaidIn()/attachCodeCopyButtons() into the stream-result path.
reference:
---

**Issue:** `renderMarkdown()` relied on basic regexes that turned triple-backtick blocks into `<pre><code>`. Mermaid fenced blocks (` ```mermaid `) rendered as raw text instead of diagrams.

**Suggested improvement:** For any agent-facing chat UI that renders LLM markdown output, locally vendor a markdown parser + diagram renderer (not CDN-only) and route fenced `mermaid` blocks to the renderer explicitly, with progressive re-render on stream completion.

**Principle:** Web chat interfaces must integrate client-side markdown parsers and diagram renderers (marked.js + mermaid.js) locally vendored on the host, with graceful progressive rendering during streams.
