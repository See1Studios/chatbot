# 계획 문서 인덱스

여기서 상태를 보고 필요한 문서만 연다. **이 표가 SSOT**다(문서 안의 "상태" 줄보다 우선).

## 상태 값 (필수)

| 값 | 의미 |
|---|---|
| `active` | 진행·계획 중. `docs/plans/` 루트에 둔다 |
| `done` | 티켓 완료 또는 스펙이 코드에 흡수됨 → 그 주에 아카이브 |
| `superseded` | 다른 active 계획으로 대체됨 → 그 주에 아카이브 |
| `abandoned` | 착수하지 않고 폐기 → 그 주에 아카이브 |

표시용으로 한국어 요약(`진행`/`계획` 등)을 덧붙여도 되지만, **첫 토큰은 위 네 값 중 하나**여야 한다.

## 아카이브 절차 (MUST)

1. **트리거**: 티켓 done · 스펙이 코드에 흡수 · 다른 문서로 대체 → **그 주 안에** 아카이브.
2. **이동**: `docs/plans/<파일>.md` → `docs/plans/archive/YYYY/<파일>.md` (년도 = 아카이브한 해).
3. **INDEX**: 표에서 경로를 `archive/YYYY/…`로 바꾸고, 상태 + **종료 사유 한 줄**만 남긴다.
4. **금지**: 아카이브 문서를 그 자리에서 늘리거나 이어서 쓰지 않는다. 후속 작업 = **새 active 계획** + INDEX 한 줄. 옛 문서는 `superseded`로 링크만.
5. **새 계획 만들기 전**: 이 INDEX를 먼저 읽고, 중복·아카이브 부활 여부를 확인한다. 새 파일은 상태 `active`, **같은 변경에 INDEX 행 추가**.

상세·폴더 규칙은 [`archive/README.md`](archive/README.md).

## Active

| 문서 | 상태 | 언제 읽나 |
|---|---|---|
| [multi-agent-worktree-delegation.md](multi-agent-worktree-delegation.md) | `active` — §10 PD 모델, §11 전문가, §12 캐릭터(카드·사적 기억·이미지 형식·역할 팩) | 위임·PD·캐릭터·역할을 건드릴 때 |
| [monolith-split.md](monolith-split.md) | `active` — Phase 5 완료(app.js·session.py 분리), 파일 상한 규칙 | 파일을 나누거나 새 파일을 만들 때 |
| [character-resource-pipeline.md](character-resource-pipeline.md) | `active` — 캐릭터 폴더 SSOT, 정본/파생/인스턴스, `needed_art`, 자기진화 완결성 관찰 | 캐릭터 생성·수정·그림·Hub 페르소나 경로를 건드릴 때 |
| [user-data-and-editing.md](user-data-and-editing.md) | `active` — 사용자 데이터 분리(배포), ~~직책 이름은 표시값~~(완료 #129), 카드 폼 편집, 옛 프로토타입 삭제 | 배포 준비·팀 탭 편집·직책을 건드릴 때 |
| [user-data-separation.md](user-data-separation.md) | `active` — 기본 `~/.pe`·`CHATBOT_DATA`/`PE_HOME`·ctl 하드코딩 제거·마이그레이션 (user-data-and-editing §1 상세) | 배포·데이터 경로·`~/.pe`·gitignore를 건드릴 때 |
| [release-pipeline.md](release-pipeline.md) | `active` — Now/Next/Pre-Steam 배포 로드맵, `~/.pe`, CI·런처·Steam은 브랜드 이후 | 릴리스·버전·CI·인스톨러·Steam 전 배포를 건드릴 때 |
| [plan-execution-workflow.md](plan-execution-workflow.md) | `active` — 누수 없는 계획→실행(PE 내부 경로 우선): 루트 AGENTS.md 단일 입구·정본 지도, 규칙↔집행자 레지스트리, 훅·가드 테스트, 게이트 G0–G9·DoR/DoD·항목 id·ADR·트레일러, 파일럿=release·user-data | 계획을 새로 쓰거나 항목을 티켓으로 옮길 때, 에이전트 진입·규칙 강제를 건드릴 때 |
| [localization.md](localization.md) | `active` — 주요 언어 현지화: 1차 ko+en, 2차 ja·zh-Hans(D1–D7 결정), 래칫 가드·카탈로그·답변 언어 변수화, 말투 분리 | UI·서버 문자열, 날짜 형식, 답변 언어, 번역을 건드릴 때 |
| [out-of-band-choices-actions.md](out-of-band-choices-actions.md) | `active` — 선택지·액션을 답변 본문 밖 채널(`choices` 도구·이벤트)로, 버튼 직접 전송(#134) | 선택지·버튼·액션 전달·티켓 바를 건드릴 때 |
| [private-mode.md](private-mode.md) | `active` — 사적 모드 SSOT: 액션·선택지·텐션 4단계(구현됨), 8단계 초안·호감도·HUD·렌더 데코레이터(계획), 결정 필요 D1–D12 | 사적 모드·텐션·호감도·HUD·렌더링을 건드릴 때 |
| [private-engine-brand.md](private-engine-brand.md) | `active` — Private Engine / 프라이빗엔진 브랜드·도메인 공개 스캔(2026-09-27), privateengine.ai 기울기, 상표≠도메인 | 브랜드명·도메인·상표 클리어런스·외부 배포 명칭을 건드릴 때 |
| [character-memory-adapter.md](character-memory-adapter.md) | `active` — 캐릭터 스코프 관계 기억 어댑터(설계·열린 질문), provider/visual 옆 층, Joi식 연속성·opt-in | 관계 기억·사적 continuity·캐릭터 메모리 층을 건드릴 때 |

## Archived (한 줄 · 펼치지 말 것)

| 문서 | 상태 | 종료 사유 |
|---|---|---|
| [archive/2026/recursive-self-evolution.md](archive/2026/recursive-self-evolution.md) | `done` | 코어(관찰·티켓·보호) 구현됨 — 코드가 정본 |
| [archive/2026/instruction-architecture.md](archive/2026/instruction-architecture.md) | `done` | 지침 계층 흡수; 역할 팩(§12.5)이 캐릭터 부분 대체 |
| [archive/2026/token-accounting.md](archive/2026/token-accounting.md) | `done` | 창 점유 vs 과금 해설 — 필요 시 참고만 |
| [archive/2026/api-provider-adapters.md](archive/2026/api-provider-adapters.md) | `done` | API 프로바이더 Phase 0–5 완료 |
| [archive/2026/in-flight-interruption.md](archive/2026/in-flight-interruption.md) | `done` | §4(2026-09-20) 최종; §1–3 대체됨 |
| [archive/2026/chatbot-host-portability.md](archive/2026/chatbot-host-portability.md) | `done` | 호스트 일반화 Phase 0–3 완료 |
| [archive/2026/direction-2026-09-22.md](archive/2026/direction-2026-09-22.md) | `superseded` | PD·캐릭터 방향 → delegation §10–12 |
| [archive/2026/audit-2026-09-22-work-ordered.md](archive/2026/audit-2026-09-22-work-ordered.md) | `done` | 감사 작업 목록 완료 |
| [archive/2026/audit-2026-09-22-recheck.md](archive/2026/audit-2026-09-22-recheck.md) | `done` | 감사 재확인 완료 |
| [archive/2026/self-evolution-loop-review-2026-09-22.md](archive/2026/self-evolution-loop-review-2026-09-22.md) | `done` | 평가 보고 완료 |
| [archive/2026/recursive-self-evolution-review-grok-v2.md](archive/2026/recursive-self-evolution-review-grok-v2.md) | `done` | 교차 검증 v2 완료 |
| [archive/2026/recursive-self-evolution-review-grok-v3.md](archive/2026/recursive-self-evolution-review-grok-v3.md) | `done` | 교차 검증 v3 완료 |
