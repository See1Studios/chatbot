# chatbot

Sphere Hub용 DiskStation 채팅 에이전트 호스트.

캐릭터와 분리된 **범용 프로젝트**. 기본 페르소나는 냥피디, SSOT는 [`data/workspace/PERSONA.md`](./data/workspace/PERSONA.md) 하나뿐(`ADD_DIRS`로 agy에 직접 노출되는 실제 시스템 컨텍스트).

**유지보수 1순위: 이 챗봇 자신.** 최대 가치·목표는 [docs/concept.md](./docs/concept.md). 이력은 [docs/DEVLOG.md](./docs/DEVLOG.md).

## 구성

작업 위치는 [`data/workspace/PROJECT.md`](./data/workspace/PROJECT.md) **Where to edit**.

| 경로 | 역할 |
|------|------|
| `server.py` | HTTP 엔트리 (:3011). `session.py` / `adapters.py` / `host_config.py`를 로드 |
| `mcp_server.py` | MCP 도구 서버 (:3012, 서버 이름 `nas`). 코어 도구는 `mcp_core.py`, 이 NAS 전용은 `nas_mcp_host.py` |
| `static/` | 전체 창 UI. `app.js`가 세션/SSE, 나머지는 theme/markdown/artifacts/slash |
| `data/workspace/PERSONA.md` | 페르소나 SSOT |
| `data/` | 세션·아티팩트·워크스페이스·페르소나 이미지 |
| `chatbot-ctl.sh` | start/stop/status/probe/repair. `~/services/chatbot-ctl.sh`와 동일 |

## URL

- `http://diskstation:3011/` — API + 전체 창
- `http://diskstation/chat/` — 숏컷
- `http://diskstation/` — Hub FAB 팝업

## 운영

```bash
~/services/chatbot-ctl.sh status
~/services/chatbot-ctl.sh restart
```

## 자기개선

워크스페이스: `data/workspace/`

- 관찰: 호스트가 소유 (`evolution.py`·`observations.py`, MCP `observation` 도구, 슬래시 `/review`). 로그는 `skill-observations/`
- `PROJECT.md`, `AGENTS.md`, `PERSONA.md` (제품 헌장·페르소나; 호스트가 첫 턴에 지침 묶음으로 주입. 호스트 법은 `~/AGENTS.md`)
- 하네스: `adapters.py` `AGENT_ADAPTERS` (`agy` 기본, `claude`, `grok`, `codex`, `omniroute`)
- 장기 기억: `data/workspace/memory/MEMORY.md` (규칙은 코어 `memory_store.py`; MCP `memory` 도구 또는 `python3 tools/memory.py show|add|search|forget`)
- `skill-observations/observation-log/`

실장님이 버그를 말하면 챗봇이 여기 코드를 읽고 고친 뒤 DEVLOG에 한 줄 남긴다.

## 정체성 (이름·직책·호칭)

챗봇의 이름·직책·호칭은 코드에 없고 **지침 파일 머리말**에서 나온다 (`identity.py`, 설계는
`docs/plans/chatbot-host-portability.md` Phase 3):

| 키 | 파일 | 뜻 |
|---|---|---|
| `title` | `data/workspace/AGENTS.md` | 직책 — 화면 상단 제목 |
| `persona` | `data/workspace/PERSONA.md` | 캐릭터 이름 (선택; 아바타 표기·대화 라벨·프롬프트에 쓰임) |
| `user_title` | `data/workspace/PERSONA.md` | 사용자 호칭 |
| `voice` | `data/workspace/PERSONA.md` | 호스트가 만드는 짧은 프롬프트의 말투 한 줄 |

성격·말투 본문은 `PERSONA.md` 본문에 쓴다. 새 설치에서 `PERSONA.md`가 없으면 `templates/PERSONA.md`가 복사된다.
