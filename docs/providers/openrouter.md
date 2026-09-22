# openrouter (HTTP, OpenAI dialect)

`adapters.OpenAIDialectAdapter` — 프로세스 없음, `https://openrouter.ai/api/v1/chat/completions` 스트리밍. 무료 모델만. 표기 뜻은 [README](README.md#상태-표기).

| # | 주장 | 상태 | 근거 |
|---|---|---|---|
| R1 | `OPENROUTER_API_KEY`가 있으면 `/api/providers`에서 `available: true` | ✅ | 라이브 호스트 PID environ + `/api/providers` 2026-09-21 |
| R2 | `openrouter/free` 는 공식 무료 라우터 (pricing prompt=0, completion=0) | ✅ | GET `/api/v1/models` 2026-09-21, name "Free Models Router" |
| R3 | `openrouter/auto` 는 무료가 아니다 (pricing -1) | ✅ | 같은 `/v1/models` 응답 |
| R4 | `:free` 접미사 모델 21종 (같은 날 카탈로그 446종 중) | ✅ 1회 | GET `/api/v1/models` 2026-09-21 |
| R5 | HTTP dialect SSOT는 `data/providers.json`. `adapters.load_openai_dialect_adapters`가 로드 | ✅ | 코드 + `tests.test_providers_json` |
| R6 | 유료 id는 요청 직전에 `openrouter/free` 로 강제 치환 | ✅ 단위 | `is_openrouter_free_model` / `coerce_openrouter_model`, `tests/smoke.py` |
| R7 | 스트리밍 응답 `model`을 턴마다 `served_model`로 저장하고 말풍선 꼬리말에 표시 | 📄 코드 | `openai_chunk_model` / `stamp_served_model`. 라이브는 소생 후 확인 |

## 아직 안 해 본 것
1. 소생 후 `openrouter/free` 한 턴 → 꼬리말에 라우터가 아니라 실제 서빙 id가 찍히는지.
2. 옛 세션의 유료 모델명이 실제 호출에서 무료로 바뀌는지 UI 확인.
