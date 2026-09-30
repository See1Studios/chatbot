# chatbot 개발로그

2026-09-28 기록은 하루 40KB 예산에 도달해 [devlog/2026-09-28.md](devlog/2026-09-28.md)로 회전했습니다.

## 2026-09-30 — 대화방 목록: 다른 캐릭터는 항상 업무방으로 (ux/S1, #481)

- **운영자**: "노노와 사적대화에서 리리를 누르면 갑자기 리리가 사적대화가 아니었는데 사적 대화가 되기도 하고 … 이건 문제야."
- **원인**: 목록이 트레이의 `selectCharacter`를 그대로 불렀고, 그 호출은 "지금 화면의 모드"로 상대 캐릭터의 세션을 연다 — 사적 중이면 서버가 그 캐릭터의 **새 사적 세션**을 만든다(`REG.get_private(fresh=True)`).
- **변경**: `selectCharacter(c, mode)` — 목록은 `'work'`를 넘긴다. 열린 줄의 "사적 대화 중"은 `body.private-session`이 바뀌는 즉시 다시 그린다. 서버 변경 없음.
- **테스트**: `test_shell_page` 고르기(사적 상태에서도 work).

## 2026-09-30 — 대화방 목록: 업무 대화만, 사적 표시는 열린 방만 (ux/S1, #480)

- **운영자 확인**: ① 허브 칩이 방해 ② 나눈 말이 있는데 "없다"고 나옴 ③ 사적 대화가 아닌데 "사적 대화 중".
- **원인(세션 메타데이터로 확인, 본문 안 읽음)**: ② `/api/sessions`는 최근 40개뿐인데 기본 캐릭터가 거의 다 차지해 한 캐릭터는 0건. ③ "가장 최근 세션이 사적이면 사적 중"이라는 내 가정이 틀림 — 사적 방에 다녀오면 업무로 돌아와도 최근 세션은 사적 세션.
- **변경**: `session_registry.py::talks`(캐릭터별 가장 최근 업무 대화, 말이 없는 세션·사적·방 세션 제외) → `/api/sessions` 응답의 `talks`. `room_chat.py::rooms`에 `last`(누가·언제·80자). 목록은 업무 대화만 보이고 "사적 대화 중"은 열린 방이 사적일 때만. 허브 칩은 `html.shell2` 아래에서 숨김.
- **⚡ 필요**: 서버 두 파일. 재시작 전에는 화면이 최근 40개 안에서 업무 세션을 찾는 대체 경로로 동작(③은 바로 고쳐짐, ②는 재시작 뒤).
- **테스트**: `test_session_index` talks 1건, `test_room_chat` last, `test_shell_page` 17건.

## 2026-09-30 — 메신저 뼈대 1단계: 스위치 뒤의 대화방 목록과 두 칸 (ux/S1, #479)

- **변경**: `static/app-shell.js`·`static/shell.css`(새 파일), `static/index.html`(스위치·목록 자리·뒤로 버튼), `static/app.js`(`shellInit()` 한 줄). `?shell=2`를 붙인 브라우저에서만 켜짐 — 없으면 화면은 그대로.
- **동작**: 왼쪽 목록 = 캐릭터 한 줄 + 단체방 한 줄(최근 대화 순, 마지막 말 한 줄·시각, 사적 대화 중이면 미리보기 없음, 이름 검색). 줄을 누르면 트레이와 같은 호출(`selectCharacter`·`roomEnter`·`roomLeave`). 940px 아래는 한 칸: 목록이 대화 위를 덮고, 머리의 뒤로 버튼과 시스템 뒤로가 목록으로.
- **서버 변경 없음**: 목록은 있는 API 셋으로 조립. 그래서 단체방은 마지막 말 대신 멤버를 보이고, 최근 40개 세션 밖의 캐릭터는 미리보기가 빈다.
- **확인 못 한 것**: 실제 브라우저 화면. 이 호스트의 헤드리스 브라우저는 라이브러리가 없어 뜨지 않음 — 운영자 확인 필요(넓은 창, 폰, 키보드).
- **테스트**: `tests/test_shell_page.py` 14건(줄 조립·사적 가림·미리보기 정리·시각·고르기·좁은 화면·스위치 꺼짐·옛 화면 불변).

## 2026-09-30 — 메신저 뼈대 결정 (ux/P, #478)

- **계기(운영자)**: "UX를 모던 메신저 스타일로 전면 개편하고 싶어. 하나씩 질문하면서 진행해보자."
- **결정**: `docs/plans/ux-shell-roadmap.md` 4.2.3, UX7–UX16 — 뼈대는 메신저·개성은 D10, 원칙 "메신저는 틀, 방 안은 일이 벌어지는 자리", 캐릭터 한 줄 목록, 두 칸 + 프로필 카드, 탭 7개를 프로필 카드와 ⚙ 설정으로, 입력 바 `＋ · 입력칸 · 보내기`(행동은 스페이스), 반응 = 행위·행위는 가운데 지문, 스킨 + 캐릭터 두 겹(키 컬러의 모델 표시 역할 종료), 머리에 장소 + 기척.
- **방법**: 눌러 보는 시안 세 판(저장소 밖, 가짜 데이터). 코드 변경 없음.
- **다음**: `ux/S1`(두 칸 + 목록)부터. 열린 점 — 업무방 답변에서 지문으로 볼 범위(`ux/S5`), 색감(`ux/S8`).

## 2026-09-30 — 단체방 첫 사용 뒤 다듬기 (#476)

- **관찰(실사용, 방 "테스트" 노노·리리)**: 17:12:59·17:13:56 두 번 모두 노노→리리→노노로 한도(답 3·연쇄 2)를 꽉 채움 — 캐릭터가 매번 서로를 @로 부름. 17:13:44에 보낸 말은 방이 답하는 중이라 409로 거절됐는데 화면은 알려 주지 않았음.
- **변경**: 방 안내문 — 대부분 사용자에게 말하고 **꼭 그 멤버의 답이 필요할 때만** 멘션. 화면 — 답하는 동안 [보내기] 꺼짐(폴링마다 갱신), Enter도 막음.
- **테스트**: `test_room_chat` 안내문, `test_rooms_page` 보내기 막기.

## 2026-09-30 — 단체방 화면 (evt/E-2, #475)

- **변경**: `static/app-rooms.js`·`rooms.css` — 캐릭터 트레이에 [단체방](캐릭터가 둘 이상일 때). 모달 왼쪽 방 목록·[+ 새 방](이름·멤버 체크·발언 방식: 자연스럽게/순서대로/부른 사람만), 오른쪽 대화(멤버 아바타·이름, 내 말은 오른쪽), 입력창에서 `@` 치면 멤버 자동완성(버튼), Enter 보내기(한글 조합 중 제외), 방이 답하는 동안 "답하는 중…"과 1.5초 폴링(평소 5초). 방 멤버의 숨은 세션은 세션 탭 목록에서 뺌(`Registry.list`).
- **남은 것**: 단체 놀이방(E7, 방 사적 기억), 이번 턴 두뇌 호출 수 표시(E5).
- **테스트**: `tests/test_rooms_page.py`(멘션 판별·완성, 메시지 모양, 연결), `test_room_chat` 세션 목록 1건.

## 2026-09-30 — 재시작 이벤트가 로그 거울에서 빠지던 부팅 순서 (#474)

- **증상**: 반영 뒤 실제 로그를 보니 `react.defer`(시간당 한도 — 노노가 16:14·16:30·16:36에 이미 3번 반응해서, 16:46·16:48 재시작엔 미룸: 설계대로)·`events.deliver`는 남는데 `events.publish`가 0건.
- **원인**: `main()`이 `_record_boot()`(재시작 이벤트 발행)를 `obslog.start_process()`(로그 설정)보다 먼저 불러, 부팅 때 발행은 로그가 설정되기 전이었음.
- **변경**: 순서 교정, 소스 순서 테스트(`test_events`).

## 2026-09-30 — 단체방 1단계: 업무방 서버 (evt/E-1, #473) · 자동 반응 한 목소리 규칙

- **단체방**: `room_chat.py` — 방(이름·모드·멤버·발언 방식)과 대화 기록(`data/rooms/`, gitignore). 멤버는 각자 **숨은 세션(mode `room`)**에서 자기 두뇌·카드·역할·업무 기억으로 말함(사적 기억 없음; 제공자 중립 — oneshot은 agy에만 있어 쓰지 않음). 차례가 오면 지난번 이후 방 대화만 받음. 발언자 선택은 SillyTavern 이름 그대로 `natural`(멘션 먼저 → talkativeness 0.5 확률, 아무도 없으면 한 명) · `list` · `manual`. 한도(E4): 사용자 한마디당 답 3번, 그중 캐릭터끼리 멘션 연쇄 2번. `/api/rooms`(목록·만들기·대화·말하기), 방이 답하는 중엔 409. `session.py`·`session_registry.py`가 `room` 모드를 유지(재시작 뒤에도 `work`로 바뀌어 1:1 대화를 가로채지 않게; `session.py` 줄 수 그대로). 놀이방(E7)과 화면은 다음.
- **자동 반응 수정**: 모두에게 가는 이벤트(재시작)는 **기본 캐릭터만** 반응(재시작 때 네 캐릭터가 한꺼번에 반응함), 반응 턴 실패는 `react.failed`로 로그.
- **사고와 정리(내 잘못)**: 단체방 테스트·디버그를 실행기 없이 돌려 ① 실제 세션 폴더에 빈 노노 세션 4개(업무 2·방 2)가 생겨 잠시 노노의 최신 업무 세션이 됨 — 16:14 재시작 자동 반응이 그 빈 세션으로 들어가 화면에 안 보였음, ② 실제 우편함에 테스트 이벤트 2건. 세션은 치우고(스크래치로 이동) 메모리에서도 지우려 16:29 재시작, 이벤트 2건 삭제. 원인: 가져다 쓴 테스트 기반이 세션 폴더를 `make()`에서만 바꿈 → 새 테스트는 직접 임시 폴더로 바꾸고, 실행기로만 돌림.
- **같이 고친 버그**: 세션 요약(`session_registry._meta_summary`)도 모드를 사적/업무로 접고 있어 방 세션이 1:1 업무 대화로 잡힐 수 있었음(전체 실행에서 드러남) — `room` 유지.
- **로그(운영자: "이벤트 시스템 로그도 촘촘히?", "한 몸 아닌가?")**: 우편함과 엔진 로그는 한 기록의 두 모습 — `events.publish`가 쓰는 순간 `events.publish` 로그, 배달 `events.deliver`, 정리 `events.prune`, 반응 판단 `react.defer`/`react.skip`(중복 묶음), 단체방 `room.create`/`say`/`turn`/`chain`/`done`/`failed`. 메타데이터만, 사적 이벤트는 대상도 뺌. `docs/LOGGING.md`에 표.
- **테스트**: `tests/test_room_chat.py` 8건, `test_event_react` 한 목소리 1건, `test_events` 로그 1건(내용·사적 대상 없음). 실행 전후 실제 세션 수·우편함 줄 수 같음 확인.

## 2026-09-30 — 캐릭터가 먼저 말 걸기: 자동 반응 (evt/D, #472)

- **변경**: `event_react.py` — 운영자가 켠 이벤트(`work.phase`의 끝남·실패·승인 대기, `host.restart`)가 오면 관계있는 캐릭터가 **자기 업무 세션에서 먼저 한두 줄**(`session._send_direct(notice=True)` — 사용자 말풍선·사용자 기록 아님, 도구·작업 금지 지시). **기본 꺼짐**(E2), 캐릭터당 시간당 3회, 방해 금지 00–08시(미뤘다가 아침에 한 번에), 어느 대화든 진행 중이면 미룸, 처음 볼 때 옛 이벤트엔 반응 안 함, 먼저 말한 이벤트는 다음 턴 안내에서 뺌. 20초마다 도는 반응 스레드(서버). 설정은 작업공간 `events.json`(사용자 데이터), 팀 탭 맨 아래 "자동 반응" 카드에서 켜고 끔(`PUT /api/experts/auto-react`). 사적 세션은 업무 채널만 보므로 사적 대화 중엔 업무 이벤트로 끼어들지 않음.
- **테스트**: `tests/test_event_react.py` 6건(기본 꺼짐·옛 이벤트 무시·끝남에만·한도·방해 금지·대화 중·설정 정리·화면 값).

## 2026-09-30 — 이벤트 발행 지점: 사적 대화 입장/퇴장·계정 전환 (evt/C, #471)

- **변경**: `threshold.enter`/`leave`(실제로 들어가고 나갈 때만, 같은 전환 반복은 걸러짐)에서 `session.private.start`/`.end` — 그 캐릭터의 **사적 채널에만, 시각만**(E1, private-security T3). `accounts.observe`가 계정 변경을 처음 볼 때 `account.switch` — 제공자 이름만, 계정(메일)은 싣지 않음. 위임 단계(`work.phase`)는 #470. 배달 문구는 아직 없음(사적 이벤트는 단체 놀이방·화면 기척(`evt/F`)에서 씀).
- **테스트**: `test_events` 2건.

## 2026-09-30 — 이벤트 우편국 1단계: 작업 안내·재시작 안내를 우편함 위로 (evt/B, #470)

- **계획**: [character-events-and-rooms.md](plans/character-events-and-rooms.md)(E1–E8 추천대로 결정).
- **변경**: `events.py` — `publish(type, to, channel, subject, **payload)`(수취인은 발행자가 관계로 정한 캐릭터 id 또는 전체, 대화 본문 없음), 세션별 커서(`data/events/cursors.json`, 재시작해도 유지), `pending(sid, character, channel)`, 보관 30일·10MB·사적 7일(E3), 스레드·프로세스 잠금. 발행: 위임 단계 변화는 서버의 10초 감시 루프에서 `delegation.publish_work_changes`(현재 태스크 작업자 + 기본 캐릭터에게, 처음 본 끝난 작업은 안 알림), 재시작은 부팅 때 전체에게. 배달: `server._turn_notices`가 우편함을 읽음 — 세션 첫 읽기는 재시작 안내 + 진행 중 작업 요약(이전과 같은 문구), 그 뒤엔 그 캐릭터에게 온 것만. 사적 세션엔 업무 안내 없음, 사적 이벤트는 참여자의 사적 채널에만(E1). `.gitignore`에 `data/events/`, 테스트는 실제 우편함을 안 건드림(`run-tests.sh`가 `CHATBOT_EVENTS_DIR`를 임시 폴더로).
- **테스트**: `tests/test_events.py` 6건, `test_restart_notice`·`test_work_note` 그대로 통과.

## 2026-09-30 — 멈춘 위임 작업자를 10분 만에 끊고 다음 두뇌로 (WORKER_STALL_v1, #468)

- **증상**: #462가 두 번 연속 20분 시간 초과. agy 로그 — 첫 시도는 커밋 뒤 `500 Internal`·`503 No capacity available for model gemini-3.8-flash-high` 재시도, 두 번째는 모델 호출 1번 뒤 **18분 무응답**(모델 목록 조회만). 러너는 20분을 다 기다렸음.
- **근거**: 위임 작업자 agy 로그 83개 — 모델 호출 사이 최대 공백 303초(1건), 나머지 ≤131초, 중앙값 31초.
- **변경**: `delegation_watch.run` — 작업자·리뷰어를 감시하며 돌리고, 제공자가 활동 신호를 주는데 `CHATBOT_WORKER_STALL_SEC`(기본 600초) 동안 없으면 멈춰 "stalled: … (quota, capacity or a hung stream)"로 반환 → 러너는 기존 규칙대로 '두뇌 응답 없음' → 다음 두뇌, 없으면 시도 반환·작업 보관. 신호는 어댑터 훅 `AgentAdapter.last_activity`(기본 None = 신호 없음 → 전체 시간 제한만), agy는 자기 로그의 마지막 `streamGenerateContent` 시각(`accounts.agy_log_for`로 pid→로그). 파일 변경 여부는 신호로 안 씀(읽기·생각만 하는 정상 작업을 끊지 않게). 러너는 `run_as_login`에서 감시 실행으로(줄 상한 안).
- **테스트**: `tests/test_delegation_watch.py` 8건.

## 2026-09-30 — 팀 탭: 두뇌가 하나면 '예비 두뇌 없음' 빈 칸 (#467)

- **계기(운영자)**: 예비 두뇌는 "지정할 수 있는 슬롯만 만들어 두자". 편집기엔 이미 [+ 두뇌 추가](최대 6, 두뇌별 제한 초)가 있고 러너도 다음 두뇌로 넘어가지만, 평소 화면엔 한 줄뿐이라 슬롯이 있는 줄 모름.
- **변경**: `app-team.js` `teamSpareSlot` — 두뇌가 정확히 1개면 흐린 점선 칸 "2 · 예비 두뇌 없음 — [두뇌]에서 추가하면 1번이 응답하지 않을 때 넘어갑니다".
- **테스트**: `tests/test_team_brain_slot.py`(node).

## 2026-09-30 — 위임한 쪽(기본 캐릭터)도 작업 상태를 안다 (WORK_NOTE_v1 확장, #466)

- **증상**: 노노가 시간 초과로 멈춘 #462를 "리리가 끝내고 `--stop-before-merge`로 병합 승인 대기 중, 가드 테스트 18종 통과"라고 설명하고 "바로 병합할까?"를 물음 — 모두 사실 아님(Tier 0이라 대기 없음, 게이트·확인 단계 도달 못 함). `delegate status`를 안 보고 짐작.
- **변경**: `work_note` — 기본 캐릭터는 모든 위임 작업의 단계 변화를 `[Work you delegated] … Before telling the user about delegated work, check delegate status; never guess a run's state.`로. 작업자는 그대로 `[Your delegated work]`. 단계 문구에 `unavailable`(응답 없음: 작업 보관·시도 반환)·`base_broken` 추가.
- **테스트**: `test_work_note` 6건.

## 2026-09-30 — 위임받은 캐릭터가 자기 작업을 안다 (WORK_NOTE_v1, #465)

- **증상(운영자)**: 리리에게 위임한 뒤 리리에게 "일은 잘되가냐?"라고 물으면 처음엔 자기가 작업 중인 걸 모르고, 다시 말해 줘야 앎.
- **원인**: 지침 묶음은 CLI 두뇌에 첫 턴(과 고정 부분이 바뀔 때)만 들어감 — 묶음 끝의 동적 부분도 대화 도중엔 안 감. 위임 상태를 캐릭터에게 알리는 통로가 없었음.
- **변경**: `delegation.work_note(character, told)` — 그 캐릭터가 지금 맡은 작업(현재 태스크의 역할을 그 캐릭터가 연기)의 번호·제목·단계를 한 줄로. 세션 첫 턴엔 진행 중인 것 전부, 그다음엔 **단계가 바뀔 때만**(작업 중 → 테스트 → 노노 확인 → 승인 대기/반영/실패), 끝난 건 한 번 알리고 뺌. 기본 캐릭터(위임하는 쪽, `delegate status`가 있음)와 사적 세션엔 없음. 통로는 기존 턴 훅(`session.boot_notice`)을 서버의 `_turn_notices`로(재시작 안내 + 작업 안내) — `session.py`는 한 줄도 안 늘림.
- **같이 고침**: `characters.by_role` — 역할을 가진 사람이 여럿이면 **기본 캐릭터가 아닌 사람**(위임 받는 쪽)을 먼저. 노노도 `dev`를 가져서 dev 작업자가 id 순서로 우연히 리리였음.
- **확인**: 실데이터 — 리리에게 `#462 "하단 위젯의 높이·정렬·간격 및 모바일 일관성 개선": you are working on it`, 나머지는 없음.
- **테스트**: `tests/test_work_note.py` 5건, `test_team_roles` by_role 1건.

## 2026-09-30 — 첫 MEMORY.md가 반쯤 쓰인 채 읽히던 경쟁 (MEMORY_CREATE_v1, #464)

- **증상**: 전체 테스트에서 `test_memory_store.test_concurrent_writers_lose_nothing`가 가끔 `MemoryRefused('--section 은  중 하나.')`로 실패(단독 실행은 통과).
- **원인**: `_ensure`가 쓰기 잠금 **밖에서** 템플릿을 "비우고 쓰기"로 만듦 → 동시에 첫 기억을 쓰면 잠금 안의 다른 스레드가 빈 파일을 읽고 섹션 없음으로 거절. 실제로는 기억 파일이 처음 생길 때만.
- **변경**: 임시 파일에 다 쓴 뒤 `os.link`로 "없을 때만" 제자리에(하드링크가 없는 파일 시스템은 `os.replace`). 읽는 쪽은 없거나 완성된 파일만 봄.
- **테스트**: 동시 읽기 8스레드×20회로 재현(옛 코드 6회 중 2회 실패), 수정 후 8회 연속 통과.

## 2026-09-30 — 역할 이름 정리: lead 총괄 · plan 기획 · dev 개발 · art 아트 (#463)

- **결정(운영자, 채팅 → 이 세션)**: 팀 체계 [총괄-기획-개발-아트], 식별자 `lead`·`plan`·`dev`·`art`. `staff`는 `plan`으로 바꾸고 리리가 개발+기획.
- **변경(사용자 데이터, Tier 3 — 운영자 승인)**: `roles/pd`→`lead`, `roles/staff`→`plan`(본문을 기획 역할로 새로 씀), `roles/artist`→`art`(배포 템플릿도 같이, 매니페스트 갱신), 제목 한국어(총괄·기획·개발·아트). 팩 본문에서 다른 역할을 부르던 "the PD"·"staff"·"the user"는 매크로 `{{default}}`·`{{user}}`로(#461). 필요할 때 파일로 읽는 `PROCEDURE.md`는 치환되지 않으니 역할 id를 그대로. `team.json`: 노노 [lead, dev](직책 총괄), 리리 [dev, plan](개발), 코코 [art]. `PROJECT.md` 경로. 옛 팩은 `git mv`로 옮겨 이력에 남음. PD 채팅이 만들다 둔 빈 폴더 `roles/lead|plan|art` 정리.
- **확인**: 실제 데이터로 네 캐릭터 지침 묶음 렌더 — 풀리지 않은 매크로 0, 역할 글·직책 정상, 역할 없는 Yae Miko는 "…are 노노's".
- **테스트**: `test_team_roles`(실데이터: 기본 캐릭터가 delegate 팩을 가짐, 이름 비의존), `test_data_bootstrap`(배포 역할 `art`).

## 2026-09-30 — 카드·역할 팩 매크로 {{user}} {{char}} {{title}} {{default}} {{role:id}} (CARD_MACROS_v1, #461)

- **계기**: 운영자 제안("{user}{role}{title} 등의 플레이스홀더"). 확인해 보니 이미 버그 — 리리·코코·Yae Miko 카드에 SillyTavern식 `{{user}}`·`{{char}}`가 있는데 엔진이 치환하지 않아 **모델이 글자 그대로 받음**(Yae Miko는 description에 있어 매 턴). 또 역할 팩·엔진 문장이 "PD"·"staff" 같은 역할 이름을 박아 둬서 이름 바꾸기가 파일 여러 개 수정이 됨.
- **결정(운영자)**: `{{ }}` 이중 중괄호(SillyTavern·카드 표준 호환) + 팀 확장. 한 겹 `{user}`는 가져온 카드와 안 맞고 JSON·코드 예시와 겹쳐서 제외.
- **변경**: `characters.render_macros(text, cid, ws)` — `{{user}}`(그 캐릭터의 호칭, 없으면 기본 캐릭터의 것) `{{char}}`(이름) `{{title}}`(직책) `{{default}}`(기본 캐릭터 이름) `{{role:<id>}}`(그 역할 팩 제목), 대소문자·공백 허용, 못 푸는 건 그대로. 적용은 렌더링 세 곳뿐: 업무 묶음의 규칙 부분(헌장·로어·카드·역할 팩), 사적 묶음의 고정 부분, 위임 페르소나(`identity.persona_body`). 기억·스킬은 제외, 파일은 매크로 유지. 엔진 문장 중립화: 역할 없는 안내 "…are {{default}}'s", 위임 도구 설명·거절 문구에서 "PD"·"e.g. staff" 제거, 러너 관계 문장 "producer (PD)/staff member" → "delegated this work".
- **테스트**: `tests/test_card_macros.py` 6건, `test_worktree_runner` 문구.

## 2026-09-30 — 엔진 역할명 중립화: 기본 캐릭터 한 자리만 (engine/A, #460 — #456 인계)

- **경위**: 채팅에서 운영자 결정("이건 어디까지나 사용자 데이터고 엔진 코드는 이런 걸 몰라야해") → PD가 #456 위임. 시간 초과 → 경로 요청 → 리뷰 FAIL 2라운드(시도 1 소진) → 또 경로 요청으로 멈춤. 원인: "역할 이름 없이 누가 기본인가"가 정해지지 않아 작업자가 `"pd"`를 `"staff"`로 바꾸는 식으로 추측했고 리뷰가 매번 반려. 러너(`worktree_runner.py`)의 `"pd"`·`"staff"`는 티켓 범위 밖이라 손도 못 댐.
- **결정(아키텍처)**: 엔진이 아는 건 **기본 캐릭터**(`team.json` `default`) 한 자리. 없으면 가장 오래된 카드(옛 "pd 카드만 기본" 규칙 삭제).
- **변경**: `characters.expert_roles`(기본 캐릭터가 아닌 캐릭터들의 역할) → `delegation.experts()`. `workspace_status` 매 턴 카드 = 기본 캐릭터. `identity.seed_workspace_files` 새 설치 기본 캐릭터는 역할 `[]`(미리 만든 팩이 채움, 매니페스트 C3). 러너: 확인자 = 기본 캐릭터 페르소나·두뇌(`roster("default_character")`), 역할 없는 작업 = 첫 전문 역할(`WORKER_ROLE="staff"` 삭제; 앱은 항상 계획의 역할을 넘기므로 수동 CLI 실행에만 해당). 러너 1,500줄 상한 때문에 #459의 재실행 로직을 `accounts.rerun_on_switch`로 옮김.
- **현재 팀 동작 변화 없음**: 기본 노노[dev, pd] → 전문 역할 staff·dev·artist(전과 같음), 확인자 노노(전과 같음).
- **테스트**: `test_team_roles` 3건(자리≠이름, 명단 없을 때 가장 오래된 카드, **엔진 코드에 역할 이름 금지 가드**), 픽스처가 기본 캐릭터를 `team.json`으로 명시(`test_delegation`·`test_instructions_api`·`test_worktree_runner`·`test_identity`), `test_accounts` 재실행 3건.

## 2026-09-30 — agy 계정 전환 뒤 옛 계정 작업자·로그인 프로세스가 남음 (ACCOUNT_SWITCH_v1·LOGIN_BASELINE_v1, #459)

- **증상**: 13:06 agy 계정 전환 뒤 `/api/accounts`에 두 프로세스가 남음 — #456 위임 작업자(`agy -p`, 옛 계정, `stale`인데 `external`)와 상태 탭 로그인 TUI(pts/2, 새 계정, 로그인 완료 후에도 살아 있음). 앞의 것은 9/19 사고(옛 refresh token이 토큰 파일을 되돌려 씀)와 같은 위험.
- **원인**: ① 자동 재시작(`stale_owned`)은 서버가 직접 띄운 세션·standby만 봄 — 러너의 자식은 `external`. ② `account_login.complete()`가 성공을 표시하고 끝, 감시 스레드는 상태가 pending이 아니면 바로 빠져나가 아무도 CLI를 끝내지 않음. ③ 로그인 성공 판정이 "로그인돼 있음"이라 로그아웃 없이 전환하면 옛 로그인으로 즉시 성공.
- **변경(운영자 결정: 멈추고 새 계정으로 재실행)**: `accounts` — 부모가 `worktree_runner.py`면 `worker`, `stale_workers`·`stop_workers`(부모 재확인 후 SIGTERM). 서버 자동 재시작 루프와 [재시작] 버튼이 옛 계정 작업자도 멈춤. `worktree_runner.run_as_login` — 에이전트·리뷰어 실행 후 실패했고 그 사이 로그인이 바뀌었으면 같은 단계를 다시(최대 2번, 시도 안 씀; 로그인을 들고 있는 제공자만 = `accounts.RECYCLE_ON_LOGIN`). `account_login` — 시작 시점 로그인(이메일 + `login_fingerprint` = refresh token 해시, 시간당 갱신과 구별)을 기준으로 "새 로그인"만 성공, 모르면 CLI가 끝날 때만; `complete()` 성공 뒤 CLI 종료. 상태 탭 라벨 "위임 작업자". 제공자 문서 A48·A49.
- **남은 것**: 지금 돌고 있는 #456 러너는 옛 코드를 읽은 채라 재실행 기능이 없음 — 멈추면 그 시도는 실패로 기록됨.
- **테스트**: `test_accounts` 3건, `test_auto_recycle` 1건, `test_account_login` 3건, `test_worktree_runner.AccountSwitch` 4건.

## 2026-09-30 — 그림 관리: 빠진 그림을 PD에게 부탁 (ART_ASK_v1, am/E #458)

- **결정(운영자)**: [생성 요청]은 티켓을 직접 만들지 않고 입력창에 부탁 문장을 채움 — PD가 받아 티켓·위임(PD 모델, 티켓 증거는 대화 기록). 계획 §4.3에 기록.
- **변경**: `app-art.js` 아이콘·배경·표정 탭 아래 [빠진 그림 부탁하기] — 그 탭에서 자기 그림이 없는 칸(대체만 되는 칸 포함) 이름, `character-art` 스킬, §10 사양 한 줄(표정은 투명·지금 프레이밍·같은 캔버스, 배경은 인물 금지), 결과는 그 캐릭터 갤러리로. 모달을 닫고 `fillComposer`로 채움(보내기는 운영자). 사적 대화에선 버튼 없음. 빠진 게 없으면 알림만.
- **테스트**: `test_art_manager_page` 문장·빠진 것 없음·업무 대화 한정.

## 2026-09-30 — 그림 관리: SillyTavern 스프라이트 ZIP 팩 가져오기 (ART_PACK_v1, am/D #457)

- **변경**: `art_manager.pack` + `POST /api/characters/<id>/art/pack`(본문 = ZIP, `X-Framing` = bust/full). 파일 이름이 곧 표정 — `Joy.png`→`joy`, `joy-1.png`는 joy 두 번째 장, 모르는 이름(`smug`)은 그 캐릭터만의 표정. ZIP 안 폴더·`__MACOSX`·점 파일은 무시. 칸에 넣는 규칙은 갤러리 [표정으로]와 같은 `_place` 한 곳(캔버스 맞춤·WebP 상한·PNG 마스터·옛 그림 `_old/`). 팩을 고른 것이 승인이라 갤러리를 거치지 않음. 넣을 수 없는 파일(투명 아님·이름 불가·같은 이름 두 번·그림 아님)은 이유와 함께 건너뛰고 나머지는 반영. 상한: ZIP 100MB, 파일 200개, 풀었을 때 300MB. `server.py` 변경 없음(업로드 연결 줄이 이미 `art_manager.handle_upload`).
- **화면**: 표정 탭 아래 [ZIP 팩 가져오기 · 상반신/전신](지금 고른 프레이밍), 표정 탭에 ZIP을 끌어다 놓아도 됨. 결과 한 줄 "표정 N개 반영 · 건너뜀 M개: 파일 (이유)".
- **배포**: ⚡.
- **테스트**: `test_art_manager` 3건(이름·건너뜀·교체 보관, 잘못된 팩, 라우트), `test_art_manager_page` 결과 문장.

## 2026-09-29 — 병합은 됐는데 티켓이 열린 작업의 [승인] (MERGED_CLOSE_v1, #378)

- **증상**: 그림 카드 #371 [승인] → "ticket 371 has no delegated change awaiting a merge". 01:42 병합(fast-forward)은 됐지만 티켓을 닫기 전에 병합 작업권이 만료돼(`author lease expired`) 러너는 `merged-ticket-open`, 티켓은 `awaiting_merge`로 어긋남. 카드는 티켓을 보고 [승인]을 띄우고, 서버는 러너를 보고 거절.
- **변경**: `delegation.merge`가 `merged-ticket-open`이면 `_close_merged` — 러너가 남긴 병합 커밋이 main의 조상일 때만, 운영자 작업권(`merge_go`)으로 평소의 완료 관문(`release done`)을 거쳐 티켓을 닫음. 실패하면 작업권을 돌려놓아 원래 상태로.
- **배포**: ⚡.
- **테스트**: `test_delegation` 2건(닫힘, main에 없으면 거절).

## 2026-09-29 — HTTP 두뇌에 Edit·Glob·Skill, 도구 예산 업무 40 / 사적 8 (PARITY_TOOLS_v1, par/C–F #377)

- **변경**: `mcp_parity.py`(웹 도구처럼 서버 옆 모듈) — `edit_file`(Claude Edit 계약: 정확히 한 번 일치 또는 `replace_all`, 결과는 `write_file`과 같은 규칙으로 검사 — 규칙은 `mcp_server._write_refusal` 하나로 뽑음), `find_files`(허용 루트 안 glob, 비밀 이름·.git 제외, 200개 상한), `skill`(목록: 이름+설명(YAML `>`/`|` 포함), 로드: SKILL.md 본문+참조 파일 목록). `adapter_openai.tool_budget`: 업무 40·사적 8(D3 결정).
- **테스트**: `tests/test_mcp_parity_tools.py`, `test_tool_budget_wrapup`에 모드별 예산, `test_mcp_server` 도구 목록. `mcp_server.py` 900줄 가드 안(898).
- **배포**: ⚡.

## 2026-09-29 — HTTP 두뇌에 웹: MCP `web` 도구 (WEB_TOOL_v1, #376)

- **증상**: OpenRouter Space Bunny가 웹을 못 씀. CLI 두뇌는 웹 도구가 내장, HTTP 경로는 우리가 넘긴 MCP 도구(17개)뿐이고 웹이 없었음.
- **변경**: `web_tool.py` — `web {action: read|search}`. 백엔드는 agent-reach(이 호스트에서 웹을 제일 잘 쓰는 리서치 라우터)가 고른 키 없는 서비스를 CLI 없이 차용: 읽기 Jina Reader(실패하면 직접 가져와 본문 추출), 검색 Exa 공개 MCP(실패하면 DuckDuckGo lite — html 페이지는 이 IP에 캡차). `CHATBOT_WEB_READER`·`CHATBOT_WEB_SEARCH`로 교체·끄기. **공개 인터넷만**: 루프백·사설·링크로컬·tailnet 주소로 풀리는 호스트는 연결 전·리다이렉트마다 거절(사적 세션 기록 등 집 안 서비스 보호, 제3자 리더에도 넘기지 않음). **사적 세션에선 닫힘**(검색어로 사적 대화가 나가지 않게).
- **확인**: 실측 — Exa 검색 3건, Jina로 SillyTavern 문서 읽기, 127.0.0.1·localhost·100.x·file://·diskstation 거절.
- **배포**: ⚡(MCP 서버).
- **테스트**: `tests/test_web_tool.py`(오프라인: 가짜 DNS·응답), `test_mcp_server` 도구 목록에 `web`.

## 2026-09-29 — 그림 관리 모달 v0: 갤러리에서 골라 칸에 (ART_MANAGER_v1, am/B·am/C #375)

- **계기**: 코코가 위임으로 그린 그림(`characters/<노노>/gallery/nono-desk-01.png`, #371)을 볼 곳이 없었음. 그림을 직접 할당할 방법도 없음.
- **서버** `art_manager.py`: `GET /api/characters/<id>/art`(칸 목록 — 아이콘·배경·표정(bust/full), 각 칸이 자기 그림/대체된 이름/placeholder인지 — + 갤러리 + 형식 문제), `…/gallery/<파일>`, `POST …/art/assign`(갤러리 그림을 칸에: 종류별 캔버스에 맞춰 WebP 상한 이하로, PNG 마스터 보관, 옛 그림은 `_old/`; 표정은 투명 필수), `…/art/upload`(갤러리로), `…/art/remove`(칸의 그림을 갤러리로 되돌림). 삭제 없음. `server.py`는 기존 연결 줄에 붙이기만(+1줄).
- **화면** `app-art.js`·`art-manager.css`: 탭 갤러리·아이콘·배경·표정, 칸 배지(내 그림 / → 대체 이름 / 기본), 갤러리 카드의 [아이콘으로][배경으로][표정으로…], 올리기·끌어다 놓기, 반영하면 헤더 아바타·무대·스프라이트 다시 읽음. 여는 곳: 캐릭터 트레이 끝 [그림], 갤러리에 그린 작업 카드의 [갤러리].
- **배포**: ⚡.
- **테스트**: `tests/test_art_manager.py`(Pillow로 실제 변환), `tests/test_art_manager_page.py`.

## 2026-09-29 — 작업 결정 버튼은 누르면 바로, 말풍선 없이 (TICKET_BUTTONS_v1·FILL_COMPOSER_v1, #374)

- **증상**: 위임 카드 버튼이 입력창에 `/ticket …`만 채우고 보내기 버튼은 꺼진 채(값만 넣고 `updateSendButton`을 안 부름). 운영자: 바로 전송, 말풍선도 필요 없음.
- **변경**: `app-evolution.js::runTicketDecision` 하나로 — 작업 카드·개선 탭 행·입력창 위 티켓 바·선택지 칩이 모두 이 경로(전엔 세 벌 복사). 버튼은 즉시 결정하고 알림만, 입력창·말풍선 없음. [폐기](decline·discard)만 확인 창. [진행]은 지시문을 보통 메시지로 에이전트에게. [반려]·[계획 수정]은 입력창에 채우고 `fillComposer`로 보내기 버튼을 깨움(인용하기도 같은 함수). 손으로 친 `/ticket …`은 말풍선을 남김.
- **테스트**: `tests/test_ticket_buttons.py`, `test_observation_ui`를 새 결정으로(옛 "Enter가 결정" 고정 해제). 래칫 기준선 두 줄 하향(복사본 제거).

## 2026-09-29 — 그림은 이름으로 대체 (ART_NAMES_v1, crp/S2 #373)

- **결정**: 운영자가 SD1–SD4·AM1–AM4 모두 추천대로. 모달은 "적당히 붙여서 깎아보자".
- **변경**: `characters.art_file`이 SillyTavern 이름 규칙(표정 + `.`/`-` 접미사)을 거꾸로 읽어 대체 — `joy.giggle-2`→`joy.giggle`→`joy`→`neutral`→다른 프레이밍→placeholder, 두뇌 폴더(`sprites/bust/grok/`)가 먼저. 한 표정 여러 장(`joy`, `joy-1`)은 무작위 한 장. 무대는 장소: `stage.<이름>`→`stage`→(옛 `stage/<두뇌>` 읽기만)→placeholder. 라우트가 스프라이트에 `provider`, 무대에 `name`을 넘김. 데이터 표 없음.
- **배포**: ⚡ (서버 모듈).
- **테스트**: `test_character_art_fallback` 4건 추가.

## 2026-09-29 — 모바일에서 보내기를 눌러도 키보드가 안 내려감 (SEND_KEEPS_KEYBOARD_v1, #370)

- **증상**: 보내기를 누르면 가상 키보드가 내려갔다가 다시 올라옴 — 버튼이 입력창의 포커스를 가져가 키보드가 내려가고, `send()`가 입력창에 다시 포커스를 줌.
- **변경**: 보내기 버튼의 `pointerdown` 기본 동작을 막아 포커스가 입력창에 머묾(`#modelBtn`과 같은 방식). 전송은 그대로 `click`.
- **테스트**: `tests/test_send_keeps_keyboard.py`.

## 2026-09-29 — 부팅 커튼: 로딩 중 덜그럭거림 없이 한 번에 (BOOT_CURTAIN_v1, #368)

- **증상**: 로딩되면서 위젯이 덜그럭거림. `boot()`가 제공자→테마 색→캐릭터·아바타→모델→세션(기록, 사적 모드 버튼 숨김)→무대 순서로 페이지를 바꾸는데 그 과정이 전부 보였음. 무대는 기본 스튜디오 그림을 보여 주다 캐릭터 그림으로 바뀜.
- **변경**: `<html class="booting">`이면 body 투명(배치는 그대로라 측정 가능), `boot()`가 끝난 뒤 두 프레임 후 0.3초에 걸쳐 나타남, 멈춘 부팅이면 4초 뒤 강제로. `html` 바탕을 `--bg`로(흰 번쩍임 방지). 무대 층은 자기 그림이 로드된 뒤(`stage-ready`) 서서히.
- **테스트**: `tests/test_boot_curtain.py`.

## 2026-09-29 — 최적화 2: 코드 강조기는 코드 블록이 있을 때만 (HIGHLIGHT_LAZY_v1, #367)

- **측정**: `highlight.min.js` 125KB(gzip 42KB) — 페이지 스크립트의 1/6, 사적 대화에선 거의 안 씀.
- **변경**: 페이지에서 `<script>` 제거, `markdown.js::ensureHighlightLoaded`(mermaid와 같은 방식)가 첫 코드 블록 때 한 번 불러옴. 실패하면 다음 블록이 다시 시도. 미리보기 창(`artifacts.js`)도 같은 로더. 테마 CSS는 작아서 그대로.
- **테스트**: `tests/test_highlight_lazy.py`.

## 2026-09-29 — 최적화 1: 세션 동기화는 안전망만, JSON API 압축 (SYNC_THROTTLE_v1·API_GZIP_v1, #366)

- **측정**: 화면이 보이는 동안 2.5초마다 세션 전체(20–30KB, 무압축) + 세션 목록(15KB) + active를 받아 화면과 대조 — SSE가 멀쩡해도. 탭 하나 시간당 약 60MB. 서버 응답은 4–8ms라 병목은 전송·대조.
- **변경**: `app-session.js::syncDue` — 스트림이 닫혔으면 매 틱(전과 같음), 열려 있으면 30초마다, 작업 중 스트림이 10초 조용하면 즉시. 탭 복귀·SSE 재연결 때 동기화는 그대로. `server.py::_send`가 JSON 응답도 gzip 요청 시 압축(1KB 이상, `Vary`).
- **배포**: 서버 변경 ⚡ 필요(gzip). 페이지 쪽은 새로고침.
- **테스트**: `tests/test_sync_throttle.py`, `test_static_delivery`(JSON gzip 실서버).

## 2026-09-29 — 작성 중 흐르는 바가 말풍선 밖으로 안 나감 (FLOW_SWEEP_INSIDE_v1, #365)

- **증상**: 작성 중인 문단 위를 흐르는 1px 바(폭 38%)가 자기 폭의 −110%→280%로 움직여 문단 왼쪽 42% 앞에서 시작해 오른쪽 44% 밖에서 끝남 — 말풍선 옆면을 뚫음.
- **변경**: 0%→163%(38%×2.63=100%)로 문단 안에서만, 양 끝은 서서히 나타나고 사라짐.
- **테스트**: `tests/test_flow_sweep.py`(폭×이동량으로 양 끝이 문단 안인지).

## 2026-09-29 — 프라이빗 토글은 맨 왼쪽, 사적 모드에선 스킬·위치 버튼 없음 (PRIVATE_FIRST_v1, #364)

- **요청**: 모드 토글은 늘 있으니 가장 왼쪽으로. 사적 모드에선 `/act` 말고 의미 있는 게 없으니 스킬·위치 버튼 제거.
- **변경**: `#privateBtn`을 컴포저 맨 앞으로(마크업 + 폰 `order:0`). `body.private-session`에서 `#slashBtn`·`#geoBtn` 숨김(`chat-features.css`). `/` 입력 메뉴와 위치 동기화 자체는 그대로 — 켜 두었다면 사적 모드에서도 계속 보냄.
- **테스트**: `test_private_toggle` 갱신.

## 2026-09-29 — 중지하면 알림이 한 번만 (STOP_NOTICE_ONCE_v1, #363)

- **증상**: 중지 버튼을 누르면 "…의 요청으로 작업이 중지되었습니다."(서버 `stopped` 이벤트)와 "작업을 중지했습니다."(버튼 처리 코드)가 둘 다 뜸.
- **변경**: 서버 알림이 정본(모든 창·기록에 감). 버튼 쪽 알림은 1.5초 안에 `stopped` 이벤트가 안 오면(스트림 끊김)만 대신 띄움(`app-sse.js` `lastStopNoticeAt`).
- **테스트**: `tests/test_stop_notice.py`(실제 클릭 처리 코드를 node로).

## 2026-09-29 — 모델 버튼을 입력창 구석으로: 들어가면 이름, 좁으면 아이콘 (MODEL_TAG_v2, #362)

- **요청**: 폭이 줄면 긴 모델명이 입력창을 대부분 덮음. 왼쪽 모델 아이콘을 없애고, 좁을 때 그 아이콘이 뜨게.
- **변경**: 따로 있던 `#modelTag`를 없애고 `#modelBtn` 자체를 입력창 오른쪽 구석(첨부 버튼 왼쪽, 마지막 줄)으로 옮김 — 메뉴·접근성·단축키는 그대로. 빈 칸에서 이름이 입력창 폭의 35%를 넘으면 아이콘만(`icon-only`), 글을 치는 중·낮은 화면(`max-height:500px`)·폰 키보드가 열렸을 때도 아이콘. 키보드·낮은 화면에서 버튼을 숨기던 규칙은 제거(모델은 늘 바꿀 수 있음).
- **테스트**: `test_model_tag` 재작성, `test_model_picker` 갱신.
