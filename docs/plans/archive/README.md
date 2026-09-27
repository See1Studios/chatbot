# plans/archive

종료된 계획 문서 보관소. **INDEX.md의 아카이브 절차가 SSOT**다.

## 레이아웃

- `archive/YYYY/<name>.md` — 아카이브한 해 기준
- 이 README는 규칙 요약만. 상태·트리거·금지 사항은 [`../INDEX.md`](../INDEX.md)

## 에이전트 MUST (요약)

- 새 계획 전 INDEX 확인 → 상태 `active` → INDEX 행 추가
- 상태: `active` | `done` | `superseded` | `abandoned`
- 끝나면 그 주에 여기로 옮기고 INDEX에 한 줄(경로 + 종료 사유)
- 아카이브 문서를 그 자리에서 확장하지 말 것. 후속 = 새 active 계획
- 아카이브本을 루트에 되살리지 말 것 (`superseded` + 새 문서)
