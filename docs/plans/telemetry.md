# 로그 시스템(텔레메트리): 근거가 되는 데이터를 모으고 오래 쌓는다 (telemetry)

> 방향 (align/D, 2026-10-09): **개발 기반** — 오류 수정·경로 최적화·토큰과 응답 속도·기억 최적화를 데이터로 깎으려면, 양과 시간축 둘 다 충분한 수집이 먼저다. 개선 고리([improvement-layers.md](improvement-layers.md))의 근거(D2: 데이터만)가 여기서 나온다
> 상태: **active** (2026-10-09 수립, D1–D4 2026-10-09 운영자: 추천대로. tl/A 끝(#836), tl/B 끝(#837), tl/C 끝(#841), tl/D 일부 끝(#844), tl/E 끝(#845). 운영자: "근거 수집 도구가 중요… 데이터 양 뿐 아니라 시간축으로도 충분한 데이터를 쌓을 필요", "로그 시스템도 대형 피쳐로 별도 분리", "메시지 시스템하고의 연계도 신경써야")
> 흡수: 계획 없이 올라온 `metrics/A`(#826, 운영자 거절 10-08 23:49; 같은 크래시는 #831이 고침, `--latency`는 `tl/H`로)·`metrics/B`(#827, TTFT, 진행 중)는 이 계획의 `tl/D`다. 앞으로 지표 티켓은 `tl/*`로 연다.
> 관련: [improvement-layers.md](improvement-layers.md)(이 데이터를 쓰는 개선 고리) · [token-economy.md](token-economy.md)(토큰 대책 — 측정은 이 계획의 지표로) · `OPERATIONS.md` Logging(OBSLOG_v1, 현행 규격의 정본)

---

## 1. 지금 (2026-10-09 실측)

**한 줄기 기록**: `engine/logs/events.jsonl`(OBSLOG_v1). 메타데이터만 — 대화의 말은 남기지 않는다(`test_log_no_content`). 이 원칙은 그대로 간다.

**시간축이 짧다.** 10MB에서 회전하고 백업 5개까지 둔다(`obslog.MAX_BYTES`·`BACKUPS`). 하루 약 1MB라 50–60일이 지나면 가장 오래된 파일부터 덮어써 사라지고, 압축하지 않는다. 지금 남은 것은 OBSLOG가 생긴 2026-09-23부터 전부(16일). 날짜별 요약은 어디에도 쌓이지 않는다 — "지난달보다 느려졌나"를 물을 수 없다. (처음 쓸 때 "백업 1개, 7일"이라 적었다 — 파일 순서를 잘못 읽은 착오, 2026-10-09 바로잡음)

**소음이 보관 기간을 깎는다.** 최근 줄의 약 40%가 `proc.heartbeat`(5분마다, 두 프로세스)와 `http.summary`다.

**흩어진 저장소.**

| 무엇 | 어디 | 문제 |
|---|---|---|
| 이벤트 | `engine/logs/events.jsonl` | 50–60일 뒤 덮어씀(tl/B 전) |
| 턴 토큰 | 세션마다 `~/.pe/sessions/*/meta.json` (`tools/token_audit.py`가 읽음) | 이벤트 줄에 없음, 세션이 지워지면 사라짐 |
| 위임 토큰 | `~/.worktrees/chatbot/runs/usage.jsonl` (81줄) | 따로 논다 |
| 서버 표준 출력 | `logs/chatbot.log`, `chatbot-mcp.log`, `chatbot-doctor.log` | 사람용, 구조 없음 |
| 메시지 | 이벤트 우편함 `~/.pe/events/` (30일·10MB, 비공개 7일) — 쓸 때마다 `events.publish`로 이 로그에도 남음 | 우편함과 로그는 한 기록의 두 모습(OPERATIONS "Events, reactions and rooms") |

**네 영역에서 빠진 것.**

| 영역 | 있는 것 | 없는 것 |
|---|---|---|
| 오류 수정 | `err.fp` 묶음, `rid` 추적, 재시작·복구 기록, `main.check` | 기록 형식이 제각각인 곳(#831에서 읽기만 맞춤) |
| 경로 최적화 | `mcp.call`, `turn.loop_notice`, `context.inject`(주입 크기·층) | 턴 안 단계별 시간(대기·spawn·첫 바이트·도구), 에이전트 자체 도구 호출 수 |
| 토큰·응답 속도 | `turn.end.dur_s` | 첫 반응까지(TTFT, #827 진행 중), 턴별 입력/출력/캐시 토큰 |
| 기억 최적화 | 없음 | 회상(무엇을 몇 자 꺼냈나, 쓰였나)·저장 이벤트 0건 |
| 메시지 | `events.publish`/`deliver`, `react.*`, `room.*` | 발송→전달 지연, 미뤄짐 비율(10-08: `react.defer` 1132 대 `react.turn` 170)의 추세, 알림이 읽혔나 |

## 2. 원칙

1. **한 기록.** 새 지표도 `events.jsonl`의 이벤트로 남긴다. 우편함·세션 파일·위임 기록에 있는 수치는 이벤트로도 남겨, 읽는 쪽은 한 곳만 본다.
2. **메타데이터만.** 대화의 말, 기억의 내용, 비공개 채널의 제목은 남기지 않는다(현행 그대로).
3. **엔진이 잰다.** 지표는 엔진이 시계와 수로 잰다. 모델에게 묻지 않는다([engine-decides.md](engine-decides.md)). 제공자마다 다른 것(토큰 필드 이름 등)은 어댑터가 공통 형식으로 넘긴다 — 공통 코드에 제공자 이름 없음.
4. **두 겹 보관.** 원본은 넉넉히, 요약은 영구히(§4).
5. **근거로 쓸 수 있게.** 지표 구간은 티켓 근거로 인용할 수 있는 참조를 갖는다(`metric:<이름>@<시작>..<끝>`, improvement-layers D2).

## 3. 기능 패키지 `engine/telemetry/`

| 모듈 | 무엇 | 지금 |
|---|---|---|
| `obslog.py` | 쓰기(형식·가림·폭주 방지·회전) | `engine/obslog.py` → 이동 |
| `logdigest.py` | 창(window) 요약·findings·조회 CLI | `engine/logdigest.py` → 이동 |
| `archive.py` | 회전된 원본을 압축 보관, 기한·용량 정리 | 새로 |
| `rollup.py` | 날짜별 요약 만들기·읽기, 추세 비교 | 새로 |

호출부는 `from telemetry import obslog`처럼 바꾼다(`providers/` 선례). `chatbot-ctl.sh logs`, `/api/service-log`, 로그 탭은 그대로 동작해야 한다. 새 폴더는 `protected_paths.json`·`tests/test_code_layout.py` `CODE_DIRS`에 같은 변경으로.

improvement-layers §3의 `engine/health/`는 이 패키지를 **읽기만** 한다: 사건 묶기·알림·분석은 `health`, 수집·보관·요약·추세는 `telemetry`.

## 4. 보관 (시간축)

| 겹 | 무엇 | 기한 | 크기(추정) |
|---|---|---|---|
| 원본 | `events.jsonl` + 백업 5개, 밀려난 파일은 `logs/archive/events-<마지막 줄 시각>.jsonl.gz` | 90일(D1) | 하루 약 1MB → gzip 약 10–15% |
| 요약 | `metrics/YYYY-MM-DD.json`: 지표별 count·합·p50·p95·max, 차원별(제공자·모델·캐릭터·모드·경로) | 영구 | 하루 수십 KB |

- 위치는 `host_config.LOG_DIR` 아래(LOG_PATH_v1: 경로는 한 곳에서만) — 2026-10-09부터 개발판도 사용자 데이터 `~/.pe/logs`(운영자: "~/.pe/logs"). 저장소를 새로 받아도 요약이 남는다.
- 요약은 하루가 끝날 때(또는 다음 기동 때 빠진 날을) 원본에서 만든다. 원본이 기한으로 지워져도 요약은 남는다.
- 첫 요약은 남아 있는 원본(2026-09-23부터) + 세션 `meta.json`의 토큰으로 거꾸로 채운다(backfill).
- 소음 줄이기: `proc.heartbeat`는 요약에 들어가니 원본에서는 값이 바뀔 때만, 또는 간격을 늘린다(D3).

## 5. 수집 (무엇을 더 재나)

| 영역 | 이벤트 / 필드 | 묻는 질문 |
|---|---|---|
| 턴 | `turn.end`에 `ttft_ms`(#827), `tok_in`·`tok_out`·`tok_cache_read`·`tok_cache_write`, `tool_calls`, `mcp_calls`, `ctx_chars`, `phases`(대기·spawn·첫 바이트·도구·마무리 ms) | 어느 모델·캐릭터·모드에서 느려지나, 어디서 시간이 새나, 토큰은 어디로 가나 |
| 기억 | `memory.recall`(출처·항목 수·주입 글자 수·hash), `memory.write`(종류·글자 수), 턴 끝에 회상한 항목이 응답에 쓰였는지(엔진이 판정할 수 있는 범위만) | 무엇을 꺼내 얼마나 쓰나, 과주입은 없나 |
| 경로 | `turn.phase`(단계 경계), 도구 호출 묶음 요약 | 반복·우회·불필요한 읽기 |
| 오류 | 모든 `err`는 dict(`{type,msg,where,fp}`) — 쓰는 쪽에서 맞춘다(#831은 읽는 쪽 응급처치) | 같은 오류의 빈도 추세 |
| 위임 | `runs/usage.jsonl`의 각 줄을 `deleg.usage` 이벤트로도 | 위임 한 건의 비용·시간 |
| 메시지 | `events.deliver`에 `lag_ms`(발송→전달), `react.*` 결과, 알림 읽힘(화면이 열어 본 시각) | 알림이 제때 닿나, 먼저 말 걸기가 왜 미뤄지나 |

## 6. 메시지 시스템과의 연계

- **한 기록, 두 모습**(현행 유지): 우편함에 쓰는 모든 것은 로그에도 남는다. 새 지표(`lag_ms`, 읽힘)도 같은 길.
- **텔레메트리 → 메시지**: 개선 고리의 사건(improvement-layers il/D)은 `events.publish("host.incident", to=[기본 캐릭터])`로 알린다. 전달·먼저 말 걸기·조용한 시간·시간당 한도는 우편함과 `event_react`의 것을 그대로 쓴다 — 알림 경로를 새로 만들지 않는다.
- **메시지 → 텔레메트리**: 우편함의 보관 기한(30일)이 지나도 메시지 지표는 날짜별 요약에 남는다.
- **비공개**: 비공개 채널의 이벤트는 지금처럼 제목 없이, 요약에서도 개수만.

## 7. 분석 (요약 위에서)

- `logdigest`의 창 요약은 그대로, 여기에 **추세**를 더한다: 이번 주 대 지난주, 지표별 p95·실패율·토큰 중앙값. 나빠진 지표는 finding(`trend_regression`)이 된다.
- finding은 `metric:` 참조를 달고, 개선 고리의 사건이 되어 티켓 근거로 이어진다.

## 8. 단계

| id | 무엇 | 끝의 모습 |
|---|---|---|
| `tl/A` | `engine/telemetry/` 패키지로 `obslog`·`logdigest` 이동 + 루트 모듈 ratchet(improvement-layers il/C와 같은 장치) — **끝 (#836)**: 루트 모듈 상한 `tests/test_code_layout.py` `TOP_LEVEL_MAX`, 가드들이 각자 들고 있던 코드 폴더 목록을 `tests/_paths.py` `CODE_DIRS` 하나로 | 호출부 전부 바뀜, 로그 탭·CLI 동작 그대로 |
| `tl/B` | 원본 보관: 회전에서 밀려나는 파일을 gzip 보관, 기한·용량 정리 — **끝 (#837)**: `telemetry/archive.py`, 날짜별 파일 대신 회전 단위 파일(이름에 마지막 줄 시각), 날짜 구분은 `tl/C` 요약이 맡는다 | 90일(D1) 원본이 남는다 |
| `tl/C` | 날짜별 요약 + 기존 원본(09-23부터)·세션 토큰 backfill — **끝 (#841)**: `telemetry/rollup.py`, 한 시간마다 빠진 날을 채움(`log.rollup`), 턴의 캐릭터·모드는 세션의 `context.inject`에서 이어 붙임. 토큰 backfill은 `tl/D`로(턴 기록에 토큰이 생긴 뒤) | `metrics/`에 하루 한 파일 |
| `tl/D` | 턴 기록 풍부화: TTFT(#827 흡수), 토큰, 도구 수, 단계 시간 — 어댑터 공통 형식 — **토큰·도구·읽은 양 끝 (#844)**: `turn.end`에 `tool_calls`·`read_kb`·`tok_in/out/think/cache_read/total`(어댑터의 `normalize_usage` 합), 요약에 합·백분위, 그 전 날은 세션 사용량으로 채움(남은 세션만 — 하한). 단계 시간 **끝 (#847)**: `prep_ms`(메시지를 받고 에이전트에 넘기기까지: 지시문·기동), `spawn_ms`(이 턴에 에이전트를 띄웠을 때), `first_tool_ms`. 대기열에서 기다린 시간은 남음(대기열 항목에 시각이 없다) | `turn.end`만으로 속도·토큰 질문에 답한다 |
| `tl/E` | 기억 이벤트 — **끝 (#845)**: 도구 기록이 인자의 말을 300자까지 남기던 것(기억 문장·검색어·캐릭터 간 대화·위임 지시)을 막고 메타데이터만(`obslog.arg_meta`, 결과는 개수 `result_meta`). 요약(VERSION 3)에 기억 도구 호출·추가·검색 적중·주입된 기억 층 크기 | 회상·저장이 지표로 |
| `tl/F` | 오류 형식 통일(쓰는 쪽), 위임 사용량 이벤트 — **끝 (#850)**: `obslog.event`가 글자 `err`를 `{msg, type, where, fp}`로(숫자를 뺀 지문으로 묶임), 러너 사용량은 `deleg.usage`(필드명 `tok_*` — 이름에 token이 있으면 가려진다), 요약 VERSION 6에 제공자·역할별 위임 비용 | `err`는 언제나 dict |
| `tl/G` | 메시지 지표: 전달 지연, 먼저 말 걸기 결과, 읽힘 — **끝 (#848)**: `events.deliver`에 `lag_s`(가장 오래 기다린 이벤트의 대기), 요약 VERSION 5에 전달 지연 분포·작업 카드 결과 열람 수(`/api/delegations/:n/seen`). 먼저 말 걸기 결과는 tl/C부터 | 알림 경로의 건강을 숫자로 |
| `tl/H` | 추세 분석 + `metric:` 참조 | 나빠진 지표가 finding으로, 티켓 근거로 |

순서: A → B → C를 먼저(시간축은 지금부터 쌓아야 늘어난다). D·E·F·G는 그 뒤 아무 순서로, H는 C 뒤 2주쯤 쌓인 다음.

## 9. 결정 (운영자)

| id | 질문 | 추천 |
|---|---|---|
| D1 | 원본 보관 기한 | **결정**: 90일(압축, 수백 MB 이내). 요약은 영구 |
| D2 | 요약의 차원 | **결정**: 제공자·모델·캐릭터·모드(업무/사적)·HTTP 경로. 세션 단위는 원본에만 |
| D3 | 생존 신호 소음 | **결정**: 5분 간격 유지하되 값이 그대로면 원본에 쓰지 않고 요약에만 센다 |
| D4 | #827(TTFT, agy 위임 진행 중) | **결정**: 그대로 끝내게 두고 `tl/D`의 첫 조각으로 받는다. 필드 이름만 이 계획(`ttft_ms`)에 맞춘다 |
