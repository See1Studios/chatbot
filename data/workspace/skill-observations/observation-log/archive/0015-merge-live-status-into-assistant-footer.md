---
id: 15
title: Duplicate live-status widgets belong on the answering bubble footer
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: none — chatbot workspace UI, no skill-families.md registry
area: static chat UI — live turn chrome
date: 2026-09-18
session_context: 실장님 asked to merge the two top working widgets into the answering window at the token-usage spot, and move the composer stop button there
parked_until:
resolved: 2026-09-18
resolution: Turn elapsed+tool line now renders on the assistant .msg-footer (.turn-live) where the token badge lands when the turn ends. #progress is host-only. Composer no longer has 중지; the same #stopBtn mounts on that footer (meta-bar fallback when not on the chat tab).
reference:
---

**Issue:** While a turn ran, the header showed the same working state twice — a long procBadge sentence and a separate #progress strip — plus a stop button crowding the composer, while the answering bubble already existed.

**Suggested improvement:** One live-status surface, on the assistant footer that already shows per-turn tokens. Move stop there. Keep a compact meta chip and host-only #progress for defibrillate/dead-process.

**Principle:** Live turn chrome belongs next to the message being written, not as duplicate banners above the transcript.
