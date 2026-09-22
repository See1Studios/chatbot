#!/bin/bash
set -euo pipefail
# ${HOME_DIR:-...}: this NAS's actual value is the default, but a different
# deployment can export HOME_DIR before calling this script (see
# docs/plans/chatbot-host-portability.md) without editing it.
HOME_DIR="${HOME_DIR:-/volume1/homes/me}"
export PATH="$HOME_DIR/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
CODE="$HOME_DIR/services/chatbot"
DATA="$CODE/data"  # consolidated under chatbot/ 2026-09-16
# API-Provider plan: API-key-based adapters (e.g. omniroute) read credentials
# from os.environ, not a config file -- server.py is git-tracked, so the key
# must never be hardcoded into it. This is the one place that env lives:
# untracked (see .gitignore), sourced before every spawn of server.py below,
# so start/restart/repair all pick it up the same way regardless of which
# one actually launches the process.
if [ -f "$DATA/secrets.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$DATA/secrets.env"
  set +a
fi
LOG_DIR="$CODE/logs"
mkdir -p "$DATA/workspace" "$DATA/sessions" "$DATA/artifacts" "$DATA/persona" "$LOG_DIR"
LOG_CHAT="$LOG_DIR/chatbot.log"
LOG_MCP="$LOG_DIR/chatbot-mcp.log"
LOG_DOCTOR="$LOG_DIR/chatbot-doctor.log"
MAX_LOG_BYTES=$((10 * 1024 * 1024)) # 10MB
LOG_BACKUPS=3

rotate_log() {
  local target="$1"
  if [ -f "$target" ]; then
    local size
    size=$(stat -c%s "$target" 2>/dev/null || wc -c < "$target" 2>/dev/null || echo 0)
    if [ "$size" -gt "$MAX_LOG_BYTES" ]; then
      for i in $(seq $((LOG_BACKUPS - 1)) -1 1); do
        [ -f "${target}.${i}" ] && mv -f "${target}.${i}" "${target}.$((i + 1))"
      done
      mv -f "$target" "${target}.1"
      touch "$target"
    fi
  fi
}
PID_CHAT="$LOG_DIR/chatbot.pid"
PID_MCP="$LOG_DIR/chatbot-mcp.pid"
PORT_CHAT="${AGY_CHAT_PORT:-3011}"
PORT_MCP="${NAS_MCP_PORT:-3012}"
PROBE_STAMP="$DATA/doctor-probe.stamp"
PROBE_EVERY_SEC=${CHATBOT_PROBE_EVERY_SEC:-3600}

HOST_TICKET="$DATA/host-force.ticket"
HOST_TICKET_TTL_SEC=120

issue_host_ticket() {
  # Only trusted ctl paths call this before stop/restart.
  local reason="${1:-repair}"
  mkdir -p "$DATA"
  printf '%s\n' "v1 ${reason} $(date +%s) $$" > "$HOST_TICKET"
  chmod 600 "$HOST_TICKET" 2>/dev/null || true
}

consume_host_ticket() {
  rm -f "$HOST_TICKET" 2>/dev/null || true
}

require_host_force() {
  # Live agy must not stop/restart host. CHATBOT_FORCE_HOST=1 alone is NOT enough
  # (model learned to export it). Requires a fresh ticket issued only by repair/doctor/defibrillate.
  local op="$1"
  if [ "${CHATBOT_FORCE_HOST:-}" != "1" ]; then
    echo "REFUSED: $op blocked without CHATBOT_FORCE_HOST=1"
    echo "Use FAB ⚡소생 / POST /api/host/defibrillate / ctl repair (not raw restart)."
    return 1
  fi
  if [ ! -f "$HOST_TICKET" ]; then
    echo "REFUSED: $op blocked — missing host-force ticket (CHATBOT_FORCE_HOST alone is ignored)"
    echo "Self-improve must NOT restart the host. Use ⚡소생 button or ask GameDeveloper."
    return 1
  fi
  # freshness
  local now ts
  now=$(date +%s)
  ts=$(awk '{print $3}' "$HOST_TICKET" 2>/dev/null || echo 0)
  if [ -z "$ts" ] || [ "$ts" -lt $((now - HOST_TICKET_TTL_SEC)) ] 2>/dev/null; then
    echo "REFUSED: $op blocked — host-force ticket expired"
    consume_host_ticket
    return 1
  fi
  return 0
}



kill_orphan_agy() {
  # 1) PPID=1 stream-json orphans
  # 2) probe leftovers: stream-json WITHOUT --conversation
  # 3) unprotected flash-low (not in real session JSON protected set)
  python3 - "$DATA/sessions" <<'PY'
import glob, json, os, signal, subprocess, sys
sessions_dir = sys.argv[1]
protected = set()
# 2026-09-16/17: sessions live at sessions/<sid>/meta.json now (folder per
# session, holding its own artifacts/ alongside), not flat sessions/<sid>.json
# -- this glob matched nothing after that migration, so `protected` was
# always empty and EVERY live flash-low conversation got killed as
# "unprotected-flash-low" below, mid-turn, real conversations included
# (visible as agy stderr "stream input cancelled: context canceled" /
# "interrupted", and as messages that simply never get a reply).
for p in glob.glob(sessions_dir + "/*/meta.json"):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    cid = d.get("conversation_id")
    if not cid:
        continue
    hist = d.get("history") or []
    texts = " ".join(str(h.get("text") or "") for h in hist)
    if "[doctor-probe]" in texts and len(hist) <= 2:
        continue
    if hist:
        protected.add(cid)

standby_pid = None
standby_marker = os.path.join(os.path.dirname(sessions_dir), "standby.pid")
try:
    standby_pid = int(open(standby_marker, encoding="utf-8").read().strip())
except Exception:
    standby_pid = None

live_pids = set()
live_pids_marker = os.path.join(os.path.dirname(sessions_dir), "live_pids.json")
try:
    live_pids = set(json.load(open(live_pids_marker, encoding="utf-8")))
except Exception:
    live_pids = set()

NO_CONV_GRACE_SEC = 90  # a brand-new real session's first turn has no --conversation
                        # yet either (learned only after its first reply) — give it
                        # time to finish before treating it as a probe leftover.
out = subprocess.check_output(["ps", "-eo", "pid=,ppid=,etimes=,args="], text=True, errors="replace")
killed = 0
for line in out.splitlines():
    line = line.strip()
    if not line:
        continue
    parts = line.split(None, 3)
    if len(parts) < 4:
        continue
    pid_s, ppid_s, etimes_s, args = parts
    # Multi-Provider plan Phase 1/2: claude and grok spawns matter here too
    # now that their adapters actually run real processes -- without this,
    # an orphaned child from either would never get reaped at all. agy/claude
    # are the persistent --input-format stream-json protocol; grok is a
    # one-shot --prompt-file exec per turn (no stream-json flag at all), so
    # it needs its own identifying flag rather than sharing agy/claude's.
    # Phase 3: codex is one-shot like grok, identified by --json (its
    # --output-format-equivalent) rather than agy/claude's stream-json flag.
    is_agy_or_claude = ("/.local/bin/agy" in args or "/.local/bin/claude" in args) and "--input-format stream-json" in args
    is_grok = "/.local/bin/grok" in args and "--prompt-file" in args
    is_codex = "/.local/bin/codex" in args and "--json" in args
    if not (is_agy_or_claude or is_grok or is_codex):
        continue
    try:
        pid = int(pid_s); ppid = int(ppid_s); etimes = int(etimes_s)
    except ValueError:
        continue
    toks = args.split()
    cid = None
    for flag in ("--conversation", "--resume"):
        if flag in args:
            for i, t in enumerate(toks):
                if t == flag and i + 1 < len(toks):
                    cid = toks[i + 1]
                    break
        if cid:
            break
    # codex's own resume syntax is a bare `resume <id>` subcommand, not a
    # --flag value pair like agy/claude/grok all use.
    if cid is None and "resume" in toks:
        i = toks.index("resume")
        if i + 1 < len(toks):
            cid = toks[i + 1]
    has_conv = cid is not None
    reason = None
    is_standby = (pid == standby_pid)
    is_live_server_child = (pid in live_pids)
    if ppid == 1:
        reason = "ppid1"  # true orphan even for a standby (parent chat server died/restarted)
    elif is_live_server_child:
        continue  # actively tracked by live chat server (standby or active session)
    elif not has_conv and etimes > NO_CONV_GRACE_SEC and not is_standby:
        reason = "no-conversation"  # standby is exempt — see _StandbyPool, it's meant to sit idle
    elif cid and cid not in protected and "flash-low" in args:
        reason = "unprotected-flash-low"
    if not reason:
        continue
    try:
        os.kill(pid, signal.SIGTERM)
        killed += 1
        print(f"killed pid={pid} reason={reason}", file=sys.stderr)
    except OSError:
        pass
print(killed)
PY
}

is_up() {
  local pidf="$1"
  if [ -f "$pidf" ]; then
    pid=$(cat "$pidf" 2>/dev/null || true)
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then return 0; fi
  fi
  return 1
}
health_chat() { curl -fsS -m 3 "http://127.0.0.1:${PORT_CHAT}/healthz" >/dev/null 2>&1; }
health_mcp() { curl -fsS -m 3 "http://127.0.0.1:${PORT_MCP}/healthz" >/dev/null 2>&1; }

stop_one() {
  local pidf="$1" name="$2"
  if is_up "$pidf"; then
    pid=$(cat "$pidf")
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi
    rm -f "$pidf"; echo "stopped $name"
  else
    echo "not-running $name"
  fi
}

# Static guard: AgySession.lock must be RLock (ensure->_spawn->stop nests).
guard_rlock() {
  python3 - "$CODE/session.py" <<'PY'
import ast, sys
path = sys.argv[1]
src = open(path, encoding="utf-8").read()
tree = ast.parse(src)
ok = False
bad = False
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "AgySession":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                for st in ast.walk(item):
                    if not isinstance(st, ast.Assign):
                        continue
                    for t in st.targets:
                        if isinstance(t, ast.Attribute) and t.attr == "lock":
                            # self.lock = threading.RLock() / Lock()
                            val = st.value
                            name = None
                            if isinstance(val, ast.Call):
                                f = val.func
                                if isinstance(f, ast.Attribute):
                                    name = f.attr
                                elif isinstance(f, ast.Name):
                                    name = f.id
                            if name == "RLock":
                                ok = True
                            elif name == "Lock":
                                bad = True
if bad or not ok:
    print("GUARD_FAIL: AgySession.lock must be threading.RLock() (deadlock if Lock + ensure/spawn/stop)")
    sys.exit(1)
print("guard_rlock OK")
PY
}

# Evolution guard: host module changes (.py) require an active approved/in_progress ticket.
guard_tickets() {
  python3 - "$CODE" "$DATA" <<'PY'
import os, subprocess, sys
from pathlib import Path

code_dir = Path(sys.argv[1]).resolve()
data_dir = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(code_dir))
try:
    import tickets
except Exception as e:
    print(f"GUARD_FAIL: tickets module cannot be loaded ({e})")
    sys.exit(1)

# Host modules, ctl, and protocol files (charter/design) need an open ticket.
try:
    cmd = [
        "git", "diff", "HEAD", "--name-only", "--",
        "*.py", "chatbot-ctl.sh",
        "data/workspace/AGENTS.md", "data/workspace/PROJECT.md",
        "data/workspace/SELF-MODIFY.md",
        "docs/plans/recursive-self-evolution.md",
    ]
    out = subprocess.check_output(cmd, cwd=str(code_dir), text=True, errors="replace")
    changed = [line.strip() for line in out.splitlines() if line.strip()]
except Exception:
    changed = []

if not changed:
    print("guard_tickets OK (no uncommitted host module changes)")
    sys.exit(0)

# If host modules are modified, require at least one approved or in_progress ticket
try:
    all_tickets = tickets.list_tickets(data_dir)
    active = [t for t in all_tickets if t.get("status") in ("approved", "in_progress")]
except Exception as e:
    print(f"GUARD_FAIL: failed to read ticket ledger ({e})")
    sys.exit(1)

if not active:
    print(f"GUARD_FAIL: uncommitted host changes detected in {len(changed)} file(s), but no approved/in_progress ticket found!")
    for f in changed[:5]:
        print(f"  - {f}")
    if len(changed) > 5:
        print(f"  ... and {len(changed) - 5} more")
    print("Self-evolution requires an approved ticket before modifying Tier 2 host modules.")
    sys.exit(1)

print(f"guard_tickets OK (active ticket #{active[0]['id']} matches changes)")
PY
}

# Message path probe: healthz alone misses lock deadlocks.
probe_message() {
  local timeout_s="${1:-5}"
  python3 - "$PORT_CHAT" "$timeout_s" <<'PY'
import json, sys, urllib.request, urllib.error
port = int(sys.argv[1]); timeout = float(sys.argv[2])
base = f"http://127.0.0.1:{port}"
def req(method, path, body=None, timeout=timeout):
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Origin": f"http://127.0.0.1:{port}"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(base+path, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")
sid = None
try:
    st, created = req("POST", "/api/sessions", {"model": "gemini-3.8-flash-low"}, timeout=5)
    sid = created["session"]["id"]
    st, msg = req("POST", f"/api/sessions/{sid}/message", {"text": "[doctor-probe] ping"}, timeout=timeout)
    if st != 200 or not msg.get("ok"):
        print(f"PROBE_FAIL http={st} body={msg}")
        raise SystemExit(2)
    print(f"probe_message OK sid={sid}")
except Exception as e:
    if not isinstance(e, SystemExit):
        print(f"PROBE_FAIL {type(e).__name__}: {e}")
        raise SystemExit(2) from e
    raise
finally:
    if sid:
        # Fully remove the probe session (folder + all) instead of the old
        # stop+discard, which stopped the process but left meta.json (and
        # now artifacts/) on disk forever -- one of these accumulates every
        # PROBE_EVERY_SEC, cluttering the session list/git history with
        # nothing but "[doctor-probe] ping" turns. /message returns as soon
        # as the turn is queued (the real reply streams back later), so the
        # session is still busy=True here -- /stop first (clears busy +
        # proc) so DELETE's still-working guard doesn't just refuse it.
        try:
            req("POST", f"/api/sessions/{sid}/stop", {}, timeout=5)
        except Exception:
            pass
        try:
            req("DELETE", f"/api/sessions/{sid}", timeout=5)
        except Exception:
            pass
PY
}

should_probe_now() {
  # throttle expensive agy spawn; force with CHATBOT_FORCE_PROBE=1
  if [ "${CHATBOT_FORCE_PROBE:-0}" = "1" ]; then return 0; fi
  local now age
  now=$(date +%s)
  if [ ! -f "$PROBE_STAMP" ]; then return 0; fi
  age=$(( now - $(cat "$PROBE_STAMP" 2>/dev/null || echo 0) ))
  [ "$age" -ge "$PROBE_EVERY_SEC" ]
}

mark_probe() { date +%s > "$PROBE_STAMP"; }

doctor_log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DOCTOR"
}

cmd_start() {
  export HOME="$HOME_DIR"
  export AGY_CHAT_HOST=0.0.0.0 AGY_CHAT_PORT="$PORT_CHAT"
  export AGY_BIN="${AGY_BIN:-$HOME_DIR/.local/bin/agy}"
  export AGY_CHAT_ROOT="$CODE" AGY_CHAT_DATA="$DATA"
  guard_rlock
  # Rotate only right before a process is (re)spawned: a live process keeps
  # its fd on the renamed inode, so rotating under it would send its output to
  # chatbot.log.1 and leave chatbot.log empty. doctor.log is safe anywhere
  # (doctor_log reopens it per write).
  rotate_log "$LOG_DOCTOR"
  if ! is_up "$PID_MCP" || ! health_mcp; then
    stop_one "$PID_MCP" mcp >/dev/null || true
    rotate_log "$LOG_MCP"
    setsid nohup python3 "$CODE/mcp_server.py" >>"$LOG_MCP" 2>&1 < /dev/null & echo $! > "$PID_MCP"
    sleep 1
  fi
  if is_up "$PID_CHAT" && health_chat; then
    echo "already running chat pid=$(cat "$PID_CHAT") mcp pid=$(cat "$PID_MCP")"
    return 0
  fi
  stop_one "$PID_CHAT" chat >/dev/null || true
  kill_orphan_agy >/dev/null
  rotate_log "$LOG_CHAT"
  setsid nohup python3 "$CODE/server.py" >>"$LOG_CHAT" 2>&1 < /dev/null & echo $! > "$PID_CHAT"
  sleep 1
  if health_chat; then echo "started chat pid=$(cat "$PID_CHAT") mcp pid=$(cat "$PID_MCP")"; else echo "start failed"; tail -n 40 "$LOG_CHAT"; return 1; fi
}

wait_for_idle_session() {
  # cmd_repair used to stop_one the chat server unconditionally, no matter
  # what was in flight. If a real conversation was mid-turn, its agy child
  # got reparented to ppid=1 the instant the server died, and
  # kill_orphan_agy's "ppid1" branch reaps ANY ppid=1 process a few lines
  # later regardless of protected-session status -- silently dropping the
  # user's turn with no reply and no retry (2026-09-18, session
  # 20260918-154037-ad23b8: "팝업 고치는 거 아니었어?" never answered).
  # Give an in-progress reply a bounded window to finish before we go
  # ahead with the restart; a stuck busy=true forever shouldn't block
  # repair indefinitely, so we cap the wait and proceed anyway after it.
  local waited=0 max_wait=60 busy
  is_up "$PID_CHAT" && health_chat || return 0
  while [ "$waited" -lt "$max_wait" ]; do
    busy=$(curl -fsS -m 3 "http://127.0.0.1:${PORT_CHAT}/api/sessions/active" 2>/dev/null \
      | python3 -c 'import json,sys
try:
    print("1" if json.load(sys.stdin).get("busy") else "0")
except Exception:
    print("0")' 2>/dev/null || echo 0)
    [ "$busy" = "1" ] || return 0
    sleep 3
    waited=$((waited + 3))
  done
  return 1
}

cmd_repair() {
  export CHATBOT_FORCE_HOST=1
  issue_host_ticket repair
  trap consume_host_ticket EXIT
  doctor_log "REPAIR begin"
  kill_stale_session_agy || true
  guard_rlock || doctor_log "WARNING guard_rlock failed — refusing blind restart may be wrong; continuing after note"
  wait_for_idle_session || doctor_log "WARNING active session still busy after wait — proceeding with repair anyway"
  stop_one "$PID_CHAT" chat || true
  stop_one "$PID_MCP" mcp || true
  orphans=$(kill_orphan_agy)
  doctor_log "killed orphan agy count=$orphans"
  # clear stale pid
  rm -f "$PID_CHAT" "$PID_MCP"
  cmd_start
  # force one message probe after repair
  CHATBOT_FORCE_PROBE=1
  if probe_message 8; then
    mark_probe
    pruned=$(kill_orphan_agy)
    doctor_log "REPAIR ok (probe passed) post_probe_pruned=$pruned"
    return 0
  else
    pruned=$(kill_orphan_agy)
    doctor_log "REPAIR probe still failing post_probe_pruned=$pruned"
    return 1
  fi
}


kill_stale_session_agy() {
  # After host restart, agy may reparent to user systemd (PPID!=chat pid) while still holding a conversation.
  local chat_pid=""
  if [[ -f "$PID_CHAT" ]]; then chat_pid=$(cat "$PID_CHAT" 2>/dev/null || true); fi
  ps -eo pid,ppid,args 2>/dev/null | while read -r pid ppid args; do
    [[ "$args" == *"/agy "* ]] || [[ "$args" == *" agy "* ]] || continue
    [[ "$args" == *"--input-format stream-json"* ]] || continue
    if [[ -n "$chat_pid" && "$ppid" == "$chat_pid" ]]; then continue; fi
    # leave non-chat agy alone if no conversation flag? kill conversation orphans not owned by chat
    if [[ "$args" == *"--conversation "* ]]; then
      echo "stale_session_agy_kill pid=$pid ppid=$ppid"
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

cmd_doctor() {
  local auto=0 age hash_out
  # Maintenance flag (data/maintenance.flag, made by a person): no automatic start/repair.
  if age=$(python3 "$CODE/evolution.py" maintenance "$DATA/maintenance.flag" 2>/dev/null); then
    echo "doctor: maintenance flag present ($age) — auto start/repair skipped"
    doctor_log "doctor: maintenance flag present ($age) — auto start/repair skipped"
    return 0
  fi
  # Warn-only check of the protected files against protected_manifest.json.
  hash_out=$(python3 "$CODE/evolution.py" manifest-check 2>&1 || true)
  if [ -n "$hash_out" ]; then
    echo "$hash_out"
    case "$hash_out" in WARN*) doctor_log "$hash_out" ;; esac
  fi
  if [ "${1:-}" = "--auto-repair" ] || [ "${1:-}" = "auto" ]; then auto=1; fi
  local rc=0
  echo "=== chatbot doctor ==="
  if ! guard_rlock; then
    echo "FAIL guard_rlock"
    doctor_log "doctor FAIL guard_rlock"
    # code regression — restart won't help; still try start for availability
    rc=1
  fi
  if ! is_up "$PID_CHAT" || ! health_chat; then
    echo "chat down — starting"
    doctor_log "doctor: chat down, start"
    if ! cmd_start; then
      doctor_log "doctor: start failed"
      return 1
    fi
  else
    echo "chat healthz OK pid=$(cat "$PID_CHAT")"
  fi
  if ! is_up "$PID_MCP" || ! health_mcp; then
    echo "mcp down — starting via start"
    cmd_start || true
  else
    echo "mcp healthz OK pid=$(cat "$PID_MCP")"
  fi
  orphans=$(kill_orphan_agy)
  kill_stale_session_agy >/dev/null || true
  echo "orphan_agy_killed=$orphans"

  if should_probe_now; then
    echo "message probe (every ${PROBE_EVERY_SEC}s)..."
    if probe_message 5; then
      mark_probe
      echo "probe OK"
    else
      echo "FAIL probe_message"
      doctor_log "doctor FAIL probe_message"
      rc=1
      if [ "$auto" = "1" ]; then
        doctor_log "doctor auto-repair triggered by probe fail"
        if cmd_repair; then
          rc=0
        else
          rc=1
        fi
      fi
    fi
    # Always prune probe leftovers after a probe attempt
    pruned=$(kill_orphan_agy)
    echo "post_probe_agy_pruned=$pruned"
    doctor_log "post_probe_agy_pruned=$pruned"
  else
    echo "probe skipped (throttle; stamp=$(cat "$PROBE_STAMP" 2>/dev/null || echo none))"
  fi
  if [ "$rc" = "0" ]; then echo "doctor PASS"; else echo "doctor FAIL"; doctor_log "doctor FAIL"; fi
  return $rc
}

# start/doctor/repair share one lock, held by a Python supervisor (evolution.py),
# not by bash flock (macOS has none). doctor skips when it is busy; start/repair
# wait, then exit 75. CHATBOT_LOCK_PPID == $PPID means "already inside the lock".
# If the helper cannot run, carry on unlocked: the lock is a safeguard, not a precondition.
case "${1:-status}" in
  start|doctor|repair|defibrillate|shock|cpr)
    if [ "${CHATBOT_LOCK_PPID:-}" != "$PPID" ] \
       && python3 "$CODE/evolution.py" self-check "$DATA/lifecycle.lock" >/dev/null 2>&1; then
      lock_wait="${CHATBOT_LOCK_WAIT_SEC:-120}"
      if [ "${1:-status}" = "doctor" ]; then lock_wait=0; fi
      exec python3 "$CODE/evolution.py" run-locked "$DATA/lifecycle.lock" "$lock_wait" -- bash "$0" "$@"
    fi
    ;;
esac

cmd="${1:-status}"
case "$cmd" in
  start) cmd_start ;;
  stop)
    require_host_force stop || exit 3
    stop_one "$PID_CHAT" chat
    stop_one "$PID_MCP" mcp
    kill_orphan_agy >/dev/null
    kill_stale_session_agy >/dev/null || true
    ;;
  restart)
    require_host_force restart || exit 3
    CHATBOT_FORCE_HOST=1 "$0" stop || true
    "$0" start
    ;;
  status)
    if is_up "$PID_CHAT" && health_chat; then echo "chat up pid=$(cat "$PID_CHAT")"; curl -sS -m 3 "http://127.0.0.1:${PORT_CHAT}/healthz"; echo; else echo "chat down"; fi
    if is_up "$PID_MCP" && health_mcp; then echo "mcp up pid=$(cat "$PID_MCP")"; curl -sS -m 3 "http://127.0.0.1:${PORT_MCP}/healthz"; echo; else echo "mcp down"; fi
    ;;
  doctor) shift || true; cmd_doctor "${1:-}" ;;
  probe) CHATBOT_FORCE_PROBE=1; probe_message "${2:-5}"; mark_probe; kill_orphan_agy >/dev/null ;;
  repair|defibrillate|shock|cpr)
    export CHATBOT_FORCE_HOST=1
    cmd_repair
    ;;
  guard)
    guard_rlock
    guard_tickets
    ;;
  *) echo "usage: $0 {start|stop|restart|status|doctor [--auto-repair]|probe|repair|defibrillate|guard}"; exit 2 ;;
esac
