---
id: 41
title: "Tailscale Funnel /chat 에서 API가 Sphere 허브로 샘"
status: open
type: internal
skill: []
proposes_skill: []
area: "chatbot"
date: 2026-09-22
parked_until:
resolved:
resolution:
reference:
---

https://diskstation.taile611bf.ts.net/chat/ 는 Funnel이 /chat 접두사를 떡 떄고 127.0.0.1:3011 로 보낸다. HTML·./app.js 는 뜻지만 app.js가 fetch('/api/...')·EventSource('/api/...')를 원점 루트로 부르면 https://.../api/ 가 Sphere 허브(8088) HTML을 돌린다. /chat/api/identity·/chat/api/sessions·SSE hello는 200이다. 허브 FAB는 HTTPS에서 origin+'/chat'를 쓴다.
