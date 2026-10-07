# Rules

Every rule for agents that change this repo. Code names are relative to `engine/`. The entry is the root `AGENTS.md`; it lists the rules you must not
break and points here for the rest. Conventions first (the numbers and how-to), then the registry: each rule with the
test or gate that fails when it is broken.

## Conventions

### Test pairing

A `feat`, `fix`, `refactor` or `perf` commit that changes code carries the test that shows the change, under `tests/`.
When no test can show it (CSS spacing, a rename the existing tests already cover), the commit says why in a trailer
line `No-Test: <why>`; the reason stays in history for review. Code and test files are defined once, in
`tools/review_checklist.py::is_code_file` and `is_test_file`; the delegation review warns with the same check.

### Size ceilings

- Python module: `MAX_BYTES=80_000`. Python function: `FUNC_MAX_LINES=80`.
- Page script or stylesheet: 43,000 bytes (`tests/test_page_scripts.py`).
- Code already over a cap is pinned in its test's ceiling table and may not grow. Lower the ceiling when you shrink
  it, never raise it. The tables are the backlog: there is no second list.
- Why: an agent reads a whole module and changes a whole function in one go; bytes track tokens.

### Timeouts

Every blocking `subprocess` call (`run`, `check_output`, `check_call`, `call`) names an explicit `timeout`. There is no
single number: pick what the call needs (a `ps` gets 30 s, a test run minutes). Long model turns are watched by
`turn_watchdog.py`, not by a call timeout.

### Work banter

In delegation, handoff, commit and report text, banter is one or two sentences at most; the rest is facts, diff, test
results, causes. No enforcer, on purpose: judging banter would mean matching words or sentences, which the engine does
not do.

### Naming

- Standing documents (one copy, always current) are UPPERCASE: `AGENTS.md`, `RULES.md`, `CONCEPT.md`,
  `SKILL.md`, `ROLE.md`, `PROCEDURE.md`, ...
- Documents that accumulate are lower-kebab: `docs/plans/*.md` (`INDEX.md` excepted), `docs/history/YYYY-MM-DD.md`.
- No snake_case document names.
- Renaming a document: update every live link in the same change. Leave history (HISTORY, `docs/history/`, archives,
  ticket records) as written.

### Harness

- Default provider `agy`. Registry `providers/adapters.py::AGENT_ADAPTERS`; a session restores its provider from
  `meta.json`. Provider- or harness-specific rules live in the adapter or `chatbot-ctl.sh`, nowhere else.
- Spawned agents see only `services/chatbot` and `<web root>/chat` (`host_config.py::ADD_DIRS`). Never add the home
  dir, `.hermes`, the whole web root or `services`. Widen minimally and say why in DEVLOG.

### Release

This repository is private. Treat a release as a reviewed source snapshot; never include personal data, credentials, or runtime state.

Cut a release later:

1. Set the intended release version in engine/VERSION, for example 1.0.0.
2. Write the version's user-visible changes into CHANGELOG.md (made from the commits since the last tag; HISTORY.md is
   the work diary, not release notes).
3. Run the test entry point: engine/run-tests.sh. Then run engine/chatbot-ctl.sh repair and confirm its smoke checks pass.
4. Review the complete diff and tracked file list. Do not stage data/, secrets.env, session files, tokens, keys, or other private runtime output; release files must contain no secrets.
5. Commit the reviewed release changes.
6. Create an annotated local tag matching VERSION: git tag -a vVERSION -m Release-vVERSION. Verify it with git show vVERSION. Publishing a tag is a separate, explicitly approved step.

The current development snapshot is 0.0.0-dev; this procedure does not publish tags.

## Propagation ledger

Read on demand, never injected. It tracks a new rule while it spreads through the code, and code drift that no guard
already tracks. Plan: [propagation-and-state-architecture.md](docs/plans/archive/2026/propagation-and-state-architecture.md).

- Item progress lives in tickets; a rule's home is this file.
  This file only lists what is in flight, with the ticket that carries each part.
- Drift a guard already pins is not copied here: oversized functions are `tests/test_file_sizes.py::FUNC_CEILINGS`,
  calls without a timeout are `tests/test_conventions.py::LEGACY_SUBPROCESS_EXEMPTIONS`, ratchets are
  `ratchet_baseline.json`. Those tables only shrink.
- Who-fields hold role ids (`dev`, `lead`, `claude-code`), never a character's name.

### Active

None.

Entry shape:

```markdown
### [DEV-PROP-nnn] <rule being spread>
- Source: <RULES.md section or registry row>; enforcer: <test>
- Parts: `<path>` -- #<ticket> (open | done <hash>)
```

### Drift no guard tracks

None.

Entry shape: `- [DRIFT-nnn] <path>::<symbol> -- <rule> -- found <date> by <role id> -- plan: <ticket or item>`

### Done

- [DEV-PROP-001] Governance documents and the convention checker: #720, #724, #726 (`5de6799`, `c5f89c9`), 2026-10-06.
- [DEV-PROP-002] Governance review 2026-10-07 (prop/E–H): green main, guarded enforcers, test pairing hook, dev and
  shipped instructions split, these documents trimmed: #766–#769.

## Rules

- Audience in the registry: **all** = every agent changing this repo, including the PE chat agent doing engine work.
- Enforcer: the test or gate that fails when the rule is broken. `manual` means none yet; a planned one follows in
  parentheses. `tests/test_rule_registry.py` checks that each named enforcer exists, is Tier 3 and runs on commit.
- Add a rule in the same change that adds its enforcer. A rule without one says `manual` and why.

| Rule | Audience | Enforcer |
|---|---|---|
| Work starts from the operator's words or an approved, claimed ticket; claim names the paths | all | `test_tickets` (release refuses dirty paths); `test_unticketed_write` (PE sessions: a visible unticketed write stops the turn, any other change to the tree is held) |
| A live chat agent and its subagents run the guards or named test modules, never the whole suite | PE chat agent only | `test_live_agent_suite` (`run-tests.sh` refuses when `CHATBOT_LIVE_AGENT` is set; unittest/pytest around the script is refused too) |
| A test run never gets an install's data: outside `run-tests.sh` a unittest/pytest process is pointed at the repo's `data/` | all | `test_live_agent_suite` (`host_config.test_run_outside_runner`, `tickets.py::_data_dir`) |
| A handoff chain from one request is at most two hops; a director has one open handoff at a time | PE chat agent only | `test_dialog_handoff` |
| A delegated worker cannot change its own pass condition (guard tests, `run-tests.sh`) | all | `test_worktree_runner` |
| The shipped build never touches engine code: no `run_command`/`ticket`/`delegate`, file tools reach user data only; the edition is decided only by `host_config.EDITION` | all | `test_edition_boundary` |
| Guard tests green before commit (`engine/run-tests.sh --fast`); full suite before release | all | `.githooks/check_staged.py` (pre-commit); `test_worktree_runner` (runner gates: guards + related tests); `test_tickets` (done refused while guards fail) |
| Conventional Commits subject; `Plan:` trailer when `docs/plans/` changes | all | `test_githooks` (commit-msg hook) |
| `Ticket:` trailer, own author name | all | `test_githooks` (commit-msg: a feat/fix/refactor/perf commit without `Ticket: #n` is refused; on a `worktree/ticket-n` branch it is written in); author name: `test_githooks` (pre-commit: never a character's name; a live chat session commits as the app `PE`) |
| A live chat session never lands a worker's branch on main (landing is the operator's) | all | `test_githooks` (`.githooks/reference-transaction`) |
| A merged delegation leaves its line in `HISTORY.md` | all | `test_history_entry` (the runner writes it with the ticket record, `tools/history_entry.py`) |
| A ticket names the agent doing the work (`--actor`), never `unknown-cli`; who-fields hold role ids, not persona names | all | `test_ticket_quick` (ticket-quick records nothing when neither `--actor` nor the parent processes name the agent); `test_tickets` (`tickets.py` refuses a non-role-id actor at write time). A romanized nickname (`nono`) passes the role-id shape: manual |
| No secrets, `.env`, private memory or style references in commits | all | `test_githooks` (pre-commit hook) |
| Never `--no-verify`; hooks installed (`core.hooksPath=.githooks`) and executable | all | manual (run-tests.sh warns); backstops `test_worktree_runner`, `test_tickets` |
| Data paths only through `host_config` (`DATA_ENV` order; `tickets.py` mirrors it) | all | `test_data_paths` |
| Python module ≤ 80,000 bytes; Python function ≤ 80 lines; listed ceilings only go down | all | `test_file_sizes` (numbers: Conventions above) |
| Size numbers in this file match the size guard (80 lines, 80,000 bytes) | all | `test_conventions` |
| Blocking `subprocess` calls (`run`, `check_output`, `check_call`, `call`) name an explicit `timeout` (legacy allowlist in the test) | all | `test_conventions` |
| Test pairing: a feat/fix/refactor/perf commit that changes code carries `tests/`, or a `No-Test: <why>` trailer says why not | all | `test_githooks` (commit-msg hook, TEST_PAIRING_v1; code/test definition `tools/review_checklist.py`, which also warns in the delegation review) |
| Work banter in delegation / handoff / commit reports ≤ 1-2 sentences (Conventions above) | all | manual (a check would have to match words or sentences, which the language rule below bars) |
| Page script or stylesheet ≤ 43,000 bytes; listed ceilings only go down | all | `test_page_scripts` |
| New code folder is protected (`tools/` too: the delegation gate's verdict reader is governance) | all | `test_code_layout` |
| Every code file (`engine/`, its `providers/` and `tools/`, `static/`) has a row in `CODEMAP.md` before it lands | all | `test_code_map` |
| Core modules import stdlib + each other only | all | `test_core_standalone` |
| The repo root and the engine folder are decided only in `repo_layout.py` (code) and `tests/_paths.py` (tests); no code finds `static/`, `templates/`, `tests/` or `docs/` from its own file | all | `test_code_layout` |
| No new pair of modules that import each other (top or inside a function); the known pairs only go away | all | `test_import_cycles` |
| No provider names in common code | all | `test_provider_neutrality` |
| Persona names/titles are display values, never ids or keys | all | `test_identity_wiring` |
| Injected instruction bundles within `bundle_budget.json` | all | `test_bundle_budget` |
| Every plan file has one INDEX row with a valid status | all | `test_plans_index` |
| HISTORY stays small; old dates in `docs/history/` | all | `test_docs_budget` |
| Docs cite code as `path` or `path::symbol`, never line numbers; links resolve | all | `test_doc_refs` |
| Tool-named entry files (`CLAUDE.md`, `GEMINI.md`) only point to `AGENTS.md`; no new invented entry files | all | `test_entrypoints` |
| `AGENTS.md` is the dev-build entry only: at most 6,000 bytes, no chat-runtime conventions. The repo root holds the entry files and the standing documents (guidance: `RULES.md`, `CODEMAP.md`, `ARCHITECTURE.md`, `OPERATIONS.md`; project: `README.md`, `CONCEPT.md`, `PRODUCT.md`, `DESIGN.md`, `HISTORY.md`); `docs/` holds folders only | all | `test_entrypoints` |
| Document names: standing UPPERCASE, accumulating lower-kebab, no snake_case | all | `test_doc_names` |
| Every registry row names an audience and a real enforcer | all | `test_rule_registry` |
| Every enforcer is Tier 3 (`protected_paths.json` governance) and runs on each commit (`run-tests.sh` FAST), or is listed slow with where it runs instead | all | `test_rule_registry` |
| No new hardcoded Korean in engine/page code (i18n catalogs instead); mark intended lines `l10n-ok` | all | `test_ratchets` (`ratchet_baseline.json`) |
| No new host/persona identity (DiskStation, `/volume1`, Sphere, 실장님, 냥) in engine code outside the host plugin | all | `test_ratchets` |
| Tracked workspace template twins (repo `data/workspace` when present) are classified in `templates/workspace-manifest.json`; `same` pairs stay byte-equal; the template names no host and no engine work | all | `test_workspace_template` |
| Observations only via `observations.add` / the `observation` tool | all | `test_observations` (shape) |
| Speak with the operator in Korean. Agent guidance (`AGENTS.md`, `RULES.md`, `CODEMAP.md`, `ARCHITECTURE.md`, `OPERATIONS.md`, charters, role packs, skills) in plain English; project documents (`CONCEPT.md`, `PRODUCT.md`, `DESIGN.md`, plans, `HISTORY.md`) may be Korean | all | manual (chat-agent runtime voice stays in workspace charter, not here) |
| Agent-facing machine text (prompts, tool strings, LEARNED lines) in English | all | manual |
| Check each request against project goals; reject or propose re-scoping when it does not fit | all | manual (plan gate G2, DoR) |
| Look for prior art before building (`~/AGENTS.md` §0) | all | manual |
| The engine decides what code can settle (tool choice, argument shape, format, classification); the model keeps only the character's words and acts | all | manual (plan `docs/plans/engine-decides.md`; failure rates from `logs/events.jsonl`) |
| Results never depend on language or the model's wording: no word or phrase matching, no guessing at model text; show engine facts and the text as is | all | manual (review; the l10n ratchet in `test_ratchets` catches hardcoded Korean only) |
| Spawn-visible dirs stay minimal (`ADD_DIRS`) | all | manual |
| Engine-work rules for the chat agent live in the `dev` role pack, never the shared charter or another role's `role.md` | PE chat agent only | `test_dev_role` |
| Dev and shipped instructions never mix: one shipped charter for both builds; dev-build rules only in `DEV-CHARTER.md`, injected only when `host_config.EDITION` is dev; neither file repeats the other; a shipped bundle names no dev tool; a shipped role pack names only skills that ship | all | `test_edition_instructions`, `test_workspace_template` |

