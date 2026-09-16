# chatbot 개발로그

## 상태 (2026-09-16)

**인계 완료.** 이후 이 표면의 버그/UX/스킬 개선은 GameDeveloper 대신 **이 챗봇 자신**(`chatbot-self-improve` + `task-observer`)이 1차 담당한다.

---

## 2026-09-16 — v0 스냅샷

### 배경
Sphere Hub에 Antigravity(`agy`) 채팅을 붙이면서 VibeCat식 지속 세션 호스트가 생겼다.
- Hermes `antigravity-cli` = `agy -p` 원샷 위임
- Hub chatbot = stream-json 지속 프로세스 (본체)

### 결정
| 항목 | 내용 |
|------|------|
| 프로젝트명 | `chatbot` (캐릭터명 금지, 경로=이름) |
| 페르소나 | `config/persona.json` + `chatbot-data/persona/` (현재 기본=냥피디) |
| 이미지 | SuperGrok Imagine / 기존 persona 자산. chubby jpg 폐기본 사용 금지 |
| Lore 브랜딩 | See1 only (Zero 표기 금지) |
| UX | Hub FAB 팝업 + `/chat/` → `:3011` 전체 창 |

### 레이아웃
| 경로 | 역할 |
|------|------|
| `~/services/chatbot/` | `server.py`, `nas_mcp.py`, `static/`, `config/`, `docs/` |
| `~/services/chatbot-data/` | sessions, artifacts, persona, workspace |
| `~/services/chatbot-ctl.sh` | start/stop/restart/status (+ orphan `agy` 정리) |
| `/volume1/web/index.html` | Hub FAB (`AGY_CHAT_FAB_*` 마커) |
| `/volume1/web/chat/persona/` | 퍼블리시 페르소나 자산 |
| `/volume1/web/chat/vendor/` | marked / mermaid (FAB용) |
| ports | **3011** chat, **3012** NAS MCP |

구 `sphere-agy-*` 는 shim/심링크.

### 구현 완료
1. VibeCat급 지속 `agy` 호스트 + NAS MCP
2. skip-permissions, trusted NAS 경로, `/artifacts/` 서빙
3. 세션 히스토리 복원, 생성 이미지 마크다운
4. 프로젝트화 (`chatbot` / `chatbot-data`)
5. UI: 상단 갤러리 제거, 배경 옅은 오버레이, 얼굴 아이콘, 대화/로그 분리
6. 세션 키 `chatbot.sessionId` 통합, 없으면 **최신 세션 복원**
7. `tool: tool` 스팸 서버 필터 + 클라이언트 스킵
8. marked + mermaid (전체 창 `static/vendor` + Hub `/chat/vendor`)
9. 진행 표시: `…` 대신 말풍선에 `요청 보냄` / `작업 중 ·` / `작성 중…`
10. 자기강화: `task-observer` 심링크 + PreInvocation hook + `chatbot-self-improve` 스킬
11. 재시작 시 orphan `agy` 정리 (`chatbot-ctl.sh`)

### 운영
```bash
~/services/chatbot-ctl.sh status|restart|stop|start
```
Watchdog가 `chatbot-ctl.sh start` 유지.

### 알려진 이슈 / 백로그 (챗봇이 이어받을 것)
- [ ] 페르소나 미소녀 톤 자산 품질 락 / 핫스왑 UI
- [ ] Hub FAB ↔ 전체 창 기능 드리프트 방지 (공통 번들화 검토)
- [ ] `\n` 이스케이프가 HTML 인라인 JS를 깨뜨리지 않도록 배포 레시피 고정
- [ ] 긴 툴 작업 시 진행 문구 품질(툴 이름 파싱) 개선
- [ ] DEVLOG ↔ Sphere Tech 연재 면 연결 여부

### 인계 규칙
- 이 챗 UI/호스트/페르소나/hook/스킬 이슈 → **챗봇에게 시킴** (skill: `chatbot-self-improve`)
- GameDeveloper는 Zero/Godot·Sphere 상위 아키텍처·긴급 복구만
- 위험한 삭제/포트 변경은 실장님 승인
- 관찰 로그: `chatbot-data/workspace/skill-observations/`

---

## 2026-09-16 — 렌더링 정상화, 자산 경로 복구 및 작업 중 샛길 질의(/btw)·대기열·중지 체계 구축

### 변경 내역
1. **마크다운 & 다크 Mermaid 렌더러 로컬 번들링**:
   - `marked.min.js`, `mermaid.min.js`를 `:3011` 및 Web Hub에 로컬 벤더링하여 온프레미스 완전 오프라인 렌더링 지원.
   - 코드 복사 버튼 및 GFM 테이블/인라인 코드/블록쿼트 스타일링 완료.
2. **페르소나 얼굴/배경 자산 경로 정상화**:
   - `:3011` 정적 루트에 자산 심볼릭 링크 생성 및 `mimetypes.guess_type` 적용으로 이미지 서빙 404/MIME 오류 해결.
   - 2중 `onerror` 웹허브 폴백 장착.
3. **작업 중 샛길 질문 (`/btw`) & 자동 감지 (Auto-Inquiry)**:
   - 긴 턴 실행 중에도 메인 `stdin`을 방해하지 않는 경량 Flash 모델 기반 1회성 사이드 채널 서빙 (`_run_btw`).
   - 사용자가 굳이 `/btw`를 입력하지 않아도 물음표(`?`) 또는 의문형 한국어 어미를 감지하여 자동으로 샛길 답변 카드로 즉시 응답.
4. **반응형 전송 버튼 & 안전 대기열 (Message Queueing)**:
   - 작업 중 지시문 입력 시 버튼이 `대기열 등록 ↵`으로 전환되며, 큐에 보관 후 작업 완료 즉시 자동 연쇄 실행.
   - 작업 중 질문 입력 시 버튼이 보라색 `샛길 질문 ✦`으로 자동 전환.
5. **명시적 작업 중지 (`[중지]` 버튼)**:
   - 작업 진행 중일 때만 노출되는 빨간색 중지 버튼 추가 (`POST /api/sessions/:id/stop`).
   - 세션 프로세스 및 대기열을 즉시 안전 정리하고 `event: stopped` 알림 전파.
6. **데몬 프로세스 안전성 강화 (`chatbot-ctl.sh`)**:
   - `kill_orphan_agy`가 부모가 살아있는 agy를 죽이지 않도록 `PPID=1` 고아 프로세스만 타깃하도록 엄격화.


## 2026-09-16 — 긴급: 메시지 데드락 (ensure→spawn→stop)

### 증상
- `:3011` health는 살아 있는데 전송(POST `/message`)이 응답 없이 멈춤 → UI가 망가진 것처럼 보임
- 서버 재시작 직후/세션에 agy proc 없을 때 재현

### 원인
- `AgySession.ensure()`가 `threading.Lock`을 잡은 채 `_spawn()` → `stop()` 호출
- `stop()`이 같은 `Lock`을 다시 획득하려 해서 **데드락**
- `/btw`·대기열·중지 추가 과정에서 `stop()`이 `_spawn` 경로에 들어간 뒤 표면화

### 수정
- `self.lock = threading.RLock()` (세션 락만; REG 락은 그대로)
- `/stop` 응답에 session 스냅샷 포함
- 백업: `server.py.bak-deadlock-202609160820`

### 검증
- POST `/message` ~11ms 200, agy 기동, assistant 답변 수신 확인


## 2026-09-16 — 재발 방지: doctor / repair / 워치독 프로브

### 추가
- `chatbot-ctl.sh`: `doctor [--auto-repair]`, `probe`, `repair`, `guard`
- `guard`: AST로 `AgySession.lock == RLock` 강제 (Lock 회귀 시 start 거부)
- `probe`: throwaway 세션에 POST `/message` (healthz가 못 잡는 데드락 탐지)
- 프로브 스로틀 기본 600s (`CHATBOT_PROBE_EVERY_SEC`, `CHATBOT_FORCE_PROBE=1`)
- `gateway-watchdog.sh`: `start` → `doctor --auto-repair`
- `docs/EMERGENCY.md` 비상 수리 카드


## 2026-09-16 — 자기수정 경계 문서 전달 (실장님)

- `chatbot-data/workspace/SELF-MODIFY.md` (+ docs 복사)
- AGENTS.md / PROJECT.md / `chatbot-self-improve` 스킬에 강제 참조
- 요지: 디스크 설계도·재기동 후 코어 OK / 라이브 자가 뇌수술 금지 / 외부 doctor·repair


## 2026-09-16 — 아티팩트 전용 탭 & 라이트박스 뷰어 구축

### 배경 및 요청
- 실장님 요청: "채팅 도중 생성한 이런 이미지나 파일 (아티팩트?)들을 열람할 수 있는 별도의 탭이나 공간이 있으면 좋겠어"
- 생성된 미디어(이미지) 및 문서/코드 파일들이 긴 대화창 속에서 유실되지 않고 한눈에 파악, 열람, 다운로드 및 인용할 수 있는 전용 공간 필요.

### 구현 내용
1. **백엔드 아티팩트 API (`server.py`)**:
   - `AgySession.get_artifacts()`: 세션 brain 디렉터리, `chatbot-data/workspace/artifacts`, 페르소나 갤러리 및 캐시를 일괄 스캔.
   - 파일 크기 및 파일명 스템 기반 중복 이미지 필터링.
   - `_safe_artifact_rel()`: 이미지뿐만 아니라 `.md`, `.txt`, `.json`, `.py`, `.sh` 등 문서/코드 파일도 brain 내에서 안전하게 서빙하도록 확장.
   - 엔드포인트 `GET /api/sessions/:id/artifacts` 및 `GET /api/artifacts` 제공.
2. **헤더 3단 탭 네비게이션 (`index.html`)**:
   - 상단 바에 `[💬 대화]`, `[📁 아티팩트 <span id="artBadge"></span>]`, `[📜 로그]` 탭 스위처 배치.
   - 보유 아티팩트 개수 뱃지 표시.
   - 아티팩트 탭 상태에서도 하단 메시지 입력창(컴포저)이 유지되어 파일을 보면서 질문하거나 인용 가능.
3. **아티팩트 갤러리 및 필터 UI (`app.js`, `index.html`)**:
   - 반응형 카드 그리드: 호버 줌 썸네일, 파일 형식 아이콘(💻 코드, 📄 문서), 파일 크기 및 생성 일시.
   - 카테고리 필터(`전체`, `이미지`, `문서/코드`) 및 `[새로고침 ↻]` 버튼.
   - 카드 액션: `[미리보기]` 모달 및 `[인용 💬]` (채팅창에 마크다운 자동 삽입 후 대화 탭으로 즉시 전환).
4. **라이트박스 모달 뷰어 (`#artModal`)**:
   - 고해상도 원본 이미지 확대 및 텍스트/코드 파일 실시간 내용 뷰어.
   - `[다운로드]` 및 `[채팅에 인용]` 버튼 제공. ESC 키 및 배경 클릭 시 닫기.
5. **실시간 SSE 동기화**:
   - 작업 도중 새로운 이미지가 생성(`event: image`)되거나 작업이 완료(`event: result`)될 때 백그라운드에서 자동으로 아티팩트 목록과 뱃지를 갱신.


## 2026-09-16 — 세션 비대화·ADD_DIRS 축소·프로브 agy 정리 (latency)

### 배경
- 메인 세션 `20260916-064817-8da2bb` / cid `8e51e0c6-…`: UI hist ~61턴이지만 conversation.db ~19MB·brain ~8MB·216 steps → 같은 세션 비대화가 체감 지연의 주원인.
- doctor 프로브 flash-low agy가 `--conversation` 없이 호스트 자식으로 남는 경우 있음 (기존 `kill_orphan_agy`는 PPID=1만 정리).

### 변경
1. **ADD_DIRS 축소** (`server.py`)
   - 유지: `chatbot`(ROOT), `chatbot-data`(DATA), `/volume1/web/chat`
   - 제거: 전체 `HOME`, `/volume1/web`, `.hermes`, `HOME/services`, 중복 artifacts/workspace 단독 항목
2. **세션 길이 가드**
   - soft: turns≥40 또는 hist chars≥15k 또는 db≥5MB → SSE `session_heavy` + UI 배너(한/새 채팅 버튼)
   - hard: turns≥60 또는 chars≥25k 또는 db≥8MB → 다음 메시지에서 **새 세션 자동 생성**(`session_rotate`, 구 세션/DB 삭제 안 함)
3. **ctl doctor/repair**
   - `kill_orphan_agy`: PPID=1 + **no `--conversation`** + (보호되지 않은 flash-low) 정리
   - probe: `stop`+`/discard` 후 prune 재실행
4. UI: `static/index.html` 배너, `app.js` + Hub FAB SSE/rotate 처리

### 검증
- `chatbot-ctl.sh guard` / `doctor` / healthz / 프로브 후 flash-low 잔존 없음


## 2026-09-16 — 스마트폰 가상키보드 대응 & 모바일 반응형 UX 최적화

### 증상 및 원인
- 스마트폰에서 대화창 터치 시 가상키보드가 올라오면서 상단 헤더와 대화가 화면 위로 밀려 사라짐.
- 원인:
  1. `.stage`, `#log`, `#artifacts`, `#activity`에 `min-height: 420px`가 강제되어 키보드 영역(300~350px) 확보 불가로 윈도우 스크롤 발생.
  2. `body`와 `.wrap`에 `min-height: 100vh`가 적용되어 키보드 팝업 시 포커스된 `textarea`를 브라우저가 화면 중앙으로 스크롤하면서 헤더 영역이 화면 밖으로 벗어남.
  3. `textarea` 폰트 크기 및 높이가 모바일 미최적화되어 iOS 자동 줌 및 화면 압박 발생.

### 변경
1. **뷰포트 및 스크롤 고정 (`static/index.html`)**:
   - `meta[name=viewport]`에 `viewport-fit=cover, interactive-widget=resizes-content` 추가.
   - `html, body`: `height: var(--app-height, 100dvh); overflow: hidden;` 로 윈도우 스크롤 차단.
   - `.stage`, `#log`, `#artifacts`, `#activity`: `min-height: 420px` 제거, `flex: 1 1 0; min-height: 0;` 적용하여 키보드가 열려도 내부 스크롤만 유연하게 축소/동작.
2. **모바일 컴팩트 헤더 (`@media (max-width: 640px)`)**:
   - 아바타 34px, 서브텍스트 숨김, 패딩 및 여백 대폭 슬림화로 상단 고정 헤더 영역 확보.
3. **가상키보드 연동 & 입력창 최적화 (`static/app.js`)**:
   - `window.visualViewport` 리사이즈 및 스크롤 이벤트 감지하여 `--app-height` 실시간 업데이트.
   - `textarea` 16px 지정(iOS 포커스 시 자동 확대 방지) 및 1줄(38~42px)에서 입력 내용에 따라 최대 90~120px로 자동 확장(auto-grow).
   - 입력창 포커스 시 최신 대화 위치로 부드럽게 스크롤.
4. **Hub FAB 모바일 대응 (`/volume1/web/index.html`)**:
   - 모바일에서 FAB 팝업 시 화면 전체(Full-screen sheet) 모드로 열리도록 스타일 및 VisualViewport 핸들러 동기화.



## 2026-09-16 09:10 KST — successor-sticky rotate
- hard 세션 rotate 시 `successor_session_id` 재사용 (매 POST마다 새 세션 생성 금지)
- GET hard+successor → `redirect_session_id` 노출; UI boot/openSession이 successor로 점프
- hard `20260916-064817-8da2bb` meta에 successor 지정; ctl restart + guard/smoke


## 2026-09-16 — FAB↔전체창 세션 패리티 마무리
- FAB: 이어하기(continue) + 세션 길이 배너 + SSE 자동 재연결
- 전체창: SSE 재연결 동일
- ctl: 호스트 재시작 후 conversation 고아 agy(PPID≠chat) 정리
- SELF-MODIFY: 라이브 턴에서 `chatbot-ctl.sh restart` 금지 (스트림 단절)


## 2026-09-16 — host self-restart hard gate
- Repeated SSE drops: live agy ran `chatbot-ctl.sh restart` mid-turn (background webp work)
- `stop`/`restart` require `CHATBOT_FORCE_HOST=1`; `repair` exports it
- Persona: half.webp ~132KB / face-icon.webp ~19KB (png was multi-MB)


## 2026-09-16 — ⚡전기충격·심폐소생 버튼
- ctl: `defibrillate|shock|cpr` → FORCE repair
- API: `POST /api/host/defibrillate` (202 후 백그라운드 repair), `GET /api/host/status`
- UI: FAB `⚡소생`, 전체창 `⚡ 소생` — confirm → repair → healthz 폴링 → 세션 재연결


## 2026-09-16 — host ticket gate (FORCE bypass closed)
- Model bypassed FORCE by exporting `CHATBOT_FORCE_HOST=1` then restart
- stop/restart now need FORCE **and** fresh `{DATA}/host-force.ticket` (TTL 120s)
- Ticket minted only by `repair` / API defibrillate; consumed on EXIT


## 2026-09-16 — 상세 도구 실행 로그 & 결과 파싱 지원 (0 추가 토큰)
- 배경: 실장님 피드백("로그가 좀 더 자세히 찍히면 좋겠어. 지금은 제목만 나오네. 토큰이 추가적으로 든다면 안해도 되고.")
- 핵심: LLM 추가 호출 없이 agy 로컬 stream-json에 이미 존재하는 도구 인자(명령어, 파일 경로, 액션 요약 등) 및 결과 요약을 파싱하여 노출. **추가 토큰 소모 0**.
- `server.py`:
  - `_format_tool_call`: 도구별 핵심 인자(run_command의 CommandLine, view_file의 AbsolutePath/Line, grep/find의 Query/Pattern, edit/write의 TargetFile/설명 등)를 사람이 읽기 쉬운 한 줄 요약으로 포맷.
  - `_format_tool_result`: 도구 결과(type=GENERIC, tool_result)의 첫 유의미한 라인과 요약 반환 (`↳ 결과... (외 N줄)`).
  - `_tool_summary`: `tool_calls` 리스트 및 `GENERIC` 결과 파싱 확장, 도구 이벤트 리스트 반환 지원.
- `static/app.js` & `/volume1/web/index.html`:
  - UI `addActivity(line, kind)` 확장 및 카테고리별 컬러 하이라이팅(`.act-tool` 파랑, `.act-result` 회색/들여쓰기, `.act-error` 빨강, `.act-warn` 주황).
  - 서버 재기동 전에도 즉시 반영되도록 `event: agy`의 payload `tool_calls`/`GENERIC` 클라이언트 폴백 파서 탑재.
  - 브라우저 캐시 버스터 `app.js?v=10` 갱신.
- 안전: 라이브 자가 재기동 금지 규칙 준수. 프론트엔드는 새로고침(F5)으로 즉시 적용, 서버 코어는 디스크 반영 완료 (다음 소생/재기동 시 로드).



## 2026-09-16 — 정체성 강화 (자가진화형·고양이 수인·만능 콘텐츠 크리에이터)
- 실장님 요청: "자가진화형 미소녀 고양이 수인 만능 컨텐츠 크리에이터 챗봇" 정체성 강화
- `PERSONA.md` / `AGENTS.md` (workspace)에 정체성(Identity) 섹션 추가:
  - 자가진화형: SELF-MODIFY.md 원칙 그대로, 스스로 성장하는 걸 자부심으로 삼는 성격 서술 추가
  - 미소녀 고양이 수인: 기존 비주얼 락(풀 동물화 금지, 귀·꼬리 악센트) 유지한 채 명시적으로 재확인
  - 만능 콘텐츠 크리에이터: NAS 운영 비서 범위를 넘어 이미지 프롬프트/카피/자막/문서/코드 등 콘텐츠 제작자 역할 명시, Domain & Lore scope에 반영
- `persona.json`(config)은 코드에서 미참조 확인 → 변경 대상 아님, 손대지 않음
- 코어 코드(server.py) 무변경 — 세션 스폰 시 agy가 읽는 workspace 파일만 수정, 재기동 불필요, 다음 새 세션부터 반영
- smoke: healthz OK


## 2026-09-16 — 자기 상태 대시보드 (⚙ 상태 탭) + task-observer 정식 업그레이드
- 실장님 요청: 규칙/MCP/스킬/훅/플러그인 현재 상태를 보고 관리할 수 있는 UI
- **task-observer**: 워크스페이스 사본이 구버전(446줄, references 3/7)이었음 → FIREBAT 최신판(709줄, references 7/7)으로 교체.
  기존 legacy `skill-observations/log.md`(관찰 5건, 전부 APPLIED)를 신규 per-file 포맷(`observation-log/0001~0005-*.md`)으로 마이그레이션, `log.md` → `log.md.migrated`로 보존.
  `last-review-date.txt`는 정직하게 `never` 유지 (실제 주간 리뷰가 실행된 적 없어서 — 지어내지 않음).
- **신규 관찰 0006 (OPEN)**: `/skill <name> ...` 형태 메시지가 agy를 무응답으로 죽이는 버그를 실측으로 확인 (평문 채팅은 9초 내 정상 응답, `/skill korea-weather ...`는 SKILL.md 스텁을 view_file로 읽은 직후 응답 없이 프로세스 종료 — k-skill.sh cli-stub → npx 후속 호출 이전에 죽음). 근본원인 미확정 (agy 단독 재현은 하니스의 "Create Unsafe Agents" 분류기에 막힘) — `chatbot-ctl.sh doctor`에 스킬 전용 스모크 테스트 추가를 제안.
- **API 추가 (server.py)**: `GET /api/self-status` (규칙/스킬/MCP/훅/task-observer 요약), `GET/PUT /api/rules/:name` (AGENTS/PERSONA/PROJECT/SELF-MODIFY 읽기·편집, 편집 시 `.bak-selfstatus-<ts>` 자동 백업), `GET/POST /api/mcp` + `DELETE /api/mcp/:name` (nas는 core라 삭제 불가), `POST /api/skills/:name/toggle` (워크스페이스 스킬 on/off, `_` 접두사로 비활성화).
- **UI 추가**: 4번째 탭 `⚙ 상태` — 규칙 파일 목록(편집 버튼→textarea 저장), 프로젝트 스킬 토글, MCP 서버 목록+추가/삭제, 훅/플러그인 안내, task-observer 상태 요약. `app.js?v=11`.
- 안전: 이번 변경은 server.py 코어 변경이라 재기동 필요 — 라이브 세션 2개 있어 즉시 재기동하지 않고 실장님 ⚡소생 대기 (SELF-MODIFY.md 원칙 준수). static(index.html/app.js)은 재기동 없이 새로고침만으로 반영됨.
- smoke: `python3 -m py_compile server.py` OK. 재기동 후 `/api/self-status` 응답 및 상태 탭 렌더링 확인 필요 (TODO).

## 2026-09-16 — 프롬프트 최적화: AGENTS.md 중복 제거 + SELF-MODIFY.md 조건부 로드
- 실장님 질문: 프롬프트 최적화 가능한지
- 발견: `AGENTS.md`에 host-restart 규칙이 `Host safety`와 `Host restart — hard rule` 두 섹션에 중복 서술돼 있었음 (하나로 병합, 내용 손실 없음). `Observation Protocol`의 `skill-observations/log.md` 경로도 오늘 마이그레이션으로 stale해진 걸 발견해서 `observation-log/`로 수정.
- **진짜 최적화 지점**: `SELF-MODIFY.md`(4.1KB, 4개 규칙파일 중 최대)가 코드/호스트를 전혀 안 건드리는 일반 대화/콘텐츠/NAS-ops 턴에서도 매번 읽힐 가능성이 컸음 (AGENTS.md가 무조건 "Obey SELF-MODIFY.md"라고만 했음). AGENTS.md의 self-modification 규칙을 "핵심 한 줄은 항상 유효, 전체 문서는 실제 코드/호스트를 건드릴 때만 view_file"로 명시적으로 게이팅함.
- 참고: AGENTS.md 자체 바이트 수는 거의 그대로 (3708→3826, 게이팅 설명 문장이 길어서) — 절약은 파일 크기가 아니라 "코드 안 건드리는 턴엔 SELF-MODIFY.md 안 읽음"이라는 행동 변화에서 나옴.
- 재기동 불필요 (AGENTS.md는 세션 스폰마다 새로 읽힘). healthz OK.

## 2026-09-16 — SSE 멀티 클라이언트 브로드캐스트 패치 (스트리밍 글자 누락/핑퐁 버그 수정)
- 증상: 동일 세션에 브라우저 창/탭이 복수 연결(또는 재연결)되어 있을 때, 스트리밍 텍스트 청크(`delta` 이벤트)가 각 클라이언트로 홀수/짝수 번갈아가며 분할 소비되어 화면상에 글자가 듬성듬성 통째로 누락되는 현상 발생.
- 원인: `AgySession.events`가 단일 `queue.Queue`로 구현되어 있어, 복수 SSE 연결(`_sse`)이 동일 큐에서 `.get()`을 호출하며 이벤트를 1:1로 가로채가는 구조적 결함.
- 해결: `AgySession.subscribers` 리스트를 도입하여 `_emit` 시 활성 SSE 연결 각각의 전용 큐로 브로드캐스트하도록 수정. `_sse` 종료 시 `finally` 블록에서 안전하게 구독 해제.
- 검증: `python3 -m py_compile server.py` 통과, `chatbot-ctl.sh guard` (guard_rlock OK) 통과.
- 안전: 라이브 세션 보호를 위해 디스크 패치만 완료 (`SELF-MODIFY.md` 원칙). 상단 ⚡소생 버튼 또는 다음 서비스 재기동 시 자동 적용.

## 2026-09-16 — 진짜 원인 확정: doctor의 orphan-kill이 방금 시작한 세션을 죽임 (`/skill` 무응답 사망 버그)
- 배경: 관찰 0006 — `/skill korea-weather ...` 등 스킬 호출이 간헐적으로 무응답으로 죽는 버그. 처음엔 k-skill cli-stub → npx 후속 호출 과정의 크래시로 추정했으나 틀렸음.
- 진단: `AgySession.to_public()`에 `debug_stderr_tail`(프로세스 죽었을 때만 최근 stderr 15줄 노출) 추가 → 재현했더니 완전한 정답을 다 준 뒤에도 죽으면서 stderr에 `stream input cancelled: context canceled` 포착. "스킬 호출 자체가 깨진다"가 아니라 "정상 작업 도중 뭔가 죽인다"로 방향 전환.
- **진짜 원인**: `chatbot-ctl.sh`의 `kill_orphan_agy()`가 `--conversation` 플래그 없는 agy 프로세스를 전부 "doctor 프로브 잔재"로 간주해 즉시 SIGTERM. 그런데 **신규 세션의 첫 턴도 원래 `--conversation`이 없음**(agy 응답을 받아야 conversation_id를 알 수 있음) — doctor의 주기적(~600초) 정리가 하필 첫 턴 처리 중에 돌면 진짜 대화를 죽여버림. `/skill`은 `view_file`+`npx` 등 추가 호출로 30~40초 걸려서 평문 채팅(~9초)보다 이 창에 걸릴 확률이 훨씬 높았을 뿐, `/skill` 고유 버그가 아니었음.
- 수정: `kill_orphan_agy()`(`chatbot-ctl.sh`)에 `NO_CONV_GRACE_SEC=90` 유예 시간 추가. `ps -eo pid=,ppid=,etimes=,args=`로 경과 시간(etimes)까지 받아서, `--conversation` 없는 프로세스라도 90초 이내면 죽이지 않음. `ppid==1`(진짜 고아) 조건은 그대로 즉시 정리.
- **실측 검증**: `/skill korea-weather 부산 날씨` 전송 후 5초 시점에 `--conversation` 없이 살아있는 걸 `ps`로 확인, 그 순간 `chatbot-ctl.sh doctor`를 수동 실행 → `orphan_agy_killed=0`으로 안 죽음 확인, 35초 뒤 정상 응답 + `alive: true`로 완료. 서버(`server.py`) 재기동 불필요 — `chatbot-ctl.sh`는 독립 스크립트라 다음 실행부터 바로 반영.
- 관찰 0006을 `status: actioned`로 갱신, 근본원인 정정 기록.

## 2026-09-16 — 음성 입력(STT)/읽어주기(TTS) 추가
- 배경: 실장님 요청 — TTS/STT 지원. agy 자체 `/voice`(F5) STT는 확인했지만 대화형 터미널+로컬 마이크 전용 기능이라 헤드리스 stream-json 서버 구조엔 안 맞음(브라우저 사용자 마이크를 agy 프로세스로 연결할 방법이 없음). TTS는 agy에 아예 내장 안 됨. 그래서 브라우저 네이티브 Web Speech API로 구현 — 서버/agy 변경 없이 순수 프론트엔드.
- **STT (`static/index.html`, `static/app.js`)**: 컴포저에 🎤 버튼 추가. `SpeechRecognition`/`webkitSpeechRecognition`(`lang=ko-KR`, `interimResults=true`)으로 실시간 받아쓰기 → `#input`에 반영. 듣는 중엔 버튼이 빨갛게 pulse 애니메이션. 미지원 브라우저(Firefox 등)는 버튼 반투명 처리 + 클릭 시 안내.
- **TTS**: 완성된 assistant 메시지 하단에 🔊 버튼 추가 (`attachTtsButton`, `postProcessAssistant`에 raw markdown 텍스트 전달). `stripMarkdownForSpeech()`로 `**`/`#`/코드블록/테이블 등 마크다운 문법 제거 후 `speechSynthesis`로 재생, 한국어 음성(`lang.startsWith('ko')`) 자동 선택. 재생 중 버튼 🔊→⏹ 전환, 다시 누르면 정지.
- 캐시 버스터 `app.js?v=12`.
- 범위: 전체창(`:3011`)만 적용. Hub FAB(`/volume1/web/index.html`)은 별도 컴포저라 아직 미적용 — 필요하면 FAB↔전체창 패리티 작업 때 같이.
- 재기동 불필요 (순수 static 파일). git 커밋: `a869cad`.

## 2026-09-16 — AgentAdapter 구조 도입, 사용량(/usage) 대시보드, 응답 속도 최적화(프로세스 프리웜)
- **AgentAdapter (구조만)**: 실장님 요청 — VibeCat(`Source/VibeCat/Private/AgentAdapters.cpp`)처럼 여러 provider를 고려한 설계로 리팩터 가능한지 문의받아 진행. `AgentAdapter` 베이스 + `AgyAdapter` 구현체 추가 (`find_executable/build_args/build_env/format_stdin`). `AgySession._spawn()`/`_send_direct()`가 하드코딩 대신 `self.adapter`를 통해 프로세스 스폰·stdin 작성. `claude`/`codex`/`grok` 어댑터는 미구현 — diskstation엔 `grok`만 설치돼 있고 나머지는 없어서, 실제 필요해지면 그때 상속 추가. `_read_stdout`의 stream-json 파싱(~300줄, 오늘 데드락 사고 2건의 근원지)은 의도적으로 안 건드림 — 구조만 요청 범위 밖. 커밋 `2de9e0b`.
- **사용량 대시보드**: 실장님 문의 — `agy`에 `/usage`(모델별 주간/5시간 한도) 확인 기능이 있는지. 확인 결과 `/usage`는 stream-json 세션 안에서는 못 쓰고(`agy` 자체가 명시적으로 에러 반환: "unavailable with --input-format stream-json"), `agy --print /usage`로 별도 단발 호출해야 함. `GET /api/usage` 추가 — 5분 캐싱, `?force=1`로 강제 재조회. ⚙ 상태 탭에 "📊 사용량" 섹션(모델별 잔여율 바 차트, 20% 이하 빨간색). 커밋 `f7a168b`.
- **응답 속도 조사**: 실장님이 "첫 메시지가 느리다"고 보고. 실측 결과 — 같은 세션 두 번째 메시지부터는 ~3.5초인데 신규 세션 첫 메시지는 ~10초. `agy --print` 단독 호출도 모델/effort 무관하게 항상 7~9초 걸리는 걸 확인 (네트워크 지연 아님 — googleapis.com TTFB는 0.3초 수준; CPU도 1.3초만 씀 → 나머지 ~7초는 agy/Antigravity 백엔드 자체의 고정 콜드스타트 오버헤드).
- **표준 대기(prewarm) 풀 도입**: `_StandbyPool` — DEFAULT_MODEL·effort 없음 조건으로 idle agy 프로세스 1개를 항상 미리 띄워둠 (`_standby_maintenance_loop`, 15초마다 점검). 신규 세션 첫 메시지가 이 조건에 맞으면 콜드스팟 대신 이 프로세스를 즉시 인수(adopt). 못 쓰이고 남은 standby는 `--conversation` 없는 상태라 기존 `kill_orphan_agy`의 90초 유예 로직이 자동으로 정리 — 별도 만료 로직 불필요. **실측 검증**: 신규 세션 첫 메시지 10초 → **3.5초**로 단축 확인, standby 소비 후 재충전도 확인. 커밋 `005243c`.
- **사용량 감소 체감 관련 별도 발견**: `chatbot-ctl.sh`의 doctor 프로브가 10분마다(`PROBE_EVERY_SEC=600`) **실제로 새 프로세스를 띄우고 진짜 메시지를 gemini-3.8-flash-low에 전송**해서 정상 응답을 확인함 — 주간 최대 ~1,000회, 실장님 대화량과 무관하게 상시 실제 토큰 소비. 다음 작업으로 healthz 우선·의심될 때만 실제 메시지 보내는 2단계 프로브로 최적화 예정 (진행 중).
