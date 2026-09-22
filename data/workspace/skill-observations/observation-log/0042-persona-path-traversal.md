---
id: 42
title: "/persona/ 경로 탐색"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "security"
date: 2026-09-22
parked_until:
resolved: 2026-09-22
resolution: "rel_p에 ..·절대·점 성분 거부. resolve 후 DATA/persona 또는 WEB_ROOT/chat/persona 하위만 200. tests.test_persona_traversal. needs ⚡소생."
reference: "audit-2026-09-22 T1.1"
---

GET /persona/../server.py 가 http.server에서 ..를 접지 않아 data 밖으로 읽힐 수 있었음. 아바타 200은 유지.
