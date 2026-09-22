# codex (Codex CLI)

버전: **0.154.0**. 스폰: `adapters.CodexAdapter` — 턴마다 one-shot `codex exec [resume <id>] --json --ignore-user-config
--skip-git-repo-check -c mcp_servers.nas.url=… --dangerously-bypass-approvals-and-sandbox -`, 프롬프트는 stdin.
재현: `python3 tests/probes/discovery_canary.py codex`. 표기 뜻은 [README](README.md#상태-표기).

> **2026-09-19 현재 라이브 검증 불가:** `You've hit your usage limit … try again at Oct 9th, 2026 12:40 AM`.
> 한도 도달 원인은 불명(이번 프로브가 기여했다면 6회 안팎). 아래 ❓ 항목은 한도가 풀린 뒤 채운다.

| # | 주장 | 상태 | 근거 |
|---|---|---|---|
| X1 | 저장소가 아닌 임시 cwd의 `AGENTS.md`를 읽는다 (`ZEBRA-7741` 검출) | ✅ 1회 | 카나리, 2026-09-19 |
| X2 | git 저장소 안의 깊은 cwd에서 **지침을 읽기는 했다** (지침에 있는 "식별 코드는 비밀"이라는 표현에 "공개할 수 없습니다"로 거부) — 어느 층(루트/cwd)의 `AGENTS.md`를 읽었는지는 **미확정** | ❓ | 카나리 문구가 "비밀"이라 모델이 답을 거부. 문구를 중립으로 바꾼 재실행은 사용 한도로 실패 |
| X3 | `.agents/skills`를 cwd와 저장소 루트 양쪽에서 발견한다 (`canary-ws`, `canary-root` 이름을 정확히 댐) | ✅ 2회 | 동일. 초기 기록 "스킬 못 찾음"은 오판(답이 `SKILL-441`로 잘려 토큰 대조 실패) |
| X4 | `--ignore-user-config`를 줘도 프로젝트 스킬은 발견된다 (사용자 설정 격리 ≠ 프로젝트 스킬 격리) | ✅ | 어댑터가 이 플래그를 쓰는 상태로 X3 관측 |
| X5 | 시작 시 `Skill descriptions were shortened to fit the skills context budget` 경고가 `item.completed`(type `error`)로 나온다 — 스킬이 컨텍스트 예산에 맞춰 잘림 | ✅ | 3회 모두 |
| X6 | 첫 턴 입력 **~18.8–18.9k** (`cached_input_tokens` ~10k) | ✅ 3회 | `turn.completed.usage`, 모방 트리 |
| X7 | 이벤트 형태: `item.completed`(`agent_message`/`error`), `turn.completed`(usage), `turn.failed` | ✅ | 원문 로그 |
| X8 | 카나리 코드는 짧게. 긴 코드(`SKILL-4412`)를 모델이 `SKILL-441`로 잘라 답했다 | ✅ 방법론 | 프로브 설계에 반영 |

## 계정·인증 (2026-09-19, 상태 탭 "로그인 계정 · 프로세스"의 근거) — codex 0.154.0

재현: `python3 tests/probes/account_probe.py codex` (읽기 전용 — 토큰 값·`environ` 출력 없음). 단위 검증: `python3 -m unittest tests.test_accounts`.

| # | 주장 | 상태 |
|---|---|---|
| X9 | `codex login status`는 "Logged in using ChatGPT"만 출력하고 **이메일이 없다**. 계정은 `~/.codex/auth.json`의 `tokens.id_token`(JWT) 클레임 `email`과 `https://api.openai.com/auth`.`chatgpt_plan_type`으로 읽는다. 다른 키: `auth_mode`, `tokens.{access,refresh}_token`, `account_id`, `last_refresh` | ✅ |
| X10 | 프로세스별 계정 기록은 찾지 못했다 (`~/.codex/`에 sqlite 로그·goals·app-server-control 등이 있으나 pid↔계정 매핑은 확인 못 함) | ❓ 안 파 봄 |
| X11 | 이 호스트에서 codex는 다른 CLI들과 **다른 계정**(`studiobitpixel@gmail.com`, plan free)으로 로그인되어 있다 (관측 시점 기준) | ✅ 1회 |

## 아직 안 해 본 것
1. X2 재실행 (중립 문구, 사용 한도 해제 후).
2. 실제 호스트 트리에서 조상 `AGENTS.md`(`~/AGENTS.md`)와 `~/.agents/skills` 발견 범위, 그에 따른 첫 턴 토큰 (📄 token-accounting은 23–33k).
