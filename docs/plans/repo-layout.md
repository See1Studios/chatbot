# 저장소 배치 (루트에는 진입·개발 지침과 폴더만)

> 방향 (align/D, 2026-10-08): **개발 기반** — 누가 개발하든 루트에서 길을 잃지 않게. 에이전트가 처음 보는 곳을 작게 유지해 토큰도 아낀다

> 상태: **active** (초안 2026-10-08)
> 목적: 저장소 루트에는 진입 파일(`AGENTS.md`·`CLAUDE.md`·`GEMINI.md`), 에이전트가 늘 읽는 문서(지침과 프로젝트 문서), 그리고 폴더만 둔다. `docs/`에는 폴더만. 루트에 평평하게 깔린 코드를 폴더로 옮긴다.
> 관련: [plan-execution-workflow.md](plan-execution-workflow.md) §3(진입과 정본 배치, pew/S) · [archive/2026/monolith-split.md](archive/2026/monolith-split.md)(크기 분할 완료, 폴더 재배치는 보류로 남았던 것을 이 계획이 잇는다) · [edition-boundary.md](edition-boundary.md)(배포 제외 목록) · [platform-portability.md](platform-portability.md)
> 약칭: `layout`

---

## 1. 범위 / 비목표

- 범위: 저장소 루트의 파일 배치, 코드 폴더, 그에 따라 바뀌는 경로(실행 스크립트, 보호 경로, 테스트 범위, 러너·훅, 루트 계산).
- 비목표: 모듈 내용 변경, 크기 분할(monolith-split에서 끝남), 사용자 데이터 위치(`~/.pe`, user-data-separation).

## 2. 현황 점검 (2026-10-08)

| 확인 | 결과 |
|---|---|
| 문서 | ✅ pew/S(#774): 루트 문서는 `AGENTS.md`·`CLAUDE.md`·`GEMINI.md`·`RULES.md`·`CODEMAP.md`만. 나머지는 `docs/`. `test_entrypoints`가 지킨다 |
| 루트 파이썬 | 68개(`providers/` 10, `tools/` 16은 이미 폴더) |
| 루트의 그 밖의 파일 | 설정 `bundle_budget.json`·`core_modules.json`·`observation_signals.json`·`protected_paths.json`·`ratchet_baseline.json`, 스크립트 `chatbot-ctl.sh`·`run-tests.sh`, `VERSION`·`requirements.txt`·`secrets.env.example` |
| 루트를 스스로 계산하는 파일(`Path(__file__)`) | 코드 25, 테스트 204 |
| `chatbot-ctl.sh`가 부르는 루트 파이썬 경로 | 11곳(`server.py`, `mcp_server.py`, `evolution.py` 등) |
| 루트 파이썬을 가정하는 것 | `protected_paths.json`의 `*.py`, 테스트 18개의 `glob("*.py")`(크기·코드 지도·래칫·중립성·순환 import 등), 위임 러너·훅, `~/services/chatbot-ctl.sh` 래퍼 |
| import 방식 | 평평한 import(`import session`). 실행 스크립트가 같은 폴더에 있으면 폴더를 옮겨도 그대로 동작한다 |

## 3. 결정

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 코드 폴더 이름과 범위 | **`engine/`** 하나에 루트 파이썬 68개 + `providers/` + `tools/`. 이름이 제품 축(엔진)과 맞고, `src/`보다 뜻이 분명하다 | 결정 2026-10-08 (운영자: 추천대로) |
| D2 | import 방식 | **평평한 import 유지**: `engine/`을 실행 위치로 두면 코드 본문은 거의 그대로. 패키지 import(`from engine import ...`)로 바꾸는 것은 따로, 필요해질 때 | 결정 2026-10-08 (운영자: 추천대로) |
| D3 | 루트의 설정·스크립트 | 설정 json 5개와 `VERSION`·`requirements.txt`·`secrets.env.example`은 `engine/`으로(코드가 읽는 것). `run-tests.sh`·`chatbot-ctl.sh`도 `engine/`으로 옮기고, 호스트 래퍼(`~/services/chatbot-ctl.sh`)와 훅만 새 경로를 가리키게. 루트에 남는 것은 진입·개발 지침·폴더·`.git*` | 결정 2026-10-08 (운영자: 추천대로) |
| D4 | `engine/` 안을 영역별로 더 나눌까(코어·세션·팀·운영) | **나중에, 따로**. monolith-split 때 운영자 보류(2026-10-04). 한 번에 한 가지만 움직인다 | 보류 |

## 4. 작업 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `layout/A` | 이 문서 + INDEX 행 | `docs/plans/repo-layout.md`, `docs/plans/INDEX.md` | INDEX 행, 커밋 | 0 · — | S | — | ✅ 티켓 없음(pew D3) |
| `layout/B` | 루트 계산을 한 곳으로: 저장소 루트와 엔진 폴더를 `host_config`(코드)와 테스트 공용 도우미(테스트) 하나에서만 정하고, 229개 파일이 그것을 쓰게. 이동 전에 해 두면 이동은 상수 하나만 바뀐다 | 코드·테스트 다수 | 동작 변화 없이 `./run-tests.sh` 통과, `Path(__file__)`로 루트를 계산하는 곳이 도우미뿐(테스트로 고정) | 3 · ⚡ | M | D1 | ✅ #775 `1f19de3` |
| `layout/C` | 이동: D1·D3대로 `git mv`, `chatbot-ctl.sh`·보호 경로·테스트 범위·러너·훅·래퍼 경로 | 코드 전반 | 루트에 진입·개발 지침·폴더·`.git*`만(테스트), `./run-tests.sh` 통과 | 3 · ⚡ | L → 쪼갬 | layout/B, D1–D3 | ✅ #776 `2ee643c` `31518c8` |
| `layout/D` | 라이브 전환: 운영자 유휴 때 재시작, probe·doctor, 위임 한 번 돌려 보기 | 라이브 | 재시작 후 probe 통과, 위임 러너 한 건 성공 | — · ⚡ | S | layout/C | 재시작·probe 통과(2026-10-08), 호스트 링크·`~/bin/ticket-quick` 갱신, 티켓 완료 관문이 `engine/run-tests.sh`로 돎. 위임 한 건은 다음 위임 때 확인 |
| `layout/F` | 에이전트 지침도 루트로(운영자 2026-10-08: "매번 에이전트가 읽어야 하는 지침들은 저장소 루트로"): `ARCHITECTURE.md`(쉬운 영어로 다시, 있는 것과 계획을 나눔), `OPERATIONS.md`(EMERGENCY + LOGGING), `RULES.md`가 STATE·RELEASE를 흡수, 포인터뿐인 `docs/SELF-MODIFY.md` 삭제. 이어서(운영자: "docs 루트에 있는 것들 모두 저장소 루트로") README·CONCEPT·PRODUCT·DESIGN·HISTORY·CHANGELOG도 루트로, `docs/`에는 폴더만(plans/·providers/·devlog/) | 루트 지침, `docs/`, 참조 | `test_entrypoints`(루트 문서 목록), `test_doc_refs`(새 지침도 검사) 통과 | 3 · — | M | layout/C | ✅ #777 `e1a8958`, #778 `ARCHITECTURE` 내용 복원, #779 |
| `layout/E` | `engine/` 안 영역별 분할 | — | — | 3 · ⚡ | L | D4 | 보류 |

## 5. 의존·순서·리스크

- 순서: D1–D3 결정 → B(루트 계산 정리, 이동 없음) → C(이동) → D(라이브). B를 먼저 하면 C는 기계적인 이동이 된다.
- 리스크: 진행 중인 위임 작업 브랜치와 충돌한다. C는 열린 티켓·위임이 없을 때 한 번에. 라이브는 재시작 때 main 작업 폴더를 그대로 읽으므로, 반쯤 옮긴 상태를 main에 두지 않는다(워크트리에서 끝내고 한 번에 착륙).
- 되돌리기: C는 `git mv`뿐이라 한 커밋 되돌리기로 원상복구된다.
