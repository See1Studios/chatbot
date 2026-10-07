# Engineering conventions

For every agent that changes engine code (`*.py`, `providers/`, `tools/`, `static/`, `tests/`). Not for how the chat
agent talks at runtime (that is the workspace charter). The rule registry in the root `AGENTS.md` lists each rule
with its enforcer; this file holds the numbers and the detail. A rule here without an enforcer says so.

## 1. Sections

| § | Rule | Enforcer |
|---|---|---|
| 2.1 | Test pairing | `.githooks/check_staged.py` commit-msg (TEST_PAIRING_v1), `test_githooks` |
| 2.2 | Size ceilings | `tests/test_file_sizes.py`, `tests/test_page_scripts.py` |
| 2.3 | Timeouts | `tests/test_conventions.py` |
| 2.4 | Work banter | manual |

## 2. Rules

### 2.1 Test pairing

A `feat`, `fix`, `refactor` or `perf` commit that changes code carries the test that shows the change, under `tests/`.
When no test can show it (CSS spacing, a rename the existing tests already cover), the commit says why in a trailer
line `No-Test: <why>`; the reason stays in history for review. Code and test files are defined once, in
`tools/review_checklist.py::is_code_file` and `is_test_file`; the delegation review warns with the same check.

### 2.2 Size ceilings

- Python module: `MAX_BYTES=80_000`. Python function: `FUNC_MAX_LINES=80`.
- Page script or stylesheet: 43,000 bytes (`tests/test_page_scripts.py`).
- Code already over a cap is pinned in its test's ceiling table and may not grow; lower the ceiling when you shrink
  it, never raise it. The tables are the backlog: there is no second list.
- Why: an agent reads a whole module and changes a whole function in one go; bytes track tokens.

### 2.3 Timeouts

Every blocking `subprocess` call (`run`, `check_output`, `check_call`, `call`) names an explicit `timeout`. There is no
single number: pick what the call needs (a `ps` gets 30 s, a test run minutes). Long model turns are watched by
`turn_watchdog.py` (QUOTA_FAILFAST, SILENT_HANG), not by a call timeout. The few legacy calls without one are listed,
with reasons, in `tests/test_conventions.py` and may only go away.

### 2.4 Work banter

In delegation, handoff, commit and report text, banter is one or two sentences at most; the rest is facts, diff, test
results, causes. No enforcer, on purpose: judging banter would mean matching words or sentences, which the engine does
not do (results must not depend on language or wording).
