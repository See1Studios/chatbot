# 계층형 컨텍스트 및 지침·메모리·스킬 동적 재할당 아키텍처

> 방향 (align/D): **핵심 + 기반** — 개인화 하네스의 지침·메모리·스킬을 4×3 매트릭스로 일반화하고, 상황(모드·캐릭터·장소)에 따라 안전하게 동적 재할당(Dynamic Re-assignment)하는 프롬프트 및 실행 하네스 기반.

상태: `active`
목적: 지침(Static) · 메모리(Dynamic) · 스킬(On-Demand) 3대 요소를 4대 층위(공통·캐릭터·사적·업무)로 직교 일반화하고, 런타임 상황(업무/사적 모드, 캐릭터 핸드오프, 장소/맥락)에 따라 슬롯처럼 안전하고 결합도 낮게 재할당되는 하네스를 구축한다.
관련 문서: [`direction-alignment.md`](direction-alignment.md), [`personalization-ladder.md`](personalization-ladder.md), [`private-mode.md`](private-mode.md), [`instruction-architecture.md`](archive/2026/instruction-architecture.md)

---

## 1. 범위 및 비목표

### 범위 (Scope)
1. **4×3 직교 매트릭스 규격화**:
   - 4개 층위: L0 최상위 공통, L1 캐릭터 정체성, L2 직무/업무, L3 상황/사적 관계
   - 3대 요소: 지침(Static / Always-on 규범), 메모리(Dynamic / 누적 상태), 스킬(On-Demand / 필요 시 절차 로드)
2. **상황별 동적 재할당(Dynamic Re-assignment) 엔진 설계**:
   - 모드 전환 (`work` ↔ `private`), 캐릭터 전환 (`코코` ↔ `노노` ↔ `리리`), 장소/맥락 키워드 매칭 시 주입 레이어 교체 메커니즘.
   - `instructions.py::build_instruction_bundle`의 모드 분기 구조 정돈.
3. **Anti-Slop 다계층 통합**:
   - 텍스트/표현 품질: L0 공통 헌장(기본 3대 원칙) + L2/L3 스킬(`avoid-ai-writing`) 연계.
   - 코드 품질: L2 업무/개발 계층에 Oxlint Anti-Slop 가드 편입.
   - 캐릭터 보이스 보호: L1 캐릭터 고유 말투와 사적 교감은 보호하고 업무 팩트 설명에서만 슬롭 제거.

### 비목표 (Non-goals)
- 특정 LLM 프로바이더 전용 하드코딩 (모든 프로바이더 중립성 유지).
- 캐릭터의 만담 및 감정적 표현 일괄 거세 (업무 설명과 캐릭터성 분리).
- 공개 네트워크 Funnel 확장 (호스트 보안 원칙 준수).

---

## 2. 현황 점검 (Current Facts, 2026-10-06)

| # | 사실 | 근거 / 측정 |
|---|---|---|
| F1 | `instructions.py`가 `_rules_text`, `_skills_text`, `_memory_text`, `_private_bundle`로 나뉘어 있으나 모드별 분기가 하드코딩되어 새 층위 확장이 어려움 | `instructions.py::build_instruction_bundle` |
| F2 | `instructions.py`에서 해시(`hash`)는 오직 Static 레이어(`rules` + `skills`)에만 적용되어 Dynamic 레이어(메모리·상태) 변동 시에도 프롬프트 캐시가 보존됨 | `instructions.py::build_instruction_bundle` |
| F3 | 스킬 색인(`_skills_text`)은 워크스페이스의 `.agents/skills/`를 스캔하고 역할 팩(`role_pack["skills"]`)으로 소유권을 필터링하고 있음 | `instructions.py::_skills_text` |
| F4 | 워크스페이스 스킬 디렉터리(`~/.pe/workspace/.agents/skills/`)에는 `fact-check`, `plan-doc` 등 13개 스킬이 등록되어 있으나, 텍스트 품질 검수 스킬(`avoid-ai-writing`)은 미배치 상태 | `ls ~/.pe/workspace/.agents/skills/` |
| F5 | 홈 루트(`~`)에 Oxlint Anti-Slop 플러그인이 벤더링되어 있으나, `services/chatbot/static/` 40여 개 파일에 린트 진단이 잔존하며 `run-tests.sh` 가드에는 미편입 | `npx oxlint services/chatbot/static/` |

---

## 3. 결정 (Decisions)

| D | 질문 | 추천 | 상태 |
|---|---|---|---|
| D1 | 지침·메모리·스킬을 4×3 매트릭스 구조로 일반화할 것인가? | **예**. 공통/캐릭터/사적/업무의 대칭성을 확립해 결합도 해소 | 결정 대기 |
| D2 | 텍스트 Anti-Slop을 '헌장 상시 규칙 + 온디맨드 스킬' 투-트랙으로 연동할 것인가? | **예**. 토큰 낭비 방지 및 21개 세부 패턴/대체표 활용 양립 | 결정 대기 |
| D3 | 사적 모드(`private`) 진입 시 업무 스킬 및 업무 지침을 완전히 격리(언로드)할 것인가? | **예**. 사적 공간에서의 업무 오염 및 보안 누출 방지 | 결정 대기 |
| D4 | Oxlint Anti-Slop을 `run-tests.sh` 가드에 편입하는 시점은? | **점진적 파일 정리 후 단계별 편입** (빌드 브레이크 방지) | 결정 대기 |

---

## 4. 아키텍처 상세: 4×3 직교 매트릭스

```text
[Context State] ──▶ (Mode, Character, Roles, Scene)
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  ① 지침      │   │  ② 메모리    │   │  ③ 스킬      │
│  (Static)    │   │  (Dynamic)   │   │  (On-Demand) │
├──────────────┤   ├──────────────┤   ├──────────────┤
│ L0. 공통헌장 │   │ L0. 장기기억 │   │ L0. 공용도구 │
│ L1. 캐릭터   │   │ L1. 개인기억 │   │ L1. 고유특기 │
│ L2. 직무역할 │   │ L2. 실무상태 │   │ L2. 직무스킬 │
│ L3. 사적규칙 │   │ L3. 관계기억 │   │ L3. 감정지문 │
└──────────────┘   └──────────────┘   └──────────────┘
```

1. **상황별 재할당(Re-assignment) 규칙**:
   - `Mode == work`: L0(공통) + L1(캐릭터) + L2(직무역할) 활성화, L3(사적관계) 비활성화.
   - `Mode == private`: L0(축약헌장) + L1(캐릭터) + L3(사적관계) 활성화, L2(직무역할/스킬/티켓) 완전 격리 언로드.
   - `Character Handoff`: L1(카드/보이스) 교체 및 해당 캐릭터가 보유한 직무에 맞춰 L2(역할팩/스킬셋) 동적 재바인딩.

2. **Anti-Slop의 층위별 배치**:
   - **L0 (공통 지침)**: 상시 3대 원칙 (영혼 없는 아첨 금지, 버즈워드 금지, 결론 우선 두괄식 서술).
   - **L2 (업무 스킬)**: 산출물 작성 시 스킬 `avoid-ai-writing` 정밀 검수. 코드 커밋 시 Oxlint Anti-Slop 가드.
   - **L1/L3 (캐릭터/사적)**: 캐릭터 고유 감정선과 만담은 보존.

---

## 5. 작업 항목 (Work Items)

| id | 작업 | paths(변경) | 수용 기준 | tier·⚡ | 크기 | 의존 | 티켓 |
|---|---|---|---|---|---|---|---|
| `lca/A` | 계획 문서 등록 및 INDEX 반영 | `docs/plans/layered-context-architecture.md`, `docs/plans/INDEX.md` | `test_plans_index.py` 통과 | 0 · — | S | — | #698 |
| `lca/B` | 텍스트 Anti-Slop 스킬팩 등록 | `.pe/workspace/.agents/skills/avoid-ai-writing/` | 워크스페이스 스킬 색인에 노출 확인 | 1 · — | S | D2 | 대기 |
| `lca/C` | L0 공용 헌장 Anti-Slop 상시 앵커 추가 | `.pe/workspace/AGENTS.md`, `templates/dev-workspace/AGENTS.md` | 헌장 ## Work에 상시 3대 원칙 및 스킬 포인터 기재 | 3 · — | S | lca/B | 대기 |
| `lca/D` | `instructions.py` 4×3 계층 구조 및 재할당 로직 정돈 | `instructions.py`, `tests/test_instructions.py` | 매트릭스 계층화 및 캐시 해시 일관성 검증 통과 | 3 · ⚡ | M | D1, D3 | 대기 |
| `lca/E` | 프론트엔드 정적 파일 Oxlint Anti-Slop 점진 해소 | `static/app-shell-brain.js`, `static/theme.js` 등 | 타깃 파일별 린트 0건 통과 | 2 · — | S | D4 | 대기 |

---

## 6. 의존·순서·리스크

### 순서
1. **lca/A** (계획 등록) → **lca/B** (스킬 등록) → **lca/C** (헌장 앵커 반영): 문서와 프롬프트 거버넌스 우선 확립.
2. **lca/D** (`instructions.py` 리팩토링): 엔진의 4×3 계층 재할당 로직을 깔끔하게 구조화하고 테스트 가드 확인 후 소생.
3. **lca/E** (코드 Anti-Slop): 경량 정적 모듈부터 시작해 린트 점진 해소.

### 리스크
- **프롬프트 캐시 무효화 리스크**: Static 레이어 텍스트가 바뀔 때마다 해시가 변경되므로, 변경 작업은 턴 간 잦은 수정 대신 일괄 확정 후 1회 반영.
- **모드 오염 리스크**: 사적 모드에서 업무 지침이나 도구가 노출되지 않도록 `test_private_bundle` 및 관련 경계 테스트 강화 필수.
