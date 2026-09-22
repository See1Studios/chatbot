# agy (Antigravity CLI)

버전: agy **1.2.7** (`agy changelog`). 스폰: `adapters.AgyAdapter` — 지속 자식 프로세스,
`--input-format stream-json --output-format stream-json`, `cwd=WORKSPACE`, `--add-dir`는 `host_config.ADD_DIRS`.
재현: `python3 tests/probes/agy_first_turn.py`, `tests/probes/discovery_canary.py agy agy+`.
표기 뜻은 [README](README.md#상태-표기).

## 1. 시작 토큰 세금 (첫 턴 `input_tokens`, "안녕" 한 문장, gemini-3.8-flash-low)

| # | 주장 | 상태 | 근거 |
|---|---|---|---|
| A1 | `--add-dir /volume1/web/chat`만 → **12,957~13,074**, 1스텝 | ✅ | 2026-09-19 여러 번 재현 (12,957 / 12,958 / 13,074) |
| A2 | `--add-dir` 에 홈 저장소 안의 폴더(WORKSPACE 등)를 더하면 **46.6k~47.9k**, 스텝에 `unknown` 1개가 붙음 | ✅ | 2026-09-19 10회 이상. 빈 하위폴더(`workspace/tools`)도 47.7k |
| A3 | 위 A2의 **원인 경로는 홈의 `.agents` 스킬 스캔**: agy 자체 로그에 `skills.go … ~/.agents/plugins/master-skills/skills/…/SKILL.md` 파싱 오류, `loaded 1 named hooks`. 저장소 밖 add-dir 로그에는 스킬 스캔도 훅도 없음 (`loaded 0 named hooks`) | ✅ | `agy_first_turn.py`의 `skill-scan=`/`hooks=` 열. 홈 아래 SKILL.md **2,649개**(`~/.agents/plugins` 2,643 + `~/.agents/skills` 144 + `~/.gemini/skills`) |
| A4 | 같은 내용의 WORKSPACE **사본을 홈 밖(`/tmp`)** add-dir → **+0.8k**(13.8k), 문서 전부(`AGENTS.md`, `PERSONA.md` …) 있어도 동일 | ✅ | 2026-09-19 사본 6종 |
| A5 | 47k 중 스킬 색인이 **정확히 몇 토큰**인지는 직접 분해하지 못함 | ❓ | 스킬 스캔을 끌 방법이 없어 단독 측정 불가. 이름+첫 줄 설명만 세면 약 12.7k 토큰(3B/토큰 추정) |

## 2. 격리 시도 — 이미 해 봤고 **소용없었다** (다시 시도하지 말 것)

| # | 시도 | 결과 | 상태 |
|---|---|---|---|
| A6 | `--disable-slash-commands` | 45,970 → 45,961 (Δ9). `--print` 모드도 동일 | ❌ (DEVLOG 2026-09-19 + 실장님 재확인) |
| A7 | `--new-project` | 47,743 (기준 47,742) | ❌ |
| A8 | `--project <없는 이름>` | 실행 실패, 결과 없음 (usage 0) | ❌ |
| A8b | `--project` 에 **실제 존재하는** 프로젝트 (`default-cli-project`, `workspace`, workspace의 uuid `00cb07b5-…`) | 47,742 / 47,738 / 47,739 (기준 47,741), 스킬 스캔·훅 그대로 | ❌ `~/.gemini/config/projects/*.json`에 정의된 프로젝트를 골라도 무관 |
| A9 | 자식에게 격리 HOME (`.gemini`만 심볼릭) | 47,885, 스킬 스캔 그대로 | ❌ 스캔은 `$HOME`이 아니라 **작업공간의 조상 경로** 기준 |
| A10 | 위 HOME에 **빈 `projects.json`** 오버레이 (대화·인증은 공유) | 47,898, 스킬 스캔 그대로 | ❌ 프로젝트 매핑(`~/.gemini/projects.json`)이 스위치가 아님 |
| A11 | `agy plugin` 으로 끄기 | `agy plugin list` → "No imported plugins." | ❌ `master-skills`는 플러그인이 아니라 경로 규칙으로 스캔됨 |
| A12 | `AGENTS.md`를 없애기 / 본문 없는 stub으로 대체 | 46,660 / 46,830 — 그대로 | ❌ `AGENTS.md`는 원인이 아님 (초기 가설이 틀렸음) |
| A13 | WORKSPACE를 저장소 밖 **심볼릭 링크 경로**로 add-dir | 14,635·14,634 두 번, 이후 **44,461**로 되돌아감 | ⚠ 불안정. 경로 연관을 agy가 저장하는 것으로 보임 → **채택 불가** |
| A14 | 위 A13으로 **기존 대화를 이어받기** (실경로로 만든 대화를 심볼릭 경로에서 `--conversation`) | `status=ERROR`, 빈 응답, in=197,020 (1회) | ⚠ 경로를 바꾸면 이어받기가 깨짐. 같은 경로끼리는 정상(실경로→실경로, 심볼릭→심볼릭 모두 "청개구리7" 회수) |

## 3. 자동 발견 (카나리 + 모방 트리, 2026-09-19)

| # | 주장 | 상태 |
|---|---|---|
| A15 | `--add-dir`이 **없으면** cwd의 `AGENTS.md`/스킬/훅을 아무것도 안 읽는다 | ✅ |
| A16 | `--add-dir <폴더>` → 그 폴더와 **저장소 루트까지 올라가며** `AGENTS.md`, `.agents/skills`를 모은다 (루트·폴더 둘 다 검출) | ✅ |
| A17 | `CLAUDE.md`, `.claude/skills`는 읽지 않는다 | ✅ |
| A18 | 워크스페이스 `.agents/hooks.json`은 WORKSPACE가 add-dir일 때만 로드 (`loaded 1` vs `0`) | ✅ 로그 |
| A19 | `AGENTS.md` **한 파일만** 든 저장소 밖 폴더 → 83,561~103,169, 스텝 6(도구 5회: `run_command`×3, `view_file`×2). 내용이 도구 실행을 유도 | ⚠ 2회. 모델이 지침을 따라 움직인 것이지 발견 비용이 아님 |
| A20 | 시스템 프롬프트 주입 플래그는 **없다** (`agy --help`) | ✅ |

## 4. 기타

| # | 주장 | 상태 |
|---|---|---|
| A21 | 페르소나를 주입하지 않아도 답이 "안녕하세요, **실장님**!"으로 나온다 → 격리되지 않은 홈 컨텍스트가 모델에 닿는다. 출처(`~/GEMINI.md`, 조상 `AGENTS.md`, 대화 요약 중 무엇인지)는 미확정 | ✅ 관측 5회 / ❓ 출처 |
| A22 | 없는 conversation id를 `--conversation`에 주면 agy가 무시하고 새 대화를 만든다 (`Conversation … not found, ignoring --conversation flag`) | ✅ 로그 |
| A23 | 사용량은 `result.result.usage` 와 `step_update.usage` 에 있다. `input_tokens`는 그 턴의 **모든 LLM 스텝 합** — 도구를 부른 턴은 1스텝 턴과 비교 불가 | ✅ |
| A24 | 재기동 직후 첫 standby 채택 턴은 `input_tokens == 0`으로 나올 수 있다 (observation 0009) | ⚠ 이번에도 재현(`stub` 측정 1회) |
| A25 | 시작 세션의 `workspaceDirs`에는 cwd가 항상 첫 항목으로 들어가고, WORKSPACE를 add-dir로 주면 **두 번** 나타난다 | ✅ 로그 |
| A26 | `~/.gemini/antigravity-cli/` 에 대화(224M)·요약 DB(692K, 426건 동기화)·brain(233M)이 쌓인다. 스폰마다 `summary store reconciliation` | ✅ 로그 |
| A27 | 설정 파일에는 스킬 스캔을 제어하는 키가 **없다**. `~/.gemini/settings.json`(인증뿐), `~/.gemini/antigravity-cli/settings.json`(모드·권한·`trustedWorkspaces`: `/volume1/homes/me`, `/volume1/web` 등), `~/.gemini/config/config.json`(원격제어 호스트명뿐). 프로젝트 정의는 `~/.gemini/config/projects/`에 2개(`workspace`=WORKSPACE 폴더, `default-cli-project`=빈 자원) | ✅ 전문 확인 2026-09-19 |
| A28 | 사용자가 "암호를 기억해: …"라고 하면 agy가 `AGENTS.md`의 지침대로 `python3 tools/memory.py add`를 실행해 **실제 장기 기억 파일에 쓴다** (첫 관측: 이어받기 테스트가 `MEMORY.md`를 오염시킴, 수동 `forget`으로 원복). 즉 기억 **쓰기**는 "기억해" 요청 시 작동하고, 안 도는 건 시작 시 **읽기**와 자발적 기록이다 | ✅ 1회 (add-dir=WORKSPACE, 네이티브 `AGENTS.md` 발견 상태) |

## 4b. 계정·인증 (2026-09-19 사고, 상태 탭 "로그인 계정 · 프로세스"의 근거)

재현: `python3 tests/probes/account_probe.py agy` (읽기 전용 — 토큰 값·`environ` 출력 없음). 단위 검증: `python3 -m unittest tests.test_accounts`.

| # | 주장 | 상태 |
|---|---|---|
| A29 | 이 NAS에는 DBus/OS keyring이 없고, agy 로그의 `ChainedAuth: authenticated via keyring`은 **`~/.gemini/antigravity-cli/antigravity-oauth-token` 파일**이다 (토큰 만료 = 파일 갱신 시각 +1h). 구 gemini-cli의 `~/.gemini/oauth_creds.json`·`google_accounts.json`(8월 13일자)은 agy 인증과 무관해 보인다 | ✅ (구 파일 무관은 ❓ 로그상 추정) |
| A30 | 인증은 **프로세스가 뜰 때 읽고 메모리에 든다**. 오래 떠 있는 옛 `agy`(예: SSH 대화형 세션)는 옛 refresh token을 들고 있다가 refresh 때 **공유 토큰 파일을 옛 계정으로 되돌려 쓴다** — 새로 로그인해도 되돌아간 원인. 9/17 세션 종료 후 재로그인은 유지됨 | ✅ 정황(종료 전후 비교), 파일 쓰기 순간은 직접 못 봄 |
| A31 | 각 agy 로그(`log/cli-<시각>.log`) 첫 줄에 `Starting language server process with pid <pid>`가 있고, 이후 `authenticated successfully as <email>`이 찍힌다 → **pid로 프로세스별 인증 계정을 정확히 매칭**할 수 있다 (시각 근사 불필요) | ✅ |
| A32 | 계정을 바꿀 때(한도 소진 → 다른 계정) **다른 agy 프로세스를 먼저 모두 종료**하고 로그인한다. 그러면 챗봇 소유 agy는 30초 안에 **자동으로 재시작**된다(유휴 세션·standby만, 작업 중은 건드리지 않음, 외부 프로세스는 절대 안 건드림; `CHATBOT_AUTO_RECYCLE=0`으로 끔). 재시작은 기존 15분 유휴 리퍼와 같은 상태 전이(`proc=None` → 다음 메시지에서 `ensure`가 같은 `--conversation`으로 재기동)다 | ✅ 코드 경로·`tests/test_auto_recycle.py`, ❓ 실계정 전환 end-to-end는 미실측 |
| A33 | 사용량 캐시(TTL 5분)는 예전엔 프로바이더 기준이라 계정을 바꿔도 최대 5분간 **이전 계정의 사용량**이 보일 수 있었다(코드 읽기로 추론, 재현은 안 함). 지금은 현재 계정이 바뀌면 캐시를 버리고 응답에 `account`를 싣는다. claude는 `auth status` 캐시(60초) 때문에 전환 인식이 최대 1분 늦다 | ✅ 단위 테스트 / ❓ 실계정 전환은 미실측 |
| A34 | 새 계정으로 재시작된 agy가 **옛 계정에서 만든 대화를 `--conversation`으로 이어받는지**는 확인하지 않았다 (대화는 로컬 `conversations/*.db`라 될 것으로 보이나 미확인) | ❓ |

| A35 | agy는 진짜 대화 ID를 stdout으로 알려 준다: `init.conversation_id`, 모든 `step_update.conversation_id`, `result.result.conversation_id`. 우리가 `--conversation`으로 넘긴 유령 ID와 **다른 값**이고(A22), agy 로그에 `Created conversation <id>`, `conversations/<id>.db`가 생긴다 | ✅ 2026-09-20 프로브 (유령 `16d6f861…` → 실제 `fd45a3f5…`) |
| A36 | 챗봇이 저장한 agy `conversation_id`는 **114개 세션 중 0개**가 agy 저장소에 실재했다(유령 ID). 그래서 프로세스를 다시 띄울 때마다(유휴 정리·전환·정지·크래시) 매번 `not found, ignoring --conversation flag`로 **빈 새 대화**가 시작됐고, 지침 재주입 조건(대화 ID 기준)도 안 걸려 페르소나·규칙·맥락이 모두 사라졌다 | ✅ 로그·저장소 대조 → 수정: 보고된 ID를 채택 + 재기동 시 없으면 재주입(`session._resume_or_reseed`) |
| A37 | 도구 호출 스텝의 스트림 모양: `step_update{step_type:"tool", state:ACTIVE→DONE, tool_name, tool_info:{name, parameters:{AbsolutePath,…}, output}}`. DONE만 세면 호출당 1번 | ✅ 2026-09-20 프로브 |
| A38 | `--print-timeout`(8분)이 지나면 agy는 턴을 **빈 `result`**로 끝내는데 **에이전트는 그 뒤에도 눈에 안 보이게 계속 돈다**(00:40:30 시작 → 00:48:30 빈 결과 → 01:03:42 프로세스 종료). 챗봇은 빈 결과를 "완료"로 처리해 화면에 아무것도 안 남았다 → 미완료 결과(`status`≠SUCCESS, 또는 타임아웃 근처의 빈 결과)는 알리고 자식을 정지 | ✅ 세션 이벤트·agy 로그 대조 |
| A39 | Gemini가 코드 작업 중 무한 반복에 빠진다(운영자 관찰: "확실히 많다"). 실제 사례: `view_file`이 254번, `static/app.js`만 239번 — (a) 같은 15줄 창을 79번·60번 그대로 반복, (b) 큰 파일을 15줄씩 186번 연속 훑기. 인자에는 모델이 쓴 `toolAction`/`toolSummary`가 섞여 서명에서 빼야 한다. 스트림의 도구 요약은 직전과 같으면 화면에서 걸러져 **아무것도 안 보였다** → `loop_guard.py`(반복 감시, 기본 켜짐) | ✅ transcript 분석 |
| A40 | 기동 직후(약 4초 이내)에 stdin을 쓰면 `result{status:"ERROR", error:"interrupted"}`가 2초 안에 나오는 경우가 있었다(프로브 3회 중 2회, 9초 대기하면 정상). 실서비스에서의 빈도는 조사하지 않았다 | ⚠ 프로브만 / ❓ 실서비스 |

| A41 | 턴이 진행 중일 때 stdin에 쓴 두 번째 메시지는 **진행 중인 턴을 방해하지 않고 대기열에 쌓였다가 그 턴의 `result` 뒤에 새 턴으로** 처리된다(`sleep 6` 세 번이 모두 끝난 뒤 "끝"(+30.7s), 이어서 새 입력 → "수정됨"(+36.7s)). 진행 중인 턴에는 반영되지 않는다. `--input-format` 도움말도 "runs a turn for each" | ✅ 2026-09-20 프로브 |
| A42 | 대화형 TUI에는 `store.(*Manager).sendMessageOrSteer`가 있으나 print/stream-json 모드에는 끼워 넣기 입력이 없다 (바이너리 심볼 + 도움말 기준) | ✅ / 실제 TUI 동작은 ❓ |
| A43 | `agy agentapi send-message <대화> <내용>`은 `ANTIGRAVITY_LS_ADDRESS`와 언어 서버의 **CSRF 토큰**이 필요하다("missing CSRF token") — 자식이 자기 도구용으로 갖는 값이라 바깥에서 쓸 수 없다. 토큰을 빼내는 우회는 하지 않았다 | ✅ 2026-09-20 |
| A44 | 도구 스텝 **경계**에서 자식을 멈추고 **진짜 대화 ID**(A35)로 재기동하면 하던 일이 보존된다: 세 번 중 한 번을 끝낸 시점에 새 지시를 끼워 넣었더니 같은 대화로 재개돼 **남은 두 번만** 실행하고(총 3번) 새 지시("수정됨")를 반영했다 | ✅ 2026-09-20 실서버 (agy 기록으로 확인) |
| A45 | 범위(`StartLine`/`EndLine`) 없이 큰 파일(`adapters.py` 1949줄·94KB)에 `view_file`을 부르면 **스트림의 `tool_info.output`은 `1949 lines, 94302 bytes` 한 줄뿐**이다(2회 프로브 모두 5개 호출 전부 동일). 그러나 **모델은 내용을 본다** — 같은 턴에서 클래스 위치를 정확히 답했다(`OpenAIDialectAdapter` 1536줄, 실제와 일치; input 85,035토큰). 즉 이 출력은 표시용 요약이라 **출력 해시는 범위 없는 전체 읽기의 반복 판별에 정보가 없다**(인자가 같으면 무조건 '같은 출력'). 정상 턴에서도 같은 전체 읽기를 2~3번 부른다 → 2026-09-21 루프(10회)의 원인은 '내용을 못 받아서'가 아니다(가설 기각). 남은 원인 후보: 무거운 문맥의 Gemini flash-low가 편집 전에 같은 파일을 되읽는 습관(❓ 미검증), 한 번에 ~25k토큰씩 들어가 비용도 큼 | ✅ 2026-09-21 `tests/probes/agy_bigfile_view.py` (원문 `/tmp/agy_bigfile_view.jsonl`) |
| A46 | 루프 재현 시도(1회): 큰 파일 편집 지시(`OpenAIDialectAdapter`에 `base_url` 받는 `__init__` 바로 적용, /tmp 복사본, 가벼운 새 대화, flash-low)를 주자 45초·도구 11번 만에 끝났고 **루프는 나지 않았다**. `view_file` 전체 읽기는 1·3·5번째로 **다른 도구(grep) 사이에 끼어 3번** 반복됐다(모두 같은 요약 출력) — 연속 아님·6회 미만이라 `loop_guard` 재생 결과 조용. 이후 복사본이 git 저장소가 아니라는 걸 보고 `find`/`locate`로 파일 시스템을 헤매다 스스로 `manage_task kill`, 턴은 `status:ERROR, error:interrupted`로 끝남(복사본은 수정되지 않음). → 사고 재현엔 부족: 사고 세션은 `session_heavy` 문맥(DEVLOG 347KB 전체 읽기 이력)이었고 이 실험은 가벼운 문맥이었다. 가설 "무거운 문맥 + 편집 전 되읽기"는 **미검증 그대로** | ⚠ 1회 / ❓ 무거운 문맥 |
| A47 | 루프 경고 시 스텝 경계에서 멈추고 **같은 대화 ID로 재개하며 방향 전환 알림**을 넣는 자동 개입을 구현(`session.py` `_notice_loop`, A44 재개 경로 재사용). 알림 뒤 3회 더 반복하면 중단. **알림이 루프를 실제로 끊는지는 미측정** — 루프 재현 실패(A46). 다음 사고의 `events.jsonl`(`evidence.action="notice"` 이후 호출 패턴)로 판정 | ⚠ 단위 테스트만 / ❓ 라이브 효과 |

## 5. 아직 안 해 본 것 (다음 실험 후보, 우선순위 순)

1. **WORKSPACE를 홈 트리 밖의 실제 위치로 옮기기** (심볼릭 아님). A4로 홈 밖이 싸다는 건 사본으로 확인됨. 미확인: 훅·MCP가 정상 동작하는지, 기존 대화 이어받기(A14)가 깨지는 범위. 기존 세션 141개에 영향 → 계획 후 착수.
2. ~~조상 `.agents/` 스캔을 끄는 설정 키~~ — **읽어 봤고 없다** (A27). 남은 건 바이너리 내부라 확인 불가.
3. 47k 중 스킬 색인 몫을 분리 측정 (임시로 홈 밖에 스킬 N개만 두고 개수-토큰 곡선). 
