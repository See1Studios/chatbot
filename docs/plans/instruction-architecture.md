# 냥피디 지침 아키텍처 — 멀티 프로바이더 동일 동작 설계

상태: **부분 구현 (P1 커밋됨, P2 일부 디스크·미소생).** 작성 2026-09-19.
프로바이더 CLI의 실측 동작은 [`docs/providers/`](../providers/README.md)가 SSOT — 이 문서의 F항목은 거기서 인용한다.

전제(실장님): **모든 프로바이더에서 동일한 동작.** 페르소나뿐 아니라 지침 인식, 스킬, 기억,
자기관찰 사이클까지 (`cross-cutting-principles.md` #8 의 연장).

## 1. 왜 지금 손봐야 하나 (실측 근거, 2026-09-19)

| # | 사실 | 근거 |
|---|---|---|
| F1 | agy는 `--add-dir`에 **홈 저장소 안의 폴더**를 주면 첫 턴 입력이 12,957 → 47.7k. 원인은 워크스페이스 문서가 아니라 **홈의 `.agents` 스킬 묶음(SKILL.md 2,649개) 스캔** — agy 자체 로그로 확인, 홈 밖 사본은 +0.8k. `AGENTS.md`는 원인이 아님(없애도/stub으로 바꿔도 46.7k). 격리 플래그·HOME·프로젝트 지정은 전부 무효 | [agy.md](../providers/agy.md) A1–A14 |
| F2 | agy는 **`--add-dir` 폴더에서만** 자동 발견한다(cwd만으로는 아무것도 안 읽음). add-dir 폴더에서 **저장소 루트까지 위로 걸으며** `AGENTS.md`와 `.agents/skills`를 모은다. `CLAUDE.md`, `.claude/skills`는 안 읽음 | 카나리 + 모방 트리(P0) |
| F3 | Claude는 cwd에서 저장소 루트까지 **`CLAUDE.md`와 `.claude/skills`만** 읽는다. `AGENTS.md`, `.agents/skills`는 **안 읽음**. `ClaudeAdapter` docstring("AGENTS.md 자동 발견")은 사실이 아니었다 | 카나리 + 모방 트리(P0) |
| F4 | Codex는 `AGENTS.md`를 읽고 `.agents/skills`도 발견한다(워크스페이스·저장소 루트 둘 다 스킬 이름을 정확히 댐). **초기 기록("스킬 못 찾음")은 오판** — 답이 `SKILL-441`로 잘려 토큰 대조에 실패했던 것. 층별로 어떤 `AGENTS.md`를 읽었는지는 미확정(카나리 문구 "비밀"에 거부 응답) | 카나리, 재실측은 사용 한도로 차단(2026-10-09 이후) |
| F5 | Grok은 (문서상) `AGENTS.md`+`CLAUDE.md`를 **repo root부터 cwd까지 모두** 읽고, `.agents/skills`·`.claude/skills`·`~/.claude/skills`도 스캔. `--rules`로 시스템 프롬프트에 규칙 추가 가능. **실측 불가: 계정 402(잔액 소진)** | `~/.grok/docs`, 실호출 실패 |
| F6 | 시스템 프롬프트 채널: claude `--append-system-prompt[-file]` 있음, grok `--rules` 있음, codex 있음(미확정), **agy 없음**, omniroute는 system message | `--help` |
| F7 | `persona_injected`는 `meta.json`에 **저장되지 않는다** → 서버 재기동 후 재개된 대화에 페르소나 재주입(중복). `maybe_swap_provider()`는 `handoff_injected`만 리셋하고 `persona_injected`는 안 건드림 → **도중에 프로바이더를 바꾸면 새 프로바이더는 페르소나를 못 받는다** | `session.py:428,469,1615` |
| F8 | 장기 기억 `MEMORY.md` 비어 있음, 이벤트 로그가 있는 9개 세션 중 `memory.py` 호출 0건. 지침이 "shell로 `python3 tools/memory.py`"를 시키는데 omniroute는 shell이 없다 | 세션 로그, `AGENTS.md` §2 |
| F9 | 관찰 훅(`task-observer`)은 `.agents/hooks.json`이라 **agy만** 실행. 관찰 로그는 09-18 19:05(0026)에서 멈췄고 `last-review-date`는 09-16 | 파일 mtime |

한 줄 요약: 지금 구조는 **"프로바이더가 알아서 읽어주길 기대"** 하고, 기대가 프로바이더마다 다르게
맞거나 틀린다. 그리고 지침에 "모델이 스스로 도구를 불러라"로 적어 둔 기억·관찰은 실제로 안 돈다.

### 1a. P0 결과 — 조상 디렉토리까지 포함한 발견 매트릭스 (모방 트리, 2026-09-19)

모방 트리: `git init` 루트에 `AGENTS.md`/`CLAUDE.md`/`.agents/skills`/`.claude/skills`, 스폰 cwd(워크스페이스)에도 동일. 각 층에 다른 카나리.

| 프로바이더 | 루트 `AGENTS.md` | 워크스페이스 `AGENTS.md` | 루트 `CLAUDE.md` | 워크스페이스 `CLAUDE.md` | `.agents/skills` (루트+ws) | `.claude/skills` (루트+ws) |
|---|---|---|---|---|---|---|
| agy (add-dir=ws) | 읽음 | 읽음 | 안 읽음 | 안 읽음 | 둘 다 | 안 봄 |
| agy (add-dir 없음) | 안 읽음 | 안 읽음 | 안 읽음 | 안 읽음 | 안 봄 | 안 봄 |
| claude | 안 읽음 | 안 읽음 | 읽음 | 읽음 | 안 봄 | 둘 다 |
| codex | 미확정 | 미확정 | - | - | 둘 다 | - |
| grok | 문서상 읽음 | 문서상 읽음 | 문서상 읽음 | 문서상 읽음 | 문서상 둘 다 | 문서상 둘 다 |

시사점:
- **조상은 프로바이더마다 다르게 합쳐진다.** 실제 호스트에서 `~/AGENTS.md`(호스트 헌장 7KB)와 `~/.agents/skills`(호스트 스킬 약 146개)가 agy/codex/grok에는 자동으로 들어가고, Claude에는 들어가지 않는다(`~/CLAUDE.md`는 "AGENTS.md를 읽어라"라는 포인터). 즉 **같은 워크스페이스인데 프로바이더마다 보이는 스킬 집합이 다르다.** 자동 발견에 기대는 한 동일 동작은 불가능하다.
- 자동 발견은 프로바이더마다, 그리고 **작업공간 밖의 조상 층까지** 달라서 워크스페이스가 통제할 수 없다. 그래서 스킬은 색인(L0)과 `skill_get`(L1)이 기준이고 자동 발견분은 "덤"이라고 규칙에 못박고, 층별 차이는 적합성 테스트에서 **기록만** 한다(T3).
- (정정) 초안은 "워크스페이스 `AGENTS.md`를 본문 없는 stub으로 두면 무해"라고 했으나 **실측으로 반증**됐다(agy.md A12). stub·`rules/` 이동은 철회.
- 카나리는 **"비밀" 같은 단어를 쓰지 말 것.** codex가 보안 요청으로 받아들여 답을 거부했다.

## 2. 설계 원칙

1. **호스트가 유일한 주입자.** 지침 묶음(bundle)은 `session.py` 어댑터 위에서 한 번 조립해 모든 프로바이더에 같은 텍스트로 전달한다. 프로바이더의 자동 발견은 **기대하지 않는다**.
2. **자동 발견에 기대지 않는다.** 프로바이더별 발견 범위는 다르고(README 교차 요약) 워크스페이스가 못 막는 조상 층도 있다. 어느 프로바이더가 무엇을 읽든 결과가 같도록 **호스트 주입본이 기준**이고, 자동 발견분은 있어도 없어도 되는 덤이다. (stub 방식은 철회 — 원인이 아니었음)
3. **능력은 MCP에.** 기억·스킬 조회·관찰 기록은 shell 스크립트나 훅이 아니라 `nas_mcp` 도구로. 모든 프로바이더(omniroute 포함)가 같은 경로로 닿는다 (#8).
4. **강제는 코드가, 권고는 지침이.** "세션 시작 때 memory show 해라" 같은 모델 자율에 맡기던 것은 호스트가 주입/호출한다.
5. **주입은 멱등·검증 가능.** 언제 무엇을 넣었는지 `meta.json`에 남기고, 회귀는 적합성 테스트가 잡는다.

## 3. 지침 묶음 (Bundle) 계층

| 층 | 내용 | 전달 | 예산 |
|---|---|---|---|
| L0 상시 | `PERSONA.md`, 헌장(`AGENTS.md`), **`MEMORY.md` 스냅샷**, **스킬 색인**(이름+한 줄) | 호스트가 첫 턴에 주입 | ≤ 6k 토큰 |
| L1 필요시 | `PROJECT.md`, `SELF-MODIFY.md`, `EMERGENCY.md`, 스킬 본문 | MCP `rules_get(name)`, `skill_get(name)` | 요청 시만 |
| L2 기록 | 기억 추가/삭제/검색, 관찰 기록 | MCP `memory_*`, `observe_add` | 요청 시만 |

호스트 헌장(`~/AGENTS.md`, 7KB)은 자동 발견 경로(repo root 상위)로 일부 프로바이더에만 들어간다(F5). **결정 필요** → §8-2.

스킬 색인은 `SKILL.md` frontmatter에서 자동 생성한다. 워크스페이스 스킬 4개 + 고정(pin) 목록만 색인하고,
호스트 전체 스킬(약 146개)은 `skill_search(query)`로 찾게 한다(색인 비대화 방지).

## 4. 문서 트리 (현행 유지)

파일을 옮기지 않는다. 측정상 자동 발견되는 이름은 `AGENTS.md`(와 `CLAUDE.md`)뿐이고, 나머지 규칙 파일은 무해하며(agy.md A4),
`AGENTS.md`도 토큰 세금의 원인이 아니라(A12) 옮길 이유가 없다. `rules/` 재배치와 stub은 철회 — 옮기면 `RULE_FILES`,
`_self_status()`, UI 규칙 편집기 경로만 흔들고 소득이 없다.

```
~/AGENTS.md                         # 호스트 헌장 (변경 없음, Priority 0)
services/chatbot/
  instructions.py                   # 지침 묶음 조립 (신규) — AGENTS.md + PERSONA.md + 스킬 색인 + 기억 + 관찰 상태
  data/workspace/                   # 스폰 cwd
    AGENTS.md  PERSONA.md           # L0 (호스트가 주입)
    PROJECT.md  SELF-MODIFY.md      # L1 (필요시 읽음)
    cross-cutting-principles.md
    memory/MEMORY.md                # L0 스냅샷 원본 (≤4KB)
    .agents/skills/*                # 워크스페이스 스킬 (SSOT), 색인 대상
    skill-observations/             # observation-log/ (+ 후속 candidates.jsonl)
  docs/providers/                   # 프로바이더 CLI 실측 SSOT (신규)
  docs/plans/instruction-architecture.md
  tests/test_instructions.py        # 묶음·주입 계약 단위 테스트 (신규)
  tests/probes/                     # 실측 프로브 스크립트 (신규)
```

## 5. 주입 계약 (Injection Contract)

- **주체:** `session.py`의 `_send_direct()` 한 곳. 어댑터는 모른다.
- **키:** `(session, conversation_id, bundle_hash)`. `meta.json`에 `injected_conversation_id`, `injected_bundle_hash` 저장.
- **재주입 조건:** 그 conversation_id로 아직 안 넣었을 때 (신규 세션, 회전 후 새 세션, **프로바이더 교체로 conversation_id가 바뀐 때**), 또는 `bundle_hash`가 바뀌었을 때(규칙 갱신 — 전체 재주입, 드묾).
- **재주입 금지:** 서버 재기동 후 같은 conversation_id로 재개(F7 중복 제거).
- **순서:** `[규칙 묶음]` → `[인계 맥락]`(있으면) → `[실장님의 현재 메시지]`. 인계 프레임 문구는 지금 그대로.
- **전송 채널:** 모든 프로바이더에 **사용자 턴 앞머리**로 동일하게. claude `--append-system-prompt`, grok `--rules`는 채널이 있지만 쓰지 않는다 — 채널 차이가 곧 동작 차이라서. (성능·캐시 이득이 실측으로 크면 재검토, 기본값은 동일 채널.)
- **제외:** 채팅 UI/`history`에는 원문 메시지만 남기고 묶음은 남기지 않는다(지금과 같음).

## 6. MCP 도구 (신규; 구현은 코어 어댑터 `mcp_core.py`, 서버 `mcp_server.py` — 2026-09-21 기준)

| 도구 | 역할 | 대체하는 것 |
|---|---|---|
| `memory_show / add / forget / search` | `MEMORY.md` CRUD | `python3 tools/memory.py` (shell 필요) |
| `recall(query, recent)` | 세션 아카이브 검색 | `tools/recall_memory.py` |
| `rules_get(name)` | L1 문서 조회 | "SELF-MODIFY.md 전체를 읽는다" |
| `skill_get(name)`, `skill_search(q)` | 스킬 본문/검색 | 프로바이더별 스킬 자동 발견 |
| `observe_add(title, body)` | `observation-log/` 한 건 추가 | task-observer 훅 |

호스트 전용 로직이 필요하면 `nas_mcp_host.py` 플러그인에 둔다(#8 관례). shell 없는 프로바이더도 동일하게 호출 가능해야 한다.

## 7. 자기개선 사이클 (호스트 구동)

목표 사이클: **관찰 → 기록 → 참조 → 반영.**

1. **관찰:** 턴 종료 시 호스트 훅 `on_turn_end()`가 신호를 감지 — 사용자 정정("아니", "왜 안", "망가"), 중단(stop), 도구 오류, 세션 회전. 후보를 `candidates.jsonl`에 한 줄 append. (프로바이더 훅 미사용 → agy 전용 문제 해소, F9)
2. **기록:** 모델이 의미 있다고 판단하면 `observe_add`. 없어도 후보는 남는다.
3. **참조:** 첫 턴 주입에 "열린 관찰 N건, 마지막 리뷰 D일 전"을 한 줄 넣는다(현재 훅이 하던 일을 코드로).
4. **반영:** 리뷰(수동 또는 `/review` 슬래시)에서 후보→`observation-log` 승격→작업→`actioned`. `last-review-date` 갱신.

주기 실행(스케줄러)은 이 NAS에 `crontab`이 없어 별도 결정이다 → §8-4.

## 8. 결정 기록

실장님 "추천대로 해" (2026-09-19)로 1~3은 권장안 채택. 4는 권장안이 없어 미정.

1. ~~채택: 자동 발견 무해화(stub)~~ **철회 (2026-09-19).** stub이 무해하다는 가정이 실측으로 틀렸다(agy.md A12). 대안 "WORKSPACE를 `--add-dir`에서 빼기"는 훅(A18)·MCP가 죽어서 배제. **agy의 47k는 격리 수단이 없어 미해결** — agy.md §5 참고.
2. **채택:** 호스트 `~/AGENTS.md`는 요약 20줄만 헌장에 포함, 전문은 `rules_get("host")`. (P0로 조상 층은 프로바이더마다 다르게 들어온다는 게 확인돼 더 필요해짐.)
3. **채택:** 주입 채널은 사용자 턴 앞머리로 통일.
4. **미정:** 관찰 리뷰의 자동 실행 방식. 호스트 내부 타이머 스레드 / 수동 `/review`만 / 없음. (P4 착수 전에 정하면 됨.)

## 9. 검증 설계

### 9.1 원칙
- **카나리로 증명한다.** "그럴듯한 답"이 아니라, 정해진 토큰이 답에 나타나는지 본다.
- **격리:** 프로덕션 파일은 건드리지 않는다. `CHATBOT_RULES_DIR`/`CHATBOT_WORKSPACE`를 임시 트리로 돌려 실제 조상(`~/AGENTS.md` 등) 구조를 흉내낸 **모방 트리**(`/tmp/x/AGENTS.md`, git init, `services/chatbot/data/workspace/...`)에서 실행한다. 조상 발견은 위치에 따라 달라서, 임시 폴더 하나로는 재현되지 않는다(이번 실험의 한계).
- **호스트 동일 인자:** 어댑터 `build_args/build_env`를 그대로 쓴다.

### 9.2 테스트 (프로바이더 5종 × T1~T9)

| ID | 내용 | 통과 조건 |
|---|---|---|
| T1 정체성 | 새 세션 "너 누구야? 나를 뭐라 불러?" | 냥피디 / 실장님 |
| T2 주입 도달 | 임시 규칙에 카나리 `RULE-CANARY-n` | 전 프로바이더가 인용 |
| T3 발견 기록 | 모방 트리의 각 층(루트/cwd) × 관례(`AGENTS.md`, `CLAUDE.md`, `.agents/skills`, `.claude/skills`)에 카나리 | 통과/실패 없음. 프로바이더별로 무엇이 보이는지만 README 교차 요약에 기록 (`tests/probes/discovery_canary.py`) |
| T4 기억 왕복 | "X 기억해" → `memory_add` 호출 → 새 세션, 다른 프로바이더에 "X가 뭐였지?" | 정답 |
| T5 스킬 | 색인에 있는 카나리 스킬을 물음 | `skill_get` 호출 후 본문 카나리 인용 |
| T6 교체 | 같은 세션에서 A→B 프로바이더 교체 | 정체성·기억 유지 (F7) |
| T7 재개 | `meta.json`에서 세션 복원 | 묶음 재주입 0회 |
| T8 예산 | 첫 턴 입력 토큰 | 프로바이더별 기준선 + 6k 이하, 도구 호출 0 |
| T9 관찰 | 스크립트된 정정 턴 | `candidates.jsonl`에 1줄 |

### 9.3 합격 기준
- 5×9 표가 전부 통과하거나, 실패는 **이유와 함께** 표에 남긴다(예: grok 402 → 미검증).
- 결과는 `docs/instruction-conformance.md`에 날짜·버전(각 CLI `--version`)과 함께 기록한다. 규칙·어댑터를 바꿀 때마다 재실행.
- 회귀 방지: `ctl doctor`에 T2/T3만 가벼운 스모크(프로바이더 1개)로 연결하는 것은 후속.

## 10. 단계

| 단계 | 내용 | 소생 | 위험 |
|---|---|---|---|
| P0 | 모방 트리로 조상 발견 실측 — **완료 (agy/claude)**. codex는 카나리 재실측이 사용 한도로 차단(~10-09), grok은 잔액 소진(402) | 불필요 | 낮음, 읽기 전용 |
| P1 | 결함 수정: `persona_injected` 저장(`meta.json`), 프로바이더 교체 시 리셋, `ClaudeAdapter`/`_persona_system_prompt` docstring 정정 — **디스크 수정·단위 검증 완료, ⚡소생 대기** | 필요 | 낮음 |
| P2 | 묶음 조립기(`instructions.py`) + 주입 계약(§5): 해시 기반 갱신·구 세션 무중복·HTTP 앞머리 생략·인계 뒤 덮어쓰기 결함 수정 — **디스크·단위 테스트 13개 완료, ⚡소생 대기.** `rules/` 이동·stub은 철회 | 필요 | 중 |
| P2b | agy 홈 스킬 스캔(47k) 격리 — **수단 미발견.** 후보는 agy.md §5 (WORKSPACE를 홈 밖 실경로로 이전 등) | 필요 | 높음 (기존 세션 141개 이어받기) |
| P3 | MCP 도구(§6) | 필요 (`nas_mcp`) | 중 |
| P4 | `on_turn_end` 관찰 + 첫 턴 관찰 요약 | 필요 | 낮음 |
| P5 | 적합성 테스트 + 결과표 + DEVLOG | 불필요 | 낮음 |

P1은 독립적으로 먼저 가능하다. P2~P4는 §8 결정 후.

## 11. 알려진 한계 (지금 시점)

- **Grok은 계정 잔액 소진(402), Codex는 사용 한도 도달(~2026-10-09).** 두 프로바이더는 지금 적합성 테스트를 돌릴 수 없다. Grok 발견 규칙은 문서 기반, Codex는 층별 `AGENTS.md` 발견이 미확정. 한도가 풀리면 P0와 §9.2를 다시 돌려 표를 채운다.
- Codex `developer_instructions` 류 채널은 확인 안 함(채널 통일 방침이라 당장은 불필요).
- 47.7k 중 `AGENTS.md` 몫과 나머지를 정확히 분해하지 못했다(F1). P2 이후 재측정으로 검증한다.
- 모방 트리는 실제 호스트와 조상 구성이 다르다(실제는 `~/.agents/skills` 약 146개, `~/.claude`). 조상 층의 **양**이 토큰에 미치는 영향은 P2 이후 실제 트리에서 재측정한다.
