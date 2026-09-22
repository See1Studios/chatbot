# chatbot 호스트 일반화 (DiskStation 결합 제거) + 멀티에이전트 작업 시퀀스

## Context

`services/chatbot`(냥피디)는 지금 DiskStation 하나에서만 돌아가는 걸 전제로 짜여
있다. 실장님이 배포(다른 호스트로 이전/복제)를 염두에 두고 두 가지를 요청함:

1. **일반화**: 이 환경(DiskStation)에 묶인 요소를 걷어내서, 다른 호스트에서도
   돌 수 있게 만든다.
2. **작업 시퀀스 명시**: 이 프로젝트는 지금까지도 Claude Code/Grok/Antigravity(Gemini)/
   Codex 등 여러 에이전트가 세션을 넘나들며 같은 자기수정 루프를 이어왔다
   (`docs/plans/api-provider-adapters.md`가 그 실제 전례 — `## Phase N` 섹션 +
   완료 시 `## Phase N 진행 상태: 구현 + 실측 완료 (날짜)` 마커를 그 자리에 덧붙이는
   방식). 이번 일반화 작업도 같은 패턴의 phase-tracked 문서로 남겨서, 어느
   에이전트가 이어받든 "뭐가 끝났고 뭐가 남았는지"를 바로 알 수 있게 한다.

**조사 결과(읽기 전용 서베이, 실측 file:line 근거 — 2026-09-18)**:

- **server.py** — `HOME`/`AGY_BIN` 등은 이미 env override 가능하지만 *기본값만*
  DiskStation 경로. 하지만 다음은 override 자체가 없음: `BRAIN`(`.gemini/antigravity-cli`,
  agy 고유 캐시 위치라 `HOME`에서 파생되는 건 맞지만 자기 몫의 override는 없음),
  `/volume1/web/chat`(ADD_DIRS·페르소나 서빙), 4곳에 중복된
  `env["PATH"]="/volume1/homes/me/.local/bin:..."`, `_rewrite_artifact_paths()`의
  경로 문자열 치환, `/volume1/homes/me/.agents/skills` 스킬 디렉터리, 소생용
  `chatbot-ctl.sh repair` Popen 호출.
- **chatbot-ctl.sh** — `HOME_DIR=/volume1/homes/me`가 파일 맨 위에 리터럴로 고정.
  `repair`/`start` 경로에서 `AGY_BIN=/volume1/homes/me/.local/bin/agy`를 강제
  export해서, 다른 배포에서 `AGY_BIN`을 이미 세팅해놔도 이 줄이 덮어씀(버그성
  비일관). `PORT_CHAT`/`PORT_MCP`도 여기선 env를 안 읽고 리터럴.
- **nas_mcp.py** — `WEB = Path("/volume1/web")` override 없이 고정. `ALLOW_ROOTS`/
  `READ_ROOTS`가 이 NAS의 디렉터리 레이아웃(`~/.hermes`, `~/wiki`, `~/projects`,
  `~/.agents`)을 전제. `CMD_PREFIXES`/`SERVICE_CTLS`가 `namuwatcher-ctl.sh`,
  `~/.hermes/scripts/hermes-lifecycle.sh`, `hermes` 바이너리 같은 **이 NAS에만
  있는 형제 서비스**를 이름으로 하드코딩. `sphere_hub_status`/`factory_status`/
  `hermes_status` MCP 툴 3종도 전부 이 NAS 전용.
- **문서** — `PROJECT.md`/`SELF-MODIFY.md`가 `/volume1/web/chat` 경로를 안전
  경계 텍스트에 직접 적어놓음.
- 이미 env로 잘 빠져있는 것(손 안 대도 됨): `AGY_CHAT_HOST/PORT`, `AGY_BIN`/
  `AGY_CLAUDE_BIN`/`AGY_GROK_BIN`/`AGY_CODEX_BIN`(server.py 쪽 메커니즘 자체는
  이미 portable), `NAS_MCP_HOST/PORT`, 각 프로바이더의 `api_key_env`,
  `secrets.env` 소싱 패턴(자체는 portable, `HOME_DIR`에서만 간접 오염).

**설계 확인 (실장님 승인, 2026-09-18)**: `nas_mcp.py`는 **core/host-plugin 분리** —
범용 도구(`ping_nas`/`list_dir`/`read_file`/`write_file`/`run_command`/
`search_text`)는 `nas_mcp/core.py`로, DiskStation 전용 도구
(`service_ctl`/`sphere_hub_status`/`factory_status`/`hermes_status`)는
`nas_mcp/host_plugin.py`로 분리. 새 배포는 플러그인 모듈을 그냥 안 두거나
설정으로 끄면 그 도구들이 노출되지 않음(억지로 비활성 스텁을 만들 필요 없음 —
애초에 로드가 안 됨).

## Phase 0 — server.py + chatbot-ctl.sh 경로 일반화

**파일**: `services/chatbot/server.py`, `services/chatbot/chatbot-ctl.sh`

- 새 env var `AGY_CHAT_WEB_ROOT`(기본값 `/volume1/web` — 이 NAS 한정 기본값이지,
  하드코딩 제거) 도입. `server.py`의 `/volume1/web/chat` 참조(ADD_DIRS,
  `_rewrite_artifact_paths`, persona 서빙 관련 부분)를 이 변수에서 파생.
- 4곳에 중복된 `env["PATH"] = "/volume1/homes/me/.local/bin:..."`를 헬퍼 함수
  하나(`_agent_env()` 같은)로 묶고, `HOME`에서 파생.
- `/volume1/homes/me/.agents/skills` → `HOME / ".agents" / "skills"`.
- 소생용 `chatbot-ctl.sh repair` Popen 호출의 절대경로 → `ROOT`(이미 있는
  `AGY_CHAT_ROOT` env, server.py 상단에 정의돼 있음)에서 파생.
- `chatbot-ctl.sh`: `HOME_DIR`을 `${HOME_DIR:-/volume1/homes/me}` 식으로 env
  override 가능하게(기존 기본값 유지, 강제 아님). `repair`/`start`의
  `AGY_BIN=/volume1/homes/me/.local/bin/agy` 강제 export를
  `AGY_BIN="${AGY_BIN:-$HOME_DIR/.local/bin/agy}"`로 바꿔서 이미 세팅된
  override를 안 덮어쓰게. `PORT_CHAT`/`PORT_MCP`도 같은 패턴으로
  `${AGY_CHAT_PORT:-3011}`/`${NAS_MCP_PORT:-3012}`.

**검증**: `py_compile server.py`, `chatbot-ctl.sh guard`, `chatbot-ctl.sh repair` 후
`probe_message` PASS, 기존 세션 하나 살아있는지(`GET /api/sessions/active` 200),
env override 없이 돌렸을 때 지금과 동일하게 동작(리그레션 없음) 확인.

## Phase 0 진행 상태: 구현 + 실측 완료 (2026-09-18)

계획대로 `WEB_ROOT`(env `AGY_CHAT_WEB_ROOT`, 기본값 `/volume1/web`)와
`AGENT_PATH_PREFIX` 도입. `ADD_DIRS`/`_short_path`/`_rewrite_artifact_paths`
(정규식을 `BRAIN`/`DATA`에서 동적으로 빌드하도록 변경)/persona 정적 서빙
fallback/`skills_dir`/소생용 `chatbot-ctl.sh` Popen 호출 전부 하드코딩 대신
`HOME`/`ROOT`/`WEB_ROOT`에서 파생. 4곳 중복된 PATH env 라인을
`AGENT_PATH_PREFIX` 하나로 통합. 계획에 없었지만 같은 카테고리라 같이 처리:
`healthz`의 `"mcp_port": 3012` 리터럴 → `MCP_PORT`(env `NAS_MCP_PORT`) 파생.

`chatbot-ctl.sh`: `HOME_DIR="${HOME_DIR:-/volume1/homes/me}"`로 override
가능(기존 기본값 유지). `cmd_start()`의 `export HOME=/volume1/homes/me` →
`export HOME="$HOME_DIR"`, `AGY_BIN=` 강제 대입 → `AGY_BIN="${AGY_BIN:-...}"`로
바꿔 기존 override를 안 덮어쓰게. `PORT_CHAT`/`PORT_MCP`도
`${AGY_CHAT_PORT:-3011}`/`${NAS_MCP_PORT:-3012}`.

**실측 검증**:
- `py_compile server.py` OK, `bash -n chatbot-ctl.sh` OK.
- `chatbot-ctl.sh guard` → `chatbot-ctl.sh repair` → `probe_message` PASS.
- 리그레션 없음: 재기동 후 `GET /api/sessions/active`가 재기동 전과 같은
  세션 id(`20260918-224646-8bfbd3`)를 그대로 반환, `add_dirs`에
  `/volume1/web/chat` 그대로(env override 안 준 기본 동작 불변), 페르소나
  정적 자산(`/chat/persona/face-icon.webp`) 200.
- **override가 실제로 먹는지 별도 인스턴스로 확인**: 임시 포트/데이터
  디렉터리로 `AGY_CHAT_WEB_ROOT=<임시 경로>` 줘서 별도 `server.py` 프로세스를
  띄우고 새 세션을 만들어보니 `add_dirs`에서 `/volume1/web/chat`이 사라짐
  (오버라이드된 경로는 테스트 디렉터리에 `chat/` 서브폴더가 없어서
  `ADD_DIRS`의 기존 existence 필터에 걸려 빠진 것 — 정상 동작, 버그 아님).
  `healthz`의 `mcp_port`도 실제 라이브 재확인 시 env 기본값(3012)과 일치.
- 커밋: `f63fa0c2`

## Phase 1 — nas_mcp core/host-plugin 분리

**파일**: `services/chatbot/nas_mcp.py` → `services/chatbot/nas_mcp/core.py` +
`services/chatbot/nas_mcp/host_plugin.py` + `services/chatbot/nas_mcp/__main__.py`
(또는 최소 변경으로 같은 파일 안에서 두 섹션으로 나누고 로딩만 조건부 —
작업 시작 시 디렉터리 분리 vs 단일 파일 내 섹션 분리 중 더 작은 diff로 같은
효과를 내는 쪽으로 다시 판단)

- `ALLOW_ROOTS`/`WEB`/`CMD_PREFIXES`/`SERVICE_CTLS`를 하드코딩에서
  `nas_mcp_host.json`(또는 env) 설정 파일로 이동 — 없으면 core 도구만 뜨고
  host_plugin 도구(`service_ctl`/`sphere_hub_status`/`factory_status`/
  `hermes_status`)는 `tools/list`에 안 나타남.
- 이 NAS 자신의 설정값(현재 하드코딩된 값 그대로)은 그 설정 파일의
  "이 배포의 기본값"으로 옮겨서 지금 동작은 완전히 동일하게 유지.

**검증**: `python3 -m py_compile`, `tools/list` 응답에 host_plugin 도구가 여전히
나오는지(이 NAS에서는 설정돼 있으므로), 설정 파일을 비웠을 때 core 도구만
남는지 로컬로 한 번 시뮬레이션.

## Phase 1 진행 상태: 구현 + 실측 완료 (2026-09-18)

디렉터리 분리가 아니라 **같은 패턴의 두 번째 파일** — `nas_mcp.py`(core)는
그대로 스크립트로 직접 실행되고(`chatbot-ctl.sh`가 `python3 nas_mcp.py`로
띄우는 방식 불변), 새 `nas_mcp_host.py`가 optional plugin. `nas_mcp.py`가
`_run()`/`envelope`/`_scrub_text` 정의 *뒤에* `import nas_mcp_host`를 두고
(순환 임포트 순서 문제 방지), `NAS_MCP_HOST_PLUGIN=0`이면 로딩 자체를
건너뜀. 애초에 계획한 JSON 설정 파일 대신 **plugin 모듈 자체의 존재/env
플래그**로 게이팅 — 이 NAS엔 이미 `nas_mcp_host.py`가 있으니 그게 곧
"이 배포의 설정"이고, 다른 배포는 이 파일을 안 가져가면 끝이라 별도 설정
파일 포맷이 필요 없었음(diff 더 작음, 계획보다 단순화).

- `nas_mcp.py`: `WEB_ROOT`(server.py와 같은 env `AGY_CHAT_WEB_ROOT`) 도입,
  `ALLOW_ROOTS`/`READ_ROOTS`를 core 전용(DATA/AGENTS/WEB_ROOT의 chat
  하위/TMP_ROOT)으로 축소. `CMD_PREFIXES`/`SERVICE_CTLS`에서
  namuwatcher/hermes 항목 제거, 남은 `chatbot-ctl.sh` 경로도 `SERVICES`에서
  파생. `tool_defs()`/`call_tool()`에서 `sphere_hub_status`/
  `factory_status`/`hermes_status` 3개 분기와 그 도구 정의를 제거,
  `_allow_roots()`/`_read_roots()`/`_cmd_prefixes()`/`_service_ctls()`
  헬퍼로 core+plugin 병합, `call_tool()` 끝에 plugin fallback 디스패치
  추가. `list_services`의 `namuwatcher` 항목도 plugin
  `EXTRA_SERVICE_LIST_ITEMS`로 이동. 포트 하드코딩(`3011`/`3012` 리터럴)도
  `PORT_CHAT_HINT`/`PORT`로.
- `nas_mcp_host.py`(신규): `WEB`/`HERMES`/`WIKI`/`PROJECTS` +
  `EXTRA_ALLOW_ROOTS`/`EXTRA_READ_ROOTS`/`EXTRA_CMD_PREFIXES`/
  `EXTRA_SERVICE_CTLS`/`EXTRA_SERVICE_LIST_ITEMS`/`EXTRA_TOOL_DEFS` +
  `call_tool(name, args)`(자기 몫 아니면 `None` 반환) — `sphere_hub_status`/
  `factory_status`/`hermes_status` 구현 원문 그대로 이전.

**실측 검증**:
- `py_compile nas_mcp.py nas_mcp_host.py` OK.
- 격리 포트로 두 번 띄워봄: (1) 기본(plugin 로드) → `tools/list` 11개
  그대로(리팩토링 전과 동일 개수/이름), `list_services`에 namuwatcher 포함.
  (2) `NAS_MCP_HOST_PLUGIN=0` → `tools/list` 8개(core만), `list_services`에
  namuwatcher 없음, `hermes_status`를 직접 호출해도
  `{"success": false, "message": "unknown tool: hermes_status"}` — 게이팅이
  실제로 도구를 안 보여주는 것뿐 아니라 호출도 막는 것까지 확인.
- 병합이 실제로 되는지: plugin 로드 상태에서 `list_dir(~/wiki)`(plugin
  contributed root) 성공, `run_command("namuwatcher-ctl.sh status")`가
  prefix 체크는 통과(plugin contributed prefix) — "command not found"는
  이 테스트 셸에 그 바이너리가 없어서일 뿐, allowlist 로직 자체는 정상.
- 실제 라이브 서비스(`chatbot-ctl.sh repair`) 재기동 후 `tools/list` 11개
  그대로, `healthz` 정상 — 리그레션 없음.
- 커밋: (다음 커밋에서 이 파일과 함께 기록)

## Phase 2 — 문서 템플릿화

**파일**: `data/workspace/PROJECT.md`, `data/workspace/SELF-MODIFY.md`

- `/volume1/web/chat` 리터럴 언급을 "웹 루트(`AGY_CHAT_WEB_ROOT`)" 식 표현으로
  바꾸고, 두 문서 상단에 "이 배포의 실제 값" 한 줄 요약(현재 이 NAS 기준)을
  덧붙인다.

## Phase 2 진행 상태: 구현 완료 (2026-09-18)

`PROJECT.md`: Paths 섹션 상단에 "웹 루트는 env `AGY_CHAT_WEB_ROOT`, 이 배포의
실제 값은 `/volume1/web`" 한 줄 추가, 표의 Hub FAB/페르소나 퍼블리시 경로와
Harness 섹션의 add-dir 경계 문구를 `<웹 루트>`로. `SELF-MODIFY.md`의 스폰 루트
문구도 동일하게. 코드 변경 없음(문서만) — `py_compile`/`repair` 불필요.

## Phase 3 — 정체성(identity)을 지침에서 (타이틀 / 페르소나 / 호칭 분리)

**원칙 (실장님 결정, 2026-09-19):** 챗봇의 모든 identity는 **지침 파일**에서 나온다. 코드·화면·프롬프트에
이름을 박지 않는다. 별도 설정 파일도 만들지 않는다 — 모델이 읽는 텍스트와 호스트(UI·서버 프롬프트)가
쓰는 값이 **같은 파일**이어야 어긋나지 않는다. (초안의 `persona.json`은 이중 진실 원천이라 철회.)

세 개념을 나눈다:

| 개념 | 뜻 | 정본 | 쓰이는 곳 |
|---|---|---|---|
| **타이틀** | 이 챗봇이 맡은 **직책/역할** (예: 프로듀서, 아트디렉터, 테크디렉터) | 워크스페이스 `AGENTS.md`(헌장) 머리말 `title` | 화면 상단 제목 |
| **페르소나** | 캐릭터 — 이름·성격·말투 (예: 냥피디). **선택 사항** | 워크스페이스 `PERSONA.md` 머리말 `persona`(이름) + 본문(성격·말투) | 아바타 alt/툴팁, 대화 표기, 프롬프트 속 자기 지칭 |
| **호칭** | 사용자를 부르는 말 (예: 실장님) | `PERSONA.md` 머리말 `user_title` | 프롬프트·사용자 대면 문구 |

`voice`(머리말, 한 줄)는 옆길 질문(`/btw`) 같은 **호스트가 직접 만드는 짧은 프롬프트**에 넣을 말투 지시다.
성격·말투의 본문은 계속 `PERSONA.md` 본문이 정본이다.

```
# AGENTS.md                         # PERSONA.md
---                                 ---
title: 냥피디                       persona: 냥피디
---                                 user_title: 실장님
                                    voice: 친근한 냥체(~냥, ✦)
                                    ---
```

**읽는 곳:** `identity.py` — 항상 그 인스턴스의 `WORKSPACE`(= `DATA/workspace`, env `AGY_CHAT_DATA`)에서
읽고 mtime으로 캐시한다. 모듈 상수에 이름을 두지 않으므로, 워크스페이스만 다르면 인스턴스마다 자기 identity가
자동 적용된다 (**멀티 챗봇**: 아트디렉터 봇과 테크디렉터 봇이 각자 자기 이름·성격·말투를 자기 지침에 둔다).

**폴백:** 머리말이 없거나 깨지면 중립 기본값(`title=Assistant`, `persona` 없음, `user_title=사용자`, `voice` 없음).
값은 길이 제한 + 제어문자 제거 후 사용하고, `<script>`에 심을 때는 `<`를 이스케이프한다(지침 파일은 편집 가능한
사용자 데이터이므로).

**화면:** 서버가 `index.html`의 `<!--IDENTITY-->`를 `window.__IDENTITY__ = {...}`로 바꿔 서빙해 깜빡임 없이
초기 렌더에 쓴다(마커가 안 바뀌어도 주석이라 무해, JS가 `/api/identity`로 폴백). 아바타는 제공자 선택 트레이의 트리거이므로
`persona`가 없어도 남는다. (마스코트 오버레이는 2026-09-19 폐기 — 아래 "마스코트 폐기".)

**범위 (이번 Phase):** 사용자에게 보이는 이름·호칭 문자열, 서버가 만드는 프롬프트(옆길 질문, 인계 요약기, 대화
라벨), 에이전트 카탈로그의 agy 표기, 새 설치용 `PERSONA.md` 템플릿(워크스페이스에 파일이 없을 때만 복사).

**범위 밖 (기록만):**
- **냥체 UI 문구**(`…다냥`)와 `/help` 안내의 어투 — 페르소나 팩(말투·대사·아트) 단계에서 다룬다.
  이번엔 이름·호칭만 치환하므로, 타이틀/페르소나를 바꿔도 일부 문구는 냥체로 남는다.
- `live.html`(Live2D 뷰어), 아바타 **자산 교체** — 페르소나 팩.
- 메모리 도구·스킬 문서 안의 문구 — 사용자 데이터.
- **멀티 인스턴스에서 identity 밖에서 겹치는 곳:** `chatbot-ctl.sh`의 데이터 경로·pid/log 파일명 고정, 브라우저
  저장소 키(`chatbot.provider`, `sphereAgySession` …) 무접두(같은 origin에서 경로로 봇을 나누면 충돌; 포트가 다르면
  origin이 달라 무방), `/chat/` 경로 접두 하드코딩. 그리고 봇마다 워크스페이스가 따로면 호스트 운영 규칙이
  `AGENTS.md`에 중복되므로 **공통 헌장 + 봇별 역할 파일**로 나눌지 결정 필요.

**영향:** `AGENTS.md`/`PERSONA.md`를 고치면 지침 묶음 해시가 바뀌어 진행 중인 대화에 지침이 **한 번 재주입**된다
(`instructions.py`, 의도된 동작). 이 배포의 타이틀은 처음 "프로듀서"로 정했다가 실장님이 `AGENTS.md`에서 직접 `냥피디`로 바꿨다 — 직책과 페르소나 이름이 같아도 된다(별개 키이므로).

## Phase 3 진행 상태: 구현 + 실측 완료 (2026-09-19)

`identity.py`(머리말 파서·값 정제·mtime 캐시·`<script>` 안전 직렬화·새 설치 시드), `GET /api/identity`,
`index.html`의 `<!--IDENTITY-->` 주입, agy 카탈로그 이름 파생, `session.py`의 프롬프트를 순수 함수
`_btw_prompt`/`_handoff_prompt`로 빼서 identity에서 값을 받게 함, 화면(`app.js`·`mascot.js`·`index.html`)의 이름/호칭
문자열 제거, `templates/PERSONA.md`(중립). (`persona`가 없을 때 마스코트를 숨기던 `body.no-persona`는 마스코트 폐기로 제거.)
이 배포의 값: `AGENTS.md` `title: 냥피디`(실장님이 직접 설정; 처음 합의값은 프로듀서), `PERSONA.md` `persona: 냥피디`/`user_title: 실장님`.

- **테스트:** `tests/test_identity.py`(파서·정제·캐시·시드), `tests/test_identity_wiring.py`(다른 봇으로 프롬프트를 만들어
  옛 이름이 새지 않는지, 서버를 실제로 띄워 `/api/identity`·HTML 주입·악성 값 이스케이프, **런타임 코드/UI에 이름
  리터럴이 다시 들어오면 실패하는 가드**). 전체 76개 통과.
- **실측:** 재배포 후 `/api/identity`, 주입된 HTML(마커 소비됨), `/api/providers`의 agy 표기 확인. **T1 정체성 테스트**
  ("너 누구야? 나를 뭐라 불러?") → "만능 콘텐츠 프로듀서 냥피디이고, 당신을 실장님이라고 부른다냥!" — 본문에서 이름
  서술을 걷어냈어도 모델이 **머리말만으로** 페르소나·호칭·말투를 정확히 인식.
- **미확인:** 브라우저 실화면(스텁 DOM 렌더만 확인 — 이 호스트의 헤드리스 Chromium은 `libatk` 없음).
  `persona`가 없는 봇의 실제 기동은 시뮬레이션(단위 테스트·스텁)만 했다.
- **남은 것(범위 밖):** 냥체 UI 문구·`/help` 어투, `live.html`, 자산 교체 — 페르소나 팩. 멀티 인스턴스에서
  identity 밖의 충돌 지점(ctl 경로·pid/log, 저장소 키 접두, `/chat/` 접두)과 공통 헌장/봇별 역할 분리.
- **운영 메모:** `AGENTS.md`/`PERSONA.md`를 고치면 지침 묶음 해시가 바뀌어 진행 중인 대화에 지침이 한 번 재주입된다.
  머리말 값은 재기동 없이 반영된다(mtime 캐시)지만 화면의 정적 부분은 새로고침이 필요하다.

### 마스코트 폐기 (2026-09-19, 실장님 결정)

Live2D 스타일 마스코트 오버레이(`static/mascot.js`, `index.html`의 `#mascotOverlay`, `chat.css`의 `.mascot-*`/`#m-*`,
`app.js`의 표시·애니메이션 호출, ⋯ 메뉴의 토글)를 **제거**했다. 이유: 위치가 애매하고, 숨겨진 것처럼 보여도 클릭을 가로채는 등
문제가 많았다(숨김 상태에서도 이미지 레이어 약 20장을 불러오는 구조이기도 했다). 그 결과 `persona`가 없을 때 마스코트를 숨기던
규칙(`body.no-persona`)도 필요 없어졌다 — `persona`는 이제 아바타 alt/툴팁, 대화 표기, 프롬프트에만 쓰인다.

**남긴 것:** `static/live.html`(2.5D 뷰어), 레이어 PNG 자산(`data/sessions/_shared/see_through/`), 아바타 이미지.
**재도입 방향(실장님 구상):** 움직이는 캐릭터 비주얼이 다시 필요해지면 오버레이가 아니라 **지금 배경화면으로 쓰이는 이미지를
대체**하는 방식으로 — 화면 위에 떠서 클릭을 막는 요소를 만들지 않는다.

## 검증 방법 (전체, 매 Phase 공통)

`py_compile`/`node --check`(해당되면) → `chatbot-ctl.sh repair` → `probe_message`
PASS → 실측 curl로 최소 1개 실제 동작 확인 → 기존 세션 데이터 손실 없는지 확인 →
이 문서에 `## Phase N 진행 상태: 구현 + 실측 완료 (날짜)`로 기록 → 커밋
(`docs/DEVLOG.md`에도 한 줄).

**다음 에이전트가 이어받을 때**: 이 문서에서 아직 "진행 상태" 마커가 없는 가장
낮은 번호의 Phase부터 시작. Context의 조사 결과는 실측 근거이므로 재조사 없이
그대로 신뢰 가능 — 단, 코드가 그 사이 바뀌었으면 먼저 `grep`으로 여전히 유효한지
확인.
