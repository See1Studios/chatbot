# chatbot 모노리스 분리 (동작 불변)

> 방향 (align/D, 2026-09-28): **개발 기반** — 파일 크기·구조 규칙. 누가 개발하든 필요하고 배포판 동작과는 무관

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

5. ✅ **폴더 시범 `providers/`** (FOLDERS_PROVIDERS_v1, #123): 프로바이더 모듈 9개를 `providers/`로(파일 이름 유지). 호출부는 `from providers import accounts` / `from providers.adapters import ...`로 모듈 이름을 그대로 둬서 사용처는 안 바뀜 — import 47줄, 문자열 경로 몇 곳. 발견: 보호 규칙 `*.py`는 루트만 덮어서, 옮기기만 하면 코드가 보호에서 빠진다 → `protected_paths.json`에 `providers/`, 가드 `tests/test_code_layout.py`. 나머지 폴더(`core/`·`sessions/`·`team/`·`ops/`)는 보류(사용자, 2026-09-24): 새 파일은 그룹 접두어로.

6. ✅ **`chat.css`** (CSS_SPLIT_v1, #124): 1,839줄 → 순서를 지킨 여섯 조각 `chat-base/log/composer/panes/responsive/features.css`(147–547줄). 이어 붙이면 원래와 규칙 단위로 같다. 테스트는 `tests/page_source.css_source()`로 합본을 읽고, 크기 상한·링크 누락은 `test_page_scripts`가 본다.

알려진 것: 테스트를 한 프로세스에서 한꺼번에(`unittest discover`) 돌리면 실패한다 — 몇 모듈이 전역(`instructions.WORKSPACE` 등)을 임시 폴더로 바꾸고 되돌리지 않아서. 규칙은 모듈별 실행(`for f in tests/test_*.py; do python3 -m unittest tests.$(basename $f .py); done`). 격리 정리는 Phase 6 `split/A`다.

## Phase 6 — 구조 부채 실측 (2026-09-28)

Phase 0–5는 **크기**를 다뤘다. 이 단계는 그 규칙이 통과하는 것과 통과하는 것을 구분해 잰다 — `test_file_sizes`와 `test_page_scripts`를 모두 통과한 트리에 남는 부채.

측정 트리: `72acf1a` 이후, edition 경계 작업 착수 전. 아래 숫자는 그때의 실측이고 항목마다 재는 방법을 적었다. **규칙이 이미 잡는 것(파일 크기·페이지 스크립트·프로바이더 중립성·문서 규칙)은 제외**했다.

### 6.1 실측

| 측정 | 값 | 다시 재는 방법 |
|---|---|---|
| 단일 프로세스 전체 실행 | **93 실패 / 1,190 테스트** (모듈 104개) | `run-tests.sh` 대신 `unittest`로 `tests.test_*` 전체를 한 프로세스에 로드 |
| 모듈별 프로세스 실행 | 102/103 모듈 통과, 224초 | `./run-tests.sh` |
| 대문자 모듈 전역을 가진 모듈 | 42개 (`host_config` fan-in 25) | `ast`로 모듈 최상위 대입과 `import` 별칭 집계 |
| import 순환 | 3쌍 + 자기참조 1 | `ast` 임포트 그래프 DFS |
| 60줄 이상 함수 | 34개 | `ast` 함수별 `(end_lineno - lineno)` |
| 미해소 상한 | `session.py` 여유 **0줄**, `server.py` 여유 **+22줄** | `test_file_sizes`의 `CEILINGS`와 실제 길이 |

### 6.2 항목

| id | 지점 | 측정 | 리팩터 방향 | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|---|
| `split/A` | **테스트 격리** | 93/1,190 실패. 원인: 대문자 모듈 전역 42개와 되돌리지 않는 캐시 2개 — `characters.py::_CARD_INFO_CACHE`, `workspace_status.py::_SKILLS_CACHE` | DI가 아니라 **리셋 지점** 하나와 캐시 명시적 리셋. 테스트 하네스로 전역 격리 | 단일 프로세스 0 실패. `run-tests.sh`는 그대로 통과. `host_config` 공개면 안 바뀜 | 2 · — | M | — | ✅ #544 — 실측(10/2): 빈 데이터 탓 16개를 뺀 진짜 격리 실패 102개 중 100개가 **한 모듈** `test_account_login`이 import 때 `HOME`·데이터·코드 위치·CLI 경로를 `os.environ`에 박아 `host_config`를 프로세스째 굳힌 것(git 사용자 없음, 코드 위치 이동, 판 설정 무시). 고침: 환경 변수 대신 로그인 코드가 읽는 값만 모듈이 도는 동안 바꿈. 남은 둘은 `mcp_server`의 판·호스트 플러그인이 먼저 import한 모듈 때문 — 쓰는 모듈 셋이 도는 동안만 고정. 캐시 2개·전역 42개는 범인이 아니었음. 결과: 한 프로세스 1,809개 통과, 라이브 데이터 변화 없음. `./run-tests.sh --one-process`로 다시 잼 |
| `split/B` | **`server.py` 라우터** | 1,478줄 중 719줄이 라우팅. `server.py::_do_GET` 366줄/54분기, `do_POST` 353줄/50분기, 라우트 문자열 35개, 테이블 디스패치 0개. 여유 +22줄 | `(method, path pattern) → handler` 테이블, 도메인별 핸들러 모듈로 | 라우팅이 표 1곳에서 보임. 새 엔드포인트가 상한을 넘지 않음 | 2 · ⚡ | M | — | ✅ #534 — `server.py` 77,091B → 약 32KB. 경로는 `server.py`의 방식별 표(`GET_ROUTES` 등) 한 곳, 처리 함수는 `route_sessions`·`route_accounts`·`route_files`, 맞추기는 `route_table`. 도메인 모듈의 제각각 진입점은 고치지 않고 표의 어댑터(`route_table.api`·`gift`)로 받음. 옛 코드와 새 코드를 빈 임시 데이터로 나란히 띄워 요청 102개(이상한 경로·교차 출처·형식 오류·크기 초과 포함)의 응답이 상태·헤더·본문까지 같음을 확인 |
| `split/C` | **`session.py` 경계** | 2,298줄 / 상한 2,298 → **여유 0줄**. `session.py::_send_direct` 200줄, `_tool_summary` 180줄(지금 `session_view.py::SessionView._tool_summary`) | `turn_watchdog.py`를 뽑은 같은 방식으로 문 responsibility 경계 | 한 줄도 못 붙이는 상태가 끝남. 상한을 낮추고 테스트로 고정 | 2 · ⚡ | M | — | **1단 ✅ #539** — 보여주기 메서드 다섯(`_tool_summary`·`to_public`·`get_log`·`get_artifacts`·`get_handover_summary`)을 믹스인 `session_view.py`로(`turn_watchdog.py`와 같은 방식). 119,633B → 98,453B, 천장도 그만큼 내림. 테스트가 바꾸는 경로 값은 부를 때마다 `session`에서 읽음. 옛/새 코드 응답 111개 같음. **2단 ✅ #540** — 턴 실행 여섯(`send`·`_start_turn`·`_run_btw`·`interrupt_current_turn`·`_rotate_to_fresh_session`·`continue_to_successor`)을 믹스인 `session_turn.py`로. `session.py` 73,028B — **상한 80,000B 아래, 천장 항목 삭제**. `session.py`가 정의하거나 테스트·`server.py`가 바꿔치기하는 이름(`REG`·`boot_notice`·`build_instruction_bundle`·`_oneshot`·`evolution` …)은 `_s().이름`으로 부를 때마다 읽음 |
| `split/D` | **`characters`·`identity` 순환** | `identity.py` 238줄에 안쪽 `import characters` **11회, 17개 함수**. `characters.py`가 `parse_frontmatter` 하나 때문에 `identity`를 씀 | 카드 원본을 읽는 얇은 공유 계층을 만들고 양쪽이 그걸 읽게 한다. 세 순환이 한 번에 풀려야 한다 | 순환 0. 안쪽 import 0. 계층 방향을 가드로 못 박아야 한다(계측은 `ast`) | 2 · — | M | split/A | 대기 |
| `split/E` | **생성물 커플링** | `protected_manifest.json`이 소스 옆에 커밋되고, 보호 파일을 건드리면 `evolution.py`의 `manifest-update`을 사람이 돌려야 한다. 테스트는 계속 추가 중 | 스텝을 자동화하거나, 커밋 대상에서 빼고 doctor에서 만든다 | 보호 파일 변경 뒤 사람이 손대지 않아도 가드가 통과 | 2 · — | S | — | 대기 |
| `split/F` | **`static/role.js`** | 308줄. `index.html`이 참조하지 않고 `static/` 안에서도 아무도 부르지 않는데 `ratchet_baseline.json`에 남아 래칫이 세고 있다 | 쓰는 곳을 찾아 연결하거나, 죽은 파일이면 지우고 래칫 기준선에서 뺀다 | `ratchet_baseline.json`에 없는 파일은 어디에서도 로드되지 않음 | 2 · — | S | — | ✅ #532 — 죽은 파일이라 지움. 같이: 쓰는 곳 없던 `_touch_assistant_delta` 별칭과 늘 `_last_turn_activity_at`과 같던 옛 기록값 |
| `split/0` | **상한 기준** | 줄 수는 읽는 양을 못 잼: `app-shell.js` 740줄 41.6KB ≈ `app.js` 980줄 42.6KB. 상한을 맞추려 한 줄에 우겨 넣은 문장(`session.py`, 335자) | 파일은 바이트, 함수는 줄 수로 잰다(6.7 결정 D1) | 두 테스트가 바이트·함수 래칫을 강제 | 0 · — | S | — | ✅ #530 |
| `split/G` | **`tools/worktree_runner.py`** | 1,499줄 / 82,775B(상한 80,000 초과, 천장 고정). `tools/worktree_runner.py::cmd_run` 319줄 | `cmd_run`을 단계별로(준비·실행·관문·검토·병합). 그 뒤 위임 측정 기록(D1 ③) | 파일이 80,000B 아래로, `cmd_run` 천장을 낮춤 | 2 · — | M | — | ✅ #541 — 검토 프롬프트·diff 맞추기·판정 읽기(`review_prompt`·`doc_review_prompt`·`fit_diff`·`parse_review`·`DOC_CHECKLIST` …)를 `tools/review_checklist.py`로(러너가 다시 가져와 씀), `cmd_run`에서 인자 검사·티켓 얻기·새 작업 사본 만들기를 단계 함수로. 82,775B → 77,791B, `cmd_run` 319 → 282줄. **이제 크기 천장에 걸린 파이썬 파일 없음**(`CEILINGS` 빔). D1 ③도 #543으로 끝 |

### 6.3 순서와 충돌

`split/A` → `split/B` → `split/C` → `split/D`, `split/E`·`split/F`는 독립. 수령 대비 순서: `split/A`가 압도적이다(8% 테스트가 그 위에 있고 프로덕션 위험이 거의 없다).

**경고 — 이미 손이 가고 있다.** edition 경계(`align/I` 계열, `host_config.EDITION` + `test_edition_boundary`) 작업이 `host_config.py`·`mcp_server.py`·`run-tests.sh`·`protected_paths.json`을 고쳤다. `split/A`는 `host_config`의 경로 전역을 다루므로 **그 작업이 끝나기 전에 착수하지 않는다.** `split/B`는 `server.py`만이라 lesser conflict지만, 라우팅이 `mcp_server`를 호출하므로 순서를 본다.

### 6.4 손대지 말 것 (측측 결과 판단)

- **프런트 전역**: 23개 클래식 스크립트에 최상위 선언 571개지만 **이름 충돌은 3개뿐**(`api`, `stripOuterParens`, `BASE_PATH`). `app.js` 933줄 + 파트 13개가 전부 1,000줄 미만이고 `test_page_scripts`가 가짜 브라우저로 로드까지 검증한다. Phase 2가 이미 해냈다.
- **계층 방향 자체**: 순환이 3쌍이고 무한 층상 순환은 아니다. `host_config` fan-in 25는 그 파일이 SSOT이므로 설계다.
- **파일 크기 규칙 자체**: Phase 5가 만들었다. Phase 6은 여유분을 벌기 위한 것이지 상한을 올리려는 것이 아니다. 재는 단위는 6.7 D1에서 바이트로 바꿨다(상한은 그대로 래칫).

### 6.5 이 부채와 시장 쪽의 관계 (알아둘 것)

이 여섯 항목은 전부 **공급 쪽**이다. [market-direction-review.md](market-direction-review.md) §2.4가 지적한 "공급이 수요 증빙보다 한 사이클 앞선다"는 판정은 이 Phase를 시작해도 그대로다. `split/B`는 여유 22줄이 급해 언젠가는 필요하지만, 그 급함은 **데모(그 문서의 `rev/D`)를 만들고 나서도 그대로**다. 순서를 뒤집을 이유는 없지만, "구조를 다듬었으니 이제 수요 측이다"로 읽으면 안 된다.

### 6.6 재실측 (2026-10-01, `6c1d2fe`)

| 측정 | 6.1(9/28) | 지금 |
|---|---|---|
| 상한 여유 | `session.py` 0줄, `server.py` +22줄 | `session.py` 1줄, `server.py` 4줄(#178에서 전용 천장이 빠져 일반 상한 1,500), `tools/worktree_runner.py` **1줄**(새로 막힘) |
| 라우팅 | GET 366줄/54분기, POST 353줄/50분기 | GET 362줄/`If` 55, POST 361줄/`If` 52. 도메인 모듈 12개로 `or` 위임하는 선례가 있으나 호출 모양이 넷(`api(method, path, body)`, `handle_get(path)`, `handle(path, headers, rfile)`, `dispatch_push_api(handler, …)`) — split/B는 이것을 하나로 맞추는 일 |
| `session.py` 큰 함수 | `_send_direct` 200, `_tool_summary` 180 | `session.py::AgentSession._start_turn` 186, `_tool_summary` 180, `get_artifacts` 101 |
| 60줄 이상 함수 | 34 | 37 |
| import 순환 | 3쌍 + 자기참조 1 | 최상위끼리 1쌍(`mcp_server`↔`nas_mcp_host`). 함수 안 import 포함 상호 참조 6쌍, 함수 안 로컬 import 126개 |
| 단일 프로세스 실행 | 93 / 1,190 | 115 / 1,788(실패 55 + 오류 60; `test_delegation` 45, `test_mcp_server` 31). 데이터 폴더를 빈 임시 폴더로 돌려 잼 — 빈 데이터 탓인 실패가 섞였을 수 있음 |

### 6.7 결정

| id | 결정 | 근거 | 결정자·날짜 |
|---|---|---|---|
| D1 | 크기 상한을 ① 파일 **바이트**(파이썬 80,000, 화면 스크립트·스타일 43,000 — 당시 1,500줄·1,000줄의 크기)와 ② 파이썬 **함수 80줄**로 잰다. 넘은 것은 지금 값이 천장이고 내려가기만 한다(래칫 유지). ③ 위임 러너가 티켓마다 대상 파일 크기·소요 시간·결과를 남겨 다음 숫자를 데이터로 정한다 — ✅ #543: 실행 상태 파일(`~/.worktrees/chatbot/runs/ticket-N.json`)의 `target_bytes`(시작 때 대상 파일별 바이트)·`started`·`ended_<결과>`(`tools/worktree_runner.py::path_bytes`) | 목적은 "가벼운 모델이 한 번에 읽고 고치나": 읽는 비용은 토큰(≈ 바이트), 고치는 단위는 함수. 근거였던 #113은 대상 파일을 잘못 짚은 실패가 섞인 한 건(원인은 `session.py`). 줄 상한의 부작용: #515가 무관한 줄을 지움, #503이 서버 필드 대신 글 속 인용을 고름 | 운영자, 2026-10-01 (#530) |

## 검증 방법 (매 Phase 공통)

`py_compile`/`node --check` → `chatbot-ctl.sh guard` → (코어면) 실장님 ⚡소생
→ `probe_message` PASS → 이 문서에 `## Phase N 진행 상태` 기록 → DEVLOG.
