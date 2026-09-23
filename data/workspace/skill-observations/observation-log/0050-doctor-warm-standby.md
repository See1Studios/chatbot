---
id: 50
title: "doctor가 살아 있는 서버의 warm standby를 반복 종료"
status: actioned
type: internal
skill: []
proposes_skill: []
area: "chatbot"
date: 2026-09-23
parked_until:
resolved: 2026-09-23
resolution: "티켓 #51(05a15b9)·#53(f1bfd88): 판단을 OS 사실(ctl_proc.py)로, 설계서 §7-7"
reference:
actor: "claude-code"
resolved_by: "claude-code"
---

측정: 12:15:30 agent.reaped pid 1938(standby, 부모=라이브 chat 610, reason=unprotected-flash-low). 근거 candidate:1790133706.978(host:agent_reaped_live).
원인: 보호 판단이 서비스가 갱신하는 live_pids.json에 의존, standby 생성 시 갱신 누락. 사용자: doctor는 서비스에 의존하면 안 됨.
