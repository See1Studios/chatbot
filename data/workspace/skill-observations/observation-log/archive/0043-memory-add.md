---
id: 43
title: "memory add 항상 실패 버그"
status: declined
type: internal
skill: []
proposes_skill: []
area: ""
date: 2026-09-22
parked_until:
resolved: 2026-09-23
resolution: "서버(memory_store/mcp_core) 자체는 정상 동작함. 호출 모델(Claude Sonnet)이 스키마 키인 'text' 대신 'content'로 잘못 호출하여 None으로 처리되어 발생했던 오류임이 확인됨. 호스트 모듈 불필요한 변경 없이 원인 규명 완료로 종결."
reference:
resolved_by: "chat-agent:agy"
---

memory add 액션이 '추가할 사실이 없습니다' 오류로 항상 실패. show로 확인 시 해당 내용 없음. NAS memory MCP 서버 add 핸들러 버그 의심. 티켓 propose는 evidence 형식 검증(세션#라인) 때문에 실패. 컴대시 ticket propose로 재시도 필요.
