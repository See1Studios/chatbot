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

> 관련: 규칙과 집행자 목록은 루트 [`AGENTS.md`](../AGENTS.md)(규칙표·코드 지도), 숫자는 [CONVENTION.md](CONVENTION.md), 보호 등급은 `protected_paths.json`이 정본이다. 이 절은 구조만 설명하고 그 목록을 다시 적지 않는다. 계획: [propagation-and-state-architecture.md](plans/archive/2026/propagation-and-state-architecture.md) · [edition-boundary.md](plans/edition-boundary.md)

### 7.1 계층과 의존 방향

- 계층: 코어(자가진화·티켓·관찰·기억·플랫폼 차이) → 프로바이더 어댑터 → 세션·턴 → HTTP 라우트 → 도구 서버(MCP). 파일별 소속은 `AGENTS.md` 코드 지도 한 곳에만 있다.
- 위 계층은 아래를 알 수 있지만 아래는 위를 모른다. 코어는 표준 라이브러리와 코어끼리만 import한다(`core_modules.json`, `test_core_standalone`).
- 서로 import하는 모듈 쌍은 새로 생기지 않고, 있던 쌍은 줄어들기만 한다(`test_import_cycles`).
- 공통 코드에 프로바이더 이름이 없다(`test_provider_neutrality`). 프로바이더 차이는 `providers/adapter_<이름>.py` 안에만.

### 7.2 배포판과 개발판

- 판정은 `host_config.EDITION` 하나(`CHATBOT_EDITION`, 기본 `shipped`, 이 NAS는 `host.env`에서 `dev`).
- 배포판: 개발 도구(`run_command`·`ticket`·`delegate`)가 도구 목록에 없고, 파일 쓰기는 사용자 데이터 폴더만(`test_edition_boundary`).
- **지침도 섞이지 않는다**(DEV_SPLIT_v1, 운영자 2026-10-07): 헌장은 배포판 하나(`templates/workspace/AGENTS.md`)를 두 판이 같이 쓴다. 개발판 규칙은 `templates/dev-workspace/DEV-CHARTER.md`에만 있고, 엔진이 `EDITION=dev`일 때만 헌장 다음 층(업무 세션만)으로 붙인다. 배포판 역할 팩은 배포되는 스킬만 쓴다(`test_edition_instructions`).
- 아직 아닌 것(예정): 개발 장치(티켓·위임·러너)를 배포 패키지에서 빼는 목록(edition/F), `evolution.py`의 공통/개발판 분리(edition/E). 지금은 같은 코드가 배포판에서 도구만 숨긴 채 돈다.

### 7.3 보호 등급

| 등급 | 무엇 | 누가 바꾸나 |
|---|---|---|
| 0 | 이 설치가 예외로 둔 경로(지금은 `static/`) | 티켓만 있으면 |
| 1 | 사용자 데이터(스킬·기억·카드·`$CHATBOT_DATA/workspace/`) | 사용자 승인으로 |
| 2 | 엔진 코드(`protected_paths.json` protect) | 티켓 + 위임이면 운영자의 병합 승인 |
| 3 | 거버넌스(`protected_paths.json` governance: 가드·훅·러너·헌장·규칙표의 집행자 전부) | 운영자만 |

규칙표의 집행자 테스트는 모두 3등급이고 커밋마다 돈다(`test_rule_registry`). 위임 작업자는 자기 통과 조건(게이트가 실행하는 파일)을 바꿀 수 없다(`test_worktree_runner`).

### 7.4 집행 지점

- 커밋 훅(`.githooks/`): 비밀·금지 파일, 작성자, 스테이징한 내용으로 FAST 가드, 커밋 메시지 형식·`Plan:`·`Ticket:` 트레일러, 테스트 페어링(`No-Test:` 예외), 채팅 세션의 main 착륙 금지.
- 티켓 완료: FAST 가드가 빨가면 거절(`test_tickets`).
- 위임 러너: FAST + 관련 테스트 + PD 확인.
- 전체 스위트: 운영자·외부 CLI가 커밋 전에, 러너가 위임 작업에. CI는 아직 없다(pew D8, release-pipeline Next).
