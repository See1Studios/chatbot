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

Code map, engine rules, SSOT map, commit and ticket procedure: repo-root `AGENTS.md` (`~/services/chatbot/AGENTS.md`). Kept there only — do not copy it back here.

## 고칠 때

- **시작**: 사용자 발화나 승인된 티켓으로만. "왜 안 돼?"면 provider 장애·오해·버그부터 구분. 시작했으면 GameDeveloper에게 넘기지 않는다.
- **기존 구현부터**: 새 기능·페이지·도구를 만들기 전에 이미 있는 구현(오픈소스·제품·플러그인)을 먼저 찾아 2~3개를 링크와 함께 비교하고, 채택·개조·직접 제작 중 추천을 사용자에게 낸다. 바닥부터 만들기는 맞는 게 없을 때만, 이유를 적어서. 사용자가 정하기 전에 계획(plan)을 내지 않는다.
- **역할별 절차**: 맡은 역할 팩(`roles/<role>/role.md`)을 따른다. PD의 계획·위임·확인·보고, Tier, 직접 예외는 `roles/pd/procedure.md`(매 턴 들어가는 짧은 부분은 `role.md`).
- **순서·검증**: concept → 루트 `AGENTS.md` 코드 지도 → DEVLOG → 대상 파일, 최소 패치. 특정 로직/핸들러 수정 시 동일·유사 구조의 자매 코드경로(어댑터 쌍, UI 대칭 이벤트/게이트 등)를 grep하여 동반 점검 및 누락 방지. `./run-tests.sh`(저장소 루트), 코어면 `chatbot-ctl.sh guard`+`doctor`/`probe`. 끝나면 DEVLOG 한 블록 + `observation` + 한국어 요약.

## Harness · Git

Repo-root `AGENTS.md` (provider contracts live in `providers/adapter_<name>.py` only).
