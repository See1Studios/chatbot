# Chatbot 비상 수리 (EMERGENCY)

실장님이 「챗봇 망가짐」이라고 할 때. `healthz`만 보면 데드락을 놓친다.

## 한 줄
```bash
~/services/chatbot-ctl.sh repair
```

## 명령
| 명령 | 용도 |
|------|------|
| `doctor` | healthz + RLock 소스 가드 + (1시간마다, `PROBE_EVERY_SEC`) 메시지 프로브 |
| `doctor --auto-repair` | 프로브 실패 시 자동 `repair` (워치독이 이걸 씀) |
| `probe` | 지금 당장 POST `/message` 타임아웃 검사 |
| `repair` | stop → orphan agy 정리 → start → 강제 프로브 |
| `guard` | `AgySession.lock`이 `RLock`인지 AST 검사만 |

## 알려진 고장 모드
1. **메시지 데드락** (2026-09-16): `ensure`가 `Lock` 보유 중 `_spawn`→`stop`이 같은 락 재획득. 증상: healthz OK, 전송 무한 대기. 수정: 세션 락=`RLock`. 가드=`ctl guard`.
2. **고아/프로브 agy**: PPID=1 orphan + doctor flash-low(대개 `--conversation` 없음). `repair`/`doctor`의 `kill_orphan_agy`가 PPID=1·no-conversation·비보호 flash-low를 정리. probe는 `stop`+`/discard` 후 한 번 더 prune.
3. **서버 다운**: 워치독 1분마다 `doctor --auto-repair` (예전엔 `start`만이라 2번을 못 잡음).

## 로그
- `~/services/chatbot.log` — HTTP
- `~/services/chatbot-doctor.log` — doctor/repair 이벤트

## 관련
- 자기수정 경계: `SELF-MODIFY.md` (라이브 뇌수술 vs 디스크 설계도)
