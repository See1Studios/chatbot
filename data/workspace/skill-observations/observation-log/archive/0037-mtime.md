---
id: 37
title: "최신 대화·동기화·과거 열람이 mtime과 썸질로 충돌"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "ui"
date: 2026-09-21
parked_until:
resolved: 2026-09-21
resolution: "get_active를 세션 id+successor 끝으로. 클라이언트 liveSessionId/archiveBrowse. 버튼은 라이브+바닥만 숨김. 동기화는 과거 열람 중이 아니면 라이브 follow. app.js?v=100. session.py 소생 필요."
reference:
---

실장님: 상황별 땀질이 요구를 충돌시킨다. 라이브=세션 id 최댓값+successor 끝. 과거 열람은 이전/세션 탭만. 버튼은 라이브+바닥일 때만 숨김. 다른 기기는 과거 열람 중이 아니면 라이브를 따라감.
