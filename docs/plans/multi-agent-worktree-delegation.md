# 멀티 에이전트 Git Worktree 격리 외주 계획서 (Multi-Agent Worktree Delegation)

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
