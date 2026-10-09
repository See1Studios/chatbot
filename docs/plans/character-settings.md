# 캐릭터 설정 한곳에서: 스키마로 그리고, 서버가 합쳐 쓰고, 판마다 되돌린다 (character-settings)

> 방향 (align/D, 2026-10-09): **핵심** — 개인화 레이어의 입구. 캐릭터에 관한 모든 것을 프로필 서랍 한곳에서 보고 고친다
> 선행 사례: Hermes — 대시보드 설정이 `DEFAULT_CONFIG`에서 항목마다 스키마(점 경로 키, 종류, 설명, 분류)를 만들어 내려주고 화면은 그것으로 칸을 그린다(`~/.hermes/hermes-agent/hermes_cli/web_server_config.py` `_build_schema_from_config`, `CONFIG_SCHEMA`) — **따른다**: 서버의 항목 스키마 + 범용 화면. **다르게**: Hermes는 설정 파일 하나지만 캐릭터 설정은 여러 파일(카드·표시·두뇌·팀·상태·기억·외형)에 흩어져 있어 항목마다 출처를 둔다. 그 밖: SillyTavern 캐릭터 편집기(카드 V2 필드 전부를 한 화면에서) — 필드 이름과 뜻은 ST를 그대로 쓴다(VISION「SillyTavern Delegation」)
> 상태: **active** (2026-10-09 수립, 운영자: "캐릭터 관련 모든 설정을 여기에서 조회 및 편집할 수 있으면 좋겠어" · "그래")
> 목적: 흩어진 캐릭터 설정을 서버의 항목 스키마 하나로 묶어 프로필 서랍에서 보고 고치게 한다. 저장은 서버가 해당 파일에 합쳐 쓰고, 쓸 때마다 이전 판을 남겨 되돌릴 수 있다.
> 관련: [personalization-ladder.md](personalization-ladder.md)(`ladder/B` 공통 변경 기록·되돌리기, `ladder/C` 카드·팀 쓰기 — 이 계획이 캐릭터 층부터 실제로 만든다) · [ux-shell-roadmap.md](ux-shell-roadmap.md)(프로필 서랍, #880·#884·#886·#888) · [private-mode.md](private-mode.md)(상태·사적 기억은 아직 다듬는 중) · [demo-60s.md](demo-60s.md)(48–56초: 말투 한 줄 고치기)

---

## 1. 지금 (2026-10-09)

| 묶음 | 항목 | 저장 위치 | 서랍에서 |
|---|---|---|---|
| 카드(ST 표준) | 이름, 설명, 성격, 시나리오, 첫 대사, 다른 첫 대사들, 예시 대화, 시스템 지침, 후행 지침, 태그, 제작자·제작자 메모·버전 | `characters/<id>/card.json` `data` | 이름·설명·성격·태그만 편집 |
| 표시 | 화면 이름, 사용자 호칭, 목소리, 얼굴 초점 | `card.json` `extensions.chatbot.display` | 호칭·목소리·초점 |
| 두뇌 | 업무·사적 두뇌 목록(카드 기본) / 운영자 선택 | `card.json` `brains` / `brain-override.json` | 설정 탭(따로 그린 칸) |
| 역할 | lead·dev·art … | `team.json` `members` | 보기만 |
| 상태 | 호감도·선물, 장소, 문턱 세기, 자동 장면, 선물 취향 | `state.json` | 관계 칸(보기만, #875) |
| 기억 | 본인 기억, 사적 기억, 관계 기록 | `memory.md`, `private-memory.md`, `relationship.md` | 본인 기억 보기만 |
| 외형 | 외형 시트, 그림 | `visual.md`, 그림 파일 | 그림 띠 |

**위험 (2026-10-09 평가)**: 서랍의 인라인 저장(`saveCharacterInline`)은 화면이 카드를 읽어 와 고친 항목을 덮어 PUT한다 — **읽기가 실패하면 빈 카드를 만들어 저장한다**(첫 대사·시나리오·예시 대화·두뇌가 사라진다). 이 계획의 서버 합쳐 쓰기가 그 자리를 대신한다.

## 2. 설계

1. **스키마**: `GET /api/characters/<id>/settings` → `{fields: [{key, group, type, label, editable, sensitive, value}]}`. `key`는 점 경로(`card.first_mes`, `display.user_title`, `brain.work`, `state.threshold`, `memory.private` …), `group`은 서랍의 탭(`character` · `relationship` · `settings`), `type`은 `text` · `longtext` · `list` · `bool` · `select`(선택지 함께) · `brain`. 이름은 카탈로그 키(화면 언어로).
2. **합쳐 쓰기**: `PATCH /api/characters/<id>/settings` `{key: value, …}` → 서버가 항목의 출처 파일을 읽고 그 항목만 바꿔 원자적으로 쓴다. 화면은 파일 전체를 만들지 않는다. 모르는 키·편집 불가 항목·형식이 틀린 값은 그 항목만 거절하고 이유를 돌려준다.
3. **판(스냅숏)**: 쓰기 전에 그 파일의 이전 판을 `<data>/backups/characters/<id>/<파일>.<시각>`에 남긴다(파일마다 최근 20판). `GET …/settings/versions?key=` 목록, `POST …/settings/restore` 되돌리기. `workspace_status._backup`(지침 백업)을 일반화하는 `ladder/B`의 첫 구현이다.
4. **민감 항목**: 사적 기억·관계 기록은 `sensitive` — 화면은 접어 두고 펼쳐야 보인다. 호감도 점수는 보기만(엔진이 정한다, private-mode D8).
5. **로그**: `character.setting` 이벤트에 캐릭터 id와 바뀐 키만(값·글 없음).
6. **범용 화면**: 서랍은 스키마를 탭별로 그린다. 항목이 늘어도 서버 스키마만 바꾼다(#875 관계 칸과 같은 방식).

## 3. 결정 (운영자)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 사적 기억·관계 기록을 서랍에서 고칠 수 있게 할지 | 예, 접어 두고 펼쳐서 — 잘못 남은 기억을 지우는 일(2026-10-09 하루의 기억)이 `rm`이 아니라 판이 남는 편집이 된다 | 열림 |
| D2 | 남길 판 수 | 파일마다 20 | 열림 |
| D3 | 역할(`team.json`) 편집을 서랍에 둘지 | 예, 설정 탭에 — 역할은 운영자만 정한다(로어는 권한을 주지 않는다) | 열림 |

## 4. 작업 항목

| 항목 | 내용 | 완료 기준 |
|---|---|---|
| `cs/A` | 서버: 스키마와 값(`GET`) — `engine/character_settings/` 패키지 | 모든 출처의 항목이 한 응답에 나온다 |
| `cs/B` | 서버: 합쳐 쓰기(`PATCH`) + 판 남기기 + 되돌리기 | 항목 하나를 고치면 그 파일의 다른 내용은 그대로, 이전 판으로 되돌릴 수 있다 |
| `cs/C` | 화면: 서랍의 세 탭을 스키마로 그리기, 손으로 그린 편집 칸과 `saveCharacterInline` 대체 | 서랍에서 모든 항목을 보고 고친다. agy #888이 끝난 뒤 |
| `cs/D` | 되돌리기 화면: 항목의 판 목록과 되돌리기 | 한 번에 이전 판으로 |

순서: cs/A → cs/B → (#888 뒤) cs/C → cs/D.
