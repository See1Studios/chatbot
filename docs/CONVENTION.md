# PE 개발 엔지니어링 컨벤션 (Engineering Conventions)

> 방향: **개발 기반** — Private Engine(PE) 소프트웨어 엔지니어링 및 개발 거버넌스 컨벤션 정본 (SSOT)
> 관련: [ARCHITECTURE.md](ARCHITECTURE.md) · [STATE.md](STATE.md) · [propagation-and-state-architecture.md](plans/propagation-and-state-architecture.md) · [monolith-split.md](plans/monolith-split.md) · [../AGENTS.md](../AGENTS.md)
> 관할: 저장소 소스 코드를 작성·수정·검토하는 모든 에이전트 및 개발자

---

## 1. 개요 및 거버넌스 원칙

본 문서는 Private Engine(PE) 코드베이스의 장기적 유지보수성, 안정성, 자가진화 신뢰성을 보장하기 위한 엔지니어링 컨벤션의 단일 진실 공급원(SSOT)이다.

- **개발 거버넌스 전용**: 본 컨벤션은 엔진 소스 코드(`*.py`, `providers/`, `tools/`, `static/`, `tests/`) 및 개발 절차에만 적용된다.
- **런타임 엔진 거동 분리**: 대화 모델 추론, 캐릭터 페르소나 및 발화 연기, 텐션/호감도 FSM, UI 대화 렌더링 프로토콜 등 런타임 챗 에이전트의 행동 양식은 `$CHATBOT_DATA/workspace/AGENTS.md` 및 역할 팩(`roles/<role>/`)의 관할이며 본 컨벤션의 대상이 아니다.
- **기계적 집행 원칙**: "문서에만 있는 규칙은 없는 규칙이다." 모든 컨벤션 규칙은 가드 테스트 또는 커밋 훅을 통한 자동 강제를 목표로 하며, 본 문서에서는 **[현재 운영 중인 가드]**와 **[신설 예정 강제 메커니즘]**을 명확히 구분하여 기술한다.

---

## 2. 핵심 컨벤션 규약

### 2.1 Mandatory Test Pairing (테스트 페어링 의무)

- **원칙**: 모든 기능 추가(`feat`), 버그 수정(`fix`), 리팩토링(`refactor`), 성능 개선(`perf`)은 반드시 해당 변경 사항을 직접 검증하는 테스트 코드(`tests/`)와 1:1로 페어링되어 커밋되어야 한다. 테스트 없는 제품 코드 수정은 허용되지 않는다.
- **[현재 상태]**:
  - 규칙으로 확립되어 있으며, 커밋 훅(`.githooks/check_staged.py`)의 가드 테스트 실행 및 워크트리 러너 리뷰(`tools/review_checklist.py`) 시 테스트 동반 여부를 인간/리뷰어 에이전트가 확인하여 관리한다.
- **[신설 예정 강제 메커니즘]**:
  - 커밋 훅 레벨에서 제품 코드 변경 시 대응하는 `tests/` 변경이 없는 커밋을 기계적으로 거부하는 검사기 도입.
  - 워크트리 러너 리뷰 체크리스트(`tools/review_checklist.py`) 연동을 통해 Mandatory Test Pairing 기계 확인 자동화.

### 2.2 함수 80줄 / 모듈 80KB 상한 (Function & Module Ceilings)

- **원칙**:
  - 단일 함수(메서드 포함)의 길이는 **최대 80줄**(`FUNC_MAX_LINES=80`) 이하로 유지한다.
  - 단일 모듈의 파일 크기는 **최대 80,000 바이트**(`MAX_BYTES=80_000`, 약 80KB)를 초과할 수 없다.
  - 목적: 단일 책임 원칙 준수, 컨텍스트 토큰 예산 절약, 에이전트가 단일 턴에서 전체 모듈을 안전하게 파악하고 수정할 수 있는 크기 보장. 복잡도 누적 시 조기 모듈/함수 분리([monolith-split.md](plans/monolith-split.md))를 유도한다.
- **[현재 운영 중인 가드]**:
  - **이미 상시 기계적으로 완전 강제 중**: `tests/test_file_sizes.py`의 `FUNC_MAX_LINES=80` 및 `MAX_BYTES=80_000` 가드가 `run-tests.sh --fast` 및 pre-commit 훅을 통해 매 커밋마다 자동 실행된다.
  - 과거 레거시에서 80줄을 초과했던 일부 함수는 `FUNC_CEILINGS` 래칫 테이블로 동결 관리되며, 이 상한은 오직 줄어들기만 하고 늘어날 수 없다.
- **[예정 집행]**: 기존 래칫 초과 함수들의 점진적 리팩토링 및 래칫 상한 축소 지속.

### 2.3 비동기 30초 타임아웃 규약 (Async 30s Timeout)

- **원칙**:
  - 모든 비동기 작업(`asyncio`), 서브프로세스 호출(`subprocess.run`), 외부 HTTP 통신, 대화 턴 실행 등 대기 가능성이 있는 모든 블록에는 **최대 30초 타임아웃**을 기본 규약으로 명시한다.
  - 무한정 블로킹되는 비동기 작업은 세션 전체의 프리징 및 리소스 고갈을 초래하므로, 어떠한 외부 I/O나 비동기 대기도 타임아웃 없이 호출될 수 없다.
- **[현재 상태]**:
  - 런타임 워치독(`turn_watchdog.py`)의 세션 턴 실행 감시 및 빠른 실패(Fail-Fast: `QUOTA_FAILFAST`, `SILENT_HANG`)가 일부 적용되어 있음.
  - 개별 서브프로세스 및 CLI 어댑터 호출부에서 개별 timeout 파라미터 지정 운영.
- **[신설 예정 강제 메커니즘]**:
  - 비동기 함수 및 `subprocess` 호출 전반에서 명시적 `timeout` 인자 누락을 탐지하는 정적 검사기 및 가드 테스트(`tests/test_conventions.py` 등) 신설.

### 2.4 업무 대화 및 사담 상한 규약 (Work Banter Limit)

- **원칙**:
  - 에이전트 간 위임 대화, 작업 핸드오프(`dialog_handoff.py`), 커밋 메시지, PR 및 작업 카드 보고 시 캐릭터 페르소나에 기반한 사담은 **최대 1~2문장**으로 엄격히 제한한다.
  - 기술적 분석, diff, 테스트 결과, 실패 원인 등 핵심 정보만을 군더더기 없이 간결하게 교환한다.
  - 목적: 에이전트 간 협업 시 불필요한 토큰 낭비 방지, 컨텍스트 오염 차단, 장애 분석 및 디버깅 가독성 극대화.
- **[현재 상태]**:
  - 에이전트 프롬프트 지침(`roles/dev/PROCEDURE.md`, 위임 프롬프트)을 통해 1~2문장 제한 지시.
- **[신설 예정 강제 메커니즘]**:
  - 워크트리 러너의 보고서 검증기(`tools/worker_output.py`) 및 리뷰 체크리스트(`tools/review_checklist.py`) 연계를 통해 보고 메시지 내 사담 분량 자동 판정 및 점검.

---

## 3. 컨벤션 강제 메커니즘 요약표

| 컨벤션 규칙 | 상한 / 기준 | 현재 강제 수단 | 신설 예정 강제 수단 | 관련 문서 및 가드 |
|---|---|---|---|---|
| **Mandatory Test Pairing** | 모든 코드 변경에 1:1 테스트 동반 | 커밋 훅 가드 실행, 리뷰어 확인 | 테스트 미동반 커밋 기계적 거부 훅, 워크트리 리뷰 연동 | `.githooks/check_staged.py`, `tools/review_checklist.py` |
| **함수 줄 수 상한** | 최대 80줄 (`FUNC_MAX_LINES=80`) | **[기계적 상시 강제]** `run-tests.sh --fast` | 레거시 `FUNC_CEILINGS` 래칫 단계적 축소 | `tests/test_file_sizes.py` |
| **모듈 바이트 상한** | 최대 80,000 바이트 (`MAX_BYTES=80_000`) | **[기계적 상시 강제]** `run-tests.sh --fast` | 대형 모듈 분리 지속 | `tests/test_file_sizes.py` |
| **비동기 타임아웃** | 최대 30초 기본 타임아웃 | 턴 워치독 일부 감시, 호출부 개별 지정 | 전수 타임아웃 정적 린터 및 전용 가드 테스트 | `turn_watchdog.py`, `tests/test_conventions.py`(예정) |
| **업무 사담 상한** | 최대 1~2문장 | 프롬프트 지침 | 워커 보고서 검증기 및 리뷰 체크리스트 자동 판정 | `tools/worker_output.py`, `tools/review_checklist.py` |
