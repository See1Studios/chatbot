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
| agy | ~75k | ~119k |
| codex | ~23–33k | 들쭉날쭉. 짧은 턴 수백~1.6만, 도구 턴 10만~, 최장 세션 마지막 1.9M |
| omniroute | 짧은 인사 ~0.7k (시스템만). 도구 켠 실세션 첫 턴 ~128k | 매 HTTP 요청이 시스템+도구+히스토리 전량. 툴 홉은 요청이 하나 더 |

시작 세금에 들어가는 것 (한 번 깔리고, CLI가 대화를 이어가면 캐시될 수 있음):
- `AGENTS.md` + `PERSONA.md` + 스킬 색인 (호스트가 조립하는 지침 묶음, `instructions.py`, 약 6KB)
- MCP 도구 스키마
- 스킬 카탈로그 가설은 **기각** (2026-09-19 A/B). 호스트와 같은 spawn
  (`stream-json` + ADD_DIRS + 모델)에서 `--disable-slash-commands`는
  첫 턴 input 45970 vs 45961 (차이 9, 노이즈). `--print` 모드도
  45966 vs 45974. 현재 시작 세금은 **~46k이고 슬래시/스킬 펼침이 아님**.
  역사 세션 중앙값 ~75k는 도구·긴 히스토리가 섞인 값. claude ~11k와의
  잔여 차(~35k)는 ADD_DIRS/MCP/agy 시스템 쪽 다음 실험.
- `ADD_DIRS` (ROOT + `/chat`). 2026-09-16에 ROOT 통째가 첫 턴을 불리지 않음을
  측정함. 세션 폴더를 빼는 실험은 아직 안 함.

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
