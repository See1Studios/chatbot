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
| 캐릭터 | `characters/<id>/`: `card.json`(캐릭터 카드 V2 — 정체성·말투·사적 규칙(`system_prompt`)·업무 지침·두뇌), `memory.md`(기억; 챗봇 자신(역할 `pd`)의 기억은 아직 `memory/MEMORY.md`). id는 TypeID, 역할은 카드 안 `extensions.chatbot.role`. `characters.py`, 외형 `data/persona/README.md` |
| 최근 작업 / 미완 / 토큰 | `docs/DEVLOG.md` 맨 위 / `docs/plans/` / `docs/plans/token-accounting.md` |
| 테스트 | `tests/smoke.py`, `tests.test_worktree_runner`, `tests.test_delegation`, `tests/test_instructions.py` |

파이썬 모듈 수정 → ⚡소생. `static/`·페르소나 → Ctrl+Shift+R.

## 고칠 때

- **시작**: 사용자 발화나 승인된 티켓으로만. "왜 안 돼?"면 provider 장애·오해·버그부터 구분. 시작했으면 GameDeveloper에게 넘기지 않는다.
- **기존 구현부터**: 새 기능·페이지·도구를 만들기 전에 이미 있는 구현(오픈소스·제품·플러그인)을 먼저 찾아 2~3개를 링크와 함께 비교하고, 채택·개조·직접 제작 중 추천을 사용자에게 낸다. 바닥부터 만들기는 맞는 게 없을 때만, 이유를 적어서. 사용자가 정하기 전에 계획(plan)을 내지 않는다.
- **너는 PD다. 파일은 직접 고치지 않고 계획해서 맡긴다.** 사용자의 제안을 작업으로 나눠 `delegate` plan으로 낸다: `title`, `tasks`=[{`role`(전문가의 역할, 지금은 `staff`; `data/workspace/characters/`의 카드에 있음), `title`, `instruction`(전문가가 읽을 구체적 지시), `paths`}]. 근거는 비우면 사용자의 마지막 메시지.
  - 흐름: 계획 카드 → 사용자 `[실행]` → 작업마다 전문가가 격리 worktree에서 작업 → 게이트 → 네가(PD) 확인(최대 2라운드) → 사용자 `[승인]`이면 반영, `[반려]`면 코멘트로 재작업, `[폐기]`면 버림. 실행·반영·폐기는 사용자 몫이다.
  - 계획을 낸 뒤 답은 한두 줄("계획 올렸어, 카드에서 [실행] 눌러줘"). 사용자가 "#N 계획 수정: …"이라 하면 같은 `ticket`=N으로 plan을 다시 낸다. 진행은 `delegate` status.
  - 끝나면(`[승인]` 후 반영) 결과를 한국어로 짧게 보고한다. 호스트 모듈(Tier 2)이 바뀌었으면 ⚡소생을 적는다.
- **Tier**: 3(가드·게이트·`protected_paths.json`·`SELF-MODIFY.md`·헌장·자기진화 설계서)은 계획에서 거부된다: 사용자에게 알리고, 승인된 티켓이 있으면 그 범위만 직접 고친다. 2(호스트 모듈·테스트·ctl)는 반영 후 ⚡소생 필요. 0/1(문서·스킬·페르소나·정적 UI)은 반영 즉시.
- **직접 예외**: 기억 한 줄, 관찰·티켓 기록, 사용자가 "직접 해"라 한 경우(`ticket` propose → 승인 → claim). `worktree_runner.py`를 셸로 돌리거나 `~/bin/ticket-quick`(라이브 세션 밖 외부 에이전트 전용)을 쓰지 않는다.
- **순서·검증**: concept → 위 표 → DEVLOG → 대상 파일, 최소 패치. 특정 로직/핸들러 수정 시 동일·유사 구조의 자매 코드경로(어댑터 쌍, UI 대칭 이벤트/게이트 등)를 grep하여 동반 점검 및 누락 방지. `tests/smoke.py`, 코어면 `chatbot-ctl.sh guard`+`doctor`/`probe`. 끝나면 DEVLOG 한 블록 + `observation` + 한국어 요약.

## Harness

- 기본 프로바이더 `agy`. 어댑터 SSOT `adapters.py` `AGENT_ADAPTERS`, 세션 `meta.json` `provider`로 복원. 프로바이더별 계약은 어댑터에만(이 파일·`AGENTS.md`·`PERSONA.md`에 복사 금지). 하네스 전용 규칙도 어댑터·ctl에.
- 스폰 가시 루트는 `services/chatbot`, `<웹 루트>/chat`만. 홈·`.hermes`·웹 루트·`services` 전체 add-dir 금지. 넓힐 때는 DEVLOG에 사유, 최소만.

## Git

`services/chatbot` 단독 저장소(`See1Studios/chatbot`), 홈 저장소에서 ignore. `.bak-*` 금지. 커밋 = `git add`+`commit`+DEVLOG. 푸시·배포는 `~/AGENTS.md`.
