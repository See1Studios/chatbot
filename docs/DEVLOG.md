# chatbot 개발로그

2026-09-28 기록은 하루 40KB 예산에 도달해 [devlog/2026-09-28.md](devlog/2026-09-28.md)로 회전했습니다.
2026-09-29 기록도 같은 이유로 [devlog/2026-09-29.md](devlog/2026-09-29.md)로 회전했습니다.
2026-09-30 기록도 [devlog/2026-09-30.md](devlog/2026-09-30.md)로 회전했습니다.
2026-10-01 기록은 하루 예산을 넘어 [devlog/2026-10-01.md](devlog/2026-10-01.md)로 회전했습니다.

## 2026-10-02 — [grh/A] 단체방 헤더 카드 스택 아바타 연출 및 최근 발화자 동기화 (#561, 위임 agy)

- **커밋**: `5d64dd5` fix(rooms): verify updateBrandAvatar signature and direct roomClose avatar restoration, `5d2db56` feat(rooms): avatar card stack and sync for group room header (grh/A)
- **바뀐 파일**: `static/app-rooms.js`, `static/rooms.css`, `tests/test_rooms_page.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-02 — [cgs/B] 캐릭터 생성 프롬프트 및 수치 상세도 포팅 모듈 (card_prompt.py) (#547, 위임 agy)

- **커밋**: `0b8fee4` fix(card_prompt): clean up image prompt fallback, nonce handling, and empty specs, `e20abf5` feat(card_prompt): align detail specs with ST-CardGen and expand prompt rules, `e58be20` fix(card_prompt): filter detail lines, keyword-only overrides, tighten tests, `2c39ada` feat(card_prompt): add character generation prompt builders and detail specs
- **바뀐 파일**: `card_prompt.py`, `tests/test_card_prompt.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-02 — 재시작으로 화면 코드가 바뀌면 열린 페이지가 스스로 새로고침 (#563)

- **실측**: 오늘 두 번, 서버 재시작 뒤에도 열린 페이지가 옛 스크립트로 돌아 새 기능이 안 보임(동료 턴 404 뒤 재요청 없음, 창 열기 반응 요청 없음 — 서버는 정상, 직접 부르면 반응).
- **변경**: `/healthz`에 화면 코드 지문(`static_delivery.fingerprint`: js/css/html 이름·크기·수정 시각). 페이지는 처음 본 지문을 기억하고, 재시작을 감지했을 때(`checkRevived`, 리부트 버튼 흐름) 지문이 다르면 새로고침. 입력 중이던 글은 `sessionStorage`에 두었다가 돌려놓음. 지문이 같으면 지금처럼 재연결만.
- **함께**: `dialog` 도구 설명에 "몸으로 하는 일은 action, say는 읽거나 듣는 말뿐" — 노노가 서류 놓기를 말로 보낸 실사용 사례.

## 2026-10-02 — 1:1 창에 동료의 턴 + 보고 있을 때 바로 반응 (inbox/E·G, #558–#560)

- **운영자 제안**: 노노가 리리에게 한 말·행동을 리리가 옮겨 말하는 대신 리리 창에 노노의 턴으로(얼굴 말풍선, 행동 지문) → 추천대로(D8·D11·D12 재결정). "DM으로 커피" 어색함은 메시지/자리 방문 구분으로 먼저 고침(#558).
- **변경**: `dialog_log.feed`, `/api/office`(창에 그릴 dm 글), `/api/office/notify`(도구가 보낸 뒤 호스트에 알림 → 양쪽 창에 SSE `office`, 반응 깨우기), `static/app-office.js`(노노 말풍선은 단체방의 얼굴 말풍선, 행동은 가운데 지문, 내가 보낸 건 "→ 이름" 한 줄, 동기화와 안 겹치게 `syncRole=office`). 사적 방·회의실 화면에는 안 뜸.
- **바로 반응**: 자동 반응 종류에 `msg.new`(팀 탭 "동료가 메시지를 보내거나 자리에 들렀을 때"). 1:1만, 그 창을 보고 있을 때만(SSE 구독), 반응하면 읽음. 다른 대화가 돌면 E2대로 미뤄져 보통 20초 안.
- **한계**: 노노에게 보내라고 시키는 동안 운영자는 노노 창을 보고 있으므로 리리는 그때 바로 반응하지 않는다 — 리리 창을 열면 노노의 턴이 보이고 다음 턴의 [Office] 안내로 반응. ⚡ 재시작 필요, 팀 탭에서 켜야 바로 반응.
- **이어서 (#562)**: 창을 열 때 아직 안 들은 동료의 턴이 있으면 그 자리에서 한 번 반응(`event_react.react_on_open`, `/api/office/opened`). 동료 글 불러오기를 SSE가 열릴 때마다로 옮겨 호스트 재시작 뒤에도 다시 그림(실사용: 재시작 전 새 화면이 404를 받은 뒤 다시 안 불러옴).

## 2026-10-02 — 통합 메시지: 밑단은 메신저, 겉은 역할극 (inbox/F, #554–#555)

- **실사용 확인**: 재시작 뒤 노노→리리 전달이 끝까지 됨(호출 세션 판정 0 실패). 받는 쪽이 처음엔 `dialog_id`로 4번 실패 → 인자 이름·오류 문구·안내 줄의 id로 고침(#554), 다음 시도는 한 번에 열고 읽음 처리.
- **운영자 방향**: "정확히 메신저는 아니고 역할극 엔진" → 밑단(기록·순번·읽은 위치 = 누가 무엇을 아는가)은 그대로, 겉은 UX8. 캐릭터끼리는 라운지에서의 **화면 밖 대면 대화**(D9, 현행 방향), 행동 지문도 주고받음(D10). 사용자에게는 숫자 대신 기척·지문·캐릭터의 말(D6·D8 재결정).
- **변경**: 글에 `kind`(`say`·`action`), 읽기·인계 단락에서 "X does: …", 도구 설명과 턴 안내 문구를 대면 대화로("[Off-screen] …").
- **같은 날 재결정 (#556)**: 채팅방은 공간 — 1:1은 사무실 속 캐릭터 자리(동료 DM·멘션에 대화 중에도 반응, §8.3 그대로), 단체방은 회의실, 사적은 방해받지 않는 곳. D9의 "라운지 대면 대화"를 동료 DM·멘션으로 바꾸고 문구를 "[Office] …", "(DM)", "(meeting room)"으로.
- **남은 것**: `inbox/E`(기척·지문 화면, `ux/S5`·`ux/D1` 뒤), `inbox/G`(먼저 꺼내기, D11 보류). ⚡ 재시작해야 반영.

## 2026-10-02 — 통합 메시지: 텔레그램식 대화·읽은 위치·dialog 도구 (inbox/0–D, #549–#553)

- **운영자 결정**: 계획을 텔레그램 구조로 다시 씀 — 본문은 대화 저장소에, 이벤트 대장에는 가리키는 줄만(D7), 1:1 `@`는 멘션일 뿐(D4 재결정), 턴에는 대화 목록 한 줄(D5 재결정). 1:1은 세션 기록이 저장소라 옮기지 않음.
- **inbox/0 (#549)**: 도구 호출의 세션을 연결한 프로세스의 족보로 찾음(`session.caller_session`, `/api/sessions/caller`, `mcp_caller.py`). CLI들의 도구 설정이 작업공간 공용 파일이라 세션마다 값을 실을 수 없어서. agy 언어 서버는 agy 프로세스 안(agy.md A50). HTTP 두뇌는 헤더, 호스트 자신의 연결에서만 믿음. 모르는 호출은 `mcp.caller_unknown` — claude·codex·grok은 이 로그로 실사용 확인 필요(시험 실행은 권한 검사에서 막힘).
- **inbox/A (#550)**: `dialog_log.py` — 대화마다 파일 하나, 번호는 대화 안에서. 방 로그 형식 그대로, 캐릭터끼리 `dm:<a>:<b>`, `reply_to`. 방은 등록으로 붙어 순환 없음.
- **inbox/B (#551)**: `msg.new`(본문 없음), 읽은 위치 둘(캐릭터 읽음·세션 본 곳). 새 세션이 밀린 글을 건너뛰지 않음. 말한 방 멤버는 읽음, 기존 방은 마지막 발언 위치에서 시작. 테스트는 `CHATBOT_DIALOGS_DIR`로 격리.
- **inbox/C (#552)**: 업무 턴 앞 "[Unread dialogs]" 한 줄(새 것이 있을 때만), 교대 뒤 최근 대화 단락 + 본 곳 되돌림. 방 자리·사적 세션은 없음.
- **inbox/D (#553)**: `dialog` 도구(list·read·send). 보내는 이는 호출 세션, 모르면·사적이면 거절. 쪽지 도구 없음.
- **남은 것**: `inbox/E`(화면 안 읽음 푸시)는 D6(뱃지 자리) 결정 뒤. D8(캐릭터끼리 1:1 열람) 보류. 캐릭터가 받은 글에 바로 답하게 하려면 `evt/D` 자동 반응에 `msg.new`를 켤지 결정 필요. ⚡ 재시작해야 반영(`server.py`·`mcp_server.py`·`session*.py`).

## 2026-10-02 — 위임 관문은 마지막 커밋에서 읽는다 (#548, #547의 원인)

- **일**: agy의 위임 #547이 "이 작업 없이도 관문 실패"로 두 번 돌려보내짐. 원인은 내 split/D 작업 — main 작업 폴더의 `run-tests.sh` 빠른 가드 목록에 새 테스트를 넣고 그 파일을 약 40분 커밋하지 않았음. 러너는 관문 목록과 테스트 파일 유무를 **main 작업 폴더**에서 읽고, 테스트는 **마지막 커밋으로 만든 작업 사본**에서 돌려서 "없음"으로 실패.
- **운영자**: 두 에이전트에게 동시에 일을 맡기는 게 문제라고 했지만, 병렬 작업은 이 구조가 지원해야 하는 방식 — 장치의 구멍으로 보고 고침.
- **변경**: `tools/worktree_runner.py::guard_gate`·`related_gate`가 `run-tests.sh`와 `tests/`를 HEAD에서 읽음(`head_files` — `git cat-file --batch` 한 번, `head_tests`). main 작업 폴더에 무엇이 반쯤 있어도 위임 관문은 작업 사본과 같은 기준. 지금 저장소에서 옛/새 관문 목록 같음(가드 1, 관련 테스트 5경우).
- **테스트**: `test_worktree_runner` 두 개가 픽스처를 커밋한 뒤 확인, 커밋 안 한 가드 등록·테스트 파일은 무시되는지 추가.
- **남은 것**: 러너 79,807B — 상한 80,000B까지 193B. 다음 러너 변경 전에 관문 만들기(`guard_gate`·`related_gate`·`head_*`)를 따로 빼야 함. 나도 앞으로 코드·테스트·관문 변경은 작업 사본에서만(메모리).

## 2026-10-02 — `characters`↔`identity` 순환 풀기 + import 순환 래칫 (split/D, #546)

- **실측**: `identity`(누구로 보일지, 윗층)가 `characters`(카드, 아랫층)를 함수 안에서 11번 import. 거꾸로 `characters`는 `identity.parse_frontmatter` 하나 때문에 `identity`를 불렀고, 그래서 양쪽 다 import를 함수 안에 숨겨야 했음.
- **변경**: `parse_frontmatter`와 울타리 정규식 `_FRONT`를 `characters.py`로(아랫층이 갖는다). `characters`에는 같은 이름 `_FRONT` 사본(캡처 그룹만 없음, 지우기에만 씀)이 이미 있어 처음엔 옮긴 것을 덮어썼음 — 하나로 합침(지우기 결과 같음). `identity`는 맨 위에서 `import characters` 한 번, `identity.parse_frontmatter`는 그대로 쓸 수 있음. 계획의 "얇은 공유 계층"은 필요 없었음.
- **가드**: `tests/test_import_cycles.py`(빠른 가드, 규칙 표 등록) — 서로 import하는 모듈 쌍은 이유를 적은 7쌍만(호스트 플러그인, 테스트가 바꾸는 값을 부를 때 읽는 것들, split/C 믹스인 둘 …). 새 쌍은 실패, 없어진 쌍은 목록에서 지우라고 실패.
- **⚡ 필요**: `characters.py`, `identity.py`. 이로써 monolith-split Phase 6(A–G) 끝.

## 2026-10-02 — 보호 파일 검사를 git 기준으로 (split/E, #545)

- **운영자 결정**: 손으로 다시 찍는 지문 대신 git 마지막 커밋과 비교.
- **왜**: `protected_manifest.json`은 9/24에 한 번 찍은 지문(133개)이었고, 그 뒤 정상 커밋으로 수정 87·새 파일 146개가 쌓여 `doctor` 경고가 늘 켜져 있었음 — 진짜 무단 변경이 와도 구별이 안 됨. 승인된 변경은 이미 커밋(티켓·훅)으로 들어오므로, 무단 변경의 흔적은 "보호 파일인데 커밋 안 된 수정·삭제·새 파일".
- **변경**: `evolution.py::protected_changes`(git status에서 보호 대상만, `except`·`volatile` 제외) + `protected_report`, 명령 `manifest-check`/`manifest-update` → `protected-check` 하나(`chatbot-ctl.sh` 호출부). `protected_manifest.json` 삭제, `protected_paths.json`에서 그 항목 세 곳 삭제. 로그 이벤트 이름 `manifest.drift`는 로그 요약이 세고 있어 그대로(`docs/LOGGING.md` 뜻만 고침). 서비스 폴더가 저장소 맨 위가 아니면(바깥 저장소의 커밋은 기준이 아님) 또는 git이 없으면 정보만.
- **테스트**: `test_lifecycle` 지문 테스트 → git 기준 8개(깨끗함, 무시 대상, 수정·삭제·새 파일·스테이지만 한 파일, 커밋하면 OK, git 아님, 깨진 등록부, 긴 목록, 이 저장소, CLI). `test_core_standalone`은 git 없는 환경에서 정보만 내는지.
- **⚡ 필요**: `evolution.py`(서버가 import).

## 2026-10-02 — 테스트 격리: 한 프로세스 1,809개 통과 (split/A, #544)

- **실측**: 한 프로세스 실패 116개 중 16개는 빈 임시 데이터 탓(모듈별로 돌려도 실패), 102개가 진짜 격리 문제. 앞 모듈을 반씩 나눠 같이 돌리는 이분 탐색으로 범인을 찾음.
- **원인 하나가 100개**: `tests/test_account_login.py`가 import 순간 `HOME`·`AGY_CHAT_ROOT`·`AGY_CHAT_DATA`·CLI 경로를 `os.environ`에 넣고 안 되돌림. 한 프로세스에서는 모든 테스트 파일을 먼저 import하고 이 파일이 알파벳으로 맨 앞이라, `host_config`가 가짜 홈·가짜 코드 위치로 굳음 → git이 사용자를 못 찾아 커밋 실패, `delegation`이 러너 파일을 엉뚱한 곳에서 찾음. 고침: 환경은 건드리지 않고 로그인 코드가 읽는 값(인증 파일 경로, CLI 경로, 대기 시간)만 이 모듈이 도는 동안 바꿨다 되돌림.
- **나머지 둘**: 개발판이 필요한 세 모듈(`test_delegation`·`test_mcp_server`·`test_mcp_parity_tools`)은 `mcp_server.EDITION`을, `test_mcp_server`는 호스트 플러그인(`mcp_server.HOST_PLUGIN`)을 자기 테스트가 도는 동안만 고정 — 다른 모듈이 `mcp_server`를 먼저 import하면 환경 변수가 늦음.
- **계획의 추정과 달랐던 것**: 대문자 전역 42개·되돌리지 않는 캐시 2개는 범인이 아니었음. 중앙 리셋 지점도 필요 없었음.
- **확인**: `run-tests.sh`와 같은 조건(실제 데이터 폴더)으로 한 프로세스 1,809개 통과. 실행 전후 세션 수(671)·추적 데이터 파일 같음, 그사이 바뀐 두 파일(`account_state.json`·`live_pids.json`)은 테스트 없이도 서버가 1분 안에 다시 씀을 확인.
- **도구**: `./run-tests.sh --one-process`(약 5분). 기본은 그대로 모듈별.

## 2026-10-02 — 구글 계정 1초 즉시 스왑 도구 및 프로필 저장 기능 구현 (#542, 위임 claude)

- **커밋**: `d9ea56d` feat(accounts): saved agy login profiles with an atomic switch CLI; stray reaper matches whole helper args
- **바뀐 파일**: `providers/accounts.py`, `tests/test_accounts.py`, `tools/switch_account.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-02 — 위임 측정 기록: 대상 파일 크기와 끝난 시각 (D1 ③, #543)

- **왜**: 크기 상한(1,500줄·1,000줄, 지금은 80,000B·43,000B)은 측정값이 아니라 판단값이었다(계획 6.7 D1). 다음에 숫자를 고칠 때 "이 크기의 파일을 맡긴 위임이 얼마나 걸려 어떻게 끝났나"를 보고 정하려고.
- **변경**: 이미 위임마다 남는 실행 상태 파일(`~/.worktrees/chatbot/runs/ticket-N.json`, 지금 252개)에 `target_bytes`(시작 때 대상 파일별 바이트)와 `ended_<결과>`(done·awaiting_merge·gate_failed …, 병합 대기 뒤 완료가 일한 시간을 덮어쓰지 않게 결과별)를 더함. `started`·`provider`·`round`는 원래 있었음. 새 저장소 없음 — 라이브 로그(`logs/events.jsonl`)는 러너 테스트가 실제 로그를 건드리게 돼서 쓰지 않음.
- **테스트**: `test_worktree_runner` 병합 경로에서 두 값 확인.
- **재시작 불필요**(러너는 위임마다 새 프로세스).

## 2026-10-02 — `worktree_runner.py` 80KB 아래: 검토 부분은 `review_checklist.py`로, `cmd_run` 앞부분은 단계로 (split/G, #541)

- **변경**: 검토자에게 주는 프롬프트, diff를 한도에 맞추기, 판정 읽기(`review_prompt`·`doc_review_prompt`·`fit_diff`·`parse_review`·`is_doc_task`·`deleted_lines`·`DOC_CHECKLIST`·`DIFF_LIMIT`)를 `tools/review_checklist.py`로 — 실행은 안 하는 순수 함수라 러너가 다시 가져와 씀(`wr.parse_review` 등 기존 호출 그대로). `cmd_run`에서 인자 검사(`arg_error`), 티켓 얻기(`claim_ticket`), 새 작업 사본(`new_worktree`)을 뺌 — `created` 표시는 전처럼 사본이 생긴 뒤 호출 쪽에서. 82,775B → 77,791B, `cmd_run` 319 → 282줄. 크기 천장에 걸린 파이썬 파일이 이제 없음.
- **동작 불변 확인**: 전체 테스트(러너 생명주기를 가짜 에이전트로 도는 `test_worktree_runner` 포함), 잘못된 인자 7가지에 옛/새 러너의 문구·종료 코드가 같음.
- **재시작 불필요**: 러너는 위임마다 새 프로세스. 서버가 `delegation.runner()`로 들고 있는 옛 모듈은 바뀌지 않은 상태 함수만 씀.
- **다음**: D1 ③ 위임 측정 기록(티켓마다 대상 파일 크기·걸린 시간·결과) — 이제 러너에 자리가 있음.

