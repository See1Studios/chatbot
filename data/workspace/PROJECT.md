# chatbot

Sphere Hub NAS chat agent. **이 프로젝트를 스스로 유지한다.**

일상 UI/호스트/페르소나/스킬 수정은 여기. 자기수정 경계는 `SELF-MODIFY.md`, 라이브 사망은 `docs/EMERGENCY.md`, 설계 원칙은 `cross-cutting-principles.md`.

## Paths

상대경로 기준: `~/services/chatbot/` (코드+데이터 한 트리). 웹 루트는
하드코딩이 아니라 env `AGY_CHAT_WEB_ROOT`(`host_config.py`) — **이 배포의 실제
값**: `/volume1/web` (다른 배포는 다를 수 있음, `docs/plans/chatbot-host-portability.md`).

| 무엇 | 어디 |
|---|---|
| 코드 | 아래 **Where to edit**. 엔트리 `server.py` — 운영 기동은 ctl만(`chatbot-ctl.sh`가 LAN용 `AGY_CHAT_HOST=0.0.0.0`을 export). `python3 server.py` 직접 실행은 `127.0.0.1` 로컬 전용 |
| 데이터 | `data/workspace/`, `data/sessions/`, `data/persona/` |
| 장기 기억 | `data/workspace/memory/MEMORY.md` (`tools/memory.py`) |
| Hub FAB | `<웹 루트>/index.html` (`AGY_CHAT_FAB_*` — 이름만 레거시). 이 레포 밖 |
| 페르소나 퍼블리시 | `<웹 루트>/chat/persona/` |
| ctl | `~/services/chatbot-ctl.sh` (이 트리의 `chatbot-ctl.sh`와 동일) |
| 포트 | 3011 (chat, env `AGY_CHAT_PORT`), 3012 (NAS MCP, env `NAS_MCP_PORT`) |

## Where to edit

이어받는 에이전트는 이 표만 보고 연다. 새 파일을 만들기 전에 해당 칸을
고친다. `static/app.js`에 SSE/세션/전송·상태 탭·프로바이더 트레이를 더
쪼개지 말 것 (`docs/plans/monolith-split.md`).

코드를 만지기 **전에** `docs/concept.md`(최대 가치·목표)를 연다. 패치는 그 기조로만 빌드업한다.

| 작업 | 파일 |
|---|---|
| 제품 기조 (최대 가치·목표) | `docs/concept.md` — 수정·개발 시 항상 |
| 경로·포트·env·토큰 임계값 | `host_config.py` |
| 프로바이더 CLI/API (agy/claude/grok/codex + HTTP dialect) | `adapters.py`. HTTP 엔드포인트·키·모델·뱃지는 `data/providers.json` |
| 세션 수명·스폰·로테이트·AgySession.lock | `session.py` (`ctl guard` AST가 여기) |
| 세션 가중치·토큰 집계·/btw 샛길 질의 | `session_weights.py` |
| 웜 에이전트 대기 풀 (스탠바이) | `standby_pool.py` |
| 아티팩트 경로·원자적 파일 저장 | `artifact_manager.py` |
| 미디어/이미지 수집·마크다운 URL 치환 | `media_handler.py` |
| HTTP 라우트·`main` | `server.py` |
| 파일 프리뷰 보안 화이트리스트 | `preview_guard.py` |
| 워크스페이스 규칙/스킬/MCP 상태 | `workspace_status.py` |
| 툴 로그 한 줄 포맷 | `tool_format.py` |
| MCP 도구 서버 (파일·명령·플러그인 배선. 서버 이름 `nas`는 각 provider의 설정 키라 그대로) | `mcp_server.py` |
| 코어 MCP 도구 (`memory`·`observation`·`ticket`) | `mcp_core.py` — 코어 호출만 하는 어댑터 |
| 이 NAS 전용 MCP (`ping_nas`·`list_services`·`service_ctl`·`wiki`, Sphere/Hermes) | `nas_mcp_host.py` |
| 채팅 세션 / SSE / 전송 | `static/app.js` |
| 테마·헤더 메뉴 | `static/theme.js` + `static/chat.css` |
| 마크다운·머메이드 | `static/markdown.js` |
| 아티팩트 탭 | `static/artifacts.js` |
| `/` 메뉴 | `static/slash.js` |
| 모델 선택 버튼·메뉴, 입력창 placeholder(현재 모델) | `static/model-picker.js` (값의 원천은 숨긴 `<select id="model">`) |
| 셸 마크업 | `static/index.html` |
| 시각 시스템 | `DESIGN.md` + `.impeccable/design.json` |
| 페르소나 | `data/workspace/PERSONA.md` (말투·호칭). 시각 빌드업 `data/persona/README.md` |
| 지침 묶음 조립·주입 | `instructions.py` + `session.py` `_send_direct()`. 설계 `docs/plans/instruction-architecture.md`, 테스트 `python3 tests/test_instructions.py` |
| 방금 뭐 했는지 | `docs/DEVLOG.md` 맨 위 |
| 미완 시퀀스 | `docs/plans/` |
| 토큰 집계 | `docs/plans/token-accounting.md`, `data/workspace/tools/token_audit.py` |
| 스모크 | `python3 tests/smoke.py` |

파이썬 호스트 모듈을 고치면 ⚡소생. 정적(`static/`·페르소나)은 Ctrl+Shift+R.

## 고칠 때 (자기수정 절차)

- **시작**: 실장님 발화 또는 승인된 티켓으로만. "왜 안 돼?"만으로 Tier 2+를 시작하지 않는다 — provider 장애·오해인지 우리 버그인지부터 구분한다. 시작했으면 GameDeveloper에게 넘기지 말고 직접 고친다.
- **순서**: `docs/concept.md` → 위 표 → `docs/DEVLOG.md` 맨 위 → 대상 파일. 가장 작은 패치로. 하네스 전용 규칙은 `AgentAdapter`·ctl에 두고 헌장·페르소나에 넣지 않는다.
- **Tier**: 0/1(기억 한 줄·페르소나·정적 UI·새 스킬 스크립트)은 수정 → 테스트 → 사후 보고. 2(호스트 모듈·ctl)는 디스크 수정 후 실장님께 **⚡소생**. 3(가드·`protected_paths.json`·`SELF-MODIFY.md`·헌장·이 설계서)은 승인된 티켓 없이 시작하지 않는다. 승인되면 그 티켓 범위만 고친다.
- **검증·기록**: `python3 tests/smoke.py`, 코어를 건드렸으면 `chatbot-ctl.sh guard` + `doctor`/`probe` (`healthz`만으로는 부족). 끝나면 DEVLOG 한 블록 + `observation` 한 건 + 한국어 요약.

## Harness

- 제품 호스트는 켜 둔 채로 어댑터를 붙인다. 기본 프로바이더: `agy`.
- 어댑터 SSOT: `adapters.py` → `AGENT_ADAPTERS`. 세션 `meta.json`의 `provider`로 복원.
- 프로바이더별 계약(플래그, usage, stdin vs one-shot, conversation id)은 어댑터에만. 이 파일·`AGENTS.md`·`PERSONA.md`에 복사하지 말 것.
- 스폰 가시 루트는 좁게: `services/chatbot`, `<웹 루트>/chat`(env `AGY_CHAT_WEB_ROOT`). 홈 전체 / `.hermes` / 웹 루트 전체 / `services` 전체를 add-dir 하지 말 것. 추가는 DEVLOG에 사유를 남기고 최소만.

## Git

홈 루트 단일 repo (`~/`, origin `See1Studios/HermesBackup`). `chatbot/`는 별도 repo가 아니다. 옛 분리 repo 히스토리는 `~/tmp-trash-2026-09-16/` — 되살리지 말 것.
디스크 수정 후 `.bak-*` 만들지 말 것. `git add` + `git commit` (홈 루트) + `docs/DEVLOG.md`.
push 절차는 `~/AGENTS.md`.

## Sessions

- `data/sessions/<id>/meta.json` + `artifacts/brain/*`
- URL: `/artifacts/<id>/brain/<file>`
- 공유 자산: `data/sessions/_shared/` → `/artifacts/<rel>`
