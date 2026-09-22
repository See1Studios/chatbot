# omniroute (HTTP, OpenAI dialect)

`adapters.OpenAIDialectAdapter` — 프로세스 없음, `/v1/chat/completions` 스트리밍. 표기 뜻은 [README](README.md#상태-표기).

| # | 주장 | 상태 | 근거 |
|---|---|---|---|
| O1 | stateless라 **매 요청**의 `role:"system"` 메시지가 유일한 지속 채널이다. 히스토리는 `_history_to_openai_messages()`가 매번 재생 | ✅ | 코드, DEVLOG 2026-09-18 |
| O2 | 시스템 메시지를 넣기 전에는 냥피디가 페르소나 없이 평이한 톤으로 답했다 | ✅ 관측 | DEVLOG 2026-09-18 |
| O3 | 런타임 정보(`provider`, `model`)를 시스템 메시지로 따로 줘야 "너 무슨 모델이야"에 하네스 목록을 보고 `agy`라고 짐작하지 않는다 | ✅ 관측 | session `20260918-193213-e30f27` |
| O4 | 지침 묶음을 첫 턴 사용자 메시지 앞머리에 **또** 붙이면 첫 턴에 중복된다 → HTTP는 앞머리 주입을 건너뛰고 시스템 메시지만 쓴다 | ⚠ 단위 테스트만 | `tests/test_instructions.py::test_http_transport_flags_but_does_not_prefix`. 라이브 미검증 (미소생 코드) |
| O5 | 짧은 인사 첫 요청 ~0.7k(시스템만), 도구를 켠 실세션 첫 턴 ~128k. 툴 홉마다 요청이 하나 더 나간다 | 📄 | `token-accounting.md` |
| O6 | `auto/*` 콤보는 keepalive만 길어서 기본은 핀 모델 `antigravity/claude-sonnet-4-6` | ✅ | DEVLOG 2026-09-18. 설정은 `data/providers.json` |
| O7 | HTTP dialect 엔드포인트·키·모델은 `data/providers.json` | ✅ | `load_openai_dialect_adapters` |

## 아직 안 해 본 것
1. 실제 omniroute 세션에서 O4 (이중 주입 제거) 라이브 확인.
