# 방향 정렬 (개인화 하네스로의 전환)

> 상태: **active** (초안 2026-09-28)
> 목적: 바뀐 제품 지향점에 맞춰 기조 문서·계획·코드의 낡은 부분을 정렬한다. 기조(`docs/concept.md`)를 다시 쓰는 일이 첫 단계이고, 나머지는 그 기조를 기준으로 한다.
> 관련: [concept.md](../concept.md) · [plan-execution-workflow.md](plan-execution-workflow.md) · [release-pipeline.md](release-pipeline.md) · [localization.md](localization.md) · [character-memory-adapter.md](character-memory-adapter.md) · [private-mode.md](private-mode.md)
> 방향 인용(G0): 숨은 로어(전영소녀·조이)는 방향만 쓴다. 로어 세부는 이 계획의 항목이 아니다.
> 약칭: `align`

---

## 0. 새 지향점 (운영자, 2026-09-28)

> 초반에 개인 용도로 가볍게 쓰려고 만들었다가 욕심이 생기면서 여기까지 왔고, 지향점이 바뀌면서 낡아버린 문서와 코드가 많다. 제품으로서는 **전영소녀나 블레이드 러너의 조이**를 컨셉으로 한다. 프로바이더가 제공하거나 천편일률적으로 개발되는 **업무 중심 하네스가 아니라, 내 취향껏 개인화가 쉬운 하네스**가 목표다. 업무 능력이나 효율로 경쟁하지 않고 **개인화 레이어를 두텁게 쌓는 것**이 목적이다. 에이전트의 능력은 생산성보다 **개인화 레이어를 쉽게 쌓도록 돕는 역할**이 주가 된다. NAS 제어는 설치 환경이 NAS라서 생긴 것이고, 엔드유저 배포 시에는 사용자의 PC나 서버가 된다.

## 1. 무엇이 바뀌나

| 항목 | 지금 문서·코드가 말하는 것 | 새 지향점 |
|---|---|---|
| 최대 가치 | "친근하면서 유능, 다재다능·만능에 가깝다" (`concept.md`) | 취향대로 쌓이는 개인화된 동반자. 유능함은 목적이 아니라 수단 |
| 사용자 | 실장님 한 명의 개인 NAS 비서 (`PRODUCT.md`) | 자기 PC·서버에 설치하는 엔드유저 |
| 차별점 | NAS 직접 제어 (`PRODUCT.md` Positioning) | 두꺼운 개인화 레이어(캐릭터·기억·외형·말투·관계의 연속성) |
| 경쟁 축 | 업무 수행 | 업무 경쟁은 하지 않음 |
| 에이전트 능력의 쓰임 | 호스트 제어, 엔진 코드 수정, 전문가 위임 | 사용자가 개인화 레이어를 쉽게 쌓도록 돕기 |
| 자기 진화 | 에이전트가 엔진 코드를 고친다(관찰 → 티켓 → 관문) | 제품 사용자에게는 **개인화 레이어의 진화**. 엔진 코드 진화는 개발자용 |
| NAS·호스트 | 핵심 기능 | 설치 환경별 선택 플러그인 |

## 2. 현황 점검 (2026-09-28)

| 확인 | 결과 |
|---|---|
| NAS 시절 정체성(DiskStation, Sphere, `/volume1`, 실장님, 냥피디, 관제 등)이 나오는 문서 | 21개. 많은 순: `PRODUCT.md` 25, `character-resource-pipeline.md` 16, `DEVLOG.md` 11, `DESIGN.md` 10, `multi-agent-worktree-delegation.md` 8, `README.md` 5 |
| 같은 정체성이 박힌 코드(`*.py`, `static/`) | 15개 이상. `session.py` 8, `nas_mcp_host.py` 7, `mcp_server.py` 6, `host_config.py` 5, `static/app.js`·`app-messages.js` 각 5 … |
| 업무 중심 기능 구조 | PD 모델·전문가 위임(`delegation.py`, `tools/worktree_runner.py`), 티켓·관찰·자기 진화(`tickets.py`, `observations.py`, `evolution.py`), NAS 도구(`nas_mcp_host.py`) |
| 개인화 레이어에 해당하는 것 | 캐릭터 카드·편집(`characters.py`, 팀 탭), 캐릭터별 기억(`memory.md`, `private-memory.md`), 외형(`visual.md`, 이미지), 사적 모드(`private_engine.py`), ST 카드 가져오기(`tools/st_import.py`), 로어북 |

활성 계획별 방향 적합성(초안):

| 계획 | 판정 |
|---|---|
| character-memory-adapter, private-mode, character-resource-pipeline, user-data-and-editing, out-of-band-choices-actions | **핵심**: 개인화 레이어 자체 |
| release-pipeline, user-data-separation, localization, private-engine-brand | **기반**: 엔드유저 배포에 필요 |
| plan-execution-workflow, monolith-split | **개발 기반**: 누가 개발하든 필요 |
| multi-agent-worktree-delegation | **재정의 필요**: 업무·엔진 개발 중심. D2 결정에 따라 개발자 도구로 남기거나 개인화 도우미로 바꾼다 |

## 3. 결정

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 기조 문안 | 운영자의 §0 발언을 기준으로 `concept.md`의 "최대 가치·최대 목표·열린 축"을 다시 쓴다. 초안은 에이전트가 쓰고 문안은 운영자가 확정 | 열림 |
| D2 | 업무 중심 장치(PD·위임·티켓·자기 진화)의 자리 | **두 개의 고리로 나눈다.** ① 엔진 개발 고리: 지금의 티켓·관문·위임. 개발자와 개발 역할용이며 제품 기본값에서 꺼져 있다(pew/L과 연결). ② 개인화 고리: 제품의 에이전트가 하는 일. 캐릭터·기억·외형·말투를 사용자와 함께 만들고 다듬는다. 새 계획으로 설계한다 | 열림 |
| D3 | NAS·호스트 기능 | 설치 환경별 **선택 플러그인**. 배포판 기본값은 꺼짐. 이미 분리된 `nas_mcp_host.py`가 출발점 | 열림 |
| D4 | 코드·UI에 박힌 개인 호칭과 페르소나("실장님", "냥") | 엔진 문자열은 중립으로, 호칭과 말투는 캐릭터 카드와 사용자 설정으로(l10n/D와 같은 작업) | 열림 |
| D5 | `PRODUCT.md`·`README.md`·`DESIGN.md` | 엔드유저 제품 기준으로 다시 쓴다. 운영자 개인 설치에 대한 내용은 "개발 환경" 절로 옮긴다 | 열림 |
| D6 | 정렬 순서 | 기조(D1) → 제품 문서(D5) → 계획별 적합성 표시 → 코드(D3·D4) → 개인화 고리 설계(D2의 ②) | 열림 |

## 4. 작업 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `align/A` | 이 문서 + INDEX 행 | `docs/plans/direction-alignment.md`, `docs/plans/INDEX.md` | INDEX 행, 커밋 | 0 · — | S | — | ✅ 티켓 없음(pew D3) |
| `align/B` | `concept.md` 기조 재작성 초안 → 운영자 확정 | `docs/concept.md` | 운영자 확정 문안, "만능·유능" 중심 문장 제거, 축 목록이 개인화 중심 | 0 · — | S | D1 | 대기 |
| `align/C` | `PRODUCT.md`·`README.md`·`DESIGN.md` 엔드유저 기준 재작성 | 세 파일 | NAS 시절 정체성은 "개발 환경" 절에만 | 0 · — | M | align/B | 대기 |
| `align/D` | 활성 계획마다 방향 적합성 한 줄 + INDEX 반영, 맞지 않는 계획은 재정의 또는 대체 | `docs/plans/*.md`, `INDEX.md` | 모든 활성 계획에 적합성 표시 | 0 · — | M | align/B | 대기 |
| `align/E` | **래칫 가드**: 엔진 코드(호스트 플러그인 제외)에 NAS·개인 정체성 문자열이 늘면 실패 | `tests/test_host_identity_ratchet.py` | 새로 늘면 실패, 줄면 기준선 낮춤 | 3 · — | S | — | 대기 |
| `align/F` | NAS 기능을 선택 플러그인으로(D3): 설정 없으면 로드 안 함 | `nas_mcp_host.py`, `mcp_server.py`, `host_config.py` | NAS가 아닌 환경에서 기본 설치가 NAS 도구 없이 동작 | 3 · ⚡ | M | D3 | 대기 |
| `align/G` | 호칭·말투 중립화(D4) — l10n/D와 한 번에 | `static/*.js`, `*.py` | 래칫 기준선 0 | 2 · ⚡ | M | D4, l10n/D | 대기 |
| `align/H` | **개인화 고리 설계**(D2 ②): 새 계획 문서. 에이전트가 사용자와 함께 캐릭터·기억·외형·말투를 쌓는 흐름, 기존 역할 팩(`artist` 등)·카드 편집·기억 어댑터와의 관계 | 새 계획 | 운영자 검토를 거친 설계 | 0 · — | M | align/B, D2 | 대기 |
| `align/I` | 엔진 개발 고리를 개발 역할·개발자 전용으로 분리(D2 ①) — pew/L 확장 | `data/workspace/roles/`, `data/workspace/AGENTS.md`, 기본 템플릿 | 배포 기본 팀에 개발 역할이 없고, 켜면 동작 | 3 · — | M | D2, pew/L | 대기 |

## 5. 원칙

- **기조가 먼저다.** 기조 문안(align/B)이 확정되기 전에는 코드 정렬을 시작하지 않는다. 확정된 기조가 이후 모든 "맞는가/맞지 않는가" 판단의 기준이다(루트 `AGENTS.md` "Your role").
- **지우기 전에 옮긴다.** 운영자 개인 설치에 필요한 NAS 기능은 없애지 않고 플러그인으로 옮긴다.
- **래칫으로 막는다.** 정렬 중에도 낡은 정체성이 새로 늘지 않게 align/E를 먼저 건다.
