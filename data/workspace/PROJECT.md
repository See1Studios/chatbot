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

새 파일 전에 해당 칸을 고친다. `static/app.js`를 더 쪼개지 말 것(`docs/plans/monolith-split.md`).

| 작업 | 파일 |
|---|---|
| 경로·포트·env·토큰 임계값 | `host_config.py` |
| 프로바이더 CLI/HTTP | `adapters.py`, `data/providers.json` |
| 세션 수명·스폰·lock / 가중치·/btw / 대기 풀 | `session.py` / `session_weights.py` / `standby_pool.py` |
| 아티팩트 저장 / 미디어 | `artifact_manager.py` / `media_handler.py` |
| HTTP 라우트 / 프리뷰 화이트리스트 | `server.py` / `preview_guard.py` |
| 워크스페이스 상태 / 툴 로그 포맷 | `workspace_status.py` / `tool_format.py` |
| MCP 서버 / 코어 도구(memory·observation·ticket) / NAS 전용 | `mcp_server.py` / `mcp_core.py` / `nas_mcp_host.py`. 서버 이름 `nas`는 각 provider 설정 키라 바꾸지 않는다 |
| 지침 조립 | `instructions.py` + `session.py` `_send_direct()` (`docs/plans/instruction-architecture.md`) |
| 위임 | `delegation.py`, `mcp_server.py` `delegate`, `tools/worktree_runner.py`(Tier는 `protected_paths.json` `governance`) |
| UI | `static/`: `app.js`(세션·SSE·작업 카드) `theme.js`+`chat.css` `markdown.js` `artifacts.js` `slash.js` `model-picker.js` `index.html` |
| 시각 시스템 | `DESIGN.md` + `.impeccable/design.json` |
| 캐릭터 | `data/workspace/PERSONA.md`(PD, 챗봇 자신), `PERSONA-staff.md`(role `staff`, 작업자), 외형 `data/persona/README.md` |
| 최근 작업 / 미완 / 토큰 | `docs/DEVLOG.md` 맨 위 / `docs/plans/` / `docs/plans/token-accounting.md` |
| 테스트 | `tests/smoke.py`, `tests.test_worktree_runner`, `tests.test_delegation`, `tests/test_instructions.py` |

파이썬 모듈 수정 → ⚡소생. `static/`·페르소나 → Ctrl+Shift+R.

## 고칠 때

- **시작**: 사용자 발화나 승인된 티켓으로만. "왜 안 돼?"면 provider 장애·오해·버그부터 구분. 시작했으면 GameDeveloper에게 넘기지 않는다.
- **파일 변경은 `delegate`가 기본**(직접 고치지 않음): `title`·`paths`·`instruction`(근거는 비우면 사용자의 마지막 메시지). 스태프가 격리 worktree에서 고치고 PD(이 페르소나)가 확인해 PASS/FAIL(최대 2라운드), 사용자는 작업 카드에서 본다. 답은 한두 줄, 진행은 `delegate` status, 병합·폐기는 사용자 몫.
- **Tier**: 0/1(문서·스킬·페르소나·정적 UI) 바로 시작 → 게이트·리뷰 통과 시 병합. 2(호스트 모듈·테스트·ctl) 티켓 제안 → `[맡겨]`/`[병합·⚡]`. 3(가드·게이트·`protected_paths.json`·`SELF-MODIFY.md`·헌장·자기진화 설계서)은 `delegate`가 거부한다: 사용자에게 알리고, 승인된 티켓이 있으면 그 티켓 범위만 직접 고친다.
- **직접 예외**: 기억 한 줄, 관찰·티켓 기록, 사용자가 "직접 해"라 한 경우(`ticket` propose → 승인 → claim). `worktree_runner.py`를 셸로 돌리거나 `~/bin/ticket-quick`(라이브 세션 밖 외부 에이전트 전용)을 쓰지 않는다.
- **순서·검증**: concept → 위 표 → DEVLOG → 대상 파일, 최소 패치. `tests/smoke.py`, 코어면 `chatbot-ctl.sh guard`+`doctor`/`probe`. 끝나면 DEVLOG 한 블록 + `observation` + 한국어 요약.

## Harness

- 기본 프로바이더 `agy`. 어댑터 SSOT `adapters.py` `AGENT_ADAPTERS`, 세션 `meta.json` `provider`로 복원. 프로바이더별 계약은 어댑터에만(이 파일·`AGENTS.md`·`PERSONA.md`에 복사 금지). 하네스 전용 규칙도 어댑터·ctl에.
- 스폰 가시 루트는 `services/chatbot`, `<웹 루트>/chat`만. 홈·`.hermes`·웹 루트·`services` 전체 add-dir 금지. 넓힐 때는 DEVLOG에 사유, 최소만.

## Git

`services/chatbot` 단독 저장소(`See1Studios/chatbot`), 홈 저장소에서 ignore. `.bak-*` 금지. 커밋 = `git add`+`commit`+DEVLOG. 푸시·배포는 `~/AGENTS.md`.
