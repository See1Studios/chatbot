# API 어댑터 능력 동등화 (CLI 두뇌와 같은 손발)

> 방향 (align/D, 2026-09-29): **기반** — 키 없는 무료 구독(CLI)과 API 키(HTTP) 어느 쪽으로 들어와도 같은 친구·같은 일솜씨. 두뇌를 바꿔도 능력이 줄지 않아야 두뇌 선택이 취향이 된다

> 상태: **active** (2026-09-29 초안)
> 목적: CLI 두뇌(claude·agy·codex·grok)가 내장으로 가진 능력을 HTTP 두뇌(OpenRouter·omniroute …)에게도 **제공자 중립 MCP 도구**로 가능한 한 같게 준다.
> 관련: [private-security.md](private-security.md)(사적 세션·외부 전송) · [edition-boundary.md](edition-boundary.md)(배포판 도구 범위) · [multi-agent-worktree-delegation.md](multi-agent-worktree-delegation.md)(쓰기 권한이 큰 일은 워크트리에서)

## 1. 운영자 요청 (2026-09-29)

"왜 OpenRouter Space Bunny는 웹 접근을 못 하는 거야?" → B(우리 MCP에 웹 도구) → "cli가 가진 능력을 가급적 동등하게 api 어댑터에도 부여했으면 좋겠어" → "agent reach가 웹을 제일 잘 쓰던데".

## 2. 현재 능력표 (2026-09-29 코드 확인)

CLI 두뇌는 자기 도구 + 우리 MCP. HTTP 두뇌는 우리 MCP뿐(`providers/adapter_openai.py::_mcp_openai_tools`). Claude CLI 허용 목록(`adapter_claude.ALLOWED_TOOLS`)을 기준으로 삼는다.

| 능력 | CLI 두뇌 | HTTP 두뇌 (지금) | 차이 |
|---|---|---|---|
| 웹 검색·읽기 | WebSearch·WebFetch | `web` (#376, Exa·Jina, 공개 주소만) | **메움** |
| 파일 읽기·목록·찾기 | Read·Glob·Grep (작업공간 전체) | `read_file`·`list_dir`·`search_text` (허용 루트) | Glob(패턴으로 파일 찾기) 없음 |
| 파일 고치기 | Edit (부분 교체) | `write_file` (통째로 쓰기) | **부분 교체 없음** — 큰 파일은 통째로 다시 써야 함 |
| 셸 | Bash (권한 확인 없이) | `run_command` (읽기 전용 허용 목록) | **큼** — 의도된 차이일 수 있음(D2) |
| 스킬 | Skill (`.agents/skills` 로드) | 없음 (허용 루트면 read_file로 가능) | 스킬 목록·로드 도구 없음 |
| 그림 보기 | 파일 경로로 | 첨부 이미지(IMAGE_LOOKBACK) | 대체로 메움 |
| 그림 그리기 | 일부 CLI(위임 artist) | 없음 | OpenRouter 이미지 출력 모델로 가능(D4) |
| 도구 호출 수 | 사실상 제한 없음 | 한 턴 20회 + 마무리 1회 | 긴 작업에서 끊김 |
| 위임·메모리·티켓·선택지 | 우리 MCP | 우리 MCP | 같음 |

## 3. 원칙

- **도구는 제공자 중립 MCP로.** HTTP 어댑터에 특정 제공자 기능(OpenRouter `web` 플러그인 등)을 넣지 않는다. 한 번 만들면 모든 HTTP 두뇌가 같이 얻는다.
- **백엔드는 검증된 것을 차용.** 웹은 agent-reach가 고른 키 없는 서비스(Jina Reader, Exa 공개 MCP)를 CLI 없이 직접 쓴다. 키가 있으면 더 좋은 백엔드로 바꿀 수 있게 설정 한 줄.
- **권한은 두뇌가 아니라 자리에 묶는다.** 무료·스텔스 모델은 대화 기록이 학습에 쓰일 수 있다. 셸·쓰기 같은 큰 권한은 "어느 모델이냐"가 아니라 "대화 중이냐, 위임 워크트리 안이냐"로 정한다.
- **사적 세션은 밖으로 나가는 도구를 닫는다**(웹과 같은 규칙, private-security).

## 4. 항목

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `par/A` | 이 문서 + INDEX 행 | 이 문서, `docs/plans/INDEX.md` | 커밋 | 0 · — | S | — | ✅ #376 |
| `par/B` | `web` 도구 | `web_tool.py`, `mcp_server.py`, 테스트 | 읽기·검색, 공개 주소만, 사적 세션 닫힘 | 2 · ⚡ | M | — | ✅ #376 |
| `par/C` | `edit_file` (부분 교체) | `mcp_server.py`, 테스트 | Claude Edit와 같은 계약: 옛 문자열이 정확히 한 번 있을 때만 바꿈(`replace_all` 선택), 쓰기 허용 루트·보호 경로 규칙 그대로 | 2 · ⚡ | S | — | 대기 |
| `par/D` | `find_files` (Glob) | `mcp_server.py`, 테스트 | 허용 루트 안 패턴 검색, 비밀 이름 제외, 개수 상한 | 1 · ⚡ | S | — | 대기 |
| `par/E` | `skill` (목록·로드) | `mcp_server.py` 또는 새 모듈, 테스트 | 스킬 이름·설명 목록, 이름으로 SKILL.md 본문 | 1 · ⚡ | S | — | 대기 |
| `par/F` | 도구 예산 | `providers/adapter_openai.py`, 테스트 | 업무 모드 상한 상향(예: 40), 사적 모드는 낮게, 마무리 규칙 유지 | 1 · ⚡ | S | D3 | 대기 |
| `par/G` | 셸 | D2대로 | D2 | 2–3 · ⚡ | M | D2 | 대기 |
| `par/H` | 그림 그리기 | 새 도구 | D4 | 2 · ⚡ | M | D4 | 대기 |

추천 순서: C → D → E → F (작고 효과 큼) → G·H(결정 뒤).

## 5. 결정 (운영자 확인 필요)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 검색 백엔드 기본값 | Exa 공개 MCP → DuckDuckGo lite(지금). 키 있는 백엔드(Exa·Brave·Tavily)는 설정으로만, 기본값 아님 | 대기 |
| D2 | HTTP 두뇌의 셸 | 대화 중에는 지금처럼 읽기 전용. 쓰기 가능한 셸은 **위임 워크트리 안의 작업자**에게만(CLI 작업자와 같은 자리) — 무료·스텔스 모델에 호스트 셸을 주지 않는다 | 대기 |
| D3 | 도구 예산 | 업무 40 / 사적 8, 넘으면 지금의 마무리 요청 | 대기 |
| D4 | 그림 그리기 | OpenRouter 이미지 출력 모델을 쓰는 `image` 도구는 그림 관리 모달의 "생성 요청"과 같이 설계(결과는 갤러리로) | 대기 |

## 6. 하지 않는 것

- 제공자 전용 기능을 HTTP 어댑터에 직접 넣기(OpenRouter 웹 플러그인 등) — 중립 도구로.
- CLI의 내부 기능(할 일 목록, 자체 요약) 흉내 — 대화 기록·위임이 이미 맡는다.
