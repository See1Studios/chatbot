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
| PP4 | 배포 형태 (운영자 2026-09-29 "사용자가 건드리면 안 되는 것들은 다 binary로") | **OS별 Nuitka 바이너리**(Python → C 컴파일: 되읽기 어렵고, 시작이 빠르고, Apache 라이선스). 사용자·에이전트가 바꾸는 것은 `~/.pe`(캐릭터·기억·스킬·플러그인)뿐 — edition-boundary를 물리적 경계로. 대안 PyInstaller(쉽지만 풀면 코드가 거의 그대로). 한계: 보안 장치가 아니라 "실수로 망가뜨리지 않게, 쉽게 복제되지 않게"; 화면(HTML·JS·CSS)은 실행 파일 안 리소스로 묶는 정도; 두뇌 CLI는 사용자가 따로 설치. OS별 조건 — Windows: 코드 서명 없으면 SmartScreen 경고. **macOS: Apple Developer ID 서명 + 공증(notarization) 없으면 Gatekeeper가 실행을 막음**, arm64·x86_64 둘 다(universal2 또는 두 빌드). Linux·스팀덱: 한 파일 또는 Flatpak(DK1과 함께). 빌드는 CI 매트릭스(`pp/F`)에서 테스트와 같이 | **결정** (방향, 2026-09-29 운영자) — 도구 확정은 `pp/K` 시험 뒤 |
| PP5 | 자기 진화 핵심(`core_modules.json`)에 `platform_compat` 포함? | 포함 추천: 잠금 코드가 `evolution.acquire_lock`과 `platform_compat` 두 곳에 생겼다(#397). 포함하면 한 곳으로. 파일이 운영자 소유라 운영자 결정 | **결정** (2026-09-29 운영자: 추천대로) — #398에서 `core_modules.json`에 추가, `evolution.acquire_lock`이 `platform_compat.lock_file`을 씀, 래칫 49 → 47 |
| PP3 | CI 위치 | GitHub Actions(비공개 저장소 무료 한도 안에서, Windows 분은 비싸니 push마다가 아니라 main 병합·수동 실행 때) | 대기 |

## 5. 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `pp/A` | 이 문서 + INDEX 행 | 이 문서, `docs/plans/INDEX.md` | 커밋 | 0 · — | S | — | ✅ #394 |
| `pp/B` | OS 전용 기능 래칫 | `tests/test_ratchets.py`, 기준선 파일 | 표의 기능이 새로 늘면 실패, 줄면 기준선 낮춤 | 2 · — | S | — | ✅ #394 (13개 파일 52줄) |
| `pp/C` | FIREBAT 실측 1차(읽기만): Python·git·node·두뇌 CLI 유무와 버전, 저장소 사본에서 테스트 전체를 돌려 실패 목록 | 이 문서 §6 | 실패 목록과 원인 분류 | 0 · — | S | — | ✅ #394 (§6.1: 93/143) |
| `pp/D` | `platform_compat` 모듈 + 첫 이전(파일 잠금) — 첫 수로 `pty` import 이전 ✅ #395 | 새 모듈, `obslog.py`, `evolution.py` | Windows에서 잠금 테스트 통과, 래칫 기준선 하락 | 3 · ⚡ | M | pp/B, pp/C | 대기 |
| `pp/E` | 프로세스 관리 이전(종료·생존·분리 실행) | `session.py`, `server.py`, `delegation.py` 등 | 같음 | 3 · ⚡ | M | pp/D | 대기 |
| `pp/F` | CI 매트릭스(Windows·macOS·Linux) + 알려진 실패 래칫 | `.github/workflows/` | 세 OS에서 돌고, 알려진 실패 목록이 늘지 않음 | 2 · — | M | PP3 | 대기 |
| `pp/G` | Python 런처(배포판 시작·중지·상태) | 새 파일, release-pipeline과 합침 | Windows에서 런처로 켜고 대화 1턴 | 2 · — | M | pp/E, PP1 | 대기 |
| `pp/I` | 스팀덱 실측(실기 또는 SteamOS VM): 데스크톱 모드·게임 모드에서 설치, 두뇌 연결, 화면 1280×800, 게임패드·화상 키보드 | 이 문서 §6 | 실측 기록과 DK1 결정 근거 | 0 · — | S | pp/G | 대기 |
| `pp/J` ✅ #396 | 의존성 선언: Pillow(NAS 10.4.0, 하한은 3.8·3.12 둘 다 되는 버전)를 `requirements.txt`에, 새 가상환경에서 `import` 전수 검사하는 테스트 | `requirements.txt`, 테스트 | 빈 가상환경 + requirements만으로 엔진 모듈 전부 import | 2 · — | S | — | 대기 |
| `pp/K` | 바이너리 빌드 시험(PP4): Nuitka로 서버 하나를 Windows(FIREBAT)·Linux에서 빌드해 켜고 대화 1턴, 크기·시작 시간·빠진 리소스 기록. macOS는 CI 러너에서 빌드만 + 서명·공증 절차 조사 | 새 빌드 스크립트, 이 문서 §6 | 두 OS에서 바이너리로 1턴, macOS 빌드 성공, 서명 절차 메모 | 2 · — | M | pp/E, pp/J | 대기 |
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
