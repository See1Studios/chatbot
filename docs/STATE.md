# PE 개발 거버넌스 전파 장부 및 상태 (Propagation State & Backlog)

> 방향: **개발 기반** — 아키텍처 및 컨벤션 전파 추적, 모듈별 체크리스트, 코드 표류(Drift) 백로그 동적 장부
> 관련: [ARCHITECTURE.md](ARCHITECTURE.md) · [CONVENTION.md](CONVENTION.md) · [propagation-and-state-architecture.md](plans/propagation-and-state-architecture.md) · [../AGENTS.md](../AGENTS.md)
> 관리: 리드(PD/노노) 및 개발자(코코 등)가 티켓 작업과 연동하여 동적으로 갱신

---

## 1. 개요 및 운영 원칙

본 문서는 `docs/ARCHITECTURE.md`와 `docs/CONVENTION.md`에 선언된 아키텍처 원칙과 엔지니어링 컨벤션이 코드베이스 전체에 누수 없이 전파되도록 진행 상황을 추적하는 동적 상태 장부(State Ledger)이다.

- **전파 수명주기 6단계 연계** ([propagation-and-state-architecture.md](plans/propagation-and-state-architecture.md) §3):
  1. `SSOT 선언`: 아키텍처/컨벤션 문서에 정본 규칙 명문화
  2. `state.md 큐 등록`: 본 문서의 Active Queue에 `[DEV-PROP-xxx]` 항목 등록 및 모듈 체크리스트 수립
  3. `리드 작업/티켓 분해`: 리드가 원자적 단위 티켓(#N)으로 분해하고 경로 클레임
  4. `개발 구현 및 테스트 검증`: 분리된 워크트리에서 Mandatory Test Pairing 준수하여 개발 및 가드 통과
  5. `머지 및 체크박스 갱신`: 메인 머지 후 해당 모듈 체크박스를 `[x]`로 갱신
  6. `완료 아카이브`: 모든 모듈 완료 시 Archived History로 이동 (결정 D-3: 개별 항목 완료 시 즉시 체크박스 마감 후 해당 주차에 아카이브)
- **온디맨드 파일 읽기 원칙**: 본 문서는 런타임 세션 프롬프트에 상시 주입되지 않으며, 개발 에이전트가 전파 큐를 확인하거나 작업할 때만 파일 읽기 도구로 선별 조회하여 컨텍스트 예산을 보존한다.

---

## 2. Active Queue (활성 전파 큐)

현재 코드베이스 전파가 진행 중인 아키텍처 개편 및 컨벤션 적용 큐 목록이다.

### 등록 서식 규약 (Template)
새로운 전파 항목 등록 시 아래 서식을 엄격히 준수한다:

```markdown
### [DEV-PROP-xxx] <전파 항목 제목>

- **상태**: `대기` | `진행 중` | `완료 대기`
- **목표**: <전파 목적 및 기대 효과 1~2문장>
- **기준 SSOT**: [<문서명>](<상대경로>) §<섹션>
- **주관 티켓 / 담당자**: #<티켓번호> / <담당 역할 id>
- **모듈 체크리스트**:
  - [ ] `<계층/모듈명>`: <세부 작업 내용 및 검증 테스트> (티켓 #<N>)
  ...
```

---

<!-- Active Queue 항목 시작 -->

### [DEV-PROP-001] 거버넌스 3대 정본 문서 체계 수립 및 전파 기반 구축

- **상태**: `완료 대기`
- **목표**: 아키텍처 확장, 컨벤션 제정, 전파 장부 신설을 통해 PE 소프트웨어 공학 거버넌스 3대 정본 체계를 확립한다.
- **기준 SSOT**: [propagation-and-state-architecture.md](plans/propagation-and-state-architecture.md) (prop/A)
- **주관 티켓 / 담당자**: #720 / `dev` (개발 코코)
- **모듈 체크리스트**:
  - [x] `docs/ARCHITECTURE.md`: 거버넌스, 모듈 경계, 단방향 의존성, 에디션 경계, 티어 격리 확장 (티켓 #720)
  - [x] `docs/CONVENTION.md`: Mandatory Test Pairing, 80줄/80KB 상한, 30초 타임아웃, 사담 상한 정본 신설 (티켓 #720)
  - [x] `docs/STATE.md`: Active Queue, 모듈 체크리스트, Drift Backlog, Archive 서식 신설 (티켓 #720)
  - [x] `tests/test_conventions.py`: 신규 컨벤션 검사기(비동기 타임아웃 등) 개발 및 가드 연동 (티켓 #724)

<!-- Active Queue 항목 끝 -->

---

## 3. Module-level Checklist 서식 (모듈 단위 체크리스트 규약)

전파 영향도를 누락 없이 추적하기 위해 계층별 표준 모듈 분류를 기준으로 체크리스트를 구성한다:

| 계층 | 대상 모듈 | 전파 검증 관점 |
|---|---|---|
| **Core** | `evolution.py`, `tickets.py`, `observations.py`, `memory_store.py`, `platform_compat.py` | 외부 의존성 배제, 독립 테스트 통과, 80줄/80KB 상한 준수 |
| **Providers** | `providers/adapters.py`, `providers/adapter_*.py`, `providers/accounts.py` | 제공자 중립성, 비동기 30초 타임아웃, 예외 처리 격리 |
| **Session & Runtime** | `session.py`, `session_turn.py`, `session_view.py`, `turn_watchdog.py`, `instructions.py` | 단방향 의존성, 턴 워치독 연계, 락 격리 및 큐 보존 |
| **HTTP Routes** | `server.py`, `route_*.py`, `route_table.py` | 라우트 테이블 매칭 순서, 가드 적용, 비동기 응답 처리 |
| **Tools & MCP** | `mcp_server.py`, `mcp_core.py`, `nas_mcp_host.py`, `web_tool.py`, `mcp_parity.py` | 판별 도구 격리(`host_config.EDITION`), 인자 유효성 검증, 900줄 상한 준수 |
| **Tests & Guards** | `tests/`, `.githooks/check_staged.py`, `run-tests.sh` | Mandatory Test Pairing, 게이트 불변성 유지 |

---

## 4. Drift Backlog (코드 표류 부채 추적)

새로운 아키텍처 원칙이나 컨벤션 규칙이 선언된 이후, 기존 레거시 코드베이스에서 발견된 불일치(Drift) 및 기술 부채를 기록하고 Active Queue 진입을 대기하는 장부이다.

### Drift 등록 서식 (Template)

```markdown
- **[DRIFT-xxx]** `<파일경로>::<함수명>`
  - **위반 규칙**: <ARCHITECTURE 또는 CONVENTION 규칙>
  - **발견일 / 리포터**: YYYY-MM-DD / <역할 id>
  - **현황 및 부채 내용**: <현재 상태 및 해결 필요 사항>
  - **계획**: <진입 예정 DEV-PROP 큐 또는 해결 티켓>
```

### 등록된 Drift 목록

- **[DRIFT-001]** `mcp_server.py::call_tool`, `instructions.py::match_lorebook_entries` 등 레거시 함수
  - **위반 규칙**: CONVENTION §2.2 함수 80줄 상한 (`FUNC_MAX_LINES=80`)
  - **발견일 / 리포터**: 2026-10-06 / `dev`
  - **현황 및 부채 내용**: 현재 `tests/test_file_sizes.py`의 `FUNC_CEILINGS` 래칫으로 동결되어 추가 증가는 차단되어 있으나, 단일 책임 원칙에 따른 단계적 분리 필요.
  - **계획**: [monolith-split.md](plans/monolith-split.md) 후속 티켓을 통해 단계적 분리 및 래칫 축소 예정.

- **[DRIFT-002]** 서브프로세스 및 외부 비동기 호출 타임아웃 전수 점검
  - **위반 규칙**: CONVENTION §2.3 비동기 30초 타임아웃 규약
  - **발견일 / 리포터**: 2026-10-06 / `dev`
  - **현황 및 부채 내용**: 워치독이 적용되지 않은 일부 보조 도구 및 서브프로세스 호출에서 명시적 `timeout=30` 누락 가능성 존재.
  - **계획**: prop/B (신규 컨벤션 검사기) 개발 후 정적 스캔을 통해 전수 식별 및 일괄 패치 예정.

---

## 5. Archived History (완료 전파 아카이브)

Active Queue에서 모든 모듈 체크리스트가 완료(`[x]`)된 항목은 결정 D-3에 따라 즉시 마감 후 이 섹션으로 이동하여 영구 보존한다.

### 아카이브 서식 (Template)

```markdown
### [DEV-PROP-xxx] <전파 항목 제목> (완료)
- **완료일**: YYYY-MM-DD
- **주관 티켓 / 머지 커밋**: #<티켓번호> (<커밋 해시 또는 브랜치>)
- **결과 요약**: <완료 내용 요약 1~2문장>
- **영향 모듈**: <완료된 주요 모듈 목록>
```

*(현재 완료되어 아카이브된 전파 항목 없음)*
