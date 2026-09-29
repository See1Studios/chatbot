# 플랫폼 이식성 — NAS 밖, OS마다 도는 엔진

> 방향 (align/D, 2026-09-29): **기반** — 배포판은 사용자 PC에서 돈다. Steam 1차 대상은 Windows인데 엔진은 지금 NAS(Linux, Python 3.8)에서만 검증됐다

> 상태: **active** (2026-09-29 초안)
> 목적: OS 전용 기능 의존을 재고, 더 늘지 않게 막고, 한 곳으로 모은 뒤, Windows·macOS·Linux에서 자동·실기로 확인한다.
> 관련: [release-pipeline.md](release-pipeline.md)(최소 CI·런처·인스톨러) · [user-data-separation.md](user-data-separation.md) §3.4(OS별 데이터 폴더) · [edition-boundary.md](edition-boundary.md)(배포판 범위) · [ux-shell-roadmap.md](ux-shell-roadmap.md) `ux/G`(Windows 투명 창 스파이크) · 아카이브 `chatbot-host-portability.md`(호스트 경로 분리, 완료)

## 1. 운영자 질문 (2026-09-29)

"우리 계획에 이 NAS 말고 다른 시스템에 배포해서 OS 별 호환성 체크하는 게 있던가? 말하자면 시스템 아키텍쳐 독립성 확보?" → 없음을 확인하고 이 계획 제안 → "그래".

## 2. 현황

- 계획에 있는 조각: OS별 데이터 폴더 경로(user-data-separation §3.4), "최소 CI(테스트+린트)"(release-pipeline Next, OS 미정), OS별 인스톨러(브랜드 이후), 호스트 이름·NAS 경로 래칫(`align/E`). **OS 기능 의존을 재거나 막는 장치, 다른 OS에서 돌려 보는 절차는 없다.**
- 엔진 코드의 OS 전용 기능 사용 (2026-09-29 `grep`, 테스트 제외):

| 기능 | 파일 | 막히는 곳 |
|---|---|---|
| `fcntl` 파일 잠금 | 3 (`obslog.py`, `evolution.py`, `providers/account_login.py`) | Windows에 없음 |
| `/proc/` 읽기 | 4 (`ctl_proc.py`, `obslog.py`, `tools/ticket_quick.py`, `providers/accounts.py`) | Linux 전용 |
| `setsid`·`start_new_session` | 5 (`server.py`, `delegation.py`, `session.py`, `providers/adapter_codex.py`, …) | POSIX 전용 |
| `killpg`·`SIGKILL`·`SIGTERM` | 8 (`mcp_server.py`, `evolution.py`, `session.py`, `server.py`, …) | Windows에서 다르게 동작 |
| `bash`/`sh` 호출 | 7 (`mcp_server.py`, `server.py`, `nas_mcp_host.py`, `tools/ticket_quick.py`, …) + `chatbot-ctl.sh`·`run-tests.sh` | Windows 기본 환경에 없음 |

- 이 NAS: x86_64, Python 3.8.15. CPU 아키텍처 자체는 Python이라 큰 문제가 아니고, 네이티브 패키지(Pillow 등)는 CI에서 같이 확인된다.
- 실기: 다른 방 **FIREBAT**(Windows 11 Pro, Ryzen 7, SSH `ssh firebat`, 스킬 `firebat`)을 쓸 수 있다.

## 3. 설계

### 3.1 대상

| OS | 순위 | 이유 |
|---|---|---|
| Windows x64 | 1 | Steam 1차, 데스크톱 캐릭터(`ux/G`) |
| macOS (arm64, Intel은 universal2로) | 2 — **반드시 포함** (운영자 2026-09-29 "macos까지 고려해야") | 개발자·크리에이터 사용자. POSIX라 `pty`·`fcntl`·`setsid`는 되지만 `/proc`이 없고(`ctl_proc.py`·`accounts.py`), 기본 셸이 zsh·bash 3.2, 바이너리 배포에 **서명·공증**이 필요(PP4). 테스트 기계가 없으니 CI의 macOS 러너가 주 확인 수단 |
| Linux x64 | 3 | 지금의 개발 환경, 서버형 설치 |
| **Steam Deck**(SteamOS, Linux x64) | 후보 (운영자 2026-09-29) | Steam 배포라면 Deck 호환 표시(Verified/Playable)가 노출에 직결. 두 길: ① Windows 빌드를 Proton으로 ② 네이티브 Linux 빌드. 엔진이 Linux에서 이미 돌므로 ②가 자연스럽지만, 두뇌 CLI(agy·claude 등)가 SteamOS 읽기 전용 루트·게임 모드에서 설치·로그인되는지가 관건(DK1) |

Python 하한은 배포 방식과 함께 정한다(PP1).

### 3.2 래칫: 늘지 못하게

`align/E`와 같은 방식. 위 표의 기능마다 파일별 줄 수를 기준선으로 두고, 늘면 실패, 줄면 기준선을 낮춘다. 의도한 줄(`platform_compat` 안의 OS별 구현)은 표시로 뺀다.

### 3.3 한 곳으로: `platform_compat`

파일 잠금, 프로세스 트리 종료, 살아 있는지 확인, 떼어 낸 실행(detached spawn), 프로세스 정보 읽기를 한 모듈의 함수로. OS별 구현은 그 안에만. 나머지 코드는 이 함수만 부른다(캐릭터 외형 어댑터와 같은 발상). 옮길 때마다 래칫 기준선이 내려간다.

### 3.4 확인: 자동(CI)과 실기

- **CI**: GitHub Actions에서 Windows·macOS·Linux 각각 테스트 전체. node가 필요한 화면 테스트는 node를 설치해서. 처음에는 Windows 실패가 많을 것 — 실패 목록이 곧 할 일 목록이고, "알려진 실패" 목록을 줄여 가는 래칫으로 운영한다.
- **실기(FIREBAT)**: CI가 못 잡는 것 — 설치, 경로(공백·한글), 콘솔 인코딩, 두뇌 CLI(agy·claude)가 Windows에서 실제로 뜨는지, 방화벽. 체크리스트 한 장으로 단계마다 한 번.

### 3.5 관리 스크립트

배포판은 bash `chatbot-ctl.sh` 대신 Python 런처(시작·중지·상태·재시작). release-pipeline의 런처 항목과 합친다. 개발판 NAS는 당분간 `chatbot-ctl.sh` 유지.

## 4. 결정 (운영자 확인 필요)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| PP1 | Python 배포 | 인스톨러가 Python을 같이 넣는다(사용자 PC의 Python에 기대지 않음). 하한은 그 번들 버전, 개발 NAS 3.8은 개발판 전용 | 대기 |
| PP2 | 대상 순위 | 3.1 표 | 대기 |
| DK1 | 스팀덱 빌드 | 네이티브 Linux 빌드 + 두뇌는 API 키·OAuth 경로 우선(게임 모드에서 CLI 로그인이 어려울 수 있음). Proton은 대안. `pp/C`처럼 실기 실측 뒤 확정 | 대기 |
| PP4 | 배포 형태 (운영자 2026-09-29 "사용자가 건드리면 안 되는 것들은 다 binary로") | **OS별 Nuitka 바이너리**(Python → C 컴파일: 되읽기 어렵고, 시작이 빠르고, Apache 라이선스). 사용자·에이전트가 바꾸는 것은 `~/.pe`(캐릭터·기억·스킬·플러그인)뿐 — edition-boundary를 물리적 경계로. 대안 PyInstaller(쉽지만 풀면 코드가 거의 그대로). 한계: 보안 장치가 아니라 "실수로 망가뜨리지 않게, 쉽게 복제되지 않게"; 화면(HTML·JS·CSS)은 실행 파일 안 리소스로 묶는 정도; 두뇌 CLI는 사용자가 따로 설치. OS별 조건 — Windows: 코드 서명 없으면 SmartScreen 경고. **macOS: Apple Developer ID 서명 + 공증(notarization) 없으면 Gatekeeper가 실행을 막음**, arm64·x86_64 둘 다(universal2 또는 두 빌드). Linux·스팀덱: 한 파일 또는 Flatpak(DK1과 함께). **배포판은 Python UTF-8 모드로 실행**(한국어 Windows의 기본 인코딩은 cp949 — #401). 빌드는 CI 매트릭스(`pp/F`)에서 테스트와 같이 | **결정** (방향, 2026-09-29 운영자) — 도구 확정은 `pp/K` 시험 뒤 |
| PP5 | 자기 진화 핵심(`core_modules.json`)에 `platform_compat` 포함? | 포함 추천: 잠금 코드가 `evolution.acquire_lock`과 `platform_compat` 두 곳에 생겼다(#397). 포함하면 한 곳으로. 파일이 운영자 소유라 운영자 결정 | **결정** (2026-09-29 운영자: 추천대로) — #398에서 `core_modules.json`에 추가, `evolution.acquire_lock`이 `platform_compat.lock_file`을 씀, 래칫 49 → 47 |
| PP3 | CI 위치 | GitHub Actions. Linux는 main push마다, Windows·macOS(분당 요금 2배·10배)는 **하루 한 번(main이 바뀐 날)과 수동 실행** | **결정** (2026-09-29 운영자: 추천대로) — `.github/workflows/tests.yml` (#416) |

## 5. 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `pp/A` | 이 문서 + INDEX 행 | 이 문서, `docs/plans/INDEX.md` | 커밋 | 0 · — | S | — | ✅ #394 |
| `pp/B` | OS 전용 기능 래칫 | `tests/test_ratchets.py`, 기준선 파일 | 표의 기능이 새로 늘면 실패, 줄면 기준선 낮춤 | 2 · — | S | — | ✅ #394 (13개 파일 52줄) |
| `pp/C` | FIREBAT 실측 1차(읽기만): Python·git·node·두뇌 CLI 유무와 버전, 저장소 사본에서 테스트 전체를 돌려 실패 목록 | 이 문서 §6 | 실패 목록과 원인 분류 | 0 · — | S | — | ✅ #394 (§6.1: 93/143) |
| `pp/D` | `platform_compat` 모듈 + 첫 이전(파일 잠금) — 첫 수로 `pty` import 이전 ✅ #395 | 새 모듈, `obslog.py`, `evolution.py` | Windows에서 잠금 테스트 통과, 래칫 기준선 하락 | 3 · ⚡ | M | pp/B, pp/C | 대기 |
| `pp/E` | 프로세스 관리 이전(종료·생존·분리 실행) | `session.py`, `server.py`, `delegation.py` 등 | 같음 | 3 · ⚡ | M | pp/D | 대기 |
| `pp/F` | CI 매트릭스(Windows·macOS·Linux) + 알려진 실패 래칫 | `.github/workflows/` | 세 OS에서 돌고, 알려진 실패 목록이 늘지 않음 | 2 · — | M | PP3 | 워크플로 작성 #416 — **push 대기**: 로컬 main이 GitHub보다 717커밋 앞서고 15커밋 뒤처짐(9/22~23 배달용 패치 파일들, 내용은 이미 로컬에 있음). 알려진 실패 래칫은 첫 실행 결과를 보고 |
| `pp/G` | Python 런처(배포판 시작·중지·상태) | 새 파일, release-pipeline과 합침 | Windows에서 런처로 켜고 대화 1턴 | 2 · — | M | pp/E, PP1 | 대기 |
| `pp/I` | 스팀덱 실측(실기 또는 SteamOS VM): 데스크톱 모드·게임 모드에서 설치, 두뇌 연결, 화면 1280×800, 게임패드·화상 키보드 | 이 문서 §6 | 실측 기록과 DK1 결정 근거 | 0 · — | S | pp/G | 대기 |
| `pp/J` ✅ #396 | 의존성 선언: Pillow(NAS 10.4.0, 하한은 3.8·3.12 둘 다 되는 버전)를 `requirements.txt`에, 새 가상환경에서 `import` 전수 검사하는 테스트 | `requirements.txt`, 테스트 | 빈 가상환경 + requirements만으로 엔진 모듈 전부 import | 2 · — | S | — | 대기 |
| `pp/K` | 바이너리 빌드 시험(PP4): Nuitka로 서버 하나를 Windows(FIREBAT)·Linux에서 빌드해 켜고 대화 1턴, 크기·시작 시간·빠진 리소스 기록. macOS는 CI 러너에서 빌드만 + 서명·공증 절차 조사 | 새 빌드 스크립트, 이 문서 §6 | 두 OS에서 바이너리로 1턴, macOS 빌드 성공, 서명 절차 메모 | 2 · — | M | pp/E, pp/J | 대기 |
| `pp/L` | 필터링 프로그램(AdGuard 등)과의 공존: 브라우저 ↔ PE를 AdGuard 켠 채 FIREBAT에서 확인, 재현되면 화면 요청 재시도(멱등만)·오류 안내·설치 안내 | `static/`(요청 공통부), 안내 문서 | AdGuard 켠 FIREBAT에서 대화·결정 버튼이 실패 없이 동작하거나 분명한 안내 | 2 · — | S | — | 대기 |
| `pp/H` | FIREBAT 실기 체크리스트(설치 → 대화 → 두뇌 연결) | 이 문서 | 체크리스트 전 항목 통과 기록 | 0 · — | S | pp/G | 대기 |

## 6. 실측 기록

### 6.1 FIREBAT 1차 (2026-09-29, `pp/C`)

- **기계**: Windows 11 Pro (NT 10.0.26200) AMD64, 콘솔 UTF-8. Python 3.12.10(`python`, `py`; `python3`은 Store 별칭), git 2.55, node v24, **두뇌 CLI 넷 다 있음**: agy 1.2.8(`agy.bat`), claude 2.1.278, codex 0.153.4(`codex.ps1`), grok 1.0.5. `bash`는 WSL 껍데기뿐(배포판 없음) → `run-tests.sh` 불가.
- **방법**: `git archive HEAD -- . ':!data'`(개인 데이터 제외, 코드만) → `%TEMP%\pe-probe`, 그 안 가상환경에 `requirements.txt` 설치, 테스트 모듈 143개를 하나씩 `python -m unittest`. FIREBAT의 기존 Python은 건드리지 않음. 사본은 `%TEMP%\pe-probe`에 남겨 둠(다음 실측에 재사용, 지워도 됨).
- **결과: 93/143 통과, 50 실패.**

| 원인 | 수 | 모듈 | 다음 |
|---|---|---|---|
| **A. 실측 방식 탓**: `data/`를 통째로 빼서 엔진이 추적하는 `data/workspace/AGENTS.md`·`items.json`·`roles/`·`providers.json` 등이 없음 (+ NAS 플러그인은 Linux 전용이 설계) | 13 | bundle_budget, code_layout, dev_role, entrypoints, identity, items, memory_cli, providers_config, providers_json, rule_registry, team_roles, workspace_template, nas_mcp_host | 2차는 추적 파일만 포함(개인 파일 제외 목록으로). 엔진 파일이 `data/` 아래 있는 것 자체가 user-data-separation의 과제 |
| **B. 선언 안 된 의존성**: `PIL`(Pillow)이 `requirements.txt`에 없음. NAS엔 따로 깔려 있어(10.4.0) 몰랐다 — **어느 OS든 새 설치에서 깨진다** | 1 | character_art_fallback | `pp/J` |
| **C. POSIX 전용 import**: `providers/account_login.py`가 맨 위에서 `import pty`(안에서 `termios`) → **`server.py`가 Windows에서 불러와지지 않음**, 서버를 부르는 테스트가 모두 실패. 그 밖에 `/proc` 읽기 | 16 | account_login, accounts, auto_recycle, character_picker, file_links, file_preview_guard, host_api_guards, identity_wiring, observation_api, persona_traversal, provider_neutrality, restart_notice, service_log, session_split, st_import_api, ticket_api | `pp/D`·`pp/E` — 첫 수는 `pty`를 쓰는 함수 안으로 옮기기(한 줄로 16개가 풀릴 가능성) |
| **D. 경로 구분자**: `\tmp` vs `/tmp`, `references\a.md` vs `references/a.md` — 화면·에이전트로 가는 경로는 `/`로 통일해야 | 3 | data_paths, mcp_parity_tools, media_sources | `pp/E`와 함께 |
| **E. 인코딩**: 자식 프로세스 출력을 UTF-8로 읽다 cp949 바이트에서 실패 | 3 | ctl_paths, lifecycle, log_no_content | `subprocess`에 `encoding`/`errors` 지정 |
| **F. 파일 권한 비트**: 0o700/0o600을 기대했는데 Windows는 0o777/0o666 | 2 | data_bootstrap, ticket_quick | 비밀 파일 보호를 Windows에서는 ACL로 — 결정 필요 |
| **G. 파일 잠금 의미 차이**: 열린 파일을 지우거나 바꾸려다 `WinError 32`(다른 프로세스가 사용 중) | 1 | tickets | `platform_compat` 잠금·교체 |
| **H. 셸 스크립트**: git 훅(bash), MCP의 `chatbot-ctl.sh` 허용 목록 | 2 | githooks, mcp_server | 개발판 전용으로 표시하거나 런처(`pp/G`)로 |
| **I. 줄바꿈·텍스트**: 파일 크기 2088 > 2048(쓸 때 `\n`→`\r\n` 추정), 문자열 비교 불일치 | 2 | characters, private_tension | `write_text(newline="\n")` 규칙 |
| **J. 아직 분류 안 됨** | 7 | core_standalone, evolution, memory_store, models_meta_cache, obslog, st_import, worktree_runner | 2차 실측에서 트레이스백 확인 |

- **래칫(`pp/B`)**: POSIX 전용 호출 + `pty`·`termios` 같은 import까지 기준선 **13개 파일 52줄**.
- **한 줄 결론**: 코드 자체의 OS 의존은 생각보다 적고 몇 군데에 몰려 있다(C가 16/50). 가장 싼 첫 수는 `account_login.py`의 `pty` import를 함수 안으로 옮기는 것, 그다음이 Pillow 선언.

### 6.2 `pty` import 이전 뒤 (2026-09-29, #395)

- `import pty`를 로그인을 띄우는 `_spawn()` 안으로. Windows에서는 그 기능만 명확한 메시지로 실패한다(대화형 로그인의 Windows 대체는 `pp/E`: ConPTY/`pywinpty`(MIT) 또는 CLI의 브라우저 로그인).
- 재발 방지: `tests/test_platform_imports.py` — 엔진 모듈이 모듈 맨 위에서 POSIX 전용 모듈(`pty`·`termios`·`fcntl`·…)을 try 없이 불러오면 실패.
- FIREBAT 재확인: **`server.py`가 Windows에서 처음으로 import됨.** C 분류 16개 중 **9개 통과**, 남은 7개(accounts, host_api_guards, identity_wiring, observation_api, service_log, st_import_api, ticket_api)는 import가 아니라 더 안쪽 원인(`/proc`, 그림 변환, 경로 등) — 2차 실측에서 분류.
- 참고: 운영자가 제안한 termiWin(veeso/termiWin)은 **시리얼 포트(COM)**용 `termios` 이식이고, 보관된 저장소·GPL-3.0이라 우리 용도(CLI 대화형 로그인의 가짜 터미널)와 맞지 않음.

### 6.3 Pillow 선언 뒤 남은 실패 분류 (2026-09-29, #396)

- `requirements.txt`에 `Pillow>=10.4`(3.8과 3.12 둘 다 되는 하한). `tests/test_platform_imports.py`에 선언 검사 추가: 엔진 코드가 쓰는 외부 패키지가 `requirements.txt`에 없으면 실패. 엔진 코드의 외부 패키지는 **Pillow 하나**. PyYAML은 엔진 `.py`에서 import하는 곳이 없음(스킬 스크립트 등 다른 쓰임 확인 전까지 유지).
- FIREBAT에서 남은 15개 재실행: **4개 통과**(character_art_fallback, service_log, obslog, st_import).

| 원인 | 모듈 | 다음 |
|---|---|---|
| **K. 서버 HTTP 테스트가 연결 강제 종료(`WinError 10054`)** — 테스트 서버가 요청 처리 중 안쪽에서 죽는 것으로 보임(서버 쪽 트레이스백 미확인) | host_api_guards, observation_api, st_import_api, ticket_api | 서버 스레드의 예외를 테스트 출력으로 끌어내 원인 확인 |
| C. `/proc` | accounts (`providers/accounts.py::_scan_procs`) | `platform_compat` 프로세스 목록(`pp/D` 다음 수) |
| G. 권한·사용 중 파일(`PermissionError 13`) | evolution, memory_store | `platform_compat` 잠금·교체, 권한 비트 규칙(F와 함께) |
| H. 테스트의 `sh -c` 가짜 두뇌 | worktree_runner | 개발판 전용(위임 러너) — Windows 대상에서 빼거나 가짜 두뇌를 Python으로 |
| A. 실측에서 뺀 데이터(역할 팩) | identity_wiring | 2차 실측 방식 |
| 미확인 | core_standalone, models_meta_cache | 트레이스백 전문 확인 |

### 6.4 `platform_compat` 첫 이전 (2026-09-29, #397)

- 새 모듈 `platform_compat.py`: 파일 잠금(`lock_file`/`unlock_file` — POSIX `flock`, Windows `msvcrt.locking` 첫 바이트, 둘 다 없으면 건너뜀)과 `has_proc()`. 래칫은 이 파일만 건너뛴다.
- `obslog.py`의 잠금을 이 모듈로. `providers/accounts.py`의 실행 중 CLI 조사는 `/proc`이 없으면(Windows·macOS) 빈 결과 — 죽지 않고 기능만 줄어듦(각 OS의 프로세스 목록 구현은 `pp/E`).
- `evolution.py`는 핵심 모듈이라(운영자 소유 `core_modules.json`: 표준 라이브러리와 서로만) 이 모듈을 부르지 않고, 설계 주석대로 `acquire_lock` 한 함수 안에 Windows(`msvcrt`) 분기를 뒀다. 핵심에 `platform_compat`을 넣을지는 운영자 결정(PP5).
- 래칫 **52 → 49줄**(obslog 5 → 2).
- FIREBAT: `test_platform_compat`(두 프로세스 잠금 경합 포함) 통과. **accounts, memory_store가 새로 통과.** 새로 보인 별개 원인: evolution의 보호 경로 판정(`~/.agents` 아래, Windows 홈 경로), tickets의 운영자 터미널 확인(tty) — 다음 분류 대상.
- 배운 것: Windows 잠금은 **재진입이 안 되고**(같은 손잡이로 두 번 잡으면 실패), 죽은 프로세스의 잠금이 **조금 늦게** 풀린다.

### 6.5 FIREBAT 2차 전체 (2026-09-29, 오늘 수정 모두 반영 뒤)

- **107/145 통과** (1차 93/143). 새로 통과 16: account_login, accounts, auto_recycle, character_art_fallback, character_picker, file_links, file_preview_guard, host_api_guards, memory_store, platform_compat, platform_imports, provider_neutrality, restart_notice, service_log, session_split, st_import.
- 새로 실패 2(art_manager, character_art)는 퇴보가 아니라 **가려져 있던 원인이 드러난 것**(전에는 Pillow가 없어 import에서 멈춤): 경로 구분자, 실측에서 뺀 스킬 파일.
- HTTP 연결 끊김(K): 단독 실행에서는 `test_ticket_api` 결정 테스트가 5/5 통과, 추적을 붙이면 10번 중 1번 실패 — **드물게 흔들림**이 남음. 전체 실행에서는 observation_api·st_import_api·ticket_api가 여전히 실패(원인 줄 없음) → 다음 조사.
- 남은 38개 원인별:

| 원인 | 수 | 모듈 |
|---|---|---|
| A. 실측에서 뺀 추적 데이터(`data/workspace/…`, `providers.json`) + NAS 플러그인 | 15 | bundle_budget, character_art, code_layout, dev_role, entrypoints, identity, identity_wiring, items, memory_cli, nas_mcp_host, providers_config, providers_json, rule_registry, team_roles, workspace_template |
| D. 경로 구분자(`\` vs `/`) | 4 | art_manager, data_paths, mcp_parity_tools, media_sources |
| E. 자식 프로세스 출력 인코딩(cp949 바이트를 UTF-8로) | 4 | ctl_paths, lifecycle, log_no_content, tickets |
| H. 셸(bash 훅, `chatbot-ctl.sh`, `sh -c` 가짜 두뇌) | 3 | githooks, mcp_server, worktree_runner |
| F. 권한 비트 | 2 | data_bootstrap, ticket_quick |
| I. 줄바꿈·텍스트 | 2 | characters, private_tension |
| K·미확인(원인 줄 없음 포함) | 8 | core_standalone, evolution, models_meta_cache, observation_api, obslog, persona_traversal, st_import_api, ticket_api |

- **다음 수(싼 순서)**: A는 실측 방식만 바꾸면 되는 가짜 실패라 먼저 없앤다(추적 파일 포함 + 개인 파일 제외 목록). 그다음 D·E·I는 규칙 하나씩(경로는 `as_posix()`, 자식 출력은 `encoding`/`errors` 지정, 쓰기는 `newline="\n"`)이라 각각 래칫으로 막을 수 있다.

### 6.6 FIREBAT 3·4차 (2026-09-29, #401·#403)

- **실측 방식 변경**: 사본에 엔진이 추적하는 `data/` 파일은 넣고 개인 기록(캐릭터 폴더, 개선 기록, 페르소나 그림)은 뺀다(`git archive HEAD -- . ':!data/workspace/characters' ':!data/workspace/skill-observations' ':!data/persona'`). 실행은 새 도구 `tools/run_modules.py`(bash 없이 모듈별, FAST 목록은 `run-tests.sh`에서 읽음).
- **3차에서 드러난 것**: UTF-8 모드를 강제하지 않자 **한국어 Windows는 인코딩 없는 파일 읽기·쓰기를 cp949로 한다**는 게 보였다(1·2차는 UTF-8 모드를 켜 둬서 가려짐). 엔진의 13곳에 `encoding="utf-8"`, 새로 생기면 실패하는 검사, 배포판은 UTF-8 모드로(PP4). 테스트는 배포판과 같은 UTF-8 모드로 돈다. 3차는 러너 자체가 cp949 콘솔 출력에서 멈춰 중단 → 고침.
- **4차: 121/146** (2차 107/145). 그 뒤 경로 수정(#403: `as_posix()` 6곳, 산출물 경로 재작성이 양쪽 구분자 인식)으로 art_manager·data_paths·mcp_parity_tools·media_sources 4개가 더 풀릴 것으로 보임(5차에서 확인).
- **남은 원인 (4차 기준, 경로 4개 제외 21개)**:

| 원인 | 모듈 | 메모 |
|---|---|---|
| **대소문자를 가리지 않는 파일 시스템** (새로 드러남) | team_roles (`ROLE.md` vs `role.md`) | Windows NTFS와 **macOS 기본 APFS도 대소문자 무시** — 역할 팩 파일 이름 규칙을 한 가지로 |
| 서버 HTTP 연결 끊김(K) | observation_api, obslog, ticket_api | 전체 실행에서 재현, 단독으로는 대개 통과 — 테스트 서버 종료·재시작 사이 경합 의심 |
| bash·셸 의존(H) — 자식 출력 디코딩 실패 포함 | ctl_paths, lifecycle, log_no_content, tickets, githooks, mcp_server, worktree_runner | `bash`가 WSL 껍데기라 cp949 메시지를 냄. 개발판 전용(관리 스크립트·훅·위임 러너)이면 Windows 대상에서 제외 표시, 엔진 경로면 Python으로 |
| 권한 비트(F) | data_bootstrap, ticket_quick | Windows 비밀 파일 보호 방식 결정 필요 |
| 줄바꿈·텍스트(I) | characters, private_tension | `newline="\n"` 규칙 |
| 개인 기록을 뺀 탓(A) | bundle_budget, code_layout, identity_wiring | 테스트가 개인 기록 폴더를 전제 — 테스트가 스스로 만들도록 |
| NAS 전용 | nas_mcp_host | 설계상 Linux |
| 미확인 | core_standalone, evolution | 트레이스백 확인 |

### 6.7 대소문자·줄바꿈 규칙 (2026-09-29, #405)

- **대소문자**: `platform_compat.named_file(폴더, 이름들)` — 폴더 항목과 정확히 비교해 디스크에 적힌 그대로의 이름을 돌려준다. 역할 팩 파일(`ROLE.md`/`role.md`) 찾기가 이것을 쓴다.
- **줄바꿈**: `platform_compat.write_text()` — 모든 OS에서 `\n`으로 쓴다(Python 3.8의 `Path.write_text`에는 `newline=`이 없음). 엔진의 텍스트 쓰기 28곳을 옮기고, 추가 쓰기 `open` 8곳에 `newline="\n"`. `session.py`의 두 곳은 이미 쓰던 `_atomic_write_text`로(줄 수 상한 유지).
- 재발 방지: `test_platform_imports`에 줄바꿈 검사(개발판 전용 도구 둘은 예외). 핵심 모듈 세 곳의 import 허용 목록에 `platform_compat`(PP5 후속).

### 6.8 개발판 bash 도구 테스트 표시 (2026-09-29, #407)

- `tests/_platform.py`의 `dev_only_bash`: POSIX + bash가 있을 때만 돌고, 아니면 "개발판 bash 도구"라는 이유로 건너뜀. Windows의 `bash.exe`는 WSL 껍데기라 `which("bash")`만으로는 안 되고 OS도 본다.
- 붙인 곳(모두 배포판에 없는 개발판 도구): githooks 전체, lifecycle의 `WrapperTest`·`RealCtlTest`(관리 스크립트 — 잠금 등 나머지는 그대로 돈다), ctl_paths 전체, log_no_content의 관리 스크립트 테스트 2개, tickets의 `run-tests.sh` 가드 게이트 테스트 2개, mcp_server의 `RunCommandTest`·`ServiceCtlTest`(명령 실행 도구), worktree_runner 전체(위임 실행기).

### 6.9 FIREBAT 5차와 HTTP 연결 끊김의 정체 (2026-09-29, #409)

- **5차: 129/146** (4차 121). 남은 17개 중 4개가 HTTP 연결 끊김(`WinError 10054`).
- 조사 순서: ① 포트 재사용 가설(Windows의 `SO_REUSEADDR`는 두 소켓이 같은 포트를 공유하게 함) → 서버를 독점 바인딩(`SO_EXCLUSIVEADDRUSE`)으로 바꿨으나 **끊김 그대로 — 가설 틀림**. ② 서버는 매번 200을 보내는데 클라이언트가 약 25% 리셋을 받음. ③ 우리 핸들러 대신 최소 핸들러: 즉시 응답이면 120/120 정상, **30ms 지연만 넣어도 40% 리셋**. ④ HTTP 모듈 없이 **순수 소켓**으로도 지연 0에서 10%, 30ms에서 40% 리셋.
- **결론: FIREBAT의 로컬(루프백) 연결 자체가 리셋된다** — 우리 코드도 Python도 아니다. **.NET(`TcpListener`/`TcpClient`)으로도 같은 리셋**(지연 0ms 1/30, 30ms 7/30, 200ms 6/30) → Windows 네트워크 스택 쪽.
- **유력 원인: AdGuard** (2026-09-29, 읽기 전용 조사). WFP 필터 1132개 중 제3자는 AdGuard뿐 — 전송 계층 스트림 콜아웃(`FWP_ACTION_CALLOUT_TERMINATING`), 연결 가로채기(`ALE_CONNECT_REDIRECT`), 흐름 수립·종료(`ALE_FLOW_ESTABLISHED`, `ALE_ENDPOINT_CLOSURE`) 콜아웃. 연결을 가로채 필터링하는 방식이라 루프백의 종료 과정에 끼어들 수 있다. 그 밖에 Tailscale, Sunshine, Windows Defender(네트워크 보호 꺼짐), Hyper-V 중첩 가상화 필터가 있으나 루프백 WFP 필터는 없음. **확정 (2026-09-29, 운영자가 AdGuard를 잠시 끔)**: .NET 루프백 실험이 지연 0·30·200ms 모두 **30/30 정상(리셋 0)**, 서버 HTTP 테스트 8개 중 7개 통과(남은 1개 identity_wiring은 실측에서 뺀 캐릭터 데이터 탓). **원인은 AdGuard의 연결 가로채기 필터.**
- **제품 위험**: AdGuard 같은 연결 가로채기 필터(광고 차단·보안 프로그램)가 깔린 사용자 PC에서도 브라우저 ↔ PE 서버 연결이 가끔 끊길 수 있다. 브라우저는 GET을 다시 시도하지만 POST는 아니다 → 화면의 POST 호출에 재시도(멱등한 것만)나 오류 안내가 필요할 수 있음. 깨끗한 Windows(CI 러너)에서 재현되는지로 확인한다(`pp/F`).
- **다음 수 (`pp/L`)**: ① 사용자 PC에서 브라우저 ↔ PE 서버를 AdGuard 켠 채로 확인(FIREBAT, 브라우저가 실제 경로 — 이번 실험은 Python ↔ Python이었다) ② 문제가 재현되면: 화면의 요청이 연결 리셋을 만나면 다시 시도(멱등한 요청만)하거나 분명히 알리고, 안내 문서에 "AdGuard 등 필터링 프로그램에서 PE를 예외로" 한 줄. 인스톨러 단계에서 흔한 필터링 프로그램 감지·안내 검토.
- 포트 독점 바인딩(`platform_compat.http_server`)은 이 문제를 풀지는 못했지만 유지: Windows에서 다른 프로그램이 우리 포트에 함께 붙는 것을 막는다(로컬 보안).

### 6.10 남은 Windows 실패 정리 (2026-09-29, #411)

- **엔진 버그 1건**: `evolution.run_locked`(핵심 모듈, 관리 잠금 실행)가 `signal.SIGHUP`을 무조건 등록 — Windows에는 없어 함수가 곧바로 죽었다. 이 OS에 있는 신호만 등록하고, 자식에게 전달할 수 없는 신호는 종료 요청으로 대신.
- **테스트의 POSIX 가정**: ① 홈 폴더를 `HOME`으로만 옮김 — Windows의 Python은 `USERPROFILE`을 본다(`tests/_platform.home_env`). 환경을 거의 비우는 `core_standalone`은 홈을 못 찾아 보호 판정이 "전부 보호"로 떨어졌었다(엔진 판정은 정상). ② 잠금 실행 테스트가 `sh -c` — Python 명령으로. ③ 권한 비트 검사는 POSIX에서만(Windows는 사용자 프로필 ACL). ④ 경로 문자열 비교는 OS 표기로. ⑤ 대소문자 무시 디스크에서 `ROLE.md` 쓰고 `role.md` 지우면 같은 파일 — 순서를 바꿈. ⑥ 디렉터리 심볼릭 링크는 Windows에서 권한이 필요 — 없으면 건너뜀. ⑦ 부모 PID 표식 검사는 POSIX에서만(Windows 가상환경의 `python.exe`는 중계 프로그램).
- **POSIX 전용 표시(`posix_only`)**: NAS 호스트 플러그인 상태 검사, 티켓 CLI의 `/dev/tty` 운영자 확인.
- FIREBAT에서 10개 모듈 재실행 → 모두 통과. **남은 Windows 실패**: 개인 기록을 뺀 실측 탓 2개(bundle_budget, code_layout), 원인 미확인 1개(private_tension), FIREBAT 네트워크 환경의 HTTP 리셋 4개(§6.9).
- 열린 결정: Windows에서 비밀 파일(토큰·데이터 폴더) 보호를 ACL로 명시할지 — 지금은 사용자 프로필 폴더의 기본 ACL에 기댄다.
