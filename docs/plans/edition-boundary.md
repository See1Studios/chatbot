# 배포판/개발판 경계

> 방향 (align/D, 2026-09-28): **기반** — 기조 「배포판과 개발판」을 코드의 경계로 만든다. 엔드유저 배포의 전제

> 상태: **active** (초안 2026-09-28)
> 목적: 하나의 코드베이스에서 **배포판**(엔드유저, 엔진 코드를 고치지 않음)과 **개발판**(엔진을 만드는 쪽, 코드 자가진화)을 가르는 경계를 설계한다. 경계는 글이 아니라 설정·도구 권한·패키지 목록·테스트로 선다.
> 관련: [../CONCEPT.md](../../CONCEPT.md) 「배포판과 개발판」 · [direction-alignment.md](direction-alignment.md) D2·align/I · [personalization-ladder.md](personalization-ladder.md)(배포판의 자기 개발은 제안 카드) · [plan-execution-workflow.md](plan-execution-workflow.md)(개발판 관문) · [release-pipeline.md](release-pipeline.md)(설치기에 무엇이 들어가나) · [user-data-separation.md](user-data-separation.md)(`~/.pe`) · [plugin-architecture.md](plugin-architecture.md)
> 약칭: `edition`

---

## 1. 범위 / 비목표

**범위**: 모듈·도구·UI·지침을 배포판/개발판/공통으로 분류, 판(edition)을 정하는 한 곳, 배포판에서 에이전트의 쓰기 범위, 배포 패키지에서 뺄 목록, 경계를 지키는 테스트.

**비목표**: 설치기·셸 자체(release-pipeline), 제안 카드 UI(personalization-ladder `ladder/E`), 플러그인 로딩(plugin-architecture).

## 2. 현황 점검 (2026-09-28)

| 확인 | 결과 |
|---|---|
| 위임(`delegation.py`)의 결합 | 이미 선택적: `mcp_server.py`와 `server.py`가 있으면 불러오고 없으면 넘어간다 |
| `evolution.py`의 결합 | 10개 모듈이 불러온다. 역할이 셋 섞임 — ① 재기동 잠금(`evolution.acquire_lock`, 공통) ② 보호 경로·매니페스트(개발판) ③ 턴 신호 수집(`evolution.on_turn_end`, `record_candidate` — 배포판 제안 흐름에도 필요) |
| 티켓(`tickets.py`) | 코어 모듈(`core_modules.json`). `mcp_core.py`(`ticket` 도구), `delegation.py`, `workspace_status.py`, `write_guard.py`가 쓴다 |
| 관찰(`observations.py`) | `instructions.py`·`mcp_core.py`·`workspace_status.py`. 배포판 제안 카드의 재료(ladder D3) |
| 쓰기 감시(`write_guard.py`) | `session.py`가 쓴다. 티켓 없는 저장소 쓰기를 알림 — 개발판 개념 |
| **MCP 파일 도구의 쓰기 범위** | `mcp_server.py::ALLOW_ROOTS`에 엔진 저장소(`services/chatbot`)가 들어 있다. **「배포판 에이전트는 엔진 코드를 고치지 않는다」를 막는 장치가 없다** |
| MCP 도구 | 공통 `memory`·`choices`·파일·검색, 개발판 성격 `ticket`·`delegate`·`run_command`(허용 목록), 환경 플러그인 NAS 도구 |
| UI | 개선 탭(관찰·티켓·작업 카드)은 개발판 표면 |
| 지침 | 공용 헌장 `data/workspace/AGENTS.md`의 Self-modification 절은 개발 절차(pew/L에서 개발 역할 팩으로) |
| 판을 정하는 곳 | 없다 |

## 3. 분류

| 구성 | 배포판 | 개발판 | 비고 |
|---|---|---|---|
| 세션·프로바이더·캐릭터·기억·지침·로어북·사적 엔진·채팅 UI | ✅ | ✅ | 엔진 본체 |
| 재기동 잠금(`evolution.acquire_lock`), 턴 신호(`on_turn_end`) | ✅ | ✅ | `evolution.py`에서 공통 부분 |
| 관찰(`observations.py`) | ✅(제안의 재료) | ✅ | |
| 제안 카드(ladder) | ✅ | ✅ | 배포판 자기 개발의 표면 |
| 티켓(`tickets.py`)·`ticket` 도구 | 숨김 | ✅ | 배포판은 제안 카드로 |
| 위임(`delegation.py`, `tools/worktree_runner.py`, `delegate` 도구, 작업 카드) | ❌ | ✅ | 이미 선택적 로딩 |
| 보호 경로·커밋 안 된 보호 파일 검사(`protected_paths.json`, `evolution.py::protected_changes` — git 기준, split/E), 쓰기 감시(`write_guard.py`) | ❌ | ✅ | 배포판은 엔진 파일 자체를 쓸 수 없게(4.2) |
| MCP 파일 쓰기 범위 | 사용자 데이터만 | 저장소 포함 | 4.2 |
| `run_command` | 없음 또는 최소 | 허용 목록 | D3 |
| 개선 탭 UI | 제안 목록으로 대체 | ✅ | ladder/E |
| 개발 역할 팩·Self-modification 지침 | ❌ | ✅ | pew/L |
| `.githooks/`, `run-tests.sh`, `tests/`, `docs/`, 루트 `AGENTS.md`·`RULES.md`·`CODEMAP.md` | 패키지 제외 | ✅ | 저장소 전용 |
| NAS 호스트 플러그인 | 환경별 | 환경별 | align/F(`host.env`) |

## 4. 설계 초안

### 4.1 판은 한 곳에서 정한다

- `host_config.EDITION` = `CHATBOT_EDITION` 환경변수(`shipped` | `dev`). 다른 모듈은 이 값만 본다.
- 기본값은 **`shipped`**(최소 권한). 개발 설치는 `$CHATBOT_DATA/host.env`에 `CHATBOT_EDITION=dev`를 적는다(align/F의 설치별 설정과 같은 자리). 이 NAS의 `data/host.env`에 추가한다.
- 테스트는 판을 명시해서 돈다(개발판 기능 테스트는 `dev`, 경계 테스트는 `shipped`).

### 4.2 배포판의 쓰기 범위 = 사용자 데이터

- MCP 파일 쓰기·쓰기 도구의 허용 루트는 판에 따라 계산한다. `shipped`: `$CHATBOT_DATA`(와 임시 폴더)만. `dev`: 지금처럼 저장소 포함.
- 설치기는 엔진 폴더를 사용자 쓰기 불가 위치에 둔다(release-pipeline). 코드 차원(허용 루트)과 설치 차원(파일 권한) **두 겹**.
- 배포판에서 에이전트의 자기 개발은 사용자 데이터 안의 스킬·기억·지침·캐릭터에 한정되고, 제안 카드와 변경 기록(ladder)을 거친다.

### 4.3 개발 장치는 없어도 돈다

- 선택적 로딩 패턴(지금의 `delegation`)을 개발판 모듈 전체로 넓힌다: 티켓 도구, 위임, 쓰기 감시, 보호 경로 검사는 `EDITION == "dev"`일 때만 켜고, 모듈이 없어도 엔진이 뜬다.
- `evolution.py`는 공통 부분(잠금·턴 신호)과 개발판 부분(보호 경로·매니페스트)을 나눈다. 모듈을 쪼갤지 함수 단위로 가를지는 D2.

### 4.4 패키지 제외 목록

- 배포 빌드가 제외할 경로 목록을 한 파일로 둔다(`edition_exclude.txt` 초안: `.githooks/`, `tests/`, `docs/`, `AGENTS.md`, `RULES.md`, `CODEMAP.md`, `CLAUDE.md`, `GEMINI.md`, `run-tests.sh`, `tools/worktree_runner.py`, `delegation.py`, 개발 역할 팩 …).
- 경계 테스트가 이 목록의 모듈을 가린 채 `shipped`로 엔진을 띄워 본다(4.5).

### 4.5 경계를 지키는 테스트

`test_edition_boundary`(초안):
- `CHATBOT_EDITION` 미설정이면 `shipped`다.
- `shipped`에서 MCP 도구 목록에 `ticket`·`delegate`가 없다.
- `shipped`에서 파일 쓰기 허용 루트에 엔진 저장소가 없고 `$CHATBOT_DATA`만 있다.
- 제외 목록의 모듈을 가린 상태(`sys.modules`에 막음)에서 서버·MCP 서버·세션을 불러와도 오류가 없다.
- `dev`에서는 지금 도구가 그대로 있다.

## 5. 결정 (2026-09-28 운영자: 전부 추천안 채택)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 기본 판 | **`shipped`**(최소 권한). 개발 설치가 `host.env`에서 `dev`로 켠다. 이 NAS는 `dev` | 결정 2026-09-28 (운영자: 추천대로) |
| D2 | `evolution.py` 분리 | 공통(잠금·턴 신호)과 개발판(보호 경로·매니페스트)을 **모듈로** 나눈다. 코어 경계(`core_modules.json`)도 맞춰 갱신 | 결정 2026-09-28 (운영자: 추천대로) |
| D3 | 배포판의 `run_command` | **없음.** 필요한 작업은 전용 도구로(예: 파일 가져오기). 개발판은 지금 허용 목록 | 결정 2026-09-28 (운영자: 추천대로) |
| D4 | 배포판에서 티켓 | 모듈은 남기되 도구·UI는 숨김. 배포판 표면은 제안 카드(ladder D3) | 결정 2026-09-28 (운영자: 추천대로) |

## 6. 작업 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `edition/A` | 이 문서 + INDEX 행 + 정렬 계획 연결 | `docs/plans/edition-boundary.md`, `docs/plans/INDEX.md`, `docs/plans/direction-alignment.md` | INDEX 행, 커밋 | 0 · — | S | — | ✅ 티켓 없음(pew D3) |
| `edition/B` | `host_config.EDITION` + 이 NAS `host.env`에 `dev` + `templates/host.env.example` | `host_config.py`, `templates/host.env.example` | 미설정 시 `shipped`, 이 NAS는 재기동 후에도 개발판 | 2 · ⚡ | S | D1 | ✅ #282 |
| `edition/C` | 판별 MCP 도구·쓰기 범위(4.2) | `mcp_server.py`, `mcp_core.py` | `shipped`에서 `ticket`·`delegate` 없음, 쓰기 루트는 사용자 데이터만 | 3 · ⚡ | M | edition/B, D3, D4 | ✅ #282 |
| `edition/D` | `test_edition_boundary`(4.5) — 가드 목록·보호 목록에 등록 | `tests/`, `run-tests.sh`, `protected_paths.json` | 4.5의 다섯 항목이 테스트로 고정, 일부러 어기면 실패 | 3 · — | M | edition/C | ✅ #282 |
| `edition/E` | `evolution.py` 분리(D2) | `evolution.py`, 새 모듈, 호출부, `core_modules.json` | 공통 부분만으로 서버가 뜸, 개발판 부분은 `dev`에서만 | 3 · ⚡ | M | D2 | 대기 |
| `edition/F` | 패키지 제외 목록(4.4)과 release-pipeline 연결 | `edition_exclude.txt`, `docs/plans/release-pipeline.md` | 목록의 모듈을 가린 경계 테스트 통과. 엔진 개발 지침(루트 `AGENTS.md`·`RULES.md`·`CODEMAP.md`·`CLAUDE.md`·`GEMINI.md`, `docs/`)도 배포판에 싣지 않음(pew/S) | 2 · — | S | edition/D | 대기 |
| `edition/G` | UI: `shipped`에서 개선 탭 대신 제안 목록 | `static/` | `shipped`에서 티켓·작업 카드 UI가 보이지 않음 | 2 · — | M | ladder/E | 대기 |
| `edition/H` | 지침도 판별로 분리(운영자 2026-10-07: "개발용 지침과 배포용 지침은 절대 섞이지 않고 독립적"): 헌장은 배포판 하나, 개발판 규칙은 `DEV-CHARTER.md`에만 두고 `EDITION=dev`에서만 별도 층으로 주입. 배포판 역할 팩은 배포되는 스킬만 | `instructions.py`, `templates/`, `tools/link_dev_workspace.py` | `test_edition_instructions` | 3 · ⚡ | M | edition/D | #768 (= [prop/G](archive/2026/propagation-and-state-architecture.md)) |

## 7. 의존·순서·리스크

```text
D1 → B(판 설정) → C(도구·쓰기 범위) → D(경계 테스트) → F(제외 목록)
D2 → E(evolution 분리)        ladder/E → G(UI)        pew/L(개발 역할 팩)
```

- 리스크: 기본값을 `shipped`로 바꾸는 순간 `host.env`가 없는 개발 설치는 개발 도구를 잃는다 → B에서 이 NAS의 `host.env`를 같은 변경으로 갱신하고, 재기동 후 도구 목록을 확인한다(align/F와 같은 방식).
- 리스크: 테스트가 판을 가정하면 조용히 건너뛴다 → 테스트는 판을 명시하고, 건너뛴 수를 확인한다(align/F에서 NAS 플러그인 테스트를 켠 것과 같은 방식).
- 되돌릴 수 있는 설계: 판은 설정값 하나라서, 시장 방향이 바뀌어 배포판에 기능을 더 열어야 하면 분류표의 한 칸만 바꾸면 된다.
