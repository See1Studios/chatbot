#!/bin/bash
# The one way to run this repo's tests (plan-execution-workflow pew/B). Hooks, the delegation
# runner's gates and CI call this script; do not add another test loop elsewhere.
#
#   ./run-tests.sh              every tests/test_*.py, one process per module
#   ./run-tests.sh --fast       guard tests only (FAST below), for the commit hook
#   ./run-tests.sh test_x ...   the named modules only
#
# One process per module: some modules leave globals changed, so `unittest discover` in a single
# process fails (README "Run tests"). Exit status is 0 only when every module passed.
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" || exit 2

# Guard tests: cheap, no network, no live service. They keep structure rules (docs, layout,
# neutrality, sizes) from rotting. Add a new guard test here in the same change that creates it.
FAST=(
  test_docs_budget
  test_code_layout
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
)
TIMEOUT="${TEST_TIMEOUT:-300}"

mods=()
if [ "${1:-}" = "--fast" ]; then
  mods=("${FAST[@]}")
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
