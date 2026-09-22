---
name: role
description: 서예린/시우/아이리스/SimCore 대화·롬플레잇 시뮬레이션 및 대사 추출 스킬. 호감도/스트레스 상태 추적. (키워드: 서예린, simcore, 캐릭터챗, /role)
---

# Role 스킬 (자체 독립 엔진)

## 개요
외부 `character-chat` 웹 서비스(포트 3013)나 외부 엔진과 완전히 분리되어, **우리 챗봇 전용 provider 및 SimCore 상태 머신**을 사용해 캐릭터 롬플레잇과 대사 추출을 수행하는 독립 스킬입니다.

## 아키텍처 및 자산
- **자체 엔진**: `data/workspace/.agents/skills/role/engine.py` (독립 실행 및 세션 관리)
- **자체 세션 저장소**: `data/workspace/.agents/skills/role/sessions/*.json`
- **캐릭터 카드**: `~/data/characters/*.yaml` (`yerin.yaml`, `siwoo.yaml`, `iris.yaml` 등)
- **사용 Provider**: 챗봇 기본 provider (`agy`, `gemini-3.8-flash-low` 등)

## 사용 방법 (CLI 직접 실행)
실행 시 작업 디렉터리는 반드시 `~/services/chatbot` 기준이어야 합니다.

### 1. 캐릭터 상태 조회
```bash
python3 ~/services/chatbot/data/workspace/.agents/skills/role/engine.py yerin --status
```

### 2. 새 세션 시작 및 대화
```bash
python3 ~/services/chatbot/data/workspace/.agents/skills/role/engine.py yerin "예린 씨, 오늘 연구 진행 상황은 어때요?"
```
- JSON 형태로 `dialogue`(대사), `thought`(속마음), `state_delta`(수치 변화량), `state`(현재 호감도/스트레스/기분), `session_id`가 출력됩니다.

### 3. 기존 세션 이어하기
```bash
python3 ~/services/chatbot/data/workspace/.agents/skills/role/engine.py yerin "그렇군요, 커피 한 잔 마시면서 계속하죠." --session <SESSION_ID>
```

## 출력 및 대화 원칙
1. **표정 태그 보존**: 출력 대사 시작 부분의 `[expression: neutral|joy|shy|serious|sorrow|tired]` 태그를 그대로 살려 실장님께 보여줍니다.
2. **속마음 및 SimCore 상태 보고**: 대화 후 3rd Deep POV 속마음(`thought`)과 호감도/스트레스 변화를 실장님께 요약 전달합니다.
3. **독립성 유지**: 냥피디의 운영 비서 정체성과 캐릭터 대화 공간을 분리하여 시뮬레이션을 진행합니다.
