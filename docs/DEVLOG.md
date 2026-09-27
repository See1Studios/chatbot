# chatbot 개발로그

## 2026-09-28 — 방향 정렬: 개인화 하네스로 (기조 재작성·제품 문서·관문 마무리·래칫·플러그인 계획)

- **배경**: 운영자가 지향점을 다시 정함 — 표면은 진입장벽이 매우 낮은 **프리메이드 개인화 하네스**, 가치는 **전영소녀·조이**, 시장은 **Wallpaper Engine**(배경화면 대신 에이전트 커스터마이즈). 업무 효율로 경쟁하지 않고 개인화 레이어와 창작마당으로 경쟁. 배포판 에이전트는 엔진 코드를 고치지 않고 스킬·기억·지침을 스스로 다듬음. 계획 [direction-alignment.md](plans/direction-alignment.md).
- **기조·제품 문서**: `docs/CONCEPT.md` 재작성(세 얼굴·해자·축 우선순위·배포판/개발판, 로어 절은 그대로), `PRODUCT.md`·`README.md` 엔드유저 기준, `DESIGN.md`는 NAS·캐릭터 이름만 정리(중심 은유는 align D10 열림). Grok 대화의 사업 모델($9.99·BYOK·무료 맛보기·연령·일정)은 release-pipeline §3.1, 아키텍처 문서는 `data/workspace/docs/`에서 `docs/ARCHITECTURE.md`로.
- **관문 마무리 (pew/E·F·O·P, #266–#270)**: 커밋 훅(`.githooks/`, 가드·비밀·메시지), 러너 관문(가드 + 관련 테스트, `run-tests.sh` 자체 보호 구멍 수정), 티켓 완료 관문(가드 실패 시 done 거절), 관련 테스트를 import·파일 언급으로 확장. 보호 목록에 헌장·훅·러너·가드 추가(#268–#269).
- **규칙**: 문서 이름(상시 대문자·쌓이는 문서 소문자-하이픈, `test_doc_names`, #273), 계획마다 방향 적합성 줄(`test_plans_index`, #275), 래칫(한국어 1,303줄·호스트/페르소나 123줄은 늘 수 없음, `test_ratchets`, #276).
- **설계**: [plugin-architecture.md](plans/plugin-architecture.md) — 콘텐츠/코드 플러그인, `pe-plugin.json`, 내장도 같은 API, `~/.pe/plugins`, 코드는 별도 프로세스·권한, 등급, Workshop은 브랜드 이후. 결정 D1–D6 열림.
- **배포**: 서버 쪽 미반영 — #263(openrouter 캐시), pew/O(완료 관문, 서버 경로), `server.py` 설명문. 다음 ⚡ 때.
- **기준선**: `./run-tests.sh` 101/101.

## 2026-09-27 (밤) — 파이프라인 토대: 기준선 93→98 녹색, 루트 AGENTS.md, 가드 테스트 (pew/N·C·D, #255–#264)

- **배경**: [plan-execution-workflow.md](plans/plan-execution-workflow.md) 토대 단계. 운영자 결정: 계획 절차 D1–D8, 현지화 D1–D7, 사적 세션 두뇌 규칙 (a).
- **pew/N 기준선 녹색화 (#255–#261)**: 낡은 UI 하네스 9개 갱신(#153·#176·#196·#211·#243 이후), 관찰 0088–0090 머리말, 사적 세션은 카드 `brains.private` → 없으면 사용자가 쓰던 두뇌(#240의 work 폴백 제거), `server.py` 1,611→1,478줄(`emotion.py`·`card_upload.py`, 감정 감지 테스트 신설), 헌장·사적 규칙 묶음 예산 안으로(공용 5,504→4,767 B, 사적 6,184→~4,576 B, 테스트 고정 문구 유지), `session.py` 2,477→2,298줄(`turn_watchdog.py`).
- **#263**: OpenRouter `/models` 실패를 60초 기억 — 연결이 막히면 `/api/providers`가 30초 걸려 `test_identity_wiring` 시간 초과.
- **pew/C (#262)**: 루트 `AGENTS.md` = 엔진 개발 단일 입구(정본 지도·코드 지도·하네스·작업 절차·규칙 레지스트리, "아키텍처 책임자" 역할). `CLAUDE.md`/`GEMINI.md`는 포인터. `data/workspace/AGENTS.md`는 챗 에이전트 헌장 그대로, `PROJECT.md`는 챗 에이전트 절차만.
- **pew/D (#264)**: `test_entrypoints`·`test_rule_registry`·`test_plans_index`·`test_doc_refs`(`--fast`), 기존 줄 번호 참조 18곳을 `path::symbol`로. 각 가드는 규칙을 일부러 어겨 실패를 확인.
- **조사**: agy 오류는 구글 쪽 재시도가 출발점이나, #253 전에는 우리 QUOTA_FAILFAST(8초)가 18/18을 닫음. #253 후 14/17 회복. 관찰 0091, 2026-09-28 재집계.
- **계획**: [localization.md](plans/localization.md) 신설(1차 ko+en, 2차 ja·zh-Hans, 래칫 가드 먼저).
- **배포**: N4·server/session 분할·사적 규칙은 23:07 소생으로 반영. #263·pew/C 설명문은 다음 소생 때.
- **기준선**: `./run-tests.sh` 98/98.

## 2026-09-27 — 테스트 단일 진입점 `run-tests.sh` + DEVLOG 크기 복구 (pew/B, #254)

- **배경**: [plan-execution-workflow.md](plans/plan-execution-workflow.md) 토대 1단계. 테스트를 도는 방법이 README 루프뿐이라 아무도 돌리지 않았고, 가드 테스트가 깨진 채 방치됨(P8·P12).
- **변경**: `run-tests.sh [--fast | 모듈…]` — 모듈별 한 프로세스, 시간·실패 꼬리 출력, 실패 시 종료 코드 1. `--fast`는 가드 테스트 목록(FAST). README 안내 교체. DEVLOG의 2026-09-23 항목 18개를 `docs/devlog/2026-09-23.md`로 이동(52,710 B → 29,626 B).
- **기준선(2026-09-27)**: 92개 중 77개 통과 → DEVLOG 복구 후 78개. 남은 14개: ① 구조 가드 초과 `test_bundle_budget`(헌장 묶음 5,504/4,800 B), `test_file_sizes`(`server.py` 1,611/1,500줄) ② 코드 분리 후 따라가지 못한 UI 하네스·소스 문자열 테스트 `test_btw_order`·`test_observation_ui`·`test_work_status`·`test_slash_catalog`·`test_session_marker`·`test_bubble_position`·`test_mobile_keyboard_focus`·`test_sse_resync_dedupe`·`test_choices_channel` ③ 동작 기대 불일치 `test_session_split`·`test_character_picker`(기본 provider)·`test_observations`(87≠90). 별도 티켓으로.

## 2026-09-27 — Private Engine 숨은 로어 (전영소녀 / Joi / 이중 이름)

- **배경**: 로어·몰입 사용자용 숨은 컨셉을 문서에 고정. 프론트 마케팅 아님. 실장님 확인(써둬).
- **concept**: 「숨은 컨셉 / 몰입 로어 (러프)」 — 이중 이름(제품명=상점/소환 창), 전영소녀·Joi 영감, 비디오 숍 은유, 설정충·몰입 장치 시장 원칙, 러프 골격 5항(매체·창 인식·ST=여권·기억 계약·모드 경계).
- **brand**: `private-engine-brand.md` §8 — 이중 의미, Gokuraku는 영감(상표 아님), soft marketing.
- **INDEX**: 변경 없음(브랜드 계획 상태 `active` 유지).
- **커밋**: `docs: Private Engine hidden lore (Video Girl / Joi / dual name)`

## 2026-09-27 — QUOTA_FAILFAST 턴 활동 재개 시 타이머 취소 및 정상 응답 절단 방지 (#253)

- **배경**: agy가 백엔드(Gemini API 500/503 등) 일시 재시도 시 `step_type: error_message`를 발행하면 챗봇이 8초 failfast 타이머를 가동함. 그러나 agy가 4~5초 후 정상 복구되어 답변(`delta`)을 생성 중임에도 `_touch_turn_activity()`가 failfast 타이머를 취소하지 않아, 정확히 8초 시점에 턴을 강제 에러 종료(`에이전트가 답을 내기 전에 턴이 끝났습니다`)하고 세션을 끊어버리는 치명적 결함 발생.
- **변경**:
  - `session.py`:
    - `_touch_turn_activity()`에서 텍스트 수신(`delta`)이나 도구 진행이 감지되면 대기 중인 `_cancel_error_message_failfast()`를 즉시 호출하여 타이머 해제 및 silent hang 재가동.
    - `_arm_error_message_failfast()`: 이미 `self.current_text`가 버퍼에 누적되어 활발히 답변 중인 경우 8초 타이머 격발 방지.
    - `_error_message_failfast()`: 타이머 만료 시점에도 버퍼에 텍스트가 있거나 최근 5초 이내 턴 활동이 있었으면 턴을 강제 종료하지 않고 회귀.
  - `tests/test_conversation_sync.py`: `test_delta_after_error_message_cancels_failfast_and_rearms_silent_hang` 테스트 추가.
- **검증**: `python3 -m unittest tests.test_conversation_sync`, `python3 tests/smoke.py`, `chatbot-ctl.sh guard` 통과.
- **티켓**: #253 (claim -> done)

## 2026-09-27 — 사용자 데이터 경로 `~/.pe` + 릴리스 파이프라인 계획

- **배경**: Private Engine 배포 준비 — 엔진/개인 데이터 분리와 릴리스 로드맵을 계획 문서로 고정. 구현·마이그레이션 착수는 실장님 말 후.
- **경로 SSOT** ([user-data-separation.md](plans/user-data-separation.md) §0 갱신):
  - 배포 기본: **`~/.pe`** (`~/.privateengine` 아님)
  - env: `CHATBOT_DATA` → `PE_HOME` → `PRIVATEENGINE_HOME` → 레거시 `AGY_CHAT_DATA`
  - 개발: `CHATBOT_DATA=$CODE/data`
  - **ctl** `DATA="$CODE/data"` 하드코딩 제거 MUST
  - Windows: `%USERPROFILE%\.pe` (XDG 등은 이후)
- **신규** [release-pipeline.md](plans/release-pipeline.md) (`active`):
  - **Now**: repo private/PII, VERSION+CHANGELOG+tag, RELEASE.md, run-tests.sh, repair→smoke, secrets.env.example
  - **Next 1–2mo**: `~/.pe` 기본, migrate, templates bootstrap, `data/` gitignore, 최소 CI
  - **Pre-Steam**: thin launcher, installer, signing — Steam은 브랜드·도메인 이후
  - **NOT**: 공개 푸시·히스토리 scrub 단독, 두꺼운 데스크톱 셸, `~/.privateengine` 기본 고정 등
- **INDEX**: user-data-separation 행 갱신 + release-pipeline Active 행. **concept** 열린 축 1줄.
- **교차**: private-engine-brand, user-data-and-editing §1, character-memory-adapter.
- **실장님 경로 요약**: 배포 `~/.pe` · 개발 `$CODE/data` · ctl 하드코딩 금지 · Steam은 브랜드 후.

## 2026-09-27 — 캐릭터 스코프 관계 기억 어댑터 계획 문서화

- **배경**: 개인화 에이전트 하네스(걸프렌드-퍼스트 아님). 사적 관계는 opt-in 능력. Joi식 공감·연속성. 현행 `MEMORY.md`/`memory.md`/`private-memory.md`는 동반자 깊이에 부족.
- **추가**: `docs/plans/character-memory-adapter.md` (`active`) — provider/visual 옆 **per-character memory adapter** 층. 개념 슬롯(진행·약속·선호·금기·관계 온도·사적 히스토리). 구현 없음.
- **열린 질문**: 저장 vs `CHATBOT_DATA`, 암호화·user-data-separation 연동, `turn_context` 주입, vs lorebook, opt-in depth, private-mode 호감도 경계.
- **INDEX**: Active 행 추가. **concept** `열린 축` 1줄 링크.
- **교차**: `private-mode.md`, `user-data-separation.md`, delegation §12.

## 2026-09-27 — Private Engine 브랜드·도메인 검토 계획 문서화

- **배경**: 대화(2026-09-27) 공개 스캔 — Private Engine / PrivateEngine / 프라이빗엔진 채택 가능성, 도메인·레지스트리, 상표 리스크. 법률 자문 아님.
- **추가**: `docs/plans/private-engine-brand.md` (`active`) — 스캔 요약, privateengine.ai 기울기, PrivacyEngine.io·Wallpaper Engine 인접, pe.ai TAKEN, 도메인 홀드→클리어런스 권고.
- **INDEX**: Active 표에 행 추가.
- **concept**: `열린 축`에 브랜드·도메인 검토 링크 1줄.
- **면책**: 공개 스캔 기록만. KR/US/(EU) 변호사 전 스케일 금지 고지 문서에 포함.

## 2026-09-27 — docs/plans 아카이브 절차 + 에이전트 MUST

- **INDEX**: 상태 `active|done|superseded|abandoned`, 아카이브 절차, Active/Archived 표 분리.
- **이동**: 완료·대체 계획 12개를 `docs/plans/archive/2026/`로 (README 추가).
- **MUST 경로**: `data/workspace/AGENTS.md` § Plans, `PROJECT.md` 계획 칸 포인터; Grok Bot `sphere-hub-chatbot-protocol`과 동기.
- **규칙**: 새 계획 전 INDEX 확인·active 행 추가; 종료 주 아카이브; 아카이브 문서 확장/부활 금지.


## 2026-09-27 — Gemini 사적 OPTIONAL refusal-mitigation TEST LAYER (#249)

- **목표**: craft(텐션/반응/액체/선택지)와 **분리**된 Gemini/agy 사적 전용 **옵트인** 거부완화 A/B 테스트 레이어. 기본 OFF. 긴 disregard 탈옥 덤프 금지 — 짧은 친밀 RP 연속성 프레이밍(KO+EN).
- **A** `data/private_refusal_mitigation_gemini.json` — `default_enabled:false`, marker `GEMINI_REFUSAL_MITIGATION_TEST_v1`.
- **B** `private_engine.py` — `load_refusal_mitigation` / `refusal_mitigation_enabled` / `refusal_mitigation_text`; `turn_context`에만 조건부 append. `private_tension_*.json`·`RENDER_PROTOCOL*` 불변.
- **C** `session.py` — meta `refusal_mitigation` load/save (기본 false).
- **ON**: 세션 `meta.json`에 `"refusal_mitigation": true` **또는** env `CHATBOT_PRIVATE_REFUSAL_MITIGATION=1` 후 repair. **OFF**: 키 삭제/false · env unset (일반 craft).
- **문서**: `docs/providers/private-refusal-mitigation.md`
- **검증**: `python3 -m unittest tests.test_private_tension`
- **배포**: 호스트 py → `chatbot-ctl.sh repair` / ⚡소생. **새 사적 세션** 또는 meta 켠 기존 세션에서 A/B.
- **티켓**: #249

## 2026-09-27 (새벽) — SILENT_HANG 도구활동 재장전 · 오탐 수정 (#248, #247 follow-up)

- **배경**: SILENT_HANG_v1이 assistant **TEXT delta만** 재장전 → 멀티툴/장시간 도구 턴(수 분)은 텍스트가 없어 90초에 오탐 종료. 의도는 Gemini 무응답 스톨 감지이지, 바쁜 도구 작업을 죽이는 것이 아님.
- **변경** `session.py`: `_touch_turn_activity()` — assistant delta **및** tool start/result/progress(heartbeat)마다 90s 타이머 재장전. `error_message`는 계속 QUOTA_FAILFAST 전용(재장전 안 함). 진짜 침묵(텍스트·도구활동 둘 다 없음)만 발화. `SILENT_HANG_SEC=90` 유지. TURN_END_ORDER·QUOTA_FAILFAST 불변.
- **검증**: `SilentHangWatchdog` — tool call 재장전 · 장시간 progress heartbeat · error_message 비재장전 + 기존 4건.
- **배포**: 호스트 py → `chatbot-ctl.sh repair` / ⚡소생.
- **마커**: `SILENT_HANG_v1` (activity reset)
- **티켓**: #248

## 2026-09-27 (새벽) — 무응답 silent-hang 워치독 (SILENT_HANG_v1, #247)

- **배경**: busy인데 assistant delta도 `error_message`도 없으면 agy print-timeout(8분)까지 대기. orphan `agy` 잔존·체감 행 유발.
- **변경** `session.py`: `SILENT_HANG_SEC=90`(승인 구간 60–120초 중 기본, QUOTA_FAILFAST 8초보다 길고 print-timeout 480초보다 짧음). busy 시작 시 타이머 — assistant delta마다 재장전 — `error_message`는 QUOTA_FAILFAST에 양보 — result/error/stopped·stop()에서 취소. 발화 시 한글 무응답 공지 + finalize 후 자식 중지(`TURN_END_ORDER` 유지).
- **검증**: `tests.test_conversation_sync.SilentHangWatchdog`.
- **Ops**: DiskStation orphan `agy` pid 16420(PPID1·deleted exe·live_pids 외) TERM 후 소멸. chatbot/mcp 유지.
- **배포**: 호스트 py → `chatbot-ctl.sh repair` / ⚡소생.
- **마커**: `SILENT_HANG_v1`

## 2026-09-26 (밤) — 사적 선택지 ALL=action · 본문 action-echo 금지 (#246)

- **실장님 Clarification**: (1) 선택지 클릭은 **전부 ACTION** — 칩의 대사는 optional flavor로 액션에 굽힘(`/act` 와이어). 진짜 말은 사용자가 타이핑. (2) 캐릭터 본문은 사용자 행동 재진술 금지 — 반응(액체/신음/몸)만 dense.
- **A** `static/markdown.js` `classifyChoicePayload`/`pickChoice`: `"대사"`·콤보도 `kind:action` → `sendAction`. 균형 괄호 `stripOuterParens` (안쪽 `(행동)` 보존).
- **B** `static/app-sse.js` `actionTextOf` · `app.js` `/act` 파싱 · `server.py` action wire · `private_engine.strip_outer_parens`/`tension_step`: 콤보 와이어 `("대사" (행동))` 안전.
- **C** `RENDER_PROTOCOL` + Grok overlay + `private_tension_{grok,defaults,gemini}.json`(grok **v13**): ALL choices=action · ACTION-ECHO BAN.
- **D** 캐시 `markdown.js?v=19` · `app.js?v=161` · `app-messages.js?v=6` · `app-sse.js?v=2`.
- **검증**: `python3 -m unittest tests.test_private_tension tests.test_choice_chips`. py → repair. **새 사적 세션**+하드 리프레시.
- **티켓**: #246.


## 2026-09-26 (밤) — 사적 선택지 speech-optional · silent /act 기본 + POST type=action (#245)

- **진단(라이브)**: `markdown.js?v=17` 분류기는 정상 — `(행동)`→`/act`→wire `(…)`, `"대사"`→say, 콤보→say 유지. 그런데 최근 사적 세션(`20260926-233858` 등) 모델 제안이 **combo 30 / action 0**. 프로토콜 `Combined (preferred)` + 텐션 `권장 콤보`가 매 칩에 대사를 강제 → 클릭이 전부 say로만 나감. 또한 `server.py` `/message`가 클라이언트의 `type: "action"` / `action_text`를 무시하고 `sess.send`에 `event_type`을 안 넘김.
- **A** `RENDER_PROTOCOL` + `RENDER_PROTOCOL_GROK_OVERLAY`: **Default = action-only** `(행동)` (silent /act). **Speech is OPTIONAL** — 자연스러울 때만 대사/콤보, 강제 대사 금지. `Combined (preferred)` 제거.
- **B** `private_tension_{grok,defaults,gemini}.json` `choice_forms`: 동일 원칙. grok **v12**.
- **C** `server.py`: `body.type=="action"` → wire `(action_text)` + `sess.send(..., event_type="action")`.
- **D** `app-messages.js` `choiceItemToMarker`: action 재조립 시 `(행동)` 유지. `markdown.js?v=18` · `app-messages.js?v=5`.
- **검증**: `python3 -m unittest tests.test_private_tension tests.test_choice_chips`. py 변경 → repair. **새 사적 세션**에서 ✦ 행동 칩 클릭 시 지문(`/act` wire) 확인. 하드 리프레시(캐시 무시) 필요.
- **티켓**: #245.

## 2026-09-26 (밤) — 사적 Grok 선택지 USER 대사: 말≠행동재진술 · 상황 주소 (#244)

- **배경**: 행동/상황 선택지는 충분한 데 `"대사"`가 행동을 말로 반복(action-narration)하거나 캐릭터 신음이 따옴표에 섞임. 말은 상대를 향한 상황적 의도·놀림·명령·애원·돌봄이어야 함.
- **유지 #243**: LIQUID-FIRST·ZERO FILLER·장식 지문 금지·직설은 캐릭터 말투일 때만·`/act` 분류 고정.
- **원칙(사례 나열 없이)**: **Speech ≠ restating the act** · **Speech = situational address** (intent/tease/command/plea/care). 서술뿐이면 `(행동)`만.
- **A** `RENDER_PROTOCOL` Choices + `RENDER_PROTOCOL_GROK_OVERLAY`: 위 일반 원칙. 캐릭터 신음·목석 몸명령 금지 유지.
- **B** `private_tension_grok.json` v11 `choice_forms`·슬롯 가이드: 동일 원칙.
- **검증**: `python3 -m unittest tests.test_private_tension`. 호스트 py → repair. **새 사적 세션** 재시험.


## 2026-09-26 (밤) — 사적 Grok 장식 지문 금지·액체 주력·선택지 /act 고정 (#243)

- **배경**: 창가·청록눈·장식꼬리 반복이 산통을 깸. 선택지 클릭이 대사/say로 새는 버그 잔존. 강제 천박 지양.
- **작법** `RENDER_PROTOCOL_GROK_OVERLAY` + `private_tension_grok.json` v10: ZERO FILLER(매 음절 각성) · LIQUID-FIRST(침/애액/점성/정액) · 창가·청록눈 금지(행동 관련만) · 꼬리는 핫할 때만 · 직설은 캐릭터 말투에 맞을 때만 · #242 유지(USER 선택지·Gemini 신음·SFX↔행위·dense·grok-4.7 low).
- **선택지 UI** `static/markdown.js`: 스마트쿼트/전각괄호 정규화, pure `(행동)`→/act, `"대사"`는 say, combo는 말 유지. `pickChoice`가 이미 action인 칩을 재파싱으로 뒤집지 않음. 순수 행동은 따옴표로 감싸지 말 것(오버레이·choice_forms).
- **검증**: `python3 -m unittest tests.test_private_tension tests.test_choice_chips`. 호스트 py → repair. **새 사적 세션** 재시험.

## 2026-09-26 (밤) — 사적 선택지=코치 행동 + Grok 작법 밀도 (#242)
- **Gemini 채굴**: 사적 agy/gemini 세션 신음·의태 강세(하아앙/하읏/응으읏, 파르르·찌릿)를 오버레이에 증류. SFX는 행위 짝짓기(**찌걱=삽입만**, 쪽쪽=입). 손애무에 삽입 SFX 금지.

- **배경**: #241 이후 피드백 — 선택지 `"대사"`가 캐릭터 대사/신음처럼 쓰이고, 클릭 시 전부 `/act`로 들어가 사용자 말이 액션 지문에 삼켜짐. 상황 서사 미사여구·약한 의태어(움찔) 남발, 직설/천박 부족.
- **제품 규약**: 선택지 = **코치/USER 행동(+사용자 대사)**. 캐릭터 반응은 **다음 턴 어시스턴트 본문만**. 권장 형식 `라벨 -> "사용자 대사" (행동)`.
- **A** `private_engine.RENDER_PROTOCOL` Choices: USER 주체·캐릭터 대사 금지. `RENDER_PROTOCOL_GROK_OVERLAY`: dense not purple(미사여구 컷) · 젖은/천박 의성(찌걱찌걱·찔꺽·찐득) · 직설/천박 권장 · 한국어 only · grok-4.7+low 유지.
- **B** `private_tension_{defaults,gemini,grok}.json` choice_forms/slots (grok v8). 노노·코코 카드 Voice 동기화.
- **C** `static/markdown.js`: `classifyChoicePayload` — `(행동)`→silent `/act`, `"대사"`→say, `"대사" (행동)`→사용자 말+행동(비-/act). aria `내 다음 행동`. `markdown.js?v=16`.
- **검증**: `python3 -m unittest tests.test_private_tension tests.test_choice_chips`. 호스트 py → repair. **새 사적 세션**에서 재시험.
- **재시험**: 선택지 따옴표가 코치 대사인지 · 클릭 시 말풍선에 사용자 말이 사리는지 · 캐릭터 반응이 다음 턴에만 오는지 · 본문이 미사여구 없이 젖은 의성+직설인지.

## 2026-09-26 (밤) — 사적 Grok 작법 교정 (반응 우선·한국어 only, #241)

- **배경**: #240 이후 실장님 피드백 — 지문 늘린다고 야설 작가가 되지 않음. Gemini 사적 대비 상대 반응이 목석, 영어 누수, 기계적 절정. 길이 말고 작법 수정 요청.
- **진단(요약)**: 오늘 밤 Grok 사적(코코 등)에서 EN 메타 누수(`Wait, I need to write…`, `Need 3 choices`/`Stage 3`), 대사가 사용자 몸 지휘 명령형(「허리 잡아」「리듬 유지해」). Gemini 사적은 숨결·놀림·주저→항복 반응이 살아 있음. #240 오버레이가 장면 페인팅 길이만 키운 것이 원인 축.
- **A** `data/private_tension_grok.json` v5: REACTION-first·목석 대사 금지·한국어 only·방/빛/침대는 반응에 복무. Gemini 표보다 짧게 유지.
- **B** `RENDER_PROTOCOL_GROK_OVERLAY`(#241): 길이 완화 → 반응 우선 + 열 있는 한국어 대사 + EN/메타 금지로 교체. 공용 `RENDER_PROTOCOL`·타 계열 불변. 여전히 grok-4.7+low, 크로스모델 라우팅 없음.
- **C** 노노·코코 카드 `system_prompt` Voice를 반응 우선/한국어 only로. 코코 `brains.private`=grok-4.7 effort low 추가.
- **검증**: `python3 -m unittest tests.test_private_tension` 21 OK.
- **배포**: 호스트 py 변경 → repair/⚡소생. **반드시 새 사적 세션**에서 재시험(기존 세션 meta의 model·effort·프롬프트 캐시 유지).

## 2026-09-26 (밤) — 사적 Grok 보완 (텐션·속도·렌더 오버레이, #240)

- **배경**: 사적 모드 Grok 보완(야설 작가). FULL 스코프. build-fast는 비싸서 제외 → **grok-4.7 + reasoning-effort low**.
- **A** `data/private_tension_grok.json` v4: 장소·거리 연속, 다감각, 대사+지문 밀도, 기계적 절정 루프 방지. gemini 표보다 짧게 유지.
- **B** `session_registry.get_private`: brains.private 우선, Grok이면 model=grok-4.7·effort=low. `adapter_grok.build_args`: 빈 effort→low, build-fast→4.7 치환. CLI enum 확인: xhigh|high|medium|low.
- **C** `private_engine.RENDER_PROTOCOL_GROK_OVERLAY`: 사적+Grok 턴만 메신저 1–2줄 천장 완화(가족 스코프). stale 테스트 `detect_model_family("grok","grok-4")`→`grok`. 노노 카드 Voice 완화 + brains.private.
- **검증**: `python3 -m unittest tests.test_private_tension`. 호스트 py 변경 → ⚡소생(repair 우선).
- **배포**: 새 사적 세션에서 provider=grok / model=grok-4.7 / effort=low 확인. 기존 사적 세션은 메타에 박힌 model·effort 유지.

## 2026-09-24 (밤) — 선택지(choices) UI 독립 작업카드 컨테이너 분리 (OUT_OF_BAND_CHOICES_UI, 티켓 #146)

- **배경**: 실장님 피드백 — 선택지가 대화 말풍선 밑에 달리는 칩 형태가 아니라 작업카드(`work-card`/`ticket-bar`)처럼 입력창 상단의 독립 카드 컨테이너에 표시되도록 UI 개편 요청.
- **변경**:
  - `static/index.html`: `workBar`/`ticketBar`와 나란히 입력창 위쪽에 `#choiceBar` 컨테이너 추가.
  - `static/app.js`: 전역 `choiceBarEl` 요소 바인딩.
  - `static/chat-panes.css`: `.choice-bar`, `.choice-card`, `.choice-card-head`, `.choice-card-body` 스타일 정의 (반투명 백드롭, 테두리 글로우, 카드 헤더).
  - `static/markdown.js`: `renderChoiceChips()`를 개편하여 `choiceBarEl`이 존재할 때 독립 `.choice-card`로 렌더링하고, 없으면 기존 마크다운 영역으로 안전 폴백. `syncChoiceChips()`에서 최신 응답 여부에 따라 독립 카드/칩 가시성을 정확히 동기화.
  - `tests/test_choices_channel.py`: 마크다운 선택지 렌더러가 `#choiceBar` 컨테이너에 카드로 정상 렌더링되는지 검증하는 단위 테스트 추가.
- **검증**: `tests.test_choice_chips`, `tests.test_choices_channel`, `tests.test_page_scripts` 전체 통과.
- **배포**: 정적 UI 변경(Tier 0/1)이므로 새로고침(F5)으로 즉시 반영.

## 2026-09-24 (저녁) — 오후 정리와 위임 절차 보강 A·C·D (STABILIZE_v1, DELEGATION_HARDENING_v1, 티켓 #143, #142)

- **배경**: 오후에 여러 에이전트(Hermes, Claude Code 세션 둘, 챗봇 claude·agy)가 같은 저장소를 동시에 고쳤고, #140(선택지 밖 채널 1단계)이 리뷰 시간 초과·불합격으로 두 번 실패. 챗봇이 드러난 구멍을 #142로 모음. 사용자: "난리가 났어… 알아서 해줘".
- **정리 (#143)**: #130이 커밋을 빠뜨린 `app-messages.js`(액션 말풍선 `✦ …`을 기록 `(…)`로 맞춤)를 살리고 테스트 가짜 DOM에 선택자 목록 지원·사례 추가. 커밋 안 된 티켓 기록 #130–#143, #130의 DEVLOG, 기본 캐릭터 두뇌 변경(claude/opus)을 커밋. `MEMORY.md`는 개인정보라 제외.
- **보강 (#142 A·C·D)**:
  - A. 지시문 2,000자 자르기 없앰. claude·codex는 프롬프트를 표준 입력으로(`stdin_prompt`) — 128KB 인자 상한이 없어 리뷰 diff 한도 200KB, 인자로 받는 agy·grok은 36KB 유지. 리뷰 프롬프트는 두뇌마다 그 한도로 만든다.
  - C. 응답 자체가 없던 실패(한도·시간 초과·CLI 없음)는 `unavailable`로 반납, 티켓이 시도를 돌려준다(티켓당 3번까지). `ticket-quick fail --outcome unavailable`.
  - D. PD 절차: 작업 하나 = 관심사 하나(대략 파일 몇 개·300줄), 경로는 실제 파일·새 파일은 `creates`, 테스트 포함, 무관한 수정 금지.
- **B (NEED_PATH_v1, #144)**: 작업자가 범위 밖 파일이 필요하면 `NEED_PATH: 경로 -- 이유`로 멈춘다 → 러너가 작업을 보존하고 `paused`로 반납(시도 반환, 횟수 제한 없음 — 재개는 실장님만). 작업 카드 "경로 요청"에 파일·이유와 [경로 허용]·[폐기]. 허용하면 경로 검사(Tier 3·없는 폴더 거절) 후 그 작업에 더해 보존된 브랜치에서 다시 실행.
- **#140 1a (OUT_OF_BAND_CHOICES_v1)**: 선택지 표식을 서버(`finalize_turn`, 모든 프로바이더 공통)가 답에서 떼어 `choices` 필드로 기록·전송. 기록·CLI·에이전트 맥락에 표식이 남지 않고, 화면은 그 값으로 버튼을 그림. #140의 나머지(`choices` 도구·`action` 이벤트·티켓 바 직접 실행)는 계획서 1단계에 남김. agy 리뷰어는 도구를 끌 수 없으니 PD 두뇌 목록에서 claude를 앞에.

## 2026-09-24 — 사적 모드 액션 선택지 · 직접 행동 입력 · 표정 연동 · 속마음 연출 (PRIVATE_INTERACTION_v1, 티켓 #130)

- **배경**: 실장님 제안 — `character-chat` 서비스의 검증된 상호작용 메커니즘을 참고하여 See1 챗봇 규격에 맞게 흡수 및 리네이밍. 지문/대사 분리, 표정 태그 연동, 속마음 토글 박스, 액션 선택지 및 직접 행동 전달 방식 구현.
- **변경**:
  - 표정 태그 연동 (`static/markdown.js`, `static/chat-log.css`): 응답 헤더의 `[expression: neutral|joy|shy|serious|sorrow|tired]`를 파싱해 메시지 상단에 감정 뱃지(`.exp-badge`)로 렌더링하고 마크다운 본문에서는 깔끔하게 제거.
  - 속마음 독백 연출 (`static/markdown.js`, `static/chat-log.css`): SimCore `state` JSON 블록의 `thought` 및 `<thought>` 태그를 본문에서 분리, 하단에 '속마음 보기' 토글 버튼(`.thought-toggle`)과 독백 상자(`.thought-box`)로 연출.
  - 액션 선택지 (`static/markdown.js`, `static/chat-log.css`): `<!--choices: 라벨 -> 행동 | ...-->` 화살표 구문 파싱 지원, 선택지 버튼에 `✦ ` 및 `.choice-action` 스타일 적용, 클릭 시 사용자 말풍선 없이 즉시 지문 액션 발송.
  - 직접 행동 입력 (`static/app.js`, `static/slash.js`, `static/app-messages.js`): `/act <행동>` 슬래시 명령어 등록 및 `sendAction()` 연동. 사용자 입력창에서 행동 전달 시 대화 말풍선 대신 지문(`.msg.action`)으로 표시하고 모델에는 `(<행동>)` 지문으로 전달.
- **검증**: `tests/test_choice_chips.py` 8개 테스트 전체 통과(액션 선택지, 표정, 속마음, 화살표 구문), `tests/test_page_scripts.py` 4개 통과(1,000줄 미만 유지), `tests/smoke.py` 및 관련 테스트 전체 통과.
- **배포**: 정적 UI 자산이므로 브라우저 새로고침(Ctrl+Shift+R / F5)으로 즉시 적용.

## 2026-09-24 (오후) — 세션 조회 캐시 · 파일 단위 잠금 · 테스트 기준선 · app.js 분리 (SESSION_INDEX_v1 … APP_SPLIT_v1, 티켓 #113–#117)

- **배경**: 사용자 "전체적으로 반응이 나빠진 것 같아"; 이번 대화에서 드러난 불편(잠금 하나에 다른 작업이 막힘, 막힌 [진행]이 조용히 실패, 남의 티켓에 버튼) 1–3번 개선 승인; "리팩토링 한 번 해야 하지 않을까?" → 추천안(안전망 → app.js → session.py) 승인.
- **변경**:
  - 반응성: 페이지가 2.5초마다 묻는 최신 세션 조회가 `meta.json` ~320개(2.8MB)를 매번 전부 읽었다(REG.lock 안, p50 174ms). 파일별 요약 캐시(수정 시각·크기)로 실서버 7ms, 목록 4ms (#113; 챗봇 위임 1차는 20분 제한으로 실패 — 증상 없는 티켓, 없는 파일 경로).
  - 잠금 (#115): 파일 단위 잠금 `leases.json`(겹칠 때만 대기, 파일을 안 적으면 전체), 막힌 이유 `blocked_by` 표시, [실행] 대기열(파일이 풀리면 서버가 시작, [대기 취소]), 담당자 `owner`(`ticket-quick start`로 연 티켓은 그 에이전트만; [담당 해제]), 상위 폴더부터 적은 경로를 저장소 기준으로 맞춤. `~/bin/ticket-quick`에 `claim`.
  - 테스트 기준선 (#116): 오래 실패하던 4개를 현재 동작에 맞춤. 덤: 중지 후 agy의 "interrupted"가 에러 공지로 남던 버그.
  - app.js 분리 (#117): 6,197줄 → 931줄 + 13개 부분, 로드 순서 가드 테스트. `PROJECT.md`의 "더 쪼개지 말 것" 지침을 새 지도로 교체.
  - session.py 분리 (#118): 세션 목록·조회를 `session_registry.py`(297줄)로, `session.py` 2,601 → 2,335줄. 이름은 `session`에서 그대로 다시 내보냄.
  - 위임 명확화 (#119): 계획의 `paths`는 실제 파일만(없으면 가장 가까운 실제 파일을 알려 주며 거절), 새 파일은 `creates`. 작업 카드에 라운드 시계(12:30/20:00)와 바뀐 파일 수, 시간 초과는 "timed out after Ns". 위임 중 채팅 배지는 "루루 작업 중 · mm:ss".
  - 에이전트 중심 구조 (#120–#122): DEVLOG 401→29KB(지난 날짜 `docs/devlog/`), `docs/plans/INDEX.md`, README는 입구만(지도는 PROJECT.md 하나), 사적 세션 지침 7.6→4.2KB(헌장은 앞머리+Scope, 전환 규칙은 호스트 안내 한 곳, 카드 규칙 영어), `adapters.py` 프로바이더별 분리(#122), `providers/` 폴더 시범과 보호 누락 수정(#123), `chat.css` 여섯 조각(#124), 문서·파일 크기·보호 가드 테스트.
- **검증**: 모든 테스트 모듈 개별 실행 통과(이전 실패 4개 포함). 한 프로세스 `discover`는 전역 누수로 ~40개 실패 — 규칙은 모듈별 실행, 격리는 별도 작업.
- **배포**: repair 3회(유휴 3연속 확인 후). app.js 분리는 정적 파일만(새로고침).
- **남은 것**: 테스트 격리(한 번 test_delegation·test_mcp_server가 개별 실행에서도 실패했다가 재실행 3회는 통과 — 원인 미상),.

## 2026-09-24 — 캐릭터 선택기 · 이미지 형식 · 역할 팩 · 개선 히스토리 (CHARACTER_PICKER_v1 … AVATAR_BASE_PATH_v1, 티켓 #102–#112)

- **배경**: 사용자 결정 — 왼쪽 위는 캐릭터 선택, 프로바이더는 이름을 눌러 고름(캐릭터마다 마지막 두뇌 기억). 이미지 에이전트가 따를 형식이 필요하고, 전신·표정도 같은 형식으로 만들 수 있게 한다(데스크톱 모드는 먼 구상). "모든 캐릭터는 동등하다 — PD는 PD 지침과 PD 스킬셋으로 정해진다."
- **변경**:
  - 캐릭터 선택기: 아바타 = 캐릭터 트레이, 프로바이더 이름 = 두뇌 트레이. 캐릭터를 고르면 그 캐릭터의 같은 모드 최신 세션(없으면 카드의 첫 두뇌로 새 세션) (#102).
  - 이미지 형식 `character-art` 스킬 + `tools/check_character_art.py`: 아바타 512·가발, 투명 스프라이트 `bust` 1024²·`full` 1024×2048(SillyTavern 표정 이름표, `neutral` 먼저), `visual.md` 외형 락 (#103).
  - 역할 팩: 카드에는 역할이 없다. `roles/<role>/role.md`(매 턴, `tools`·`skills`) + `procedure.md`(필요할 때), `team.json`(`default`, `members`). 도구 권한 `delegate`·`house-memory`는 역할 팩이 준다(PD 팩만 가짐). `memory/MEMORY.md`는 집 공용 기억, 캐릭터마다 자기 `memory.md`. 팀 탭은 캐릭터를 똑같이 보여 주고 `[역할]`로 편성 (#104–#105). 루루 카드·그림은 챗봇이 직접 (#106–#107).
  - 개선 탭: "오늘 처리" 대신 처리된 관찰 전체를 10개씩 페이지로 (#108).
  - 그림 주소에 `BASE_PATH`와 파일 시각 버전, 선택기는 열 때마다 목록 새로 읽음, 프로바이더 트레이·채팅 배경도 열린 캐릭터 기준. 배경은 형식에 추가: `stage.webp`·`stage/<provider>.webp` 1024² (#109).
  - 챗봇 직접: 냥피디 → 냥냥 이름 변경(#110), 옛 `role` 스킬 폴더 삭제(#111–#112).
- **사고**: 세션 캐릭터 이전(#105)이 `meta.json` 312개를 다시 쓰면서 수정 시각이 모두 같아져 세션 목록 순서가 뒤섞임(사용자 "세션이 꼬여서…"). `updated_at`으로 311개 복구, 이전 코드는 수정 시각을 보존하게 고침.
- **검증**: 새 테스트 test_character_picker(`BASE_PATH` 가드 포함)·test_character_art·test_team_roles·test_observation_history 통과, 전체 실패 목록은 작업 전과 같음. 실서버에서 선택기·가발·배경·역할 편성 확인.
- **배포**: repair는 모두 유휴 3연속 확인 후. 헌장·`protected_paths.json`이 바뀌어 `evolution.py manifest-update`는 사용자 몫.
- **남은 것**: 카드 가져오기·내보내기, §11 5단계(PD의 영입 제안), 냥냥 이미지를 `data/persona/`에서 캐릭터 폴더로. 작성자 잠금이 하나라 사람이 티켓을 쥐면 챗봇 위임이 막힘.
