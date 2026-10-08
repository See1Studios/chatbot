# 사용자 데이터 완전 분리 설계서 (배포 준비)

> 방향 (align/D, 2026-09-28): **기반** — `~/.pe` 분리 — 개인화 레이어가 엔진 업데이트에 덮어써지지 않게 하는 전제

> 상태: **active** (갱신 2026-10-03) — 코드 기본값은 `~/.pe`다. 이 NAS는 비추적 `data-pin.env`의 `CHATBOT_DATA`로 `~/.pe`를 쓴다. 인덱스에서 `data/` 추적 파일은 빠졌다(티켓·작업공간 거울·페르소나·캐릭터 자산). 파일은 디스크와 `~/.pe`에 그대로 있고 내용은 바꾸지 않았다. 배포 트리에 개인 캐릭터 샘플은 넣지 않았다(C3, 운영자가 고르기 전). 이력은 다시 쓰지 않는다.
> 선행 문서: [user-data-and-editing.md §1](user-data-and-editing.md)
> 목적: 엔진 코드 저장소와 개인화 데이터(기억, 캐릭터, 세션, 비밀 등)의 물리적·논리적 완전 분리
> 관련: [release-pipeline.md](release-pipeline.md) · [private-engine-brand.md](private-engine-brand.md) · [character-memory-adapter.md](character-memory-adapter.md) Q1–Q2 (Memory/`CHATBOT_DATA` 분류와 맞출 것) · [VISION.md](../../VISION.md)

---

## 0. 경로 SSOT (2026-09-27 확정 방향)

| 항목 | 값 |
|---|---|
| **기본 사용자 데이터 디렉터리** | `~/.pe` (**`~/.privateengine` 아님** — 별도 별칭이 없으면 쓰지 않음) |
| **환경변수 (우선순위)** | `CHATBOT_DATA` → `PE_HOME` → `PRIVATEENGINE_HOME` → (레거시) `AGY_CHAT_DATA` → 기본 `~/.pe` |
| **개발 오버라이드** | `CHATBOT_DATA=$CODE/data` (저장소 옆 `data/` 유지 — 현행 NAS/FIREBAT 개발 흐름) |
| **ctl** | `chatbot-ctl.sh`의 `DATA="$CODE/data"` **하드코딩 제거** 필수. 위 env/기본값을 따르고, 개발 시에만 `$CODE/data`를 export |
| **Windows** | `%USERPROFILE%\.pe` (단기). XDG/`LOCALAPPDATA` 등은 이후 |
| **브랜드 별칭** | `PE_HOME` / `PRIVATEENGINE_HOME`은 **선택적 별칭** — SSOT 이름은 `CHATBOT_DATA` (코드·문서 통일). `~/.privateengine`은 기본값이 아님 |

**uds/B 완료(2026-09-28, #284)**: 경로 결정은 `host_config.py::DATA_ENV` 한 곳(`CHATBOT_DATA` → `PE_HOME` → `PRIVATEENGINE_HOME` → `AGY_CHAT_DATA` → `ROOT/data`). `tickets.py`(코어)는 같은 순서를 되풀이하고 `test_data_paths`가 둘을 같게 묶는다. `mcp_server.py`·`logdigest.py`의 우회 제거, `chatbot-ctl.sh`도 같은 순서. 남은 것: `data/` 안의 엔진 설정표(`content_guards.json`, `private_tension_*.json`)를 저장소 쪽으로 옮기기(분류 감사), `~/bin/ticket-quick`의 고정 경로(pew/K). 이전 기록 — 현재 코드: `host_config.py`는 `CHATBOT_DATA`/`AGY_CHAT_DATA` → 없으면 `ROOT/data`. `chatbot-ctl.sh`의 `DATA="$CODE/data"` 줄이 고정 후 export. **배포 기본 `~/.pe` 전환(uds/F, 2026-10-03)**: 환경변수가 없으면 `host_config.py`·`tickets.py`·`chatbot-ctl.sh`가 `~/.pe`를 쓴다. 개발 체크아웃은 git에 넣지 않는 `data-pin.env`(리터럴 `CHATBOT_DATA`)로 덮고, 테스트 실행기는 체크아웃 `data/`를 넘긴다. 라이브 `data/`는 옮기지도 지우지도 않았다. 도구와 이후 파일 금지는 들어갔다. 원격 이력 정리는 아직 아니다(푸시하지 않음).


**uds/D 완료(2026-09-28, #297)**: `data_bootstrap.py` — 작업공간이 없거나 비어 있으면 `templates/workspace/`를 통째로 복사(임시 폴더에 만든 뒤 한 번에 이름 바꾸기, 데이터 폴더 0700), 복사한 파일의 sha256을 `$DATA/bootstrap.json`에 남긴다(나중에 엔진 업데이트가 사용자가 안 고친 파일을 알아볼 기준). 작업공간이 이미 있으면 아무것도 안 한다 — 덮어쓰지 않고, 지운 파일을 되살리지 않는다. `chatbot-ctl.sh`가 매 실행 시 `mkdir` 앞에서 부른다(실패해도 경고만). 이 NAS는 변화 없음. 남은 것: 기본 캐릭터(C3), `providers.json`·`secrets.env` 첫 설정(BYOK 온보딩), 기본값 `~/.pe` 전환(uds/F), 템플릿 갱신을 기존 설치에 전하는 업데이트 규칙(`bootstrap.json` 해시 기준, 별건).
---

## 0.1 지침 소유 기준 SSOT (2026-10-04 운영자 확정)

어떤 지침이 엔진 저장소에 있고 어떤 지침이 사용자 폴더(`~/.pe`)에 있는지는 이 절이 정한다. 파일 단위 목록은 `templates/workspace-manifest.json`, 집행은 `tests/test_workspace_template.py`.

**판정 질문 (위에서부터)**
1. 이 사용자·이 기기의 사실이나 선택이 들어 있나(이름, 기억, 관계, 캐릭터, 호스트 경로)? → **사용자 폴더**
2. 모든 설치에서 같아야 하고 엔진 코드가 그 내용에 기대나? → **엔진 저장소**
3. 엔진을 개발하는 방법인가? → **엔진 저장소(개발판 전용)**

| 쪽 | 무엇 | 위치 | manifest |
|---|---|---|---|
| 엔진 | 코딩 에이전트용 엔진 개발 헌장 | 저장소 루트 `AGENTS.md` 등 | — |
| 엔진 | 엔진 규칙표 | `engine_data/` | — |
| 엔진 | 코드가 만드는 지침 층 | `instructions.py` | — |
| 엔진 | 배포판 기본값(배포 헌장, 기본 스킬·도구, 기본 아이템, 빈 명단)과 기본 역할 팩(art) | `templates/workspace/` | `same` · `variant` |
| 엔진 | 개발판 전용(개발 헌장, PROJECT, SELF-MODIFY, 설계 원칙, 엔진 스킬, 개발 문서)과 개발판 기본 역할 팩(dev·lead·plan·scout) | `templates/dev-workspace/` | `not_shipped` |
| 사용자 | 캐릭터(카드·외형·기억·사적 기억·관계·상태), 실제 명단, 장기 기억 | `~/.pe/workspace/` | `per_user` |
| 사용자 | 모든 역할 팩(art·dev·lead·plan·scout와 사용자가 만든 것), 사용자가 만든 스킬, 이 설치의 티켓·관찰 기록 | `~/.pe/workspace/` | — |
| 사용자 | 개인 도구, 이 기기 전용 스킬·설정, 비밀, 런타임 기록 | `~/.pe` | `per_install` |

**규칙**
- 엔진 소유 지침(헌장, PROJECT, SELF-MODIFY, 설계 원칙, 엔진 도구를 부르는 스킬, 개발 문서)의 정본은 저장소 한 곳뿐이다. 사용자 폴더에 사본을 두지 않는다. 개발 설치에서는 에이전트가 작업 폴더 기준 상대 경로로 지침을 열기 때문에, `~/.pe/workspace`의 해당 경로는 저장소 파일을 가리키는 **링크**다(사본 아님). 엔진은 보호 경로 검사에서 링크를 끝까지 따라가므로 `templates/` 보호가 그대로 걸린다.
- 헌장은 엔진 소유다. 개인 규칙은 캐릭터 카드와 장기 기억에 둔다.
- **역할 팩은 dev든 art든 똑같이 사용자 데이터다**(운영자 2026-09-30 "역할은 사용자 데이터, 엔진은 역할을 모른다", 2026-10-04 "dev와 art는 동등"). 템플릿의 역할 팩은 설치 때 없으면 한 번 복사되는 기본값이고, 그 뒤로는 사용자 것이다. 링크로 묶지 않는다.
- 배포판 기본 스킬·도구(`same`)도 설치 때 한 번 복사하고(uds/D), 그 뒤로는 사용자 것이다.
- 테스트는 사용자 폴더(`~/.pe`)도, 저장소의 옛 `data/`도 읽지 않는다. 엔진 지침은 `templates/`에서, 그 밖은 고정물에서 읽는다.

## 1. 배경 및 목표

1. **배경**:
   - 현재 `services/chatbot` 저장소 아래 `data/` 및 `data/workspace/`에 개인 기억(`MEMORY.md`), 가족/위치 정보, 개인 캐릭터 카드, 세션 로그가 함께 보관되어 있음.
   - 오픈소스 배포, 타 환경 설치, 또는 협업 배포 시 개인정보 유출 위험 및 저장소 비대화 문제 발생.
2. **목표**:
   - **엔진 코드(`services/chatbot/`)**는 100% 재사용 가능하고 개인 데이터가 없는 순수 엔진 저장소로 유지.
   - **사용자 데이터(`CHATBOT_DATA`)**는 기본값 **`~/.pe`** (또는 외부 지정 경로)로 완전히 격리.
   - 새 환경에서 클론 후 실행 시 템플릿(`templates/`)으로부터 사용자 데이터 공간 자동 부트스트랩.
   - 기존 데이터를 유실 없이 이전할 수 있는 멱등성 마이그레이션 도구 제공.
   - 개발 머신에서는 `CHATBOT_DATA=$CODE/data`로 현행 레이아웃을 깨지 않음.

---

## 2. 데이터 분류 및 경로 매핑 SSOT

| 분류 | 대상 파일 / 디렉토리 | 저장 위치 | Git 추적 여부 | 설명 |
|---|---|---|---|---|
| **엔진 (Engine)** | `*.py`, `static/`, `tests/`, `roles/`, `docs/`, `tools/` | 저장소 루트 (`services/chatbot/`) | **추적 (Commit)** | 코드, UI, 기본 역할 팩, 도구 |
| **템플릿 (Templates)** | `templates/team.json`, `templates/characters/`, `templates/AGENTS.md` | 저장소 루트 `templates/` | **추적 (Commit)** | 첫 부트스트랩 시 복사할 기본값 |
| **사용자 설정 (Config)** | `team.json`, `characters/` (카드/스프라이트/`visual.md`), `providers.json` | `$CHATBOT_DATA/` | **제외 (.gitignore)** | 사용자 정의 캐릭터 및 팀 구성 |
| **사용자 기억 (Memory)** | `memory/MEMORY.md`, 캐릭터별 `memory.md`, `private-memory.md` | `$CHATBOT_DATA/memory/`, `$CHATBOT_DATA/characters/<id>/` | **제외 (.gitignore)** | 장기 기억, 페르소나 기억 |
| **런타임 및 세션 (Runtime)** | `sessions/`, `skill-observations/`, `backups/`, `lifecycle.lock`, `*.pid` | `$CHATBOT_DATA/runtime/` 또는 `$CHATBOT_DATA/sessions/` | **제외 (.gitignore)** | 대화 세션, 자체진화 티켓/관찰, 백업 |
| **비밀 정보 (Secrets)** | `secrets.env`, API 키 토큰 | `$CHATBOT_DATA/secrets.env` (권한 0600) | **제외 (.gitignore)** | 민감 자격증명 |

---

## 2.1 분류 감사 (uds/C, 2026-09-28)

`git ls-files data` = **426개**. §2의 분류를 실제 파일에 적용한 결과다. 옮기기·추적 해제는 아래 결정(C1–C6) 뒤에 항목별로 한다.

| 묶음 | 파일 수 | 분류 | 가야 할 곳 | 비고 |
|---|---|---|---|---|
| `content_guards.json`, `private_tension_{defaults,gemini,grok}.json`, `private_refusal_mitigation_gemini.json` | 5 | **엔진** | 저장소의 엔진 폴더(C1) | 코드가 읽는 규칙표. `data/`가 `~/.pe`로 가면 엔진이 못 찾는다(`test_data_paths` 허용 목록의 이유) |
| `providers.json` | 1 | **템플릿** | `templates/`의 기본값 → 설치 때 `~/.pe`로 복사 | 사용자가 API 프로바이더를 더하면 사용자 데이터가 된다 |
| `workspace/AGENTS.md`, `PROJECT.md`, `CROSS-CUTTING-PRINCIPLES.md`, `team.json`, `.mcp.json`, `.gemini/config/mcp_config.json`, `.gitignore` | 7 | **템플릿** | `templates/workspace/` → 부트스트랩(uds/D) | 챗 에이전트 헌장·기본 팀·CLI MCP 설정 |
| `workspace/SELF-MODIFY.md`, `roles/pd/procedure.md` | 2 | **개발판 템플릿** | 개발판에서만(edition) | 엔진 코드 자가진화 절차 |
| `workspace/roles/{artist,staff,pd}/role.md` | 3 | **템플릿** | `templates/workspace/roles/` | 역할 팩(pd는 배포판용으로 다듬기, pew/L) |
| `workspace/tools/*.py`(memory·recall_memory·lunar_calendar·token_audit) | 4 | **템플릿(에이전트 도구)** | `templates/workspace/tools/` | 에이전트가 쓰는 도구 스크립트 |
| `workspace/.agents/skills/*`(character-art·character-pipeline·image-brief·fact-check·anime-layer-animator) | 7 | **템플릿(기본 스킬)** | `templates/workspace/.agents/skills/` | 표준 `SKILL.md` |
| `workspace/.agents/skills/nas-sphere` | 1 | **환경 플러그인** | NAS 설치에만 | align/F와 같은 성격 |
| `persona/providers/*` | 12 | **엔진(UI 자산)** | `static/` 쪽 | 프로바이더 아이콘 |
| `persona/*`(avatar·half·wave·face-icon·icon·bg-studio·gallery·README) | 24 | **템플릿(기본 캐릭터 자산)** | 프리메이드 팩 | 기본 페르소나 이미지 |
| `workspace/characters/<id>/`(3명: card·visual·avatar·stage·gallery) | 43 | **템플릿 후보 + 사용자** | 프리메이드 팩으로 고를 것만(C3) | `memory.md`는 사용자 데이터 |
| `workspace/memory/MEMORY.md` | 1 | **사용자(개인 정보)** | 추적 해제(C4) | 사용자·가족·위치 사실이 들어 있다 |
| `workspace/characters/*/memory.md` | 1 | **사용자** | 추적 해제(C4) | 캐릭터별 기억 |
| `sessions/_shared/*`, `session-quarantine/*` | 42 | **사용자·런타임** | 추적 해제(C4) | 공유 아티팩트, 격리된 세션 메타 |
| `workspace/skill-observations/`(tickets 209·observation-log 62·기타 3) | 274 | **개발판 기록** | 개발 저장소에 남김(C2) | 이 엔진의 개발 이력. 배포판 `~/.pe`는 빈 상태로 시작 |

### 결정 (uds/C)

| C | 질문 | 추천 | 상태 |
|---|---|---|---|
| C1 | 엔진 규칙표 5개의 자리 | 저장소 `engine_data/`(가칭)로 옮기고 `content_guard.py`·`private_engine.py`가 `host_config.ROOT` 기준으로 읽는다. `test_data_paths` 허용 목록에서 두 항목 제거 | 결정·실행 2026-09-28 (#292: `engine_data/`로 이동, 보호 대상) |
| C2 | 개발판 기록(티켓·관찰, 274개) | 개발 저장소에 그대로 둔다(개발판은 `CHATBOT_DATA=$CODE/data`). 배포 패키지에서는 제외(edition/F) | 결정 2026-09-28 (운영자: 추천대로) |
| C3 | 기본 캐릭터 | 프리메이드 팩 후보를 운영자가 고른다. 고른 캐릭터에서 사적 규칙·기억 등 개인 부분을 걷어 템플릿으로. 가져온 저작권 캐릭터(예: 게임 캐릭터 카드)는 팩에서 제외 | 보류 — 운영자가 프리메이드 팩 후보를 고른 뒤 |
| C4 | 개인 정보·런타임 파일(45개) | **지금 추적 해제**(`git rm --cached` + `.gitignore`, 파일은 로컬에 남음). 과거 이력에 남은 부분의 정리(히스토리 재작성)는 운영자가 따로 결정(release-pipeline What NOT) | 결정·실행 2026-09-28 (#290: 44개 추적 해제, 파일은 로컬에 남음; 과거 이력 정리는 별도 결정) |
| C5 | 템플릿으로 갈 파일(약 60개)의 이동 방식 | `templates/workspace/`로 **복사**해 정본으로 두고, 개발 설치의 `data/` 쪽은 그대로(부트스트랩이 빈 `~/.pe`에만 복사, uds/D) | 결정·실행 2026-09-28 (#295: `templates/workspace/` 12개 + `templates/workspace-manifest.json`. 목록의 모든 파일이 `same`(바이트 동일)·`variant`(배포판 전용 판)·`not_shipped`(이유와 함께) 중 하나. 헌장·`team.json`은 배포판 판. pd·staff·dev 역할, PROJECT·SELF-MODIFY는 개발판 전용. character-art·character-pipeline·image-brief는 엔진 도구 경로가 생길 때까지(edition E) 보류. `providers.json` 기본값은 BYOK 온보딩(uds/D)에서. 집행: `test_workspace_template`(FAST)) |
| C6 | 프로바이더 아이콘 | `static/providers/`로 옮긴다(엔진 UI 자산) | 결정·실행 2026-09-28 (#299: 12개 → `static/providers/`, 주소 `/chat/providers/<id>.webp`. 옛 주소는 이 NAS에선 웹 루트 사본으로 계속 열림. `providers/bg/` 무대 배경은 다른 작업의 미추적 파일이라 손대지 않음) |

## 3. 아키텍처 및 경로 추상화 설계

### 3.1 `host_config.py` 기준 경로 체계 개편

현재 `host_config.py`는 `DATA = Path(_env("CHATBOT_DATA", ..., ROOT / "data"))`로 환경변수를 지원한다.
목표 표준:

```python
# host_config.py (목표)
ROOT = Path(_env("CHATBOT_ROOT", "AGY_CHAT_ROOT", str(Path(__file__).resolve().parent)))
# 기본값: ~/.pe  (Windows: %USERPROFILE%\.pe)
# ~/.privateengine 은 기본값 아님 — PE_HOME/PRIVATEENGINE_HOME 별칭만 선택적
DEFAULT_DATA_DIR = Path.home() / ".pe"
DATA = Path(
    _env(
        "CHATBOT_DATA",
        "PE_HOME",
        "PRIVATEENGINE_HOME",
        "AGY_CHAT_DATA",
        str(DEFAULT_DATA_DIR),
    )
)

WORKSPACE = DATA / "workspace"
MEMORY_DIR = WORKSPACE / "memory"
SESSIONS = DATA / "sessions"
OBSERVATIONS = WORKSPACE / "skill-observations"
BACKUPS = DATA / "backups"
SECRETS_FILE = DATA / "secrets.env"
```

### 3.2 `chatbot-ctl.sh` — 하드코딩 제거 (MUST)

현재:

```bash
DATA="$CODE/data"  # consolidated under chatbot/ 2026-09-16
# …
export CHATBOT_ROOT="$CODE" CHATBOT_DATA="$DATA"
```

목표:

```bash
# 이미 export된 CHATBOT_DATA / PE_HOME / PRIVATEENGINE_HOME 존중
# 미설정 시: 개발 편의로 기본을 $CODE/data 로 둘지, 배포 기본 ~/.pe 로 둘지는
# release-pipeline Next 단계에서 전환. 하드코딩 한 줄에 묶지 말 것.
CODE="${CODE:-$SCRIPT_DIR}"
if [ -z "${CHATBOT_DATA:-${PE_HOME:-${PRIVATEENGINE_HOME:-}}}" ]; then
  # 2026-10-03 적용. 개발 체크아웃은 비추적 data-pin.env 가 CHATBOT_DATA 를 준다.
  DATA="${HOME}/.pe"
else
  DATA="${CHATBOT_DATA:-${PE_HOME:-$PRIVATEENGINE_HOME}}"
fi
export CHATBOT_ROOT="$CODE" CHATBOT_DATA="$DATA"
```

**실장님 경로 요약**: 배포 기본 `~/.pe` · 개발 `CHATBOT_DATA=$CODE/data` · ctl은 CODE/data 고정 금지 · Windows `%USERPROFILE%\.pe`.

### 3.3 신규 설치 시 부트스트랩 (Bootstrap) 흐름

1. `server.py` 또는 `host_config.py` 구동 시 `DATA` 디렉토리 존재 여부 확인.
2. 미존재 시 디렉토리 생성 및 `ROOT / "templates"`의 기본 파일 복사:
   - `templates/team.json` → `$CHATBOT_DATA/workspace/team.json`
   - `templates/characters/default/` → `$CHATBOT_DATA/workspace/characters/char_default/`
   - `templates/AGENTS.md` → `$CHATBOT_DATA/workspace/AGENTS.md`
   - 빈 `MEMORY.md` 초기화
3. `secrets.env` 부재 시 `templates/secrets.env.example` 복사 (0600 권한).

### 3.4 Windows · 크로스플랫폼 메모

| OS | 기본 경로 | 비고 |
|---|---|---|
| Linux / macOS | `~/.pe` | `$HOME/.pe` |
| Windows (단기) | `%USERPROFILE%\.pe` | `Path.home() / ".pe"` 와 동일 |
| Windows (이후) | XDG 또는 `%LOCALAPPDATA%\PrivateEngine` 검토 | 브랜드 확정·인스톨러 단계에서 |

`~/.privateengine`은 **기본값이 아니다**. 필요 시 `PE_HOME`/`PRIVATEENGINE_HOME` 별칭으로만 지정.

---

## 4. 단계별 실행 계획

```mermaid
flowchart TD
    A[1단계: 상세 설계 확정 및 템플릿 폴더 준비] --> B[2단계: 마이그레이션 스크립트 작성 및 테스트]
    B --> C[3단계: host_config·ctl 하드코딩 제거]
    C --> D[4단계: 실제 데이터 이전 실행 및 소생 검증]
    D --> E[5단계: 저장소 data/ 정리 및 커밋 가드 적용]
```

### 1단계: 템플릿 폴더(`templates/`) 체계화
- 저장소 내에 공용 기본값 저장:
  - `templates/workspace/team.json`
  - `templates/workspace/AGENTS.md`
  - `templates/workspace/PROJECT.md`
  - `templates/characters/` (기본 캐릭터 1종)
  - `templates/secrets.env.example`

### 2단계: 데이터 이전 도구 (`tools/migrate_user_data.py`)
- 기존 `services/chatbot/data` → 목표 `$CHATBOT_DATA`(예: `~/.pe` 또는 지정 위치)로 복사/이동.
- 멱등성: 이미 복사된 파일은 건너뛰며, 원본은 백업 디렉토리에 보존.
- 심볼릭 링크 모드(개발 호환: `data` → `~/.pe` 옵션).

구현: `tools/migrate_user_data.py`는 기본이 미리보기다. `--apply`만 복사하고, 목적지에 파일이 있으면 `--force` 없이 거절한다. 내용이 다른 파일은 덮어쓰지 않는다. `--remove-source`는 목적지와 바이트가 같은 원본만 지우며, 하나라도 다르면 아무것도 지우지 않는다. `--keep-tracked`는 git에 있는 파일은 원본 자리에 남긴다.

### 3단계: 코드·ctl 경로 정리
- `server.py`, `mcp_server.py`, `memory_store.py`, `delegation.py` 등 `"data/"` 하드코딩 → `host_config.DATA`.
- **`chatbot-ctl.sh` `DATA="$CODE/data"` 제거** 및 env/기본값 체계 적용.

### 4단계: 실제 이전 및 서비스 검증
- 실장님 승인 하에 `python3 tools/migrate_user_data.py` 실행.
- 서비스 재기동(소생) 후 정상 세션, 기억, 캐릭터 로드 확인.

### 5단계: 저장소 정리 및 원격 히스토리 가드
- `.gitignore`에 `data/` 전면 추가.
- 커밋 전 검사(개인정보·비밀 패턴).
- *(원격 히스토리 재작성은 실장님 별도 판단)*

---

## 5. 영향 및 리스크 평가

- **호스트 소생 필요**: `host_config.py`·ctl 경로 변경 시 **⚡소생** 필요.
- **기존 세션/기억 연속성**: 이전 후 심볼릭 링크(`data` → `~/.pe`) 임시 유지 가능.
- **개발 워크플로**: NAS/FIREBAT는 전환 전까지 `CHATBOT_DATA=$CODE/data` 유지. 기본값만 `~/.pe`로 바꿔도 ctl/문서가 따라가지 않으면 깨짐 — ctl·migrate·gitignore를 한 묶음으로.
- **교차**: 배포 일정·CI·런처는 [release-pipeline.md](release-pipeline.md).
