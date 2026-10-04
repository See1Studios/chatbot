# chatbot 개발로그

## 2026-10-05 — agy의 소요 시간도 누적값: 턴 시간은 엔진이 잰다 (#647)

- **실사용 #7·#8**(Claude Code가 넣은 시험): #7은 서브에이전트가 375초 걸린 뒤에도 턴이 8분 한도까지 열려 있다가 닫혀서 실패가 맞았다. #8은 46초 만에 "통과"로 답했는데 "시간 초과"로 실패 처리됐다. agy 결과의 `duration_seconds`도 대화 누적이다(54.4초 다음 턴이 147.6초).
- **고침**: 시간 초과 판정과 "빈 결과 + 시간 초과면 멈춤" 판정 둘 다 엔진이 잰 턴 시간을 쓴다.
- **확인된 것**: 턴 사용량은 이제 턴 몫이다(#8: 새 입력 9,927, 캐시 61.7만, 맥락 15.7만).
- **남은 것**: #7처럼 서브에이전트가 끝나고 보고까지 한 뒤에도 agy 턴이 한도까지 열려 있는 경우가 있다(원인 미확인).
- **재시작**: 필요(⚡ 어댑터).

## 2026-10-05 — agy 사용량 누적은 대화 단위, 넘기기 실패는 한 번 더 보고 (#646)

- **실사용 #6**(Claude Code가 넣은 시험): 코코는 32초 만에 지정 테스트만 돌리고 노노에게 보고했다. 전체 테스트 금지는 작동했다. 그런데 기록상 넘기기는 "실패"였다. 턴이 끝난 직후 답이 아직 기록에 안 들어간 순간을 봤다. 이제 답 없음은 한 번 더 본 뒤에야 실패다.
- **정정**: #644는 agy 누적을 "프로세스 단위"로 봤지만, 재시작한 새 프로세스의 첫 턴이 입력 212만이었다. 누적은 대화 단위다. 직전 턴의 누적값을 기록(`running_total`)에 남기고 같은 대화의 다음 턴에서 뺀다. 이 고침 전 마지막 턴은 기준값이 없어서 다음 한 턴은 한 번 더 과대치일 수 있다.
- **재시작**: 필요(⚡ 어댑터, `dialog_handoff.py`).

## 2026-10-05 — 토큰 배지의 "창" 값은 마지막 호출의 맥락 (#645)

- **운영자 질문**: 말풍선의 토큰 표시는? 말풍선 툴팁은 턴 usage를 그대로 보여 주는데, agy는 그 값이 프로세스 누적이었다(#644에서 턴 몫으로 고침, 새 턴부터 맞음, 옛 말풍선은 과대치 그대로).
- **고침**: 세션 배지의 "창 ○○"은 "마지막 턴 입력"(턴 안의 호출 합)이 아니라 마지막 모델 호출의 맥락(`context_tokens`)을 보인다. 기록이 없는 옛 턴은 이전처럼 입력값이다. 말풍선 툴팁에 "맥락"을 더했다.
- **재시작**: 필요 없음(페이지 새로고침).

## 2026-10-05 — 넘기기 #5에서 나온 세 가지 (#644)

- **실사용**: 줄 단위 페이드인을 코코에게 다시 넘겼다(#5, Claude Code가 넣은 시험). 코코는 서브에이전트에 맡겼고 서브에이전트는 70초 만에 확인을 마쳤지만, 끝에 전체 테스트(`./run-tests.sh`, 7분+)를 돌렸다. agy가 그것을 백그라운드로 돌리며 기다렸고, 코코의 턴은 8분 출력 한도에서 "맡겨 뒀다"는 말만 남기고 닫혔다. 넘기기는 "완료"로 기록됐다.
- **채팅 에이전트는 전체 테스트 금지** (LIVE_AGENT_SUITE_v1): 호스트가 띄우는 에이전트 프로세스에 `CHATBOT_LIVE_AGENT`를 붙이고(서브에이전트도 물려받음), `run-tests.sh`는 그 표시가 있으면 전체 실행을 거절한다. 지정한 모듈과 `--fast`는 그대로 돈다.
- **시간 초과 턴은 완료가 아니다**: 8분 한도까지 간 턴은 표시되고(`_turn_timed_out`), 넘기기는 이유와 함께 실패로 돌아간다.
- **agy 턴 사용량은 누적값이었다** (TURN_USAGE_v1): 상시 프로세스가 내는 턴 usage는 시작 뒤 누적이다. 같은 프로세스의 직전 값을 빼서 턴 몫만 기록한다. **정정**: 앞서 운영자에게 말한 "10/04 노노 새 입력 4,040만 토큰"은 누적값을 다시 더한 과대치다(token-economy T9).
- **재시작**: 필요(⚡ `session.py`, 어댑터, `dialog_handoff.py`).

## 2026-10-05 — DM의 굵은 글씨가 행동 지문으로 쪼개지던 문제 (#643)

- **실사용**: 넘기기 #4 보고에서 코코의 `**삭제 가능**`이 DM에서 행동 지문("삭제 가능")으로 따로 떨어졌다. `*…*` 규칙이 `**…**` 안쪽 별표까지 잡았다.
- **고침**: 행동 지문은 양쪽에 별표 하나, 글자에 붙어 있을 때만이다. `**굵게**`와 `* ` 목록 기호는 말이다(`dialog_log.py::pieces`).
- **정리**: 운영자 결정으로 미추적 `static/palette-preview.png`를 지웠다(코코의 서브에이전트 조사: 참조 없음).
- **재시작**: 필요(⚡ `dialog_log.py`, 도구 서버와 호스트 둘 다).

## 2026-10-05 — 넘겨받은 디렉터는 지휘한다: 읽기는 서브에이전트가 (HANDOFF_DIRECTS_v1, #642)

- **운영자**: "코코가 직접 하는 게 아니라 서브에이전트 시켜서 하고 나한테 피드백 줄 수 있는 상태를 원했어". 넘기기 #2·#3에서 코코는 서브에이전트 없이 파일 20여 개를 직접 읽다가 예산에 걸렸다.
- **실측**: agy를 엔진과 같은 상시 실행 방식으로 띄워도, 서브에이전트를 시작하고 "started"라고 말한 뒤 결과가 올 때까지(63초) 턴이 끝나지 않는다. 그동안 운영자의 질문은 기존 `/btw` 경로(별도 프로세스)가 답한다.
- **고침**: 넘겨받은 턴에서 디렉터가 코드 파일을 직접 열면, 첫 번째는 그 자리에서 멈추고 "서브에이전트에게 시켜라" 안내와 함께 같은 대화로 이어 간다(루프 안내와 같은 방식). 두 번째는 턴을 멈춘다. 문서는 열린다. 이어 가는 사이에 넘기기 처리 루프가 "끝났는데 답 없음"으로 잘못 판정하던 틈도 막았다.
- **재시작**: 필요(⚡ `role_guard.py`, `dialog_handoff.py`).

## 2026-10-05 — 넘긴 일이 두 디렉터의 창에 보인다 (#641)

- **실사용**: 넘기기 #2는 돌았지만(코코 3분, 코드 변경 없이 "이미 반영됨" 결론) 운영자 창에는 아무것도 안 보였다. 넘김과 결과를 DM에 기록만 하고 창에 그리는 알림(`office`)을 보내지 않았다.
- **고침**: 넘길 때 할 일(`#번호` 붙음)이, 끝날 때 결과가 두 디렉터의 업무 창에 바로 그려진다(사무실 화면과 같은 경로). 이 DM은 `msg.new`를 내지 않아 받은 쪽이 따로 "반응"하지 않는다. 넘김 턴이 곧 답이다.
- **정정**: 코코가 `app-sse.js`를 "통째로 8번" 읽었다고 봤는데, agy 자체 기록으로는 40~80줄 구간 읽기였다. 엔진 스트림의 `view_file`에는 범위가 없고 파일 전체 크기만 와서, 턴 예산의 읽기 바이트는 상한값으로 세진다(알려진 한계, 이번 중단은 도구 20회 때문).
- **재시작**: 필요(⚡ `dialog_tool.py`(도구 서버), `dialog_handoff.py`).

## 2026-10-05 — 첫 실사용 넘기기에서 고친 것 (#639)

- **실사용**: 노노가 줄 단위 페이드인을 dev(코코)에게 handoff(#1). 코코가 자기 세션에서 시작했지만 `app-sse.js`(43KB)·DEVLOG(31KB)를 통째로 읽다가 알림 턴 예산(도구 20회)에 걸려 멈췄고, 노노에게는 "응답 없이 실패"로만 갔다.
- **고침**: 넘겨받은 턴은 알림 턴의 절반 예산이 아니라 온전한 턴 예산(40회)을 쓴다. 프롬프트에 "검색 먼저, 필요한 줄만"을 넣었다. 실패하면 멈춘 이유(예산 초과 등)를 넘긴 쪽 DM에 같이 보낸다.
- **오탐**: 역할 권한 검사가 URL(`read_url`의 GitHub 주소)을 저장소 경로로 보고 노노의 턴을 멈췄다. URL은 판정하지 않는다.
- **재시작**: 필요(⚡ `session_turn.py`, `dialog_handoff.py`, `role_guard.py`).

## 2026-10-05 — 세션 무게를 잘못 재서 세션을 괜히 바꾸던 문제 (CONTEXT_METRIC_v1, #638)

- **실측**: 노노의 모델 호출 하나는 4.9만~8.9만 토큰(약 5만이 고정분). 엔진은 턴 안의 모든 호출을 더한 값(24만~50만)을 맥락 크기로 읽어, 10/04에 "무거움" 경고 55번·세션 교체 15번을 냈다. 교체는 요약 호출·캐시 손실·망각으로 오히려 토큰을 더 쓴다.
- **고침**: agy 어댑터가 마지막 호출의 맥락(새 입력+캐시)을 턴 사용량의 `context_tokens`로 남기고, 무게 계산이 그것을 먼저 쓴다. 기록이 없는 옛 턴과 다른 프로바이더는 그대로.
- **남은 낭비**: 호출마다 붙는 고정분 약 5만 × 한 턴의 호출 수. 줄이는 장치는 턴 예산(T1)과 총괄의 코드 읽기·서브에이전트 차단(director-handoff).
- **재시작**: 필요(⚡ 어댑터, `session_weights.py`).

## 2026-10-05 — 총괄은 서브에이전트 대신 넘기기 (#637)

- **실사용**: "위임해서 진행해"에 노노가 handoff도 delegate도 아닌 agy 서브에이전트(전체 도구, 본 트리)를 두 번 띄웠다. 턴 하나가 489초, 입력 24만 토큰. 운영자 요청으로 중단했다(본 트리는 깨끗).
- **고침**: `repo: none` 역할이 서브에이전트를 띄우면 턴을 멈추고 handoff를 안내한다(어댑터 `subagent_tools`). agy는 끝난 서브에이전트 호출을 step_type `subagent`로 보내서, 도구 단계 추출기가 그동안 이 호출을 세지 못했다(`loop_guard.py::extract_tool_steps`).
- **역할 지침**: 모든 역할 팩에 "다른 역할의 일은 handoff, 서브에이전트는 읽기·확인만"을 넣고, 개발 역할에 `delegate`를 줬다(넘겨받은 코드 일을 계획으로 올릴 수 있게).
- **재시작**: 필요(⚡ `role_guard.py`, `loop_guard.py`, 어댑터). 라이브 역할 팩도 같이 고친다.

## 2026-10-05 — 디렉터끼리 일 넘기기 (director-handoff 2단계, #636)

- **넘기기** (HANDOFF_v1, `dialog_handoff.py`): 캐릭터가 자기 역할 밖의 일을 `dialog` 도구의 `handoff`로 그 일을 맡은 디렉터(역할 또는 캐릭터)에게 넘긴다. 할 일과 완료 조건이 둘의 DM에 남는다.
- **받은 쪽 착수**: 호스트 반응 루프가 20초마다 보고, 받은 디렉터의 업무 세션이 비어 있으면 그 세션에서 일하는 턴을 연다(도구 허용, 사용자 말 아님). 운영자는 그동안 다른 캐릭터와 계속 대화한다. 프롬프트는 "읽기·확인은 서브에이전트에게, 코드 수정은 delegate 계획(운영자 [실행] 대기)으로, 저장소 파일을 직접 고치지 말 것"이다. 실제로 막는 건 1단계의 트리 감시와 역할 권한이다.
- **결과 보고**: 그 턴이 끝나면 답이 넘긴 쪽 DM으로 돌아가고, 넘긴 디렉터가 한가하면 운영자에게 한두 줄로 알린다. 답 없이 끝나면 실패로 돌아간다.
- **제한(D-4)**: 한 요청에서 넘기기는 2번까지, 디렉터당 열린 넘기기 1건. 받은 턴은 호스트 턴이라 알림 턴 예산(도구 20회)으로 돈다.
- **분야(D-5)**: 역할 팩 `owns:`(맡는 일). 넘길 곳을 안 정하면 역할별로 맡는 일을 보여 준다. 어댑터가 서브에이전트 사용법(`subagents`, `subagent_hint`)을 알린다.
- **재시작**: 필요(⚡ `dialog_tool.py`(도구 서버), `event_react.py`, `dialog_handoff.py`, `characters.py`, 어댑터). 라이브 역할 팩에 `owns:`를 넣는다.

## 2026-10-05 — 새던 가드를 막는 가드로 (director-handoff 1단계, #634 #635)

- **실측(dir/C)**: CLI 4개 모두 서브에이전트를 띄우지만, 서브에이전트가 도는 동안 턴을 끝내는 CLI는 없었다. 서브에이전트 안의 도구 호출은 agy·codex에선 안 보이고, grok에선 메인 호출처럼 보인다. 결과는 계획 §3.4.
- **티켓 없는 쓰기 = 턴 중단** (NO_TICKET_WRITE_v1 강화): 경고만 하던 것을 바로 멈추게 바꿨다. 10/4에 경고 3번이 무시됐다.
- **작업 트리 감시** (TREE_WATCH_v1, `write_guard.py`): 턴 시작과 끝에 git 작업 트리를 비교한다. 리스 없이 바뀐 파일은 보류로 잡아 운영자에게 알리고, 깨끗해지거나 티켓이 생길 때까지 업무 턴마다 "되돌리거나 티켓부터"를 앞에 붙인다. 서브에이전트가 고친 파일도 잡힌다. 한계: 턴 도중 다른 사람이 본 트리를 고치면 그 턴 탓으로 잡힌다.
- **역할 권한 집행** (ROLE_TOOLS_v1, `role_guard.py`): 역할 팩의 `repo: none`(총괄). 엔진 경로 도구는 거절하고, 프로바이더 자체 도구가 코드 파일을 열면 턴을 멈춘다. 문서(`docs/`, `.md`)는 열린다. grok처럼 서브에이전트 호출이 메인 것처럼 보이는 프로바이더는 어댑터가 `own_tool_steps = False`로 알리고, 그때는 판정하지 않는다. 명령 실행은 판정하지 않고 트리 감시가 잡는다.
- **재시작**: 필요(⚡ `session.py`, `session_turn.py`, `write_guard.py`, `role_guard.py`, `mcp_server.py`, `characters.py`, 어댑터). 라이브 `~/.pe` lead `ROLE.md`에 `repo: none`을 넣어야 켜진다.

## 2026-10-05 — 위임에서 방해만 되던 절차 걷어내기 (director-handoff 0단계, #632 #633)

- **운영자 지적**: "질질 새고 방해나 되고 있는 구조". 채팅에서 시작한 위임 9건(#605–#631) 중 머지는 4건. 두뇌 없음(쿼터·타임아웃) 10번, 리뷰 FAIL 3번.
- **화면 작업은 리뷰 없이 코치 확인으로** (DISPLAY_LANE_v1): `static/`와 그 테스트만 바꾸는 작업은 diff 리뷰를 건너뛰고, 게이트만 통과하면 운영자 머지를 기다린다. 화면 느낌은 diff로 판정할 수 없다(#627–#631).
- **리뷰는 한 번** (REVIEW_ONCE_v1): 코드 리뷰가 FAIL하면 작업자가 한 번 고치고 게이트를 다시 돈다. 두 번째 리뷰로 다 된 일을 버리지 않고(#631), 요청된 수정은 참고 의견으로 운영자에게 간다. FAIL을 받은 작업은 스스로 main에 올라가지 않는다.
- **쉬는 두뇌 기억** (BRAIN_LIMITS_v1, `tools/brain_limits.py`): 한도에 걸린 두뇌는 오류의 "Resets in …" 시각까지, 타임아웃 난 두뇌는 30분 동안 건너뛴다. 모두 쉬는 중이면 실행하지 않고 바로 `unavailable`로 끝낸다(#628: 1200초 타임아웃 3번).
- **정리**: 노노가 티켓 없이 넣은 lead `PROCEDURE.md` 한 줄은 되돌렸다(D-6, 역할 권한 집행 dir/A로 대체).
- **재시작**: 필요 없음(러너는 위임마다 새로 읽힌다).

## 2026-10-04 — [ui/stream] 줄 단위 스트리밍(Line Reveal) 마크다운 컨테이너 렌더링 순회 및 페이드인 실동작 보강 (#630, 위임 agy)

- **커밋**: `d22b378` feat(stream): traverse nested markdown containers for line reveal and enhance fade-in
- **바뀐 파일**: `static/app-sse.js`, `static/chat-log.css`, `tests/test_stream_style.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-04 — [ui/stream] 줄 단위 스트리밍(Line Reveal) 페이드인 부드러운 전환 연출 추가 (#629, 위임 agy)

- **커밋**: `79de6b0` fix(ui): restore app-sse comments and refine line reveal test harness, `996c540` feat(ui): add smooth fade-in transition for line reveal streaming
- **바뀐 파일**: `static/app-sse.js`, `static/chat-log.css`, `tests/test_stream_style.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-04 — [stream/reveal] 스트리밍 애니메이션 줄 단위(Line Reveal) 옵션 추가 (#627, 위임 agy)

- **커밋**: `7058fa6` fix(ui): restore app-sse comments and strictly validate stream style, `94bf2f3` feat(ui): add line reveal streaming mode and settings toggle
- **바뀐 파일**: `static/app-shell.js`, `static/app-sse.js`, `static/chat-log.css`, `tests/test_stream_style.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-04 — 위임 병합의 DEVLOG 줄이 커밋되지 않던 문제 (#626)

- **원인**: 러너는 병합 뒤 "티켓 기록 + DEVLOG 줄"을 함께 커밋하는데, 기록이 `~/.pe`로 나간 뒤로는 "저장소에 기록이 없으면 아무것도 안 함"에 걸려 DEVLOG 줄만 main에 미커밋으로 남았다(#620에서 발견, `7ce0803`로 수습).
- **고침**: 기록이 저장소에 없으면 DEVLOG 줄만 `docs(devlog): …`로 커밋한다(`tools/worktree_runner.py::commit_ticket_record`).
- **재시작**: 필요 없음(러너는 위임마다 새로 읽힌다).

## 2026-10-04 — 작업 만담은 동료 DM으로, 카드는 결재판으로 (WORK_TALK_v1, #623)

- **운영자 결정**: 9/23의 "만담은 카드 안에 접힘"을 바꿈. 위임 중 전문가의 한마디와 PD의 리뷰 한마디가 둘의 DM(`dm:<a>:<b>`)에 쌓인다. 사무실 화면에서는 동료끼리 주고받는 말로 보이고, 두 캐릭터가 기억한다.
- **카드**: 대사 목록을 뺐다. 단계, 최신 판정(PASS/FAIL과 수정 요청), 버튼, 그리고 `대화 보기`(작업한 캐릭터의 창을 연다).
- **안전**: 작업 대사는 `msg.new`를 내지 않는다(`dialog_log.append(announce=False)`). 자동 반응을 켜 둬도 대사마다 상대가 턴을 돌려 연쇄되지 않는다. 처음 본 실행이 이미 끝난 것이면 옛 대사를 되살리지 않는다.
- **위치**: 서버의 위임 감시 루프가 진행 파일을 읽어 옮긴다(`delegation.py::mirror_work_talk`, 커서 `<data>/work_talk.json`). 러너(운영자 전용 파일)는 그대로.
- **재시작**: `delegation.py`·`dialog_log.py`가 바뀌어 `chatbot-ctl.sh repair`가 필요하고, 화면은 새로고침.
## 2026-10-04 — [client/device] 모바일 클라이언트 기기 환경 수집 확장 (배터리·네트워크·복귀감지·정밀도) (#620, 위임 agy)

- **커밋**: `c216f23` fix(client): harden client context formatting against non-finite values and bools, `4e5a789` feat(device): add background return detection and harden accuracy parsing, `3a6582c` feat(device): extend client context with battery, network, visibility, accuracy
- **바뀐 파일**: `session.py`, `static/app-device.js`, `tests/test_client_device_context.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-04 — 누가 했는지 모르는 티켓을 막음 (ACTOR_REQUIRED_v1, #622)

- **장치**: `ticket-quick`은 `--actor`도 없고 부모 프로세스로도 에이전트를 모를 때(`unknown-cli`) 아무것도 쓰지 않고 거절한다. 규칙표의 "manual" 한 줄이 강제 장치를 얻었다.
- **실측**: 규칙표의 "290건"은 낡은 수치였다. 실제 `unknown-cli`는 3건(#245 #594 #595). 캐릭터 로마자 별명 `nono`가 actor인 기록 3건(#566 #579 #580)은 role id 모양이라 기계로 못 막는다(manual로 표기).
- **죽은 장치 정리**: "티켓 기록은 role id" 검사는 커밋 훅이었는데, 기록이 `~/.pe`로 나간 뒤 커밋되지 않아 돌지 않았다. 규칙표의 강제 장치를 실제로 막는 쪽(`tickets.py`가 쓸 때 거절, `test_tickets`)으로 고쳐 적었다.
- **재시작**: 필요 없음(외부 CLI 도구만 바뀜).

## 2026-10-04 — 모든 위임이 "기반 고장"으로 멈추던 문제 (#621, #620에서 발견)

- **원인**: `c54e312`부터 게이트가 작업 트리의 빈 `data/`로 돈다. `tests/smoke.py`는 HTTP 제공자(openrouter·omniroute)가 등록돼 있다고 보는데, 그 설정(`providers.json`)은 설치 데이터라 체크아웃에 없다. 그래서 그 뒤 위임은 작업과 무관하게 smoke에서 실패했고, 기반 검사도 같이 실패해 `base_broken`으로 멈췄다(#620).
- **고침**: smoke가 임시 데이터 폴더에 견본 `templates/providers.example.json`을 깔고 돈다(테스트가 고정물을 직접 가짐, #604와 같은 방향).
- **#620**: 작업은 보존돼 있다. 다음 실행(`--plan-from-state`)이 main 위로 옮겨 게이트·확인부터 이어 간다.

## 2026-10-04 — 위임 러너의 282줄 함수를 단계별로 (split/H, #619)

- **무엇**: `tools/worktree_runner.py::cmd_run` 하나가 준비·worktree·작업·게이트·리뷰·병합·정리를 다 했다. 단계 함수 10개로 나누고 공유 상태는 실행 문맥 하나에 모았다. 동작 불변(러너 테스트 전부 그대로 통과), 가장 긴 함수 약 60줄.
- **재시작**: 필요 없음(러너는 위임마다 새로 읽힌다; 엔진이 들고 있는 사본은 다음 재시작에 교체).

## 2026-10-04 — 티켓이 엔진 저장소를 다시 본다: 꺼져 있던 완료 전 가드 (split/H, #618)

- **원인**: 데이터가 `~/.pe`로 나간 뒤 `tickets.py`는 "저장소"를 데이터 폴더의 git 루트 = 홈 저장소로 잡았다. 그래서 `AGENTS.md`는 `~/AGENTS.md`로 검사됐고(엔진 파일의 잔여물은 못 잡고, 홈 파일 때문에 엉뚱한 거절), 홈엔 `run-tests.sh`가 없어 **`done` 전 가드 검사가 0초 만에 통과**했다(pew/O 안전장치가 꺼진 상태).
- **고침**: 설치의 데이터 폴더면 엔진 체크아웃(`CHATBOT_ROOT`, 없으면 `tickets.py` 위치)의 저장소에서 판정한다(`tickets.py::_repo_root`). 테스트 고정물처럼 다른 폴더는 예전 그대로.
- **바뀌는 체감**: 코드 티켓의 `done`이 가드 검사(약 50초)를 다시 돈다. main HEAD의 가드가 깨져 있으면 완료가 거절된다(의도).
- **재시작**: `tickets.py`는 엔진이 불러 쓰는 모듈이라 `chatbot-ctl.sh repair`가 필요하다. 외부 CLI의 `ticket-quick`은 바로 적용.

## 2026-10-04 — 구조 감사: tools/ 보호, 코드 지도 강제, 러너 여유 (split/H, #617)

- **보호 구멍**: `tools/`가 보호 목록 밖이라 위임 작업자가 리뷰 판정 읽기(`tools/review_checklist.py`)를 티켓 없이 고칠 수 있었다. `tools/` 보호, 판정 읽기는 거버넌스(운영자 전용).
- **코드 지도**: 빠진 파일 50개를 AGENTS.md 지도에 채우고 `test_code_map`(가드)로 새 파일이 지도 없이 들어오지 못하게 했다.
- **러너**: 상한 31바이트 앞이던 `tools/worktree_runner.py`에서 작업자 출력 읽기를 `tools/worker_output.py`로 분리(동작 불변).
- **시간 의존 테스트**: `test_event_react`의 방문 반응 검사가 실제 시각으로 돌아 0–8시(조용한 시간)엔 늘 실패했다. 그 클래스만 조용한 시간을 끔.
- **정리**: 남아 있던 `.bak-248` 3개 삭제, ARCHITECTURE의 옛 경로 수정. 폴더 재배치는 계속 보류.
- **재시작**: 필요 없음(호스트 모듈 변경 없음; 엔진이 읽어 둔 러너는 다음 재시작 때 새 파일로 바뀌며 동작은 같다).

## 2026-10-03 — 귀향은 미뤄 코드를 되돌림

- **되돌림**: `54d0d85`의 소환 해제(압축 보관)는 커밋됐지만 기능은 미룬다. 모듈, 경로, 화면 버튼을 빼서 다음 기동이 그 코드를 읽지 않게 했다.
- **하지 않음**: 보관함은 만들지 않는다. 캐릭터 폴더, 대화, 노노는 그대로다.
- **재시작**: 20:20에 뜬 엔진은 이 모듈을 읽지 않아 다시 띄우지 않았다.

## 2026-10-03 — 데이터가 ~/.pe로 간 뒤 남은 옛 경로 (uds/F 후속, #601 #602)

- **재시작 안전장치**: `ctl_proc.py`가 에이전트를 `CODE/data/workspace`에서만 찾아, ~/.pe로 옮긴 뒤로는 작업 중인 에이전트를 못 봤다(바쁨 판정 항상 '한가함', 고아 정리 0건). 이제 ctl이 `$DATA`를 넘긴다.
- **스킬 색인**: 에이전트에게 옛 `~/services/chatbot/data/workspace/.agents/skills`를 가리키던 줄을 실제 작업공간 경로로.
- **테스트**: `run-tests.sh`가 내보내는 `CHATBOT_DATA`가 `AGY_CHAT_DATA`보다 앞서, 티켓·ctl 테스트가 고정물 대신 저장소 `data/`를 읽었다. 고정물을 `CHATBOT_DATA`로 지정.
- **재시작**: ctl·`instructions.py`가 바뀌어 `chatbot-ctl.sh repair`가 필요하다.

## 2026-10-03 — 개발자 모드에서만 캐릭터 폴더 삭제 (#600)

- **버튼**: 캐릭터 프로필 맨 아래 `이 캐릭터 삭제`. `pe.devMode`(`body.dev-mode`)가 켜져 있을 때만 보인다. 확인을 누른 뒤에만 보낸다.
- **지우는 것**: `characters/<id>` 폴더(카드, 기억, 외형, state, brain override)와 명단의 그 한 줄. 기본 캐릭터(노노)는 거절. 설치가 `CHATBOT_EDITION=dev`가 아니면 거절.
- **남기는 것**: `~/.pe/dialogs`, 방, 세션. 귀향(압축 보관)은 아직 아니다.
- **재시작**: 새 경로라 `chatbot-ctl.sh repair`가 필요하고, 화면은 새로고침.

## 2026-10-03 — 동료 대화 로그는 ~/.pe/dialogs (crp/D1, #599)

- **규칙**: 개인 쌍 로그는 ~/.pe/dialogs에 있고 거기 머문다. 캐릭터 폴더로 옮기던 경로는 되돌렸다.
- **데이터**: `dm_char_01m3768dpsfywrz2ty226x0p2z_char_01m376xaa1e0fsdhm3e3kbnybd.log.jsonl` 사본은 원본과 sha256이 같아 지웠다. `positions.json`은 ~/.pe/dialogs에 그대로다.
- **재시작**: 19:45에 뜬 엔진이 캐릭터 폴더로 쓰므로 19:54에 repair 했다.

## 2026-10-03 — 소환 마법사 REST와 메뉴 (cgs/F, #597)

- **REST**: `GET /api/summon` 단계 정의, `POST /api/characters/summon` 생성, `POST /api/characters/*/regenerate` 지정 필드만 재생성. 카드는 `card_gen`의 chara_card_v2와 `visual.md`만 쓴다.
- **메뉴**: 팀 탭의 새 친구 소환, 캐릭터 트레이의 같은 버튼. 단계 0-5와 7(부름, 모습, 성격, 말투, 관계, 이름, 소환). 진행, 뒤로, 바로 소환. 고른 값이 모델보다 우선하고, 직조가 실패해도 고른 값으로 카드가 생긴다.
- **하지 않음**: 첫 실행 온보딩, BYOK, 그림 생성, PNG 내보내기(마스터 이미지가 없음). `ccl/D`는 아직 대기.
- **재시작**: 호스트 모듈이라 `chatbot-ctl.sh repair`가 필요하고, 화면은 새로고침.

## 2026-10-03 — SillyTavern PNG 카드 내보내기 (cgs/E, #596)

- **도구**: `tools/st_export.py`. `card.json`과 마스터 PNG를 SillyTavern `chara` tEXt로 IEND 직전에 넣는다. 기존 `chara`/`ccv3`는 tEXt뿐 아니라 zTXt·iTXt도 빼서, `st_import.py`가 방금 쓴 카드를 읽게 한다.
- **권한**: `extensions.chatbot`의 role/roles/tools/skills는 내보낼 때 버린다. 가져올 때와 같다. 카드 형식은 새로 만들지 않는다.
- **아직**: 소환 마법사 REST(`cgs/F`)는 하지 않았다. 엔진 재시작 없음.

## 2026-10-03 — 두뇌 오버라이드를 캐릭터에 기억

- **기본값**: 카드 brains.work / brains.private 는 그대로 기본이다. 노노 사적 기본은 grok-4.7 이다.
- **기억**: 사용자가 제공자나 모델을 바꾸면 characters/<id>/brain-override.json 에 모드별로 남긴다. 카드 본문은 고치지 않는다. 제공자와 모델이 카드 첫 두뇌와 같으면 기록은 비운다.
- **다음 방문**: 사적 방을 새로 열 때 기록이 카드보다 우선이다. 기록이 없거나 기본값으로 되돌렸으면 카드를 쓴다.
- **정보창**: 프로필의 쓰는 두뇌에 업무와 사적 각각 기본인지 직접 골랐는지 보이고, 직접 고른 쪽에는 기본값으로 버튼이 있다.
- **재시작**: 호스트 모듈이라 chatbot-ctl.sh repair 가 필요하다.


## 2026-10-03 — 인수인계: 데이터 분리·관계 기억

- **데이터**: 사용자 데이터는 `~/.pe`에 있다. 이 NAS의 pin은 `CHATBOT_DATA=/var/services/homes/me/.pe`이고, 저장소 `data/`는 gitignore 대상이다. `95c1526` tip의 추적 데이터 파일은 0개다. `~/.pe`를 삭제하지 말고 개인 캐릭터 본문을 git에 넣지 않는다.
- **이력**: 로컬 이력은 재작성되어 force-push됐다. `origin/main`은 확인된 순서가 `8156908 → 95c1526 → e1f7dc0`이므로 오래된 SHA를 전제로 작업하지 않는다.
- **릴리스**: `VERSION=0.0.0-dev`, `CHANGELOG.md`, `secrets.env.example`, `docs/RELEASE.md`, 로컬 태그 `v0.0.0-dev`가 있다.
- **관계 기억**: `e1f7dc0`의 어댑터는 사적 턴에 `characters/<id>/relationship.md`의 진행·약속·선호·금기를 짧은 `[Relationship]` 블록으로 넣는다. `character-memory-adapter` 계획은 `active`이며 암호화와 메모리 UI는 아직 없다. Grok overlay는 짧아졌고 `RENDER_PROTOCOL`은 평탄화하지 않았다.
- **라이브 상태**: `e1f7dc0` 뒤 라이브 프로세스는 재시작하지 않아 옛 프롬프트를 사용한다. 반영하려면 `chatbot-ctl.sh repair`가 필요하다.

2026-09-28 기록은 하루 40KB 예산에 도달해 [devlog/2026-09-28.md](devlog/2026-09-28.md)로 회전했습니다.
2026-09-29 기록도 같은 이유로 [devlog/2026-09-29.md](devlog/2026-09-29.md)로 회전했습니다.
2026-09-30 기록도 [devlog/2026-09-30.md](devlog/2026-09-30.md)로 회전했습니다.
2026-10-01 기록은 하루 예산을 넘어 [devlog/2026-10-01.md](devlog/2026-10-01.md)로 회전했습니다.

## 2026-10-03 — 관계 기억 슬롯, 사적 작법 중복을 줄임

- **층**: 사적 묶음은 헌장 머리·Scope·카드 페르소나·카드 사적 규칙·렌더 계약·(Grok이면 턴마다 반응 오버레이)·`[Private memory]`. 업무 묶음은 헌장·역할·스킬·집 기억·캐릭터 `memory.md`. 라이브 카드의 사적 규칙은 캐릭터 고유라 고치지 않았다.
- **기억**: `memory_relationship.py`가 진행·약속·선호·금기를 사적 묶음에만 짧게 넣는다. 명시 태그만 `relationship.md`에 남고, 태그가 없는 기존 줄은 Continuity로 그대로 읽는다. 호감도 수치는 만들지 않았다. 업무 세션에는 안 넣는다.
- **작법**: Grok 오버레이에서 선택지·에코 규칙을 한 번씩만 남기고, 젖음·신음·의성·직설 조건은 유지했다. 공용 렌더 계약은 그대로다.
- **재시작**: 없음. `~/.pe`는 지우거나 덮어쓰지 않았다.
- **아직**: 암호화, 슬롯 화면, 업무/사적 옵트인 스위치. 계획은 active.

## 2026-10-03 — data/ 를 배포 트리에서 뺌

- **인덱스**: 추적 중이던 `data/` 424개를 `git rm --cached`로 뺐다. 디스크의 파일과 `~/.pe`는 지우거나 고치지 않았다. 424개 모두 `~/.pe`와 sha256이 같았고, 없는 파일은 없어 복사하지 않았다.
- **gitignore**: `data/**`만 무시한다. 티켓 기록을 다시 넣는 예외는 닫았다.
- **샘플**: 개인 페르소나·캐릭터 카드는 예시로 만들지 않았다. 빈 작업공간 템플릿은 그대로다.
- **재시작**: 없음. pin은 `~/.pe`.

## 2026-10-03 — 버전 파일과 비밀 예시 (release Now)

- **파일**: `VERSION`(`0.0.0-dev`), `CHANGELOG.md`, `secrets.env.example`(빈 자리표시). 코드는 `VERSION`을 읽지 않는다. 태그와 `RELEASE.md`는 만들지 않았다.
- **data/ 인덱스**: 개인 파일(`MEMORY.md`, `secrets.env`, 세션)은 없다. 티켓 기록은 C2라 남겼고, 작업공간 거울·페르소나·캐릭터는 C3·C5라 풀지 않았다. `~/.pe`는 지우지 않았다.
- **아직**: origin 이력에 예전 개인 데이터가 있다. 푸시하지 않음. 계획은 active.

## 2026-10-03 — 사용자 데이터 이전 도구, 새 data/ 는 커밋하지 않음 (user-data-separation)

- **도구**: `tools/migrate_user_data.py`. 기본은 미리보기라 목적지를 만들지 않는다. `--apply`만 복사하고 원본은 그대로 둔다. 목적지에 파일이 있으면 `--force` 없이 거절하고, 내용이 다른 파일은 덮어쓰지 않는다. `--remove-source`는 바이트가 같은 파일만 지우며, 비밀이든 뭐든 하나라도 다르면 아무것도 지우지 않는다.
- **git**: 새로 생기는 `data/` 파일은 무시한다. 개발 티켓 기록(`skill-observations/`)만 예외로 계속 넣을 수 있다. 이미 추적 중인 작업공간 거울·페르소나 자산은 인덱스에 남겨 두었다.
- **아직**: 원격 이력에는 개인 데이터가 남아 있다. origin은 푸시하지 않았다. 계획은 active.

## 2026-10-03 — 사용자 데이터 기본 경로를 ~/.pe 로 (uds/F, #592)

- **변경**: 환경변수가 없으면 `host_config.py`·`tickets.py`·`chatbot-ctl.sh`가 `~/.pe`를 쓴다. 우선순위는 `CHATBOT_DATA` → `PE_HOME` → `PRIVATEENGINE_HOME` → `AGY_CHAT_DATA` → (개발 pin) → `~/.pe`.
- **이 NAS**: 커밋하지 않는 `data-pin.env`가 기존 `data/`를 가리킨다. ctl이 그것을 읽고, 같은 파일을 파이썬 경로 결정도 읽어서 ctl을 거치지 않은 프로세스(티켓 도구 등)가 `~/.pe`를 새로 만들지 않는다. 데이터는 옮기거나 지우지 않았다.
- **테스트**: `run-tests.sh`는 호출자가 경로를 주지 않으면 체크아웃 `data/`를 넘긴다. 스위트가 운영자 홈의 `~/.pe`를 만들거나 읽지 않는다.
- **아직**: 마이그레이션 스크립트, `data/` 전면 gitignore, 이력 재작성. 계획 상태는 active. ⚡ 재시작 필요(`host_config.py`). pin은 재시작 전에 두었다.


## 2026-10-03 — [voice/stt] 컴포저 마이크 실시간 음성 입력 (Web Speech API STT) (#590, 위임 agy)

- **커밋**: `9663b09` fix(speech): guard against late results, restart race condition, and cleared input, `709c868` feat(ui): 컴포저 마이크 실시간 음성 입력(STT) 연동 및 테스트, `a0c337d` chore(tickets): #590 gate_failed -- [voice/stt] 컴포저 마이크 실시간 음성 입력 (Web Speech API STT), `62ebb91` chore(tickets): #590 failed -- [voice/stt] 컴포저 마이크 실시간 음성 입력 (Web Speech API STT), `e8a0951` chore(tickets): #590 gate_failed -- [voice/stt] 컴포저 마이크 실시간 음성 입력 (Web Speech API STT), `e262641` chore(tickets): #590 gate_failed -- [voice/stt] 컴포저 마이크 실시간 음성 입력 (Web Speech API STT)
- **바뀐 파일**: `static/app-speech.js`, `static/chat-composer.css`, `static/chat-responsive.css`, `static/index.html`, `tests/test_speech.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-03 — 찾을 수 없는 근거는 운영자의 마지막 말로 (engine-decides/A4, #591)

- **실측**: 티켓 제안·위임 계획이 근거 형식 틀림·없는 후보 번호로 27번 거절.
- **변경**: `mcp_args.fill_evidence` — 있는 근거는 두고, 없거나 틀린 것은 빼고, 남는 게 없으면 **도구를 부른 세션**의 운영자 마지막 말(`event:<sid>#<line>`)로. 결과 메시지에 한 줄로 알림. `delegation.latest_request_ref`도 부른 세션 기준(전엔 화면에 뜬 세션 — 다른 창의 말이 근거가 될 수 있었음). ⚡ 재시작 필요.

## 2026-10-03 — 도구 인자는 엔진이 도구가 읽는 모양으로 (engine-decides/A1, #589)

- **실측**: 9/23–10/3 `mcp.call` 1,706건 중 325건 실패, 엔진 경로 고장은 없고 이름·포장·동작 이름이 대부분.
- **변경**: `mcp_args.py` — 도구 스키마를 보고 agy식 포장(`Arguments` 문자열) 풀기, 키 대소문자, 별칭(`command`→`cmd`, `query`→`pattern`, `fact`→`text`, `content`→`body`, 위임 작업의 `name`/`description`), 글로 온 배열·객체, 동작 동의어(`show`→`get` 등)와 빠진 동작 추론. 운영자 몫 동작(승인·실행·착륙)은 바꾸지 않음. `mcp.call` 이벤트는 보낸 인자 그대로 + 고친 내용(`fixed`).
- **효과 측정**: 지난 실패에 돌리면 66건이 고쳐짐. 1주 뒤 실패율로 확인. ⚡ 재시작 필요(`mcp_server.py`).

## 2026-10-03 — 대화 에이전트는 작업자 브랜치를 main에 착륙시키지 못한다 (engine-decides/A5, #587)

- **사고**: 노노(agy)가 자체 셸로 실패한 #583을 직접 고치고 `Coco` 이름으로 커밋, `git merge --ff-only`로 main 착륙, 티켓 기록을 내부 함수로 고쳐 씀(리뷰·[승인] 건너뜀). 러너가 그 기록을 커밋하자 가드가 main을 깨뜨려 #584가 두 번 `base_broken`.
- **변경**: `.githooks/reference-transaction`(대화 세션 안에서 `worktree/*` 커밋으로 main을 옮기면 거절, 판정은 `ticket_quick.detect_actor`의 프로세스 족보), pre-commit이 역할 id가 아닌 티켓 기록 행위자·캐릭터 이름 작성자·두뇌와 다른 대화 세션 작성자를 거절. 러너 착륙·바깥 에이전트·"직접 해" 커밋은 그대로.
- **한계**: 같은 사용자 권한이라 일부러 피하는 것은 못 막음 → engine-decides D6(대화 에이전트 자체 셸 권한).

## 2026-10-03 — [ui/map] 지도 파서 결정론적 정규식 루틴 고도화 (토큰 제로, center 라인, 쉼표 구분 마커) (#584, 위임 agy)

- **커밋**: `cdcfb7b` fix(map): discard out-of-range markers and test center array and invalid paths, `fba831d` feat(map): parse center line and comma-separated markers via deterministic regex
- **바뀐 파일**: `static/markdown-map.js`, `tests/test_map_block.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-03 — [ui/map] 모바일 동적 지도 고도화 v2 (다중 마커, 구글맵 길찾기 연동, 팝업 고도화, 모바일 전체화면) (#582, 위임 agy)

- **커밋**: `32718f0` fix(ui): align single-marker coordinates and clean up fullscreen esc listener, `8a006fa` feat(ui): enhance mobile dynamic map v2 with multi-marker, google maps link, and fullscreen, `d5f4065` feat(map): multi-marker, Google Maps popup link, fullscreen toggle
- **바뀐 파일**: `static/chat-features.css`, `static/markdown-map.js`, `tests/test_map_block.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-03 — [ui/map] Leaflet 기반 인앱 동적 지도 렌더러 지원 (마크다운 map 블록) (#581, 위임 agy)

- **커밋**: `d4f07f3` test(ui): verify script onerror path and fix mock in Leaflet fallback test, `19218b5` fix(ui): reinforce Leaflet SRI, load failure text fallback, and scrollWheelZoom defense, `fff1b6d` fix(ui): use safe typeof checks for map functions to support headless node test harnesses, `ab2efa3` fix(ui): prevent popup DOM XSS, add load timeout, and enforce OSM attribution, `b1f5785` feat(ui): integrate markdown-map.js and add test_map_block, `6522110` fix(ui): revert unrelated markdown.js edits and keep clean map hooks, `60460a6` feat(ui): Leaflet 기반 인앱 동적 지도 렌더러 지원 (마크다운 map 블록)
- **바뀐 파일**: `static/chat-features.css`, `static/index.html`, `static/markdown-map.js`, `static/markdown.js`, `tests/test_map_block.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-03 — [geo/fix] 페이지 로드 시 위치 동기화(geoEnabled) 실패 시 getClientContext 재조회 누락 버그 수정 (#579, 위임 agy)

- **커밋**: `55ad24c` chore(geo): drop hook cache from ticket 579 scope, `92dbe33` chore(ticket #579): changes the agent left uncommitted, `4804b74` fix(geo): retry GPS in getClientContext after a failed page-load fetch
- **바뀐 파일**: `static/app-device.js`
- 위임 병합 때 자동으로 쓴 줄(`tools/devlog_entry.py`). 이유와 결정은 티켓과 계획 문서에.

