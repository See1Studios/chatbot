# 프로바이더 CLI 동작 SSOT

냥피디가 붙이는 프로바이더 CLI(agy / claude / codex / grok)와 HTTP(omniroute / openrouter)의
**실측으로 확인된 동작**만 여기에 둔다. 새 실험을 하기 전에 이 문서를 먼저 읽고,
실험이 끝나면 **여기에 기록**한다. 같은 실험을 두 번 하지 않기 위한 문서다.

| 문서 | 대상 | 확인한 버전 |
|---|---|---|
| [agy.md](agy.md) | Antigravity CLI (기본 프로바이더) | agy 1.2.7 |
| [claude.md](claude.md) | Claude Code | 2.1.277 (계정 항목 C11~C13은 2.1.278) |
| [codex.md](codex.md) | Codex CLI | 0.154.0 |
| [grok.md](grok.md) | Grok Build | 1.0.34 |
| [omniroute.md](omniroute.md) | OmniRoute (HTTP, OpenAI dialect) | - |
| [openrouter.md](openrouter.md) | OpenRouter (HTTP, 무료 모델만) | 2026-09-21 `/v1/models` |

## 상태 표기

| 표기 | 뜻 | 요구 사항 |
|---|---|---|
| ✅ | 실측 확인 | 날짜, CLI 버전, 재현 방법(스크립트 또는 명령), 관측값 |
| ❌ | 실측으로 **반증됨** — 다시 시도하지 말 것 | 반증한 수치 |
| ⚠ | 조건부/불안정 | 어떤 조건에서 어떻게 달라졌는지 |
| ❓ | 미확인 | 왜 못 했는지 (계정 한도, 도구 없음 등) |
| 📄 | 공식 문서·`--help` 기준. **실측 아님** | 출처 |

**규칙**
1. ✅는 이 저장소에서 다시 돌릴 수 있어야 한다. 재현 스크립트는 `tests/probes/`.
2. 가설은 ❓로 적고, 증거가 생기면 ✅/❌로 바꾼다. 추측을 ✅로 쓰지 않는다.
3. **한 번 관측한 것과 재현된 것을 구분한다.** 한 번이면 "1회"라고 적는다.
4. CLI 버전이 바뀌면 해당 항목은 재검증 전까지 신뢰하지 않는다.
5. 카나리 문구에 "비밀" 같은 단어를 쓰지 않는다 (codex가 보안 요청으로 보고 거부했다).
6. **프로브 메시지에 "기억해"/"저장해" 같은 말을 쓰지 않는다.** 냥피디는 그걸 실제 `MEMORY.md`에 쓴다 (agy.md A28). 이어받기·기억 테스트는 임시 워크스페이스에서 하거나, 끝나면 `python3 data/workspace/tools/memory.py forget`으로 지운다.

## 프로브 스크립트

| 스크립트 | 무엇을 재나 |
|---|---|
| `tests/probes/agy_first_turn.py` | agy 첫 턴 입력 토큰·스텝·도구 호출·agy 자체 로그(스킬 스캔, 훅 로드) |
| `tests/probes/discovery_canary.py` | 프로바이더별로 `AGENTS.md`/`CLAUDE.md`/스킬을 스스로 발견하는지 (카나리 토큰) |

호스트와 같은 `build_args`/`build_env`로 스폰하고 한 턴만 보낸 뒤 자식을 죽인다. 라이브 서버는 건드리지 않는다.

## 교차 요약 (프로바이더 간 비교)

| 항목 | agy | claude | codex | grok |
|---|---|---|---|---|
| 첫 턴 입력 토큰 (호스트 구성) | ✅ ~47k (add-dir chat만이면 ~13k) | 📄 ~11k (token-accounting 중앙값) | 📄 ~23–33k | 📄 ~46k |
| `AGENTS.md` 자동 발견 | ✅ add-dir 폴더 + 조상 | ✅ **안 읽음** | ✅ 읽음 | 📄 읽음 |
| `CLAUDE.md` 자동 발견 | ✅ 안 읽음 | ✅ 읽음 | ❓ | 📄 읽음 |
| `.agents/skills` 발견 | ✅ 조상까지 | ✅ **안 봄** | ✅ 조상까지 | 📄 조상까지 |
| `.claude/skills` 발견 | ✅ 안 봄 | ✅ 조상까지 | ❓ | 📄 조상까지 |
| 시스템 프롬프트 채널 | ✅ 없음 (`--help`) | 📄 `--append-system-prompt[-file]` | ❓ | 📄 `--rules` |
| 홈 설정 격리 수단 | ❌ 못 찾음 | ✅ `--setting-sources project` | ⚠ `--ignore-user-config`(스킬은 그대로 발견) | ❓ |
| 지금 라이브 검증 가능? | ✅ | ✅ | ❌ 사용 한도 ~2026-10-09 | ❌ 잔액 소진(402) |

**핵심 귀결:** 같은 워크스페이스라도 프로바이더마다 보이는 지침·스킬 집합이 다르다.
자동 발견에 기대는 한 동일 동작은 불가능하므로, 지침은 호스트가 주입하고(`instructions.py`)
프로바이더의 자동 발견에 의존하는 설계를 하지 않는다 (`docs/plans/instruction-architecture.md`).

## 계정 확인

상태 탭의 **로그인 계정 · 프로세스** 카드가 4개 프로바이더의 현재 계정과 실행 중인 CLI 프로세스를 보여 준다 (`accounts.py`). 프로세스별 인증 계정은 **agy만** 로그로 증명 가능(agy.md A29~A32); claude/codex/grok은 계정 변경 관측 시각과 프로세스 시작 시각 비교만 한다.
