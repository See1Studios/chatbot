# 설정집(세계 층) 계획

> 방향 (align/D, 2026-09-29): **핵심** — 동반자와 「어디서」 지내는지를 사용자가 쉽게 고치고 주고받는 층. 캐릭터 카드 위에 한 겹 더 붙는다

상태: `active` · W3a 조사 완료(2026-09-29), 결정 S1–S4 대기. 상위 설계: [private-mode.md §8.6](private-mode.md#rooms).

## 1. 무엇인가
- 카드가 「캐릭터 자체」라면 설정집은 「그 캐릭터와 지내는 세계」다: 업무 방을 무엇으로 부를지(사무실), 옆의 숨은 곳(비상계단·탕비실), 퇴근 후 장소, 장소별 텐션 속도·상한, 허용 행위 등급, 작은 사건, 이동 선택지 문구.
- 카드와 따로 만들고 따로 공유한다. 아무 카드나 아무 설정집에 넣을 수 있다. 카드는 어울리는 설정집을 추천만 한다.
- 관계(호감도, 현재 장소, 열린 장소, 사적 기억)는 설정집에 들어가지 않는다. 사적 저장소에만 있다.

## 2. 현재 코드 (2026-09-29)
| 항목 | 사실 | 근거 |
|---|---|---|
| 로어북 | 캐릭터별 `characters/<id>/lorebook.json`. ST·표준 형식을 정규화(`keys`/`key`, `order`·`insertion_order`→priority, `position` 0/1 → before/after_char) | `characters.normalize_lorebook`, `load_lorebook` |
| 매칭 | 최근 5개 메시지에서 키 부분 문자열(대소문자 무시) 또는 `constant`. 최대 3개, 항목당 500자. 보조 키·정규식·대소문자·책 단위 `scan_depth`·`token_budget`은 안 봄 | `instructions.match_lorebook_entries`, `LOREBOOK_*` |
| 삽입 | 지침 묶음에서 페르소나 앞(before_char)·뒤(after_char) | `instructions.lorebook_context` |
| 카드 | V2만 저장(`SPEC = "chara_card_v2"`). V3 JSON은 가져올 때 V2로 바꾼다 | `characters.py`, `tools/st_import.py convert_st_card` |
| 빈틈 1 | PNG는 `chara` 조각만 읽는다. V3 전용 `ccv3` 조각만 있는 PNG는 못 읽는다 | `tools/st_import.py extract_chara_raw` |
| 빈틈 2 | 가져오기가 카드 안의 `character_book`을 버린다(이름 붙은 필드만 옮김). 카드에 딸린 로어북이 사라진다 | `tools/st_import.py convert_st_card` |

## 3. 선행 사례
### 3.1 Character Card V3 (`chara_card_v3`, spec_version `3.0`)
출처: [SPEC_V3.md](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md)
- V2 위에 `nickname`, `creator_notes_multilingual`, `source`, `group_only_greetings`(그룹 채팅 전용 인사 — `ux/O`와 연결), `assets`(icon·background·emotion 등), `creation_date`·`modification_date`를 더한다.
- 로어북 객체: `name`, `description`, `scan_depth`, `token_budget`, `recursive_scanning`, `extensions`, `entries`. 항목: `keys`, `content`, `enabled`, `insertion_order`, `use_regex`, `constant`, `case_sensitive`, 선택으로 `name`·`id`·`comment`·`priority`·`selective`·`secondary_keys`·`position`.
- **데코레이터**: 항목 본문 맨 앞의 `@@이름 값` 줄. 발동(`@@activate_only_after`, `@@activate_only_every`, `@@dont_activate_after_match` 등), 위치(`@@depth`, `@@position`, `@@role`), 매칭(`@@additional_keys`, `@@exclude_keys`, `@@scan_depth`).
- 묶음 파일 **CHARX**: ZIP 안에 `card.json` + `assets/{type}/{category}/`. 배경·스프라이트를 카드와 함께 옮길 수 있다.
- 규칙: 모르는 필드는 무시하되 버리지 말고 다시 내보낼 때 보존한다. 앱 고유 데이터는 새 최상위 필드가 아니라 `extensions`에 둔다.

### 3.2 SillyTavern World Info
출처: [World Info 문서](https://docs.sillytavern.app/usage/core-concepts/worldinfo/), [저장소](https://github.com/SillyTavern/SillyTavern)(AGPL — 코드는 가져오지 않고 형식과 동작만 참고)
- 붙는 곳이 넷: 캐릭터 로어(카드에 묶임), 페르소나 로어, 채팅 로어(그 채팅만), 전역. 순서: 채팅 → 페르소나 → 캐릭터/전역.
- 항목의 추가 기능: 보조 키 논리(AND ANY/AND ALL/NOT ANY/NOT ALL), 발동 확률(%), 포함 그룹(여럿 중 하나만), 시간 효과(sticky·cooldown·delay), 캐릭터 필터, 깊이 삽입(@D), 재귀, 벡터 매칭, STscript 자동 실행.
- 전역 설정: 스캔 깊이, 예산(컨텍스트 %), 최소 발동 수, 재귀 단계, 대소문자, 단어 단위 매칭.

### 3.3 시장 (OpenRouter의 SillyTavern 앱 페이지)
- 페이지: [openrouter.ai/apps/sillytavern](https://openrouter.ai/apps/sillytavern). 모델별 순위는 브라우저에서 그려져서 자동으로 읽지 못했다. **운영자가 브라우저로 확인**해야 한다.
- 제3자 스냅숏(2026-08-24, [CodeSOTA](https://www.codesota.com/agentic/openrouter-apps/sillytavern)): 30일 131억 토큰, 69.1만 요청. 모델별 분포는 없음.
- 쓰는 곳: 기본 두뇌 추천, 설정집 지침이 어떤 모델 계열에서 잘 따라지는지 시험할 대상 고르기.

## 4. 판단: 따를 것 / 늘릴 것 / 미룰 것
| 구분 | 내용 | 이유 |
|---|---|---|
| **따른다** | 설정집의 그릇은 **CCv3 로어북 객체**(`name`·`description`·`scan_depth`·`token_budget`·`recursive_scanning`·`entries`·`extensions`), 항목 필드는 CCv3 이름 그대로 | ST·RisuAI에서 그대로 열린다. 공유 생태계와 통한다 |
| **따른다** | 모르는 필드 보존, 앱 고유 데이터는 `extensions`에만 | 명세 규칙. 다른 앱을 거쳐 와도 PE 데이터가 살아남는다 |
| **늘린다** | `extensions.pe_pack`에 장소·거리·공개도·텐션 조정·허용 행위 등급·체류 턴·열림 조건·작은 사건·이동 선택지 문구 | 로어북에는 「장소」라는 개념이 없다 |
| **늘린다** | 장소 설명은 평범한 로어 항목(장소 이름이 키)으로도 넣는다 | **다른 앱에서 열면 평범한 로어북, PE에서 열면 세계**가 된다 |
| **미룬다** | 데코레이터 일부(`@@activate_only_after`, `@@dont_activate_after_match`), 발동 확률, 포함 그룹 | 작은 사건(「누가 지나간다」)의 무작위성에 쓸 만하다. W3b 이후 |
| **미룬다** | CHARX 묶음(장소 배경 이미지 동봉) | 배경은 처음에 공통 이미지로 시작한다(private-mode §8.6) |
| **버린다** | 벡터 매칭, STscript 자동 실행, 아웃렛 매크로 | ST 고유 실행 환경에 묶여 있다 |

### 4.1 형식 초안
```json
{
  "name": "사무실",
  "description": "기본 설정집: 모든 캐릭터가 함께 지내는 사무실과 그 주변",
  "scan_depth": 5,
  "token_budget": 800,
  "recursive_scanning": false,
  "entries": [
    {"keys": ["비상계단", "계단실"], "content": "사무실 옆 비상계단. 인적이 드물지만 가끔 발소리가 울린다.",
     "enabled": true, "insertion_order": 10, "constant": false}
  ],
  "extensions": {
    "pe_pack": {
      "version": 1,
      "work_room": {"name": "사무실", "publicness": 3},
      "places": [
        {"id": "stairwell", "name": "비상계단", "distance": "office_hidden", "publicness": 1,
         "mood": "숨죽인 긴장, 들킬 것 같은 공기",
         "tension": {"rate": 1.5, "cap": 2}, "action_tier_max": 2, "stay_turns": 6,
         "unlock": {"affection_lv": 1}, "background": "stairwell", "events": ["아래층에서 발소리가 올라온다"]}
      ]
    }
  }
}
```
- `distance`: `office` · `office_hidden` · `after_work`(private-mode §8.6 표). `publicness` 0–3.
- `tension.cap`은 현행 4단계 기준이다. 8단계 채택(private-mode D1) 시 재매핑한다.
- `action_tier_max`는 W3b의 행위 등급표(아직 없음)를 가리킨다.

## 5. 결정 필요
| # | 질문 | 추천 |
|---|---|---|
| S1 | 설정집 그릇: CCv3 로어북 + `extensions.pe_pack` vs PE 전용 형식 | **CCv3 로어북**(§4) |
| S2 | 붙는 곳: 인스턴스 전체에 활성 설정집 하나(공용 사무실) vs 캐릭터별 | **인스턴스 하나**. 사무실은 모든 캐릭터의 공용 공간(private-mode §8.3). 캐릭터별 로어북은 지금처럼 따로 둔다 |
| S3 | 가져오기 빈틈 2개(§2)를 먼저 메울지 | **먼저**. 작고, 사용자가 받아 오는 카드의 로어북이 조용히 사라지는 문제다 |
| S4 | 로어 매칭을 CCv3 수준(보조 키, 대소문자, 책 단위 scan_depth·token_budget)으로 올릴지 | 설정집 구현(sp/C) 때 함께. 지금 3개·500자 상한은 설정집 예산과 다시 맞춘다 |

## 6. 항목
| id | 작업 | 수용 기준 | 의존 | 상태 |
|---|---|---|---|---|
| `sp/A` | 이 문서(W3a 조사) | 커밋 | — | ✅ |
| `sp/B` | 가져오기 빈틈: PNG `ccv3` 조각 읽기, 카드의 `character_book` → `lorebook.json` | V3 전용 PNG가 가져와짐. 로어북 달린 카드를 가져오면 로어북이 남음(테스트) | S3 | 대기 |
| `sp/C` | 설정집 형식 검사·가져오기·내보내기(W3a 구현) | 잘못된 설정집은 짧은 오류로 거절. 내보낸 파일에 사적 저장소 키 없음. 모르는 필드가 왕복 후 보존됨 | S1, S2 | 대기 |
| `sp/D` | 기본 설정집 「사무실」 | 엔진이 제공, 장소 5개 안팎(사무실 안 숨은 곳 + 퇴근 후) | sp/C | 대기 |
| `sp/E` | 카드 기반 자동 생성 초안(W3c) | 생성 결과가 sp/C 검사를 통과해야 저장. 입력에 사적 저장소 없음 | sp/C | 대기 |
| `sp/F` | OpenRouter ST 페이지 모델 순위 확인(운영자, 브라우저) | 상위 모델 목록을 §3.3에 기록 | — | 대기 |
