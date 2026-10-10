# 플러그인 아키텍처와 창작마당

> 방향 (align/D, 2026-09-28): **핵심** — 기조의 「확장성」 축이자 Wallpaper Engine 포지션의 해자(창작마당 플랫폼). 개인화 레이어를 남이 만들어 더할 수 있게 한다

> 상태: **active** (초안 2026-09-28)
> 목적: 코어를 어댑터로 짜서 주요 레이어를 모두 사용자가 플러그인으로 더하고, 콘텐츠부터 Steam Workshop에서 교환하게 한다. 이 문서는 설계와 순서다. 구현은 항목별 티켓으로.
> 관련: [../VISION.md](../../VISION.md) 「확장성」·「해자」 · [../ARCHITECTURE.md](../../ARCHITECTURE.md)(레이어·어댑터 명세, 출발점) · [direction-alignment.md](direction-alignment.md) D8·align/J · [user-data-separation.md](archive/2026/user-data-separation.md)(`~/.pe`) · [release-pipeline.md](release-pipeline.md)(Steam은 브랜드 이후) · [localization.md](localization.md)
> 방향 인용(G0): 숨은 로어의 「테이프」(카드·세이브·에셋 = 소환 매체)는 콘텐츠 플러그인의 몰입 표현으로 쓸 수 있다. 로어 세부는 이 계획의 항목이 아니다.
> 약칭: `plug`

---

## 1. 범위 / 비목표

**범위**: 플러그인의 종류·형식(매니페스트)·버전·권한, 레이어별 인터페이스, 로딩 위치와 순서, 코드 플러그인의 격리, 창작 도구, 콘텐츠 등급, Workshop 단계.

**비목표**
- 엔진 코드를 고치는 플러그인. 배포판의 에이전트와 플러그인은 엔진을 **바꾸지 않고 확장**만 한다(VISION 「배포판과 개발판」).
- 자체 마켓 서버·결제. 교환은 Steam Workshop(과 로컬 파일)으로.
- 코드 플러그인의 Workshop 교환(격리·권한이 준비되기 전까지, D3).
- 지금 레이어 전체를 한 번에 재작성. 기존 어댑터를 같은 API로 **옮겨 가며** 연다.

## 2. 현황 점검 (2026-09-28)

| 레이어 | 지금 있는 연결부 | 부족한 것 |
|---|---|---|
| LLM 프로바이더 | `providers/adapter_base.py::AgentAdapter`(약 20개 메서드) + 등록부 `providers/adapters.py::AGENT_ADAPTERS`, HTTP 계열은 `data/providers.json` 설정만으로 추가 | 엔진 밖에서 불러오기, 공개할 최소 인터페이스, 버전 |
| 외형·렌더러 | `static/visual-adapter.js`의 `VisualAdapter`(`load`·`setEmotion`·`speak`·`destroy`) + `AdapterRegistry`, `static/visual-sprite-adapter.js` | 사용자 폴더의 렌더러·외형 팩 로딩 |
| 미디어 소스 | `register_media_source`(프로바이더별 이미지 위치) | 내부 전용 |
| 도구 | MCP 서버 `mcp_server.py` + 코어 도구 `mcp_core.py` + 호스트 플러그인 `nas_mcp_host.py`(파일이 있으면 로드, `NAS_MCP_HOST_PLUGIN=0`으로 끔) | 외부 MCP 서버 연결 UX, 권한 |
| 콘텐츠 | 캐릭터 카드 V2(`characters/<id>/card.json`), ST PNG 가져오기(`tools/st_import.py`), 로어북, 스킬 `SKILL.md`, 역할 팩(`roles/<role>/role.md`), 테마 7종(CSS 내장) | 패키지 형식, 설치·제거·업데이트, 테마·보이스 팩의 외부 로딩 |
| 기억·TTS·STT·저장·세션 | [ARCHITECTURE.md](../../ARCHITECTURE.md) §3.3–3.7에 명세만 | 구현 없음 |

요약: 연결부는 대부분 **엔진 안의 파일**을 부른다. 사용자 폴더(`~/.pe/plugins`)에서 불러오는 구조, 매니페스트, 플러그인 API 버전, 권한은 아직 없다.

## 3. 선행 사례와 채택 판단

| 사례 | 무엇 | 판단 | 가져올 것 |
|---|---|---|---|
| [Wallpaper Engine](https://store.steampowered.com/app/431960/) + Workshop | 저가 앱 + 사용자 콘텐츠 교환. 웹 월페이퍼는 브라우저(CEF) 안, 씬 스크립트(SceneScript)는 제한된 JS | **채택(롤모델)** | 콘텐츠 우선 교환, 스크립트는 샌드박스 안에서만, 편집기(창작 도구)가 생태계의 엔진, 연령 등급 태그 |
| [VS Code 확장](https://code.visualstudio.com/api) | `package.json` 매니페스트(`contributes`·`activationEvents`), **별도 프로세스(Extension Host)**, 엔진 버전 범위 `engines.vscode` | **채택(코드 플러그인 모델)** | 매니페스트에 기여 지점과 권한 선언, 코드 플러그인은 별도 프로세스, 플러그인 API 버전 범위 |
| [SillyTavern 확장](https://docs.sillytavern.app/for-contributors/writing-extensions/) | `manifest.json` + 브라우저 JS(샌드박스 없음). 서버 플러그인은 설정으로 켜야 함 | **참고(생태계 호환)** | 카드·로어북·프리셋은 그대로 가져온다(ST 위임). 무제한 실행 모델은 따르지 않는다 |
| [Obsidian 플러그인](https://docs.obsidian.md/Plugins/Getting+started/Build+a+plugin) | `manifest.json`, 프로세스 안에서 제한 없이 실행, 커뮤니티 목록 심사 | **부분 참고** | 매니페스트 필드(`id`·`version`·`minAppVersion`), 커뮤니티 목록 심사. 무제한 실행은 따르지 않는다 |
| [MCP](https://modelcontextprotocol.io/) | 도구·자원을 별도 프로세스 서버로 표준화 | **채택(도구 플러그인)** | 도구 플러그인 = MCP 서버. 새 형식을 만들지 않는다(생태계 진입, VISION) |
| Agent Skills `SKILL.md` | 스킬 패키지 표준 | **채택(스킬)** | 이미 쓰는 형식 그대로 가져오기·내보내기 |

## 4. 설계 초안

### 4.1 두 종류의 플러그인

| 종류 | 예 | 실행 | 교환 |
|---|---|---|---|
| **콘텐츠** (데이터만) | 캐릭터 카드, 로어북, 스킬, 외형 팩(스프라이트·스테이지), 보이스 팩(설정), UI 테마(CSS 변수), 역할 팩, 지침 팩 | 실행 없음. 스키마 검증만 | Workshop 1단계 |
| **코드** | 프로바이더 어댑터, 렌더러(2.5D·VRM), TTS·STT 엔진, 기억 백엔드, 도구(MCP 서버) | **별도 프로세스**, 권한 선언, 사용자 승인 | 격리·권한·서명 준비 후(D3) |

### 4.2 패키지 형식 (초안)

```text
<plugin-id>/
├── pe-plugin.json      # 매니페스트
├── ...                 # 종류별 파일 (card.json, SKILL.md, sprites/, theme.css, server entry, …)
└── preview.png         # Workshop·목록 미리보기
```

`pe-plugin.json` 필드 초안: `id`(역도메인 또는 slug), `name`, `version`(semver), `kind`(`character`|`lorebook`|`skill`|`visual-pack`|`voice-pack`|`theme`|`role-pack`|`provider`|`renderer`|`tts`|`stt`|`memory`|`tool`), `engine`(지원하는 플러그인 API 범위, 예 `^1.0`), `rating`(D5), `permissions`(코드 플러그인만: 네트워크·파일·기억 읽기·기억 쓰기·오디오 등), `entry`(코드 플러그인의 시작 명령), `locales`(지원 언어).

ST 카드(PNG)·로어북(JSON)·`SKILL.md`는 **매니페스트 없이도** 가져온다. 가져올 때 엔진이 매니페스트를 만들어 붙인다(ST 위임, 쉬운 진입).

### 4.3 레이어별 인터페이스

- 내장 기능도 **같은 API**로 돈다. 내장 스프라이트 렌더러, 내장 프로바이더, 기본 캐릭터 팩이 플러그인 API의 첫 사용자다. 내장만 특권을 가지면 API가 낡는다.
- 공개 인터페이스는 **최소**로. 예: 프로바이더는 지금 `AgentAdapter`의 약 20개 메서드 중 외부에 약속할 최소 집합만 공개 API로 고정하고, 나머지는 내부로 남긴다.
- 플러그인 API는 semver. 매니페스트의 `engine` 범위로 호환을 판단하고, 맞지 않으면 설치를 거절하며 이유를 알린다.

### 4.4 로딩

- 위치: `$CHATBOT_DATA/plugins/<id>/`(배포 기본 `~/.pe/plugins`). Workshop 구독분은 Steam이 내려받은 경로를 같은 방식으로 등록한다.
- 순서: 내장 → 로컬 → Workshop. 같은 `id`는 사용자가 고른 것 하나만 켠다.
- 콘텐츠 플러그인은 켜고 끄는 데 재기동이 필요 없다. 코드 플러그인은 별도 프로세스를 띄우고 내린다.
- 개인화 레이어 보존: 사용자가 플러그인 콘텐츠를 고친 결과는 원본 패키지가 아니라 사용자 데이터에 쌓인다. 플러그인이 업데이트돼도 사용자의 수정은 남는다(VISION 「내 것」).

### 4.5 창작 도구와 등급

- 창작 도구: 캐릭터(카드 폼 편집 — [user-data-and-editing.md](archive/2026/user-data-and-editing.md)), 외형 팩(스프라이트 규격 검사 `tools/check_character_art.py` 재사용), 로어북, 스킬, 테마. 결과물을 바로 `pe-plugin.json` 패키지로 내보낸다.
- 에이전트의 역할(개인화 사다리): 사용자와 대화하며 캐릭터·스킬·외형 팩을 만들고, 원하면 패키지로 묶어 준다.
- 콘텐츠 등급: 매니페스트 `rating`(예: `general`·`mature`·`adult`) + Steam의 성인 콘텐츠 정책. 사적 모드 규칙이 든 캐릭터는 기본 `mature` 이상. 기본값은 등급 높은 콘텐츠를 숨김.

## 5. 결정 (2026-09-28 운영자: 전부 추천안 채택)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 매니페스트 이름·형식 | `pe-plugin.json`(JSON, 필드는 §4.2 초안). ST·`SKILL.md`는 매니페스트 없이 가져오고 엔진이 붙인다 | 결정 2026-09-28 (운영자: 추천대로) |
| D2 | 첫 공개 레이어 | **콘텐츠**부터: 캐릭터·외형 팩·테마·스킬·로어북. 프리메이드 기본 팩을 이 형식으로 만드는 것이 첫 사용자 | 결정 2026-09-28 (운영자: 추천대로) |
| D3 | 코드 플러그인 격리 | 별도 프로세스 + 매니페스트 권한 + 사용자 승인. 도구는 MCP 서버로. Workshop 교환은 서명·심사 방식이 정해진 뒤 | 결정 2026-09-28 (운영자: 추천대로) |
| D4 | 공개 API 범위 | 레이어마다 최소 인터페이스만 v1으로 고정. 프로바이더는 `AgentAdapter`에서 최소 집합 선별 | 결정 2026-09-28 (운영자: 추천대로) |
| D5 | 콘텐츠 등급 | `general`·`mature`·`adult` 3단계 + Steam 정책. 기본값은 높은 등급 숨김 | 결정 2026-09-28 (운영자: 추천대로) |
| D6 | Workshop 시점 | 브랜드 클리어런스 이후(release-pipeline). 그 전에는 로컬 폴더 설치와 파일 공유로 형식을 검증 | 결정 2026-09-28 (운영자: 추천대로) |

## 6. 작업 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `plug/A` | 이 문서 + INDEX 행, ARCHITECTURE·정렬 계획 연결 | `docs/plans/plugin-architecture.md`, `docs/plans/INDEX.md`, `docs/plans/direction-alignment.md` | INDEX 행, 커밋 | 0 · — | S | — | ✅ 티켓 없음(pew D3) |
| `plug/B` | 매니페스트 스키마 + 검증기(콘텐츠 종류 먼저) | 새 모듈, `tests/` | 잘못된 매니페스트는 이유와 함께 거절 | 2 · — | M | D1 | 대기 |
| `plug/C` | 로컬 로딩: `$CHATBOT_DATA/plugins/` 스캔, 켜기·끄기, 같은 `id` 충돌 처리 | 새 모듈, `server.py` 라우트 | 폴더에 넣은 테마·캐릭터 팩이 목록에 뜨고 켜짐 | 2 · ⚡ | M | plug/B, uds | 대기 |
| `plug/D` | 내장 기능을 같은 API로: 테마 7종과 기본 캐릭터를 콘텐츠 플러그인 형식으로 | `static/`, `templates/` | 내장 테마·기본 캐릭터가 플러그인 목록에 같은 방식으로 뜸 | 2 · ⚡ | M | plug/C | 대기 |
| `plug/E` | 가져오기 경로 통합: ST 카드·로어북·`SKILL.md`에 매니페스트 자동 부여 | `tools/st_import.py`, `card_upload.py` | 가져온 항목이 플러그인 목록에 뜸 | 2 · ⚡ | S | plug/C | 대기 |
| `plug/F` | 내보내기: 캐릭터·외형 팩·테마를 패키지로 | 새 모듈, UI | 내보낸 패키지를 다른 설치에서 가져오면 같게 보임 | 2 · ⚡ | M | plug/C | 대기 |
| `plug/G` | 프로바이더 공개 인터페이스 v1 선별(D4) | `providers/adapter_base.py`, 문서 | 최소 인터페이스 문서 + 내장 어댑터가 그것만으로 동작하는지 테스트 | 3 · — | M | D4 | 대기 |
| `plug/H` | 코드 플러그인 격리 설계(D3): 별도 프로세스·권한·승인 UX, 도구는 MCP | 새 계획 또는 이 문서 개정 | 운영자 검토 | 0 · — | M | D3 | 대기 |
| `plug/I` | 등급(D5)과 Workshop 연동 설계 | 이 문서 개정 | 운영자 검토, 브랜드 이후 착수 | 0 · — | S | D5, D6 | 대기 |

## 7. 의존·순서·리스크

```text
uds (~/.pe) ─┐
D1 → B(매니페스트) → C(로컬 로딩) → D(내장도 같은 API) → E(가져오기) · F(내보내기)
D4 → G(프로바이더 API)        D3 → H(코드 격리)        D5·D6 → I(등급·Workshop)
```

- 리스크: **API를 일찍 굳히면 되돌리기 어렵다.** 콘텐츠 형식부터 열고, 코드 인터페이스는 내장 어댑터로 충분히 써 본 뒤 v1로 고정한다.
- 리스크: **코드 플러그인 = 남의 코드가 사용자 PC에서 실행.** 격리 전에는 교환하지 않는다(D3).
- 리스크: 사적 콘텐츠의 교환은 Steam 정책·연령 게이트와 맞물린다(D5, release-pipeline 연령·약관).
- 교차: 현지화 — 매니페스트 `locales`와 카탈로그를 플러그인도 쓸 수 있게(l10n). 개인화 사다리(align/H) — 에이전트가 만든 결과물을 플러그인 패키지로 묶는 흐름.
