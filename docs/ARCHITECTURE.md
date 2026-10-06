# Private Engine — Architecture

> 2026-09-28 `data/workspace/docs/`에서 옮겨 옴(사용자 데이터 폴더는 배포 때 `~/.pe`로 빠지므로). 이름을 PE → PE로 바꾸고, [direction-alignment.md](plans/direction-alignment.md)(개인화 하네스, 배포판/개발판, 플러그인 플랫폼)에 맞춰 NAS·자가진화 표현만 고쳤다. 플러그인 아키텍처 계획(align/J)의 출발점.

> **설계 원칙:** 모든 외부 의존성은 어댑터 인터페이스 뒤에 숨긴다.
> PE Core는 구체적인 벤더·라이브러리를 알지 못한다.

> **ST 정책:** SillyTavern에 이미 있는 기능은 ST를 그대로 쓴다.
> PE 자체 포맷·기능은 ST에 **없는 것만** 설계한다.

---

## 1. 전체 레이어 구조

```
┌──────────────────────────────────────────────────────────┐
│                    Community / User                      │
│         UI 테마 · 보이스 팩 · 캐릭터 카드 · 확장          │
├──────────────────────────────────────────────────────────┤
│                    Plugin Layer                          │
│  ThemeAdapter │ VoicePackAdapter │ ExtensionAdapter       │
├──────────────────────────────────────────────────────────┤
│                    PE Core                               │
│  세션 · 메모리 · 지시문 · 로어북 · 라우팅                  │
├──────────────────────────────────────────────────────────┤
│                    Adapter Layer                         │
│  LLM │ Visual │ TTS │ STT │ Memory │ Storage │ Session    │
├──────────────────────────────────────────────────────────┤
│                    Infrastructure                        │
│    사용자 PC·서버 (개발 설치: NAS) · 파일시스템 · 외부 API    │
└──────────────────────────────────────────────────────────┘
```

---

## 2. ST vs PE 역할 분담

| 기능 | 담당 | 비고 |
|------|------|----- |
| 캐릭터 카드 편집 UI | **ST** | PNG V2/V3 규격 그대로 |
| 스프라이트 (28종 표정) | **ST** | 플랫 구조 `<label>.png` |
| 로어북 / World Info | **ST** | JSON 규격 그대로 |
| 확장(Extension) 기본 | **ST** | ST 확장 규격 참고 |
| LLM 멀티 프로바이더 | **PE** | 로컬 상주 |
| 멀티 프레이밍 스프라이트 | **PE** | bust / full / avatar 구분 (ST 없음) |
| 2.5D / VRM / 3D 렌더러 | **PE** | ST 없음 |
| 호스트 제어 (예: NAS) | **PE 환경 플러그인** | 설치 환경별 선택, 제품 정체성 아님 |
| 세션 연속성·인계 | **PE** | ST 없음 |
| 자기 개발: 스킬·기억·지침 | **PE** | 배포판. 사용자 승인·되돌리기 |
| 코드 자가진화 (티켓·위임) | **PE 개발판** | 배포판에 없음 |
| 멀티 캐릭터 동시 세션 | **PE** | ST 없음 |
| 프로바이더별 보완 레이어 팩 (거절 완화·작법·속도) | **PE** | 모델 계열별 오버레이, A/B로 두꺼워지는 해자 (`private_engine.py`, `engine_data/private_tension_*.json`) |
| 모드 잠금·로컬 대화 암호화·키체인 | **PE** | 사적 보호 (release-pipeline Pre-Steam) |
| 오피스↔프라이빗 모드 전환 | **PE** | 한 캐릭터가 하루를 같이 사는 경험 |

---

## 3. 핵심 어댑터 명세

### 3.1 LLM Provider Adapter
**목적:** LLM 벤더 종속성 제거. Core는 `generate(messages) → stream` 인터페이스만 사용.

| 구현체 | 상태 |
|--------|------|
| OpenAI (GPT-4o 등) | ✅ 운영 중 |
| Anthropic (Claude) | ✅ 운영 중 |
| Google (Gemini / AGY) | ✅ 운영 중 |
| Grok | ✅ 운영 중 |
| Local (Ollama / LM Studio) | 🔜 예정 |

```python
class LLMAdapter:
    def generate(self, messages: list, stream: bool = True) -> Iterator[str]: ...
    def supports_vision(self) -> bool: ...
    def max_context(self) -> int: ...
```

---

### 3.2 Visual (Character Renderer) Adapter
**목적:** 캐릭터 시각화 방식을 런타임에 교체 가능.

**ST 스프라이트(28종 플랫)는 ST가 담당** — SpriteAdapter는 PE 전용 멀티 프레이밍 처리.

| 구현체 | 설명 | PE 전용 |
|--------|------|----------|
| SpriteAdapter | bust / full / avatar 프레이밍 분리 | ✅ |
| AnimeLayerAdapter | 2.5D 인터랙티브 레이어 | ✅ |
| VRMAdapter | 3D VRM 모델 (Three.js / @pixiv/three-vrm) | ✅ |
| SpineAdapter | Spine 2D 스켈레탈 애니메이션 | ✅ |
| Live2DAdapter | Live2D Cubism SDK | ✅ |

**스프라이트 경로 규칙 (PE):**
```
sprites/bust/<label>.webp    ← 상반신 (채팅 사이드패널)
sprites/full/<label>.webp    ← 전신 (데스크탑 VN 모드)
avatar/<provider>.webp       ← 뱃지
```

**프레이밍 선택 로직:** UI 컨텍스트에 따라 자동 결정
- 모바일 / 좁은 화면 → `bust`
- 데스크탑 VN 모드 → `full`
- 채팅 뱃지 → `avatar`

```typescript
interface VisualAdapter {
  load(character: CharacterCard): Promise<void>;
  setFraming(mode: 'bust' | 'full' | 'avatar'): void;
  setEmotion(label: string): void;
  speak(text: string, audio?: AudioBuffer): void;
  destroy(): void;
}
```

---

### 3.3 TTS Adapter
**목적:** 음성 합성 엔진 교체 가능. (ST TTS 기능 위에 로컬 엔진 추가)

| 구현체 | 설명 |
|--------|------|
| ElevenLabsAdapter | 클라우드 고품질 TTS |
| XTTSAdapter | 로컬 XTTS-v2 (로컬 상주) |
| CoquiAdapter | Coqui TTS 로컬 |
| BrowserTTSAdapter | Web Speech API (폴백) |

```python
class TTSAdapter:
    def synthesize(self, text: str, voice_id: str) -> bytes: ...
    def stream(self, text: str, voice_id: str) -> Iterator[bytes]: ...
```

---

### 3.4 STT Adapter
**목적:** 음성 인식 엔진 교체 가능.

| 구현체 | 설명 |
|--------|------|
| WhisperAdapter | 로컬 Whisper (로컬) |
| GoogleSTTAdapter | Google Speech-to-Text API |
| BrowserSTTAdapter | Web Speech API |

---

### 3.5 Memory Adapter
**목적:** 장기 기억 저장소 교체 가능.

| 구현체 | 설명 |
|--------|------|
| JSONMemoryAdapter | 파일 기반 JSON (현재) |
| VectorDBAdapter | ChromaDB / Qdrant 시맨틱 검색 |
| RedisAdapter | 인메모리 + 영속화 |

---

### 3.6 Storage Adapter
**목적:** 파일 저장 위치 추상화.

| 구현체 | 설명 |
|--------|------|
| LocalFSAdapter | 로컬 파일시스템, 사용자 데이터 `~/.pe` (현재 개발 설치는 DiskStation) |
| S3Adapter | AWS S3 / 호환 오브젝트 스토리지 |
| LocalAdapter | 개발용 로컬 경로 |

---

### 3.7 Session Adapter
**목적:** 세션 상태 저장 방식 교체 가능.

| 구현체 | 설명 |
|--------|------|
| FileSessionAdapter | JSON 파일 (현재) |
| DBSessionAdapter | SQLite / PostgreSQL |

---

## 4. Plugin Layer (커뮤니티 커스텀)

> 설계·순서·결정은 [plans/plugin-architecture.md](plans/plugin-architecture.md) (콘텐츠/코드 구분, 매니페스트, 로딩, 격리, 등급, Workshop).

### 4.1 UI Theme
- ST에 없는 PE 전용 UI 테마 시스템
- 로드 경로: `$CHATBOT_DATA/workspace/themes/<name>/theme.css` (배포 기본 `~/.pe`)
- 런타임 핫스왑 가능 (페이지 새로고침 없이)

### 4.2 Voice Pack
- 캐릭터별 보이스 설정 번들 (ST에 없는 로컬 TTS 연동)
- 로드 경로: `$CHATBOT_DATA/workspace/voices/<name>/pack.json`
- `pack.json`: `{ "tts_adapter": "...", "voice_id": "...", "params": {} }`

### 4.3 Extension
- ST 확장 규격 참고하되 PE 백엔드 훅 추가
- 로드 경로: `$CHATBOT_DATA/workspace/extensions/<name>/`
- 진입점: `index.js` (프론트) + `hook.py` (백엔드, PE 전용)

---

## 5. 구현 로드맵

| Phase | 내용 | 상태 |
|-------|------|----- |
| 1 | ST PNG 카드 임포터 | ✅ 완료 |
| 2 | 로어북 엔진 | ✅ 완료 |
| 3 | Visual Adapter 인터페이스 + SpriteAdapter (멀티 프레이밍) | ✅ 완료 |
| 4 | AnimeLayerAdapter (2.5D) | 🔜 |
| 5 | VRMAdapter (3D) | 🔜 |
| 6 | TTS Adapter + Voice Pack | 🔜 |
| 7 | UI Theme Plugin | 🔜 |
| 8 | Extension Plugin (백엔드 훅) | 🔜 |

---

## 6. 설계 원칙 요약

1. **어댑터 우선** — Core는 인터페이스만 알고 구현체를 모른다.
2. **ST 위임** — ST에 있는 기능은 ST를 쓴다. 중복 구현 금지.
3. **PE 전용 확장** — ST에 없는 것만 자체 설계 (멀티 프레이밍, VRM, 연속성, 스킬·기억·지침 자기 개발 등).
4. **로컬 우선** — 기본 구현체는 항상 사용자 기기(로컬) 우선.
5. **커뮤니티 개방** — 어댑터 표준만 지키면 서드파티 기여 가능.
6. **점진적 전환** — 각 어댑터는 독립적으로 교체·업그레이드 가능.
7. **거버넌스 단방향 흐름** — 상위 계층은 하위를 알지만 코어는 상위를 알지 못하며, 순환 import는 원천 차단된다.
8. **배포판 불변과 티어 격리** — 배포판은 엔진 코드를 고치지 않으며, Tier 3 거버넌스 및 통과 조건은 운영자의 승인 하에서만 변경된다.

---

## 7. 소프트웨어 엔지니어링 거버넌스 및 모듈 경계 (Software Engineering Governance)

> 관련 계획: [propagation-and-state-architecture.md](plans/propagation-and-state-architecture.md) (거버넌스 전파·상태 아키텍처) · [edition-boundary.md](plans/edition-boundary.md) (배포판/개발판 경계) · [CONVENTION.md](CONVENTION.md) (엔지니어링 컨벤션) · [STATE.md](STATE.md) (전파 장부)

### 7.1 모듈 경계 및 책임 (Module Boundaries)

코드베이스는 단일 책임과 명확한 의존성 경계를 갖는 5대 계층으로 구조화된다:

| 계층 | 대상 모듈 | 역할 및 책임 | 의존성 규칙 및 가드 |
|---|---|---|---|
| **Core** | `evolution.py`, `tickets.py`, `observations.py`, `memory_store.py`, `platform_compat.py` | 자가진화, 티켓 장부, 관찰 신호, 기억 영속화, 플랫폼 호환성 코어. | 표준 라이브러리와 상호 의존만 허용하며 외부 패키지 및 상위 계층 import 배제.<br>**[현재 가드]** `tests/test_core_standalone.py` (`core_modules.json`) |
| **Providers** | `providers/` (`adapters.py`, `adapter_base.py`, `adapter_agy.py`, `adapter_claude.py`, `adapter_grok.py`, `adapter_codex.py`, `adapter_openai.py`, `accounts.py`, `account_login.py`) | LLM CLI 및 HTTP 두뇌 연결 계층. 모델별 요청·응답 규격 정규화. | 공통 코드에 특정 프로바이더 특화 로직 침투 금지, 교체 가능성 보장.<br>**[현재 가드]** `tests/test_provider_neutrality.py` |
| **Session & Runtime** | `session.py`, `session_turn.py`, `session_view.py`, `session_registry.py`, `session_weights.py`, `standby_pool.py`, `turn_watchdog.py`, `instructions.py` | 세션 생명주기 관리, 턴 실행 및 중단, 프롬프트 번들 조합, 턴 감시(Fail-Fast). | 세션 런타임은 Core와 Providers를 조합하되 하위 계층에 역방향 결합을 만들지 않음. |
| **HTTP Routes** | `server.py`, `route_table.py`, `route_sessions.py`, `route_accounts.py`, `route_files.py` 및 라우트 헬퍼 (`origin_guard.py`, `preview_guard.py` 등) | REST API 엔드포인트 및 Server-Sent Events(SSE) 스트리밍 처리. | 요청 유효성 검증 및 세션/파일 계층 위임. 경로 일치 순서 유지. |
| **Tools & MCP** | `mcp_server.py`, `mcp_core.py`, `nas_mcp_host.py`, `mcp_args.py`, `web_tool.py`, `mcp_parity.py`, `mcp_caller.py` | 에이전트 도구 인터페이스(JSON-RPC MCP 표준 기반 및 Core 도구). | 도구 인자 검증, 권한 및 실행 격리.<br>**[현재 가드]** `tests/test_tool_format_clean.py`, 파일 크기 상한 준수 |

### 7.2 단방향 의존성 및 순환 import 금지 (Dependency Directions)

- **단방향 흐름 원칙**:
  - 상위 계층(HTTP Routes, Tools, Session)은 하위 계층(Core, Providers)을 참조할 수 있으나, 하위 코어는 상위 계층이나 특정 프로바이더를 일절 참조하지 않는다.
  - Core 모듈은 `core_modules.json`에 명시된 모듈 간 상호 참조 외에 상위 비즈니스 로직(세션, 라우터, 어댑터 등)을 import하지 않는다.
- **순환 import 차단**:
  - 모듈 간의 상호 순환 참조(`A -> B -> A`)는 런타임 데드락 및 부트스트랩 실패를 유발하므로 최상단 및 함수 내부 import를 막론하고 엄격히 차단한다.
  - **[현재 가드]** `tests/test_import_cycles.py`가 전체 모듈 그래프를 분석하여 새로운 순환 import 쌍의 유입을 기계적으로 방지하며, 기존 잔여 순환 쌍은 줄어들기만 하도록 래칫 관리한다.

### 7.3 배포판/개발판 경계 격리 (Edition-Boundary Separation)

PE는 단일 코드베이스에서 최종 사용자용 배포판(`shipped`)과 자체 엔진 개발용 개발판(`dev`)을 명확히 격리한다 ([plans/edition-boundary.md](plans/edition-boundary.md)):

- **판정 기준의 단일 진실 공급원 (SSOT)**:
  - `host_config.EDITION` (`CHATBOT_EDITION` 환경변수)만을 유일한 판정 기준으로 삼는다.
  - 기본값은 최소 권한인 `shipped`이며, 개발 인스턴스는 `$CHATBOT_DATA/host.env`에 `CHATBOT_EDITION=dev`를 명시한다.
- **배포판 (`shipped`) 격리 원칙**:
  - **엔진 코드 불변**: 배포판 에이전트는 엔진 소스 코드를 일절 수정하지 않는다.
  - **도구 목록 격리**: 개발 전용 도구(`run_command`, `ticket`, `delegate`)가 MCP 도구 목록에서 완전히 제외된다.
  - **쓰기 범위 제한**: 파일 쓰기 및 수정 허용 루트가 사용자 데이터 폴더(`$CHATBOT_DATA`) 및 임시 디렉터리로 한정되며, 엔진 저장소 디렉터리는 쓰기 대상에서 제외된다.
  - **[현재 가드]** `tests/test_edition_boundary.py`를 통해 `shipped` 환경에서의 개발 도구 제외 및 쓰기 범위 제한을 검증한다.
  - **[예정 집행]** 배포판 런타임에서 사용자 데이터 외 엔진 코드 수정을 런타임 레벨에서 원천 차단하는 하드닝 가드.
- **개발판 (`dev`) 운영**:
  - 엔진 자가진화, 티켓 발급, 워크트리 위임, 저장소 코드 쓰기가 허용 목록과 티켓 클레임 가드 하에서 동작한다.
  - 개발 장치(`tickets.py`, `delegation.py`, `tools/worktree_runner.py`)는 배포 빌드 시 패키지 제외(`edition_exclude.txt`) 또는 선택적 로딩(conditional import)으로 격리된다.

### 7.4 Tier 1/2/3 다층 보안 격리 원칙 (Tier Isolation)

코드 및 데이터 변경의 위험도에 따라 4단계 격리 티어(`protected_paths.json`, `evolution.py`)를 적용한다:

| 티어 | 관할 대상 | 권한 및 변경 규칙 | 강제 및 방어 수단 |
|---|---|---|---|
| **Tier 0** | 극소 런타임 지침, 부트스트랩, 정적 UI(`static/`, 인스턴스 예외 허용 시), 순수 문서 작업(`DOC_LANE_v1`) | 즉시 수정 가능 또는 1회 문서 리뷰 후 반영. | 가드 테스트 및 인스턴스 설정. |
| **Tier 1** | 사용자 영역 데이터 (스킬, 기억, 캐릭터 카드, `$CHATBOT_DATA/workspace/`) | 배포판 에이전트의 자기 개발 허용 (사용자 승인 및 제안 카드를 통해 반영). | 사용자 승인 게이트, 변경 기록 추적. |
| **Tier 2** | 엔진 구현체 (세션, 어댑터, 라우터, UI 스크립트, 일반 도구) | 개발판 위임 에이전트의 일반 티켓(#N) 작업 영역. 경로 클레임 필수. | `test_tickets`, `test_unticketed_write`, 워크트리 러너 게이트. |
| **Tier 3** | 코어, 보안, 가드 테스트, 커밋 훅, 거버넌스 문서 (`protected_paths.json` "governance") | **운영자 명시적 승인 전용**. 위임 에이전트의 자의적 수정 엄격 차단. | `test_code_layout`, `test_worktree_runner` (통과 조건 불변성). |

