# 재귀적 자기 개발·개선 설계서 v2 — Grok 교차 검증

- **대상**: [`recursive-self-evolution.md`](./recursive-self-evolution.md) v2
- **검증자**: Grok (Grok Build TUI, 2026-09-20). Claude Code v1 리뷰를 반영한 v2를, 그 수정 목록 없이 코드로 다시 대조.
- **기준**: `docs/concept.md`, `data/workspace/SELF-MODIFY.md`, `data/workspace/cross-cutting-principles.md` #8 #9
- **결론: 수정 후 진행.** 호스트 단일 `gate`/`promote` + Tier 차등 + 라이브 디스크에 안 쓰는 스테이징은 기조에 맞고 뼈대는 유지해도 된다. §4「에이전트 수정 불가」와 §6 스테이징은 지금 코드 기준으로는 성립하지 않는다. 아래 구멍을 문서에 닫기 전에는 구현에 들어가면 안 된다.
- **이 검증에서 하지 않은 것**: 문서·코드 수정, `chatbot-ctl.sh stop|restart|repair|defibrillate`, `git worktree add`.

`[신규]`는 이 검증에서 코드로 잡은 항목. 앞 리뷰 본문은 보지 않았으므로, v1에 있던 지적과 겹칠 수 있다.

---

## 확인한 것 / 확인하지 않은 것

확인함:

- `chatbot-ctl.sh` 전편 (`guard_rlock`, `probe_message`, `cmd_doctor`/`cmd_repair`/`require_host_force`, usage에 `gate`/`promote` 없음)
- `instructions.py` 번들·`_status_text`·해시 범위
- `session.py` `_send_direct` 주입, `_observe_agent_step`
- `loop_guard.py` + `adapters.py`에서 호출되는 위치
- `nas_mcp.py`/`nas_mcp_host.py` 허용 루트·`write_file`·`run_command`·`service_ctl`
- `server.py` `/api/rules` PUT, `/api/host/defibrillate`
- `workspace_status.py` `_rule_path` (`AGENTS.md`/`PERSONA.md`/`PROJECT.md`/`SELF-MODIFY.md`)
- `tests/` unittest discover, `tests/probes/` 3개
- `data/workspace/tools/memory.py`, `MEMORY.md` 788B, `.bak` 없음
- `data/workspace/.agents/skills/chatbot-self-improve/SKILL.md`
- git 루트 `/volume1/homes/me`, worktree 1개, `.git` 2.8G, git 2.55.0
- Python 3.8.15, node v22.23.2, `Ran 209 tests in 4.332s OK`
- Hermes cron `gateway-watchdog.sh` → `doctor --auto-repair` 1분 주기
- 관찰 로그 workspace vs `~/.agents/skill-observations/`
- `/tmp` tmpfs 3.9G vs `/volume1` 다른 장치

확인하지 않음:

- 각 `tests/probes/` 최근 실측 통과(쿼터·플레이크)
- DSM 작업 스케줄러 DB
- chattr/immutable 지원
- 스테이징 포트 방화벽
- 챗봇이 띄운 grok 자식이 상대경로만 쓰는지(절대경로면 라이브 `services/chatbot`도 씀)

---

## §1.1 표

| 항목 | 문서 | 실제 | 판정 |
|---|---|---|---|
| 관찰 상태 주입 | `instructions.py` `_status_text` | `OBS_DIR = WORKSPACE/"skill-observations"/"observation-log"` (`instructions.py:28-29,107-114`). 열린 건수·마지막 리뷰만 넣는다. 본문은 안 넣는다. | 있음. 「관찰 루프」는 과대 표현 — 배지일 뿐 |
| 장기 기억 | `tools/memory.py` 4KB·flock·원자적 쓰기 | `MAX_BYTES=4096`, `fcntl.flock`, `os.replace` (`memory.py:28,43-47,55-63`). 현재 788B. `MEMORY.md.bak` 없음 | 맞음 |
| `loop_guard` | 세션 단위, 턴 내부만 | 턴마다 `reset()` (`session.py:142,422,1289`). **호출은 `AgyAdapter.normalize_line` 한 곳** (`adapters.py:233`). claude/grok/codex/omniroute는 안 탄다 | 「있음」은 agy에만 맞음 |
| 원자적 파일 쓰기 | `artifact_manager._atomic_write_text` | `tmp.replace(path)` (`artifact_manager.py:30-43`) | 맞음. 파일 단위만 |
| 유닛/스모크 209개·약 4초·네트워크·spawn 없음 | | `python3 -m unittest discover -s tests` → Ran 209 tests in 4.332s OK. `tests/probes/` 3개는 discover 대상 아님 | 개수·시간 맞음. `smoke.py:65-74`는 `ctl guard`를 서브프로세스로 돌림 (네트워크는 아님) |
| `guard_rlock` | 이 불변식 하나 | `chatbot-ctl.sh:232-267`. `AgySession.lock is RLock`만 본다 | 맞음 |
| `probe`/`doctor` | 라이브 메시지 경로 | `probe_message`가 `POST /api/sessions` + `/message` (`ctl:270-316`). `healthz`만 보지 않음 | 맞음 |
| `gate`/`promote`/해시 매니페스트/사이클 예산·락 | 없음 | `ctl` usage에 `gate`/`promote` 없음 (`ctl:524`). `docs/.protected.sha256` 없음 | 맞음 |
| provider 카나리 | `tests/probes/`에 3개 | `account_probe.py`, `agy_first_turn.py`, `discovery_canary.py` | 맞음 |

---

## Blocker

### 1. [신규] §4 보호 경로는 지금 에이전트가 직접 쓸 수 있다. 게이트 시점 해시는 이걸 막지 못한다

문서 §4는 보호 경로를 「에이전트 수정 불가」로 두고, 검증은 `docs/.protected.sha256`를 `gate`가 대조한다고 한다. 쓰기를 막는 장치가 코드에 없다.

- `nas_mcp.py` `ALLOW_ROOTS`에 `(SERVICES / "chatbot").resolve()`와 `DATA/workspace`가 들어 있다 (`nas_mcp.py:40-47`). `write_file`은 이 루트 아래면 그대로 쓴다 (`351-367`).
- 따라서 `chatbot-ctl.sh`, `tests/`, `SELF-MODIFY.md`, `AGENTS.md`, 이 설계서, 제안된 `docs/.protected.sha256` 모두 MCP로 덮어쓸 수 있다. `secrets.env`만 파일명 정규식에 걸려 거부되고 (`57-58`, 실측 `secrets.env DENY`), `host-force.ticket`은 **허용**된다.
- CLI 프로바이더는 MCP보다 넓다. agy `--dangerously-skip-permissions` (`adapters.py:192-193`), grok `--always-approve --trust` (`971-972`), codex `--dangerously-bypass-approvals-and-sandbox`. 네이티브 파일 도구로 라이브 트리를 직접 고친다.
- `_is_under`는 `Path.resolve()`라 심링크를 따라간다 (`95-97`). 허용 루트 **밖**으로 나가는 심링크 쓰기는 거절되지만, 허용 루트 **안**의 보호 파일을 직접 쓰는 경로는 그대로다.

`gate`는 스테이징 트리를 검사할 뿐이다. 에이전트가 라이브 `services/chatbot/`에 쓰면 게이트를 우회한다. `/api/rules`만 선결로 적은 것(`§4.1`)은 구멍의 일부다.

**수정:** 보호 경로 쓰기를 호스트가 거절해야 한다.

1. `nas_mcp.write_file`에 보호 경로 deny 리스트 (ctl의 `guard`/`gate`/`promote`/`repair`, `tests/`, `SELF-MODIFY.md`, `AGENTS.md` 자기수정·사전승인, `EMERGENCY.md`, 이 설계서, 매니페스트).
2. `/api/rules` PUT에서 `AGENTS.md`·`SELF-MODIFY.md` 읽기 전용 (문서에 이미 있음 — 유지).
3. CLI가 라이브 보호 파일을 고쳐도 `promote`만 라이브에 반영. 전제: 에이전트 cwd/ADD_DIRS를 스테이징으로 고정하고, 라이브 `services/chatbot`는 MCP·스킬 스크립트에서 빼기.
4. 매니페스트는 에이전트 쓰기 루트 **밖**이거나, 사람만 갱신하는 불변 파일. `docs/.protected.sha256`를 chatbot 트리에 두면 MCP로 해시까지 맞출 수 있다.
5. `gate`는 매니페스트 없거나 불일치면 실패 폐쇄.

해시만 추가하고 쓰기 경로를 안 막으면 §4는 문서상의 금지다.

### 2. [신규] `nas_mcp run_command`로 `chatbot-ctl.sh repair`가 열린다. repair는 티켓을 스스로 발급한다

`CMD_PREFIXES`에 `chatbot-ctl.sh`와 `/volume1/homes/me/services/chatbot-ctl.sh`가 있다 (`nas_mcp.py:80-82`). `run_command`는 그 접두면 `bash -lc`로 실행한다 (`369-382`). `repair`는 `;|&`$()`가 없어서 필터를 통과한다.

`ctl`의 `repair|defibrillate|...` 분기는 `CHATBOT_FORCE_HOST=1`을 스스로 export하고 (`519-521`), `cmd_repair`는 `issue_host_ticket`을 직접 한다 (`390-392`). SELF-MODIFY 규칙 1(대화 루프에서 repair 금지)은 **문구**이고, MCP는 강제하지 않는다.

같은 계열:

- `service_ctl(chatbot, start)`는 티켓 없이 `cmd_start` (`nas_mcp.py:292-303`, `ctl:334-361`). 호스트가 내려가 있으면 라이브 디스크 코드로 기동한다.
- 인증 없는 `POST /api/host/defibrillate` (`server.py:561-569`)가 같은 repair를 예약한다. concept.md대로 LAN 평문이라 로컬 curl이면 충분하다. MCP `curl -fsS` 접두는 GET이라 이 경로는 MCP만으로는 안 되지만, 셸 있는 프로바이더는 POST 가능하다.

**수정:** `run_command`에서 `chatbot-ctl.sh`는 `status|doctor|probe|guard|gate`만 허용. `repair|stop|restart|defibrillate`는 거절. `service_ctl`의 chatbot `start/stop/restart`도 거절(status만). `promote`만 repair를 부르게. `/api/host/defibrillate`는 사람 UI 전용으로 남기되, 에이전트 도구 목록·curl 허용 접두에서 빼기.

### 3. [신규] 스테이징 설계가 이 NAS의 git·파일시스템·워치독과 충돌한다

문서 §6.1은 `git worktree add` 또는 스크래치 복사. 실측:

- git 루트는 `/volume1/homes/me`. worktree는 한 개(메인).
- `.git`만 2.8G. 홈 전체 체크아웃 worktree는 그 이상이다.
- `/tmp`는 tmpfs 3.9G. 홈 worktree를 `/tmp`에 둘 수 없다.
- `/tmp`와 `/volume1`은 다른 장치라, `/tmp` 스냅샷을 라이브로 `replace()`하면 원자성이 깨진다.
- `git worktree add`는 pathspec이 아니라 커밋 전체 체크아웃이다. 공유 더티 트리에서 브랜치 체크아웃 금지는 맞지만, 그 대안으로 홈 worktree를 쓰는 것은 비현실적이다.

문서 §6.2는 라이브 미반영으로 `doctor --auto-repair`의 시간창을 없앤다고 한다. 그 크론은 실제로 있다(아래 §9.3). promote가 라이브를 멈춘 1분 안에 워치독이 `cmd_start`를 치면, 반만 스왑된 트리가 기동된다 (`ctl:449-454` — chat down이면 `--auto-repair`가 아니어도 start).

G5 스테이징도 포트만 바꿔서는 안 된다. `AGY_CHAT_DATA` 기본값이 `ROOT/data` (`host_config.py:23`)이고 MCP는 3012 고정 (`nas_mcp.py:25-26`). 데이터 디렉터리를 안 나누면 스테이징 프로브가 라이브 `sessions/`·`live_pids.json`·`doctor-probe.stamp`를 건드린다. 스테이징 `nas_mcp`가 라이브 MCP를 그대로 쓰면 `write_file`은 계속 라이브 `services/chatbot`에 쓴다.

**수정:** 문서에 구현 제약을 못 박기.

- 격리 = `/volume1` 위의 `services/chatbot` 복사본(또는 그 prefix의 sparse worktree). 홈 전체 worktree 금지. `/tmp` 금지.
- 스테이징은 `AGY_CHAT_ROOT` + **별도** `AGY_CHAT_DATA` + **별도** `AGY_CHAT_PORT`/`NAS_MCP_PORT` + 별도 pid/로그. 라이브 MCP를 공유하지 않기.
- `promote`와 `doctor`가 같은 flock을 잡기. 워치독은 그 락이 있으면 start/repair를 하지 않기.
- last-good 스냅샷도 `/volume1`에 두기.

---

## Major

### 4. [신규] `loop_guard`를 진화 루프 브레이크로 보면 안 된다

§1.1과 §3.2는 `loop_guard`를 「턴 내부 반복 차단」으로 정확히 한정한다. 그래도 「세션 단위 도구 호출 반복 차단 | 있음」은 과장이다.

- `_observe_agent_step`는 agy 스트림에만 연결됨 (`adapters.py:233`).
- OmniRoute는 `MAX_TOOL_HOPS = 10` (`adapters.py:1704,1817`)뿐이고, 같은 `write_file`을 10번 반복하는 것은 막지 않는다.
- 가드가 잡아도 프로세스 중단이지 티켓 `wontfix`가 아니다. 다음 턴에 같은 Draft를 다시 시작할 수 있다.

§3 종료 조건(시도 3회, 연속 실패 2회, 작성자 락)은 티켓 상태 머신으로만 강제해야 한다. `loop_guard`에 의존한다는 인상을 표에서 지우기.

### 5. [신규] 이미 있는 스킬이 §3.1 트리거를 무시하게 되어 있다

계획은 실장님 발화 또는 승인된 관찰 티켓만 Draft를 시작한다고 한다. 실제 주입·온디맨드 문서는 다르다.

- `chatbot-self-improve`: 「Prefer fixing this project yourself」 (`data/workspace/.agents/skills/chatbot-self-improve/SKILL.md:11`).
- `task-observer`: 작은 가산 변경은 리뷰를 기다리지 말라고 한다 (전역 스킬 `Acting on Observations`).
- `AGENTS.md` 사전 승인은 「계획을 세우자」류와 대량 작업만 기다린다. 진화 티켓이 아니다.
- `_status_text`는 매 세션에 「열린 관찰 N건」을 넣는다 (`instructions.py:114`). 계획은 작업 지시가 아니라고 하지만, 자기개선 스킬과 겹치면 착수 힌트가 된다.

**수정:** 구현 1호에 `chatbot-self-improve`와 workspace `task-observer`를 §3.1에 맞게 고치고, 헌장에 「관찰 배지는 지시가 아니다」를 한 줄. 스킬을 안 고치면 게이트를 만들어도 에이전트는 라이브 패치로 간다.

### 6. 동작 불변성 — `gate`/`promote`를 ctl에 두는 방향은 맞다. 깨지는 지점은 「누가 Draft를 쓰느냐」

원칙 #8/#9대로 호스트가 돌리면 판정 규칙 자체는 프로바이더와 무관하다. 작성 경로가 다르다.

| 프로바이더 | Draft를 worktree에 쓸 수 있나 | 비고 |
|---|---|---|
| agy/claude/codex/grok | 예, 네이티브 파일+셸 | 라이브 트리도 쓸 수 있음 (Blocker 1) |
| omniroute | 셸 없음. `nas_mcp`만 | `MAX_TOOL_HOPS=10`, 턴 180s (`adapters.py:1709-1718`). `git worktree`/`gate` 호출 불가. MCP `write_file`이 라이브를 가리키면 스테이징 자체가 성립하지 않음 |

문서 「작성자는 셸 가능한 provider, 또는 사람이 `gate`만 호출」은 omniroute에 맞다. 빠진 문장: omniroute는 Draft 작성자가 될 수 없고, 그 세션에서 나온 MCP 쓰기는 라이브 보호 경로에 적용되면 안 된다.

이 Grok 환경에서 깨지는 지점 (이 세션에서 실측):

- 셸 있음. Python 3.8.15, git 2.55.0, node v22.23.2.
- 쓰기 도구가 열려 있고, 보호 경로를 막을 샌드박스는 보이지 않았다. `/usr/syno/etc`, `~/.hermes/cron/jobs.json`까지 읽혔다.
- 포그라운드 셸은 약 15초 후 백그라운드로 넘어간다. `gate`의 unittest(4초)는 되지만, G5 스테이징 기동+probe는 백그라운드 태스크로 설계해야 한다.
- 챗봇이 띄운 grok도 `--always-approve --trust`라 권한 프롬프트가 없다 (`adapters.py:967-973`). TUI와 챗봇 grok 모두 「게이트 밖에서 라이브 파일을 고칠 수 있는 작성자」다.

### 7. YAGNI / 누락

과한 것:

- 24시간 Tier 1+ 승격 5건 / Tier 2 초안 2건 — 티켓당 3회와 작성자 락이면 초기 런어웨이는 막힌다. 일일 상한은 관측 후에.
- provider 카나리를 선택으로 둔 것은 맞다. 필수에 넣지 말 것.

유지할 것:

- Tier 0–3. SELF-MODIFY의 정적 UI / 호스트 모듈 / 권한·포트와 같다.
- 해시 매니페스트. 단, 테스트 **개수·skip**만 보면 본문을 `assert True`로 비울 수 있다. `tests/` 내용 해시가 §4에 이미 있으므로, G0는 카운트가 아니라 그 해시를 쓰면 된다.
- 작성자 락. `standby_pool.py`와 멀티 세션이 있다.

빠진 엣지:

- promote 다중 파일 스왑 도중 크래시 → 혼합 트리. 디렉터리 통째 rename 또는 스테이징 디렉터리 포인터 스왑을 명시.
- 같은 파일을 다른 에이전트가 더티 상태로 들고 있는 경우. pathspec 커밋은 커밋만 보호하고, 워킹 트리 덮어쓰기는 다른 에이전트 편집을 지운다. promote 전 `git diff -- path`로 라이브 더티면 중단.
- G5 `probe_message`는 실제 `gemini-3.8-flash-low` 턴을 만든다 (`ctl:285-287`). 쿼터·플레이크. 스테이징 전용 더미 어댑터 또는 고정 예약 모델이 필요하다.
- 테스트 7개가 `@unittest.skipUnless(shutil.which("node"))`. node가 사라지면 skip이 늘고 G0가 실패한다(의도가 맞으면 문서에 「node는 게이트 의존성」).

---

## Minor

- §7 L3 라인 수: `session.py` 1996줄, `adapters.py` 1930줄. 문서와 맞다. 자동 트리거를 안 두는 판단에 동의.
- `workspace_status.py:143`의 `last_review = "never"`는 파일을 안 읽는다. 주입 경로(`instructions.py`)는 읽는다 (`2026-09-16`). 상태 탭과 번들이 어긋남. 이 계획의 범위는 아님.
- `cmd_start`가 라이브에서 `guard_rlock`만 보고 기동한다. 해시 게이트와 별 라인. promote가 아닌 워치독 start는 G0를 안 탄다 → Blocker 3의 락과 함께 고쳐야 함.

---

## §9 코드로 답한 것

### 3번 — `doctor --auto-repair` 크론 여부

**걸려 있다.**

- `~/.hermes/scripts/gateway-watchdog.sh:167-171`이 `chatbot-ctl.sh doctor --auto-repair`를 호출한다.
- Hermes cron 잡 `1fc4635b35a4` 「System Monitor」가 그 스크립트를 **1분마다** 돌린다 (`~/.hermes/cron/jobs.json` `schedule.minutes: 1`, `enabled: true`, 검증 당시 `repeat.completed: 30845`).
- 사용자 crontab은 비어 있다. 이 경로가 실체다.
- 로그: `doctor auto-repair triggered by probe fail`가 2026-09-16에 2회. 그 이후는 probe throttle(`PROBE_EVERY_SEC=3600`) 때문에 시간당 probe + 1분마다 health/start.

§6.2 시간창 논거는 더 강해진다. 라이브 디스크에 미검증 코드가 있으면, 호스트가 내려간 뒤 최대 약 1분 안에 워치독이 그걸 기동한다. `cmd_doctor`는 `--auto-repair`가 아니어도 chat down이면 `cmd_start`한다 (`ctl:449-454`).

### 7번 — 관찰 저장 위치 SSOT

**챗봇 제품 SSOT는 `data/workspace/skill-observations/`이다. 전역 `~/.agents/skill-observations/`는 다른 저장소다.**

| | workspace | 전역 `~/.agents` |
|---|---|---|
| 호스트가 읽음 | 예. `instructions.py:28-29`, `workspace_status.py:131` | 아니오 |
| 포맷 | per-file `observation-log/*.md` (활성 파일 + archive) | 레거시 단일 `log.md` (검증 당시 1857줄) |
| last-review | `2026-09-16` | `never` |
| 스킬 사본 | `data/workspace/.agents/skills/task-observer/` | `~/.agents/skills/task-observer/` |

전역 로그는 챗봇 번들에 안 들어간다. 합치지 말고, 냥피디 자기개선은 workspace만 쓰기. 전역 task-observer가 `[ABSOLUTE PATH]`를 안 고정하면 세션마다 갈라진다.

---

## 문서에 동의하는 부분

- concept.md의 자체 개발·자기 진화 축에 맞고, 「이미 있는 관찰→수정→기록 위에 등급·예산·게이트만 얹는다」는 범위가 맞다.
- 게이트를 에이전트 밖 호스트 진입점으로 둔 것, L3 강등, 메모리 자동 증류 보류, `session_weights.py`를 판단 가중치로 오해하지 않은 것.
- 브랜치 체크아웃 금지, pathspec 커밋, 「디스크 설계도 → 스테이징」을 Tier 3 승인으로 열어 둔 것.
- G3를 이 트리에서 재현 가능함 (209 / 4.332s). G1의 3.8.15 `py_compile`도 이 호스트와 일치한다.

---

## 구현 전 문서에 넣을 최소 수정

1. 보호 경로 쓰기 거절 목록 (MCP + rules API + 스테이징 cwd)
2. ctl `repair`를 에이전트 `run_command`에서 제거
3. chatbot-scoped 복사본 + 별도 DATA/포트 + doctor/promote flock
4. `chatbot-self-improve`/task-observer를 §3.1에 맞게 고친다는 선행 작업

이 네 줄이 들어가면 착수해도 된다.
