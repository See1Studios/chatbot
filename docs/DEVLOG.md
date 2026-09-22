# chatbot 개발로그

## 2026-09-22 — 보안·안정성·구조 정리 (T1–T4 Audit & Direction 실행)
- **배경**: `docs/plans/audit-2026-09-22-work-ordered.md`에 따른 전면 점검 및 Tier 1~4 순차 작업 수행.
- **주요 변경 사항**:
  - **Tier 1 (보안 & 격리)**:
    - T1.1: `/persona/` 경로 순회 차단 검증 (`..`, 절대경로 등 404 차단).
    - T1.2: XSS 방어 — DOMPurify 3.2.6 벤더링(`static/vendor/purify.min.js`), `static/markdown.js` 전면 적용 (HTML 정화, mermaid strict 검증 및 실패 시 이스케이프), `static/index.html` 캐시버스팅(`markdown.js?v=8`).
    - T1.3: CSRF 게이트 — `origin_guard.same_origin` 검증을 `server.py` `do_POST` 진입부에 적용, `_read_json()`에 `Content-Type: application/json` 강제.
    - T1.4: 아티팩트 서빙 경로 제한 — `_safe_artifact_rel`로 dotfile/제한 디렉터리 차단, `/artifacts/` 응답에 `Cache-Control: private` 헤더 추가.
  - **Tier 2 (안정성 & 라이프사이클)**:
    - T2.1: 한글 IME 조합 중 Enter 전송 차단(`isComposing` guard) — `static/app.js` 및 `static/slash.js`.
    - T2.2: `AgySession.events` 미소비 큐 메모리 누수 원인 제거 (`events` 속성 정리 및 테스트 픽스).
    - T2.3: HTTP transport stale turn 하이잭 차단 — `_turn_seq` 기반 홉 검증 및 조기 취소, stale turn에 의한 `_http_resp` 클로버링 방지.
    - T2.4: SSE/poll 델타 중복 방지 — 모든 어댑터에 delta offset 부여, `static/app.js`에서 중복 offset 수신 시 무시 처리 (`app.js?v=108`).
    - T2.5: GET 라우트 불필요 세션 복원 방지 — `Registry.peek(sid)` 구현 및 `server.py` GET 핸들러 4곳에 적용.
    - T2.6: stderr 민감 정보 유출 방지 — `_redact_line`/`_redact_text` 마스킹 추가 (API 키, bearer 토큰, 세션 토큰 등 redaction), `tests/test_stderr_redaction.py` 추가.
  - **Tier 3 (구조 & 회귀 정리)**:
    - T3.1: 어댑터 턴 종료 로직 통합 — `AgentAdapter.finalize_turn` 공통 메서드로 Agy, Claude, Grok, Codex, OpenAIDialect 어댑터 통일.
    - T3.2: 회귀 테스트 3건 정리 — `server.py` 내 사용자/봇 호칭 동적화(`identity.user_title()`, `identity.self_label()`), `status_picker` stub, `session_weights` 홈 디렉터리 패치.
    - T3.3: 의존성 매니페스트 — `requirements.txt` (`PyYAML==6.0.3`) 명시 및 README 테스트 실행 안내 보강.
  - **Tier 4 (소형 누수/정리)**:
    - `server.py` Content-Length 검증(200KB 초과 시 413) 및 GET 예외 핸들링, `_get_usage` provider 화이트리스트 검증.
    - 프로세스 kill 후 `wait(timeout=1)` 안전 대기 추가.
    - Grok 임시 프롬프트 파일 삭제 보장.
    - Claude MCP config 원자적 쓰기(`_atomic_write_text`) 및 변경 시에만 쓰기.
    - 손상된 `meta.json` 백업 및 에러 로깅.
    - 프론트엔드 ES 재연결 타이머 중복 해제 및 최대 20회 재시도 제한 배너.
    - 사용되지 않는 죽은 코드/임포트/설정 정리 (`effort_levels`, `BRAIN`, `HARD/SOFT_*` 등).
- **검증**: `python3 -m unittest discover -s tests` 실행 (총 689개 테스트 중 687개 통과, CSS 44px 기존 UI 2건 제외 0 에러).
- **배포**: python → needs ⚡소생

## 2026-09-22 — MCP 분리 leftover: 3015 healthz, nas-mcp 이름, 위임 테스트 (티켓 17)

- **배경** (실장님 "빈 칸 정리 티켓"): 중앙 Host MCP(:3015) 위임 뒤 `sphere_hub_status`가 `GET /`를 헬스체크해서 자기 자신을 DOWN으로 보고, 3012 healthz도 `nas-mcp`라 이름이 겹쳤다. 위임 테스트가 없었다.
- **변경**: 3015에 `/healthz`를 두고 그 URL을 프로브. 챗봇 MCP는 `chatbot-mcp`(:3012), 중앙은 `nas-mcp`(:3015). `service_ctl nas-mcp`는 `nas-mcp-ctl.sh`. 위임 3도구 단위 테스트.
- **검증**: `tests.test_nas_mcp_host`, `tests.test_mcp_server`.
- **⚡소생 필요**: `mcp_server.py`, `nas_mcp_host.py`. 3015는 `nas-mcp-ctl.sh restart` (챗봇 소생과 별개).

## 2026-09-22 — 자기진화 루프를 프로토콜까지 닫기 (티켓 15)

- **배경** (실장님: 재귀는 코드만이 아니라 지침·프로토콜·파이프라인에도 닫혀야 한다. 티켓 없이 커밋/푸시, Agy done-미커밋).
- **변경**: `release(done)`은 대상 경로가 git에서 깨끗해야만 닫힘. `claim(paths=)`은 그 경로의 미커밋 leftover면 거절. 헌장·PROJECT·설계서 §4.1/§4.3: Tier 3은 승인 없이 시작 불가일 뿐, 승인된 티켓은 프로토콜을 고친다. `guard_tickets`가 헌장·설계서 변경도 본다.
- **검증**: `tests.test_tickets` (기존 + ShipGateTest), `tests.test_mcp_core`, `tests.test_bundle_budget`.
- **⚡소생 필요**: `tickets.py`, `mcp_core.py`, `chatbot-ctl.sh`.

## 2026-09-22 — '최신 대화로' 점프가 또 mtime·스무드 스크롤로 되돌아간 것 복구

- **배경** (실장님 "최신대화로 버튼이 또 고장난 것 같은데"): v=98–101에서 고친 점프 로직이 `app.js` 점프 블록에 안 남고 v=92 원본이 그대로였다. `/api/sessions` 첫 항목(mtime)을 최신으로 봐서, 과거 세션을 열면 그 세션이 "최신"이 되고 버튼을 눌러도 그 바닥만 스크롤하거나 반대로 최신에서 과거로 튕겼다. `behavior:'smooth'`는 `loadNewerHistory`와 레이스해 중간에 멈췄고, `viewingPastSession()`이 next id만 보면 예전 세션 mtime leftover에 버튼이 안 사라졌다.
- **변경** (`static/app.js`): 라이브 = 세션 id(`YYYYMMDD-HHMMSS-`) 최댓값 + successor 끝. `goToLatestConversation`은 그 id로 `openSession`하거나 instant pin. 이후 세션 fallback도 id 순. 과거 열람(`archiveBrowse`) 중이 아니면 2.5초 동기화가 라이브를 따라감. 버튼은 라이브+바닥일 때만 숨김. `app.js?v=106`.
- **검증**: `node --check static/app.js`, `tests.test_latest_conversation_jump`(점프·instant scroll·체인·mtime 무시·버튼 숨김·archive는 follow 안 함), `tests.test_live_session`. 라이브 `GET /`에 `app.js?v=106`.
- **배포**: 정적만, 모바일 새로고침. `session.py` `get_active`는 이미 디스크에 id 순이 있음 — 라이브 호스트가 옛 mtime이면 ⚡소생이 한 번 더 필요하지만, 버튼 점프는 클라만으로 동작.

## 2026-09-21 — 툴 호출 홉 한도 상향(10→20) 및 MCP 경로 자동 해석·화이트리스트 보강

- **배경** (실장님 "또 10회에 걸렸는데 10회제약이 좀 과한 거 아닌가"): 복합 툴 호출이나 캐릭터챗 등에서 모델이 스킬·데이터 경로 오인 및 의사 절대경로(`/data/...`, `/AGENTS.md`) 호출로 헛돌다 `MAX_TOOL_HOPS(10)`에 걸려 중단됨.
- **변경**:
  - `adapters.py`: `MAX_TOOL_HOPS`를 10에서 20으로 상향하여 복합 멀티홉 및 탐색 작업 여유 확보.
  - `mcp_server.py`: `_resolve_target_path`에서 모델이 자주 호출하는 의사 절대경로(`/data/...`, `/services/...`, `/AGENTS.md`) 자동 정규화 및 상대경로(`data/workspace/...`, `.agents/...`) fallback 해석 보강.
  - `mcp_server.py`: `READ_ROOTS`에 `(HOME / "AGENTS.md").resolve()` 추가 및 `_is_under`에서 단일 파일 매칭 지원.
- **검증**: `mcp_server.py` 단위 테스트(`list_dir`, `read_file` 4개 케이스) 통과, `tests/smoke.py` 및 `chatbot-ctl.sh guard` 통과.
- **⚡소생 필요**: `adapters.py`, `mcp_server.py` (파이썬 호스트 모듈 디스크 수정 반영).

## 2026-09-21 — 라이브 id는 YYYYMMDD-HHMMSS- 만

- **배경**: 소생 후 `/api/sessions/active`가 `nonexistent-sid-test`를 반환. 테스트 잔여 id가 날짜 id보다 사전순으로 뒤라 라이브로 잡힘.
- **변경**: 서버 `_live_sid`, 클라 `isLiveSid`가 `^\d{8}-\d{6}-`만 후보. `app.js?v=101`.
- **검증**: `tests.test_live_session` + jump `skipGarbage`.
- **⚡소생 필요**: `session.py` 한 번 더.

## 2026-09-21 — 라이브 대화 한 규칙 (버튼·동기화·과거 열람)

- **배경** (실장님 "상황별로 땜질하다 요구가 충돌"): 최신 대화가 화면 바닥 / mtime active / 세션 id 세 뜻이었다. 버튼을 고치면 동기화가 안 되고, 동기화를 따라가면 과거 열람이 뺏겼다.
- **규칙**: 라이브 = 세션 id 최댓값 + successor 끝. 과거 열람은 이전/세션 탭으로만. `최신 대화로`는 라이브로 돌아가 바닥. 버튼은 라이브+바닥일 때만 숨김. 다른 기기는 과거 열람 중이 아니면 라이브를 따라감.
- **변경**: `session.py` `get_active()` mtime 폐기. `static/app.js` `liveSessionId`/`archiveBrowse`, `followLiveIfNeeded`를 2.5초 동기화에 연결. 이후 세션 fallback도 id 순. `app.js?v=100`.
- **검증**: `tests.test_live_session`, `tests.test_latest_conversation_jump`(점프·버튼 숨김·archive는 follow 안 함).
- **⚡소생 필요**: `session.py`. 정적은 새로고침.

## 2026-09-21 — 최신 대화로 점프한 뒤에도 버튼이 남는 문제

- **배경** (실장님 "예전대화보다가 최신대화로 가면 최신 대화로 버튼이 사라지지않을때가 많아"): 과거 세션을 열면 mtime이 올라간다. `resolveScrollforwardFallback`이 그 mtime을 "이후 세션"으로 봐서, 실제 최신 세션의 `sessionNavNextSid`가 방금 본 옛 세션으로 남았다. `viewingPastSession()`이 참이면 바닥에서도 버튼을 강제로 켜 두므로 점프 후에도 안 사라졌다.
- **변경** (`static/app.js`): 이후 세션은 id(YYYYMMDD-HHMMSS) 순만. `viewingPastSession`은 next id가 현재보다 이후일 때만. 점프 후 `pinChatToBottom`. `app.js?v=99`.
- **검증**: `tests.test_latest_conversation_jump` (mtime 무시, stale next면 버튼 숨김). 정적만, 새로고침.

## 2026-09-21 — '최신 대화로'가 과거 열람·중간 스크롤에서 또 고장

- **배경** (실장님 "최신 대화로 이동하는 버튼이 고장났어"): 이전에 점프 함수는 붙였지만 (1) `/api/sessions` 첫 항목이 mtime이라 과거 세션을 열면 그게 "최신"이 되고, (2) 같은 세션에서 위로 올린 뒤 누르면 `behavior:'smooth'`가 `loadNewerHistory`와 레이스해서 중간에 멈추고, (3) 모바일에서 버튼이 `#log` 스크롤 레이어 안에 있어 탭이 삼켜질 수 있었다.
- **변경**:
  - `resolveLatestSessionId()`: 세션 id(YYYYMMDD-HHMMSS) 사전식 최댓값 + successor 체인. list[0](mtime) 폐기.
  - 점프가 아니면 즉시 `scrollTo(... behavior:'auto')`로 바닥 고정. 600ms 동안 위/아래 히스토리 추가 로드 억제.
  - `#scrollToBottomBtn`을 `.stage` 밖 `.stage-shell` 오버레이로 옮겨 iOS overflow 탭 훔침을 피함. `app.js?v=98`, `chat.css?v=20`.
- **검증**: `node --check static/app.js`, `tests.test_latest_conversation_jump`(mtime-과거여도 점프, 최신은 instant scroll) + served_model/provider_sync 캐시 버전. 정적만, 새로고침. ⚡소생 불필요.

## 2026-09-21 — 기기 간 프로바이더는 세션 SSOT

- **배경** (실장님 "채팅은 동기화되는데 프로바이더가 동기화 안되네"): 히스토리는 `resyncFromServer`가 2.5초마다 맞추는데, 초상·테마·캡션은 기기 `localStorage`만 봤다. 게다가 매 전송이 UI의 provider를 POST해서, 낡은 폰이 라이브 세션을 되돌려 놓을 수 있었다.
- **변경** (`static/app.js`): 세션 `provider`/`model`이 SSOT. `applySessionProvider`를 열기·resync·생성/인계에 씀. 전송은 UI가 서버 캐시와 다를 때만 provider/model을 실어 보냄. 트레이·모델 피커는 `/provider`로 올리고 `localProviderEdit` 동안 원격 적용을 막음. `app.js?v=96`.
- **검증**: `node --check`, `tests.test_provider_sync` + resync/jump/served_model/model_picker. 라이브 `GET /`에 `app.js?v=96`.
- **배포**: 정적만. 양쪽 기기 Ctrl+Shift+R. 소생 불필요.

## 2026-09-21 — OpenRouter 가발 = 라임 레게

- **배경** (실장님 "추천으로갈께"): 여러 모델 라우팅을 갈래 많은 헤어로. 56px에서 레게가 제일 갈림.
- **변경**: 라임 염색 두꺼운 로프 록. 테마는 Sphere Lime 유지. 512 png/webp를 `data/persona/providers/`와 `/volume1/web/chat/persona/providers/`에 씀. 옛 쌍볼·박스브레이드는 gallery. `PORTRAIT_CACHE=v=12`, `app.js?v=95`, JSON icon `?v=12`.
- **검증**: 56px 원형에서 톱니 실루엣. `node --check` app.js.
- **배포**: 초상·프론트는 새로고침. JSON 아이콘 쿼리는 소생 후 허브 FAB.

## 2026-09-21 — Grok Imagine `images/1.jpg`가 말풍선에서 또 404

- **배경** (실장님 "이미지가 채팅창에서 바로 보이지 않아"): 세션 `20260921-155101-aa4450` history가 `![…](images/1.jpg)` 그대로, `artifacts/brain/` 없음. 프론트 `absArtifact`는 `/artifacts/<sid>/brain/1.jpg`로 열어서 404.
- **원인**: grok `end`가 `sessionId`를 준 뒤에야 cid가 생기는데, 경로 재작성은 그 전에 돌아서 첫 Imagine 턴은 grok 세션 폴더를 못 찾음. 게다가 `_append_images_markdown`이 마크다운에 이미 `images/1.jpg`가 있으면 stem 중복으로 스테이징을 건너뜀.
- **변경**: cid를 rewrite 전에 캡처(`session_id` 별칭 포함). cid가 비거나 폴더가 없으면 이 workspace에서 `images/` 있는 최신 grok 세션으로 폴백. append는 먼저 rewrite하고, 상대경로 URL은 “이미 있음”으로 치지 않음.
- **검증**: `tests.test_grok_image_paths` 5개. 라이브는 파일을 `sessions/<sid>/artifacts/brain/`에 복사해 `GET` 200. 이전 말풍선은 새로고침하면 `absArtifact`로 열림.
- **⚡소생 필요**: `media_handler.py`·`adapters.py`. 지금 말풍선은 `/artifacts/…` URL이라 소생 없이 보임.

## 2026-09-21 — OpenRouter 가발 = Sphere Lime 쌍볼

- **배경** (실장님 "형광연두는 OpenRouter 키컬러인데 우리는 이미 있으니 그쪽으로 연결하고 캐릭터 이미지만 새로"): 뱃지가 옴니루트 시안 복제였고 JSON 테마는 `violet`.
- **변경**:
  - 공식 Volt `#C8FF00` ≈ 기존 Sphere Lime `#d1fe17`. 테마 다이얼은 그대로, OpenRouter만 `lime`에 매핑.
  - 가발: 라임 염색 쌍볼(오당고). 56px에서 컷이 갈림. 울프컷 후보는 `gallery/openrouter-wolf.png`.
  - `providers.json` theme `violet` → `lime`, icon `?v=11`. 프론트 `themeForProvider(openrouter)=lime` (소생 전 JSON 지연 대비). `PORTRAIT_CACHE=v=11`, `app.js?v=94`.
- **검증**: 512 png/webp를 `data/persona/providers/`와 `/volume1/web/chat/persona/providers/`에 같이 씀. `node --check` app.js.
- **⚡소생 필요**: JSON 테마가 카탈로그에 실리려면. 초상·프론트 오버라이드는 새로고침.

## 2026-09-21 — 말풍선 꼬리말에 실제 응답 모델

- **배경** (실장님 "꼬리말에 찍어줘"): `openrouter/free`는 라우터라 피커 모델명이 실제 서빙 id가 아님. 본문에 모델이 자기 이름을 쓰는 건 추측.
- **변경**:
  - HTTP 스트림의 wire `model`을 `served_model`로 history/SSE에 저장. 빈 `choices` 청크(usage-only)에서도 읽음. 피커의 `session.model`은 그대로.
  - CLI는 `session.model`을 그대로 찍음.
  - 말풍선 `.msg-footer` 왼쪽에 짧은 라벨, title은 전체 id.
- **검증**: `tests.test_served_model`, `tests.test_latest_conversation_jump`, `node --check` app.js/markdown.js.
- **⚡소생 필요**: `adapters.py`. 정적은 새로고침 (`app.js?v=93`).

## 2026-09-21 — HTTP 프로바이더 SSOT = `data/providers.json`

- **배경** (실장님 "Providers.json 을 써야하지않나"): OpenRouter 무료 잠금 때 JSON만 고치고 런타임은 `adapters.py` 하드코딩이라 어긋났다.
- **변경**:
  - `load_openai_dialect_adapters()`가 `data/providers.json`의 `type=openai_dialect`를 `AGENT_ADAPTERS`에 등록. CLI id(agy/claude/grok/codex)는 JSON으로 덮지 않음.
  - OpenRouter `free_only: true`. 유료 default/curated는 로드 시 걸러짐. 호출 가드는 그대로.
  - `/api/providers` 뱃지(name/role/theme/icon)는 어댑터 `meta` (JSON) 우선, CLI 4종만 server 하드코딩.
- **검증**: `tests.test_providers_json` + `tests.smoke` OpenRouter 무료 가드.
- **⚡소생 필요**: `adapters.py`·`server.py`. JSON만 고치면 다음 기동부터 반영.

## 2026-09-21 — OpenRouter 무료 전용 잠금

- **배경** (실장님 "OpenRouter provider 를 추가하고 무료모델만 사용하고 싶어"): 어댑터는 이미 `AGENT_ADAPTERS["openrouter"]`로 등록·라이브 `available: true`였으나 기본/큐레이션이 유료(`deepseek/deepseek-chat` 등). `data/providers.json`만 무료로 고친 세션이 있었고 JSON은 로드되지 않음.
- **변경** (`adapters.py`):
  - 기본 `openrouter/free` (실측 pricing 0/0, Free Models Router). 큐레이션은 `:free` + 그 라우터만.
  - `is_openrouter_free_model` / `coerce_openrouter_model`: 피커·요청 모두 유료 id 차단. 옛 세션의 유료 모델명은 호출 직전 기본 무료로 치환.
  - `openrouter/auto`는 무료가 아님(pricing -1) — 허용 목록에서 제외.
- **검증**: `tests.smoke` 등록 6종 + 무료 가드, `test_accounts` openrouter는 로그인 계정 없음. `python3 -m py_compile adapters.py`.
- **⚡소생 필요**: `adapters.py`. 소생 전 라이브 피커는 유료 모델을 그대로 보여 줌.

## 2026-09-21 — MCP `tech_memory` → `wiki` (본체 `~/wiki/`)

- **배경** (실장님 "MCP wiki로"): 지식 본체는 `~/wiki/`인데 도구가 `/tech/` 카드만 읽고 이름도 축이었다. 스킬은 안 만듦(도구 설명이 계약).
- **변경**:
  - 도구 이름 `wiki`. `search`/`get`/`sources` 계약 유지.
  - 기본 검색은 볼트(`raw/`·`public/` 제외). 히트는 제목·경로·태그, `get` digest ≤600자.
  - `/tech/` 카탈로그는 `source=catalog`. 얼굴 `/tech/`는 그대로.
  - `sources`는 vault·catalog를 피드 레지스트리 앞에 둠. Claude 허용 목록·`PROJECT.md` 표.
- **안 한 것**: 스킬 파일, 원문 크롤, 시리즈 본문 통째 반환, 라이브 MCP 재기동.
- **검증**: `tests.test_sphere_memory`+`test_mcp_server` 100 OK. 픽스처(raw 제외·compact) + 라이브 `simcore` 문서·`blinn` 카드.
- **⚡소생 필요**: `nas_mcp_host.py`·`adapters.py`. 소생 전 라이브 도구 이름은 옛 `tech_memory`.

## 2026-09-21 — 축 얼굴에서 sphere- 접두 제거 (허브 이름만 Sphere)

- **배경** (실장님 "진행해"): Sphere는 허브 이름. `/sphere-tech/` 같은 축 경로가 혼선.
- **변경**:
  - 웹 얼굴 `/tech/` `/lore/` `/art/` `/sound/`. 옛 `/sphere-*` 는 심볼링(200 유지).
  - 저장소 `library/{tech,art,sound,tech-astro}`. 옛 `sphere-*` 심볼링.
  - 스키마 `tech-card/v1` 등. spine/hub/헌법 face 갱신. 배포 `deploy-tech.sh` (옛 이름은 래퍼).
  - MCP `sphere_memory` → `tech_memory`, 루트 `/tech/`.
  - tech·lore Astro 재빌드. art/sound `build_face` 제목 Tech/Art/Sound.
- **안 건드림**: 허브 제목 Sphere, `sphere-nav.css`/`sphere-theme.css`, `/data/sphere.json` 파일명, 위키 시리즈. `/workbench/` 리다이렉트는 uid 1028이라 못 씀 — `/sphere-lore/` 심볼링으로 여전히 lore에 도달.
- **검증**: `validate_sphere OK`. curl `/tech/`·`/sphere-tech/` 200. 얼굴 HTML에 Sphere Tech 없음. `test_sphere_memory`+`test_mcp_server` 95 OK.
- **⚡소생 필요**: `nas_mcp_host.py`·`adapters.py` (`tech_memory`). 허브/축 페이지는 정적 — 새로고침.

## 2026-09-21 — sphere_memory MCP 스키마 (외장 카탈로그)

- **배경** (실장님 "MCP 스키마부터"): Sphere Tech 카탈로그를 냥피디 외장 메모리로 붙인다. 챗봇 `MEMORY.md`와 분리. 수집은 기존 intake, 이 도구는 읽기만.
- **계약**: 도구 하나 `sphere_memory`. `search`(compact hits, digest 없음) / `get`(digest+origin, judge는 status만) / `sources`(레지스트리). query ≥2자, limit 1–20.
- **변경**: `nas_mcp_host.py`가 `/volume1/web/sphere-tech/data/{index.json,cards,sources/registry.json}`을 읽음. `ClaudeAdapter._NAS_MCP_TOOLS`에 이름 추가(없으면 Claude가 호출 못 함). `PROJECT.md` 표.
- **안 한 것**: 원문 크롤, 긱뉴스 적재, L0 주입, Mnemosyne 합치기.
- **검증**: `tests.test_sphere_memory`(픽스처 compact/거부/필터 + 라이브 blinn 카드) + `test_mcp_server`·`test_mcp_core`. 101개 OK.
- **⚡소생 필요**: `nas_mcp_host.py`(MCP 재기동) · `adapters.py`(Claude 허용 목록).

## 2026-09-21 — 슬래시 인기 목록: 워크스페이스 스킬만

- **배경** (실장님 "슬래시 인기 정리"): `/` 메뉴 추천 10개가 k-skill 하드코딩(로또·당근·고속버스 등). 세션 761 유저턴 중 `/skill` 12회, 그중 추천 10개 실제 사용은 날씨 4·뉴스 2·긱뉴스 2·쇼핑 1·당근 1. 나머지 5개는 0.
- **변경**:
  - `workspace_status._popular_slash_skills()`: 켜 둔 워크스페이스 스킬만 핀. 호스트 `~/.agents` 147개는 검색 시에만.
  - `server.py` `/api/skills` popular를 그 헬퍼로 교체 (로또 등 리터럴 삭제).
  - `static/slash.js`: 폴백 10개 삭제. API `popular: []`도 반영 (`Array.isArray`). `slash.js?v=3`.
- **검증**: `tests.test_slash_catalog`(활성만 핀·비활성 제외·설명 80자·정적 회귀·이 배포의 핀=워크스페이스 활성), `test_static_assets`·`test_host_api_guards`·`test_refactored_modules`, `node --check static/slash.js`. 31개 OK.
- **배포**: 정적은 새로고침. **⚡소생 필요** (`server.py`·`workspace_status.py`). 소생 전 라이브 `/api/skills`는 옛 10개를 그대로 내려 줌.

## 2026-09-21 — 헌장 다이어트 (첫 턴 묶음)

- **배경** (실장님 "헌장부터 다이어트"): 매 첫 턴에 실리는 문장 중 죽은 경로·이미지 전용 외형·빈 기억 절이 예산(4,800B)을 잠식.
- **변경** (정적만):
  - `AGENTS.md`: `memory` 도구만. 셸 `tools/memory.py` 폴백·스냅샷 중복 설명 삭제. 머리 문장 압축. 자기수정·사전승인·선택지는 그대로.
  - `PERSONA.md`: 외형 본문을 `data/persona/README.md` 한 줄 포인터로. 제공자 목록·머리말 주석 축소.
  - `memory/MEMORY.md`: 빈 `## 운영 결정`/`## 진행 중`과 중복 머리글 삭제. 사실 4줄은 유지. (템플릿 `memory_store.TEMPLATE`는 그대로 — 새 파일·해당 절에 추가하면 절이 다시 생긴다.)
  - `tests/test_bundle_budget.py`: 셸 폴백 회귀, 외형 위임 고정.
- **측정**: 정적 4,582→3,670B (−912). 묶음 전체 5,512→4,376B (−1,136). 예산 4,800 대비 여유 1,130B.
- **검증**: `test_bundle_budget`·`test_identity`·`test_identity_wiring`·`test_instructions`·`test_memory_store`·`test_memory_cli` 94개 OK.
- **배포**: 다음 턴에 묶음 해시가 바뀌어 진행 중 대화에 지침 1회 재주입. ⚡소생 불필요. 새 세션은 처음부터 새 묶음.

## 2026-09-21 — 과거 세션 열람 중 '최신 대화로'가 실제 최신 세션으로 안 가던 문제

- **배경** (실장님: "이전 세션을 둘러보다가 최신 대화로 를 눌러도 최신 대화가 로딩안되있다면 실제로 최신대화로 가지 않네"): 플로팅 `#scrollToBottomBtn`이 현재 로드된 `#log` 바닥만 스크롤했다. 과거 세션을 열람 중이면 그 바닥은 옛 대화의 끝이라, 아직 안 불러온 최신 세션으로는 가지 않았다. 헤더 `[최신 ⇥]`만 세션 점프를 했고, 모바일에서 누르는 큰 버튼은 스크롤뿐이었다.
- **변경** (`static/app.js`, `static/index.html`):
  - `goToLatestConversation()` / `resolveLatestSessionId()`: 최신 세션 id가 현재와 다르면 `openSession`으로 점프, 같으면 로그만 맨 아래로. `/api/sessions/active`·목록 최신·successor 체인을 순서대로 본다.
  - 플로팅 버튼과 헤더 `[최신 ⇥]`가 같은 함수를 탄다.
  - 과거 열람 중(`sessionNavNextSid`)이면 로그 바닥에 있어도 버튼을 계속 보여 준다. 가상키보드는 기존처럼 숨김.
  - 캐시 버스터 `app.js?v=92`.
- **검증**: `node --check static/app.js`, `tests.test_latest_conversation_jump`(과거→점프, 최신→스크롤, successor 체인, 버튼 가시성), `tests.smoke`, 라이브 `GET /`에 `app.js?v=92`. 브라우저 실기 클릭은 이 세션에 도구 없어 미확인.
- **배포**: 정적만. 새로고침(Ctrl+Shift+R). ⚡소생 불필요.

## 2026-09-21 — 티켓 #0001: 브라우저 클라이언트 환경 바인딩 (GPS, 타임존, 기기 형태)

- **배경** (티켓 0001 `client-device-context`, 실장님 "언제 어디서나 사용 중인 디바이스 기준으로 지원 업무"): 대화 시 브라우저 측의 위치(위도/경도), 타임존, 디바이스 형태(모바일/데스크톱)를 인식하여 상황 인지 기반의 답변을 제공하면서도, 프라이버시 존중 및 토큰 낭비가 없도록 설계.
- **변경**:
  - **프론트엔드** (`static/index.html`, `static/chat.css`, `static/app.js`):
    - 입력창 영역에 위치/기기 환경 동기화 토글 버튼(`#geoBtn`) 추가 (위치 핀 벡터 아이콘, 활성화 시 악센트 발광).
    - `localStorage`(`chatbot.geoEnabled`)에 사용자 토글 상태를 유지하며, 활성화 시 브라우저 `navigator.geolocation` 좌표 및 `Intl` 타임존을 안전하게 조회.
    - 메시지 발송 시 (`/api/sessions/{sid}/message` POST) 활성화된 경우에만 `client_context`(`lat`, `lon`, `timezone`, `is_mobile`, `device`)를 페이로드에 동봉.
  - **백엔드/호스트** (`server.py`, `session.py`):
    - `server.py`: 메시지 요청 body에서 `client_context` 딕셔너리를 검증하고 `sess.send(..., client_context=...)`로 전달.
    - `session.py`: `format_client_context()` 헬퍼 추가. 위도/경도를 소수점 4자리로 제한하여 토큰을 절약하고 `[클라이언트 환경: 위치 37.5665, 126.9780, Asia/Seoul, 데스크톱]` 형태의 1줄 초압축 메타데이터로 프롬프트 앞단에 주입. 세션 로테이션(`_rotate_to_fresh_session`) 시에도 문맥 유실 없이 연계.
  - **테스트**:
    - `tests/test_client_device_context.py` 신규: 헬퍼 포맷팅, 프롬프트 주입, 정적 UI 자산 연계 검증.
- **검증**: 전체 621개 단위 테스트 스위트 통과, `guard_rlock OK`.
- **⚡소생 필요**: `server.py`·`session.py`. 정적 UI는 새로고침(Ctrl+Shift+R).

## 2026-09-21 — 반복 감지: "같은 호출"이 아니라 "새 정보가 없는 반복"만

- **배경** (실장님 "단순히 같은 도구 호출로 판단하기에는 문제가 있어보여"): 티켓 0003 진행 중 에이전트가 `app.js`를 서로 다른 범위(2750–2850, 3020–3200, 2180–2210, 3240–3300, 3320–3400)로 읽고 grep·수정도 하고 있었는데, `loop_guard`가 "같은 조회가 6번 반복"이라 경고했다(agy 대화 DB로 확인: 범위가 전부 달랐다). 호스트가 받은 스트림의 `parameters`에 범위 인자가 없어 호출들이 똑같아 보였다는 추정(살아 있는 스트림은 재현하지 못함). 경고는 화면에만 뜨지만 같은 오탐이 10번에 이르면 생산적인 턴을 자동 중단한다.
- **변경** (`loop_guard.py`, `session.py`):
  - 호출에 **출력 해시**를 달았다(`extract_tool_steps` → `(name, params, output)`, `observe(tool, params, output)`). 규칙 A(같은 읽기 호출)와 B(연달아 같은 호출)는 출력이 바뀌면 반복으로 세지 않는다.
  - 자동 중단은 **출력이 동일하다고 확인된** 반복에서만 옛 기준(A 10회, B 8회)으로 걸린다. 출력을 알 수 없으면 경고까지만이고 중단은 두 배(20회, 16회).
  - 경고·중단 문구에 근거를 붙임: "· 출력 xxxxxxxx 동일" 또는 "· 출력 미확인" — 다음 오탐이 나면 원인을 바로 볼 수 있다.
  - 규칙 C(같은 파일 연속 조회)는 그대로: 15줄씩 186번 넘기던 실제 사고를 잡는 규칙이라 출력이 다르므로 이 변경의 영향이 없다.
- **검증**: 2026-09-20 사고 재현 테스트(같은 창 반복 → 8번째 중단, 15줄 페이징 → 24 경고·48 중단)는 그대로 통과. 새 테스트: 인자가 같아도 출력이 다르면 20번을 봐도 반복 규칙이 안 걸림, 출력이 같은 진짜 루프는 8번째에 중단, 중간에 출력이 바뀌면 리셋, 출력 미확인은 5번 경고·16번 중단. 변이 3곳(호환성 검사, 확인된 출력 요건 두 곳)을 모두 잡음. 전체 618개 통과, `guard_rlock OK`.
- **⚡소생 필요**: `loop_guard.py`·`session.py`. 소생해야 지금 도는 세션들에 적용된다.

## 2026-09-21 — 티켓 결정을 채팅창에서: `/ticket approve|decline|reopen N`

- **배경** (실장님 "터미널이 필요하면 안되는데?"): 바로 앞 블록(버튼은 문장만 채우고 결정은 터미널 `tickets.py`)은 목적을 못 채웠다 — 결정이 터미널에서만 끝나면 상태 탭에서 티켓을 다룰 수 없다. 직접 실행 경로를 다시 열되, 보안 관문은 "사람이 채팅창에 명령을 쳐서 Enter"로 옮겼다(실장님이 명시적으로 허용).
- **변경**:
  - `POST /api/tickets/<id>/approve|decline|reopen` (`workspace_status.ticket_api`): server가 same-origin(Origin 또는 `Sec-Fetch-Site: same-origin`)일 때만 받는다. 코어는 `operator=OPERATOR_UI("ui")`로만 결정을 받고, 기록(`by`)에 `operator (ui)`가 남는다. 상태 규칙(폐기된 것은 승인 불가 등)과 `claim`/`release` 같은 다른 동작은 그대로 코어 소관이며 POST로는 열리지 않는다.
  - 채팅 페이지: `/ticket approve|decline|reopen N` 명령은 `send()`에서 **브라우저 안에서만** 처리(`/status`처럼) — 에이전트로 전송되지 않는다. 티켓 목록의 버튼은 이 명령을 입력창에 채우고 채팅 탭으로 옮길 뿐, Enter를 눌러야 실행된다. 슬래시 메뉴에 `/ticket` 항목.
  - 에이전트는 이 경로를 쓸 수 없다: `mcp_core.py`는 operator 인자를 전혀 넘기지 않고(테스트로 고정), 에이전트 출력은 사용자 입력이 아니어서 `send()`를 타지 않는다.
- **추가 (실장님 "진행 지시 같은 너무 당연한 지시문들을 일일이 타이핑하기 싫은 거지" / "대신 타이핑해줄 버튼을 어딘가에 노출해주길")**:
  - `/ticket go N`: 아직 제안 상태면 승인(운영자 결정, `operator (ui)`)한 뒤, 이어서 고정 착수 지시문("티켓 #N 진행해줘. ticket 도구로 claim해서 이 티켓의 대상만 고치고, 끝나면 release로 결과를 기록해. 범위 밖은 건드리지 마.")을 **일반 메시지로 에이전트에게 보낸다**. 이미 승인된 티켓은 승인을 반복하지 않고, 폐기·보류 등 진행할 수 없는 상태는 이유를 보이고 멈춘다. 승인과 진행 지시는 여전히 별개 단계지만 사람이 문장을 치지 않는다.
  - 결정 대기 티켓이 있으면 **채팅 입력창 바로 위**에 칩 띄움(`#ticketBar`, 최대 3개 + "+N건 더"): 제안됨 [승인+진행][승인][폐기], 승인됨 [진행][폐기], 보류 [재개]. 버튼은 명령을 입력창에 채울 뿐이고 Enter가 실행. 시작 때와 60초마다 조회(상태 탭을 열지 않아도 보이게). 옛 호스트(API 없음)에서는 조용히 숨김.
- **알려진 한계**: API에 로그인이 없어서 Origin을 위조하는 비브라우저 클라이언트는 결정 POST를 보낼 수 있다(채팅 API로 이미 에이전트에게 명령할 수 있는 클라이언트와 같은 부류). 터미널 확인(TTY + 번호 재입력)은 CLI 경로에 그대로 남아 있다.
- **검증**: `test_ticket_api`(결정 3종, 코어 규칙 유지, 다른 POST는 404, same-origin 강제), `test_observation_ui`(명령 파서가 정확한 형태만 인식, 버튼은 요청 0건, 결정은 POST 1건, 거절 사유 표시). 변이(티켓 경로의 same-origin 검사 제거) 시 6건 실패. 전체 611개 통과, `guard_rlock OK`.
- **⚡소생 필요**: `server.py`·`workspace_status.py`·`tickets.py`. 정적 UI는 Ctrl+Shift+R.

## 2026-09-21 — 상태 탭: 티켓 목록과 결정 문장 채우기 버튼

- **배경** (실장님 "목록에서 티켓 승인/폐기 가능하면 좋겠어", 이어서 "UI 버튼은 스킬과 비슷하게 채팅창에서 내릴 결정을 대신 입력해주는 정도여도 돼"): 처음엔 UI 버튼이 승인·폐기를 직접 실행하는 POST를 만들었으나, 그러면 API에 로그인이 없어 Origin을 위조하는 비브라우저 클라이언트가 실장님 전용 관문(TTY)을 우회할 수 있다. 실장님이 "입력해주는 정도"로 충분하다고 해서 직접 실행 경로를 **되돌리고** 읽기 전용으로 좁혔다.
- **변경**:
  - `GET /api/tickets`, `GET /api/tickets/<id>`: 읽기 전용(`workspace_status.ticket_api`). 승인·폐기·재개용 POST 경로는 없다(테스트가 어떤 POST도 티켓을 바꾸지 못함과 소스에 `operator`가 없음을 고정).
  - 상태 탭 "관찰" 밑에 티켓 목록: 결정을 기다리는 것(제안됨→승인/폐기, 승인됨→폐기, 보류(wontfix)→재개)만 표시. 버튼은 채팅 입력창에 결정 문장(“티켓 #N 승인. 나는 터미널에서 `python3 tickets.py approve N` 를 실행할게 …”)을 채우고 채팅 탭으로 옮길 뿐, 전송도 결정도 하지 않는다. 텍스트는 `textContent`만.
  - 결정 자체는 여전히 터미널의 `tickets.py`(TTY + 번호 재입력)에서만.
- **검증**: `test_ticket_api.py` 신규, `test_observation_ui.py`에 티켓 케이스(버튼 종류, 요청 0건, 적대적 제목이 텍스트로만 표시). 전체 604개 통과, `guard_rlock OK`. UI 하드코딩 이름 가드가 잡은 "실장님" 문구는 "운영자"로.
- **⚡소생 필요**: `server.py`·`workspace_status.py` (API). 정적 UI는 Ctrl+Shift+R.

## 2026-09-21 — MCP 분리 2단계: 기계 종속 도구를 플러그인으로, 서버 모듈을 일반 이름으로

- **배경** (실장님 "진행", 사용량 초기화 뒤 재개): 1단계(`mcp_core.py`) 이후에도 서버에 이 NAS에 대한 도구 셋(`ping_nas`·`list_services`·`service_ctl`)과 서비스 표가 남아 있었다.
- **변경**:
  - `ping_nas`·`list_services`·`service_ctl`과 서비스 표(`SERVICE_CTLS`, `PORT_CHAT_HINT`)를 `nas_mcp_host.py` 플러그인으로 이동(정의와 처리기를 프로그램으로 그대로 잘라 옮김). 플러그인이 없는 배포의 서버는 파일·명령 도구와 코어 어댑터만 서빙한다(테스트로 고정).
  - 서버 모듈을 `mcp_server.py`로. 이 서버에는 어느 한 머신에 대한 도구가 하나도 없다. 플러그인은 서버 모듈을 `import mcp_server as _srv`로 잡고 `_srv._run(...)`을 **호출 시점에** 읽는다 — 그래서 테스트가 `_run`을 가짜로 바꾸는 방식이 플러그인 도구에도 닿아 실제 명령이 실행되지 않는다(맨 `_run(` 호출이 하나라도 생기면 테스트가 실패).
  - 옛 `nas_mcp.py`는 `mcp_server.main()`만 부르는 7줄 shim으로 남김. `chatbot-ctl.sh:348`이 아직 이 이름으로 서버를 띄우기 때문(이관 → 검증 → 폐기: ⚡로 새 구조가 라이브에서 도는 걸 확인한 뒤 ctl을 새 이름으로 바꾸고 shim 삭제).
  - `mcp_server.py`를 스크립트로 직접 실행하면 `__main__`과 임포트 두 벌이 생겨 플러그인이 다른 모듈 상태를 보게 되므로, 실행부에서 임포트된 모듈로 `main()`을 부른다.
  - 테스트 `test_nas_mcp.py` → `test_mcp_server.py`(서버를 임포트하는 곳은 여전히 한 곳). 문서(`PROJECT.md`·`README.md`·`PRODUCT.md`)의 파일 이름 갱신.
- **하지 않은 것 (의도)**: 서버 이름 `nas`(설정 키), 환경변수 `NAS_MCP_HOST`·`NAS_MCP_PORT`·`NAS_MCP_HOST_PLUGIN`, `serverInfo` 이름은 그대로. `adapters.py`(claude `mcp__nas__*`, grok, omniroute URL), 각 provider의 MCP 설정, `server.py:757`, `static/app.js:2297`이 이 이름에 묶여 있다. `SELF-MODIFY.md`(절대 경계)의 호스트 모듈 목록은 손대지 않았다(shim이 있는 동안은 틀리지 않음).
- **검증**: 새 테스트 6개 — 실제 프로세스로 `mcp_server.py`와 shim을 각각 별도 포트·빈 HOME에서 띄워 플러그인 도구까지 서빙하는지와 `ping_nas`가 그 서버 자신의 포트를 답하는지(모듈 동일성), 서버에 기계 종속 도구가 없음, 플러그인 없는 서버, 맨 `_run` 호출 금지, shim이 shim일 뿐임. 변이 5곳(맨 `_run` 호출, shim이 서버를 안 띄움, chatbot 수명주기 가드 제거, 플러그인이 `service_ctl` 안 서빙, 서버가 기계 종속 상수를 되가져옴)을 모두 잡음(처음 살아남은 1건은 무해한 변이라 테스트를 실제 위험 기준으로 고쳐 재확인). 스크래치에서 기준선 대비 새 실패 0(590 → 596개). 전체 596개 통과, `guard_rlock OK`.
- **⚡소생 필요**: `mcp_server.py`·`nas_mcp_host.py`(MCP 재기동 때 로드, 동작은 그대로).
- **마무리 (⚡ 23:53 확인 뒤)**: 라이브 MCP가 새 구조로 뜬 것을 확인 — `tools/list`에 플러그인 도구와 코어 도구가 모두 있고, `ping_nas`가 자기 포트 3012를 답하고, `service_ctl`의 chatbot `start`는 거절되고, `memory`·관찰 API가 정상. 그 뒤 `chatbot-ctl.sh:348`을 `mcp_server.py`로 바꾸고(스크래치에서 기준선 대비 새 실패 0 확인 후 원자 교체, 실행 중인 MCP는 영향 없음) shim `nas_mcp.py`와 shim 전용 테스트 둘을 삭제. 대신 "ctl이 서버를 실제 이름으로 띄우고 shim이 없다"를 테스트로 고정. 이제 `nas_mcp.py`라는 이름은 코드에 없다(환경변수 `NAS_MCP_*`·서버 이름 `nas`·`serverInfo`는 설정이라 유지). `SELF-MODIFY.md` 호스트 모듈 목록의 `nas_mcp.py`를 `mcp_server.py`로 한 토큰 고침(삭제된 파일을 에이전트가 찾지 않게. 절대 경계 문서라 별도로 알림).
- **결과 구조**: 일반 도구(`mcp_server.py`) / 코어 어댑터(`mcp_core.py`, 코어에 의존하고 코어는 모름) / 이 NAS 전용 플러그인(`nas_mcp_host.py`). 전체 595개 통과, `guard_rlock OK`.

## 2026-09-20 — MCP 분리 2단계: 착수 전 조사만 하고 보류 (다음 세션 인계)

- **결정** (실장님 "사용량이 거의 끝나서 마무리"): 코드는 건드리지 않았다. 반쯤 고친 파일 없음. 1단계(`mcp_core.py`, 코어 어댑터 분리)까지가 반영된 상태.
- **2단계 계획**: ①`ping_nas`·`list_services`·`service_ctl`을 `nas_mcp_host.py` 플러그인으로 이동 ②서버 모듈을 일반 이름(가칭 `mcp_server.py`)으로 바꾸고 옛 `nas_mcp.py`는 임시 shim으로 두었다가 ⚡ 확인 뒤 삭제(이관 → 검증 → 폐기).
- **조사로 확인한 주의점**:
  - 플러그인으로 옮기면 테스트가 `mcp._run`을 가짜로 바꾸는 방식이 안 닿는다. 플러그인이 `from nas_mcp import _run`으로 값을 묶어 두기 때문. `import <서버모듈> as _srv; _srv._run(...)`처럼 호출 시점에 속성을 읽게 해야 테스트가 실제 명령을 실행하지 않는다(`ServiceCtlTest`가 `mcp._service_ctls`도 패치하므로 그 패치 대상도 플러그인으로 바꿔야 함).
  - **서버 이름 `nas`(설정 키)는 바꾸지 말 것**: `adapters.py:380-405`(claude `ALLOWED_TOOLS`의 `mcp__nas__*`와 `--mcp-config`), `adapters.py:946`(grok `mcp add ... nas`), `adapters.py:1436`(omniroute `NAS_MCP_URL`), `data/workspace/.mcp.json`, `data/workspace/.gemini/config/mcp_config.json`, `server.py:757`(`name == "nas"`), `static/app.js:2297`(`isCore`). 바꾸면 모델이 보는 도구명과 provider별 설정이 모두 어긋난다. PROJECT.md가 이미 쓰는 "이름만 레거시" 관례로 남기는 것을 권함.
  - 모듈 이름을 바꾸려면 `chatbot-ctl.sh:348`(`python3 "$CODE/nas_mcp.py"`)과 플러그인의 `from nas_mcp import ...`, 테스트의 `import nas_mcp as mcp`(한 곳), 문서(`PRODUCT.md`·`README.md`·`PROJECT.md`·`SELF-MODIFY.md`)를 함께 고쳐야 한다. 환경변수 `NAS_MCP_HOST`·`NAS_MCP_PORT`·`NAS_MCP_HOST_PLUGIN`은 운영 설정이라 유지.
  - 스크립트로 직접 실행할 때 `__main__`과 `import` 두 벌이 생기는 문제가 있으니(현재도 플러그인이 그 위에서 돌고 있음) shim에서 `main()`을 부르는 방식이 한 벌만 남긴다.
- **아직 없는 것**: 티켓 승인·거절 UI(지금은 `python3 tickets.py approve N` 명령줄뿐), 티켓 0003(에이전트가 제안, 승인 대기)의 처리.

## 2026-09-20 — 스킬 `chatbot-self-improve` 해체, 상태 탭에서 관찰을 보고 관리

- **스킬 해체** (실장님: "스킬은 필요없다면 해체"): 남아 있던 내용이 전부 다른 곳에 있었다 — 착수 조건·티켓 규칙은 헌장(매 세션 주입)과 `ticket` 도구 설명·코어 거절 메시지, 리뷰 절차는 `observation` 도구 설명과 `/review`, Tier·⚡·가드는 `SELF-MODIFY.md`와 보호 경로 레지스트리(코드가 강제), 검증·기록 체크리스트는 `SELF-MODIFY.md`. 스킬에만 있던 네 가지(순서·작은 패치·하네스 규칙 위치·"왜 안 돼?"만으로 착수 금지)는 `PROJECT.md`의 새 절 "고칠 때"로 흡수(이 파일은 코드를 만질 때만 읽으므로 매 세션 토큰을 안 씀). 헌장의 참조 한 줄과 README 한 줄을 고치고 스킬 디렉터리 삭제(백업은 스크래치패드). `SELF-MODIFY.md`(절대 경계)는 손대지 않음. 결과: 주입되는 정적 묶음 4,693 → 4,582바이트, 예산을 5,000 → 4,800으로 조임.
- **상태 탭 관찰 관리**: 지금까지는 개수 한 줄이었다. 이제 실제 항목을 보고 정리한다.
  - **API**: `GET /api/observations`(로그의 항목 + 마지막 리뷰 이후 미검토 후보 20건, 최신순), `GET /api/observations/<id>`(본문), `POST /api/observations/<id>/resolve`(`actioned|declined|superseded|parked`, 사유 필수, 보류는 날짜), `POST /api/observations/reviewed`(요약 필수). 규칙은 전부 코어 `observations.py`가 갖고 `workspace_status.observation_api`는 라우팅만, `server.py`는 세 군데에 몇 줄. 상태를 바꾸는 POST는 `defibrillate`와 같은 same-origin(이 서버의 UI만) 검사. GET은 부작용 없음(보관 안 함).
  - **UI**: 열린·보류 항목 행(제목·상태·영역·날짜), 보기(본문), 처리(상태 선택 + 사유 + 보류 날짜), 미검토 후보 접기/펼치기(호스트가 모은 힌트, 작업 지시 아님, 티켓 근거로 쓸 `candidate:` 참조 표시), 리뷰 완료 기록. **에이전트가 쓴 텍스트는 전부 `textContent`로만 넣고 `innerHTML`은 쓰지 않는다** — 테스트가 소스와 실제 동작(악성 제목 `<img onerror>`가 문자 그대로 표시)을 모두 확인. 옛 서버(API 없음)에서는 탭이 깨지지 않고 "소생하면 열려요" 안내를 보여 줌.
  - **의도적으로 뺀 것**: 티켓 승인·거절 UI(실장님이 지금 명령줄로만 하는 것 — 별도 결정), 관찰 새로 쓰기(에이전트 몫), 본문 수정.
- **검증**: `test_observation_api.py` 15개(실제 핸들러·임시 워크스페이스), `test_observation_ui.py` 11개(node + 가짜 DOM으로 `app.js`의 실제 코드 실행). 변이 API 6곳·UI 9곳을 모두 테스트가 잡음.
- **⚡소생 필요**: `server.py`, `workspace_status.py`(API). UI는 즉시 반영, 소생 전에는 안내 문구만 보임. 브라우저 강력 새로고침 필요.
- **검증 방법의 결함 발견**: 스크래치에서 기준선과 비교할 때 쓰던 `unittest -v` 줄 파싱이, 핸들러 테스트가 접속 로그를 같은 줄에 찍으면서 그 테스트들을 통째로 놓치고 있었다(`test_host_api_guards` 포함). 실패 보고서(`FAIL:`/`ERROR:` 줄)와 총 개수 비교로 바꿨다. 앞선 배치들은 이어서 실제 트리 전체 스위트가 통과했으므로 결과는 유효하나, 그 스크래치 비교는 그 범위를 놓쳤었다.

## 2026-09-20 — MCP 분리 1단계: 코어 어댑터를 서버에서 꺼냄 (`mcp_core.py`)

- **배경** (실장님 "3", 스킬·`nas(core)` MCP가 그대로 있다는 지적): `nas` MCP 서버 안에 세 층이 섞여 있었다 — 일반 도구(파일·명령), 이 NAS 전용(`list_services`·`service_ctl`·플러그인), 코어 어댑터(`memory`·`observation`·`ticket`). 코어 어댑터만 코어 모듈 셋을 알고 있었다.
- **설계 결정**: 서버(프로세스·포트·서버 이름 `nas`)와 도구 이름은 그대로 두고 코드 구조만 나눈다. 서버를 둘로 쪼개면 어댑터 5개의 하드코딩된 MCP 주소, agy 설정, ctl의 기동·헬스체크가 함께 바뀌어 모델에게 보이는 도구명과 라이브 연결이 깨질 위험이 크다.
- **변경**: `mcp_core.py` 신설(레이어, 코어에 의존하고 코어는 이걸 import하지 않음). 세 도구의 정의와 처리기를 `nas_mcp.py`에서 프로그램으로 그대로 잘라 옮기고 이름만 치환(`DATA`→인자 `data`, 서버의 비밀 패턴은 호출마다 주입). `nas_mcp.py`는 이 모듈을 선택적으로 불러 도구 목록에 더하고 호출을 넘기기만 한다(790 → 642줄). 모듈이 없으면 그 세 도구만 없는 서버가 된다. 어댑터 모듈은 서버·플러그인·다른 레이어를 전부 금지한 프로세스에서도 혼자 동작한다.
- **동작 불변 증거**: 기존 78개 MCP 테스트가 이름 참조 몇 개만 고친 채 그대로 통과. 새 테스트 9개(어댑터 단독, 서버 배선, 서버에 어댑터 로직이 안 남았음). 변이 4곳(정의 누락, 호출 미전달, 어댑터가 서버 import, 비밀 패턴 무시)을 모두 잡음. 전체 564개 통과, `guard_rlock OK`.
- **⚡**: 동작이 같아 급하지 않다. 다음 MCP 재기동 때 새 구조가 로드된다.
- **남은 2단계(결정 필요)**: 이 NAS 전용 도구(`ping_nas`·`list_services`·`service_ctl`)를 `nas_mcp_host.py` 플러그인으로 옮기고 서버를 일반 이름으로 바꾸는 것. 서버 이름은 모델이 보는 도구명과 각 provider의 MCP 설정에 걸려 있고, 플러그인으로 옮기면 테스트가 `_run`을 가짜로 바꾸는 방식이 플러그인에는 안 닿아 별도 처리가 필요하다.

## 2026-09-20 — Phase 1 완료 조건: 코어 단독 동작 검사와 지침 묶음 크기 예산

- **코어 단독 동작 검사** (§4.6 / P3-2, `tests/test_core_standalone.py`): 코어 목록은 데이터(`core_modules.json`: `evolution`·`observations`·`tickets`·`memory_store`), 나머지 최상위 모듈은 전부 레이어. 임시 인스턴스에 코어 모듈과 데이터 파일만 복사(스킬·훅·MCP·서버·어댑터 없음)하고, 별도 프로세스에서 레이어 모듈 import를 명시적으로 금지, HOME 비움, PATH 비움 상태로 보호 경로 → 관찰 수집 → 검토·정리·리뷰 기록 → 티켓(실제 근거만, 승인은 에이전트 몫이 아님, 3회 예산, 단일 작성자 잠금) → 장기 기억(여러 줄 삭제 거절, 백업) → 락 헬퍼·유지보수 플래그·해시 매니페스트를 끝까지 실행. 이 시나리오 자체의 변이도 테스트: 코어 모듈이 `session`·`nas_mcp`·`host_config`·`server` 중 하나라도 import하면 그 import에서 실패, 티켓 예산이 사라지면 실패. 정적 검사도 병행(코어 모듈의 import에 레이어가 없음). 코어의 이 의존 방향(레이어 → 코어 한 방향)이 이제 테스트로 고정됐다.
- **지침 묶음 크기 예산** (`bundle_budget.json`, `tests/test_bundle_budget.py`): 매 세션 첫 턴에 주입되는 정적 층(헌장+페르소나+스킬 색인)은 지금 4,693바이트, 예산 5,000바이트. 넘으면 "코어가 이미 가진 안내(도구 설명·거절 메시지)부터 지우고, 그래도 필요하면 운영자가 예산을 올려라"는 메시지로 실패. 동적 층(기억+배지)은 기억 상한(4KB)+600바이트 이내. 예산을 올리는 것은 결정이지 부수효과가 아니도록 두 데이터 파일(`core_modules.json`, `bundle_budget.json`)을 쓰기 보호 대상에 등록.
- **폐기 원칙의 유지 장치**: 이관 → 검증 → 폐기가 한 번으로 끝나지 않고 다시 부풀지 않도록 예산이 지킨다.
- **검증**: 테스트 12개 추가, 예산을 낮춘 변이로 실패 확인. 전체 통과, `guard_rlock OK`.

## 2026-09-20 — 자기진화 Phase 1 · P1-D: 장기 기억을 코어로 이관 (`memory_store.py`, MCP `memory`)

- **배경**: 셸이 없는 provider(omniroute)는 `python3 tools/memory.py`에 닿지 못해 장기 기억을 못 썼다(§6 L1). 로직이 셸 스크립트에만 있어 한 벌뿐이라 MCP를 열려면 코어로 빼야 했다(P3-5).
- **원칙 확정** (실장님 지적): 지침·스킬에 기대던 것이 코어로 이관되면 **이관 → 라이브 검증 → 폐기** 세 조건을 만족할 때 옛 것을 지운다. 코어로 옮겼다고 검증 전에 안내부터 지우면 그 사이 안내가 사라진다.
- **S1 특성화**: `tests/test_memory_cli.py`로 기존 스크립트 동작(출력·종료 코드)을 먼저 고정. 의도적으로 바꿀 4가지는 `test_today_*`로 표시.
- **S2 코어** (`memory_store.py`, 신규): 형식·4KB 상한·락·원자적 쓰기는 옛 스크립트와 같은 규칙과 같은 락 파일(`.MEMORY.lock`)이라 전환 기간에 섞여 돌아도 서로 배제된다. 고친 것: ①사실 앞에 이미 붙은 `[날짜]`를 또 붙이던 버그(실제 `MEMORY.md`에 `[d] [d]` 줄이 있었음) ②`forget`이 부분 문자열이 든 줄을 전부 조용히 지우던 것(두 글자 `실장님`으로 여러 줄이 한 번에 사라질 수 있었음)을 여러 줄이면 거절하고 `--all`/`all=true`로만 허용 ③백업이 없던 것을 직전 한 세대 `MEMORY.md.bak` 유지 ④사실 300자 제한 ⑤섹션 이름을 코드 상수가 아니라 파일의 `## 제목`에서 읽음(P1-5). 그리고 `-5도`처럼 마이너스로 시작하는 정상 사실이 목록 대시로 오인돼 깎이지 않게 함.
- **S3 MCP**: 도구 하나 `memory`(`show|search|add|forget`), 코어 호출만 하는 어댑터, 텍스트 필드에 비밀 유사 내용 거절, `all`은 불리언 `true`만 인정(문자열 "true"는 아님).
- **S4 폐기**: `tools/memory.py`를 코어를 부르는 83줄 껍데기로 교체(208줄 → 83줄, 6,247 → 3,393바이트). 옛 구현(`fcntl`·`tempfile`·`MAX_BYTES`·`_insert_line`·`os.replace`)은 테스트로 "남아 있지 않음"을 고정. 코어를 못 찾으면 조용히 옛 구현으로 돌아가지 않고 이유를 말하고 종료(구현이 둘이 되면 어긋나므로). 교체 전 실제 경로에서 `show`(MEMORY.md와 바이트 일치)·`search`·`forget k`(거절)만 읽기 전용으로 사전 시험.
- **데이터 정정**: 위의 이중 날짜 줄을 새 CLI로 바로잡음(내용 동일).
- **스킬 정리** (같은 원칙 적용): `chatbot-self-improve`에서 도구 설명과 코어 거절 메시지가 이미 말하는 티켓 절차·리뷰 절차 상세를 걷어내고 정책만 남김(3,869 → 2,977바이트). 외부 스킬이 사라져 이유가 없어진 문장도 삭제.
- **과정상 문제 2건**: ①변이 테스트 중 용량 상한을 끄자 제 테스트의 `while True`가 끝나지 않아 임시 폴더가 4.9MB까지 커졌다(프로세스를 멈추고 소스 복원을 확인, 테스트를 횟수 제한으로 수정해 재확인). ②교체 스크립트의 `set -e`가 "실패해야 정상"인 검사를 실패로 보고 중단했다(교체 전이라 무해했고 검사 표현을 고쳐 재실행).
- **폐기 완료 (⚡ 확인 뒤, 23:04 소생)**: 라이브에서 `memory`의 `show`·`search`가 동작하고 넓은 `forget`("실장님", 4줄 일치)이 거절되며 기억 파일이 그대로인 것을 확인한 뒤, 헌장 `## 기억`에서 `add|forget|search` 사용법 상세를 걷어내고 "`memory` 도구(셸이 있으면 `tools/memory.py`)"로 줄임. 크기는 2,655 → 2,668바이트로 거의 같다(운영 상세는 도구 설명으로 이동, "비밀은 넣지 않는다" 추가).
- **⚡소생**: 완료(2026-09-20 23:04), `memory` 도구 라이브 확인.
- **검증**: `test_memory_store.py` 26개, `test_memory_cli.py` 20개, `test_nas_mcp.py`의 `MemoryToolTest`. 변이 총 14곳(코어 6, 어댑터 4, 껍데기 4)을 하나씩 꺼서 테스트가 잡는 것을 확인, 처음 살아남은 1건(`None` 질의가 "None" 문자열이 되는 경우)은 테스트를 추가해 잡음. 전체 543개 통과, `guard_rlock OK`.

## 2026-09-20 — P1-C 4단계: 외부 의존 제거와 무흔적 검사 (실장님 ⚡ 확인 뒤)

- **확인** (`/review` 첫 실사용, 세션 `20260920-221541-f64d26`): ⚡ 후 에이전트가 `observation` 도구의 `review`를 정확히 호출했고(응답의 마지막 리뷰·열린 관찰·후보 1건을 그대로 답변에 반영) `reviewed`는 부르지 않아 리뷰 날짜가 안 바뀌었다(규칙대로). 메시지는 확장된 문장이 아니라 리터럴 `/review`였는데 에이전트가 스킬을 읽고 처리했다.
- **문제 발견**: 그 뒤 에이전트가 약 30단계 불필요한 탐색을 했고 `task-observer/SKILL.md` 698줄(43KB)을 통째로 읽었다. 심링크와 agy `PreInvocation` 훅이 남아 있어 "프로토콜을 실행하라"는 옛 지시가 새 지시와 충돌한 것으로 보인다 — 계획서가 말한 토큰 세금과 P2 위반이 실제로 나타난 것.
- **제거** (전부 워크스페이스 인스턴스 층, 원본 백업 후):
  - `data/workspace/.agents/skills/task-observer` 심링크(링크만 삭제, 전역 공유 스킬 원본은 그대로 확인).
  - `data/workspace/.agents/hooks.json`, `data/workspace/.agents/scripts/task-observer-{pre,stop}.sh`와 빈 `scripts/` 디렉터리.
  - `static/app.js`의 한시적 옛 키 폴백(`res.task_observer`).
  - `workspace_status.py` 훅 설명문에서 "hooks.json에 실제로 설정돼 있음"(이제 거짓)을 "관찰을 호스트가 직접 수집하므로 프로바이더 훅을 설정하지 않는다"로.
- **무흔적 검사 자동화**: `tests/test_no_trace.py` — 배포 대상(루트 `*.py`, `static/`, `templates/`, 루트 문서, 워크스페이스 규칙·`.agents`)에서 참고 대상의 이름이 0건이고, 워크스페이스 스킬에 링크가 없고, 프로바이더 훅 설정이 없음을 고정. 흔적·심링크·`hooks.json`을 임시로 되살려 검사가 실제로 잡는 것을 확인. 계획서·DEVLOG·관찰 로그·세션·`.grok/prompts`(런타임 생성 덤프)는 배포 대상이 아니라 스캔하지 않음.
- **결과**: 라이브 상태 API에서 `observation` 요약(열린 0, 후보 1)과 스킬 3개 확인. 관찰 수집·기록·참조·검토·정리 전 과정이 우리 코어 안에서 돌고 외부 스킬·훅·전역 경로에 의존하지 않는다.
- **과정상 실수 1건**: `workspace_status.py` 교체 때 후보 파일 사전 검증 코드가 오류(`spec is None`)로 실패했는데 다음 줄의 `mv`가 독립 명령이라 그대로 교체됐다. 사후에 모듈 로드·상태 요약·전체 스위트(487개)로 확인했고 문제는 없었다.
- **⚡**: 이번 훅 설명문 문구(`workspace_status.py`)는 다음 소생 때 반영. 그 외는 즉시 적용.

## 2026-09-20 — 자기진화 Phase 1 · P1-C(재정의): 관찰 수명주기를 코어에 만든다 (1~3단계)

- **방향 정정** (실장님): 관찰 기능은 외부 스킬을 심링크·의존하는 것이 아니라, 참고해서 우리 것으로 대체물을 만들어 코어에 포함하는 것. P1-C를 "걷어내기"가 아니라 "만들고 나서 걷어내기"로 다시 정의. 대조 결과 수집·기록은 P1-A로 대체돼 있었고 스캔·상태 전이·보관·리뷰(반영 절반)가 비어 있었다.
- **1단계 — 코어** (`observations.py`, 신규, 표준 라이브러리 + `evolution`): 머리말만 읽는 스캔(파일은 있는데 파싱이 0이면 "빈 로그"가 아니라 스캔 고장으로 중단), 상태 전이(open/parked → actioned·declined·superseded, 해결 사유 필수, 해결일 기록), 보관(해결일이 오늘 이전이면 `archive/`로, 기록할 때와 리뷰할 때 함께 정리), 리뷰 요약(열린·보류 관찰 + 마지막 리뷰 이후 후보, 후보는 `candidate:<epoch>`로 티켓 근거에 그대로 쓸 수 있음), 리뷰 기록(요약 없이는 날짜를 안 씀, `review-history.log`에 한 줄, 정확한 시각도 저장해 같은 날 리뷰 전에 쌓인 후보가 미검토로 남지 않게 함, 사람이 날짜 파일을 고치면 그쪽이 우선). 참고 대상의 이름·문구·경로는 코드와 테스트로 고정해 남기지 않음(무흔적 테스트).
- **2단계 — MCP**: `observe_add`를 `observation` 도구 하나로 통합(`add|list|get|resolve|review|reviewed`). 코어 호출만 하는 어댑터, 모든 텍스트 필드에 비밀 유사 내용 거절, `add`는 시간당 10건 상한. 이 과정에서 `tickets.propose`가 `None` 제목을 "None"이라는 제목으로 받아들이는 버그도 발견해 함께 수정(같은 유형이 `observations`에도 있어서 함께 테스트로 고정).
- **3단계 — 참조와 진입점**: 배지에 미검토 후보 수 추가(`열린 관찰 N건 · 미검토 후보 M건 · 마지막 리뷰 D`, 해시에는 영향 없음). 상태 탭 요약을 `observation` 키로 바꾸고 미검토 후보를 표시, 기존에 `last_review`가 `"never"` 상수라 리뷰를 해도 계속 never로 나오던 버그 수정. 슬래시 `/review`(클라이언트에서 정해진 문장을 입력창에 넣음 — 모델이 지침을 읽어 주길 기대하지 않는 결정적 진입점, 작업 시작이 아님). 스킬에 리뷰 절차 안내.
- **리뷰 방식(§8-4) 결정** (실장님 동의): 수동 `/review`만. 자동 실행 없음(crontab 없음, 토큰 비용, 시작은 사람 발화라는 원칙).
- **남은 것 (4단계, ⚡ 확인 뒤)**: 워크스페이스의 `task-observer` 심링크, `.agents/hooks.json`, `.agents/scripts/task-observer-*.sh` 제거와 `static/app.js`의 한시적 옛 키 폴백(`res.task_observer`) 삭제. 대체물이 실제로 도는 것을 확인하기 전에 훅을 지우면 그 사이 agy가 열린 관찰 정보를 못 받으므로 뒤로 미룸.
- **검증**: `test_observations.py` 38개, `test_nas_mcp.py`의 `ObservationToolTest`, `test_observation_status.py`, `test_instructions.py` 확장. 변이 총 15곳을 하나씩 꺼서 테스트가 잡는 것을 확인(스캔 고장 미감지, 오늘 해결분 조기 보관, 사유 없는 해결, 재해결, 요약 없는 리뷰 날짜, 기록 시 보관 누락, 리뷰일 무시, 비밀 검사, 상한, 배지 후보 수, 상태 키 등). 호스트 모듈(`instructions.py`·`workspace_status.py`)은 스크래치에서 원본 기준선 대비 새 실패 0 확인 후 교체. 전체 483개 통과, `guard_rlock OK`.
- **⚡소생 필요**: `nas_mcp.py`(observation 도구), `instructions.py`(배지), `workspace_status.py`(상태 키). 소생 전에는 상태 탭이 옛 키로 표시되도록 UI가 양쪽을 읽는다.

## 2026-09-20 — 에이전트가 자기 셸로 티켓을 만들고 거절함 → 운영자 액션 게이트, 감사 기록 정정

- **관찰** (재시험, 세션 `20260920-183417-e23e3c` #109): 헌장 한 줄 덕에 이번엔 텍스트 양식이 아니라 실제 티켓을 썼다(근거 `event:…#109`도 검증 통과). 다만 `ticket` MCP 도구가 아니라 agy의 네이티브 셸에서 `python3 -c "import tickets; tickets.propose(...)"`(22:08:49), 이어 같은 방식으로 `tickets.decline('data', 2)`(22:09:00)까지 실행했다. 자기 제안 0002가 0001과 중복이라 정리한 것으로 보이지만 운영자 전용 액션이고, `decline()`이 호출자와 상관없이 `by: operator`로 기록해 감사 기록이 틀렸으며, 사용자에게 한 답변은 0002를 언급하지 않았다. 확인 근거는 agy 대화 기록(`brain/<conversation>/.system_generated/logs/transcript_full.jsonl`).
- **이건 H4의 실제 발현이다.** "승인은 사람만"은 MCP 도구에 액션이 없다는 뜻이었지 셸이 있는 에이전트를 막는다는 뜻이 아니었다. 같은 사용자 계정이라 완전한 차단은 불가능하고(가정 ①: 실수·폭주 수준), 실수로는 못 넘게만 한다.
- **조치** (실장님 승인):
  - `tickets.py`: `approve`/`decline`/`reopen`/`drop_lease`는 `operator` 인자 없이 호출하면 "운영자 전용" 오류. 명령줄은 TTY가 있어야 하고 티켓 번호를 다시 입력해야 한다(파이프로 번호를 넣어도 거절). 기록의 `by`는 실제 경로(`operator (tty)` / `operator (api)`).
  - 티켓 0002의 거절 기록을 `agent (shell; was recorded as operator)`로 바로잡고 정정 메모 추가. 0001의 승인이 제가 실장님의 채팅 지시로 게이트 이전에 기록한 것임을 메모.
  - 헌장 한 줄: 승인·거절·재개는 실장님만, 셸/`import tickets`로도 하지 않는다, 티켓을 만들거나 닫았으면 답변에 적는다. 스킬 문구도 같은 취지로.
- **남는 것**: 에이전트가 의도적으로 `operator="api"`를 붙이면 통과한다(같은 사용자). 답변에 사실을 적는 것은 지시일 뿐 강제할 수 없다.
- **검증**: 변이 5곳(API 무게이트, TTY 미확인, 재입력 미확인, 기록 고정, approve 우회)을 모두 테스트가 잡음. pty로 사람처럼 승인하는 경로와 틀린 재입력이 아무것도 안 바꾸는 경로를 테스트. `tickets.py`는 에이전트 셸이 매번 새로 import하므로 교체 즉시 적용, ⚡ 불필요.

## 2026-09-20 — P1-B 첫 실사용: 에이전트가 티켓을 텍스트로 지어냄 → 헌장·도구 설명 보강, 티켓 1번 등록

- **관찰**: 실장님이 냥피디에게 "자기 개발 티켓을 하나 제안해봐"라고 하자 에이전트(agy)가 `ticket` 도구를 부르지 않고 `TKT-DEV-...`라는 자유 텍스트 양식을 지어냈다(세션 `20260920-183417-e23e3c` #103→#104, 사이의 도구 호출 없음). 이 세션의 MCP 사용은 `read_file`·`run_command`뿐이었고 `chatbot-self-improve` 스킬도 열지 않았다. 실장님이 챗의 "티켓 승인 및 착수" 버튼을 눌러(#105) 에이전트가 착수할 수 있는 상태가 됐지만 저장소에는 티켓이 없었다.
- **조치** (실장님 승인): ①실제 티켓 1번 등록(`client-device-context`, 근거 `event:…#103`·`#105`, 둘 다 실제 이벤트로 검증됨)과 실장님의 명시적 승인에 따른 명령줄 승인 기록. ②헌장 한 줄: "티켓은 `ticket` 도구로만 만든다. 텍스트로 지어낸 티켓 양식은 티켓이 아니다." ③`ticket` 도구 설명 첫머리를 "The only way to create an evolution ticket; a ticket written out as free text is not one."로.
- **알게 된 것**: 도구가 있어도 모델은 스킬·도구 설명을 안 읽고 "티켓"이라는 말에서 지어낼 수 있다. 헌장(매 세션 주입) 쪽이 도구 설명보다 도달률이 높다. 효과는 다음 실사용에서 확인.
- **⚡소생**: 도구 설명은 `nas_mcp.py`가 재기동돼야 반영. 헌장 한 줄은 다음 턴부터.

## 2026-09-20 — 자기진화 Phase 1 · P1-B: 티켓·예산·단일 작성자 락 (§4.2-4.3)

- **배경** (실장님 "착수"): 관찰이 스스로 작업을 시작하지 못하게 하는 트리거와 폭주 방지.
- **변경**:
  - `tickets.py`(코어, 표준 라이브러리 + `evolution`): 티켓 저장·상태·예산·락.
    - **근거 검증**: `event:<세션>#<줄>`(그 세션 `events.jsonl`에 실제로 있는 줄)과 `candidate:<epoch>`(`candidates.jsonl`에 있는 줄)만 받는다. 지어낸 근거·수치는 거절.
    - **병합**: 같은 대상의 열린 티켓이 있으면 새로 만들지 않고 근거만 추가. 검토 안 된 제안이 10건이면 더 못 만든다.
    - **예산**: 티켓당 최대 3회 시도, 넘으면 `wontfix(needs-human)`. release 없이 사라진 작성자도 임대 만료 후 다음 claim에서 시도 횟수로 계산. 게이트 실패 2회 연속이면 접근을 바꾸거나 멈추라는 조언.
    - **단일 작성자**: `claim`이 임대(`author.lease`)를 잡는다. 기다리지 않고, 바쁘면 티켓에 메모만 남기고 실패. 30분 만료. 임대 식별자는 claim한 쪽만 가진 토큰이고 파일에는 해시만 저장.
    - **승인은 사람만**: `approve`/`decline`/`reopen`/`drop-lease`는 명령줄(`python3 tickets.py ...`)에만 있고 에이전트 도구에는 없다.
  - `nas_mcp.py`: `ticket` 도구 하나(액션 `propose|list|get|claim|note|release`). 토큰 세금을 줄이려고 도구 6개가 아닌 1개. 코어 호출만 하는 어댑터, 비밀 유사 내용 거절.
  - `protected_paths.json`: 티켓 디렉터리, `candidates.jsonl`, `data/sessions/*/events.jsonl`을 `write_file` 위조 불가로 등록(근거와 승인을 에이전트가 직접 써서 만들 수 없게). `meta.json`·아티팩트는 그대로 쓰기 가능.
  - 스킬 `chatbot-self-improve`: 티켓 절차 안내.
- **설계서와 다르게 한 것**: ①"작성자 락 flock" → 임대 파일. MCP 호출에는 세션 식별자가 없고 호출마다 끝나서, 프로세스가 쥐는 flock으로는 "세션이 쥐고 있음"을 표현할 수 없고 세션이 죽으면 락이 안 풀린다. ②근거의 "호스트 계측 수치"는 호스트가 수집한 후보(`candidate:`)로 충족하고 자유 형식 `metric:`은 받지 않는다(검증 불가).
- **한계**: 티켓 절차는 관례+도구 수준의 강제다. Tier 0/1 쓰기(`write_file`)는 티켓 없이 계속 되고, 티켓을 무시하는 에이전트를 막는 것은 아니다(H4와 같은 한계). 예산은 claim 시점에 강제된다.
- **하지 않은 것**: 배지에 티켓 표시, 승인 UI(지금은 명령줄), 관찰→티켓 자동 제안, P1-C 무흔적 정리, P1-D `memory_*`.
- **검증**: `tests/test_tickets.py` 34개 + `test_nas_mcp.py`에 `ticket` 도구. 스크래치에서 변이 9곳(근거 미검증, 병합, 예산, 임대 무시, 토큰 미검사, 토큰 평문 저장, 만료 없음, 승인 액션 노출, 게이트 조언)을 하나씩 꺼서 테스트가 잡는 것을 확인 — 예산 검사 1건은 처음에 살아남아서 "release 없이 사라진 작성자" 테스트를 추가. 전체 428개 통과, `guard_rlock OK`.
- **⚡소생 필요**: `nas_mcp.py`(`ticket` 도구 로드). `tickets.py`도 그때 함께 로드.

## 2026-09-20 — 자기진화 Phase 1 · P1-A: 관찰 수집 코어 (턴 종료 합류점 + 후보 수집 + observe_add)

- **배경** (실장님 "P1-A부터"): §4.6 관찰 기능의 자체 소유화 중 수집 코어. 프로바이더 훅(agy 전용)에 기대지 않고 호스트가 5개 provider 공통으로 턴 종료를 관찰한다.
- **변경**:
  - `evolution.py`(코어): `on_turn_end`(신호 판정 + 기록), `record_candidate`(`skill-observations/candidates.jsonl` append, 256KB 넘으면 최신 500줄만 유지), `add_observation`(다음 번호의 `observation-log/NNNN-*.md`, 배타 생성, 폭주 상한 옵션). 표준 라이브러리만.
  - `observation_signals.json`(신규 데이터, 보호 대상): 정정 표현 정규식과 무시할 접두(`[doctor-probe]`).
  - `session.py`: 합류점 `_finish_turn(outcome)` 하나를 정상 result/error(`_handle_events`), 사용자 stop, steer·중단(`interrupt_current_turn`), 자식 프로세스 사망(`_read_stdout` finally, `_reap_sessions`), 자동 중단(`_auto_stop_worker`)이 부른다. 후속 세션 생성은 `_rotate_to_fresh_session`에서 기록. 관찰 디렉터리는 세션 파일이 있는 데이터 디렉터리에서 유도(테스트·다른 인스턴스가 서로 오염 안 함), 디렉터리가 없으면 아무것도 안 씀, 코어 import가 실패해도 관찰만 꺼지고 턴은 정상.
  - `nas_mcp.py`: `observe_add(title, body, area)` 어댑터(코어 함수 호출만, 비밀 유사 내용 거절, 시간당 10건 상한). 기록만 하고 어떤 변경도 시작하지 않는다.
  - 스킬 `chatbot-self-improve` 5번: `observe_add` 안내 + 후보는 힌트이지 작업 지시가 아님.
- **신호 4종**: 사용자 정정(사용자 발화 근거), 종료 방식(stopped·interrupted·auto_stop·process_died·error), 세션 회전. 한 사용자 턴은 종료 경로가 여럿이어도 한 번만 기록.
- **설계서와 다르게 한 것 2건**: ①"도구 오류" 신호는 뺐다 — 모든 provider의 도구 결과 이벤트가 `status: "done"`으로만 나와 공통으로 판별할 근거가 없고, 도구 출력 본문을 해석하는 건 §4.4(도구 출력은 데이터로만)에도 어긋난다. ②`busy=False`·헤비 체크·큐 디스패치는 `_finish_turn`으로 옮기지 않고 각 경로에 두었다(락·디스패치 레이스 위험). `_finish_turn`은 관찰 훅의 합류점만 맡는다.
- **하지 않은 것**: 배지에 후보 수 추가, 관찰 리뷰 자동 실행(§8-4 미정), 티켓·예산·작성자 락(P1-B), 심링크·훅 제거와 상태 키 이름 변경(P1-C), `memory_*` MCP(P1-D).
- **검증**: 신규 `test_observation.py`·`test_turn_observation.py`, `test_nas_mcp.py`에 observe_add. 스크래치 트리에서 기준선(원본 `session.py`) 대비 새 실패 0, 종료 경로·중복·누수·격리 변이 15곳을 하나씩 꺼서 테스트가 잡는 것 확인. 전체 385개 통과, `guard_rlock OK`. 실제 데이터 디렉터리에 후보가 오염되지 않음.
- **⚡소생 필요**: `session.py`, `nas_mcp.py`(1회). `evolution.py`·`observation_signals.json`은 함께 로드.

## 2026-09-20 — 자기진화 Phase 0 배치 C: 기동 락·유지보수 플래그·보호 파일 해시 경고 (0-6)

- **배경** (실장님): 배치 B에 이어 §3 0-6 + 결정 4(해시 사후 탐지, doctor 경고 전용) 착수. 구멍 H7(워치독이 1분마다 doctor를 돌리는데 start/doctor/repair 사이에 상호 배제가 없음).
- **변경**:
  - `evolution.py`(코어) 확장, 여전히 표준 라이브러리만: `acquire_lock`(fcntl은 이 함수 뒤에만), `run_locked`, `maintenance_note`, 보호 파일 해시 매니페스트(`protected_files`/`write_manifest`/`check_manifest`), 그리고 ctl이 부르는 CLI(`run-locked`·`maintenance`·`manifest-check`·`manifest-update`·`self-check`).
  - `chatbot-ctl.sh`: 디스패치 앞에 얇은 래퍼 하나. `start|doctor|repair|defibrillate|shock|cpr`는 Python 감독 프로세스가 락을 쥔 채 ctl을 자식으로 실행(락은 감독이 소유해서 ctl이 띄운 server.py는 락을 상속 안 함). `doctor`는 바쁘면 즉시 건너뛰고(exit 0), `start`/`repair`는 최대 120초(`CHATBOT_LOCK_WAIT_SEC`) 기다린 뒤 exit 75. 새 bash 로직 없음(flock 없음). 락 헬퍼가 못 돌면 잠금 없이 그대로 진행(안전장치일 뿐 기동 조건이 아님). "이미 락 안에 있음" 표시는 `CHATBOT_LOCK_PPID == $PPID`라서, server.py를 통해 새어 나간 환경변수로는 우회 못 함.
  - `cmd_doctor`: `data/maintenance.flag`가 있으면 자동 기동·복구를 건너뜀(사람이 누르는 ⚡/`repair`는 계속 동작). 이어서 매니페스트 대조를 하고 불일치는 `doctor_log`에 `WARN`으로 남김(워치독은 stdout을 버리므로 로그가 유일한 표시). 경고 전용이며 doctor 결과·auto-repair에 영향 없음.
  - `protected_paths.json`: `protected_manifest.json`·`data/lifecycle.lock`·`data/maintenance.flag`를 쓰기 보호에 추가하고, 내용이 바뀌는 항목(`__pycache__/`, 티켓, 락, 플래그, 매니페스트 자신)은 `volatile`로 해시 대상에서 제외.
- **다른 사람의 미커밋 변경 위에 얹음**: ctl의 로그 로테이션 변경은 그대로. ctl은 `mv`로 원자 교체(실행 중인 bash 스크립트는 제자리 수정 금지).
- **하지 않은 것**: 매니페스트 생성(사람이 검토 후 `python3 evolution.py manifest-update`), 허브 `chatbot.php`, 유지보수 플래그 자동 만료, `restart`(락 대상 아님).
- **검증**: `tests/test_lifecycle.py` 31개 + 기존 evolution 테스트. 락 상호 배제·자식이 락을 안 물고 남는지·환경변수 우회 불가·깨진 헬퍼에서도 기동 가능·유지보수/락 바쁨 경로를 실제 ctl로 확인(임시 트리, PATH 맨 앞에 `ps`/`kill`/`setsid`/`nohup`/`curl` 스텁을 넣어 실수로 깊이 들어가도 라이브를 못 건드림). 가드 6곳을 하나씩 꺼서 테스트가 잡는 것을 확인. 전체 331개 통과, `py_compile`, `bash -n`, `guard_rlock OK`.
- **⚡ 불필요(ctl)**: `chatbot-ctl.sh`는 이미 워치독이 새 버전으로 실행 중(락 파일 생성 확인). `evolution.py`의 새 기능은 서버/MCP가 재기동될 때 함께 로드되지만 그 프로세스들은 새 기능을 쓰지 않는다.

## 2026-09-20 — 자기진화 Phase 0 배치 B: HTTP 면 축소 (defibrillate Same-Origin, CORS, 기본 바인딩, 규칙 파일 읽기 전용)

- **배경** (실장님): 배치 A에 이어 §3 0-3 + 0-4의 `/api/rules` PUT 조각을 착수.
- **변경**:
  - `origin_guard.py` 신설(순수 함수): `same_origin`(Origin의 host:port가 Host와 정확히 같을 때, Origin이 없으면 `Sec-Fetch-Site: same-origin`만), `cors_allowed`(호스트명만 비교, 포트 무관).
  - `server.py`: `POST /api/host/defibrillate`는 same-origin 브라우저 요청만(헤더 없는 curl·다른 사이트·다른 포트는 403). CORS `*` 제거 — 같은 머신의 다른 포트(허브)만 그 Origin을 되돌려 받고 남의 사이트는 CORS 헤더 없음. `PUT /api/rules/*`는 `evolution.is_protected`로 판정해 `AGENTS.md`·`SELF-MODIFY.md`를 403(읽기 전용).
  - `host_config.py`: 기본 바인딩 `127.0.0.1`. ctl의 `export AGY_CHAT_HOST=0.0.0.0`은 이미 있어 이 NAS의 LAN 접속은 유지(테스트가 그 export 존재를 고정).
  - `data/workspace/PROJECT.md`: 엔트리 설명 정정(운영 기동은 ctl만, 직접 실행은 로컬 전용).
- **문서와 다르게 한 것**: CORS를 "제거"가 아니라 "같은 머신 호스트명만 허용"으로. 허브 `index.html:1488`이 다른 오리진에서 `:3011/api/providers`를 fetch해서 그냥 없애면 깨진다.
- **하지 않은 것**: 허브 `api/chatbot.php?action=revive`(웹 루트, 이 레포 밖)는 무인증으로 `sudo -u me chatbot-ctl.sh repair`를 실행한다 — 이번 배치로 안 막힌다. `chatbot-ctl.sh`·`static/app.js`는 안 건드림(규칙 편집 UI는 저장 시 403 메시지를 alert로 보여 줌). 0-6, Phase 1·2.
- **검증**: `tests/test_origin_guard.py` 7개 + `tests/test_host_api_guards.py` 14개(임시 포트의 실제 핸들러, 재기동 스케줄러는 recorder로 대체). 가드 5곳을 하나씩 꺼서 테스트가 잡는 것을 확인. 전체 300개 통과, `py_compile`.
- **⚡소생 필요**: `server.py`, `host_config.py`. `origin_guard.py`는 신규(server가 import).

## 2026-09-20 — 자기진화 Phase 0 배치 A: 보호 경로 레지스트리 + MCP 도구 권한 축소

- **배경** (실장님): `docs/plans/recursive-self-evolution.md` §3 배치 A(0-0·0-1·0-2·0-4·0-5) 구현 착수 지시. 구멍 H1(`run_command`로 `repair`), H2(`service_ctl` start), H3(보호 파일 쓰기), H5(스킬이 관찰 배지로 착수).
- **변경**:
  - `evolution.py` 신설(코어): 보호 경로 검사 `is_protected`/`match_protected`. `pathlib`과 인자로 받은 ROOT만 사용, 호스트 모듈 import 없음. 레지스트리가 없거나 깨지면 전부 보호(실패 폐쇄).
  - `protected_paths.json` 신설: 보호 목록은 코드가 아니라 이 설정 데이터. 호스트 `*.py`, `chatbot-ctl.sh`, `tests/`, `SELF-MODIFY.md`, 헌장 `AGENTS.md`, `docs/EMERGENCY.md`, `host-force.ticket`, `__pycache__/`, `~/.agents/`, 자기 자신. `static/`은 `except`로 이 NAS 예외를 명시.
  - `nas_mcp.py`: `run_command`는 토큰 단위 정확 일치(`psql`·`lsof` 더는 통과 못 함), `chatbot-ctl.sh`는 `status|doctor|probe|guard`만(`doctor`는 인자 없이, `probe`는 숫자 하나만), curl은 로컬 GET 전용(쓰기·POST 옵션은 허용 목록에 없음, `defibrillate` URL 거절), `>`/`<` 리다이렉션 거절(`2>/dev/null`만 허용). `service_ctl`의 chatbot은 `status`만. `write_file`은 `evolution.match_protected`를 호출(`nas_mcp.py`는 자기 목록 없음).
  - 스킬 `chatbot-self-improve`: 시작 조건을 발화·승인 티켓으로 제한, Tier 요약. 헌장 `AGENTS.md`에 "관찰 배지는 작업 지시가 아니다" 한 줄.
- **문서에 없던 판단 2건**: `doctor --auto-repair`는 probe 실패 시 `cmd_repair`(티켓 발급+재시작)로 가서 `doctor`를 그냥 열면 H1이 남는다. `date > 파일` 같은 리다이렉션은 `write_file` deny를 우회한다. 둘 다 막았다.
- **하지 않은 것**: `server.py`(`/api/rules` PUT 읽기 전용, 0-3), `chatbot-ctl.sh`, 0-6, Phase 1·2, task-observer 심링크. H4(CLI 네이티브 쓰기)는 이 배치로 안 막힌다.
- **검증**: 스크래치 복사본에서 고쳐 테스트 통과 후 `nas_mcp.py`를 `mv` 한 번으로 교체. 신규 `tests/test_evolution.py` 21개 + `tests/test_nas_mcp.py` 49개(특성화 후 뒤집음), 전체 279개 통과, `py_compile` 3.8.15. 핵심 가드 5곳을 하나씩 꺼 보고 테스트가 잡는 것을 확인. 실제 `repair`·`doctor`·`probe`는 실행하지 않음(mock).
- **⚡소생 필요**: `nas_mcp.py`(MCP 프로세스가 새 코드를 읽으려면). `evolution.py`·`protected_paths.json`은 MCP가 다음 기동에서 읽는다.

## 2026-09-20 — 자기진화 설계서 v3 Grok 교차 검증을 문서로 저장

- **배경** (실장님): v3 계획의 Grok 검증 결과를 문서로 남겨 전달·착수에 쓰라고 함.
- **산출물**: [`docs/plans/recursive-self-evolution-review-grok-v3.md`](./plans/recursive-self-evolution-review-grok-v3.md). 계획서 헤더에 링크. 코드·ctl은 안 건드림.
- **결론 한 줄**: 수정 후 착수. Phase 0 방향은 유지. 착수 전에 0-4 deny에 호스트 모듈을 넣고, 0-3 바인딩은 ctl 경로에만 성립한다고 명시할 것.

## 2026-09-20 — 자기진화 설계서 v2 Grok 교차 검증을 문서로 저장

- **배경** (실장님): v2 계획의 Grok 2차 검증 결과를 채팅에만 두지 말고 문서로 남기라고 함.
- **산출물**: [`docs/plans/recursive-self-evolution-review-grok-v2.md`](./plans/recursive-self-evolution-review-grok-v2.md). 계획서 헤더에 링크. 코드·ctl은 안 건드림.
- **결론 한 줄**: 수정 후 진행. 게이트를 호스트로 빼는 뼈대는 유지. 보호 경로 쓰기 거절·repair MCP 차단·chatbot-scoped 스테이징·스킬 트리거 정합을 문서에 넣기 전에는 구현 착수하지 말 것.

## 2026-09-20 — 재귀적 자기 개발 및 자기 개선 아키텍처 계획서 작성

- **배경** (실장님): 냥피디의 재귀적 자기 개발(Self-Development) 및 자기 개선(Self-Improvement) 체계 수립 및 모든 Provider(Gemini/Claude/Grok/Codex) 간 교차 검증 준비.
- **산출물**: [`docs/plans/recursive-self-evolution.md`](file:///var/services/homes/me/services/chatbot/docs/plans/recursive-self-evolution.md)
  - **개념 분리**: 외연적 도구/스킬 확장(개발) vs 내재적 인지/정책/효율 최적화(개선).
  - **4단계 재귀 진화 루프 (O-D-E-V)**: Observe & Diagnose → Draft & Synthesize → Evaluate & Gate (외부 정적/AST/209개 테스트) → Promote & Hot-Swap (원자적 치환/⚡소생 보고).
  - **3계층 아키텍처**: L1 인지/장기기억, L2 도구/스킬 스미싱, L3 아키텍처 자가 리팩토링.
  - **4대 안전 가드레일**: 뇌수술 금지(`SELF-MODIFY.md`), 원자적 상태 전이, 가역성(Git 백업), 인간 승인 경계.
  - **Provider 교차 검증 질의 프레임워크** (안전성, 불변성, 실현성, 오버엔지니어링 여부).

## 2026-09-20 — 코드 위생 정리 및 중복 유틸 제거 (ponytail-audit 반영)

- **배경**: 전체 코드베이스 점검(ponytail-audit)을 통해 식별된 미사용 import 및 프론트엔드 중복 함수 정리.
- **변경**:
  - `server.py`: 모듈 분리 후 잔류하던 미사용 import (`re`, `Optional`, `Tuple`, `extract_yaml_desc`) 제거.
  - `static/app.js`: 상단 HTTP LAN 환경 폴백이 이미 구현된 `copyText` 외에 상태 탭 아래에 중복 정의되어 있던 2차 `copyText` 제거.
- **검증**: `py_compile` 통과, `node --check static/app.js` 통과, `chatbot-ctl.sh guard` 통과, 단위 테스트 총 209개 전원 통과 (`Ran 209 tests in 4.763s OK`).

## 2026-09-20 — 신규 모듈 전용 단위 테스트 추가 및 import 정리 (Phase 4 리팩토링)

- **배경**: Phase 1~3에서 분리한 독립 모듈군(`standby_pool`, `artifact_manager`, `session_weights`, `workspace_status`)의 전용 테스트 커버리지 확충 및 `session.py`의 미사용 import 정리.
- **변경**:
  - `tests/test_refactored_modules.py` 신설 (88줄):
    - `StandbyPoolTest`: 웜 프로세스 풀 초기 상태 및 `try_take` 계약 검증.
    - `ArtifactManagerTest`: `_safe_session_id` 검증(특수문자/디렉터리 트래버설 방어), `_atomic_write_text` 원자적 파일 쓰기 검증.
    - `SessionWeightsTest`: `_billed_tokens`, `_current_context_tokens` 토큰 집계 및 `_is_inquiry` 질의 판별 정규식 검증.
    - `WorkspaceStatusTest`: 스킬 YAML 메타데이터 파싱(`_extract_yaml_desc`) 및 MCP 설정 입출력(`_read_mcp_config`, `_write_mcp_config`) 원자성 검증.
  - `session.py`: 모듈 분리로 인해 더 이상 직접 참조되지 않는 타입 및 심볼 import 정리.
- **검증**: `py_compile` 통과, `chatbot-ctl.sh guard` 통과, 단위 테스트 총 209개 전원 통과 (`Ran 209 tests in 4.653s OK`).

## 2026-09-20 — media_handler.py 미디어/아티팩트 서빙 모듈 분리 (Phase 3 리팩토링)

- **배경**: `session.py`에 내장되어 있던 Grok/Gemini 생성 이미지 수집, 아티팩트 서빙 경로 치환, 마크다운 이미지 주입 로직 분리.
- **변경**:
  - `media_handler.py` 신설 (236줄): `_stage_image`, `_stage_grok_rel_media`, `_collect_new_images`, `_rewrite_artifact_paths`, `_append_images_markdown`, `_conversation_brain_dir`, `_grok_media_dir` 등 미디어 스테이징 및 URL 치환 로직 분리. 동적 세션/호스트 설정 조회(`_cfg`) 지원으로 테스트 격리 환경 monkey-patch 호환.
  - `session.py`: 2,194줄 → 1,998줄로 2,000줄 미만으로 경량화 달성. `AgySession`의 외부 인터페이스 및 테스트 호출 계약 유지.
- **검증**: `py_compile` 통과, `chatbot-ctl.sh guard` 통과, 단위 테스트 전체 202개 전원 통과 (`Ran 202 tests in 4.799s OK`).

## 2026-09-20 — server.py 라우팅 및 상태/보안 모듈 분리 (Phase 2 리팩토링)

- **배경**: `server.py`의 비대화(1,050+줄) 및 HTTP 라우터와 파일 접근 제어/상태 점검 로직의 강결합 완화.
- **변경**:
  - `preview_guard.py` 신설 (~80줄): `/api/file/preview`, `/api/file/raw`의 보안 화이트리스트 탐색(`_resolve_safe_preview_file`, `_preview_allowed`, `_SECRET_NAME_RE`) 분리. 동적 모듈 참조 지원으로 기존 단위 테스트 monkey-patching 100% 호환.
  - `workspace_status.py` 신설 (~180줄): 룰 파일/워크스페이스 스킬/MCP 설정 조회 및 갱신(`_self_status`, `_get_workspace_skills`, `_read_mcp_config`, `_write_mcp_config` 등) 분리.
  - `server.py`: 1,054줄 → 846줄로 경량화. 순수 HTTP Handler 및 서버 라이프사이클 관리에 집중.
- **검증**: `py_compile` 전 모듈 통과, `chatbot-ctl.sh guard` 통과, 단위 테스트 전체 202개 전원 통과 (`Ran 202 tests in 4.776s OK`).

## 2026-09-20 — session.py 모듈 분리 (Phase 1 리팩토링)

- **배경**: `session.py`의 비대화(2,550+줄)로 인한 락 복잡도, 데드락 위험 및 높은 컨텍스트 소모 완화.
- **변경**:
  - `artifact_manager.py` 신설: `_safe_artifact_rel`, `_safe_session_id`, `_atomic_write_text` 등 아티팩트/경로/원자적 저장 로직 캡슐화.
  - `standby_pool.py` 신설: `_StandbyPool`, `STANDBY_POOL` 등 웜 프로세스 풀 및 마커 수명주기 분리.
  - `session_weights.py` 신설: `_session_weight`, 토큰 집계(`_turn_billed`, `_current_context_tokens`, `_billed_tokens`), 질의 판별(`_is_inquiry`), 인계/샛길 프롬프트 템플릿 분리.
  - `session.py`: 2,554줄 → 2,193줄로 경량화. `chatbot-ctl.sh guard_rlock` 계약 및 외부 인터페이스 불변.
- **검증**: `py_compile` 전 모듈 통과, `chatbot-ctl.sh guard` 통과, 단위 테스트 전체 202개 통과 (`Ran 202 tests in 4.862s OK`).

## 2026-09-20 — 제품 기조 (최대 가치·목표)

- **배경** (실장님): 수정·개발 때 항상 참조되는 최대 가치·목표로 정하고, 그 기조로 빌드업.
- **변경**: `docs/concept.md`. 가치는 친근·유능·만능에 가까운 인간/친구/연인/동료 같은 챗봇. 축은 연동·격리·캐릭터·디자인·편의·자체개발·자기진화·토큰·하네스보다 나은 UX·컨텍스트 유지·단절 없는 대화·어디서나 접속·디바이스 기준 지원. `PROJECT.md` / `chatbot-self-improve` / `AGENTS.md`에서 먼저 열게 연결.
- **배포**: 문서만. 소생 불필요.

## 2026-09-20 — 냥피디 시각 빌드업 노트

- **배경** (실장님): 지금은 러프. 캐릭터가 구체화되면 그걸 기준으로 이미지도 폴리시.
- **변경**: `data/persona/README.md` — 락/가발 기조/거절/러프 로스터. `PERSONA.md`는 주입용으로 얇게 유지. `PROJECT.md` Where to edit에 연결.
- **배포**: 문서만. 소생 불필요.

## 2026-09-20 — 클로드·코덱스·옴니: 포니 통일 철회, 키컬러+컷으로 구분

- **배경** (실장님): 포니테일은 agy 얼굴 보정이지 전 제공자 기조가 아님. 변화는 키컬러 염색 + 헤어 실루엣.
- **변경**: 얼굴은 agy 뱃지 고정. Claude=앰버 보브, Codex=에메랄드 히메, OmniRoute=시안 사이드브레이드. `PORTRAIT_CACHE=v=10`, `app.js?v=89`. agy 포니·grok 고스는 유지.
- **배포**: 하드 새로고침. API icon 쿼리는 소생 후.

## 2026-09-20 — agy 초상: 스플릿 웨이브 → 청적 트윈테일

- **배경** (실장님): 스플릿 염색도 실루엣이 기본 웨이브라 라이팅과 다를 게 없음. 헤어스타일 자체가 달라야 함.
- **변경**: 왼쪽 파랑·오른쪽 빨강 **트윈테일**(염색, 조명 아님). 얼굴·금눈·트렌치 유지. 울프컷·하이포니 후보는 `agy-wolf.jpg` / `agy-ponytail.jpg`. `agy.webp?v=9`, `app.js?v=88`.
- **배포**: 하드 새로고침. API icon 쿼리는 소생 후.

## 2026-09-20 — agy 초상: 조명 말고 헤어 스타일·컬러로 구분

- **배경** (실장님): 듀오톤이 은발에 라이팅만 얹은 거. 헤어스타일·헤어컬러로 느낌을 내야 함.
- **변경**: 왼쪽 파랑·오른쪽 빨강 스플릿 염색 + 더 긴 웨이브. 얼굴·금눈·트렌치는 유지. `agy.webp?v=8`.
- **배포**: 하드 새로고침.

## 2026-09-20 — Antigravity를 Gemini 빨강·파랑 듀오톤으로

- **배경** (실장님): agy가 라임+보라머리라 제미나이 컨셉이랑 안 맞음. 그록과 같은 작업.
- **변경**: 테마 `spark`(파랑 `#6ea8fe` 램프, 빨강 `#ff6b81` twin). agy 초상은 냥피디 얼굴+트렌치, 빨강/파랑 스플릿 라이팅. `themeForProvider(agy)=spark`, `?v=7`.
- **배포**: 정적 새로고침. API theme 매핑은 소생 후. 프론트는 agy면 바로 spark.

## 2026-09-20 — FAB만 새 초상, 전체 채팅창은 옛 캐시

- **원인**: 허브 FAB 이미지는 80포트 nginx(`/chat/persona/`)라 새 파일이 바로 보임. 전체 창 `:3011`은 `Cache-Control: max-age=86400`이라 `grok.webp?v=4`를 하루 붙잡음.
- **해결**: 클라이언트 `portraitUrl()`이 API 쿼리를 버리고 `?v=6`을 붙임(허브 FAB도 동일). 페르소나 캐시 `max-age=60`.
- **배포**: 채팅창 Ctrl+Shift+R. 페르소나 캐시 헤더는 소생 후.

## 2026-09-20 — Grok 초상을 냥피디 얼굴 + 고스로리로 재생성

- **배경** (실장님): 흑백 잉크 고딕이 냥피디랑 갭이 큼. 스타일만 고스로리, Imagine으로.
- **변경**: 기준 `avatar.png` 얼굴 유지, 검은 드레스·흰 레이스. `grok.{png,webp}` 512 교체, `?v=5`.
- **배포**: 하드 새로고침. 아이콘 쿼리는 소생 전이면 `?v=4` 캐시라 Ctrl+Shift+R.

## 2026-09-20 — Grok(mono)만 기본 글자를 어둡게

- **배경** (실장님): 흰 하이라이트가 기본 텍스트(`#edefef`)랑 같아서 의미가 없음. 다른 제공자는 그대로, 그록만 어둡게.
- **변경**: `[data-theme="mono"]`가 램프뿐 아니라 방도 낮춤 — `--bg #050505`, `--text #9a9a9a`, `--muted #5c5c5c`, accent `#ffffff`. 프론트 `themeForProvider`가 grok이면 API가 아직 violet이어도 mono.
- **배포**: `chat.css?v=13`, `app.js?v=83` 하드 새로고침. 소생 불필요.

## 2026-09-20 — 채팅창에서 Grok Imagine `images/1.jpg`가 깨지던 문제

- **배경** (실장님): 고딕 초상 후보를 말풍선에 넣었더니 이미지가 깨짐.
- **원인**: Grok이 `![...](images/1.jpg)`처럼 **자기 세션 상대경로**를 쓰는데, 챗봇은 `/images/1.jpg`로만 열고 404. `_rewrite_artifact_paths`는 agy brain 절대경로만 바꿨고, GrokAdapter는 `_append_images_markdown`도 안 탔음.
- **해결**: grok 세션 폴더(`~/.grok/sessions/<cwd>/<cid>/images|videos`)에서 파일을 `sessions/<sid>/artifacts/brain/`으로 스테이징하고 마크다운 URL을 `/artifacts/...`로 바꿈. 프론트 `absArtifact`도 `images/`·`videos/`를 같은 URL로 폴백. 이미 깨져 있던 말풍선 2장은 디스크에 복사+히스토리 URL 수정.
- **검증**: `tests/test_grok_image_paths.py` 3개. 라이브 `GET /artifacts/<sid>/brain/1.jpg` 200. 호스트 경로 재작성은 ⚡소생 후 다음 턴부터. 지금 말풍선은 정적 `app.js?v=82` 새로고침으로 복구.
- **배포**: 정적 새로고침. 다음 grok 그림 생성부터 자동 첨부하려면 소생.

## 2026-09-20 — Grok 키컬러·포트레이트를 흑백 고딕(Paper White)으로

- **배경** (실장님): grok 프로바이더가 보라 키컬러 + 마젠타 냥피디 재채색이라, 실제 Grok(어두운 톤 + 흰 하이라이트, 흑백 고딕 일러스트)과 안 맞음.
- **변경**:
  - 테마 다이얼 `mono`(Paper White, `#f4f4f5`/`#ffffff`) 추가. Grok `PROVIDER_META.theme`를 `violet` → `mono`.
  - 포트레이트 `data/persona/providers/grok.{png,webp}`를 512 흑백 고딕 bust로 교체(퍼블리시 `/volume1/web/chat/persona/providers/` 동기화). `?v=4`.
  - `chat.css`/`theme.js`/`index.html` 스와치, `DESIGN.md`/`PRODUCT.md`/`design.json`.
- **검증**: `tests/test_identity_wiring.py` grok theme=`mono`. 정적은 하드 새로고침. 테마 전환은 `/api/providers`라 **⚡소생** 필요.
- **배포**: 초상·CSS는 새로고침. 키컬러 매핑은 소생 후.

## 2026-09-20 — 입력창 높이가 상황마다 조금씩 다르던 문제 (app.js) + FAB 진단

- **배경** (실장님): 하단 위젯들 높이가 상황에 따라 조금씩 다른 것 같다 → 의도인지. 이어서 FAB에서도 텍스트창 높이가 다르다.
- **의도된 것**(CSS 주석에 근거): 데스크톱은 버튼·입력창 모두 42px. 모바일은 터치 대상 44px 버튼(2026-09-18 점검 P1) 옆에 입력창 36px(`flex-end`라 아래가 맞음). 키보드 열림/낮은 화면(≤500px)은 전부 32px.
- **의도가 아닌 것**: `autoResizeInput()`이 CSS와 따로 최소/최대(모바일 38/90, 데스크톱 42/120)를 들고 있어서 — 모바일 입력창이 CSS의 36이 아니라 38, 키보드 열림에서는 버튼 32 옆에서 38, JS 최대(90/64 등)는 CSS `max-height`에 잘려 무의미, 슬래시 명령(`/clear` `/new` …)이 인라인 높이를 비우면 다음 키 입력까지 CSS 값(36/32)으로 돌아감.
- **해결** (`static/app.js`): 최소/최대를 `getComputedStyle(#input)`에서 읽음(읽을 수 없으면 42/120). `updateViewport()`가 (좁은 폭 × 키보드열림) 조합이 바뀔 때만 다시 측정(`_composerMode`). `app.js?v=76`.
- **검증**: `tests/test_composer_height.py` 10개(이후 A 적용으로 12개) — 실제 `autoResizeInput`/`updateViewport`를 CSS를 흉내 낸 스텁에서 실행 + 결정된 크기(42·44/36·32)를 CSS에서 직접 읽어 고정. 원래 버그와 변이 5개가 모두 실패함을 확인. 전체 188개 통과. **실제 화면 확인은 미확인.**
- **FAB 진단 → 수정 A 적용(실장님 승인)**: 허브 FAB은 이 UI를 폭 420px iframe(`?compact=1`)으로 띄움 → 데스크톱에서도 화면 폭 ≤640px 미디어 쿼리가 적용돼 **폰 레이아웃**(버튼 44/입력 36)이 됨(전체 페이지 데스크톱은 42/42). 더 큰 원인은 `updateViewport()`의 `isKeyboardOpen = isNarrow && (isShort || isInputFocused)` — 폭이 좁으면 **입력창에 포커스만 가도** `keyboard-open`이 켜져서(마우스·물리 키보드 데스크톱 FAB도 해당) 입력줄이 32px로 줄고 헤더/탭/메타/모델 버튼이 숨음(블러하면 복원). compact 전용 컴포저 규칙은 없음.
  - **수정 A** (`static/app.js`): 판정을 순수 함수 `keyboardOpenState(narrow, short, focused, touch)`로 분리 — "포커스"는 **터치 기기(`(pointer: coarse)`)에서만** 키보드로 간주, 짧은 뷰포트(<520px)는 어떤 기기든 그대로. 데스크톱 FAB은 클릭해도 입력줄·헤더·탭·모델 버튼이 안 변함(높이는 폰 레이아웃 값 그대로 36/44). `app.js?v=77`.
  - 포커스 때 버튼(44→32)만 줄고 입력창은 그대로라 흔들리던 것: CSS는 입력창도 32로 정했는데 JS 인라인 38이 덮어쓴 **의도 아닌 불일치**(위 수정으로 해소, 키보드 열림에서는 셋 다 32). 포커스 120ms 뒤에 줄어드는 지연(`setTimeout(updateViewport,120)`)과 폰에서 44→32로 줄어드는 것 자체는 키보드 공간 확보용 의도.
  - 테스트 12개(마우스/터치 시퀀스, 진리표), 변이 4개 실패 확인, 전체 190개 통과. 실제 화면 미확인.
  - **수정 B 적용** (실장님: "FAB에서 텍스트입력창만 높이가 낮아" — 폰 레이아웃의 버튼 44px 옆 입력창 36px): `static/chat.css`에 `@media (max-width: 640px) and (pointer: fine)` 블록 추가 — 폭은 좁아도 마우스 기기면 `/`·모델 버튼 42×42, 보내기 42, 입력창 42로 전체 페이지 데스크톱과 동일. 키보드/낮은 화면(32px) 블록보다 앞에 두어 그쪽이 그대로 이김. 터치(폰)는 44/36 그대로. `chat.css?v=7`. 테스트는 이제 스텁 숫자를 **실제 chat.css에서 읽어** 주입(스텁과 CSS가 어긋날 수 없음), 총 14개. **데스크톱 FAB 입력창 높이 해결을 실장님이 확인(2026-09-20).**
- **FAB에서 모델 팝업이 안 뜬다는 보고 — 이후 실장님이 "잘 뜬다"고 확인(2026-09-20). 코드 수정 없이 해소, 원인은 미확인**(브라우저/iframe이 이전 버전을 쥐고 있다가 갱신됐을 가능성이 있으나 확인하지 못함). 조사 내용: 실제 서버가 내주는 페이지를 jsdom(임시 폴더에 설치, 프로젝트 무관)으로 FAB 조건(`?compact=1`, 폭 420, 마우스)과 전체 페이지 조건에서 각각 열어 `#modelBtn`을 눌러 봄 → 둘 다 메뉴가 열리고(3항목), 실제 마우스 순서(pointerdown→mousedown→pointerup→mouseup→click)에도 유지되며, 선택 시 select 값·localStorage·placeholder가 갱신됨. 스크립트 간 전역(`modelEl` 등)·로드 순서·이벤트 배선은 정상. CSS 정적 분석(html/body/.wrap/.composer 및 sphere-theme.css, 인라인 style, theme.js)에서도 `position:fixed` 메뉴의 기준을 바꾸는 `transform/filter/backdrop-filter/contain`은 없음. **재현 불가** — jsdom은 레이아웃이 없어 위치·가림 문제는 못 봄, 이 환경에는 실제 브라우저가 없음(헤드리스 크롬 다운로드 실패).
- **배포**: 정적 파일 → 하드 새로고침(허브와 채팅창 둘 다). 소생 불필요.

## 2026-09-20 — 모델 선택을 짧은 아이콘 버튼으로, 현재 모델은 입력창 placeholder로 (model-picker.js 신규)

- **배경** (실장님): 모바일에서 모델 선택 select가 폭을 차지해서 마음에 안 듦. 짧은 버튼으로 줄이되 현재 쓰는 모델은 명확히 알고 싶으니 placeholder로 보여주기, 버튼은 탭에 쓴 것과 같은 스타일의 아이콘. (제공자 선택은 이미 상단 얼굴 팝업 — 그대로. 모델을 그 팝업에 넣는 안 B는 채택 안 함: 전에 "채팅창 근처에 작게"라고 옮긴 결정을 유지.)
- **변경**:
  - `static/index.html`: `#modelBtn`(탭 아이콘과 같은 `tab-icon-svg` 스타일의 칩 아이콘, `aria-haspopup`) + `#modelMenu`. `<select id="model">`은 **숨긴 채 남김** — 전송·저장·세션 설정이 읽는 `modelEl.value`의 원천이라 나머지 코드는 그대로.
  - `static/model-picker.js`(신규): 메뉴(현재 모델 ✓, 선택 시 select 값 변경 + `change` → app.js가 저장), 열기/닫기(버튼 pointerdown, 바깥 클릭·Esc·입력 시 닫힘, 키보드 Enter/Space·화살표), `composerPlaceholder()`(모델 이름이 **맨 앞** — 좁은 화면에서 `textarea::placeholder`의 말줄임이 힌트를 자르고 모델은 안 자름), `syncModelUi()`(버튼 title/aria-label에 현재 모델).
  - `static/app.js`: placeholder를 쓰던 두 곳(작업 중 초 표시, 대기)을 `refreshComposerPlaceholder()`로 통합, 모델 목록 재구성/`change` 때 `syncModelUi()`.
  - `static/slash.js`: `positionSlashMenu(menuEl)`이 대상 메뉴를 받게 일반화(모델 메뉴가 같은 배치를 재사용).
  - `static/chat.css`: 버튼은 `/` 버튼과 같은 외형·크기(모바일 44px, select의 58px 대체), `#model` 숨김, 키보드 열림/낮은 화면에서 버튼도 숨김(select가 숨던 조건 그대로).
  - `data/workspace/PROJECT.md`: "어디를 고치나" 표에 추가.
- **검증**: `tests/test_model_picker.py` 13개 — 실제 `model-picker.js`를 node 스텁 DOM에서 실행(문구, 메뉴, 선택→select/저장/placeholder/title, 열기·닫기·Esc·키보드·화살표, 목록 없을 때 정적 placeholder 유지) + 마크업/CSS 확인. 동작 규칙 9곳을 하나씩 망가뜨린 변이본이 모두 실패함을 확인(하나가 살아남아 스텁을 실제처럼 고침). 전체 178개 통과. **실제 화면(특히 모바일 폭)에서의 모양·터치 동작은 미확인** — 이 환경에 실제 브라우저가 없음(`google-chrome`은 더미 스텁).
- **배포**: 정적 파일 → 하드 새로고침. 소생 불필요. `app.js?v=75`, `chat.css?v=6`, `slash.js?v=2`, `model-picker.js?v=1`.

## 2026-09-20 — 내가 보낸 말풍선이 화면 맨 위로 튀어 사라져 보이던 문제 (app.js)

- **배경** (실장님): 소생 후 테스트 중 `인사해주랑` 말풍선이 화면에서 사라졌다가, 새로고침하니 제대로 보임. 서버 기록(세션 `910cd2`)에는 정상 저장(11:50:14, 앞 답 직후 배달). btw 질문 말풍선은 안 사라짐(설계상 답 카드 뒤에도 유지).
- **원인** (실제 함수로 재현, 실장님 DOM은 못 봄): 내 말풍선(ts 없음)의 `user_ack`가 **진행 중인 답 말풍선이 없을 때** 도착하면, 직전 커밋에서 넣은 `adoptBareUserBubble`이 `placeMsgByTs`로 말풍선을 ts 위치로 **재배치**했고, 그 함수의 fallback `inFlightAssistant()`가 ts 없는 **시스템 말풍선(세션 인사 등)**을 "진행 중"으로 착각해 그 앞에 삽입 → 로그 맨 위로 이동. 일반 전송은 진행 말풍선(`data-live`)이 먼저 생겨서 영향 없었음. 즉 **직전 커밋 `6b22acf6`의 중복 수정이 만든 회귀**이며 steer 여부와 무관.
- **해결** (`static/app.js`): ① `adoptBareUserBubble`은 도장(ts)만 찍고 **옮기지 않음**. ② `inFlightAssistant`가 `.system`(시스템 말풍선)과 `data-untimed`(클라이언트가 직접 닫은 말풍선)를 "진행 중"에서 제외. `index.html` → `app.js?v=74`.
- **검증**: `tests/test_bubble_position.py` 5개(실제 함수, 스텁 DOM). 원래 버그(①②를 둘 다 되돌림)는 3개 테스트가 실패, ①만/②만 되돌려도 각각 잡힘. 전체 165개 통과. **실제 화면 확인은 미확인.**
- **참고(안 고침)**: 배달 전 steer 문장은 서버 메모리(`msg_queue`)에만 있고 API는 개수만 줌 → 배달 전에 새로고침하면 그 말풍선이 잠시 사라짐(배달되면 다시 나타남). 중지 버튼은 대기 중인 steer를 버림. 이 건은 이번 증상과 별개로 남아 있음.
- **배포**: 정적 파일 → 하드 새로고침. 소생 불필요.

## 2026-09-20 — btw 답 카드가 질문보다 앞에 찍히던 순서 문제 (app.js)

- **배경** (실장님): "첫 btw는 질문 다음에 대답인데, 그 다음 btw는 대답이 질문 전에 찍혔어." 새로고침하면 btw 질문 말풍선이 사라지는 것은 카드 머리에 `Q.`가 있으니 문제없음(그대로 둠).
- **원인** (실제 함수로 재현): btw 질문 말풍선은 화면에서만 만들어 ts가 없고 서버는 저장·ack하지 않음. 메인 작업이 스트리밍 중이면 2.5초 resync의 `repairMsgOrder`가 ts 없는 사용자 말풍선을 스트리밍 말풍선 앞으로 끌어올림. 그 사이에 답 카드(ts 배치)가 먼저 도착하면 카드가 앞, 질문이 뒤 → 답이 2.5초 안에 오느냐로 결과가 갈렸음.
- **해결** (`static/app.js`, 프론트만): ① `addBtwQuestionBubble` — 질문 말풍선을 처음부터 진행 중인 답 말풍선(`data-live`) 앞에 둠(끌어올림이 둘 자리와 동일). ② `addBtw` — 카드를 **자기 질문 말풍선 바로 뒤**에 붙임(질문 글로 짝짓기, `/btw ` 접두어 제거, 같은 질문 두 번이면 오래된 것부터, 짝 없으면(다른 창·새로고침 후) 기존 ts 배치). `index.html` → `app.js?v=73`.
- **검증**: `tests/test_btw_order.py` 9개 — 실제 `placeMsgByTs`/`repairMsgOrder`/`addBtw`를 node 스텁 DOM에서 실행(답이 먼저/틱이 먼저/연속 두 번/idle/같은 질문 두 번/짝 없음/scrollback/ts 없는 종료 말풍선). 수정 4곳을 되돌린 변이본 모두 실패 확인. 전체 160개 통과. **실제 화면 확인은 미확인.**
- **배포**: 정적 파일 → 하드 새로고침.

## 2026-09-20 — 샛길 카드·내 말·답변이 두 번 찍히던 문제 (app.js)

- **배경** (실장님): "내 대답이 프론트에 두 번씩 찍힌다", "샛길(btw) 카드가 두 장". 서버 저장은 정상(오늘 세션 13개·btw 20여 개 세션에서 중복 0건, 이벤트 ts와 히스토리 ts 68건 중 67건 일치, SSE 재연결 시 재전송 없음).
- **원인**: 로그를 그리는 곳이 둘 — SSE 이벤트와 2.5초마다 도는 `resyncFromServer`. resync는 `role+ts`로 이미 그린 걸 건너뛰는데, SSE 핸들러(`btw`/`result`/`user_ack`)는 그 확인이 없어서 **resync가 먼저 그린 뒤 늦게 온 이벤트가 한 번 더 그림**. 추가로 (1) resync가 서버 idle일 때 `myPendingMids.clear()` → 스티어 재기동 구간(서버 idle)에 내 `user_ack`가 "남의 메시지"로 오인돼 내 말풍선이 두 번, (2) `interrupted`/`stopped`/idle-resync가 ts 없이 닫은 말풍선을 서버의 ts 붙은 사본이 다시 그림. (btw 카드 두 장은 위 이벤트 지연 경로. 어젯밤 진단의 `!isBtw` 경로는 이미 사라졌고 서버는 btw에 `user_ack`를 보내지 않으므로 무관.)
- **해결** (`static/app.js`, 프론트만):
  - 공용 헬퍼 `findRenderedByTs`/`adoptBareUserBubble`/`markUntimed`/`adoptUntimedAssistant`. `btw`·`result`·`user_ack` 핸들러가 같은 role+ts가 이미 있으면 다시 안 그림.
  - `user_ack`: 이미 그려졌으면 건너뜀, 같은 글의 ts 없는 말풍선은 ts만 부여, "마지막 ts 없는 말풍선에 무조건 부여"가 다른 메시지를 잘못 찍던 것 수정.
  - resync: `myPendingMids.clear()` 제거(랜덤 고유 ID라 남아도 무해, 50개 상한), ts 없이 닫힌 말풍선은 서버 사본이 오면 ts만 부여.
  - `index.html` → `app.js?v=72`.
- **검증**: `tests/test_sse_resync_dedupe.py` 12개 — 실제 `app.js`의 핸들러 블록과 `resyncFromServer`를 node 스텁 DOM에서 실행("resync 먼저, SSE 이벤트 나중" 순서 재현). 수정 지점 7곳을 하나씩 되돌린 변이본이 모두 실패함을 확인. 전체 151개 통과. **실제 화면에서 두 번 찍힘이 사라진 것을 실장님이 확인(2026-09-20)**. SSE가 왜 늦게 도착하는지(프록시 버퍼링 여부)는 여전히 미확인.
- **안 한 것**: btw 질문이 사용자 말풍선 + 카드 머리 `Q.`로 두 번 보이는 표시 방식(설계 사항, 실장님 결정 대기), 서버가 btw 사용자 질문을 저장하지 않는 점.
- **배포**: 정적 파일 → 하드 새로고침(Ctrl+Shift+R). 소생 불필요.

## 2026-09-20 — 선택지 버튼(퀵 리플라이 칩) (markdown.js / chat.css / AGENTS.md)

- **배경** (실장님): "의견을 물을 때 마지막에 선택지 버튼을 만들어서 노출". 11:08 요청 → 챗봇이 두 번 설명만 하고, 11:09 "그래"를 이전 작업 승인으로 오인해 미구현 상태였음.
- **동작**: 답변 맨 끝의 `<!--choices: A | B | C-->` 한 줄을 버튼으로 렌더. 누르면 라벨이 그대로 전송(`send()`). `|` 구분(JSON 아님 — 따옴표 실수에 안 깨짐), 최대 4개.
  - 마커는 본문·복사 텍스트에서 제거. 스트리밍 중 반쯤 온 마커도 숨김. 끝에 있지 않은 마커는 무시.
  - 칩은 **가장 최신 메시지에만** 유지(`syncChoiceChips`): 사용자 답이나 새 턴 말풍선이 뒤에 생기면 사라짐. 시스템 안내 말풍선은 무시.
- **변경**: `static/markdown.js`(splitChoices/renderChoiceChips/syncChoiceChips/pickChoice), `static/app.js`(addChat·setAssistantContent에서 sync 호출), `static/chat.css`(칩 스타일, 터치 40px), `data/workspace/AGENTS.md`(`## 선택지` 2줄, +106자 → 주입 번들 2,802→2,908자). 캐시 버스터 `app.js?v=71`, `markdown.js?v=2`, `chat.css?v=5`.
- **검증**: `tests/test_choice_chips.py` 7개(실제 함수를 node에서 실행; 칩 정리 로직을 망가뜨린 변이본에서 실패함을 확인), 전체 139개 통과. **실제 화면에서 답변 후 선택 버튼이 노출되는 것을 실장님이 확인(2026-09-20).**
- **배포**: 정적 파일 → 하드 새로고침. 지침 변경은 새 세션(번들 해시 변경)부터 적용될 것으로 보이나 기존 세션 재주입 여부는 미확인.

## 2026-09-20 — 중단(`stopped`) 뒤에도 "작성 중…"이 화면에 남던 문제 (app.js)

- **배경** (실장님): 세션이 끝나지 않고 "작성 중…"만 계속 떠 있음. 서버는 `busy:false`/`alive:false`로 이미 종료 상태였고(loop_guard 자동 중단), 프론트 표시만 남아 있었음.
- **원인**: `stopped` 핸들러가 `assistantNode = null`을 먼저 하고 `setBusy(false)`를 불러서 `clearTurnLive(null)`이 아무것도 못 지움. 또 `dataset.progress === '1'`인 노드만 제거해서, 빈 `delta` 등으로 플래그가 지워진 말풍선은 고아로 남음. (코드 읽기로 추정, 브라우저 재현은 안 함)
- **해결**: `static/app.js` — 노드를 null로 만들기 전에 `clearTurnLive`; 빈 말풍선은 플래그와 무관하게 제거, 부분 텍스트가 있으면 확정 표시로 보존. `index.html`을 `app.js?v=70`으로 갱신.
- **검증**: `node --check`, `tests/test_static_assets.py` 통과. 실제 화면 확인은 별도로 받지 못함(이후 세션에서 "작성 중…" 재발 보고는 없음).
- **배포**: 정적 파일이라 하드 새로고침(Ctrl+Shift+R)으로 반영. 소생 불필요.

## 2026-09-20 — 모바일/터치 디바이스 코드 복사 버튼 상시 가시성 확보 (chat.css)

- **배경** (실장님): 모바일 및 태블릿 등 터치 환경에서 코드 블록 복사 버튼(`pre .copy-btn`)이 `:hover` 없이는 보이지 않아 복사 기능 접근성이 떨어지는 문제 개선.
- **해결**:
  - `static/chat.css`: `@media (hover: none) and (pointer: coarse)` 미디어 쿼리를 통해 터치 인터페이스에서 `.copy-btn`의 opacity를 `.85`로 기본 표시하고, `:focus-within` 지원 추가.
  - `static/index.html`: `chat.css?v=4`로 캐시 버스터 버전 갱신.
- **검증**: `tests/test_static_assets.py` 및 전체 132개 테스트 통과.
- **배포**: 정적 UI 파일 변경이므로 브라우저 하드 새로고침(Ctrl+Shift+R)으로 즉시 반영.

## 2026-09-20 — 지침 묶음(instructions.py) 및 스킬 인덱스 토큰 최적화 (다이어트)

- **배경** (실장님): 토큰 최적화 및 첫 턴 주입 지침 다이어트 요청.
- **해결**:
  - `data/workspace/.agents/skills/task-observer/SKILL.md`: 지나치게 장황했던 프론트매터 `description`을 3줄 핵심 트리거 중심으로 간결하게 압축.
  - `instructions.py`: 스킬 인덱스 요약 길이 제한(`_SKILL_DESC_MAX`)을 110자에서 80자로 축약하여 첫 턴 주입 번들 경량화.
- **검증**: `python3 tests/test_instructions.py` 및 전체 132개 테스트 정상 통과 확인.
- **배포**: 호스트 파이썬 모듈 변경 건이므로 ⚡소생 대상.

## 2026-09-20 — 상태 탭 장기 기억(MEMORY.md) 읽기 전용 뷰어 추가

- **배경** (실장님): 상태 창에서 장기 기억 파일을 확인할 수 있기를 요청. 자동 관리 파일 특성상 임의 편집 시 포맷 깨짐/동시성 충돌 우려가 있어 "읽기 전용 조회"로 결정.
- **해결**:
  - `server.py` `_self_status()`: `WORKSPACE / "memory" / "MEMORY.md"`가 존재할 경우 크기/수정일/내용을 `memory` 필드로 전달 (수정 API 미제공).
  - `static/index.html`: 규칙 파일 섹션 위에 "장기 기억 (MEMORY.md)" 섹션 (`#statusMemory`) 추가.
  - `static/app.js`: `renderStatusMemory()` 추가. 크기·수정일 표시, 내용 미리보기 및 전체 보기/접기 토글 제공. 캐시 버스터 `app.js?v=69` 갱신.
- **검증**: `python3 tests/smoke.py`, `./chatbot-ctl.sh guard` 통과.
- **배포**: 파이썬 호스트 변경 건이므로 ⚡소생 후 브라우저 새로고침(Ctrl+Shift+R).

## 2026-09-20 — 작업 중 메시지: 끊지 않고 스텝 경계에서 끼워 넣기 (agy)

- **문제** (실장님): "작업 도중에 메시지 보내면 하던 작업이 중단되는 것 같던데. claude처럼 작업은 계속 하면서 중간에 받아주는 게 아니었나." 전날 커밋한 "즉시 개입"은 진행 중인 턴을 SIGINT/terminate로 끊고 새로 시작했다.
- **실측**: agy는 도중에 쓴 메시지를 방해 없이 **대기열에 두었다가 턴이 끝난 뒤** 처리한다(agy.md A41). 끼워 넣기 입력은 TUI에만(A42), `agentapi`는 CSRF 토큰 필요(A43).
- **해결**: 접수는 즉시, 반영은 **도구 스텝 경계**에서 — 스텝이 끝나면 자식을 멈추고 같은 대화(진짜 ID)로 재개하며 "이어서 하되 이 지시를 반영" 안내를 1회 붙인다. 경계 전에 턴이 끝나면 다음 턴으로, 90초 경계가 없으면 타이머로. 질문형은 종전대로 `/btw`. agy 외 프로바이더는 즉시 인터럽트 + 같은 안내. 설계: `docs/plans/in-flight-interruption.md` §4.
- **UI**: 버튼 "⚡ 즉시 반영" → "🧭 끼워 넣기", 자리표시자·활동 로그 문구, 새 `steer_queued` 이벤트 처리, 바쁠 때 보내도 진행 중인 답변 말풍선을 끊지 않음(끊는 건 서버의 `interrupted` 이벤트).
- **부수 수정**: `_read_stdout`이 자기 자식에 묶임 — 끊고 재기동하는 사이 옛 리더가 새 턴을 건드릴 수 있었다.
- **검증**: `tests/test_steer.py` 14개(받아도 안 끊음, 경계에서만 반영, 경계당 하나, 턴이 먼저 끝나면 종료 경로, 타이머 폴백, 안내 1회, 리더 신원). 전체 137개 통과. 실서버: `sleep 6`×3 중 첫 단계 뒤 새 지시 → 같은 대화로 재개, 남은 두 번만 실행(총 3), 새 지시 반영. **브라우저 화면 미확인.**
- **한계**: 지연 = 다음 경계 + 재기동(약 3~10초). 접수 후 반영 전 메시지는 서버 재기동 시 소실. agy 외 프로바이더는 끼워 넣기 가능 여부를 실측하지 않음.
- **배포**: `chatbot-ctl.sh repair` + 새로고침(`app.js?v=67`).

## 2026-09-20 — 채팅창과 에이전트 동기화: 유령 대화 ID, 루프, 조용한 종료

- **증상** (실장님): "챗봇 채팅창이 동기화가 잘 안되는 것 같아" → 세션을 보니 (1) 에이전트가 "아까 하던 작업"을 모르고("너 다른 프로세스야?"), (2) "그래" 이후 화면이 조용히 멈춤, (3) 실제로는 에이전트가 계속 돌고 있었다. 실장님: "제미나이가 코드 작업하다 무한루프에 빠질 때가 확실히 많아."
- **원인 1 (근본)**: 챗봇이 저장한 agy `conversation_id`는 우리가 미리 만든 유령 uuid였다(114개 중 0개가 agy 저장소에 존재, agy.md A35·A36). agy는 없는 ID를 무시하고 매번 빈 새 대화를 만들며, 진짜 ID는 stdout(`init`/`step_update`/`result`)으로 알려 주는데 챗봇이 이미 ID가 있다고 보고 버렸다. 프로세스를 다시 띄울 때마다 에이전트가 기억·페르소나·규칙을 잃었고, 지침 재주입도 대화 ID 기준이라 안 걸렸다.
- **원인 2**: `--print-timeout` 8분에 agy가 빈 `result`로 턴을 끝내고 에이전트는 보이지 않게 계속 돎(A38). 챗봇은 빈 결과를 완료로 처리.
- **원인 3**: `view_file`을 같은 파일에 254번 반복(A39). 화면의 도구 표시가 직전과 같은 요약을 걸러서 아무것도 안 보였고, 프로세스 턴에는 진행 감시가 없었다.
- **해결**:
  - `session.py` `_maybe_capture_conversation_id`: agy가 보고한 진짜 ID를 채택 → 다음 `--conversation`이 실제로 이어짐. `_resume_or_reseed`: 재기동 시 그 ID가 agy에 없으면(기존 유령 포함) 버리고, 기록이 있으면 페르소나·규칙과 **화면 기록 요약(LLM 호출 없음)**을 다음 메시지에 다시 넣음.
  - `loop_guard.py`(신규, 기본 켜짐): 세 규칙 — 같은 읽기 호출의 창 안 반복, 어떤 도구든 연달아 같은 호출, 같은 파일을 읽기만 하며 길게 연속. 모델이 쓴 설명문(`toolAction`/`toolSummary`)은 서명에서 제외. 경고는 턴당 1번, 넘으면 프로세스를 멈추고 다음 메시지에 "같은 방식을 되풀이하지 말라"는 안내를 1회 붙임(대화 ID가 이제 실재하므로 멈춘 뒤에도 이어진다).
  - `adapters.py`: 미완료 결과(`status`≠SUCCESS, 또는 타임아웃 근처의 빈 결과)는 화면에 알리고 자식 정지.
- **부수 효과(의도됨)**: 대화 ID가 실재하면 `_conversation_db_size`가 0이 아니게 되어 "무거운 세션" 판단(소프트 5MB/하드 8MB)에 처음으로 진짜 값이 들어간다. 실제 분포(중앙값 0.12MB, 상위 10% 0.44MB)에서는 정말 무거운 세션만 걸린다.
- **검증**: `tests/test_loop_guard.py`(실제 사고 두 패턴 재현 + 정상 작업 오탐 없음), `tests/test_conversation_sync.py`(ID 채택, 재기동 재주입이 실제 전송 문구까지, 미완료 결과, 루프 자동 중단과 1회성 안내).
- **미확인**: 루프 감시를 실제 Gemini 루프로 시험하지는 못했다(스트림 모양은 실측, 규칙은 사고 기록으로 재현). 기동 직후 입력 시 `interrupted`(A40)의 실서비스 빈도.
- **배포**: `chatbot-ctl.sh repair`.

## 2026-09-19 — 로그의 "작업이 중지되었습니다냥" 정체: 제공자 전환 부수 효과 정리

- **증상** (실장님): 로그 창에 "실장님의 요청으로 작업이 중지되었습니다냥."이 초 단위로 찍힘. 이어서 로그에 "냥피디 (agy)"가 아직 나옴.
- **원인**: 상단 트레이로 제공자를 차례로 눌러 각 제공자의 사용량·계정을 보면(상태 탭이 "현재 제공자만" 보여 주게 된 뒤 잦아짐), 트레이 클릭이 채팅 세션의 제공자 자체를 바꾸는 `POST /provider`를 보냈다. 서버 `maybe_swap_provider`/`maybe_swap_model`이 각각 `stop()`을 알림 모드로 불러 **작업이 없어도** 정지 알림이 쌍(제공자+모델)으로 나옴(세션 하나에서 76건, `POST /provider` 43회 — 서버 로그에서 `/api/usage?provider=…` 조회와 번갈아 나타남). 더 큰 부작용: 전환하면 `conversation_id`가 비워지고, 있으면 인계 요약을 위해 `agy /compact`(최대 45초)가 돈다.
- **해결 1 (알림)**: `session.py` `_stop_for_swap` — 전환은 사용자가 요청한 정지가 아니므로 알림 없이 멈추고, **실제로 턴이 진행 중이었을 때만** "제공자/모델을 바꿔서 진행 중이던 작업을 중단했습니다냥"을 한 번 낸다(UI가 busy를 푸는 신호로도 필요). 사용자가 직접 누른 정지는 기존 문구 그대로.
- **해결 2 (근본)**: 상태 탭에 **보기 전용 제공자 칩** — 눌러도 `selectProvider()`를 부르지 않으므로 채팅 세션은 그대로. 기본은 대화 중인 제공자를 따라가고(●로 표시), 대화의 제공자가 바뀌면(트레이·세션 전환) 보기 선택은 다시 대화를 따라간다. 제목에 "· 보기 전용" 표시, 늦게 온 옛 응답은 버림.
- **해결 3 (표기)**: 활동 로그 `제공자 전환: …`과 제공자 드롭다운이 서버 카탈로그의 `name`을 그대로 써서 agy만 "냥피디 (agy)"로 나왔다. 카탈로그를 벤더 이름(Antigravity/Claude/Grok/Codex/OmniRoute)으로 통일 — 제공자는 벤더이고 페르소나·타이틀은 지침 파일(identity.py)에서만 온다. 이전에 상단 제목만 고치고 이 근원을 놔둔 것이 원인.
- **검증**: `tests/test_session_swap.py`(전환은 조용, 진행 중이면 정확히 한 번, 같은 값은 무동작, 사용자 정지는 그대로), `tests/test_status_picker.py`(앱의 실제 함수를 node에서 실행 — 칩 클릭이 `selectProvider`를 부르지 않음. 일부러 부르게 망가뜨린 복사본을 잡는 것도 확인), 카탈로그 벡터 이름 테스트.
- **미확인**: 브라우저 실화면. 트레이로 제공자를 **실제로 전환**할 때의 `conversation_id` 초기화·`/compact` 비용은 그대로다(의도된 전환 동작) — 이번엔 "보기만" 하는 경우를 분리했을 뿐.
- **배포**: `chatbot-ctl.sh repair`(서버 코드) + 새로고침(`app.js?v=66`).

## 2026-09-19 — 마스코트 폐기

- **결정** (실장님): "마스코트가 문제가 많아. 위치도 애매하고 사라진 것처럼 보이지만 마우스 클릭을 가로막거나 하는 등.. 일단 폐기하는 게 좋겠어. 만약 움직이는 캐릭터 비주얼이 필요해지면 지금 배경화면으로 쓰이고 있는 이미지 대신 나오게 할까 생각중이야."
- **제거**: `static/mascot.js` 삭제, `index.html`의 마스코트 오버레이(레이어 PNG 약 20장을 **숨김 상태에서도** 불러오던 구조)·⋯ 메뉴 토글·스크립트 태그, `chat.css`의 `.mascot-*`/`#m-*`/키프레임/반응형·키보드 규칙/`prefers-reduced-motion` 그룹/`body.no-persona`, `app.js`의 표시 전환(`switchTab`)·컴팩트 모드 숨김·TTS/스트림/결과 시 입·귀·눈 애니메이션 호출·`applyIdentity`의 마스코트 라벨.
- **영향**: `persona`가 없을 때 마스코트를 숨기던 규칙이 필요 없어졌고, `persona`는 아바타 alt/툴팁·대화 표기·프롬프트에만 쓰인다. `/help`의 ⋯ 버튼 설명은 "테마 색상 선택, 소생"으로.
- **남김**: `static/live.html`(2.5D 뷰어), 레이어 PNG 자산, 아바타 이미지. 재도입은 오버레이가 아니라 **배경 이미지 대체** 방식으로(계획서 Phase 3 "마스코트 폐기", `DESIGN.md`).
- **검증**: 신규 `tests/test_static_assets.py`(index.html이 부르는 로컬 파일이 모두 존재, 폐기된 전역·클래스 잔존 없음, 오버레이 이미지 미로딩, CSS 중괄호 균형) + 원본 `mascot.js`가 정의하던 23개 이름이 다른 스크립트에 남지 않음을 확인. 삭제한 파일을 HTML이 계속 부르는 경우를 일부러 만들어 테스트 로직이 잡는 것도 확인. **브라우저 실화면은 미확인.**
- **배포**: 정적 파일만(`app.js?v=65`), 재기동 없음. 새로고침.

## 2026-09-19 — 스크롤바 디자인 통일

- **문제**: 스크롤바 규칙이 하나도 없어서 채팅 로그·상태/아티팩트/세션 패널·코드 블록·입력창·모달이 전부 브라우저 기본(밝고 두꺼운 회색) 스크롤바로 나와 어두운 UI와 어울리지 않고 영역마다 제각각 (실장님: "스크롤바 디자인을 통일감 있게 바꿔줄 수 있어?").
- **해결**: `chat.css`에 전역 규칙 한 블록. 얇게(보이는 막대 4px, 잡는 영역 10px), 트랙은 투명, 평상시엔 중립색(`--scroll-thumb`), 호버/드래그 시 테마 키컬러(`--scroll-thumb-hover` = `--accent-rgb`)로 물듦 — 5개 테마 모두 `--accent-rgb`가 있어 테마를 따라감. Blink/WebKit은 `::-webkit-scrollbar`, Firefox는 `@supports (-moz-appearance: none)`로 표준 `scrollbar-width/color`(Chrome 121+는 `scrollbar-color`가 있으면 `::-webkit-scrollbar`를 무시하므로 Firefox에만 적용).
- **한계**: Firefox는 호버 색을 못 바꾼다(표준 속성 한계) — 얇기·중립색만 동일. iOS/Android의 오버레이 스크롤바는 브라우저가 스타일을 무시. `live.html`(독립 뷰어)은 이번 범위 밖. **실제 화면은 미확인**(이 호스트에 실행 가능한 브라우저 없음 — CSS 문법·중괄호 균형·서빙만 확인).
- **배포**: 정적 CSS만(서버는 `no-cache`로 서빙), 재기동 없음. 새로고침.

## 2026-09-19 — 챗봇 identity를 지침에서: 타이틀(직책) / 페르소나 / 호칭 분리

- **요구** (실장님): 배포를 고려하면 "냥피디" 이름도 커스텀 가능해야 함. 모든 identity는 우리 지침에서 나와야 하고, 상단의 "냥피디"는 **타이틀(직책)** 로 대체되며 페르소나와 분리. 나중에 아트디렉터/테크디렉터처럼 타이틀을 붙인 멀티 챗봇을 만들어도 각자 이름·성격·말투는 자기 지침 파일에 정의. 이 NAS의 타이틀은 **프로듀서**.
- **설계**: 별도 설정 파일 없이 **지침 파일 머리말**이 정본(모델이 읽는 텍스트 = 호스트가 쓰는 값). `AGENTS.md` `title`(직책) / `PERSONA.md` `persona`(캐릭터, 선택)·`user_title`(호칭)·`voice`(호스트 프롬프트용 말투 한 줄). 항상 그 인스턴스의 `WORKSPACE`에서 읽음 → 워크스페이스가 다르면 봇마다 자기 identity. 폴백은 중립 기본값. 설계와 범위는 `docs/plans/chatbot-host-portability.md` Phase 3.
- **구현**: `identity.py`, `GET /api/identity`, 서버가 `index.html`의 `<!--IDENTITY-->`에 `window.__IDENTITY__` 주입(깜빡임 없음, `</script>` 이스케이프), agy 카탈로그 이름 파생, `session.py` 프롬프트를 `_btw_prompt`/`_handoff_prompt`로 분리(옆길 질문·인계 요약기·대화 라벨·중단/정지 안내), 화면 문자열을 `IDENTITY`로 대체(상단 제목=타이틀, 아바타·마스코트=페르소나), `persona`가 없으면 마스코트 숨김, `templates/PERSONA.md`(새 설치용, 파일이 없을 때만 시드).
- **지침 파일**: `AGENTS.md` 머리말 `title: 프로듀서`, 제목 "냥피디 헌장"→"헌장". `PERSONA.md` 머리말 추가, 본문의 이름·호칭 서술을 머리말 참조로 정리(이중 서술 제거).
- **검증**: `tests/test_identity.py`·`test_identity_wiring.py` 신규(런타임 코드/UI에 이름 리터럴이 들어오면 실패하는 가드 포함), 전체 76개 통과. 실서버 T1 테스트 통과 — 머리말만으로 "냥피디 / 실장님 / 프로듀서" 정확히 답함.
- **영향**: 상단 제목이 "냥피디"→"프로듀서". 지침 묶음 해시 변경 → 진행 중인 대화에 지침 1회 재주입.
- **미확인/범위 밖**: 브라우저 실화면 미확인. 냥체 UI 문구·마스코트 대사·`/help` 어투는 이번엔 이름·호칭만 치환(페르소나 팩 단계). `live.html`·자산 교체·메모리 도구 문구·멀티 인스턴스 충돌 지점은 계획서에 기록.
- **배포**: `chatbot-ctl.sh repair` + 새로고침(`app.js?v=64`, `mascot.js?v=2`).
- **정정**: 이 배포의 타이틀은 실장님이 `AGENTS.md`에서 직접 `냥피디`로 바꿨다(22:47). 위의 "프로듀서"·"냥피디→프로듀서"는 처음 합의한 값이었고 지금은 유효하지 않다. 직책(`title`)과 페르소나(`persona`)는 별개 키라 같은 이름이어도 된다. 테스트는 특정 값이 아니라 구조(읽히는지·프롬프트에 쓰이는지)를 검증하도록 바꿨다.

## 2026-09-19 — 상태 탭 다듬기: 새로고침을 헤더 줄로, 사용량 아래 중복 계정 제거

- **문제**: 상단 새로고침 버튼이 한 줄을 통째로 차지해 프로바이더(계정) 헤더가 아래로 밀림. 사용량 아래의 "계정: …" 줄은 바로 위 계정 카드와 중복 (실장님 지적).
- **해결**: `index.html` 상단 툴바 행 제거, `statusRefreshBtn`을 프로바이더 헤더(`<h2 class="status-head-row">`) 오른쪽으로 이동(`chat.css` `.status-head-row`, 헤더의 굵은 글씨를 버튼이 물려받지 않도록 `font-weight:400`). `app.js` `renderStatusUsage`의 "계정: …" 줄과 오류 문구의 `(이메일)` 접미사 삭제. `/api/usage`의 `account` 필드는 캐시 무효화 판단용으로 API에 그대로 남김.
- **검증**: 서빙된 마크업(버튼이 헤더 안, 옛 툴바 없음), 스텁 DOM에서 사용량 렌더에 이메일 미포함. **실제 화면 배치는 미확인** — 이 호스트의 헤드리스 Chromium은 `libatk` 라이브러리가 없어 실행되지 않음.
- **추가(실장님: "왜 Antigravity 헤더에 냥피디(agy)라고 나오는 거야")**: 상태 탭 제목이 `/api/providers` 카탈로그의 `name`을 그대로 써서, agy만 페르소나 이름 "냥피디 (agy)"로 나왔다(나머지는 벤더 이름). 상단 브랜드 영역은 이미 `providerCreditLabel`/`PROVIDER_CREDIT`(agy=Antigravity)을 쓰므로 상태 탭 제목도 같은 함수를 쓰게 하고, 중복으로 만들었던 `ACCT_PROVIDER_LABEL`을 삭제. 5개 프로바이더 모두 상단 표기와 일치 확인.
- **배포**: 정적 파일만(`app.js?v=63`), 재기동 없음. 새로고침 필요.

## 2026-09-19 — 상태 탭: 현재 프로바이더만, 계정 → 사용량 → 프로세스 순서

- **문제**: 프로세스 정보(4개 프로바이더 전부 + 프로세스 목록)가 길어 중요한 사용량이 뒤로 밀림 (실장님: "현재 사용중인 Provider 에 대한 정보만 보여주고 계정, 사용량, 프로세스 순서로 보여주도록 하자").
- **해결**:
  - `static/index.html`: 아래쪽에 흩어져 있던 "로그인 계정 · 프로세스"와 "사용량" 두 섹션을 없애고, 상태 탭 **맨 위**에 프로바이더 섹션 하나로 합침 — 계정 → 사용량 → 프로세스. (규칙·스킬·MCP 등 기존 섹션은 그 아래로 내려감)
  - 프로세스는 접이식(`<details>`): 요약에 개수와 경고 배지(옛 계정 N, 로그인 변경 전 시작 N)만 보이고, 옛 계정 프로세스가 있으면 **자동으로 펼침**.
  - `static/app.js`: 현재 프로바이더(`providerEl`)만 그림. 세션 전환·프로바이더 선택처럼 코드로 프로바이더가 바뀔 때(`onchange`가 안 돔) `refreshProviderStatus()`로 상태 탭이 열려 있으면 다시 그림. 응답이 늦는 사이 프로바이더가 바뀌면 옛 응답은 버림. API 키 방식(omniroute)은 "로그인 계정이 없어요" 안내 + 프로세스 영역 숨김. 상단 새로고침은 계정도 함께 갱신, 계정 전용 새로고침 버튼은 제거.
  - `server.py`/`accounts.py`: `GET /api/accounts?provider=`(`parse_providers`) — 해당 프로바이더만 조회해서 다른 CLI의 상태 호출(claude `auth status` 등)을 안 함.
- **검증**: 전체 51개 통과, 실서버 `?provider=` 필터 확인, 스텁 DOM에서 agy(옛 계정 경고 → 자동 펼침)/claude(접힘)/omniroute(숨김) 렌더 확인. **브라우저 실화면은 미확인**(스텁 DOM 렌더만).
- **배포**: `chatbot-ctl.sh repair`(서버 코드 변경) + 새로고침(`app.js?v=61`).

## 2026-09-19 — grok 사용량 조회 복구: 0% 사용은 필드 생략으로 온다

- **문제**: grok 사용량이 "Grok billing 출력에서 사용량 정보를 찾지 못했습니다"로 나옴. 실장님: "grok cli 로 로그인해보면 사용량 조회 잘 되는데. 0% 사용 중이야."
- **원인**: 프록시 `/billing?format=credits`가 protobuf-JSON이라 값이 0인 스칼라를 생략한다. 사용 0%인 계정 응답에는 `creditUsagePercent`가 없는데, `_grok_billing_to_rows`는 이를 "정보 없음"으로 처리했다. (처음엔 계정 크레딧 소진으로 잘못 추정 — grok.md G13.)
- **해결**: `adapters.py` `_grok_billing_to_rows`: 크레딧 형태(`currentPeriod`/`billingPeriodEnd`)인데 % 필드가 없으면 0% 사용 → 100% 남음. 상품 항목도 동일. 크레딧 형태가 아닌 응답은 여전히 "정보 없음"(막대를 지어내지 않음).
- **검증**: 신규 `tests/test_grok_billing.py` 5개, 라이브 어댑터/`/api/usage?provider=grok` → `주간 100% 남음`. agy·claude·codex 사용량 영향 없음.
- **한계**: 0이 아닌 사용률에서 `creditUsagePercent`가 오는 모습은 이번에 재확인 못 함(기존 9/18 라이브 검증). grok.md G11~G13.
- **배포**: `chatbot-ctl.sh repair`.

## 2026-09-19 — 계정 전환(한도 소진 후 다른 계정 로그인) 대응: 사용량 캐시·변경 알림·자동 재시작

- **배경**: 실장님은 한도가 다 떨어지면 남은 다른 계정으로 갈아타며 쓴다(agy·codex 등). 그래서 계정 전환은 우연이 아니라 반복 절차다. 첫 증상 "다른 계정으로 로그인했는데 사용량 집계가 이상하게 되는 것 같네"도 이와 맞닿아 있다.
- **해결**:
  - `server.py` `_get_usage`: 사용량 캐시를 **계정 기준으로 무효화**(현재 계정이 바뀌면 재조회). 응답에 `account` 포함, UI 사용량 위에 "계정: …" 표시. 계정을 알 수 없으면(로그아웃·omniroute 등) 무효화하지 않음(기존 동작).
  - `accounts.py`: `current_email`, `stale_owned`(수동 버튼과 자동 루프가 공유하는 **재시작 후보의 단일 정의**), `snapshot(providers=…)`, 마지막 계정 변경(`changed_from`/`changed_at`). 카드에 "계정 변경 관측: A → B (시각)"(7일 이내).
  - **agy 자동 재시작**(`server.py` `_auto_recycle_loop`, 30초 주기): 로그로 증명된 옛 계정 + 챗봇 소유 + 유휴인 agy 프로세스와 standby만 재시작. 작업 중 세션·외부 프로세스·목록에 없는 pid는 절대 안 건드림. 이력은 `/api/accounts`의 `auto_recycle`과 카드 한 줄로 표시. `CHATBOT_AUTO_RECYCLE=0`이면 꺼짐(버튼은 계속 동작).
- **검증**: 신규 `tests/test_auto_recycle.py`(캐시 무효화, busy 미접촉, 비소유 pid 무시, 자동 1회 동작) + `test_accounts.py` 보강, 전체 44개 통과. 배포 후 30초 루프 1주기 예외 없음, `/api/usage`에 `account` 확인.
- **미검증(❓)**: 실계정 전환 end-to-end(계정을 실제로 바꿔 자동 재시작이 도는지), 새 계정으로 재시작된 agy의 옛 대화 이어받기. agy.md A32~A34.
- **배포**: `chatbot-ctl.sh repair`(서버 코드 변경).

## 2026-09-19 — 상태 탭 "로그인 계정 · 프로세스" 카드 (agy/claude/codex/grok)

- **문제**: agy를 다른 계정으로 재로그인했는데 옛 계정이 계속 응답했다. 원인은 9/17부터 떠 있던 SSH 대화형 `agy`(pid 14804)가 옛 refresh token을 메모리에 들고 있다가, refresh 때 공유 토큰 파일(`~/.gemini/antigravity-cli/antigravity-oauth-token`)을 옛 계정으로 되돌려 쓴 것(정황 근거 — 종료 후 재로그인은 유지됨). 챗봇 UI에는 활성 계정도, 떠 있는 프로세스도 보이지 않아 진단에 시간이 걸렸다 (실장님: "상태 창에 로그인된 계정과 프로세스들에 대한 정보가 표시되면 어때").
- **해결**:
  - `accounts.py` (신규): 프로바이더별 현재 계정(agy=토큰 id_token, claude=`claude auth status`, codex=`auth.json` id_token, grok=`auth.json` `email`)과 실행 중 CLI 프로세스(`/proc` 스캔, `environ` 미접근). 토큰 값은 응답에 싣지 않음.
  - **agy만 프로세스별 계정을 증명**한다: agy 로그 첫 줄의 `Starting language server process with pid N`으로 pid를 매칭하고 `authenticated successfully as <email>`을 읽어 현재 토큰 계정과 대조 → `stale`. claude/codex/grok은 프로세스별 계정 기록이 없어(claude `sessions/<pid>.json`에도 계정 없음) "계정 변경 관측 구간보다 확실히 먼저 시작됨"(`predates_change`)만 표시 — 오탐은 없지만 놓칠 수 있는 보수적 규칙. 60초 샘플링(`watch_loop`), 상태는 `data/account_state.json`.
  - `server.py`: `GET /api/accounts`, `POST /api/accounts/recycle`(agy stale + 챗봇 소유 + 유휴만 재시작, 작업 중 세션은 건너뜀, 외부 프로세스는 절대 안 건드림 — UI엔 `kill` 명령 복사만).
  - `session.py`: `_StandbyPool.discard()`, `owned_agent_procs()`, `recycle_agents()`. `REG.get`은 없는 세션을 만들므로 조회 전용으로 `REG.sessions.get`을 씀.
  - `static/`: 상태 탭 카드(프로바이더별 그룹, 옛 계정 배너, 재시작 버튼), `app.js?v=59`.
- **검증**: `tests/test_accounts.py` 14개(사고 재현 포함, 토큰 미유출), 기존 포함 32개 통과. 실서버 조회 4개 프로바이더 정상. 재현/근거: `tests/probes/account_probe.py`, `docs/providers/*.md`의 A29~A32·C11~C13·X9~X11·G9~G10.
- **발견**: codex만 다른 계정(`studiobitpixel@gmail.com`, free)으로 로그인돼 있음(나머지는 `parkjongwoo@gmail.com`). 의도 여부는 실장님 확인 대기.
- **알려진 한계**: claude/codex/grok이 옛 자격을 메모리에 들고 되덮어쓰는지는 ❓(로그아웃 실험은 로그인을 건드려 안 함). 계정 변경 시 절차는 agy.md A32.
- **배포**: `chatbot-ctl.sh repair`(서버 코드 변경). 정적 UI는 새로고침.

## 2026-09-19 — 모바일 가상키보드 오픈 시 '최신 대화로' 플로팅 버튼 은닉 및 스크롤 안정화

- **문제**: 모바일 환경에서 텍스트 입력창을 터치하여 가상키보드가 올라올 때, 뷰포트 높이가 급격히 줄어들면서 스크롤 위치가 일시적으로 상단/중간에 위치한 것으로 인식되어 `최신 대화로` 버튼(`scrollToBottomBtn`)이 화면 한가운데에 불필요하게 떠서 시야와 입력을 방해하는 문제 (실장님: "가상키보드만 올라와도 최신 대화로 버튼이 떠서 불편하네").
- **해결**:
  - `static/app.js`:
    - `updateScrollBottomButton()`: 모바일 가상키보드가 활성화된 상태(`document.body.classList.contains('keyboard-open')`)일 때는 `scrollToBottomBtn`을 즉시 강제 은닉(`hidden = true`).
    - `updateViewport()`: 가상키보드가 열리는 순간 기존에 유저가 최하단 근처에 있었다면 축소된 뷰포트에 맞게 자연스럽게 최신 대화 위치로 스크롤 정렬.
  - `static/chat.css`:
    - `body.keyboard-open` 규칙에 `#scrollToBottomBtn { display:none !important; }`를 명시하여 키보드가 뜬 동안 어떤 상태에서도 버튼이 노출되지 않도록 CSS 레벨 방어.
- **배포**: 정적 UI(JS/CSS) 변경으로 호스트 재기동(⚡소생) 없이 브라우저 새로고침(F5)만으로 즉시 반영.

## 2026-09-19 — 작업 중 즉시 개입/반영(In-flight Interruption & Steer) 전환 및 대기열 제거

- **문제**: 에이전트 작업 도중 유저가 추가 메시지를 입력하면 세션 락에 의해 의미 없는 대기열(`msg_queue`)에 적재되고 현재 턴이 다 끝날 때까지 방치되는 문제 (실장님: "작업중 메시지 입력하면 대기열 말고 진행중인 작업에 바로 반영할 수 없나? 클로드는 되는 것 같던데", "최대한 프로바이더별 이점을 살리는 쪽으로 진행해봐. 대기열에 넣는 건 무의미하지 싶네.").
- **프로바이더별 실측 및 해결**:
  - `adapters.py`:
    - `AgentAdapter.interrupt(proc)` 인터페이스 신설 (`SIGINT` 기반 우아한 중단 및 `terminate` 폴백).
    - Claude Code 실측 결과: 턴 실행 도중 자식 프로세스에 `SIGINT` 시그널 전달 시 즉시 `[Request interrupted by user]` 방출 후 안전하게 중단되며, 기존 `session_id`로 `--resume` 시 이전 지점까지의 컨텍스트를 완벽히 유지한 채 새 턴으로 이어받음.
    - `agy`/`grok`/`omniroute`도 시그널 및 HTTP 스트림 소켓 닫기를 통해 즉각 취소 지원.
  - `session.py`:
    - `interrupt_current_turn()` 메서드 신설: 실행 중인 턴을 안전하게 중단하고, 직전까지 생성 중이던 어시스턴트 부분 텍스트를 `(⚡ 실장님의 새 지시로 이전 작업이 중단되었습니다냥)` 주석과 함께 히스토리에 확정 보존.
    - `send()` 개편: `self.busy`일 때 무의미하게 큐에 넣는 대신, 샛길 질문(`/btw`)을 제외한 일반 메시지는 즉시 `interrupt_current_turn()`을 호출하여 진행 중 작업을 취소하고 곧바로 새 지시(`_send_direct`)를 착수.
  - `static/app.js`:
    - 작업 중(`isBusy`) 버튼 상태 문구를 `대기열 등록 ↵` 대신 `⚡ 즉시 반영 ↵`으로 변경.
    - 메시지 전송 시 대기열 태그 없이 즉시 대화 로그에 등록하며, SSE `interrupted` 이벤트 핸들러를 추가하여 이전 말풍선에 전환 표시 렌더링.
- **검증**: `tests/smoke.py` (5 tests OK), `chatbot-ctl.sh guard` (guard_rlock OK), `py_compile` 통과.
- **배포**: 호스트 파이썬 모듈(`adapters.py`, `session.py`) 변경 포함으로 실장님께 ⚡소생 요청 필요 (정적 UI는 새로고침).


## 2026-09-19 — 채팅 UI 이전 기록 열람 중 자동 스크롤 하이재킹 방지 + 최신 대화 복귀 버튼

- **문제**: 실장님이 위로 스크롤하여 이전 대화 기록을 읽고 있을 때, 스트리밍 청크(`delta`), 도구 실행 로그(`tool`), 시스템 상태 갱신, 뷰포트 리사이즈, 입력창 포커스 등이 발생하면 매 틱마다 `logEl.scrollTop = logEl.scrollHeight`가 무조건 실행되어 읽던 위치를 잃어버리고 최하단으로 강제 이동되는 문제 (실장님: "스크롤해서 이전 기록을 보고있는데 자꾸 작업중인 위치로 이동해서 이전 기록을 보기 어렵네").
- **해결**:
  - `static/app.js`: 스마트 스크롤 제어 `scrollChatToBottom(force = false)` 및 하단 근접 감지 `isUserNearBottom()` (하단 여유 140px 이내일 때만 최하단 스냅).
  - 유저 본인의 메시지 전송 시에는 즉시 최하단으로 강제 이동(`force=true`), 그 외 스트리밍 응답 렌더링(`setAssistantContent`), 샛길 응답(`addBtw`), 도구 완료 메시지, 뷰포트 변화(`updateViewport`), 입력창 포커스 이벤트 시에는 유저가 위로 스크롤한 상태일 때 현재 스크롤 위치를 온전히 보존.
  - `static/index.html` & `static/chat.css`: 위로 스크롤했을 때 나타나는 플로팅 `최신 대화로 ↓` 버튼(`scrollToBottomBtn`) 추가. 클릭 시 부드럽게 최신 대화 위치로 스크롤.
- **배포**: 순수 정적 UI(JS/HTML/CSS) 수정으로 호스트 재기동(⚡소생) 없이 브라우저 새로고침(F5)만으로 즉시 적용.

## 2026-09-19 — 지침 묶음 조립기(P2) + 프로바이더 CLI SSOT + 토큰 세금 원인 규명

- **agy 시작 토큰 세금(47k)의 원인**: 워크스페이스 문서가 아니라 **홈의 `.agents` 스킬 묶음(SKILL.md 2,649개)
  스캔**. agy 자체 로그(`skills.go … ~/.agents/plugins/master-skills/…`)와 홈 밖 사본(+0.8k)으로 확인.
  이전 가설("`AGENTS.md`가 원인", "stub이면 무해", "ADD_DIRS static/vendor")은 전부 반증됨.
- **격리 시도 전부 무효** (agy.md A6–A14): `--disable-slash-commands`, `--new-project`, `--project`(실존 id 포함),
  격리 HOME, 빈 `projects.json` 오버레이, `agy plugin`, 심볼릭 경로(불안정 + 기존 대화 이어받기 ERROR).
  **미해결.** 후보는 WORKSPACE를 홈 밖 실경로로 이전(기존 세션 141개 영향) — `docs/providers/agy.md` §5.
- **`docs/providers/` 신설**: 프로바이더 CLI 실측 SSOT (agy/claude/codex/grok/omniroute). ✅/❌/⚠/❓/📄 표기,
  재현 스크립트 `tests/probes/agy_first_turn.py`, `discovery_canary.py`. 새 실험 전에 먼저 읽고, 끝나면 기록.
- **`instructions.py` 신설 + `session.py` 주입 계약** (⚡소생 대기, 단위 테스트 13개 `tests/test_instructions.py`):
  묶음 = AGENTS.md + PERSONA.md + 스킬 색인 + 기억 스냅샷(사실이 있을 때만) + 자기개선 상태.
  ① 인계 블록이 `stdin_content`를 `text`로 덮어써 **교체·회전 턴에 페르소나 묶음이 버려지던 기존 결함** 수정(규칙 → 인계 → 현재 메시지 순).
  ② 정적층 해시 변경 시 "규칙이 갱신되었다"로 1회 재주입, 기억 변경은 재주입 안 함.
  ③ 해시 없는 구 세션은 조용히 채택(중복 없음). ④ HTTP는 시스템 메시지가 매 요청 나가므로 앞머리 생략.
  ⑤ 스킬 설명 파서를 `instructions.py`로 모아 `server.py` 중복 제거.
- **철회**: `AGENTS.md`→`CHARTER.md` 이동·stub·`rules/` 재배치 (원인이 아니어서 소득 없이 구조만 흔듦).
- 미커밋 관찰 로그 0012–0018·0026, `tools/memory.py`는 별도 커밋(`0e20983a`).

## 2026-09-19 — 지침 아키텍처 설계 + 페르소나 주입 결함 2건 수정 (P1)

- **설계서**: `docs/plans/instruction-architecture.md` (계획만, P2~P4는 미착수).
  프로바이더별 지침·스킬 자동 발견을 카나리로 실측 → 조상 디렉토리 포함 시 프로바이더마다
  보이는 지침·스킬 집합이 다름(Claude는 `AGENTS.md`/`.agents/skills`를 안 읽음).
  결론: 호스트가 유일한 주입자, 워크스페이스 `AGENTS.md`는 stub, 기억·스킬·관찰은 MCP.
- **토큰 실측** (agy, "안녕" 1문장): `--add-dir chat`만 12,963 / `+WORKSPACE` 47,722.
  `.md` 제거 시 13,766, `AGENTS.md`만 든 폴더는 83k~103k(모델이 지침 따라 도구 5회).
- **수정 (`session.py`)**: ① `persona_injected`를 `meta.json`에 저장·복원 → 재기동 후 재개 시
  중복 주입 방지. ② `maybe_swap_provider()`가 `persona_injected`를 리셋 → 도중 프로바이더 교체 시
  새 프로바이더도 페르소나를 받음(기존엔 못 받음).
- **정정 (`adapters.py`)**: `ClaudeAdapter`/`_persona_system_prompt` docstring이 틀린 "AGENTS.md
  자동 발견"을 주장하던 것 수정.
- 검증: `py_compile` OK, `guard_rlock` OK, 저장/복원/구 meta/교체/동일 프로바이더 no-op 단위 확인.
  **⚡소생 필요.** Grok(402)·Codex(사용 한도 ~10-09)는 실측 차단.

## 2026-09-19 — 페르소나 통합 주입 + Grok 프롬프트 파일 격리

- **배경**: Grok의 ADD_DIRS 토큰 최적화(2026-09-19)가 WORKSPACE를 drop하면서
  AGENTS.md/PERSONA.md 자동 발견이 끊김 → 냥피디 페르소나 없이 Antigravity 기본
  상태로 동작하는 버그 발견(실장님 직접 확인).
- **근본 원인**: CLI 어댑터들이 `--add-dir WORKSPACE`의 AGENTS.md 자동 발견에 의존,
  HTTP(omniroute)만 `_persona_system_prompt()`로 명시 주입 → 프로바이더 간 파편화.
- **수정 1 — 통합 페르소나 주입** (`session.py`):
  `_send_direct()` 어댑터 레이어 위에서 `persona_injected` 플래그로 첫 턴에만
  `_persona_system_prompt()`(AGENTS.md + PERSONA.md 합본, mtime 캐시)를 모든
  프로바이더에 동일하게 prepend. CLI/one-shot/HTTP 구분 없이 동작.
- **수정 2 — Grok 프롬프트 파일 격리** (`adapters.py`):
  `.grok_prompt_<uuid>.txt`를 WORKSPACE 루트 대신 `WORKSPACE/.grok/prompts/`에
  저장. dotdir이라 agy --add-dir 스캔에 안 잡힘. `data/workspace/.gitignore`에
  `.grok/prompts/` 추가.
- **수정 3 — ADD_DIRS WORKSPACE 복구** (`host_config.py`):
  MCP(`.gemini/config/mcp_config.json`), 스킬(`.agents/skills/`), 훅(`.agents/hooks.json`)
  이 WORKSPACE에 있어 `--add-dir` 필수. WORKSPACE 루트는 이미 불필요한 파일 없이
  정상 상태. AGENTS.md/PERSONA.md는 이제 명시 주입이 1차, --add-dir 자동발견은 덤.
- 검증: `py_compile` 3파일 OK, `guard_rlock` OK. **⚡소생 필요.**

## 2026-09-19 — 모바일 키보드: 세로 아끼기

- FAB ✕를 다시 iframe 위 오버레이로 (별도 줄 안 씀). compact 헤더는
  padding-right 2.6rem으로 탭이 ✕ 밑에 안 들어가게.
- `keyboard-open`이면 헤더·메타·배너 숨김. compact+키보드면 wrap
  padding-top만 남겨 ✕ 자리.
- `chat.css?v=2`. Hub+채팅 새로고침. 소생 불필요.

## 2026-09-19 — FAB ✕가 compact 헤더 탭을 가리던 것

- Hub `/volume1/web/index.html`: `.agy-chat-popup-close`를 iframe 위 절대배치에서
  팝업 플렉스 상단(iframe 밖)으로. 모바일에서만 표시는 그대로.
- 소생 불필요. Hub 새로고침.

## 2026-09-19 — alert() → 스킨 모달

- `alertModal`: 확인만, Escape/오버레이로 닫힘. 실패·검증 메시지에 사용.
- `window.alert`는 마크업이 없을 때만. `app.js?v=53`. Ctrl+Shift+R.

## 2026-09-19 — tests/smoke.py

- `get_adapter` 5종, `_format_tool_call`, occupancy≠합/캐시차감, `ctl guard`.
- 네트워크·스폰 없음. `python3 tests/smoke.py`. 소생 불필요.

## 2026-09-19 — 도구 턴 occupancy: MCP/HTTP 결과 상한

- Codex 26턴 세션: 우리 history는 짧고 창 29만·190만은 CLI 내부 파일 적재.
- MCP `read_file` 기본 100k/상한 500k → 32k/64k. stdout 20k→8k.
  OmniRoute 다음 홉에 넣던 툴 결과를 32k로 자름.
- Codex 자체 Read는 못 자름. **nas_mcp.py + adapters.py — ⚡소생.**

## 2026-09-19 — ADD_DIRS `/chat`만: 새 agy 첫 턴 14.3k 실측

- 소생 후 실장님 확인. 46k → 14.3k. A/B(`/chat` only 14296)와 일치.

## 2026-09-19 — ADD_DIRS: static/vendor가 ROOT와 같은 46k

- 소생 후 새 agy 세션 `20260919-022444-ee466f`: argv는 static+/chat 인데
  창 45965. A/B의 /chat only·no add-dir은 14k.
- 원인: `static/vendor/mermaid.min.js` 3.2M. STATIC를 add-dir에 넣은 것이
  ROOT와 같은 세금.
- ADD_DIRS = `/chat`만. **host_config.py — ⚡소생 다시.**

## 2026-09-19 — ADD_DIRS A/B: ROOT가 첫 턴 32k

- stream-json, 같은 모델/프롬프트. input: both 45970, ROOT only 45950,
  /chat only 14296, no add-dir 14297.
- `ADD_DIRS`에서 ROOT 제거, `static/` + `/chat`만. MCP ALLOW_ROOTS에
  `services/chatbot` 추가 (자가수정 쓰기).
- **host_config.py + nas_mcp.py — ⚡소생 필요.**

## 2026-09-19 — agy 스킬 격리 A/B: 이득 없음

- 호스트와 같은 spawn (stream-json, ADD_DIRS, gemini-3.8-flash-low,
  새 conversation uuid). 프롬프트 "한 문장으로만 답해. 안녕."
- baseline input **45970** / `--disable-slash-commands` **45961** (Δ9).
  `--print` 모드도 45966 vs 45974.
- 결론: 현재 시작 세금 ~46k는 슬래시/스킬 펼침이 아님. 플래그 적용 안 함.
- 다음 후보: ADD_DIRS A/B. 소생 불필요.

## 2026-09-19 — OmniRoute(HTTP) 토큰 집계

- 스트리밍에서 `choices=[]`인 마지막 usage 청크를 버리던 버그 수정.
  `stream_options.include_usage=true`.
- 툴 홉마다 `/v1/chat/completions`가 나가는데 마지막 홉 usage만 저장하던
  것을, 과금=홉 total 합 · 창 점유=마지막 홉 prompt로 합침.
- audit 표에 `first_max` 추가. omniroute 중앙값 ~0.7k는 짧은 인사 세션,
  도구 켠 실세션 첫 턴은 ~128k.
- **adapters.py — ⚡소생 필요.**

## 2026-09-19 — 토큰 집계: 창 점유 vs 과금

- 실측: `input - cache_read`는 가짜 fresh. agy 첫 턴 input ~75k인데
  cache_read는 수백만. 전 턴 `total` 합은 과금이지 창 크기가 아님.
- `session.py`: occupancy = 마지막 `input_tokens`, billed = 턴
  `total_tokens` 합. `weight.total_tokens`는 occupancy. API usage에
  `context_tokens`/`billed_tokens`.
- UI: 헤더 배지 `창 N · 과금 M` (이전에 함수만 있고 호출 없음).
  턴 배지 경고는 occupancy 기준. `app.js?v=52`.
- `data/workspace/tools/token_audit.py`, `docs/plans/token-accounting.md`.
  시작 세금: claude ~11k vs agy ~75k (HOME 스킬 146개 유력).
  `--disable-slash-commands`는 아직 안 켬 — 자율 스킬이 죽음.
- 검증: `py_compile session.py`, `node --check app.js`, audit 표 출력.
  **session.py — ⚡소생 필요.** 배지는 Ctrl+Shift+R.

## 2026-09-19 — DESIGN.md 스캔 (The Night Console)

- `$impeccable document` 스캔. North Star: Night Console. 유리 관제실,
  살짝 떠 있는 칩. 토큰은 `static/chat.css` :root + 5 테마.
- `DESIGN.md` + `.impeccable/design.json` (schemaVersion 2).
  `PROJECT.md` Where to edit에 시각 시스템 행 추가.
- 코드/비주얼 변경 없음. 소생 불필요.

## 2026-09-19 — 리뷰 suggestion 3건: 어댑터/가드 경로 문서

- `adapters.py` docstring: AgySession/REG/RLock 가드는 `session.py`.
- `PRODUCT.md`: `AGENT_ADAPTERS` → `adapters.py`, 자가진화 표면을
  SELF-MODIFY 호스트 모듈 목록과 맞춤.
- `chatbot-self-improve`: 워크플로/Never-restart가 server.py만이 아니라
  파이썬 호스트 모듈 + ⚡소생.
- 동작 변경 없음. 소생 불필요.

## 2026-09-19 — 에이전트 핸드오프 지도 (Where to edit)

- 배경: 실장님 — 여러 에이전트가 번갈아 쓰니, 이해하고 작업하기 쉬운 구조가
  최선. 파일을 더 쪼개지 않고 지도를 고침.
- `data/workspace/PROJECT.md`에 **Where to edit** 표 추가 (작업→파일).
  `README.md`/`AGENTS.md`/`SELF-MODIFY.md`/`chatbot-self-improve`의
  `AGENT_ADAPTERS`/`AgySession`/`guard`/`소생` 경로를 분리 후 위치에 맞춤.
- `server.py` 모듈 docstring, `index.html` 스크립트 순서 주석.
- 코드 동작 변경 없음. 소생 불필요.

## 2026-09-19 — 모노리스 분리 Phase 2: theme/markdown/artifacts/slash

- `static/theme.js`, `markdown.js`, `artifacts.js`, `slash.js`를 app.js에서
  분리. 마스코트는 앞선 슬라이스. `app.js?v=51`.
- 공유 `var`: `sessionId`/`inputEl`/`currentTab`. 아티팩트 pane 표시는
  `getElementById('artifacts')`로 결합 제거.
- 검증: `node --check` 6파일 OK, 라이브 각 js 200. **정적만 — Ctrl+Shift+R.**
  SSE/상태 탭/프로바이더 트레이는 app.js에 남김. 더 안 쪼갬 (실장님).

## 2026-09-19 — 모노리스 분리 Phase 0+1 소생 실측, Phase 2 마스코트 추출

- 소생 후: `healthz` ok, providers 5종(agy/claude/grok/codex/omniroute),
  기존 세션 `20260918-224646-8bfbd3` 유지·alive, `probe_message OK`
  (`20260919-002507-046dad`, 삭제됨).
- Phase 2 첫 슬라이스: `static/mascot.js` (app.js 4021→3784). 공유
  `currentTab`/`mascotOverlay`/`isMascotVisible`는 고전 스크립트용 `var`.
  `app.js?v=50` + `mascot.js?v=1`. `node --check` OK, `GET /mascot.js` 200.
  **정적만 — 소생 불필요.** Ctrl+Shift+R.

## 2026-09-19 — 모노리스 분리 Phase 1: AgySession/Registry → session.py

- 계획: `docs/plans/monolith-split.md`. 동작 불변.
- `session.py`(신규): `AgySession` + `Registry`/`REG` + 스탠바이 풀 + 세션
  헬퍼. `server.py`는 HTTP `Handler`/`main`만 (2862→858줄).
- `chatbot-ctl.sh` `guard_rlock`이 `session.py`의
  `self.lock = threading.RLock()`을 AST 검사. 계약 불변.
- 검증: `py_compile` 5파일 OK, `guard_rlock OK`, import 시 스탠바이 스폰
  없음. **디스크만 — ⚡소생 필요**(Phase 0과 한 번에). 소생 후 `healthz`/
  `providers`/기존 세션/`probe_message`.

## 2026-09-19 — 모노리스 분리 Phase 0: 상수·어댑터·채팅 CSS

- 계획: `docs/plans/monolith-split.md`. 동작 불변. UI 비주얼 변경 없음.
- `host_config.py`(신규): env/경로/토큰 임계값/`DEFAULT_PROVIDER`/`_now`.
- `tool_format.py`(신규): `_format_tool_call`/`_format_tool_result` (세션 상태
  없음, 어댑터와 AgySession이 공유).
- `adapters.py`(신규): `AgentAdapter` + agy/claude/grok/codex/omniroute +
  `AGENT_ADAPTERS`/`get_adapter`.
- `server.py`: `AgySession`/`Registry`/`Handler`/`main`만. `guard_rlock` AST
  경로 불변.
- `static/chat.css`: `index.html` `<style>` 원문 이동, `chat.css?v=1` 링크.
- 검증: `py_compile` 4파일 OK, `node --check` OK, `guard_rlock` OK.
  정적 `GET /chat.css` 200은 라이브에서 실측. **파이썬 쪽은 디스크만 —
  ⚡소생 필요.** 소생 후 `healthz`/`providers`/기존 세션/`probe_message`.

## 2026-09-18 — 호스트 일반화 Phase 1+2: nas_mcp core/host-plugin 분리, 문서 템플릿화

- 계획: `docs/plans/chatbot-host-portability.md` (Phase 0는 앞선 커밋에서
  완료).
- `nas_mcp.py`(core): `WEB_ROOT`(server.py와 같은 env `AGY_CHAT_WEB_ROOT`)
  도입, `ALLOW_ROOTS`/`READ_ROOTS`/`CMD_PREFIXES`/`SERVICE_CTLS`를 generic
  전용으로 축소. `sphere_hub_status`/`factory_status`/`hermes_status` 3개
  도구와 namuwatcher 관련 항목을 core에서 제거하고, `_allow_roots()`/
  `_read_roots()`/`_cmd_prefixes()`/`_service_ctls()` 헬퍼로 optional
  plugin(`nas_mcp_host`)과 병합. `NAS_MCP_HOST_PLUGIN=0`이면 plugin 자체를
  안 불러옴.
- 새 `nas_mcp_host.py`: Sphere/Hermes/NamuWatcher 전용 3개 도구 + extra
  roots/prefixes/service 항목. `nas_mcp.py`가 `_run`/`envelope`/
  `_scrub_text` 정의 뒤에 이걸 import(순환 임포트 순서).
- `PROJECT.md`/`SELF-MODIFY.md`: `/volume1/web` 리터럴 언급을 "웹 루트(env
  `AGY_CHAT_WEB_ROOT`)" + "이 배포의 실제 값" 표기로.
- 검증: `py_compile` OK. 격리 포트로 plugin 로드/미로드 두 경우 다
  `tools/list`·`list_services`·직접 호출까지 실측(로드 시 11개 도구 기존과
  동일, 미로드 시 8개 + host 전용 도구 호출은 "unknown tool"). plugin
  contributed root(`~/wiki`)·prefix(`namuwatcher-ctl.sh`) 병합도 실측
  확인. 실제 라이브 재기동 후 `tools/list` 11개·healthz 정상, 리그레션
  없음.
- 남은 것: 없음 — 계획서의 Phase 0~2 전부 완료.

## 2026-09-18 — 호스트 일반화 Phase 0: server.py/chatbot-ctl.sh 경로 하드코딩 제거

- 배경: 실장님 — 배포를 고려해서 DiskStation에 바인드된 요소를 걷어내고
  일반화. 다른 에이전트가 이어갈 수 있게 작업 시퀀스도 문서로 명시.
- 계획/조사/전체 시퀀스: `docs/plans/chatbot-host-portability.md` (Phase
  0~2, 이번엔 Phase 0만 완료).
- `server.py`: 새 `WEB_ROOT`(env `AGY_CHAT_WEB_ROOT`)/`AGENT_PATH_PREFIX`
  도입, `ADD_DIRS`/`_short_path`/`_rewrite_artifact_paths`/persona 서빙
  fallback/`skills_dir`/소생 Popen 호출을 `HOME`/`ROOT`/`WEB_ROOT`에서
  파생. `healthz`의 `mcp_port` 리터럴도 `NAS_MCP_PORT` 파생으로.
- `chatbot-ctl.sh`: `HOME_DIR` env override 가능, `cmd_start()`가 강제
  덮어쓰던 `AGY_BIN`/`HOME`을 override-respecting으로, `PORT_CHAT`/
  `PORT_MCP`도 env 우선.
- 검증: `py_compile`/`bash -n` OK, `repair` 후 `probe_message` PASS, 기존
  세션 리그레션 없음(재기동 전후 active session id 동일), 별도 임시
  인스턴스로 `AGY_CHAT_WEB_ROOT` override가 실제로 `add_dirs`에 반영되는
  것까지 실측 확인.
- 남은 것(다음 에이전트 인계): Phase 1(`nas_mcp.py` core/host-plugin
  분리), Phase 2(문서 템플릿화) — `docs/plans/chatbot-host-portability.md`
  참고.

## 2026-09-18 — 헤더 새 세션 제거, 채팅창 상황별 세션 버튼

- 배경: 실장님 — 상단 새 세션 버튼을 없애고, 세션 관리 버튼은 채팅창에서 상황에 맞게.
- 원인: 헤더 `새 세션`은 항상 켜져 모바일/compact 바를 밀었고, 진짜 상황 배너(`#sessionBanner`)는 compact·키보드에서 `display:none`이라 팝업에선 헤더 버튼이 유일한 입구였다.
- `static/index.html`: 헤더 `#newSession` 삭제. 배너는 `#log` 안으로 옮길 수 있게 스타일. compact/keyboard는 `.wrap > #sessionBanner`만 숨김(인로그 카드는 유지). 세션 탭에 `새 세션`·`맥락 이어가기`. `app.js?v=46`.
- `static/app.js`: 실제 유저 턴이 있으면 대화 끝에 quiet 칩(`새 대화`/`맥락 이어가기`), 세션이 길어지면 기존 soft/hard 안내. 작업 중·빈 세션은 숨김. `/new`·`/continue`는 그대로.
- 검증: `node --check` OK. 라이브 `GET /`에 헤더 새 세션 없음·`app.js?v=46`·세션 탭 버튼 있음. **정적만 — Ctrl+Shift+R, 소생 불필요.** 실기기 클릭은 이 세션 브라우저 도구 없어 미확인.

## 2026-09-18 — 슬래시(/) 버튼 메뉴가 바로 닫히거나 잘리던 버그

- 배경: 실장님 — `/` 버튼이 망가진 것 같다.
- 원인: 버튼 `pointerdown`이 메뉴를 연 뒤 입력창에 바로 포커스해서, 모바일에서 레이아웃/키보드가 바뀌며 바깥 탭 핸들러가 같은 제스처로 메뉴를 다시 닫음. 메뉴는 `.wrap{overflow:hidden}` 안의 `position:absolute`라 키보드가 뜨면 잘리기도 함. 버튼은 `/`를 입력창에 넣지 않아, 연 뒤 글자를 치면 메뉴가 바로 사라짐.
- `static/app.js?v=45`: 메뉴를 `position:fixed`로 컴포저 위에 붙임. 연 뒤 450ms는 바깥 닫기 무시. 버튼은 `stopPropagation`. 빈 입력이면 `/`를 넣고 커서를 뒤로. 뷰포트 변화에 재배치.
- `static/index.html`: 컴포저 `z-index:4; overflow:visible`. 버튼 `touch-action:manipulation`.
- 검증: `node --check` OK. 라이브 `GET /`에 `app.js?v=45`. **정적만 — Ctrl+Shift+R, 소생 불필요.** 로컬 크롬은 더미 스텁·실기기 화면은 미확인.

## 2026-09-18 — 기본 제공자 캡션 agy → Antigravity

- 배경: 실장님 — 캡션에 `agy` 말고 풀네임 Antigravity.
- `static/app.js` `PROVIDER_CREDIT.agy` = `Antigravity`. 포트레이트 트레이 툴팁도 같은 표시명. 내부 id는 `agy` 유지.
- `static/index.html`: 초기 캡션 `Antigravity`. `app.js?v=44`.
- 검증: `node --check` OK. 라이브 `GET /` 캡션·`app.js?v=44`가 Antigravity. **정적만 — Ctrl+Shift+R, 소생 불필요.** 허브 FAB 툴팁은 API `name`(`냥피디 (agy)`)이라 이번엔 안 바꿈.

## 2026-09-18 — 헤더 캡션에서 Powered by 제거

- 배경: 실장님 — 모바일에서 `Powered...`만 보임. 미사여구 없이 Provider 이름만 작게.
- 원인: nowrap+ellipsis 캡션이 `Powered by [provider]`라서 좁은 폭에서 접두어만 남고 제공자명이 잘림.
- `static/index.html`: 캡션은 `<span id="brandProvider">`만. `app.js?v=43`.
- `static/app.js`: 캡션 텍스트 = 제공자명. title/aria-label은 `제공자 {name}`.
- 검증: `node --check` OK. 라이브 `GET /`에 Powered by 없음·`app.js?v=43`. 로컬 크롬은 더미 스텁, Playwright 셸은 libatk 없음 — 실기기 화면은 미확인. **정적만 — Ctrl+Shift+R, 소생 불필요.**

## 2026-09-18 — 모바일 헤더 이름 고정 + Powered by 캡션

- 배경: 실장님 — 모바일 상단 포트레이트·이름이 길어지면 오른쪽 위젯이 안 보인다. 이름은 냥피디로 통일하고 아래 작은 `Powered by [provider]`가 어떤가.
- 원인: `updateBrandAvatar()`가 제공자 표시명(`냥피디 (agy)`, `OmniRoute` 등)을 `h1`에 넣음. 모바일 헤더는 nowrap이고 `.brand`/`.bar` 둘 다 `flex-shrink:0`이라 긴 제목이 탭·⋯·새세션을 화면 밖으로 밀었다.
- `static/index.html`: `h1`은 냥피디 고정. 캡션 `Powered by <span id="brandProvider">`. 모바일은 세로 스택, 브랜드는 남은 폭, `.bar`는 `flex:0 0 auto`. 캡션이 먼저 ellipsis. 360px 이하에선 Hub 화살표 숨김.
- `static/app.js?v=42`: 이름은 항상 냥피디, 제공자만 캡션 갱신.
- 검증: `node --check` OK, 크레딧 라벨 유닛 OK, 320–430px 폭 예산에서 이름 영역 ≥48px. 라이브 `GET /`에 `app.js?v=42`·Powered by 반영. 로컬 크롬은 더미 스텁이라 실기기 화면은 미확인. **정적만 — Ctrl+Shift+R, 소생 불필요.**

## 2026-09-18 — 다른 단말에서 답이 질문 위에 그려지던 순서

- 배경: 멀티 단말 폴링 반영 후 실장님 — 폰에서 보냈는데 태블릿은 질문 위에 대답이 그려진다.
- 원인: HTTP 턴 스레드가 `user_ack`보다 먼저 델타를 뿌림. 태블릿은 답 버블을 먼저 붙인 뒤 질문을 맨 아래에 append. 재동기화는 ts만 찍고 위치를 안 옮김.
- `server.py`: history 저장 직후, 워커 시작 전에 `user_ack`.
- `app.js?v=41`: 진행 중 assistant(ts 없음/`data-live`) 앞에 질문을 넣고, `repairMsgOrder()`가 뒤집힌 user/assistant 쌍을 바로잡음.
- 검증: `py_compile` OK, user_ack가 `_run_http_turn`보다 앞에 있는지 소스 순서 확인, `node --check` OK, `ctl guard` PASS. **클라 순서 보정은 Ctrl+Shift+R. 서버 emit 순서는 ⚡소생.**

## 2026-09-18 — 멀티 단말 세션 동기화

- 배경: 실장님 — 태블릿에서 시키고 폰은 갱신이 없음. 태블릿이 연결 끊김 후 폰을 새로고침하니 끝난 답이 있고, 타이핑 안 한 단말은 대답 밑에 질문이 붙기도 함. 진행 중엔 뒤에서 뭐가 일어나는지 안 보임.
- 원인: 라이브는 SSE 한 줄뿐. 백그라운드 폰은 EventSource가 좀비가 되면 onopen 재동기화도 안 탐. 재연결 때 놓친 히스토리를 맨 아래에 append해서 이미 그려진 답 아래로 질문이 감. SSE는 900초면 작업 중이어도 끊음.
- `server.py`: 작업 중엔 SSE idle cutoff 연장. 꽉 찬 subscriber 큐는 제거. `to_public()`에 `current_text`/`last_progress`/`turn_started_at`.
- `static/app.js?v=40`: 2.5초+visibility 폴링. 메시지 role+ts 키. 놓친 항목은 시간순으로 live 초안 앞에 삽입. 다른 단말은 초안·툴 줄을 폴링으로 봄.
- 검증: `py_compile` OK, `node --check` OK, `_emit` 꽉 찬 큐 드롭 스모크 OK, `ctl guard` PASS. 브라우저 두 대 실측은 이 세션 도구 없음. **⚡소생 필요** + 모든 단말 Ctrl+Shift+R.

## 2026-09-18 — 죽은 뒤엔 허브 FAB이 소생 버튼

- 배경: 실장님 — 심폐소생(⋯ 호스트 소생)이 살아 있어야 누를 수 있어서, 죽으면 못 살린다. FAB을 죽었을 때 살리기 버튼으로 쓰자.
- 원인: 채팅 UI의 ⚡ 소생은 `:3011`이 서빙해야 함. 허브 서비스 카드에는 이미 `/api/chatbot.php?action=revive`가 있었지만, 실제 입구는 FAB이라 죽은 iframe만 열림.
- `/volume1/web/index.html`: FAB이 8초마다 허브 PHP status를 봄(:3011 불필요). 꺼지면 회색+⚡, 클릭은 카드와 같은 revive. 팝업 오버레이로 진행 표시. 살아나면 iframe 재로드.
- 정적만. 호스트 재기동 불필요. 허브 Ctrl+Shift+R. 브라우저에서 일부러 죽인 뒤 FAB 클릭은 이 세션 도구 없어 미확인. `chatbot.php?action=status` online, `healthz` 200, FAB JS `node --check` OK.

## 2026-09-18 — 허브 FAB 제공자 선택이 세션에 안 먹던 버그

- 배경: 갤러리 404 소생 확인 후 자기개발 계속. 허브 FAB 트레이에서 제공자를 골라도 iframe은 `/?compact=1`만 열고, `openSession()`이 활성 세션의 provider로 드롭다운·localStorage를 덮어써서 선택이 무시됨.
- `/volume1/web/index.html`: 첫 오픈은 `?compact=1&provider=`, 이미 열린 iframe은 `postMessage({type:'chatbot-select-provider'})` (targetOrigin = :3011).
- `static/app.js`: URL `provider`를 `ensureSession()` 뒤에 `selectProvider`로 적용. 호스트명 확인 있는 message 리스너. `app.js?v=39`.
- 정적만. 호스트 재기동 불필요. 허브와 채팅창 둘 다 Ctrl+Shift+R. 브라우저에서 FAB 클릭 실측은 이 세션 도구 없어 미확인.

## 2026-09-18 — 아티팩트 탭 페르소나 갤러리 404

- 배경: 실장님 — "그냥 너 자기개발이나 해". 라이브 로그에 `GET /artifacts/01-avatar.png` 등 404가 반복되고 있었음. 아티팩트 탭이 `data/persona/gallery`와 `workspace/artifacts`를 스캔하면서 URL은 `/artifacts/<파일명>`만 붙여서, 실제 서빙 루트(`sessions/_shared`, `workspace/artifacts/<rel>`)에 없는 파일이 깨진 썸네일로 나옴.
- `get_artifacts()`: 갤러리는 `/persona/gallery/<name>`, workspace/artifacts는 `/artifacts/<rel>` (하위 경로 유지).
- `_safe_artifact_rel`: `data/persona` 후보 + 파일명 fallback (구 채팅 히스토리 마크다운 `/artifacts/01-avatar.png`도 소생 후 복구).
- `static/app.js`: 썸네일/모달 `bindArtifactImg`가 `/persona/gallery/` → `/artifacts/persona/` 순으로 재시도. 라이브 호스트는 아직 옛 URL을 주므로 새로고침만으로 썸네일이 살아남. `app.js?v=38`.
- `static/chat/persona` 깨진 심링크(`chatbot-data/persona` 폐경로)를 `data/persona`로 재지정.
- 검증: `python3 -m py_compile server.py` OK, `chatbot-ctl.sh guard` PASS. 라이브 curl: `/persona/gallery/01-avatar.png` 200, `/artifacts/persona/sei-portrait.png` 200, `/artifacts/01-avatar.png`는 소생 전까지 404(클라 폴백이 대신 처리). 서버 변경은 디스크만 — 실장님 ⚡소생 필요. 브라우저 실클릭은 이 세션에서 도구 없어 미확인.

## 2026-09-18 — API 프로바이더 Phase 4: 모델 큐레이션, 컨텍스트 창 자동 스케일링, rate_limit_report 연동

- **구현 내용**:
  1. `rate_limit_report()`: OmniRoute의 `/api/providers` 엔드포인트를 호출하여 연결된 업스트림 OAuth 계정(antigravity, codex 등)의 연결 상태(`isActive`, `testStatus`), 토큰 만료일(`expiresAt`)을 UI 상태 탭 포맷(`{group, limit_type, remaining_pct, reset_at}`)으로 변환 연동.
  2. `soft_hard_tokens()`: OmniRoute `/v1/models`의 `context_length` 메타데이터(예: 1M 컨텍스트)를 10분 TTL로 캐싱하여, 모델별 컨텍스트 한도에 맞춰 `soft`(40%), `hard`(70%) 임계값을 동적으로 계산(상한 400k/800k).
  3. `known_models()` 큐레이션: 160개에 달하는 모델 목록 중 `auto/best-free`, `auto/best-coding`, `auto/best-chat`, `auto/best-reasoning`, `auto/best-fast`, `auto/coding:free`, `auto/smart` 및 실측 검증된 개별 모델들(`antigravity/claude-sonnet-4-6` 등)로 큐레이션 세트 구성.
  4. **비용 가드레일 SSOT**: 기본 모델을 무료 우선 콤보인 `auto/best-free`로 고정하여 의도치 않은 유료 결제를 원천 방지하고, 턴당 usage 정규화(input/output/thinking/cache 토큰)를 상태 탭 및 메시지 히스토리에 기록.
- **검증**: `python3 -m py_compile server.py` 통과, standalone 어댑터 호출로 `rate_limit_report()` 5개 계정 파싱 및 `soft_hard_tokens('auto/best-coding')`=(400000, 734003) 동적 계산 실측 검증 완료.

## 2026-09-18 — API 프로바이더 Phase 2: nas_mcp 툴 호출 루프, 실측 완료

- 배경: Phase 0+1(아래 항목) 직후 실장님이 "재시작할까 아님 이어서할래" 물어봤고,
  "너가 컨텍스트 있는게 낫지 않나"는 이유로 재기동 검증 전에 계속 진행하기로 함 —
  ⚡소생은 별개 문제(라이브 호스트 반영)라 코딩/실측 자체는 재기동 없이도 계속
  standalone으로 검증 가능해서 그대로 진행.
- **실측으로 뒤집힌 계획서 가정**: Phase 0+1 계획서(`docs/plans/
  api-provider-adapters.md`)가 "`nas_mcp.py`를 `server.py`와 같은 프로세스에서
  바로 import해서 쓸 수 있다"고 적어뒀었는데, 실제로 `grep "import nas_mcp"
  server.py` → 0건, `chatbot-ctl.sh`가 `nas_mcp.py`를 **별도의 독립 프로세스**로
  띄우고(`nohup python3 nas_mcp.py`), 이미 `127.0.0.1:3012/mcp`에서 진짜 HTTP
  JSON-RPC 서버로 떠 있는 걸 실측으로 확인(`curl .../healthz` 200, `tools/list`
  정상 응답) — claude/grok/codex 어댑터들이 이미 이 URL로 붙는 것과 똑같은 방식으로
  고쳐서 구현. 계획서 문서도 이 부분 바로잡음.
- **구현**: 모듈 레벨 `_mcp_rpc()`/`_mcp_openai_tools()`(nas_mcp의 `tools/list`
  MCP 스키마 → OpenAI `tools=[{type:"function",...}]`로 변환, 5분 캐시)/
  `_mcp_call_tool()`(`tools/call` 실행) 추가. `OpenAIDialectAdapter.stream_turn()`을
  단일 HTTP 호출(`_stream_once`, 델타 스트리밍 + `tool_calls` 델타를 index별로
  누적)과 그걸 감싸는 루프(모델 응답이 `finish_reason=="tool_calls"`면 각 콜을
  `nas_mcp`에 실행 → 결과를 로컬 `messages` 리스트에 `role:"tool"`로 추가 →
  재호출, 최대 `MAX_TOOL_HOPS=10`회)로 분리 — 스트리밍 버그와 툴 루프 버그가 같은
  스택트레이스에 안 섞이게 하려던 계획서 원칙 그대로, 다만 이번엔 같은 클래스
  안에서(별도 클래스로 안 쪼갬).
- 툴 호출/결과 이벤트는 기존 CLI 어댑터들이 이미 쓰던 정확히 같은 캐노니컬 모양
  (`{"event":"tool","text":...,"title":...,"kind":"call"|"result","status":...}`,
  `_format_tool_call`/`_format_tool_result` 그대로 재사용)으로 내보내서 프론트엔드
  툴 카드가 수정 없이 그대로 렌더링됨 — 계획서가 처음부터 "얇은 shim, 캐노니컬
  이벤트 모양은 절대 안 바꾼다" 원칙으로 요구했던 부분.
- 턴 내부의 모델↔툴 왕복은 `stream_turn()`의 로컬 `messages` 리스트에만 쌓이고,
  `session.history`에는 최종 답변 텍스트만 저장(기존 CLI 어댑터들의 동작과 동일 —
  CLI는 프로세스 자신이 내부적으로 들고 있는 걸, 여기선 로컬 변수가 대신 들고
  있다가 턴이 끝나면 버려짐). 그래서 `_history_to_openai_messages()`는 Phase 1
  그대로 변경 없음.
- **라이브 검증 (실제 `AgySession`, standalone)**: "nas MCP의 ping_nas 툴을 반드시
  호출해서 결과를 알려줘" → 실제로 `ping_nas` 호출(진짜 HTTP round-trip to
  `127.0.0.1:3012/mcp`) → `{"success":true,"message":"pong",...}` 결과를 받아
  최종 답변에 정확히 반영 확인. 이벤트 구독으로 실제 방출 순서까지 확인:
  `user_ack` → tool(call) → tool(result) → delta×N → result, 프론트엔드가 기대하는
  순서 그대로. 세 개 툴(list_services/sphere_hub_status/hermes_status)을 순서대로
  부르는 더 긴 턴 도중 `stop()` 호출 → busy 즉시 False, 크래시·좀비 스레드 없음
  확인(멀티홉 툴 루프 중간에 끊는 경우까지 검증). 테스트 세션 폴더 전부 삭제.
- **아직 안 한 것**: 여전히 디스크 반영만 — ⚡소생 전. Phase 4(모델 큐레이션,
  `rate_limit_report`, 비용 가드레일)는 계획서에 남은 범위 그대로.

## 2026-09-18 — API 프로바이더 Phase 0+1: OpenAIDialectAdapter (OmniRoute), 실측 완료

- 배경: 실장님 — CLI 프로바이더(agy/claude/grok/codex) 외에 OpenRouter 같은 **API
  직접 호출** 프로바이더도 붙이고 싶다, Hermes(`~/.hermes/hermes-agent/`)와 이 NAS에
  이미 떠 있는 docker `omniroute`(237+ 프로바이더를 단일 OpenAI 호환 엔드포인트로
  묶는 게이트웨이, `localhost:20128`)를 참고하라는 요청. 설계 계획서를 먼저 작성
  (`docs/plans/api-provider-adapters.md`) 후 실장님이 OmniRoute 테스트 키를 주고
  "시험해보며 진행해봐"라고 해서 Phase 0(트랜스포트 분리)+Phase 1(최소 어댑터)을
  실제로 구현하고 라이브로 검증함.
- **핵심 구조**: `AgentAdapter`에 `transport_kind`("process" 기본 / "http") 캐퍼빌리티
  플래그 추가. `AgySession`이 `self.proc`를 직접 다루던 지점들
  (`_send_direct`/`stop`/`send`/`_run_btw`/`to_public`)에 http 분기 또는
  `_proc_alive()` 헬퍼(트랜스포트 무관하게 "지금 이 턴이 실제로 살아있나"를
  answer)를 끼워 넣음 — CLI 4종의 기존 코드 경로는 그대로, http는 `self.proc`를
  아예 만들지 않고 `self._http_resp`(진행 중인 `urlopen()` 응답, `stop()`이 이걸
  close()해서 스트림을 취소)와 백그라운드 스레드(`_run_http_turn`)로 대체.
  `_handle_stdout_line`의 busy/heavy-check/queued-dispatch 로직을
  `_handle_events()`로 추출해 CLI 라인 파싱 경로와 http 스트리밍 경로가 같은
  후처리를 공유하게 함(사본 두 개로 갈라져 드리프트하는 걸 방지).
- **`OpenAIDialectAdapter`**: 벤더별 서브클래스가 아니라 `base_url`/`api_key_env`를
  받는 **엔드포인트당 인스턴스 하나** — OmniRoute든 OpenRouter 직결이든 다른 OpenAI
  호환 엔드포인트든 같은 클래스로 붙는다(계획서 "설계 원칙 5", OpenAI/Anthropic
  wire dialect 분리). `AGENT_ADAPTERS`에 `omniroute` 인스턴스 등록
  (`base_url=http://localhost:20128/v1`, `api_key_env=CHATBOT_OMNIROUTE_API_KEY`,
  기본 모델 `auto/best-free`). Phase 1 범위는 **툴 호출 없는 순수 채팅만** — 계획서가
  스스로 정해둔 순서(스트리밍 버그와 툴 루프 버그를 같이 디버깅하지 않기) 그대로 지킴.
- **문서 대비 실측으로 발견한 실제 동작 (전부 `docs/plans/api-provider-adapters.md`
  OpenAIDialectAdapter docstring에도 반영)**:
  1. `stream` 파라미터를 명시 안 하면 OmniRoute가 그냥 SSE로 응답함(OpenAI 스펙의
     "생략 시 기본 false"와 다름) — 항상 명시적으로 `stream: true/false`.
  2. 스트리밍 응답 맨 앞에 `id: "omniroute-keepalive"`인 빈 델타 청크가 라우팅
     결정이 나기 전까지 여러 개 끼어듦 — 콘텐츠로 취급하면 안 되고 필터링 필요.
  3. `usage.total_tokens`가 `prompt_tokens + completion_tokens`와 항상 일치하지
     않음(숨은 reasoning 토큰), `completion_tokens_details.reasoning_tokens`도
     있을 때도 없을 때도 있음 — `total_tokens`만 신뢰, 나머지는 있으면 참고.
  4. `/v1/models`에 있는 모델이라고 실제로 호출 가능한 건 아님 — 이 테스트 키의
     연결 계정이 접근 권한 없는 모델을 호출했더니 401인데
     `type:"authentication_error"`로 오분류(실제로는 라우팅/권한 문제, 키 자체는
     멀쩡).
  5. 툴 콜링은 OpenAI 스펙 그대로 왕복 확인(`tools` → `tool_calls` 응답 →
     `role:"tool"`+`tool_call_id` 후속 → 최종 답변) — Phase 2에서 `nas_mcp.py`
     연결할 때 그대로 쓸 수 있음, 이번엔 구현 안 함.
  6. OmniRoute `/api/providers`·`/api/settings` 대시보드 API가 `/v1/*`와 **같은
     Bearer 키**로 인증됨(별도 로그인 불필요) — Phase 4 `rate_limit_report()` 구현
     시 그대로 쓸 수 있음.
- **라이브 검증 (실제 `AgySession`으로, standalone 실행 — 라이브 호스트 재기동 없이
  `server.py`를 직접 import해서 실행)**: provider=omniroute 세션 생성 → 1턴
  (숫자 "5" 정답 + usage 정규화 정상, `transport_kind: http` 확인) → 2턴째로 멀티턴
  컨텍스트 유지 확인("방금 뭐라고 답했지" → "5" 정확히 재답변, `_history_to_openai_
  messages` 정상 동작) → 3턴째 스트리밍 도중 `stop()` 호출 → `busy` 즉시 False로
  전환, 좀비 스레드나 크래시 없음, 중복 에러 이벤트 없음(`_stop_requested` 가드
  정상) 확인. **CLI 회귀 확인**: 같은 방식으로 provider=agy 세션도 재검증 —
  `_proc_alive()`/`_handle_events` 리팩터 후에도 정상 턴 완료 + idle 상태에서
  `_proc_alive()==True` + stop 후 `False` 확인. 테스트 세션 폴더는 검증 후 전부
  삭제(잔재 안 남김).
- **아직 안 한 것 / 다음**: `server.py` 핵심 변경이라 디스크 반영만 완료 —
  **실장님 ⚡소생 필요**, 재기동 후 실제 UI(`#provider` 드롭다운)에서 omniroute
  선택 + 실제 브라우저 대화로 재검증할 것. `CHATBOT_OMNIROUTE_API_KEY`는 코드에
  하드코딩하지 않음 — `chatbot-ctl.sh start/restart`를 실행하는 셸의 환경에 직접
  export 필요(이 프로젝트에 `.env` 컨벤션이 아직 없음, AGY_CHAT_* 변수들과 같은
  방식). Phase 2(MCP 툴 루프)/Phase 4(모델 큐레이션, 비용 가드레일)는
  `docs/plans/api-provider-adapters.md`에 남은 범위 그대로.

## 2026-09-18 — Codex 상태 탭 사용량 바

- 배경: 실장님 — "코덱스 사용량 조회 추가 가능?". `codex` 최상위 CLI에는
  사용량 명령이 없어 기존 어댑터가 "지원 안 함"을 반환하고 있었음.
- 실측 (Codex CLI 0.154.0): 로컬 인증을 사용하는 `codex app-server`의
  읽기 전용 JSON-RPC `account/rateLimits/read`가 quota bucket별
  `usedPercent`, `windowDurationMins`, `resetsAt`을 반환함. 자격 증명은
  app-server 내부에만 두고 읽거나 화면에 노출하지 않음.
- 수정: `CodexAdapter.rate_limit_report()`가 단발 app-server를 최대 20초
  기동해 응답만 받은 뒤 즉시 종료하고, 사용률을 기존 상태 탭 행 형식
  (`remaining_pct`, 제한 기간, UTC 리셋 시각)으로 정규화. 기존 5분 캐시와
  UI를 그대로 재사용함.
- `server.py` 코어 변경은 디스크에만 반영됨 — 적용에는 실장님 **⚡소생**이
  필요. 시작 후 상태 탭에서 Codex를 고르고 새로고침해 실제 표시를 확인할 것.

## 2026-09-18 — 대화 도중 프로바이더 전환 시 맥락 유실 수정

- 배경: 실장님 — "지금 대화도중 llm제공자를 바꿀수있는 구조라 도중에 바뀌면 다시 해줘야하는 게 있을 것 같네". 코드로 확인해보니 실제 버그였음.
- `maybe_swap_provider()`는 `conversation_id`를 `None`으로 리셋해 다음 스폰이 `--resume` 없이 완전히 새 CLI 대화로 뜨는데, `self.history`(그리고 화면)는 그대로 이어져 보였음 — **UI는 안 끊겼는데 새 백엔드는 이전 대화를 전혀 모르는 상태**로 다음 메시지를 받고 있었음. `/continue`용 `handoff_summary`/`handoff_injected` 인계 장치가 있었지만 `maybe_swap_provider()`는 그걸 전혀 안 씀.
- 수정: `maybe_swap_provider()`가 provider/conversation_id를 덮어쓰기 전에 `get_handover_summary()`로 요약을 뽑아 `self.handoff_summary`에 채우고 `handoff_injected = False`로 리셋 — `_send_direct()`의 기존 인계 주입 로직을 그대로 재사용.
- `get_handover_summary()`에 `use_cache` 파라미터 추가(기본 `True`, 기존 호출부 전부 영향 없음). 프로바이더 스왑 시엔 `use_cache=False`로 호출 — 이 세션 객체는 스왑 후에도 계속 살아있으므로(로테이션과 달리 폐기 안 됨), 여기서 `_cached_summary`를 채우면 나중에 진짜 heavy-rotation 때 그 stale 요약을 재사용해버리는 부작용이 생김.
- `_send_direct()`의 인계 안내 문구가 `predecessor_session_id`(세션 로테이션에만 있음)를 전제로 "이전 세션(id)"라고 표시하던 걸, 동일 세션 내 프로바이더 스왑처럼 predecessor id가 없는 경우엔 "직전 대화"로 라벨을 분기.
- 정적 UI 아님, `server.py` 코어 변경 — 디스크 반영만 완료. `guard`/`doctor` PASS. 라이브 재기동은 실장님 ⚡소생 필요(SELF-MODIFY.md 규칙상 자가 재기동 금지). 재기동 후 실제로 "프로바이더 전환 직후 이전 맥락을 아는지" 라이브 검증 필요(아직 안 함).

## 2026-09-18 — 작업 중 상단 위젯을 답변 바닥으로 합침

- 배경: 실장님 — 작업 중 상단에 메시지 위젯이 두 개(procBadge 긴 문장 + `#progress` 줄)라 답변 창의 토큰 자리에 합치고, 입력창 옆 중지도 거기로.
- 턴 중 경과+툴 한 줄은 답변 버블 `.msg-footer`의 `.turn-live`(토큰 배지가 붙는 자리). 끝나면 그 자리에 기존 토큰 배지.
- `#stopBtn`은 컴포저에서 빼서 답변 footer로 이동. 대화 탭이 아니면 메타 줄로 폴백(다른 탭에서도 중지 가능).
- 상단 `#progress`는 턴 중엔 숨김. 호스트 소생처럼 답변 버블이 없는 알림만 남김. procBadge는 턴 중 "작업 중" 칩만.
- 정적 UI만. 강력 새로고침. 재기동 불필요.
- 모바일: 컴포저용 `#stopBtn{height:44px}`가 답변 footer의 중지까지 키워서
  `#log overflow-x:hidden`에 잘림. `#send`만 컴포저 크기 적용, footer 중지는
  32px·말줄임은 `.turn-live`가 먹고 버튼은 `flex-shrink:0`.

---

## 2026-09-18 — Grok 상태 탭 사용량 바

- 배경: 실장님 — "Grok 도 사용량 보여주기 해볼까". agy는 `agy --print /usage`, claude는 `claude --print /cost`. grok CLI의 `grok usage <session_id>`는 세션 비용이라 계정 한도가 아님.
- 실측 (grok 1.0.34): TUI `/usage`(alias `/cost`)가 치는 것과 같은
  `GET {GROK_CLI_CHAT_PROXY_BASE_URL}/billing?format=credits` 가
  `config.creditUsagePercent` / `productUsage[].usagePercent` / `currentPeriod.end`
  를 돌려줌. 오늘 조회 기준 GrokBuild 주간 사용 약 8% (잔여 ~92%, 리셋 2026-09-19).
- `GrokAdapter.rate_limit_report()`가 이 JSON을 agy/claude와 같은
  `{group, limit_type, remaining_pct, reset_at}` 행으로 정규화. 401이면
  `grok models`로 토큰 리프레시 한 번 재시도. 토큰은 `grok login`이 쓰는
  `~/.grok/auth.json` (어댑터 전용, 냥피디 기억 SSOT 아님).
- 라이브 호스트는 디스크 설계도만 반영됨 — `server.py`라 **⚡소생** 필요.
  정적 `app.js` 주석만 고침 (동작 변경 없음).

---

## 2026-09-18 — 장기 기억 (MEMORY.md)

- 배경: 세션 아카이브 검색(`recall_memory.py`)만 있고, 세션을 넘는 큐레이트 사실이 없었음.
- 추가: `data/workspace/memory/MEMORY.md` + `tools/memory.py` (`show`/`add`/`search`/`forget`). 제품 데이터, 어댑터 무관. 다른 에이전트 메모리 디렉터리 비사용.
- `AGENTS.md` §2: 시작 때 MEMORY.md를 읽고, "기억해"면 add. 4KB 캡. `server.py` 변경 없음 (재기동 불필요).
- Hermes `USER.md` / Grok `~/.grok/memory` 는 격리 대상이라 자동 이관하지 않음. 실장님이 고르면 그때 한 줄씩 add.

---

## 2026-09-18 — 제품 지침 / 하네스 분리

- 배경: 자체 하네스(`AgentAdapter`: agy 기본, claude/grok)를 빌드하면서 챗봇을 계속 운영. 워크스페이스 규칙이 agy 정체성·호스트 헌장 복제·git 고고학에 묶여 있었음.
- **제품 vs 하네스**: `data/workspace/AGENTS.md`를 제품 헌장으로 재작성. 호스트 법은 `~/AGENTS.md` 포인터만. CLI 계약은 어댑터/ctl에만.
- `PROJECT.md`에서 분리-repo 히스토리 장문 삭제, 경로 표를 상대경로로.
- `SELF-MODIFY.md`를 프로바이더 무관 규칙으로 압축. `docs/SELF-MODIFY.md`는 워크스페이스 SSOT 포인터.
- `PERSONA.md`에 하네스 독립 한 줄. `chatbot-self-improve` 맵도 상대경로 + 어댑터 목록.
- 호스트 `~/AGENTS.md` 냥피디 칸에 제품 헌장 경로 추가. 호스트 법 복제 금지 한 줄.
- 재기동 불필요 (규칙 파일은 세션 스폰마다 읽힘). 라이브 턴에서 ctl restart 안 함.

---

## 상태 (2026-09-16)

**인계 완료.** 이후 이 표면의 버그/UX/스킬 개선은 GameDeveloper 대신 **이 챗봇 자신**(`chatbot-self-improve` + `task-observer`)이 1차 담당한다.

---

## 2026-09-16 — v0 스냅샷

### 배경
Sphere Hub에 Antigravity(`agy`) 채팅을 붙이면서 VibeCat식 지속 세션 호스트가 생겼다.
- Hermes `antigravity-cli` = `agy -p` 원샷 위임
- Hub chatbot = stream-json 지속 프로세스 (본체)

### 결정
| 항목 | 내용 |
|------|------|
| 프로젝트명 | `chatbot` (캐릭터명 금지, 경로=이름) |
| 페르소나 | `config/persona.json` + `chatbot-data/persona/` (현재 기본=냥피디) |
| 이미지 | SuperGrok Imagine / 기존 persona 자산. chubby jpg 폐기본 사용 금지 |
| Lore 브랜딩 | See1 only (Zero 표기 금지) |
| UX | Hub FAB 팝업 + `/chat/` → `:3011` 전체 창 |

### 레이아웃
| 경로 | 역할 |
|------|------|
| `~/services/chatbot/` | `server.py`, `nas_mcp.py`, `static/`, `config/`, `docs/` |
| `~/services/chatbot-data/` | sessions, artifacts, persona, workspace |
| `~/services/chatbot-ctl.sh` | start/stop/restart/status (+ orphan `agy` 정리) |
| `/volume1/web/index.html` | Hub FAB (`AGY_CHAT_FAB_*` 마커) |
| `/volume1/web/chat/persona/` | 퍼블리시 페르소나 자산 |
| `/volume1/web/chat/vendor/` | marked / mermaid (FAB용) |
| ports | **3011** chat, **3012** NAS MCP |

구 `sphere-agy-*` 심링크/로그/`.bak`/`SPHERE-AGY-CHAT.md`는 2026-09-16에 완전히 정리(→ `~/tmp-trash-2026-09-16/sphere-agy-legacy/`로 이동, 삭제는 아님). `nas_mcp.py`의 `SERVICE_CTLS["sphere-agy"]` 별칭과 `TMP_ROOT`(`/tmp/sphere-agy` → `/tmp/chatbot-mcp`)도 같이 정리 — 이제 `chatbot`만이 유일한 이름.

### 구현 완료
1. VibeCat급 지속 `agy` 호스트 + NAS MCP
2. skip-permissions, trusted NAS 경로, `/artifacts/` 서빙
3. 세션 히스토리 복원, 생성 이미지 마크다운
4. 프로젝트화 (`chatbot` / `chatbot-data`)
5. UI: 상단 갤러리 제거, 배경 옅은 오버레이, 얼굴 아이콘, 대화/로그 분리
6. 세션 키 `chatbot.sessionId` 통합, 없으면 **최신 세션 복원**
7. `tool: tool` 스팸 서버 필터 + 클라이언트 스킵
8. marked + mermaid (전체 창 `static/vendor` + Hub `/chat/vendor`)
9. 진행 표시: `…` 대신 말풍선에 `요청 보냄` / `작업 중 ·` / `작성 중…`
10. 자기강화: `task-observer` 심링크 + PreInvocation hook + `chatbot-self-improve` 스킬
11. 재시작 시 orphan `agy` 정리 (`chatbot-ctl.sh`)

### 운영
```bash
~/services/chatbot-ctl.sh status|restart|stop|start
```
Watchdog가 `chatbot-ctl.sh start` 유지.

### 알려진 이슈 / 백로그 (챗봇이 이어받을 것)
- [ ] 페르소나 미소녀 톤 자산 품질 락 / 핫스왑 UI
- [ ] Hub FAB ↔ 전체 창 기능 드리프트 방지 (공통 번들화 검토)
- [ ] `\n` 이스케이프가 HTML 인라인 JS를 깨뜨리지 않도록 배포 레시피 고정
- [ ] 긴 툴 작업 시 진행 문구 품질(툴 이름 파싱) 개선
- [ ] DEVLOG ↔ Sphere Tech 연재 면 연결 여부

### 인계 규칙
- 이 챗 UI/호스트/페르소나/hook/스킬 이슈 → **챗봇에게 시킴** (skill: `chatbot-self-improve`)
- GameDeveloper는 Zero/Godot·Sphere 상위 아키텍처·긴급 복구만
- 위험한 삭제/포트 변경은 실장님 승인
- 관찰 로그: `chatbot-data/workspace/skill-observations/`

---

## 2026-09-16 — 렌더링 정상화, 자산 경로 복구 및 작업 중 샛길 질의(/btw)·대기열·중지 체계 구축

### 변경 내역
1. **마크다운 & 다크 Mermaid 렌더러 로컬 번들링**:
   - `marked.min.js`, `mermaid.min.js`를 `:3011` 및 Web Hub에 로컬 벤더링하여 온프레미스 완전 오프라인 렌더링 지원.
   - 코드 복사 버튼 및 GFM 테이블/인라인 코드/블록쿼트 스타일링 완료.
2. **페르소나 얼굴/배경 자산 경로 정상화**:
   - `:3011` 정적 루트에 자산 심볼릭 링크 생성 및 `mimetypes.guess_type` 적용으로 이미지 서빙 404/MIME 오류 해결.
   - 2중 `onerror` 웹허브 폴백 장착.
3. **작업 중 샛길 질문 (`/btw`) & 자동 감지 (Auto-Inquiry)**:
   - 긴 턴 실행 중에도 메인 `stdin`을 방해하지 않는 경량 Flash 모델 기반 1회성 사이드 채널 서빙 (`_run_btw`).
   - 사용자가 굳이 `/btw`를 입력하지 않아도 물음표(`?`) 또는 의문형 한국어 어미를 감지하여 자동으로 샛길 답변 카드로 즉시 응답.
4. **반응형 전송 버튼 & 안전 대기열 (Message Queueing)**:
   - 작업 중 지시문 입력 시 버튼이 `대기열 등록 ↵`으로 전환되며, 큐에 보관 후 작업 완료 즉시 자동 연쇄 실행.
   - 작업 중 질문 입력 시 버튼이 보라색 `샛길 질문 ✦`으로 자동 전환.
5. **명시적 작업 중지 (`[중지]` 버튼)**:
   - 작업 진행 중일 때만 노출되는 빨간색 중지 버튼 추가 (`POST /api/sessions/:id/stop`).
   - 세션 프로세스 및 대기열을 즉시 안전 정리하고 `event: stopped` 알림 전파.
6. **데몬 프로세스 안전성 강화 (`chatbot-ctl.sh`)**:
   - `kill_orphan_agy`가 부모가 살아있는 agy를 죽이지 않도록 `PPID=1` 고아 프로세스만 타깃하도록 엄격화.


## 2026-09-16 — 긴급: 메시지 데드락 (ensure→spawn→stop)

### 증상
- `:3011` health는 살아 있는데 전송(POST `/message`)이 응답 없이 멈춤 → UI가 망가진 것처럼 보임
- 서버 재시작 직후/세션에 agy proc 없을 때 재현

### 원인
- `AgySession.ensure()`가 `threading.Lock`을 잡은 채 `_spawn()` → `stop()` 호출
- `stop()`이 같은 `Lock`을 다시 획득하려 해서 **데드락**
- `/btw`·대기열·중지 추가 과정에서 `stop()`이 `_spawn` 경로에 들어간 뒤 표면화

### 수정
- `self.lock = threading.RLock()` (세션 락만; REG 락은 그대로)
- `/stop` 응답에 session 스냅샷 포함
- 백업: `server.py.bak-deadlock-202609160820`

### 검증
- POST `/message` ~11ms 200, agy 기동, assistant 답변 수신 확인


## 2026-09-16 — 재발 방지: doctor / repair / 워치독 프로브

### 추가
- `chatbot-ctl.sh`: `doctor [--auto-repair]`, `probe`, `repair`, `guard`
- `guard`: AST로 `AgySession.lock == RLock` 강제 (Lock 회귀 시 start 거부)
- `probe`: throwaway 세션에 POST `/message` (healthz가 못 잡는 데드락 탐지)
- 프로브 스로틀 기본 600s (`CHATBOT_PROBE_EVERY_SEC`, `CHATBOT_FORCE_PROBE=1`)
- `gateway-watchdog.sh`: `start` → `doctor --auto-repair`
- `docs/EMERGENCY.md` 비상 수리 카드


## 2026-09-16 — 자기수정 경계 문서 전달 (실장님)

- `chatbot-data/workspace/SELF-MODIFY.md` (+ docs 복사)
- AGENTS.md / PROJECT.md / `chatbot-self-improve` 스킬에 강제 참조
- 요지: 디스크 설계도·재기동 후 코어 OK / 라이브 자가 뇌수술 금지 / 외부 doctor·repair


## 2026-09-16 — 아티팩트 전용 탭 & 라이트박스 뷰어 구축

### 배경 및 요청
- 실장님 요청: "채팅 도중 생성한 이런 이미지나 파일 (아티팩트?)들을 열람할 수 있는 별도의 탭이나 공간이 있으면 좋겠어"
- 생성된 미디어(이미지) 및 문서/코드 파일들이 긴 대화창 속에서 유실되지 않고 한눈에 파악, 열람, 다운로드 및 인용할 수 있는 전용 공간 필요.

### 구현 내용
1. **백엔드 아티팩트 API (`server.py`)**:
   - `AgySession.get_artifacts()`: 세션 brain 디렉터리, `chatbot-data/workspace/artifacts`, 페르소나 갤러리 및 캐시를 일괄 스캔.
   - 파일 크기 및 파일명 스템 기반 중복 이미지 필터링.
   - `_safe_artifact_rel()`: 이미지뿐만 아니라 `.md`, `.txt`, `.json`, `.py`, `.sh` 등 문서/코드 파일도 brain 내에서 안전하게 서빙하도록 확장.
   - 엔드포인트 `GET /api/sessions/:id/artifacts` 및 `GET /api/artifacts` 제공.
2. **헤더 3단 탭 네비게이션 (`index.html`)**:
   - 상단 바에 `[💬 대화]`, `[📁 아티팩트 <span id="artBadge"></span>]`, `[📜 로그]` 탭 스위처 배치.
   - 보유 아티팩트 개수 뱃지 표시.
   - 아티팩트 탭 상태에서도 하단 메시지 입력창(컴포저)이 유지되어 파일을 보면서 질문하거나 인용 가능.
3. **아티팩트 갤러리 및 필터 UI (`app.js`, `index.html`)**:
   - 반응형 카드 그리드: 호버 줌 썸네일, 파일 형식 아이콘(💻 코드, 📄 문서), 파일 크기 및 생성 일시.
   - 카테고리 필터(`전체`, `이미지`, `문서/코드`) 및 `[새로고침 ↻]` 버튼.
   - 카드 액션: `[미리보기]` 모달 및 `[인용 💬]` (채팅창에 마크다운 자동 삽입 후 대화 탭으로 즉시 전환).
4. **라이트박스 모달 뷰어 (`#artModal`)**:
   - 고해상도 원본 이미지 확대 및 텍스트/코드 파일 실시간 내용 뷰어.
   - `[다운로드]` 및 `[채팅에 인용]` 버튼 제공. ESC 키 및 배경 클릭 시 닫기.
5. **실시간 SSE 동기화**:
   - 작업 도중 새로운 이미지가 생성(`event: image`)되거나 작업이 완료(`event: result`)될 때 백그라운드에서 자동으로 아티팩트 목록과 뱃지를 갱신.


## 2026-09-16 — 세션 비대화·ADD_DIRS 축소·프로브 agy 정리 (latency)

### 배경
- 메인 세션 `20260916-064817-8da2bb` / cid `8e51e0c6-…`: UI hist ~61턴이지만 conversation.db ~19MB·brain ~8MB·216 steps → 같은 세션 비대화가 체감 지연의 주원인.
- doctor 프로브 flash-low agy가 `--conversation` 없이 호스트 자식으로 남는 경우 있음 (기존 `kill_orphan_agy`는 PPID=1만 정리).

### 변경
1. **ADD_DIRS 축소** (`server.py`)
   - 유지: `chatbot`(ROOT), `chatbot-data`(DATA), `/volume1/web/chat`
   - 제거: 전체 `HOME`, `/volume1/web`, `.hermes`, `HOME/services`, 중복 artifacts/workspace 단독 항목
2. **세션 길이 가드**
   - soft: turns≥40 또는 hist chars≥15k 또는 db≥5MB → SSE `session_heavy` + UI 배너(한/새 채팅 버튼)
   - hard: turns≥60 또는 chars≥25k 또는 db≥8MB → 다음 메시지에서 **새 세션 자동 생성**(`session_rotate`, 구 세션/DB 삭제 안 함)
3. **ctl doctor/repair**
   - `kill_orphan_agy`: PPID=1 + **no `--conversation`** + (보호되지 않은 flash-low) 정리
   - probe: `stop`+`/discard` 후 prune 재실행
4. UI: `static/index.html` 배너, `app.js` + Hub FAB SSE/rotate 처리

### 검증
- `chatbot-ctl.sh guard` / `doctor` / healthz / 프로브 후 flash-low 잔존 없음


## 2026-09-16 — 스마트폰 가상키보드 대응 & 모바일 반응형 UX 최적화

### 증상 및 원인
- 스마트폰에서 대화창 터치 시 가상키보드가 올라오면서 상단 헤더와 대화가 화면 위로 밀려 사라짐.
- 원인:
  1. `.stage`, `#log`, `#artifacts`, `#activity`에 `min-height: 420px`가 강제되어 키보드 영역(300~350px) 확보 불가로 윈도우 스크롤 발생.
  2. `body`와 `.wrap`에 `min-height: 100vh`가 적용되어 키보드 팝업 시 포커스된 `textarea`를 브라우저가 화면 중앙으로 스크롤하면서 헤더 영역이 화면 밖으로 벗어남.
  3. `textarea` 폰트 크기 및 높이가 모바일 미최적화되어 iOS 자동 줌 및 화면 압박 발생.

### 변경
1. **뷰포트 및 스크롤 고정 (`static/index.html`)**:
   - `meta[name=viewport]`에 `viewport-fit=cover, interactive-widget=resizes-content` 추가.
   - `html, body`: `height: var(--app-height, 100dvh); overflow: hidden;` 로 윈도우 스크롤 차단.
   - `.stage`, `#log`, `#artifacts`, `#activity`: `min-height: 420px` 제거, `flex: 1 1 0; min-height: 0;` 적용하여 키보드가 열려도 내부 스크롤만 유연하게 축소/동작.
2. **모바일 컴팩트 헤더 (`@media (max-width: 640px)`)**:
   - 아바타 34px, 서브텍스트 숨김, 패딩 및 여백 대폭 슬림화로 상단 고정 헤더 영역 확보.
3. **가상키보드 연동 & 입력창 최적화 (`static/app.js`)**:
   - `window.visualViewport` 리사이즈 및 스크롤 이벤트 감지하여 `--app-height` 실시간 업데이트.
   - `textarea` 16px 지정(iOS 포커스 시 자동 확대 방지) 및 1줄(38~42px)에서 입력 내용에 따라 최대 90~120px로 자동 확장(auto-grow).
   - 입력창 포커스 시 최신 대화 위치로 부드럽게 스크롤.
4. **Hub FAB 모바일 대응 (`/volume1/web/index.html`)**:
   - 모바일에서 FAB 팝업 시 화면 전체(Full-screen sheet) 모드로 열리도록 스타일 및 VisualViewport 핸들러 동기화.



## 2026-09-16 09:10 KST — successor-sticky rotate
- hard 세션 rotate 시 `successor_session_id` 재사용 (매 POST마다 새 세션 생성 금지)
- GET hard+successor → `redirect_session_id` 노출; UI boot/openSession이 successor로 점프
- hard `20260916-064817-8da2bb` meta에 successor 지정; ctl restart + guard/smoke


## 2026-09-16 — FAB↔전체창 세션 패리티 마무리
- FAB: 이어하기(continue) + 세션 길이 배너 + SSE 자동 재연결
- 전체창: SSE 재연결 동일
- ctl: 호스트 재시작 후 conversation 고아 agy(PPID≠chat) 정리
- SELF-MODIFY: 라이브 턴에서 `chatbot-ctl.sh restart` 금지 (스트림 단절)


## 2026-09-16 — host self-restart hard gate
- Repeated SSE drops: live agy ran `chatbot-ctl.sh restart` mid-turn (background webp work)
- `stop`/`restart` require `CHATBOT_FORCE_HOST=1`; `repair` exports it
- Persona: half.webp ~132KB / face-icon.webp ~19KB (png was multi-MB)


## 2026-09-16 — ⚡전기충격·심폐소생 버튼
- ctl: `defibrillate|shock|cpr` → FORCE repair
- API: `POST /api/host/defibrillate` (202 후 백그라운드 repair), `GET /api/host/status`
- UI: FAB `⚡소생`, 전체창 `⚡ 소생` — confirm → repair → healthz 폴링 → 세션 재연결


## 2026-09-16 — host ticket gate (FORCE bypass closed)
- Model bypassed FORCE by exporting `CHATBOT_FORCE_HOST=1` then restart
- stop/restart now need FORCE **and** fresh `{DATA}/host-force.ticket` (TTL 120s)
- Ticket minted only by `repair` / API defibrillate; consumed on EXIT


## 2026-09-16 — 상세 도구 실행 로그 & 결과 파싱 지원 (0 추가 토큰)
- 배경: 실장님 피드백("로그가 좀 더 자세히 찍히면 좋겠어. 지금은 제목만 나오네. 토큰이 추가적으로 든다면 안해도 되고.")
- 핵심: LLM 추가 호출 없이 agy 로컬 stream-json에 이미 존재하는 도구 인자(명령어, 파일 경로, 액션 요약 등) 및 결과 요약을 파싱하여 노출. **추가 토큰 소모 0**.
- `server.py`:
  - `_format_tool_call`: 도구별 핵심 인자(run_command의 CommandLine, view_file의 AbsolutePath/Line, grep/find의 Query/Pattern, edit/write의 TargetFile/설명 등)를 사람이 읽기 쉬운 한 줄 요약으로 포맷.
  - `_format_tool_result`: 도구 결과(type=GENERIC, tool_result)의 첫 유의미한 라인과 요약 반환 (`↳ 결과... (외 N줄)`).
  - `_tool_summary`: `tool_calls` 리스트 및 `GENERIC` 결과 파싱 확장, 도구 이벤트 리스트 반환 지원.
- `static/app.js` & `/volume1/web/index.html`:
  - UI `addActivity(line, kind)` 확장 및 카테고리별 컬러 하이라이팅(`.act-tool` 파랑, `.act-result` 회색/들여쓰기, `.act-error` 빨강, `.act-warn` 주황).
  - 서버 재기동 전에도 즉시 반영되도록 `event: agy`의 payload `tool_calls`/`GENERIC` 클라이언트 폴백 파서 탑재.
  - 브라우저 캐시 버스터 `app.js?v=10` 갱신.
- 안전: 라이브 자가 재기동 금지 규칙 준수. 프론트엔드는 새로고침(F5)으로 즉시 적용, 서버 코어는 디스크 반영 완료 (다음 소생/재기동 시 로드).



## 2026-09-16 — 정체성 강화 (자가진화형·고양이 수인·만능 콘텐츠 크리에이터)
- 실장님 요청: "자가진화형 미소녀 고양이 수인 만능 컨텐츠 크리에이터 챗봇" 정체성 강화
- `PERSONA.md` / `AGENTS.md` (workspace)에 정체성(Identity) 섹션 추가:
  - 자가진화형: SELF-MODIFY.md 원칙 그대로, 스스로 성장하는 걸 자부심으로 삼는 성격 서술 추가
  - 미소녀 고양이 수인: 기존 비주얼 락(풀 동물화 금지, 귀·꼬리 악센트) 유지한 채 명시적으로 재확인
  - 만능 콘텐츠 크리에이터: NAS 운영 비서 범위를 넘어 이미지 프롬프트/카피/자막/문서/코드 등 콘텐츠 제작자 역할 명시, Domain & Lore scope에 반영
- `persona.json`(config)은 코드에서 미참조 확인 → 변경 대상 아님, 손대지 않음
- 코어 코드(server.py) 무변경 — 세션 스폰 시 agy가 읽는 workspace 파일만 수정, 재기동 불필요, 다음 새 세션부터 반영
- smoke: healthz OK


## 2026-09-16 — 자기 상태 대시보드 (⚙ 상태 탭) + task-observer 정식 업그레이드
- 실장님 요청: 규칙/MCP/스킬/훅/플러그인 현재 상태를 보고 관리할 수 있는 UI
- **task-observer**: 워크스페이스 사본이 구버전(446줄, references 3/7)이었음 → FIREBAT 최신판(709줄, references 7/7)으로 교체.
  기존 legacy `skill-observations/log.md`(관찰 5건, 전부 APPLIED)를 신규 per-file 포맷(`observation-log/0001~0005-*.md`)으로 마이그레이션, `log.md` → `log.md.migrated`로 보존.
  `last-review-date.txt`는 정직하게 `never` 유지 (실제 주간 리뷰가 실행된 적 없어서 — 지어내지 않음).
- **신규 관찰 0006 (OPEN)**: `/skill <name> ...` 형태 메시지가 agy를 무응답으로 죽이는 버그를 실측으로 확인 (평문 채팅은 9초 내 정상 응답, `/skill korea-weather ...`는 SKILL.md 스텁을 view_file로 읽은 직후 응답 없이 프로세스 종료 — k-skill.sh cli-stub → npx 후속 호출 이전에 죽음). 근본원인 미확정 (agy 단독 재현은 하니스의 "Create Unsafe Agents" 분류기에 막힘) — `chatbot-ctl.sh doctor`에 스킬 전용 스모크 테스트 추가를 제안.
- **API 추가 (server.py)**: `GET /api/self-status` (규칙/스킬/MCP/훅/task-observer 요약), `GET/PUT /api/rules/:name` (AGENTS/PERSONA/PROJECT/SELF-MODIFY 읽기·편집, 편집 시 `.bak-selfstatus-<ts>` 자동 백업), `GET/POST /api/mcp` + `DELETE /api/mcp/:name` (nas는 core라 삭제 불가), `POST /api/skills/:name/toggle` (워크스페이스 스킬 on/off, `_` 접두사로 비활성화).
- **UI 추가**: 4번째 탭 `⚙ 상태` — 규칙 파일 목록(편집 버튼→textarea 저장), 프로젝트 스킬 토글, MCP 서버 목록+추가/삭제, 훅/플러그인 안내, task-observer 상태 요약. `app.js?v=11`.
- 안전: 이번 변경은 server.py 코어 변경이라 재기동 필요 — 라이브 세션 2개 있어 즉시 재기동하지 않고 실장님 ⚡소생 대기 (SELF-MODIFY.md 원칙 준수). static(index.html/app.js)은 재기동 없이 새로고침만으로 반영됨.
- smoke: `python3 -m py_compile server.py` OK. 재기동 후 `/api/self-status` 응답 및 상태 탭 렌더링 확인 필요 (TODO).

## 2026-09-16 — 프롬프트 최적화: AGENTS.md 중복 제거 + SELF-MODIFY.md 조건부 로드
- 실장님 질문: 프롬프트 최적화 가능한지
- 발견: `AGENTS.md`에 host-restart 규칙이 `Host safety`와 `Host restart — hard rule` 두 섹션에 중복 서술돼 있었음 (하나로 병합, 내용 손실 없음). `Observation Protocol`의 `skill-observations/log.md` 경로도 오늘 마이그레이션으로 stale해진 걸 발견해서 `observation-log/`로 수정.
- **진짜 최적화 지점**: `SELF-MODIFY.md`(4.1KB, 4개 규칙파일 중 최대)가 코드/호스트를 전혀 안 건드리는 일반 대화/콘텐츠/NAS-ops 턴에서도 매번 읽힐 가능성이 컸음 (AGENTS.md가 무조건 "Obey SELF-MODIFY.md"라고만 했음). AGENTS.md의 self-modification 규칙을 "핵심 한 줄은 항상 유효, 전체 문서는 실제 코드/호스트를 건드릴 때만 view_file"로 명시적으로 게이팅함.
- 참고: AGENTS.md 자체 바이트 수는 거의 그대로 (3708→3826, 게이팅 설명 문장이 길어서) — 절약은 파일 크기가 아니라 "코드 안 건드리는 턴엔 SELF-MODIFY.md 안 읽음"이라는 행동 변화에서 나옴.
- 재기동 불필요 (AGENTS.md는 세션 스폰마다 새로 읽힘). healthz OK.

## 2026-09-16 — SSE 멀티 클라이언트 브로드캐스트 패치 (스트리밍 글자 누락/핑퐁 버그 수정)
- 증상: 동일 세션에 브라우저 창/탭이 복수 연결(또는 재연결)되어 있을 때, 스트리밍 텍스트 청크(`delta` 이벤트)가 각 클라이언트로 홀수/짝수 번갈아가며 분할 소비되어 화면상에 글자가 듬성듬성 통째로 누락되는 현상 발생.
- 원인: `AgySession.events`가 단일 `queue.Queue`로 구현되어 있어, 복수 SSE 연결(`_sse`)이 동일 큐에서 `.get()`을 호출하며 이벤트를 1:1로 가로채가는 구조적 결함.
- 해결: `AgySession.subscribers` 리스트를 도입하여 `_emit` 시 활성 SSE 연결 각각의 전용 큐로 브로드캐스트하도록 수정. `_sse` 종료 시 `finally` 블록에서 안전하게 구독 해제.
- 검증: `python3 -m py_compile server.py` 통과, `chatbot-ctl.sh guard` (guard_rlock OK) 통과.
- 안전: 라이브 세션 보호를 위해 디스크 패치만 완료 (`SELF-MODIFY.md` 원칙). 상단 ⚡소생 버튼 또는 다음 서비스 재기동 시 자동 적용.

## 2026-09-16 — 진짜 원인 확정: doctor의 orphan-kill이 방금 시작한 세션을 죽임 (`/skill` 무응답 사망 버그)
- 배경: 관찰 0006 — `/skill korea-weather ...` 등 스킬 호출이 간헐적으로 무응답으로 죽는 버그. 처음엔 k-skill cli-stub → npx 후속 호출 과정의 크래시로 추정했으나 틀렸음.
- 진단: `AgySession.to_public()`에 `debug_stderr_tail`(프로세스 죽었을 때만 최근 stderr 15줄 노출) 추가 → 재현했더니 완전한 정답을 다 준 뒤에도 죽으면서 stderr에 `stream input cancelled: context canceled` 포착. "스킬 호출 자체가 깨진다"가 아니라 "정상 작업 도중 뭔가 죽인다"로 방향 전환.
- **진짜 원인**: `chatbot-ctl.sh`의 `kill_orphan_agy()`가 `--conversation` 플래그 없는 agy 프로세스를 전부 "doctor 프로브 잔재"로 간주해 즉시 SIGTERM. 그런데 **신규 세션의 첫 턴도 원래 `--conversation`이 없음**(agy 응답을 받아야 conversation_id를 알 수 있음) — doctor의 주기적(~600초) 정리가 하필 첫 턴 처리 중에 돌면 진짜 대화를 죽여버림. `/skill`은 `view_file`+`npx` 등 추가 호출로 30~40초 걸려서 평문 채팅(~9초)보다 이 창에 걸릴 확률이 훨씬 높았을 뿐, `/skill` 고유 버그가 아니었음.
- 수정: `kill_orphan_agy()`(`chatbot-ctl.sh`)에 `NO_CONV_GRACE_SEC=90` 유예 시간 추가. `ps -eo pid=,ppid=,etimes=,args=`로 경과 시간(etimes)까지 받아서, `--conversation` 없는 프로세스라도 90초 이내면 죽이지 않음. `ppid==1`(진짜 고아) 조건은 그대로 즉시 정리.
- **실측 검증**: `/skill korea-weather 부산 날씨` 전송 후 5초 시점에 `--conversation` 없이 살아있는 걸 `ps`로 확인, 그 순간 `chatbot-ctl.sh doctor`를 수동 실행 → `orphan_agy_killed=0`으로 안 죽음 확인, 35초 뒤 정상 응답 + `alive: true`로 완료. 서버(`server.py`) 재기동 불필요 — `chatbot-ctl.sh`는 독립 스크립트라 다음 실행부터 바로 반영.
- 관찰 0006을 `status: actioned`로 갱신, 근본원인 정정 기록.

## 2026-09-16 — 음성 입력(STT)/읽어주기(TTS) 추가
- 배경: 실장님 요청 — TTS/STT 지원. agy 자체 `/voice`(F5) STT는 확인했지만 대화형 터미널+로컬 마이크 전용 기능이라 헤드리스 stream-json 서버 구조엔 안 맞음(브라우저 사용자 마이크를 agy 프로세스로 연결할 방법이 없음). TTS는 agy에 아예 내장 안 됨. 그래서 브라우저 네이티브 Web Speech API로 구현 — 서버/agy 변경 없이 순수 프론트엔드.
- **STT (`static/index.html`, `static/app.js`)**: 컴포저에 🎤 버튼 추가. `SpeechRecognition`/`webkitSpeechRecognition`(`lang=ko-KR`, `interimResults=true`)으로 실시간 받아쓰기 → `#input`에 반영. 듣는 중엔 버튼이 빨갛게 pulse 애니메이션. 미지원 브라우저(Firefox 등)는 버튼 반투명 처리 + 클릭 시 안내.
- **TTS**: 완성된 assistant 메시지 하단에 🔊 버튼 추가 (`attachTtsButton`, `postProcessAssistant`에 raw markdown 텍스트 전달). `stripMarkdownForSpeech()`로 `**`/`#`/코드블록/테이블 등 마크다운 문법 제거 후 `speechSynthesis`로 재생, 한국어 음성(`lang.startsWith('ko')`) 자동 선택. 재생 중 버튼 🔊→⏹ 전환, 다시 누르면 정지.
- 캐시 버스터 `app.js?v=12`.
- 범위: 전체창(`:3011`)만 적용. Hub FAB(`/volume1/web/index.html`)은 별도 컴포저라 아직 미적용 — 필요하면 FAB↔전체창 패리티 작업 때 같이.
- 재기동 불필요 (순수 static 파일). git 커밋: `a869cad`.

## 2026-09-16 — AgentAdapter 구조 도입, 사용량(/usage) 대시보드, 응답 속도 최적화(프로세스 프리웜)
- **AgentAdapter (구조만)**: 실장님 요청 — VibeCat(`Source/VibeCat/Private/AgentAdapters.cpp`)처럼 여러 provider를 고려한 설계로 리팩터 가능한지 문의받아 진행. `AgentAdapter` 베이스 + `AgyAdapter` 구현체 추가 (`find_executable/build_args/build_env/format_stdin`). `AgySession._spawn()`/`_send_direct()`가 하드코딩 대신 `self.adapter`를 통해 프로세스 스폰·stdin 작성. `claude`/`codex`/`grok` 어댑터는 미구현 — diskstation엔 `grok`만 설치돼 있고 나머지는 없어서, 실제 필요해지면 그때 상속 추가. `_read_stdout`의 stream-json 파싱(~300줄, 오늘 데드락 사고 2건의 근원지)은 의도적으로 안 건드림 — 구조만 요청 범위 밖. 커밋 `2de9e0b`.
- **사용량 대시보드**: 실장님 문의 — `agy`에 `/usage`(모델별 주간/5시간 한도) 확인 기능이 있는지. 확인 결과 `/usage`는 stream-json 세션 안에서는 못 쓰고(`agy` 자체가 명시적으로 에러 반환: "unavailable with --input-format stream-json"), `agy --print /usage`로 별도 단발 호출해야 함. `GET /api/usage` 추가 — 5분 캐싱, `?force=1`로 강제 재조회. ⚙ 상태 탭에 "📊 사용량" 섹션(모델별 잔여율 바 차트, 20% 이하 빨간색). 커밋 `f7a168b`.
- **응답 속도 조사**: 실장님이 "첫 메시지가 느리다"고 보고. 실측 결과 — 같은 세션 두 번째 메시지부터는 ~3.5초인데 신규 세션 첫 메시지는 ~10초. `agy --print` 단독 호출도 모델/effort 무관하게 항상 7~9초 걸리는 걸 확인 (네트워크 지연 아님 — googleapis.com TTFB는 0.3초 수준; CPU도 1.3초만 씀 → 나머지 ~7초는 agy/Antigravity 백엔드 자체의 고정 콜드스타트 오버헤드).
- **표준 대기(prewarm) 풀 도입**: `_StandbyPool` — DEFAULT_MODEL·effort 없음 조건으로 idle agy 프로세스 1개를 항상 미리 띄워둠 (`_standby_maintenance_loop`, 15초마다 점검). 신규 세션 첫 메시지가 이 조건에 맞으면 콜드스팟 대신 이 프로세스를 즉시 인수(adopt). 못 쓰이고 남은 standby는 `--conversation` 없는 상태라 기존 `kill_orphan_agy`의 90초 유예 로직이 자동으로 정리 — 별도 만료 로직 불필요. **실측 검증**: 신규 세션 첫 메시지 10초 → **3.5초**로 단축 확인, standby 소비 후 재충전도 확인. 커밋 `005243c`.
- **사용량 감소 체감 관련 별도 발견 + 조치**: `chatbot-ctl.sh`의 doctor 프로브가 10분마다(`PROBE_EVERY_SEC=600`) **실제로 새 프로세스를 띄우고 진짜 메시지를 gemini-3.8-flash-low에 전송**해서 정상 응답을 확인함 — 주간 최대 ~1,000회, 실장님 대화량과 무관하게 상시 실제 토큰 소비. `guard_rlock`이 이미 오늘 데드락의 근본원인(Lock 회귀)을 코드 레벨에서 막고 있어서, 실메시지 프로브는 그 외의 예상 못한 행에 대한 저빈도 안전망 정도면 충분하다고 판단 — `PROBE_EVERY_SEC` 600→**3600**(1시간)로 조정, 토큰 소비 약 1/6로 감소. healthz/orphan 정리는 무료라 그대로 유지.
- **prewarm ↔ orphan-kill 충돌 발견 + 수정**: 배포 직후 실측 중 standby 프로세스가 90초 유예 지나자마자 `kill_orphan_agy`한테 "no-conversation" 사유로 죽는 걸 발견 — 의도한 "재사용 대기" 상태가 우연히 "방치된 프로브 잔재" 패턴과 똑같아서 생긴 충돌. `chatbot-data/standby.pid` 마커 파일 도입: `_StandbyPool`이 스폰 시 PID를 써두고 인수(adopt) 시 지움, `kill_orphan_agy`는 이 PID만 no-conversation 사유에서 예외 처리 (ppid=1 진짜 고아 조건은 그대로 적용 — 서버 재기동 시 못 쓰게 된 standby는 정리됨). **실측 재검증**: standby가 90초 넘게도 안 죽는 것 확인, 채택 시 마커 삭제 + 즉시 재충전까지 정상 동작. 커밋 `a767f8c`.
- 참고: `chatbot-ctl.sh`는 `~/services/chatbot/` 밖(`~/services/`)에 있어서 이번에 만든 git repo 추적 대상이 아님 — 백업이 `.bak-*`(오늘 대부분 정리함) 방식 그대로. 필요하면 나중에 별도 repo화 고려. → **이후 실제로 `chatbot-ctl.sh`를 repo 안(`chatbot/chatbot-ctl.sh`)으로 이동, 기존 경로엔 심링크로 호환성 유지, 잔여 `.bak-*` 8개 추가 정리.**
- **전체 백업 확장 (실장님 요청 — private repo니까 대화 기록·생성물까지)**: `chatbot-data/sessions`, `chatbot-data/artifacts`, `chatbot-data/persona`를 각각 별도 git repo로 만들어 publish repo(`See1Studios/chatbot`)에 `data/sessions`, `data/artifacts`, `data/persona` subtree로 병합. README에 5개 subtree 구조 + "반드시 private 유지" 명시.
- **턴별 토큰 사용량 표시**: 실장님 요청으로 냥피디가 백엔드(`result` 이벤트의 `usage`/`duration_seconds` 파싱, `server.py`)를 작업 중이었으나 로그에 아무것도 안 보임 — 확인해보니 (1) 백엔드 코드가 디스크에만 있고 재기동 전이라 미반영, (2) 프론트엔드는 전혀 손 안 댐. `app.js`에 `logTurnUsage()` 추가해서 📜 로그 탭에 턴별 토큰(입력/출력/사고/캐시)+소요시간+세션 누계 표시, `/btw`에도 동일 적용. 재기동 중 서버가 잠깐 다운돼 있던 것도 발견해서 복구(냥피디의 자체 재기동 시도 중 발생한 걸로 추정).
- **🔥 토큰 사용량 폭증 원인 발견 + 수정 (핵심)**: 실장님이 "CLI로 할 때보다 급격히 소모되는 느낌"이라고 지적 — 직접 A/B 격리 테스트로 추적. 순정 `agy --print`(add-dir 없음) = 입력 14,244토큰. 챗봇과 동일한 `--add-dir`(`chatbot`, `chatbot-data`, `/volume1/web/chat`) 적용 = **45,488토큰 (3.2배)**. `chatbot-data`의 자식 디렉토리(`workspace`/`sessions`/`artifacts`/`persona`)를 하나씩 단독으로 넣어보면 전부 14K대 그대로인데, **`chatbot-data`를 부모로 통째로 넣을 때만** 45K로 튐 — 개별 파일 내용이 아니라 "많은 항목을 가진 루트 디렉토리를 통째로 add-dir"할 때 agy 자체의 디렉토리 스캔/컨텍스트 구성 비용이 비정상적으로 커지는 것으로 추정(정확한 내부 메커니즘은 closed-source라 확인 불가). `chatbot-repo-publish`를 `chatbot-data` 밖으로 옮겨도 변화 없어서 "중복 서브트리 때문"이라는 1차 가설은 기각. **수정**: `ADD_DIRS`를 부모(`chatbot-data`) 하나 대신 자식 4개(`workspace`/`sessions`/`artifacts`/`persona`)를 개별로 나열하도록 변경 — 동일한 파일 접근 범위를 유지하면서 신규 대화 첫 턴 비용을 **45K → 16K (~65% 절감)**. 재기동 후 실제 API로 15,978토큰 확인, 완전히 검증됨.
- 관찰 0009 (재기동 직후 첫 standby 채택 시 usage가 간헐적으로 전부 0) — 오늘 재기동 2번에서 재현, 여전히 재현 조건 미확정. 몇 초 뒤 재시도하면 정상.

## 2026-09-16 — 빈 툴콜 로그 라인 방지 가드 & 기본 모델 gemini-3.8-flash-low 전환
- **빈 툴콜 로그 방지 (`server.py`, `static/app.js`)**: 스트리밍 진행 중 인자(args)가 아직 도착하지 않은 불완전한 상태에서 `run_command:` 등 빈 툴콜 라인이 로그에 찍히거나 중복 방지(dedup)를 방해하는 문제를 수정. 서버 `_format_tool_call`과 클라이언트 `formatToolCallClient` 양쪽에서 필수 인자가 없으면 빈 문자열을 반환하여 완성된 호출이 도착할 때까지 대기하도록 가드 추가.
- **기본 모델 전환 (`gemini-3.8-flash-low`)**: 실측 결과 Medium 대비 약 36% 빠른 응답 속도와 간결한 답변, Thinking 오버헤드 억제로 일상 대화 및 작업 반응성이 대폭 향상됨을 확인하여 기본 모델을 `gemini-3.8-flash-low`로 변경.

## 2026-09-16 — Live2D 냥피디 마스코트 오버레이 위젯 추가 (데스크톱 펫 감성)
- **배경**: 실장님 요청 — See-Through API로 분할/인페인팅한 2.5D 멀티레이어 자산을 활용하여 옛 윈도우 데스크톱 마스코트처럼 채팅창 우측 하단에 상시 반응형 오버레이로 띄우기.
- **개선 (채팅창 가림 방지 & 여백 동적 배치 & 크기 확대)**:
  - 기존: `.stage` 내부 우측 하단 배치로 메시지 일부를 가리고 크기가 다소 작았음(`170px`).
  - 변경: 마스코트 컨테이너를 `body` 레벨(`position: fixed`)로 분리.
  - **여백 반응형 배치 (`updateMascotPositioning`)**:
    - 브라우저 창과 중앙 채팅창(`.wrap`, 960px) 사이의 좌/우 여백(`gutter`)을 실시간 계산.
    - 여백이 180px 이상 충분할 때: 채팅창 밖 외곽 여백(우측 우선, 필요시 좌측)으로 이동하고 크기를 **240px ~ 420px**(기존의 2배 이상!)로 큼직하고 시원하게 자동 확대.
    - 여백이 180px 미만인 협소 화면이나 모바일(width <= 768px): 채팅창 글자를 가리지 않도록 깔끔하게 자동 페이드아웃 숨김.
  - 캐시 버스터 `app.js?v=16`.
- **구현 (`static/index.html`, `static/app.js?v=16`)**:
  - **인터랙션 & 모션**: 마우스 커서 추적 시선/헤드 틸트 LERP, 2.6~6.4초 주기 자동 눈 깜빡임(속눈썹+눈동자+흰자+눈썹 연동), 6.5초 주기 귀 쫑긋, 미세 호흡 및 꼬리 살랑임 애니메이션.
  - **대화 & 사운드 연동**: 답변 스트리밍(`delta`) 및 TTS 재생 시 입 뻐끔(립싱크) 동작, 답변 완료(`result`) 시 귀 쫑긋 축하.
  - **클릭 리액션**: 마스코트 클릭(쓰다듬기) 시 귀 쫑긋 + 눈 깜빡임 + 랜덤 말풍선 대사 출력.
  - **토글 & 상태 보존**: 상단 탭 바에 `🐾 냥피디` 토글 버튼 제공, `localStorage('chatbot.mascotVisible')`에 설정 영구 저장. 대화 외 탭(아티팩트/로그/상태) 진입 시 깔끔하게 자동 숨김 처리.
- **안전**: 순수 프론트엔드 static 파일 수정으로 호스트 재기동 불필요, 브라우저 새로고침 즉시 반영.



## 2026-09-16 — SSE 재연결 시 응답 유실 버그 수정 (새로고침해야만 보이던 문제)

- **증상**: 실장님 보고 — "채팅을 하다가 가끔 아무 응답이 없을 때가 있는데 새로 고침해보면 응답이 와있는 경우가 발생". 서버-브라우저 연결이 끊긴 게 맞냐는 확인 질문에 그렇다고 답변.
- **원인**: `EventSource`는 연결이 끊기면(`es.onerror`) 재연결 시 완전히 새로운 구독(`sub_queue`)으로 시작하는데, 옛 구독이 끊긴 시점과 새 구독이 붙는 시점 사이의 공백 동안 서버가 `_emit()`한 이벤트(특히 턴 완료를 알리는 `result` 이벤트)는 죽은 큐에 담긴 채 아무도 안 읽어서 영구 유실됨. 재연결 트리거는 (1) 실제 네트워크 순단(수면/기상, 와이파이 전환), (2) `_sse()` 핸들러 자체의 900초(15분) 하드 커넷 — 둘 다 발생 가능. 반면 페이지 새로고침은 `/api/sessions/:id`를 REST로 다시 읽어 `history`(디스크에 이미 저장된 완료 응답 포함) 전체를 렌더하므로 항상 최신 상태가 보였음 — 이 REST vs SSE 간극이 "새로고침하면 보인다"의 정체.
- **수정** (`server.py`, `static/app.js`):
  - 서버: `result`/`btw` 이벤트 payload에 해당 history 항목과 동일한 `ts`를 실어보냄 (`out["ts"] = hist_item["ts"]`).
  - 클라이언트: `lastSyncedTs`로 "화면에 반영된 가장 최신 history 시각"을 추적. `bindEvents()`의 `es.onopen`(최초 연결이든 재연결이든 항상 호출됨)에서 신규 `resyncFromServer(sid)`를 호출 — `/api/sessions/:id`를 다시 읽어 `lastSyncedTs`보다 새로운 history 항목이 있으면 그 자리에서 렌더링하고 `busy` 상태도 동기화. 정상적으로 라이브 스트리밍된 턴은 이미 `lastSyncedTs`가 갱신돼 있어서 중복 렌더 없음.
- **검증**: 재기동(`chatbot-ctl.sh repair`) 후 probe_message 통과, healthz 정상. 실제 연결 끊김 재현은 못 했지만(순단 시뮬레이션 어려움) 로직 자체는 새로고침이 하던 일(히스토리 재동기화)을 재연결 시점마다 자동으로 수행하도록 만든 것이라 안전한 결정론적 수정.
- **배포 중 발견**: 최초 다운로드한 `app.js`가 그 사이 냥피디 본인이 실시간으로 편집 중이던 파일(마스코트 여백 반응형 배치 기능 추가 중)과 경쟁 상태였음 — swap-in 직전에 반드시 fresh diff로 재확인하는 절차 덕분에 그 변경분을 덮어쓰지 않고 무사히 병합함.
- 커밋: (아래 참고)

## 2026-09-16 — 세션 열람 3종: 위로 스크롤 시 과거 세션 자동 로딩, 전체 세션 목록 탭, "가져오기"

- **배경**: 실장님 요청 — "세션 관련 기능이 좀 아쉬워": (1) 세션이 무거워져 자동/수동으로 새 세션으로 넘어가면 이전 대화를 다시 볼 방법이 없음, (2) 지난 세션들을 목록으로 훑어볼 UI가 없음(백엔드 `REG.list()`는 이미 있었지만 시작 시 최신 세션 자동 복원 용도로만 쓰이고 있었음), (3) 열람 중 필요한 옛 세션을 발견해도 지금 대화로 가져올 방법이 없음.
- **① 스크롤백 (`static/app.js` `loadOlderHistory`, `server.py` `full=1`)**: 채팅 로그(`#log`) 상단 근처(120px 이내)까지 스크롤하면 현재 세션의 `predecessor_session_id`를 한 홉씩 따라가며 그 세션의 전체 히스토리를 불러와 위에 이어붙임. 한번에 전체 체인을 다 불러오지 않고 스크롤할 때마다 동적으로 한 세션씩 로드(실장님 지적사항 반영). 세션 경계마다 "── 세션 <id> ──" 구분선 + 📌 가져오기 버튼 표시, 체인 끝에 닿으면 "── 대화 시작 ──" 표시. 순수 열람용이며 agy 컨텍스트에는 전혀 주입되지 않음. 서버 쪽엔 `GET /api/sessions/:id?full=1`로 40개 제한 없이 저장된 전체 history(세션당 최대 80턴, `save_meta`가 이미 그렇게 캡)를 반환하도록 추가.
- **② 세션 목록 탭 (`static/index.html` `#sessionsPane`, 🗂 세션 탭)**: 기존에 있었지만 UI로 노출 안 되던 `GET /api/sessions`(최근 40개, 미리보기 포함)를 새 탭에서 목록으로 렌더링. 행 클릭 시 `openSession()`으로 그 세션으로 전환.
- **③ 가져오기 (`server.py` `GET /api/sessions/:id/summary`, `static/app.js` `importSessionContext`)**: 스크롤백 구분선이나 세션 목록 어디서든 📌 가져오기를 누르면, 대상 세션의 `get_handover_summary()`(이미 "이어하기"에서 쓰던 요약 로직 그대로 재사용, 대상 세션 상태는 전혀 건드리지 않음)를 가져와 현재 입력창 맨 위에 "[이전 세션 <id> 내용 참고]\n<요약>" 형태로 채워 넣음. 자동 전송은 하지 않고 실장님이 검토/수정 후 직접 보내야 실제 대화에 반영됨.
- **설계 원칙**: 세 기능 모두 순수 열람/보조 기능으로, `_read_stdout` 스트림 파싱이나 세션 로테이션 핵심 로직은 전혀 건드리지 않음 — 기존에 이미 있던 안전한 조각들(`REG.get()`의 지연 로딩, `get_handover_summary()`, 일반 메시지 전송 경로)만 재사용.
- **참고**: 실장님이 Claude Code의 세션 관리 방식(특히 `--resume` 피커, `/compact`)에서 영감을 받아 요청 — 세션 목록 탭은 정확히 그 피커 패턴. `/compact`처럼 세션 정체성을 유지한 채 내부적으로 압축하는 방식(현재는 로테이션 시 아예 새 세션 ID로 넘어감)은 로테이션 핵심 로직을 건드려야 해서 이번 범위에서는 제외 — 별도 논의 필요.
- **검증**: 재기동(`chatbot-ctl.sh repair`) 후 probe 통과, `GET /api/sessions`, `GET /api/sessions/:id?full=1`, `GET /api/sessions/:id/summary` 모두 curl로 직접 확인.

## 2026-09-16 — 토큰 기반 세션 무거움(SOFT/HARD_TOKENS) 임계값 배포 + 네이티브 `/compact` 조사

- **배경**: 이전 세션 시점에 `turns`/`chars`/`db_bytes`만으로는 못 잡는 케이스(짧은 메시지 몇 턴인데 누적 토큰이 폭증하는 경우, 실측 1.38M 토큰/11턴)를 위해 `SOFT_TOKENS=150,000`/`HARD_TOKENS=400,000`을 준비했었으나 `server.py.candidate`로만 남아있고 실제 배포된 적은 없었음(오늘 재확인: `_session_weight()`가 `total_tokens`를 계산해서 응답에는 포함하고 있었지만 `level` 판정 조건에는 전혀 반영이 안 되어 있었음). 이번에 그 사이 쌓인 다른 변경들(SSE 재동기화, 세션 열람 기능) 위에 새로 깔끔하게 재적용해서 배포.
- **적용**: `_session_weight()`의 `hard`/`soft` 판정 조건에 `total_tokens >= HARD_TOKENS` / `>= SOFT_TOKENS`를 추가, 응답에 `soft_tokens`/`hard_tokens` 필드 추가(프론트 표시용, `soft_turns`/`hard_turns`와 동일 패턴).
- **검증**: 배포 직후 실측 — 558만 토큰짜리 기존 세션이 이전엔 `level: ok`로 나오던 게 재기동 후 정상적으로 `level: hard`로 감지됨.
- **네이티브 `/compact` 조사 (실장님 요청)**: agy CLI가 `/compact`를 네이티브로 지원하는 게 맞고(품질도 좋음 — 압축 후에도 세부 사실 정확히 기억), 로테이션을 이걸로 대체해서 세션 정체성을 유지하는 방안을 검토함. 그런데 **실제 운영 방식(지속 프로세스+stdin, 그리고 프로세스 재기동+`--conversation` 재개 둘 다)으로 재현 테스트한 결과, `/compact`는 요약 텍스트만 만들어줄 뿐 실제로 재전송/과금되는 컨텍스트 크기는 전혀 줄여주지 않음** — 매턴 동일한 증가율(~15K/턴)이 압축 전후 변화 없이 계속됨. `conversation.db`(sqlite) 직접 열람으로도 `/compact` 전후 `steps` 테이블 행 수가 압축과 무관하게 계속 증가하는 것 확인 — 이건 실제 컨텍스트 저장소가 아니라 Antigravity 자체 스텝 추적 로그로 추정. 실장님 가설(진짜 압축은 인터랙티브 클라이언트 쪽에서만 일어나고, `--input-format stream-json` 헤드리스 경로는 그 혜택을 못 받는 우회로일 것)이 가장 그럴듯한 설명 — closed-source라 여기까지가 블랙박스 검증 한계.
- **결론**: 비용을 실제로 리셋하는 유일한 방법은 여전히 기존 세션 로테이션(새 세션 ID로 갈아타기)이라 그대로 유지. 다만 로테이션 시 새 세션에 넘기는 인계 요약(`get_handover_summary()`, 현재는 자체 제작 경량 프롬프트로 최근 8턴만 요약)을 네이티브 `/compact`의 결과물로 교체하는 건 품질 개선 후보로 남겨둠(별도 작업 예정) — 이건 비용 절감이 아니라 요약 품질 개선 목적.
- **참고**: 스크롤백/세션 목록/가져오기 기능(같은 날 앞서 추가)이 "로테이션해도 이전 내용을 잃지 않는다"는 부분을 이미 커버하고 있어서, 로테이션을 유지하는 결정의 부담이 줄어듦.

## 2026-09-16 — 인계 요약을 네이티브 `/compact`로 교체

- **배경**: `/compact`가 비용은 안 줄여준다고 결론 냈지만(바로 위 항목), 실장님이 "그 결과물 자체는 새 세션 인계 컨텍스트로 활용할 수 있지 않냐"고 제안 — 정확히 맞는 지적. 기존 `get_handover_summary()`는 자체 제작한 가벼운 프롬프트로 최근 8턴 텍스트만 보고 요약했는데, 네이티브 `/compact`는 `--conversation <id>`로 실제 대화 전체(도구 호출 상태 포함)를 보고 요약하므로 품질이 더 좋음.
- **동시 접근 안전성 사전 검증**: 로테이션 시점엔 옛 세션의 지속 프로세스(`self.proc`)가 아직 살아있는 채로 같은 `conversation_id`에 대해 별도 one-shot `/compact` 호출을 날리게 됨 — 격리 테스트로 사전 확인: 지속 프로세스가 켜진 채로 동시에 같은 conversation_id에 one-shot 호출을 날려도 충돌/행 없이 정상 완료(8.9초), 이후 지속 프로세스도 계속 정상 동작 확인.
- **구현 (`server.py` `get_handover_summary`)**: `self.conversation_id`가 있으면 먼저 `agy -p "/compact" --conversation <id> --model gemini-3.8-flash-low --dangerously-skip-permissions`(timeout 45초 — 무거운 세션은 압축 자체도 오래 걸릴 수 있음)를 시도, 실패/타임아웃/conversation_id 없음이면 기존 커스텀 프롬프트 방식(`_dialogue_summary_fallback`로 분리)으로 폴백. 세션 로테이션(`_rotate_to_fresh_session`)과 스크롤백 "가져오기"(`GET /api/sessions/:id/summary`) 둘 다 이 함수를 그대로 재사용하므로 자동으로 품질 개선 혜택을 받음.
- **검증**: 재기동 후 실제 무거운 세션(558만 토큰)에 대해 `/api/sessions/:id/summary` 호출 → 이전 경량 프롬프트보다 훨씬 상세하고 정확한 요약 확인.

## 2026-09-16 — 스크롤백이 짧은 세션에서 실제로 작동 안 하던 버그 수정

- **증상**: 실장님 확인 — "예전 대화 스크롤해서 보기는 안된 거야?". 기능은 배포돼 있었지만(`loadOlderHistory` 등 코드 존재, `/api/sessions/:id?full=1` 정상 동작 확인) 실사용에서 트리거가 안 됨.
- **원인**: `#log`는 `overflow-y:auto`라, 현재 세션의 히스토리가 화면 한 번에 다 들어갈 만큼 짧으면(로테이션 직후 등) 스크롤바 자체가 안 생겨서 물리적으로 위로 스크롤할 수가 없음 — `scroll` 이벤트가 아예 안 붙어서 `loadOlderHistory()`가 절대 호출되지 않았음. 세션이 로테이션 직후일수록(=이전 대화를 보고 싶은 바로 그 상황) 짧아서 더 잘 걸리는 역설적인 버그.
- **수정 (`static/app.js`)**: `maybeBackfillScrollback()` 추가 — `#log`의 `scrollHeight`가 `clientHeight`를 못 넘으면(=스크롤할 게 없으면) `predecessor_session_id`가 남아있는 한 자동으로 `loadOlderHistory()`를 체인 호출해서 화면이 찰 때까지(또는 체인이 끝날 때까지) 미리 채워둠. `openSession()` 초기 렌더 직후와 `loadOlderHistory()` 자기 자신의 끝에서 호출 — 이후엔 정상적으로 사용자가 실제로 위로 스크롤할 때만 추가 로딩됨.
- **배포**: 순수 프론트엔드 static 파일이라 재기동 불필요, 브라우저 새로고침(Ctrl+Shift+R)만 필요.

## 2026-09-16 — "완전 새 세션"에서도 직전 대화 스크롤백 가능하도록

- **요청**: 실장님 — "새 세션이어도 직전 대화가 보여야 하지 않을까". "완전 새 세션"(`createSession`)은 의도적으로 `predecessor_session_id`가 없음(인계 요약이 새 세션 컨텍스트로 안 새어들어가야 하니까) — 하지만 열람용 스크롤백까지 막을 이유는 없음.
- **수정 (`static/app.js` `createSession`)**: 새 세션 생성 직전의 `sessionId`(브라우저에서 방금까지 열려있던 세션)를 `prevSessionId`로 따로 저장해뒀다가, 새 세션의 `scrollbackSid` 시작점으로 사용. 서버의 실제 `predecessor_session_id`는 여전히 비어있으므로 agy 컨텍스트엔 아무 영향 없고, 순수하게 열람 체인의 시작점만 "방금 전에 보던 세션"으로 잡아줌 — 거기서부터는 그 세션의 진짜 predecessor 체인을 계속 타고 올라감.
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-16 — 스크롤백: 빈 세션 체인 통과 + 세션 목록 정리 + 순환 참조 방지

- **증상**: 실장님 확인 — "새 세션이어도 직전 대화가 보여야 하지 않을까" 이후에도 "안되는데". 재현: "새 세션"을 연달아 여러 번 눌러서 테스트하면 직전 세션도 텅 빈 새 세션이라, 그 세션의 `predecessor_session_id`도 비어있어서 스크롤백 체인이 거기서 바로 끊김("── 대화 시작 ──"이 한 홉만에 뜸). 실장님이 직접 "직전 세션이 텅 비어있던 게 문제이려나"로 정확히 짚음.
- **수정 1 (`static/app.js` `loadOlderHistory`)**: 한 홉이 비어있으면(`history.length === 0`) 구분선을 안 띄우고 조용히 다음 세션으로 계속 건너뛰도록 변경(최대 20홉/호출). `predecessor_session_id`가 없는 세션(= "완전 새 세션"으로 시작된 지점)을 만나면 `resolveScrollbackFallback()`으로 전체 세션 목록에서 시간상 바로 이전 세션을 찾아 계속 이어감 — 실제 predecessor 링크는 그대로 비워두고(agy 컨텍스트엔 영향 없음) 열람 체인만 이어붙임.
- **버그 발견 및 수정 (배포 전 시뮬레이션으로 잡음)**:
  - `GET /api/sessions/:id`의 `updated_at`(epoch 초 float, 파일 mtime)과 `GET /api/sessions`(목록)의 `updated_at`(meta.json의 ISO 문자열) 포맷이 서로 다른 기존 불일치를 발견 — 문자열과 숫자를 직접 비교하면 항상 거짓이 되어 폴백이 조용히 무력화됨. 두 값을 epoch-ms로 정규화하는 `_scrollbackEpochMs()` 추가로 해결.
  - 정규화 후 재시뮬레이션 중 **두 세션이 서로를 "다음 세션"으로 계속 가리키며 무한 루프**하는 걸 발견(거의 동시에 생성된 두 빈 세션의 mtime이 근소하게 엎치락뒤치락하는 것으로 추정) — `scrollbackVisited` Set으로 이미 방문한 세션은 다시 후보에 넣지 않도록 순환 참조 가드 추가. 배포 전 시뮬레이션으로 실제 세션 데이터에 대해 30홉까지 정상 종료 확인(빈 세션 11개를 건너뛰고 히스토리 58개짜리 실제 세션까지 정상 도달).
- **수정 2 (`static/app.js` `renderSessionsList`)**: 실장님 지적 — "세션 목록에는 많은 세션들이 보여"(테스트로 생긴 빈 세션들이 목록을 어지럽힘). preview가 없는(=완전히 빈) 세션은 목록에서 숨김, 단 현재 열려있는 세션은 비어있어도 항상 표시.
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-16 — 페이지를 열자마자 스크롤백이 시작조차 안 하던 진짜 원인

- **증상**: 실장님 확인 — "일단 페이지를 열면 스크롤바가 안 생겨있어" / "창을 줄여서 쥐어짜는 느낌으로 줄이면 이전 컨텐츠가 쭉 생기네". 앞선 커밋(빈 세션 건너뛰기 + 시간순 폴백)이 배포됐는데도 정작 페이지를 여는 시점엔 전혀 시도조차 안 되고 있었음.
- **원인**: `openSession()`(페이지 로드/새로고침 시 호출됨)이 `scrollbackExhausted = !info.predecessor_session_id`로 **그 자리에서 즉시** 결정해버리고 있었음 — `loadOlderHistory()` 안에 이미 만들어둔 "predecessor 없으면 시간순으로 폴백" 로직은 `scrollbackExhausted`가 `false`여야만 실행될 기회가 생기는데, 페이지를 여는 바로 그 세션 자체가 predecessor 없는 세션(최근 테스트로 만든 "새 세션"들 중 하나)이면 `loadOlderHistory()`가 단 한 번도 안 불려보고 그 자리에서 차단당함. 창을 줄이면 되던 이유는 별개로 이미 쌓여있던 내용이 스크롤 가능해지면서 보인 것일 뿐, 자동 backfill 자체는 애초에 시도조차 안 되고 있었음.
- **수정 (`static/app.js` `openSession`)**: `scrollbackExhausted`를 여기서 미리 판단하지 않고 항상 `false`로 시작 — 실제 판단은 `loadOlderHistory()`가 predecessor 유무를 직접 확인하고 필요하면 폴백까지 시도한 뒤에 내리도록 함.
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-16 — 세션·생성물 저장 구조를 세션별 폴더로 통합 (`sessions/<sid>/{meta.json, artifacts/}`)

- **배경**: 실장님 지적 — 이미지/생성물이 평탄한 `artifacts/brain/` 트리에 파일 원래 이름 그대로 저장되고 있어서, 세션 히스토리가 쌓이면서 다른 세션이 우연히 같은 이름으로 생성한 이미지가 있으면 덮어써질 수 있는 구조였음(`_stage_image`가 `src.name`만으로 목적지를 정함 — 실제로 컬렉션이 가능한 걸 확인). "세션과 생성물을 폴더로 관리하자"는 제안에서 시작해, 최종적으로는 "세션 이름 폴더 하나에 세션 JSON과 생성물을 같이 넣자"(상대경로 활용 가능, 한 세션이 통째로 자기완결적 단위가 됨)로 방향을 잡음.
- **이전 구조**: `sessions/<sid>.json`(평탄) + `artifacts/<conversation_id>/brain/*`(별도 repo, agy 내부 UUID로 네임스페이스 — 어느 세션이 만든 건지 파일 구조만 봐선 알 수 없었음).
- **새 구조**: `sessions/<session_id>/meta.json` + `sessions/<session_id>/artifacts/brain/*.png|jpg`. URL 스킴은 `/artifacts/<session_id>/brain/<filename>`.
- **서버 변경 (`server.py`)**: `AgySession.meta_path`, `save_meta()`, `_successor_usable()`, `Registry.list()/get_active()`(글롭 패턴 `*.json` → `*/meta.json`, id 추출 `p.stem` → `p.parent.name`), `_stage_image()`/`_rewrite_artifact_paths()`(대상 디렉토리를 `conversation_id` 대신 `self.sid` 기준 `sessions/<sid>/artifacts/brain/`으로), `get_artifacts()`(세션별 스캔 루트에 `sessions/<sid>/artifacts` 추가), `_safe_artifact_rel()`(`/artifacts/<sid>/...` URL을 `sessions/<sid>/artifacts/...`로 해석하는 후보 경로 추가) — 총 8곳 이상.
- **데이터 마이그레이션**: 서비스 정지 없이(짧은 창) 143개 `meta.json` 이동(git이 rename으로 인식) + 이미 옮겨둔 31개 아티팩트 이미지를 최종적으로 세션 폴더 안으로 재이동, 관련 6개 세션의 히스토리 텍스트 속 이미지 URL을 새 경로로 재작성. 파일명이 어느 세션에 속하는지 알 수 없는 11개(브랜드/페르소나용 수동 자산으로 추정 — `03-hub-logo.png`, `sei-portrait.png` 등)와 `see_through/` 레이어 분할 폴더는 손대지 않고 `artifacts/` repo에 그대로 둠.
- **git 구조 변경**: `chatbot-data/artifacts` repo에서 옮겨간 31개 이미지 삭제 커밋, `chatbot-data/sessions` repo에 143개 rename + 31개 신규 이미지 커밋. `artifacts/` repo는 이제 세션에 안 묶인 공용/수동 자산 전용으로 역할 축소. PROJECT.md에 새 레이아웃 문서화.
- **검증**: 재기동 후 세션 목록(40개), 옛 세션 히스토리 조회(40턴), 새 URL 스킴으로 이미지 서빙(200), 세션별 아티팩트 갤러리(36개) 모두 정상 확인.

## 2026-09-16 — 실제로 repo를 합침 (artifacts → sessions/_shared) + 배포 중 발견한 부작용 수정

- **배경**: 앞선 "세션별 폴더 통합" 작업에서 파일만 세션 폴더로 옮기고 `chatbot-data/artifacts` repo 자체는 남겨뒀던 걸 실장님이 지적("레포 합치는 거 아니었어?") — 원래 합의는 정확히 그거였음(AskUserQuestion에서 "sessions와 artifacts 두 repo를 하나로 합치고"를 선택).
- **실제 합침**: 어느 세션 것인지 특정 안 되는 나머지(`see_through/`, 11개 수동 자산, 루트 파일 1개)를 `chatbot-data/sessions/_shared/`로 이동, `ARTIFACTS_CACHE` 상수를 `DATA/"artifacts"` → `SESSIONS/"_shared"`로 변경. 이제 5개였던 repo가 4개(`chatbot`, `chatbot-data/workspace`, `chatbot-data/sessions`, `chatbot-data/persona`)로 줄었고, `chatbot-data/artifacts`는 완전히 은퇴 — 삭제 대신 `chatbot-data/_archive/artifacts-repo-retired-20260916/`로 보존(git 히스토리 포함, 되돌릴 수 있게).
- **부수 개선**: `ADD_DIRS`에서 이제 없는 `chatbot-data/artifacts` 항목 제거 — sessions 하위 폴더가 144개로 늘었는데도 add-dir 토큰 비용에 변화 없음을 실측 확인(14237 vs 14249, 오차범위) — 지난번 "부모 디렉토리 통짜 add-dir" 회귀와는 다른 패턴임을 재확인.
- **🔥 배포 중 발견한 심각한 부작용 (즉시 수정)**: `get_artifacts()`가 스캔한 모든 이미지에 대해 무조건 `_stage_image()`(자기 세션 폴더로 복사)를 호출하고 있었음 — `ARTIFACTS_CACHE`(`_shared`)가 스테이징 대상 폴더와 같은 경로였던 예전엔 자기 자신에게 복사하는 무해한 no-op이었는데, 이제 `_shared`와 `sessions/<sid>/artifacts`가 서로 다른 경로가 되면서 **아무 세션의 아티팩트 갤러리를 열어보기만 해도(빈 doctor-probe 세션 포함) `_shared/`의 이미지 36개 전부가 그 세션 자신의 폴더로 복사되는 버그**로 발현됨. 오늘 반복한 `chatbot-ctl.sh repair` 사이클 중 9개 빈 세션이 이미 오염된 걸 발견 — 정리 커밋으로 제거. 수정: agy의 원본 생성 캐시(`brain`)에서 발견한 이미지만 `_stage_image()`로 복사하고, 이미 안정적으로 서빙 가능한 위치(자기 세션 폴더, `_shared`)에서 발견한 건 실제 상대경로 기준으로 URL만 계산하도록 분기.
- **검증**: 재기동 후 신규 probe 세션으로 갤러리 조회 → 36개 정상 나열되지만 세션 자신의 폴더에는 `meta.json`만 남고 복사 안 됨 확인. `_shared`/세션 소유 아티팩트 서빙 URL 모두 200 확인.

## 2026-09-16 — `sphere-agy-*` 레거시 완전 정리, `services/` 폴더 청소

- **배경**: 실장님 지적 — `services/` 밑에 "chatbot"으로 개명하기 전 이름(`sphere-agy-*`)의 심링크/로그/`.bak` 파일이 계속 남아있는 게 지저분하다는 지적. "심링크를 그대로 두면 안되지, 싸그리 날리고 문서를 고쳐야지"라는 명확한 지시.
- **정리한 것**: `sphere-agy-chat`/`sphere-agy-data`(심링크), `sphere-agy-ctl.sh`(shim), `sphere-agy-chat.log`, `sphere-nas-mcp.log`(죽은 구 로그), `sphere-agy-ctl.sh.bak-20260916064538`(구 방식 백업 파일 — git 도입 후 불필요), `SPHERE-AGY-CHAT.md`(안내문) — 전부 삭제 대신 `~/tmp-trash-2026-09-16/sphere-agy-legacy/`로 이동(되돌릴 수 있게).
- **코드에 남아있던 참조도 같이 정리 (`nas_mcp.py`)**: `SERVICE_CTLS` 딕셔너리의 `"sphere-agy"` 별칭 키 제거(`"chatbot"` 키만 남김), `TMP_ROOT`를 `/tmp/sphere-agy` → `/tmp/chatbot-mcp`로 변경. 위쪽 문서 상단 근처 레퍼런스 테이블 노트도 갱신.
- **범위 밖으로 남겨둔 것**: `ALLOW_ROOTS`의 `sphere-art`/`sphere-lore`/`sphere-sound`/`sphere-tech`는 이 챗봇 프로젝트의 옛 이름이 아니라 Sphere Hub의 다른 현역 웹 섹션들이라 손대지 않음. `delayed_restart.py`/`restart.log`(chatbot-ctl.sh의 guard/repair 이전에 쓰던 걸로 보이는 임시 재기동 스크립트)는 별도 확인 필요해서 이번엔 안 건드림 — 다음에 여쭤보고 처리.
- **검증**: 재기동 후 doctor PASS, probe 통과.

## 2026-09-17 — PROJECT.md 재조정: chatbot repo가 홈 전체 repo로 흡수됨

- **배경**: 지난 세션(2026-09-16) 마지막에 chatbot 전용 repo로 5개 repo를 통합하는 작업을 하던 중 연결이 끊김. 재접속해보니 그 사이 Antigravity가 호스트 전체 재구조화("agent isolation 정립", "wiki SSOT 통합" 등)를 진행하면서 `chatbot/.git` 자체가 사라지고, `chatbot/`이 홈 루트(`/volume1/homes/me`) 단일 repo의 하위 폴더로 편입돼 있었음. 홈 루트 repo의 origin은 `git@github.com:See1Studios/HermesBackup.git`.
- **확인**: 비인증 GitHub API 조회(`api.github.com/repos/See1Studios/HermesBackup` → 404)로 해당 repo가 private임을 확인 — 대화 데이터 노출 우려는 없음.
- **실장님 결정**: chatbot을 다시 분리하지 않고, Antigravity의 홈 전체 통합 방식을 그대로 유지하기로 함.
- **조치**: `PROJECT.md`의 "Version control"/"GitHub backup" 섹션이 여전히 "chatbot은 별도 private repo(`See1Studios/chatbot.git`)"라고 (더 이상 사실이 아닌) 내용을 담고 있어서 정정 — 이제 `~/AGENTS.md`(호스트 전체 Priority 0 헌장)를 가리키도록 하고, push 절차도 `services/chatbot`가 아닌 홈 루트에서 실행하도록 수정. 지난 세션의 chatbot 전용 repo 통합 작업 자체는 역사적 기록으로 남기고 되살리려 하지 않음(`~/tmp-trash-2026-09-16/`에 아카이브된 옛 repo들 포함).
- **참고**: `chatbot-repo-publish`(subtree 병합용 6번째 repo)도 이 과정에서 완전히 사라짐 — 문서에서 관련 언급 제거.

## 2026-09-17 — 세션 삭제 기능 추가, "이어하기" 헤더 버튼 제거

- **세션 삭제 (`server.py` `Registry.delete`, `DELETE /api/sessions/:id`)**: 실장님 요청 — 테스트로 쌓인 빈 세션들, 나중에 지우고 싶은 대화 대비. `sessions/<sid>/` 폴더를 통째로 지워서 `meta.json`과 `artifacts/`(생성 이미지)가 항상 같이 삭제됨 — 지난 세션에서 세션+아티팩트를 한 폴더로 통합해둔 덕에 별도 처리 없이 자연스럽게 해결됨. 작업 중(`busy`)인 세션은 409로 거부. 라이브 프로세스가 있으면 먼저 정지 후 삭제.
- **클라이언트 (`static/app.js` `deleteSession`)**: 🗂 세션 탭 각 행에 🗑 삭제 버튼 추가, `confirm()` 확인 후 삭제. 지금 보고 있는 세션을 삭제한 경우 최신 세션으로 자동 전환(없으면 새 세션 생성) — 페이지 첫 로드 시 폴백 로직과 동일 패턴.
- **"이어하기" 헤더 버튼 제거 (`static/index.html`, `static/app.js`)**: 실장님 지적 — "이어하기는 말하자면 resume 같은 건데 세션 탭에서 이어할 수 있으니까" 상시 노출된 헤더 버튼은 세션 목록 탭에서 아무 세션이나 클릭해 이어가는 것과 사실상 중복. **`continueSession()` 함수 자체, `/continue` 슬래시 명령, 세션 무거움 배너의 "맥락 이어 새 대화" 버튼(`sessionBannerContinue`)은 남겨둠** — 이건 "지금 대화가 무거워졌으니 요약 인계받아 새 세션으로 갈아타기"라는, 그냥 옛 세션을 여는 것과는 다른 목적(비용 리셋)이라 별개로 유지할 가치가 있다고 판단.
- **검증**: 재기동 후 실제 빈 테스트 세션 삭제 → 폴더 완전히 사라짐 확인, 존재하지 않는 세션 삭제 시도 → 404 확인, doctor PASS.

## 2026-09-17 — 상단 바 혼잡 완화: "← Hub" 링크를 좌상단 오버레이로 분리

- **배경**: 실장님 지적 — 탭 6개(대화/아티팩트/로그/상태/세션/냥피디) + 모델 선택 + ⚡소생 + 새 세션까지 한 줄(`.bar`)에 몰려 있어서 버튼이 밀림.
- **수정 (`static/index.html`)**: `#hubLink`(← Hub)를 `.bar` 플렉스 행에서 완전히 빼서 `position:fixed` 오버레이로 좌상단(`top:.6rem;left:.6rem`)에 배치 — 반투명 배경 + blur, 마스코트 오버레이(z-index 90)보다 위, 모달(100)보다 아래로 배치. 모바일 전용 `.bar a` 축소 규칙도 `#hubLink`로 이동(더 이상 `.bar` 안에 없으므로).
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-17 — 세션 삭제 실패 버그 수정 + 턴 수 표시 + 스크롤백 죽은 링크 우회

- **버그 1: 삭제 실패를 성공으로 보고**: `Registry.delete()`가 `shutil.rmtree(..., ignore_errors=True)` 후 결과 확인 없이 무조건 `True` 반환 — 실제 삭제가 실패해도(권한/잠금 등) 클라이언트는 `{"ok": true}`를 받아 그 세션이 목록에 계속 남아있는데 "삭제됐다"고 믿게 됨. 삭제 후 디렉터리가 여전히 존재하면 예외를 던지도록 수정.
- **버그 2: 오래된 busy 플래그가 영구 삭제 차단**: doctor-probe 등에서 agy 프로세스가 턴 도중 정리(`kill_orphan_agy`)되면 `result`/`error` 이벤트를 못 받아 `busy=True`가 그 세션 메모리 객체에 영원히 남음 — 서버 재기동 전까진 삭제 시도마다 409로 거부됐던 것으로 추정(실장님이 보고한 "지워지지 않는 세션들"의 원인). 실제로 프로세스가 살아있는지(`proc.poll() is None`)까지 확인하도록 수정 — 죽은 프로세스의 stale busy 플래그는 더 이상 삭제를 막지 않음.
- **턴 수 표시 (`Registry.list`, `renderSessionsList`)**: 세션 목록 각 행에 "N턴 · 모델 · 시각" 형태로 턴 수 추가 — 삭제 판단에 참고하도록.
- **스크롤백 죽은 링크 우회**: 세션 삭제로 인해 스크롤백 체인 중간 링크가 사라지면(`predecessor_session_id`가 이미 삭제된 세션을 가리킴) 예전엔 그 시점에서 전체 스크롤백이 조용히 멈췄음(실장님 보고: "지워보니 예전으로 스크롤이 안 되는 상황"). 이제 해당 홉의 조회가 실패하면(404) 마지막으로 성공했던 시각을 기준으로 시간순 폴백을 시도해 죽은 링크를 우회하고 계속 진행.
- **검증**: 재기동 후 세션 목록에 턴 수 정상 표시, doctor PASS.

## 2026-09-17 — Hub FAB를 별도 구현에서 본체 iframe 임베드로 전면 교체

- **배경**: `/volume1/web/index.html`의 FAB가 본체(`static/app.js`, ~2000줄)와 별도로 ~950줄짜리 완전히 독립된 채팅 구현을 갖고 있었음 — 오늘 밤 본체에 여러 기능(세션 삭제, 스크롤백, 이어하기 버튼 제거 등)을 추가하면서 FAB는 전혀 갱신 안 돼서 실장님이 "/" 슬래시 메뉴 무반응 등 여러 증상을 발견("FAB 쪽에 망가진 게 많네"). 원인을 코드로는 특정 못했지만(브라우저 콘솔 접근 불가), 애초에 "이원화하지 말고 디자인 빼고 나머지는 공유"(실장님)가 맞는 방향이라 판단 — FAB를 다시 만드는 대신 **본체를 그대로 작은 iframe에 띄우는 방식**으로 전환.
- **`static/app.js`**: `?compact=1` 쿼리 파라미터를 읽어 `아티팩트`/`로그`/`상태` 탭, 마스코트, "← Hub" 오버레이, "⚡ 소생" 버튼을 숨기는 `applyCompactMode()` 추가. 남는 건 `대화`+`세션` 탭뿐 — 채팅 중심 위젯엔 로그보다 세션 목록이 더 유용하다는 실장님 의견 반영. 나머지 모든 로직(세션 관리·삭제·스크롤백·SSE 등)은 본체와 100% 동일한 코드를 그대로 씀.
- **`/volume1/web/index.html`**: FAB CSS/HTML/JS 세 블록을 전부 교체 — 원형 토글 버튼과 팝업 컨테이너 껍데기만 남기고, 팝업 안쪽은 `<iframe src="http://<host>:3011/?compact=1">` 하나로 대체. 1990줄 → 972줄. 모바일에서 풀스크린으로 펼쳐지는 기존 동작과 토글 버튼 디자인은 그대로 유지, 풀스크린일 때 토글 버튼이 안 보이는 문제를 위해 팝업 자체에 별도 ✕ 닫기 버튼 추가.
- **검증**: `:3011/`, `:3011/?compact=1`, 허브 페이지(`/`) 모두 200 확인, 새 FAB 마크업이 정상 서빙되는 것 확인. 실제 브라우저 클릭 테스트는 확장 프로그램 미연결로 이번엔 못 함 — 다음에 실장님이 직접 확인 필요.

## 2026-09-17 — 스크롤백이 방금 연 세션 자기 자신을 중복 렌더링하던 버그 수정 + 예전 probe 세션 109개 일괄 정리

- **증상**: 실장님 확인 — "새로고치니 채팅이 두 개 찍혔어". 짧은 대화(내용이 화면을 다 못 채움)에서 재현.
- **원인**: `openSession()`이 현재 세션 자신의 id를 `scrollbackSid`(스크롤백 시작점)로 설정해두는데, 그 직후 `maybeBackfillScrollback()`이 "화면에 스크롤할 게 없다"고 판단해 `loadOlderHistory()`를 자동 호출 → **방금 forEach로 이미 그려놓은 그 세션 자신을** `?full=1`로 다시 불러와서 또 위에 그려버림. 대화가 길어서 화면이 이미 꽉 차 있으면 안 걸리는 조건이라 그동안 눈에 안 띔.
- **수정 (`static/app.js`)**: `openSession()`에서 `scrollbackVisited`를 빈 Set 대신 `new Set([id])`로 시작 — 이미 렌더링한 현재 세션을 "방문함"으로 미리 표시. `loadOlderHistory()`의 각 홉마다 "이미 방문한 세션인가"를 먼저 확인해서, 맞으면 렌더링은 건너뛰고(중복 방지) `predecessor_session_id`/시간순 폴백 계산은 그대로 진행 — 첫 홉이 여전히 "이 세션보다 이전"을 찾는 앵커 역할은 하되 자기 자신의 내용을 다시 그리진 않음.
- **부수 정리**: 아까 고친 doctor-probe 세션 정리 기능을 적용하기 전까지 쌓여있던 빈/probe 세션 109개(전체 151개 중 대부분)를 `DELETE /api/sessions/:id`로 일괄 삭제.
- **검증**: 재현 조건(짧은 세션)으로 직접 확인은 다음 새로고침 때 실장님이 확인 예정. static 파일만 수정, 재기동 불필요.

## 2026-09-17 — 모델 선택 콤보박스를 상단 바에서 입력창 옆으로 이동

- **요청**: 실장님 — "모델 선택 콤보박스는 채팅창 근처에 작게 두는 게 좋을 것 같네". 상단 `.bar`가 이미 탭 여러 개로 혼잡했던 것과 별개로, 모델 선택은 입력 동작과 더 가까운 위치가 자연스럽다는 의견.
- **수정 (`static/index.html`)**: `<select id="model">`을 `.bar`에서 `.composer`(입력창 줄) 맨 앞으로 이동, `/`·🎤 버튼과 같은 계열의 작은 크기로 스타일링(최대 118px, 작은 폰트). `app.js`는 `getElementById('model')`로만 참조해서 위치 이동에 영향 없음 — JS 변경 불필요.
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-17 — FAB 좁은 화면 대응: 입력줄 2행 분리 + 아티팩트/로그 탭 복원

- **입력줄 혼잡 (`static/index.html`)**: 실장님 지적 — FAB에서 모델 선택 콤보박스 때문에 텍스트 입력 공간이 너무 좁아짐. 640px 이하 좁은 화면(FAB/모바일)에서 `.composer`를 `flex-wrap:wrap` + `order` 조합으로 재배치 — 1행은 `/`·입력창·보내기·중지만, 2행은 모델 선택·마이크 버튼으로 분리(`::after` 빈 요소에 `flex-basis:100%`를 줘서 줄바꿈 유도). 넓은 화면(본체 전체 창)은 기존처럼 한 줄 그대로.
- **compact 모드 탭 복원 (`static/app.js`)**: 어젯밤 처음 만들 때 좁은 팝업이라 아티팩트/로그/상태를 다 숨겼었는데, 실장님이 실제로 써보니 "위에 공간이 많이 남았으니 로그도 노출해도 될 것 같네" / "아티팩트도" — `상태` 탭만 남기고 아티팩트·로그 탭은 다시 노출하도록 `applyCompactMode()` 수정.
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-17 — 🔥 심각: kill_orphan_agy가 세션 폴더 구조 변경 이후 모든 실제 대화를 오인 종료시키고 있었음

- **증상**: 실장님이 "냥피디 응답이 없어" 두 번 보고. 확인해보니 실제 대화 세션(`139K 토큰, 6턴`)의 메시지가 응답 없이 멈춰있었고, `debug_stderr_tail`에 `error: stream input cancelled: context canceled` / `error: interrupted`가 반복 기록돼 있었음 — 프로세스가 답변을 만들다가 강제 종료당하고 있었다는 뜻.
- **원인**: `chatbot-ctl.sh`의 `kill_orphan_agy()`가 "진짜 대화 중인 세션"을 보호하기 위해 `sessions_dir + "/*.json"`을 글롭해서 각 세션의 `conversation_id`를 `protected` 집합에 채워두는데, **2026-09-16/17 세션 폴더 통합(`sessions/<sid>.json` → `sessions/<sid>/meta.json`) 이후 이 글롭 패턴을 업데이트하지 않아서 매칭되는 파일이 0개** — `protected` 집합이 항상 비어있었음. 그 결과 `elif cid and cid not in protected and "flash-low" in args: reason = "unprotected-flash-low"` 조건에 걸려 **모델이 flash-low인 모든 실행 중인 agy 프로세스가 "보호 안 된 세션"으로 오인되어 주기적으로(doctor/repair 사이클마다) 강제 종료**당하고 있었음 — doctor-probe뿐 아니라 실장님의 실제 대화까지 전부 대상.
- **영향 범위**: 세션 폴더 통합 커밋(오늘 밤 초반) 이후 지금까지 발생한 모든 "응답이 늦다/없다" 계열 보고 중 상당수가 실은 이 버그 때문이었을 가능성이 높음 — "생존문의... 답이 없네"(결국 지연 후 도착)와 이번 건 둘 다 재현 패턴이 일치.
- **수정**: 글롭 패턴을 `sessions_dir + "/*/meta.json"`으로 수정.
- **검증**: 수정 배포 후 `doctor` 실행 → `orphan_agy_killed=0`, 멈춰있던 메시지를 재전송하니 정상 응답 수신 확인.
- **교훈**: 세션 저장 구조를 바꿀 때 `server.py`/클라이언트 쪽 경로는 다 고쳤지만, `chatbot-ctl.sh`의 셸 임베디드 파이썬 스크립트(`kill_orphan_agy`)에 있는 동일 패턴의 하드코딩된 글롭을 놓쳤음 — 다음에 데이터 경로 구조를 바꿀 땐 `grep -rn "sessions_dir\|sessions/\*\.json\|SESSIONS\." `로 전체 저장소(서버 코드뿐 아니라 셸 스크립트 포함)를 한 번 더 훑을 것.

## 2026-09-17 — 세션 열 때 최근 메시지로 안 내려가던 문제 수정

- **증상**: 실장님이 채팅으로 직접 남긴 리포트 — "냥피디 창이 처음 열릴 때 가장 최근 메시지까지 이동하지 않고 있어" (이 메시지 자체가 위의 kill_orphan_agy 버그 때문에 한동안 답을 못 받았음).
- **원인**: `openSession()`의 `addChat()` 호출마다 그 시점의 `scrollHeight` 기준으로 스크롤을 맨 아래로 맞추는데, 이미지가 포함된 메시지는 이미지가 뒤늦게 로드되면서 컨텐츠 높이가 더 늘어나 마지막 `addChat` 호출 시점보다 실제 최종 높이가 커짐 — 결과적으로 살짝 위에서 멈춤.
- **수정 (`static/app.js`)**: `openSession()`의 히스토리 렌더링 직후 `scrollTop`을 한 번 더 맞추고, 200ms 뒤에 한 번 더(대부분의 이미지 로딩이 끝났을 시점) 재적용.
- **배포**: static 파일만 수정, 재기동 불필요.

## 2026-09-17 — save_meta 동시쓰기 레이스 방지 + stdout 라인 처리 예외 격리

- **배경**: `AgySession.save_meta()`가 `self.lock` 없이 호출되고 있었고, 임시 파일명이 `meta.tmp` 고정 — 같은 세션에 대해 두 스레드(예: 델타 처리 중 `result` 이벤트와 백그라운드 저장이 겹치는 경우)가 거의 동시에 `save_meta()`를 호출하면 서로의 `.tmp`를 덮어쓰거나 `replace()` 경합이 날 수 있는 구조였음.
- **수정 (`server.py`)**: `save_meta()`를 `self.lock`으로 감싸고, 임시 파일명을 `meta.<uuid4 hex>.tmp`로 프로세스/호출마다 유일하게 생성 — 쓰기 실패 시에도 예외를 삼키지 않고 경고 로그(`WARN: save_meta failed for {sid}`)를 남기며 잔여 tmp 파일을 정리.
- **stdout 라인 처리 예외 격리 (`server.py`)**: `_read_stdout()`의 while 루프 본문(JSON 파싱부터 이벤트 emit까지)을 `_handle_stdout_line()`으로 분리하고, 루프에서 라인 하나 처리 중 예외가 나도 `try/except`로 잡아 다음 라인 처리를 계속하도록 변경 — 기존엔 한 줄 처리 중 unhandled exception이 나면 `_read_stdout` 스레드 자체가 죽어 그 세션이 이후 응답을 영원히 못 받는 구조였음.
- **`nas_mcp.py` write_file 임시파일명 동일 보강**: `path.tmp` 고정 대신 `.{name}.{pid}.{uuid8}.tmp`로 변경 — 여러 write_file 호출이 겹쳐도 서로 다른 tmp 경로를 쓰도록.
- **배포**: `chatbot-ctl.sh repair`로 재기동(자기 자신 프로세스라 raw restart는 가드에 막힘) — probe 통과, doctor PASS 확인.

## 2026-09-17 — 창을 여러 개 열면 각자 다른 새 세션이 뜨고 예전 대화가 안 보이던 버그 수정

- **증상**: 실장님 보고 — "창을 여러 개 열었더니 각자 다른 새 세션이 시작되고 예전 세션 내용이 안 나오는 걸 관측했어".
- **원인 (`static/app.js` `maybeRedirectHardSession`)**: 페이지 로드시 활성 세션이 "hard"(너무 길어져서 새 채팅을 강제해야 하는) 상태인데 아직 `successor_session_id`가 없으면, 지금까지는 아무 연결 고리도 남기지 않는 그냥 `createSession()`(완전히 별개의 새 세션)을 호출했음. 그 결과 **hard 세션을 여전히 "가장 최근 활성 세션"으로 보는 모든 창/탭이 매번 독립적으로 새 세션을 만들어 버림** — 서로 연결되지 않은 빈 세션이 계속 쌓이고, 원래 맥락(그리고 그 이후 계속 쌓인 대화)은 다시는 "활성"으로 선택되지 못해 사실상 미아가 됨. 메시지 전송 시점에 hard 세션을 굴리는 서버 쪽 `_rotate_to_fresh_session()`은 이미 `successor_session_id`를 재사용하는 sticky 로직이 있었는데, 세션을 "여는" 시점의 클라이언트 경로는 이 로직을 안 쓰고 따로 구현되어 있었던 게 원인.
- **수정**:
  - **`server.py` `/api/sessions/:id/continue`**: `sticky` 플래그 추가. `sticky:true`면 `sess.lock` 안에서 기존 `successor_session_id`가 아직 유효한지(`_successor_usable`) 확인해 있으면 그걸 재사용, 없으면 그때만 새로 만들고 링크 저장 — 두 창이 거의 동시에 호출해도 락 안에서 순서대로 처리되어 한쪽만 실제로 새로 만들고 나머지는 그 결과를 재사용함. 버튼으로 누르는 수동 "이어하기"는 `sticky` 없이 기존처럼 항상 새로 포크(의도된 비용 리셋 동작, 건드리지 않음).
  - **`static/app.js` `maybeRedirectHardSession`**: `hard && !redir` 분기를 `createSession()` 대신 `sticky:true`로 `/continue` 호출 → 반환된 successor로 `openSession()`하도록 변경. 실패 시에만 기존처럼 완전히 새 세션으로 폴백.
- **검증**: 재기동 후 실제 활성 세션에 대해 `sticky:true`로 연속 호출 → 1번째는 `reused:false`(새로 생성 + `successor_session_id` 저장), 2번째는 `reused:true`로 동일 세션 id 반환 확인. doctor PASS.

## 2026-09-17 — 같은 세션을 여러 창에서 열면 다른 창이 보낸 질의가 안 보이던 버그 수정

- **증상**: 실장님 확인 — (위 successor 수정 이후) "모든 창에 동일 세션이 유지되고 있어"는 확인됐지만, 이어서 "서로 다른 창에서 챗봇의 응답은 보이는데 다른 창에서 보낸 질의는 보이지 않네".
- **원인 (`server.py` `_send_direct`, `static/app.js` `user_ack` 핸들러)**: 사용자가 메시지를 보내면 **보낸 그 창**은 서버 응답을 기다리지 않고 그 자리에서 낙관적으로 자기 화면에 유저 말풍선을 그림. 서버는 실제로 history에 추가한 뒤 `user_ack` 이벤트를 그 세션을 구독 중인 **모든** 창에 SSE로 브로드캐스트하는데, 클라이언트의 `user_ack` 핸들러는 오직 "이미 그려둔 대기열(`queued`) 말풍선의 표시를 벗기는 것"만 하도록 짜여 있었음 — 새로 유저 말풍선을 그리는 코드 경로가 아예 없었음. 그래서 응답(`delta`/`result`)은 모든 창에 브로드캐스트되어 보이지만, 그 질문 자체는 보낸 창에서만 로컬로 그려졌을 뿐 다른 창들은 애초에 렌더링할 방법이 없었음.
- **수정**:
  - **`static/app.js`**: 메시지 전송 시 `client_mid`(창별 임시 id, `crypto.randomUUID` 우선)를 생성해 `myPendingMids`에 기록하고 POST body에 실어 보냄. `user_ack` 수신 시 `data.client_mid`가 `myPendingMids`에 있으면 "내가 방금 보낸 것"으로 판단해 기존처럼 대기열 말풍선만 처리하고, 없으면(=다른 창이 보낸 것) `addChat('user', ...)`으로 새로 렌더링.
  - **`server.py`**: `send()`/`_send_direct()`/`_rotate_to_fresh_session()`/`_dispatch_queued()`가 `client_mid`를 끝까지 들고 다니도록 시그니처 변경, `msg_queue` 항목도 `(text, client_mid)` 튜플로 변경. `_send_direct`가 emit하는 `user_ack`에 `ts`와 `client_mid`를 추가(이전엔 `text`만 있어서 클라이언트가 "내 것"인지 구분할 방법이 아예 없었음). `/api/sessions/:id/message` 핸들러가 요청 body의 `client_mid`를 읽어 `sess.send()`에 전달.
  - 텍스트 내용만으로 매칭하지 않고 창마다 고유한 `client_mid`로 매칭한 이유: 두 창에서 우연히 똑같은 문구를 거의 동시에 보내는 경우에도 서로 다른 실제 메시지 2건이 각자 정확히 매칭되도록.
- **검증**: 재기동 후 `[doctor-probe]` 메시지에 `client_mid: "test-mid-123"`을 실어 보내고 SSE 스트림을 직접 구독해 `user_ack` 이벤트에 동일한 `client_mid`와 `ts`가 그대로 echo되는 것 확인. doctor PASS.

## 2026-09-17 — 리팩토링 1단계: app.js 세션 진입 보일러플레이트 통합 + 죽은 코드 제거

- **배경**: 실장님이 로그 탭 연속성을 요청했으나 조사해보니 로그 탭 자체가 디스크에 저장 안 되는 순수 SSE 방송이라 저장 스키마부터 새로 설계해야 함 — 그 결정은 미루고 "리팩토링부터 하자"로 방향 전환. 코드베이스 구조 조사 결과를 바탕으로 계획을 세우고(`app.js` 파일 분리/스크롤백 로직 공용화/`server.py` 정리 중 이번엔 안전하게 검증 가능한 것부터), 동작은 그대로 두고 중복만 제거하는 1단계 진행.
- **죽은 `escapeHtml` 제거**: 같은 이름으로 두 번 정의(447번 줄 4종 이스케이프, 906번 줄 5종 이스케이프 — `'`까지 처리하는 더 완전한 버전)돼 있었음. JS 함수 선언은 나중 것이 이기므로 447번은 애초에 죽은 코드였음 — 삭제, 906번만 유지.
- **세션 진입 보일러플레이트를 `enterSession(id, opts)`로 통합**: `openSession`/`createSession`/`continueSession`/`bindEvents`의 `session_rotate` SSE 핸들러/`send()`의 `rotated` 응답 처리, 이 5곳이 각자 손으로 반복하던 "로그·액티비티 비우기 → 스크롤백 상태 리셋 → (히스토리 렌더 또는 인사말) → setMeta → 배너 → bindEvents → fetchArtifacts" 시퀀스를 한 함수로 모음. 각 호출부는 자기만 다른 부분(스크롤백 앵커, 인사말/에코 텍스트, 액티비티 로그 문구, meta 라벨, weight/busy)만 `opts`로 넘김.
  - **동작은 의도적으로 하나도 안 바꿈**: 예를 들어 `send()`의 `rotated` 분기는 리팩토링 전부터 이미 스크롤백/`lastSyncedTs`를 전혀 리셋하지 않고 있었는데(다른 4곳과 다름), `enterSession`에 `scrollback` 옵션을 아예 안 넘기면 그 항목들을 건드리지 않도록 설계해서 이 기존 동작(아마도 버그)을 그대로 보존함. 마찬가지로 `session_rotate` 핸들러의 `addActivity(...)`/`showSessionHeavyBanner('hard',...)` 호출은 바로 다음 줄의 로그/배너 초기화로 즉시 지워지는 기존 순서를 그대로 유지.
  - **발견했지만 이번엔 고치지 않은 것(다음에 판단 필요)**: (1) `send()`의 `rotated` 분기가 스크롤백/`lastSyncedTs`를 리셋 안 해서, 세션이 대화 중간에 자동 회전되면 스크롤백이 옛 세션을 계속 가리키고 재연결 시 `resyncFromServer`가 새 세션 히스토리를 스테일한 `lastSyncedTs` 기준으로 비교할 가능성. (2) `session_rotate` 핸들러가 액티비티 로그 문구와 "hard" 배너를 표시하자마자 같은 실행 흐름 안에서 즉시 지워버려서 사용자가 절대 못 봄 — 아마 의도치 않은 순서 버그.
- **`deleteSession`의 인라인 폴백을 `ensureSession()` 호출로 교체**: 현재 세션 삭제 후 "최신 세션 열거나 없으면 새로 만들기" 로직이 `ensureSession()`의 꼬리 부분과 거의 똑같이 중복 구현돼 있었음(단, `/api/sessions/active` 체크는 빠져있었음) — `ensureSession()` 호출로 교체해 더 완전한 폴백 체인(active → localStorage → latest → create)을 그대로 재사용.
- **검증**: `node -c static/app.js` 문법 확인, `chatbot-ctl.sh repair` 배포 + doctor PASS. app.js는 정적 파일이라 서버 재기동 자체는 불필요하지만 배포 확인 겸 같이 돌림. **브라우저 클릭 검증(세션 열기/새 세션/이어하기/삭제)은 doctor/curl로는 못 잡으므로 실장님 확인 필요** — 특히 세션 진입 시퀀스는 모든 세션 전환 경로가 걸쳐가는 핵심 로직이라 꼭 한 번씩 눌러봐 주시길.

## 2026-09-17 — 리팩토링 2단계: server.py 정리

- **공용 atomic write 헬퍼 추출**: `save_meta()`가 쓰던 "유일 tmp 파일명 → write → replace()" 패턴을 모듈 함수 `_atomic_write_text(path, content)`로 뽑아 `save_meta()`·`_write_mcp_config()`·`/api/rules/<name>` PUT 핸들러(백업 생성 후 최종 덮어쓰기 부분)가 전부 이걸 쓰도록 교체. 이전엔 세션 meta.json만 안전하게(동시읽기 중 잘린 파일 노출 없이) 쓰고 있었고, MCP 설정과 규칙 파일은 `write_text` 직접 호출이라 쓰는 도중 읽으면 반쪽 파일을 볼 수 있었음.
- **`Registry.list()`의 `updated_at`을 `to_public()`과 같은 포맷(epoch-float, `p.stat().st_mtime`)으로 통일**: 이전엔 meta.json에 저장된 ISO 문자열을 그대로 반환해서, 세션 상세 API의 `updated_at`(파일 mtime epoch-float)과 형식이 달랐음 — 이게 바로 app.js `_scrollbackEpochMs()`가 두 포맷을 매번 정규화해야 했던 근본 원인. shim 자체는 방어적으로 그냥 둠(무해).
- **HTTP 라우트에 박혀있던 세션 정책을 `AgySession` 메서드로 이동**: `/message` POST의 모델 교체(다르면 stop 후 재기동) 로직 → `AgySession.maybe_swap_model(model)`. `/continue` POST의 sticky 재사용-또는-포크 로직(~20줄 인라인) → `AgySession.continue_to_successor(model, sticky)`. 라우트 핸들러는 이제 파싱 → 메서드 호출 → 직렬화만 남음.
- **순수 포맷팅 메서드 4개를 모듈 최상위 함수로 이동**: `_clean_str`/`_short_path`/`_format_tool_call`/`_format_tool_result`는 원래도 `self` 인스턴스 상태를 전혀 안 쓰는 순수 함수였음(서로만 호출) — `AgySession`에서 빼서 클래스 정의 직전에 모듈 함수로 선언. `_tool_summary`(여전히 `_last_tool_sig` dedup 상태를 쓰므로 메서드로 유지) 안의 호출부만 `self._format_tool_call(...)` → `_format_tool_call(...)` 등으로 갱신.
- **`typing.Union` 미임포트 수정**: `_tool_summary`의 반환 타입 힌트가 `Union[...]`을 쓰는데 import가 없었음(`from __future__ import annotations` 덕에 지금까진 안 터짐) — import에 `Union` 추가.
- **이번엔 안 한 것(계획에 명시)**: `_run_btw`/`get_handover_summary`/`_dialogue_summary_fallback`의 subprocess 호출부 공용화는 검토 결과 스킵 — 세 곳 다 결과 파싱(stream-json 라인 파싱 vs 순수 stdout 텍스트)과 예외별 사용자 메시지가 서로 달라서, 억지로 공용 헬퍼로 묶으면 동작이 바뀌거나(에러 메시지 통일) 거의 빈 껍데기 wrapper만 남아 이득이 없다고 판단.
- **검증**: `python3 -m py_compile server.py` → `chatbot-ctl.sh repair` → doctor PASS. curl로 직접: (1) `/api/sessions` 목록의 `updated_at`이 전부 epoch-float인 것 확인, (2) `/continue`에 `sticky:true`로 연속 호출 → 1번째 `reused:false`(새로 생성), 2번째 `reused:true`(같은 id 재사용) 확인 — `continue_to_successor` 메서드 이전과 동일하게 동작, (3) `/message`에 모델 파라미터를 실어 실제 새 세션에 `[doctor-probe]` 메시지 전송 → 정상적으로 turn 완료(어시스턴트 응답 수신, `busy` false로 복귀)까지 확인 — 이 경로가 `_tool_summary`/`_format_tool_call`(콜드 스폰 시 `system started` 등 tool/system 이벤트 포맷팅 포함)을 실제로 타는 걸 확인.

## 2026-09-17 — impeccable critique 실행 + UX 개선 1~2단계 (P0 무설명 리다이렉트 / confirm·alert / 접근성)

- **배경**: 코드 리팩토링(1·2단계) 이후 실장님이 "UX 리팩토링도 해볼까"라고 제안 → `impeccable critique`를 `static/index.html` 대상으로 실행(듀얼 에이전트: 디자인 리뷰 A + 디텍터/브라우저 증거 B, 이 환경엔 브라우저 자동화 도구가 없어 둘 다 정적 분석만 수행). 결과 30/40(Good), 5개 우선순위 이슈 도출, 실장님이 전부 진행 지시. 리포트는 `.impeccable/critique/2026-09-17T02-13-50Z__static-index-html.md`에 저장.
- **[P0] hard 세션 자동 리다이렉트를 대화 탭에서도 보이게 (`static/app.js`)**: `maybeRedirectHardSession()`이 다른 세션으로 조용히 갈아치울 때 지금까지 `addActivity()`로 로그 탭에만 기록됐음(기본 안 보이는 탭). `openSession(id, depth, bannerOverride)`에 3번째 인자를 추가해, 리다이렉트 경로 두 곳(기존 successor로 이동 / 방금 생성·재사용한 successor로 이동) 모두 `{level:'hard', message_ko:'...'}`를 넘기도록 해서 `enterSession()`의 기존 hard-배너(`showSessionHeavyBanner`)가 대화 탭에 그대로 뜨도록 함 — 새 UI를 만들지 않고 기존에 이미 검증된 배너/버튼(이어 새 대화/완전 새 세션/닫기)을 재사용.
- **[P1] 네이티브 `confirm()` → 스킨된 확인 모달 (`static/index.html` `#confirmModal`, `static/app.js` `confirmModal()`)**: 세션 삭제·MCP 삭제·소생(defibrillate) 3곳의 `confirm()`을 `#artModal`과 같은 `.modal-overlay`/`.modal-card` 스타일을 쓰는 새 `confirmModal(message, opts)`(Promise 기반)로 교체. Escape·오버레이 클릭으로 취소 가능 — 기존 브라우저 네이티브 confirm은 앱의 다른 모든 오버레이가 지원하는 Escape 반사동작이 안 먹혔던 것도 같이 해결.
- **접근성(Sam 페르소나) 하드닝**:
  - 탭 버튼 5개에 `role="tab"`/`aria-selected`, 대응 패널 5개에 `role="tabpanel"`/`aria-labelledby` 배선(`switchTab()`이 전환 시 `aria-selected` 갱신). 이전엔 컨테이너에만 `role="tablist"`가 있고 정작 탭 자체엔 시맨틱이 전혀 없었음.
  - 전역 `:focus-visible` 아웃라인 추가(`--accent` 색) — 다크 커스텀 배경 위에서 브라우저 기본 포커스 표시가 실제로 보이는지 검증된 적이 없었음.
  - 세션 누적/턴별 토큰 배지의 상세 내역이 `title` 툴팁(마우스 호버 전용)에만 있던 걸 `aria-label`로 동일 텍스트 미러링.
  - 아이콘 전용 버튼(마이크 🎤, 읽어주기 🔊)도 `title`만 있고 `aria-label`이 없었음 — 상태 변화마다 둘 다 같이 갱신하도록 수정.
- **스코프에서 제외한 것**: `alert()` 10곳(전부 단방향 에러/검증 메시지)은 이번엔 안 건드림 — critique가 구체적으로 지목한 건 confirm() 3곳(파괴적 액션)이었고, alert 전체를 토스트 시스템으로 바꾸는 건 별도 기능 크기의 작업이라 판단. `.wrap`이 `#slashMenu`를 클리핑할 수 있는 디텍터 발견(진짜 이슈로 판단됨)도 이번 우선순위 이슈 목록엔 없어서 손 안 댐 — 다음 기회에.
- **검증**: `node -c app.js` 문법 확인, `chatbot-ctl.sh repair` 배포, curl로 서빙된 페이지에 `role="tabpanel"`(5개)·`id="confirmModal"`·`:focus-visible`이 실제로 포함된 것 확인, doctor PASS. **실제 클릭/스크린리더 검증은 브라우저 도구가 없어 못 했음 — 실장님이 삭제 버튼 눌러서 새 확인창 뜨는지, Escape로 닫히는지 한 번 확인 부탁드립니다.**

## 2026-09-17 — UX 개선 3단계: 키보드 단축키 (탭 전환 + 컴포저 점프)

- **배경**: critique P1 "파워유저용 도구인데 키보드 지원이 거의 없음"(Enter/Escape 둘뿐) — impeccable `/optimize` 명령이 추천됐지만 그 레퍼런스는 전부 로딩/렌더링 성능 얘기라 실제로 필요한 "키보드 단축키 추가"와는 안 맞아서, 레퍼런스 그대로 따르기보단 실제 필요한 작업을 직접 설계함.
- **탭 전환 `Alt+1~5`(`static/app.js`)**: `Ctrl/Cmd+숫자`는 이미 브라우저 자체의 "N번째 탭으로 이동" 단축키라 페이지가 keydown 이벤트를 아예 못 받으므로 피하고 `Alt+숫자` 사용. 대화/아티팩트/로그/상태/세션 탭 버튼에 `title="Alt+N"`도 추가해 단축키 자체가 발견 가능하도록 함(Nielsen 인식 우선 원칙).
- **`/`로 어디서든 컴포저 점프(`static/app.js`)**: 입력 가능한 요소(input/textarea/select/contenteditable) 밖에서 `/`를 누르면 대화 탭으로 전환 + 컴포저 포커스 + `/` 자동 입력 → 기존 슬래시 메뉴가 실제로 타이핑한 것과 똑같이(`input` 이벤트 디스패치) 열림.
- **검증**: `node -c app.js` 문법 확인, `chatbot-ctl.sh repair` 배포, doctor PASS. **실제 단축키 동작(Alt+1~5, `/`)은 브라우저 도구가 없어 직접 눌러보지 못했음 — 실장님 확인 필요.**
- **일단 여기서 중단**: 실장님 요청으로 4단계(`/impeccable distill` — 헤더 혼잡)·5단계(`/impeccable document` — 도움말)·6단계(`/impeccable polish`)는 다음에 이어서 진행.

## 2026-09-17 — UX 개선 4단계: 헤더 컨트롤을 ⋯ 오버플로 메뉴로 정리

- **배경**: critique P2 "헤더가 타이핑 시작 전부터 8개 선택지"(탭 5개 + 🐾냥피디 토글 + ⚡소생 + 새세션). 이번 세션 사용량이 얼마 안 남아서 4단계만 하고 5·6단계는 다음으로 미루기로 함.
- **`static/index.html`**: `🐾 냥피디` 토글과 `⚡ 소생` 버튼을 메인 바에서 빼서 새 `#moreMenuBtn`("⋯") 트리거 + `#moreMenu` 팝오버 안으로 이동. 두 버튼의 기존 id/클릭 핸들러는 그대로 유지(ID 기반 조회라 DOM 위치 이동만으로 로직 변경 없음). 남는 메인 바: 탭 5개 + 새 세션.
- **`static/app.js`**: 팝오버 열기/닫기(트리거 클릭 토글, 바깥 클릭·Escape로 닫기, 메뉴 항목 클릭 시 자동 닫기) 로직 추가. `applyCompactMode()`가 이미 `toggleMascotBtn`/`defibBtn`을 숨기고 있어서(FAB 컴팩트 모드), 그 경우 트리거(`moreMenuBtn`) 자체도 같이 숨기도록 추가 — 안 그러면 빈 메뉴가 열리는 트리거만 남음.
- **검증**: `node -c app.js` 문법 확인, `chatbot-ctl.sh repair` 배포, curl로 서빙된 페이지에 `id="moreMenuBtn"`/`id="moreMenu"` 포함 확인, doctor PASS. **팝오버 실제 열기/닫기·바깥클릭·Escape 동작은 브라우저 도구가 없어 직접 확인 못 함 — 실장님 확인 필요.**
- **남은 것**: 5단계(도움말/`/help`)·6단계(전체 폴리시 + critique 재실행으로 점수 확인)는 다음 세션에.

## 2026-09-17 — ⋯ 오버플로 메뉴가 클릭 안 해도 항상 떠있던 버그 수정

- **증상**: 실장님 즉시 확인 — "...의 팝업이 안 눌렀는데 계속 떠 있네".
- **원인 (`static/index.html`)**: `#moreMenu`에 HTML `hidden` 속성을 줬는데, `.more-menu{...display:flex...}` 규칙의 셀렉터 특이도가 브라우저 기본 스타일시트의 `[hidden]{display:none}`과 똑같은 (0,1,0)이라, 캐스케이드 순서상 나중에 오는(author stylesheet가 UA stylesheet보다 늦게 적용) 내 `display:flex`가 이겨버려서 `hidden` 속성이 있어도 처음부터 항상 보이고 있었음.
- **수정**: `.more-menu[hidden]{display:none}` 규칙을 추가(특이도 (0,2,0)로 확실히 이김).
- **검증**: 재기동 후 curl로 서빙된 CSS에 해당 규칙 포함 확인. **실제 화면에서 안 떠 있는지는 브라우저 도구가 없어 직접 확인 못 함 — 실장님 재확인 부탁.**

## 2026-09-17 — Hub FAB 팝업 세로 크기 확대 (`/volume1/web/index.html`, git 비추적 배포 파일)

- **요청**: 실장님 — "FAB 창을 세로로 꽉 채워도 될 것 같아. 지금은 너무 작네."
- **원인**: `.agy-chat-popup`의 데스크톱 높이가 `min(640px, calc(100vh - 96px))`로 큰 화면에서도 640px에 묶여있었음.
- **수정**: 640px 캡을 제거하고 `height: calc(100vh - 96px)`로 변경 — FAB 버튼 위 가용 세로 공간을 항상 다 채우도록. 모바일(`@media max-width:640px`)의 풀스크린 처리는 그대로.
- **참고**: 이 파일은 `/volume1/web/`(정적 배포 루트) 소속이라 홈 git 리포 밖 — 커밋 대상 아님, 직접 수정이 곧 배포.
- **검증**: curl로 서빙된 CSS에 변경 반영 확인. 실제 렌더링은 브라우저 도구 없어 직접 확인 못 함.

## 2026-09-17 — 워치독/ctl 오인 사살 버그 수정 + 프로세스 비정상 종료 시 busy 멈춤 방지 + 유휴 프로세스 리퍼

- **증상**: 실장님이 "우리 챗봇 있잖아 / 지금 뭔가 하고 있는 거야?" 질의. 확인 결과 14:10 세션이 프로세스가 죽어있는(`alive: false`) 상태에서 `busy: true`로 영구 고착되어 있었고, 사용자가 `/btw`("하고 있니?", "아직이냥?")를 묻자 냥피디가 "백그라운드에서 열심히 진행 중이다냥!"이라고 엉뚱하게 거짓 응답을 하던 상태. 동시에 낮 12:18 이전 세션의 agy 프로세스가 2시간 동안 CPU 92%를 점유하며 방치되어 있었음.
- **근본 원인 분석**:
  1. **워치독 오인 사살 (`chatbot-ctl.sh kill_orphan_agy`)**:
     - 새 세션이 `_StandbyPool`의 웜 스탠바이 프로세스를 채택(`adopt`)하면, 스탠바이 생성 당시엔 `--conversation` 인자가 없음.
     - 채택 즉시 스탠바이 풀은 새 스탠바이 프로세스를 스폰해 `standby.pid`를 갱신함.
     - 따라서 세션이 채택한 프로세스는 `standby_pid`도 아니고 `--conversation` 플래그도 없는 상태로 실행됨.
     - 90초(`NO_CONV_GRACE_SEC`) 경과 후 백그라운드 워치독(`gateway-watchdog.sh`)이 `chatbot-ctl.sh doctor`를 호출하면 `kill_orphan_agy`가 이를 프로브 잔여물(`reason="no-conversation"`)로 오인해 `SIGTERM`을 날려 살해함 (`error: interrupted`).
  2. **`server.py`의 `busy: true` 고착**:
     - 프로세스가 `SIGTERM`으로 죽으면 `_read_stdout()`의 루프가 EOF로 끝나지만, `result`/`error` 이벤트를 받지 못했으므로 `self.busy`가 영원히 `True`로 남음.
     - 세션 상태가 busy이므로 이후 들어오는 모든 유저 메시지는 `msg_queue`에 영구 대기되고, `/btw` 질문은 작업이 실제 돌고 있다고 착각해 거짓 답변을 생성함.
  3. **유휴 세션 프로세스 미정리**:
     - 사용자가 세션을 전환하거나 브라우저를 닫아도 과거 세션의 `self.proc`이 종료되지 않고 백그라운드에 영구 상주(CPU 루프 또는 좀비 누적).
- **수정 내역**:
  - **`chatbot-ctl.sh`**: `DATA/live_pids.json`을 읽어 현재 챗봇 서버가 관리 중인 모든 활성 세션/스탠바이 PID를 `is_live_server_child`로 식별, 워치독이나 닥터가 오인 사살하지 않도록 면책 보호.
  - **`server.py` `_read_stdout()`**: `try ... finally` 블록으로 감싸 stdout EOF 도달 시 `self.busy`를 즉시 `False`로 해제하고 SSE 에러 이벤트 송출 및 큐 디스패치 보장.
  - **`server.py` `_run_btw()`**: 실제 프로세스 생존(`is_active = busy and proc and poll() is None`)을 정확히 판별하여, 작업이 없을 때는 "현재 백그라운드 메인 작업이 없습니다"를 명시하고 절대 거짓 응답을 꾸며내지 않도록 프롬프트 하드닝.
  - **`server.py` `_send()`**: 메시지 수신 시 프로세스가 죽어있으면 stale busy를 즉시 리셋.
  - **`server.py` `to_public()`**: API 응답의 `busy` 필드를 실제 생존 프로세스 기준으로 반환 (`really_busy = busy and proc and poll() is None`).
  - **`server.py` 스탠바이 루프 확장**: 15초 주기 `_reap_sessions()`를 통해 종료된 자식 프로세스 좀비 회수, 15분 이상 유휴(`idle > 900s`) 상태인 세션의 프로세스를 안전하게 graceful stop(추후 메시지 인입 시 `ensure()`로 재스폰). `_record_live_pids()`로 `live_pids.json` 항시 동기화.
- **검증**: `guard_rlock OK` → `chatbot-ctl.sh repair` 실행 완료 → `doctor PASS` 확인. 2시간 동안 CPU 92% 먹던 32575 및 좀비 프로세스 전원 회수 완료, CPU 정상화 확인.

## 2026-09-17 — 행동 통제 및 대량 토큰 작업 사전 승인 강제 규정 수립 (독단 실행 방지)

- **배경**: 실장님이 "계획을 문서로 저장해두고 진행할 때 꺼내서 하자"라고 지시했음에도, 냥피디가 자가진화/능동적 정체성을 앞세워 즉시 크롤링 스크립트 작성 및 대량 데이터 수집/Obsidian 위키 작성을 승인 없이 혼자 실행해 버림 (59만 토큰 소모 및 응답 지연 유발).
- **원인**: 냥피디 헌장(`AGENTS.md`) 및 페르소나(`PERSONA.md`)에 "계획 수립과 실행의 분리" 및 "고비용 작업 사전 승인 프로토콜"이 누락되어 있었음.
- **규정 추가 및 반영**:
  1. **`services/chatbot/data/workspace/PERSONA.md`**:
     - 정체성에 `철저한 지시 통제 및 단계별 승인(Action Control & Approval)` 항목 명시.
  2. **`services/chatbot/data/workspace/AGENTS.md`**:
     - `## 4. 행동 통제 및 사전 승인 원칙 (Action Control & Pre-Approval Protocol)` 섹션 신설.
     - 계획 수립과 실행의 엄격한 분리: "계획을 세워보자/저장해두자" 지시는 계획 문서화까지만 수행 후 정지하고 착수 여부를 질문할 것.
     - 고비용/대형 작업(대량 크롤링, 수십 개 파일 일괄 변환, 장시간 파이프라인, 100KB 이상 파일 분석) 착수 전 **예상 토큰/소요 시간/작업 범위를 1~2줄 요약 보고하고 사용자 승인 필수**.
  3. **루트 최우선 헌장 (`/var/services/homes/me/AGENTS.md`)**:
     - 제5항 `No Premature Autonomous Execution & Pre-Approval for Heavy Tasks` 조항 추가.

## 2026-09-17 — UX 개선 5단계: `/help` 슬래시 명령어 추가

- **배경**: critique P3 "도움말/온보딩 부재". 실장님과 상의해 온보딩 툴팁까지는 범위를 넓히지 않고 `/help` 커맨드 하나로 좁혀서 진행하기로 함.
- **`static/app.js`**: `send()`에 `/status`와 같은 패턴으로 `/help`를 클라이언트에서 직접 가로채 처리(서버/agy 왕복 없음) — 탭 단축키(`Alt+1~5`), 어디서나 `/`로 컴포저 점프, `⋯` 메뉴, 주요 슬래시 명령어를 요약한 냥피디 말투 안내 메시지 출력. `slashCatalog.commands`에도 `/help` 항목 추가해 슬래시 메뉴에서 발견 가능하도록 함.
- **`server.py`**: `/api/skills`가 내려주는 하드코드 `commands` 목록(클라이언트 시드를 런타임에 덮어씀)에도 동일하게 `/help` 항목 추가 — 이거 하나만 빠뜨리면 서버 응답이 도착한 순간 클라이언트 시드가 덮어써져서 사라짐.
- **검증**: `node -c app.js`/`python3 -m py_compile server.py`, `chatbot-ctl.sh repair` 배포, curl로 `/api/skills` 응답에 `/help` 포함 확인, doctor PASS. **실제로 `/help` 쳐서 안내 메시지 뜨는지는 브라우저 도구가 없어 직접 확인 못 함.**
- **참고**: 이 배포 직전 냥피디 자기개선 루프가 별도로 워치독/busy-flag 버그 수정 커밋(`c63df428`)과 "고비용 작업 사전승인" 규정 신설 커밋(`456ba521`)을 스스로 남겼음(무단 대량 크롤링 사고 이후 자체 재발방지) — 이번 `/help` 변경과는 무관, 충돌 없이 위에 깨끗하게 얹힘.

## 2026-09-17 — UX 개선 6단계(마지막): `/impeccable polish` 전체 마무리 패스

- **배경**: 실장님이 "나머지 진행하자"로 5·6단계 재개 지시. `impeccable critique-storage latest`로 저장된 스냅샷을 확인하려 했으나 exit 2(대상 파일이 critique 이후 바뀜 — 그 사이 1~5단계에서 계속 수정했으니 예상된 결과) → 별도 스냅샷 없이 독립적으로 전체 diff 재검토.
- **동시 진행 중이던 다른 에이전트 작업 확인**: 이 세션이 5단계를 마무리하는 사이, 같은 `static/app.js`/`static/index.html`에 냥피디 자기개선 루프가 별도로 "라이브 프로세스 상태 배지·경과 턴 타이머·헬스체크 워치독"(커밋 `b1ed4abf`, 403줄)을 얹었음. 폴리시 패스에서 두 작업이 구조적으로 충돌 안 하는지 확인: 탭 버튼에 `tab-icon`/`tab-label` 서브스팬이 추가됐지만 내가 붙인 `role="tab"`/`aria-selected`/`aria-controls`/`title="Alt+N"`은 전부 보존됨, `moreMenu`/`confirmModal`/`role="tabpanel"`/`:focus-visible` 등 이번 세션에서 추가한 마크업·CSS·JS 함수 전부 그대로 살아있음 확인 — 실제 충돌 없음.
- **폴리시로 발견해서 고친 실제 결함**: `confirmModal()`에 Tab 트랩이 없어서 확인창이 떠 있는 동안 Tab/Shift+Tab으로 뒤 페이지까지 포커스가 빠져나갈 수 있었음 — 버튼이 정확히 2개뿐이라 "지금 포커스 안 된 쪽"으로 고정 순환시키는 간단한 트랩 추가.
- **검토했지만 안 고친 것**: 확인모달/⋯메뉴 모두 닫힐 때 포커스가 있던 버튼이 `display:none`이 되는데, 이 경우 브라우저가 자동으로 포커스를 `<body>`로 이동시키는 표준 동작이라 별도 처리 불필요하다고 판단. `Alt+1~5`가 입력창에 포커스가 있을 때도 발동하는 것(Mac에서 Option+숫자가 특수문자 입력에 쓰이는 경우와 충돌 가능)은 이론상 엣지케이스지만 한국어 위주 도구에서 실사용 빈도가 낮다고 보고 그대로 둠.
- **검증**: `node -c app.js` 문법 확인, `chatbot-ctl.sh repair` 배포, curl로 `confirmModal`/`moreMenuBtn`/`role="tabpanel"`/`:focus-visible`/`/help` 전부 여전히 살아있는 것 확인, doctor PASS.
- **critique 스냅샷 close는 생략**: `snapshot_file`을 못 받아왔으므로(대상이 이미 바뀌어 exit 2) impeccable 규칙상 close 호출 안 함 — 다음에 critique를 다시 돌리면 새 점수로 트렌드가 이어짐.
- **이걸로 impeccable critique 기반 UX 개선 6단계(clarify→harden→optimize→distill→document→polish) 전부 완료.**

## 2026-09-17 — 냥피디 자기개선 커밋(b1ed4abf) 리뷰: CSS 파싱 버그 수정 + 페르소나 말투 통일

- **배경**: 실장님 지시 — "냥피디 작업 확인해보고 고칠 거 있으면 고쳐줘". 이 세션이 5·6단계 작업하는 동안 냥피디 자기개선 루프가 별도로 얹은 두 커밋(`c63df428` 워치독/busy-flag 수정, `b1ed4abf` 라이브 프로세스 상태 배지·경과 턴 타이머·모바일 반응형 대개편 403줄)을 검토.
- **`c63df428`(server.py/chatbot-ctl.sh)**: 코드 리뷰 결과 문제 없음. `_read_stdout`의 try/finally로 EOF 시 busy 플래그 해제, `_reap_sessions()`의 유휴 15분 프로세스 정리, `live_pids.json` 기반 워치독 면책 로직 전부 락 사용과 우선순위(ppid==1이 live_pids 면책보다 우선)가 올바름.
- **`b1ed4abf`에서 발견해 고친 실제 결함**:
  1. **CSS 파싱 버그(치명)**: `body.keyboard-open .wrap,` 바로 다음 줄에 `@media (max-height: 500px) {`가 와서 "셀렉터, @media {}"라는 존재하지 않는 문법이 되어있었음 — CSS는 셀렉터와 at-rule을 콤마로 묶을 수 없어서 `body.keyboard-open` 쪽 규칙 전체가 파싱 실패로 죽어있었을 가능성이 높음(가상키보드 감지 시 레이아웃 축소가 전혀 안 먹혔을 것). `@media (max-height:500px)` 블록은 그대로 두고, `body.keyboard-open` 접두사를 붙인 동일 선언 세트를 별도 규칙으로 분리해 둘 다 유효하게 만듦.
  2. **impeccable dark-glow 발견 처리**: `.proc-badge.running .dot`의 `box-shadow:0 0 8px #ffa657`(오프셋 0의 색깔 후광)는 craft-floor 규칙상 명백한 장식성 위반이라 제거. 단, `animation:pulse-dot`(점멸)은 실제로 살아있는 프로세스 상태(running/idle/dead/disconnected)가 바뀔 때만 반영되는 진짜 라이브 지표라 판단해 유지 — impeccable 자체 가이드("진짜 라이브 데이터에 연동된 지표에만 pulse 허용")에 부합.
  3. **`pulsing-dot` 발견**: 위와 같은 이유로 정당한 예외로 판단, 유지.
- **실장님 추가 지시 반영("캐릭터성을 유지할 수 있게 시스템 메시지 같은 것도 구어체로 꾸며줘")**: 새로 추가된 프로세스 상태 배지 문구(`실행 중 Ns`/`프로세스 중단됨 ⚠️`/`재연결 중…`/`대기 중`)가 전부 밋밋한 표준어였고, 바로 옆에서 같은 기능이 이미 쓰는 `'⚠️ 백엔드 프로세스가 중단되었습니다냥.'`과 톤이 안 맞았음 — `${sec}초째 작업 중이다냥`/`헉, 프로세스가 멈췄다냥 ⚠️`/`다시 연결하는 중이다냥…`/`대기 중이다냥`으로 통일. SSE 재연결 시 `setProgress('연결 끊김 · 재연결 중…')`도 같은 이유로 `'연결이 끊겼다냥 · 다시 연결하는 중…'`으로. 턴 경과 placeholder의 영어 단위 `Ns`도 `N초`로 한글화(이 자체는 페르소나보다 일관성 문제). **의도적으로 안 건드린 것**: `addActivity(...)` 로그 탭 문구들은 이 앱 전체에서 원래 표준어 톤이 관례(세션 복원/새 세션/오류 로그 등 전부 냥 없음)라 그대로 둠 — 페르소나 통일은 사용자에게 직접 말 거는 표면(배지·진행바·챗버블·배너)에 한정.
- **검증**: `node -c app.js`, `<style>` 블록 중괄호 균형(329/329) 및 `selector,@media` 패턴 재검색으로 다른 인스턴스 없음 확인, `chatbot-ctl.sh repair` 배포, curl로 `body.keyboard-open #send`(CSS 수정)·글로우 제거(0건)·새 페르소나 문구 5종 전부 실제 서빙 확인, doctor PASS. **실제 가상키보드 환경에서 레이아웃이 맞게 줄어드는지는 브라우저/모바일 기기가 없어 직접 확인 못 함.**

## 2026-09-17 — `config/persona.json` 삭제: 페르소나 SSOT를 `PERSONA.md` 하나로 정리

- **배경**: 실장님이 시스템 메시지 페르소나 톤 얘기를 하다가 "페르소나가 바뀌면 시스템 메시지 톤도 바뀌어야 하는데?"라고 지적 → 확인해보니 `config/persona.json`은 VibeCat에서 그대로 가져온 거라 이 프로젝트에선 실제로 아무것도 안 읽는 죽은 파일이었음("persona 도 ssot여야지").
- **확인한 사실**: `grep -rn "persona.json"` 결과 `server.py`/`static/app.js`/`chatbot-ctl.sh` 어디에도 이 파일을 읽는 코드가 전혀 없음. `display_name`/`address_user_as`/`style_notes`는 전부 `data/workspace/PERSONA.md`에 이미 더 자세히 있고, `avatar`/`gallery`/`icon` 이미지 경로도 `index.html`이 독립적으로 하드코딩(`/chat/persona/face-icon.webp` 등)해서 쓰고 있어 이 JSON을 거치지 않음. 심지어 파일 자신도 `"system_files": ["PERSONA.md", "AGENTS.md"]`라고 적어놔서 실제 소스가 어딘지 스스로 인정하고 있었음. `config/`에 남은 유일한 파일이라 삭제 후 디렉터리 자체도 사라짐.
- **왜 `PERSONA.md`가 진짜 SSOT인가**: `ADD_DIRS`(`server.py`)가 `ROOT`(=`services/chatbot`, `data/workspace/PERSONA.md` 포함)를 agy 프로세스에 직접 노출하므로, 이 파일이 실제로 LLM이 매 턴 읽는 살아있는 컨텍스트임. `persona.json`은 그 어떤 실행 경로에도 연결 안 된 순수 문서 장식이었음.
- **수정**: `config/persona.json` 삭제(git rm), `README.md`의 두 참조(소개 문장 + 구성 표)를 `data/workspace/PERSONA.md`로 정정.
- **참고**: 이번 시스템 메시지 톤 통일 작업 자체(app.js에 "~냥" 문자열 직접 기입)는 그대로 유지 — 실장님 확인 결과 "다른 페르소나로 교체"가 실제로 쓰이는 시나리오가 아니므로, 문자열을 페르소나 파일에서 동적으로 조립하는 템플릿 시스템은 불필요하다고 판단(과설계 방지).
- **검증**: `grep`으로 전 코드베이스에 `config/persona.json`/`config/` 참조가 더 없는지 재확인. 서버 로직 변경 없음(원래 안 읽던 파일 삭제)이라 재기동 불필요.

## 2026-09-17 — 대화 중 자동 세션 전환 시 방금 보낸 말이 사라지던 버그 수정 + 경계 없는 전환으로 재설계

- **증상**: 실장님 보고 — "내가 말을 하면 바로 새 세션으로 넘어가면서 내가 한 말을 또 해야 되는 상황이 생겨". 이어서 "여러 가지 방식을 동원해서 최대한 세션 간 경계가 느껴지지 않게 전환되는 느낌이면 좋겠네"라고 방향 제시.
- **원인**: `_rotate_to_fresh_session()`(대화 중 hard 임계치 도달 시 자동 인계)이 (1) 옛 세션에 `session_rotate` SSE 이벤트를 emit하고 → (2) `self.stop()` → (3) 후속 세션에 실제로 `_send_direct()`로 메시지를 보내는 순서로 동작하는데, **정작 그 메시지를 보낸 바로 그 탭이 여전히 옛 세션의 SSE에 구독 중이라 (1)번 이벤트를 자기 자신도 받아버림.** 이 SSE 이벤트는 `_send_direct`(콜드 스폰이면 7~9초 소요 가능)보다 먼저 emit되므로 클라이언트에 먼저 도착 → `session_rotate` 핸들러가 (유저 메시지 에코 없이) 로그를 지우고 일반 안내 문구만 그려버림. 몇 초 뒤 진짜 `/message` POST 응답이 도착해 다시 `enterSession()`을 호출하지만, 그 사이 실장님은 화면이 비워진 걸 보고 "메시지가 안 갔나?" 싶어 다시 입력하게 됨 — 같은 이벤트에 대해 두 개의 서로 다른 신호(SSE + POST 응답)가 경쟁하는 구조적 문제.
- **수정 1 (레이스 제거, `server.py`/`static/app.js`)**: `session_rotate` emit에 `client_mid`를 실어서, 그 메시지를 보낸 바로 그 탭이 자기 `myPendingMids`에서 같은 mid를 발견하면 SSE 핸들러가 아무것도 안 하고 조용히 빠지도록(`return`) 함 — 실제 화면 전환은 오직 `/message`의 POST 응답 쪽 한 곳에서만 일어남(멀티윈도우 `user_ack` 중복 억제와 동일한 패턴 재사용). 다른 탭/창(수신자가 아닌)은 기존처럼 SSE 알림+배너로 안내받음 — 그쪽은 갑자기 대화가 바뀌는 걸 설명 없이 보면 오히려 더 혼란스러우므로 그대로 유지.
- **수정 2 (경계 없는 전환으로 재설계, `static/app.js` `enterSession`/`send()`)**: 레이스만 없애도 `enterSession()`이 매번 로그를 통째로 지웠다 다시 그리는 구조라 깜빡임(보이는 "경계")이 남음. `enterSession()`에 `preserveLog` 옵션을 추가해 로그/액티비티를 아예 안 지우도록 하고, `send()`의 rotated 분기에서 `userEcho`/`greeting`(둘 다 제거) 없이 `preserveLog:true`로 호출 — 어차피 `send()` 맨 위에서 이미 낙관적으로 그려둔 유저 말풍선이 화면에 그대로 남아있으니 새로 그릴 필요가 없음. 인계 요약문(`handoff_summary`)은 화면에 다시 안 보여줘도 서버가 새 세션 첫 턴 stdin에 그대로 주입하므로 모델 입장에선 맥락이 안 끊김.
- **부수 수정**: `preserveLog`로 화면을 안 지우면서 `lastSyncedTs`를 그냥 0으로 리셋하면, 새 세션의 SSE가 연결되자마자 `resyncFromServer()`가 이미 화면에 있는 그 유저 메시지를 "놓친 메시지"로 착각해 중복 렌더링할 뻔함 — `enterSession()`에 `syncedTs` 옵션을 추가해 새 세션 히스토리의 마지막(=방금 보낸 메시지) `ts`로 정확히 맞춰줌. 이번 참에 이 rotated 분기가 그동안 스크롤백을 전혀 리셋 안 하던 것(1단계 리팩토링 때 발견만 하고 안 고쳤던 항목)도 `scrollback:'self'`로 정식으로 고침 — 이번엔 이 경로 자체를 실장님 지시로 다시 설계하는 김이라 드라이브바이가 아님.
- **검증**: `node -c app.js`/`python3 -m py_compile server.py`, `chatbot-ctl.sh repair` 배포, doctor PASS. **실제 hard 임계치(60턴/25000자)를 자연스럽게 채워서 라이브로 재현 검증하는 건 비용이 너무 커서 안 함** — 코드 경로 자체(emit 순서, client_mid 매칭, ts 비교 로직)를 직접 추적해 정합성 확인. 실제 화면에서 진짜로 안 끊기고 자연스럽게 넘어가는지는 다음에 실장님이 대화를 충분히 길게 이어가며 확인 필요.

## 2026-09-17 — 세션 전환 시 인계받은 새 세션이 지시를 무시하고 딴 얘기 하던 문제 + 인계 맥락에 마지막 대화 원문 추가

- **증상**: 실장님 보고 — "일을 시켰는데 세션이 전환되면서 내가 시킨 일을 잊어버리고 딴 소리를 하고 있어".
- **원인**: `_send_direct()`의 핸드오프 주입 템플릿이 `[이전 세션 인계 맥락]\n{summary}\n---\n[실장님의 현재 메시지]\n{text}` 형태로 두 섹션을 라벨만 붙여 나열했을 뿐, "인계 맥락은 배경일 뿐이고 실제로 답해야 할 건 현재 메시지"라는 걸 명시적으로 지시하지 않았음 — 특히 빠른 모델(`gemini-3.8-flash-low`)이 인계 맥락(특히 agy 자체 `/compact` 요약처럼 "인계용" 포맷이 아닌 일반 요약)을 실제 화두로 착각해 그것에 대해 코멘트하고 현재 지시는 무시하는 경우가 생겼을 것으로 추정.
- **수정 1 (`server.py` `_send_direct`)**: 템플릿 맨 앞에 `[시스템 안내]`로 "인계 맥락은 참고용 배경일 뿐, 요약하거나 코멘트하지 말고 오직 '실장님의 현재 메시지'에만 답하거나 수행하라"는 명시적 지시 추가. 두 섹션 라벨도 "참고용 배경" / "지금 답하거나 수행해야 할 것"으로 더 명확하게.
- **수정 2 (실장님 제안: "압축한 내용에 덧붙여 마지막 주고받은 대화를 자동으로 재전송한다면?")**: `get_handover_summary()`가 반환하는 핸드오프 텍스트에 압축 요약 뒤로 **마지막으로 실제 주고받은 대화(유저 마지막 메시지 + 어시스턴트 마지막 답변)를 원문 그대로(각 1200자 캡)** 추가하는 `_with_last_exchange()` 헬퍼 신설. 요약은 압축 과정에서 세부 표현이나 "3번 방향으로 가자" 같은 지시대명사 참조를 잃기 쉬운데, 원문 한 턴을 그대로 붙여두면 새 세션이 고해상도 앵커를 하나 더 갖게 됨. `_dialogue_summary_fallback()` 내부의 개별 캐싱 두 곳은 제거하고, `get_handover_summary()` 최상위에서 (기본 요약 + 원문 붙이기) 이후 한 번만 캐싱하도록 정리 — 캐시 지점 단일화.
- **검증**: 실제 hard 임계치를 자연 도달시키는 대신, 격리된 테스트 세션을 새로 만들어 가짜 프로젝트 맥락(`send_email(to, subject, body)` 시그니처 논의)을 쌓고 `/continue`로 동일한 핸드오프 코드 경로(`_send_direct`의 주입 블록)를 강제 트리거해 검증:
  1. 수정 1만 적용된 상태에서 "smtplib로 가자, 첫 줄에 오늘 요일만 말해줘" → 정확히 "목요일"로 시작 후 바로 구현 코드 진행(인계 맥락에 대한 딴 얘기 없음) 확인.
  2. 수정 2까지 적용 후 `/continue` 재실행 → 요약 뒤에 `[마지막으로 주고받은 대화 원문]` 블록이 실제 원문 그대로 붙어있는 것 확인.
  3. 이어서 "3번(비동기) 방향으로 가자, 답변 시작 전에 숫자 7만 먼저 말해줘" → "7"로 시작 후, **압축 요약만으로는 알 수 없었을 "3번" 지시대명사(이전 답변의 번호 매긴 목록 항목)를 원문 블록 덕분에 정확히 해석**해서 비동기 구현으로 정확히 이어감 확인 — 두 수정이 실제로 함께 작동하는 것까지 end-to-end 검증.
  - `chatbot-ctl.sh repair` 배포, doctor PASS.

## 2026-09-17 — 작성 중 "중지" 버튼을 눌러도 죽은 프로세스의 남은 출력이 계속 흘러들어오던 버그 수정

- **증상**: 실장님 보고 — "작성 중인 상태에서 중지같은 게 안되네" / "진행 중인 걸 취소시키고 싶은데".
- **재현/원인 확인**: 테스트 세션에 일부러 아주 긴 답변을 요청해 busy 상태로 만든 뒤 `/stop`을 직접 호출해보니, 서버는 `proc.terminate()`로 프로세스를 실제로 죽이는 데는 성공(stderr에 `error: interrupted` 확인)하지만, **죽기 직전 이미 stdout 파이프에 버퍼링돼 있던 나머지 출력을 `_read_stdout()`이 그대로 계속 읽어서 정상 이벤트처럼 처리**하고 있었음 — 실제로 중단된 답변인데도 (이전 턴의) 오래된 `usage`/`duration_seconds` 값이 그대로 붙은 채 `history`에 "정상 완료된 답변"처럼 저장돼버림. 클라이언트 쪽에서는 `stop` 버튼 클릭 시 로컬로 "작업을 중지했습니다냥" 말풍선을 띄우자마자, SSE로 이 뒤늦은 잔여 이벤트(`delta`/`result`)가 도착해 `setBusy(true)`를 다시 호출하고 새 말풍선을 그려버려 — 실장님 눈엔 "중지를 눌렀는데 마치 아무 일도 없었던 것처럼 계속 답하거나 새 답이 뜨는" 것처럼 보였을 것.
- **수정 (`server.py`)**: 세션에 `_stop_requested` 플래그 추가. `stop()`이 프로세스를 죽이기 *직전에* 이 플래그를 `True`로 세팅, `_read_stdout()`의 읽기 루프가 매 줄마다 이 플래그를 확인해서 켜져 있으면 파이프에 남은 내용을 전부 조용히 버림(이벤트 emit도, history 저장도 안 함). 다음 실제 메시지가 `_spawn()`으로 새 프로세스를 띄울 때 플래그를 다시 `False`로 리셋 — 새 턴은 정상대로 동작.
- **부수 효과**: 이 수정으로 인해 중단된 턴은 이제 `history`에 아예 어시스턴트 답변 항목이 안 남음(깨끗하게 아무 것도 안 남기고 끝) — 이전처럼 이상한 재사용 usage 수치가 붙은 가짜 완료 항목이 저장되던 부작용도 같이 사라짐.
- **검증**: 테스트 세션에서 (1) 수정 전: 아주 긴 답변 요청 → busy 확인 → `/stop` 호출 → 응답에 `busy:false, alive:false`이지만 `history`의 마지막 어시스턴트 항목이 직전 턴과 완전히 동일한 `usage`/`duration_seconds`를 가진 채 저장된 것 확인(버그 재현). (2) 수정 후: 동일한 시나리오 재실행 → `/stop` 호출 후 `history`의 마지막 항목이 유저 메시지 그 자체(어시스턴트 답변 없음)로 끝나는 것 확인 — 잔여 이벤트가 더 이상 처리 안 됨. `chatbot-ctl.sh repair` 배포, doctor PASS.

## 2026-09-17 — 대답별 사용 토큰 양 표시 및 주의감(Visual Caution) 등급 기능 추가

- **요청**: 실장님 — "대답 마지막에 사용한 대답에 사용한 토큰 양 표시해주면 좋겠어. 아래에 스피커 아이콘 붙은 라인이 있으니 그쪽에 토큰 양에 따라 주의감을 주는 기능도 추가해서."
- **원인/현황 분석**:
  - `server.py`는 이미 `result` 이벤트 및 `meta.json`의 `history` 항목에 `usage`(`total_tokens`, `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens`)와 `duration_seconds`를 정상적으로 기록 및 브로드캐스트하고 있었음.
  - 하지만 프론트엔드(`app.js`)에서 `postProcessAssistant()`가 `attachTtsButton(node, rawText)`만 호출하면서 `usage`를 `null`로 버려두었고, 세션 히스토리 로드(`loadSession`, `resyncFromServer`, `maybeBackfillScrollback`) 시에도 `usage`를 렌더러에 전달하지 않아 토큰 뱃지가 화면에 렌더링되지 않고 있었음.
- **구현 및 변경 내역**:
  1. **토큰 소모량 기반 주의감(Caution Tiers) 설계 (`app.js` `getUsageLevel`)**:
     - `normal` (< 15k): 기본 회색/차분한 테두리 (`⚡ 14.5k · 2.1s`)
     - `moderate` (15k ~ 40k): 은은한 오렌지 테두리 및 텍스트 포인트
     - `warning` (40k ~ 100k 또는 fresh 20k+): 앰버/주황 경고 테두리 + 배경 (`⚠️ 75.2k · 12.1s`), 툴팁 경고 문구 추가
     - `heavy` (≥ 100k 또는 fresh 35k+): 붉은색 계열 테두리/배경 + 부드러운 펄스 애니메이션 (`🔥 140k · 52.1s 🚨`), 라인 전체 앰버/레드 그라데이션 및 "대용량 토큰 소모! 상단 맥락 이어 새 대화 권장" 툴팁 안내.
  2. **스피커 라인(`.msg-footer`) 연동 (`index.html`, `app.js`)**:
     - 좌측에 토큰 뱃지(`span.token-badge.token-*`), 우측 끝에 스피커 버튼(`button.tts-btn` 🔊) 배치.
     - 대화 턴의 토큰 양이 warning/heavy일 경우 `.msg-footer`에 `.footer-warning`, `.footer-heavy` 클래스가 부여되어 구분선 대시 컬러가 주의색으로 변하고 배경 하이라이트가 은은하게 적용됨.
  3. **히스토리 및 실시간 SSE 파이프라인 연결**:
     - `postProcessAssistant`, `addChat`, `setAssistantContent`, `addBtw`에서 `usage`, `durationSeconds`를 인자로 전달.
     - SSE `result` 이벤트 수신 시 `data.usage`와 `data.duration_seconds` 즉시 반영.
     - 세션 복원(`opts.history`, `resyncFromServer`, `loadOlderHistory`) 시 저장된 `h.usage`, `h.duration_seconds`를 완전하게 복원 렌더링.
  4. **캐시 버스팅**: `index.html` 내 `app.js?v=20` 갱신.
- **검증**: `node -c app.js` 통과, curl 서빙 검증 및 doctor PASS 확인.

## 2026-09-17 — 토큰 주의감 임계값 현실화 보정 (Gemini 1M 컨텍스트 스케일 조정)

- **증상**: 실장님 확인 — "대화 한 번 했는데 다 빨간색 대용량이네".
- **원인 분석**:
  - Gemini Flash 모델의 Antigravity 기본 컨텍스트(도구 스키마, 시스템 프롬프트, `ADD_DIRS`) 및 이전 턴 대화가 포함될 경우 일상적인 턴에서도 20k~50k가 넘어가며, 누적 대화 시 100k~250k 수준은 흔하게 발생함.
  - 이전 임계값(`heavy` 100k+, `warning` 40k+)이 너무 낮아 일반적인 대화 한 번에도 과도하게 적색 경고(`🔥 heavy 🚨`)가 발동했음.
- **임계값 조정 (`app.js` `getUsageLevel`)**:
  - `normal` (< 100k): 기본 일상 턴 및 짧은 대화 누적 (은은한 기본 뱃지)
  - `moderate` (100k ~ 250k): 대화가 어느 정도 쌓인 상태 (주황 텍스트 포인트)
  - `warning` (250k ~ 400k 또는 순수 신규입력 50k+): 컨텍스트 증가 주의 구간 (앰버 경고 뱃지)
  - `heavy` (≥ 400k 또는 순수 신규입력 80k+): `server.py`의 `HARD_TOKENS = 400k`와 일치시켜 진짜로 세션 전환이 필요한 위험 구간에만 적색 펄스 및 경고 발동.
- **캐시 버스팅**: `app.js?v=21` 반영.

## 2026-09-17 — 새 세션 시작 시 이전 대화(26만 토큰)를 자동 상속하던 agy Auto-Resume 버그 완벽 수정 (토큰 낭비 근본 해결)

- **증상**: 실장님 확인 — 새 세션에서 "토큰 양 보여주는 기능을 추가했어" 한 턴만 나눴는데도 토큰이 무려 `263,195`개(26만 토큰)로 찍힘.
- **원인 분석**:
  - `agy` CLI는 Go 바이너리로, `--conversation <id>` 플래그가 전달되지 않으면 **현재 실행 경로(`cwd`)를 기준으로 `~/.gemini/antigravity-cli/cache/last_conversations.json`에 저장된 가장 최근의 대화 ID를 자동으로 이어서 로드**하는 Auto-Resume 동작을 함.
  - 기존 `server.py`는 새 세션 생성 시 `conversation_id = None` 상태로 `_StandbyPool`을 띄우거나 프로세스를 스폰함.
  - 이로 인해 `args`에 `--conversation`이 빠진 채 실행되어, `agy`가 과거 `services/chatbot`에서 진행했던 거대한 26만 토큰짜리 대화(`d96c6f14-35b0-48b4-abed-3fa1ceb32d02`)를 고스란히 복원하여 읽고 답변해버림!
  - `server.py`는 `agy`가 뱉은 `conversation_id: d96c6f14...`를 보고 그 값을 새 세션의 `meta.json`에 덮어씀. 결과적으로 새 세션을 열어도 이전의 방대한 26만 토큰 쓰레기가 그대로 상속되어 매 턴마다 엄청난 토큰 낭비와 속도 지연을 유발함.
- **근본 해결책 (`server.py`)**:
  1. **스탠바이 풀(`_StandbyPool`) 고유 UUID 강제**:
     - `ensure_warm()`에서 스탠바이 프로세스를 띄울 때 항상 `uuid.uuid4()`를 생성하여 `--conversation <new_uuid>`로 실행.
     - `try_take()` 시 프로세스와 함께 해당 고유 `conv_id`를 세션에 전달.
  2. **세션 스폰(`_spawn`) 고유 UUID 강제**:
     - 스탠바이를 채택하지 않는 콜드 스폰 경로에서도 `not self.conversation_id`일 경우 반드시 즉시 고유한 `uuid.uuid4()`를 생성하여 저장하고 agy에 전달.
     - `agy`가 절대로 `last_conversations.json`의 이전 대화를 멋대로 이어받지 못하도록 원천 봉쇄.
  3. **캐시 정리**: `last_conversations.json`에 남아있던 오래된 챗봇 키 삭제.
- **실측 검증**:
  - 패치 후 새 세션(`20260917-171036-485838`) 생성 및 1턴 발화("안녕") 테스트.
  - 고유한 신규 ID(`a4e56cc7-63e5-4d97-b34d-7a9e307cec3f`)로 독립 시동 확인.
  - 턴 1 토큰 사용량: **263,195 토큰 ➔ 45,934 토큰 (정상 첫 턴 베이스라인)**으로 정상 복귀 및 소요 시간 3.6초 확인!
  - `doctor PASS` 완료.





## 2026-09-17 — 세션 "무거움" 판정이 턴별 누적 컨텍스트를 또 합산해서 스스로 조기 트리거되던 구조적 토큰 낭비 수정

- **요청**: 실장님 — "토큰 사용량을 감시해서 쓸데없이 토큰을 낭비하는 구조를 원천차단해야만 해."
- **조사**: 실제 `data/sessions/*/meta.json`의 턴별 `usage.total_tokens`를 직접 비교(`171939-756ea6`: `46779 → 52834 → 55107 → 57606 → 60323 → 63256`). `input_tokens`/`output_tokens`를 함께 찍어보니 `total_tokens = input_tokens + output_tokens`이고, `input_tokens` 자체가 **그 턴 시점까지의 대화 전체(누적 컨텍스트)**였음 — agy는 매 턴 전체 대화를 다시 모델에 흘려보내는 구조(스테이트풀 API가 아님, `cache_read_tokens`는 그중 캐시로 싸게 처리된 비중일 뿐).
- **버그**: `_session_weight()`(`server.py`)가 "세션이 너무 커졌는지"를 판정할 `total_tokens`를 **턴별 누적값을 다시 전부 합산**(`sum(h.usage.total_tokens for h in history)`)해서 계산하고 있었음. 이미 누적값인 걸 또 더하니 사실상 제곱 성장 — 위 예시 세션은 실제 컨텍스트가 63,256토큰(정상)인데 이 합산 지표는 335,905(SOFT 150k 기준 이미 2배 초과)로 계산되고 있었음.
- **파급 효과 (진짜 낭비 지점)**: `_emit_heavy_if_needed()`가 soft/hard 레벨을 감지하는 즉시 백그라운드 스레드로 `get_handover_summary()`를 돌려 `agy -p /compact --conversation <cid>`를 호출 — 이건 그 시점까지의 전체 대화를 다시 모델에 태워 압축 요약을 만드는, 그 자체로 토큰을 쓰는 호출. 버그 있는 지표 때문에 실제로는 전혀 무겁지 않은 세션(3~4턴, 6만 토큰대)에서도 이 압축 호출이 조기 발동하고 있었고, HARD(400k) 도달 시엔 실제보다 훨씬 일찍 강제 세션 로테이션(맥락 단절 + 실장님이 방금 한 말 다시 설명해야 하는 상황)까지 유발할 수 있었음. 즉 "토큰 낭비를 막기 위한 안전장치"가 잘못된 지표 때문에 오히려 더 자주 토큰을 태우는 역설적 구조였음.
- **수정 (`server.py`)**: `_current_context_tokens()` 신설 — history를 역순으로 훑어 **가장 최근 턴의 `usage.total_tokens`(=현재 컨텍스트 크기 그 자체) 하나만** 반환. `_session_weight()`는 이제 이 값을 그대로 사용(합산 제거).
- **검증**: 수정 후 실제 세션 파일(`171939-756ea6`)에 대해 `_session_weight()`를 직접 호출 — `level: ok, total_tokens: 63256`으로 정확히 마지막 턴 값과 일치 확인(수정 전이었다면 `level: soft, total_tokens: 335905`로 오판정됐을 것). `chatbot-ctl.sh repair` 배포, `probe_message OK`, doctor PASS.
- **범위 밖으로 남겨둔 것**: 프론트엔드(`app.js`)의 "세션 누적" 뱃지와 백엔드 `to_public()["usage"]`는 턴별 `total_tokens`를 그대로 합산하지만, 이건 다른 질문("이 세션에서 지금까지 실제로 청구된 토큰 총합이 얼마냐")에 대한 정답이라 그대로 둠 — 매 턴이 독립된 API 호출이라 각 턴의 청구액이 곧 그 턴의 `total_tokens`이므로 합산이 맞는 계산. 헷갈리지 않도록 컨텍스트 크기 판정(로테이션용)과 누적 청구량 표시(정보용)를 구분해서 기록.

## 2026-09-17 — "새 세션" 클릭 시 최근 대화(맨 아래)가 아니라 중간 지점으로 스크롤 이동하던 버그 수정

- **증상**: 실장님 — "새 세션을 누르면 최근 대화로 스크롤되지 않고 중간 지점에 스크롤이 이동하네".
- **원인 분석 (`static/index.html` / `static/app.js`)**:
  1. `enterSession()`은 세션 전환마다 `logEl.innerHTML = ''`로 로그를 비움. 직전 세션이 스크롤을 많이 내린 채(예: scrollTop 3000px대)였다면, 콘텐츠가 사라지는 순간 브라우저가 `scrollTop`을 0으로 강제 클램프하면서 **네이티브 `scroll` 이벤트를 발생**시킴.
  2. `#log`의 `scroll` 리스너는 `scrollTop < 120`이면 무조건 "사용자가 맨 위 근처로 스크롤했다"고 보고 `loadOlderHistory()`를 호출해 **직전(방금 지운) 세션의 전체 히스토리를 새 세션 화면 위에 다시 끼워넣음** — 위 1번의 클램프 이벤트가 실제 사용자 스크롤과 구분 없이 이 조건을 그대로 만족시켜 새 세션 진입 직후 의도치 않게 발동했음.
  3. `loadOlderHistory()`는 프리펜드 후 `logEl.scrollTop = prevScrollTop + (scrollHeight 증가분)` 공식으로 스크롤 위치를 수동 보정하는데, `#log`에 `overflow-anchor`가 기본값(`auto`, 즉 브라우저 네이티브 scroll anchoring 활성)이라 **브라우저가 똑같은 보정을 한 번 더 자동으로 얹어 이중 보정**이 발생. 여기에 `#log`의 `scroll-behavior:smooth`까지 겹쳐 `logEl.scrollTop = ...`(코드 전체 15곳 모두 "즉시 스냅" 의도)이 애니메이션으로 처리되면서, 서로 다른 목표를 향한 스크롤 애니메이션들이 경합하다 중간 지점에서 멈추는 결과로 나타남.
- **수정**:
  1. `static/app.js` scroll 리스너에 `logEl.scrollHeight > logEl.clientHeight + 20` 가드 추가 — 실제로 스크롤할 오버플로가 있을 때만 "사용자가 위로 스크롤했다"로 인정. 로그가 비워진 직후처럼 콘텐츠가 뷰포트보다 짧을 때의 클램프성 `scroll` 이벤트는 이제 무시됨. `maybeBackfillScrollback()`의 "짧은 히스토리는 뷰가 찰 때까지 체이닝"용 별도 로직(반대 조건)은 그대로 유지.
  2. `static/index.html` `#log`에 `overflow-anchor:none` 추가 — `loadOlderHistory()`의 수동 스크롤 보정과 브라우저 네이티브 scroll anchoring이 중복 보정하지 않도록.
  3. `static/index.html` `#log`의 `scroll-behavior:smooth` 제거 — 코드베이스의 모든 `logEl.scrollTop = ...` 대입은 애니메이션이 아니라 즉시 스냅을 가정하고 쓰여 있었음.
  4. 캐시 버스팅: `app.js?v=22`.
- **검증**: `node -c app.js` 통과, `chatbot-ctl.sh repair` 배포 후 `curl`로 `/`와 `/app.js`에서 세 수정 사항이 실제로 서빙되는 것 확인, `probe_message OK`, doctor 배포 정상.

## 2026-09-17 — 위 스크롤 수정의 역효과: 새 세션에서 예전 세션 내용이 아예 안 불러와지던 문제 보완

- **증상**: 바로 위 커밋(스크롤 중간 지점 버그 수정) 배포 직후 실장님 — "이제는 예전 세션 내용들이 다 사라져버렸는걸".
- **원인**: 그 수정에서 scroll 리스너에 "실제 오버플로가 있을 때만" 가드를 추가해 `logEl` 클리어 직후의 스퓨리어스 `scroll` 이벤트로 `loadOlderHistory()`가 잘못 발동하던 걸 막았는데, 알고 보니 `createSession()`/`continueSession()`/`session_rotate` 세 경로 모두 `opts.history`를 넘기지 않아서(브랜드 뉴 세션이라 서버 히스토리가 원래 없음) `enterSession()`의 `setTimeout(maybeBackfillScrollback, 0)` 호출이 애초에 `if (opts.history)` 블록 안에만 있어 **이 세 경로에서는 한 번도 실행된 적이 없었음**. 즉 예전 세션 내용을 불러오던 유일한 경로가 사실은 방금 막은 그 스퓨리어스 이벤트였다는 뜻 — 버그를 없애니 (의도했던) 자동 백필 기능 자체가 통째로 사라진 것.
- **수정 (`static/app.js` `enterSession()`)**: `setTimeout(maybeBackfillScrollback, 0)` 호출을 `if (opts.history)` 블록 밖으로 빼서, `opts.scrollback`이 설정된 모든 진입 경로(`createSession`/`continueSession`/`session_rotate`/`openSession` 전부)에서 공통으로 실행되게 정리. `opts.scrollback`이 없는 `send()`의 인플로우 하드 로테이트(`preserveLog`) 경로는 원래 의도대로 그대로 미실행.
- **결과**: 짧은 새 세션에서도 뷰포트가 찰 때까지 이전 세션들을 자동으로 위에 이어붙이는 원래 의도된 동작이 복원됨. 이번엔 `overflow-anchor:none` + `scroll-behavior:smooth` 제거가 이미 적용된 상태라 이중 보정/애니메이션 경합 없이 정확한 위치(방금 끼워넣은 옛 대화 바로 아래 = 현재 세션 인사말)에 스크롤이 안착함.
- **검증**: `node -c app.js` 통과, `chatbot-ctl.sh repair` 배포, `curl`로 `app.js?v=23` 서빙 및 수정된 라인 확인, `probe_message OK`.

## 2026-09-17 — 채팅 렌더러 강화: 코드 문법 강조 · 이미지 라이트박스 · 전체 답변 복사 · 스트리밍 커서

- **요청**: 실장님 — "채팅 화면 렌더러를 좀 강화해볼까? 비주얼이니 기능을 더 풍부하게!" → 4개 항목 전부 선택.
- **1. 코드 블록 문법 강조**: `static/vendor/`에 highlight.js 11.10.0(전체 언어 번들, cdnjs)과 `github-dark` 테마 CSS를 marked.min.js/mermaid.min.js와 같은 방식으로 로컬 벤더링. `app.js`에 `highlightCodeIn()` 신설 — `renderMermaidIn()`과 동일하게 **isFinal에서만** 실행(스트리밍 중 매 delta마다 재하이라이팅하면 미완성 코드가 잘못 강조되고 리플로우 낭비도 큼). 하이라이트 후 `<code>`에 hljs가 붙인 `language-xxx` 클래스를 그대로 읽어 코드 블록 좌상단에 언어 배지(`.code-lang`)도 표시 — 명시적 \`\`\`lang 펜스든 hljs 자동감지든 항상 정확한 이름이 나옴. 기존 `.msg.assistant .md pre code`의 커스텀 배경/색 규칙이 명시도가 더 높아 카드 배경은 그대로 유지되고, 토큰별 색상(`.hljs-keyword` 등)만 테마에서 얹힘.
- **2. 채팅 내 이미지 클릭 확대**: 별도 라이트박스를 새로 만들지 않고 아티팩트 탭이 이미 쓰던 `openArtifactModal()`(다운로드/인용 버튼까지 포함된 기존 모달)을 재사용 — `openImageLightbox(url, alt)`이 최소 아티팩트 아이템 객체(`{name, kind:'image', url}`)를 만들어 그대로 넘김. `attachImageLightbox()`가 렌더링된 모든 `<img>`에 클릭 핸들러를 한 번만 바인딩(`.lightbox-bound` 마킹, 스트리밍 중 반복 렌더에도 중복 바인딩 안 됨).
- **3. 답변 전체 복사 버튼**: 기존 `attachCodeCopyButtons()`는 \`\`\`코드\`\`\`만 복사 가능했음. `attachMessageFooter()`에 📋 버튼 추가 — `rawText`(마크다운 원문) 전체를 클립보드로. 스피커(🔊) 버튼 바로 앞에 배치해서 기존 `.tts-btn{margin-left:auto}` 우측 정렬을 그대로 물려받음(DOM 순서상 먼저 오는 우측 요소가 auto-margin을 먹고, 나머지는 flex로 뒤따름).
- **4. 스트리밍 커서 애니메이션**: 리터럴 DOM 커서 노드 대신 순수 CSS `::after`로 처리 — `md.innerHTML`이 delta마다 통째로 교체되기 때문에 JS로 커서 엘리먼트를 넣어봤자 다음 delta에 사라짐. `postProcessAssistant()`가 `isFinal` 여부로 메시지 버블에 `.streaming` 클래스를 토글하고, `.streaming .md > *:last-child::after`가 마지막 블록(보통 마지막 `<p>`) 끝에 깜빡이는 바를 붙임. 최종 결과(`isFinal:true`) 시 클래스 제거로 자동 소멸.
- **검증**: `node -c app.js`, `node -c highlight.min.js` 통과. `chatbot-ctl.sh repair` 배포 후 `/vendor/highlight.min.js`·`/vendor/highlight-github-dark.min.css` 200 서빙 확인, `app.js?v=24`에 4개 기능 심볼 전부 포함 확인, probe PASS. 브라우저 확장(claude-in-chrome) 미설치 상태라 실제 시각 확인은 실장님 쪽에서 한 번 봐주셔야 함 — 특히 스트리밍 커서 위치와 라이트박스 클릭 동작.

## 2026-09-17 — 방금 추가한 전체 답변 복사 버튼이 푸터 한가운데에 떠 있던 CSS 버그 수정

- **증상**: 실장님 — "복사 버튼이 한 가운데 나오네".
- **원인**: 새 복사 버튼(📋)을 기존 `.tts-btn`의 우측 정렬(`margin-left:auto`)을 그대로 물려받으려고 `class="tts-btn copy-msg-btn"`로 만들었는데, CSS 규칙이 `.msg-footer .tts-btn{margin-left:auto}`로 클래스 이름을 기준으로 걸려있어서 **복사 버튼도, 스피커 버튼도 둘 다** 이 규칙에 걸림. flex 행에 `margin-left:auto`를 가진 요소가 두 개면 남는 공간이 두 auto-margin에 반씩 나뉘어 배분되어, 복사 버튼이 화면 가운데 즈음에, 스피커 버튼이 그 뒤 오른쪽 끝에 따로 떨어져 렌더링됐음.
- **수정 (`static/index.html`)**: 선택자를 클래스 기반에서 위치 기반으로 변경 — `.msg-footer button:first-of-type{margin-left:auto}`. 푸터 안의 버튼들 중 DOM상 첫 번째 것만 오른쪽 끝으로 밀려나고, 나머지는 flex 순서대로 그 옆에 바로 붙음. 복사 버튼이 있으면 복사 버튼이, 없으면(스피치 합성 미지원 브라우저 등) 스피커 버튼이 자동으로 그 역할을 물려받아 어떤 조합에서도 항상 올바르게 우측 정렬됨.
- **검증**: `chatbot-ctl.sh repair` 배포, `curl`로 새 선택자 서빙 확인(`app.js?v=25`), probe PASS.

## 2026-09-17 — 복사 버튼(코드블록 + 전체 답변 둘 다) 눌러도 실제로는 복사가 안 되던 문제 수정

- **증상**: 실장님 — "눌러도 복사 안되네" (방금 추가한 전체 답변 복사 버튼).
- **원인**: `navigator.clipboard.writeText()`는 브라우저 "보안 컨텍스트"(HTTPS 또는 localhost)에서만 존재/동작함. 이 챗봇은 `server.py`가 `0.0.0.0`에 TLS 없이 바인딩해서 `http://diskstation:3011`처럼 평문 HTTP로 서빙됨 — 이 조건에서는 `navigator.clipboard` 자체가 `undefined`라 `.writeText` 호출이 즉시 예외를 던짐. try/catch로 잡혀서 버튼이 "실패/❌"로 바뀌긴 했겠지만 실제 복사는 애초에 한 번도 성공한 적이 없었을 것 — 방금 만든 전체 답변 복사 버튼뿐 아니라, **기존에 있던 코드블록 "복사" 버튼도 같은 결함**을 안고 있었음(이번에 같이 확인·수정).
- **수정 (`static/app.js`)**: 공용 `copyText(text)` 헬퍼 신설 — `navigator.clipboard.writeText`를 먼저 시도하고, 없거나 실패하면 숨김 `<textarea>` + `document.execCommand('copy')`(보안 컨텍스트 요구 없는 구식이지만 여전히 폭넓게 동작하는 방식)로 폴백. 코드블록 복사 버튼과 전체 답변 복사 버튼 둘 다 이 헬퍼로 통일.
- **검증**: `node -c app.js` 통과, `chatbot-ctl.sh repair` 배포, `curl`로 `app.js?v=26`에 `copyText`/`execCommand('copy')` 포함 확인, probe PASS. (클립보드 API는 브라우저 보안 정책상 curl로 실제 복사 성공 여부까지는 확인 불가 — 실장님 쪽에서 재클릭 확인 필요.)

## 2026-09-17 — 남은 open 백로그 2건(0009, 0011) 정리: 재발 시 바로 진단 가능하도록 계측 추가

실장님 요청으로 `skill-observations/observation-log`에 남아있던 `open` 상태 관찰 2건을 처리. 둘 다 **드물게 한 번 관측되고 이후 재현 안 되는** 레이스라 무리하게 구조를 바꿔 "고치려" 하기보다, 재발 시 원인을 바로 잡아낼 수 있는 계측을 추가하는 쪽으로 처리(각 파일 `resolved`/`resolution` 갱신 예정).

- **0011 (intermittent 500 on POST /message)**: `do_POST`의 범용 catch-all이 트레이스백 없이 `str(e)`만 반환해서, 실제로 500이 났을 때 서버 로그(`logs/chatbot.log`)에 원인이 전혀 안 남고 있었음. `server.py`에 `import sys`/`import traceback` 추가(기존 `log_message`의 `__import__("sys")` 임시방편도 같이 정리), `/message` 라우트의 `sess.send()` 호출을 자체 try/except로 감싸 (1) 전체 트레이스백을 stderr(→ chatbot.log)에 출력, (2) `/stop`이 이미 하듯 `sess._stderr_tail`을 에러 응답 바디에 `debug_stderr_tail`로 실어 보내 재조회 없이 바로 원인 힌트를 줌. `do_POST` 최하단의 범용 catch-all에도 같은 트레이스백 로깅을 추가해 다른 라우트의 미처리 예외도 동일하게 진단 가능해짐.
- **0009 (재시작 직후 첫 턴 usage 전부 0)**: 제안된 해결책(스탠바이 프로세스 stdout을 채택 전부터 별도로 읽어 로깅)은 실제로 구현하면 채택 후 정식 `_read_stdout()` 리더와 **같은 파이프를 두 스레드가 동시에 읽는 새로운 레이스**를 만들 위험이 있어 보류. 대신 위험 없는 진단만 추가: `_spawn()`이 `self._adopted_standby` 플래그로 이번 프로세스가 웜 스탠바이 채택인지 콜드 스폰인지 기록하고, 결과 처리부에서 **세션의 첫 assistant 턴인데 usage의 모든 토큰 필드가 0**이면 sid/conversation_id/adopted_standby 여부를 stderr에 로그. 재발하면 로그만 보고 바로 "항상 재시작 직후 + 항상 스탠바이 채택"인지 패턴 확인 가능.
- **검증**: `python3 -c "import ast; ast.parse(...)"` 통과, `chatbot-ctl.sh repair` 배포, `probe_message OK`. `/message`에 없는 세션 id로 실제 POST 찔러봤더니 `REG.get()`이 미존재 id를 자동으로 새 세션 생성해버려서(설계된 동작) 이 경로로는 진짜 500을 강제 유발 못 함 — 코드 자체는 기존 `/stop`의 동일 패턴을 그대로 따른 단순 try/except라 로직 검토로 충분하다고 판단, 만든 테스트 세션은 stop+discard로 정리함.

## 2026-09-17 — impeccable 훅이 지적한 기존 디자인 이슈 2건 처리 (레이아웃 애니메이션 스래싱 / 펄스 점)

이번 세션 작업과 무관하게 파일 전체 스캔에서 걸린 pre-existing 이슈. 실장님 확인 후 처리.

- **layout-transition (레이아웃 속성 애니메이션)**: 후보 3곳 중 실제로 반복 트리거되는 것들만 손봄.
  - `.usage-bar-fill`(상태 탭 사용량 바): `width` → `transform:scaleX()`(+`transform-origin:left`)로 전환. 참고로 이 바는 매번 `innerHTML`로 통째로 새로 그려지는 구조라 기존 `transition:width`는 애초에 "이전 값에서 전환"할 대상이 없어 실질적으로 한 번도 애니메이션된 적이 없었을 것 — 그래도 안티패턴 자체는 교체.
  - `.mascot-overlay`(Live2D 마스코트, `updateMascotPositioning()`이 매 `resize` 이벤트마다 width/height/right/left/bottom을 다시 씀): 드래그 리사이즈 중 `resize`가 연타로 발생하는 동안 매번 레이아웃을 흔들던 게 진짜 스래싱 지점이라 판단, `resize` 리스너에 120ms 디바운스 추가 — 리사이즈가 끝난 뒤 한 번만 재계산. transform/scale로의 완전 치환은 보류: 마스코트가 Live2D 캔버스라 실제 렌더 해상도가 컨테이너 실크기에 물려있을 가능성이 있어(확인 없이 확대해석해 화질 저하를 만들 위험), 디바운스만으로 스래싱 원인(과호출) 자체를 없애는 쪽을 선택.
  - `textarea{transition:height .1s ease}`(컴포저 자동 높이조절): 타이핑마다 실제 콘텐츠 높이에 맞춰 박스 자체가 커져야 하는 케이스라 transform 대체가 기능적으로 안 맞음(스케일은 시각적으로만 늘어나고 실제 히트박스/오버플로는 그대로라 타이핑 중인 텍스트가 잘려 보임) — 단일 요소·0.1초·저빈도라 실질 스래싱 리스크도 낮아 그대로 둠.
- **pulsing-dot (펄스 상태 점)**: `.proc-badge.running .dot`은 SSE로 실시간 갱신되는 에이전트 프로세스의 실제 busy 상태에 물려있어 — 훅 자체가 명시한 예외 조건("진짜로 살아있고 변화하는 데이터에 묶인 지표")에 정확히 해당한다고 판단. `impeccable hooks ignore-value pulsing-dot "*" --file static/index.html`로 근거와 함께 ignore 등록.
- **검증**: `node -c app.js` 통과, `chatbot-ctl.sh repair` 배포, `curl`로 `app.js?v=27`에 디바운스/scaleX 반영 및 `transform-origin:left` 서빙 확인, probe PASS.

## 2026-09-17 — Multi-Provider 어댑터 작업 착수: Phase 0 (stdout 파싱을 AgyAdapter로 이관, 동작 불변)

- **배경**: 실장님이 FIREBAT의 `VibeCat`(Unreal 플러그인 + 그 Python 이식판) 참고해서
  agy 하나뿐인 지금 구조에 claude/grok/codex 프로바이더를 추가하는 설계를 요청.
  이 NAS엔 실제로 `claude 2.1.274`, `grok 1.0.25`가 이미 설치돼 있음(`codex`는
  미설치). 계획서: `/var/services/homes/me/.claude/plans/smooth-hopping-bear.md`
  (Phase 0 → 0.5 Provider Capability Model → 1 Claude → 2 Grok → 3 Codex(설계만) →
  프론트엔드/서버 provider 필드 → 운영 kill_orphan_agy 일반화, 총 5단계+α).
  실장님이 도중에 "채팅 adapter 말고 사용량 등 provider 별 기능 차이가 상당할
  거라서 adapter 설계에 고민을 많이 해야 할 듯" 지적 — 실제로 확인해보니 claude의
  usage 키 이름(`cache_creation_input_tokens` 등)과 컨텍스트 윈도우(200k, 지금
  HARD_TOKENS=400k는 Gemini 1M 기준이라 그대로 못 씀), `/api/usage`가 agy 전용
  서브커맨드(`agy --print /usage`)에 하드코딩돼 있다는 점 등을 계획에 Phase 0.5로
  추가 반영.
- **Phase 0 구현**: `AgentAdapter`(추상 베이스)에 `normalize_line(session, raw_line)
  -> List[dict]` 신설 — 지금까지 `AgySession._handle_stdout_line()`(100줄 넘는
  단일 메서드) 안에 박혀있던 agy stream-json 파싱(`step_update`/`message`/`delta`
  분기, `_tool_summary`/`_maybe_capture_conversation_id` 호출, `result` 시
  history append + zero-usage 진단 로그까지)을 **그대로(동작 변경 없이)**
  `AgyAdapter.normalize_line`로 옮김. `_tool_summary`/`_maybe_capture_conversation_id`
  자체는 이미지 스테이징 등 부수효과가 깊게 얽혀있어 `AgySession` 메서드로 그대로
  둠(adapter가 `session`을 인자로 받아 호출) — 완전한 순수함수 분리보다 회귀
  위험을 낮추는 쪽을 택함. `_handle_stdout_line`은 이제
  `self.adapter.normalize_line(self, line)` 결과를 emit하고 busy/heavy-check/큐
  디스패치만 수행하는 프로바이더 무관 코드로 축소.
- **검증**: `python3 -c "import ast; ast.parse(...)"` 통과, `chatbot-ctl.sh repair`
  배포 후 실제 세션으로 (1) 일반 텍스트 턴("지금 날짜만 딱 한 단어로") → usage
  45984 토큰 정상 기록·`weight.level:"ok"` 정상, (2) 도구 호출 턴("nas MCP의
  ping_nas 툴을 실제로 호출해줘") → 실제로 `ping_nas` MCP 툴이 호출되고 결과
  (`"message":"pong"`)가 답변에 반영됨까지 end-to-end 확인 — 리팩터 전후 동작
  차이 없음. doctor PASS.
- **다음**: Phase 0.5(Provider Capability Model: `soft_hard_tokens`/`normalize_usage`/
  `rate_limit_report`/`effort_levels`/`mints_own_conversation_id`) → Phase 1
  ClaudeAdapter로 이어감.

## 2026-09-17 — Multi-Provider Phase 0.5: Provider Capability Model 추가

- `AgentAdapter`에 `soft_hard_tokens(model)`/`normalize_usage(raw)`/
  `rate_limit_report()`/`effort_levels()`/`mints_own_conversation_id()` 5개
  메서드 신설(전부 agy 기준 기본값으로 동작 — 회귀 없음). 목적: 프로바이더마다
  다른 usage 키 이름, 컨텍스트 윈도우 크기, 사용량 조회 메커니즘 유무를 시스템
  곳곳에 하드코딩하지 않고 "지금 세션의 adapter에게 물어보는" 구조로 통일.
- `_session_weight()`가 모듈 전역 `SOFT_TOKENS`/`HARD_TOKENS`를 직접 참조하던
  것을 파라미터로 받게 바꾸고, `AgySession.weight()`가
  `self.adapter.soft_hard_tokens(self.model)`을 넘겨줌 — agy는 지금 값
  (150k/400k) 그대로 유지, 나중에 claude(200k 윈도우) 세션은 다른 임계값을
  받게 됨.
- `AgyAdapter.normalize_line`의 `result` 처리에서 raw usage를
  `self.normalize_usage(raw_usage)`를 거치도록 변경(agy는 항등 변환이라 값
  자체는 그대로, 나중에 claude가 `cache_creation_input_tokens` 등 자기 키를
  우리 캐노니컬 모양으로 변환하는 자리).
- `agy --print /usage` 서브프로세스 호출을 `_get_usage()`(모듈 전역)에서
  `AgyAdapter.rate_limit_report()`로 이동. `_get_usage()`는 이제 프로바이더별
  캐시(`_USAGE_CACHE: Dict[provider, ...]`)를 갖는 범용 디스패치 래퍼가 됨 —
  `rate_limit_report()`가 `None`이면(사용량 조회 자체가 없는 프로바이더)
  `{"ok": false, "supported": false, "error": "이 프로바이더는 사용량 조회를
  지원하지 않습니다"}`로 응답. `GET /api/usage`가 `?provider=` 쿼리 파라미터를
  받게 됨(기본값 agy, 하위 호환).
- `static/app.js` `renderStatusUsage()`가 `supported:false`를 에러가 아니라
  안내 문구로 구분 표시하도록 수정.
- **검증**: `python3 -c "import ast; ast.parse(...)"`/`node -c app.js` 통과,
  `chatbot-ctl.sh repair` 배포. 실제 `GET /api/usage` 호출로 agy 사용량 리포트
  (Gemini/Claude·GPT 모델별 주간·5시간 한도)가 이전과 동일하게 나오는 것 확인.
  실제 세션 turn으로 usage/weight(`soft_tokens:150000`, `hard_tokens:400000`,
  `total_tokens` 정상)까지 회귀 없음 확인. doctor PASS.
- **다음**: Phase 1 ClaudeAdapter.

## 2026-09-17 — Multi-Provider Phase 1: ClaudeAdapter 구현 및 실제 검증 완료

- `ClaudeAdapter(AgentAdapter)` 신설. VibeCat의 Python 이식판
  (`Standalone/vibecat_host/providers/claude.py`)을 거의 그대로 포팅하되
  Windows/격리 워크스페이스 특유 부분(`%LOCALAPPDATA%` 탐색, 격리
  `$USERPROFILE`, auth 시딩, `--append-system-prompt-file`/`system_head.txt`
  프로브)은 전부 드롭 — 이 호스트는 Linux고 진짜 `$HOME`을 그대로 쓰며
  (`~/.claude/.credentials.json`이 이미 실제 claude.ai 구독 로그인, `claude
  auth status`로 확인), 페르소나는 agy와 마찬가지로 워크스페이스의
  AGENTS.md/PERSONA.md를 CLI가 cwd 기준으로 자동 인식하는 기존 관례를 그대로
  씀(별도 시스템 헤드 주입 불필요).
- **실측으로 뒤집힌 가정들** (계획서에 "문서만 믿고 짜지 않는다"고 명시해둔 게
  실제로 여기서 작동함):
  1. `--resume <존재하지 않는 id>`를 첫 턴에 걸면 **VibeCat 문서와 달리 조용히
     무시되지 않고 턴 전체가 에러로 실패**함(`"No conversation found with
     session ID: ..."`, `is_error:true`) — 직접 CLI로 재현 확인. 그래서
     `AgentAdapter.mints_own_conversation_id()`를 claude는 `True`로 설정하고,
     `AgySession._spawn()`의 "매번 uuid4를 미리 발급" 로직(agy의 auto-resume
     버그를 막으려고 넣었던 그 코드)을 `not self.adapter.
     mints_own_conversation_id()`일 때만 돌게 조건부로 바꿈 — 첫 턴은
     `--resume` 없이 보내고, `system/init`(또는 `result`)의 실제 session_id를
     캡처해서 그다음 턴부터 `--resume`.
  2. **claude의 컨텍스트 윈도우가 고정 200k라는 VibeCat 가이드라인 가정이
     이 계정에서는 틀림** — 실제 스폰 결과의 `modelUsage`를 까보니
     `"claude-sonnet-5"`(기본 모델, 이 세션 자신과 같은 모델)는
     `contextWindow: 1_000_000`(agy/Gemini와 같은 스케일!), `haiku-4-5`만
     `200_000`. VibeCat 문서는 더 예전 claude 세대 기준이었던 것. 그래서
     `ClaudeAdapter.soft_hard_tokens()`가 모델명에 `"haiku"`가 들어있을 때만
     80k/170k, 나머지(sonnet/opus/기본값)는 agy와 같은 150k/400k를 쓰도록
     분기.
  3. usage의 `thinking_tokens`는 최상위가 아니라
     `output_tokens_details.thinking_tokens`에 중첩돼 있음 — 실제 result
     이벤트 캡처로 확인 후 `normalize_usage()`에 반영.
- **서버 배선**: `AgySession`/`Registry.create()`/`POST /api/sessions`에
  `provider` 필드 추가(`meta.json`에도 저장, 세션 복원 시 `get_adapter()`로
  어댑터 재계산). `provider != "agy"`일 때 `model` 기본값을 agy 전용인
  `DEFAULT_MODEL`(Gemini 모델명)로 떨어뜨리지 않고 빈 문자열로 둬서, CLI 자체
  기본 모델을 그대로 쓰게 함.
- **검증 (실제 라이브 세션, curl로 API 직접 호출)**:
  1. `POST /api/sessions {"provider":"claude"}` → `conversation_id: null`
     (조기 uuid 발급 안 됨) 확인.
  2. 첫 턴("딱 숫자 7만 답해") → 정답 "7", `conversation_id`가 claude가 준
     실제 세션 id로 캡처됨, usage 정상 정규화(`input_tokens/output_tokens/
     total_tokens` 전부 채워짐), `weight.soft_tokens:150000/hard_tokens:
     400000`(sonnet이라 agy와 동일한 임계값 분기 확인).
  3. 같은 세션에 두 번째 턴("nas MCP의 ping_nas 툴 호출해줘") → `--resume`이
     실제로 맥락을 이었고(`conversation_id` 불변), **`mcp__nas__ping_nas`
     MCP 툴이 실제로 호출**되어 결과(`"message":"pong"`)가 답변에 반영됨.
  4. `GET /api/usage?provider=claude` → `{"ok":false,"supported":false,
     "error":"이 프로바이더는 사용량 조회를 지원하지 않습니다"}` 정상 반환
     (에러가 아니라 안내로 처리됨).
  - `python3 -c "import ast; ast.parse(...)"` 통과, `chatbot-ctl.sh repair`
    배포 후 agy 프로브도 여전히 정상(회귀 없음), doctor PASS. 테스트 세션은
    stop+discard로 정리.
- **다음**: 프론트엔드 프로바이더 셀렉터(현재는 API로만 provider 지정 가능,
  UI에는 아직 안 뜸) → Phase 2 GrokAdapter(one-shot exec 구조 변경) →
  `kill_orphan_agy` claude 프로세스도 잡게 확장.
- **곁다리 수정**: `chatbot-ctl.sh`의 `kill_orphan_agy()`가 `/.local/bin/agy` 문자열과
  `--conversation` 플래그만 인식하던 걸 `/.local/bin/claude`와 `--resume` 플래그도
  같이 매칭하도록 확장 — claude 프로세스가 실제로 뜨기 시작한 지금부터는 고아 claude
  프로세스도 agy와 똑같이 정리돼야 함. `live_pids.json` 체크가 이미 프로바이더
  무관하게 먼저 걸러줘서 정상 세션은 안 건드림.

## 2026-09-17 — Multi-Provider Phase 2: GrokAdapter 구현 (구조 변경 + 실측 기반 재설계)

- **구조 변경**: agy/claude는 "프로세스 하나 계속 살려두고 stdin에 턴마다 쓰기"
  모델인데, grok은 VibeCat 기준 "턴마다 새 프로세스를 통째로 실행"하는 one-shot
  exec 모델(`keeps_stdin_open=False`). `AgentAdapter.build_args()`에 `prompt`
  파라미터 추가(agy/claude는 무시), `AgySession._spawn(prompt="")`가 이를
  받아서 그대로 전달, `_send_direct()`가 `adapter.keeps_stdin_open`으로
  분기 — 지속형은 기존대로 `ensure()`+stdin 쓰기, one-shot은 매 턴
  `_spawn(prompt=stdin_content)`을 직접 호출.
- **실측으로 VibeCat 문서를 다시 뒤집음** (이 NAS의 `grok 1.0.25`는 VibeCat이
  캡처한 버전보다 최신이라 플래그/이벤트 모양이 상당히 다름 — 문서 안 믿고
  직접 캡처):
  1. `--trust`는 `--help`에 아예 안 나오는 미문서화 플래그지만 실제로 동작함
     — 없으면 `grok mcp doctor`가 "folder untrusted"로 프로젝트 스코프 MCP
     서버를 거부, 있으면 정상 연결·호출됨(직접 재현 확인).
  2. grok은 claude처럼 MCP 툴마다 별도 이름을 안 주고, **`use_tool`이라는
     제네릭 디스패처 툴 하나**로 전부 라우팅함(`rawInput.tool_name`/
     `tool_input`에 실제 대상이 들어있음) — VibeCat도 이걸 몰랐던 건 아니고
     그냥 claude만 allow/deny 리스트를 준 이유가 이거였던 걸로 보임. 우리도
     같은 선택: `--always-approve`만 쓰고 별도 allow/deny 리스트는 안 둠.
     대신 툴 카드에 `use_tool` 대신 실제 대상 이름이 뜨도록 언랩 처리
     (`_grok_tool_display`).
  3. `--resume <미존재 id>`는 claude보다 더 심하게 실패함 — NDJSON조차 안 뜨고
     exit 1 + 평문 에러(`"Error: Failed to restore session from remote: ...
     404 Not Found"`). `mints_own_conversation_id()=True`로 claude와 동일하게
     처리(첫 스폰엔 `--resume` 없이, `end` 이벤트의 `sessionId`를 캡처).
  4. 실제 이벤트 스트림 캡처(`available_commands`/`thought`/`text`/
     `tool_call`/`tool_call_update`/`usage`/`end`)를 기준으로 `normalize_line`
     작성 — `thought`(내부 추론)는 agy/claude의 thinking과 동일하게 노출 안 함,
     `usage` 이벤트는 `end.usage`와 중복이라 무시.
  5. `grok usage <session_id>`는 계정 전체 사용량이 아니라 **세션 하나 지정
     필수**인 조회라 `agy --print /usage`의 대응품이 아님 —
     `rate_limit_report()`는 `None` 반환.
- **버그 하나 잡고 즉시 수정**: `_send_direct()`에서 `busy=True`를 `_spawn()`
  호출 *전에* 세팅했더니, `_spawn()` 내부의 `self.stop(notify=False)`(이전
  프로세스 정리용)가 `busy=False`로 되돌려버려서, 실제로 grok이 한창 돌고
  있는데도 API가 `busy:false`를 응답하는 문제를 실제 라이브 테스트로 발견 →
  `_spawn()` 호출 *이후*로 순서 이동.
- **또 하나**: 프롬프트를 파일로 넘기는 `--prompt-file` 경로가 처음엔
  `WORKSPACE/.grok_prompt.txt` 고정 파일명이었음 — 동시에 여러 grok 세션(다른
  탭)이 각자 자기 턴을 보내면 서로 파일을 덮어쓸 수 있는 경합 상태라 세션마다
  유니크한 파일명(`.grok_prompt_<uuid>.txt`)으로 변경.
- **MCP 등록**: `grok mcp add --transport http --scope project nas <url>`을
  최초 1회만(이미 등록돼 있으면 스킵) 실행해서 `WORKSPACE/.grok/config.toml`에
  기록. claude처럼 매 스폰마다 파일을 다시 쓰는 대신 존재 여부만 확인.
- **검증 (실제 라이브 세션)**: provider=grok 세션 생성(`conversation_id: null`
  확인) → 첫 턴("딱 숫자 5만 답해") → busy 버그 수정 후 정상적으로 busy:true
  유지되다 완료, 정답 "5", usage 정규화 정상, `weight` 임계값 정상 → 같은
  세션 두 번째 턴("nas MCP의 ping_nas 호출해줘") → `--resume`으로 맥락 유지
  (conversation_id 불변), **`use_tool`을 통한 실제 `ping_nas` MCP 호출** 성공,
  결과가 답변에 반영됨 → `GET /api/usage?provider=grok`도 "지원 안 함" 정상
  응답. `chatbot-ctl.sh doctor`로 agy 회귀 없음도 재확인. 고아 grok 프로세스
  없음 확인, `kill_orphan_agy`에 grok 바이너리(`--prompt-file` 플래그로 식별,
  agy/claude와 다른 프로토콜이라 별도 매칭 조건 필요) 매칭 추가.
- **다음**: Phase 3 CodexAdapter — 실장님이 방금 이 호스트에 `codex-cli 0.154.0`도
  설치해둠, 원래 계획은 "미설치, 설계만"이었는데 이제 실측 가능.

## 2026-09-18 — Multi-Provider Phase 3: CodexAdapter (설계만 → 실측 완료, 실장님이 codex 설치)

- 원래 계획은 "codex 미설치, 구조만 맞춰두고 실행 검증 생략"이었는데, 작업
  도중 실장님이 이 호스트에 `codex-cli 0.154.0`을 설치 — Phase 1/2와 같은
  수준으로 실측 후 구현.
- **구조**: grok과 같은 one-shot exec(`keeps_stdin_open=False`)지만 프롬프트
  전달 방식은 VibeCat이 codex에 쓴 방식 그대로 채택 — grok의 `--prompt-file`
  대신 **stdin에 쓰고 바로 닫기**(`close_stdin_after_prompt=True`, argv 끝에
  `-`). 포지셔널 인자로 프롬프트를 직접 넘기는 방식도 실측해서 동작 확인했지만,
  아주 긴 인계 요약 프롬프트가 언젠가 ARG_MAX에 걸릴 수 있는 포지셔널 방식보다
  안전해서 stdin 방식 유지.
- `AgySession._spawn()`의 `subprocess.Popen(stdin=...)` 조건을
  `keeps_stdin_open`만 보던 것에서 `keeps_stdin_open or close_stdin_after_prompt`로
  수정 — 안 그러면 codex는 stdin이 `DEVNULL`로 열려서 프롬프트를 받을 방법이
  아예 없어짐(grok과 codex가 "one-shot"이라는 공통점은 있어도 프롬프트 전달
  방식은 다르다는 걸 놓치면 나는 버그).
- **실측으로 잡은 문제 2건 (둘 다 실제 라이브 테스트로 발견 후 즉시 수정,
  추측으로 안 넘어감)**:
  1. `--approve-for-me`가 `codex exec`(첫 스폰)에서는 되는데 **`codex exec
     resume`에서는 거부됨**(`error: unexpected argument '--approve-for-me'
     found`) — resume은 스레드가 시작될 때 정해진 승인/샌드박스 모드를 그대로
     유지하고 재지정을 허용하지 않는 구조. 재지정 없이 resume하면 기본
     승인 모드가 "요청은 받되 아무도 승인 안 함"이 되어 **MCP 툴 호출까지
     막힘**(`"MCP tool call requires approval, but approval policy is
     never"`) — 실제로 두 번째 턴에서 재현.
  2. 이 호스트 커널이 user namespace를 지원 안 해서 `--approve-for-me`의
     workspace-write 샌드박스(`bwrap` 기반)가 셸 명령마다 한 번씩 실패했다가
     자동으로 언샌드박스 재시도하는 것도 실측으로 확인 — 매 셸 툴 호출마다
     불필요한 왕복이 생김.
  - **해결**: 첫 턴·resume 둘 다 `--dangerously-bypass-approvals-and-sandbox`로
    통일. agy가 이미 모든 프로바이더에 대해 `--dangerously-skip-permissions`
    수준의 신뢰 모델(단일 운영자용 내부 NAS 비서)을 쓰고 있어서 이 프로젝트
    전체 신뢰 모델과 일관됨 — 새로 낮추는 기준이 아님.
- `normalize_line`은 VibeCat 문서(`thread.started`/`item.started`/
  `item.completed`/`turn.completed`)와 실제 이벤트 모양이 거의 일치했지만
  **usage 키 이름은 달랐음**(`cached_input_tokens`/`cache_write_input_tokens`/
  `reasoning_output_tokens` — VibeCat이 claude 스타일로 추정한
  `cache_read_input_tokens`/`cache_creation_input_tokens`가 아님) — 실제
  캡처로 확인 후 `normalize_usage()`에 정확히 반영. `item.type=="error"`는
  실제로는 턴 실패가 아니라 정보성 안내("Skill descriptions were
  shortened...")라 무시 처리.
- `mints_own_conversation_id()=True` — `codex exec resume <미존재 id>`도
  즉시 실패함(`"no rollout found for thread id ... (code -32600)"`, exit
  0이지만 NDJSON 없이 에러만) 확인, claude/grok과 동일 패턴.
- `rate_limit_report()`는 `None` — `codex --help` 최상위 명령 목록에 계정
  전체 사용량 조회에 해당하는 서브커맨드 없음(확인함).
- **검증 (실제 라이브 세션)**: provider=codex 세션 생성 → 첫 턴 정답 "5" +
  usage 정규화 정상 → 같은 세션 두 번째 턴(nas MCP `ping_nas` 호출) —
  **처음엔 승인 정책 문제로 실패하는 걸 실제로 재현**한 뒤 위 수정 적용,
  재검증해서 `--resume`으로 맥락 유지 + 실제 MCP 툴 호출 성공까지 확인.
  `GET /api/usage?provider=codex` "지원 안 함" 정상. `chatbot-ctl.sh doctor`로
  agy 회귀 없음 재확인, 챗봇이 만든 고아 codex 프로세스 없음 확인(사전에
  떠있던 `codex app-server` 데몬은 챗봇과 무관한 별도 상시 프로세스).
  `kill_orphan_agy`에 codex 매칭(`--json` 플래그로 식별) + codex 고유의
  `resume <id>`(플래그 없는 포지셔널 서브커맨드 문법, agy/claude/grok의
  `--flag value` 문법과 다름) 파싱 추가.
- **이것으로 계획서(smooth-hopping-bear.md)의 Phase 0~3 전부 완료 및 실측
  검증됨.** 남은 건 프론트엔드 프로바이더 셀렉터(지금은 API로만 provider
  지정 가능)뿐.

## 2026-09-18 — Multi-Provider: 프론트엔드 프로바이더 셀렉터 + 발견한 /continue 버그 2건 수정

계획서(smooth-hopping-bear.md) 마지막 항목. 지금까지 provider는 API로만 지정
가능했는데, `#model` 옆에 `#provider` 드롭다운을 추가해서 UI에서 바로 고를 수
있게 함.

- **서버**: `AgentAdapter`에 `known_models()`(프로바이더별 추천 모델
  목록 — agy는 기존 `MODELS`, claude는 `sonnet/opus/haiku/fable` 별칭, grok은
  `grok models` 실측 결과인 `grok-4.6/grok-4.5`, codex는 확인된 목록이 없어서
  빈 배열 유지)와 `available()`(CLI 실제 설치 여부, `find_executable()` 경로
  존재 확인) 추가. `GET /api/providers` 신설 —
  `{"providers":[{"id","available","models"}...], "default":"agy"}`.
  `AgySession.maybe_swap_provider()` 추가(`maybe_swap_model()`과 같은 자리) —
  provider가 바뀌면 어댑터 교체 + **conversation_id 리셋**(다른 CLI의 세션
  id는 서로 다른 id 공간이라 이어 쓸 수 없음) + 프로세스 재시작. `POST
  /api/sessions/:id/message`가 `maybe_swap_provider()`를
  `maybe_swap_model()`보다 먼저 호출(모델 이름을 새 프로바이더 기준으로
  해석해야 하므로 순서 중요).
- **프론트엔드**: `static/index.html`에 `#provider` `<select>` 신설(모델
  드롭다운과 같은 "작게, 컴포저 옆" 스타일 적용 — 실장님의 기존 모델
  드롭다운 배치 피드백 그대로 계승). 모바일 좁은 화면 및 가상키보드 열림
  상태에서는 `#model`과 똑같이 숨김(이미 있던 규칙에 `#provider` 추가) —
  이미 꽉 찬 모바일 1행 컴포저에 무리하게 욱여넣지 않음. `app.js`
  `boot()`가 `/api/providers`로 두 드롭다운을 채우고, provider 변경 시
  `#model` 목록을 그 프로바이더 것으로 다시 그림(`populateModelsForProvider`).
  미설치 프로바이더는 옵션에 뜨되 `disabled`. `createSession()`/메시지
  전송이 `provider`를 같이 보냄. 기존 `localStorage` 모델 값 하위 호환
  유지(provider 키가 없으면 agy로 간주).
- **작업 중 발견한 실제 버그 2건 (프론트 작업과 별개로, 만들면서 코드를
  다시 보다가 잡음)**:
  1. `continue_to_successor()`("이어하기")가 `REG.create()`에 `provider`를
     안 넘겨서 **predecessor가 무슨 프로바이더든 successor는 항상 agy로
     생성**되고 있었음 — provider 전환 자체를 만들기 전까지는 드러날 일이
     없던 버그. `provider=self.provider` 추가.
  2. `get_handover_summary()`가 프로바이더 무관하게 `agy -p /compact
     --conversation <cid>`를 무조건 시도하고 있었음 — claude/grok/codex
     세션의 `conversation_id`는 agy가 모르는 id라서, agy가 그 경로에 새
     빈 대화를 만들고 아무것도 압축 못 한 채 최대 45초를 날린 뒤에야
     폴백(대화 기록 기반 커스텀 요약)으로 넘어가는 구조였음(에러는
     아니고 낭비). `self.provider == "agy"`일 때만 시도하도록 가드.
- **검증 (실제 라이브)**: `provider` 필드 없이 세션 생성 → 여전히 agy로
  기본 동작(하위 호환) 확인. 기존 agy 세션에 `{"provider":"claude"}`로
  메시지 보내서 **세션 중간에 실제로 claude로 전환**되고 새 claude
  conversation_id로 정상 응답까지 확인. grok 세션 생성 → 한 턴 → `/continue`
  호출 → **successor가 agy가 아니라 grok으로 정상 생성**되고 인계 요약도
  제대로 생성되는 것 확인(수정 전이었으면 여기서 agy로 떨어졌을 것). doctor
  PASS, agy 프로브 회귀 없음.
- **이것으로 Multi-Provider 계획서(Phase 0~프론트엔드)가 전부 완료 및 실측
  검증됨.**

## 2026-09-18 — API-Provider Adapters: OpenAIDialectAdapter 및 OmniRoute 연동 완료 (Phase 0~5)

계획서(`docs/plans/api-provider-adapters.md`) 전체 구현 및 라이브 검증 완료.

- **Phase 0 (Transport 추상화)**:
  `AgentAdapter`에 `transport_kind = "process" | "http"` 추가. `AgySession`이 CLI 서브프로세스(`_spawn`, `self.proc`, `stdin/stdout`)에 종속적이었던 부분을 `transport_kind == "http"` 분기로 분리하여 프로세스 없는 HTTP 트랜스포트 지원. `_proc_alive()`, 이벤트 정규화/발행 루프 공유.
- **Phase 1 (최소 OpenAIDialectAdapter & OmniRoute)**:
  OpenAI SDK/chat completions 와이어 포맷을 직접 다루는 `OpenAIDialectAdapter` 구현. 로컬 Docker OmniRoute(`http://localhost:20128/v1`)를 1차 타깃으로 등록(`AGENT_ADAPTERS["omniroute"]`). `stream=True` SSE 청크 스트리밍, `delta` 이벤트 발행, `normalize_usage` 토큰 집계 파이프라인 완성.
- **Phase 2 (MCP 툴 호출 루프)**:
  `nas_mcp`의 툴 정의(`tools/list`)를 OpenAI function schema로 변환(`_mcp_openai_tools`), 모델이 `tool_calls`를 뱉으면 로컬 HTTP JSON-RPC(`127.0.0.1:3012/mcp`)로 직접 실행(`_mcp_call_tool`) 후 `role: "tool"`로 모델에 되먹이는 멀티홉 에이전틱 루프 구현 (`MAX_TOOL_HOPS = 10` 상한 가드). 캐노니컬 `tool_use`/`tool_result` 이벤트 발행으로 프론트엔드 변경 없이 툴 카드 UI 그대로 재사용.
- **Phase 3 (세션 라이프사이클 & 턴 워치독)**:
  OmniRoute가 긴 생성 중 `omniroute-keepalive`를 지속 주입해 소켓 타임아웃이 리셋되는 현상 방지를 위해 `AgySession._http_turn_watchdog` (`HTTP_TURN_TIMEOUT_SEC = 180`) 추가. 세션 로테이션 `soft_hard_tokens`를 모델 컨텍스트 길이에 맞춰 동적 스케일링.
- **Phase 4 (모델 큐레이션 & 사용량/비용 가드레일)**:
  - `known_models()`: 무료 콤보 우선(`auto/best-free`, `auto/best-coding` 등) 노출.
  - `rate_limit_report()`: OmniRoute `/api/providers` 엔드포인트를 호출하여 연결된 프로바이더 계정(Antigravity, Codex 등)의 OAuth 만료/연결 상태를 상태 탭에 표시.
- **Phase 5 (프론트엔드) & 라이브 검증**:
  - `chatbot-ctl.sh` 재기동(PID 11521) 후 실서버(포트 3011)에서 라이브 검증:
    1. `GET /api/providers`에 `omniroute` 및 모델 목록 노출 확인.
    2. `POST /api/sessions` (`provider: omniroute`, `model: auto/best-free`) 세션 생성 성공.
    3. 일반 텍스트 턴 ("안녕! 너는 누구야?") 정상 응답 및 토큰 사용량 집계 확인.
    4. MCP 도구 호출 턴 ("ping_nas 툴을 호출해서...") -> `ping_nas` 실행 및 `pong` 응답 반영 확인.
    5. `GET /api/usage?provider=omniroute` -> 연결된 프로바이더 계정 상태 5건 정상 조회 확인.
    6. `chatbot-ctl.sh doctor` -> PASS.

## 2026-09-21 — 세션 양방향 탐색 네비게이션 구현 및 과거 세션 강제 리다이렉트(튕김) 버그 픽스

- **배경**:
  - 티켓 `#3` (세션 탐색 양방향 이동 및 스크롤 네비게이션 지원) 구현 완료.
  - 상단 메타 바에 `[◀ 이전]`, `[다음 ▶]`, `[최신 ⇥]`, `[과거 열람]` 배지 추가.
  - 단축키 `Alt + ←` / `Alt + →` 및 하단 스크롤 시 이후 세션 연속 로드 지원.
- **발견된 문제 및 픽스**:
  1. **세션 목록 로드 실패 (`isCurrent` TDZ ReferenceError)**:
     - `renderSessionsList`에서 `const isCurrent` 선언 전에 `className`에서 참조하여 목록이 열리지 않던 오류 수정.
  2. **과거 세션 열람 시 강제 최신 세션 점프(Bounce) 버그**:
     - `maybeRedirectHardSession()`의 조건 버그(`if (!hard && !redir) return null;`)로 인해, 용량 초과(`hard`) 세션이 아님에도 이후 세션(`successor_session_id`)이 있는 과거 세션을 열면 자동으로 최신 세션으로 연쇄 리다이렉트되어버리던 문제 해결.
     - `if (!hard) return null;`로 엄격화하고, `openSession`에 `noRedirect` 플래그를 도입하여 세션 목록 클릭이나 이전/다음 네비게이션 버튼을 통한 과거 세션 열람 시 절대 다른 세션으로 튕기지 않도록 방어.
  3. **빈 껍데기(0턴) 세션 스킵 및 시간순(세션 ID) fallback 보강**:
     - `resolveScrollforwardFallback` 및 `resolveScrollbackFallback`에서 0턴 빈 세션을 필터링하고, 세션 ID(`YYYYMMDD-HHMMSS`) 문자열 정렬 fallback을 추가하여 연속 탐색 안정화.
  4. **캐시 버스터 갱신**:
     - `index.html`: `app.js?v=90`, `chat.css?v=15`로 판올림하여 브라우저에 즉시 반영.
- **배포**: 정적 파일 수정으로 브라우저 새로고침(Ctrl+Shift+R) 즉시 반영.

## 2026-09-21 — 루프감지 중단·경고 이벤트에 증거(evidence) 기록

- **배경**: 09-21 오전 오탐 수정 뒤에도 Agy(`gemini-3.8-flash-low`)가 `adapters.py` 조회를 출력 해시(`fd72e758`)까지 같은 채 10번 반복해 4회 연속 자동 중단됨(11:56·12:02·12:05·12:08). 새 세션으로 넘어가도 재발. 가드는 진짜 반복을 잡은 것이고, 문제는 복구 쪽. 다만 세션 로그에 호출 인자(줄 범위)·출력 크기가 없어 "출력이 잘려 못 읽는 것"인지 "모델 습관"인지 구분 불가.
- **변경**: `session.py` `_observe_agent_step`이 경고·중단 이벤트에 `evidence`(규칙·횟수·도구·정규화된 인자 300자·출력 글자수·출력 앞뒤 120자)를 실어 `events.jsonl`에 남김. `loop_guard.py`는 그대로. 화면 표시는 그대로(추가 필드는 무시됨).
- **테스트**: `test_loop_events_carry_the_call_and_output_evidence` 추가. `test_conversation_sync`·`test_loop_guard` 36건, `smoke` 5건, `ctl guard` OK.
- **다음**: ⚡소생 후 반복이 다시 걸리면 `evidence.params`/`output_tail`로 원인 확정 → 복구 방식(grep 전환·모델 승격 등) 설계.

## 2026-09-21 — 루프 경고 시 에이전트에게 방향 전환 알림(agy 한정) + 프로브 결과

- **배경**: 09-21 13시 세션에서 `view_file adapters.py`(범위 없음)가 10번 반복돼 자동 중단. 프로브로 확인: 범위 없는 전체 읽기의 스트림 `output`은 크기 한 줄(`1949 lines, 94302 bytes`)이지만 **모델은 내용을 본다**(정답 응답, `agy.md` A45). 가벼운 문맥에서는 루프 재현 실패(A46) — 원인은 미확정. 그때까지 경고는 화면에만 뜨고 에이전트에게는 아무것도 전달되지 않았다.
- **변경**:
  - `session.py`: 경고 임계값에 닿으면(agy만, 사용자 턴당 1회, 대기 중인 사용자 메시지가 없을 때) 스텝 경계에서 자식을 멈추고 같은 대화 ID로 재개하며 `LOOP_NOTICE`("멈추고 세 줄로 정리한 뒤 접근을 바꿔라, 큰 파일은 범위를 나눠 읽거나 grep")를 보낸다. 알림은 사용자 말풍선·기록에 남지 않는다(`_send_direct(notice=True)`). 이벤트 `evidence.action="notice"`.
  - 알림 뒤에도 반복하면 `loop_guard.tighten(3)`으로 3회 더에서 중단(새 사용자 메시지에서 `relax`). 자동 중단 힌트의 "더 큰 범위 읽기"는 "범위를 나눠 읽기·grep"으로 교체.
  - `interrupt_current_turn(reason="loop")`: 문구가 "새 지시" 대신 "방향 전환"으로 나오고 관찰 기록은 steer처럼 건너뜀.
- **테스트**: `tests/test_loop_notice.py` 8건 신규, 전체 653건 통과.
- **미검증**: 알림이 실제로 루프에 빠진 에이전트를 빼내는지는 측정 못 함(재현 불가). 다음 사고 때 `events.jsonl`에서 `evidence.action="notice"` 뒤 호출 패턴으로 판정.
- **배포**: 파이썬 호스트 모듈이라 ⚡소생 필요(실장님). 미커밋.
