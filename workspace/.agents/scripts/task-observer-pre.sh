#!/bin/sh
OBS_ROOT="/volume1/homes/me/services/chatbot-data/workspace"
CODE="/volume1/homes/me/services/chatbot"
d="$OBS_ROOT/skill-observations"
payload=$(cat)
inv=$(printf '%s' "$payload" | python3 -c 'import sys,json
try:
 d=json.load(sys.stdin); print(int(d.get("invocationNum") or 0))
except Exception:
 print(0)')
open=0
if [ -d "$d/observation-log" ]; then
  open=$(find "$d/observation-log" -maxdepth 1 -name '*.md' 2>/dev/null | xargs -r grep -l '^status: open$' 2>/dev/null | wc -l | tr -d ' ')
fi
last=$(cat "$d/last-review-date.txt" 2>/dev/null || echo never)
if [ "$inv" -le 1 ]; then
  msg="[task-observer] Before tools/planning: invoke task-observer and run Session Start Protocol. Pinned workspace: $OBS_ROOT. Own project code: $CODE. Prefer chatbot-self-improve for bugs in this chat. Open observations: ${open}; last review: ${last}."
  printf '%s' "$msg" | python3 -c 'import sys,json; print(json.dumps({"injectSteps":[{"ephemeralMessage":sys.stdin.read()}]}))'
else
  printf '%s\n' '{}'
fi
