# chatbot

Sphere Hub NAS chat agent. **이 프로젝트를 스스로 유지한다.** 경계 `SELF-MODIFY.md`, 라이브 사망 `docs/EMERGENCY.md`, 원칙 `cross-cutting-principles.md`, 기조 `docs/concept.md`(코드 만지기 **전에** 연다).

## Paths

루트 `~/services/chatbot/`(코드+데이터, 독립 Git). 웹 루트는 env `AGY_CHAT_WEB_ROOT`(이 배포: `/volume1/web`).
- 데이터: `data/workspace/`·`sessions/`·`persona/`. 기억 `data/workspace/memory/MEMORY.md`. 티켓 `data/workspace/skill-observations/tickets/`
- 위임 상태: `~/.worktrees/chatbot/runs/ticket-<id>.json`(러너가 씀, `/api/delegations`). 읽음 `data/delegation_seen.json`
- 세션: `data/sessions/<id>/meta.json` + `artifacts/brain/*` → `/artifacts/<id>/brain/<file>`. 공유 `data/sessions/_shared/`
- 웹(레포 밖): FAB `<웹 루트>/index.html`, 페르소나 퍼블리시 `<웹 루트>/chat/persona/`
- 기동은 ctl만(`chatbot-ctl.sh`, LAN `0.0.0.0`). `python3 server.py`는 127.0.0.1 전용. 포트 3011 chat(`AGY_CHAT_PORT`), 3012 NAS MCP(`NAS_MCP_PORT`)

## Where to edit

새 파일 전에 해당 칸을 고친다. 코드 폴더를 새로 만들면 `protected_paths.json`에 넣는다(`tests/test_code_layout.py`). 새 모듈은 그룹 접두어를 붙인다(`session_`, `adapter_`, …). 페이지 스크립트는 한 파일 1,000줄 미만(`tests/test_page_scripts.py`, `docs/plans/monolith-split.md` Phase 5).

| 작업 | 파일 |
|---|---|
| 경로·포트·env·토큰 임계값 | `host_config.py` |
| 프로바이더 CLI/HTTP·계정 | `providers/`: `adapters.py`(목록·`get_adapter`) + `adapter_base.py`(공통) + `adapter_<agy|claude|grok|codex|openai>.py`, `accounts.py`·`account_login.py`; `data/providers.json` |
| 세션 수명·스폰·lock / 세션 목록·최신 찾기 / 가중치·/btw / 대기 풀 | `session.py` / `session_registry.py` / `session_weights.py` / `standby_pool.py` |
| 아티팩트 저장 / 미디어 | `artifact_manager.py` / `media_handler.py` |
| HTTP 라우트 / 프리뷰 화이트리스트 | `server.py` / `preview_guard.py` |
| 워크스페이스 상태 / 툴 로그 포맷 | `workspace_status.py` / `tool_format.py` |
| MCP 서버 / 코어 도구(memory·observation·ticket) / NAS 전용 | `mcp_server.py` / `mcp_core.py` / `nas_mcp_host.py`. 서버 이름 `nas`는 각 provider 설정 키라 바꾸지 않는다 |
| 지침 조립 | `instructions.py` + `session.py` `_send_direct()` (`docs/plans/instruction-architecture.md`) |
| 위임 | `delegation.py`, `mcp_server.py` `delegate`, `tools/worktree_runner.py`(Tier는 `protected_paths.json` `governance`) |
| UI | `static/`: `app.js`(전역·전송·부팅, 로드 때 도는 코드는 여기만) + 먼저 로드되는 부분들 `app-api` `app-device` `app-messages`(말풍선·공지) `app-turn`(진행 표시) `app-activity`(로그 탭) `app-evolution`(개선 탭·티켓·작업 카드) `app-status`(상태 탭) `app-sessions-tab` `app-team` `app-sse` `app-session`(세션 열기·이동) `app-characters`(캐릭터·프로바이더 선택기) `app-viewport`; `theme.js`+`chat.css` `markdown.js` `artifacts.js` `slash.js` `model-picker.js` `index.html` |
| 시각 시스템 | `DESIGN.md` + `.impeccable/design.json` |
| 캐릭터 | `characters/<id>/`: `card.json`(캐릭터 카드 V2 — 정체성·말투·사적 규칙(`system_prompt`)·업무 지침·두뇌), `memory.md`(그 캐릭터의 기억). 집 기억(사용자·호스트 사실, 모든 캐릭터가 읽음) `memory/MEMORY.md`. id는 TypeID. 카드에는 역할이 없다: 역할 팩 `roles/<role>/role.md`(지침·스킬·도구 권한), 편성 `team.json`(기본 캐릭터, 누가 어떤 역할). `characters.py`, 외형 `characters/<id>/visual.md` + 이미지(형식·절차: 스킬 `character-art`, 검사 `tools/check_character_art.py`) |
| 최근 작업 / 계획 상태 | `docs/DEVLOG.md` 맨 위(지난 날짜 `docs/devlog/YYYY-MM-DD.md`) / `docs/plans/INDEX.md` — 계획 문서는 인덱스에서 골라 연다 |
| 테스트 | `tests/smoke.py`, `tests.test_worktree_runner`, `tests.test_delegation`, `tests/test_instructions.py` |

파이썬 모듈 수정 → ⚡소생. `static/`·페르소나 → Ctrl+Shift+R.

## 고칠 때

- **시작**: 사용자 발화나 승인된 티켓으로만. "왜 안 돼?"면 provider 장애·오해·버그부터 구분. 시작했으면 GameDeveloper에게 넘기지 않는다.
- **기존 구현부터**: 새 기능·페이지·도구를 만들기 전에 이미 있는 구현(오픈소스·제품·플러그인)을 먼저 찾아 2~3개를 링크와 함께 비교하고, 채택·개조·직접 제작 중 추천을 사용자에게 낸다. 바닥부터 만들기는 맞는 게 없을 때만, 이유를 적어서. 사용자가 정하기 전에 계획(plan)을 내지 않는다.
- **역할별 절차**: 맡은 역할 팩(`roles/<role>/role.md`)을 따른다. PD의 계획·위임·확인·보고, Tier, 직접 예외는 `roles/pd/procedure.md`(매 턴 들어가는 짧은 부분은 `role.md`).
- **순서·검증**: concept → 위 표 → DEVLOG → 대상 파일, 최소 패치. 특정 로직/핸들러 수정 시 동일·유사 구조의 자매 코드경로(어댑터 쌍, UI 대칭 이벤트/게이트 등)를 grep하여 동반 점검 및 누락 방지. `tests/smoke.py`, 코어면 `chatbot-ctl.sh guard`+`doctor`/`probe`. 끝나면 DEVLOG 한 블록 + `observation` + 한국어 요약.

## Harness

- 기본 프로바이더 `agy`. 어댑터 SSOT `providers/adapters.py` `AGENT_ADAPTERS`, 세션 `meta.json` `provider`로 복원. 프로바이더별 계약은 어댑터에만(이 파일·`AGENTS.md`·`PERSONA.md`에 복사 금지). 하네스 전용 규칙도 어댑터·ctl에.
- 스폰 가시 루트는 `services/chatbot`, `<웹 루트>/chat`만. 홈·`.hermes`·웹 루트·`services` 전체 add-dir 금지. 넓힐 때는 DEVLOG에 사유, 최소만.

## Git

`services/chatbot` 단독 저장소(`See1Studios/chatbot`), 홈 저장소에서 ignore. `.bak-*` 금지. 커밋 = `git add`+`commit`+DEVLOG. 푸시·배포는 `~/AGENTS.md`.
