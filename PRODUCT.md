# Product

<!-- impeccable:product-schema 1 -->

최대 가치·해자·목표 축은 [`CONCEPT.md`](CONCEPT.md)가 정본이다. 이 문서는 그 기조를 제품 결정(누구에게, 무엇을, 어떤 원칙으로)으로 옮긴 것이다. 기조와 부딪히면 기조가 이긴다.

## Platform

web — 로컬에서 도는 Python 엔진 + 브라우저 UI. 배포는 그 위에 얇은 데스크톱 셸(Tauri류)을 씌워 Steam으로 낸다([release-pipeline.md](docs/plans/release-pipeline.md) Pre-Steam).

## Users

**자기 PC·서버에 설치하는 엔드유저.** 이미 AI 구독(구글·xAI·Anthropic·OpenAI 등)이나 CLI를 쓰고 있고, 업무용 챗창 말고 **자기 취향의 캐릭터가 곁에 있기**를 원하는 사람.

- 핵심층: SillyTavern·캐릭터 카드·AI 동반자 쪽 파워 유저. 설정과 몰입을 중시한다(설정충).
- 입구층: 구글 계정 하나로 무료 쿼터를 써서 맛보는 가벼운 사용자.
- 쓰는 상황: 데스크톱 옆에 띄워 두고 하루를 같이 보낸다 — 낮에는 업무 톤(office), 원하면 사적인 관계(private). 모바일 브라우저로도 이어서 쓴다.

지금 설치는 개발자 한 명(운영자)의 DiskStation NAS다. 그 환경에 딸린 것은 아래 「개발 설치」에만 적는다.

## Product Purpose

**진입장벽이 매우 낮은 프리메이드 개인화 하네스.** 설치하면 완성된 캐릭터·외형·규칙이 들어 있어 바로 대화하고, 쓰면서 조금씩 내 것으로 바꾼다.

성공 기준:
- 설정 없이 첫 대화까지 간다(프리메이드, BYOK 로그인).
- 매번 다시 설명하지 않아도 캐릭터가 나와 관계를 기억한다(연속성).
- 사용자가 캐릭터·기억·외형·목소리·규칙을 어렵지 않게 바꾸고, 에이전트가 그 일을 돕는다.
- 프로바이더를 바꿔도, 엔진을 업데이트해도 쌓은 개인화가 그대로 남는다.

## Positioning

**Wallpaper Engine의 자리 — 배경화면 대신 에이전트를 커스터마이즈한다.** Steam 저가 1회 구매 + BYOK(엔진과 UX를 팔고 모델은 사용자가 가져온다) + 창작마당.

업무 능력·효율로 프로바이더의 업무 하네스와 겨루지 않는다. 겨루는 곳은 **두껍게 쌓이는 개인화 레이어**와 그 레이어가 모이는 **플러그인·창작마당 생태계**다.

공개 얼굴은 **개인화 가능한 에이전트 하네스·데스크톱 동반자**다. 사적 관계 기능은 그 안의 한 축이고, 어떻게 쓸지는 사용자 몫이다. 숨은 컨셉(전영소녀·조이, 비디오 가게로서의 Private Engine)은 제품 안의 몰입 장치이고 스토어 전면에 내세우지 않는다.

## Operating Context

**제품(배포판)**
- 사용자 기기에서 로컬로 돈다. 사용자 데이터는 `~/.pe`(Windows `%USERPROFILE%\.pe`), 엔진 코드와 분리된다([user-data-separation.md](docs/plans/user-data-separation.md)).
- 브라우저 UI가 로컬 엔진에 붙는다. 데스크톱·모바일 브라우저 둘 다 쓴다(좁은 화면용 컴포저 레이아웃 있음).
- 두뇌는 사용자가 연결한 프로바이더 CLI·API가 이 기기에서 스폰된다. 브라우저는 얇은 클라이언트.

**개발 설치 (지금, 운영자 한 명)**
- Synology DiskStation에 상시 데몬(`chatbot-ctl.sh`), 포트 3011(채팅)·3012(MCP). 포트는 env `CHATBOT_PORT` / `NAS_MCP_PORT`.
- 평문 HTTP, LAN 내부 접속(TLS 없음). 보안 컨텍스트가 필요한 브라우저 API는 폴백이 필요했던 전례가 있다(HISTORY.md).
- UI 표면은 전체 창 채팅 하나: `http://diskstation:3011/`와 숏컷 `http://diskstation/chat/`가 같은 `static/index.html`을 연다. `static/live.html`(2.5D 뷰어)은 제품 표면이 아니다.
- Sphere Hub(이 NAS의 허브 홈)의 FAB은 레포 밖 호스트 셸이다. 입구·호스트 소생 경로로만 존재하고 이 제품의 디자인 표면이 아니다.
- NAS 서비스 제어(`nas_mcp_host.py`)는 이 설치 환경의 플러그인이다. 제품 기능이 아니다([direction-alignment.md](docs/plans/direction-alignment.md) D3). 기본은 꺼짐이고, 이 NAS는 `data/host.env`의 `NAS_MCP_HOST_PLUGIN=1`·`CHATBOT_WEB_ROOT=/volume1/web`로 켠다(선택지는 `templates/host.env.example`).

## Capabilities and Constraints

**있는 것**
- **멀티 프로바이더(BYOK)**: agy(기본)·claude·grok·codex CLI + `data/providers.json`의 HTTP OpenAI 계열(omniroute·openrouter, OpenRouter는 무료 모델만). 프로바이더마다 프로세스 모델·사용량 체계가 다르다(`providers/adapters.py::AGENT_ADAPTERS`). 사용자의 API 키는 `secrets.env`(배포 전 OS 키체인으로 옮긴다).
- **캐릭터**: 캐릭터 카드 V2가 정본(`characters/<id>/card.json`: 정체성·말투·사적 규칙·업무 지침·두뇌). 외형 `visual.md` + 이미지. SillyTavern PNG 카드 가져오기(#250), 로어북.
- **기억**: 공용 기억 `memory/MEMORY.md`, 캐릭터별 기억 `memory.md`, 사적 기억 `private-memory.md`(커밋·배포 제외). 관계 기억은 사적 세션의 짧은 슬롯이다([character-memory-adapter.md](docs/plans/character-memory-adapter.md), 최소 구현·계획 active).
- **외형·연출**: 스프라이트 멀티 프레이밍(Visual Adapter, #251), 표정 태그, 감정 이벤트(`emotion.py`).
- **사적 모드**: 선택지·행동 입력·텐션 단계, 모델 계열별 보완 레이어(`private_engine.py`, [private-mode.md](docs/plans/private-mode.md)).
- **연속성**: 토큰 기반 세션 교대, 이어하기(인계 요약), 세션 목록·복원, 무응답·쿼터 오류 감시(`turn_watchdog.py`).
- **자기 개발**: 에이전트가 스킬(`SKILL.md`)·기억·지침을 쓰고 다듬는다. 관찰 → 제안 → 승인 흐름(`observations.py`, `tickets.py`).
- **도구**: MCP 서버(`mcp_server.py`)와 코어 도구(`memory`·`observation`·`ticket`).

**제약·경계**
- 배포판의 에이전트는 **엔진 코드를 고치지 않는다.** 엔진 코드 수정과 그 장치(티켓 관문·워크트리 위임·커밋 훅)는 개발판에만 있다([CONCEPT.md](CONCEPT.md) 「배포판과 개발판」).
- 라이브 세션은 자기 호스트를 재기동하지 않는다. 재기동은 `engine/chatbot-ctl.sh`와 소생 경로만(`templates/dev-workspace/SELF-MODIFY.md`, `OPERATIONS.md`).
- 아직 없는 것: 데스크톱 셸·설치기, 모드 잠금·로컬 암호화·키체인, 현지화, 플러그인 로딩·창작마당, 보이스, 2.5D/3D 렌더러 — 각 계획에서 다룬다.
- 미확정: 프로바이더별 토큰 임계값 일부, 일부 모델의 컨텍스트 크기.

## Brand Commitments

- **이름**: 가칭 Private Engine(PE). 상표 클리어런스 전([private-engine-brand.md](docs/plans/private-engine-brand.md)).
- **캐릭터**: 이름·말투·호칭은 캐릭터 카드, 외형은 `visual.md`가 정본이다. 엔진 문자열에 특정 캐릭터의 이름·호칭·말투를 박지 않는다(기본 캐릭터는 `team.json`의 `default`).
- **공개 톤**: 스토어·UI 전면은 개인화 하네스. 사적 수위 장면은 공식 표면에 올리지 않는다.
- **테마**: 7종 선택 테마(CSS 커스텀 프로퍼티) — `lime`(기본)·`amber`·`cyan`·`emerald`·`violet`·`mono`·`spark`. 한 색에 브랜드를 고정하지 않는다. 디자인 방향은 [DESIGN.md](DESIGN.md).

## Evidence on Hand

- 동작하는 POC: 멀티 프로바이더 채팅, 캐릭터 카드·기억, 사적 모드(Gemini 작법·거절 완화 실험, #249), ST 카드 가져오기, 스프라이트 연출.
- 기본 캐릭터·페르소나 에셋: `data/persona/`, `data/workspace/characters/`.
- 기록: `HISTORY.md`(2026-09-16~), 계획 `docs/plans/INDEX.md`, 구조 `ARCHITECTURE.md`, 운영 `OPERATIONS.md`, 자기수정 경계 `templates/dev-workspace/SELF-MODIFY.md`.

## Product Principles

1. **처음부터 완성돼 있다** — 설치 직후 프리메이드 캐릭터와 바로 대화한다. 설정은 나중에, 원할 때.
2. **개인화를 돕는 데 능력을 쓴다** — 에이전트의 능력은 생산성보다 사용자가 레이어를 쌓는 일을 돕는 데 쓴다. 업무 효율 기능은 개인화를 돕지 않으면 만들지 않는다.
3. **캐릭터는 백엔드보다 오래간다** — 어떤 프로바이더가 두뇌든 캐릭터·호칭·말투·관계는 같게 느껴져야 한다.
4. **끊겨도 이어진다** — 토큰 한도, 재시작, 프로바이더 전환, 엔진 업데이트 그 무엇으로도 관계와 맥락이 사용자 모르게 사라지면 안 된다.
5. **익숙한 생태계로 들어온다** — SillyTavern에 있는 것은 ST 형식 그대로, 없는 것만 만든다. 쓰던 구독·카드·스킬을 그대로 가져온다.
6. **내 데이터는 내 것** — 로컬에 쌓이고, 들키면 안 되는 대화는 잠그고 암호화한다. 깊이로 붙잡되 내보내기를 막지 않는다.

## Accessibility & Inclusion

엔드유저 제품이 되므로 실용 수준 이상을 목표로 한다: 대비·포커스 링·alt 텍스트(2026-09-18 감사에서 양호), 모바일 터치 타겟·입력 필드 라벨(개선 필요), 키보드만으로 대화·선택지 조작. 현지화는 [localization.md](docs/plans/localization.md)(1차 한국어·영어). 공식 WCAG 인증은 목표로 두지 않는다.
