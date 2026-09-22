# 자기수정 경계 (강제)

실장님·GameDeveloper 합의 (2026-09-16). 자기강화는 허용하되 **실행 중인 자기 머리를 연 채로 수술하지 않는다.**
디스크에 설계도를 쓰고, 가드·외부 프로브로 검증하고, 라이브가 죽으면 바깥 의사(`repair`/실장님)에게 넘긴다.

## 구분
- **디스크 설계도 (OK):** `server.py`·`session.py`·`adapters.py`·`instructions.py` 등 호스트 코드, `static/`, ctl, 스킬, 페르소나·문서. 수정하고 재기동해야 새 코어가 "나"가 된다.
- **뇌수술 (금지):** 지금 이 턴의 추론·락·stdin/SSE·기동 경로가 이미 죽은 채로, 그 죽은 경로로 코어를 패치. 프로바이더와 무관하다 — stdin 단절이든 one-shot 재실행이든 라이브 턴에서 호스트를 죽이면 "응답 없음"이 된다.

## 하드 룰
1. 대화·도구 루프에서 `chatbot-ctl.sh stop|restart|repair|defibrillate` 금지. `CHATBOT_FORCE_HOST=1` 무단 export 금지 (repair/⚡소생만 짧은 티켓을 발급).
2. 정적 UI(`static/`·페르소나): 수정 + 강력 새로고침. 호스트 재시작 없음.
3. 파이썬 호스트 모듈(`server.py`/`session.py`/`adapters.py`/`host_config.py`/`instructions.py`/`tool_format.py`/`mcp_server.py`): 디스크 수정 후 실장님께 **⚡소생**. 자가 재기동 금지.
4. `AgySession.lock`은 `threading.RLock` 유지 (`ctl guard`가 `session.py`를 AST 검사). `Lock`으로 되돌리지 말 것.
5. 포트 변경, 세션·페르소나 일괄 삭제는 실장님 승인.
6. 연결이 죽으면 호스트 수술을 멈추고, 디스크에 끝난 것만 요약하고 ⚡소생을 요청한다.

## 이렇게 판정하지 말 것
데드락 세션만 보고 락·프로토콜·`ensure`/`_spawn`/`stop`을 "고쳤다"고 끝내기 · `healthz`만 보고 정상 판정(메시지 경로를 놓침) · 라이브 메모리 조작 · 죽은 stdin에 치료 주입.
증상이 있으면 `~/services/chatbot-ctl.sh repair` 또는 실장님께. 카드는 `docs/EMERGENCY.md`.

## 코어 체크리스트
1. 변경이 디스크 설계도인지 라이브 뇌인지 한 줄로 구분
2. `chatbot-ctl.sh guard` + `doctor` 또는 `probe`
3. Hub FAB와 전체 창 드리프트 확인
4. `docs/DEVLOG.md` 한 블록 + `observation-log/` 한 줄
