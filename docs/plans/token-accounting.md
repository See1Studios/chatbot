# 토큰 집계 (창 점유 vs 과금)

## 두 숫자

| 이름 | 식 | 쓰는 곳 |
|---|---|---|
| **창 점유 (occupancy)** | 마지막 턴 `input_tokens` | 로테이트 `weight`, 배지 "창" |
| **과금 (billed)** | 각 턴 `total_tokens`의 **합** | 배지 툴팁, 로그 "세션 누계" |

`total_tokens` ≈ 그 요청의 `input + output`. 캐시 카운터를 입력에서 빼지 않는다.
agy 실측: 첫 턴 input ~75k, `cache_read` 수백만 — 부분집합이 아님.

합산한 `total_tokens`를 "지금 창 크기"로 쓰면 안 된다. 마지막 `total`도 출력까지
포함하므로 점유는 `input_tokens`다.

## 세션 처음 vs 매 턴 (실측 중앙값, 2026-09-19)

| 프로바이더 | 첫 턴 input (시작 세금) | 이후 턴 input (매 턴) |
|---|---|---|
| claude | ~11k | ~9k |
| grok | ~46k | ~49k |
| agy (2026-09-19 구세션) | ~75k | ~119k |
| agy (2026-09-25 실측) | ~15k (probe) / ~17k (실세션) | ~25k–35k (최근 중앙값) |
| codex | ~23–33k | 들쭉날쭉. 짧은 턴 수백~1.6만, 도구 턴 10만~, 최장 세션 마지막 1.9M |
| omniroute | 짧은 인사 ~0.7k (시스템만). 도구 켠 실세션 첫 턴 ~128k | 매 HTTP 요청이 시스템+도구+히스토리 전량. 툴 홉은 요청이 하나 더 |

시작 세금에 들어가는 것 (한 번 깔리고, CLI가 대화를 이어가면 캐시될 수 있음):
- `AGENTS.md` + `PERSONA.md` + 스킬 색인 (호스트가 조립하는 지침 묶음, `instructions.py`, 약 6KB)
- MCP 도구 스키마
- 스킬 카탈로그 가설은 **기각** (2026-09-19 A/B). 호스트와 같은 spawn
  (`stream-json` + ADD_DIRS + 모델)에서 `--disable-slash-commands`는
  첫 턴 input 45970 vs 45961 (차이 9, 노이즈). `--print` 모드도
  45966 vs 45974. 현재 시작 세금은 **~46k이고 슬래시/스킬 펼침이 아님**.
- **claude ~11k와의 잔여 차(~35k) 원인 규명 완료** (2026-09-25 실측):
  - 2026-09-19 당시 ~46k의 주원인은 `static/vendor/mermaid.min.js`(3.2M) 유입이었으며, `static/` 제외 시 즉시 46k → 14k로 급감함(잔여 ~35k 격차는 static 제외로 사실상 해소됨).
  - 2026-09-25 성분 분리 실측 (`gemini-3.8-flash-low`, stream-json, 단문 인사 1턴):
    * **순정 agy 기본값** (add-dir 없음, MCP 없음): **11,898 tokens** (claude 기본 ~11k와 실질적으로 동일).
    * **MCP 도구 스키마** (`nas` 17개 도구 스키마): **+1,869 tokens** (11,898 → 13,767).
    * **ADD_DIRS `/chat`**: **~0 tokens** (13,760, 노이즈 범위 차이 없음).
    * **ADD_DIRS `WORKSPACE` (또는 하위 폴더)**: **+1,187 tokens** (13,760 → 14,947).
      하위 폴더(`characters`, `roles`, `memory`, `tools`, `skill-observations`, `.agents`, `.gemini`)를 개별 추가해도 동일하게 14,949~14,959로 일괄 ~1.19k 증가 (동일 git 저장소 메타데이터가 공통 유입됨). 반면 외부 빈 폴더(`/tmp/empty`) 추가 시 13,776(+16)으로 영향 없음.
    * **호스트 실세션 첫 턴**: 호스트 지침 번들(`AGENTS.md` + `PERSONA.md` 등 약 6KB) 인젝션이 더해져 **~17k** (2026-09-25 실세션 24건 중앙값 16,987, 최소 16,418).
  - 결론: agy 자체의 시스템 프롬프트는 claude와 사실상 같고, 호스트 기준선(~15k)과의 차이는 MCP 스키마(~1.8k) 및 git repo add-dir(~1.2k)뿐임. 과거 역사 세션 중앙값(~75k)은 `static/` 누수 및 긴 도구 히스토리가 누적된 수치임.
- `ADD_DIRS` (ROOT + `/chat`). 2026-09-16에 ROOT 통째가 첫 턴을 불리지 않음을
  측정함. 세션 폴더를 빼는 실험은 아직 안 함.

### 2026-09-25 agy 시작 세금 성분별 실측 (gemini-3.8-flash-low, 단문 인사 1턴)

| 구성 | 첫 턴 input (tokens) | 증감 (diff) | 비고 |
|---|---|---|---|
| 순정 agy (add-dir 없음, MCP 없음) | 11,898 | 기준선 | claude 기본(~11k)과 사실상 동등 |
| + MCP 도구 스키마 (`nas` lazy 17개) | 13,767 | +1,869 | `call_mcp_tool` 및 tool definition |
| + ADD_DIRS `/chat` | 13,760 | -7 | 노이즈 범위 (영향 없음) |
| + ADD_DIRS `WORKSPACE` (전체) | 14,947 | +1,187 | git 저장소 메타데이터 유입 |
| + ADD_DIRS `WORKSPACE/characters` | 14,952 | +1,192 | 하위 폴더별 개별 추가도 동일 (~1.19k) |
| + ADD_DIRS `WORKSPACE/roles` | 14,949 | +1,189 | " |
| + ADD_DIRS `WORKSPACE/memory` | 14,955 | +1,195 | " |
| + ADD_DIRS `WORKSPACE/tools` | 14,954 | +1,194 | " |
| + ADD_DIRS `WORKSPACE/skill-observations` | 14,959 | +1,199 | " |
| + ADD_DIRS `WORKSPACE/.agents` | 14,957 | +1,197 | " |
| + ADD_DIRS `WORKSPACE/.gemini` | 14,952 | +1,192 | " |
| + ADD_DIRS `/tmp/empty` (외부 빈 폴더) | 13,776 | +16 | git 외부 빈 폴더는 세금 거의 없음 |
| 호스트 실세션 (지침 번들 포함) | 16,987 | +2,040 | 2026-09-25 실세션 24건 중앙값 (min 16,418) |

매 턴:
- 늘어나는 대화 히스토리 (불가피)
- HTTP(omniroute): 시스템 프롬프트+도구+히스토리 **전량 재전송** (대화 id 없음).
  툴을 부르면 홉마다 `/v1/chat/completions`가 한 번 더 나간다. 과금은 홉
  `total_tokens` 합, 창 점유는 **마지막 홉** `prompt_tokens`.
  스트리밍 `usage`는 `choices=[]` 마지막 청크에 오는 경우가 많아 그걸
  건너뛰면 턴이 0으로 남는다 (`stream_options.include_usage` + empty
  choices에서도 usage 읽기).
- 도구 결과

빼지 말 것:
- agy `--disable-slash-commands` — 측정됨, 토큰 이득 없음. 켜지 말 것.

ADD_DIRS (2026-09-19): ROOT와 `static/` 둘 다 빼면 첫 턴 46k → 14k.
`static/vendor/mermaid.min.js`(3.2M)가 static add-dir을 ROOT와 같은 46k로
만든다. `host_config.ADD_DIRS` = `/chat`만. 코드/UI 쓰기는 MCP
`services/chatbot`.

## 확인 방법

```
python3 data/workspace/tools/token_audit.py
python3 data/workspace/tools/token_audit.py --sid <session-id>
```

짧은 "안녕" 한 턴을 프로바이더마다 남기면 시작 세금 기준선이 갱신된다.

## 도구 턴 occupancy

우리 `history` 텍스트는 짧다. Codex 세션 `20260918-024833-5471d3` 유저 17자에
창 1.9M — CLI가 파일을 내부 스레드에 쌓은 것. MCP `read_file` 기본 32kB·상한
64kB, `run_command` stdout 8k, OmniRoute 툴 메시지 32k. Codex/agy **자체**
Read는 호스트가 못 자른다. 그 턴 과금은 나가고, 다음 턴 soft/hard 로테이트가
막는다.
