<!-- AUTO-GENERATED MIRROR FROM RULES.md (source_sha256: c607196c42f86bca12f8b69ef93fda35fe9c82a28c7b176978788b7dc0562d9c) — DO NOT EDIT MANUALLY -->

# 규칙

이 저장소를 변경하는 에이전트에 대한 모든 규칙입니다. 코드 이름은 `engine/`를 기준으로 합니다. 항목은 루트 `AGENTS.md`입니다. 하지 말아야 할 규칙을 나열합니다.
나머지 부분은 여기에서 중단하고 포인트를 지정하세요. 먼저 규칙(숫자 및 방법), 그 다음 레지스트리: 각 규칙은
깨지면 실패하는 테스트나 게이트.

## 규칙

### 테스트 페어링

코드를 변경하는 `feat`, `fix`, `refactor` 또는 `perf` 커밋은 `tests/` 아래에서 변경 사항을 보여주는 테스트를 수행합니다.
어떤 테스트에서도 이를 표시할 수 없는 경우(CSS 간격, 기존 테스트의 이름 변경) 커밋은 예고편에 이유를 표시합니다.
라인 `No-Test: <why>`; 그 이유는 검토를 위해 기록에 남습니다. 코드와 테스트 파일은 한 번 정의됩니다.
`tools/review_checklist.py::is_code_file` 및 `is_test_file`; 위임 검토에서는 동일한 확인으로 경고합니다.

### 크기 한도

- Python 모듈: `MAX_BYTES=80_000`. Python 함수: `FUNC_MAX_LINES=80`.
- 페이지 스크립트 또는 스타일시트: 43,000바이트(`tests/test_page_scripts.py`).
- 이미 한도를 초과한 코드는 테스트 천장 테이블에 고정되어 늘어나지 않을 수 있습니다. 몸이 줄어들면 천장을 낮추세요
  그, 절대로 올리지 마세요. 테이블은 백로그이며 두 번째 목록은 없습니다.
- 이유: 에이전트는 전체 모듈을 읽고 전체 기능을 한 번에 변경합니다. 바이트는 토큰을 추적합니다.

### 시간 초과

모든 차단 `subprocess` 호출(`run`, `check_output`, `check_call`, `call`)은 명시적인 `timeout` 이름을 지정합니다. 없다
단일 번호: 호출에 필요한 것을 선택합니다(`ps`는 30초, 테스트 실행 시간(분)을 얻습니다). 긴 모델 회전을 지켜보는 사람
`turn_watchdog.py`, 통화 시간 초과가 아닙니다.

### 일 농담

위임, 핸드오프, 커밋 및 보고 텍스트에서 농담은 최대 한두 문장입니다. 나머지는 사실, 차이점, 테스트입니다.
결과, 원인. 의도적으로 집행자가 없음: 농담을 판단하는 것은 단어나 문장을 일치시키는 것을 의미하며 엔진은 이를 수행합니다.
하지 마십시오.

### 명명

- 현재 문서(1부, 항상 최신)는 대문자: `AGENTS.md`, `RULES.md`, `VISION.md`,
  `SKILL.md`, `ROLE.md`, `PROCEDURE.md`, ...
- 쌓이는 문서는 하케밥 : `docs/plans/*.md`(`INDEX.md` 제외), `docs/history/YYYY-MM-DD.md`입니다.
- snake_case 문서 이름이 없습니다.
- 문서 이름 바꾸기: 동일한 변경 사항의 모든 라이브 링크를 업데이트합니다. 탈퇴 이력(HISTORY, `docs/history/`, 아카이브,
  티켓 레코드)에 작성된 대로입니다.

### 하네스

- 기본 제공자 `agy`. 레지스트리 `providers/adapters.py::AGENT_ADAPTERS`; 세션은 제공자를 다음에서 복원합니다.
  `meta.json`. 공급자 또는 하네스별 규칙은 어댑터나 `chatbot-ctl.sh`에 있으며 다른 곳에서는 없습니다.
- 생성된 에이전트는 `services/chatbot` 및 ​​`<web root>/chat`(`host_config.py::ADD_DIRS`)만 참조하세요. 집을 추가하지 마세요.
  dir, `.hermes`, 전체 웹 루트 또는 `services`. 최소한으로 확대하고 HISTORY.md에서 그 이유를 말해보세요.

### 역할 팩 및 기본 기준

- 기본 베이스라인은 엔진 소유입니다(`characters.BASE_TOOLS`, `instructions.BASE_SKILLS`). 모든 캐릭터는 무조건 기본 도구(`choices`, `dialog`, `memory`, `web`)와 기본 스킬(`handoff-brief`)을 보유합니다. 원예 제로.
- 역할은 `workspace/roles/<role>/`의 사용자 데이터입니다. 기본 기준에 더해 전문화된 전문 도구와 기술을 부여합니다.
- 역할이 할당되지 않은 캐릭터는 기본 베이스로 안전하게 작동합니다.

### 문서 언어와 인간 거울

- 루트 스탠딩 문서(`*.md`)는 일반 영어로 된 에이전트 SSOT입니다.
- 한국어 미러 문서(`*.ko.md`)가 인간 운영자 옆에 있습니다.
- 자동 번역 파이프라인: `*.ko.md` 파일은 `tools/sync_mirrors.py`(sha256 캐시 번역 파이프라인)를 통해 동기화된 기계 제작 아티팩트입니다. 에이전트와 인간은 `*.ko.md`를 수동으로 편집해서는 안 됩니다.
- 사전 커밋 후크는 준비된 대상의 미러(대상: `tools/sync_mirrors.py::DEFAULT_MIRROR_TARGETS`, 용어: `GLOSSARY`)를 동기화합니다. 오프라인에서는 경고만 하고 `test_sync_mirrors`는 오래된 미러 이름을 지정합니다.
- 생성된 헤더: 모든 `*.ko.md`는 `<!-- AUTO-GENERATED MIRROR FROM <file>.md (source_sha256: <hash>) — DO NOT EDIT MANUALLY -->` 헤더를 전달합니다.
- 에이전트 수집 없음: 에이전트 및 프롬프트 로더는 `*.ko.md`를 에이전트 컨텍스트로 수집해서는 안 됩니다.
- 누적된 작업일지(`HISTORY.md`) 및 프로젝트 계획서에는 필요에 따라 한국어 항목 또는 번역이 포함될 수 있습니다.

### 출시

이 저장소는 비공개입니다. 릴리스를 검토된 소스 스냅샷으로 취급합니다. 개인 데이터, 자격 증명 또는 런타임 상태를 포함하지 마십시오.

나중에 릴리스를 잘라냅니다.

1. 엔진/VERSION에서 원하는 릴리스 버전을 설정합니다(예: 1.0.0).
2. 버전의 사용자가 볼 수 있는 변경 사항을 HISTORY.md(또는 릴리스 노트, HISTORY.md는
   진행중인 작업 일기).
3. 테스트 진입점(engine/run-tests.sh)을 실행합니다. 그런 다음engine/chatbot-ctl.sh 복구를 실행하고 연기 검사가 통과되었는지 확인합니다.
4. 전체 차이점 및 추적 파일 목록을 검토합니다. data/, secrets.env, 세션 파일, 토큰, 키 또는 기타 개인 런타임 출력을 준비하지 마십시오. 릴리스 파일에는 비밀이 포함되어서는 안 됩니다.
5. 검토된 릴리스 변경 사항을 커밋합니다.
6. VERSION과 일치하는 주석이 달린 로컬 태그를 생성합니다: git tag -a vVERSION -m Release-vVERSION. git show vVERSION으로 확인하세요. 태그 게시는 명시적으로 승인된 별도의 단계입니다.

현재 개발 스냅샷은 0.0.0-dev입니다. 이 절차에서는 태그를 게시하지 않습니다.

## 전파 원장

요청 시 읽기, 주입되지 않음. 코드를 통해 확산되는 동안 새로운 규칙을 추적하고 가드가 없는 코드 드리프트
이미 추적 중입니다. 계획: [전파 및 상태 아키텍처.md](docs/plans/archive/2026/propagation-and-state-architecture.md).

- 아이템 진행 상황은 티켓에 있습니다. 규칙의 홈은 이 파일입니다.
  이 파일에는 각 부품을 운반하는 티켓과 함께 비행 중인 항목만 나열되어 있습니다.
- 드리프트 가드 이미 핀은 여기에 복사되지 않습니다. 특대 기능은 `tests/test_file_sizes.py::FUNC_CEILINGS`,
  시간 초과가 없는 호출은 `tests/test_conventions.py::LEGACY_SUBPROCESS_EXEMPTIONS`이고 래칫은
  `ratchet_baseline.json`. 그 테이블은 줄어들기만 합니다.
- Who-fields는 역할 ID(`dev`, `lead`, `claude-code`)를 보유하며 캐릭터 이름은 보유하지 않습니다.

### 활성

없음.

입구 모양:

```markdown
### [DEV-PROP-nnn] <rule being spread>
- Source: <RULES.md section or registry row>; enforcer: <test>
- Parts: `<path>` -- #<ticket> (open | done <hash>)
```

### 가드 트랙이 없는 드리프트

없음.

입구 모양: `- [DRIFT-nnn] <path>::<symbol> -- <rule> -- found <date> by <role id> -- plan: <ticket or item>`

### 완료

- [DEV-PROP-001] 거버넌스 문서 및 컨벤션 검사기: #720, #724, #726 (`5de6799`, `c5f89c9`), 2026-10-06.
- [DEV-PROP-002] 거버넌스 검토 2026-10-07(prop/E–H): 그린 메인, 보호된 집행자, 테스트 페어링 후크, 개발 및
  배송 지침이 분할되어 문서가 잘려졌습니다: #766–#769.

## 규칙

- 레지스트리의 대상자: **모두** = 엔진 작업을 수행하는 PE 채팅 에이전트를 포함하여 이 저장소를 변경하는 모든 에이전트.
- 집행자(Enforcer): 규칙이 깨졌을 때 실패하는 테스트 또는 게이트입니다. `manual`는 아직 없음을 의미합니다. 계획된 일이 뒤따른다
  괄호. `tests/test_rule_registry.py`는 각 명명된 집행자가 존재하고 Tier 3이며 커밋 시 실행되는지 확인합니다.
- 시행자를 추가하는 동일한 변경 사항에 규칙을 추가합니다. 규칙이 없는 경우 `manual`와 그 이유를 알 수 있습니다.

| 규칙 | 관객 | 집행자 |
|---|---|---|
| 작업은 운영자의 단어 또는 승인되고 주장된 티켓에서 시작됩니다. 클레임은 경로 이름을 지정합니다 | 모두 | `test_tickets`(릴리스에서는 더티 경로를 거부함); `test_unticketed_write`(PE 세션: 눈에 띄는 티켓팅되지 않은 쓰기는 차례를 중지하고 트리에 대한 다른 변경 사항은 유지됩니다.) |
| 라이브 채팅 에이전트 및 ​​해당 하위 에이전트는 전체 제품군이 아닌 가드 또는 명명된 테스트 모듈을 실행합니다 | PE 채팅 에이전트 전용 | `test_live_agent_suite`(`CHATBOT_LIVE_AGENT`가 설정된 경우 `run-tests.sh`는 거부합니다. 스크립트 주변의 unittest/pytest도 거부됩니다.) |
| 호스트에서 한 번에 하나의 테스트 스위트: 이후의 `run-tests.sh`는 잠금(`/tmp/chatbot-tests.lock`)을 기다립니다. 잠긴 실행 내부의 실행이 계속됩니다 | 모두 | `test_live_agent_suite` (`OneSuiteAtATime`) |
| 테스트 실행은 설치 데이터를 가져오지 않습니다. `run-tests.sh` 외부에서 단위 테스트/pytest 프로세스는 저장소의 `data/` | 모두 | `test_live_agent_suite`(`host_config.test_run_outside_runner`, `tickets.py::_data_dir`) |
| 한 요청의 핸드오프 체인은 최대 2개의 홉입니다. 감독은 한 번에 하나의 공개 핸드오프를 갖습니다 | PE 채팅 에이전트 전용 | `test_dialog_handoff` |
| 위임된 작업자는 자신의 합격 조건을 변경할 수 없습니다(가드 테스트, `run-tests.sh`) | 모두 | `test_worktree_runner` |
| 배송된 빌드는 엔진 코드를 건드리지 않습니다. `run_command`/`ticket`/`delegate`는 없으며 파일 도구는 사용자 데이터에만 접근합니다. 에디션은 `host_config.EDITION`에 의해서만 결정됩니다 | 모두 | `test_edition_boundary` |
| 커밋 전에 가드 테스트 및 준비된 파일 관련 테스트를 녹색으로 유지합니다. 출시 전 전체 제품군 | 모두 | `.githooks/check_staged.py`(사전 커밋: `--fast` 및 `related_for`, 모든 커미터); 메인 이동 후 전체 제품군이 이를 확인합니다(MAIN_WATCH_v1; 빨간색은 로그 다이제스트의 `main_red` 결과입니다). `test_worktree_runner`(러너 게이트: 가드 + 관련 테스트); `test_tickets`(경비원이 실패하는 동안 거부됨) |
| 기존 커밋 주제; `docs/plans/` 변경 시 `Plan:` 예고편 | 모두 | `test_githooks`(커밋-메시지 후크) |
| `Ticket:` 예고편, 작가 이름 | 모두 | `test_githooks`(commit-msg: `Ticket: #n`가 없는 feat/fix/refactor/perf 커밋은 거부됩니다. `worktree/ticket-n` 브랜치에서는 작성됩니다.) 작성자 이름: `test_githooks`(사전 커밋: 캐릭터 이름 없음, 라이브 채팅 세션은 `PE` 앱으로 커밋) |
| 라이브 채팅 세션은 작업자 지점을 메인에 착륙시키지 않습니다(착륙은 운영자의 지점입니다) | 모두 | `test_githooks` (`.githooks/reference-transaction`) |
| 병합된 대표단이 `HISTORY.md` | 모두 | `test_history_entry` (러너는 티켓 레코드, `tools/history_entry.py`로 씁니다) |
| 티켓은 작업을 수행하는 에이전트의 이름을 `--actor`로 지정하고 `unknown-cli`로 지정하지 않습니다. who-fields는 페르소나 이름이 아닌 역할 ID를 보유합니다 | 모두 | `test_ticket_quick`(`--actor`나 상위 프로세스 모두 에이전트를 지정하지 않으면 ticket-quick은 아무 것도 기록하지 않습니다) `test_tickets`(`tickets.py`는 쓰기 시 역할 ID가 아닌 행위자를 거부합니다). 로마자로 표기된 별명(`nono`)은 역할 ID 형태를 전달합니다. manual |
| 커밋에 비밀, `.env`, 개인 메모리 또는 스타일 참조가 없습니다 | 모두 | `test_githooks`(사전 커밋 후크) |
| 절대 `--no-verify`; 후크가 설치되고(`core.hooksPath=.githooks`) 실행 가능 | 모두 | 수동(run-tests.sh 경고); 백스톱 `test_worktree_runner`, `test_tickets` |
| `host_config`를 통해서만 데이터 경로(`DATA_ENV` 순서, `tickets.py`가 이를 미러링함) | 모두 | `test_data_paths` |
| Python 모듈 ≤ 80,000바이트; Python 함수 ≤ 80줄; 나열된 천장만 내려갑니다 | 모두 | `test_file_sizes`(번호: 위의 규칙) |
| 이 파일의 크기 번호는 크기 가드(80줄, 80,000바이트)와 일치합니다. | 모두 | `test_conventions` |
| `subprocess` 호출(`run`, `check_output`, `check_call`, `call`)을 차단하면 명시적인 `timeout` 이름이 지정됩니다(테스트의 레거시 허용 목록) | 모두 | `test_conventions` |
| 테스트 페어링: 변경 코드가 `tests/`를 전달하는 feat/fix/refactor/perf 커밋 또는 `No-Test: <why>` 예고편에 표시되지 않는 이유 | 모두 | `test_githooks`(commit-msg 후크, TEST_PAIRING_v1; 코드/테스트 정의 `tools/review_checklist.py`, 위임 검토에서도 경고함) |
| 위임/인계/커밋 보고 시 작업 농담 ≤ 1-2 문장(위 규칙) | 모두 | 수동(검사는 막대 아래의 언어 규칙에 따라 단어 또는 문장과 일치해야 함) |
| 페이지 스크립트 또는 스타일시트 ≤ 43,000바이트; 나열된 천장만 내려갑니다 | 모두 | `test_page_scripts` |
| 새 코드 폴더가 보호됩니다(`tools/`도 마찬가지입니다. 위임 게이트의 판정 리더는 거버넌스입니다) | 모두 | `test_code_layout` |
| 모든 코드 파일(`engine/`, `providers/` 및 `tools/`, `static/`)은 도착하기 전에 `CODEMAP.md`에 행이 있습니다. 모두 | `test_code_map` |
| 핵심 모듈은 stdlib + 서로만 가져옵니다 | 모두 | `test_core_standalone` |
| repo 루트와 엔진 폴더는 `repo_layout.py`(코드) 및 `tests/_paths.py`(테스트)에서만 결정됩니다. 자체 파일에서 `static/`, `templates/`, `tests/` 또는 `docs/`를 찾는 코드가 없습니다 | 모두 | `test_code_layout` |
| 서로를 가져오는 새로운 모듈 쌍이 없습니다(함수 상단 또는 내부). 알려진 쌍만 사라집니다 | 모두 | `test_import_cycles` |
| 공통 코드에 제공자 이름이 없습니다 | 모두 | `test_provider_neutrality` |
| 페르소나 이름/제목은 표시 값이며 ID나 키가 아닙니다 | 모두 | `test_identity_wiring` |
| `bundle_budget.json` 내에 삽입된 명령어 번들 | 모두 | `test_bundle_budget` |
| 모든 계획 파일에는 유효한 상태의 하나의 INDEX 행이 있습니다. | 모두 | `test_plans_index` |
| 역사는 작게 유지됩니다. `docs/history/`의 오래된 날짜 | 모두 | `test_docs_budget` |
| 문서에서는 코드를 `path` 또는 `path::symbol`로 인용하며 줄 번호는 사용하지 않습니다. 링크 해결 | 모두 | `test_doc_refs` |
| 도구 이름이 지정된 항목 파일(`CLAUDE.md`, `GEMINI.md`)은 `AGENTS.md`만 가리킵니다. 새로 발명된 항목 파일이 없습니다 | 모두 | `test_entrypoints` |
| `AGENTS.md`는 개발 빌드 항목 전용입니다. 최대 6,000바이트이며 채팅 런타임 규칙이 없습니다. 저장소 루트에는 항목 파일과 대기 문서(지침: `RULES.md`, `CODEMAP.md`, `ARCHITECTURE.md`, `OPERATIONS.md`, 프로젝트: `README.md`, `VISION.md`, `PRODUCT.md`, `DESIGN.md`, `HISTORY.md`)가 들어 있습니다. `docs/`에는 폴더만 보유 | 모두 | `test_entrypoints` |
| 문서 이름: 대문자, 소문자 케밥 누적, snake_case 없음 | 모두 | `test_doc_names` |
| 모든 등록 행에는 대상자와 실제 집행자의 이름이 지정됩니다. 모두 | `test_rule_registry` |
| 모든 시행자는 Tier 3(`protected_paths.json` 거버넌스)이고 각 커밋(`run-tests.sh` FAST)에서 실행되거나 대신 실행되는 위치와 함께 느리게 나열됩니다. 모두 | `test_rule_registry` |
| 엔진/페이지 코드에 새로운 하드코딩된 한국어가 없습니다(대신 i18n 카탈로그). 의도한 라인을 표시 `l10n-ok` | 모두 | `test_ratchets` (`ratchet_baseline.json`) |
| 호스트 플러그인 외부의 엔진 코드에 새 호스트/페르소나 정체성(DiskStation, `/volume1`, Sphere, 실장님, 냥)가 없습니다 | 모두 | `test_ratchets` |
| 추적된 작업 영역 템플릿 쌍(존재하는 경우 `data/workspace` 저장소)은 `templates/workspace-manifest.json`로 분류됩니다. `same` 쌍은 바이트 동일하게 유지됩니다. 템플릿 이름에는 호스트가 없고 엔진이 작동하지 않습니다. | 모두 | `test_workspace_template` |
| `observations.add`/`observation` 도구를 통해서만 관찰 | 모두 | `test_observations`(모양) |
| 운영자와 한국어로 대화하세요. 루트 스탠딩 문서(`*.md`)는 일반 영어로 된 에이전트 SSOT입니다. `*.ko.md` 미러는 사람이 읽을 수 있도록 기계 번역됩니다(에이전트는 수집/편집하지 않음). 계획은 한국어일 수 있습니다 | 모두 | 수동(채팅 에이전트 런타임 음성은 여기가 아닌 작업 공간 헌장에 유지됨) |
| 영어로 된 상담원 관련 기계 텍스트(프롬프트, 도구 문자열, LEARNED 줄) | 모두 | 매뉴얼 |
| 각 요청을 프로젝트 목표와 비교하여 확인하세요. 적합하지 않을 경우 범위 재지정을 거부하거나 제안 | 모두 | 매뉴얼(플랜 게이트 G2, DoR) |
| 구축하기 전에 선행 기술을 찾으십시오(`~/AGENTS.md` §0) | 모두 | 매뉴얼 |
| 엔진은 어떤 코드를 해결할 수 있는지(도구 선택, 인수 형태, 형식, 분류) 결정합니다. 모델은 캐릭터의 말과 행동만 유지합니다 | 모두 | 설명서(`docs/plans/engine-decides.md` 계획, `logs/events.jsonl`의 실패율) |
| 결과는 언어나 모델의 표현에 좌우되지 않습니다. 단어나 구문이 일치하지 않으며 모델 텍스트를 추측할 필요도 없습니다. 엔진 사실과 텍스트를 있는 그대로 표시 | 모두 | 설명서(검토; `test_ratchets`의 l10n 래칫은 하드코딩된 한국어만 포착합니다.) |
| 생성 가능한 디렉토리는 최소화됩니다(`ADD_DIRS`) | 모두 | 매뉴얼 |
| 채팅 에이전트에 대한 엔진 작업 규칙은 `dev` 역할 팩에 있으며 공유 헌장이나 다른 역할의 `role.md` | PE 채팅 에이전트 전용 | `test_dev_role` |
| 개발 및 배송 지침은 절대 혼합되지 않습니다. 두 빌드 모두에 대해 하나의 배송된 지침이 있습니다. `DEV-CHARTER.md`에서만 dev-build 규칙이 적용되며, `host_config.EDITION`가 dev인 경우에만 삽입됩니다. 어느 파일도 다른 파일을 반복하지 않습니다. 배송된 번들 이름에는 개발 도구가 없습니다. 배송된 역할 팩은 배송된 기술만 명명합니다 | 모두 | `test_edition_instructions`, `test_workspace_template` |

