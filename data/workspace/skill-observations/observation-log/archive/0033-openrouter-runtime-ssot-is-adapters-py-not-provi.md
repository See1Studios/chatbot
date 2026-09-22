---
id: 33
title: "OpenRouter runtime SSOT is adapters.py, not providers.json"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "adapters openrouter"
date: 2026-09-21
parked_until:
resolved: 2026-09-21
resolution: "실장님 “Providers.json 을 써야하지않나”. load_openai_dialect_adapters() 가 data/providers.json 을 읽어 HTTP dialect를 등록. OpenRouter free_only. CLI id 덮지 못함. tests.test_providers_json OK."
reference:
---

실장님: OpenRouter provider 를 추가하고 무료모델만 사용하고 싶어. 측정: AGENT_ADAPTERS[“openrouter”] 는 이미 등록·라이브 available=true 였으나 기본/큐레이션이 유료(deepseek/deepseek-chat 등). data/providers.json 만 무료로 고친 세션이 있었고 JSON은 로드하지 않음. 개선: 런타임 SSOT는 adapters.py. OpenRouter는 :free와 openrouter/free만 피커·호출. openrouter/auto는 pricing -1이라 허용 금지. 옛 세션 유료 id는 coerce_openrouter_model이 openrouter/free로 바꿈.
