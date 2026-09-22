# 재귀적 자기 개발·개선 설계서

- **문서 상태**: 계획 v3. 열린 결정 1~10 확정 (실장님, 2026-09-20). **구현 착수는 별도 지시 대기** — 이 문서는 범위와 순서를 확정한 것이지 착수 지시가 아니다.
- **작성일**: 2026-09-20
- **상위 기조**: `docs/concept.md` (자체 개발·자기 진화 축)
- **절대 경계**: `data/workspace/SELF-MODIFY.md` (실행 중인 자기 머리를 연 채로 수술 금지)
- **근거 리뷰**: v1 → Claude Code 리뷰 → v2 → Grok 재검증 ([`recursive-self-evolution-review-grok-v2.md`](./recursive-self-evolution-review-grok-v2.md)) + Claude Code 3차 독립 검증. 세 리뷰는 v2의 안전장치가 현재 코드에서 집행되지 않는다는 점에서 일치했다. Grok v3 검증 ([`recursive-self-evolution-review-grok-v3.md`](./recursive-self-evolution-review-grok-v3.md), 결론: 수정 후 착수, 재설계 아님). 이 문서는 v3 리뷰의 수정 5건과 열린 결정 추천을 반영했다.
- **Grok v3 검증**: [`recursive-self-evolution-review-grok-v3.md`](./recursive-self-evolution-review-grok-v3.md) (2026-09-20, 결론: 수정 후 착수).

---

## 전제

**P1. 범용 애플리케이션이다 (실장님 확정, 2026-09-20).** 이 앱은 지금 이 NAS와 실장님 한 명에 바인딩돼 있지만 불변이 아니다. 여러 OS에 독립 애플리케이션으로 배포되고 다른 사용자에게 배포될 수 있다. **개인화보다 범용화에 가치를 두고, 당장 하지 않더라도 언제든 범용화할 수 있는 구조로 시작한다.** (기존 계획: [`chatbot-host-portability.md`](./chatbot-host-portability.md), `identity.py`의 이름 비하드코딩 원칙, `cross-cutting-principles.md` #2)

이 전제에서 이 문서가 따르는 설계 규칙:

1. **NAS 결합은 이름을 붙여 격리한다.** Hermes 크론 워치독, `/volume1`, `~/.hermes`, sibling 서비스, "실장님" 호칭은 이 인스턴스의 배선이지 제품의 규칙이 아니다. 문서의 "실장님"은 **운영자(owner) 역할의 이 인스턴스 호칭**이며, 주입되는 규칙 문구는 역할어를 쓴다 (`user_title`은 `identity.py`가 공급).
2. **배포 단위를 나눈다.** *core*(배포되는 코드: `server.py` 등 호스트 모듈, `static/`, `chatbot-ctl.sh`)와 *인스턴스 층*(`data/workspace/`의 규칙·페르소나·스킬·기억, 플러그인). **자기 진화의 기본 출력은 인스턴스 층이다.** core 수정은 업스트림 업데이트와 충돌하고, 남의 기기에서 에이전트가 배포된 코드를 패치하는 것은 위험 등급이 다르다.
3. **안전의 기본값은 배포 관점에서 정한다.** 이 NAS에서 열어 두는 것은 opt-in으로 열고, 기본은 닫는다 (§3 0-3의 바인딩, §5 Phase 2의 기본 꺼짐).
4. **새 로직은 OS 종속 셸에 늘리지 않는다.** `chatbot-ctl.sh`는 bash이고 `ps -eo`·`setsid`·`flock`에 기대며 macOS에는 `flock`이 없다. 락·게이트·보호 경로 검사 같은 새 로직은 Python 모듈로 두고 ctl은 얇게 호출만 한다. `memory.py`의 `fcntl`도 POSIX 전용이라, 락은 한 함수 뒤로 숨겨 나중에 플랫폼별로 교체할 수 있게 한다 (지금 Windows를 구현하지는 않는다).
5. **경로·이름·명령을 코드에 박지 않는다.** 보호 경로 목록, 게이트 명령, 허용 명령 접두는 `ROOT`/`WORKSPACE` 상대 경로의 데이터로 둔다. 이 NAS 전용 항목은 `nas_mcp_host.py` 플러그인 쪽에 둔다.
6. **범용화는 지금 구현이 아니라 구조의 조건이다.** 다른 OS 지원이나 멀티유저 기능을 이번 범위에 넣지 않는다. 다만 위 규칙을 어기는 결정은 하지 않는다.

**P2. 재귀적 자기 개발·개선 시스템(코어 동작)은 외부 레퍼런스를 직접 참조하지 않고 우리 것으로 만든다. 최종 산출물에는 그 흔적이 없다 (실장님 확정, 2026-09-20).** 이 전제는 **이 코어 동작에 한정**된다. 스킬, MCP, 감시자 같은 그 밖의 것은 외부의 것을 그대로 써도 된다. Hermes, task-observer는 대표적인 자가 진화형 메타 스킬·에이전트 구현이므로 **설계를 배우는 대상으로는 적극 활용**한다. 하지만 런타임 의존도, 출처 표기도 남기지 않는다. 배운 것 중 필요한 것만 추려 **우리 스키마·경로·용어로 다시 써서 우리 시스템의 일부로 만든다.** 규칙:

1. **직접 참조 금지**: 외부 저장소·전역 경로로의 심링크, 절대경로 참조, 공유 파일 실시간 의존을 두지 않는다. 다른 에이전트가 고친 파일이 이 챗봇의 동작을 바꾸면 안 된다.
2. **흔적 없음**: 코어 자기 개선 시스템의 최종 산출물(그 코드, 주입되는 규칙, 상태 API, 사용자 대면 문서)에 외부 이름·경로·심링크·출처 주석·"~에서 가져옴" 표기를 두지 않는다. 그래서 출처·정제 이력을 남기는 별도 기록 파일도 만들지 않는다. 학습 메모가 필요하면 배포 대상 밖의 개인 작업 노트에 둔다. 완료 여부는 §4.6의 **무흔적 검사**로 확인한다.
3. **provider 종속 메커니즘 금지**: 특정 CLI의 훅·플러그인 형식(예: agy `PreInvocation`)에 기대지 않고 호스트 메커니즘으로 만든다 (`cross-cutting-principles.md` #8·#9).
4. **우리 용어**: 코어 시스템 안에서는 외부 명칭을 제품 용어로 끌어오지 않는다. 우리 용어는 `observation` 같은 역할 이름.

**적용 범위**
- **대상 (P2 적용)**: 관찰→진화 루프(O-D-E-V), 게이트·승격, 그 상태 API, 그것을 구동하는 규칙과 훅. 즉 이 문서가 설계하는 것.
- **대상 밖 (외부 것 사용 가능)**: 일반 스킬, MCP 도구, 감시자(재기동 감시), `nas_mcp_host.py`의 형제 서비스 연동 등. 이들은 P1(범용화)의 규칙만 따른다.
- **로그와 계획 문서는 에이전트만 보고 관리한다** (실장님 확정, 2026-09-20). 이 계획서, 리뷰 문서, `docs/plans/`, `DEVLOG.md`, 관찰 로그는 배포·사용자 대면 대상이 아니므로 P2의 무흔적 검사에서 제외하고, 현재 상태를 설명하려고 외부 이름을 쓴다(이 문서가 그렇다).

이 전제는 §1 표, §3 0-5, §4.6에 반영돼 있다.

**P3. 재귀적 자기 개발·개선 코어는 단단한 기반이고, 다른 것은 그 위에 얹는 레이어다 (실장님 확정, 2026-09-20).**

```
  레이어 (외부 것 사용 가능)   스킬 · MCP 도구 · 페르소나 · 기억 내용 · 외부 서비스 연동 · 감시자
        ▲  레이어는 코어 API를 호출한다
  코어 (우리 것, 무흔적, P2)    관찰 수집 · 진화 트리거·예산·락 · 보호 경로 · 게이트 · 승격
```

1. **의존은 한 방향**: 레이어 → 코어. 코어는 레이어(스킬, MCP, 외부 서비스)에 의존하지 않는다.
2. **코어 단독 동작**: 레이어를 전부 꺼도(스킬 없음, MCP 다운, 외부 감시자 없음) 코어는 관찰 기록, 예산, 락, 보호 검사, 게이트를 수행한다. 이것을 검사 항목으로 둔다 (§4.6).
3. **코어는 레이어를 진화시키고, 레이어는 코어를 고치지 못한다.** 자율 진화(Tier 0/1)의 대상은 레이어, 코어는 항상 Tier 2 이상이다. Tier 경계와 레이어 경계는 대체로 같은 선이다.
4. **보호는 코어가 소유한다.** 보호 경로 목록과 검사 로직은 코어에 있고, MCP 같은 레이어는 그것을 **호출해서 따를 뿐** 자기 목록을 따로 갖지 않는다 (§3 0-0). 외부 레이어는 신뢰할 수 없으므로 코어 보호가 레이어의 협조에 의존하면 안 된다.
5. **레이어 인터페이스는 코어 함수의 얇은 어댑터**: 예를 들어 MCP `observe_add`는 코어의 기록 함수를 부르는 껍데기다 (§4.6).

**현재 이 원칙에서 어긋난 곳**: 코어의 관찰 수집이 외부 스킬 심링크와 agy 훅(레이어)에 얹혀 있어 **의존이 거꾸로**다 (§1). 보호 규칙(`write_file` 허용 루트, `run_command` 접두)도 코어가 아니라 MCP 서버(레이어) 안에 흩어져 있다 (§2 H1~H3, H6).

**세 가지 가정 (Grok v3 검증에서 "이 전제로 진행 가능" 판정, 실장님 명시 확인은 아직 없음)**: ①위협 모델은 "악의적 공격자"가 아니라 "에이전트의 실수·폭주" (배포 시 LAN 평문·무인증은 기본값으로 부적절하므로 0-3 기본 닫힘으로 대응. 공격자 모델로 올리면 Phase 0 범위가 인증 계층까지 커진다), ②승인 주체는 인스턴스당 owner 한 명 (`identity.py`의 `user_title`과 맞음), ③범위는 챗봇 서비스로 한정. 이 가정이 바뀌면 §3·§8을 다시 본다.

---

## 0. 한눈에

- **목표**: 냥피디가 운영 경험으로 스스로 기능(스킬·도구)과 판단(기억·규칙)을 늘린다. 5개 provider(agy, claude, codex, grok, omniroute)에서 같은 규칙으로.
- **v2의 문제**: "보호 경로는 에이전트가 못 고친다", "재기동은 사람만 한다"를 전제로 게이트·승격을 설계했는데, **지금 코드에서는 둘 다 열려 있다** (§2).
- **그래서 순서를 바꾼다.**

| Phase | 내용 | 착수 조건 |
|---|---|---|
| **0. 기존 구멍 막기** | 도구·API 권한 축소, 스킬·헌장 정합 | 지금. 자기 진화를 안 해도 필요한 하드닝 |
| **1. 최소 루프 (Tier 0/1)** | 기억·스킬 텍스트·정적 UI·스킬 스크립트만 자율. 트리거·예산·작성자 락 | Phase 0 완료 |
| **2. 호스트 코어 자기 수정** | `gate`/`promote`/스테이징 | **착수 항목에서 제외 (결정 3).** §5는 제약 기록으로만 유지. 현행 `.candidate` + 사람 diff 확인 + ⚡ 관행이 기본 |

- Phase 0의 대상 파일(`nas_mcp.py`, `server.py`, `chatbot-ctl.sh`)은 전부 호스트 모듈이라 **Tier 2: 디스크 수정 후 실장님 ⚡소생.**

---

## 1. 이미 있는 것 / 없는 것 (코드로 확인한 표)

| 항목 | 상태 | 근거·주의 |
|---|---|---|
| 관찰 배지(열린 관찰 건수·마지막 리뷰) | 있음 | `instructions.py:28-29,107-114`. 본문은 주입하지 않음. "관찰 루프"는 과장 — 배지일 뿐 |
| **관찰 수집·리뷰 (task-observer)** | **외부 자산에 의존 중 (P2 위반)** | `data/workspace/.agents/skills/task-observer`는 **전역 `~/.agents/skills/task-observer`(697줄)로의 심링크**. 다른 에이전트와 공유하는 파일이고, 실행은 agy 전용 `PreInvocation` 훅(`.agents/hooks.json`, `scripts/task-observer-pre.sh`가 `/volume1/homes/me/...` 절대경로 하드코딩)에 의존. 우리 것으로의 대체 설계(`observe_add`, `on_turn_end`, `candidates.jsonl`)는 `instruction-architecture.md` §6-7에 있으나 **P4 미착수, 코드에 없음** (grep 0건) |
| 장기 기억 `tools/memory.py` | 있음 | 4KB 상한, flock, 원자적 쓰기. 백업 없음. **셸 있는 provider만 도달** (`nas_mcp`에 memory 도구 없음) |
| `loop_guard.py` 턴 내 반복 차단 | **agy 전용** | 호출처 `adapters.py:233` 한 곳. omniroute는 `MAX_TOOL_HOPS=10`(`adapters.py:1704`)뿐, claude·codex·grok는 없음 |
| 원자적 쓰기 | 있음 (파일 단위) | `artifact_manager._atomic_write_text` |
| 유닛 209개, 약 4.3초 | 있음 | `python3 -m unittest discover -s tests` 실측. 7개는 node 없으면 skip |
| `guard_rlock` | 있음 (RLock 하나뿐) | `chatbot-ctl.sh:232-267` |
| `probe` | **agy 모델 하드코딩** | `gemini-3.8-flash-low` 세션 생성, 쿼터 소모. `/message`는 큐 적재 시점에 반환 |
| 자동 재기동 (감시자) | **있음 (1분 주기, 이 NAS의 배선. 외부 것이며 P2 범위 밖 — P1-1만 적용)** | Hermes cron `1fc4635b35a4` → `gateway-watchdog.sh:167-171` → `doctor --auto-repair`. chat이 내려가 있으면 매분 `cmd_start` (`--auto-repair` 여부 무관) |
| `.candidate` 후보 파일 관례 | 있음 | `.gitignore`의 `*.candidate`, `docs/DEVLOG.md:1278` |
| `gate`, `promote`, 해시 매니페스트, 사이클 예산·락 | **없음** | 전부 제안 |
| provider별 카나리 스위트 | **없음** | `tests/probes/`에 개별 프로브 3개 |

---

## 2. 리뷰가 확인한 구멍 (Phase 0의 근거)

| # | 구멍 | 근거 |
|---|---|---|
| H1 | **`run_command`로 `chatbot-ctl.sh repair`가 열려 있다.** repair가 티켓을 스스로 발급하므로 "티켓은 신뢰된 경로만 발급"이 집행되지 않는다. SELF-MODIFY 규칙 1은 문구일 뿐 | `nas_mcp.py:63-82`(접두 허용), `:369-385`, `chatbot-ctl.sh:390-392,519-521` |
| H2 | `service_ctl(chatbot, start)`가 티켓 없이 `cmd_start` 실행. **`stop`·`restart`는 `chatbot-ctl.sh`의 `require_host_force`에 걸려 거절된다** (v3 초안의 "restart도 동작"은 오류였고 Grok 재검증으로 정정). `POST /api/host/defibrillate`는 인증 없음, CORS `*`, 기본 바인딩 `0.0.0.0` | `nas_mcp.py:292-303`, `chatbot-ctl.sh:501-511`, `server.py:200,561-569` |
| H3 | **보호 대상 파일을 provider가 직접 쓸 수 있다.** `write_file` 허용 루트에 `services/chatbot` 전체와 `DATA`가 있고, `host-force.ticket`도 허용. `PUT /api/rules/{AGENTS,PERSONA,PROJECT,SELF-MODIFY}.md`도 인증 없음 | `nas_mcp.py:40-47,351-367`, `server.py:694-712`, `workspace_status.py:17,47-50` |
| H4 | **CLI provider 4종 모두** 권한 프롬프트 없이 라이브 트리를 네이티브로 수정할 수 있다. agy `--dangerously-skip-permissions`, grok `--always-approve --trust`, codex `--dangerously-bypass-approvals-and-sandbox`. **claude는 skip 플래그 대신 `ALLOWED_TOOLS`에 네이티브 `Bash`·`Write`·`Edit`와 `mcp__nas__write_file`·`run_command`·`service_ctl`을 넣어** 같은 결과 (`DISALLOWED_TOOLS`는 slack·notion·m365 외부 서비스뿐) | `adapters.py:192,971-972,1239`, claude `:380-395` |
| H5 | **기존 스킬이 §4.2 트리거를 무시하게 되어 있다.** `chatbot-self-improve`는 "Prefer fixing this project yourself", task-observer는 작은 가산 변경을 리뷰 대기 없이 적용하라고 함. 배지가 매 세션 주입돼 착수 힌트가 됨 | `SKILL.md:11`, task-observer `SKILL.md:652`, `instructions.py:114` |
| H6 | `run_command`의 `curl … -o <경로>`는 쓰기 허용 루트 검사를 우회. 접두 검사가 `startswith(p)`라 느슨(`ps`→`psql`) | `nas_mcp.py:373` |
| H7 | 자동 재기동이 언제든 디스크의 코드를 기동한다. `doctor`·`repair`·`start`에 상호 배제 락이 없다 | `chatbot-ctl.sh:449-454`, 워치독 1분 주기 |

**Provider별 영향**: H1~H3는 MCP를 쓰는 **모든 provider**(omniroute 포함)에 해당한다. H4는 CLI provider만. omniroute는 셸이 없고 `nas_mcp`만 쓰므로 Draft 작성자가 될 수 없고, 그 세션의 MCP 쓰기가 라이브 보호 경로에 적용되어선 안 된다.

---

## 3. Phase 0 — 기존 구멍 막기 (선행)

모두 Tier 2. 디스크 수정 후 ⚡. 각 항목은 **호출 목록 단위의 유닛 테스트로 검증**하고, 실제 `repair`를 실행해 확인하지 않는다 (라이브 호스트를 건드림).

| 항목 | 내용 | 막는 구멍 |
|---|---|---|
| 0-0 | **코어 소유 보호 경로 레지스트리** (P3-4): 보호 경로 목록과 `is_protected(path)` 검사를 코어 모듈(`evolution`)에 두고 (`ROOT` 상대 경로의 설정 데이터, P1-5), 0-1~0-4의 MCP·API 쪽 검사는 이 레지스트리를 호출한다. 목록을 MCP 서버 안에 따로 두지 않는다. **기본 집합은 "배포 코드 전체 + 가드 + 티켓"** (0-4). **제약: `evolution`은 `pathlib`과 인자로 받은 `ROOT`만 쓰고 `host_config`·`session`·`nas_mcp`·`server`를 import하지 않는다.** `nas_mcp.py`는 별도 프로세스이고 `host_config.py:97-98`이 import 시 `SESSIONS`·`WORKSPACE`·`STATIC`을 `mkdir`하므로, MCP 프로세스가 코어를 통해 이를 끌어오면 챗 데이터 디렉터리를 부수적으로 만든다. `import evolution`은 `nas_mcp.py`·`server.py`·`session.py` 모두 `sys.path[0]=CODE`라 가능하다 (순환 금지: 레이어→코어 방향만). 모듈 이름과 범위는 구현 계획에서 확정 | H1~H3 (근본) |
| 0-1 | `run_command`에서 `chatbot-ctl.sh`는 `status\|doctor\|probe\|guard`(+추후 `gate`)만 허용. `repair\|stop\|restart\|defibrillate\|start` 거절. 접두 검사를 토큰 단위 정확 일치로 바꾸고 `curl`의 `-o`/`--output`/`-O`/`-T`/`--data @` 거절 | H1, H6 |
| 0-2 | `service_ctl`의 chatbot은 `status`만. `start` 거절 (`stop`·`restart`는 ctl이 이미 거절하나 방어를 겹친다) | H2 |
| 0-3 | `/api/host/defibrillate`를 에이전트 도구·curl에서 제외하고 UI POST는 Same-Origin으로 제한 (LAN 평문에서 토큰은 `app.js`에 노출되고 Origin 검사는 실수성 curl과 타 사이트 CSRF만 걸러 낸다는 한계를 명시). CORS `*` 제거. **기본 바인딩을 `127.0.0.1`로** (P1-3). **주의: 이 NAS의 LAN 접속은 `chatbot-ctl.sh cmd_start`가 `AGY_CHAT_HOST=0.0.0.0`을 export하기 때문에 유지되는 것이고, `PROJECT.md:15`의 엔트리 `python3 server.py`를 직접 치면 LAN이 닫힌다.** 다른 기동 경로(Hermes lifecycle, systemd user)는 chatbot `server.py`를 띄우지 않음을 확인했다. 그래서 생산 기동은 ctl만이라고 `PROJECT.md`를 정정하고 (직접 실행은 로컬 전용이라고 명시), **기본값 변경과 ctl의 명시 export를 같은 ⚡ 배치에서** 하고 기본값만 먼저 바꾸지 않는다 | H2 |
| 0-4 | `write_file` deny 기본 집합 = **배포 코드 전체 + 가드 + 티켓**: 호스트 파이썬 모듈 전부(`server.py`, `session.py`, `adapters.py`, `host_config.py`, `instructions.py`, `tool_format.py`, `nas_mcp.py`, `nas_mcp_host.py`, 신규 `evolution`), `chatbot-ctl.sh`, `tests/`, `static/`(이 NAS에서 Tier 0으로 둘 동안은 예외로 명시), `SELF-MODIFY.md`, `AGENTS.md`의 자기수정·사전 승인 규칙, `docs/EMERGENCY.md`, `host-force.ticket`, 매니페스트. **`~/.agents`(전역 공유 스킬)도 쓰기 허용 루트이므로(`nas_mcp.py:42`) 쓰기를 막는다** — 안 막으면 P2-1이 깨진다. `/api/rules` PUT은 `AGENTS.md`·`SELF-MODIFY.md` 읽기 전용. (이 계획서와 리뷰 문서는 에이전트가 관리하는 문서이므로 deny 대상이 아니다 — 결정 10) | H3 |
| 0-5 | `chatbot-self-improve`를 §4.2 트리거에 맞게 수정(우리 스킬이므로 직접 수정 가능). 헌장(`AGENTS.md`)에 "관찰 배지는 작업 지시가 아니다. 진화 작업은 발화·승인 티켓으로만 시작한다" 한 줄. **task-observer는 수정하지 않는다** — 워크스페이스의 것은 전역 공유 파일로의 심링크라 고치면 다른 에이전트의 동작까지 바뀐다(P2-1). 대체는 §4.6에서 하고, 그 전까지 헌장 한 줄이 우선하도록 한다 | H5 |
| 0-6 | `doctor`/`repair`/`start`가 공용 락을 잡는다. 유지보수 플래그 파일이 있으면 자동 기동·복구를 건너뜀. **락 구현은 bash `flock`이 아니라 Python 헬퍼** (macOS에 `flock` 없음, P1-4). 어떤 감시자(현재는 Hermes 크론)가 `doctor`를 부르든 ctl 안에서 지켜지므로 감시자에 의존하지 않음 | H7 (Phase 2의 전제이기도 함) |

**확정 ⚡ 배치 (결정 1)**: **배치 A** = 0-0·0-1·0-2·0-4·0-5, **배치 B** = 0-3, **배치 C** = 0-6 + 보호 파일 해시 사후 탐지 경고(결정 4, `doctor` 경고 전용). 0-3은 LAN 접속 면, 0-6은 기동 락 면이라 실패 양상이 달라 묶지 않는다. 0-6 락에 버그가 있으면 `cmd_start`가 영구 스킵될 수 있으나 워치독이 1분마다 `doctor`를 부르므로 깨진 ctl은 자동 재시도된다. 각 배치는 ⚡ 한 번.

**배치 A 진행 상태: S1 완료 (2026-09-20)** — `tests/test_nas_mcp.py` 특성화 테스트 27개 (현재 열린 구멍은 `test_today_*`로 고정, S3에서 뒤집음). 전체 236개 통과.

**배치 A 진행 상태: S2 완료 (2026-09-20)** — 신규 `evolution.py` + 설정 데이터 `protected_paths.json`(ROOT 바로 아래, 자기 자신도 보호 대상) + `tests/test_evolution.py` 21개. 라이브 영향 없음(신규 파일, 아직 아무도 import 안 함). 전체 257개 통과.

**배치 A 진행 상태: S3 완료 (2026-09-20)** — `nas_mcp.py`를 스크래치에서 고쳐 테스트 통과 후 원본에 `mv` 한 번으로 교체(디스크 반영 끝, **⚡소생 대기** — 실행 중인 MCP 프로세스는 옛 코드). 0-1·0-2·0-4 구현, `tests/test_nas_mcp.py` 49개(특성화 `test_today_*` 뒤집음). 전체 279개 통과. **문서에 없던 추가 결정 2건**: ①`chatbot-ctl.sh doctor`는 인자 없이만 허용(`doctor --auto-repair`가 probe 실패 시 `cmd_repair`로 가서 H1 재개방), ②`run_command`의 `>`/`<` 리다이렉션 거절(`date > 파일`이 write_file deny를 우회, `2>/dev/null`만 허용). `/api/rules` PUT 읽기 전용화(server.py)는 이 배치에서 제외 — 배치 B와 함께.

**배치 A 진행 상태: S4 완료 (2026-09-20)** — 스킬 `chatbot-self-improve`(시작 조건·Tier 요약)와 헌장 `AGENTS.md` 한 줄(0-5), `docs/DEVLOG.md` 한 블록. 다른 사람의 미커밋 변경(concept.md 읽기 문구)은 그대로 얹음. task-observer·전역 `~/.agents`는 손대지 않음.

**배치 A 진행 상태: S5 완료 (2026-09-20)** — 전체 279개 통과, 전 모듈 `py_compile`(3.8.15), `chatbot-ctl.sh guard` → `guard_rlock OK`. **배치 A는 디스크 반영까지 끝. 남은 것: 실장님 ⚡소생 (`nas_mcp.py` 변경분이 MCP 프로세스에 반영되려면).** 배치 B(0-3, `/api/rules` PUT 포함)·배치 C(0-6)는 미착수.

**배치 B 진행 상태: 디스크 반영 완료 (2026-09-20), ⚡소생 대기** — 0-3(defibrillate Same-Origin, CORS, 기본 바인딩 `127.0.0.1`, PROJECT.md 정정) + `/api/rules` PUT 읽기 전용(0-4 조각). 신규 `origin_guard.py`, 수정 `server.py`·`host_config.py`, 테스트 21개. 전체 300개 통과. **문서와 다른 결정**: CORS는 제거 대신 "같은 머신 호스트명만 허용"(허브가 `:3011/api/providers`를 다른 오리진에서 fetch). **미해결(이 레포 밖)**: 허브 `api/chatbot.php` revive가 무인증으로 `chatbot-ctl.sh repair`를 실행한다.

**배치 C 진행 상태: 디스크 반영 완료 (2026-09-20)** — 0-6(`start`/`doctor`/`repair` 공용 락, 유지보수 플래그 `data/maintenance.flag`) + 보호 파일 해시 경고(`doctor`, 경고 전용). `evolution.py` 확장, `chatbot-ctl.sh` 래퍼, `protected_paths.json` 확장, `tests/test_lifecycle.py` 31개. 전체 331개 통과. **⚡소생 불필요**: ctl은 워치독이 이미 새 버전을 실행 중이다. **남은 사람 작업**: 해시 매니페스트가 아직 없다. 보호 파일을 검토한 뒤 `python3 evolution.py manifest-update`를 한 번 실행해야 경고가 동작하기 시작한다(이후 보호 파일을 고칠 때마다 재실행). **Phase 0 남은 미해결(이 레포 밖)**: 허브 `api/chatbot.php` revive.

**Phase 1 · P1-A 진행 상태: 디스크 반영 완료 (2026-09-20), ⚡소생 대기** — §4.6 관찰 수집 코어: `session.py` 합류점 `_finish_turn` + `evolution.on_turn_end` 후보 수집(`candidates.jsonl`) + MCP `observe_add`. 신규 `observation_signals.json`. 전체 385개 통과. **설계와 다른 점**: "도구 오류" 신호는 제외(provider 공통 오류 이벤트가 없고 도구 출력 해석은 §4.4 위반), `busy` 등 기존 종료 처리는 `_finish_turn`으로 옮기지 않음. **남은 Phase 1**: P1-B 티켓·예산·작성자 락(§4.3), P1-C 무흔적 정리(심링크·훅·`task_observer` 상태 키·`static/`), P1-D `memory_*` MCP, 관찰 리뷰 자동 실행 방식 결정(§8-4).

**Phase 1 · P1-B 진행 상태: 디스크 반영 완료 (2026-09-20), ⚡소생 대기** — §4.2~4.3 티켓·예산·단일 작성자 락: 신규 `tickets.py`(근거 검증, 병합, 3회 예산, 임대 락, 승인은 명령줄 전용) + MCP `ticket` 도구 1개 + 저장소 쓰기 보호. 전체 428개 통과. **설계와 다른 점**: 작성자 락은 flock이 아니라 만료되는 임대 파일(MCP에 세션 식별자가 없음), 근거는 검증 가능한 `event:`·`candidate:`만. **사람 작업**: 티켓 승인은 `python3 tickets.py approve N`. **남은 Phase 1**: P1-C 무흔적 정리, P1-D `memory_*` MCP, 관찰 리뷰 자동 실행 방식(§8-4).

**Phase 1 · P1-C(재정의) 진행 상태: 1~3단계 디스크 반영 완료 (2026-09-20), ⚡소생 대기** — 관찰 수명주기 코어 `observations.py`(스캔·해결·보관·리뷰), MCP `observation` 도구(`observe_add` 통합), 배지의 미검토 후보 수, 상태 키 `observation`, `/review`. §8-4 결정: 수동 `/review`만. 전체 483개 통과. **4단계 완료 (2026-09-20)**: 심링크·`hooks.json`·`scripts/` 제거, UI의 옛 키 폴백 삭제, §4.6 무흔적 검사를 `tests/test_no_trace.py`로 자동화(0건). `/review` 첫 실사용에서 `observation` 도구 정상 동작 확인. **P1-C 완료.**

**Phase 1 · P1-D 진행 상태: 완료 (2026-09-20, ⚡ 확인)** — 장기 기억 코어 `memory_store.py` + MCP `memory` 도구 + `tools/memory.py`를 코어를 부르는 껍데기로 교체(옛 구현 폐기). 고친 것: 날짜 이중 부착, 무제한 `forget`(여러 줄이면 거절), 백업 없음. 전체 543개 통과. **폐기 원칙 (실장님)**: 지침·스킬이 하던 일이 코어로 이관되면 이관 → 라이브 검증 → 폐기 순으로 옛 것을 지운다. 헌장 `## 기억` 안내도 줄임. Phase 1 최소 루프(관찰 수집·기록·검토·티켓·예산·락·기억)는 이것으로 갖춰졌다. **Phase 1 완료 조건 남은 것**: 코어 단독 동작 검사(§4.6, 스킬 비우고 MCP 끄고 외부 감시자 없이 수집·예산·락·보호 경로 동작).

**Phase 1 완료 (2026-09-20)** — P1-A 수집, P1-B 티켓·예산·락, P1-C 관찰 수명주기와 의존 제거, P1-D 장기 기억이 모두 코어에 있고 이관된 옛 안내는 폐기됐다. §4.6 완료 조건 둘을 테스트로 고정: **무흔적 검사**(`tests/test_no_trace.py`, 배포 대상에서 참고 대상 이름 0건)와 **코어 단독 동작 검사**(`tests/test_core_standalone.py`, 레이어를 전부 금지한 채 수집·리뷰·티켓 예산과 락·보호 경로·기억·락 헬퍼가 동작). 추가로 지침 묶음 크기 예산(`bundle_budget.json`). **Phase 2는 결정 3에 따라 착수하지 않는다.** **사람 작업으로 남은 것**: 해시 매니페스트 기준선(`python3 evolution.py manifest-update`), 허브 `chatbot.php` revive(웹 루트, 이 레포 밖), `observation_signals.json` 정규식 튜닝(실사용 후보를 본 뒤), `/review`로 첫 후보 정리.

**Phase 0 완료 기준**
- `call_tool("run_command", {"cmd": "chatbot-ctl.sh repair"})`가 거절된다. (호출은 목(mock) 테스트로, 실제 실행 금지)
- `write_file`이 보호 경로를 거절한다. 신규 유닛 테스트 추가.
- `defibrillate`가 무인증 curl로 호출되지 않는다.
- `write_file`이 호스트 `*.py`, `~/.agents` 경로를 거절하고 `static/`은 명시한 예외대로 동작한다. 신규 유닛 테스트.
- 기존 209개 전부 통과

**한계 (문서에 명시)**: 0-4는 MCP와 API 경로만 막는다. **H4의 CLI 네이티브 쓰기는 이 Phase로 막히지 않는다.** CLI provider가 보호 파일을 직접 고칠 수 있다는 위험은 남고, 이건 §5의 격리(Phase 2)나 파일시스템 권한으로만 해결된다. 그전까지는 사후 탐지(보호 파일 해시를 `doctor`가 대조하고 어긋나면 경고)로 완화한다.

---

## 4. Phase 1 — 최소 루프 (Tier 0/1)

새 아키텍처를 만들지 않는다. 기존 `chatbot-self-improve` + `task-observer` + `DEVLOG` + `observation-log`가 관찰→수정→기록 루프이고, 여기에 **등급·트리거·예산**만 얹는다.

### 4.1 위험 등급 (Tier)

| Tier | 대상 | 절차 | 반영 |
|---|---|---|---|
| **0** | `MEMORY.md` 한 줄(`tools/memory.py`), 스킬 본문 텍스트, 정적 UI·페르소나 | 수정 → 관련 유닛 테스트 → 사후 보고 | 에이전트 자율 |
| **1** | 신규 스킬 스크립트, 신규 독립 도구 스크립트 | 수정 → `unittest discover` + `smoke.py` → 사후 보고 | 에이전트 자율 |
| **2** | 파이썬 호스트 모듈, `chatbot-ctl.sh` 일반 로직 | 초안(`.candidate`)까지만 | 사람이 diff 확인 후 ⚡ |
| **3** | 가드 자체(§3 deny 리스트), 권한·포트, 대량 삭제, 승인 규칙, 헌장, 이 설계서 | 승인된 티켓으로만 시작 | 승인 후 패치. 호스트면 ⚡ |

- 애매하면 한 단계 높게. 메모리 자동 증류(압축)는 Tier 3.
- **P3 적용**: Tier 0/1은 레이어(기억 내용, 스킬, 인스턴스 스크립트) 안에서만 자율이다. 코어(관찰 수집, 예산, 락, 보호 경로, 게이트, 승격)는 항상 Tier 2 이상. `nas_mcp.py`는 MCP 레이어의 코드이지만 배포되는 호스트 모듈이라 수정은 Tier 2다.
- **P1-2 적용**: Tier 0/1의 대상 중 `data/workspace/` 아래(기억·스킬·페르소나·인스턴스 스크립트)는 인스턴스 층이라 배포 후에도 그대로다. **`static/`은 core(배포 코드)다.** 이 NAS에서는 지금처럼 Tier 0으로 다루지만, 배포판에서는 인스턴스 오버레이(덮어쓰기 계층)가 생기기 전까지 Tier 2로 격상한다는 전제로 설계하고 오버레이 도입은 별도 계획으로 남긴다.
- 보호 경로 목록·게이트 명령은 코드에 박지 않고 `ROOT` 상대 경로의 설정 데이터로 둔다 (P1-5).
- 반영 시점: 스킬 본문은 즉시(온디맨드 읽기). 스킬 색인·AGENTS·PERSONA는 해시가 바뀌면 다음 턴에 재주입. `MEMORY.md`는 **새 세션 첫 턴부터**. `instructions.py`와 `nas_mcp` 도구는 호스트 모듈이라 ⚡.

### 4.2 트리거
- 시작할 수 있는 것은 **실장님의 명시적 발화**, 또는 **실장님이 승인한 관찰 티켓**뿐. 관찰이 스스로 Draft를 시작하지 않는다.
- 티켓에는 근거(`events.jsonl` 이벤트 ID 또는 호스트 계측 수치)가 필수. "이거 왜 안 돼?"만으로 Tier 2 이상을 시작하지 않는다 — provider 장애·사용자 오해와 자기 버그를 구분한다.

### 4.3 예산과 종료
- 티켓당 시도 **최대 3회**, 초과 시 `wontfix(needs-human)`로 닫고 사람에게 넘김. 게이트 연속 실패 2회면 접근을 바꾸거나 중단. 동일 대상 티켓은 병합.
- 일일 승격 상한은 두지 않는다 (Grok 지적: 티켓당 3회와 작성자 락이면 초기 런어웨이는 막힘. 관측 후 추가).
- **단일 작성자 락**: 멀티 세션·`standby_pool`에서 동시에 두 세션이 수정하지 않도록 `flock`. 실패 시 대기하지 않고 티켓에 메모만 남김.
- 이 종료 조건은 **티켓 상태로 강제**한다. `loop_guard.py`는 agy의 턴 내부 반복만 잡으므로 사이클 브레이크가 아니다.
- **`done` = 배송**: 대상 경로가 git에서 깨끗하다. 미커밋이면 `release(done)` 거절. 호스트 모듈이면 답변에 ⚡소생을 적는다.
- **claim에 경로**: repo-상대 파일을 적는다. 그 경로에 다른 작업의 미커밋이 있으면 claim 거절.
- **프로토콜도 대상**: 지침·설계서·파이프라인·가드는 코드와 같은 루프(관찰 → 티켓 → 승인 → 패치). Tier 3은 승인 없이 시작 불가일 뿐, 승인된 티켓은 이 문서를 고친다.
- 절차 실패(티켓 없이 쓰기, done인데 미커밋, 파일 통째 덮어쓰기)는 관찰을 남기고 프로토콜 티켓을 바로 낸다.

### 4.4 입력 신뢰와 성과 측정
- Observe 입력은 사용자 발화와 호스트 계측 지표로 한정. 웹·도구 출력 본문은 데이터로만 취급하고 티켓·메모리·스킬에 그대로 옮기지 않는다 (프롬프트 인젝션의 영속화 방지).
- `memory.py add`는 실장님 발화 근거로만.
- 개선 티켓은 전/후 지표(턴 수, 토큰, 실패 횟수)를 적는다. 지표가 없으면 "개선"이 아니라 "변경"으로 기록.

### 4.5 관찰 저장 위치
- 냥피디 SSOT는 `data/workspace/skill-observations/observation-log/` (`instructions.py`, `workspace_status.py`가 읽음). 전역 `~/.agents/skill-observations/log.md`는 별개 저장소이며 합치지 않는다.

### 4.6 관찰 기능의 자체 소유화 (P2 적용, Phase 1의 첫 작업)
외부 스킬 심링크와 agy 전용 훅을 걷어내고 **호스트가 소유하는 관찰 기능**으로 바꾼다. 새 설계를 만들지 않고 `instruction-architecture.md` §6-7(P4)을 따른다. 외부 구현에서 배운 사이클은 우리 방식으로 다시 쓴다.

- **유지할 것**: 관찰→기록→참조→반영 사이클, 열린/처리됨 상태, 주기적 리뷰. 이미 쓰는 `observation-log/*.md` 포맷과 `status: open` 규약은 우리 것이므로 그대로.
- **가져오지 않을 것**: 외부 스킬 전문(697줄)과 부속 자료, agy 훅 주입, 절대경로, 매 호출마다 도는 무거운 세션 시작 절차(토큰 세금 — concept.md 토큰 효율 축).
- **우리 메커니즘 (턴 종료 합류점)**: `on_turn_end()`는 `session.py`의 한 함수 `_finish_turn()`에서 부른다. 다섯 provider의 정상 result·error는 `_handle_events`로 모이지만 (CLI는 `_read_stdout`→`_handle_stdout_line`→`normalize_line`→`_handle_events`, omniroute는 `_run_http_turn`→`stream_turn`→`_handle_events`), **`interrupt_current_turn`, `_read_stdout`의 finally(자식이 중간에 죽음), `_reap_sessions`는 여기를 거치지 않는다.** 그래서 `_handle_events`의 result·error 분기를 `_finish_turn()`으로 빼고 위 세 경로도 그것을 부르게 한다. 턴 종료 시 호스트 훅 `on_turn_end()`가 신호(사용자 정정, 중단, 도구 오류, 세션 회전)를 `candidates.jsonl`에 append하고, 모델은 MCP `observe_add`로 기록하며, 첫 턴 주입에 배지를 넣는다. 모든 provider에 동일(프로바이더 훅 미사용). **기록 로직은 코어 함수**이고 `observe_add`는 그것을 부르는 MCP 어댑터다 (P3-5). MCP가 죽어도 `on_turn_end()`의 후보 수집은 계속된다.
- 구현물은 Tier 2(호스트 모듈, ⚡). 범위와 순서는 별도 계획으로 확정한다.
- 관찰 리뷰의 자동 실행 방식(`instruction-architecture.md` §8-4 미정)은 §8 결정 사항과 같은 문제.

**무흔적 검사 (Phase 1 완료 조건)**: 배포 대상 경로에서 외부 이름·경로가 나오지 않는다. 현재 남아 있는 흔적(확인한 것):

| 위치 | 흔적 | 처리 |
|---|---|---|
| `data/workspace/.agents/skills/` | 전역 공유 스킬로의 **심링크** | 링크 제거, 자체 관찰 기능으로 대체 |
| `data/workspace/.agents/hooks.json`, `scripts/*-pre.sh`, `*-stop.sh` | 외부 이름의 훅·스크립트, `/volume1/homes/me/...` 절대경로 | `on_turn_end()`로 대체 후 삭제 |
| `workspace_status.py:61,176` | docstring과 `"task_observer"` 상태 키 (상태 API·UI에 노출) | 역할 이름(`observation`)으로 교체. **API 응답 키 변경이라 `static/`의 소비 코드와 함께** |
| `README.md:40` | 스킬 소개 문구 | 역할 설명으로 교체 |
| `DEVLOG.md`, `docs/plans/*` | 이력·작업 문서 | 유지 (적용 범위 밖) |

검사 방법은 코어 자기 개선 시스템의 코드·주입 규칙·상태 API·사용자 문서에서 외부 이름·경로를 grep해 0건임을 확인하는 것이다 (일반 스킬·MCP는 검사 대상이 아니다).

**코어 단독 동작 검사 (Phase 1 완료 조건, P3-2)**: 스킬을 비우고 MCP 서버를 끄고 외부 감시자가 없는 상태에서 다음이 동작한다. ①`on_turn_end()` 후보 수집 ②티켓 예산·작성자 락 ③보호 경로 검사 ④(Phase 2를 살렸다면) 게이트. 임시 `WORKSPACE`를 쓰는 유닛 테스트로 작성하고 기존 `tests/test_instructions.py`의 격리 방식(임시 디렉터리, 모듈 상수 교체)을 따른다. 이 검사는 Phase 1의 게이트 항목으로 둔다 (P1-5에 따라 검사 대상 이름·경로는 코드에 박지 않고 설정 데이터로).

---

## 5. Phase 2 — 호스트 코어 자기 수정 (보류)

**확정(결정 3): 착수 항목이 아니며 이 절은 제약 기록으로만 유지한다.** Phase 0·1 운영 결과를 보고 재검토한다. **기본값은 현행 관행**(`.candidate`에 초안 → 사람이 diff 확인 → ⚡). **배포판에서는 기본 꺼짐**(P1-3): core 자기 수정은 owner가 명시적으로 켠 인스턴스에서만 동작한다. 아래는 스테이징 자동화를 하기로 정할 때의 **필수 제약**이다.

- **격리는 `git worktree`가 아니다.** 이 NAS에서는 저장소가 홈 전체(`/volume1/homes/me`)이고 `.git`만 2.8G, `/tmp`는 tmpfs 3.9G이며 `/volume1`과 다른 장치라 `/tmp`에서 라이브로의 `replace()`는 원자적이지 않다. **라이브와 같은 파일시스템 위의 `services/chatbot` 복사본**을 쓴다 (이 NAS에서는 `/volume1`. 일반 규칙은 "라이브와 같은 장치" — 원자적 `replace()`의 조건).
- 스테이징 인스턴스는 `AGY_CHAT_ROOT` + **별도** `AGY_CHAT_DATA` + 별도 `AGY_CHAT_PORT`/`NAS_MCP_PORT` + 별도 pid·로그. 현재는 **불가능**하다: `chatbot-ctl.sh:7`이 `CODE`를 하드코딩하고, 어댑터가 MCP 주소를 `127.0.0.1:3012`로 하드코딩(`adapters.py:405,938,1220,1436`)하므로 스테이징 agy가 라이브 `nas_mcp`에 붙는다. 환경변수화가 선행 작업.
- `kill_orphan_agy`(`chatbot-ctl.sh:94-`)는 `ps` 전역 스캔이고 보호 판단은 자기 `DATA` 기준이다. 스테이징의 `cmd_start`/`probe`가 라이브의 `flash-low` 대화와 대화 ID 없는 자식을 SIGTERM한다. **"자기 서버 자식만" 범위 제한이 선행.**
- `promote`는 §3의 0-6 락과 유지보수 플래그를 사용한다. 다중 파일 스왑은 디렉터리 통째 rename 또는 포인터 스왑(혼합 트리 방지). last-good 스냅샷도 `/volume1`에.
- promote 전 `git diff -- <path>`로 라이브 파일이 더티(다른 에이전트 편집)면 중단. pathspec 커밋은 커밋만 보호하고 워킹 트리 덮어쓰기는 보호하지 않는다.
- `gate` 구성: G0 보호 경로 **내용 해시**(개수 아님. 매니페스트는 에이전트 쓰기 루트 **밖**, 사람만 갱신, 없거나 불일치면 실패 폐쇄) → `py_compile`(3.8.15)·`node --check` → `guard_rlock` → `unittest discover`(읽기 전용 복사본에서 실행 후 해시 재대조) → import 스모크 + `smoke.py` → (Tier 2만) 스테이징 `probe`.
- `probe`는 agy 모델 하드코딩·쿼터 소모·큐 적재 시점 반환이므로 provider 불변성의 근거가 못 된다. 스테이징용 더미 어댑터 또는 provider 인자화 필요.
- node는 게이트 의존성 (테스트 7개가 node 없으면 skip → 게이트 실패).
- 자동 롤백: 재기동 실패 시 last-good 복원. `promote`는 Phase 0-1(ctl 서브커맨드 화이트리스트)의 허용 목록에 **넣지 않고** 사람 전용 진입점(인증)으로만 둔다.
- 라이브 경로에 직접 쓰지 않는 "스테이징" 해석은 SELF-MODIFY "디스크 설계도" 모델의 변경이므로 Tier 3 승인.

---

## 6. 계층별 적용 (v2에서 정리)

- **L1 기억**: 추가·삭제는 지금처럼 `tools/memory.py`(Tier 0). **자동 증류는 보류**(현재 788B/4KB). 필요하면 스냅샷+사람 승인 diff(Tier 3). 후속 선택: `memory.py` 쓰기 전 1세대 백업. **"판단 가중치"는 삭제** — 프롬프트 기반 에이전트에 가중치는 없고, 개선의 산출물은 규칙·스킬 텍스트다. **omniroute는 셸이 없어 `memory.py`에 못 닿으므로(`nas_mcp`에 memory 도구 없음) Tier 0 기억 자율은 `memory_*` MCP(`instruction-architecture.md` §6, 미구현)가 선행이다.** Phase 0 범위는 아니고 Phase 1 전에 필요하다 (`cross-cutting-principles.md` #8).
- **L2 도구**: 모든 provider가 도달해야 하는 능력은 `nas_mcp`에 둔다 (`cross-cutting-principles.md` #8). 스킬 스크립트는 셸 가능한 provider의 편의일 뿐 "모든 provider 동일 능력"이 아니다. `nas_mcp` 도구 추가는 Tier 2(⚡).
- **L3 구조 리팩터링**: 에이전트는 분리 설계안 티켓까지만. 라인 수(`session.py` 1,996, `adapters.py` 1,930) 임계 자동 트리거 없음.

---

## 7. 절대 안전장치

1. **뇌수술 금지**: 실행 중인 프로세스 메모리·stdin 파이프 조작 금지, 자가 재기동 금지 (기존).
2. **원자적 쓰기** `.tmp` → `replace()` (기존, 파일 단위).
3. **가역성**: 파괴적 변경 전 스냅샷 또는 커밋. 롤백은 자기 pathspec에만.
4. **인간 승인 경계**: 권한·포트·대량 파기·**가드 자체의 변경**은 실장님 승인.
5. **자기 통과 조건 수정 금지**: 게이트·테스트·가드를 에이전트가 고쳐서 통과하지 않는다 (집행은 Phase 0-4).

---

## 8. 결정 (확정)

실장님 "추천대로 확정" (2026-09-20). 1~4, 6~8은 리뷰 추천 그대로이고, 5는 결정 3의 결과로 불필요해졌으며, 9·10은 앞서 확정했다.

1. **Phase 0 범위·배치 — 확정**: 배치 A(0-0·0-1·0-2·0-4·0-5) → 배치 B(0-3) → 배치 C(0-6 + 해시 경고). 각 배치는 ⚡ 한 번. *이 결정은 범위와 순서의 확정이며 착수 지시가 아니다.*
2. **`defibrillate` 인증 — 확정**: 에이전트 도구·curl에서 막는 것(0-1)을 본체로 하고, UI POST는 Same-Origin만 둔다. LAN 평문에서 토큰은 `app.js`에 노출되므로 토큰 방식은 채택하지 않는다. 배포판 인증은 127.0.0.1 기본 + 앞단 프록시로 미룬다.
3. **Phase 2 — 확정**: 착수 항목에서 제외하고 §5의 제약 절만 남긴다. 현행 `.candidate` + 사람 diff 확인 + ⚡로 확정. 스테이징은 ctl의 `CODE`·MCP URL 환경변수화와 `kill_orphan_agy` 범위 제한이 선행이라 별도 문서 사안.
4. **해시 사후 탐지 — 확정**: `doctor`에 **경고만** 넣는다 (배치 C). 불일치로 auto-repair는 하지 않는다 (미검증 코드를 기동하거나 고친 가드를 옛 해시로 되돌릴 수 있음).
5. **"디스크 설계도"→"스테이징" 재해석 — 불필요**: 결정 3으로 Phase 2를 착수하지 않으므로 SELF-MODIFY 재해석도 하지 않는다. Phase 2를 되살릴 때 다시 논의한다.
6. **배포판의 자기 수정 기본값 — 확정**: 인스턴스 층(Tier 0/1)만 기본 허용, core(Tier 2)는 owner opt-in (P1-3).
7. **`static/` — 확정**: 배포판은 인스턴스 오버레이가 생기기 전까지 **Tier 2**, 이 NAS만 SELF-MODIFY 규칙 2대로 Tier 0. (P1-2와 P3-3의 충돌 해소)
8. **감시자 배선 — 확정**: 제품에 OS 서비스 유닛 템플릿을 넣지 않는다. `chatbot-ctl.sh doctor`의 호출 계약만 문서화한다 (별도 작은 문서 작업, Phase 0 배치에 포함하지 않음).
9. **코어의 물리적 경계 — 확정 (2026-09-20)**: 코어는 **독립 Python 모듈로 따로 만든다** (가칭 `evolution`, 이름은 구현 계획에서 확정). `server.py`·`session.py`는 그 얇은 호출자다. 이에 따라 `nas_mcp.py`는 코어가 아니라 레이어로 분류한다 (이 분류는 확정된 결정에서 제가 도출한 것이니 다르면 정정). 신규 모듈이라 Tier 2(⚡).
10. **P2 "최종 산출물"의 경계 — 확정 (2026-09-20)**: 로그(`DEVLOG.md`, 관찰 로그 등)와 계획 문서(`docs/plans/`)는 에이전트만 보고 관리한다. 무흔적 검사는 코어 자기 개선 시스템의 코드·주입 규칙·상태 API·사용자 대면 문서에만 적용한다.

## 8-1. 관련 문서 정정 필요 (구현 착수 전)

- `chatbot-host-portability.md` Phase 1은 완료로 적혀 있고 형태는 `nas_mcp/core.py` 패키지가 아니라 **`nas_mcp.py` + 선택 플러그인 `nas_mcp_host.py`**(`NAS_MCP_HOST_PLUGIN`)다.
- 같은 문서는 `ALLOW_ROOTS`를 DATA·AGENTS·web-chat·TMP로 **축소**했다고 적지만 현재 코드는 `(SERVICES/"chatbot")`를 다시 넣었다 (`nas_mcp.py:46`, 주석: 코드 편집용). H3의 원인이며 0-4로 다시 막는다. 그 문서의 서술과 코드를 맞춰야 한다.
- 두 문서(`chatbot-host-portability.md`와 이 문서)가 모두 "Phase 0"을 쓴다. 구현 착수 시 이 문서의 것을 **"보안 Phase 0"**으로 부르거나 번호를 정정한다.
- `instruction-architecture.md` §6은 `observe_add`를 "`nas_mcp.py` 코어"에 두지만, 이 문서는 `nas_mcp`를 레이어로 본다 (P3). 구현은 `evolution`에 기록 함수를 두고 MCP는 얇은 래퍼여야 한다. 그 문서를 이에 맞게 갱신한다.
- `PROJECT.md:15`의 엔트리 `python3 server.py`는 0-3에 맞춰 정정한다.

## 9. 확인하지 못한 것

- claude adapter의 권한 플래그와 provider별 실제 쓰기 범위 (agy·grok·codex만 확인).
- `hooks.json`(task-observer)이 provider별로 작동하는지.
- DSM 작업 스케줄러 DB에 chatbot 관련 항목 (Hermes cron만 확인).
- chattr/immutable 지원 여부 (파일시스템 수준 보호의 가능성).
- 챗봇이 띄운 grok 자식이 상대경로만 쓰는지 (절대경로면 라이브 `services/chatbot`도 씀).
- Grok 리뷰는 MCP `curl`이 GET만 가능하다고 봤으나, 접두 검사만 있고 메서드 제한은 코드에 없다. 실제 POST 가능 여부는 라이브 호스트를 건드리므로 실행 검증하지 않았다.
- 리뷰 시점 이후 파일 변경분.
- task-observer 외의 다른 외부 의존 전수 (확인한 것: task-observer 심링크·훅, Hermes 크론 워치독. `nas-sphere`, `anime-layer-animator` 스킬과 `nas_mcp_host.py`의 Hermes/Sphere 연동은 P2 관점에서 분류하지 않았다).
- macOS·Windows에서의 동작 (P1은 구조 조건이지 검증 범위가 아님). (Grok v3 검증에서 대조 완료 — 아래 "관련 문서 정정" 참고.)
