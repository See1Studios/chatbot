# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

실장님(단일 운영자) 혼자만 접근하는 개인용 NAS 비서. 다른 사람(가족·팀원 등)의
접근은 없음 — 페르소나의 말투·호칭("실장님")도 이 전제로 이미 일관되게
설계돼 있음. 사용 상황: Synology DiskStation을 데스크톱/모바일 브라우저로
접속해서, NAS 운영 확인·제어와 일반 콘텐츠 제작(카피, 스토리, 자막, 이미지
프롬프트, 코드, 위키 정리)을 한 채팅 인터페이스에서 처리.

## Product Purpose

최대 가치·최대 목표는 [`docs/concept.md`](docs/concept.md). 이 문서의 목적·원칙은 그 기조를 구현하는 운영 규칙이다.

호스트(DiskStation) 자체에 상시로 떠 있는 채팅 에이전트. 실장님이 매일 쓰는
개인 AI 비서이자, 이 NAS 인프라를 직접 조작할 수 있는 관제 콘솔 역할을 겸함.
성공 기준: 실장님이 매번 다시 설명하지 않아도(페르소나·맥락 유지), 실제로
서비스를 재시작하거나 파일을 확인하는 등 "말만 하는 게 아니라 진짜로
수행"할 수 있는 것.

## Positioning

**NAS 직접 제어가 핵심 차별점.** ChatGPT 웹 같은 범용 AI 챗과 달리, 이
챗봇은 `nas` MCP를 통해 실제로 이 호스트의 서비스 상태를 확인하고, 재시작하고,
파일을 읽고 쓸 수 있음 — 대화만 하는 게 아니라 실제로 인프라를 조작하는
관제 콘솔. 지속되는 페르소나(냥피디)와 세션 연속성(핸드오프 요약, 멀티
프로바이더 전환)은 이 핵심 정체성을 뒷받침하는 부차 요소로 취급.

## Operating Context

- Synology DiskStation NAS에 상시 데몬으로 실행(`chatbot-ctl.sh`), 포트
  3011(채팅)·3012(NAS MCP). 포트는 env `AGY_CHAT_PORT` / `NAS_MCP_PORT`.
- 평문 HTTP, LAN 내부 접속(TLS 없음) — 이 제약 때문에 클립보드 API 등
  보안 컨텍스트 의존 기능은 폴백이 필요했던 전례 있음(docs/DEVLOG.md).
- 데스크톱·모바일 브라우저 둘 다 실사용(모바일은 좁은 화면용 별도 컴포저
  레이아웃 존재).
- **제품 UI 표면은 전체 창 채팅 하나.** `http://diskstation:3011/` 와
  숏컷 `http://diskstation/chat/` 가 같은 `static/index.html` 셸을 연다.
  `static/live.html`(2.5D 마스코트 뷰어)은 이 제품 표면이 아님.
- Sphere Hub 홈(`http://diskstation/`, 웹 루트 `/volume1/web/index.html`)의
  FAB은 이 레포 밖 호스트 셸이다. 입구·호스트 사망 시 소생
  (`/api/chatbot.php?action=revive`) 경로로만 존재하며, 이 챗봇의 디자인
  표면으로 취급하지 않는다.
- 백엔드 CLI/API 프로세스(agy/claude/grok/codex/omniroute/openrouter)를 직접 스폰해서
  대화를 구동 — 브라우저는 얇은 클라이언트, 실제 두뇌는 이 호스트에서 돈다.

## Capabilities and Constraints

- **멀티 프로바이더**: agy(기본)·claude·grok·codex + `data/providers.json`의
  HTTP OpenAI dialect(omniroute·openrouter). CLI 스폰형과 API 키형
  (`data/secrets.env`의 `CHATBOT_OMNIROUTE_API_KEY` / `OPENROUTER_API_KEY`)이
  공존. OpenRouter는 JSON `free_only`로 무료 모델(`:free` 및 `openrouter/free`)만
  노출·호출한다. 프로바이더별 프로세스 모델(지속형 vs one-shot exec vs HTTP)과
  사용량 체계가 서로 다름 (`adapters.py`의 `AGENT_ADAPTERS`).
- **MCP 연동**: `mcp_server.py`(포트 3012, 서버 이름 `nas`) — 파일
  읽기/쓰기(화이트리스트), 명령 실행(화이트리스트), 그리고 코어 도구(`memory`·
  `observation`·`ticket`, `mcp_core.py`). 이 NAS의 서비스 목록/제어·호스트 상태
  요약은 플러그인 `nas_mcp_host.py`.
- **세션 관리**: 토큰 사용량 기반 소프트/하드 로테이션, 이어하기(핸드오프
  요약), 세션 목록·복원, 아티팩트(생성 이미지/파일) 갤러리.
- **장기 기억**: `data/workspace/memory/MEMORY.md` (`tools/memory.py`
  show|add|search|forget). 세션을 넘기는 사실 기록. 페르소나 SSOT와 별개.
- **호스트 소생**: 라이브 세션이 자기 호스트를 재기동하지 않음. 죽은 호스트는
  FAB 소생 / `POST /api/host/defibrillate` / `chatbot-ctl.sh repair` 만
  재기동한다 (`SELF-MODIFY.md` + host-force ticket).
- **자가진화형(self-evolving)**: 실장님의 피드백을 받아 챗봇 스스로
  자기 코드(`server.py`/`session.py`/`adapters.py`/`host_config.py`/
  `tool_format.py`/`mcp_server.py`/`static/`)를 고치고 `docs/DEVLOG.md`에 기록 —
  단, 라이브 세션 중 자기 자신을 직접 재기동하지는 않음.
- **하네스 독립 페르소나**: 백엔드가 바뀌어도 호칭·말투·외형은 유지됨 —
  `data/workspace/PERSONA.md`가 SSOT.
- **미확정**: 프로바이더별 정확한 소프트/하드 토큰 임계값(claude/grok/codex/
  omniroute는 실사용 데이터 축적 전까지 잠정치), 일부 프로바이더의 컨텍스트
  윈도우 크기.

## Brand Commitments

- **페르소나 "냥피디(냥PD)"**: 미소녀 인간형 애니메 소녀 본체 + 고양이
  귀·꼬리 악센트(풀 수인·동물 얼굴 금지). 은회색 웨이브 머리, 금색 눈,
  베이지 트렌치+흰 블라우스. 냥체 말투(~냥, ฅ, ✦), 사용자를 "실장님"으로
  호칭, 자신을 "냥피디"로 지칭. 상세 락은 `data/workspace/PERSONA.md`.
- **See1 브랜드만 취급** — Zero 게임 클라이언트 개발/빌드는 전면 FIREBAT
  영역, 이 챗봇과 무관(`~/AGENTS.md` 호스트 헌장의 경계).
- 7종 선택 가능 테마를 CSS 커스텀 프로퍼티로 제공. 키는 `lime`(Sphere Lime,
  기본)·`amber`(Studio Amber)·`cyan`(Electric Cyan)·`emerald`(Cyber Mint)·
  `violet`(Neon Violet)·`mono`(Paper White, Grok)·`spark`(Gemini Spark, Antigravity).
  특정 색 하나로 브랜드가 고정돼 있지 않음.

## Evidence on Hand

- 페르소나 이미지 에셋: `data/persona/` (avatar/half/wave/face-icon/icon,
  프로바이더 아이콘 `data/persona/providers/`), 퍼블리시 경로
  `/chat/persona/`.
- 마스코트 레이어 합성: `data/sessions/_shared/see_through/*.png` (오버레이는 2026-09-19 폐기, 자산은 보존).
- 장기 기억 원문: `data/workspace/memory/MEMORY.md`.
- 운영 이력: `docs/DEVLOG.md`(버그 수정·기능 추가 상세 기록, 2026-09-16~),
  `docs/EMERGENCY.md`, `docs/SELF-MODIFY.md`.

## Product Principles

1. **말뿐이 아니라 실제로 수행한다** — NAS MCP를 통한 진짜 서비스
   제어·파일 조작이 이 제품의 존재 이유. 대화만 그럴싸한 기능은 후순위.
2. **페르소나는 백엔드보다 오래간다** — 어떤 CLI/API가 두뇌 역할을 하든
   호칭·말투·정체성은 실장님에게 항상 동일하게 느껴져야 함.
3. **단일 운영자 최적화** — 다중 사용자·권한 분리를 설계하지 않는다.
   실장님 한 명의 워크플로에 맞춰 판단.
4. **끊겨도 이어진다** — 토큰 한도, 프로세스 재시작, 프로바이더 전환
   그 무엇으로도 대화 맥락이 실장님 모르게 사라지면 안 됨(핸드오프 요약,
   세션 복원, 장기 기억이 이 원칙의 구현).
5. **스스로 고치되, 함부로 재기동하지 않는다** — 자가진화는 이 제품의
   정체성이지만, 라이브 세션을 끊는 방식으로는 하지 않는다
   (`SELF-MODIFY.md` 경계 존중).

## Accessibility & Inclusion

공식 WCAG 준수를 목표로 하지 않음 — 실장님 개인용 도구. 다만 실용적
수준(터치 타겟 크기, 명확한 라벨, 키보드 포커스 가시성 등)은 유지 —
2026-09-18 `/impeccable audit` 결과 대비/포커스링/alt 텍스트는 이미 양호,
모바일 터치 타겟과 입력 필드 라벨은 개선 여지 있음(감사 리포트 참고).
