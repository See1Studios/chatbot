# Private Engine (가칭) — chatbot

**진입장벽이 매우 낮은 프리메이드 개인화 하네스.** 설치하면 완성된 캐릭터가 바로 곁에 있고, 쓰면서 캐릭터·기억·외형·목소리·규칙을 내 취향대로 쌓아 간다. 모델은 이미 쓰는 AI 구독·CLI·API 키를 연결한다(BYOK).

포지션은 Wallpaper Engine의 자리다. 배경화면 대신 에이전트를 커스터마이즈한다. 기조는 [docs/CONCEPT.md](CONCEPT.md), 제품 결정은 [PRODUCT.md](./PRODUCT.md), 구조는 [ARCHITECTURE.md](../ARCHITECTURE.md).

**상태**: 동작하는 POC(멀티 프로바이더 채팅, 캐릭터 카드·기억, 사적 모드, ST 카드 가져오기, 스프라이트 연출). 제품화 진행 중 — [docs/plans/INDEX.md](plans/INDEX.md)에서 [direction-alignment.md](plans/direction-alignment.md)와 [release-pipeline.md](plans/release-pipeline.md)부터.

**에이전트 입구 — 루트 [`AGENTS.md`](../AGENTS.md). 규칙은 [`RULES.md`](../RULES.md), 코드 지도는 [`CODEMAP.md`](../CODEMAP.md).** 여기에 따로 적지 않는다.

| 무엇 | 어디 |
|---|---|
| 최근 작업 | [docs/DEVLOG.md](DEVLOG.md) (지난 날짜는 `docs/devlog/YYYY-MM-DD.md`) |
| 계획과 상태 | [docs/plans/INDEX.md](plans/INDEX.md) |
| 캐릭터·역할·기억 | `data/workspace/characters/`, `roles/`, `team.json`, `memory/` (설명은 PROJECT.md) |
| 헌장 | 엔진 개발: [`AGENTS.md`](../AGENTS.md) · PE 챗 에이전트: `templates/workspace/AGENTS.md` · 호스트 법: `~/AGENTS.md` |

## 개발 설치 (DiskStation)

지금은 운영자 한 명의 Synology NAS에서 돈다. 사용자 데이터는 아직 저장소 옆 `data/`에 있고, 배포판에서는 `~/.pe`로 옮긴다([user-data-separation.md](plans/user-data-separation.md)).

- `http://diskstation:3011/` — API + 전체 창
- `http://diskstation/chat/` — 숏컷
- `http://diskstation/` — Sphere Hub(이 NAS의 허브 홈) FAB 팝업

```bash
~/services/chatbot-ctl.sh status
~/services/chatbot-ctl.sh restart
```

## Run tests

- Python 3.8+, 노드 테스트(UI 하네스)에는 `node` v20+. NAS 전용 테스트는 형제 `../chatbot-ctl.sh`가 있을 때만 돈다.
- **기본은 모듈별 실행**(실패가 그 모듈에 머물고 모듈별 시간이 보임). split/A(2026-10-02) 뒤로는 전체를 한 프로세스에서 돌려도 통과한다 — 모듈이 전역이나 환경 변수를 바꾸고 안 되돌리면 뒤 모듈이 깨지므로, 그런 변경을 찾을 때 `--one-process`.

```bash
engine/run-tests.sh                      # 전체 (모듈별 한 프로세스, 실패 시 종료 코드 1)
engine/run-tests.sh --fast               # 가드 테스트만 (커밋 훅용, 목록은 스크립트 FAST)
engine/run-tests.sh test_identity_wiring # 하나만
engine/run-tests.sh --one-process        # 전체를 한 프로세스에서 (격리 확인, 약 5분)
```

테스트를 도는 방법은 `engine/run-tests.sh` 한 곳뿐이다. 훅·위임 러너 게이트·CI도 이 스크립트를 부른다.

클론마다 한 번 커밋 훅을 켠다: `git config core.hooksPath .githooks` (가드 테스트·비밀 검사·커밋 메시지 형식).
