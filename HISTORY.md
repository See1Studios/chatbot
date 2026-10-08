# History

작업 기록이다. 새 것이 위, 눈에 띄는 변경마다 한 블록(무엇을, 왜, 재시작이 필요한지). 지난 날짜는
`docs/history/<날짜>.md`로 넘어간다(`engine/tools/history_entry.py`가 위임 작업의 줄을 쓰고, 크기가 넘치면 옮긴다).
릴리스는 아직 없다(`engine/VERSION` 0.0.0-dev, 태그 없음). 릴리스 때 사용자용 `CHANGELOG.md`를 커밋에서 만든다
(`RULES.md` Release). 2026-10-08까지 이 파일은 `DEVLOG.md`, 릴리스 메모는 `CHANGELOG.md`였다.
2026-10-07 기록은 하루 예산을 넘어 [docs/history/2026-10-07.md](docs/history/2026-10-07.md)로 회전했습니다.
2026-10-08 기록은 하루 예산을 넘어 [docs/history/2026-10-08.md](docs/history/2026-10-08.md)로 회전했습니다.

## 2026-10-09 — 로그 원본을 덮어쓰지 않고 압축 보관 90일 (telemetry tl/B, #837)

- **운영자**: "계속합시다" (D1 원본 90일 추천대로)
- **바뀐 것**: 회전에서 `.5` 뒤로 밀려나는 로그 파일을 `logs/archive/`로 옮기고(이름 바꾸기라 쓰는 쪽을 막지 않음), 오래 도는 프로세스의 백그라운드 스레드가 한 시간에 한 번 gzip 압축·90일 지난 것과 1GB 넘는 것 정리(`log.archive`). `logdigest`는 긴 기간이면 보관본도 읽는다. 계획의 "7일뿐" 서술은 착오여서 바로잡음(실제 50–60일 뒤 덮어씀, 09-23부터 전부 남아 있음).
- **집행**: `test_telemetry_archive`.
- **재시작**: 필요 (`obslog`).

## 2026-10-09 — 로그 시스템을 기능 패키지로: `engine/telemetry/` (telemetry tl/A, #836)

- **운영자**: "로그 시스템도 대형 피쳐로 별도 분리해서 개발" · "feature 별로 모듈이나 패키지를 만들어서 정리" · D1–D4 "추천대로"
- **바뀐 것**: `obslog.py`·`logdigest.py`를 `engine/telemetry/`로(이름 유지, `from telemetry import obslog`). `chatbot-ctl.sh`(emit·logs), 보호 경로·Tier 3 항목, 가드가 따라감. 엔진 루트 모듈 수 상한(`test_code_layout` `TOP_LEVEL_MAX` 69, 늘릴 수 없음). 가드 7곳이 따로 들고 있던 코드 폴더 목록을 `tests/_paths.py` `CODE_DIRS` 하나로.
- **재시작**: 필요 (서버가 옮긴 모듈을 다시 읽어야 함). `chatbot-ctl.sh logs`는 바로 새 경로.

