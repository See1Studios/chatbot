---
id: 35
title: "Chat syncs across devices but provider chrome stays per-device localStorage"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "static app.js multi-device provider"
date: 2026-09-21
parked_until:
resolved: 2026-09-21
resolution: "세션 provider/model이 SSOT. applySessionProvider를 열기·resync·생성/인계에 적용. 전송은 UI가 서버 캐시와 다를 때만 provider/model을 실음. app.js?v=96. 정적만, 양쪽 기기 새로고침."
reference:
---

실장님 “서로 다른 디바이스에서 채팅은 동기화되는데 프로바이더가 동기화 안되네”. GET 세션 히스토리는 2.5초 resync가 맞추는데, 초상·테마·캡션은 chatbot.provider localStorage라 기기마다 달랐다. send()가 UI provider를 매 턴 POST해서 낡은 기기가 라이브 세션을 되돌릴 수 있었다.
