---
id: 17
title: Persona gallery listed under /artifacts/<basename> 404s
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI/server, no skill-families.md registry
area: server.py get_artifacts / _safe_artifact_rel + static artifacts tab
date: 2026-09-18
session_context: 실장님 asked the chatbot to self-improve; live logs showed repeated GET /artifacts/01-avatar.png 404 while the artifacts tab was polling
parked_until:
resolved: 2026-09-18
resolution: Fixed listing URLs, added persona/basename serving fallbacks, client onerror retry, and retargeted static/chat/persona. Live thumbs need Ctrl+Shift+R; server listing/old-markdown URLs need ⚡소생.
reference:
---

**Issue:** `get_artifacts()` scanned `data/persona/gallery` and `workspace/artifacts` but emitted `/artifacts/<filename>` with no subdirectory. `_safe_artifact_rel` only looked in `_shared`, workspace/artifacts (exact rel), sessions, and brain — so gallery files 404'd (`01-avatar.png`, `02-half.png`, `06-casual-studio.jpg`) and `sei-portrait.png` 404'd because it lives in `workspace/artifacts/persona/`. `static/chat/persona` was also a dangling symlink to the retired `chatbot-data/persona` path.

**Suggested improvement:** Emit `/persona/gallery/<name>` for gallery files and `/artifacts/<rel>` for workspace/artifacts; add persona + basename fallbacks in `_safe_artifact_rel` so old chat-history markdown still resolves after ⚡소생. Client `bindArtifactImg` retries those same fallbacks so the live host (pre-소생) already shows thumbs. Retarget `static/chat/persona` at `data/persona`.

**Principle:** A listing endpoint must emit URLs the same process can actually serve. If a scan root is not one of the serving roots, either add the serving path or change the listed URL — never join `/artifacts/` to a basename from a different tree.
