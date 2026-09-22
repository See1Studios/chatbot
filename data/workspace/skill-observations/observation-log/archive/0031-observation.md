---
id: 31
title: "최신 대화로 버튼이 과거 세션 열람 중에는 스크롤만 하고 실제 최신 세션으로 안 간다"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "ui"
date: 2026-09-21
parked_until:
resolved: 2026-09-21
resolution: "goToLatestConversation()가 최신 세션 id를 풀어 현재와 다르면 openSession으로 점프, 같으면 스크롤. 플로팅 버튼과 헤더 [최신 ⇥]가 같은 함수. 과거 열람 중엔 로그 바닥에서도 버튼 유지. app.js?v=92. 정적만, 새로고침."
reference:
---

**Issue:** 실장님: "이전 세션을 둘러보다가 최신 대화로 를 눌러도 최신 대화가 로딩안되있다면 실제로 최신대화로 가지 않네." 플로팅 #scrollToBottomBtn은 logEl.scrollTo(바닥)만 했다. 과거 세션 열람 중이면 그 바닥은 옛 대화의 끝이라, 아직 불러오지 않은 최신 세션으로는 가지 않는다. 헤더 [최신 ⇥]만 openSession 점프를 했다.

**Suggested improvement:** 버튼이 최신 세션 id를 풀어 현재와 다르면 openSession으로 점프, 같으면 스크롤. 과거 열람 중이면 로그 바닥에 있어도 버튼을 남겨 둔다.

**Principle:** 단절감 없는 대화 경험. “최신 대화로”는 화면 바닥이 아니라 지금 이어야 할 대화로 간다.
