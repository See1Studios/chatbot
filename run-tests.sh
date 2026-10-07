#!/bin/bash
# The one way to run this repo's tests (plan-execution-workflow pew/B). Hooks, the delegation
# runner's gates and CI call this script; do not add another test loop elsewhere.
#
#   ./run-tests.sh              every tests/test_*.py, one process per module
#   ./run-tests.sh --fast       guard tests only (FAST below), for the commit hook
#   ./run-tests.sh test_x ...   the named modules only
#   ./run-tests.sh --one-process every module in one interpreter (split/A: a module that leaves a global or the
#                               environment changed breaks the modules after it -- this finds that)
#
# One process per module is the default: a failure stays in its own module and the times show per module. Since
# split/A the whole suite also passes in one process. Exit status is 0 only when every module passed.
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" || exit 2
# uds/F: shipped default data is ~/.pe. The suite never reads or writes an install's data: always the repo's own
# data/, whatever the caller exported (a chat agent inherits CHATBOT_DATA=~/.pe from ctl).
unset PE_HOME PRIVATEENGINE_HOME AGY_CHAT_DATA
export CHATBOT_DATA="$PWD/data"
export CHATBOT_TEST_RUNNER=1   # LIVE_DATA_GUARD_v1: host_config and tickets.py redirect a test run without this
# LIVE_AGENT_SUITE_v1: a live chat agent and its subagents (CHATBOT_LIVE_AGENT, set by session._spawn) run the guards
# or named modules, never the whole suite: it takes minutes, agy backgrounds it and waits, and the turn above it runs
# out of time (2026-10-05, handoff #5). The delegation runner's gates and the operator run the whole suite.
if [ -n "${CHATBOT_LIVE_AGENT:-}" ] && { [ $# -eq 0 ] || [ "${1:-}" = "--one-process" ]; }; then
  echo "run-tests.sh: a chat agent does not run the whole suite (minutes; the delegate gates run it)." >&2
  echo "Name the modules: ./run-tests.sh test_x test_y   (or --fast for the guards)" >&2
  exit 2
fi

# Guard tests: cheap, no network, no live service. They keep structure rules (docs, layout,
# neutrality, sizes) from rotting. Add a new guard test here in the same change that creates it.
FAST=(
  test_docs_budget
  test_code_layout
  test_code_map
  test_file_sizes
  test_page_scripts
  test_session_swap
  test_smoke
  test_provider_neutrality
  test_no_trace
  test_tool_format_clean
  test_bundle_budget
  test_static_assets
  test_entrypoints
  test_rule_registry
  test_plans_index
  test_doc_refs
  test_githooks
  test_doc_names
  test_ratchets
  test_edition_boundary
  test_data_paths
  test_migrate_user_data
  test_workspace_template
  test_import_cycles
  test_conventions
  test_core_standalone
  test_dev_role
  test_devlog_entry
  test_dialog_handoff
  test_identity_wiring
  test_live_agent_suite
  test_observations
  test_tickets
  test_unticketed_write
)
TIMEOUT="${TEST_TIMEOUT:-300}"

mods=()
if [ "${1:-}" = "--fast" ]; then
  mods=("${FAST[@]}")
elif [ "${1:-}" = "--one-process" ]; then
  ONE=1
  for f in tests/test_*.py; do mods+=("$(basename "$f" .py)"); done
elif [ $# -gt 0 ]; then
  for m in "$@"; do mods+=("$(basename "${m%.py}")"); done
else
  # The slowest modules start first so none of them is left running alone at the end (2026-10-05 times, seconds).
  SLOW=(test_worktree_runner test_ticket_quick test_art_manager test_lifecycle test_githooks test_platform_imports)
  mods=("${SLOW[@]}")
  for f in tests/test_*.py; do
    m="$(basename "$f" .py)"; [[ " ${SLOW[*]} " == *" $m "* ]] || mods+=("$m")
  done
fi

if [ "$(git config --get core.hooksPath 2>/dev/null)" != ".githooks" ]; then
  echo "warning: commit hooks are not installed; run: git config core.hooksPath .githooks"
elif [ ! -x .githooks/pre-commit ] || [ ! -x .githooks/commit-msg ]; then
  echo "warning: a commit hook is not executable, so git skips it; run: chmod +x .githooks/*"
fi

# Each run gets its own TMPDIR under /tmp and removes it at exit (2026-09-28: tests that never cleaned their
# tempfile dirs left ~114k folders in /tmp -- a small tmpfs -- until every inode was used and the whole host could
# not create a temp file). It stays under /tmp on purpose: under $HOME, tests saw the home directory's own git
# repository and behaved differently.
RUN_TMP="$(mktemp -d /tmp/chatbot-tests.XXXXXX)" || exit 2
export TMPDIR="$RUN_TMP"
export CHATBOT_EVENTS_DIR="$RUN_TMP/events"   # evt/B: tests never write the live event mailbox
export CHATBOT_DIALOGS_DIR="$RUN_TMP/dialogs" # inbox/B: nor the live dialogs and read positions
trap 'rm -rf "$RUN_TMP"' EXIT

if [ "${ONE:-}" = 1 ]; then
  timeout 900 python3 -m unittest "${mods[@]/#/tests.}"
  exit $?
fi

ms() { echo $(( $(date +%s%N) / 1000000 )); }
# PAR_SUITE_v1: modules run JOBS at a time (default: cores - 1; JOBS=1 is the old one-after-another run). Each
# module gets its own TMPDIR, event mailbox and dialogs dir so two modules never share a scratch file. A module's
# result line prints when it finishes; the summary and exit status are the same as before.
JOBS="${JOBS:-$(( $(nproc 2>/dev/null || echo 2) - 1 ))}"
[ "$JOBS" -ge 1 ] 2>/dev/null || JOBS=1
run_one() {
  local m="$1" dir="$RUN_TMP/m/$1" s d rc out why
  mkdir -p "$dir/tmp"
  if [ ! -f "tests/$m.py" ]; then
    echo "MISSING $m (no tests/$m.py)" > "$dir/line"; echo 1 > "$dir/rc"; return
  fi
  s=$(ms)
  out=$(TMPDIR="$dir/tmp" CHATBOT_EVENTS_DIR="$dir/events" CHATBOT_DIALOGS_DIR="$dir/dialogs" \
        timeout "$TIMEOUT" python3 -m unittest "tests.$m" 2>&1)
  rc=$?
  d=$(( $(ms) - s ))
  if [ $rc -eq 0 ]; then
    printf 'ok   %6dms %s\n' "$d" "$m" > "$dir/line"
  else
    [ $rc -eq 124 ] && why="timeout ${TIMEOUT}s" || why="exit $rc"
    { printf 'FAIL %6dms %s (%s)\n' "$d" "$m" "$why"; echo "$out" | tail -n 15 | sed 's/^/     | /'; } > "$dir/line"
  fi
  rm -rf "$dir/tmp" "$dir/events" "$dir/dialogs"
  echo "$rc" > "$dir/rc"   # written last: its presence means the line is complete
}
failed=()
t0=$(ms)
running=()
reap() {   # print every finished module's line; bash 4.4 has no `wait -n -p`, so a module reports through its rc file
  local m left=()
  for m in "${running[@]}"; do
    if [ -f "$RUN_TMP/m/$m/rc" ]; then
      cat "$RUN_TMP/m/$m/line"
      [ "$(cat "$RUN_TMP/m/$m/rc")" = 0 ] || failed+=("$m")
    else
      left+=("$m")
    fi
  done
  running=("${left[@]}")
}
for m in "${mods[@]}"; do
  while [ "${#running[@]}" -ge "$JOBS" ]; do wait -n 2>/dev/null; reap; done
  run_one "$m" &
  running+=("$m")
done
while [ "${#running[@]}" -gt 0 ]; do wait -n 2>/dev/null || sleep 0.2; reap; done

echo "---"
echo "$(( ${#mods[@]} - ${#failed[@]} ))/${#mods[@]} modules passed in $(( ($(ms) - t0) / 1000 ))s"
if [ ${#failed[@]} -gt 0 ]; then
  echo "failed: ${failed[*]}"
  echo "rerun one: ./run-tests.sh ${failed[0]}"
  exit 1
fi
