---
id: 51
title: "session.py: meta.json 손상 시 복구 코드가 NameError로 실패"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "chatbot"
date: 2026-09-23
parked_until:
resolved: 2026-09-23
resolution: "티켓 #39(733d027): obslog.exception(session.meta_corrupt)으로 교체"
reference:
---

코드 검토로 발견: sys를 import하지 않은 채 sys.stderr 사용(손상 meta 이름 변경 경로). 해당 경로에 들어가면 복구 대신 예외.
