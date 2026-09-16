# 자기수정 경계 (Self-modification boundary)

실장님·GameDeveloper 합의 (2026-09-16). 이 문서는 **강제 규칙**이다.

## 한 줄
자기강화는 허용한다. 단 **실행 중인 자기 머리를 연 채로 수술하지 말 것**.
디스크에 설계도를 쓰고, 가드·외부 프로브로 검증하며, 라이브가 죽으면 바깥 의사에게 넘긴다.

## 비유를 코드로
| 비유 | 이 프로젝트에서 |
|------|----------------|
| 꾸미기 (옷·방) | 페르소나, UI 카피, 스타일, 갤러리, 로그 뷰 |
| 내일의 자기에게 편지/설계도 | `server.py` / `static/` / ctl / skill 파일을 **디스크에** 수정 → 재기동 후 적용 |
| 뇌수술 (하면 안 됨) | **지금 이 턴의** 추론·락·stdin/SSE·기동 경로가 이미 죽은 채로, 그 죽은 경로로 자기 코어를 패치하려 함 |

편집자(파일 쓰는 에이전트) ≠ 실행 중 뇌(지금 떠 있는 `server.py`/`agy` 프로세스).
재기동 전에는 새 코어가 “나”가 아니다. 그래서 코어 수정도 **개념적으로 성립**한다 — 다만 라이브 루프 자가수술은 성립하지 않는다.

## 해도 되는 것 (자기강화 OK)
- UI / 페르소나 / 문서 / skill 관찰 로그
- 호스트·정적 자산·FAB 동기화 (허브 `AGY_CHAT_FAB_*` + `:3011` 둘 다)
- 코어 코드 변경 **단**, 디스크 편집 → smoke(`ctl doctor`/`probe`/healthz) → `docs/DEVLOG.md` 기록
- `AgySession.lock`은 **반드시 `threading.RLock`** 유지 (`ctl guard`가 AST로 검사). `Lock`으로 되돌리지 말 것

## 하면 안 되는 것 (외부 의사 몫)
- 전송이 이미 무한 대기/데드락인 상태에서, 그 세션만으로 락·프로토콜·`ensure`/`_spawn`/`stop`을 “고쳤다”고 끝내기
- `healthz`만 보고 정상 판정 (메시지 경로 장애를 놓침)
- 라이브 프로세스 메모리를 직접 뜯거나, 죽은 stdin에 치료를 주입
- 포트 변경 / 세션·페르소나 일괄 삭제 등 파괴적 작업 (실장님 승인)

이런 증상 → **즉시** `~/services/chatbot-ctl.sh repair` 또는 실장님/GameDeveloper(비상 복구)에게 넘긴다.
카드: `/volume1/homes/me/services/chatbot/docs/EMERGENCY.md`

## 작업 체크리스트 (코어 만질 때)
1. task-observer Session Start
2. 변경이 “디스크 설계도”인지 “라이브 뇌”인지 한 줄로 구분
3. 패치 후: `chatbot-ctl.sh guard` + `doctor` 또는 `probe` (메시지 경로)
4. Hub FAB와 전체 창 드리프트 확인
5. DEVLOG 한 블록 + skill-observations 한 줄

## 위임
- 일상 UI/호스트/페르소나/hook: 이 챗봇 (`chatbot-self-improve`)
- 라이브 사망·데드락·워치독/ctl 비상: `EMERGENCY.md` + 필요 시 GameDeveloper

## ADD_DIRS 정책 (latency)
- 스폰 시 `--add-dir`는 **좁게**: `services/chatbot`, `services/chatbot-data`, `/volume1/web/chat`.
- 전체 home / `.hermes` / 전체 `/volume1/web` / 전체 `services` 넣지 말 것 (컨텍스트·기동 비용).
- 자기개선에 추가 경로가 필요하면 DEVLOG에 사유를 남기고 최소 경로만 추가.


### 절대 금지 — 라이브 자기 restart
- 진행 중인 대화/도구 루프에서 `chatbot-ctl.sh restart|stop` 또는 자기 포트 바인딩 재기동 **금지**.
- 재시작이 필요하면 사용자(또는 GameDeveloper)에게 `repair` 요청. 라이브 self-restart는 SSE·agy stdin 단절로 “응답 없음”을 만든다.

- `chatbot-ctl.sh stop|restart` hard-blocked unless `CHATBOT_FORCE_HOST=1` (repair/watchdog only).


## Host restart — hard rule for self-improve
- NEVER run `chatbot-ctl.sh stop|restart|repair|defibrillate` from a live chat turn.
- NEVER export `CHATBOT_FORCE_HOST=1` yourself — it still fails without a short-lived ticket only repair/⚡소생 can mint.
- Static UI (`app.js`, hub `index.html`, css): edit + hard-refresh browser. **No host restart.**
- `server.py` / `nas_mcp.py` changes: finish edits on disk, tell 실장님 to press **⚡소생** (or GameDeveloper). Do not self-restart.
- If connection dies mid-task: stop host surgery; summarize what is done on disk; ask for ⚡소생.
