# 개선의 두 계층: 엔진 이상 징후와 스킬(스크립트 포함) — skill-observations 정리 (improvement-layers)

> 방향 (align/D, 2026-10-08): **개발판 전용 + 핵심** — 엔진 쪽은 개발판이 스스로 아픈 곳을 알리고 일감으로 만드는 고리(개발판 전용). 스킬 쪽은 캐릭터가 한 일을 기억해 다시 쓰는 개인화 고리(배포판 포함, `VISION.md` "Agent self-evolution: skills, memories, instructions with user approval and undo")
> 상태: **active** (2026-10-08 수립, D1 2026-10-08 운영자: A, D2 2026-10-09 운영자: 데이터만 근거. 운영자: "로그에서 이상징후가 보이면 원인 분석을 하고 사용자에게 notify 한 다음 일감화해서 개선하는 구조", "코어 개발과 도구 스크립트 개발, 스킬화가 모두 다른 계층", "쓰레기들을 남김없이 걷어내줘", "feature 별로 모듈이나 패키지를 만들어서 정리")
> 대체: [archive/2026/recursive-self-evolution.md](archive/2026/recursive-self-evolution.md)의 관찰 쪽(§4.6 observe → record → refer → act). 티켓·보호 경로·가드(코어)는 그대로 쓴다.
> 관련: [engine-decides.md](engine-decides.md)(엔진이 정한다) · [multi-agent-worktree-delegation.md](multi-agent-worktree-delegation.md)(위임) · [edition-boundary.md](edition-boundary.md)(개발판/배포판) · [user-data-separation.md](user-data-separation.md)(데이터 위치)

---

## 1. 왜: 한 그릇에 세 계층이 섞였다 (2026-10-08 실측)

`~/.pe/workspace/skill-observations/` 하나에 성격이 다른 것이 다 들어 있다.

| 들어 있는 것 | 실제 계층 | 실측 |
|---|---|---|
| `tickets/` | 엔진 개발 | 832건 |
| `observation-log/` | 엔진 개발(agy 모델 목록, 쿼터, 웹 도구 형식, git index.lock …) | 33건, 열린 것 약 20건 |
| `candidates.jsonl`의 서버 로그 신호(`host:*`) | 엔진 개발 | 62건+ |
| `candidates.jsonl`의 대화 신호(`rotation` 223, `correction` 93, `stopped` 17 …) | 원래 스킬 재료 | 합 522건 |
| `candidates.jsonl`의 `manual` | 어디에도 속하지 않음: 티켓 근거 칸을 채우려는 빈 표시(`ticket_quick._ensure_candidate_evidence`) | 327건 |
| `checkpoints.log`, `log.md.migrated` | 옛 흔적, 읽는 코드 없음 | — |

결과:

- 자동 신호 522건 중 티켓 근거가 된 것은 3건(#531, #533, #748). 후보를 읽고 무엇을 제안하는 주체가 없다.
- 마지막 검토 2026-09-25, 결론은 "정규식 오탐·노이즈, 티켓 불필요". 그 뒤로 아무도 보지 않는다.
- 그런데도 매 턴 에이전트 지시문에 `[Self-improvement status] N open observations · N unreviewed candidates`가 들어간다(`instructions.py`) — 매 턴 토큰, 쓸모 없음.
- `correction` 신호는 한국어 정규식(`observation_signals.json`: "아니", "왜 안", "버그" …)으로 잡는다 — 언어에 따라 결과가 달라지면 안 된다는 원칙 위반.
- 서버의 매시간 후보 수집(`logdigest.host_candidates`)은 10-08 11:32부터 매시간 실패하고 있었고 아무도 몰랐다(#831에서 고침).
- 티켓의 "근거 필수" 규칙은 327번 빈 표시로 채워졌다 — 규칙이 형식만 남았다.
- 코드는 기능 하나가 `evolution.py`·`observations.py`·`logdigest.py`·`instructions.py`·`workspace_status.py`·`mcp_core.py`·`session.py`·`server.py`·`static/app-evolution.js`에 흩어져 있다. `engine/` 바로 아래 모듈 71개가 평평하게 놓인 구조가 이렇게 만든다.

## 2. 두 계층

| | 엔진 (코어 개발) | 스킬 (에이전트의 능력) |
|---|---|---|
| 바꾸는 것 | `engine/` 코드 | 지침·절차(`SKILL.md`) + 그 일을 위한 스크립트 + 언제 쓰는지 |
| 위치 | 저장소 | 사용자 작업 폴더(`<workspace>/.agents/skills/<이름>/`) |
| 빌드 | 개발판만 | 배포판 포함 |
| 신호 | 서버 로그 이상 징후(`logdigest` findings), main 감시(`main.check`), 운영자 요청 | 같은 일을 다시 한 것, 운영자의 명시적 동작(다시 생성·중단·고쳐 쓰기) — 말의 내용을 단어로 판정하지 않는다 |
| 흐름 | 징후 → 사건 → 원인 분석 → 알림 → 일감(티켓) → 위임 → 승인 병합 → 해결 확인 | 작업 중 스크립트 작성 → "스킬로 남길까요" 제안 → 운영자 승인 → 다음엔 스킬 목록에서 찾아 재사용 |
| 기록 | 사건 기록 + 엔진 티켓 (작업 폴더 밖, 개발판 데이터) | 스킬 폴더 자체 |
| 승인 | 티켓 → 가드 → 검토 → 운영자 병합 승인 | 운영자 승인 + 되돌리기 |

"도구 스크립트"는 별도 계층이 아니라 스킬의 일부다(운영자 2026-10-08: "엄밀히 말해 스킬에 포함").

## 3. 코드는 기능 패키지로 짓는다

이 계획의 새 코드는 `engine/` 바로 아래 모듈로 늘리지 않는다.

- `engine/health/`: 엔진 이상 징후 고리. `tools/main_watch.py`를 이리로 옮기고 사건 기록·알림·분석을 더한다. 수집·보관·요약(`obslog`·`logdigest`)은 [telemetry.md](telemetry.md)의 `engine/telemetry/`가 맡고, `health`는 읽기만 한다.
- `engine/skills/`: 스킬 목록(`instructions.skill_index`, `mcp_parity` skill 도구가 읽는 부분), 스크립트 목록, 저장 제안.
- 걷어 낼 관찰 코드는 옮기지 않고 지운다.

`providers/` 시범(FOLDERS_PROVIDERS_v1, #123)을 따른다: 모듈 이름 유지, 호출부는 `from health import logdigest`처럼 바꾼다. 새 폴더는 `protected_paths.json`과 `tests/test_code_layout.py`의 `CODE_DIRS`에 같은 변경으로 넣는다.

막는 장치: `engine/` 바로 아래 `*.py` 개수가 늘지 못하는 ratchet(`tests/test_ratchets.py`). 새 기능은 패키지로만 들어온다. 나머지 71개 모듈의 재배치는 모듈 지도와 함께 별도 계획(`feature-packages`)으로 올린다 — 이 계획은 그 첫 사례다.

## 4. 걷어 낼 것 / 옮길 것 / 남길 것 (전수)

### 4.1 걷어 낸다

| 대상 | 위치 |
|---|---|
| 턴 끝 후보 기록 | `evolution.on_turn_end`, `record_candidate`, `SIGNALS_NAME`·`CANDIDATES_NAME`; `session.py`의 `_observation_root`·호출부 |
| 한국어 정규식 판정 | `engine/observation_signals.json` (+ `protected_paths.json` 항목) |
| 서버 매시간 후보 수집 | `logdigest.host_candidates`·`HOST_SIGNAL_*`·`OBS_ROOT`; `server.py` `_host_signal_tick`·`_host_signal_loop` |
| 관찰 기록 | `observations.py` 전체(scan/resolve/review/mark_reviewed/unreviewed_candidates), `evolution.add_observation`·`OBSERVATION_LOG` |
| 관찰 도구 | `mcp_core.py`의 `observation` 도구 |
| 지시문 상태 줄 | `instructions.py`의 `[Self-improvement status]`, `OBS_DIR`·`LAST_REVIEW_FILE` |
| 상태 탭 요약 | `workspace_status._observation_summary`·`_observation_overview` |
| 관찰 API | `/api/observations*` (`server.py` 라우트 표 포함) |
| 화면 | `static/app-evolution.js`의 observation manager(관찰 목록·이력·검토 칸), 관련 i18n 키 |
| 빈 근거 표시 | `ticket_quick._ensure_candidate_evidence`, 티켓 근거의 `candidate:` 형식(`tickets.verify_evidence`) |
| 옛 흔적 | `candidates.jsonl`, `last-review-*.txt`, `review-history.log`, `checkpoints.log`, `log.md.migrated`; 빈 `~/.pe/tickets.db`(0바이트, 2026-10-04, 엔진 코드가 쓰지 않음 — `test_handoff_drill`의 목록에서도 뺀다) |
| 테스트 | `test_observations`·`test_observation`·`test_observation_api`·`test_observation_history`·`test_observation_status`·`test_observation_ui`·`test_turn_observation`, 그 밖의 테스트 안 관찰 사례 |
| 개발 지침의 옛 줄 | `templates/dev-workspace/SELF-MODIFY.md`("observation-log 한 줄", 루트 경로 `server.py` 등) → 살아 있는 규칙만 `DEV-CHARTER.md`로 옮기고 파일 삭제 |

### 4.2 옮긴다

| 대상 | 어디로 | 방법 |
|---|---|---|
| 엔진 티켓 `skill-observations/tickets/` | 작업 폴더 밖 개발판 데이터(`host_config`가 정하는 한 곳, 예: `<data>/dev/tickets/`) | `migrate_user_data` 이전 단계 + `tickets.tickets_dir` 한 곳만 바꿈. `protected_paths.json`, `worktree_runner.TICKETS_REL`, `history_entry.TICKET_FILES`, `.githooks/check_staged.RECORDS`·`TICKET_RECORD`, `handoff_drill.SKIP`, `templates/workspace-manifest.json`, `templates/dev-workspace/PROJECT.md`가 같은 변경으로 따라간다 |
| 열린 관찰 약 20건 | 엔진 티켓(`proposed`) | 한 건씩 제목·본문을 티켓으로, 근거는 관찰 파일 이름. 옮긴 뒤 `observation-log/`는 보관 압축 후 삭제 |
| 떠 있는 스크립트 `<workspace>/tools/*.py` 4개 | 맞는 스킬의 `scripts/` | 음력 변환·기억 저장·기억 회상·토큰 감사 — 스킬이 없으면 스킬을 만든다 |
| main 감시 | `engine/health/` | §3 (로그 요약은 `engine/telemetry/`, telemetry `tl/A`) |

### 4.3 남긴다

- 티켓·작업 잠금(lease)·보호 경로·가드·위임(코어) — 이름에 "evolution"이 붙어 있어도 실제로는 엔진 개발 관리 장치다.
- `unticketed_write` 가드(라이브 세션이 티켓 없이 고치면 턴을 멈춤) — 신호 기록만 뺀다.
- `logdigest` findings, `main.check`, 이벤트 우편함(`events.py`), 먼저 말 걸기(`event_react.py`).

### 4.4 티켓 근거 규칙

빈 표시를 없애면 근거 규칙을 다시 정해야 한다 — D2로 정했다: 근거는 데이터만, 운영자의 말은 요청이다.

## 5. 단계 (각 단계 = 티켓 하나 이상, 기능 패키지로)

| id | 무엇 | 끝의 모습 |
|---|---|---|
| `il/A` | 걷어내기: §4.1 전부, 근거 규칙(D2) | 관찰·후보 코드 0, 지시문 상태 줄 0, 테스트 녹색 |
| `il/B` | 티켓 이전: §4.2 첫 줄 + 열린 관찰 → 티켓 | `skill-observations/`에 엔진 것 0 |
| `il/C` | `engine/health/` 패키지 + ratchet(루트 모듈 수 불어남 금지 — telemetry `tl/A`와 같은 장치, 먼저 하는 쪽이 건다) | main 감시가 패키지 안 |
| `il/D` | 사건 기록: findings를 사건으로 묶고 새로 생김/나빠짐/해결을 엔진이 판정 | 같은 징후는 한 사건, 해결되면 닫힘 |
| `il/E` | 알림 + 버튼: 사건 → 이벤트(`host.incident`) → PD가 먼저 말 걸기, [일감으로]/[무시] | 버튼 하나로 근거(fp/rid/sha) 달린 티켓 |
| `il/F` | 원인 분석: 사건 근거 묶음을 분석 두뇌에 맡김(읽기 전용, 결론마다 근거) | 알림에 원인 가설과 근거 |
| `il/G` | 스킬에 스크립트: `scripts/`, 목록에 스크립트 표시, `tools/` 4개 이전 | 에이전트가 목록에서 스크립트를 찾아 씀 |
| `il/H` | 스크립트 저장 제안: 작업 중 쓴 스크립트를 스킬로 남길지 묻기 | 운영자 승인 → 스킬에 저장 |

순서: A → B → C를 먼저. D(사건)는 telemetry `tl/C`(날짜별 요약) 뒤 — 사건의 근거가 지표 구간이다. D → E를 끝내 며칠 돌려 보고(알림이 쓸모 있는지, 시끄럽지 않은지), F를 붙인다. G·H는 A 뒤 아무 때나.

## 6. 결정 (운영자)

| id | 질문 | 추천 |
|---|---|---|
| D1 | 엔진 티켓의 새 위치 | **결정 A (2026-10-08)**: `<data>/dev/tickets/` — 개발판 데이터, 작업 폴더 밖. 작업 폴더는 채팅 에이전트에게 `--add-dir`로 열리고 배포판에선 사용자의 것이다. 버린 안: 저장소 안(상태 변화마다 커밋, `leases.json` 충돌, uds 때 밖으로 뺀 이력), 작업 폴더 안 이름만 변경(캐릭터 작업실 문제 그대로). 경로는 `host_config.py`가 정하고 `tickets.tickets_dir()`가 쓴다 |
| D2 | 티켓 근거 규칙 | **결정 (2026-10-09, 운영자: "철저하게 데이터 기반으로. 내가 개입하는 건 그냥 요청사항")**: 두 칸을 나눈다. `evidence`는 엔진이 실재를 확인하는 데이터만 — `log:fp`, `log:rid`, `event:<세션>#<줄>`, 사건 id(il/D), `main.check` 커밋. `request`는 운영자의 말 그대로(채팅이면 그 `event:` 줄, CLI면 원문 인용과 받은 에이전트) — 근거로 치지 않는다. 티켓은 둘 중 하나는 있어야 하고, 에이전트가 스스로 올리는 티켓은 `evidence` 필수. 요청으로 시작한 티켓도 작업 중 재현·로그를 찾으면 `evidence`를 붙인다. `manual` 표시와 `candidate:` 형식은 없앤다(il/A) |
| D3 | 알림 빈도 | 새 사건·나빠진 사건만, 같은 사건 하루 1번, 조용한 시간 지킴(`event_react` 설정 재사용) |
| D4 | 원인 분석 두뇌 | 대화 두뇌와 따로 지정(강한 모델). 정해지기 전에는 F를 켜지 않는다 |
| D5 | 스킬 쪽 대화 신호 | 말 내용을 단어로 판정하지 않는다. 명시적 동작(다시 생성·중단·고쳐 쓰기)만 신호로, H 이후에 다시 본다 |
