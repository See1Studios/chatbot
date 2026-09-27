---
id: 91
title: "QUOTA_FAILFAST 8초가 agy 자동 재시도(10~57초)를 자름 — #253 이후 잔여 사례 관찰"
status: parked
type: internal
skill: []
proposes_skill: []
area: "provider/agy"
date: 2026-09-27
parked_until: 2026-09-28
resolved:
resolution: "Watch one day after #253; rerun the tally on 2026-09-28, then decide option (가) or (나)."
reference:
actor: "claude-code"
resolved_by: "claude-code"
---

## 무엇을 봤나 (2026-09-27, Claude Code, 운영자 요청 조사)

운영자: "agy(gemini) 오류가 심한데 우리 쪽과 관계없는지" 확인 요청.

- 출발점은 구글 쪽: agy가 `error_message` 단계를 내고 스스로 재시도한다. 저녁(21시 9건)에 가장 잦았다.
  agy는 오류 내용을 넘겨주지 않는다(`session.py` error_message hint가 항상 비어 기본 문구가 찍힘) → 구글 오류 종류는 우리 기록으로 알 수 없다.
- 사용자에게 보인 실패의 상당수는 우리 `QUOTA_FAILFAST`(오류 뒤 8초 무활동이면 닫음, `turn_watchdog.py::TurnWatchdog`)가 만들었다.

| 구간 | agy 오류 턴 | 우리가 ~8초에 닫음 | agy 회복 (회복까지 초) |
|---|---|---|---|
| 00~20시 (#253 반영 전) | 18 | 18 | 0 |
| 21~23시 (#253 반영 후, 20:54 재기동) | 17 | 3 | 14 (10.0~57.4, 한 건 189) |

- #253(4f34e29, "활동이 있으면 failfast 취소")이 효과를 냈다. 코드는 pew/N1d에서 `turn_watchdog.py`로 그대로 옮겨졌고 테스트 통과.
- 잔여 사례: agy가 오류 뒤 **아무 신호 없이** 8초 넘게 재시도하면 여전히 닫힌다. 예: 세션 20260927-113258-6c43b2, 23:07:54 입력 → +15s error_message → +23s 닫힘. 같은 세션 다음 턴은 error_message 뒤 10.2초에 회복.

## 결정 (운영자, 2026-09-27)

하루 지켜본다(표본이 적고 구글 쪽 급증이 가라앉을 수 있음). 2026-09-28에 아래 집계를 다시 돌려
잔여 사례가 계속되면 안 (가)를 티켓으로: error_message가 와도 턴을 닫지 않고 "구글 쪽 오류로 재시도 중" 알림만,
실제 멈춤은 SILENT_HANG(90초)이 닫는다. 대안 (나): ERROR_MESSAGE_FAILFAST_SEC 8 → 30.
주의: 8.x초 "회복"으로 보이는 행은 대부분 우리 failfast가 부분 답을 붙여 닫은 것(result 뒤 error). 다시 셀 때 error 이벤트 동반 여부로 구분할 것.

## 다시 돌리는 집계 (services/chatbot에서)

```
python3 - <<'EOF'
import json,glob,collections,datetime
DAY=datetime.datetime(2026,9,28)   # 볼 날짜
S=collections.defaultdict(lambda:[0,0,0,[]])  # 오류턴, 회복, 우리가닫음, 회복초
for p in glob.glob('data/sessions/*/events.jsonl'):
    ev=[e for e in (json.loads(l) for l in open(p,errors='replace') if l.strip().startswith('{'))
        if isinstance(e.get('ts'),(int,float)) and DAY.timestamp()<=e['ts']<DAY.timestamp()+86400]
    t=None
    for i,e in enumerate(ev):
        if e.get('step_type')=='user_input': t=None
        if e.get('step_type')=='error_message' and t is None:
            t=e['ts']; h=datetime.datetime.fromtimestamp(t).strftime('%H'); S[h][0]+=1
        elif t and e.get('event') in ('result','error'):
            closed = e.get('event')=='error' or any(x.get('event')=='error' for x in ev[i+1:i+2])
            S[h][2 if closed else 1]+=1
            if not closed: S[h][3].append(round(e['ts']-t,1))
            t=None
for h in sorted(S): print(h,*S[h][:3],sorted(S[h][3]))
EOF
```
