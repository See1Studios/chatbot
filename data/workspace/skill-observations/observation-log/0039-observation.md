---
id: 39
title: "자기진화 루프가 코드에만 닫히고 프로토콜·지침·배송은 비어 있다"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "self-evolution"
date: 2026-09-22
parked_until:
resolved: 2026-09-22
resolution: "티켓 15: release(done) 은 커밋 전제, claim(paths) leftover 거절, 헌장·설계서는 승인된 티켓으로 프로토콜을 고친다. 3718f450."
reference:
---

실장님 발화: 재귀적 자기개발이 코드에만 국한되면 안 되고, 지침·프로토콜·파이프라인까지 닫혀야 한다. 여러 에이전트가 티켓 없이 작업하고, 실수를 기록한 뒤 재발을 막지 못 한다.

계측:
- 이 세션(grok) 콤밋 4개·푸시 19개를 티켓 propose/claim 없이 실행. 발화는 있었으나 기록은 없다.
- 티켓 13: app.js만 대상, done 후 미커밋. 같은 파일의 미커밋 점프 로직이 아침 코드로 남음.
- 티켓 1~14 전부 done, 워킹 트리는 더러움. release(done)은 git/push/⚡를 안 본다.
- guard_tickets는 열린 티켓+미커밋 .py만 본다. done 이후 남은 호스트 더러우이 오히려 스모크를 떨어뜨린다.
- 설계서 §4.1 Tier 3: 프로토콜/승인 규칙은 에이전트 수정 불가. 프로토콜이 틀리면 루프가 멈춠다.
