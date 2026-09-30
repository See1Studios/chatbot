# chatbot 개발로그

2026-09-28 기록은 하루 40KB 예산에 도달해 [devlog/2026-09-28.md](devlog/2026-09-28.md)로 회전했습니다.

## 2026-09-30 — 역할 이름 정리: lead 총괄 · plan 기획 · dev 개발 · art 아트 (#463)

- **결정(운영자, 채팅 → 이 세션)**: 팀 체계 [총괄-기획-개발-아트], 식별자 `lead`·`plan`·`dev`·`art`. `staff`는 `plan`으로 바꾸고 리리가 개발+기획.
- **변경(사용자 데이터, Tier 3 — 운영자 승인)**: `roles/pd`→`lead`, `roles/staff`→`plan`(본문을 기획 역할로 새로 씀), `roles/artist`→`art`(배포 템플릿도 같이, 매니페스트 갱신), 제목 한국어(총괄·기획·개발·아트). 팩 본문에서 다른 역할을 부르던 "the PD"·"staff"·"the user"는 매크로 `{{default}}`·`{{user}}`로(#461). 필요할 때 파일로 읽는 `PROCEDURE.md`는 치환되지 않으니 역할 id를 그대로. `team.json`: 노노 [lead, dev](직책 총괄), 리리 [dev, plan](개발), 코코 [art]. `PROJECT.md` 경로. 옛 팩은 `git mv`로 옮겨 이력에 남음. PD 채팅이 만들다 둔 빈 폴더 `roles/lead|plan|art` 정리.
- **확인**: 실제 데이터로 네 캐릭터 지침 묶음 렌더 — 풀리지 않은 매크로 0, 역할 글·직책 정상, 역할 없는 Yae Miko는 "…are 노노's".
- **테스트**: `test_team_roles`(실데이터: 기본 캐릭터가 delegate 팩을 가짐, 이름 비의존), `test_data_bootstrap`(배포 역할 `art`).

## 2026-09-30 — 카드·역할 팩 매크로 {{user}} {{char}} {{title}} {{default}} {{role:id}} (CARD_MACROS_v1, #461)

- **계기**: 운영자 제안("{user}{role}{title} 등의 플레이스홀더"). 확인해 보니 이미 버그 — 리리·코코·Yae Miko 카드에 SillyTavern식 `{{user}}`·`{{char}}`가 있는데 엔진이 치환하지 않아 **모델이 글자 그대로 받음**(Yae Miko는 description에 있어 매 턴). 또 역할 팩·엔진 문장이 "PD"·"staff" 같은 역할 이름을 박아 둬서 이름 바꾸기가 파일 여러 개 수정이 됨.
- **결정(운영자)**: `{{ }}` 이중 중괄호(SillyTavern·카드 표준 호환) + 팀 확장. 한 겹 `{user}`는 가져온 카드와 안 맞고 JSON·코드 예시와 겹쳐서 제외.
- **변경**: `characters.render_macros(text, cid, ws)` — `{{user}}`(그 캐릭터의 호칭, 없으면 기본 캐릭터의 것) `{{char}}`(이름) `{{title}}`(직책) `{{default}}`(기본 캐릭터 이름) `{{role:<id>}}`(그 역할 팩 제목), 대소문자·공백 허용, 못 푸는 건 그대로. 적용은 렌더링 세 곳뿐: 업무 묶음의 규칙 부분(헌장·로어·카드·역할 팩), 사적 묶음의 고정 부분, 위임 페르소나(`identity.persona_body`). 기억·스킬은 제외, 파일은 매크로 유지. 엔진 문장 중립화: 역할 없는 안내 "…are {{default}}'s", 위임 도구 설명·거절 문구에서 "PD"·"e.g. staff" 제거, 러너 관계 문장 "producer (PD)/staff member" → "delegated this work".
- **테스트**: `tests/test_card_macros.py` 6건, `test_worktree_runner` 문구.

## 2026-09-30 — 엔진 역할명 중립화: 기본 캐릭터 한 자리만 (engine/A, #460 — #456 인계)

- **경위**: 채팅에서 운영자 결정("이건 어디까지나 사용자 데이터고 엔진 코드는 이런 걸 몰라야해") → PD가 #456 위임. 시간 초과 → 경로 요청 → 리뷰 FAIL 2라운드(시도 1 소진) → 또 경로 요청으로 멈춤. 원인: "역할 이름 없이 누가 기본인가"가 정해지지 않아 작업자가 `"pd"`를 `"staff"`로 바꾸는 식으로 추측했고 리뷰가 매번 반려. 러너(`worktree_runner.py`)의 `"pd"`·`"staff"`는 티켓 범위 밖이라 손도 못 댐.
- **결정(아키텍처)**: 엔진이 아는 건 **기본 캐릭터**(`team.json` `default`) 한 자리. 없으면 가장 오래된 카드(옛 "pd 카드만 기본" 규칙 삭제).
- **변경**: `characters.expert_roles`(기본 캐릭터가 아닌 캐릭터들의 역할) → `delegation.experts()`. `workspace_status` 매 턴 카드 = 기본 캐릭터. `identity.seed_workspace_files` 새 설치 기본 캐릭터는 역할 `[]`(미리 만든 팩이 채움, 매니페스트 C3). 러너: 확인자 = 기본 캐릭터 페르소나·두뇌(`roster("default_character")`), 역할 없는 작업 = 첫 전문 역할(`WORKER_ROLE="staff"` 삭제; 앱은 항상 계획의 역할을 넘기므로 수동 CLI 실행에만 해당). 러너 1,500줄 상한 때문에 #459의 재실행 로직을 `accounts.rerun_on_switch`로 옮김.
- **현재 팀 동작 변화 없음**: 기본 노노[dev, pd] → 전문 역할 staff·dev·artist(전과 같음), 확인자 노노(전과 같음).
- **테스트**: `test_team_roles` 3건(자리≠이름, 명단 없을 때 가장 오래된 카드, **엔진 코드에 역할 이름 금지 가드**), 픽스처가 기본 캐릭터를 `team.json`으로 명시(`test_delegation`·`test_instructions_api`·`test_worktree_runner`·`test_identity`), `test_accounts` 재실행 3건.

## 2026-09-30 — agy 계정 전환 뒤 옛 계정 작업자·로그인 프로세스가 남음 (ACCOUNT_SWITCH_v1·LOGIN_BASELINE_v1, #459)

- **증상**: 13:06 agy 계정 전환 뒤 `/api/accounts`에 두 프로세스가 남음 — #456 위임 작업자(`agy -p`, 옛 계정, `stale`인데 `external`)와 상태 탭 로그인 TUI(pts/2, 새 계정, 로그인 완료 후에도 살아 있음). 앞의 것은 9/19 사고(옛 refresh token이 토큰 파일을 되돌려 씀)와 같은 위험.
- **원인**: ① 자동 재시작(`stale_owned`)은 서버가 직접 띄운 세션·standby만 봄 — 러너의 자식은 `external`. ② `account_login.complete()`가 성공을 표시하고 끝, 감시 스레드는 상태가 pending이 아니면 바로 빠져나가 아무도 CLI를 끝내지 않음. ③ 로그인 성공 판정이 "로그인돼 있음"이라 로그아웃 없이 전환하면 옛 로그인으로 즉시 성공.
- **변경(운영자 결정: 멈추고 새 계정으로 재실행)**: `accounts` — 부모가 `worktree_runner.py`면 `worker`, `stale_workers`·`stop_workers`(부모 재확인 후 SIGTERM). 서버 자동 재시작 루프와 [재시작] 버튼이 옛 계정 작업자도 멈춤. `worktree_runner.run_as_login` — 에이전트·리뷰어 실행 후 실패했고 그 사이 로그인이 바뀌었으면 같은 단계를 다시(최대 2번, 시도 안 씀; 로그인을 들고 있는 제공자만 = `accounts.RECYCLE_ON_LOGIN`). `account_login` — 시작 시점 로그인(이메일 + `login_fingerprint` = refresh token 해시, 시간당 갱신과 구별)을 기준으로 "새 로그인"만 성공, 모르면 CLI가 끝날 때만; `complete()` 성공 뒤 CLI 종료. 상태 탭 라벨 "위임 작업자". 제공자 문서 A48·A49.
- **남은 것**: 지금 돌고 있는 #456 러너는 옛 코드를 읽은 채라 재실행 기능이 없음 — 멈추면 그 시도는 실패로 기록됨.
- **테스트**: `test_accounts` 3건, `test_auto_recycle` 1건, `test_account_login` 3건, `test_worktree_runner.AccountSwitch` 4건.

## 2026-09-30 — 그림 관리: 빠진 그림을 PD에게 부탁 (ART_ASK_v1, am/E #458)

- **결정(운영자)**: [생성 요청]은 티켓을 직접 만들지 않고 입력창에 부탁 문장을 채움 — PD가 받아 티켓·위임(PD 모델, 티켓 증거는 대화 기록). 계획 §4.3에 기록.
- **변경**: `app-art.js` 아이콘·배경·표정 탭 아래 [빠진 그림 부탁하기] — 그 탭에서 자기 그림이 없는 칸(대체만 되는 칸 포함) 이름, `character-art` 스킬, §10 사양 한 줄(표정은 투명·지금 프레이밍·같은 캔버스, 배경은 인물 금지), 결과는 그 캐릭터 갤러리로. 모달을 닫고 `fillComposer`로 채움(보내기는 운영자). 사적 대화에선 버튼 없음. 빠진 게 없으면 알림만.
- **테스트**: `test_art_manager_page` 문장·빠진 것 없음·업무 대화 한정.

## 2026-09-30 — 그림 관리: SillyTavern 스프라이트 ZIP 팩 가져오기 (ART_PACK_v1, am/D #457)

- **변경**: `art_manager.pack` + `POST /api/characters/<id>/art/pack`(본문 = ZIP, `X-Framing` = bust/full). 파일 이름이 곧 표정 — `Joy.png`→`joy`, `joy-1.png`는 joy 두 번째 장, 모르는 이름(`smug`)은 그 캐릭터만의 표정. ZIP 안 폴더·`__MACOSX`·점 파일은 무시. 칸에 넣는 규칙은 갤러리 [표정으로]와 같은 `_place` 한 곳(캔버스 맞춤·WebP 상한·PNG 마스터·옛 그림 `_old/`). 팩을 고른 것이 승인이라 갤러리를 거치지 않음. 넣을 수 없는 파일(투명 아님·이름 불가·같은 이름 두 번·그림 아님)은 이유와 함께 건너뛰고 나머지는 반영. 상한: ZIP 100MB, 파일 200개, 풀었을 때 300MB. `server.py` 변경 없음(업로드 연결 줄이 이미 `art_manager.handle_upload`).
- **화면**: 표정 탭 아래 [ZIP 팩 가져오기 · 상반신/전신](지금 고른 프레이밍), 표정 탭에 ZIP을 끌어다 놓아도 됨. 결과 한 줄 "표정 N개 반영 · 건너뜀 M개: 파일 (이유)".
- **배포**: ⚡.
- **테스트**: `test_art_manager` 3건(이름·건너뜀·교체 보관, 잘못된 팩, 라우트), `test_art_manager_page` 결과 문장.

## 2026-09-29 — 병합은 됐는데 티켓이 열린 작업의 [승인] (MERGED_CLOSE_v1, #378)

- **증상**: 그림 카드 #371 [승인] → "ticket 371 has no delegated change awaiting a merge". 01:42 병합(fast-forward)은 됐지만 티켓을 닫기 전에 병합 작업권이 만료돼(`author lease expired`) 러너는 `merged-ticket-open`, 티켓은 `awaiting_merge`로 어긋남. 카드는 티켓을 보고 [승인]을 띄우고, 서버는 러너를 보고 거절.
- **변경**: `delegation.merge`가 `merged-ticket-open`이면 `_close_merged` — 러너가 남긴 병합 커밋이 main의 조상일 때만, 운영자 작업권(`merge_go`)으로 평소의 완료 관문(`release done`)을 거쳐 티켓을 닫음. 실패하면 작업권을 돌려놓아 원래 상태로.
- **배포**: ⚡.
- **테스트**: `test_delegation` 2건(닫힘, main에 없으면 거절).

## 2026-09-29 — HTTP 두뇌에 Edit·Glob·Skill, 도구 예산 업무 40 / 사적 8 (PARITY_TOOLS_v1, par/C–F #377)

- **변경**: `mcp_parity.py`(웹 도구처럼 서버 옆 모듈) — `edit_file`(Claude Edit 계약: 정확히 한 번 일치 또는 `replace_all`, 결과는 `write_file`과 같은 규칙으로 검사 — 규칙은 `mcp_server._write_refusal` 하나로 뽑음), `find_files`(허용 루트 안 glob, 비밀 이름·.git 제외, 200개 상한), `skill`(목록: 이름+설명(YAML `>`/`|` 포함), 로드: SKILL.md 본문+참조 파일 목록). `adapter_openai.tool_budget`: 업무 40·사적 8(D3 결정).
- **테스트**: `tests/test_mcp_parity_tools.py`, `test_tool_budget_wrapup`에 모드별 예산, `test_mcp_server` 도구 목록. `mcp_server.py` 900줄 가드 안(898).
- **배포**: ⚡.

## 2026-09-29 — HTTP 두뇌에 웹: MCP `web` 도구 (WEB_TOOL_v1, #376)

- **증상**: OpenRouter Space Bunny가 웹을 못 씀. CLI 두뇌는 웹 도구가 내장, HTTP 경로는 우리가 넘긴 MCP 도구(17개)뿐이고 웹이 없었음.
- **변경**: `web_tool.py` — `web {action: read|search}`. 백엔드는 agent-reach(이 호스트에서 웹을 제일 잘 쓰는 리서치 라우터)가 고른 키 없는 서비스를 CLI 없이 차용: 읽기 Jina Reader(실패하면 직접 가져와 본문 추출), 검색 Exa 공개 MCP(실패하면 DuckDuckGo lite — html 페이지는 이 IP에 캡차). `CHATBOT_WEB_READER`·`CHATBOT_WEB_SEARCH`로 교체·끄기. **공개 인터넷만**: 루프백·사설·링크로컬·tailnet 주소로 풀리는 호스트는 연결 전·리다이렉트마다 거절(사적 세션 기록 등 집 안 서비스 보호, 제3자 리더에도 넘기지 않음). **사적 세션에선 닫힘**(검색어로 사적 대화가 나가지 않게).
- **확인**: 실측 — Exa 검색 3건, Jina로 SillyTavern 문서 읽기, 127.0.0.1·localhost·100.x·file://·diskstation 거절.
- **배포**: ⚡(MCP 서버).
- **테스트**: `tests/test_web_tool.py`(오프라인: 가짜 DNS·응답), `test_mcp_server` 도구 목록에 `web`.

## 2026-09-29 — 그림 관리 모달 v0: 갤러리에서 골라 칸에 (ART_MANAGER_v1, am/B·am/C #375)

- **계기**: 코코가 위임으로 그린 그림(`characters/<노노>/gallery/nono-desk-01.png`, #371)을 볼 곳이 없었음. 그림을 직접 할당할 방법도 없음.
- **서버** `art_manager.py`: `GET /api/characters/<id>/art`(칸 목록 — 아이콘·배경·표정(bust/full), 각 칸이 자기 그림/대체된 이름/placeholder인지 — + 갤러리 + 형식 문제), `…/gallery/<파일>`, `POST …/art/assign`(갤러리 그림을 칸에: 종류별 캔버스에 맞춰 WebP 상한 이하로, PNG 마스터 보관, 옛 그림은 `_old/`; 표정은 투명 필수), `…/art/upload`(갤러리로), `…/art/remove`(칸의 그림을 갤러리로 되돌림). 삭제 없음. `server.py`는 기존 연결 줄에 붙이기만(+1줄).
- **화면** `app-art.js`·`art-manager.css`: 탭 갤러리·아이콘·배경·표정, 칸 배지(내 그림 / → 대체 이름 / 기본), 갤러리 카드의 [아이콘으로][배경으로][표정으로…], 올리기·끌어다 놓기, 반영하면 헤더 아바타·무대·스프라이트 다시 읽음. 여는 곳: 캐릭터 트레이 끝 [그림], 갤러리에 그린 작업 카드의 [갤러리].
- **배포**: ⚡.
- **테스트**: `tests/test_art_manager.py`(Pillow로 실제 변환), `tests/test_art_manager_page.py`.

## 2026-09-29 — 작업 결정 버튼은 누르면 바로, 말풍선 없이 (TICKET_BUTTONS_v1·FILL_COMPOSER_v1, #374)

- **증상**: 위임 카드 버튼이 입력창에 `/ticket …`만 채우고 보내기 버튼은 꺼진 채(값만 넣고 `updateSendButton`을 안 부름). 운영자: 바로 전송, 말풍선도 필요 없음.
- **변경**: `app-evolution.js::runTicketDecision` 하나로 — 작업 카드·개선 탭 행·입력창 위 티켓 바·선택지 칩이 모두 이 경로(전엔 세 벌 복사). 버튼은 즉시 결정하고 알림만, 입력창·말풍선 없음. [폐기](decline·discard)만 확인 창. [진행]은 지시문을 보통 메시지로 에이전트에게. [반려]·[계획 수정]은 입력창에 채우고 `fillComposer`로 보내기 버튼을 깨움(인용하기도 같은 함수). 손으로 친 `/ticket …`은 말풍선을 남김.
- **테스트**: `tests/test_ticket_buttons.py`, `test_observation_ui`를 새 결정으로(옛 "Enter가 결정" 고정 해제). 래칫 기준선 두 줄 하향(복사본 제거).

## 2026-09-29 — 그림은 이름으로 대체 (ART_NAMES_v1, crp/S2 #373)

- **결정**: 운영자가 SD1–SD4·AM1–AM4 모두 추천대로. 모달은 "적당히 붙여서 깎아보자".
- **변경**: `characters.art_file`이 SillyTavern 이름 규칙(표정 + `.`/`-` 접미사)을 거꾸로 읽어 대체 — `joy.giggle-2`→`joy.giggle`→`joy`→`neutral`→다른 프레이밍→placeholder, 두뇌 폴더(`sprites/bust/grok/`)가 먼저. 한 표정 여러 장(`joy`, `joy-1`)은 무작위 한 장. 무대는 장소: `stage.<이름>`→`stage`→(옛 `stage/<두뇌>` 읽기만)→placeholder. 라우트가 스프라이트에 `provider`, 무대에 `name`을 넘김. 데이터 표 없음.
- **배포**: ⚡ (서버 모듈).
- **테스트**: `test_character_art_fallback` 4건 추가.

## 2026-09-29 — 모바일에서 보내기를 눌러도 키보드가 안 내려감 (SEND_KEEPS_KEYBOARD_v1, #370)

- **증상**: 보내기를 누르면 가상 키보드가 내려갔다가 다시 올라옴 — 버튼이 입력창의 포커스를 가져가 키보드가 내려가고, `send()`가 입력창에 다시 포커스를 줌.
- **변경**: 보내기 버튼의 `pointerdown` 기본 동작을 막아 포커스가 입력창에 머묾(`#modelBtn`과 같은 방식). 전송은 그대로 `click`.
- **테스트**: `tests/test_send_keeps_keyboard.py`.

## 2026-09-29 — 부팅 커튼: 로딩 중 덜그럭거림 없이 한 번에 (BOOT_CURTAIN_v1, #368)

- **증상**: 로딩되면서 위젯이 덜그럭거림. `boot()`가 제공자→테마 색→캐릭터·아바타→모델→세션(기록, 사적 모드 버튼 숨김)→무대 순서로 페이지를 바꾸는데 그 과정이 전부 보였음. 무대는 기본 스튜디오 그림을 보여 주다 캐릭터 그림으로 바뀜.
- **변경**: `<html class="booting">`이면 body 투명(배치는 그대로라 측정 가능), `boot()`가 끝난 뒤 두 프레임 후 0.3초에 걸쳐 나타남, 멈춘 부팅이면 4초 뒤 강제로. `html` 바탕을 `--bg`로(흰 번쩍임 방지). 무대 층은 자기 그림이 로드된 뒤(`stage-ready`) 서서히.
- **테스트**: `tests/test_boot_curtain.py`.

## 2026-09-29 — 최적화 2: 코드 강조기는 코드 블록이 있을 때만 (HIGHLIGHT_LAZY_v1, #367)

- **측정**: `highlight.min.js` 125KB(gzip 42KB) — 페이지 스크립트의 1/6, 사적 대화에선 거의 안 씀.
- **변경**: 페이지에서 `<script>` 제거, `markdown.js::ensureHighlightLoaded`(mermaid와 같은 방식)가 첫 코드 블록 때 한 번 불러옴. 실패하면 다음 블록이 다시 시도. 미리보기 창(`artifacts.js`)도 같은 로더. 테마 CSS는 작아서 그대로.
- **테스트**: `tests/test_highlight_lazy.py`.

## 2026-09-29 — 최적화 1: 세션 동기화는 안전망만, JSON API 압축 (SYNC_THROTTLE_v1·API_GZIP_v1, #366)

- **측정**: 화면이 보이는 동안 2.5초마다 세션 전체(20–30KB, 무압축) + 세션 목록(15KB) + active를 받아 화면과 대조 — SSE가 멀쩡해도. 탭 하나 시간당 약 60MB. 서버 응답은 4–8ms라 병목은 전송·대조.
- **변경**: `app-session.js::syncDue` — 스트림이 닫혔으면 매 틱(전과 같음), 열려 있으면 30초마다, 작업 중 스트림이 10초 조용하면 즉시. 탭 복귀·SSE 재연결 때 동기화는 그대로. `server.py::_send`가 JSON 응답도 gzip 요청 시 압축(1KB 이상, `Vary`).
- **배포**: 서버 변경 ⚡ 필요(gzip). 페이지 쪽은 새로고침.
- **테스트**: `tests/test_sync_throttle.py`, `test_static_delivery`(JSON gzip 실서버).

## 2026-09-29 — 작성 중 흐르는 바가 말풍선 밖으로 안 나감 (FLOW_SWEEP_INSIDE_v1, #365)

- **증상**: 작성 중인 문단 위를 흐르는 1px 바(폭 38%)가 자기 폭의 −110%→280%로 움직여 문단 왼쪽 42% 앞에서 시작해 오른쪽 44% 밖에서 끝남 — 말풍선 옆면을 뚫음.
- **변경**: 0%→163%(38%×2.63=100%)로 문단 안에서만, 양 끝은 서서히 나타나고 사라짐.
- **테스트**: `tests/test_flow_sweep.py`(폭×이동량으로 양 끝이 문단 안인지).

## 2026-09-29 — 프라이빗 토글은 맨 왼쪽, 사적 모드에선 스킬·위치 버튼 없음 (PRIVATE_FIRST_v1, #364)

- **요청**: 모드 토글은 늘 있으니 가장 왼쪽으로. 사적 모드에선 `/act` 말고 의미 있는 게 없으니 스킬·위치 버튼 제거.
- **변경**: `#privateBtn`을 컴포저 맨 앞으로(마크업 + 폰 `order:0`). `body.private-session`에서 `#slashBtn`·`#geoBtn` 숨김(`chat-features.css`). `/` 입력 메뉴와 위치 동기화 자체는 그대로 — 켜 두었다면 사적 모드에서도 계속 보냄.
- **테스트**: `test_private_toggle` 갱신.

## 2026-09-29 — 중지하면 알림이 한 번만 (STOP_NOTICE_ONCE_v1, #363)

- **증상**: 중지 버튼을 누르면 "…의 요청으로 작업이 중지되었습니다."(서버 `stopped` 이벤트)와 "작업을 중지했습니다."(버튼 처리 코드)가 둘 다 뜸.
- **변경**: 서버 알림이 정본(모든 창·기록에 감). 버튼 쪽 알림은 1.5초 안에 `stopped` 이벤트가 안 오면(스트림 끊김)만 대신 띄움(`app-sse.js` `lastStopNoticeAt`).
- **테스트**: `tests/test_stop_notice.py`(실제 클릭 처리 코드를 node로).

## 2026-09-29 — 모델 버튼을 입력창 구석으로: 들어가면 이름, 좁으면 아이콘 (MODEL_TAG_v2, #362)

- **요청**: 폭이 줄면 긴 모델명이 입력창을 대부분 덮음. 왼쪽 모델 아이콘을 없애고, 좁을 때 그 아이콘이 뜨게.
- **변경**: 따로 있던 `#modelTag`를 없애고 `#modelBtn` 자체를 입력창 오른쪽 구석(첨부 버튼 왼쪽, 마지막 줄)으로 옮김 — 메뉴·접근성·단축키는 그대로. 빈 칸에서 이름이 입력창 폭의 35%를 넘으면 아이콘만(`icon-only`), 글을 치는 중·낮은 화면(`max-height:500px`)·폰 키보드가 열렸을 때도 아이콘. 키보드·낮은 화면에서 버튼을 숨기던 규칙은 제거(모델은 늘 바꿀 수 있음).
- **테스트**: `test_model_tag` 재작성, `test_model_picker` 갱신.
