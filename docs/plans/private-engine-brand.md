# Private Engine 브랜드·도메인 검토 (2026-09-27)

> 방향 (align/D, 2026-09-28): **기반** — Steam 출시 이름·도메인·상표. 공개 얼굴은 개인화 하네스

- **상태:** `active`
- **작성:** 2026-09-27 (대화 스캔 기록) · **갱신:** 2026-09-30 (운영자 검토: 1순위 대안 후보 `Persona Engine` 추가 및 '사적인 대화' 본질 보존 과제)
- **범위:** 공개 웹·레지스트리 스캔 기반 **채택 가능성** 메모. **법적 클리어런스 아님.** 법률 자문 아님.
- **관련:** [`docs/CONCEPT.md`](../CONCEPT.md) (가칭 Private Engine / PE)

## 1. 브랜드명 후보군

| 표기 | 약칭 | 성격 및 포지셔닝 |
|---|---|---|
| **Private Engine** | PE | 기존 가칭. '사적인 대화(Private Intimacy & Local Privacy)'라는 구매 동기를 직접 타격. B2B 보안 툴 연상 리스크 |
| **Persona Engine** | PE | 1순위 대안 후보 (2026-09-30). Wallpaper Engine 대칭("배경 대신 페르소나를 구동"), 툴/설정 유연성 극대화, 약칭 `PE` 및 자산 100% 계승. 단, '사적 대화' 훅 희석 및 상표/도메인 선점 이슈 검토 필요 |
| **Personal Engine** | PE | 절충안. PC(Personal Computer)처럼 '오직 나만을 위한' 사적인 엔진. |

공개 스캔 기준으로 채택 가능성을 비교 검토 중이며, 상표·법인 등록·변호사 검토는 별도.

## 2. 운영자 핵심 의도: '사적인 대화'의 가치 보존 (2026-09-30)

- **핵심 문제의식**: 사용자가 스팀에서 지갑을 여는 결정적 이유(Killer Feature)는 **"빅테크 검열도, 서버 기록도 없는 내 기기 안에서의 가장 깊은 사적인 대화(Private Intimacy)"**이다.
- **딜레마**: `Persona Engine`은 툴로서의 중립성과 직관성(어떤 캐릭터든 담는 그릇)은 완벽하지만, 타이틀에서 '사적인 대화'라는 가장 뜨거운 구매 훅이 희석될 위험이 있다.
- **조화 및 브랜딩 해법안**:
  1. **안 A (타이틀 툴 + 태그라인 사적 가치)**: 메인 타이틀 `Persona Engine (PE)` + 공식 태그라인 *"Your Private AI Persona Platform"* / *"내 PC에만 존재하는 가장 사적인 인격들"*. 스팀 플랫폼 심사는 중립 툴로 통과하고 마케팅 카피로 킬러 피쳐 타격.
  2. **안 B (원래 훅 유지 + 서브타이틀 툴 명시)**: 메인 타이틀 `Private Engine: AI Persona & Companion`.
  3. **안 C (융합형)**: `Personal Engine (PE)`.

## 3. 레지스트리·플랫폼 스캔 (2026-09-30 갱신)

| 대상 | Private Engine | Persona Engine | 비고 |
|---|---|---|---|
| Steam | exact 0건 (대부분 clear) | exact 0건 | 단, 'Persona' 검색 시 세가/아틀러스 게임이 스팀 검색을 지배함 |
| npm | exact 대부분 clear | exact 확인 필요 | - |
| PyPI | exact 대부분 clear | exact 확인 필요 | - |
| crates.io | exact 대부분 clear | exact 확인 필요 | - |
| GitHub | exact 대부분 clear | exact 확인 필요 | - |
| 기존 제품 충돌 | ScummVM 코드네임 | **BearingPoint Persona Engine** (유럽 대형 컨설팅펌 B2B 솔루션 상용 운영 중) | 상표/상호 인접 혼동 리스크 |

## 4. 도메인 상태 (2026-09-30 갱신)

| 도메인 | 상태·메모 |
|---|---|
| **privateengine.ai** | **NXDOMAIN → 등록 가능** (Private 계열 1순위) |
| privateengine.com | 애프터마켓 매물 수준 약 $10k |
| PrivacyEngine.io | SaaS 충돌 (유사 명칭 운영 중) |
| **personaengine.com** | **TAKEN** — BearingPoint 사가 `https://personaengine.com/en/`로 실제 서비스 운영 중 |
| **personaengine.ai** | **TAKEN / PARKED** — 2026-09-20 Atom.com 통해 등록되어 파킹 중 |
| personaengine.app | NXDOMAIN (등록 가능) |
| pe.ai | TAKEN |

짧은 약어(`pe.ai` 등)는 확보 못하면 손해가 크므로 본명(`privateengine.*` 또는 `personaengine.*`) 축으로 검토.

## 5. 상표·법적 리스크 및 문화권별 검토 과제 (2026-09-30)

1. **ATLUS(SEGA)의 『Persona』 상표권 충돌 리스크 (최우선 과제)**:
   - 세가/아틀러스가 게임 및 엔터테인먼트 소프트웨어 분류(Nice 9류, 41류 등)에서 전 세계적으로 보유한 『Persona』 상표와의 저촉/이의 제기 가능성.
   - 스팀 상점에 'Persona Engine'으로 등록 시 상표 분쟁 회피 가능 여부(변호사 검토 필요).
2. **BearingPoint 사의 'Persona Engine' 상표권 조사**:
   - `personaengine.com`을 운영하는 BearingPoint 사가 상표를 출원/보유하고 있는지 확인 필요.
3. **문화권별 인식 및 수용성**:
   - **영어권 (US/EU)**:
     - `Private`: "Privacy-first & Uncensored (검열 없는 로컬 프라이버시)"라는 기술적·심리적 소구력이 매우 강력.
     - `Persona`: 융 심리학, UX 사용자 모델, 아틀러스 게임 이미지가 혼재.
   - **일본/동아시아권**:
     - `Private(プライベート)`: '사적인 시간', '둘만의 비밀 공간'이라는 감성적·낭만적 뉘앙스가 긍정적.
     - `Persona(ペルソナ)`: 대다수 게이머가 아틀러스 RPG 게임 프랜차이즈로 직결하여 인식함.

## 6. 현재 기울기 (운영자)

- **핵심 방향**: `Persona Engine`을 1순위 대안 후보로 상정하되, '사적인 대화(Private)'라는 제품의 진짜 킬러 피쳐가 희석되지 않도록 서브타이틀/태그라인과의 결합 구조 검토.
- **선행 조건**: ATLUS 『Persona』 상표 충돌 여부 및 BearingPoint 기사용 상태, 문화권별 느낌에 대한 추가 법률/시장 검토 선행.

## 7. 다음 액션 (착수는 실장님 말)

1. ATLUS(SEGA) 『Persona』 상표(9류/41류) 스팀 내 상표권 충돌 리스크 법적 자문/선행 조사
2. BearingPoint Persona Engine 및 Atom.com 파킹된 `personaengine.ai` 현황 모니터링
3. 타이틀(`Persona Engine`) + 태그라인(`Your Private AI Companion / Persona`) 결합안의 마케팅 핏 검증
4. `privateengine.ai` 선점 여부 최종 판단

## 8. 스캔 메타

- **1차 스캔일:** 2026-09-27 (Private Engine 축)
- **2차 스캔일:** 2026-09-30 (Persona Engine 대안 후보, whois.nic.ai 및 DNS/HTTP 실시간 조회 반영)
- **출처:** 대화 중 공개 스캔 및 DNS/HTTP/WHOIS 조회
- **면책:** 법적 조언 아님 · 상표 클리어런스 아님 · 채택 가능성 메모만

## 9. 이중 의미·몰입 로어 (메모)

- **이중 의미:** 제품·도구명(Steam 셸·BYOK 하네스)이자 로어上 상점·소환 창 이름 (전영소녀 '극락' 모티프).
- **마케팅:** soft marketing 유지. 연인·로어를 전면 카피에 두지 않음. 공개 얼굴 = 개인화 에이전트 하네스.
- **본문:** 숨은 컨셉·러프 골격은 [`docs/CONCEPT.md`](../CONCEPT.md) 「숨은 컨셉 / 몰입 로어 (러프)」. 여기서는 브랜드 교차만.
