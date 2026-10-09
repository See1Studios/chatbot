# History

작업 기록이다. 새 것이 위, 눈에 띄는 변경마다 한 블록(무엇을, 왜, 재시작이 필요한지). 지난 날짜는
`docs/history/<날짜>.md`로 넘어간다(`engine/tools/history_entry.py`가 위임 작업의 줄을 쓰고, 크기가 넘치면 옮긴다).
릴리스는 아직 없다(`engine/VERSION` 0.0.0-dev, 태그 없음). 릴리스 때 사용자용 `CHANGELOG.md`를 커밋에서 만든다
(`RULES.md` Release). 2026-10-08까지 이 파일은 `DEVLOG.md`, 릴리스 메모는 `CHANGELOG.md`였다.
2026-10-07 기록은 하루 예산을 넘어 [docs/history/2026-10-07.md](docs/history/2026-10-07.md)로 회전했습니다.
2026-10-08 기록은 하루 예산을 넘어 [docs/history/2026-10-08.md](docs/history/2026-10-08.md)로 회전했습니다.

## 2026-10-09 — 오류 형식 통일, 위임 비용을 로그로 (telemetry tl/F, #850)

- **운영자**: "하던 거 마저 해"
- **바뀐 것**: 오류를 글자로 넘기면 `obslog.event`가 `{msg, type: "text", where, fp}`로 바꿔 적는다 — 숫자를 뺀 지문이라 같은 실패가 한 묶음이 되고, 로그 요약이 처음으로 `git.commit_failed` 같은 것을 셀 수 있다. 위임 러너의 사용량 한 줄마다 `deleg.usage` 이벤트(필드명 `tok_*`: 이름에 token이 들어가면 비밀 값으로 가려진다), 날짜별 요약 VERSION 6에 제공자·역할별 위임 비용(호출·초·티켓 수·토큰).
- **재시작**: 필요 (`obslog`).

## 2026-10-09 — 메시지 전달 지연을 숫자로 (telemetry tl/G, #848)

- **운영자**: "이어서 진행해"
- **바뀐 것**: 우편함 전달 기록(`events.deliver`)에 `lag_s` — 전달된 것 중 가장 오래 기다린 이벤트가 발송부터 몇 초 기다렸나. 날짜별 요약 VERSION 5에 전달 지연 분포와 작업 카드 결과 열람 수. 먼저 말 걸기 결과·미룬 이유는 tl/C부터 있다.
- **재시작**: 필요.

## 2026-10-09 — 턴 안의 단계별 시간 (telemetry tl/D, #847)

- **운영자**: "이어서 진행해"
- **바뀐 것**: `turn.end`에 `prep_ms`(메시지를 받고 에이전트에 넘기기까지 — 지시문 조립·에이전트 기동), `spawn_ms`(이 턴에 새 에이전트를 띄웠을 때만), `first_tool_ms`(첫 도구 호출까지). `ttft_ms`·`dur_s`는 넘긴 뒤부터 잰다. 날짜별 요약 VERSION 4가 그룹별 백분위를 담는다. 대기열 대기 시간은 남음.
- **재시작**: 필요.

## 2026-10-09 — [ui/team] 새 역할 추가 모달 레이아웃 3단 구조화 및 UX 정리 (#846, 위임 agy)

- **커밋**: `6767529` feat(team): improve add role modal layout, validation and tool chips
- **바뀐 파일**: `static/app-team.js`, `static/i18n/en.json`, `static/i18n/ko.json`, `tests/test_team_roles.py`
- 위임 병합 때 자동으로 쓴 줄(`tools/history_entry.py`). 이유와 결정은 티켓과 계획 문서에.

## 2026-10-09 — 도구 기록에서 '말'을 빼고, 기억을 지표로 (telemetry tl/E, #845)

- **운영자**: "재시작하고 이어서 가" (tl/E)
- **발견**: `mcp.call`이 도구 인자를 300자까지 그대로 남겼다 — 기억에 저장한 문장, 기억 검색어, 캐릭터 간 대화(`dialog` text), 위임 지시(`delegate` tasks), 티켓 메모. "로그는 메타데이터만" 원칙이 도구 인자엔 없었다.
- **바뀐 것**: 도구 인자는 `obslog.arg_meta`로 — 식별자·종류(`action`, `id`, `path` 등)와 숫자, 명령은 프로그램 이름만, 나머지 글자는 길이만. 결과는 개수(`result_meta`: 검색 적중 수, `added` 같은 상태어). 날짜별 요약(VERSION 3)에 기억 항목: 도구 호출(행위별), 추가 수, 검색 적중, 지시문에 주입된 기억 층 크기.
- **남은 것**: 이미 쌓인 로그(09-23~10-09)에는 옛 방식의 인자 글자가 있다 — 지울지는 운영자 결정.
- **재시작**: 필요 (도구 서버).

## 2026-10-09 — 턴 기록에 토큰·도구 호출·읽은 양 (telemetry tl/D, #844)

- **운영자**: "계속" (tl/D)
- **바뀐 것**: `turn.end`에 `tool_calls`·`read_kb`(루프 가드가 세던 값)와 `tok_in/out/think/cache_read/total`(어댑터가 이미 공통 형식으로 기록에 붙이던 사용량의 합). 날짜별 요약(VERSION 2)이 그룹별 합·백분위를 담고, 이 필드가 없던 지난 날은 세션 파일의 사용량으로 채운다(남은 세션만이라 하한, `tokens_from`). 옛 형식 요약은 원본이 있는 동안 다시 만든다.
- **처음 채운 결과**: 하루 토큰 10-01 8,690만 → 10-08 1,140만.
- **재시작**: 필요 (`session.py`).

## 2026-10-09 — 로그를 `~/.pe/logs`로, 로그 근거가 실제로 통하게 (#842)

- **운영자**: "로그 위치는 예전 경로가 낫지 않나?" → "~/.pe/logs (권장)"
- **원인**: 티켓의 로그 근거(`log:fp`·`log:rid`)는 데이터 폴더 옆 `logs/`를 봤다(데이터가 저장소 안에 있던 때의 배치). 이 호스트에선 `~/logs`라 한 번도 통하지 않았고, 에이전트들은 근거 칸을 빈 표시로 채웠다. 로그 자체는 10-08 코드 이동 때 `engine/logs/`(코드 폴더 안)로 따라갔다.
- **바뀐 것**: `host_config.LOG_DIR` 기본값이 `DATA/logs`(개발판·배포판 같음). ctl의 fallback과 pid 파일 위치도 같이(`ctl_proc.py`는 ctl이 넘기는 LOG_DIR에서 `chatbot.pid`를 읽음 — 직접 조립하던 곳). 로그 근거는 `<data>/logs`의 live·백업·압축 보관본에서 찾는다.
- **재시작**: 필요 — 옛 코드로 멈추고, 로그·보관본·요약·pid를 옮긴 뒤 새 코드로 시작.

## 2026-10-09 — 날짜별 요약을 영구 보관 (telemetry tl/C, #841)

- **운영자**: "그래" (tl/C 진행)
- **바뀐 것**: `engine/telemetry/rollup.py` — 끝난 날마다 `logs/metrics/YYYY-MM-DD.json` 하나(약 18KB): 제공자·모델·모드·캐릭터별 턴(결과, 소요·TTFT 백분위), HTTP 경로, 오류 수와 지문 상위, 프로세스 시작·복구, MCP 호출, 주입 지시문 크기, 메시지(유형별 발송·전달·먼저 말 걸기와 미뤄진 이유), 세션 교체, main 감시. 서버 백그라운드가 한 시간마다 빠진 날을 채운다(`log.rollup`). 손으로는 `rollup.py build` / `rollup.py show --days 7`.
- **처음 채운 결과에서 보인 것**: 채팅 서버가 하루 5–45번 다시 떴고(09-23부터 16일), 거의 매번 복구(repair)였다(10-08: 29번 — 화면 응급 버튼 12·에이전트 16). 먼저 말 걸기는 09-30부터 하루 1,600–2,200번 미뤄짐(대부분 조용한 시간).
- **재시작**: 필요 (`obslog`).

## 2026-10-09 — 엔진 티켓을 작업 폴더 밖 `<data>/dev/tickets/`로 (improvement-layers il/B, #840)

- **운영자**: D1 "A" · "쓰레기들을 남김없이 걷어내줘"
- **바뀐 것**: `tickets.tickets_dir()`가 `<data>/dev/tickets/`를 가리킨다. 옛 `workspace/skill-observations/tickets/`가 있고 새 곳이 비었으면 첫 사용 때 한 번 옮긴다(이름 바꾸기 — 잡힌 잠금도 그대로). 보호 경로·러너(`TICKETS_REL`)·기록 도구·커밋 훅·리허설(`SKIP`)·작업 폴더 구성표·개발 `PROJECT.md`가 따라감. 열린 관찰은 자동 티켓으로 만들지 않고 운영자에게 목록으로(D2).
- **재시작**: 필요.

## 2026-10-09 — 낡은 개발 지침 `SELF-MODIFY.md` 정리 (improvement-layers il/A3, #839)

- **운영자**: "나 시간 많아 계속 하자"
- **바뀐 것**: `templates/dev-workspace/SELF-MODIFY.md` 삭제. 규칙 대부분은 이미 `DEV-CHARTER.md`(라이브 턴 재시작 금지)·`roles/dev/PROCEDURE.md`(새로고침/⚡소생)·`OPERATIONS.md`(healthz만으로 판단 금지)·`PROJECT.md`(guard·probe)에 있었고, 거기에만 있던 셋(포트 변경·일괄 삭제는 승인, 연결이 죽으면 멈추고 ⚡소생 요청, RLock 유지)은 `roles/dev/PROCEDURE.md`로. 낡은 경로·"Hub FAB"·observation-log 줄은 버림. 지시문 탭 목록·보호 경로·작업 폴더 구성표에서도 뺌.
- **재시작**: 필요 (`workspace_status`).

## 2026-10-09 — 관찰·후보 흐름을 걷어내고 티켓 근거는 데이터만 (improvement-layers il/A1·A2, #838)

- **운영자**: "파편화되지 않도록 최대한 기존 구조 잘 분석해서 쓰레기들을 남김없이 걷어내줘" · D2 "철저하게 데이터 기반으로. 내가 개입하는 건 그냥 요청사항"
- **걷어냄**: `observations.py`, `observation_signals.json`(한국어 정규식), 턴 끝 후보 기록(`evolution.on_turn_end`·`record_candidate`, 세션의 회전·중단 표시), 서버의 매시간 후보 수집(`_host_signal_loop`, `logdigest.host_candidates`·`--to-candidates`), `observation` MCP 도구와 별칭, `/api/observations*`, 상태 탭의 관찰 목록·이력·검토 칸과 i18n 38키, `/review` 명령, 매 턴 지시문의 `[Self-improvement status]` 줄(작업 번들 해시 바뀜 → 살아 있는 세션은 한 번 다시 주입), 관찰 테스트 7개 모듈, 개발 지침의 "observation을 남겨라" 줄들.
- **바뀐 것**: 티켓 쓰기 가드의 신호는 후보 대신 `guard.unticketed_write` 로그 이벤트. 티켓 `evidence`는 데이터만(`event:`·`log:fp:`·`log:rid:`), 운영자의 말은 `request` 칸(`ticket-quick start --request "<말>"`). 둘 중 하나 필수, 빈 `manual` 표시는 없음.
- **데이터**: `skill-observations/`의 후보·검토 파일과 관찰 기록은 아직 있음 — il/B에서 열린 관찰을 티켓으로 옮긴 뒤 백업하고 지운다.
- **재시작**: 필요.

## 2026-10-09 — 로그 원본을 덮어쓰지 않고 압축 보관 90일 (telemetry tl/B, #837)

- **운영자**: "계속합시다" (D1 원본 90일 추천대로)
- **바뀐 것**: 회전에서 `.5` 뒤로 밀려나는 로그 파일을 `logs/archive/`로 옮기고(이름 바꾸기라 쓰는 쪽을 막지 않음), 오래 도는 프로세스의 백그라운드 스레드가 한 시간에 한 번 gzip 압축·90일 지난 것과 1GB 넘는 것 정리(`log.archive`). `logdigest`는 긴 기간이면 보관본도 읽는다. 계획의 "7일뿐" 서술은 착오여서 바로잡음(실제 50–60일 뒤 덮어씀, 09-23부터 전부 남아 있음).
- **집행**: `test_telemetry_archive`.
- **재시작**: 필요 (`obslog`).

## 2026-10-09 — 로그 시스템을 기능 패키지로: `engine/telemetry/` (telemetry tl/A, #836)

- **운영자**: "로그 시스템도 대형 피쳐로 별도 분리해서 개발" · "feature 별로 모듈이나 패키지를 만들어서 정리" · D1–D4 "추천대로"
- **바뀐 것**: `obslog.py`·`logdigest.py`를 `engine/telemetry/`로(이름 유지, `from telemetry import obslog`). `chatbot-ctl.sh`(emit·logs), 보호 경로·Tier 3 항목, 가드가 따라감. 엔진 루트 모듈 수 상한(`test_code_layout` `TOP_LEVEL_MAX` 69, 늘릴 수 없음). 가드 7곳이 따로 들고 있던 코드 폴더 목록을 `tests/_paths.py` `CODE_DIRS` 하나로.
- **재시작**: 필요 (서버가 옮긴 모듈을 다시 읽어야 함). `chatbot-ctl.sh logs`는 바로 새 경로.

