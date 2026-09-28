# 사적 모드 계획 (SSOT)

> 방향 (align/D, 2026-09-28): **핵심** — 사적 관계는 공개 얼굴 안의 한 축(옵션)이자 「하루를 같이 사는」 경험의 절반

5개 문서(액션·텐션 4단계·텐션 8단계·호감도·HUD)를 합친 단일 문서(#213, 2026-09-26). 코드가 정본이다. 문서와 코드가 다르면 코드를 따르고 §6에 적는다.
호칭: 사용자 = 운영자(표시 이름은 페르소나 값, 규칙 주어로 쓰지 않음). 캐릭터 이름은 예시일 뿐이다.

<a id="status"></a>
## 0. 상태

| § | 내용 | 상태 | 근거(코드·테스트) |
|---|---|---|---|
| 1 | 액션·표정·속마음·선택지 파싱, `/act`, 렌더 계약 | **구현됨** | `static/markdown.js` `parseExpression`·`parseThought`·`postProcessAssistant`, `private_engine.RENDER_PROTOCOL`, `tests/test_private_tension.py` `test_render_protocol`·`test_private_instruction_bundle_includes_render_protocol` |
| 1 | 선택지·액션을 본문 밖 채널로 | 별도 문서 | [out-of-band-choices-actions.md](out-of-band-choices-actions.md) (`choices` 도구 #145, `action` 이벤트 — `test_choices_tool.py`, `test_an_explicit_action_event_reaches_the_engine`) |
| 2 | 텐션 4단계 엔진(stage 1–4, 3슬롯, recent_choices, 모델 계열별 표) | **구현됨** | `private_engine.py` `tension_after`·`tension_step`·`tension_context`, `session.py::AgentSession._send_direct`, `data/private_tension_*.json`, `tests/test_private_tension.py` |
| 2 | 선택지 상투성 검증·필터 | 계획 | 코드 없음 |
| 2 | 8단계 0–100 점수 엔진 | **초안** | 코드 없음, 승인 대기 |
| 3 | 영구 호감도 | 일부 구현 | 선물로만 증감(`gifts.py`, #336). 대화 기반 증감·시작 텐션 연동(§3.6-2)은 아직 |
| 4 | HUD·UX | 계획 | 코드 없음(`privateHud` 없음) |
| 5 | 렌더러 코어 + 모드별 데코레이터 | 계획 | 신규 설계 |

<a id="action"></a>
## 1. 액션·동적 선택지

목적: 행위(스킨십·동작·연출)를 타이핑 없이 고르고, 말풍선과 지문을 분리하고, 다음 턴에도 감정선·물리 상태가 이어지게 한다.

### 1.1 표시 vs 컨텍스트

| 구분 | 컨텍스트(모델이 보는 기록) | 화면 |
|---|---|---|
| 사용자 말 | `"오늘 힘들었어"` | 사용자 말풍선 |
| 사용자 액션 | `(머리를 쓰다듬는다)` 또는 `type: action` 이벤트 | 말풍선 없음, 은은한 지문 |
| 캐릭터 액션 | `*얼굴을 붉힌다*` | 나레이션 지문(이탤릭 의도 — 현재 스타일 없음, §5) |
| 캐릭터 대사 | `"..."` | 메인 말풍선 |
| 속마음 | ` ```thought ` 펜스(파서는 `<thought>`도 수용) | 접이식 `.thought-box` |
| 표정 | 첫 줄 `[expression: neutral\|joy\|shy\|serious\|sorrow\|tired]` | `.exp-badge` |

### 1.2 렌더 계약 (구현: `RENDER_PROTOCOL`, 사적 지침 묶음에 포함)
- 행동·시선·몸짓은 `*...*`, 발화는 `"..."`. 1–2문장, 소설체·메타 발언 금지.
- 표정 태그는 맨 앞, 속마음은 ` ```thought ` 블록.
- 매 답 끝에 `<!--choices: 라벨 -> "대사" | 라벨 -> (행동) | 라벨 -> "대사" (행동)-->` 2–4개. 대사형·행동형·혼합형을 상황에 맞게 섞는다.
- 사용자가 행동 선택지를 누르면 말풍선 없이 `(행동)`이 주입된다(`/act`).

### 1.3 단계
| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | `->` 파싱, 표정 뱃지, 속마음 토글, `/act` (#130) | 구현됨 |
| 2 | 사적 지침·카드에 행위 지시문·예측 선택지 규칙 주입 | 구현됨(#164 `RENDER_PROTOCOL`) |
| 3 | 선택지·액션을 `choices` 도구·`action` 이벤트로, 기록·요약 시 액션 상태 보존 | [out-of-band-choices-actions.md](out-of-band-choices-actions.md)로 대체 |
| — | 실사용 테스트·지문/대사 티키타카 품질 튜닝 | 계획 |

<a id="tension"></a>
## 2. 텐션 엔진

문제: 선택지가 1턴 수준(쓰다듬기·안아주기)에서 맴돌고, 거리감의 단계 추적이 없고, 선택지 온도차가 없다.

### 2.1 현행 4단계 vs 8단계 초안

| 항목 | 현행 (구현됨, `private_engine.py`) | 8단계 초안 (2026-09-26, PD 입안) |
|---|---|---|
| 상태 | `tension_stage` 정수 1–4, 세션 `meta.json` 저장 | `tension_score` 0–100 + `tension_phase` 0–7 |
| 단계 이름 | 계열별 데이터: defaults `도입/교감/친밀/깊은 유대`, gemini `도입/고조/밀착/절정` | 정적 0–9 · 감응 10–24 · 접촉 25–39 · 고조 40–54 · 심화 55–69 · 고원 70–84 · 돌파/결합 85–94 · 절정·여운 95–100 |
| 슬롯 | 3슬롯: 0 유지 / 1 +1 / 2 +2 (라벨·가이드는 JSON) | Slot1 +1~3 / Slot2 +5~8 / Slot3 +10~15 |
| 액션 입력 | `(…)` 또는 `type: action` → +1 | +5 |
| 일반 대화 | 유지 | +0 |
| 하강 | 없음(클램프만) | 없음 |
| 제동 | 없음 — 슬롯 2를 두 번 누르면 1→4 | T<40에서 턴당 +12 상한 → 최소 4–6턴 빌드업 |
| 행위 허용 | 단계 이름·분위기 문장만 | 페이즈별 허용 행위, 도구/자세는 페이즈 0–3 절대 금지, 4 자세 전환, 5 소품 준비, 6 전면 해금, 7 피니시·후희 |
| 최근 선택지 | `recent_choices` 최대 9개, 중복 제거 | 동일(반복 금지 줄) |
| 컨텍스트 | `[Tension Engine Context]` Stage n/4 + 분위기 + 반복 금지 + 3슬롯 계약(`tension_context`) | `Phase p/7 [Score s/100]` + 분위기 + 제약 규칙 + 슬롯별 목표 점수 |
| 계열별 표 | `FAMILY_FILES`(gemini만 자체 표), 없으면 defaults | 두 JSON 모두 8페이즈로 갱신 |
| 파일 | `private_engine.py`, `engine_data/private_tension_{defaults,gemini}.json`, `session.py`, `tests/test_private_tension.py` | 같음 |

충돌은 풀지 않는다 → §6 D1–D4.

### 2.2 원래 4단계 계획 중 코드와 다른 부분 (보존)
- 슬롯 성격: A 밀당/장난(유지·튕기기) · B 반 발짝 전진 · C 직진/도발(다음 단계로). 현 코드 슬롯은 "유지·전진·깊은 교감"으로 밀당 슬롯이 없다.
- 밀당/화제전환 선택이나 긴 쉼 → 단계 유지 또는 완만한 완화. 현 코드엔 완화가 없다.
- 선택지 검증: 상투적 선택지면 경고·필터(미구현). 반복 금지 창은 원안 "최근 3턴", 코드는 최대 9개.
- 카드 동기화: 캐릭터 카드 사적 지침에 슬롯 규격 반영(현재는 공통 `RENDER_PROTOCOL`+JSON이 담당).

<a id="affection"></a>
## 3. 영구 호감도

> 관련(설계): 진행·약속·선호·금기 등 **서술형 관계 연속**은 [character-memory-adapter.md](character-memory-adapter.md). 본 절 호감도·텐션 수치 엔진과 중복 설계하지 않는다.

목적: 세션 텐션은 새 세션마다 초기화된다. 캐릭터별 누적 유대를 정량 저장해 첫 인사 톤·시작 텐션·속마음 개방도·특별 상호작용을 해금한다. 노가다 없이 대화만으로 서서히 성장.

### 3.1 등급
| Lv | 관계 | pt | 시작 텐션 | 반응 | 해금 |
|---|---|---|---|---|---|
| 1 | 어색한 동료 | 0–19 | Stage 1 | 정중, 터치에 경계 | 기본 대화 |
| 2 | 친밀한 파트너 | 20–49 | Stage 1 | 가벼운 장난·접촉 호의 | 가벼운 스킨십 지문 |
| 3 | 특별한 호감 | 50–79 | Stage 2 | 시작부터 긴장감, 솔직한 속마음 | Stage 2 직행, 질투/애교 |
| 4 | 깊은 연인 | 80–99 | Stage 2–3 | 경계 0, 적극 호응 | 농밀한 슬롯 우선, 전용 애칭 |
| 5 | 완전한 유대 | 100 | Stage 3 | 무조건적 신뢰, 독점욕 | 히든 선택지·전용 지문 |

### 3.2 저장
- `characters/<id>/state.json` 또는 `card.json` `extensions.chatbot.private.affection`(§6 D6). Git 비추적, `private-memory.md` 옆.
- 스키마: `{"affection": {"points", "level", "title", "interactions_count", "last_updated", "milestones": []}}`. 세션 종료 시 원자적 저장.

### 3.3 성향(disposition) — `card.json` `extensions.chatbot.disposition`
같은 행동이 성향에 따라 +/−로 갈린다(예: 벽으로 밀치기 — 신중형 −3, 대담형 +2, 순종형 +3; 일 칭찬 — 신중형 +3, 대담형 −1; 볼 꼬집기 — 신중형 −2, 대담형 +2, 순종형 −1).

| 키 | 형태 | 뜻 |
|---|---|---|
| `traits` | 문자열 목록 | 성향 태그 |
| `axes` | pace·expression·initiative·boundary·focus, −1.0~+1.0 | 템포·표현·주도권·거리감·갈망 |
| `sensual` | libido 0–1, dynamics −1(순종)~+1(지배), kiss_intensity 0–1 | 사적 무드 역학 |
| `erogenous_zones` | 부위 → {sensitivity, reaction} | 민감 부위 반응 |
| `kinks` / `taboos` | {tag, desc, weight ±} | 선호(+) / 기피(−) |
| `triggers` | 이름 → {delta, reason} | 직접 증감(예: craft_praise +3, patient_waiting +2, abrupt_skinship −3) |

### 3.4 증감·반응
- 모델이 매 턴 `[affection: ±N, tag]`(또는 `[affection: 0]`)을 낸다. UI는 숨기고 게이지 `+N/−N` 애니메이션.
- 상승: joy/shy 표정, 속마음 개방, 더 과감한 선택지. 하락: serious/sorrow/tired, 물러나는 지문, 방어적 선택지.
- 누적 감점이면 레벨 강등 가능. 사과·배려 행동에 회복 보너스 +2.
- 고단계(Stage 3–4)에서만 `erogenous_zones`·`kinks`를 JIT 주입(신체 반응 지문, 슬롯 3 탐닉 선택지). Stage 1–2는 축 기반 태도 1–2줄만(토큰 절약). 수치(−1.0~1.0)는 노출하지 않고 자연어 1–2줄로 합성(Chub Lorebook·BetterSimTracker 방식).

### 3.5 흐름
세션 시작 → 호감도 로드 → Lv로 `base_stage`·태도 결정 → `[Affection & Disposition Context]` 주입 → 턴마다 텐션 상승, Stage 3+에서 부위·취향 활성화 → 세션 종료 시 포인트 정산·저장.

### 3.6 단계
1. 백엔드: `state.json` 읽기/쓰기, 계산 함수, 텐션 컨텍스트에 결합 (`characters.py`, `private_engine.py`).
2. 세션 연동: 시작 시 기본 텐션 로드, 턴·종료 시 정산 (`session.py`).
3. UI: 상단 하트/레벨 뱃지, 시작 분위기 문구, 레벨업 토스트(§4).

<a id="hud"></a>
## 4. HUD·UX

원칙: 하단(입력창·선택지)은 건드리지 않는다. 상단 메타 바 아래 34px 고정 미니 HUD, 평소 반투명 글래스, 행동 직후 1.5초 임팩트 토스트, 상세는 탭하면 드로어로. 사적 모드에서만 보이고 업무 모드는 `display:none`. CSS 변수(`--accent`, `--panel-bg`, `--border`) 재사용.

### 4.1 와이어프레임
```text
| [Hub ←] (Avatar) 캐릭터 (모델)                           [대화] [세션] ... |
| [이전] [다음]  20260925-01  [● 실시간 대기]                               |
| [♥ Lv.3 밀착 ■■■■■■■□□□ 78%] [💓 128 bpm] [😳 홍조 3] [🛡️ 경계 12%] [ℹ▼] | #privateHud
|      ⚡ [약점 저격: 귓불 (+20) | 주도권: 사용자 장악] (1.5초 후 사라짐)       | #hudImpactToast
| (대화 #log)                                                               |
```
```text
| 현재 심리 & 공략 현황                                            [닫기 ✕] |
| [영구 호감도] Lv.2 친밀한 파트너 (45/50pt) ■■■■■■■■□□                     |
| [심리 상태]  "완전히 녹아내려 순종함", "칭찬에 가슴이 뻐근함"              |
| [무장해제율] 경계심 12%                                                   |
| 5대 축: 템포 ◀●────▶ (-0.6) … (axes 5개, 양 끝 라벨 §3.3)                 |
| 부위 지도: 귀 ★★★ 공략 완료 / 목덜미 ★★☆ / 손목 ★☆☆ / 허리 ❓ LOCKED / 쇄골 ★★☆ 부분 발견 |
```

### 4.2 지표
| 지표 | 규칙 |
|---|---|
| 텐션 게이지 | Lv1 0–25% `#38bdf8` · Lv2 26–50% `#a3e635` · Lv3 51–75% `#fbbf24` · Lv4 76–100% `#f43f5e` |
| 심박 | 65–80 초록 완만 · 90–115 주황 · 120–150+ 빨강 격렬 |
| 홍조 | N0 평온 · N1 뺨 · N2 볼·콧등 · N3 귀·목덜미 · N4 온몸·눈물 |
| 경계심 | 100%에서 시작해 호감 행동·약점 공략으로 감소, 20% 이하 "무방비" |

### 4.3 임팩트 토스트
| 유형 | 조건 | 예 | 스타일 |
|---|---|---|---|
| critical | 지정 부위 자극 | `💥 약점 공략: 귓불 (+20)` | 골드 테두리 + 로즈 글로우 |
| resonance | kink 일치 | `✨ 취향 저격: 다정한 칭찬 / 호감도 +3` | 라임/에메랄드 펄스 |
| taboo | taboo·급발진 | `⚠️ 당황: 서두른 접촉 / 경계심 +15` | 연한 앰버/그레이 |
| dynamics | 주도권·거리감 변화 | `👑 저항감 0% 돌파` | 네온 바이올렛 |

### 4.4 데이터 (`private_hud`)
`enabled`, `character_id`, `tension{level,name,percent,color}`, `vital{bpm, blush{level,label}, resistance_percent}`, `affection{level,title,points,next_level_points}`, `mindset[]`, `last_impact{type,summary,timestamp}`, `axes{5}`, `zones[{id,name,sensitivity,status: revealed|partial|locked,hit_count}]`.

### 4.5 모바일
HUD 최소 높이 34px. 드로어는 로그 영역 탭 또는 `✕`로 닫힌다.

<a id="render"></a>
## 5. 렌더링

### 5.1 현재 사실
| 사실 | 위치 |
|---|---|
| `renderMarkdown()`은 두 모드 공용, 모드 분기 없음 | `static/markdown.js` |
| `postProcessAssistant()`가 사적 전용(표정 뱃지, 속마음 박스)을 하드코딩, 업무용(`highlightCodeIn`, `renderMermaidIn`)은 모든 모드에서 실행 | `static/markdown.js::postProcessAssistant` |
| 모드 신호: `body.private-session` 토글 | `static/app-session.js::enterSession` |
| 사적 CSS는 두 줄뿐(`.meta`, `#input` 색) | `static/chat-features.css` (`body.private-session`) |
| `RENDER_PROTOCOL`은 행동 `*이탤릭*`, 대사 `"따옴표"`를 요구하나 `.md em` 스타일이 없고 한글 폰트엔 진짜 이탤릭이 없어 모바일에서 지문과 대사가 똑같이 보임 | `private_engine.py::RENDER_PROTOCOL` |

### 5.2 설계
- 공용 코어 하나 + 모드별 데코레이터: `registerDecorator({id, modes, run(node, raw, isFinal)})`.
- `postProcessAssistant`는 현재 모드를 **한 곳**에서 읽어 해당 데코레이터만 실행.
- 파일: `static/render-work.js`(highlight, mermaid), `static/render-private.js`(expression, thought, 이후 나레이션·HUD).
- 사적 스타일은 전부 `body.private-session` 아래로 스코프. 프로바이더 이름 금지.

### 5.3 단계 (단계당 티켓 1개)
| 단계 | 내용 |
|---|---|
| R1 | 레지스트리 + 기존 expression/thought/highlight/mermaid를 데코레이터로 이동. 동작 변화 0, 테스트 포함 |
| R2 | 나레이션/대사 스타일: `em` 흐리게·작게, 따옴표 대사 선택적 span 래핑(색은 사적 CSS에서만) |
| R3 | HUD/게이지 훅을 §4 데이터에 연결 |

### 5.4 위험
- 스트리밍 재렌더에서 데코레이터가 멱등이어야 한다(뱃지·박스 중복 금지 — 현 코드는 querySelector로 재사용).
- 세션 전환 시 데코레이터 재적용.
- 업무 모드 출력 불변.

<a id="decisions"></a>
## 6. 결정 필요

| # | 충돌·질문 | 출처 |
|---|---|---|
| D1 | 텐션 모델: 현행 4단계 정수 vs 8단계 0–100. 채택 시 `tension_stage` 저장값 이관 방법 | §2.1 |
| D2 | 제동: 현행은 슬롯 2 두 번으로 1→4. 8단계 초안의 상한(+12/턴, T<40)을 4단계에도 둘지 | §2.1 |
| D3 | 슬롯 성격: 원안 "밀당/전진/도발" vs 코드 "유지/전진/깊은 교감". 밀당(튕기기) 슬롯 필요 여부 | §2.2, `data/private_tension_*.json` |
| D4 | 완화: 원안은 밀당·화제전환·긴 쉼 시 완만한 하강, 코드·8단계 초안 모두 하강 없음 | §2.2 |
| D5 | 단계 이름이 문서마다 다름(워밍업/의식/고조/클라이맥스 · 도입/고조/밀착/절정 · 도입/교감/친밀/깊은 유대). 코드는 계열별 JSON이 정본. 호감도·HUD는 gemini 이름을 전제 | JSON, §3.1, §4.2 |
| D6 | 호감도 저장 위치: `state.json` vs `card.json` 확장 | §3.2 — **결정 2026-09-28: `characters/<id>/state.json`** (카드는 공유 가능, 관계는 아님. composer-plus-menu 진행 때 추천안) |
| D7 | 호감도 Lv별 시작 Stage(1–3)는 4단계 전제. 8단계 채택 시 시작 점수로 재매핑 필요 | §3.1 |
| D8 | 호감도 판정을 모델의 자기 신고 태그 `[affection: ±N]`에 맡길지(검증·상한 없음), 파싱·숨김 위치 | §3.4 — **선물은 결정: 엔진 판정표**(`engine_data/affection.json`, composer-plus-menu D5). 대화 기반 증감의 방식은 여전히 열림 |
| D9 | HUD 바이탈(bpm·홍조·경계심·mindset·zones status)을 누가 계산하는지 없음. 모델 태그인지 엔진 계산인지 | §4.2, §4.4 |
| D10 | HUD 예시 불일치: 78%는 Lv4 구간(76–100)인데 "Lv.3 밀착"; 바는 ♥Lv.3, 드로어는 호감도 Lv.2; 토스트 `+20`의 단위 불명(호감도 증감은 ±3 규모) | §4 |
| D11 | 호감도 원안은 "대화 수 누적이 아니다"라면서 `interactions_count`를 둔다 — 용도 미정 | §3.2 |
| D12 | 4단계 원안의 recent_choices "최근 3턴" vs 코드 최대 9개 | §2.2 |

<a id="roadmap"></a>
## 7. 로드맵

1. R1 렌더 레지스트리(동작 변화 0) — §5.
2. R2 지문/대사 스타일 — §5.
3. 액션·선택지 품질 튜닝(실사용) — §1.3.
4. D1–D5 결정(텐션 모델·제동·슬롯·완화·이름).
5. 텐션 변경 구현(결정된 모델, 제동, 선택지 상투성 검증) — §2.
6. D6–D8 결정 후 호감도 1단계(백엔드) → 2단계(세션 연동) — §3.6.
7. D9–D10 결정 후 HUD 데이터 산출 — §4.4.
8. R3 HUD·게이지 렌더 + 호감도 UI(뱃지·토스트) — §4, §3.6-3.
