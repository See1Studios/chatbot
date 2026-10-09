# 3자 메시지 시스템: User · Assistant · System 입출력 프로토콜 및 선택지 통합 (message-system-architecture)

> 방향 (2026-10-06 운영자: "메시지시스템 관련 계획문서로 만드는 게 좋을 것 같네"): **핵심 + 기반** — 단순 텍스트 채팅을 넘어 User(발화·지문·명령) - Assistant(대사·표정·선택지) - System(공지·상태·선택지) 3자가 대등하게 상호작용하는 구조화 메시지 프로토콜. 선택지·액션·시스템 알림의 단일 SSOT
> 상태: **superseded** (2026-10-10) — 메시지·선택지의 집은 [engine-decides.md](../engine-decides.md). 모델 기록에 System을 User·Assistant와 대등한 역할로 두지 않는다. 호스트 공지는 화면 이벤트다. ed/B2는 #780으로 들어갔고, ed/B3은 engine-decides에 남아 있다. 이어서 쓰지 않는다.
> 관련: [out-of-band-choices-actions.md](out-of-band-choices-actions.md)(옛 채널 안, 같이 보관) · [engine-decides.md](../engine-decides.md)(ed/B2 #780, ed/B3) · [private-mode.md](../private-mode.md)(텐션 칸) · [layered-context-architecture.md](layered-context-architecture.md)

---

## 1. 배경과 문제 (실측 2026-10-06)

기존 챗봇 아키텍처는 LLM 특유의 `role: "user" | "assistant"` 2자 텍스트 대화 모델에 갇혀 있어 구조적 왜곡과 누더기 구현을 낳았다:

1. **왜곡된 2자 체제**: 호스트/엔진의 상태 변경이나 시스템 알림을 보낼 정규 통로가 없어, `role: "assistant"`에 `notice: "warn"` 같은 필드를 얹어 어시스턴트의 탈을 쓰고 전송했다(`content_guard.py`, `static/app-messages.js`).
2. **선택지(Choices) 시스템의 고립**: 선택지가 어시스턴트 말풍선 끝의 텍스트 주석(`<!--choices: ...-->`)으로만 취급되어, 정작 선택지 버튼이 가장 필요한 시스템 이벤트(재기동 공지, 룸 이동 제안, 티켓 승인 요청)에는 정규 칩을 달지 못했다.
3. **입력창 변조 전송 꼼수**: 사용자가 선택지 버튼을 누르면 정규 메시지 객체로 전송되지 않고, 프론트엔드가 입력창에 `/act (지문)` 텍스트를 채워 넣고 엔터를 치는 비정상적인 우회 경로를 탔다(`static/markdown.js::pickChoice`, `static/app.js::sendAction`).
4. **엔진 상태 머신과의 마찰**: 사적 텐션 슬롯(유지/+1/+2)과 세션 전환 커맨드가 선택지와 직결되어 있는데, 모델에게 복잡한 문법 규칙을 매 턴 강제하느라 4.5%의 누락과 파서 예외가 발생했다(`private_engine.py`, `engine-decides.md` ed/B3).

---

## 2. 3자 행위자 모델 (Actor Model)

대화방에 참여하는 3대 주체(`role`)의 책임을 명확히 분리한다:

| 주체 (`role`) | 주 역할 | 발신 가능한 내용 | 부속 선택지 (`choices`) |
|---|---|---|---|
| **`User`** | 사용자/코치 | • `say`: 일반 발화 텍스트<br>• `action`: 물리/심리 지문 (`/act`)<br>• `command`: 시스템 제어 명령 (`/private`, `/ticket` 등) | 수신자로서 칩을 선택해 전송 |
| **`Assistant`** | 캐릭터 에이전트 | • `text`: 캐릭터 대사/서술<br>• `expression`: 감정 표정 태그<br>• `thought`: 내면 속마음 블록 | **캐릭터 제안 선택지**<br>(대화 답변, 사적 텐션 슬롯) |
| **`System`** | 호스트 엔진/가드 | • `notice`: 시스템 공지/경고/에러/완료<br>• `text`: 시스템 안내 본문 | **시스템 제안 선택지**<br>(재기동 복구, 방 이동, 티켓 승인) |

---

## 3. 정규 메시지 및 Choice 데이터 스키마

### 3.1 ChoiceItem 스키마
```typescript
interface ChoiceItem {
  label: string;                        // 버튼 표시 라벨 (최대 28자)
  kind: "say" | "action" | "command";   // 클릭 시 발생할 사용자 메시지 타입
  payload: string;                      // 실제 발화 텍스트 / 행동 지문 / 실행할 슬래시 명령어
}
```

### 3.2 메시지 객체 스키마 (History & Wire)
```typescript
interface SessionMessage {
  role: "user" | "assistant" | "system";
  text: string;
  ts: number;
  // User 전용
  kind?: "say" | "action" | "command";
  payload?: string;
  // Assistant 전용
  expression?: string;
  thought?: string;
  // System 전용
  notice?: "info" | "status" | "warn" | "error" | "ok";
  // Assistant & System 공통
  choices?: ChoiceItem[];
}
```

---

## 4. '엔진이 정한다' (engine-decides) 통합

1. **ed/B2 사적 대화 이동 제안 엔진 주입**:
   - `personal_turn` 판정 후 쿨다운이 유효하면, 모델에게 이동 문법을 시키지 않고 **엔진이 턴 끝에 시스템 이동 칩 2개를 직접 주입**:
     - `label: "잠깐 <장소>…", kind: "command", payload: "/private on <장소>"`
     - `label: "일 계속하기", kind: "say", payload: "일 계속하기"`
2. **ed/B3 사적 선택지 누락 시 시스템 대체**:
   - 모델이 사적 모드에서 선택지를 누락하면, 텐션 표(`engine_data/private_tension_*.json`)의 슬롯별 기본 행동으로 **엔진이 3개 슬롯을 자동 보충**.
   - 모델은 순수 문구 창작만 담당하며, 상태 전이 계약은 엔진이 보장.

---

## 5. 입출력 파이프라인 정비

1. **발신 (Client → Server)**:
   - 버튼 클릭 시 `inputEl.value` 조작을 전면 제거.
   - `POST /api/sessions/<sid>/message`에 `{ type: item.kind, text: item.payload }`를 직접 전송.
2. **수신 (Server → Client)**:
   - SSE 이벤트 `event: "message"` 및 `event: "notice"`에 `choices: [...]` 필드 정규 포함.
   - `renderChoiceChips`가 발신자(`assistant`든 `system`이든)를 가리지 않고 메시지 하단에 일관되게 칩 렌더링.
3. **히스토리 및 LLM 격리**:
   - `role: "system"`의 UI 공지성 메시지와 커맨드 실행 결과는 LLM 프롬프트 생성 시 제외되어 히스토리 오염 방지.

---

## 6. 단계별 이행 로드맵

* **Phase 1 (기반 완료)**:
  - 1a. 서버가 본문 끝 마커를 분리해 `choices` 필드로 전달 (#140)
  - 1b. `choices` MCP 도구 스키마 및 검증기 추가 (#145)
* **Phase 2 (3자 메시지 및 입력창 직결)**:
  - `role: "system"` 독립 롤 정규화 및 `addNotice` 선택지 지원
  - 클라이언트 버튼 클릭 → 구조화 메시지 `POST` 직결 (`inputEl` 꼼수 제거)
  - 티켓 바(`renderTicketBar`)를 시스템 공지 선택지로 흡수
* **Phase 3 (엔진 주입 및 상태 머신 결합)**:
  - ed/B2 사적 이동 제안 칩 엔진 직접 주입
  - ed/B3 사적 선택지 누락 시 텐션 슬롯 기본값 자동 대체
* **Phase 4 (지침 정리 및 레거시 제거)**:
  - 헌장(`AGENTS.md`) 및 `private_engine.py` 지침을 표준 3종 문법으로 통일
  - 프론트엔드의 복잡한 괄호/따옴표 폴백 휴리스틱 제거
