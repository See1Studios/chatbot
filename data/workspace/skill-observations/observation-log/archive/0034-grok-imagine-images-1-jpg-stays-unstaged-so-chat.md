---
id: 34
title: "Grok Imagine images/1.jpg stays unstaged so chat bubbles 404"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "media_handler grok imagine"
date: 2026-09-21
parked_until:
resolved: 2026-09-21
resolution: "cid를 rewrite 전에 캡처하고, cid 없으면 최신 grok images/ 세션으로 폴백. append는 상대경로 stem을 이미 있다고 건너뛰지 않음. tests.test_grok_image_paths 5개. 라이브 반영은 ⚡소생."
reference:
---

실장님 “이미지가 채팅창에서 바로 보이지 않아”. 세션 20260921-155101-aa4450 history는 ![ ](images/1.jpg) 그대로고 artifacts/brain 이 비어 있었음. grok end의 sessionId보다 rewrite가 먼저 돌고, append는 상대경로 stem을 이미 있다고 스테이징을 건너뛄.
