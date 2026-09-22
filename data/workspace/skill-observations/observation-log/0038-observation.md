---
id: 38
title: "최신 대화로 버튼이 예전 세션 열람 뒤 또 고장"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "ui"
date: 2026-09-22
parked_until:
resolved: 2026-09-22
resolution: "goToLatestConversation가 세션 id 최댓값+successor로 점프. 같은 세션이면 instant pin. fallback도 id 순. 과거 열람 중엔 follow 안 함. 버튼은 라이브+바닥만 숨김. app.js?v=106. 정적만, 새로고침."
reference:
---

실장님: "최신대화로 버튼이 또 고장난 것 같은데 봐줘". 어제 v=98–101에서 고친 점프(세션 id 최댓값+successor, instant pin, archiveBrowse) 가 app.js 점프 블록에 안 남고 v=92 원본(
list[0] mtime, smooth scroll, viewingPastSession=Boolean(next)) 이 그대로였다. 과거 세션을 열면 mtime이 올라가 버튼이 그 바닥만 스크롤하거나 최신에서 과거로 팁긴다.
