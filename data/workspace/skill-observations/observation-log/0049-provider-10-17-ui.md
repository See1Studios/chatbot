---
id: 49
title: "provider 전환 요청이 10~17초 걸려 UI가 재시도로 쌓임"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "chatbot"
date: 2026-09-23
parked_until:
resolved: 2026-09-23
resolution: "티켓 #50(af4c0d1): 즉시 응답 + 모델 요약은 백그라운드 교체(session.handoff_refined)"
reference:
---

측정: 12:03:55~12:04:06 POST /api/sessions/:sid/provider 5건, 9.7~17.2초, 2건은 클라이언트 이탈(근거 log:rid:67b6f94c05ea, log:rid:ef927caf81b0).
원인: maybe_swap_provider가 인수인계 요약을 요청 안에서 동기로 생성(agy /compact 최대 45초, 대체 요약도 agy 호출 최대 12초).
