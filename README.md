# chatbot

Sphere Hub용 DiskStation 채팅 에이전트 호스트. 캐릭터와 업무·사적 관계를 이어 가는 캐릭터 에이전트(개념: [docs/concept.md](./docs/concept.md)).

**에이전트 입구 — 코드 지도·엔진 규칙·정본 지도는 루트 [`AGENTS.md`](./AGENTS.md) 한 곳뿐이다.** 여기에 따로 적지 않는다.

| 무엇 | 어디 |
|---|---|
| 최근 작업 | [docs/DEVLOG.md](./docs/DEVLOG.md) (지난 날짜는 `docs/devlog/YYYY-MM-DD.md`) |
| 계획과 상태 | [docs/plans/INDEX.md](./docs/plans/INDEX.md) |
| 캐릭터·역할·기억 | `data/workspace/characters/`, `roles/`, `team.json`, `memory/` (설명은 PROJECT.md) |
| 헌장 | 엔진 개발: [`AGENTS.md`](./AGENTS.md) · PE 챗 에이전트: `data/workspace/AGENTS.md` · 호스트 법: `~/AGENTS.md` |

## URL

- `http://diskstation:3011/` — API + 전체 창
- `http://diskstation/chat/` — 숏컷
- `http://diskstation/` — Hub FAB 팝업

## 운영

```bash
~/services/chatbot-ctl.sh status
~/services/chatbot-ctl.sh restart
```

## Run tests

- Python 3.8+, 노드 테스트(UI 하네스)에는 `node` v20+, `tests/test_nas_mcp_host.py`는 형제 디렉터리 `../nas-mcp/`.
- **모듈별로 돌린다.** 한 프로세스(`unittest discover`)는 몇 모듈이 전역을 되돌리지 않아 실패한다.

```bash
./run-tests.sh                      # 전체 (모듈별 한 프로세스, 실패 시 종료 코드 1)
./run-tests.sh --fast               # 가드 테스트만 (커밋 훅용, 목록은 스크립트 FAST)
./run-tests.sh test_identity_wiring # 하나만
```

테스트를 도는 방법은 `run-tests.sh` 한 곳뿐이다. 훅·위임 러너 게이트·CI도 이 스크립트를 부른다.

클론마다 한 번 커밋 훅을 켠다: `git config core.hooksPath .githooks` (가드 테스트·비밀 검사·커밋 메시지 형식).
