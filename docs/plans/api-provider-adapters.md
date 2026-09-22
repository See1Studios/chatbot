# 냥피디 API 프로바이더 어댑터 설계 (OpenRouter/OmniRoute 등, OpenAI/Anthropic dialect)

## Context

지금 `AgentAdapter`/`AgySession`(`services/chatbot/server.py`)은 Multi-Provider
계획서(2026-09-17~18, agy/claude/grok/codex 4종 완료 — DEVLOG 참고)로 **CLI 프로세스**를
하나의 인터페이스로 스폰하는 데까지는 도달했다. 하지만 그 인터페이스 자체가 "매
세션마다 자식 프로세스 하나가 떠 있고, stdin에 쓰고 stdout을 한 줄씩 읽는다"는 전제
위에 지어져 있다 — `AgySession._spawn()`이 `subprocess.Popen`을 직접 호출하고
(`server.py:2000`), `_read_stdout`/`_read_stderr`가 그 파이프를 스레드로 읽고,
`stop()`이 `proc.terminate()`/`kill()`을 한다(`server.py:2945`). `StandbyPool`
(warm idle 프로세스 선점)과 orphan-kill(`chatbot-ctl.sh`)도 전부 "프로세스가 존재한다"는
전제 위에 있다.

실장님 요청: OpenRouter 같은 **API 직접 호출** 프로바이더 추가. "Hermes 참고하면 될거야"
— `~/.hermes/hermes-agent/`(이 NAS의 별도 멀티에이전트 프레임워크, git 커밋 author
`Hermes Agent <hermes@nousresearch.com>`와 동일 출처)가 실제로 OpenRouter/Anthropic
API/Bedrock 등을 이미 라우팅하고 있는 참고 구현이다. 조사 결과:

- `agent/provider_base.py` + `provider_registry.py` — `ProviderBase`/`CatalogProviderBase`
  ABC(`name`, `display_name`, `is_available()`, `list_models()`, `default_model()`) +
  스레드세이프 `ProviderRegistry`. 우리 `AgentAdapter`의 가장 가까운 사촌.
- `agent/auxiliary_client.py`의 `resolve_provider_client()` — 프로바이더별 분기
  (`_EXPLICIT_PROVIDER_BRANCHES`) 후 **항상 `.chat.completions.create()` 모양을
  노출하는 객체를 반환**한다. Anthropic Messages API·Codex Responses API·Bedrock처럼
  와이어 포맷이 다른 것들도 얇은 adapter 클래스(`_AnthropicCompletionsAdapter` 등)로
  감싸서, 호출부가 프로바이더별로 절대 분기하지 않게 만든다 — 우리가 이미
  `normalize_line`으로 하고 있는 것과 같은 원칙, API 쪽에 적용한 버전.
- OpenRouter는 커스텀 HTTP 클라이언트가 아니라 **OpenAI Python SDK를 base_url만 바꿔
  씀** (`base_url=https://openrouter.ai/api/v1`), `max_retries=0`으로 SDK 자체 재시도는
  끄고 Hermes가 직접 backoff을 관리(`agent/retry_utils.py`, decorrelated jitter +
  `Retry-After` 파싱).
- Auth: `OPENROUTER_API_KEY` env var, 필요시 다중 키 풀(`credential_pool.py`,
  쿨다운 포함) + OAuth PKCE 로그인 플로우.
- Usage: 와이어 포맷이 뭐든 `SimpleNamespace(prompt_tokens, completion_tokens,
  total_tokens)`로 정규화 — 우리 `normalize_usage()`와 같은 발상.

**OmniRoute — 참고 구현이 아니라 이미 떠 있는 실제 인프라.** 실장님이 언급한 대로
이 NAS의 docker(`docker-compose.yml` at `/volume1/docker/omniroute/`, 컨테이너명
`omniroute`, 이미지 `diegosouzapw/omniroute:latest`)에 **이미 살아있고 확인됨**
(`curl localhost:20128/v1/models` → HTTP 200, 160개 모델/콤보 응답, 실측
2026-09-18). Hermes가 `providers.omniroute`로 이미 이 게이트웨이를 쓰고 있다
(`~/.hermes/config.yaml`, `base_url: http://localhost:20128/v1`).

- **무엇을 하는가**: 237+ 프로바이더(Claude, GPT, Gemini, DeepSeek, Groq, xAI 등,
  OAuth/API키/무료티어 계정 풀)를 **단일 OpenAI 호환 엔드포인트**
  (`/v1/chat/completions`, `/v1/models`) 뒤로 감춘다. 17가지 라우팅 전략(티어
  폴백/비용최적/무료전용 등), 자동 폴백, 토큰 압축(RTK+Caveman)까지 게이트웨이가
  전담. 대시보드는 `http://localhost:20128`.
- **이게 우리 계획에 왜 중요한가**: "OpenRouter냐 Anthropic 직접이냐 OpenAI
  직접이냐"를 우리가 각각 어댑터로 짤 필요가 크게 줄어든다 — OmniRoute가 그 전부를
  **자기 쪽에서 이미 OpenAI 채팅-completions 모양으로 정규화**해서 내보내기 때문에
  (Anthropic 계열 모델도 `/v1/chat/completions`로 동일하게 나옴). 우리 입장에서는
  "OpenAI 호환 dialect 어댑터 하나"만 잘 만들면 OpenRouter든 OmniRoute든 그 뒤의
  237개 프로바이더든 전부 같은 코드 경로를 탄다.
- **비용 리스크에도 직접적인 완화책**: `free-only` 라우팅 전략/콤보를 쓰면 유료
  티어를 아예 안 태우도록 강제할 수 있다 — character-chat 사고(크레딧 소진) 재발
  방지를 "우리가 잔액을 감시"하는 것보다 "애초에 유료 티어가 안 걸리게 콤보를
  구성"하는 쪽으로 한 단계 더 밀 수 있다는 뜻. (그래도 유료 콤보를 쓰기로 하면
  Phase 4의 가드레일은 여전히 필요.)
- **격리 원칙과의 관계**: OmniRoute는 `~/.hermes`의 파일이 아니라 **독립된 docker
  컨테이너가 노출하는 네트워크 엔드포인트**다 — `nas_mcp.py`를 다른 프로세스가
  HTTP로 호출하는 것과 같은 성격이라 "백엔드 CLI 런타임을 SSOT로 삼지 않는다"는
  AGENTS.md 규칙과 충돌하지 않는다. 다만 **Hermes의 `~/.hermes/.env`에 있는
  `OMNIROUTE_API_KEY`를 그대로 읽어 쓰지 않는다** — 냥피디는 자기 몫의 키를
  대시보드에서 새로 발급받아 자기 `.env`에 둔다(사용량/과금이 Hermes 것과 섞이면
  안 됨, 콤보 실수로 유료 티어를 태워도 원인 추적이 돼야 함).
- **의사결정 필요**: Phase 1의 "최소 API 어댑터"를 OpenRouter에 직접 붙일지,
  OmniRoute(로컬, 무료 티어 라우팅 가능, 이미 검증된 가동 상태)를 1차 타깃으로
  삼고 OpenRouter는 OmniRoute 뒤에 있는 여러 프로바이더 중 하나로 자연스럽게
  포함시킬지 — **OmniRoute를 1차 타깃으로 권장**(로컬 지연시간, 무료티어 라우팅으로
  비용 리스크 원천 차단, 이미 켜져 있어 별도 배포 불필요). base_url을 설정값으로
  빼두면 나중에 OpenRouter 직결로도, 다른 OpenAI-호환 엔드포인트로도 바꿀 수 있어야
  한다(아래 "설계 원칙" 5번 참고).

**Hermes를 그대로 못 베끼는 이유** (VibeCat 때와 같은 함정 — 그대로 이식하지 말고
구조만 빌릴 것):
- Hermes는 자체 CLI 세션/프로파일 개념이 있고 `~/.hermes`는 그 SSOT다. 냥피디
  워크스페이스 규칙(`AGENTS.md`)은 이미 "백엔드 CLI 런타임을 냥피디 SSOT로 삼지 않는다"
  고 못박아뒀다 — API 키/크레덴셜 저장도 `~/.hermes`를 참조·재사용하지 않고 냥피디
  자체 공간에 둬야 한다.
- Hermes의 에이전틱 루프(툴 호출 포함)는 Hermes 자신의 프레임워크 안에서 돈다. 냥피디가
  OpenRouter를 붙이면 **그 루프를 우리가 직접 구현**해야 한다 — agy/claude/grok/codex는
  CLI 프로세스 자체가 이미 "모델 호출 → 툴 실행 → 재호출" 루프를 내장하고 있어서
  우리는 그저 stdout을 파싱만 하면 됐지만, OpenRouter는 순수 chat completions
  엔드포인트라 그 루프가 없다. **이게 이번 작업에서 가장 큰 신규 범위**다 — "어댑터
  하나 추가"가 아니라 "미니 에이전트 런타임 하나를 새로 만드는 것"에 더 가깝다.
- 다행히 로컬에 `nas_mcp.py`가 이미 있다 — 단, **같은 프로세스에서 import 가능하다는
  건 이 문서 초안의 잘못된 가정이었음, Phase 2 착수 시 실측으로 정정**
  (`grep "import nas_mcp" server.py` → 0건, `chatbot-ctl.sh`가 `nohup python3
  nas_mcp.py`로 완전히 별도 프로세스를 띄우고 `127.0.0.1:3012/mcp`에서 진짜 HTTP
  JSON-RPC로 응답함, claude/grok/codex 어댑터가 이미 이 URL로 붙는 것과 동일). 그래도
  진짜 MCP 클라이언트 라이브러리까지는 필요 없다 — `tools/list`/`tools/call`
  JSON-RPC 두 메서드만 `urllib`로 직접 치면 충분(Phase 2에서 `_mcp_rpc()`로 구현,
  DEVLOG 참고).
- **비용 리스크가 실제로 있었다**: `bin/character_chat_engine.py`/
  `services/character-chat/server.py`는 원래 OpenRouter를 직접 썼다가 "계정 크레딧이
  세션 도중 소진"돼서 실장님 본인이 "우리 챗봇처럼 cli 기반으로 바꿔줄 수 있어?"라고
  요청해 agy CLI 기반으로 갈아탄 전례가 있다. CLI 프로바이더는 정액제(구독) — API는
  종량제라 이 리스크가 구조적으로 다시 생긴다. 이번 설계는 그 재발을 막는 걸 명시적
  범위에 넣는다(Phase 4).

**목표**: 범용적/미래지향적으로 — 이번에 OpenRouter 하나만 되는 게 아니라, 나중에
Anthropic 직접 API나 OpenAI 직접 API 같은 "OpenAI 호환 chat-completions 계열" 프로바이더가
추가될 때 새 구조가 또 필요하지 않고 어댑터 서브클래스 하나만 얹으면 되게 만든다.

## 설계 원칙

1. **Transport와 Protocol을 분리한다.** 지금 `AgentAdapter`는 두 가지를 한 몸에 갖고
   있다 — "바이트가 어떻게 오가는가"(프로세스 stdin/stdout vs HTTP 스트림)와 "그
   바이트가 무슨 뜻인가"(normalize_line, usage 모양). CLI 4종은 전자가 전부
   프로세스였어서 안 나뉘어도 됐지만, API 프로바이더가 들어오는 순간 전자가 갈라진다.
2. **얇은 shim, 캐노니컬 이벤트 모양은 절대 안 바꾼다.** Hermes가 "무슨 프로바이더든
   `.chat.completions.create()` 모양으로 보이게" 하듯, 우리도 "무슨 트랜스포트든
   `{"event": "delta"/"tool_use"/"tool_result"/"result"/...}` 모양으로 보이게" 한다.
   프론트엔드(`app.js`)는 이번 작업으로 거의 안 바뀌어야 하는 게 설계가 맞았다는 신호.
3. **문서 말고 실측.** OpenRouter가 실제로 무엇을 스트리밍하는지, 에러/429 모양이
   뭔지, 어떤 모델이 tool-calling을 실제 지원하는지 — grok의 `--trust`, codex의
   승인 정책처럼 문서와 실측이 갈릴 여지가 있는 지점마다 라이브로 두들겨보고 DEVLOG에
   남긴다(기존 컨벤션 그대로).
4. **기존 세션 로테이션 인프라를 재사용한다.** API는 stateless라 CLI의 `--resume`
   같은 서버측 대화 기억이 없다 — 매 턴 전체 메시지 배열을 우리가 재전송해야 한다.
   이건 사실 heavy-session 로테이션(`get_handover_summary`, `_session_weight`)이
   이미 풀어놓은 문제와 같은 모양이라, 새로 설계하지 않고 그대로 얹는다.
5. **"Transport"와 별개로 "Wire Dialect"도 분리한다.** Transport(Phase 0)는
   "프로세스냐 HTTP냐"였다면, Dialect는 **같은 HTTP 트랜스포트 안에서도 요청/응답
   JSON의 생김새가 프로바이더군마다 다르다**는 문제다 — 실장님이 지적한 "OpenAI
   방식과 Anthropic 방식이 다르다"가 정확히 이 층이다:
   - **요청 모양**: OpenAI류는 `messages: [{role, content}]` 안에 system도 role로
     섞고, 툴 호출은 `tool_calls`(assistant 메시지)/`role: "tool"`(결과 메시지)로
     표현. Anthropic Messages API는 `system`이 최상위 별도 파라미터, 툴 결과는
     `role: "user"` 메시지 안의 `tool_result` 콘텐츠 블록, 툴 요청은 어시스턴트
     콘텐츠 블록 중 `tool_use` 타입 — 메시지 role 자체가 아니라 콘텐츠 블록
     타입으로 구분한다.
   - **스트리밍 이벤트 모양**: OpenAI SSE는 전부 같은 모양의
     `chat.completion.chunk` delta가 반복. Anthropic SSE는 `message_start` →
     `content_block_start` → `content_block_delta`(여러 개) →
     `content_block_stop` → ... → `message_delta` → `message_stop`처럼 **타입이
     있는 이벤트 시퀀스**다.
   - **usage 필드명**: OpenAI `prompt_tokens`/`completion_tokens`/`total_tokens`
     vs Anthropic `input_tokens`/`output_tokens` (+ `cache_creation_input_tokens`/
     `cache_read_input_tokens`) — 이미 `ClaudeAdapter.normalize_usage`에서 CLI
     기준으로 한 번 겪은 것과 이름 계열이 비슷하니 그 매핑을 참고할 수 있다.
   - **툴 스키마 모양**: OpenAI `tools: [{type:"function", function:{name,
     description, parameters}}]` vs Anthropic `tools: [{name, description,
     input_schema}]` — Phase 2에서 `nas_mcp.tool_defs()` → 툴 스키마 변환기를
     하나가 아니라 **dialect별로 하나씩** 만들어야 할 수 있다는 뜻.
   - **실용적 결론**: OpenRouter와 OmniRoute는 둘 다 위 차이를 자기들이 흡수해서
     **OpenAI dialect로만** 내보낸다 — 그래서 Phase 1은 "OpenAI dialect 어댑터
     하나"만 있으면 되고, Anthropic dialect(네이티브 Messages API 직결)는 나중에
     "게이트웨이를 거치지 않고 Anthropic 고유 기능(프롬프트 캐싱 세부 제어,
     확장 사고 블록 등)이 꼭 필요해지는 시점"에만 별도 Phase로 추가한다 — 지금
     범위에 억지로 넣지 않는다(YAGNI, 미확정 섹션 참고).

## Phase 0+1 진행 상태: 구현 + 실측 완료 (2026-09-18)

`transport_kind` 플래그, `_proc_alive()`/`_handle_events()` 공유, `_run_http_turn`,
`OpenAIDialectAdapter`(omniroute 인스턴스로 `AGENT_ADAPTERS` 등록)까지 구현하고
실장님이 준 OmniRoute 테스트 키로 실제 `AgySession`을 standalone 실행해 라이브
검증 완료(1턴/멀티턴 컨텍스트 유지/스트리밍 중 stop() 전부 확인, agy 회귀 없음도
재확인) — 자세한 내용은 `docs/DEVLOG.md`의 같은 날짜 항목. **`server.py` 디스크
반영만 완료, 라이브 호스트는 아직 ⚡소생 전** — 아래 Phase 0 섹션의 세부 항목들은
이제 "계획"이 아니라 실제로 이렇게 구현된 것의 기록으로 읽을 것. Phase 2(MCP 툴
루프)부터는 여전히 미착수.

## Phase 0 — Transport 추상화 분리 (동작 불변, CLI 4종 리그레션 없음)

API 어댑터를 끼울 자리를 만들기 위한 선행 리팩터. 새 프로바이더는 아직 안 붙인다.

- `AgentAdapter`에 `transport_kind`(`"process"`(기본) | `"http"`) 같은 최소
  캐퍼빌리티 플래그를 추가하거나, `keeps_stdin_open`/`close_stdin_after_prompt`
  플래그 체계를 그대로 확장할지 vs `Transport` 객체(작은 ABC: `start()`, `write()`,
  `stop()`, 백그라운드에서 `session._handle_stdout_line()` 동급 콜백을 부르는 리더)로
  분리할지 결정 — 후자가 "Transport와 Protocol 분리" 원칙에 더 맞지만, 기존 4개
  CLI 어댑터 코드를 건드리는 리스크가 있으니 첫 착수 세션에서 `AgySession._spawn`/
  `_read_stdout`/`stop()`을 실제로 읽고 최소 침습 지점을 다시 확인할 것.
- `_spawn()`이 프로세스 스폰을 조건 없이 가정하는 지점(`subprocess.Popen`,
  `self.proc`, `StandbyPool.try_take()`)을 `if self.adapter.transport_kind ==
  "process"` 같은 분기로 감싸거나 Transport 위임으로 옮긴다.
- `stop()`의 `proc.terminate()/kill()` 경로도 마찬가지 — HTTP 트랜스포트는 "진행 중인
  스트림 취소 + 백그라운드 스레드 stop 플래그"가 그 자리를 대신한다.
- 검증: agy/claude/grok/codex 4종 모두 회귀 없음(`chatbot-ctl.sh doctor`) 확인 후에만
  다음 Phase로.

## Phase 1 — 최소 `OpenAIDialectAdapter` (툴 없이 plain chat만)

목표: 새 트랜스포트 + 스트리밍 + usage 파이프라인이 실제로 끝까지 도는지 가장 좁은
범위로 검증. 툴 호출은 아직 안 건드린다. **`OpenRouterAdapter`라는 이름의 전용
클래스를 만들지 않는다** — "설계 원칙 5"에 따라 OpenRouter/OmniRoute/그 외 모든
OpenAI 호환 엔드포인트가 같은 dialect이므로, `base_url`+`api_key`+표시용 이름을
파라미터로 받는 **`OpenAIDialectAdapter` 하나**를 만들고, provider 등록 시
`OpenAIDialectAdapter(id="omniroute", base_url="http://localhost:20128/v1", ...)`
식으로 인스턴스화한다. 나중에 OpenRouter 직결/다른 OpenAI 호환 엔드포인트가
필요해지면 같은 클래스에 파라미터만 새로 꽂으면 된다 — 이게 "범용적/미래지향적"
요구사항이 실제로 만족되는 지점.

- **1차 타깃은 OmniRoute** (`base_url="http://localhost:20128/v1"`, Context 참고 —
  이미 떠 있고 실측으로 `/v1/models` 200 확인됨). OpenRouter 직결은 옵션 B로
  남겨두되 이번 Phase에서 동시에 구현하지 않는다 — 한 dialect 어댑터에 대상
  엔드포인트 하나만 먼저 끝까지 검증(실제 chat completion 호출은 유료 콤보를 태울
  수 있어 실장님 확인 후 진행 — free-only 콤보로 먼저 검증 권장, Context 참고).
- Auth: env var(예: `CHATBOT_OMNIROUTE_API_KEY` — 이름에 `CHATBOT_` 접두어를 둬서
  `~/.hermes/.env`의 `OMNIROUTE_API_KEY`와 절대 안 섞이게). OmniRoute 대시보드에서
  냥피디 전용 키를 새로 발급.
- 요청: `openai` Python SDK, `base_url`은 어댑터 인스턴스 파라미터, `stream=True`.
  Hermes처럼 SDK 자체 재시도는 끄고(`max_retries=0`) 우리 쪽에서 얕은 재시도만.
- `self.history`(이미 UI/handoff용으로 유지 중)를 OpenAI `messages` 배열로 매 턴
  변환해 재전송 — `mints_own_conversation_id()`/`--resume` 개념 자체가 없음, 이
  어댑터의 그 메서드는 "해당 없음"을 어떻게 표현할지 결정 필요(빈 문자열 conversation_id
  유지 + 항상 False 등, CLI 쪽 시맨틱과 혼동 안 되게 이름 재검토).
- `normalize_usage()`: OpenAI 표준 usage 모양(`prompt_tokens`/`completion_tokens`/
  `total_tokens`) → 우리 캐노니컬 shape. reasoning/cache 토큰은 모델별로 있을 수도
  없을 수도 있음 — 실측(OmniRoute가 업스트림이 Anthropic이어도 이 필드를 OpenAI
  이름으로 정규화해 내보내는지, 원본 이름이 새어나오는 케이스가 있는지 특히 확인).
- 스트리밍 청크 → 우리 `{"event": "delta", ...}` 매핑, 마지막 청크에서 `{"event":
  "result", "usage": ...}`.
- `known_models()`: OmniRoute의 `/v1/models`가 이미 `auto/best-coding` 같은
  콤보 별칭과 구체 모델 ID를 섞어서 반환(실측: 160개 확인) — 전부 노출하지 말고
  Phase 4 큐레이션 전까지는 `auto/*` 콤보 몇 개 + `model` 파라미터 자유 입력만.
- **실측 필수, 문서만 보고 넘어가지 말 것**: 실제 SSE 청크 모양, 에러 응답 모양
  (특히 402/429, 그리고 OmniRoute 고유의 "`[AUTO] matched no connected models`"류
  라우팅 실패), 스트림 중간에 연결이 끊기는 경우의 재현.

## Phase 2 진행 상태: 구현 + 실측 완료 (2026-09-18)

`_mcp_rpc`/`_mcp_openai_tools`/`_mcp_call_tool` + `OpenAIDialectAdapter._stream_once`/
`stream_turn`의 툴-홉 루프까지 구현하고 실제 `AgySession`으로 `ping_nas` 실호출 +
멀티홉 툴 호출 도중 `stop()`까지 라이브 검증 완료 — 자세한 내용은 `docs/DEVLOG.md`
같은 날짜 항목. 아래 Phase 2 섹션도 이제 구현 기록으로 읽을 것. **여전히 ⚡소생
전**(server.py 디스크 반영만). Phase 3(세션 수명주기 점검)/Phase 4(모델 큐레이션,
비용 가드레일)는 미착수.

## Phase 2 — MCP 툴 호출 루프 (이번 작업의 핵심 신규 범위)

- `nas_mcp.tool_defs()`를 OpenAI `tools=[...]` 스키마로 변환(JSON Schema 형태라 큰
  변형 불필요, 실측으로 확인). **OpenAI dialect 전용** — "설계 원칙 5"에 따라
  Phase 1의 `OpenAIDialectAdapter`가 대상이므로 `tool_calls`/`role:"tool"` 모양만
  구현하면 된다. Anthropic dialect(`tool_use`/`tool_result` 콘텐츠 블록)는 그
  dialect를 실제로 추가하는 시점에 별도 변환기로 만든다 — 지금 두 개를 한 함수에
  욱여넣지 않는다.
- 로컬 에이전틱 루프: 모델 호출 → 응답에 `tool_calls` 있으면 각각
  `nas_mcp.call_tool(name, arguments)`를 직접 함수 호출(진짜 MCP-over-HTTP 왕복 불필요,
  같은 프로세스) → 결과를 `role: "tool"` 메시지로 append → 재호출 → `tool_calls`
  없는 최종 응답이 나올 때까지 반복.
- 안전장치: 최대 루프 횟수 상한(예: 10회) — 프로세스가 없으니 "고아 프로세스" 리스크는
  없는 대신 "무한 툴 호출 루프"라는 새로운 실패 모드가 생긴다. 상한 도달 시 명시적
  에러 이벤트로 종료, 조용히 끊지 않기.
- 이벤트 매핑: `tool_calls` → `{"event": "tool_use", ...}`, 실행 결과 →
  `{"event": "tool_result", ...}` — CLI 어댑터들이 이미 내는 모양과 동일해서
  프론트엔드 툴 카드 렌더링을 그대로 재사용할 수 있어야 한다(안 되면 설계 재검토).

## Phase 3 — 세션 수명주기 통합

- `StandbyPool`: 해당 없음, 스킵 — HTTP 어댑터에서 `try_take()` 호출 경로 자체를
  타지 않게 Phase 0에서 이미 분기됐어야 함.
- Orphan-kill(`chatbot-ctl.sh`의 `kill_orphan_agy`류): 해당 없음.
- `stop()`: HTTP 스트림 취소(SDK의 스트림 컨텍스트 매니저 종료/커넥션 close) + 진행
  중이던 툴 루프에 stop 플래그 전달.
- **전체 턴 워치독 — 실사용 중 실제로 걸려서 추가됨 (2026-09-18)**: ⚡소생 후 실장님이
  직접 UI에서 omniroute로 대화하다 응답이 몇 분째 안 끝나고 결국 프론트가 idle로
  돌아가버리는 걸 실측으로 발견. 원인: `_stream_once`의 `urlopen(timeout=120)`은
  "청크 사이 간격"만 재는데, OmniRoute가 업스트림이 멈춘 동안에도
  `omniroute-keepalive` 델타를 계속 흘려보내면 그 타이머가 매번 리셋돼서 전체 턴
  길이엔 상한이 없어짐 — `session.busy`가 영영 True로 고정되고, OS 프로세스가 아니라
  스레드라 `chatbot-ctl.sh`의 orphan-killer도 못 봄. `AgySession._http_turn_watchdog`
  + `OpenAIDialectAdapter.HTTP_TURN_TIMEOUT_SEC`(180초)로 전체 턴 벽시계 상한을 추가:
  타임아웃 시 `stop()` 호출 + 이유를 담은 assistant 메시지를 history에 기록. `_turn_seq`
  카운터로 오래된 워치독이 그 사이 새로 시작한 턴을 잘못 멈추지 않게 가드. 독립
  `AgySession`으로 (1) 진짜 멈춘 턴이 타임아웃 시점에 정확히 멈추는지, (2) 빠르게 끝난
  턴의 stale 워치독이 그 다음 턴을 안 건드리는지 둘 다 라이브 검증 완료. 여전히
  ⚡소생 전(server.py 디스크 반영만).
- 세션 로테이션: heavy-session 임계값(`soft_hard_tokens`)을 실제로 선택된 모델의
  컨텍스트 창에 맞게 오버라이드 — 이 부분은 오히려 API 프로바이더가 제일 자연스럽다
  (애초에 "요약해서 새 대화 시작" 패턴이 stateless 모델을 염두에 뒀던 것과 같은 모양).

## Phase 4 진행 상태: 구현 + 실측 완료 (2026-09-18)

OmniRoute `/api/providers` 기반의 `rate_limit_report()`(연결된 OAuth 계정들의 상태/만료일), `/v1/models`의 `context_length` 캐시를 활용한 동적 `soft_hard_tokens()` 스케일링, 그리고 큐레이션된 `known_models()`(무료 콤보 우선) 및 비용 가드레일 구현 완료. standalone 테스트로 검증 완료.

## Phase 4 — 모델 목록 / 사용량 / 비용 가드레일

- `known_models()`: 대상 엔드포인트(OmniRoute면 `/v1/models`, 실측 완료 — 160개,
  `auto/*` 콤보 15개 + 구체 모델 다수)를 캐싱 후, 수백 개를 그대로 드롭다운에 쏟지
  말고 큐레이션된 서브셋만(Hermes의 정적 카탈로그 JSON을 참고할 순 있지만 그대로
  import하지 않음 — SSOT 분리). OmniRoute의 `auto/best-*` 콤보를 1차 후보로.
- `rate_limit_report()`: OmniRoute면 `/api/providers`(연결된 프로바이더별 상태/
  쿼터, 실측 완료 — 인증 없이도 `/v1/models`는 응답했지만 `/api/*`는 대시보드
  API 키가 필요한지 별도 확인 필요)나 OpenRouter 직결이면 키/크레딧 조회
  엔드포인트를 실측 → 기존 `{group, limit_type, remaining_pct, reset_at}` 행
  모양으로.
- **비용 가드레일 (character-chat 선례 재발 방지, 이번 계획의 필수 항목)**:
  - **1차 방어선은 라우팅 자체** — OmniRoute의 `free-only`/`quota-aware` 전략이나
    무료 티어만 들어간 콤보를 기본으로 써서, 유료 과금이 구조적으로 안 걸리게
    한다(Context의 OmniRoute 절 참고). 유료 콤보를 쓰기로 결정하는 건 실장님의
    명시적 선택이어야 한다.
  - 2차 방어선: 잔액 임계값 이하일 때 상태 탭/응답에 경고 표시.
  - 턴마다 실제 비용(또는 최소 토큰 사용량)을 로그/기록 — 나중에 "왜 크레딧이
    줄었는지" 추적 가능하게.
  - 기본값은 여전히 CLI 프로바이더(agy) — API 프로바이더는 세션 단위로 실장님이
    명시 선택해야 켜지는 옵트인으로 시작, 자동 선택/자동 폴백 대상에 넣지 않는다.
  - 다중 키 폴백 풀(Hermes의 `credential_pool.py` 수준)은 v1 범위 밖 — OmniRoute
    자체가 이미 그 역할(폴백/쿼터 인지 라우팅)을 대신해주므로 실제로는 필요성도
    낮음. 단일 키로 시작.

## Phase 5 진행 상태: 구현 + 실측 완료 (2026-09-18)

프론트엔드 `#provider` 드롭다운에서 `omniroute` 선택 시 모델 목록(`auto/best-free` 등) 정상 갱신, 실제 세션 생성 및 메시지 전송, MCP 도구 호출(`ping_nas`), 상태 탭 연결 상태 조회까지 라이브 서비스(포트 3011)에서 실측 검증 완료.

## Phase 5 — 프론트엔드

- `#provider`/`#model` 드롭다운, `/api/providers`, `available()`/`known_models()`
  배관은 이미 있다(Multi-Provider 프론트엔드 단계에서 완성) — 새 API 프로바이더도
  그 목록에 한 줄 추가되는 정도여야 한다. 설계가 맞았다면 **이 Phase가 거의 할 일이
  없어야 정상**이고, 실제로 추가 수정 없이 바로 동작함.

## 미확정 / 다음 세션에서 라이브로 확인해야 할 것

- **OmniRoute 대시보드 API 키를 냥피디 몫으로 새로 발급할지, 아니면 실장님이
  이미 관리 중인 키 정책이 따로 있는지** — 착수 전에 확인. `~/.hermes/.env`의
  키를 그대로 읽어 쓰지 않는다는 원칙(Context)은 확정이지만, "새 키 발급"이 맞는
  방법인지는 실장님 확인 필요.
- **실제 `/v1/chat/completions` 호출이 유료 콤보를 태울 수 있는지** — `/v1/models`
  GET은 인증 없이도 200이 왔지만(실측 2026-09-18), POST로 실제 대화 요청을 보내는
  건 과금 가능성이 있어 이번 조사에서 실행하지 않았다. Phase 1 착수 시 free-only
  콤보로 먼저 검증하거나, 실장님에게 확인 후 진행.
- ~~OmniRoute의 `/api/providers`/`/api/settings`가 `/v1/*`와 별도 인증을 요구하는지~~
  **해결(2026-09-18 실측)**: 별도 인증 없음, `/v1/*`와 같은 Bearer 키로 인증됨 —
  Phase 4 `rate_limit_report()` 구현 시 그대로 사용 가능.
- 스트리밍 응답에서 tool_call이 여러 델타에 걸쳐 조각나는 조합 방식(OpenAI 프로토콜
  표준이긴 하지만 라우팅 계층이라 모델/프로바이더별 편차 가능성, 특히 OmniRoute가
  Anthropic류 모델을 OpenAI dialect로 재포장할 때 tool_call 델타 분할이 표준과
  다를 수 있음 — 실측 필요).
- 429/402(크레딧 부족) 응답의 정확한 모양과 `Retry-After` 유무.
- 어떤 모델이 실제로 tool-calling을 지원하는지(여러 백엔드로 라우팅하므로 모델마다
  다름) — `known_models()` 큐레이션 기준에 반영.
- `transport_kind` 분기를 캐퍼빌리티 플래그로 할지 별도 `Transport` 객체로 할지는
  Phase 0 착수 시 `_spawn`/`_read_stdout`/`stop()`을 다시 읽고 최소 침습 지점 기준으로
  확정(위에서 이미 노트 남김).
- Anthropic dialect를 언제 실제로 추가할지는 "게이트웨이를 거치지 않고 네이티브
  기능이 필요해지는 구체적 요구가 생길 때"로 미뤄둔 상태(설계 원칙 5) — 이번
  계획의 실행 범위(Phase 0~5)에는 포함하지 않는다.

## 순서

Phase 0부터 순차 진행, 각 Phase마다 실측 검증 + DEVLOG 기록(기존 Multi-Provider
계획서와 동일한 방식). Phase 1(plain chat) 끝까지 라이브 검증 없이 Phase 2(툴 루프)로
넘어가지 않는다 — 툴 루프 버그를 스트리밍 버그와 뒤섞어 디버깅하는 상황을 피하기 위함.
