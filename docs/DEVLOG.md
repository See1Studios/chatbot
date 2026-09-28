# chatbot 개발로그

## 2026-09-28 — 개발 규칙을 공용 헌장에서 dev 역할 팩으로 (pew/L, #294)

- **배경**: 공용 헌장(`data/workspace/AGENTS.md`)은 모든 캐릭터에 매 턴 주입된다. 그런데 티켓·클레임·계획·⚡소생 같은 엔진 개발 절차가 거기 있어서, 그림 담당(artist)도, 배포판의 개인 캐릭터도 쓸 일 없는 개발 규칙을 매번 읽고 있었다.
- **변경**: 새 역할 팩 `roles/dev/` — `role.md`(매 턴, 4줄: 엔진 작업이 네 몫이다, 하기 전에 procedure를 읽어라, 목표에 안 맞으면 이유와 대안) + `procedure.md`(필요할 때: 티켓·클레임·계획·테스트·`--no-verify` 금지, 루트 `AGENTS.md` 포인터). 헌장에서 Self-modification·Plans 절과 PROJECT/CONCEPT 포인터를 뺐다. 안전 규칙 두 줄(라이브 턴에 ctl stop/restart 금지, "엔진·헌장·git은 dev 역할만")은 모두에게 필요해서 헌장 Scope에 남겼다. `team.json`에서 PD·staff 캐릭터에 `dev`를 더했다.
- **효과**: 매 턴 주입량 — PD·staff 캐릭터 −578 B, artist −961 B. 정적 층 4,189/4,800 B.
- **테스트**: `tests/test_dev_role.py` — 헌장과 다른 역할의 `role.md`에 개발 표지가 없음, dev 팩이 옮겨간 내용을 가짐, dev 없는 캐릭터의 묶음에 개발 규칙이 안 들어감.
- **분리**: `role.md` → `ROLE.md` 이름 통일은 코드(로더·팀 탭 UI)와 ⚡가 필요해 `pew/R`로 뺐다.
- **비용**: 데이터·문서만 — ⚡ 불필요. 다음 턴부터 새 묶음이 들어간다.

## 2026-09-28 — ticket-quick을 저장소로 (pew/K, #293)

- **배경**: `~/bin/ticket-quick`은 저장소 밖에 있어 경로가 `/volume1/...`로 고정되고, 테스트도 이력도 없었다(P10). 오늘 클레임 토큰을 출력 필터로 두 번 잃어 운영자가 터미널에서 `drop-lease`를 해야 했다.
- **변경**: `tools/ticket_quick.py` — 같은 명령줄(start·claim·done·fail·renew·await-merge·merge-go), 데이터 폴더는 `host_config.DATA`. 토큰은 사용자별 `~/.local/state/chatbot-claims/<설치태그>-<id>.token`(0600, 폴더 0700)에도 남고, `--token`을 빼면 그 파일을 읽는다. done/fail/await-merge가 지운다. 데이터 폴더 밖에 두는 이유: 생성된 에이전트는 저장소·데이터만 보므로 남의 토큰을 못 줍는다. opencode 실행 파일도 행위자로 인식. `~/bin/ticket-quick`은 이 파일로 넘기는 포인터만 남김. `tools/worktree_runner.py`도 저장소 사본을 부른다.
- **테스트**: `tests/test_ticket_quick.py` 6개 — `CHATBOT_DATA` 폴더에 쓰는지, 토큰 파일 권한, 토큰 없이 done, 파일 없을 때 안내.
- **기준선**: 전체 스위트는 커밋 전에 따로 돌림(아래 커밋 참조). 호스트 모듈 변경 없음 — ⚡ 불필요.

## 2026-09-28 — 정적 자산 재검사 + 압축 (STATIC_DELIVERY_v1, #287)

- **배경**: 운영자 요청 — 프런트 로딩/렌더링이 느린 느낌. 추측으로 손대지 않고 층별로 잰다. 데스크톱 브라우저가 이 세션에 연결돼 있지 않아 트레이스를 못 써, 전송 계층을 curl/HTTP로 잰다.
- **측정 (변경 전)**: 풀 로드 **32개 요청 / 685 KB**. `Cache-Control: no-cache`에 ETag·Last-Modified가 없어서 **새로고침마다 전량 재다운로드**, `?v=` 캐시버스팅이 제 역할을 못 함. 압축은 클라이언트가 gzip을 제시해도 `Content-Encoding`을 안 줌. `HTTP/1.0`(keep-alive 없음). mermaid 3.3MB는 지연 로드라 풀 로드에 없었음.
- **변경**: 새 모듈 `static_delivery.py`(순수 함수) — ETag(mtime+size, 콘텐츠 해싱 안 함: 3MB 벤더 JS를 요청마다 읽고 해싱할 이유가 없다), If-None-Match(RFC 9110), gzip 협상. `server.py::_send()`가 선택적으로 `etag`/`encoding`을 받고, 정적 텍스트 경로만 넘긴다 → **API 라우트는 완전히 그대로**(테스트로 증명). `Cache-Control: no-cache`는 **의도적으로 유지** — "정적 고치고 새로고침"이 이 저장소의 습관이라 긴 max-age는 편집을 숨긴다.
- **결과 (동일 자산 32개, 동일 헤더, 격리 인스턴스 2개)**: 첫 방문 **685 KB → 216 KB (−68%)**, 재검사 **685 KB → 0 KB**(32/32 304). gzip level 6 CPU는 685KB 전체에 **47ms**(격리 측정) — 버밀 가치가 압도적. 벽시계 시간은 이 박스에서 신뢰 불가(같은 설정에서 386~1043ms 산포 — 다른 에이전트가 테스트를 돌리는 중). **일타일 변환을 단정하지 않는다.**
- **남긴 판단**: HTTP/1.1 keep-alive(연결 31회 → 1회)는 아직 안 함. 응답마다 정확한 Content-Length가 필요해 SSE·전체 라우트가 걸리고, 절약预期치가 바이트 절감보다 작다. 별건.
- **여유**: `server.py` 1499/1500 — **여유 1줄**. 다음 엔드포인트 하나면 가드가 깨진다. `monolith-split.md` `split/B`가 이 파일의 유일한 해법이다.
- **절차 실패 (자기계정)**: 라이브 서비스가 03:27에 ⚡소생으로 재시작되어 **편집 중인 코드를 그대로 로드했다**(NameError 난 `_send`를 거칠 뻔한 창이 있었다). charter는 "파이썬 모듈 변경은 ⚡을 먼저 알리고, 재시작은 운영자가 동의할 때"를 요구하는데, 알리지 않고 편집했다. 이후 측정은 전부 격리 인스턴스로 옮겼다.
- **기준선**: 가드 17/17 · 신규 테스트 9/9 · 관련 24/24. ⚡ 반영됨(03:27 재시작).

## 2026-09-28 — 세션 탭 캐릭터별 탭 (SESSION_CHAR_TABS_v1, #285)

- **배경**: 운영자 요청 — 세션 탭 안에서 캐릭터별로 세션을 탐색. **백엔드 변경 0건**: `/api/sessions`가 이미 모든 행에 `character`·`character_name`을 실어 보내고(`session_registry.py`), 행마다 이름도 이미 찍히 있었다. UI가 데이터 모델을 따라잡은 것.
- **변경**: `static/index.html`(목록 위 `sessionCharTabs`), `static/chat-panes.css`(칩 아이iom — `chat-features.css`의 팀-role 칩과 같은 문법), `static/app-sessions-tab.js`(그룹·필터·스트립). 라벨 해석은 `sessionCharacterLabel` **하나**로 묶어 탭과 행이 서로 다른 이름을 쓰지 못하게 했다. 카탈로그 순서 → 카탈로그에 없는 캐릭터는 이름순, 개수는 이미 숨겨진 빈 세션을 뺀 값. 선택은 `localStorage`에 남고, 그 캐릭터의 세션이 다 없어지면 `전체`로 되돌아온다. 캐릭터가 하나뿐이면 스트립을 내린다(선택지가 하나뿐인 선택지).
- **테스트**: `tests/test_session_character_filter.py` 9개 — 번들에서 실제 함수를 잘라 스텁 DOM으로. 변이 2종(필터 무효화, 카탈로그 조회 제거) 모두 실패 확인.
- **테스트가 잡은 버그**: 캐릭터 1명인데도 `전체` 탭 때문에 스트립이 올라오던 것. `groups.length < 3`으로 고침.
- **비용**: 정적 변경뿐 — ⚡소생 불필요, 브라우저 새로고침이면 된다.
- **참고**: `static/*` 세 파일이 l10n 래칫 한계(17/17·110/110·9/9)에 딱 걸려 있어 새 한국어 줄은 전부 `l10n-ok`. 이 문자열들은 `localization.md l10n/C`의 카탈로그 이관 대상.
- **기준선**: 가드 16/16, 신규 테스트 9/9.

## 2026-09-28 — 구조 부채 실측: monolith-split Phase 6 (문서만, #283)

- **배경**: 운영자 요청 — 리팩터링 지점 탐색. 규칙(`test_file_sizes`·`test_page_scripts`·래칫)이 이미 통과하는 트리에 남는 부채만 잰다.
- **측정**: 단일 프로세스 전체 실행 **93 실패 / 1,190 테스트**(모듈 104개) — monolith-split이 "~40개"로 적어둔 값이 낡았다. 대문자 모듈 전역 42개(`host_config` fan-in 25), import 순환 3쌍 + 자기참조 1, 60줄 이상 함수 34개. `session.py`는 상한 2,298에 **여유 0줄**, `server.py`는 1,478/1,500 **여유 +22줄**이고 그 719줄이 if분기 104개짜리 평면 라우터다. `identity.py` 238줄에 안쪽 `import characters` 11회(17개 함수).
- **추가**: [monolith-split.md](plans/monolith-split.md) **Phase 6** — 실측표·재는 방법·항목 `split/A`–`split/F`(테스트 격리·라우터·`session.py` 경계·순환 해체·생성물 커플링·죽은 `static/role.js`)·순서·경고·손대지 말 것. INDEX 행 갱신. **새 문서를 만들지 않은 이유**: 같은 concerns를 두 문서에 흩으면 INDEX가 관리가 아니라 목록이 된다.
- **경고**: edition 경계 작업이 `host_config.py`·`mcp_server.py`를 손대는 중이라 `split/A`는 그 뒤로 미룬다. 프런트 전역은 측측 결과 방어할 것이어서 Phase 6에 넣지 않았다(이름 충돌 3개뿐).
- **기준선**: 가드 15/15. 구현 없음.

## 2026-09-28 — 시장·포지셔닝 방향 재검토 (문서만, #280)

- **배경**: 운영자 요청 — 상품성과 시장 진입점의 적절성에 대한 의견. 에이전트가 문서 리뷰로 판단을 냈다(시장 조사·사용자 인터뷰·가격 데이터 없음. 전제로 문서에 명시).
- **판정**: 시장 진입 판단 자체는 옳다(BYOK·1회 구매·무료 체험·프로바이더 이중화·파워 유저 10명 = 유지). 문제는 ① "개인화 하네스"라는 포지셔닝 문구가 벤더가 가장 먼저 내는 층을 가리킴 ② 해자 목록이 경제성이 반대인 두 제품(코스메틱=창작마당 가능 / 관계 깊이=공유 불가)을 하나로 묶었고 수익선이 하나뿐 ③ 리텐션 근거가 될 콘텐츠 cadence 계획 부재 ④ 플랫폼 배관이 수요 증빙보다 한 사이클 앞섬 ⑤ "Private Engine"이 스토어에서 프라이버시 도구로 읽힘.
- **추가**: [market-direction-review.md](plans/market-direction-review.md) (`active` · 방향 **정렬**) — 진단 6건, 결정 R1–R8(모두 대기·운영자), 작업 항목 `rev/A`–`rev/F`. INDEX 행 + 방향 적합성 줄.
- **순서 제안**: 포지셔닝 교정 → 60초 데모 결정 계획 → cadence 계획 신설. 그 클립이 나올 때까지 플랫폼 계획 2개를 대기 재랭크.
- **기준선**: 가드 15/15. 구현 없음.

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

