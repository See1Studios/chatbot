#!/bin/bash
set -euo pipefail
# ${HOME_DIR:-...}: this NAS's actual value is the default, but a different
# deployment can export HOME_DIR before calling this script (see
# docs/plans/chatbot-host-portability.md) without editing it.
HOME_DIR="${HOME_DIR:-$HOME}"
export PATH="$HOME_DIR/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# CTL_SYMLINK_v1: ~/services/chatbot-ctl.sh is a symlink; follow it, or CODE becomes ~/services (the doctor then
# looked for ~/services/server.py and failed every run from 2026-09-23 19:07 to 2026-09-24 13:30).
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CODE="${CODE:-$SCRIPT_DIR}"
# uds/F: same order as host_config.DATA_ENV. Unset -> data-pin.env (literal CHATBOT_DATA) -> ~/.pe.
# Do not hardcode $CODE/data. Exported here so the log resolver and every child agree with host_config.
# DATA_RESOLVE_START
if [ -z "${CHATBOT_DATA:-}" ] && [ -z "${PE_HOME:-}" ] && [ -z "${PRIVATEENGINE_HOME:-}" ]; then
  if [ -f "$CODE/data-pin.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$CODE/data-pin.env"
    set +a
  fi
fi
DATA="${CHATBOT_DATA:-${PE_HOME:-${PRIVATEENGINE_HOME:-${HOME:-$HOME_DIR}/.pe}}}"
# DATA_RESOLVE_END
export CHATBOT_ROOT="$CODE" CHATBOT_DATA="$DATA"
# API-Provider plan: API-key-based adapters (e.g. omniroute) read credentials
# from os.environ, not a config file -- server.py is git-tracked, so the key
# must never be hardcoded into it. This is the one place that env lives:
# untracked (see .gitignore), sourced before every spawn of server.py below,
# so start/restart/repair all pick it up the same way regardless of which
# one actually launches the process.
# align/F: this install's own settings (host plugin, web root, ports) live beside its data, not in code;
# see templates/host.env.example. Sourced before secrets.env so a secret can never be overridden by it.
if [ -f "$DATA/host.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$DATA/host.env"
  set +a
fi
if [ -f "$DATA/secrets.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$DATA/secrets.env"
  set +a
fi
# LOG_PATH_v1: both log names come from the ONE resolver in host_config, so ctl cannot drift from
# obslog/logdigest and never composes a path of its own. host.env above is already sourced, so a
# per-install CHATBOT_LOG_DIR / CHATBOT_OBSLOG_PATH applies. Two things matter here:
#   - `cd "$CODE"`: python puts the working directory on sys.path, so without it `import host_config`
#     resolves to whatever checkout the caller happens to be standing in, and a copied ctl would
#     write into another tree's log dir (the CTL_SYMLINK_v1 lesson, one level down).
#   - no pipe: set -o pipefail turns a closed pipe into exit 141 and would kill the script.
# If python cannot answer (a broken checkout), fall back to the repo's logs/ exactly as before.
_paths="$(cd "$CODE" && python3 -c 'import host_config; print("%s\t%s" % (host_config.LOG_DIR, host_config.EVENTS_LOG))' 2>/dev/null || true)"
LOG_DIR=""
EVENTS_LOG=""
if [ -n "$_paths" ]; then
  IFS=$'\t' read -r LOG_DIR EVENTS_LOG <<<"$_paths"
fi
[ -n "$LOG_DIR" ] || LOG_DIR="$CODE/logs"
[ -n "$EVENTS_LOG" ] || EVENTS_LOG="$LOG_DIR/events.jsonl"
# uds/D: a new install's empty data folder gets templates/workspace once (never overwrites; no-op here). Before the
# mkdir below, which would otherwise leave an empty workspace. A failure warns and does not stop ctl (stop/status
# must still work).
(cd "$CODE" && python3 data_bootstrap.py --data "$DATA" --quiet) || echo "warning: data bootstrap failed ($DATA)" >&2
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
# OBSLOG_v1: structured events go to logs/events.jsonl (OPERATIONS.md). CHATBOT_CALLER says
# who started this run (api-defibrillate, doctor-auto, cli-tty, ppid:<parent>); it is exported
# before the lifecycle lock re-exec so the locked child keeps it.
export CHATBOT_OBSLOG_PATH="${CHATBOT_OBSLOG_PATH:-$EVENTS_LOG}"
if [ -z "${CHATBOT_CALLER:-}" ]; then
  if [ -t 0 ] || [ -t 1 ]; then
    CHATBOT_CALLER="cli-tty"
  else
    # parent command < grandparent command line (shortened): enough to tell a scheduler,
    # an agent's shell and a person's script apart.
    _pp_comm=$(ps -o comm= -p "$PPID" 2>/dev/null | tr -d ' ' || true)
    _gp=$(ps -o ppid= -p "$PPID" 2>/dev/null | tr -d ' ' || true)
    _gp_args=""
    if [ -n "$_gp" ]; then
      _gp_args=$(ps -o args= -p "$_gp" 2>/dev/null | sed "s#$HOME_DIR#~#g" | cut -c1-80 || true)
    fi
    CHATBOT_CALLER="ppid:${_pp_comm:-?}<${_gp_args:-?}"
  fi
  export CHATBOT_CALLER
fi

obs() {
  # obs <evt> <lvl> [key=value ...] -- best effort, never fails the caller
  local evt="$1" lvl="$2"
  shift 2
  python3 "$CODE/obslog.py" emit --src ctl --evt "$evt" --lvl "$lvl" "$@" >/dev/null 2>&1 || true
}

PID_CHAT="$LOG_DIR/chatbot.pid"
PID_MCP="$LOG_DIR/chatbot-mcp.pid"
PORT_CHAT="${CHATBOT_PORT:-3011}"
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
  # A live agent must not stop/restart host. CHATBOT_FORCE_HOST=1 alone is NOT enough
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



reap_orphan_agents() {
  # WATCHDOG_OS_FACTS_v1 (recursive-self-evolution.md §7-7): decided from the process table,
  # /proc cwd and ctl's own pid file only -- see ctl_proc.py. Our agents (cwd = $DATA/workspace)
  # that are not descendants of the live chat server are reaped; the server's descendants and
  # anybody else's processes are never touched. Prints the count.
  python3 "$CODE/ctl_proc.py" reap "$CODE" "$DATA"
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
# A started server needs a moment to import and bind (~2 s on this host). One check after 1 s logged ctl.start_failed
# for healthy starts (2026-10-01, twice). Wait until it answers, its process is gone, or START_WAIT_SEC pass.
wait_health_chat() {
  local i
  for ((i = 0; i < ${START_WAIT_SEC:-15}; i++)); do
    sleep 1
    health_chat && return 0
    is_up "$PID_CHAT" || return 1
  done
  return 1
}

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

# Static guard: AgentSession.lock must be RLock (ensure->_spawn->stop nests).
guard_rlock() {
  python3 - "$CODE/session.py" <<'PY'
import ast, sys
path = sys.argv[1]
src = open(path, encoding="utf-8").read()
tree = ast.parse(src)
ok = False
bad = False
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "AgentSession":
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
    print("GUARD_FAIL: AgentSession.lock must be threading.RLock() (deadlock if Lock + ensure/spawn/stop)")
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

# Host modules, ctl, static UI and the dev charter/protocol files (templates/dev-workspace, uds/F) need an open ticket.
try:
    cmd = [
        "git", "diff", "HEAD", "--name-only", "--",
        "*.py", "chatbot-ctl.sh", "static/", "templates/dev-workspace/",
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
    hdrs = {"Origin": f"http://127.0.0.1:{port}", "X-Chatbot-Caller": "doctor-probe"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(base+path, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")
sid = None
try:
    st, created = req("POST", "/api/sessions", {}, timeout=5)  # the server's default provider and model
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
  # throttle the expensive agent spawn; force with CHATBOT_FORCE_PROBE=1
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
  export CHATBOT_HOST=0.0.0.0 CHATBOT_PORT="$PORT_CHAT"
  export AGY_BIN="${AGY_BIN:-$HOME_DIR/.local/bin/agy}"
  export CHATBOT_ROOT="$CODE" CHATBOT_DATA="$DATA"
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
    obs ctl.spawn info proc=mcp pid="$(cat "$PID_MCP" 2>/dev/null || echo 0)"
  fi
  if is_up "$PID_CHAT" && health_chat; then
    echo "already running chat pid=$(cat "$PID_CHAT") mcp pid=$(cat "$PID_MCP")"
    return 0
  fi
  stop_one "$PID_CHAT" chat >/dev/null || true
  reap_orphan_agents >/dev/null
  rotate_log "$LOG_CHAT"
  setsid nohup python3 "$CODE/server.py" >>"$LOG_CHAT" 2>&1 < /dev/null & echo $! > "$PID_CHAT"
  if wait_health_chat; then
    echo "started chat pid=$(cat "$PID_CHAT") mcp pid=$(cat "$PID_MCP")"
    obs ctl.spawn info proc=chat pid="$(cat "$PID_CHAT")"
  else
    echo "start failed"
    obs ctl.start_failed error proc=chat --msg "$(tail -n 5 "$LOG_CHAT" 2>/dev/null | tr '\n' ' ' | cut -c1-600)"
    tail -n 40 "$LOG_CHAT"
    return 1
  fi
}

wait_for_idle_session() {
  # cmd_repair used to stop_one the chat server unconditionally, no matter
  # what was in flight. If a real conversation was mid-turn, its agent child
  # got reparented to ppid=1 the instant the server died and was reaped
  # a few lines later -- silently dropping the user's turn with no reply
  # (2026-09-18, session 20260918-154037-ad23b8: "팝업 고치는 거 아니었어?").
  # Give an in-progress reply a bounded window to finish before restarting.
  # WATCHDOG_OS_FACTS_v1 (§7-7): "in progress" is measured on the server's agent processes
  # (CPU/I-O over ~6 s, ctl_proc.py busy), not asked of the service's API.
  local waited=0 max_wait=60 t0=$SECONDS
  is_up "$PID_CHAT" || return 0
  while [ "$waited" -lt "$max_wait" ]; do
    python3 "$CODE/ctl_proc.py" busy "$CODE" "$DATA" || return 0
    waited=$((SECONDS - t0))
  done
  obs repair.busy_timeout warn waited_s="$waited"
  return 1
}

cmd_repair() {
  export CHATBOT_FORCE_HOST=1
  issue_host_ticket repair
  trap consume_host_ticket EXIT
  doctor_log "REPAIR begin caller=$CHATBOT_CALLER"
  local t0=$SECONDS
  obs repair.begin warn
  guard_rlock || doctor_log "WARNING guard_rlock failed — refusing blind restart may be wrong; continuing after note"
  wait_for_idle_session || doctor_log "WARNING active session still busy after wait — proceeding with repair anyway"
  stop_one "$PID_CHAT" chat || true
  stop_one "$PID_MCP" mcp || true
  orphans=$(reap_orphan_agents)
  doctor_log "reaped orphan agents count=$orphans"
  # clear stale pid
  rm -f "$PID_CHAT" "$PID_MCP"
  cmd_start
  # force one message probe after repair
  CHATBOT_FORCE_PROBE=1
  if probe_message 8; then
    mark_probe
    pruned=$(reap_orphan_agents)
    doctor_log "REPAIR ok (probe passed) post_probe_pruned=$pruned"
    obs repair.end info ok=1 dur_s=$((SECONDS - t0)) orphans="$orphans" pruned="$pruned"
    return 0
  else
    pruned=$(reap_orphan_agents)
    doctor_log "REPAIR probe still failing post_probe_pruned=$pruned"
    obs repair.end error ok=0 dur_s=$((SECONDS - t0)) orphans="$orphans" pruned="$pruned"
    return 1
  fi
}



cmd_doctor() {
  local auto=0 age hash_out
  # Maintenance flag (data/maintenance.flag, made by a person): no automatic start/repair.
  if age=$(python3 "$CODE/evolution.py" maintenance "$DATA/maintenance.flag" 2>/dev/null); then
    echo "doctor: maintenance flag present ($age) — auto start/repair skipped"
    doctor_log "doctor: maintenance flag present ($age) — auto start/repair skipped"
    obs doctor.maintenance info age="$age"
    return 0
  fi
  # Warn-only: protected files that differ from git HEAD (edited, deleted, new and uncommitted) -- split/E.
  hash_out=$(python3 "$CODE/evolution.py" protected-check 2>&1 || true)
  if [ -n "$hash_out" ]; then
    echo "$hash_out"
    # Same warning every run used to fill doctor.log (1669 of 2600 lines): log only on change.
    case "$hash_out" in WARN*)
      local sum_now sum_old
      sum_now=$(printf '%s' "$hash_out" | cksum | cut -d' ' -f1)
      sum_old=$(cat "$LOG_DIR/.manifest-warn.sum" 2>/dev/null || true)
      if [ "$sum_now" != "$sum_old" ]; then
        doctor_log "$hash_out"
        obs manifest.drift warn --msg "$hash_out"
        printf '%s' "$sum_now" > "$LOG_DIR/.manifest-warn.sum"
      fi
      ;;
    *) rm -f "$LOG_DIR/.manifest-warn.sum" ;;
    esac
  fi
  if [ "${1:-}" = "--auto-repair" ] || [ "${1:-}" = "auto" ]; then auto=1; fi
  local rc=0
  echo "=== chatbot doctor ==="
  if ! guard_rlock; then
    echo "FAIL guard_rlock"
    doctor_log "doctor FAIL guard_rlock"
    obs doctor.fail error check=guard_rlock
    # code regression — restart won't help; still try start for availability
    rc=1
  fi
  if ! is_up "$PID_CHAT" || ! health_chat; then
    echo "chat down — starting"
    doctor_log "doctor: chat down, start"
    obs doctor.chat_down error
    if ! cmd_start; then
      doctor_log "doctor: start failed"
      obs doctor.fail error check=start
      return 1
    fi
  else
    echo "chat healthz OK pid=$(cat "$PID_CHAT")"
  fi
  if ! is_up "$PID_MCP" || ! health_mcp; then
    echo "mcp down — starting via start"
    obs doctor.mcp_down error
    cmd_start || true
  else
    echo "mcp healthz OK pid=$(cat "$PID_MCP")"
  fi
  orphans=$(reap_orphan_agents)
  echo "orphan_agents_reaped=$orphans"

  if should_probe_now; then
    echo "message probe (every ${PROBE_EVERY_SEC}s)..."
    local probe_out
    if probe_out=$(probe_message 5); then
      echo "$probe_out"
      mark_probe
      echo "probe OK"
      obs doctor.probe info ok=1
    else
      echo "$probe_out"
      obs doctor.probe error ok=0 --msg "$probe_out"
      echo "FAIL probe_message"
      doctor_log "doctor FAIL probe_message"
      rc=1
      if [ "$auto" = "1" ]; then
        doctor_log "doctor auto-repair triggered by probe fail"
        export CHATBOT_CALLER="doctor-auto<${CHATBOT_CALLER}"
        if cmd_repair; then
          rc=0
        else
          rc=1
        fi
      fi
    fi
    # Always prune probe leftovers after a probe attempt
    pruned=$(reap_orphan_agents)
    echo "post_probe_agents_pruned=$pruned"
    doctor_log "post_probe_agents_pruned=$pruned"
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
    reap_orphan_agents >/dev/null
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
  probe) CHATBOT_FORCE_PROBE=1; probe_message "${2:-5}"; mark_probe; reap_orphan_agents >/dev/null ;;
  repair|defibrillate|shock|cpr)
    export CHATBOT_FORCE_HOST=1
    cmd_repair
    ;;
  guard)
    guard_rlock
    guard_tickets
    ;;
  logs) shift || true; exec python3 "$CODE/logdigest.py" "$@" ;;
  *) echo "usage: $0 {start|stop|restart|status|doctor [--auto-repair]|probe|repair|defibrillate|guard|logs [--since 24h] [--sid ID] [--json] [-f]}"; exit 2 ;;
esac

