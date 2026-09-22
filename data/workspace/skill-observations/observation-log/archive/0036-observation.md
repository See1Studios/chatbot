---
id: 36
title: "최신 대화로 버튼이 과거 열람·위로 스크롤 후에 또 고장"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "ui"
date: 2026-09-21
parked_until:
resolved: 2026-09-21
resolution: "세션 id 최댓값+successor 체인으로 점프. 같은 세션이면 instant pin(스무드 스크롤 제거, 600ms 히스토리 로드 억제). 버튼을 .stage-shell 오버레이로 옮겨 모바일 탭이 #log에 먹히지 않게. app.js?v=98 chat.css?v=20. 정적만, 새로고침."
reference:
---

실장님: "최신 대화로 이동하는 버튼이 고장났어". 이전 점프 함수는 붙였지만 (1) /api/sessions 첫 항목이 mtime이라 과거 세션을 열면 그게 최신으로 처지고 (2) 같은 세션에서 위로 올린 뒤 스무드 스크롤이 loadNewerHistory와 레이스해 중간에 멈추고 (3) 모바일에서 버튼이 #log 스크롤 레이어 안에 있어 탭이 삼켜질 수 있었다. 세션 id 최댓값+체인 점프, instant pin, 버튼을 .stage-쉘 오버레이로 옮김.
