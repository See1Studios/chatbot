# PE 개발 전파·상태 아키텍처

> 방향 (align/D, 2026-10-06): **개발 기반** — PE 소프트웨어 공학 및 개발 거버넌스 전파·상태 아키텍처 수립

> 상태: **active** (초안 2026-10-06, ticket #715)
> 목적: PE 소프트웨어 엔지니어링 거버넌스 체계를 명확히 하고, 아키텍처·컨벤션 규칙이 코드베이스 전체로 누수 없이 안전하게 전파·추적되도록 3대 거버넌스 문서(`docs/ARCHITECTURE.md`, `docs/CONVENTION.md`, `docs/STATE.md`) 및 전파 수명주기(Propagation Lifecycle)를 정의한다.
> 관련: [INDEX.md](INDEX.md) · [plan-execution-workflow.md](plan-execution-workflow.md) · [edition-boundary.md](edition-boundary.md) · [monolith-split.md](monolith-split.md)
> 약칭: `prop`

---

## 1. 범위 및 경계 (Scope & Boundary)

### 1.1 적용 범위
- **PE 소프트웨어 엔지니어링 및 개발 거버넌스 전용**: 본 계획은 Private Engine(PE) 리포지토리의 소스 코드 변경, 아키텍처 구조화, 엔지니어링 컨벤션 제정, 모듈 간 전파 대기열 추적, 코드 품질 유지 및 기계적 강제 절차만을 다룬다.
- 개발판 위임 에이전트, 워크트리 러너 워커, 외부 CLI(Claude Code, Grok, Gemini 등), 개발 세션이 준수해야 하는 엔지니어링 절차를 관할한다.

### 1.2 비목표 (Not in Scope)
- **PE 런타임/채팅 엔진 동작 제외**: 런타임 대화 모델 추론, 캐릭터 페르소나 및 발화 연기, 호감도/텐션 FSM, 대화 렌더링 프로토콜, 사용자 입력 파싱 등 런타임 엔진 거동은 본 계획의 범위에 포함되지 않는다.
- 런타임 챗 에이전트의 행동 양식과 대화 UI 규칙은 `$CHATBOT_DATA/workspace/AGENTS.md` 및 역할 팩(`roles/<role>/`)의 관할이며, 본 거버넌스 문서와 엄격히 분리된다.

### 1.3 거버넌스 경계 요약

| 영역 | 관할 문서 | 대상 | 강제 수단 |
|---|---|---|---|
| **개발 거버넌스** | 루트 `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/CONVENTION.md`, `docs/STATE.md` | 저장소 소스 코드를 수정하는 모든 에이전트/개발자 | **[현재]** git 커밋 훅(`.githooks/`), 가드 테스트(`run-tests.sh --fast`: `test_file_sizes`, `test_import_cycles` 등), 티켓 검증(`test_tickets`, `test_unticketed_write`)<br>**[예정]** `CONVENTION.md` 규칙 자동 강제, 테스트 없는 커밋 거부, Mandatory Test Pairing 기계 확인, 배포판 런타임 엔진 수정 원천 차단 |
| **런타임 동작** | `$CHATBOT_DATA/workspace/AGENTS.md`, 역할 팩(`roles/`), 설정집 | 대화방에서 사용자와 상호작용하는 챗봇 인스턴스 | 런타임 가드(`content_guard.py`, `loop_guard.py`), 인스트럭션 주입 |

---

## 2. 3대 핵심 거버넌스 문서 (The 3 Core Governance Documents)

엔지니어링 거버넌스의 지속 가능성을 위해 역할별로 명확히 분리된 3대 단일 진실 공급원(SSOT) 문서를 정의한다 (이미 존재하는 `docs/ARCHITECTURE.md` · `docs/CONVENTION.md` · `docs/STATE.md`).

### 2.1 `docs/ARCHITECTURE.md` (코드베이스 아키텍처 SSOT, 기존 정본 확장)
코드베이스의 구조적 무결성과 계층 원칙을 정의하는 기존 정본 문서다.
- **모듈 경계 (Module Boundaries)**:
  - Core (`evolution.py`, `tickets.py`, `observations.py`, `memory_store.py`, `platform_compat.py`): 표준 라이브러리와 상호 의존만 허용하며 외부 의존성을 배제.
  - Providers (`providers/`): LLM CLI 및 HTTP 두뇌 연결 계층. 공통 코드에 제공자별 특화 로직 침투 금지([현재 가드] `test_provider_neutrality`).
  - Session & Runtime (`session.py`, `session_turn.py`, `session_view.py`): 세션 생명주기 및 대화 턴 실행 관리.
  - HTTP Routes (`server.py`, `route_*.py`): REST 및 SSE 엔드포인트 핸들러.
  - Tools & MCP (`mcp_server.py`, `mcp_core.py`, `web_tool.py`, `mcp_parity.py`): 에이전트가 사용하는 도구 서버.
- **의존성 방향 (Dependency Directions)**:
  - 상위 계층은 하위 계층을 참조할 수 있으나, 하위 코어는 상위 계층이나 구체 프로바이더를 알지 못한다.
  - 모듈 간 단방향 흐름 원칙을 준수하며, 상호 import 순환을 엄격히 차단한다([현재 가드] `test_import_cycles`).
- **배포판/개발판 경계 격리 (Edition-Boundary Separation)**:
  - `host_config.EDITION` (`shipped` vs `dev`)을 유일한 판정 기준으로 삼는다([edition-boundary.md](edition-boundary.md)).
  - [현재 가드] `test_edition_boundary`: 배포판에서 개발 도구(`run_command`, `ticket`, `delegate`) 제외 및 쓰기 범위 제한 검증.
  - [예정 집행] 배포판 런타임에서 사용자 데이터 폴더(`$CHATBOT_DATA`) 외 엔진 코드 수정을 런타임 레벨에서 원천 차단하는 하드닝 가드.
  - 개발 장치(`tickets.py`, `delegation.py`, `tools/worktree_runner.py`)는 배포판 빌드에서 패키지 제외 또는 선택적 로딩으로 격리된다.
- **Tier 1/2/3 격리 (Tier Isolation)**:
  - Tier 0: 극소 런타임 지침 및 부트스트랩.
  - Tier 1: 사용자 영역 데이터(스킬, 기억, 캐릭터 카드). 배포판 에이전트의 제안·수정 허용.
  - Tier 2: 엔진 구현체(세션, 어댑터, 라우터, UI). 개발판 위임 에이전트의 일반 티켓 작업 영역.
  - Tier 3: 코어/보안/가드/거버넌스(`protected_paths.json`). 엄격한 검토와 명시적 승인 하에서만 변경.

### 2.2 `docs/CONVENTION.md` (엔지니어링 컨벤션 SSOT)
숫자와 세부 규칙의 정본(영어, 에이전트용). 2026-10-07 검토(prop/H)에서 실제와 맞췄다:
- **테스트 페어링**: 커밋 훅 commit-msg가 강제(TEST_PAIRING_v1, prop/F). 테스트를 못 붙이면 `No-Test: <이유>` 줄.
- **크기 상한**: 함수 80줄·모듈 80,000바이트, `tests/test_file_sizes.py`가 커밋마다. 넘는 옛 함수는 천장 표로 묶여 줄기만 한다.
- **타임아웃**: 고정 30초가 아니라 **막히는 subprocess 호출마다 명시적 timeout**(`tests/test_conventions.py`). 긴 대화 턴은 워치독 몫. (처음 문안의 "모든 대기 최대 30초"는 실제 턴·CLI 호출과 맞지 않아 고침.)
- **사담 상한**: 1~2문장. 집행자 없음 — 판정하려면 단어·문장 매칭이 필요한데, 그것은 언어 의존 구조라 하지 않는다.

### 2.3 `docs/STATE.md` (전파 장부)
새 규칙이 코드에 퍼지는 동안의 진행(진행 중 항목 + 각 부분의 티켓)과, 어느 가드도 잡지 않는 표류만 적는다. 가드가 이미 묶어 둔 표류(함수 천장, timeout 예외, 래칫)는 그 표가 정본이라 옮겨 적지 않는다(prop/H에서 축소).

---

## 3. 전파 수명주기 (Propagation Lifecycle)

규칙 제정부터 코드베이스 안착까지의 6단계 수명주기를 정의한다.

```text
[1. SSOT 선언] ──> [2. STATE.md 큐 등록] ──> [3. 리드 작업/티켓 분해]
                                                        │
[6. 완료 아카이브] <── [5. 머지 및 체크박스 갱신] <── [4. 개발 구현 및 테스트 검증]
```

1. **SSOT 선언 (SSOT Declaration)**:
   - 설계 원칙이나 컨벤션이 결정되면 `docs/ARCHITECTURE.md` 또는 `docs/CONVENTION.md`에 정본으로 명문화한다.
   - 원칙: "문서에만 있는 규칙은 없는 규칙이다"에 따라 가능한 한 집행자(가드 테스트)를 함께 정의한다.
   - [현재/예정] 이미 존재하는 가드(`test_file_sizes`, `test_import_cycles` 등) 외에 아직 없는 규칙은 신규 가드 테스트 개발([예정])과 함께 정의한다.
2. **STATE.md 큐 등록 (STATE.md Queue Registration)**:
   - `docs/STATE.md`의 Active Queue에 `[DEV-PROP-xxx]` 항목을 등록한다.
   - 영향받는 전체 모듈 목록을 조사하여 모듈 단위의 `[ ]` 체크리스트를 구성한다.
3. **리드 작업/티켓 분해 (Task/Ticket Decomposition via Lead)**:
   - 리드(`lead` 역할)가 `[DEV-PROP-xxx]` 큐 항목을 원자적 단위의 실행 티켓(#N)으로 분해한다.
   - 각 티켓은 변경할 파일 경로를 명확히 클레임(`tools/ticket_quick.py start --paths ...`)한다.
4. **개발 구현 및 테스트 검증 (Dev Implementation & Test Verification)**:
   - 담당 개발자(`dev` 역할)가 분리된 git 워크트리에서 구현을 수행한다.
   - Mandatory Test Pairing 규칙에 따라 테스트를 작성하고, `run-tests.sh`를 통해 검증한다(테스트 동반은 커밋 훅이 확인, prop/F).
5. **머지 및 체크박스 갱신 (Merge & Checkbox Update)**:
   - 게이트를 통과한 작업이 메인 브랜치에 머지되면, `docs/STATE.md`의 해당 모듈 체크박스를 `[x]`로 갱신한다.
   - 커밋 트레일러에 `Ticket: #N` 및 필요 시 전파 식별자를 기록한다.
6. **완료 아카이브 (Archived upon Completion)**:
   - 전파 항목 내 모든 모듈의 체크박스가 `[x]`로 완료되면 해당 `[DEV-PROP-xxx]` 블록을 `docs/STATE.md`의 `## Archived History`로 이동하여 종료한다.

---

## 4. 기존 PE 개발 장치와의 연계 (Integration with Existing PE Devices)

새로운 거버넌스 문서는 별개의 프로세스로 겉돌지 않고, 이미 존재하는 PE 개발 장치들에 유기적으로 결합된다.

### 4.1 티켓 스코핑 연계 (Ticket Scoping)
- `tickets.py` 및 `tools/ticket_quick.py`의 엄격한 경로 클레임(`--paths`) 메커니즘을 그대로 활용한다.
- `docs/STATE.md`의 각 체크리스트 항목은 1개 이상의 구체적 티켓(#N)과 대응되며, 클레임되지 않은 파일 수정을 방지하는 `test_tickets` 및 `test_unticketed_write` 가드와 연계된다.

### 4.2 테스트 러너 및 게이트 연계 (Test Runner & Gates)
아키텍처 및 컨벤션 규칙의 강제는 현재 운영 중인 가드와 신설 예정 강제 메커니즘으로 명확히 구분된다:

- **[현재 운영 중인 가드 (`run-tests.sh --fast`)]**:
  - 함수 80줄 상한 (`FUNC_MAX_LINES=80`) 및 모듈 80KB 상한 (`MAX_BYTES=80_000`): `tests/test_file_sizes.py` (이미 상시 강제 및 래칫 동작 중)
  - 의존성 상호 순환 import 금지: `tests/test_import_cycles.py`
  - 배포판 도구 경계 격리: `tests/test_edition_boundary.py` (배포판에서 개발 도구 제외 검증)
  - 데이터 경로 SSOT 준수: `tests/test_data_paths.py`
  - 프로바이더 중립성: `tests/test_provider_neutrality.py`
  - 규칙-집행자 등록 정합성: `tests/test_rule_registry.py`
  - 문서 및 참조 정합성: `tests/test_plans_index.py`, `tests/test_doc_refs.py`, `tests/test_doc_names.py`
  - 커밋 트레일러 및 게이트 무결성: `.githooks/` 및 `tests/test_githooks.py`
- **[2026-10-07 반영]**: 테스트 페어링(커밋 훅), 타임아웃 검사(run·check_output·check_call·call), 집행자는 모두 Tier 3 + 커밋마다(`test_rule_registry`), 개발판·배포판 지침 분리(`test_edition_instructions`).
- **[아직 없음]**: 배포판 런타임에서 엔진 코드 쓰기를 원천 차단하는 하드닝(edition/E·F), CI(pew D8).

### 4.3 워크트리 러너 연계 (Worktree Runner)
- 전문가 에이전트의 작업은 `tools/worktree_runner.py`가 생성하는 격리된 git 워크트리에서 실행된다.
- **[현재 운영]**: 통과 조건 불변성(`test_worktree_runner`), 커밋 트레일러, 가드 테스트 통과를 기계적으로 확인한다.
- **[완료, #747]**: 리뷰 체크리스트(`tools/review_checklist.py`) 연계를 통해 Mandatory Test Pairing 기계 확인 및 convention 규칙 준수 여부 자동 판정을 도입함 (`tools/review_checklist.py`는 `protected_paths.json`의 governance 목록에 등록된 Tier 3 거버넌스 파일).

### 4.4 컨텍스트 예산 규율 (Context Budget Discipline)
- **온디맨드 파일 읽기(On-Demand Reads) 원칙**:
  - 3대 거버넌스 문서(`docs/ARCHITECTURE.md`, `docs/CONVENTION.md`, `docs/STATE.md`)는 **런타임 세션의 프롬프트 번들에 상시 주입되지 않는다**.
  - `instructions.py`의 번들 크기 상한(`bundle_budget.json`, `test_bundle_budget`)을 침범하지 않도록 유지한다.
  - 개발 에이전트나 워크트리 워커가 특정 모듈 작업이나 전파 큐를 처리할 때만 파일 읽기 도구(`view_file`, `read_file`)로 필요한 섹션을 선별 조회하여 컨텍스트 윈도우와 토큰 비용을 엄격히 절약한다.

---

## 5. 결정 사항 (Decisions)

| ID | 질문 | 추천안 | 상태 |
|---|---|---|---|
| D-1 | 거버넌스 문서의 파일명 대소문자 규약 | 루트 `AGENTS.md` "Naming" 규약 및 `test_doc_names.py`에 따라 `docs/` 바로 아래의 스탠딩 문서는 UPPERCASE(`docs/ARCHITECTURE.md`는 기존 정본으로 이미 존재)가 원칙임. 신설할 `docs/convention.md`·`docs/state.md`의 파일명을 스탠딩 규약에 맞춰 대문자(`docs/CONVENTION.md`, `docs/STATE.md`)로 정본 신설할 것인지 결정 | 결정 완료 및 반영: 스탠딩 규약에 맞춰 본체 문서는 UPPERCASE(`docs/CONVENTION.md`, `docs/STATE.md`)로 신설하고, 기존 참조 호환성을 유지 (#720) |
| D-2 | 신규 컨벤션 검사기의 도입 및 가드 편입 시점 | 비동기 타임아웃(30초), Mandatory Test Pairing 기계 확인 등 신규 검사기를 `run-tests.sh --fast` 게이트에 즉시 편입할 것인가 (참고: 함수 80줄 상한은 이미 `tests/test_file_sizes.py` `FUNC_MAX_LINES=80`으로 존재하며 상시 강제 중임) | 결정 완료 및 반영: 이미 동작 중인 `test_file_sizes.py` 래칫을 유지하고, 신규 검사기(비동기 타임아웃 등)는 개발 완료 후 단계적으로 편입 (#724) |
| D-3 | `state.md` 전파 큐의 아카이브 단위 | 개별 `[DEV-PROP-xxx]` 항목 완료 즉시 아카이브할 것인가, 주간 단위로 배치 이동할 것인가 | 결정 완료 및 반영: 개별 항목 완료 시 즉시 체크박스 마감 후 해당 주차에 아카이브 (#726) |

---

## 6. 작업 항목 표 (Work Items)

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| prop/A | 핵심 거버넌스 문서 체계 정비 및 신설 | `docs/ARCHITECTURE.md`, `docs/CONVENTION.md`, `docs/STATE.md` | 기존 `docs/ARCHITECTURE.md` 거버넌스 확장, `docs/CONVENTION.md`(신설) 규칙 작성, `docs/STATE.md`(신설) 큐 서식 작성 및 커밋 | Tier 3 · ⚡X | M | D-1 | 완료 (#720) |
| prop/B | 신규 컨벤션 검사기 개발 및 가드 연동 | `tests/test_conventions.py` (또는 기존 가드 확장) | 비동기 30초 타임아웃 및 Mandatory Test Pairing 기계 검증 가드 추가 (함수 80줄 상한은 기존 `test_file_sizes` 활용) | Tier 3 · ⚡X | S | prop/A | 완료 (#724) — 정정 2026-10-07: 실제로는 timeout 검사만, 테스트 페어링 기계 검증은 prop/F |
| prop/C | `STATE.md` 파일럿 전파 큐 등록 및 아카이브 | `docs/STATE.md`, `docs/plans/propagation-and-state-architecture.md` | 첫 `[DEV-PROP-001]` 큐 항목 등록, 체크리스트 마감 및 아카이브 검증 | Tier 3 · ⚡X | S | prop/A, prop/B | ✅ #726 `d926a47` |
| prop/D | 워크트리 러너 리뷰 체크리스트 연동 | `tools/review_checklist.py` | 워커 리뷰 시 Mandatory Test Pairing 기계 확인 및 거버넌스 체크리스트 판정 연동 (Tier 3: protected_paths.json 거버넌스 경로) | Tier 3 (거버넌스) · ⚡X | S | prop/B | 완료 (#747) |
| prop/E | 2026-10-07 거버넌스 검토 1: main 복구 — lead 역할 팩에서 설치 전용 스킬 제거(주인 없는 스킬은 DEFAULT_ROLE_v1로 기본 캐릭터 몫), 지문 테스트의 날짜 고정 | `templates/dev-workspace/roles/lead/ROLE.md`, `tests/test_context_layers.py` | `./run-tests.sh` 전부 통과 | Tier 3 · ⚡X | S | — | ✅ #766 `de37131` |
| prop/F | 검토 2: 집행자 보호 — 레지스트리의 집행자 테스트는 모두 Tier 3, 싼 것은 FAST, 느린 것은 이유와 함께 목록; 테스트 페어링을 commit-msg 훅으로 | `tests/test_rule_registry.py`, `run-tests.sh`, `protected_paths.json`, `.githooks/check_staged.py`, `tests/test_githooks.py`, `tests/test_conventions.py`, `AGENTS.md` | 집행자를 Tier 3에서 빼거나 FAST·SLOW 어디에도 없으면 `test_rule_registry` 실패; 테스트 없는 feat/fix 커밋 거절 | Tier 3 · ⚡X | M | prop/E | ✅ #767 `df88497` |
| prop/G | 검토 3: 개발판·배포판 지침 분리(운영자 2026-10-07 "절대 섞이지 않고 독립적") — 헌장은 배포판 하나, 개발판 규칙은 `EDITION=dev`에서만 붙는 별도 층 | `instructions.py`, `templates/`, `tools/link_dev_workspace.py`, 테스트 | 배포판 묶음에 개발판 문장 0, 개발판 층이 배포판 헌장 줄을 반복하지 않음(테스트) | Tier 3 · ⚡ | M | prop/F | ✅ #768 `83f0cf8` |
| prop/H | 검토 4: 거버넌스 문서 정리 — CONVENTION 영어·숫자 위주, STATE 축소, ARCHITECTURE §7 사실만, 계획 상태 정정, 문구 확인 테스트 삭제 | `docs/`, `AGENTS.md`, `templates/dev-workspace/` | `./run-tests.sh` 통과, 문서 간 모순 0 | Tier 3 · ⚡X | M | prop/G | ✅ #769 `bc8c9f3` |

---

## 7. 의존·순서·리스크

- **선행 의존**: [plan-execution-workflow.md](plan-execution-workflow.md)의 DoR/DoD 및 게이트 프로세스, [edition-boundary.md](edition-boundary.md)의 판 분리 기준.
- **리스크**:
  - 거버넌스 규칙이 지나치게 방대해질 경우 개발 에이전트의 컨텍스트 소모 증가 -> 온디맨드 조회 원칙(4.4) 철저 준수로 방어.
  - 문서만 갱신되고 실제 코드로 전파되지 않는 표류(Drift) 현상 -> `docs/STATE.md`의 `[DEV-PROP-xxx]` 체크리스트와 가드 테스트로 추적 및 차단.
