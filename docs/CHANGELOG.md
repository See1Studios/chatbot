# 변경 기록

아직 배포하지 않았다. 버전은 `engine/VERSION` 한 줄(`0.0.0-dev`)이다. 코드는 그 파일을 읽지 않는다. git 태그는 아직 없고, 릴리스 절차는 `RULES.md`의 Release 절이다.

## 0.0.0-dev — 2026-10-03

- 사용자 데이터 기본 경로는 `~/.pe`다. 이 NAS는 커밋하지 않는 `data-pin.env`로 그 경로를 가리킨다.
- `data/`에 새로 생기는 파일은 git이 무시한다. 개발 티켓 기록(`data/workspace/skill-observations/`)만 예외다.
- 개인 파일(`MEMORY.md`, `secrets.env`, 세션)은 로컬 인덱스에 없다. origin 이력에는 예전 개인 데이터가 남아 있고, 푸시하지 않는다.
- 비밀 자리표시는 루트 `secrets.env.example`이다. 값은 비어 있다. 부트스트랩이 `templates/secrets.env.example`을 복사하는 일은 아직 아니다.
