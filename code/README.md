# chatbot

Sphere Hub용 DiskStation 채팅 에이전트 호스트.

캐릭터와 분리된 **범용 프로젝트**. 기본 페르소나는 냥피디 (`config/persona.json`).

**유지보수 1순위: 이 챗봇 자신.** 자세한 이력은 [docs/DEVLOG.md](./docs/DEVLOG.md).

## 구성

| 경로 | 역할 |
|------|------|
| `server.py` | 지속 `agy` 세션 호스트 (:3011) |
| `nas_mcp.py` | NAS MCP (:3012) |
| `static/` | 전체 창 UI (+ `vendor/` marked·mermaid) |
| `config/persona.json` | 활성 페르소나 메타 |
| `../chatbot-data/` | 세션·아티팩트·워크스페이스·페르소나 |
| `../chatbot-ctl.sh` | start/stop/restart/status |

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

워크스페이스: `../chatbot-data/workspace/`

- skill `chatbot-self-improve` — 이 프로젝트 패치
- skill `task-observer` — 관찰 로그 (hook PreInvocation)
- `PROJECT.md`, `AGENTS.md`, `skill-observations/`

실장님이 버그를 말하면 챗봇이 여기 코드를 읽고 고친 뒤 DEVLOG에 한 줄 남긴다.
