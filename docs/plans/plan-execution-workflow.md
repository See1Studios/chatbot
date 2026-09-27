# 계획 → 실행 워크플로우 (제품화 기준)

> 방향 (align/D, 2026-09-28): **개발 기반** — 계획→티켓→커밋→릴리스 절차와 관문. 개발판 도구이며 배포판을 만드는 과정의 품질을 지킨다

> 상태: **active** (초안 2026-09-27, 개정 2026-09-27: 누수 방지·강제층 추가, D1–D8 결정, PE 내부 경로 우선)
> 목적: **어떤 에이전트가 들어와도**(작업 대부분은 **PE(챗봇) 안의 에이전트**가 한다 — 외부 CLI는 소수 경로) 같은 입구로 들어오고, 같은 정본을 읽고, 규칙을 어기면 기계가 막는 구조를 만든다. 계획이 티켓·커밋·릴리스까지 끊기지 않고 추적되게 한다. 첫 적용 대상은 제품화 작업([release-pipeline.md](release-pipeline.md), [user-data-separation.md](user-data-separation.md))이다.
> 관련: [INDEX.md](INDEX.md)(계획 상태 SSOT) · [multi-agent-worktree-delegation.md](multi-agent-worktree-delegation.md) §9–10·§13(티켓·PD 실행 경로) · `tickets.py`(티켓 규칙 SSOT)
> 범위: 진입점, 정본 배치, 강제 장치, 계획 → 티켓 이음매, 완료·릴리스 기록. 티켓 엔진·러너·PD 흐름 자체는 바꾸지 않는다.

---

## 0. 원칙: 문서에만 있는 규칙은 없는 규칙이다

누수는 세 층에서 생긴다. 층마다 막는 수단을 둔다.

| 층 | 누수 형태 | 막는 수단 |
|---|---|---|
| **진입** | 에이전트마다 다른 파일을 먼저 읽거나, 아무것도 읽지 않고 시작한다 | 저장소 루트 `AGENTS.md` 하나 + 도구별 포인터 파일. 포인터는 내용을 복제하지 않는다(테스트로 강제) |
| **정본** | 같은 사실이 두 곳에 있다가 한쪽이 낡는다. 문서의 경로·줄 번호가 코드 변경 후 틀어진다 | 사실마다 정본은 한 곳. 문서는 코드를 `path` 또는 `path::symbol`로 가리키고 **줄 번호는 쓰지 않는다**. 참조가 살아 있는지는 테스트로 확인 |
| **강제** | 에이전트가 테스트를 안 돌리거나 규칙을 모른다 | 규칙마다 **집행자**(테스트·훅·게이트)를 둔다. 집행자가 없는 MUST 규칙은 레지스트리 테스트가 실패시킨다(`manual: <사유>` 표시로만 예외) |

강제 지점은 에이전트가 **피할 수 없는 곳**에 둔다. 모든 에이전트는 결국 `git commit`을 하므로 커밋 훅에 둔다. 훅을 우회하는 경우(`--no-verify`)에 대비해 러너 게이트와 이후 CI에도 같은 진입점을 한 번 더 둔다.

오류 메시지는 에이전트용으로 짧고 바로 행동할 수 있게 쓴다(무엇이 틀렸는지 + 어느 파일을 어떻게 고칠지 한 줄).

---

## 1. 왜 필요한가 (2026-09-27 점검에서 나온 증거)

| # | 문제 | 증거 |
|---|---|---|
| P1 | 계획이 코드와 어긋난 채로 착수 직전까지 간다 | user-data-separation 3단계는 `server.py`·`memory_store.py`·`delegation.py`를 대상으로 적었지만, 실제로 `host_config`를 우회하는 곳은 `mcp_server.py`(`DATA =`), `tickets.py::_data_dir`, `content_guard.py`(`TABLE_PATH`), `~/bin/ticket-quick`(`DATA_DIR`) |
| P2 | 계획 문서끼리 모순된다 | 템플릿 경로: §3.3 `templates/team.json`과 §4 `templates/workspace/team.json`. `secrets.env.example` 위치: release는 루트, separation은 `templates/` |
| P3 | Now 표에 이미 있는 것과 목표가 섞여 있다 | release Now의 `VERSION`/`CHANGELOG`/`RELEASE.md`/`run-tests.sh`/`secrets.env.example`는 모두 없는데, 표만 봐서는 알 수 없다 |
| P4 | 계획 항목과 티켓이 연결되지 않는다 | 티켓 253개 중 `docs/plans`를 언급한 티켓은 27개뿐 |
| P5 | 커밋하지 않은 계획 문서가 실행을 막는다 | delegation §13.1-1(#213, `uncommitted leftover`) |
| P6 | 사용자 결정이 계획 본문에 흩어져 있다 | "2026-09-23 사용자 결정"이 delegation §9–12에 흩어져 있어서, 아카이브하면 함께 묻힌다 |
| P7 | 방향 문서가 작업 범위로 새어 들어온다 | concept·숨은 로어는 방향만(운영자 지시, 2026-09-27) |
| P8 | 강제 장치가 없다 | `.git/hooks`에 활성 훅 0개, `core.hooksPath` 미설정, CI 없음. 테스트는 README 루프로만 돌린다 |
| P9 | 코딩 에이전트의 입구가 없다 | 저장소 루트에 `AGENTS.md`·`CLAUDE.md`·`GEMINI.md`가 없다. 헌장과 코드 지도(`PROJECT.md` "Where to edit")는 `data/workspace/` 아래에 있다. 사용자 데이터를 분리하면 **엔진 문서가 저장소 밖으로 빠진다** |
| P10 | 저장소 밖 도구가 낡는다 | `~/bin/ticket-quick`: 경로 고정, 테스트 없음, 저장소 변경 이력에 잡히지 않음 |
| P11 | 참조가 이미 썩고 있다 | active 계획에 줄 번호 참조(파일명 뒤 `:줄번호`, `L줄번호`) 18개, 깨진 상대 링크 1개(`character-resource-pipeline.md` → 아카이브된 `recursive-self-evolution.md`) |
| P12 | 가드 테스트가 있어도 돌리지 않으면 깨진 채로 남는다 | `tests.test_docs_budget` 현재 실패: `docs/DEVLOG.md` 52,710 B > 상한 40,960 B. 아무도 발견하지 못했다 |
| P13 | 규칙의 적용 대상이 표시되지 않아 다른 에이전트가 가져다 쓴다 | 2026-09-27 Claude Code가 챗 에이전트 헌장의 `<!--choices: …-->` 버튼 규칙을 터미널 답변에 따라 씀(운영자 지적). 루트 `AGENTS.md`(pew/C)는 규칙마다 적용 대상(PE 챗 에이전트 / 저장소 작업 에이전트 전부)을 표시한다 |

---

## 2. 선행 사례와 채택 판단

| 사례 | 무엇 | 판단 | 여기서의 형태 |
|---|---|---|---|
| [AGENTS.md](https://agents.md/) 규약 | 코딩 에이전트 공용 진입 파일(Codex·Cursor 등이 읽음) | **채택** | 저장소 루트 `AGENTS.md`를 정본으로, `CLAUDE.md`·`GEMINI.md`는 포인터만(홈 디렉터리의 기존 방식과 같음) |
| Fitness functions ("Building Evolutionary Architectures") | 아키텍처 규칙을 자동 테스트로 지킨다 | **채택**(이미 `test_docs_budget`, `test_code_layout`, `test_provider_neutrality`라는 선례가 있음) | §4 가드 테스트 묶음 |
| Policy as code | 규칙과 집행자를 한 표로 관리 | **적응** | 규칙 레지스트리(§4) |
| git `core.hooksPath` vs [pre-commit](https://pre-commit.com/) | 커밋 시 검사 | **후보**(D6) | 저장소에 추적되는 `.githooks/` 사용. pre-commit 프레임워크는 의존성이 하나 더 생긴다 |
| Design Doc / RFC | 착수 전 목적·비목표·리스크 | **채택** | 계획 문서 필수 섹션(§6) |
| ADR / [MADR](https://adr.github.io/madr/) | 결정 하나를 불변 파일 하나로 | **채택**(D1) | `docs/decisions/NNNN-<slug>.md` |
| Definition of Ready / Done | 착수·완료 체크리스트 | **채택** | §7 |
| [Shape Up](https://basecamp.com/shapeup) | 크기를 먼저 정하고, 넘치면 끊는다 | **적응** | 항목 크기 S/M/L, L은 쪼개기 전까지 Ready가 아님 |
| [Conventional Commits](https://www.conventionalcommits.org/) + git trailers | 구조화된 커밋 | **채택**(이미 관례) | `Plan:` / `Ticket:` 트레일러, 훅으로 형식 확인 |
| [SemVer](https://semver.org/) + [Keep a Changelog](https://keepachangelog.com/) | 버전과 변경 기록 | **채택** | release-pipeline Now |
| [git-cliff](https://git-cliff.org/) vs [release-please](https://github.com/googleapis/release-please) | 커밋에서 CHANGELOG 생성 | **후보**(D5) | git-cliff는 로컬에서 동작, GitHub 의존 없음 |
| GitHub Issues/Projects, Linear | 외부 트래커 | **기각(지금)** | 기록이 두 곳으로 갈린다. 저장소 private, 로컬 우선 |

---

## 3. 진입과 정본 배치

**입구는 하나다.** 어떤 도구로 저장소에 들어와도 루트 `AGENTS.md`(영어, 원칙 0)에 도착한다.

```text
services/chatbot/
├── AGENTS.md          # 엔진 개발 정본: 시작 순서, 정본 지도, 규칙 레지스트리, run-tests.sh, 커밋 규약
├── CLAUDE.md          # 포인터 한 줄 → AGENTS.md   (테스트: 포인터 외 내용 금지)
├── GEMINI.md          # 포인터 한 줄 → AGENTS.md
├── docs/plans/INDEX.md, docs/decisions/   # 계획과 결정
└── templates/         # 사용자 데이터 부트스트랩 기본값(엔진 소유)
$CHATBOT_DATA/workspace/AGENTS.md          # 챗 에이전트(제품 런타임) 헌장. 엔진 개발 규칙은 포인터만
```

**정본 지도**(루트 `AGENTS.md` 안의 표, 사실마다 한 곳):

| 사실 | 정본 | 다른 곳에서는 |
|---|---|---|
| 호스트 운영 법 | `~/AGENTS.md` | 링크만 |
| 엔진 개발 규칙·코드 지도 | 루트 `AGENTS.md` (현 `PROJECT.md` "Where to edit"를 옮겨 옴, D7) | 링크만 |
| 챗 에이전트 행동 규칙 | `$CHATBOT_DATA/workspace/AGENTS.md` | — |
| 데이터 경로 | `host_config.py` | 셸·도구는 `python3 -c 'import host_config…'` 또는 env만 사용 |
| 계획 상태 | `docs/plans/INDEX.md` | 계획 문서 안의 상태 줄은 INDEX와 같아야 함(테스트) |
| 항목 진행 상태 | 티켓 | 계획에는 `#N`과 `✅`만 |
| 결정 | `docs/decisions/` | 계획은 링크만 |
| 변경 기록 | git + `CHANGELOG.md` | DEVLOG는 작업 일지(서술), 릴리스 기록 아님 |

**에이전트 개인 메모리**(Claude memory, Hermes 등)는 선호와 교훈만 담고, 저장소에 있는 사실은 복제하지 않는다. 복제했다면 저장소 정본을 가리키는 링크로 바꾼다.

**저장소 밖 도구는 저장소로 들인다.** `~/bin/ticket-quick` → `tools/ticket_quick.py`(테스트 포함, `host_config` 사용). `~/bin/`에는 한 줄짜리 실행 포인터만 남긴다(P10).

### 3.1 PE 내부 경로가 주 경로다 (2026-09-27 운영자)

작업 대부분은 PE 안에서 일어난다. 규칙은 외부 CLI뿐 아니라 **PE 안의 모든 에이전트 경로**에서 똑같이 지켜져야 한다.

| 경로 | 누가 | 규칙을 받는 곳 | 끝나는 곳 |
|---|---|---|---|
| ① 라이브 수정 | 챗 에이전트(PD 직접, Tier 0/1·승인된 Tier 3) | `$WORKSPACE/AGENTS.md` 주입 묶음(`instructions.py`, **상한 4,800 B**) + 도구 응답 | 커밋 → `tickets.release(done)` |
| ② 위임 | 러너가 띄운 전문가 CLI(`tools/worktree_runner.py`) | 워크트리 = 저장소 루트 → CLI가 루트 `AGENTS.md`/`CLAUDE.md`를 자동으로 읽음 + 작업 지시 | 러너 게이트 → 커밋 → 병합 → `release` |
| ③ 외부 | 터미널의 Claude Code·Grok·Gemini 등 | 루트 `AGENTS.md` | 커밋 → `ticket-quick done` |

설계 규칙:

- **세 경로가 모두 지나는 길목에 집행자를 둔다**: `git commit`(훅, 워크트리도 `core.hooksPath` 공유), `tickets.release(done)`(이미 dirty 경로를 거절함), 러너 게이트. 한 경로에만 있는 집행자는 누수다.
- **①에는 글을 더 얹지 않는다.** 주입 묶음이 이미 상한을 넘었다(`test_bundle_budget` 5,504/4,800 B). 챗 에이전트에게는 포인터 한 줄만 주고, 규칙은 **도구가 거절하면서 짧게 알려 주는 방식**으로 전한다(기존 `ticket` 도구가 증거 형식을 알려 주는 방식과 같음).
- **②는 루트 `AGENTS.md`로 자동 해결된다.** 워커 CLI는 워크트리 루트에서 돌기 때문이다. 그래서 루트 `AGENTS.md`는 외부용이 아니라 **PE 위임 워커와 외부 에이전트가 함께 쓰는 입구**다.
- **훅 우회(`--no-verify`)는 ②의 러너 게이트와 ①·③의 `release` 관문이 다시 잡는다**(D8).

---

## 4. 강제층

### 4.1 단일 실행 진입점

`run-tests.sh [--fast | 모듈…]` 하나만 둔다(`pew/B` 완료). 기준선(2026-09-27): 92개 중 78개 통과, 14개 실패(DEVLOG 2026-09-27 pew/B 항목에 분류). **빨간 기준선 위에 훅·게이트를 걸면 모든 작업이 막히므로 녹색화(`pew/N`)가 먼저다.** 훅, 러너 게이트(`worktree_runner` 기본 게이트), 이후 CI가 모두 이것을 부른다. `--fast`는 커밋 훅용 부분 집합(가드 테스트 + 변경된 파일 관련 모듈)이다.

### 4.2 커밋 훅 (`.githooks/`, `core.hooksPath`)

| 훅 | 검사 |
|---|---|
| `pre-commit` | `run-tests.sh --fast` · 스테이징된 파일의 비밀·PII 패턴(키 형태, `secrets.env`, `private-memory.md`) · untracked 계획 문서 경고 |
| `commit-msg` | Conventional Commits 형식. `docs/plans/` 항목을 건드린 커밋은 `Plan:` 트레일러 필수 |

훅 설치 여부 자체도 `run-tests.sh`가 확인한다(`git config core.hooksPath` ≠ `.githooks`이면 한 줄 경고). 새로 클론하거나 새 워크트리를 만들어도 빠지지 않게 하기 위해서다.

### 4.3 가드 테스트 묶음 (fitness functions)

| 테스트 | 지키는 것 |
|---|---|
| `test_rule_registry` | 루트 `AGENTS.md`의 MUST 규칙마다 집행자(테스트 이름·훅) 또는 `manual: <사유>`가 있음. 적힌 테스트가 실제로 존재함 |
| `test_entrypoints` | `CLAUDE.md`·`GEMINI.md`는 포인터만 있음(줄 수 상한 + `AGENTS.md` 링크) |
| `test_plans_index` | `docs/plans/*.md` ↔ INDEX 행이 1:1 대응 · 상태 값 4종 · 계획 안의 상태 줄 = INDEX · `archive/`에 있는 문서는 archived 표에만 |
| `test_doc_refs` | active 계획·ADR·AGENTS.md의 상대 링크가 존재 · `path::symbol` 참조가 실제로 grep됨 · 줄 번호 참조(파일명 뒤 `:줄번호`, `L줄번호`) 금지 |
| `test_plan_items` | 항목 표 열 형식 · 항목 id 중복 없음 · `#N`이 실제 티켓이고, 티켓이 `done`이면 행이 `✅` · G0 방향 문서에는 항목 id 없음 |
| `test_data_paths` | `host_config.py` 밖에서 데이터 경로 리터럴·env 직접 읽기 금지(`uds/B`와 함께 들어감) |

기존 `test_docs_budget`의 "INDEX에 모든 계획" 검사는 `test_plans_index`로 옮기고, 중복은 두지 않는다.

---

## 5. 수명주기 (게이트)

```text
G0 방향 ─ G1 초안 ─ G2 검토 ─ G3 결정 ─ G4 준비 ─ G5 티켓 ─ G6 실행 ─ G7 완료 ─ G8 릴리스 ─ G9 회고·아카이브
```

| 게이트 | 산출물 | 통과 조건 | 집행 |
|---|---|---|---|
| G0 방향 | concept, brand, 로어 | 인용만, 항목 id 없음 | `test_plan_items` |
| G1 초안 | 계획 + INDEX 행 | §6 필수 섹션, 같은 변경에서 커밋 | `test_plans_index`, pre-commit |
| G2 검토 | "현황 점검" 섹션 | 코드 대조(명령·날짜) · 관련 계획과의 모순 목록 · L 크기 또는 Tier 2 이상이면 교차 리뷰 | 수동(체크리스트) |
| G3 결정 | ADR | 열린 D-n이 결정·보류·범위 밖 중 하나로 정리됨 | **운영자만** |
| G4 준비 | 항목 행 | §7 DoR | `test_plan_items`(형식), 나머지는 수동 |
| G5 티켓 | 티켓 #N, 행에 `#N` | 계획이 커밋된 상태, 티켓 제목 `[<id>] …` | `test_plan_items` |
| G6 실행 | 커밋 | 기존 경로(ticket-quick / PD delegate) + `run-tests.sh` | 훅, 러너 게이트 |
| G7 완료 | `✅ #N <hash>`, CHANGELOG | §7 DoD | `test_plan_items`, commit-msg |
| G8 릴리스 | VERSION, tag, 노트 | release-pipeline | 운영자 승인 |
| G9 회고 | 관찰, 아카이브 | 모든 항목이 ✅ 또는 폐기되면 그 주에 아카이브 | `test_plans_index`(전부 ✅인 active 계획은 경고) |

작은 수정(버그 한 건)은 G1–G4를 건너뛰고 티켓으로 바로 간다.

---

## 6. 계획 문서 표준

필수 섹션(순서 고정): **머리**(제목 바로 아래 `> 방향 (…): **등급** — 이유` 한 줄 — 등급은 INDEX 참조, `test_plans_index`가 확인 · 상태·목적·관련·방향 인용) → **범위/비목표** → **현황 점검**(날짜·명령·발견, 목표와 섞지 않음) → **결정**(`D-n | 질문 | 추천 | 상태/ADR`) → **작업 항목 표** → **의존·순서·리스크**.

작업 항목 표:

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|

- id = `<계획 약칭>/<문자>`(이 문서는 `pew`). 한 번 붙인 id는 다시 쓰지 않는다.
- 수용 기준은 **실행할 수 있는 확인**(명령·테스트·관찰 가능한 동작)으로 쓴다.
- 코드 참조는 `path` 또는 `path::symbol`. 줄 번호는 쓰지 않는다.
- 티켓 열 값: `대기` · `결정 필요(D-n)` · `준비` · `#N` · `✅ #N <hash>` · `폐기(사유)`.
- 템플릿: `docs/plans/_TEMPLATE.md`.

---

## 7. DoR / DoD

**Ready (G4)**: paths가 실제로 있고 grep으로 확인됨 · 수용 기준이 실행 가능 · tier와 ⚡ 여부 기재 · 크기 S/M · 연결된 D-n이 결정됨 · G0 문서에서 끌어온 요구 없음

**Done (G7)**: 수용 기준 통과(결과를 티켓 노트에 남김) · `run-tests.sh` 통과 · 트레일러 `Plan:`/`Ticket:` · CHANGELOG `Unreleased`에 사용자 관점 한 줄 · 행에 `✅ #N <hash>` · ⚡ 필요 시 운영자 유휴 확인 후 재기동하고 smoke 통과

---

## 8. 추적성

```text
decisions/NNNN ← 계획 항목(uds/B) ← ticket #N ← commit (Plan: uds/B · Ticket: #N) → CHANGELOG → tag vX.Y.Z
```

역방향 조회: `git log --grep='Plan: uds/'` · 티켓 제목 접두어 `[uds/B]`.

---

## 9. 결정 (2026-09-27 운영자: 전부 추천안 채택)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 결정 기록을 `docs/decisions/`(ADR)로 분리할까? | **예** | 결정 2026-09-27 (ADR 소급: pew/H) |
| D2 | 항목 진행 상태의 SSOT는? | **티켓**. 계획에는 `#N`·`✅`만 | 결정 2026-09-27 (ADR 소급: pew/H) |
| D3 | 운영자가 대화 중 요청한 계획 편집에도 티켓이 필요할까? | **불필요**. 대신 같은 턴에 커밋(훅이 untracked 계획을 잡음) | 결정 2026-09-27 (ADR 소급: pew/H) |
| D4 | 교차 리뷰 의무 범위는? | **L 크기 또는 Tier 2 이상** | 결정 2026-09-27 (ADR 소급: pew/H) |
| D5 | CHANGELOG 생성 도구는? | **git-cliff** | 결정 2026-09-27 (ADR 소급: pew/H) |
| D6 | 훅 방식은? | **`.githooks/` + `core.hooksPath`**(의존성 추가 없음) | 결정 2026-09-27 (ADR 소급: pew/H) |
| D7 | 코드 지도(`PROJECT.md` "Where to edit")와 엔진 개발 규칙을 `data/`에서 루트 `AGENTS.md`로 옮길까? | **예**. 사용자 데이터 분리 전에 옮겨야 엔진 문서가 저장소 밖으로 빠지지 않는다. 챗 에이전트 헌장에는 포인터만 남긴다 | 결정 2026-09-27 (ADR 소급: pew/H) — 이관 범위는 uds 분류 감사와 함께 |
| D8 | 훅 우회(`--no-verify`)의 백스톱은? | **러너 게이트 + 이후 CI**. 에이전트 헌장에 `--no-verify` 금지를 두고, 레지스트리에는 `manual`로 표시 | 결정 2026-09-27 (ADR 소급: pew/H) |

---

## 10. 작업 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `pew/A` | 이 문서 + INDEX 행 | `docs/plans/plan-execution-workflow.md`, `docs/plans/INDEX.md` | INDEX에 행이 있고 커밋됨 | 0 · — | S | — | ✅ 티켓 없음(D3), `git log --grep="Plan: pew/A"` |
| `pew/B` | `run-tests.sh [--fast]` 단일 진입점(`rp/A`와 공유, 소유는 여기) + DEVLOG 크기 복구 | `run-tests.sh`, `README.md`, `docs/DEVLOG.md` | 모든 `tests/test_*.py` 모듈을 개별 실행하고 실패 목록 출력, 종료 코드 반영 | 1 · — | S | — | ✅ #254 `09aca4a` |
| `pew/C` | 루트 진입점: `AGENTS.md`(정본 지도, 시작 순서, 커밋 규약, 규칙 레지스트리 초판) + `CLAUDE.md`·`GEMINI.md` 포인터 | 루트 3파일 | 포인터 두 파일이 각각 5줄 이하, `AGENTS.md` 링크 포함 | 3 · — | M | D7 | ✅ #262 `ace91b3` |
| `pew/D` | 가드 테스트 1차: `test_rule_registry`, `test_entrypoints`, `test_plans_index`, `test_doc_refs` | `tests/` | 현재 저장소에서 실패하는 항목(P11 등)을 먼저 고치고 통과. 일부러 규칙을 어기면 실패 | 3 · — | M | pew/B, pew/C | ✅ #264 `ad095f7` |
| `pew/E` | 훅: `.githooks/pre-commit`, `commit-msg` + 설치 확인 | `.githooks/`, `run-tests.sh` | 비밀 패턴이 든 파일, untracked 계획, 형식이 틀린 메시지로 커밋하면 각각 거절됨 | 3 · — | S | pew/B, D6 | ✅ #266 `6c55743` |
| `pew/F` | 러너 게이트(`DEFAULT_GATES`)를 `run-tests.sh --fast` + 변경 경로 관련 모듈로 교체 | `tools/worktree_runner.py` | 위임 실행 로그에 `run-tests.sh` 결과가 남음 | 3 · — | S | pew/N | ✅ #267 `d0acc0a` |
| `pew/N` | **기준선 녹색화**: 실패 14개를 세 티켓으로 — N1 구조 가드 초과(`test_bundle_budget` 헌장 묶음 축소, `test_file_sizes` `server.py` 분할) · N2 코드 분리 후 낡은 UI 하네스·소스 문자열 테스트 8개 · N3 동작 기대 불일치 3개(각각 코드와 테스트 중 무엇이 맞는지 운영자 확인) | 티켓별 | `./run-tests.sh` 종료 코드 0 | 3 · ⚡(N1 `server.py`) | M×3 | pew/B | ✅ #255–#261 (`git log --grep="Plan: pew/N"`) |
| `pew/O` | `tickets.release(done)`이 `run-tests.sh --fast`를 통과해야 완료되게 함(훅 우회의 백스톱, 경로 ①·③) | `tickets.py`, `tests/test_tickets.py` | 가드 테스트가 빨간 상태에서 `done`이 짧은 이유와 함께 거절됨 | 3 · ⚡ | S | pew/N | ✅ #267 `d0acc0a` |
| `pew/P` | 러너 관련 테스트 확장: 바뀐 파일 이름을 **본문에서 언급하는** 테스트도 포함(예: `protected_paths.json` → `test_lifecycle`·`test_evolution`·`test_code_layout`). 2026-09-28 `7b54fd9`에서 `test_lifecycle` 실패가 훅·완료 관문(가드만)을 통과한 사례 | `tools/worktree_runner.py`, `tests/test_worktree_runner.py` | `related_gate(["protected_paths.json"])`이 위 세 모듈을 포함 | 3 · — | S | pew/F | ✅ #270 `2313b86` |
| `pew/G` | 계획 템플릿 + INDEX 규칙에 수명주기 요약과 링크 | `docs/plans/_TEMPLATE.md`, `docs/plans/INDEX.md` | 템플릿이 §6 섹션을 모두 포함 | 0 · — | S | D2 | 대기 |
| `pew/H` | ADR 도입 + `0001-user-data-default-pe.md`(`~/.pe` 결정 소급) | `docs/decisions/` | MADR 축약 형식, 루트 AGENTS.md 정본 지도에서 링크 | 0 · — | S | D1 | 대기 |
| `pew/I` | `test_plan_items`(항목 표·티켓 대조) | `tests/test_plan_items.py` | 파일럿 두 문서에서 통과, 틀린 `#N`은 실패 | 3 · — | M | pew/J | 대기 |
| `pew/J` | **파일럿**: release-pipeline·user-data-separation을 §6 표준으로 개편(P1–P3 해소, `rp/*`·`uds/*` 재정의, `test_data_paths`는 `uds/B`에 포함) | 두 계획 문서 | 항목마다 §7 DoR 충족, 문서 간 모순 0건 | 0 · — | M | pew/G | 대기 |
| `pew/K` | `~/bin/ticket-quick` → `tools/ticket_quick.py` + 테스트, `~/bin`에는 포인터만 | `tools/ticket_quick.py`, `tests/`, `~/bin/ticket-quick` | 기존 명령줄 사용법 그대로 동작, 경로는 `host_config`에서 | 3 · — | S | uds/B | 대기 |
| `pew/L` | 역할별 개발 안내(2026-09-27 운영자): 챗봇은 여러 캐릭터가 역할을 나눠 맡으므로, 개발 규칙 포인터(루트 `AGENTS.md`, `--no-verify` 금지, "아키텍처 책임자" 역할)는 **개발에 관여하는 역할 팩에만**, 개발 작업일 때만 싣는다. 공용 헌장(`data/workspace/AGENTS.md`)에는 넣지 않고, 지금 공용 헌장에 있는 개발 절(Self-modification)도 역할 팩으로 옮길 수 있는지 검토 | `data/workspace/roles/<개발 역할>/`, `data/workspace/AGENTS.md` | 개발 역할이 아닌 캐릭터의 주입 묶음에 개발 규칙이 없음(테스트), `test_bundle_budget` 녹색 | 3 · — | M | pew/C | 대기 |
| `pew/M` | CHANGELOG 자동화(`rp/A`와 합침) | release 쪽 | `git-cliff`로 `Unreleased` 생성 | 1 · — | S | D5 | 대기 |

**순서**

1. **토대**: A ✅ → B ✅ → N ✅(93/93, 2026-09-27) → C ✅ → D ✅ → E ✅ → F ✅ · O ✅ (2026-09-28; 서버 쪽 O는 다음 ⚡에 반영). 입구와 강제층을 먼저 세우되, 빨간 기준선 위에는 걸지 않는다. 이후 작업은 모두 이 그물 아래에서 진행된다.
2. **절차**: G·H → J(파일럿) → I. 파일럿을 수작업으로 한 번 돌려 본 뒤 항목 검사를 자동화한다.
3. **정리**: K(`uds/B` 뒤) · L · M.

---

## 11. 하지 않는 것

- 티켓 엔진(`tickets.py`)에 `plan` 필드 추가: 제목 접두어와 트레일러로 충분한지 파일럿 뒤에 다시 판단한다
- 외부 트래커 동기화, 원격 CI 서비스 도입: 최소 CI는 release-pipeline Next 소관이며 같은 `run-tests.sh`를 부른다
- 기존 아카이브 계획을 소급해서 개편(깨진 링크 수리만 예외)
- concept·숨은 로어를 항목으로 만드는 일
