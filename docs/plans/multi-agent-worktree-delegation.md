# 멀티 에이전트 Git Worktree 격리 외주 계획서 (Multi-Agent Worktree Delegation)

> 방향 (align/D, 2026-09-28): **개발판 전용 + 핵심** — §1–10·§13의 코드 위임(워크트리·러너·PD 계획)은 개발판 전용(align D2). §11–12의 캐릭터·역할 팩·팀 편성은 규칙 층 개인화로 배포판 핵심

- **작성일:** 2026-09-23
- **상태:** 계획 (Proposed)
- **대상:** `services/chatbot/`, `~/bin/`, `~/tools/`
- **표기:** 사람과 에이전트는 역할로 부른다(사용자, chat-agent, 작성자·리뷰어 캐릭터). 페르소나 이름과 호칭은 인스턴스의 identity 파일에 있는 표시값이다(자기진화 설계 §7-8).

---

## 1. 배경 및 목적

### 1.1 배경
- 현재 chat-agent는 단일 런타임 호스트(`server.py`) 위에서 사용자의 질의 응답, NAS 운영, 자기수정을 단일 컨텍스트로 처리하고 있다.
- 복잡한 코드 리팩토링이나 심층 조사, 다단계 기능 개발을 단일 대화 컨텍스트에서 수행하면 **컨텍스트 팽창, 토큰 소모 극대화, 세션 지연**이 발생한다.
- 호스트에는 이미 최고 수준의 코딩 CLI들(`claude`, `codex`, `agy`, `grok`)이 설치되어 비대화형/헤드리스 실행을 완벽하게 지원하고 있다.
- 특히 **Claude Code(`claude`)의 백그라운드 에이전트 및 Git 기반 분기 모델**과, chat-agent가 기보유한 **재귀적 자기진화 거버넌스(`tickets.py`의 근거·승인·리스·검증 계약)**는 본질적으로 동일한 "호스트 무중단 격리 안전성"을 지향한다.

### 1.2 목적
- chat-agent를 **"총괄 / 오케스트레이터"**로 두고, 세부 구현·검증·심층 리서치를 **독립된 Git Worktree 격리 환경**에서 외부 CLI 서브에이전트에게 외주(`delegate`)를 주는 파이프라인을 구축한다.
- 라이브 호스트와 작업 디렉토리가 오염되지 않도록 완벽히 격리하며, 작업 결과물은 Git 커밋 및 diff 단위로 검증 후 메인 브랜치에 안전하게 병합한다.

---

## 2. 핵심 아키텍처 및 원칙

### 2.1 3대 철학 (See1 & Ponytail 원칙)
1. **SSOT & 최소 토큰 (Zero Bloat):**
   - 불필요한 데몬이나 무거운 외부 오케스트레이터를 신설하지 않는다.
   - 이미 검증된 Linux 표준 도구(`git worktree`, `bash`, `subprocess`)와 기존 티켓 시스템(`tickets.py`, `ticket-quick`)을 최대한 재활용한다.
2. **호스트 불변성 (Host Immunity):**
   - 외주 작업 중 외부 CLI가 실수를 하거나 비정상 종료되더라도 라이브 호스트는 털끝 하나 다치지 않는다.
   - 모든 수정 작업은 임시 Worktree 디렉토리 내에서만 일어나며, 실패 시 Worktree 삭제(`git worktree remove`)만으로 원상복구된다.
3. **티켓 기반 거버넌스 (Evidence & Approval):**
   - 코드를 건드리는 모든 외주 작업은 헌장에 따라 승인된 티켓과 유효한 리스(Lease)를 바탕으로 실행된다.

---

## 3. 작업 라이프사이클 (Worktree Delegation Flow)

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자 (operator)
    participant NP as chat-agent (총괄)
    participant TK as 티켓 시스템 (tickets.py)
    participant WT as Git Worktree (격리 환경)
    participant CLI as 외부 에이전트 (Claude/Codex/Agy)

    User->>NP: 기능 개발 / 리팩토링 지시
    NP->>TK: 티켓 생성 및 사용자 승인 확인 (or ticket-quick)
    NP->>WT: 임시 브랜치 및 Worktree 생성 (git worktree add)
    NP->>CLI: 격리 디렉토리 내 헤드리스 실행 (claude -p / codex exec / agy)
    CLI-->>WT: 코드 작성, 테스트 실행, 로컬 커밋
    CLI-->>NP: 작업 완료 및 exit code / 요약 보고
    NP->>WT: 결과 diff 확인 및 스모크 테스트 (tests/smoke.py)
    alt 검증 통과
        NP->>NP: 메인 브랜치로 병합 (git merge / cherry-pick)
        NP->>TK: 티켓 완료 (done & clean 상태)
        NP->>WT: Worktree 및 임시 브랜치 정리 (git worktree remove)
        NP-->>User: 완료 보고 (필요 시 ⚡소생 요청)
    else 검증 실패
        NP->>WT: Worktree 폐기 (git worktree remove --force)
        NP->>TK: 실패 기록 및 재시도/보류 (gate_failures)
        NP-->>User: 실패 원인 보고 및 대안 제시
    end
```

---

## 4. 세부 구성 요소

### 4.1 Git Worktree 헬퍼 (`~/bin/worktree-runner` or Python 헬퍼)
- **경로 규칙:** `~/.worktrees/<ticket-id>/` 또는 `/volume1/homes/me/tmp-worktrees/<ticket-id>/`
- **명령 규격:**
  ```bash
  # 1. 생성 및 격리 환경 진입
  git worktree add -b "feat/ticket-<ID>" ~/.worktrees/<ID> HEAD
  
  # 2. 외부 CLI 호출 (예: Claude Code 헤드리스)
  cd ~/.worktrees/<ID> && claude -p "지시문..."
  
  # 3. 완료 후 브랜치 병합 및 정리
  git checkout main && git merge "feat/ticket-<ID>"
  git worktree remove ~/.worktrees/<ID>
  git branch -d "feat/ticket-<ID>"
  ```

### 4.2 제공자별 에이전트 실행 프로파일 (`adapters.py` 연계)
- **`claude` (Claude Code):**
  - 대규모 리팩토링, 복잡한 파이썬 모듈 구조화에 최적.
  - 실행 형태: `claude -p "<prompt>"` 또는 `claude --bg` 후 감시.
- **`codex` (Codex CLI):**
  - 빠른 스크립트 작성, 단일 파일 버그 패치, 단위 테스트 생성에 최적.
  - 실행 형태: `codex exec "<prompt>"`.
- **`agy` (Antigravity CLI):**
  - NAS MCP 및 고유 스킬 시스템과의 연동 작업에 최적.
  - 실행 형태: `invoke_subagent` 네이티브(share/branch 모드) 또는 `agy exec`.
- **`grok` (Grok CLI):**
  - 최신 웹 트렌드 조사, 크리에이티브 콘텐츠 초안 작성에 최적.

### 4.3 chat-agent MCP 인터페이스 (`delegate_task`)
- chat-agent가 런타임에서 호출할 도구 스펙:
  ```json
  {
    "name": "delegate_task",
    "description": "외부 CLI 에이전트에게 Git Worktree 격리 환경에서 작업을 위임하고 결과를 취합합니다.",
    "parameters": {
      "provider": "claude | codex | agy | grok",
      "instruction": "수행할 작업의 구체적인 프롬프트",
      "target_paths": ["services/chatbot/foo.py"],
      "ticket_id": 123
    }
  }
  ```

---

## 5. 단계별 실행 계획 및 현황 (Milestones & Status)

- **[마일스톤 1] Worktree 격리 실행 헬퍼 스크립트 PoC (완료 - 2026-09-23)**
  - 스크립트 구현: `tools/worktree_runner.py`
  - 검증 완료:
    - `codex` 헤드리스 실행 및 임시 격리 worktree 테스트 성공 (무오염 정리 확인).
    - `claude` (`claude -p --dangerously-skip-permissions`) 헤드리스 격리 테스트 성공 (10.08s 완료, worktree 내 파일 생성 및 메인 리포 완전 격리 검증).
- **[마일스톤 2] 티켓 연동 및 검증 게이트 결합 (구현 - 2026-09-23, claude-code)**
  - `tools/worktree_runner.py run`: `ticket-quick start` → `~/.worktrees/chatbot/ticket-<ID>` (브랜치 `worktree/ticket-<ID>`) → 에이전트 헤드리스 실행 → 게이트 → `git merge --ff-only` → `ticket-quick done` → 정리. `cleanup --ticket N`은 남은 worktree/브랜치 제거.
  - 게이트 순서: 커밋 존재(미커밋 변경은 러너가 제공자 author로 대신 커밋) → 범위(`--paths` 밖 변경 = gate_failed) → 리스 연장 → 메인이 움직였으면 rebase(충돌 = gate_failed) → `DEFAULT_GATES`(smoke + provider/name 중립성 가드) + `--gate` 명령들.
  - 실패: 병합 없음 → `ticket-quick fail --outcome gate_failed|failed` (티켓에 사유 노트, 시도 예산 차감) → worktree 폐기(`--keep`이면 보존).
  - `ticket-quick`에 `fail`, `renew` 서브커맨드 추가. 커밋 author는 제공자 레지스트리(`PROVIDERS`)의 신원으로 고정.
  - 에이전트 타임아웃은 작성자 리스(1800s) 안쪽으로 제한(최대 1500s). 라이브 호스트는 재시작하지 않는다.
  - 테스트: `tests/test_worktree_runner.py` (임시 리포 + 가짜 에이전트 + 가짜 ticket-quick, 8건). 실제 CLI로 도는 end-to-end 실행은 아직 안 했다.
- **[마일스톤 3] chat-agent MCP 도구 배선 (`delegate_task`)**
  - chat-agent가 대화 중 직접 판단하여 외부 에이전트에게 작업을 분배할 수 있도록 도구 등록.
- **[마일스톤 4] 다중 에이전트 토론/교차 검증 (Dual Loop)**
  - A 에이전트(코드 작성: Codex/Claude) -> B 에이전트(코드 리뷰: Claude/Agy) -> chat-agent 취합 보고.

---

## 6. Claude Code 인수인계 안내 (Handover for Claude Code)

### 6.1 현재 기준 상황
1. **PoC 스크립트 검증 완료**: `tools/worktree_runner.py`가 구현되어 있으며 `codex`와 `claude` 헤드리스 격리 생성이 정상 동작함을 실측했습니다.
2. **리포지토리 상태**: `services/chatbot` 메인 리포지토리는 깨끗한 상태(clean)입니다.

### 6.2 마일스톤 2 개발 목표
`tools/worktree_runner.py`를 고도화하거나 상위 래퍼를 구성하여 다음 라이프사이클을 완성해주세요:
1. **티켓 발급 & 클레임 연동**:
   - `~/bin/ticket-quick start --title "<제목>" --paths "<수정대상경로>"` 호출하여 `TICKET_ID`, `CLAIM_TOKEN` 획득.
   - 발급된 `TICKET_ID` 기반 브랜치(`worktree/ticket-<ID>`)로 worktree 생성.
2. **에이전트 헤드리스 실행 및 커밋 요구**:
   - 격리 환경에서 대상 에이전트(Claude 등)가 코드를 수정하고 브랜치 내에 commit을 남기도록 지시/처리.
3. **검증 게이트 (Verification Gate)**:
   - worktree 환경(또는 메인 스테이징 전)에서 `python3 tests/smoke.py` 실행.
   - 테스트 통과 시: 메인 브랜치로 merge (`git merge --ff-only` 또는 일반 merge) -> `~/bin/ticket-quick done --id <ID> --token <TOKEN>` 실행 -> worktree 정리.
   - 테스트 실패 시: merge 중단 -> worktree 정리 및 티켓 실패/에러 보고.
4. **주의사항**:
   - 헌장 규칙 준수: 티켓 대상 경로 커밋 상태 확인 및 무중단 유지.
   - 불필요한 의존성 없이 표준 라이브러리(`subprocess`, `pathlib` 등) 중심의 깔끔한 구현 유지.

---

## 7. 재평가 (2026-09-23, 마일스톤 2 구현 후)

PoC 이후 코드와 거버넌스를 대조해 보고 나온 점. 마일스톤 3 전에 결정이 필요한 순서대로.

1. **worktree는 파일시스템 격리가 아니다.** git 상태만 분리된다. `--dangerously-skip-permissions`로 도는 에이전트는 같은 사용자(`me`)로 메인 리포, `~/bin`, `data/secrets.env` 읽기, 서비스 재시작, `git push`까지 다 할 수 있다. 2.1-2의 "호스트 불변성"은 현재 프롬프트 지시와 범위 게이트(사후 검출)에 의존한다. 실제 격리가 필요하면 제공자 샌드박스(codex `-s workspace-write`, agy `--sandbox`, claude sandbox 설정)나 별도 사용자/컨테이너가 필요하다. 러너가 부모 환경변수를 그대로 넘기므로, 서버 안에서 부를 마일스톤 3에서는 환경변수를 허용 목록으로 걸러야 한다(API 키 유출 방지).
2. **승인 우회 문제.** `ticket-quick start`는 제안과 동시에 `operator (api)`로 승인한다. 사용자가 CLI로 직접 지시한 경우엔 맞지만, 마일스톤 3에서 chat-agent가 스스로 `delegate_task`를 부르면 "승인된 티켓만 실행"(2.1-3) 원칙을 스스로 뚫는다. `delegate_task`는 이미 사용자가 승인한(`approved`) 티켓 번호만 받고 claim만 하도록 해야 한다.
3. **작성자 리스가 호스트 전체에 하나다.** `tickets.py`의 `author.lease`는 전역 1개라서 외주가 도는 동안(최대 25분) 다른 티켓 작업, 즉 chat-agent 자신의 자기수정도 막힌다. 병렬 외주나 마일스톤 4의 동시 실행은 현 거버넌스로 불가능하다. 병렬이 목표라면 리스를 티켓(또는 경로 집합) 단위로 바꾸는 것이 선행 과제다.
4. **자동 병합 + 재시작 시 자동 반영.** 게이트를 통과하면 사람 리뷰 없이 main에 들어가고, 다음 `repair`나 워치독 재기동 때 라이브에 올라간다. 게이트는 smoke(7건)와 중립성 가드뿐이다. 선택지: (a) 경로별 관련 테스트를 자동으로 게이트에 추가(`foo.py` → `tests/test_foo.py`), (b) 병합 전 사용자 확인 모드(브랜치를 남기고 diff 요약만 보고).
5. **동기 실행.** `claude -p` 작업은 수 분에서 수십 분이 걸린다. 대화 턴 안에서 동기로 부르면 턴이 묶인다. 마일스톤 3은 백그라운드 실행 + 결과 파일/티켓 노트로 완료를 알리는 비동기 구조여야 한다.
6. **마일스톤 4(교차 검증)는 별도 단계보다 게이트 한 종류로 두는 편이 싸다.** 리뷰 에이전트가 `git diff base..HEAD`를 읽고 통과/탈락만 exit code로 돌려주면 `--gate`에 그대로 끼워진다.
7. **4.2 제공자 프로파일의 "최적" 분류는 실측 근거가 없다.** 명령 형태도 틀린 곳이 있었다(`agy exec` 없음 → `agy -p`). 러너의 `PROVIDERS`가 실제 명령의 SSOT다.

---

## 8. 콤비 리뷰 (DUO_REVIEW_v1, 2026-09-23) — 목적 재정의 후 첫 단계

사용자 결정(2026-09-23): 이 파이프라인의 목적은 **두 페르소나 캐릭터의 티키타카**이며, 그중 (A) "작업 과정 자체가 만담"을 먼저 한다. 사용자 개입은 최소, 병렬 실행은 하지 않는다(토큰 예산).

- **두 번째 캐릭터:** `data/workspace/PERSONA-reviewer.md` (role id `reviewer`). `identity.get_identity(role)` / `persona_body(role)` / `self_label(role)`이 `PERSONA-<role>.md`를 읽는다. 이름은 표시값이고, 코드·티켓에는 role id만 쓴다. 이 파일은 대화 에이전트의 규칙 번들(`instructions.RULE_BUNDLE_FILES`)에 들어가지 않는다.
- **라운드:** 작성자(PERSONA.md 캐릭터)가 작업·커밋하고, 마지막에 `---` 아래 캐릭터 대사를 남긴다 → 기계 게이트 → 리뷰어가 diff(또는 게이트 실패 내용)를 보고 `VERDICT / SAY / FIX`로 답한다. 게이트 통과 + PASS면 병합한다. 아니면 FIX를 들고 다음 라운드로 간다(`--rounds`, 기본 2). 판정을 읽을 수 없으면 FAIL로 본다.
- **토큰:** 리뷰어는 도구 없이 싼 모델로 돈다(claude: `-p --tools "" --model haiku`). 작성자 재시도는 claude면 `-c`로 같은 대화를 이어 간다. 다른 제공자는 전체 지시를 다시 보낸다. 순차 실행이므로 전역 작성자 리스와 충돌하지 않는다.
- **대사 기록:** `~/.worktrees/chatbot/transcripts/ticket-<ID>-<시각>.{md,json}`, `--json` 결과의 `transcript`. 채팅 화면 표시는 마일스톤 3의 몫이다.
- **다음:** 마일스톤 3에서 transcript를 채팅에 두 화자로 흘려 보낸다. §7-2(승인 우회)는 "사용자 개입 최소"에 맞게 경로 정책으로 푼다(워크스페이스 문서·스킬은 자동, 호스트 모듈은 승인). 배포 후 상태 점검에 실패하면 자동 롤백한다.

---

## 9. 사용자 워크플로우 (2026-09-23 사용자 결정, 마일스톤 3의 설계 기준)

결정: ① Tier 2는 한 탭 확인 ② 만담은 카드 안에 접힘 ③ chat-agent가 제안하고 사용자가 승인 ④ 결과는 다음 접속 때 본다. 모두 추천안 그대로다. Tier는 `recursive-self-evolution.md` §4.1을 따른다.

### 9.1 흐름

| 단계 | 사용자가 보는 것 | 사용자 행동 |
|---|---|---|
| 요청 | 대화 중 코드 작업 요청 → chat-agent가 **작업 카드**를 제안: 제목, 바꿀 파일, Tier, 예상 비용(라운드 수·모델) | Tier 0/1: 없음. Tier 2: `[맡겨]` 한 탭(= `/ticket go N`) |
| 관찰 티켓 | Evolution 탭의 티켓 | `/ticket go N` (지금과 같음) |
| 진행 | 카드 상태가 바뀐다: 작업 중 → 게이트 → 리뷰 (라운드 n/N). 카드에는 마지막 대사 한 쌍만, 펼치면 전 라운드 | 없음. 대화는 계속할 수 있다(비동기) |
| 통과 · Tier 0/1 | 병합 완료 카드 + diff 요약. 워크스페이스 파일이라 재기동 없이 반영 | 없음 |
| 통과 · Tier 2 | **병합 대기** 카드 + diff 요약 + `[병합·⚡]` `[보류]` | 한 탭. `[병합·⚡]`는 ff 병합 후 기존 ⚡ 경로(유휴 확인 후 repair) |
| 실패 | 만담으로 실패 사유 + `[다시 시도]` `[보류]`. 시도 예산이 다하면 `needs-human`으로 닫힘(기존 규칙) | 선택 |
| 부재 중 | 읽지 않은 결과 카드가 대화에 쌓여 있다가 다음 접속 때 보인다 | 없음 |

사용자 개입은 Tier 0/1이 0회, Tier 2가 2회(맡기기, 병합)다. 실패는 사용자가 원할 때만 개입한다.

### 9.2 작업 카드 상태

`proposed` → (`awaiting_go`: Tier 2만) → `running{round, phase: writing|gates|review}` → `merged` | `awaiting_merge`(Tier 2) → `merged` → (`deployed`: ⚡ 후) / `failed` / `held`

카드 한 장은 티켓 하나다. 상태의 원본은 티켓과 러너의 실행 상태 파일이다. 카드는 그것을 비출 뿐이다(서비스 자기 보고에 의존하지 않는다, 헌장 §7-7).

### 9.3 코드에 필요한 것 (마일스톤 3 작업 목록)

1. ✅ (#65) **경로 → Tier 정책을 설정 데이터로 둔다** (P1-5). 러너가 `--paths`로 Tier를 계산한다. **Tier 3 경로는 외주를 거부**한다: 가드, 티켓/진화 코어, 게이트로 쓰는 테스트(`DEFAULT_GATES` 대상), 헌장. 외주 에이전트가 자기 통과 조건을 고칠 수 없게 하기 위해서다(헌장 §7-5).
2. ✅ (#64, `fc0becd`) **러너 `--stop-before-merge`**: Tier 2는 리뷰 PASS 후 브랜치를 남기고 멈춘다. 별도 `merge --ticket N`이 ff 병합 → done → 정리 → 기록 커밋을 한다.
3. ✅ (#62, `01f8ea6`) **티켓 상태 `awaiting_merge`** (`tickets.py`, **Tier 3 거버넌스 변경이라 승인 필요**). 병합을 기다리는 동안 전역 작성자 리스를 쥐고 있으면 다른 작업이 모두 막힌다. 그래서 리스를 풀고, 시도 횟수를 늘리지 않고, 사용자 병합(`operator (ui)`)만 받는 상태가 필요하다.
4. ✅ (#64 진행 파일, #66 분리 실행) **비동기 실행 + 진행 파일**: 서버는 러너를 분리 프로세스(setsid)로 띄운다. 러너는 `~/.worktrees/chatbot/runs/ticket-<ID>.json`에 상태, 라운드, 지금까지의 대사를 원자적으로 쓴다. 서버는 그 파일을 읽어 카드에 준다. ⚡ 재기동에도 러너가 살아남아야 한다. `ctl_proc` 정리 대상은 cwd가 `data/workspace`인 에이전트라서 worktree에서 도는 러너는 겹치지 않는다. 구현할 때 확인한다.
5. ✅ (#66, 도구 이름 `delegate`: start/status. Tier 0은 사용자 요청으로 바로, Tier 2는 제안 → [맡겨]) **chat-agent 도구 `delegate_task(ticket_id)`**: 티켓 번호만 받는다. Tier 0/1은 chat-agent가 티켓을 만들고 바로 시작할 수 있다(기존 Tier 0/1 자율). Tier 2는 사용자가 승인한 티켓만 받는다(§7-2 해소). 러너에 넘기는 환경변수는 허용 목록으로 거른다(§7-1).
6. ✅ (#66, 입력창 위 작업 카드 줄. 읽음은 `data/delegation_seen.json`) **카드 UI**: 두 화자의 표시 이름·말투는 `identity.get_identity()`와 `get_identity("reviewer")`로 입힌다. 코드와 UI에는 이름을 박지 않는다(NAME_NEUTRAL_v1). 읽지 않음 표시는 기존 세션 동기화 경로를 쓴다.

### 9.4 하지 않는 것
- 병렬 외주 (토큰 예산, 사용자 결정 ③의 전제)
- 외부 푸시 알림 (결정 ④)
- Tier 2의 자동 병합·자동 ⚡ (결정 ①, 자기진화 설계 결정 3 유지)

---

## 10. PD 모델 (PD_PLAN_v1, 2026-09-23 사용자 결정)

챗봇 페르소나는 **PD**다. 사용자는 제안만 하고, PD가 계획하고, 분야별 전문가 캐릭터에게 맡기고, 결과를 확인하고, 보고한다. 컨펌은 사용자가 두 번 한다: **실행 전(계획)**과 **반영 전(최종)**. Tier 0도 자동 병합하지 않는다. 병렬 없음. 추가 전문가(AD·MD 등)는 나중에 정한다(지금은 `staff` 한 명).

```
사용자 제안 → PD 계획(delegate plan) → [실행] → 작업마다: 전문가 작업 → 게이트 → PD 확인(최대 2라운드)
           → 최종 확인 대기 → [승인] 반영(ff 병합) → 보고   /  [반려(코멘트)] 재작업  /  [폐기]
```

- **계획 = 티켓 하나 = worktree(브랜치) 하나.** 작업들은 같은 브랜치에 차례로 커밋한다. 승인하면 한 번에 병합, 폐기하면 브랜치째 버린다.
- **작업(task)**: `role`(전문가 role id, `PERSONA-<role>.md`), `title`, `instruction`, `paths`. 범위 검사는 작업마다 그 작업의 `paths`로, Tier 판정은 계획 전체 경로로.
- **상태**: `awaiting_go`(계획 카드: [실행]/[계획 수정]/[취소]) → `running`(작업 i/n, 라운드) → `awaiting_merge`(최종 확인: [승인]/[반려]/[폐기]) → `done`/`declined`.
- **반려**: 사용자 코멘트를 들고 같은 브랜치에서 재작업 한 번(새 시도로 계산) → 다시 최종 확인. `tickets.rework`(사용자 전용).
- **전문가 확장 지점**: 역할마다 `PERSONA-<role>.md`(캐릭터·지침). 스킬셋·모델·작업 공간(코드가 아닌 산출물)은 역할을 추가할 때 정한다.

---

## 11. 서브에이전트(전문가) 관리 (2026-09-23 사용자 결정)

배경: 상시 프로바이더는 Antigravity 하나(나머지는 간헐적). Claude·Antigravity 구독은 공식 CLI로만 쓸 수 있다(챗봇이 존재하는 이유). Hermes 프로필·칸반은 **본뜰 설계**일 뿐 섞지 않는다.

결정 (모두 추천안):
1. **전문가 = 폴더 하나** — `data/workspace/experts/<role>/`에 캐릭터·지침·스킬·기억·두뇌 설정을 담는다. 전문가 추가 = 폴더 추가.
2. **지속 전문가** — 작업이 끝나도 배운 것을 짧은 기억(크기 상한)에 남기고 다음 작업에 읽는다. 프로세스는 작업마다 새로.
3. **두뇌 = 전문가별 순서 목록 + 자동 대체** — 예: agy gemini-3.1-pro-high → agy gemini-3.8-flash-high → codex. 쿼터·한도·무응답이면 다음 두뇌로. 목록은 사용자가 정하고 PD는 바꾸지 못한다.
4. **PD가 제안, 사용자가 승인** — PD는 새 전문가나 변경을 제안(카드)만 한다. 승인 전에는 존재하지 않는다. 편집은 상태 탭.

### 11.1 모양 (초안)

```
data/workspace/experts/<role>/
  expert.md     머리말: persona(표시 이름), title, voice / 본문: 캐릭터 + 분야 지침 (영어, 원칙 0)
  brain.json    {"chain": [{"provider": "agy", "model": "gemini-3.1-pro-high"}, {"provider": "agy", "model": "gemini-3.8-flash-high"}]}
  memory.md     배운 것 (한 줄씩, 상한 2KB). 작업 뒤 러너가 전문가의 LEARNED 줄을 덧붙인다. 상태 탭에서 편집 가능
  skills.txt    쓸 수 있는 공용 스킬 이름 (선택)
data/workspace/experts/_proposed/<role>/   PD가 제안한 전문가 (승인 전)
data/workspace/pd-brain.json               PD 확인의 두뇌 목록
```

- 지금의 `PERSONA-staff.md`(루루)는 `experts/staff/`로 옮긴다.
- 카드·대사에는 누가 **어떤 두뇌로** 일했는지 표시하고, 대체가 일어나면 그 사실도 남긴다.

### 11.2 구현 순서 (제안)
1. ✅ (#88) 전문가 폴더 + 러너·identity가 읽기 + 루루 이전
2. ✅ (#88) 두뇌 목록과 자동 대체 (쿼터·한도·타임아웃 감지)
3. ✅ (#90, 상태 탭이 아니라 새 "팀" 탭) 두뇌 목록 편집 — 기억은 4단계 후
4. 지속 기억 (LEARNED → memory.md, 상한·중복 제거)
5. PD의 전문가 제안 → 사용자 승인

---

## 12. 캐릭터 중심 재정의 (2026-09-23 사용자 결정)

**이 앱의 차별점: 같은 캐릭터와 일도 하고 사적인 관계도 이어 간다.** 오케스트레이터(Hermes·kandev)는 일만, 캐릭터챗(CharacterAI·SillyTavern)은 관계만 한다. 여기에 구독 CLI 두뇌로 실제 일을 해낸다는 점(§0 왜 만드는가)이 더해진다. 냥피디의 업무·사적 모드가 씨앗이었고, 이제 루루를 포함한 모든 캐릭터로 넓힌다.

기본 단위는 "에이전트"가 아니라 **캐릭터**다. 냥피디는 PD 역할을 맡은 캐릭터 하나다(§11의 "전문가"는 캐릭터의 업무 면).

결정 (모두 추천안):
1. **기억은 캐릭터별, 업무·사적 공유** — 한 사람처럼 하나의 기억. 다른 캐릭터의 기억은 보지 않는다(루루에게 한 말을 냥피디는 모른다).
   - **수정 (2026-09-23, 사용자 결정):** 사적 대화도 기억에 남기되 **업무와 완전히 분리**한다. 캐릭터마다 기억이 둘: 업무 기억(업무 대화에서만 읽고 씀)과 사적 기억(`characters/<id>/private-memory.md`, 사적 모드에서만 읽고 씀). 사적 기억은 `/private` 진입 때 호스트가 사적 규칙과 함께 넣고, `/work`로 나올 때 그 구간을 한 번짜리 호출로 최대 3줄 정리해 덧붙인다. 사적 모드 동안 업무 기억 쓰기는 도구 쪽에서 거부한다.
   - **세션 이원화 (2026-09-23, SESSION_SPLIT_v1 · #99–#101):** 한 CLI 대화에 업무·사적이 섞이지 않도록 **세션 자체를 캐릭터 × 모드로 나눴다.** `/private on`(또는 입력창 하트)은 그 캐릭터의 사적 세션을 열고, `/private off`는 업무 세션으로 돌아가며 그동안의 사적 대화를 사적 기억에 정리한다(맨 `/private`는 토글, `/work`는 옛 별칭). 사적 세션의 지침 묶음은 헌장 + 카드 + 사적 규칙 + 사적 기억뿐(스킬·업무 기억·상태 없음). 사적 세션이 응답하는 동안 MCP 업무 도구는 닫힌다(`/api/sessions/busy`). 사적 기억 파일은 git에 넣지 않는다(`.gitignore`).
2. **채팅에서 캐릭터를 골라 대화** — 프로바이더 선택 옆에 캐릭터 선택, 세션은 캐릭터별. 업무 요청은 여전히 PD를 거치지만 루루와 직접 일 얘기도 사적인 얘기도 할 수 있다.
3. **공통 집 규칙 + 캐릭터별 지침** — 헌장(안전·티켓·자기수정)은 모두가 따르고, 캐릭터마다 업무·사적 지침을 얹는다.
4. **캐릭터 카드 V2 형식 채택** — 정체성·사적인 면은 표준 V2 카드(`name`, `description`, `personality`, `scenario`, `first_mes`, `mes_example`, `system_prompt`, `character_book` …), 업무 면(지침·스킬·MCP·두뇌)은 `extensions`에. SillyTavern류와 가져오기·내보내기. 참고: `~/wiki/concepts/ai-character/character-card-format.md`.

### 12.1 캐릭터가 가지는 것

| | 업무 | 사적 |
|---|---|---|
| 정체성 (이름·외형·말투) | 공통 (카드) | 공통 (카드) |
| 지침 | `extensions` 업무 지침 | 카드 `system_prompt` 등 사적 지침 |
| 스킬·MCP | `extensions` | (필요하면) |
| 두뇌 | `extensions` 두뇌 순서 | (같거나 따로) |
| 기억 | 하나 (카드 밖 `memory.md`: 카드는 공유 가능, 기억은 사적 데이터) | 〃 |

### 12.2 탭 역할
- **상태** = 시스템: 프로바이더·계정·사용량·프로세스, 공용 도구 목록(스킬·MCP·훅).
- **팀** = 캐릭터: 카드 하나가 그 캐릭터가 보고 가진 전부(정체성, 업무·사적 지침, 스킬·MCP, 두뇌, 기억). 편집 가능·읽기 전용 구분 유지.
- **개선** = 관찰·티켓. **대화** = 대화 + 진행 중인 작업 카드.

### 12.3 구현 순서
1. ✅ 캐릭터 폴더(`data/workspace/characters/<id>/card.json` + `memory.md`)와 카드 V2 읽기·쓰기, 냥피디(PERSONA·PRIVATE·MEMORY·pd-brain)와 루루(experts/staff) 이전 — 화면 변화 없이 (#94)
2. ✅ 지침 묶음을 캐릭터별로 조립 (공통 헌장 + 카드 + 기억) (#97; 업무 기억 MEMORY.md의 캐릭터 폴더 이전은 남음)
3. ✅ 팀 탭 = 캐릭터 카드·기억·외형 락 보기, `[역할]`·`[두뇌]` 편집 (#90, #105; 카드 본문 편집기는 남음)
4. ✅ 채팅 캐릭터 선택 + 캐릭터별 세션 — 세션 구조(캐릭터 × 모드, #99), 아바타 = 캐릭터 선택·프로바이더 이름 = 두뇌 선택, 캐릭터마다 마지막 두뇌 기억 (#102)
5. 카드 가져오기·내보내기

### 12.4 캐릭터 이미지 형식 (2026-09-24, CHARACTER_ART_v1 · #103)
이미지 에이전트가 규칙대로 만들 수 있게 형식을 고정했다. 정본은 스킬 `character-art`, 검사는 `tools/check_character_art.py`(코드 `characters.check_art`).
- `characters/<id>/avatar.webp` 512 뱃지(필수), `avatar/<provider>.webp` 두뇌별 가발(선택, 없으면 기본 룩), `visual.md` 외형 락(필수).
- `sprites/<framing>/<label>.webp` 선 그림(선택): `bust` 1024×1024(숄더샷), `full` 1024×2048(전신). 투명 배경, 프레이밍마다 캔버스·기준선·배율 고정(표정을 바꿔도 몸이 안 움직이게), `neutral` 먼저. 표정 이름은 SillyTavern 표정 스프라이트 이름표.
- `stage.webp` / `stage/<provider>.webp` 1024×1024 채팅 배경(선택, 없으면 공용 스튜디오 배경). 선택기·프로바이더 트레이·배경 모두 열린 캐릭터 기준 (#109).
- 먼 구상: **데스크톱 모드** — 같은 서버에 붙는 설치형 앱, 캐릭터만 띄우고 대화는 말풍선(사용자, 2026-09-24: "상당히 멀고 흐릿한 목표"). 스프라이트 형식은 그 자리만 남겨 둔 것. 가발별 스프라이트는 아직 형식 밖.
- 냥냥(옛 냥피디, #110)의 외형 락은 `data/persona/README.md`에서 캐릭터 폴더 `visual.md`로 옮겼고, Hub용 원본 이미지는 아직 `data/persona/`에 있다.

### 12.5 역할 팩과 팀 편성 (2026-09-24, TEAM_ROLES_v1/v2 · #104–#105)
사용자 결정: **모든 캐릭터는 동등하다. PD는 캐릭터가 아니라 PD 지침과 PD 스킬셋으로 정해진다.**
- 카드에는 역할이 없다. 역할 = `data/workspace/roles/<role>/role.md`(앞머리 `title`·`tools`·`skills`, 본문은 매 턴) + 선택 `procedure.md`(필요할 때 읽음). 지금 `pd`(tools: `delegate`, `house-memory`)와 `staff`(도구 없음).
- **엔진은 역할 이름을 모른다**(2026-09-30 운영자: "사용자 데이터고 엔진 코드는 이런 걸 몰라야 해", engine/A #460). 엔진이 아는 자리는 하나, **기본 캐릭터**(`team.json`의 `default`, 없으면 가장 오래된 카드) — 매 턴 읽히는 카드, 위임을 받는 쪽이 아니라 하는 쪽, 작업을 확인하는 쪽. 위임 가능한 역할 = 기본 캐릭터가 아닌 캐릭터들이 가진 역할(`characters.expert_roles`). 새 설치의 기본 캐릭터는 역할 없이 시작. 가드: `test_team_roles.test_engine_code_names_no_role`.
- 편성 = `data/workspace/team.json` `{"default": id, "members": {id: [roles]}}`. 팀 탭 `[역할]`로 바꾼다. PD = pd를 가진 캐릭터, 기본 캐릭터 = `default`.
- 도구 권한은 역할 팩이 준다: MCP 서버가 응답 중인 세션의 캐릭터 도구(`/api/sessions/busy`의 `tools`)로 `delegate`·집 기억 쓰기를 열고 닫는다.
- 기억: `memory/MEMORY.md` = 집 공용 기억(모두 읽고 `house-memory` 권한만 씀), 캐릭터마다 자기 `memory.md`, 사적 기억은 §12 1번대로.
- `roles/`·`team.json`은 Tier 3(governance). 스킬 중 역할 팩이 요구하는 것은 그 역할을 가진 캐릭터에게만 보인다.

## 13. 파이프라인 정비 (2026-09-26 회고, 계획)
상태: **계획** (착수는 사용자 승인 후). 항목마다 티켓 하나.

### 13.1 회고 (2026-09-26에 깨진 것)
1. `[실행]` → `POST /api/delegations/213/go` HTTP 400 (로그 rid `cd515c6a7990`). 원인: 티켓 없이 디스크에 쓴 계획 문서 4개 때문에 `tickets.claim`이 `uncommitted leftover`로 거절(`tickets.py::claim`). 사유는 티켓 노트에만 있고 카드엔 맨 오류만 떴다.
2. 파일을 지우거나 이름 바꾸는 문서 작업이 실행 중에야 다른 파일의 링크도 고쳐야 함을 발견 → `NEED_PATH` 일시정지 → 재개 시 리뷰 diff에서 정지 전 커밋이 빠져 PD가 두 번 FAIL (#214, `3cd53af`에서 수정).
3. `gate_failed` 정리가 워크트리·브랜치를 지워 멀쩡한 작업 커밋 `90d85a9`가 dangling으로 남음(`git gc`면 소실). `tools/worktree_runner.py` 모듈 설명 "탈락 -> ... 정리".
4. `gate_failed` 뒤 같은 티켓으로 계획 수정 불가: `delegation.py` 당시 거절 문구 `not a plan waiting for [실행]`(시도 1/3인데도). #213을 새 티켓 #215로 대체해야 했다.
5. `paths`에 넣은 읽기 전용 참고 파일이 문서 전용 계획을 Tier 2로 올림 — tier는 `paths` 전체로 계산(`delegation.py::plan`의 `tier_of(paths)`).

### 13.2 제안
| id | 변경 | 막는 문제 | 대상 파일 | tier |
|---|---|---|---|---|
| A | `delegate plan` 시점 사전 점검: untracked/dirty/없는 `paths`는 거절 또는 경고; 삭제·이름변경 대상은 참조처를 grep해 `paths` 추가 제안 | 1, 2 | `delegation.py` | 2 |
| B | 카드에 API 오류의 거절 사유를 한국어 한 줄로 표시 | 1 | `static/app-evolution.js` | 0 |
| C | `gate_failed`/`failed` 시 브랜치 헤드를 `refs/attic/ticket-N`에 보존; 같은 티켓 재실행은 거기서 시작 가능 | 3 | `tools/worktree_runner.py` | 3 (승인 티켓 아래 PD가 직접) |
| D | `gate_failed` 티켓 재계획 허용 (같은 id, 시도 횟수 규칙 그대로) | 4 | `delegation.py` | 2 |
| E | 작업 스키마를 `paths`(변경)·`reads`(참고만)로 분리; tier와 범위 검사는 `paths`만 | 5 | `delegation.py`, `tools/worktree_runner.py` | 3 |

### 13.3 순서
1. A+B 먼저 — 싸고, 오늘의 오류를 막는다.
2. C+D 함께 — 실패를 이어서 재개 가능하게.
3. E 마지막 — 스키마 변경.

## 14. 운영 1주 평가 (2026-09-29, 운영자 요청)
상태: **진행**. 항목마다 티켓 하나.

### 14.1 숫자 (2026-09-23 → 09-29, `~/.worktrees/chatbot/runs/ticket-*.json`, `git log`)
| 항목 | 값 |
|---|---|
| 위임 실행 | 84건: 완료 66(79%), 운영자 폐기 12(절반은 실측용 탐침), 실패·탈락 4, 경로 대기 1 |
| 걸린 시간 | 완료 건 중앙값 2.1분, p90 11.6분 |
| 크기 | 과제 1개짜리 71건, 1라운드 완료 71건 |
| 검토 | 검토자 판정 약 89회 중 반려 약 1회. 작성·검토가 같은 제공자(Opus→Opus, Gemini Flash→Gemini Flash)인 경우가 대부분. 현재 PD 두뇌 `agy/gemini-3.8-flash-low`, 스태프 `agy/gemini-3.8-flash-high` — 더 약한 같은 계열 모델이 검토 |
| 기여 | 추가 줄 수: 위임(agy) 약 8.7천, Claude Code 직접 약 4.7만 |
| 장치 비용 | `delegation.py`·`tools/worktree_runner.py` 등 약 3.3천 줄, 이 두 파일을 바꾼 커밋 1주 38개 |
| Tier | 0: 31건, 2: 49건 — 절반 이상이 반영 전 운영자 승인 필요 |

### 14.2 판단
- **잘 되는 것**: 안전장치(워크트리 격리·범위 게이트·Tier·일시정지 시 작업 보존). #379에서 워커의 보안 파일 수정 요청을 막았다. 과제 1개짜리 작은 수정은 빠르고 싸다.
- **검토가 도장 찍기다.** 반려 비율과 같은 제공자 검토라는 구조에서 나온 추정이다(반영 후 재수정 비율은 아직 측정 안 함).
- **장치 비용이 산출에 비해 크다.** 개발판 전용이라 배포판에 들어가지 않는데, 제품 작업(메신저 갭 17칸, [ux-shell-roadmap.md](ux-shell-roadmap.md) §4.2.1a)과 시간을 두고 경쟁한다.
- **병목은 운영자의 버튼이다.** [실행]과 Tier 2 반영 승인.
- **환경 고장이 워커에게 떠넘겨진다.** #379: 워크트리 위치 때문에 원래부터 실패하던 테스트를 워커가 자기 일로 여기고 Tier 3 파일을 요청(테스트는 #380, 버튼은 #381에서 수정).

### 14.3 방침
1. **장치 기능 추가 동결.** 아래 신뢰성 항목과 고장 수리만 한다.
2. **쓰임새**: 위임은 과제 1개짜리 작은 수정. 설계가 필요한 작업은 직접.
3. **지표**: 반영 후 7일 안에 같은 파일을 다시 고친 비율(위임 반영분 대상). 교차 검토의 효과를 이 숫자로 본다.

### 14.4 항목
| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `dlg/A` | 이 절 | 이 문서 | 커밋 | 0 · — | S | — | ✅ |
| `dlg/B` | **교차 검토**(REVIEW_CROSS_v1): 검토는 작성한 제공자와 다른 제공자가 한다. 순서 = PD 두뇌 중 다른 제공자 → (없으면) 설치된 다른 제공자의 기본 검토 모델 → PD의 같은 제공자 두뇌(최후 수단, 기록에 표시) | `tools/worktree_runner.py`, 테스트 | 같은 제공자 두뇌만 가진 PD도 다른 제공자가 검토, 다른 제공자가 모두 못 쓸 때만 같은 제공자로, 전사 기록에 `same_provider` 표시 | 3 · — | S | — | ✅ #383 |
| `dlg/C` | **기반 확인**: 게이트 실패 시 같은 테스트를 작업 전 코드(base)에서 다시 돌려, 거기서도 실패하면 `base_broken`으로 멈추고 워커에게 고치게 하지 않는다 | `tools/worktree_runner.py`, 테스트 | base에서도 실패하는 게이트는 워커 라운드를 쓰지 않고 운영자에게 보고 | 3 · — | M | — | ✅ #384 (BASE_CHECK_v1: 실패한 게이트 하나를 base의 임시 사본에서 재실행, 단계 `base_broken`·작업 보존·시도 반환(티켓엔 `unavailable`, 최대 3회), 카드 [실행]이면 main 위로 올려 확인부터 이어감. 한계: 여러 과제 중 2번째 이후에서 멈춘 경우는 main 위로 올리지 않음) |
| `dlg/E` | **콘텐츠 위임**(CONTENT_WORK_v1, 운영자 2026-09-29 "가드·테스트·커밋이 필요한 위임과 아닌 위임으로 구분"): 계획의 경로가 모두 사용자 데이터(`host_config.DATA` 아래)면 격리 공간·커밋·게이트·검토·반영 없이 제자리에 쓴다. 덮어쓸 파일은 `_old/`에 보관, 범위 밖 변경은 실패로 보고. 티켓은 가볍게: 잠금은 유지(동시 쓰기 방지), 닫을 때 가드·미커밋 검사 없음. 계기: #371(그림 한 장)이 코드 공정을 다 거치고 닫기가 네 번 실패 | `tickets.py`(`is_content`), `tools/worktree_runner.py`(`--content`), `delegation.py` | 사용자 데이터만 건드리는 계획은 `--content`로 실행, 커밋·검토 없이 done | 3 · ⚡ | M | — | ✅ #392 |
| `dlg/F` | **병합 재시도**(LAND_RETRY_v1): 반영 직전 게이트가 도는 사이 main이 또 움직이면(다른 에이전트의 커밋) fast-forward 거절로 실패하던 것을, 다시 올리고 다시 검사해 최대 3번 시도. 계기: #406(PWA)이 15:36:00 main 커밋과 겹쳐 실패 | `tools/worktree_runner.py`(`land()` — 바로 병합·승인 뒤 병합 두 경로 공통) | main이 게이트 중 움직여도 병합, 테스트가 재시도 경로를 지남 | 3 · — | S | — | ✅ #408 |
| `dlg/D` | 지표 스크립트: 위임 반영분의 7일 내 재수정 비율 | `tools/`(새 파일) | 주 1회 실행으로 숫자 하나 | 0 · — | S | — | 대기 |

## 15. 문서 차선 (DOC_LANE_v1, 운영자 2026-09-30)

단순 문서 작업이 코드와 같은 검토 규칙(최대 2회, 불합격이면 실패)을 타서 느리고 잘 멈췄다(#443 검토 한도, #452 검토자 오류). 바꾸는 파일이 모두 Tier 0 `.md`이고 운영자 승인 대기(`--stop-before-merge`)가 있는 작업은:
- 검토 **1회**, **문서 점검표**로만: ① 시키지 않은 삭제·재작성 ② 링크·앵커·절 번호 ③ CONCEPT·다른 결정과의 충돌 ④ 계획을 「구현됨」으로 쓰기. 문체는 불합격 사유가 아니다.
- 판정은 **참고용**: 불합격이어도 시도가 실패하지 않고 승인 대기로 간다. 의견은 카드(`doc_advice`, 검토자 기록의 `advisory`)에 보이고 운영자가 판단한다.
- **삭제 경고**: 지운 줄이 20줄을 넘으면 검토 지침과 기록에 경고(`deleted`). 모델 없이 계산한다.
- 게이트(테스트·범위 검사)는 그대로다. 게이트 실패는 지금처럼 작성자에게 돌려보낸다.
- 구현: `tools/worktree_runner.py` `is_doc_task`, `doc_review_prompt`, `deleted_lines`; PD 절차(`roles/pd/PROCEDURE.md`). 테스트: `tests/test_worktree_runner.py` `test_a_doc_task_waits_for_the_operator_with_the_review_as_advice` 외 2개.
