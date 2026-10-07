# 현지화 (주요 언어)

> 방향 (align/D, 2026-09-28): **기반** — 엔드유저 배포에 필요. 프리메이드 기본 팩의 언어별 버전(l10n/K)은 첫인상과 직결

> 상태: **active** (초안 2026-09-27, D1–D7 결정)
> 목적: 엔진·화면·에이전트 답변을 주요 언어로 제공한다. 한국어는 여러 언어 중 하나가 된다(지금은 곳곳에 고정).
> 관련: [release-pipeline.md](release-pipeline.md)(Next: 기반, Pre-Steam: 번역·스토어) · [plan-execution-workflow.md](plan-execution-workflow.md)(형식·강제층) · [private-engine-brand.md](private-engine-brand.md)(외부 명칭)
> 방향 인용(G0, 범위 아님): [CONCEPT.md](../CONCEPT.md)의 캐릭터·로어 톤. 캐릭터 대사의 문체와 로어 번역은 이 계획의 항목이 아니다.
> 약칭: `l10n`

---

## 1. 범위 / 비목표

**범위**: 번역할 수 있게 만드는 구조(i18n) + 주요 언어 번역(l10n) + 언어별 품질 확인 + 강제 장치.

| 층 | 무엇 | 예 |
|---|---|---|
| L1 화면 | `static/` UI 문자열 | 버튼, 탭, 알림, 오류 |
| L2 서버 메시지 | 사용자에게 보이는 파이썬 문자열 | API 오류, 시스템 알림, 로그인 안내 |
| L3 답변 언어 | 에이전트가 사용자에게 답하는 언어 | 헌장·역할 절차의 "Reply in Korean" |
| L4 형식 | 날짜·시간·숫자, `<html lang>` | `toLocaleString('ko-KR')` |
| L5 기본 콘텐츠 | 새 설치에 들어가는 템플릿 캐릭터·팀 | `templates/`(user-data-separation) |
| L6 스토어 | Steam 페이지·스크린샷·설명 | Pre-Steam 단계 |

**비목표**
- 사용자가 만든 캐릭터 카드·기억·대화 번역: 사용자 데이터라 엔진이 번역하지 않는다
- 사적 모드의 문체·연출 규칙 재작성: 언어별 품질 확인(`l10n/H`)만 하고, 연출 내용은 [private-mode.md](private-mode.md) 소관
- 에이전트용 지침(헌장·절차·도구 설명) 번역: 원칙 0에 따라 영어 하나로 유지한다. 답변 언어만 변수로 바꾼다

---

## 2. 현황 점검 (2026-09-27)

| 확인 | 명령 | 결과 |
|---|---|---|
| UI의 한국어 줄 | `cat static/*.js static/index.html \| grep -cP '[\x{AC00}-\x{D7A3}]'` | **862줄**. 상위: `app-status.js` 127, `app-evolution.js` 122, `index.html` 110, `app.js` 60 |
| 서버의 한국어 줄 | 같은 grep, 루트·`providers/`·`tools/`의 `*.py` | `session.py` 96, `logdigest.py` 42, `worktree_runner.py` 33, `account_login.py` 32, `server.py` 29 … (사용자용과 로그용이 섞여 있음) |
| 날짜 형식 고정 | `grep -n "ko-KR" static/*.js` | `toLocale*('ko-KR')` 6곳, `<html lang="ko">` |
| 답변 언어 지시 | `grep -rn "in Korean"` | `data/workspace/roles/pd/procedure.md`, `characters.py` 기억 요약 프롬프트 등. 사용자 언어 설정은 없음 |
| 페르소나 말투가 엔진 문자열에 섞임 | `grep -rn "냥" static/*.js *.py` | **58줄**(예: "연결이 끊겼다냥"). 엔진 문자열과 캐릭터 말투가 분리돼 있지 않다(페르소나 이름·말투는 표시값이라는 원칙과도 충돌) |
| i18n 기반 | 카탈로그·`t()` 함수·언어 설정 검색 | 없음 |
| 사적 모드의 언어 고정 | `private_engine.py` Grok 오버레이 | "Korean only" 규칙(#241). 다른 언어 사용자에게는 오동작 |

---

## 3. 선행 사례와 채택 판단

| 사례 | 무엇 | 판단 |
|---|---|---|
| [i18next](https://www.i18next.com/) | JS i18n 표준급 라이브러리, 복수형·보간·폴백 | **후보**(D3). `static/vendor/`에 넣으면 빌드 도구 없이 쓸 수 있음 |
| 자체 `t(key, vars)` + JSON 카탈로그 | 수십 줄짜리 최소 구현 | **후보**(D3). 의존성 없음, 복수형은 `Intl.PluralRules`로 해결 |
| Python `gettext` / [Babel](https://babel.pocoo.org/) | 서버 문자열 카탈로그 | **적응**: 서버 사용자 문자열은 수가 적어 UI와 같은 JSON 카탈로그를 공유하는 편이 SSOT에 유리 |
| [Project Fluent](https://projectfluent.org/), ICU MessageFormat | 문법이 복잡한 언어용 메시지 형식 | **보류**: 지금 규모에는 과함. 복수형·성별 문제가 실제로 생기면 재검토 |
| `Intl.DateTimeFormat` / `Intl.NumberFormat` | 브라우저 내장 형식 | **채택**(L4) |
| Steam 지원 언어 목록 | 스토어 언어 표기와 요구 사항 | **참고**(L6, Pre-Steam) |

---

## 4. 결정 (2026-09-27 운영자: 전부 추천안 채택)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | "주요 언어"는 어디까지인가? | **1차: 한국어 + 영어**(영어가 폴백). **2차: 일본어, 중국어 간체.** 이후 수요에 따라 번체·스페인어 등 | 결정 2026-09-27 (ADR 소급: pew/H) |
| D2 | 원문 언어와 키 체계는? | **의미 기반 키**(`chat.send`, `ticket.approve`). 한국어 문장을 키로 쓰지 않는다. 폴백은 영어 | 결정 2026-09-27 (ADR 소급: pew/H) |
| D3 | UI 라이브러리는? | **자체 `t()` + JSON 카탈로그**(의존성 0, 문자열 수백 개 규모). 복수형·보간 요구가 커지면 i18next로 교체 | 결정 2026-09-27 (ADR 소급: pew/H) |
| D4 | 사용자 언어는 어떻게 정하나? | 설정값이 우선이고, 없으면 브라우저 언어, 그것도 없으면 영어. 설정은 사용자 데이터(`$CHATBOT_DATA`)에 저장 | 결정 2026-09-27 (ADR 소급: pew/H) |
| D5 | 에이전트 답변 언어는? | 사용자 언어 설정을 주입(`Reply to the user in {language}.`). 캐릭터 카드가 언어를 지정하면 그 설정이 우선 | 결정 2026-09-27 (ADR 소급: pew/H) |
| D6 | 번역은 누가 하나? | 초벌은 LLM, 한국어·영어는 운영자 검수, 2차 언어는 스토어 출시 전 원어민 검수(외주) | 결정 2026-09-27 (ADR 소급: pew/H) |
| D7 | 페르소나 말투가 섞인 엔진 문자열(58줄)은? | 엔진 문자열은 중립 문구로 바꾸고, 말투는 캐릭터 카드가 맡는다(현지화 전에 분리) | 결정 2026-09-27 (ADR 소급: pew/H) |

---

## 5. 작업 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `l10n/A` | 이 문서 + INDEX 행 + release-pipeline 연결 | `docs/plans/localization.md`, `docs/plans/INDEX.md`, `docs/plans/release-pipeline.md` | INDEX 행이 있고 커밋됨 | 0 · — | S | — | ✅ 티켓 없음(pew D3) |
| `l10n/B` | **래칫 가드**: 하드코딩 한국어 줄 수가 파일별 기준선보다 늘면 실패, 줄면 기준선을 낮춘다(`--update`는 낮추기만). 의도된 줄은 `l10n-ok` | `tests/test_ratchets.py`, `ratchet_baseline.json` (align/E와 한 장치) | 새 한국어 하드코딩을 추가하면 실패 | 3 · — | S | — | ✅ #276 |
| `l10n/C` | i18n 기반: 카탈로그 `static/i18n/<lang>.json`, `t()`, 언어 결정(D4), `Intl` 형식 헬퍼, `<html lang>` | `static/i18n/`, `static/app-i18n.js`, `static/index.html` | `?lang=en`으로 열면 이미 옮긴 문자열이 영어로 나옴 | 0 · — | M | D1–D4 | ✅ 2026-10-06 #730 — `app-i18n.js`(`tr()` — 처음엔 `t()`였으나 화면 코드에 지역 변수 `t`가 101곳이라 #731에서 `tr`로, `i18nTable()`, `data-i18n*`, `fmtNumber/fmtTime/fmtDate`), `static/i18n/ko.json`·`en.json`, `test_l10n_catalogs`. 언어는 `?lang=` → 이 브라우저에 남긴 값 → 브라우저 언어 → 영어. D4의 "사용자 데이터에 저장"은 설정 화면이 생길 때(지금은 브라우저별) |
| `l10n/D` | 페르소나 말투 분리: 엔진 문자열 58줄을 중립 문구로 | `static/*.js`, `*.py` | `grep "냥"` 결과가 엔진 코드에서 0건(카드 제외) | 2 · ⚡ | M | D7 | 대기 |
| `l10n/E` | UI 문자열 이관(파일 단위 티켓 여러 장, 큰 파일부터) | `static/app-*.js`, `index.html` | 파일마다 래칫 기준선이 0으로 내려감 | 0 · — | L → 파일별 S/M | l10n/B, C, D | ✅ 2026-10-07 #731–#753 — 화면 파일 래칫 기준선 0(서버가 단어로 비교하는 app-device.js 기기 종류 1줄만 l10n/F로). 이관 순서: app-evolution.js ✅ #731, app-status.js ✅ #732, index.html ✅ #733, app-team.js ✅ #738, app.js ✅ #739, app-sse.js ✅ #740, app-session.js ✅ #741, app-messages.js ✅ #742, app-characters.js ✅ #743, slash.js ✅ #744, app-activity.js ✅ #745, artifacts.js ✅ #746, markdown.js ✅ #749, service-log.js ✅ #750, app-sessions-tab.js·app-api.js·app-turn.js ✅ #751, 작은 화면 파일들과 CSS ✅ #752, 예외 표시 표(l10n-ok) ✅ #753 |
| `l10n/F` | 서버 사용자 메시지 이관(로그용 문자열은 영어로 통일하고 이관 대상에서 제외) | `server.py`, `session.py`, `providers/` 등 | 서버가 사용자에게 보내는 문자열은 모두 카탈로그 키 | 3 · ⚡ | M | l10n/C | 진행 중 — 기반(i18n.py) #754, 로그인 흐름(account_login.py) #755, 세션 핵심(session.py·loop_guard·write_guard·turn_watchdog·adapter_base/agy) #756, 턴 진행(session_turn.py·session_weights.py) #757, 로그 다이제스트(logdigest.py) #758 |
| `l10n/G` | 답변 언어 변수화(D5): 헌장·절차·프롬프트의 "in Korean"을 설정값 주입으로 | `instructions.py`, `characters.py`, `data/workspace/roles/*/procedure.md` | 언어를 en으로 설정하면 새 세션의 답변이 영어 | 3 · ⚡ | S | D5 | 대기 |
| `l10n/H` | 언어별 품질 확인: 사적 모드의 언어 고정 규칙(#241 "Korean only") 등 언어에 묶인 규칙을 목록으로 정리. 수정은 private-mode 계획에서 | 이 문서 §2 갱신 | 언어에 묶인 규칙 목록 + 담당 계획 링크 | 0 · — | S | — | 대기 |
| `l10n/I` | 영어 카탈로그 완성(1차) + 운영자 검수 | `static/i18n/en.json` | 래칫 기준선 0 + 누락 키 0(`test_l10n_catalogs`) | 0 · — | M | l10n/E, F | 대기 |
| `l10n/J` | 2차 언어(ja, zh-Hans) 초벌 + 원어민 검수 | `static/i18n/ja.json`, `zh-Hans.json` | 누락 키 0 | 0 · — | M | l10n/I, D6 | 대기 |
| `l10n/K` | 기본 템플릿 콘텐츠(L5)의 언어별 버전 | `templates/` | 새 설치가 설정 언어의 기본 캐릭터로 시작 | 0 · — | S | uds 템플릿 단계 | 대기 |

강제 장치(plan-execution-workflow §0 원칙):
- `test_ratchets`(l10n): 하드코딩된 한국어는 **줄어들 수만 있다**. 기준선(2026-09-28) 1,303줄(UI 893, 서버 410)에서 시작해 0을 향한다.
- `test_l10n_catalogs`(`l10n/C`에서 먼저 추가, 2026-10-06 #730): 모든 언어 카탈로그가 같은 키·같은 자리표시자를 가지고, 코드가 글자 그대로 쓰는 키(`t('…')`, `data-i18n*`)가 카탈로그에 있다. `t('prefix.' + 값)`처럼 조합하는 키는 그 값 목록을 아는 테스트가 확인한다(`test_handoff_bar` 상태, `test_context_panel` 레이어·이유).

---

## 6. 의존·순서·리스크

```text
B(래칫, 지금 바로) ─┐
D1–D4 결정 → C(기반) → D(말투 분리) → E(UI 이관, 파일별) ┬→ I(영어 완성) → J(2차 언어)
                         F(서버 메시지) ────────────────────┘
D5 결정 → G(답변 언어)            H(언어 묶인 규칙 목록)          K(템플릿, uds 이후)
```

- **B를 가장 먼저 한다.** 이관을 시작하기 전부터 새 하드코딩이 늘지 않게 막아야, 작업이 끝날 때까지 기준선이 뒤로 밀리지 않는다.
- 리스크: 문자열 이관은 화면 테스트(N2에서 고친 하네스들)가 소스 문자열을 직접 검사하는 곳에서 깨질 수 있다. 이관 티켓마다 `run-tests.sh`를 돌리고, 테스트도 키 기준으로 바꾼다.
- 리스크: 사적 모드는 언어별로 문체 품질이 크게 다르다. 번역만으로는 부족하므로 언어별 확인(H)을 스토어 출시 조건에 넣는다(release-pipeline Pre-Steam).
- release-pipeline과의 관계: **Next**에서 B·C·D, **Pre-Steam 전**에 I·J·L6 스토어.
