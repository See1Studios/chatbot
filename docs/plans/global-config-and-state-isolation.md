# 글로벌 설정과 상태 격리: config.json 통합 및 state/ 격리 (global-config-and-state-isolation)

> 방향 (align/D, 2026-10-10): **기반 + 핵심** — 파편화된 설정 파일들을 단일 config.json으로 일원화하고 런타임 상태 파일을 state/ 디렉토리로 격리하여 사용자 데이터 루트 깔끔화 및 이식성 확보
> 선행 사례: `~/.hermes/hermes-agent/` (Hermes Agent). Hermes는 사용자 홈(`~/.hermes/`)에 단일 `config.yaml`(설정)을 두고, 런타임 프로세스 및 데이터베이스는 명확히 분리 관리한다. 따른다: 설정의 단일 문서화(Single config file) 및 설정/상태 분리 원칙. 다르게 간다: YAML 대신 Private Engine의 표준인 JSON(`config.json`)을 사용하며, 무분별하게 루트에 흩어지던 PID/Lock/상태 파일들을 전용 격리 디렉토리(`state/`)로 완전히 격리 수납한다.
> 상태: **active** (2026-10-10 수립, 초안)
> 목적: `~/.pe` 루트에 흩어져 있는 설정 파일(`team.json`, `providers.json`, `events.json`, `items.json`)과 런타임 상태 파일(`*.pid`, `*.lock`, `live_pids.json`, `account_state.json`, `delegation_seen.json`, `work_talk.json`, `push_*.json`)을 정리하여, 사용자 데이터 루트를 핵심 선언적 문서 6개로 압축하고 유지보수성을 극대화한다.
> 관련: [direction-alignment.md](direction-alignment.md) · [edition-boundary.md](edition-boundary.md) · [platform-portability.md](platform-portability.md) · [release-pipeline.md](release-pipeline.md) · [archive/2026/user-data-separation.md](archive/2026/user-data-separation.md)
> 약칭: `gcs`

---

## 1. 배경 및 문제 의식

현재 Private Engine의 사용자 데이터 디렉토리(`~/.pe`) 루트에는 설정, 상태, 선언적 문서가 혼재되어 복잡도가 높다:
1. **설정 파일의 파편화**:
   - `team.json` (팀 로스터 및 캐릭터 역할 배정)
   - `providers.json` (OpenAI 호환 외부 API 엔드포인트 설정)
   - `events.json` (이벤트 반응 설정)
   - `items.json` (선물 아이템 카탈로그)
   - 이들이 각각 개별 JSON 파일로 루트에 존재하여, 애플리케이션 설정을 한눈에 파악하거나 백업/동기화하기 어렵다.
2. **런타임 상태 파일의 루트 오염**:
   - `standby.pid`, `live_pids.json` (프로세스 관리)
   - `lifecycle.lock`, `doctor-probe.stamp` (락 및 프로브 타임스탬프)
   - `account_state.json` (제공자 계정 쿼터/사용량 상태)
   - `delegation_seen.json`, `work_talk.json` (작업 위임 런타임 메모)
   - `push_vapid.json`, `push_subscriptions.json` (웹 푸시 런타임 상태)
   - `last_boot.json` (부팅 메타데이터)
   - 이 파일들은 엔진 프로세스가 동작하며 동적으로 읽고 쓰는 임시/상태 데이터임에도 루트에 방치되어 사용자가 보는 파일 목록을 어지럽힌다.
3. **환경 변수 파일과의 역할 혼선 방지**:
   - `host.env` (포트, 에디션 등 호스트 쉘 실행 환경)와 `secrets.env` (API 토큰 등 비밀키)는 쉘 스크립트(`chatbot-ctl.sh`) 소싱 및 권한 관리를 위해 환경 변수 파일로 분리되어 있어야 한다.

---

## 2. 목표 아키텍처

### 2.1 루트 파일 체계 압축 (6개 핵심 파일)

개편 후 `~/.pe` 루트는 다음 6개의 핵심 파일과 디렉토리들로 단정하게 정리된다:

```text
~/.pe/
├── AGENTS.md        # [지침] 헌장 및 공통 시스템 규칙 (심링크/파일)
├── USER.md          # [기억] 사용자 프로필, 호칭, 공통 맥락
├── PROJECT.md       # [개발] 프로젝트 목표 및 규칙 (dev 에디션)
├── config.json      # [설정] 통합 애플리케이션 설정 (team, providers, events, items)
├── host.env         # [호스트] 쉘/서비스 기동 환경변수 (PORT, EDITION 등)
├── secrets.env      # [보안] API 키 및 자격 증명 (600 권한)
│
├── state/           # [상태] 엔진 런타임 상태/PID/락 격리 디렉토리
├── logs/            # [로그] 일자별 이벤트 로그 및 회전 아카이브
├── sessions/        # [세션] 대화 세션 및 아티팩트
├── characters/      # [캐릭터] 캐릭터 카드 및 갤러리 에셋
├── roles/           # [역할] 전문가 역할 지침
├── dialogs/         # [시나리오] 시나리오 및 퀘스트 데이터
└── rooms/           # [단체방] 다자간 대화방 설정
```

### 2.2 `config.json` 규격

루트의 4대 설정 파일들을 `config.json`의 네임스페이스 키로 통합한다:

```json
{
  "version": 1,
  "team": {
    "default": "char_...",
    "members": {
      "char_...": ["planner", "critic"]
    }
  },
  "providers": {
    "custom_openai": {
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "models": ["gpt-4o", "gpt-4o-mini"]
    }
  },
  "events": {
    "morning_greeting": { "enabled": true }
  },
  "items": {
    "coffee": { "name": "따뜻한 커피", "category": "drink" }
  }
}
```

- **하위 호환성 (Fallback)**:
  - `config.json`에 해당 섹션이 없거나 파일이 없으면 기존 독립 파일(`team.json` 등)을 읽어 마이그레이션하거나 폴백한다.
  - 새로 저장할 때는 `config.json`에 원자적(atomic)으로 기록한다.

### 2.3 `state/` 디렉토리 격리 규격

모든 런타임 임시/상태 파일의 기본 경로를 `host_config.STATE_DIR` (`~/.pe/state/`) 아래로 일원화한다:

| 기존 루트 경로 | 격리 후 경로 | 관리 모듈 |
|---|---|---|
| `live_pids.json` | `state/live_pids.json` | `session_procs.py`, `ctl_proc.py` |
| `standby.pid` | `state/standby.pid` | `standby_pool.py`, `ctl_proc.py` |
| `lifecycle.lock` | `state/lifecycle.lock` | `evolution.py`, `chatbot-ctl.sh` |
| `doctor-probe.stamp` | `state/doctor-probe.stamp` | `chatbot-ctl.sh` |
| `last_boot.json` | `state/last_boot.json` | `server.py` |
| `account_state.json` | `state/account_state.json` | `providers/accounts.py` |
| `delegation_seen.json` | `state/delegation_seen.json` | `delegation.py` |
| `work_talk.json` | `state/work_talk.json` | `delegation.py` |
| `push_vapid.json` | `state/push_vapid.json` | `host_config.py`, `push_manager.py` |
| `push_subscriptions.json` | `state/push_subscriptions.json` | `host_config.py`, `push_manager.py` |

---

## 3. 단계별 추진 항목

| 항목 ID | 작업 내용 | 대상 파일 | 검증 기준 |
|---|---|---|---|
| `gcs/A` | `host_config.py`에 `STATE_DIR` 및 `CONFIG_FILE` 정의, 런타임 상태 경로 이전 | `host_config.py`, `evolution.py`, `ctl_proc.py`, `chatbot-ctl.sh`, `server.py`, `accounts.py`, `delegation.py` | 기존 파일 자동 감지 및 `state/` 우선 사용, 회귀 테스트 통과 |
| `gcs/B` | `config.json` 읽기/쓰기 헬퍼 도입 및 `team.py`, `adapters.py`, `event_react.py`, `items.py` 연동 | `engine/config_store.py`(신규), `characters.py`, `adapters.py`, `event_react.py`, `items.py` | `config.json` 우선 읽기/쓰기 및 레거시 파일 폴백 호환성 검증 |
| `gcs/C` | `~/.pe` 실데이터 마이그레이션 및 루트 평탄화 완료 | `~/.pe/` 디렉토리 | `ls -la ~/.pe` 루트가 6개 문서로 단정해짐, 서비스 재시작 후 200 OK |

---

## 4. DoR / DoD

- **DoR (정의 완료)**: 선행 사례(Hermes) 확인 완료, 운영자 승인 완료, 계획 인덱스 등록.
- **DoD (완료 기준)**:
  1. `run-tests.sh --fast` 100% 통과.
  2. `config.json`을 통해 team/providers/events/items 설정이 완벽히 읽히고 저장됨.
  3. 모든 lock/pid/state 파일이 `~/.pe/state/`에서 생성/동작함.
  4. 서비스 재시작 후 닥터 프로브 200 OK 및 채팅 정상 응답.
