# grok (Grok Build)

버전: **1.0.34**. 스폰: `adapters.GrokAdapter` — 턴마다 one-shot `grok --prompt-file <WORKSPACE/.grok/prompts/…txt>
--output-format streaming-json --always-approve --trust [--resume <id>]`. 재현: `python3 tests/probes/discovery_canary.py grok`.
표기 뜻은 [README](README.md#상태-표기).

> **2026-09-19 현재 라이브 검증 불가:** `API error (status 402 Payment Required): Grok Build usage balance exhausted`.
> 아래 📄 항목은 전부 **문서 기준이며 실측이 아니다.**

| # | 주장 | 상태 | 근거 |
|---|---|---|---|
| G1 | `AGENTS.md`(`Agents.md`)를 **저장소 루트부터 cwd까지 모든 층**에서 읽고, 깊은 폴더가 뒤에 와서 우선한다. `CLAUDE.md`/`CLAUDE.local.md`도 호환으로 읽는다. 시작 시 로딩은 폴더 신뢰(`--trust`) 필요 | 📄 | `~/.grok/docs/user-guide/12-project-rules.md` |
| G2 | 스킬 탐색: `./.grok/skills`, 저장소 `.grok/skills`, `~/.grok/skills`, `~/.claude/skills`(기본 켜짐), `./.claude/skills`; **`.agents/skills`도 각 층과 cwd~루트 사이 모든 폴더에서 스캔** | 📄 | `08-skills.md` |
| G3 | **격리 스위치(문서상):** `~/.grok/config.toml`의 `[compat.claude] skills=false` 또는 env `GROK_CLAUDE_SKILLS_ENABLED=false`, `[skills] ignore`/`disabled` | 📄 ❓ | `08-skills.md`. 어댑터에 적용 안 했고 효과 미측정 |
| G4 | `--rules <TEXT>`: 시스템 프롬프트에 규칙 추가 (`--yolo`와 조합 예시) | 📄 | `grok --help`, `14-headless-mode.md`. 냥피디는 채널 동일성을 위해 쓰지 않음 |
| G5 | 첫 턴 입력 **~46k**, 이후 ~49k (중앙값). agy와 같은 규모라 홈 스킬 스캔과 같은 원인일 가능성 | 📄 / ❓ 원인 | `token-accounting.md`. 원인은 가설일 뿐 |
| G6 | `--trust`는 헤드리스에서 필요하다 (문서에 없던 플래그를 실측으로 찾음) | ✅ | 메모리 `feedback_verify_cli_live`, DEVLOG 2026-09-17 |
| G7 | 프롬프트 파일을 WORKSPACE 루트에 두면 agy `--add-dir` 스캔에 잡혀서, dotdir `.grok/prompts/`로 옮김(`.gitignore` 추가) | ✅ | DEVLOG 2026-09-19 |
| G8 | 프로젝트 MCP는 `grok mcp add --transport http --scope project nas <url>`로 등록 | ✅ | 어댑터 `_ensure_mcp_registered` |

## 계정·인증 (2026-09-19, 상태 탭 "로그인 계정 · 프로세스"의 근거) — grok 1.0.34

재현: `python3 tests/probes/account_probe.py grok` (읽기 전용 — 토큰 값·`environ` 출력 없음). 단위 검증: `python3 -m unittest tests.test_accounts`.

| # | 주장 | 상태 |
|---|---|---|
| G9 | 계정 조회 서브커맨드는 없다(`login`/`logout`만). 현재 계정은 `~/.grok/auth.json`의 항목 `email`(평문 필드)로 읽는다. 항목이 여럿이면 `expires_at`/`create_time`이 가장 최신인 것 (`adapters._grok_access_token`과 같은 규칙) | ✅ |
| G10 | `auth.json` 항목 키: `key`, `auth_mode`, `create_time`, `user_id`, `email`, `first_name`, `last_name`, `principal_type/id`, `team_id`, `refresh_token`, `expires_at`, `oidc_issuer`, `oidc_client_id`. 프로세스별 계정 기록은 확인하지 못했다(`active_sessions.json`은 안 열어 봄) | ✅ 키 / ❓ 프로세스별 |

## 사용량 조회 (2026-09-19) — grok 1.0.34

| # | 주장 | 상태 |
|---|---|---|
| G11 | 사용량은 `GET {proxy}/billing?format=credits` 하나로 읽는다 (grok 바이너리에도 이 엔드포인트 문자열이 **하나뿐**). 응답은 protobuf-JSON이라 **값이 0인 스칼라 필드를 생략**한다 → 사용 0%인 계정은 `creditUsagePercent`(와 `productUsage[].usagePercent`)가 **아예 없다**. 파서는 "크레딧 형태(`currentPeriod`/`billingPeriodEnd` 있음)인데 % 필드가 없으면 0% 사용"으로 읽는다. 라이브 응답 키: `currentPeriod{type,start,end}`, `onDemandCap{val}`, `onDemandUsed{val}`, `prepaidBalance{val}`, `isUnifiedBillingUser`, `topUpMethod`, `billingPeriodStart/End` | ✅ 응답 구조·수정 후 `주간 100% 남음` 표시 (실장님이 grok CLI에서 0% 사용으로 확인) / ⚠ "생략=0" 규칙은 이 계정의 0% 한 경우로만 뒷받침됨 — 0이 아닌 값에서 `creditUsagePercent`가 오는 모습은 이번에 재확인하지 못함(9/18 라이브 검증 기록만) |
| G12 | `/billing`(형식 없음)과 `?format=usage`는 **같은 다른 구조**(`monthlyLimit`, `used`, `onDemandCap`, `history[]`)를 준다. 한도가 0이면 남은 %를 계산할 수 없고 `used`의 단위도 미확인이라 **쓰지 않는다** (챗봇은 이 형태를 "정보 없음"으로 둔다) | ✅ 응답 구조 / ❓ `used` 단위 |
| G13 | 처음 "사용량 정보를 찾지 못했습니다"를 **크레딧 소진으로 잘못 추정**했다(같은 날 grok.md 상단의 402 기록 때문). 실제로는 위 G11 파서 결함이었다 — 응답이 비었다고 계정 문제로 단정하지 말고 필드 생략을 먼저 의심할 것 | ✅ |

## 아직 안 해 본 것 (잔액 복구 후, 우선순위 순)
1. G1·G2를 `discovery_canary.py grok`으로 실측하고 📄 → ✅/❌.
2. G3 스위치(`GROK_CLAUDE_SKILLS_ENABLED=false`)가 첫 턴 토큰을 줄이는지.
