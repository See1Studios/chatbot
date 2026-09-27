# 캐릭터 파일·리소스 파이프라인

- **상태:** 계획. 착수는 사용자 말로.
- **작성:** 2026-09-26
- **결정:** 사용자, 같은 날 — 캐릭터 생성·수정 시 SSOT가 필요 리소스를 만들고 있어야 할 곳에 둔다. 자기진화 루프와 맞춘다. 코드가 아니라 캐릭터 파일의 집.
- **선행:** `character-art` 스킬, `characters.check_art` (CHARACTER_ART_v1), [multi-agent-worktree-delegation.md](./multi-agent-worktree-delegation.md) §12.4, [user-data-separation.md](./user-data-separation.md), [recursive-self-evolution.md](./recursive-self-evolution.md) P1·P3
- **대체하는 절차:** 스킬 `character-pipeline` 6단계의 “웹 루트에 손으로 복사”. 채팅은 이미 캐릭터 폴더 API를 읽는다.

---

## 0. 한눈에

캐릭터 하나 = 폴더 하나 `characters/<id>/`. 그 안에서 파일은 세 종류다. 채팅은 `/api/characters/<id>/avatar|stage`로 이 폴더를 직접 제공한다. 생성은 에이전트(`character-art`), 필요 목록·검증·배포는 호스트.

```mermaid
flowchart LR
    A["card.json + visual.md + avatar_master"] --> B["needed_art(id)"]
    B --> C["에이전트 생성 / I2I"]
    C --> D["check_art 게이트"]
    D --> E["채팅 API 즉시"]
    D --> F["Hub: API 또는 publisher 공개 부분집합"]
    B --> G["관찰 → 티켓"]
```

자기진화는 완결성을 관찰하고 티켓을 연다. 잠긴 마스터를 다시 그리지 않는다.

---

## 1. 이미 있는 것 / 구멍

실측 (2026-09-26).

| 항목 | 상태 |
|---|---|
| 정본 폴더 `characters/<id>/card.json` + `visual.md` + 그림 | 있음. 채팅 선택기·뱃지·스테이지가 `/api/characters/<id>/…`로 읽음 (`server.py` `_character_avatar`) |
| 형식·검사 | `character-art` 스킬, `characters.check_art`, `tools/check_character_art.py` |
| 필요 목록 함수 | **없음.** 빠진 파일은 스킬 문서와 사람이 센다 |
| `data/persona/` (35MB) | 제품 크롬(벤더 아이콘, `bg-studio`)과 옛 냥피디 그림이 한 폴더. git 추적 |
| `/volume1/web/chat/persona/` (52MB) | 레포 밖 복사. Hub FAB가 `/chat/persona/providers/<id>.webp`를 직접 읽음 |
| 파이프라인 스킬 6단계 | 여전히 “웹 루트 동기화”라고 적혀 채팅 코드와 어긋남 |
| git | 승인 webp뿐 아니라 `avatar_master.jpg`, `*_candidate_*`, `_old_avatar_wigs/`까지 추적. `references/`, `private-memory.md`만 ignore |
| 캐릭터 경로 보호 | `protected_paths.json` 밖. 위임 티어 0. 그림은 비용·정체성 때문에 티어 0 자동 랜딩으로 다루지 않음 |
| 사용자 데이터 분리 | [계획](./user-data-separation.md). 캐릭터 폴더는 최종적으로 git 밖 인스턴스 데이터 |

채팅 경로의 복사는 죽은 단계다. Hub와 제품 크롬만 정적 경로가 남는다.

---

## 2. 폴더 안 세 종류

`characters/<id>/` 하나. 종류만 나눈다. 새 최상위 디렉터리를 만들지 않는다.

### 2.1 정본 (덮어쓰기 금지, 운영자 잠금)

| 파일 | 역할 |
|---|---|
| `card.json` | 이름·말투·두뇌 목록. Character Card V2 |
| `visual.md` | 화풍·외형 락·가발 표·거절 목록 |
| `avatar_master.*` | 승인된 얼굴 앵커. 파생은 전부 이 그림에서 I2I |

마스터를 에이전트가 재생성하면 거절한다. 후보만 `gallery/`에 둔다.

### 2.2 파생 (정본에서 다시 만들 수 있음, 앱이 씀)

형식은 CHARACTER_ART_v1 그대로.

| 파일 | 크기 | 필수 |
|---|---|---|
| `avatar.webp` | 512², ≤200KB | 예 |
| `avatar/<provider>.webp` | 512², ≤200KB | `card.json` `brains.work`에 있는 프로바이더마다 **기대**. 없으면 기본 룩으로 폴백 (이미 동작) |
| `stage.webp` | 1024², ≤300KB | 아니오. 없으면 공용 스튜디오 |
| `stage/<provider>.webp` | 1024², ≤300KB | 아니오 |
| `sprites/bust/<label>.webp` | 1024² 투명, ≤400KB | 아니오. 프레이밍이 생기면 `neutral` 필수 |
| `sprites/full/<label>.webp` | 1024×2048 투명, ≤800KB | 아니오 |

표정 이름표는 SillyTavern 세트. 처음 몇 장은 `neutral`, `joy`, `sadness`, `anger`, `surprise`, `embarrassment`. 몸체는 `neutral`에 고정하고 얼굴만 고친다.

### 2.3 인스턴스 (배포·공유 금지)

| 파일 | git | 비고 |
|---|---|---|
| `memory.md` | 분리 전까지 추적 가능 | 업무 기억 |
| `private-memory.md` | 이미 ignore | 사적 세션만 |
| `references/` | 이미 ignore | 공부용, 출고 금지 |
| `gallery/`, `*_candidate_*`, `_old_*` | **ignore로 추가** | 미승인·폐기 |

### 2.4 제품 크롬 (캐릭터 파이프라인 밖)

벤더 아이콘 `providers/<id>.webp`, 공용 `bg-studio.webp`, 폴백 `face-icon.webp`는 캐릭터가 아니다. 생성·가발·스프라이트 작업이 여기를 건드리지 않는다. 위치는 구현 때 `static/` 또는 `data/persona/providers/` 중 한곳으로 고정하고, Hub는 그 한곳만 읽는다.

---

## 3. 있어야 할 곳

| 파일 | 런타임 위치 |
|---|---|
| 카드·visual·파생 그림 | `characters/<id>/`만. 채팅은 API |
| 기억 | 같은 폴더. 세션 주입만 |
| Hub FAB 기본 캐릭터 얼굴 | 기본 캐릭터의 `/api/characters/<id>/avatar` **또는** publisher가 찍은 공개 부분집합 한 장 |
| Hub 벤더 아이콘 | 제품 크롬 한곳 |

에이전트가 `data/persona/`와 웹 루트에 같은 webp를 또 넣는 단계는 없다.

`needed_art(cid) -> [{path, kind, reason}]`이 호스트 계약이다. 입력은 `card.json`의 두뇌 목록, `visual.md`의 가발·스프라이트 표, 마스터 mtime, 디스크에 있는 파생. 출력 예: `avatar.webp 없음`, `visual.md`가 `avatar/agy.webp`보다 최신`, `brains`에 `openrouter`가 있는데 가발 없음`.

오래된 파생의 기준은 마스터(있으면) 또는 `visual.md`의 mtime이 파생보다 최신인 경우. 내용 해시까지 이 계획의 1단계에 넣지 않는다.

---

## 4. 생성은 스킬, 배포는 호스트

SillyTavern 카드 V2·표정 이름표는 유지한다. 없는 것은 가발, `visual.md` 락, 생성 게이트, Hub 배포다.

1. 생성/수정이 `card.json`과 `visual.md`를 쓴다. 마스터가 없으면 후보를 `gallery/`에 두고 운영자가 고른 뒤에만 `avatar_master`로 승격한다.
2. 호스트가 `needed_art`로 빈칸·오래된 칸을 계산한다.
3. 에이전트가 그 칸만 그린다. 얼굴은 마스터 I2I, 가발은 머리색·컷·옷만.
4. `check_art`가 게이트. 실패면 그 파일을 출고하지 않는다.
5. 채팅은 API로 바로 보인다. Hub가 정적 경로를 쓰는 동안만 publisher가 공개 부분집합을 찍는다.

스킬 `character-art`는 그리기 규칙만 남긴다. “웹 루트에 복사” 문장은 뺀다. `character-pipeline`은 이 문서의 절차를 가리키고, 6단계를 publisher 호출(또는 “채팅은 복사 없음”)으로 고친다.

---

## 5. 자기진화와의 연결

캐릭터 파일은 코어가 아니라 **인스턴스 층**이다 (`recursive-self-evolution` P1·P3). 관찰·티켓·승인 루프는 쓰고, git worktree 병합은 캐릭터 바이너리의 최종 집이 아니다. `user-data-separation`이 끝나면 병합 계약은 git diff가 아니라 `check_art` + 마스터 승인이다.

| 신호 | 동작 |
|---|---|
| 필수 그림 없음 (`avatar.webp`, `visual.md`) | 관찰 → 티켓 “캐릭터 X 완결” |
| 마스터/`visual.md`가 파생보다 최신 | 같은 티켓. 오래된 파생만 재생성 |
| `brains`에 프로바이더가 늘었는데 가발 없음 | `needed_art`에 한 장 |
| 카드의 이름·호칭 변경 | 텍스트 표면만 (별도, 관찰 0065). 그림과 분리 |
| 승인된 마스터를 덮음 | 관찰 + 거절 |

자율 진화가 하지 않는 일: 잠긴 마스터 재생성, 운영자 승인 없는 이미지 API 호출, 웹 루트 수동 복사.

게이트는 둘이다.

- **규격:** `check_art` (이미 있음)
- **정체성:** 운영자의 마스터 승인. 캐릭터 경로는 보호 목록 밖이라 위임 티어는 0이지만, 그림 생성은 티어 0 자동 랜딩이 아니다. 티켓은 열고, 마스터 승인은 사람이 한다.

관찰 신호(`observation_signals.json`)에 “캐릭터 완결성”을 넣는 것은 Phase 2. 1단계는 `needed_art` + `check_art`를 doctor/도구가 호출할 수 있게만 한다.

위임: 카드·visual 텍스트 수정은 기존 worktree로 충분하다. 바이너리 생성은 Imagine 도구가 있는 세션이 직접 한다 (PD 직접 예외: 워커가 그 도구를 못 가짐). 생성된 파일은 캐릭터 폴더에 두고 `check_art`로 확인한다.

---

## 6. git (분리 전까지)

`user-data-separation` 착수 전까지 최소만 고친다.

**추적:** `card.json`, `visual.md`, 출고하는 파생 `.webp`

**ignore 추가:**

```
data/workspace/characters/*/gallery/
data/workspace/characters/*/*_candidate_*
data/workspace/characters/*/_old_*/
data/workspace/characters/*/avatar_master.*
data/workspace/characters/*/avatar_preview.*
data/workspace/characters/*/avatar_joy.*
```

마스터를 ignore하면 이 머신의 정본은 디스크에만 남는다. 백업은 인스턴스 데이터 백업 쪽에 맡긴다 (분리 계획 §4). 마스터를 저장소에 남기고 싶으면 이 ignore 한 줄만 빼면 된다 — 열린 질문 Q1.

이미 git에 있는 후보·옛 가발은 1단계 착수 때 `git rm --cached`로 추적만 끊는다. 디스크 파일은 유지.

---

## 7. Hub

Hub `index.html`은 `/chat/persona/providers/<id>.webp`를 FAB 아이콘으로 쓴다. 이건 캐릭터 가발이 아니라 벤더 크롬이다.

선택 (구현 때 하나):

- **H1.** Hub FAB도 챗봇 API의 기본 캐릭터 아바타를 읽는다. 복사 없음.
- **H2.** `characters.publish_public(cid)`가 공개 부분집합(기본 아바타 한 장 + 제품 크롬)만 웹 루트에 찍는다. 에이전트가 손으로 복사하지 않는다.

추천은 H1 (채팅과 같은 SSOT). Hub가 챗봇 프로세스 없이 떠 있어야 하면 H2.

`data/persona/`의 옛 캐릭터 그림·gallery는 1단계 이후 읽지 않는다. 삭제는 운영자가 한 번 확인한 뒤.

---

## 8. 단계 (PR)

각 단계는 독립적으로 머지 가능. 그림 생성 자체는 이 PR들에 넣지 않는다 — 형식과 호스트 계약만.

### PR 1 — 필요 목록과 스킬 정합 (Tier 1, 호스트 모듈이면 ⚡)

- `characters.needed_art(cid, providers)` + 테스트
- `check_art`는 그대로 게이트
- `.gitignore`에 §6 패턴
- 스킬 `character-art`·`character-pipeline`에서 웹 루트 수동 복사 문장 삭제, 이 계획서를 가리킴
- `docs/plans/INDEX.md`는 이 문서가 이미 한 줄

대상: `characters.py`, `tests/test_character_art.py`, `.gitignore`, 스킬 두 개, `data/workspace/docs/character_pipeline.md`

### PR 2 — 관찰 신호 (Tier 1)

- doctor 또는 `needed_art`를 도는 작은 검사: 필수 파일 없는 캐릭터를 관찰 후보로
- 마스터 덮어쓰기 감지는 나중에

대상: `evolution.py` 신호 또는 `workspace_status` 한 줄. `observation_signals.json`을 건드리면 Tier 3 → 이 PR에서 빼고 승인 티켓으로만.

### PR 3 — Hub 정적 경로 (Tier 0 정적 또는 Hub 파일)

- H1 또는 H2 중 사용자가 고른 쪽
- 제품 크롬 경로 한곳 고정

### PR 4 — 사용자 데이터 분리와 합류

- [user-data-separation.md](./user-data-separation.md)가 착수되면 `characters/` 전체를 인스턴스 데이터로 옮긴다
- 그때 캐릭터 작업의 게이트는 git merge가 아니라 `check_art` + 마스터 승인

---

## 9. 열린 질문

착수 전에 받을 것.

- **Q1.** `avatar_master.*`를 git ignore 할까, 이 저장소에 남길까.
- **Q2.** Hub는 H1(API)인가 H2(publisher)인가.
- **Q3.** 가발을 `brains`에 있는 프로바이더만 기대할 것인가, 어댑터 목록 전체인가. 지금은 카드에 `grok`만 있는 캐릭터도 가발 6장이 있다.

---

## Key Decisions

1. **정본은 캐릭터 폴더 하나.** 채팅은 이미 API로 읽는다. 같은 그림의 두 번째·세 번째 복사본을 파이프라인에 두지 않는다.
2. **파일은 정본 / 파생 / 인스턴스.** 제품 크롬은 캐릭터 파이프라인 밖.
3. **`needed_art`가 호스트 계약.** 스킬은 그리기만. 배포는 호스트.
4. **자기진화는 완결성을 관찰한다.** 그림을 그리지 않고, 마스터를 덮지 않는다. 마스터 승인은 사람.
5. **git은 출고 webp + 카드 + visual만** (분리 전까지). 후보·옛 가발·(Q1에 따라) 마스터는 ignore.
6. **SillyTavern 카드 V2와 표정 이름표는 유지.** 새로 만드는 형식은 가발·락·게이트뿐이다.

---

## PR Plan

| 순서 | 제목 | 파일 | 의존 |
|---|---|---|---|
| 1 | `needed_art` + ignore + 스킬 정합 | `characters.py`, 테스트, `.gitignore`, 스킬 2, 워크스페이스 `docs/character_pipeline.md` | 없음 |
| 2 | 캐릭터 완결성 관찰 | doctor/status 쪽, 신호는 승인 티켓 있을 때만 | 1 |
| 3 | Hub 경로 단일화 | Hub `index.html` 또는 얇은 publisher | Q2 |
| 4 | 인스턴스 데이터로 이전 | `user-data-separation`과 같이 | 그 계획 착수 |
