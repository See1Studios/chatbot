# 모델 쿼터 소진·한도 도달 및 제공자 장애 대응 강화 (quota-failure-resilience)

> 방향 (align/D, 2026-10-02): **기반** — AI 모델 쿼터 소진(Individual quota reached), 서브스크립션 한도 초과 및 스트림 장애 시 침묵하지 않고 즉시 사용자 화면에 경고 카드(.msg.system.notice-warn)를 띄우고, 원클릭 대체 모델 전환 및 사전 쿼터 고갈 경고를 제공하는 복원력 강화 계획
> 상태: **active** (2026-10-02 수립)
> 목적: 모델 쿼터 소진 및 제공자 장애로 인한 대화 단절·침묵을 방지하고, 직관적인 시각 피드백과 원클릭 모델 스왑 인터랙션을 제공하여 무중단 대화 경험을 보장한다.
> 관련: [api-adapter-parity.md](api-adapter-parity.md) · [../ARCHITECTURE.md](../../ARCHITECTURE.md) · [../VISION.md](../../VISION.md)

---

## 1. 배경 및 문제 의식

2026-10-01 및 2026-10-02 실사용 과정에서 주요 AI 모델(Gemini/Claude 등)의 쿼터 소진 및 서브스크립션 한도 초과 장애가 반복적으로 관측되었습니다.

```text
[실제 장애 로그 사례]
status=ERROR, error=Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 1h59m32s., 39초
```

엔진 내부에는 쿼터 오류 발생 시 8초 만에 턴을 조기 마감하는 `QUOTA_FAILFAST_v1` 워치독(`turn_watchdog.py::TurnWatchdog`)이 구현되어 있으나, 사용자 대화 화면 관점에서는 여전히 다음과 같은 심각한 UX 및 신뢰도 결함이 존재합니다.

### 4대 결함

1. **불친절하고 단조로운 에러 노출**:
   - 턴 실패 시 채팅창에는 raw 텍스트 형태의 시스템 안내(`[시스템 안내] 에이전트가 답을 내기 전에 턴이 끝났습니다...`)만 밋밋하게 표시됩니다.
   - 사용자 입장에서는 단순 일시 오류인지, 쿼터 소진인지, 네트워크 단절인지 한눈에 파악하기 어렵습니다.
2. **원클릭 복구 및 대체 모델 전환 경로 부재**:
   - 쿼터 소진 안내에 재설정 시간(`Resets in 1h59m32s`)이 명시되어 있어도, 사용자가 다른 가용 모델(예: Flash, Grok, Claude 등)로 즉시 전환할 수 있는 액션 버튼이 없습니다.
   - 상단 모델 선택 메뉴나 설정 패널을 찾아 직접 수동으로 교체해야 하는 번거로움이 발생합니다.
3. **사전 경고(Threshold Warning)의 부재**:
   - `route_accounts.py::_get_usage` 및 각 프로바이더 어댑터(`providers/adapter_base.py::AgentAdapter`)의 `rate_limit_report()`를 통해 쿼터 잔여량을 파악할 수 있음에도, 쿼터가 10% 이하로 고갈 직전일 때 사전 알림을 주지 않습니다.
   - 중요한 작업 도중 갑작스럽게 턴이 끊기는 문제가 지속됩니다.
4. **제공자별 에러 형식의 비정규화**:
   - 각 CLI/HTTP 제공자마다 쿼터 오류 문구(`429`, `ResourceExhausted`, `Individual quota reached`, `rate_limit_error`)가 제각각이라 프론트엔드가 이를 공통 규격으로 다루지 못하고 있습니다.

---

## 2. 목표 및 핵심 원칙

1. **실패를 숨기지 않고 명확히 소통 (Failfast & Transparent Notice)**:
   - 장애나 쿼터 고갈이 발생했을 때 침묵하거나 무한 대기하지 않고, 8초 내에 전용 경고 카드(`.msg.system.notice-warn`)로 사용자에게 상황을 명확히 전달합니다.
2. **원클릭 복구 동선 (Actionable Recovery)**:
   - 경고 카드 내에 즉시 대체 가능한 모델 전환 버튼(예: `[Gemini Flash로 전환]`, `[Grok으로 전환]`, `[새 세션 시작]`)을 인라인으로 제공하여 조작 비용을 최소화합니다.
3. **제공자 중립 에러 정규화 (Provider-Neutral Error Normalization)**:
   - 프로바이더별 에러 메시지를 공통 규격(`QuotaErrorInfo`: `code`, `reason`, `resets_in`, `provider`, `model`)으로 정규화하여 전달합니다.
4. **노-가드닝과 사전 예방 (Zero Gardening & Proactive Alert)**:
   - 잔여 쿼터가 10% 이하로 떨어지면 상태 탭 배지나 턴 시작 전 경고 안내를 통해 사용자가 사전에 인지하고 대응할 수 있도록 돕습니다.
5. **엄격한 크기 상한 준수 (Guard & Budget)**:
   - 파싱 로직은 백엔드 어댑터/워치독에 격리하고, UI 로직은 `static/app-messages.js`의 시스템 메시지 처리기에 최소한의 확장으로 안착시켜 43KB 상한(`test_page_scripts.py`)을 준수합니다.

---

## 3. 현황 점검 (2026-10-02 실측)

- **워치독 구현**: `turn_watchdog.py::TurnWatchdog`에 `ERROR_MESSAGE_FAILFAST_SEC = 8`로 조기 종료 로직(`_error_message_failfast`)이 동작 중입니다.
- **턴 종료 전달**: `session.py::AgentSession`의 `_end_unfinished_turn`에서 단순 문자열 힌트와 `notice:error` 이벤트를 발생시키고 있습니다.
- **사용량 조회 API**: `route_accounts.py::_get_usage`에서 프로바이더별 `rate_limit_report()` 결과를 캐싱(`USAGE_CACHE_TTL_SEC = 300`)하여 반환합니다.
- **클라이언트 상태**: `static/app-status.js`에서 프로바이더 사용량을 조회하지만, 채팅 화면(`static/app-messages.js`, `static/app-turn.js`)과의 유기적 경고 연동은 없습니다.

---

## 4. 세부 설계

### 4.1 에러 정규화 구조 (Backend)

`providers/adapter_base.py::AgentAdapter` 또는 `turn_watchdog.py::TurnWatchdog`에서 원시 에러 문자열을 분석하여 정규화된 쿼터 에러 객체를 생성합니다.

```json
{
  "is_quota": true,
  "code": "QUOTA_EXHAUSTED",
  "reason": "Individual quota reached",
  "resets_in": "1h59m32s",
  "provider": "agy",
  "model": "gemini-3.8-flash-high",
  "suggested_models": ["gemini-3.8-flash-low", "grok-beta", "claude-haiku"]
}
```

### 4.2 SSE 이벤트 및 시스템 카드 (Frontend)

1. **이벤트 전달**:
   - `_end_unfinished_turn` 실행 시 단순 `error` 텍스트 외에 `quota_info` 메타데이터가 포함된 시스템 이벤트를 발행합니다.
2. **UI 시스템 경고 카드 (`.msg.system.notice-warn`)**:
   - 노란색/주황색 테두리의 강조 카드 형태로 렌더링됩니다.
   - 아이콘: `⚠️ 쿼터 소진 안내`
   - 안내 문구: `현재 모델의 사용 한도에 도달했습니다. (재설정까지 약 1시간 59분 남음)`
   - 액션 버튼 바:
     - `[Flash 모델로 전환]`: 현재 세션의 모델을 즉시 가벼운 모델로 변경하고 마지막 메시지 재시도.
     - `[다른 계정/제공자 전환]`: 가용한 다른 제공자로 스왑.
     - `[새 대화 시작]`: 새로운 세션 열기.

### 4.3 사전 쿼터 고갈 경고 (Threshold Alert)

- `_get_usage` 조회 결과 중 잔여 비율(`remaining_pct`)이 10% 이하이거나 위험 임계치에 도달한 경우:
  - 상태 탭의 해당 프로바이더 행에 경고 배지 표시.
  - 대화창 진입 시 상단 헤더 서브타이틀 또는 턴 알림으로 `잔여 쿼터 10% 이하` 힌트 1회 표시.

---

## 5. 의사결정 (Decisions)

| ID | 안건 | 옵션 및 비교 | 추천안 | 상태 |
|---|---|---|---|---|
| **D1** | **쿼터 소진 시 UI 피드백 형태** | (1) 대화 흐름 내 인라인 경고 카드(`.msg.system.notice-warn`)<br>(2) 전체 화면 모달 팝업 차단 | **(1) 인라인 경고 카드**: 대화 맥락을 가리지 않고 원클릭 전환 버튼으로 자연스러운 흐름 유지 | 제안 |
| **D2** | **대안 모델 추천 정책** | (1) 동일 제공자 내 경량/대체 모델 우선 추천 후 타 제공자 제시<br>(2) 고정된 기본 폴백 모델 강제 전환 | **(1) 가용 대체 모델 추천**: 사용자의 선택권을 보장하며 즉시 원클릭으로 전환 지원 | 제안 |
| **D3** | **사전 경고 임계치 기준** | (1) 쿼터 잔여 10% 이하<br>(2) 쿼터 잔여 5% 이하 | **(1) 10% 이하**: 긴 턴(다중 툴 호출) 소비를 고려해 여유 있는 사전 전환 유도 | 제안 |
| **D4** | **스크립트 및 모듈 거버넌스** | (1) 파싱은 백엔드에 두고, 프론트는 기존 `.msg.system` 렌더러 확장<br>(2) 프론트에 정규식 파서 추가 | **(1) 백엔드 정규화**: 프론트 파일 크기(`test_page_scripts.py`) 상한을 보호하고 제공자 중립성 유지 | **합의** |

---

## 6. 마일스톤 및 작업 항목 (Milestones)

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `qfr/0` | **정식 계획 문서 수립 및 활성 인덱스 등록** | `docs/plans/quota-failure-resilience.md`<br>`docs/plans/INDEX.md` | 계획 문서 등록 및 `test_plans_index` 통과 | 0 · — | S | — | #566 |
| `qfr/A` | **쿼터/한도 에러 정규화 파서 및 워치독 연계** | `turn_watchdog.py`<br>`providers/adapter_base.py`<br>`tests/test_conversation_sync.py` | 쿼터 소진 에러 문자열에서 재설정 시간 및 원인을 정규화 객체로 추출 | 1 · ⚡ | S | `qfr/0` | ✅ #798 |
| `qfr/B` | **턴 종료 에러 시 구조화된 시스템 노티스 이벤트 방출** | `session.py`<br>`session_turn.py`<br>`session_view.py`<br>`tests/test_conversation_sync.py` | `_end_unfinished_turn`에서 쿼터/장애 정보를 담은 시스템 이벤트 SSE 브로드캐스트 | 1 · ⚡ | S | `qfr/A` | 대기 |
| `qfr/C` | **UI 쿼터 소진 경고 카드 및 원클릭 대안 모델 전환** | `static/app-messages.js`<br>`static/app-turn.js`<br>`static/chat-panes.css`<br>`tests/test_shell_page.py` | 대화창에 `.notice-warn` 카드 렌더링 및 원클릭 모델 스왑 버튼 클릭 시 즉시 전환 | 2 · — | M | `qfr/B` | ✅ #800 |
| `qfr/D` | **사전 쿼터 고갈 경고(10% 이하) 및 상태 탭 연동** | `route_accounts.py`<br>`static/app-status.js`<br>`tests/test_accounts.py` | 잔여 쿼터 10% 이하 시 상태 탭 경고 배지 및 사전 알림 연계 | 1 · ⚡ | S | `qfr/C` | ✅ #801 |

---

### 6.1 qfr/A 구현 메모 (2026-10-08, #798, QUOTA_STATE_v1)

- 운영자 2026-10-08: "에러가 다시 오는 걸 막아야 하지 않을까?" — 13:32 Claude 경로 쿼터 소진 뒤 같은 모델로 계속 보낼 수 있었다.
- 에러 문구가 아니라 **제공자의 사용량 보고**를 근거로 쓴다: `route_accounts._get_usage` 행을 어댑터의 `quota_view`가 이 모델 몫으로 읽는다(agy: 모델 그룹마다 5시간·주간 창, 남은 %와 재설정 시각). §4.1의 문자열 파서 대신이다.
- 실패한 턴(`finalize_turn`의 오류 알림)이 백그라운드에서 한 번 새로 읽어, 0%인 창이 있고 재설정이 남았으면 `quota_state`에 (제공자, 모델) → 재설정 시각을 기록한다. 메모리에만 둔다.
- 보내기 전에 기록된 모델이면 보내지 않고 `srv.quota_until`(「지금 두뇌(…)는 사용 한도에 닿아 HH:MM까지 쓸 수 없어요…」) 알림으로 답한다 — qfr/B의 일부. 재설정 시각이 지나면 풀린다. 카드의 전환 버튼은 qfr/C.

### 6.2 qfr/C 구현 메모 (2026-10-08, #800)

- 보낼 때 막힌 알림(`srv.quota_until`)에 엔진이 고른 대안 `suggest`를 싣는다: 같은 제공자의 `known_models` 순서에서 막힌 모델·기록상 바닥난 모델·캐시된 사용량 보고에 0% 창이 있는 모델을 빼고 최대 2개(`quota_state.alternatives`). 다른 제공자는 아직 권하지 않는다(로그인·계정이 달라 한 번에 바꾸기 어렵다).
- 화면은 알림 아래 「<모델>로 바꿔 다시 보내기」 버튼(`static/app-retry.js::quotaSwitchButtons`). 누르면 모델을 바꾸고(`pickModel`) 막힌 메시지(다시 보내기 대기)를 보낸다. 메시지가 현재 모델을 싣고 가서 서버가 먼저 바꾼 뒤 검사한다.
- 턴이 실패한 뒤의 오류 알림에는 아직 버튼이 없다: 그 순간에는 쿼터 기록이 백그라운드에서 만들어지는 중이다. 다음 보내기가 막히며 버튼이 나온다.

### 6.3 qfr/D 구현 메모 (2026-10-08, #801)

- 답이 나온 턴이 끝나면 백그라운드에서 그 두뇌의 캐시된 사용량 보고를 본다(보고는 route_accounts TTL마다 많아야 한 번 새로 읽힌다). 0% 초과 10% 이하인 창 중 가장 낮은 것이 재설정 전이면 대화에 한 번 알린다(`srv.quota_low`: 「지금 두뇌(…)의 5h 한도가 8% 남았어요 (18:25 재설정)…」). 같은 (제공자, 그룹, 창, 재설정 시각)은 한 번만(`quota_state.warn_low`).
- 페이지에는 턴 상태를 건드리지 않는 `notice` 이벤트가 새로 생겼다(`error`는 진행 중인 답을 지운다).
- 상태 탭 배지(§4.3)는 하지 않았다: shell2에는 상태 탭이 없고, 프로필의 쿼터 줄이 이미 남은 %를 보인다.

## 7. 의존 관계, 작업 순서 및 리스크

1. **작업 순서**: `qfr/0` (문서화) → `qfr/A` (에러 파싱/정규화) → `qfr/B` (이벤트 연계) → `qfr/C` (UI 카드 및 원클릭 전환) → `qfr/D` (사전 경고).
2. **리스크 및 대응**:
   - **CLI 프로바이더별 에러 형식 변경**: 정규식 파서가 일치하지 않더라도 기본 쿼터 안내 텍스트로 안전하게 폴백되도록 방어 로직을 둡니다.
   - **프론트엔드 파일 크기**: `app-messages.js` 및 `app-turn.js` 수정 시 43KB 상한선(`test_page_scripts.py`)을 넘지 않도록 스타일은 `chat-panes.css`에 분리합니다.

---

## 8. 하지 않는 것 (Out of Scope)

- 사용자 동의 없는 자동 강제 모델 교체 (반드시 사용자 승인/원클릭 확인을 거침).
- 외부 유료 API 결제 자동 결제 연동.
- 모든 서드파티 에러 상태 코드의 완벽한 100% 매핑 (주요 장애 패턴 위주로 단계적 정규화).
