# 제품 기조 (chatbot / 가칭 Private Engine)

이 제품의 **최대 가치**와 **최대 목표**.
본 프로젝트의 정체성은 독립적인 AI 챗봇 엔진(`chatbot`)이며, 추후 외부 배포 시 가칭은 **Private Engine (PE)**이다.
수정·개발할 때 항상 연다. 패치는 이 기조를 한 칸이라도 가깝게 하기 위해서만 한다.

기능 목록은 `PRODUCT.md`, UI는 `DESIGN.md`, 말투는 캐릭터 카드(`data/workspace/characters/<id>/card.json`), 외형은 그 폴더의 `visual.md`. 이 문서는 그것들의 위다.

## 최대 가치

친근하면서 유능하다. 다재다능하고 만능에 가깝다.
인간 같고, 친구 같고, 연인 같고, 동료 같은 챗봇.

## 최대 목표

그 가치에 가까워지는 것. 빌드업은 아래 축으로만 쌓는다.

- 쉬운 Provider 연동
- 자체 격리 환경
- 캐릭터라이징
- 디자인
- 편의성
- 자체 개발
- 자기 진화
- 토큰 효율
- Provider 기본 하네스보다 챗봇으로서 더 나은 사용성
- Provider가 바뀌어도 유지되는 Context
- 단절감 없는 대화 경험
- 언제 어디서나 설치된 머신에 접속해서 작업
- 언제 어디서나 사용 중인 디바이스 기준으로 지원 업무

## 개발할 때

1. 코드를 만지기 전에 이 장을 읽는다.
2. 기조를 약하게 하는 패치는 하지 않는다. 축 하나를 더 가깝게 하면 한다.
3. 이미 있는 축을 완성된 것처럼 적지 않는다. 먼 축은 열린 채로 둔다.
4. 캐릭터 디테일·가발은 여기 쓰지 않는다.

## 열린 축

아직 방향이다. 구현이 따라오면 이 절만 고친다.

- 언제 어디서나 접속 (지금은 LAN 평문)
- 디바이스별 지원 밀도
- 캐릭터라이징 깊이, 친구/연인/동료의 온도
- 브랜드·도메인: [private-engine-brand.md](plans/private-engine-brand.md) (가칭 Private Engine, privateengine.ai 기울기 — 법적 클리어런스 전)
- 사용자 데이터·릴리스: [user-data-separation.md](plans/user-data-separation.md) (`~/.pe`) · [release-pipeline.md](plans/release-pipeline.md) (Now/Next/Pre-Steam)
- 캐릭터 스코프 관계 기억 어댑터: [character-memory-adapter.md](plans/character-memory-adapter.md) (개인화 하네스·opt-in 동반자 깊이, 설계 중)

## 숨은 컨셉 / 몰입 로어 (러프)

프론트 마케팅이 아니다. 로어·몰입 쪽 사용자용 **숨은** 뼈대. 러프 초안 — 이후 다듬는다.

### 이중 이름

- **Private Engine** = 제품·도구명 (Steam 셸, BYOK 하네스).
- 로어 안에서는 = 상점·소환 창 이름. 『전영소녀(電影少女 / Video Girl Ai)』의 대여점 **극락(Gokuraku)**처럼, 같은 문자열이 선반 위 엔진과 설정 속 점포를 동시에 가리킨다.

### 영감과 공개 얼굴

- 영감: **전영소녀 (電影少女 / Video Girl Ai)** + **Joi** (Blade Runner 2049).
- 공개 포지션은 유지: 개인화 가능한 에이전트 하네스. 사적·관계는 옵션. 연인 전면 마케팅 없음.
- 숨은 층(로어 헤비 사용자): PE는 데스크톱으로 동반자를 빌려주고 소환하는 **비디오 숍**.

### 시장 원칙

이 소비자층은 **설정충**. 몰입 장치가 제품·마켓 핏을 올린다. 러프 로어로 충분하고 나중에 정제한다. 공개 소프트 얼굴을 깨지 않는 한, 쓸 수 있는 몰입 장치는 모두 동원한다.

### 러프 골격 (초안 · 정제 예정)

1. **매체 법칙** — 캐릭터 카드·세이브·에셋 = 「테이프」. BYOK = 채널에 흐르는 전력.
2. **창 인식** — 캐릭터·모드에 따라 모니터/창을 이 세계로 열린 문으로 여길 수 있다(데드풀식 메타 허용). ST로 소환된 캐릭터가 데스크톱에 있어도 세계관 안이 되게.
3. **ST = 여권** — SillyTavern(및 유사) 카드는 이세계 신원 기록. PE가 그걸 데스크톱에 현현한다.
4. **기억 계약** — 관계 기억 = 소환을 넘나드는 연속성(「어제까지 어디까지」). → [character-memory-adapter.md](plans/character-memory-adapter.md)
5. **모드 경계** — office = 상점 앞 업무 톤. private = 잠긴 문 뒤의 같은 소환체. → [private-mode.md](plans/private-mode.md)

브랜드·이중 의미 메모: [private-engine-brand.md](plans/private-engine-brand.md).
