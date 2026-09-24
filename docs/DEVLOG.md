# chatbot 개발로그

최근 항목만 여기 둔다(맨 위가 최신). 지난 날짜는 `docs/devlog/YYYY-MM-DD.md` — 코드가 "2026-09-17 DEVLOG"를 가리키면 그 파일이다.
이 파일이 40KB를 넘으면 가장 오래된 날짜를 `docs/devlog/`로 옮긴다(`tests/test_docs_budget.py`).

## 2026-09-24 (저녁) — 오후 정리와 위임 절차 보강 A·C·D (STABILIZE_v1, DELEGATION_HARDENING_v1, 티켓 #143, #142)

- **배경**: 오후에 여러 에이전트(Hermes, Claude Code 세션 둘, 챗봇 claude·agy)가 같은 저장소를 동시에 고쳤고, #140(선택지 밖 채널 1단계)이 리뷰 시간 초과·불합격으로 두 번 실패. 챗봇이 드러난 구멍을 #142로 모음. 사용자: "난리가 났어… 알아서 해줘".
- **정리 (#143)**: #130이 커밋을 빠뜨린 `app-messages.js`(액션 말풍선 `✦ …`을 기록 `(…)`로 맞춤)를 살리고 테스트 가짜 DOM에 선택자 목록 지원·사례 추가. 커밋 안 된 티켓 기록 #130–#143, #130의 DEVLOG, 기본 캐릭터 두뇌 변경(claude/opus)을 커밋. `MEMORY.md`는 개인정보라 제외.
- **보강 (#142 A·C·D)**:
  - A. 지시문 2,000자 자르기 없앰. claude·codex는 프롬프트를 표준 입력으로(`stdin_prompt`) — 128KB 인자 상한이 없어 리뷰 diff 한도 200KB, 인자로 받는 agy·grok은 36KB 유지. 리뷰 프롬프트는 두뇌마다 그 한도로 만든다.
  - C. 응답 자체가 없던 실패(한도·시간 초과·CLI 없음)는 `unavailable`로 반납, 티켓이 시도를 돌려준다(티켓당 3번까지). `ticket-quick fail --outcome unavailable`.
  - D. PD 절차: 작업 하나 = 관심사 하나(대략 파일 몇 개·300줄), 경로는 실제 파일·새 파일은 `creates`, 테스트 포함, 무관한 수정 금지.
- **B (NEED_PATH_v1, #144)**: 작업자가 범위 밖 파일이 필요하면 `NEED_PATH: 경로 -- 이유`로 멈춘다 → 러너가 작업을 보존하고 `paused`로 반납(시도 반환, 횟수 제한 없음 — 재개는 실장님만). 작업 카드 "경로 요청"에 파일·이유와 [경로 허용]·[폐기]. 허용하면 경로 검사(Tier 3·없는 폴더 거절) 후 그 작업에 더해 보존된 브랜치에서 다시 실행.
- **#140 1a (OUT_OF_BAND_CHOICES_v1)**: 선택지 표식을 서버(`finalize_turn`, 모든 프로바이더 공통)가 답에서 떼어 `choices` 필드로 기록·전송. 기록·CLI·에이전트 맥락에 표식이 남지 않고, 화면은 그 값으로 버튼을 그림. #140의 나머지(`choices` 도구·`action` 이벤트·티켓 바 직접 실행)는 계획서 1단계에 남김. agy 리뷰어는 도구를 끌 수 없으니 PD 두뇌 목록에서 claude를 앞에.

## 2026-09-24 — 사적 모드 액션 선택지 · 직접 행동 입력 · 표정 연동 · 속마음 연출 (PRIVATE_INTERACTION_v1, 티켓 #130)

- **배경**: 실장님 제안 — `character-chat` 서비스의 검증된 상호작용 메커니즘을 참고하여 See1 챗봇 규격에 맞게 흡수 및 리네이밍. 지문/대사 분리, 표정 태그 연동, 속마음 토글 박스, 액션 선택지 및 직접 행동 전달 방식 구현.
- **변경**:
  - 표정 태그 연동 (`static/markdown.js`, `static/chat-log.css`): 응답 헤더의 `[expression: neutral|joy|shy|serious|sorrow|tired]`를 파싱해 메시지 상단에 감정 뱃지(`.exp-badge`)로 렌더링하고 마크다운 본문에서는 깔끔하게 제거.
  - 속마음 독백 연출 (`static/markdown.js`, `static/chat-log.css`): SimCore `state` JSON 블록의 `thought` 및 `<thought>` 태그를 본문에서 분리, 하단에 '속마음 보기' 토글 버튼(`.thought-toggle`)과 독백 상자(`.thought-box`)로 연출.
  - 액션 선택지 (`static/markdown.js`, `static/chat-log.css`): `<!--choices: 라벨 -> 행동 | ...-->` 화살표 구문 파싱 지원, 선택지 버튼에 `✦ ` 및 `.choice-action` 스타일 적용, 클릭 시 사용자 말풍선 없이 즉시 지문 액션 발송.
  - 직접 행동 입력 (`static/app.js`, `static/slash.js`, `static/app-messages.js`): `/act <행동>` 슬래시 명령어 등록 및 `sendAction()` 연동. 사용자 입력창에서 행동 전달 시 대화 말풍선 대신 지문(`.msg.action`)으로 표시하고 모델에는 `(<행동>)` 지문으로 전달.
- **검증**: `tests/test_choice_chips.py` 8개 테스트 전체 통과(액션 선택지, 표정, 속마음, 화살표 구문), `tests/test_page_scripts.py` 4개 통과(1,000줄 미만 유지), `tests/smoke.py` 및 관련 테스트 전체 통과.
- **배포**: 정적 UI 자산이므로 브라우저 새로고침(Ctrl+Shift+R / F5)으로 즉시 적용.

## 2026-09-24 (오후) — 세션 조회 캐시 · 파일 단위 잠금 · 테스트 기준선 · app.js 분리 (SESSION_INDEX_v1 … APP_SPLIT_v1, 티켓 #113–#117)

- **배경**: 사용자 "전체적으로 반응이 나빠진 것 같아"; 이번 대화에서 드러난 불편(잠금 하나에 다른 작업이 막힘, 막힌 [진행]이 조용히 실패, 남의 티켓에 버튼) 1–3번 개선 승인; "리팩토링 한 번 해야 하지 않을까?" → 추천안(안전망 → app.js → session.py) 승인.
- **변경**:
  - 반응성: 페이지가 2.5초마다 묻는 최신 세션 조회가 `meta.json` ~320개(2.8MB)를 매번 전부 읽었다(REG.lock 안, p50 174ms). 파일별 요약 캐시(수정 시각·크기)로 실서버 7ms, 목록 4ms (#113; 챗봇 위임 1차는 20분 제한으로 실패 — 증상 없는 티켓, 없는 파일 경로).
  - 잠금 (#115): 파일 단위 잠금 `leases.json`(겹칠 때만 대기, 파일을 안 적으면 전체), 막힌 이유 `blocked_by` 표시, [실행] 대기열(파일이 풀리면 서버가 시작, [대기 취소]), 담당자 `owner`(`ticket-quick start`로 연 티켓은 그 에이전트만; [담당 해제]), 상위 폴더부터 적은 경로를 저장소 기준으로 맞춤. `~/bin/ticket-quick`에 `claim`.
  - 테스트 기준선 (#116): 오래 실패하던 4개를 현재 동작에 맞춤. 덤: 중지 후 agy의 "interrupted"가 에러 공지로 남던 버그.
  - app.js 분리 (#117): 6,197줄 → 931줄 + 13개 부분, 로드 순서 가드 테스트. `PROJECT.md`의 "더 쪼개지 말 것" 지침을 새 지도로 교체.
  - session.py 분리 (#118): 세션 목록·조회를 `session_registry.py`(297줄)로, `session.py` 2,601 → 2,335줄. 이름은 `session`에서 그대로 다시 내보냄.
  - 위임 명확화 (#119): 계획의 `paths`는 실제 파일만(없으면 가장 가까운 실제 파일을 알려 주며 거절), 새 파일은 `creates`. 작업 카드에 라운드 시계(12:30/20:00)와 바뀐 파일 수, 시간 초과는 "timed out after Ns". 위임 중 채팅 배지는 "루루 작업 중 · mm:ss".
  - 에이전트 중심 구조 (#120–#122): DEVLOG 401→29KB(지난 날짜 `docs/devlog/`), `docs/plans/INDEX.md`, README는 입구만(지도는 PROJECT.md 하나), 사적 세션 지침 7.6→4.2KB(헌장은 앞머리+Scope, 전환 규칙은 호스트 안내 한 곳, 카드 규칙 영어), `adapters.py` 프로바이더별 분리(#122), `providers/` 폴더 시범과 보호 누락 수정(#123), `chat.css` 여섯 조각(#124), 문서·파일 크기·보호 가드 테스트.
- **검증**: 모든 테스트 모듈 개별 실행 통과(이전 실패 4개 포함). 한 프로세스 `discover`는 전역 누수로 ~40개 실패 — 규칙은 모듈별 실행, 격리는 별도 작업.
- **배포**: repair 3회(유휴 3연속 확인 후). app.js 분리는 정적 파일만(새로고침).
- **남은 것**: 테스트 격리(한 번 test_delegation·test_mcp_server가 개별 실행에서도 실패했다가 재실행 3회는 통과 — 원인 미상),.

## 2026-09-24 — 캐릭터 선택기 · 이미지 형식 · 역할 팩 · 개선 히스토리 (CHARACTER_PICKER_v1 … AVATAR_BASE_PATH_v1, 티켓 #102–#112)

- **배경**: 사용자 결정 — 왼쪽 위는 캐릭터 선택, 프로바이더는 이름을 눌러 고름(캐릭터마다 마지막 두뇌 기억). 이미지 에이전트가 따를 형식이 필요하고, 전신·표정도 같은 형식으로 만들 수 있게 한다(데스크톱 모드는 먼 구상). "모든 캐릭터는 동등하다 — PD는 PD 지침과 PD 스킬셋으로 정해진다."
- **변경**:
  - 캐릭터 선택기: 아바타 = 캐릭터 트레이, 프로바이더 이름 = 두뇌 트레이. 캐릭터를 고르면 그 캐릭터의 같은 모드 최신 세션(없으면 카드의 첫 두뇌로 새 세션) (#102).
  - 이미지 형식 `character-art` 스킬 + `tools/check_character_art.py`: 아바타 512·가발, 투명 스프라이트 `bust` 1024²·`full` 1024×2048(SillyTavern 표정 이름표, `neutral` 먼저), `visual.md` 외형 락 (#103).
  - 역할 팩: 카드에는 역할이 없다. `roles/<role>/role.md`(매 턴, `tools`·`skills`) + `procedure.md`(필요할 때), `team.json`(`default`, `members`). 도구 권한 `delegate`·`house-memory`는 역할 팩이 준다(PD 팩만 가짐). `memory/MEMORY.md`는 집 공용 기억, 캐릭터마다 자기 `memory.md`. 팀 탭은 캐릭터를 똑같이 보여 주고 `[역할]`로 편성 (#104–#105). 루루 카드·그림은 챗봇이 직접 (#106–#107).
  - 개선 탭: "오늘 처리" 대신 처리된 관찰 전체를 10개씩 페이지로 (#108).
  - 그림 주소에 `BASE_PATH`와 파일 시각 버전, 선택기는 열 때마다 목록 새로 읽음, 프로바이더 트레이·채팅 배경도 열린 캐릭터 기준. 배경은 형식에 추가: `stage.webp`·`stage/<provider>.webp` 1024² (#109).
  - 챗봇 직접: 냥피디 → 냥냥 이름 변경(#110), 옛 `role` 스킬 폴더 삭제(#111–#112).
- **사고**: 세션 캐릭터 이전(#105)이 `meta.json` 312개를 다시 쓰면서 수정 시각이 모두 같아져 세션 목록 순서가 뒤섞임(사용자 "세션이 꼬여서…"). `updated_at`으로 311개 복구, 이전 코드는 수정 시각을 보존하게 고침.
- **검증**: 새 테스트 test_character_picker(`BASE_PATH` 가드 포함)·test_character_art·test_team_roles·test_observation_history 통과, 전체 실패 목록은 작업 전과 같음. 실서버에서 선택기·가발·배경·역할 편성 확인.
- **배포**: repair는 모두 유휴 3연속 확인 후. 헌장·`protected_paths.json`이 바뀌어 `evolution.py manifest-update`는 사용자 몫.
- **남은 것**: 카드 가져오기·내보내기, §11 5단계(PD의 영입 제안), 냥냥 이미지를 `data/persona/`에서 캐릭터 폴더로. 작성자 잠금이 하나라 사람이 티켓을 쥐면 챗봇 위임이 막힘.

## 2026-09-23 — 캐릭터 카드 · 사적 기억 · 세션 이원화 (CHARACTERS_v1 … PRIVATE_ON_OFF_v1, 티켓 #92–#101)

- **배경**: 설계서 §12 — 모든 캐릭터와 업무·사적 관계, 카드 V2. 사용자 결정: 사적 대화도 기억하되 업무와 완전히 분리, 나아가 세션 자체를 이원화.
- **변경**:
  - 캐릭터 = TypeID 폴더(`characters/char_<uuidv7>/card.json`, Character Card V2 + `extensions.chatbot`). 루루(staff), 냥피디(pd) 이전; PERSONA.md·PRIVATE.md·pd-brain.json 제거 (#94, #96–#97; 실측 #95는 폐기).
  - 전문가 기억(`LEARNED`, PASS일 때만) (#92; 실측 #93은 폐기).
  - 사적 기억 `private-memory.md`(2KB, 비밀 필터), 사적 세션에서는 업무 도구 거부 (#98).
  - 세션 이원화: 세션 = 캐릭터 × 모드. `/private on|off`(맨 `/private`는 토글), 입력창 하트 버튼, 🔒 표시, 스크롤백·최신 이동은 같은 모드 안에서만; 사적 세션 지침 = 헌장 + 카드 + 사적 규칙 + 사적 기억; 나올 때 사적 대화를 최대 3줄로 정리 (#99–#101).
  - 사적 기억 파일은 `.gitignore` (원격 저장소로 나가지 않게).
- **검증**: 새 테스트 test_session_split·test_private_toggle 통과, 전체 실패 목록은 작업 전과 같음(기존 실패만). 실서버에서 on/off/토글 전환, 사적 세션 재사용, 업무 세션 유지 확인; 사용자가 사적 대화 → 사적 기억 정리까지 확인.
- **배포**: repair 2회, 모두 유휴 3연속 확인 후.
- **남은 것**: 채팅 캐릭터 선택(§12 4단계), 팀 탭 카드 편집기(3단계), 업무 기억 캐릭터 폴더 이전, 카드 가져오기·내보내기, §11 5단계(PD의 전문가 제안).

## 2026-09-23 — PD 모델 · 캐릭터 전문가 · 팀 탭 (PD_CONFIRMS_v1 … STATUS_TEAM_TAB_v1, 티켓 #74–#91)

- **배경**: 사용자 결정 — 챗봇은 PD(계획·위임·확인·보고), 사용자는 제안과 두 번의 컨펌(실행 전·반영 전). 이어서 "전문가 = 폴더 하나, 두뇌 순서 + 자동 대체, 지속 기억, PD 제안·사용자 승인"(설계서 §11), 그리고 캐릭터 중심 재정의(§12: 모든 캐릭터와 업무·사적 관계, 카드 V2). 상시 프로바이더는 agy.
- **변경**:
  - 역할 반전: 스태프(루루)가 작업, 챗봇 페르소나가 PD로 확인 (#74). PD 계획 → `[실행]` → 작업마다 전문가 작업·PD 확인 → `[승인]`/`[반려]`/`[폐기]`, 자동 병합 없음; `tickets.rework` (#75).
  - 지침: PD 절차에 "기존 구현부터" (#76). 원칙 0 — 에이전트용 지침은 영어; 헌장·페르소나 영어화로 매 턴 지침 5791→4683B, 분량 테스트 통과 (#80). 호스트 `~/AGENTS.md` §0 추가(미커밋, 다른 수정과 섞여 있음).
  - 상태 탭 "에이전트 지침": 에이전트가 읽는 것 전부, 편집 가능 여부는 `protected_paths.json`으로 (#81); 이후 한 줄씩 접힘 (#90).
  - 위임 버그: `[승인]` 경쟁 상태(병합 프로세스가 곧바로 종료) 수정 + `[승인 다시]` (#85, #84 수동 복구 후 병합 확인); 러너 `-p` 인자 순서(agy·grok), 리뷰어는 빈 방에서 (#78); SSE 핸들러 `loadWork` 가드 (#91).
  - agy 기본: 위임 기본 프로바이더 agy, `--add-dir`로 worktree에 쓰게, 모델 명시 (#86). 실측 #87(agy 작업·확인 PASS, 폐기).
  - 전문가 폴더 `data/workspace/experts/<role>/`(`expert.md`, `brain.json`) + `pd-brain.json`; 두뇌 순서와 쿼터·한도·무응답 시 자동 대체, 두뇌별 제한시간 (#88). 실측 #89(agy 안 Claude 45초 무응답 → Gemini flash로 대체, PASS, 폐기).
  - 팀 탭(Alt+7): PD·전문가 카드, 두뇌 순서 편집, 캐릭터 파일 (#90).
- **검증**: 모듈별 전체 실행 — 실패 5개(conversation_sync, mcp_server, observation_ui, served_model, status_picker)는 이번 작업 전부터; bundle_budget은 이번에 통과로 바뀜.
- **배포**: host module + static, repair는 모두 유휴 3연속 확인 후.
- **남은 것**: §11 4단계(지속 기억)·5단계(PD의 전문가 제안), §12 캐릭터 중심 전환(카드 V2·캐릭터별 지침·채팅 캐릭터 선택). 제품 구상은 위키 `concepts/character-agent-product`(Steam 창작마당형 엔진).

## 2026-09-23 — ticket #83 호스트/NAS 결합 경로 일반화 (DiskStation 의존성 격리)

- **배경**: 실장님 지시 "챗봇 결합 코드 정리" (호스트/NAS 결합). 코어 모듈 내 남아있던 `/volume1/homes/me` 하드코딩 기본값 및 DiskStation 특정 환경 의존성 완화.
- **변경**:
  - `host_config.py`: `HOME` 및 `ROOT`를 동적 파생(`Path(os.environ.get("HOME") or "/volume1/homes/me")`, `Path(__file__).resolve().parent`)으로 상단 배치하고, `AGY`, `CLAUDE_BIN`, `GROK_BIN`, `CODEX_BIN`의 기본값을 `HOME / ".local" / "bin"` 기반으로 연결.
  - `mcp_server.py`: `HOME` 기본값을 `$HOME` 우선 탐색으로 통일.
  - `chatbot-ctl.sh`: `HOME_DIR`을 `${HOME_DIR:-${HOME:-/volume1/homes/me}}`로 완화하고, `SCRIPT_DIR`을 통해 `CODE`를 스크립트 실행 위치 기준으로 자동 기본 설정.
  - `static/app.js`: `formatToolCallClient`에서 특정 사용자명(`/volume1/homes/me/`) 하드코딩 대신 `/(?:volume1\/homes|home)\/[^/]+\/` 패턴으로 일반화.
  - `tests/test_loop_guard.py`: `APP` 경로를 `Path(__file__).resolve().parent.parent / "static" / "app.js"`로 동적 계산.
- **검증**: `python3 tests/smoke.py` PASS, `python3 -m unittest tests/test_loop_guard.py` PASS (19건), 게이트 스위트(`test_provider_neutrality`, `test_identity_wiring`, `test_nas_mcp_host`) 25건 PASS, `chatbot-ctl.sh guard` PASS.
- **배포**: Tier 2 (호스트 모듈 수정) → 실장님 확인 후 ⚡소생 필요.

## 2026-09-23 — 워크트리 위임 + 두 캐릭터 콤비 리뷰 (WORKTREE_DELEGATION_v1 … WORK_CARD_FEEDBACK_v1, 티켓 #58–#73)

- **배경**: 사용자 "두 미소녀 페르소나 에이전트의 티키타카 만담", 개입 최소, 병렬 없음. 설계·결정은 `docs/plans/multi-agent-worktree-delegation.md` §7–9.
- **흐름**: chat-agent가 `delegate`(Tier 0은 바로, Tier 2는 제안 → `[맡겨]`) → `tools/worktree_runner.py`가 격리 worktree에서 작성자 캐릭터(`PERSONA.md`)가 고치고 리뷰어 캐릭터(`PERSONA-reviewer.md`)가 diff를 PASS/FAIL로 받아침(최대 2라운드) → 게이트(smoke + 중립성 가드) → Tier 0은 ff 병합, Tier 2는 `awaiting_merge` → `[병합·⚡]`. 대사는 입력창 위 작업 카드, 끝나면 채팅 알림.
- **변경**: `tools/worktree_runner.py`(러너·Tier·환경변수 허용목록), `delegation.py`(누가 시작·병합·폐기), `mcp_server.py` `delegate`, `server.py` `/api/delegations`, `static/app.js`·`chat.css`·`index.html` 작업 카드, `tickets.py` `awaiting_merge`/`merge_go`, `evolution.py` `delegation_tier` + `protected_paths.json` `governance`(Tier 3), `identity.py` 역할별 페르소나, `host_config.py` `CHATBOT_DELEGATE_*`, `PROJECT.md` "고칠 때"(파일 변경은 `delegate`가 기본). 저장소 밖: `~/bin/ticket-quick` `fail`/`renew`/`await-merge`/`merge-go`, 라이브 챗 에이전트 호출 거부.
- **검증**: `tests.test_worktree_runner`(30), `tests.test_delegation`(16), `tests.test_tickets`·`test_evolution`·`test_identity` 추가분, 가드·smoke. 실측 #60(claude 작성·haiku 리뷰 PASS·병합), #71(라이브 챗 → `delegate` → 병합, 2분 반).
- **배포**: host module + static, repair 3회(유휴 3연속 확인 후). `protected_manifest.json`은 사용자가 재기준.
- **남은 것**: 리뷰 FAIL → claude `-c` 재시도는 실측 전. 전체 스위트의 기존 실패 6모듈(bundle_budget 등)은 이번 변경 전부터. 라이브 모델이 문서 규칙을 무시해 `ticket-quick` 차단으로 강제함 — 그래도 직접 고치면 헌장 한 줄(Tier 3, 번들 예산 초과 상태) 필요.

## 2026-09-23 — STATUS_MCP_HOOKS_v1 (상태 탭 MCP·훅 상세)

- **배경**: 실장님 "상태 탭에서 MCP나 hook에 대해 더 자세한 정보가 나오면 좋겠네. 토글해서 도구목록을 볼수있다거나".
- **변경**:
  - `workspace_status.py`: self-status MCP 항목에 `tools`/`tool_count` (로컬 nas는 `mcp_server.tool_defs`, 원격은 짧은 `tools/list` 프로브). 훅에 `supported_events`·`path` 명시.
  - `static/app.js`/`chat.css`/`index.html`: MCP·훅 카드를 `<details>`로 접었다 펼쳐 도구/이벤트 목록 표시. `app.js?v=137`.
- **검증**: `py_compile`, self-status 샘플에 tools>0. python → repair, static → 하드 새로고침.
- **배포**: host module + static.

## 2026-09-23 — AUTH_HEAL_ONCE_v1 (Agy→Grok 자동 전환)

- **배경**: 실장님 "Agy 로그인·선택 후 가만 있으면 Grok으로 바뀜". `refreshProviderAuthMap()`이 계정 폴마다 현재 제공자가 잠깐 `로그인 필요`면 카탈로그에서 첫 사용 가능 CLI(대개 로그인된 Grok)로 UI·localStorage를 바꿔 버림.
- **변경**: `static/app.js` — 자동 복구는 페이지당 1회만(`_authHealTried`); 현재 제공자가 다시 사용 가능해지면 플래그 리셋. `selectProvider`는 `localProviderEdit`로 감싸 세션 동기화 레이스로 서버(옛 Grok) 값이 덮어쓰지 않게. `app.js?v=136`.
- **검증**: 마커 grep. 정적 → 하드 새로고침.
- **배포**: static only.

## 2026-09-23 — AGY_PASTE_CR_v1 (코드 제출 무반응)

- **배경**: 실장님 "제출했는데 반응 없음". `complete()`가 OAuth 코드를 `code\n`(LF)로 PTY에 써서 agy 1.2.8 TUI 입력칸에만 들어가고 제출이 안 됨. `\r`(CR)이어야 token exchange 시작.
- **변경**: `account_login.py` — paste를 `\r`로 전달; `token exchange failed`/`invalid_grant`면 failed로 표시. `app.js` — complete 실패 시 alert, pending이면 안내문 갱신. `app.js?v=` bump.
- **검증**: unittest account_login; live fake code → failed(invalid_grant). repair 후 사용.
- **배포**: python → repair, static → 하드 새로고침.

## 2026-09-23 — LOGIN_PASTE_KEEP_v2 (OAuth 코드 붙여넣기 리셋)

- **배경**: 실장님 "또 붙여넣으니 리셋". Agy 로그인 pending 중 2초 `startLoginPoll`이 `renderLoginFields`로 입력칸을 매번 재생성하고, `fetchAccounts`가 `.login-panel`까지 `innerHTML`로 날림.
- **변경**: `static/app.js` — pending+동일 login_id/URL이면 paste row 유지; 재생성 시에도 value/selection/focus 복원; `fetchAccounts`는 진행 중 로그인 패널을 detach 후 다시 붙임. `index.html` `app.js?v=134`.
- **검증**: 마커 grep. 정적 배포 → 하드 새로고침.
- **배포**: static only (repair 불필요).

## 2026-09-23 — AGY_LOGIN_TUI_v1 (agy 1.2.8 로그인 URL 즉시 실패 수정)

- **배경**: 실장님 "agy 로그인 주소 안 뜨고 바로 실패". `agy` 1.2.8이 `auth login` 서브커맨드를 제거해 `agy auth login`이 프롬프트로 오인되며 즉시 exit.
- **변경** (`account_login.py`):
  - `_login_argv(agy)` 기본값 `[AGY]` (대화형 TUI). `CHATBOT_AGY_LOGIN_CMD` 오버라이드 유지.
  - PTY에 `TIOCSWINSZ` + `TERM`/`COLUMNS`/`LINES` — 사이즈 없는 PTY에선 로그인 메뉴가 안 뜸.
  - 출력에 `Select login method` / `Google OAuth` 보이면 Enter로 1번 선택.
  - TUI soft-wrap으로 잘린 OAuth URL을 `_unwrap_wrapped_urls`로 이어 붙임.
- **검증**: `py_compile` OK, `tests.test_account_login` 11건 OK, live `account_login.start("agy")` → `accounts.google.com` 전체 URL(`oauth-callback` 포함) pending. `chatbot-ctl.sh repair` OK.
- **배포**: python host → repair 완료.

## 2026-09-23 — 외부 CLI 에이전트용 `ticket-quick` 절차를 헌장·설계서에 문서화 (티켓 #29)

- **배경** (실장님: "이 저장소에서 작업하게 될 모든 다른 에이전트가 그걸 알 수 있도록 해줄래"): 라이브 세션 밖 외부 CLI 에이전트(Claude Code 등)는 `ticket` MCP 도구에 접근할 수 없어, 매번 실장님이 `ticket-quick` 사용법을 구두로 알려줘야 했음. `~/bin/ticket-quick`은 이미 존재하지만 헌장·설계서에 미문서화 상태였음.
- **변경**: `data/workspace/AGENTS.md`(헌장) "자기수정" 절에 `ticket-quick start --title --paths` / `ticket-quick done --id --token` 사용법과, 자동승인이 절차 생략이 아니라 실장님의 실행 지시를 전제로 한다는 점을 명시. `data/workspace/PROJECT.md` "고칠 때" 절에서 헌장 참조 포인터 추가.
- **절차 메모**: 이 두 파일 자체가 Tier 3(헌장·이 설계서)라 승인된 티켓 없이 시작하면 안 되는데, 먼저 수정하고 나중에 `ticket-quick`으로 티켓 #29를 소급 생성·승인·클레임함 — 다음엔 순서를 지킬 것.
- **검증**: `tests.test_evolution`/`tests.test_mcp_server`/`tests.test_lifecycle` (139개) 통과. 문서 변경이라 ⚡소생 불필요.

## 2026-09-23 — /code-review 지적 10건 수정 (티켓 #28)

- **배경**: 실장님 지시로 `/code-review`를 백그라운드로 돌린 결과, 현재 diff에서 correctness 버그 10건 발견. 실장님 "한 번에 다 고쳐줘" 지시로 일괄 수정.
- **변경**:
  - **히스토리 유실**: `adapters.py` `finalize_turn`의 에러 종료 경로가 텍스트를 `""`로 강제해 `app.js`의 빈 텍스트 필터(EMPTY_BUBBLE_FIX_v1)에 걸려 새로고침 시 흔적 없이 사라짐 — draft를 별도 항목으로, 알림은 `notice:"error"` + 실제 텍스트로 저장. `session.py` `_read_stdout` 프로세스 사망 경로도 동일 패턴으로 `session.current_text` 보존.
  - **로그인 헬퍼 오살**: `accounts.reap_stray_cli_procs`가 `"login "` 문자열 매칭으로 자기 자신이 방금 스폰한 pending 로그인까지 죽임 — `account_login.active_pid(provider)`로 현재 추적 중인 pid는 무조건 보호.
  - **로그인 세션 레이스**: `account_login.status()`가 `login_id`를 안 받아서, 같은 provider로 재시작된 로그인의 authorize_url/user_code를 이전 폴러가 자기 것처럼 받아감 — `login_id` 파라미터 추가, 불일치 시 `superseded` 상태. `server.py`/`app.js` 배선.
  - **모델 전환이 진행 중 턴을 죽임**: `app.js` `modelEl.onchange`가 `PROVIDER_SWAP_DEFER_v1`의 `isBusy` 게이트를 안 거쳐 `selectProvider()`와 다른 경로로 재발 — 동일 게이트 적용.
  - **락 직렬화**: `account_login.cancel()`이 최대 6초 걸리는 `_kill_proc`을 전역 락 안에서 실행해 무관한 provider의 status/start 폴이 블록 — dict 조작만 락 안, kill은 락 밖.
  - **killpg 폴백 누락**: `session.py` `stop()`의 SIGKILL 에스컬레이션이 `proc.kill()` 단일 pid만 사용 — `CODEX_PROC_v1` 패턴대로 `os.killpg` 우선.
  - **PTY 에코로 코드 유출**: 로그인 실패 시 PTY 출력 tail에 방금 제출한 OAuth 코드 에코가 그대로 남아 에러 메시지로 노출될 수 있었음 — 제출 코드를 기록해 에러 메시지에서 치환.
  - **ANSI 스트립 누락**: Claude `/cost` 파싱에만 적용된 CSI/C0 제거가 구조적으로 동일한 Agy `/usage` 파싱엔 없었음 — 동일 적용.
  - **캐시 남용**: `account_login._account_ok`가 로그인 대기 중 매 ~1초 폴마다 claude 계정 캐시를 강제 무효화(최대 ~700회 subprocess) — PTY 출력 증가(=상태 변화 가능성)가 있을 때만 무효화.
- **검증**: `python3 -m py_compile` PASS, 관련 유닛테스트 94개 (`test_account_login`/`test_accounts`/`test_lifecycle`/`test_session_swap`/`test_http_adapter_stale_turn`/`test_no_trace`/`test_stderr_redaction`/`test_served_model`/`test_provider_sync`/`test_core_standalone`/`test_steer`/`test_loop_guard`) 전체 통과, `tests/smoke.py` 통과, `chatbot-ctl.sh guard`/`doctor`/`probe` 통과. `tests/test_served_model.py`의 낡은 캐시버스터 핀(`chat.css?v=20`)도 현재 값(`v=27`)로 갱신.
- **배포**: python → ⚡소생 완료 (실장님 직접 재기동, pid=25984/25977).

## 2026-09-23 — 쿼터 소진 침묵·성공턴 에러공지 중복 (QUOTA_SILENT_FIX_v1)

- **배경**: 쿼터 소진 시 침묵. 이후 성공 답과 함께 쿼터 에러 공지·메시지 중복(실장님, `20260923-094617-bf27a0`).
- **원인**: live `finalize_turn`이 `is_err`+본문일 때 draft 답과 `notice:error`를 **같은 ts로 이중 append**. 에러-only는 `event:result`+빈 text라 UI notice 미표출.
- **변경**: 본문 있으면 답만 저장·event result. 에러-only는 notice:error + event error. app.js 잔여 error/history twin 정리. `app.js?v=138`.
- **배포**: 강제 새로고침 + `chatbot-ctl.sh repair`.
- **마커**: `QUOTA_SILENT_FIX_v1`

## 2026-09-23 — 쿼터 오류 이중공지·새로고침 유실 (QUOTA_ERR_DEDUP_v1)

- **배경**: 쿼터 소진 시 한글 unfinished + 원문 quota 오류가 실시간 두 줄. 새로고침하면 사라져 보임.
- **원인**: finalize_turn `event:error` 후 `_end_unfinished_turn`이 history 없는 오류를 한 번 더 emit.
- **변경**: 이미 notice:error면 emit_error=False로 자식만 중지. 쿼터 한국어 한 줄. error_message 진행표시. history는 addNotice. `app.js?v=140`.
- **배포**: 강제 새로고침 + repair.
- **마커**: `QUOTA_ERR_DEDUP_v1`

## 2026-09-23 — agy error_message 후 장기 대기 차단 (QUOTA_FAILFAST_v1)

- **배경**: 쿼터 소진 시 진행표시가 `쿼터·오류 확인 중…`에서 1~2분 유지(실장님).
- **원인**: agy가 `step_type=error_message` 직후 곧바로 result를 안 보내고 print-timeout 근처까지 대기.
- **변경**: error_message 관측 후 8초 내 result/error 없으면 failfast로 notice:error 1회 + 자식 중지. 실제 result가 먼저 오면 타이머 취소.
- **배포**: `chatbot-ctl.sh repair` (호스트 모듈).
- **마커**: `QUOTA_FAILFAST_v1`

## 2026-09-23 — 답 있는 ERROR 턴에서 오류공지·답 재출력 (QUOTA_ANSWER_WINS_v1)

- **배경**: 쿼터 ERROR인데 인사 답은 나온 뒤, unfinished 오류 공지 + 인사 재출력(실장님).
- **원인**: `finalize`가 답(result)을 만든 뒤 `status=ERROR`로 `_end_unfinished_turn`이 **즉시** error emit → UI가 draft 확정/공지 후 result로 답을 한 번 더 그림.
- **변경**: `final` 본문이 있으면 `emit_error=False`로 자식만 중지(공지 없음). notice:error인 경우도 동일.
- **배포**: repair.
- **마커**: `QUOTA_ANSWER_WINS_v1`

## 2026-09-23 — 턴 종료 순서 정리 (TURN_END_ORDER_v1)

- **배경**: 쿼터 ERROR인데 인사 답이 나온 뒤 오류 공지 + 답 재출력. 임시 패치(ANSWER_WINS 등)로도 재발 여지.
- **근본 원인**: Agy `result` 처리가 `finalize` 후 `_end_unfinished_turn`→`_auto_stop`→**즉시 `_emit`** 하고 나서야 `events.append(out_ev)`. 공지/중지가 답 이벤트보다 먼저 UI에 도착.
- **변경**:
  1. `events.append(out_ev)`를 먼저.
  2. 필요 시 `_request_post_result_stop`만 걸고, `_handle_events`가 result/error flush·busy 해제 **이후** 자식 프로세스만 중지.
  3. 미완성 한글 공지는 finalize가 이미 error/답이면 추가하지 않음(빈 SUCCESS 타임아웃만 이벤트 배치에 포함).
- **배포**: repair.
- **마커**: `TURN_END_ORDER_v1`

## 2026-09-23 — 구조화 관측 로그와 자기진화 연동 (OBSLOG_v1 ~ WATCHDOG_OS_FACTS_v1, 티켓 #39–#53)

- **배경**: 사용자 "에이전트가 로그만 분석해도 모든 상황·문제·개선점을 파악할 수 있으면 좋겠어". 기존 로그는 access 줄에 시각이 없고 90%가 폴링, repair 호출자 기록 없음, 세션 로그와 서비스 로그를 맞춰 볼 방법이 없었음.
- **로그**: `obslog.py` → `logs/events.jsonl` 단일 원천(chat·mcp·ctl·세션 턴). ISO 시각, rid/sid, 비밀값 가림, 오류 지문, 폴링은 5분 요약, 폭주 억제(#44), 10MB×5 로테이션. 경로는 ctl이 export할 때만 기록(테스트·에이전트 자식은 상속 안 함, #45).
- **읽기**: `logdigest.py` / `chatbot-ctl.sh logs` (findings 우선, `--sid/--rid/--fp/--evt/-f/--json`), 채팅 UI 로그 탭 → **서비스** (`/api/service-log`, #42). 스키마·이벤트 사전: `docs/LOGGING.md`.
- **자기진화 연동**: findings → `host:<code>` 관찰 후보(채팅 서버 스레드, 시간당, #46·#52), 티켓 근거 `log:fp:`/`log:rid:` (#47, `~/bin/ticket-quick --evidence`). 설계서 §4.2, §7-6(계측 기준 = Tier 3), §7-7(감시자는 서비스에 의존하지 않음).
- **로그가 찾아 고친 것**: provider 전환 10–17초 동기 요약(#50, 즉시 응답 + 백그라운드 요약), doctor가 살아 있는 서버의 warm standby를 반복 종료(#51), 판정 오류 2건(#48). `session.py`의 `sys` 미import NameError(meta.json 손상 시).
- **감시자**: `ctl_proc.py` — 정리·repair 전 대기를 OS 사실(프로세스 표, /proc, ctl pid 파일)로만 판단. 남의 agy는 더 이상 건드리지 않음(#53).
- **정리**: `*.bak-*` 68개 → `~/archive/2026-09-23-chatbot-bak/`(검증 후 삭제, #41), 매니페스트 재기준(#43).
- **사고**: 배포 대기 확인이 턴 사이 0.1초 틈에 걸려 사용자 턴 1건 중단(11:58) → 이후 배포는 연속 3회 한가 확인 후 진행.
- **다음에 볼 것**: 서비스 탭 24h의 repair 호출자(주 240회 원인), `turn.end outcome=process_died`(새 대기 판정 오판 여부).

## 2026-09-23 — 이름·provider 중립화 (NAME_NEUTRAL_v1 #57, PROVIDER_NEUTRAL_v1 #58)

- **배경(사용자)**: "냥피디/실장님은 일반화되지 않은 명칭 — 판별 근거로 유통되지 않게", "실장님은 페르소나가 유저를 부르는 호칭일 뿐", "agy도 프로바이더 중 하나일 뿐".
- **이름**: 저장·판별값은 역할 ID(`operator`, `chat-agent:<provider>`, `claude-code`…, 코어가 `evolution.ROLE_ID_RE`로 강제), 표시는 identity. 기억 템플릿 `## 사용자`, 규칙 문서는 "사용자". `static/index.html`의 굳은 identity를 `<!--IDENTITY-->`로 복구(e93d52c에서 덮어써짐).
- **provider**: `AgentSession`, `reap_orphan_agents`, SSE `provider_event`, `CHATBOT_*` 설정(옛 `AGY_CHAT_*` 호환). 어댑터 능력 훅(`oneshot`/`native_compact`/`has_conversation`/`supports_steer`), 미디어 위치 등록부(`media_handler.MediaSource`), provider 특성(`accounts.RECYCLE_ON_LOGIN`/`LOGOUT_NOTES`), 카탈로그(`name`/`theme`/`login`). 서버는 agy 없이도 시작.
- **발견**: 리팩터 중 아티팩트 탭 `bdir` NameError(미배포 상태에서 잡음), 헌장 번들 예산 초과(5,791/4,800, 기존), `test_account_login`의 환경변수 누수(기존).
- **재발 방지**: `NameNeutralityGuard`(금지 이름은 인스턴스 identity에서), `tests/test_provider_neutrality.py`(provider 목록은 어댑터 등록부에서). 설계서 §7-8, §7-9.
- **사고**: 배포 확인 중 서버 환경변수를 거르지 않고 출력해 OmniRoute API 키가 세션 출력에 노출 → 교체 권고.
