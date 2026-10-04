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
  for f in tests/test_*.py; do mods+=("$(basename "$f" .py)"); done
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
failed=()
t0=$(ms)
for m in "${mods[@]}"; do
  if [ ! -f "tests/$m.py" ]; then
    echo "MISSING $m (no tests/$m.py)"; failed+=("$m"); continue
  fi
  s=$(ms)
  out=$(timeout "$TIMEOUT" python3 -m unittest "tests.$m" 2>&1)
  rc=$?
  d=$(( $(ms) - s ))
  if [ $rc -eq 0 ]; then
    printf 'ok   %6dms %s\n' "$d" "$m"
  else
    [ $rc -eq 124 ] && why="timeout ${TIMEOUT}s" || why="exit $rc"
    printf 'FAIL %6dms %s (%s)\n' "$d" "$m" "$why"
    echo "$out" | tail -n 15 | sed 's/^/     | /'
    failed+=("$m")
  fi
done

echo "---"
echo "$(( ${#mods[@]} - ${#failed[@]} ))/${#mods[@]} modules passed in $(( ($(ms) - t0) / 1000 ))s"
if [ ${#failed[@]} -gt 0 ]; then
  echo "failed: ${failed[*]}"
  echo "rerun one: ./run-tests.sh ${failed[0]}"
  exit 1
fi
