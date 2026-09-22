---
id: 47
title: "code-review 재발 패턴: 부분 수정이 자매 코드경로에 안 퍼짐"
status: open
type: internal
skill: []
proposes_skill: []
area: "code-quality"
date: 2026-09-23
parked_until:
resolved:
resolution:
reference:
---

/code-review 10건 중 최소 2건이 같은 모양의 실수였음: (1) ANSI/C0 스트립을 Claude 어댑터 /cost 파싱에만 넣고 구조가 똑같은 Agy /usage 파싱엔 빠뜨림 (adapters.py). (2) PROVIDER_SWAP_DEFER_v1 isBusy 게이트를 selectProvider()엔 넣고 나란히 있는 modelEl.onchange엔 빠뜨림 (app.js). 둘 다 "같은 버그의 두 번째 발생 지점"을 놓친 케이스라, 앞으로 이런 류 수정을 할 땐 자매 함수/자매 핸들러가 있는지부터 grep해서 짝을 맞추는 습관이 재발 방지에 도움될 것.
