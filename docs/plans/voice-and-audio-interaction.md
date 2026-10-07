# 음성 입력과 오디오 연동 계획 (voice-and-audio-interaction)

> 방향 (align/D, 2026-10-03): **핵심 + 기반** — 손과 눈이 자유롭지 않은 모바일·이동 중 환경에서도 메신저 본연의 편의성을 제공. 모델 토큰 낭비(제로 토큰)와 외부 API 의존 없이 브라우저 네이티브 Web Speech API를 1차로 활용하며, 향후 플러그인 TTS/STT 확장 기반을 마련한다 (`docs/CONCEPT.md`, [ux-shell-roadmap.md](ux-shell-roadmap.md), [plugin-architecture.md](plugin-architecture.md)).
> 상태: **active** (2026-10-03 수립, 운영자 승인 후 착수 대기)
> 관련: [ux-shell-roadmap.md](ux-shell-roadmap.md)(§4.2.3 메신저 뼈대·입력 바), [composer-plus-menu.md](archive/2026/composer-plus-menu.md)(컴포저 확장), [engine-decides.md](engine-decides.md)(결정론적 태그/파서 처리), [plugin-architecture.md](plugin-architecture.md)(§4.1 코드 플러그인 STT/TTS 확장)

---

## 1. 배경과 문제 의식

1. **모바일/현지 이동 중 사용성**:
   - 운영자가 여행·출장·이동 중 모바일 환경에서 긴 문장을 타이핑하기 번거롭고, 시끄럽거나 급한 상황에서 음성으로 빠르게 지시하거나 질문해야 함.
2. **현지어 발음 및 현장 소통**:
   - 해외 현지(다낭 등)에서 현지어 표현(베트남어, 영어, 일본어 등)을 안내받았을 때, 현지 발음을 직접 듣거나 기사님/점원에게 큰 글씨로 보여주어야 하는 상황이 빈번함.
3. **비용 및 토큰 원칙 (제로 토큰 / 제로 외부 API)**:
   - 음성 인식이나 합성을 위해 매번 모델에게 오디오 생성/처리를 맡기거나 유료 외부 API(ElevenLabs, OpenAI Whisper/TTS 등)를 필수로 거치게 하면 레이턴시가 폭증하고 토큰/비용이 낭비됨.
   - 브라우저 네이티브 기능(Web Speech API)을 1차 베이스라인으로 활용하여 **지연 시간 0초, 추가 토큰 0개, 추가 비용 0원**으로 기본 경험을 제공한다.

---

## 2. 핵심 요구사항과 목표

### [목표 1] 컴포저 마이크 음성 입력 (STT - Speech-to-Text)
- **위치**: 컴포저 입력창 내부 또는 액션 버튼군 (`static/index.html`, `static/app.js` / `static/app-turn.js` 등).
- **기술**: 브라우저 네이티브 `webkitSpeechRecognition` / `SpeechRecognition` (`ko-KR` 기본).
- **동작**:
  1. 마이크 버튼 터치 시 청취 시작 (`recording` 상태 시각화: 붉은색 펄스 또는 마이크 채움).
  2. 실시간 중간 인식 결과(`interimResults`)를 입력창(`#input`)에 부드럽게 반영.
  3. 침묵 감지 또는 버튼 재터치 시 음성 인식 종료, 즉시 전송 버튼 활성화.
  4. 미지원 환경(일부 Firefox 등)에서는 자연스러운 툴팁 안내 및 버튼 숨김/비활성화.

### [목표 2] 현지어 발음 칩 & 오디오 재생 (TTS - Text-to-Speech)
- **구문 규칙 (Syntax)**:
  - 모델은 텍스트 작성 시 언어 태그가 달린 인라인 패턴만 가볍게 출력 (예: `Đừng cho rau mùi [vi]`, `Tính tiền giùm tôi [vi]`, `안녕하세요 [ko]`, `Thank you [en]`).
  - 정규식 기반 결정론적 파서([markdown.js](file:///volume1/homes/me/services/chatbot/static/markdown.js) 또는 [markdown-speech.js](file:///volume1/homes/me/services/chatbot/static/markdown-speech.js))가 이를 감지하여 인라인 `[🔊 발음]` 칩으로 자동 렌더링.
- **오디오 재생**:
  - 칩 클릭 시 `window.speechSynthesis`를 호출하여 해당 언어(`vi-VN`, `en-US`, `ja-JP`, `ko-KR` 등) 네이티브 보이스로 발음 즉시 재생.
  - 재생 중 버튼 상태(`playing`) 표시 및 중복 클릭 시 중지(`cancel`).
- **원터치 현장 보여주기 모드 (Show Card)**:
  - 칩 또는 보조 아이콘 터치 시, 화면 전체 또는 모달로 현지어 원문이 큼직한 폰트로 표시되어 택시 기사나 식당 직원에게 스마트폰 화면을 바로 보여줄 수 있는 기능.

### [목표 4] 오디오 음악 인식 (Shazam / 곡 찾기 연동)
- **배경**: 카페, 길거리, 매장에서 흘러나오는 노래의 제목과 가수를 찾고 싶을 때, 짧은 녹음 오디오를 들려주면 캐릭터가 음악을 찾아주는 기능.
- **파이프라인**:
  1. 클라이언트: 컴포저 마이크(또는 오디오 첨부)로 5~10초간 주변 소리 녹음 (`MediaRecorder` → WAV/WebM 버퍼).
  2. 서버/엔진: 오디오 핑거프린팅 인식기(`shazamio` 또는 경량 음원 핑거프린트 도구)로 곡 제목·아티스트·앨범 커버 조회.
  3. 에이전트/화면: 모델에게 곡 메타데이터(`title`, `artist`, `cover`)를 전달하여 대화 맥락과 함께 음악 카드로 예쁘게 추천/답변.

---

## 3. 세부 아키텍처 및 구현 계획

### 3.1 프론트엔드 모듈 분리
- **단일 책임 원칙 준수**: 용량 한도(43KB)를 위협하지 않도록 독립 모듈 또는 기존 컴포저/마크다운 모듈에 최소 침습으로 연동.
  1. `static/app-speech.js` (신설 권장):
     - `initComposerSpeech()`: 마이크 STT 초기화, 브라우저 권한 획득, 실시간 텍스트 주입.
     - `speakTargetText(text, lang)`: Web Speech Synthesis 래퍼 및 가용 보이스 자동 매칭.
     - `recordAudioSample(seconds)`: 음악 인식용 5~10초 단기 오디오 녹음 및 서버 전송.
  2. `static/markdown-speech.js` (또는 `markdown.js` 확장):
     - 정규식 `/([가-힣a-zA-Z0-9\s.,'?!~]+)\s*\[([a-z]{2}(?:-[A-Z]{2})?)\]/g` 패턴 매칭.
     - XSS 방어 적용된 렌더링 템플릿: `<button class="speech-chip" data-text="..." data-lang="..."><span>...</span><svg>...</svg></button>`.
  3. `static/chat-features.css`:
     - `.speech-chip` 스타일, `.mic-btn` 마이크 펄스 애니메이션, 보여주기 모드 풀스크린 카드 스타일.

### 3.2 단계별 항목 (Roadmap Items)

| 항목 ID | 작업 명칭 | 주요 수정 대상 | 산출물 및 검증 |
|---|---|---|---|
| **va/1** 완료 #590 | 컴포저 마이크 입력 (STT) 구현 | `static/index.html`, `static/app-speech.js`, `static/chat-composer.css` | 모바일/크롬에서 마이크 터치 시 실시간 받아쓰기 동작 확인, 단위 테스트 |
| **va/2** | 인라인 발음 칩 렌더러 (TTS) 구현 | `static/markdown.js` (또는 파서 분리), `static/chat-features.css` | `[vi]`, `[en]` 태그 칩 변환 및 Web Speech 재생 검증, 단위 테스트 |
| **va/3** | 원터치 현장 보여주기 모드 카드 | `static/app-speech.js`, `static/chat-features.css` | 칩 길게 누름(또는 별도 버튼) 시 대형 폰트 모달 노출 |
| **va/4** | 프롬프트/지침 자연스러운 안내 | `instructions.py` (또는 여행/일상 상황 팁) | 모델에게 필요한 경우에만 가볍게 `[vi]` 태그를 붙이도록 1줄 안내 |
| **va/5** | 음악 검색 (오디오 핑거프린팅 / 곡 찾기) | `route_files.py` (또는 오디오 라우트), `tools/music_recognize.py` | 5초 오디오 버퍼로 곡명/아티스트 반환하는 도구 및 UI 트리거 연동 |

---

## 4. 결정 사항 (Decisions)

| ID | 쟁점 | 선택지 | 결정 및 근거 |
|---|---|---|---|
| **D1** | STT/TTS 엔진 선택 | (a) 브라우저 네이티브 Web Speech<br>(b) 서버 Whisper/XTTS<br>(c) 외부 유료 API | **(a) 브라우저 네이티브 우선**. 비용 0원, 레이턴시 0초, 모바일 최적화. 고도화 보이스는 추후 플러그인(plugin-architecture)으로 확장. |
| **D2** | 마이크 버튼 위치 | (a) 입력창 내부 우측<br>(b) 슬래시/지오 버튼 옆 툴바<br>(c) 전송 버튼 옆 | **(a) 또는 (b)**. 한손 조작이 편한 컴포저 툴바 영역에 배치하여 터치 간섭 방지. |
| **D3** | 발음 칩 문법 규격 | (a) `단어 [lang]`<br>(b) 마크다운 확장 `~단어~{lang}`<br>(c) 코드 블록 | **(a) `단어 [lang]` 형태 권장**. 모델이 일상적으로 쓰기 가장 자연스럽고 토큰 소모가 없으며 모델 간 편차가 없음. |
| **D4** | 언어 코드 매핑 | (a) ISO 639-1 (vi, en, ja, ko, zh)<br>(b) 전체 BCP 47 (vi-VN 등) | **(a) 축약 2자리 지원 + 내부 BCP 47 자동 매핑** (`vi` ➔ `vi-VN`, `en` ➔ `en-US`, `ja` ➔ `ja-JP` 등). |

---

## 5. 완료 조건 (Definition of Done)

1. 모바일(안드로이드/iOS Safari/Chrome) 및 데스크톱 브라우저에서 마이크 버튼 클릭 시 음성으로 텍스트 입력창이 채워질 것.
2. `[vi]` 등 언어 태그가 붙은 텍스트가 시각적인 칩 버튼으로 렌더링되고, 터치 시 원어민 음성으로 재생될 것.
3. 정적 파일 용량 제한(`<= 43,000 bytes`) 및 가드 테스트(`./run-tests.sh`) 전체 통과.
4. 모델 토큰 낭비 없이 엔진 정규식 기반으로 안전하게 렌더링될 것.
