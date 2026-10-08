# 캐릭터 스코프 관계 기억 어댑터 (Character Memory Adapter)

> 방향 (align/D, 2026-09-28): **핵심** — 관계 기억은 연속성·「쌓인 깊이」 해자의 중심. 배포판 기능

- **상태:** `active`
- **작성:** 2026-09-27
- **범위:** 최소 조각은 구현됨(§8). 암호화·화면·스위치는 미정. 전 범위 스키마는 확정하지 않는다.
- **관련:**
  - [`VISION.md`](../../VISION.md) — 제품 기조·열린 축
  - [`private-mode.md`](private-mode.md) — 사적 모드·텐션·호감도(계획)
  - [`user-data-separation.md`](user-data-separation.md) — `CHATBOT_DATA`·기억 경로·배포 분리
  - [`multi-agent-worktree-delegation.md`](multi-agent-worktree-delegation.md) §12 — 캐릭터별 업무/사적 기억 분리
  - 현행 단순 기억: `memory_store.py`(집 `MEMORY.md`), `characters.py`(`memory.md` / `private-memory.md`)

## 1. 제품 프레이밍 (필수)

이 제품은 **개인화된 에이전트 하네스**다. “걸프렌드 챗봇”이 1차 정체성이 아니다.

- 업무·개발·위임·자기진화가 핵심 축이다.
- **사적 관계·동반자 깊이**는 사용자가 **선택해 켜는 한 능력**이다 (사적 모드와 같은 층).
- 비유: Blade Runner의 Joi처럼 — 공감·개인 지지·연속된 관계감. 업무 창만 있는 봇이 아니라, **사람 옆의 개인 에이전트**에 가깝게.

기조 문서의 “친구 같고, 연인 같고, 동료 같은”은 **온도의 스펙트럼**이지, 연인 전용 제품을 뜻하지 않는다.

## 2. 왜 새 층이 필요한가

| 층 (이미 있음·아카이브됨) | 역할 |
|---|---|
| Provider 어댑터 (`providers/adapter_*`) | 두뇌·프로토콜 차이 흡수 |
| Visual / 캐릭터 리소스 (`visual.md`, 아바타·가발) | 외형·출고 그림 |
| 단순 장기 기억 | 집 `MEMORY.md`, 캐릭터 `memory.md`, 사적 `private-memory.md` (짧은 bullet, 상한) |

현행 기억은 **사실 한 줄** 수준이라 동반자 깊이에 부족하다.

부족한 예 (요구 의도, 스펙 아님):

- 어제까지 **어디까지 왔는지** (진행·장면 연속)
- **약속** (“다음에 ~하자”)
- **선호 / 금기 (taboo)**
- **관계 온도** (호감·거리 — [`private-mode.md`](private-mode.md) §3과 맞닿음, 중복 설계 금지)
- **사적 히스토리**의 요약·연속 (날 단위 continuity)

→ Provider·Visual 옆에 **per-character memory adapter** 층을 연다.  
같은 캐릭터·같은 사용자 관계만 보고, 프로바이더가 바뀌어도 관계 연속은 유지하는 쪽을 목표로 둔다 (구현은 미정).

## 3. 목표 능력 (관계 특화 기억 — 개념만)

어댑터가 다루면 좋은 **개념 슬롯** (파일 포맷·필드명 확정 아님):

| 개념 | 한 줄 |
|---|---|
| Progress | 최근 대화·장면에서 “어디까지였는지” |
| Promises | 서로 한 약속·미이행 |
| Preferences | 좋아함·말투·호칭·리듬 |
| Taboos | 하지 말 것·트리거 |
| Relationship temperature | 거리·친밀 온도 (수치 UI는 private-mode 호감도와 정합) |
| Private history | 사적 구간 요약·크로스-데이 연속 |

**비목표 (이 문서에서 하지 않음):**

- 구현 패치, JSON 스키마 확정, lorebook 엔진 이식
- 아카이브 계획 부활·확장
- “걸프렌드 모드”를 제품 기본값으로 고정

## 4. 열린 설계 질문 (착수 전 결정)

가짜 구현을 적지 않는다. 아래만 남긴다.

### Q1. 저장 위치 vs `CHATBOT_DATA`

- 관계 기억은 사용자 데이터다 → [`user-data-separation.md`](user-data-separation.md)의 Memory 분류와 맞출 것.
- 후보만: 캐릭터 폴더 확장(`characters/<id>/…`) vs `$CHATBOT_DATA` 아래 전용 트리 vs 현 `private-memory.md` 진화.
- 집 공용 `MEMORY.md`와 **섞지 않을지** (캐릭터 스코프 원칙, delegation §12).

### Q2. 프라이버시·암호화

- 사적 관계 기억은 민감. git 제외는 이미 방향(`private-memory.md` ignore).
- 암호화·at-rest·백업 정책은 **user-data-separation / 배포 분리와 한 줄로 묶을지**, 별도 티켓인지 미정.
- 이 문서에서 암호 알고리즘·키 관리를 정하지 않는다.

### Q3. `turn_context` 주입

- 사적 턴은 이미 `private_engine.turn_context`가 텐션(·옵션 완화 레이어)을 붙인다.
- 관계 기억을 **어디에·얼마나** 넣을지: turn_context vs 지침 묶음(`[Private memory]`) vs 별도 블록.
- 토큰 예산·매 턴 전체 vs JIT(관련 슬롯만) — 미정.

### Q4. vs Lorebook

- SillyTavern/Chub식 lorebook(키워드 트리거 월드북)과 **같은가 / 보완인가 / 다른가**.
- 관계 기억은 “설정 사전”보다 **나와의 진행·약속**에 가깝다. lorebook을 그대로 가져오지 말지부터 결정.

### Q5. Opt-in depth

- 기본은 얕은 기억(현행 bullet) 유지.
- 관계 어댑터 깊이(진행·약속·온도 등)는 **캐릭터·모드·사용자 설정으로 opt-in**할지.
- 업무 세션에는 주입 금지(현 SESSION_SPLIT / 사적·업무 분리와 정합).

### Q6. private-mode 호감도·텐션과의 경계

- 호감도·텐션은 [`private-mode.md`](private-mode.md) SSOT.
- 관계 기억 어댑터는 **서술·약속·금기·어제 진행**에 집중하고, 수치 엔진은 중복 발명하지 않는다.
- 경계 문장 한 줄을 private-mode ↔ 본 문서에 서로 링크만 유지.

## 5. 기존 자산 (재사용 후보 — 채택 결정 전)

| 자산 | 메모 |
|---|---|
| `memory_store.py` | 집 장기 기억, 짧은 fact 줄, 락·원자 쓰기 |
| `characters.memory_path` / `private_memory_path` | 캐릭터·사적 분리 이미 있음 |
| `instructions.py` 번들 | 사적 세션에 `[Private memory]` 주입 |
| `private_engine.turn_context` | 턴 단위 사적 컨텍스트 훅 |
| Provider / visual 어댑터 패턴 | “차이 흡수 층” 비유만. API 복붙 아님 |

## 6. 다음 액션 (착수는 실장님 말)

1. Q1–Q6 중 우선순위·기본 기울기 결정
2. private-mode 호감도(D6 등)와 슬롯 경계 합의
3. user-data-separation 일정과 저장 경로를 같은 배포 이야기에서 맞출지 여부
4. 승인 후에만 스키마·스파이크·티켓

## 7. INDEX·기조

- INDEX Active 행: 본 문서
- [`VISION.md`](../../VISION.md) `열린 축`에 캐릭터 스코프 관계 기억 어댑터 1줄 링크

## 8. 최소 구현 (2026-10-03)

운영자 요청으로 Q1–Q6의 **가장 작은 읽기**만 코드에 넣었다. 상태 `active` (암호화·화면·스위치는 열림).

| 질문 | 이 조각의 결정 |
|---|---|
| Q1 | 캐릭터 폴더 `relationship.md`. 집 `MEMORY.md`와 섞지 않는다. 기존 `private-memory.md`는 요약 로그로 남긴다. |
| Q2 | 암호화 없음. `private-memory.md`와 같이 사용자 데이터라 git에 넣지 않는다. |
| Q3 | 사적 지침 묶음의 동적 블록 `[Private memory]` / `[Relationship]`만. `turn_context`에는 넣지 않는다. 슬롯당 표시 상한. |
| Q4 | 로어북이 아니다. 키워드 세계관과 별도다. |
| Q5 | 사적 세션만. 업무 세션에는 주입하지 않는다. 새 설정 스위치는 없다 (사적 모드와 같은 opt-in). |
| Q6 | 호감·텐션 수치는 `private-mode.md`만. 여기에는 문장 슬롯만. |

저장 형식은 기존 기억과 같은 `- ` 줄이고, 제목만 `## Progress` / `## Promises` / `## Preferences` / `## Taboos`.
대화 원문은 읽지 않는다. 다이제스트가 `progress:` `promise:` `pref:` `taboo:`를 붙이면 `memory_relationship.py::remember_slots`가 파일에 남긴다.
태그가 없는 줄은 파일에 쓰지 않고, 주입 때만 느슨한 힌트로 칸을 나누거나 `Continuity`에 둔다 (`memory_relationship.py::injection`).
힌트는 틀릴 수 있어 디스크를 고치지 않는다.
