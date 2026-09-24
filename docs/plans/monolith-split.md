# chatbot 모노리스 분리 (동작 불변)

## Context

`server.py` ~4920줄, `static/app.js` ~4021줄, `static/index.html` 인라인 CSS
~1470줄이 한 파일에 붙어 있다. 호스트 일반화·API 어댑터 계획(Phase 전부 완료)은
기능 추가였고, 이번은 **동작 불변 코드 분리**. UI 비주얼/카피/테마는 건드리지
않는다. `index.html`/`app.js`는 파일 경계만 옮긴다.

`nas_mcp.py` + `nas_mcp_host.py`와 같은 패턴: 엔트리 스크립트는 그대로
`python3 server.py` / 브라우저 `index.html`. 패키지화하지 않는다.

## 설계 확인 (실장님, 2026-09-19)

코드 리팩터. UI 비주얼 리디자인이 아님. UI 파일의 코드 구조는 범위에 포함.

## Phase 0 — 상수·포맷·어댑터 분리 + 채팅 CSS 추출

**파일**: `host_config.py`, `tool_format.py`, `adapters.py`, `server.py`,
`static/chat.css`, `static/index.html`

- `host_config.py`: env/경로/토큰 임계값/`DEFAULT_PROVIDER`/`_now`/데이터 디렉터리
  mkdir. `server.py`와 `adapters.py`가 같이 읽는다.
- `tool_format.py`: `_clean_str`/`_short_path`/`_format_tool_call`/
  `_format_tool_result` (세션 상태 없음. 어댑터와 `AgySession`이 둘 다 씀).
- `adapters.py`: `AgentAdapter` + 5 구현 + MCP JSON-RPC 헬퍼 + `AGENT_ADAPTERS` +
  `get_adapter`.
- `server.py`: `AgySession`/`Registry`/`Handler`/`main`만. `ctl guard_rlock`이
  이 파일의 `AgySession.lock = threading.RLock()`을 AST로 검사하므로 세션
  클래스는 아직 여기 둔다.
- `static/chat.css`: `index.html` `<style>` 원문 이동. 링크만 추가. 셀렉터·값
  변경 없음.

**검증**: `python3 -m py_compile host_config.py tool_format.py adapters.py
server.py`, `node --check static/app.js`, `chatbot-ctl.sh guard`. 라이브는
`server.py` 변경이라 ⚡소생 후 `healthz` + `GET /api/providers`에 기존 5종이
그대로인지.

## Phase 0 진행 상태: 구현 + 실측 완료 (2026-09-19)

디스크 반영 완료. `server.py` 4920→2862, `adapters.py` 1881, `host_config.py` /
`tool_format.py` 신설. `static/chat.css`는 라이브 프로세스가 정적 파일을 디스크에서
읽으므로 `GET /chat.css` 200·`index.html` 링크 실측됨. 파이썬 모듈 분리는
⚡소생 전까지 구 프로세스.

- `py_compile` 4파일 OK, `node --check static/app.js` OK, `guard_rlock` OK.
- import 실측: `AGENT_ADAPTERS` 5종, `get_adapter("agy").id == "agy"`.
- 라이브 소생 후: `healthz` ok, `GET /api/providers` 5종, 기존 세션
  `20260918-224646-8bfbd3` 유지, `probe_message OK`.

## Phase 1 — AgySession / Registry 분리

**파일**: `session.py` (가칭), `server.py`, `chatbot-ctl.sh` `guard_rlock`

- `AgySession` + `Registry` + `_StandbyPool`을 `session.py`로.
- `guard_rlock`의 검사 경로를 `server.py` → 세션 모듈로 바꾼다. `RLock` 계약은
  불변.
- `Handler`는 `server.py`에 남긴다.

**검증**: `py_compile`, `guard` (새 경로), ⚡소생 후 기존 세션 id 유지,
`probe_message` PASS.

## Phase 1 진행 상태: 구현 + 실측 완료 (2026-09-19)

- `session.py`(신규, 2040줄): 세션 헬퍼 + `_StandbyPool` + `AgySession` +
  `Registry`/`REG` + `_record_live_pids`/`_reap_sessions`.
- `server.py` 2862→858줄: HTTP `Handler`/`main` + 상태/스킬/MCP 엔드포인트만.
- `chatbot-ctl.sh` `guard_rlock` 검사 경로 `server.py` → `session.py`.
  `RLock` 계약 불변. `guard_rlock OK` 실측.
- `py_compile` 5파일 OK. import 실측: `server.AgySession is session.AgySession`,
  lock 타입이 RLock, `STANDBY_POOL._proc is None`(import만으로 스폰 안 함).
- 라이브 소생 후 Phase 0과 같은 실측(providers 5종, 기존 세션, probe PASS).

## Phase 2 — `static/app.js` 모듈 분할

번들러 없음. `index.html`에 스크립트 태그를 순서대로 추가하는 방식.
후보 경계(부팅 순서 의존을 깨지 않는 선에서 다시 자른다):

- 마크다운/머메이드/코드 하이라이트
- SSE/세션/전송
- 프로바이더 트레이/테마
- 마스코트
- 슬래시 메뉴
- 아티팩트/상태 탭

**검증**: `node --check` 각 파일, 정적 새로고침만. 소생 불필요.

고전 `<script>`는 파일 간 `const`/`let`이 안 보인다. 공유 상태는 `var`
(또는 다음 슬라이스에서 모듈). 로드 순서: `app.js` 다음 기능 파일 — `boot()`의
첫 `await` 전에 동기 스크립트가 끝나게.

## Phase 2 진행 상태: 여기까지 (2026-09-19)

세션/SSE/전송·상태 탭·프로바이더 트레이는 `app.js`에 둔다. 더 쪼개면
이득보다 고전 스크립트 `var` 결합이 커짐. 실장님: 무리하지 말 것.

로드 순서: `app.js?v=51` → `theme.js` → `markdown.js` → `artifacts.js` →
`slash.js` → `mascot.js`. 공유 상태 `var`: `currentTab`, `sessionId`,
`inputEl`, `mascotOverlay`, `isMascotVisible`.

| 파일 | 내용 |
|---|---|
| `theme.js` | 테마 스와치 + 헤더 overflow 메뉴 |
| `markdown.js` | marked/mermaid/hljs, `renderMarkdown`, 라이트박스 훅 |
| `artifacts.js` | 아티팩트 탭·모달·무한스크롤 |
| `slash.js` | `/` 메뉴 |
| `mascot.js` | Live2D 마스코트 |

- `app.js` 4021→~3000 (세션/SSE/전송 + 상태 탭 + 프로바이더 트레이).
- `node --check` 전원 OK, 라이브 GET 각 js 200. **정적만 — 소생 불필요.**

## Phase 3 — 백엔드 심층 모듈 분리 (2026-09-20)

`session.py` (2,554줄) 및 `server.py` (1,054줄)의 비대화와 단일 책임 원칙 준수를 위해 독립 서브모듈 분리:

- `artifact_manager.py`: 안전한 세션 ID(`_safe_session_id`), 원자적 파일 쓰기(`_atomic_write_text`), 아티팩트 서빙 경로 탐색(`_safe_artifact_rel`)
- `standby_pool.py`: 웜 프로세스 풀(`_StandbyPool`, `STANDBY_POOL`) 및 마커 수명주기
- `session_weights.py`: 세션 부하도/가중치(`_session_weight`), 토큰 통계(`_billed_tokens`, `_current_context_tokens`), 샛길 질의 판별(`_is_inquiry`), 프롬프트 템플릿
- `preview_guard.py`: 파일 프리뷰/다운로드 화이트리스트 보안 가드(`_resolve_safe_preview_file`, `_preview_allowed`)
- `workspace_status.py`: 룰/스킬/MCP 설정 조회 및 갱신(`_self_status`, `_get_workspace_skills`, `_read_mcp_config`, `_write_mcp_config`)
- `media_handler.py`: Grok/Gemini 이미지 수집, 마크다운 이미지 URL 변환, 세션별 격리 서빙 스테이징

**결과**: `session.py` 2,554줄 → 1,998줄 (2,000줄 미만 경량화), `server.py` 1,054줄 → 841줄.

## Phase 4 — 신규 모듈 단위 테스트 및 위생 정리 (2026-09-20)

- `tests/test_refactored_modules.py` 신설: 신규 분리 모듈 4종(`standby_pool`, `artifact_manager`, `session_weights`, `workspace_status`)에 대한 전용 단위 테스트 7개 추가.
- `server.py`, `session.py`, `static/app.js` 내 데드 코드 및 중복 유틸 정리.
- 전체 단위 테스트 209개 전원 통과 확인 (`Ran 209 tests OK`).

## Phase 5 — 다시 커진 `app.js`·`session.py` (2026-09-24, 실장님 승인)

**왜 다시**: `static/app.js` 6,197줄(Phase 2 뒤 ~3,000 → 두 배), `session.py` 2,601줄. 위임 작업 #113이 가벼운 모델로 `app.js`를 읽다가 20분 제한에 걸려 한 줄도 못 고치고 실패했다 — 파일이 크면 챗봇 위임이 계속 실패한다.

**원칙**: 동작·화면·문구 불변(Phase 0–4와 같음). 번들러 없음, 고전 `<script>` 순서 로드. 한 파일 1,000줄 미만을 테스트로 강제(`mcp_server.py` 700줄 가드와 같은 방식).

순서:
1. ✅ **안전망** (TEST_BASELINE_v1, #116): 오래전부터 실패하던 테스트 4개를 현재 동작에 맞춤 — conversation_sync(TURN_END_ORDER_v1: 어댑터는 종료 이벤트를 돌려주고 멈춤은 세션이 flush 뒤에), observation_ui(개선 탭 재설계·OBS_HISTORY_v1·문구 "작업/이슈"), served_model(캐시 버전 고정값 → 정규식), status_picker(AUTH_GATE_v1: 못 쓰는 프로바이더도 상태 보기는 가능, 표시만). 덤으로 버그 하나: 중지를 누른 뒤 agy의 "interrupted"가 에러 공지로 남던 것(`adapters.py`). 이제 모듈별 실행 전부 통과.
2. ✅ **`app.js` 기능별 분리** (APP_SPLIT_v1, #117): 6,197줄 → `app.js` 931줄 + 13개 부분(가장 큰 `app-status.js` 923줄). 부분 파일은 **선언만** 담고 `app.js`보다 먼저 로드된다. 로드 때 실행되는 코드(리스너 연결, 타이머, `applyIdentity()`, `boot()`)는 16개 덩어리 모두 `app.js`의 원래 자리에 남겼다 — 그래서 실행 순서는 전과 같다. 옮기기는 스크립트로 했고 줄 보존(빠진 줄·중복 줄 0)을 대조했다.
   - 부분: `app-api`(api·탭 전환·소생) `app-device`(위치·시간대) `app-messages`(말풍선·공지·푸터·TTS·스크롤) `app-turn`(전송 버튼·진행 표시) `app-activity`(로그 탭) `app-evolution`(개선 탭·티켓·작업 카드) `app-status`(상태 탭: 프로바이더·계정·로그인·사용량·지침·스킬·MCP·훅) `app-sessions-tab` `app-team` `app-sse`(`bindEvents`) `app-session`(모드 전환·세션 열기·재동기화·스크롤백·최신 점프) `app-characters`(정체성·캐릭터·프로바이더 선택기) `app-viewport`(입력창 높이·키보드).
   - 테스트: `tests/page_source.py`가 `index.html` 순서대로 이어 붙인 합본을 주고(파일마다 `// ==== file:` 표시), 잘라 읽는 node 테스트는 그걸 읽는다. `tests/test_page_scripts.py`: 부분마다 1,000줄 미만, 모든 부분이 `app.js`보다 먼저 로드, 가짜 브라우저에서 전체를 순서대로 로드해 로드 시 오류 0.
   - 새 부분을 만들 때: 선언만 두고, 로드 때 도는 문장은 `app.js`에, `index.html`에서 `app.js` 앞에 태그.
3. ✅ **`session.py`** (REGISTRY_SPLIT_v1, #118): 세션 목록·조회(`Registry`, 최신 세션 찾기, SESSION_INDEX_v1 요약 캐시, 세션 캐릭터 이전, 첫 두뇌)를 `session_registry.py`(297줄)로. `session.py` 2,601 → 2,335줄. `session.py`가 같은 이름으로 다시 내보내므로 호출부는 그대로(`from session import REG, Registry`). 새 모듈은 `session`의 값(SESSIONS·WORKSPACE·AgentSession·기본값)을 복사하지 않고 부를 때마다 읽는다 — 테스트가 `session.SESSIONS`를 임시 폴더로 바꾸기 때문. `session_registry`는 직접 import하지 않는다(`session`을 통해서만).

4. ✅ **`adapters.py`** (ADAPTER_SPLIT_v1, #122): 2,422줄 → 허브 138줄(목록·`get_adapter`·다시 내보내기) + `adapter_base`(298, 프로바이더 이름 없음 — 중립성 테스트 대상) + `adapter_agy/claude/grok/codex/openai`(299–627). 모든 프로바이더 파일은 `adapter_base`에만 의존. `tests/test_file_sizes.py`: 파이썬 모듈 1,500줄 상한, 이미 넘은 `session.py`·`server.py`는 현재 크기가 천장.

알려진 것: 테스트를 한 프로세스에서 한꺼번에(`unittest discover`) 돌리면 ~40개가 실패한다 — 몇 모듈이 전역(`instructions.WORKSPACE` 등)을 임시 폴더로 바꾸고 되돌리지 않아서. 규칙은 모듈별 실행(`for f in tests/test_*.py; do python3 -m unittest tests.$(basename $f .py); done`). 격리 정리는 별도 작업.

## 검증 방법 (매 Phase 공통)

`py_compile`/`node --check` → `chatbot-ctl.sh guard` → (코어면) 실장님 ⚡소생
→ `probe_message` PASS → 이 문서에 `## Phase N 진행 상태` 기록 → DEVLOG.
