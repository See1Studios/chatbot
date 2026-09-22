---
id: 30
title: "Browser-side device context bound into conversation prompt"
status: open
type: internal
skill: []
proposes_skill: []
area: "client-device-context"
date: 2026-09-21
parked_until:
resolved:
resolution:
reference:
---

**Issue:** Agent previously had no awareness of client GPS location, timezone, or device type unless explicitly mentioned by user.

**Suggested improvement:** Bind browser-side device context (GPS lat/lon, timezone, mobile/desktop) with a privacy toggle in UI, inject concise prompt metadata on message send, and persist through session rotations without token bloat.

**Principle:** Support user tasks based on real-time device context anywhere while respecting privacy and keeping prompt token usage minimal.
