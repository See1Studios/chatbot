# 재귀적 자기 개발·개선 설계서 v3 — Grok 교차 검증

- **대상**: [`recursive-self-evolution.md`](./recursive-self-evolution.md) v3
- **검증자**: Grok (Grok Build TUI, 2026-09-20). v2 리뷰 본문은 보지 않고, v3 §1~§2와 코드를 대조.
- **기준**: `docs/concept.md`, `data/workspace/SELF-MODIFY.md`, `data/workspace/cross-cutting-principles.md` #8 #9, `docs/plans/instruction-architecture.md` §6~§8, `docs/plans/chatbot-host-portability.md`
- **결론: 수정 후 착수.** Phase 0부터 가도 되는 방향이다. 다만 0-4 deny 목록이 호스트 파이썬 모듈을 빠뜨리고, 0-3 바인딩 주장은 ctl 경로에만 맞다. 그 두 줄을 고친 다음 Phase 0에 들어가면 된다. 재설계는 아니다.
- **이 검증에서 하지 않은 것**: 문서·코드 수정, `chatbot-ctl.sh stop|restart|repair|defibrillate`, `git worktree add`, defibrillate curl 실행.

`[신규]`는 이번 검증에서 코드로 잡은 항목.

---

## 확인한 것 / 확인하지 않은 것

확인함:

- `chatbot-ctl.sh` (`guard_rlock`, `probe_message`, `cmd_doctor`/`cmd_repair`/`require_host_force`, `cmd_start`의 `AGY_CHAT_HOST`)
- `host_config.py` `HOST` 기본값, `server.py` `main()` 바인딩, CORS, `/api/host/defibrillate`, `/api/rules` PUT
- `nas_mcp.py`/`nas_mcp_host.py` 허용 루트·`write_file`·`run_command`·`service_ctl`·플러그인 로딩
- `adapters.py` agy/claude/grok/codex 권한 플래그, MCP URL 하드코딩, omniroute `NAS_MCP_URL`
- `session.py` `_handle_events` / `_run_http_turn` / `interrupt_current_turn` / `_reap_sessions`
- `instructions.py` 배지, `workspace_status.py` `task_observer` 키
- `identity.py` 호칭 공급
- task-observer 심링크·훅·`task-observer-pre.sh` 절대경로
- `chatbot-self-improve/SKILL.md`
- `observe_add`/`on_turn_end`/`candidates.jsonl` — 파이썬 0건
- `PROJECT.md`·`README.md`·`monolith-split.md`의 `python3 server.py` 엔트리
- Hermes lifecycle / systemd user에 chatbot `server.py` 기동 없음
- `session.py` 1996줄, `adapters.py` 1930줄

확인하지 않음:

- DSM 스케줄러 DB, chattr, 챗봇 grok 자식의 상대경로 vs 절대경로 쓰기
- curl POST의 라이브 호출(코드상 허용만 확인)
- `hooks.json`이 agy 이외에서 도는지
- macOS/Windows

---

## §1 표 / §2 H1~H7 코드 대조

직접 확인한 범위에서 표는 대체로 맞다. 틀린 것·과장만 적는다.

| 항목 | 판정 |
|---|---|
| 관찰 배지, memory.py, loop_guard agy 전용, 원자적 쓰기, 209 테스트, `guard_rlock`, probe 모델 하드코딩, gate/promote 없음, observe_add/on_turn_end **파이썬 0건** | 맞음. task-observer는 심링크(`data/workspace/.agents/skills/task-observer` → `~/.agents/skills/task-observer`, SKILL.md 697줄). 훅은 `hooks.json` + `scripts/task-observer-pre.sh`에 `/volume1/homes/me/...` 하드코딩 |
| H1 repair 접두 | 맞음. `nas_mcp.py:80-82,369-382`, `ctl:390-392,519-521` |
| H2 `service_ctl start\|restart` | **절반만 맞음.** `start`는 티켓 없이 `cmd_start` (`nas_mcp.py:292-303`, `ctl:334-361`). **`restart`/`stop`은 `require_host_force`에 걸려 거절** (`ctl:501-511`). defibrillate 무인증 + CORS `*`는 맞음 (`server.py:200,561-569`) |
| H3 write_file + `/api/rules` | 맞음. `ALLOW_ROOTS`에 `services/chatbot` 전체 (`nas_mcp.py:40-47`). `host-force.ticket`은 파일명 정규식에 안 걸림 |
| H4 CLI 네이티브 쓰기 | agy/grok/codex 맞음. **claude는 이번에 확인 → Major 2** |
| H5 스킬 트리거 | 맞음. `chatbot-self-improve/SKILL.md:11`, 심링크 대상 `SKILL.md:651-655`, 배지 `instructions.py:114` |
| H6 curl `-o` / `startswith(p)` | 맞음. `nas_mcp.py:373`. `ps`→`psql`. 접두 `curl -fsS http://127.0.0.1:`만 맞으면 `-X POST`도 메타문자 필터를 통과한다. 실행은 안 했고 코드만 봤다 |
| H7 워치독 | 맞음. `ctl:449-454` |

---

## Blocker

### 1. [신규] Phase 0-4 deny 목록이 호스트 모듈을 빼먹는다

0-4가 막는 것: `chatbot-ctl.sh`, `tests/`, `SELF-MODIFY.md`, `AGENTS.md`, `EMERGENCY.md`, `host-force.ticket`, 이 설계서, 매니페스트.

`write_file` 허용 루트는 여전히 `services/chatbot` 전체다 (`nas_mcp.py:46`). 목록에 없는 `server.py`, `session.py`, `adapters.py`, `host_config.py`, `instructions.py`, `nas_mcp.py`, `static/`은 Phase 0이 끝나도 MCP로 덮어쓸 수 있다. SELF-MODIFY가 디스크 설계도로 적어 둔 바로 그 파일들이다.

P3는 코어를 항상 Tier 2+로 두고 보호는 코어가 소유한다고 한다. 0-4가 그 목록이 아니면 Phase 0 완료 기준(「write_file이 보호 경로를 거절」)이 빈 통과가 된다.

**수정:** 레지스트리 기본 집합을 「배포 코드 전체 + 가드 + 티켓」으로 둔다. 최소: `*.py` 호스트 모듈, `chatbot-ctl.sh`, `tests/`, `static/`(이 NAS에서 Tier 0로 둘 거면 static만 예외로 명시), `SELF-MODIFY.md`, `AGENTS.md`, `host-force.ticket`. `~/.agents`도 허용 루트라(`nas_mcp.py:42`) 전역 스킬 쓰기를 막지 않으면 P2-1이 깨진다.

---

## Major

### 2. [신규] (a) Claude는 권한 프롬프트 없이 라이브 트리를 쓸 수 있다. H4는 CLI 4종 전부다

`ClaudeAdapter`는 skip-permissions 플래그가 없다. 대신:

- `ALLOWED_TOOLS`에 `mcp__nas__write_file` / `run_command` / `service_ctl`과 네이티브 `Read`, `Glob`, `Grep`, `Bash`, `Write`, `Edit` (`adapters.py:380-431`)
- `--setting-sources project`는 계정 스킬만 막고, cwd(`WORKSPACE`)와 Bash로 `services/chatbot`을 쓰는 경로는 막지 않는다

H4를 claude까지 포함해 다시 적어야 한다. Phase 0이 CLI 네이티브를 못 막는다는 한계 문장은 그대로 맞다.

### 3. [신규] (b) 0-3 「ctl이 0.0.0.0을 export하니 LAN은 유지」는 생산 기동 경로에만 맞다

| 경로 | 바인딩 | 비고 |
|---|---|---|
| `chatbot-ctl.sh` `cmd_start` | `export AGY_CHAT_HOST=0.0.0.0` 후 `python3 $CODE/server.py` (`ctl:336,358`) | 이 NAS의 실제 운영 경로 |
| `python3 server.py` 직접 | `host_config.py:11` 기본값. 지금은 `0.0.0.0`, 0-3 이후엔 `127.0.0.1` | `PROJECT.md:15` 엔트리, `docs/plans/monolith-split.md:11` |
| 테스트 | `127.0.0.1:0` 명시 (`tests/test_identity_wiring.py:83`) | 영향 없음 |
| Hermes lifecycle / systemd user | **chatbot `server.py`를 띄우지 않음** | `hermes-lifecycle.sh:79`의 `server.py --port 9119`는 다른 서비스 |

워치독은 ctl `doctor`만 부르므로, 운영 중 LAN은 ctl만 쓰는 한 유지된다. 기본값을 127.0.0.1로 바꾸면 **PROJECT.md대로 `python3 server.py`를 치는 순간 LAN이 죽는다.** README URL은 `http://diskstation:3011/`이다.

**수정:** 0-3에 「생산 기동은 ctl만. `python3 server.py` 문서 엔트리를 ctl로 바꾸거나, 직접 실행 시 LAN이 닫힌다고 명시」. 기본값 변경과 ctl 강제 export를 **같은 ⚡ 배치**로 넣고, 기본값만 먼저 바꾸지 말 것.

### 4. [신규] (c) 독립 모듈 `evolution`은 가능하나, `host_config`를 import하면 안 된다

`nas_mcp.py`는 별도 프로세스다 (`ctl:348`, `adapters.py:1441-1446`). 코어를 `CODE` 아래 모듈로 두면:

- `python3 $CODE/nas_mcp.py`의 `sys.path[0]`가 `CODE`라 `import evolution` 가능
- `server.py`/`session.py`도 같은 디렉터리라 동일
- IPC 없이 각 프로세스가 같은 파일을 import. 공유 상태는 레지스트리 파일뿐이면 된다
- 순환: `evolution`이 `nas_mcp`/`session`/`server`를 가져오면 안 된다. 레이어가 코어를 호출하는 방향만
- `guard_rlock`은 `session.py` AST에서 `AgySession.lock = RLock`만 본다 (`ctl:232-267`). `session.py`가 evolution을 호출하는 것과 충돌하지 않는다

막히는 지점: `host_config.py:97-98`가 import 시 `SESSIONS`/`WORKSPACE`/`STATIC`을 `mkdir`한다. MCP 프로세스가 evolution → host_config를 가져오면 챗 데이터 디렉터리를 부수적으로 만든다.

**수정:** evolution은 `pathlib` + 인자로 받은 `ROOT`만 쓰고, `host_config`/`session`/`nas_mcp`를 import하지 않는다. 0-0 구현 계획에 이 제약을 한 줄.

### 5. (d) `on_turn_end` 합류점은 있다. 정상 종료만 모인다

CLI는 `_read_stdout` → `_handle_stdout_line` → `adapter.normalize_line` → `_handle_events`. HTTP(omniroute)는 `_run_http_turn` → `stream_turn` → `_handle_events` (`session.py:639-666,718-732`). 다섯 provider의 **정상 result/error**는 여기 한곳이다.

여기 안 오는 종료:

- `interrupt_current_turn` (`1473-1481`)
- `_read_stdout` finally, 자식이 중간에 죽음 (`629-636`)
- `_reap_sessions` (`1960-1968`)

**수정:** `_handle_events`의 result/error 분기를 `_finish_turn()`으로 빼고, interrupt/reap/finally도 그걸 부른다. 그 함수에서 `on_turn_end()`를 호출.

### 6. (e) 코어 단독 동작은 설계하면 가능하다. 지금은 경계가 섞여 있다

지금은 코어 모듈이 없다. 배지는 `instructions.py`, 기억은 `tools/memory.py`(셸 전용), 관찰은 심링크 스킬+agy 훅, 보호는 `nas_mcp.py` 안에 있다.

단독 검사가 성립하려면: `on_turn_end`·예산·락·`is_protected`가 evolution 안에 있고, 스킬 디렉터리 비움·MCP 미기동·워치독 없음에도 **session.py가 evolution을 직접 호출**해야 한다. `observe_add` MCP는 어댑터일 뿐이어야 한다. 그 전제는 맞다.

안 나뉘는 것: 배지는 호스트 주입(`instructions.py`)이라 코어가 아니라 호출자다. `memory.py`는 레이어인데 MCP 도구가 없어 omniroute는 Tier 0 기억 자율에 도달하지 못한다 (`cross-cutting-principles.md` #8, `instruction-architecture.md` §6의 `memory_*`는 미구현).

### 7. (f) `static/`은 문서가 이미 모순을 인정한다. 이 NAS 기본값으로는 코어를 에이전트가 고친다

P3-3: Tier 경계 ≈ 레이어 경계. P1-2: `static/`은 core. §4.1: 이 NAS에서는 Tier 0.

이 NAS에서 자율 UI 패치는 SELF-MODIFY 규칙 2와 맞다. 배포 기본값으로 두면 P1-2가 빈 말이다. 결정 7에서 배포판 Tier 2로 못 박지 않으면 전제 충돌이 남는다.

### 8. (g) `chatbot-host-portability.md`와의 겹침

portability Phase 1은 **완료**로 적혀 있고, 형태는 `nas_mcp/core.py` 패키지가 아니라 `nas_mcp.py` + 선택 `nas_mcp_host.py` (`NAS_MCP_HOST_PLUGIN`). `import nas_mcp_host`는 `_run` 정의 뒤 (`nas_mcp.py:234-245`). 이 부분은 v3 §9의 「대조하지 않았다」를 이번에 채웠다.

충돌·잔여:

- portability는 ALLOW_ROOTS를 DATA/AGENTS/web-chat/TMP로 **축소**했다고 적는다. **현재 코드는 `(SERVICES / "chatbot")`를 다시 넣었다** (`nas_mcp.py:46`). 코드 편집용으로 되돌린 것으로 보이고, H3의 원인이다.
- 두 문서가 둘 다 「Phase 0」을 쓴다. 구현자가 헷갈린다.
- `instruction-architecture.md` §6는 `observe_add`를 「`nas_mcp.py` 코어」에 둔다. v3는 `nas_mcp`를 레이어로 둔다. 구현 때 evolution에 두고 MCP는 얇은 래퍼여야 한다.

---

## 4기준

**(가) 안전성.** Phase 0를 문서대로 해도 H4(CLI 네이티브, 이제 claude 포함)는 남는다. 사후 해시(`doctor` 경고, 자동 repair 없음)는 실수 탐지용으로 타당하다. 집행은 아니다. 0-4를 호스트 모듈까지 넓히지 않으면 MCP 경로의 H3도 안 닫힌다. defibrillate는 MCP curl 접두로 POST가 열려 있어, 0-1에서 ctl 화이트리스트만으로는 부족하고 curl `-X`/`-d`/`-o` 거부가 같이 가야 한다.

**(나) 불변성.** `gate`/`promote`를 ctl에 두면 판정은 같다. Draft 작성은 셸 있는 CLI만. omniroute는 MCP만. 이 Grok 세션: 셸·쓰기 도구 있음, 보호 경로 샌드박스 없음, 포그라운드 셸 ~15초. unittest(수 초)는 되고 G5 스테이징은 백그라운드로 설계해야 한다.

**(다) 현실성.** 3.8.15에서 독립 모듈+유닛 테스트는 된다. Phase 0는 전부 디스크 후 ⚡ 한 번. 위험은 0-3 기본값만 바꾸고 ctl export를 빠뜨리는 것, 0-6 락 버그로 `cmd_start`가 영구 스킵되는 것. 워치독이 1분마다 `doctor`를 부르므로 깨진 ctl은 자동으로 재시도한다. 0-3은 다른 항목과 묶지 말고 나중 ⚡로.

**(라) YAGNI.** 0-0 레지스트리는 필요하다(P3-4, 목록 중복 방지). 일일 승격 상한 없는 것은 맞다. OS 유닛 템플릿·Phase 2 스테이징 자동화·Windows 락은 지금 넣지 말 것. `memory_*` MCP는 Phase 1 전에 #8을 맞추려면 필요하지만, Phase 0 범위는 아니다.

---

## 열린 결정 — 추천만

1. **Phase 0 범위.** 한 번의 ⚡로 **0-0 + 0-1 + 0-2 + 0-4**(deny를 호스트 모듈·`~/.agents`까지 확장한 뒤). 0-5는 같은 배치에 넣어도 호스트를 안 죽인다(스킬·헌장). **0-3과 0-6은 다음 ⚡.** 0-3은 LAN, 0-6은 기동 락이라 실패 면이 다르다.
2. **defibrillate 인증.** LAN 평문에서 Origin·세션은 연극이다. 토큰을 `app.js`에 넣어도 보인다. 추천: **MCP/curl에서 defibrillate를 막고**(0-1+curl 쓰기 거부), UI POST는 Same-Origin 정도로 실수성 curl만 거른다. 배포판 인증은 127.0.0.1 + 앞단 프록시로 미룬다.
3. **Phase 2.** 계획에 **제약 절만 남기고 착수 항목에서는 뺀다.** 현행 `.candidate` + 사람 diff + ⚡로 확정. 스테이징은 ctl `CODE`/`AGY_CHAT_ROOT`, MCP URL env, `kill_orphan_agy` 범위가 선행인데 그건 별 문서다.
4. **해시 사후 탐지.** `doctor`에 **경고만** 넣는다. mismatch로 auto-repair 하지 않는다(미검증 코드를 기동하거나, 고친 가드를 옛 해시로 되돌릴 수 있음).
6. **배포판 자기 수정 기본값.** 인스턴스 층(Tier 0/1)만 기본 허용, core는 owner opt-in. P1-3과 같다.
7. **`static/`.** 배포판은 오버레이 전까지 **Tier 2**. 이 NAS만 SELF-MODIFY 규칙 2대로 Tier 0.
8. **감시자 유닛 템플릿.** 제품에 넣지 않는다. ctl `doctor` 계약만 문서화. 유닛 파일은 OS를 코어 옆에 붙인다.

**확인되지 않은 전제 3개**

- 위협 모델이 에이전트 실수·폭주: **이 인스턴스 Phase 0/1은 그 전제로 진행해도 된다.** 배포 시 LAN 평문·무인증은 문서가 이미 부적절하다고 했고, 그건 0-3 기본 닫힘으로 대응한다. 공격자 모델로 올리면 Phase 0 범위가 인증 계층까지 커진다.
- 인스턴스당 owner 한 명: **진행해도 된다.** `identity.py`의 `user_title`과 맞다.
- 범위는 챗봇 서비스: **진행해도 된다.** Hermes/워치독은 레이어·배선이다.

---

## 문서에 동의하는 부분

구멍 먼저, 게이트는 나중. Phase 2 보류. 홈 전체 worktree 금지. 관찰 SSOT는 workspace. 코어를 독립 모듈로 두는 결정. P2를 코어 루프에만 걸고 스킬·MCP·감시자는 밖으로 둔 것. 일일 승격 상한을 안 둔 것.

---

## 구현 전 문서에 넣을 최소 수정

1. 0-4 deny에 호스트 `*.py`·`~/.agents` 포함 (static은 이 NAS 예외를 명시)
2. H2에서 `restart`는 티켓에 걸린다고 정정. H4에 claude 포함
3. 0-3에 「생산 기동은 ctl만. `python3 server.py`는 LAN이 닫힘」과 PROJECT.md 엔트리 정정
4. 0-0: evolution은 `host_config`/`session`/`nas_mcp`를 import하지 않는다
5. `on_turn_end`는 `_finish_turn()` 한곳 (interrupt/reap 포함)

이 다섯 줄이 들어가면 Phase 0 착수해도 된다.
