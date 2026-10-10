# Private Engine 릴리스·배포 파이프라인 (계획)

> 방향 (align/D, 2026-09-28): **기반** — 배포 경로(셸·설치기·Steam)와 사업 모델

> 상태: **active** (2026-09-27)
> 목적: 엔진/사용자 데이터 분리 이후 **언제·무엇을** 배포 가능하게 할지 로드맵. 구현 착수 전 계획만.
> 관련: [user-data-separation.md](archive/2026/user-data-separation.md) · [private-engine-brand.md](private-engine-brand.md) · [VISION.md](../../VISION.md) · [user-data-and-editing.md](archive/2026/user-data-and-editing.md) §1

---

## 1. Now (현재 · 내부)

| 항목 | 메모 |
|---|---|
| 저장소 | **private** — PII·개인 기억·세션이 `data/`에 혼재. 공개 금지 |
| 버전 | 루트 `VERSION`(`0.0.0-dev`) + `CHANGELOG.md` (2026-10-03 도입). git tag는 아직 없다. 코드는 `VERSION`을 읽지 않는다 |
| 릴리스 노트 | `RELEASE.md`는 아직 없다. 지금 변경 기록은 `CHANGELOG.md` |
| 테스트 | `run-tests.sh` — 로컬/호스트 일관 진입점 |
| 배포 검증 | `chatbot-ctl.sh repair` → smoke (의사 응답·기본 API) |
| 비밀 템플릿 | 루트 `secrets.env.example` (실키 없음, git 추적, 2026-10-03). 부트스트랩 복사본 `templates/secrets.env.example`은 아직 없다 |

※ 2026-10-03: `VERSION`·`CHANGELOG.md`·루트 `secrets.env.example`는 트리에 있다. `RELEASE.md`·git tag·`VERSION`을 읽는 코드는 없다. 원격 이력의 개인 데이터는 그대로라 푸시하지 않는다.

---

## 2. Next (1–2개월)

| 항목 | 메모 |
|---|---|
| 기본 데이터 경로 | `CHATBOT_DATA` 기본값 **`~/.pe`** ([user-data-separation.md](archive/2026/user-data-separation.md) §0) |
| 마이그레이션 | `tools/migrate_user_data.py` — 기존 `$CODE/data` → `~/.pe` (멱등·백업) |
| 템플릿 부트스트랩 | 빈 `~/.pe`에 `templates/` 복사 |
| gitignore | 저장소 `data/` 전면 제외 + 커밋 가드(PII/비밀 패턴) |
| 최소 CI | 테스트 + 린트/가드 정도 (배포 파이프라인 전체는 아직) |
| ctl | `DATA="$CODE/data"` 하드코딩 제거 — 개발은 `CHATBOT_DATA=$CODE/data` |
| 현지화 기반 | [localization.md](localization.md) `l10n/B`(래칫 가드)·`C`(카탈로그·`t()`)·`D`(말투 분리) |

개발 오버라이드·Windows `%USERPROFILE%\.pe`·`PE_HOME`/`PRIVATEENGINE_HOME` 별칭은 user-data-separation SSOT.

---

## 3. Pre-Steam (브랜드·도메인 이후)

| 항목 | 메모 |
|---|---|
| 씬 런처 | 엔진을 감싸는 thin launcher (호스트/포트/데이터 경로). 추천 스택: **Tauri(또는 Go+Wails) 얇은 셸 + 기존 Python 엔진 + 웹 UI**. 에이전트가 가장 잘 다루는 Python/TS를 유지하고, 성능 병목이 측정된 핫스팟만 나중에 포팅 |
| 인스톨러 | OS별 설치·업데이트 (코드 ↔ `~/.pe` 분리 전제). 형태는 OS별 Nuitka 바이너리, macOS 서명·공증 — [platform-portability.md](platform-portability.md) PP4·`pp/K` |
| 코드 서명 | 플랫폼 요구에 맞는 signing |
| 사적 보호 | **출시 관문** ([private-security.md](private-security.md)): 첫 외부 배포(배포판·창작마당 올리기) 전 `psec/B`(미리보기 가드)·`psec/D`(사적 데이터를 작업공간 밖으로)·`psec/F`(내보내기 허용 목록) 완료, 창작마당 올리기(R12)는 `psec/F` 뒤. 모드 잠금(비밀번호/생체)으로 UI·알림·최근 목록 가림, 로컬 대화 DB 암호화(키는 잠금 비밀번호에서 유도), BYOK 토큰은 OS 키체인(평문 금지), Steam 클라우드 동기화 기본 꺼짐·켤 때 별도 동의 — MVP 필수 |
| 연령·약관 | 연령 게이트, 약관, 스토어 페이지는 하네스로만(사적 수위 장면 게시 금지) |
| 현지화 완료 | 영어 카탈로그 완성·검수, 2차 언어, 스토어 페이지 언어, 언어별 사적 모드 품질 확인 ([localization.md](localization.md) `l10n/I`·`J`·`H`) |
| Steam | **브랜드·도메인 클리어런스 후** ([private-engine-brand.md](private-engine-brand.md)). 상표≠도메인 — 변호사 전 스케일 금지 |

---

## 3.1 사업 모델·진입·일정 가정 (2026-09-27 Grok 대화, 운영자 결정 포함)

| 항목 | 내용 |
|---|---|
| 판매 방식 | **Steam 저가 1회 구매 + BYOK**. 엔진과 UX를 팔고 모델비는 사용자 구독으로 넘긴다. 구독·자체 모델·웹 SaaS는 결제·검열·서버·CS 부담이 커서 1인 겸업에 맞지 않음. 무료 배포 + 기부는 채택하지 않음(운영자) |
| 가격 | **정가 $9.99**로 출시, 런칭·시즌 세일 $4.99–6.99(운영자 결정). 롤모델 Wallpaper Engine |
| 체험 경로 | 구글 계정만 있으면 Antigravity 무료 쿼터로 맛보기(주간 한도, 정확한 수치 비공개). Steam은 저가 셸 + 데모/체험 빌드. 결제 전에 「옆에 있는 존재」를 한 번 느끼게 하고, 고수위·저장·캐릭터 깊이는 구매 후 |
| 프로바이더 이중화 | 주력 데모는 Gemini, 폴백·고수위는 Grok(또는 로컬). 한 벤더의 정책 변화로 제품 전체가 무너지지 않게 |
| 공개 얼굴 | 스토어·마케팅 전면은 **개인화 가능한 에이전트 하네스·데스크톱 동반자·BYOK**. 사적 관계 기능은 그 안의 한 축이고 쓰임은 사용자 몫(운영자). 사적 수위는 커뮤니티·입소문으로 |
| 커뮤니티 (제품 가닥 이후) | 한 문장 + 15초 클립(오피스→프라이빗 전환) + Steam 페이지. 새 커뮤니티를 만들지 않고 이미 모인 곳(ST Discord/Reddit, 카드 제작자, Steam AI 토론)으로. 카드·프리셋 호환이 제작자 입소문을 만든다. 초기 목표는 팬 100명이 아니라 파워 유저 10명 |
| 일정 가정 (1인 겸업, 주 10–15시간) | MVP 3–6개월(셸·BYOK·카드 가져오기·사적 UX·모드 전환 뼈대·Steam 페이지) → 해자 1차 +4–8개월(자산 깊이·프로바이더 레이어 팩·비주얼 최소판·심사 대응). 합계 9–14개월. 비주얼·보이스·다프로바이더를 처음부터 넣으면 1.5–2년 |
| 직접비 가정 (인건비 제외) | 최소 ₩50–150만(Steam 등록·도메인·테스트 API) · 현실 MVP ₩200–500만(스토어 에셋·법무/성인 표기 자문 일부·업데이트 인프라) · 해자까지 ₩500–1,500만(외주 일러스트·리깅·QA·소액 마케팅) |

※ 일정·예산은 대화에서 나온 추정치다. 착수 계획이 아니라 범위 판단의 기준선으로만 쓴다.

---

## 4. 지금은 만들지 말 것 (What NOT)

- Steam 스토어 페이지·빌드 파이프라인 본격화 (브랜드/도메인 전)
- 공개 GitHub로의 강제 푸시·히스토리 재작성 (실장님 결정 전; PII 잔존)
- 두꺼운 데스크톱 셸 / Electron 포장 (thin launcher 이전 단계 없음)
- `~/.privateengine`을 기본 경로로 고정 (별칭만; 기본은 `~/.pe`)
- 원격 히스토리 scrub을 에이전트가 단독 수행
- 풀 SaaS·계정 서버·클라우드 동기 (로컬-first 기조와 별개 결정)

---

## 5. 의존·순서

```text
user-data-separation (경로·migrate·ctl·gitignore)
        ↓
  Next: ~/.pe 기본 + 최소 CI
        ↓
private-engine-brand (이름·도메인·클리어런스)
        ↓
  Pre-Steam: launcher · installer · signing · Steam
```

concept의 열린 축(언제 어디서나 접속 등)과 맞물리되, **배포 파이프라인은 본 문서가 SSOT**.

---

## 6. 실장님 경로 한 줄

배포 기본 **`~/.pe`** · 개발 **`CHATBOT_DATA=$CODE/data`** · env 별칭 `PE_HOME`/`PRIVATEENGINE_HOME` 선택 · ctl 하드코딩 금지 · Windows `%USERPROFILE%\.pe` · Steam은 브랜드 이후.
