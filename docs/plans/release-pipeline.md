# Private Engine 릴리스·배포 파이프라인 (계획)

> 상태: **active** (2026-09-27)
> 목적: 엔진/사용자 데이터 분리 이후 **언제·무엇을** 배포 가능하게 할지 로드맵. 구현 착수 전 계획만.
> 관련: [user-data-separation.md](user-data-separation.md) · [private-engine-brand.md](private-engine-brand.md) · [concept.md](../concept.md) · [user-data-and-editing.md](user-data-and-editing.md) §1

---

## 1. Now (현재 · 내부)

| 항목 | 메모 |
|---|---|
| 저장소 | **private** — PII·개인 기억·세션이 `data/`에 혼재. 공개 금지 |
| 버전 | `VERSION` + `CHANGELOG` + git tag 관례 (도입·유지) |
| 릴리스 노트 | `RELEASE.md` (또는 CHANGELOG와 역할 분담 명시) |
| 테스트 | `run-tests.sh` — 로컬/호스트 일관 진입점 |
| 배포 검증 | `chatbot-ctl.sh repair` → smoke (의사 응답·기본 API) |
| 비밀 템플릿 | `secrets.env.example` (실키 없음, git 추적) |

※ Now 표는 **목표 관례**와 **이미 있는 조각**을 함께 적는다. 빠진 파일이 있으면 Next에서 채운다. 코드 착수 전에 본 문서·user-data-separation을 SSOT로 본다.

---

## 2. Next (1–2개월)

| 항목 | 메모 |
|---|---|
| 기본 데이터 경로 | `CHATBOT_DATA` 기본값 **`~/.pe`** ([user-data-separation.md](user-data-separation.md) §0) |
| 마이그레이션 | `tools/migrate_user_data.py` — 기존 `$CODE/data` → `~/.pe` (멱등·백업) |
| 템플릿 부트스트랩 | 빈 `~/.pe`에 `templates/` 복사 |
| gitignore | 저장소 `data/` 전면 제외 + 커밋 가드(PII/비밀 패턴) |
| 최소 CI | 테스트 + 린트/가드 정도 (배포 파이프라인 전체는 아직) |
| ctl | `DATA="$CODE/data"` 하드코딩 제거 — 개발은 `CHATBOT_DATA=$CODE/data` |

개발 오버라이드·Windows `%USERPROFILE%\.pe`·`PE_HOME`/`PRIVATEENGINE_HOME` 별칭은 user-data-separation SSOT.

---

## 3. Pre-Steam (브랜드·도메인 이후)

| 항목 | 메모 |
|---|---|
| 씬 런처 | 엔진을 감싸는 thin launcher (호스트/포트/데이터 경로) |
| 인스톨러 | OS별 설치·업데이트 (코드 ↔ `~/.pe` 분리 전제) |
| 코드 서명 | 플랫폼 요구에 맞는 signing |
| Steam | **브랜드·도메인 클리어런스 후** ([private-engine-brand.md](private-engine-brand.md)). 상표≠도메인 — 변호사 전 스케일 금지 |

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
