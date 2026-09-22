# claude (Claude Code)

버전: **2.1.277** (C11~C13 계정 항목만 2.1.278에서 실측 — 나머지 행은 규칙 4에 따라 재검증 전까지 2.1.277 기준). 스폰: `adapters.ClaudeAdapter` — 지속 자식 프로세스, `-p --input-format stream-json --output-format stream-json`,
`--mcp-config <WORKSPACE/.mcp.json> --strict-mcp-config --setting-sources project`, `cwd=WORKSPACE`.
재현: `python3 tests/probes/discovery_canary.py claude`. 표기 뜻은 [README](README.md#상태-표기).

| # | 주장 | 상태 | 근거 |
|---|---|---|---|
| C1 | cwd와 **저장소 루트까지** `CLAUDE.md`를 읽는다 (루트 `ROOTC-2222`, cwd `WSC-7777` 모두 검출) | ✅ | 모방 트리 카나리, 2026-09-19 |
| C2 | `.claude/skills`를 cwd와 루트 양쪽에서 발견한다 | ✅ | 동일 |
| C3 | **`AGENTS.md`는 읽지 않는다.** `.agents/skills`도 발견하지 않는다 | ✅ | 동일 (카나리 2종, 두 트리). `ClaudeAdapter` docstring의 옛 주장("AGENTS.md 자동 발견")은 틀렸고 2026-09-19 정정 |
| C4 | `--setting-sources project`가 `~/.claude`의 사용자 스킬·설정을 자식에게서 격리한다 | 📄 | 어댑터 주석·플래그 문서. 홈 격리 자체를 직접 A/B 하지는 않음 |
| C5 | 실제 호스트 트리에서 `~/CLAUDE.md`(461B, "AGENTS.md를 읽어라" 포인터)가 실제로 로드되는지 | ❓ | 모방 트리에서 루트 `CLAUDE.md` 발견은 확인(C1). 실제 홈 트리는 미측정 |
| C6 | 시스템 프롬프트 채널: `--append-system-prompt[-file]`, `--system-prompt[-file]` 존재 | 📄 | `claude --help`. 냥피디는 채널 동일성을 위해 쓰지 않음(설계서 §5) |
| C7 | 첫 턴 입력 토큰 **~11k**, 이후 턴 ~9k (중앙값) | 📄 | `docs/plans/token-accounting.md` (audit 표, 2026-09-19). 이번에 스크립트로 재측정하지 않음 |
| C8 | UI에서 `/skill <이름>`을 보내면 Claude에겐 슬래시 명령이 아니다. 에이전트가 `.agents`를 Glob하고 `SKILL.md`를 직접 읽어 수행한다 | ✅ 1회 | 세션 `20260919-…` 로그 (`naver-news-search`) — 동작은 하지만 매번 스킬 위치를 다시 찾는다 |
| C9 | 대화 ID는 CLI가 발급한다(`mints_own_conversation_id`), `--resume <id>`로 이어받는다 | ✅ | 어댑터, 라이브 세션 |
| C10 | agy → claude 교체 후 답이 냥피디 톤이었다 | ⚠ | 인계 요약(앞선 agy 답)과 페르소나 주입 중 무엇 덕인지 분리 못 함 |

## 계정·인증 (2026-09-19, 상태 탭 "로그인 계정 · 프로세스"의 근거) — Claude Code 2.1.278

재현: `python3 tests/probes/account_probe.py claude` (읽기 전용 — 토큰 값·`environ` 출력 없음). 단위 검증: `python3 -m unittest tests.test_accounts`.

| # | 주장 | 상태 |
|---|---|---|
| C11 | 현재 계정은 `claude auth status`(JSON, 약 0.9초)의 `email`·`subscriptionType`으로 읽는다. `~/.claude/.credentials.json`에는 **이메일이 없다**(키: `claudeAiOauth`·`designOauth` 아래 토큰·만료·scopes) | ✅ |
| C12 | `~/.claude/sessions/<pid>.json`에 pid·cwd·startedAt·entrypoint·name은 있으나 **계정 정보는 없다** → 프로세스별 인증 계정은 알 수 없다 | ✅ |
| C13 | 실행 중인 claude 프로세스가 옛 자격을 메모리에 들고 있다가 refresh 때 자격 파일을 되덮어쓰는지(agy A30 같은 현상)는 **미확인** — 로그아웃 실험은 사용자 로그인을 건드려서 하지 않았다 | ❓ |

## 아직 안 해 본 것
1. 첫 턴 토큰을 `agy_first_turn.py` 같은 스크립트로 직접 재측정 (지금은 중앙값 인용).
2. 실제 홈 트리(`~/CLAUDE.md`, `~/.claude`)에서의 발견 범위.
