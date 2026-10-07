# Governance propagation ledger

Read on demand, never injected. It tracks a new rule while it spreads through the code, and code drift that no guard
already tracks. Plan: [propagation-and-state-architecture.md](plans/archive/2026/propagation-and-state-architecture.md).

- Item progress lives in tickets; a rule's home is the root [RULES.md](../RULES.md).
  This file only lists what is in flight, with the ticket that carries each part.
- Drift a guard already pins is not copied here: oversized functions are `tests/test_file_sizes.py::FUNC_CEILINGS`,
  calls without a timeout are `tests/test_conventions.py::LEGACY_SUBPROCESS_EXEMPTIONS`, ratchets are
  `ratchet_baseline.json`. Those tables only shrink.
- Who-fields hold role ids (`dev`, `lead`, `claude-code`), never a character's name.

## Active

None.

Entry shape:

```markdown
### [DEV-PROP-nnn] <rule being spread>
- Source: <RULES.md section or registry row>; enforcer: <test>
- Parts: `<path>` -- #<ticket> (open | done <hash>)
```

## Drift no guard tracks

None.

Entry shape: `- [DRIFT-nnn] <path>::<symbol> -- <rule> -- found <date> by <role id> -- plan: <ticket or item>`

## Done

- [DEV-PROP-001] Governance documents and the convention checker: #720, #724, #726 (`5de6799`, `c5f89c9`), 2026-10-06.
- [DEV-PROP-002] Governance review 2026-10-07 (prop/E–H): green main, guarded enforcers, test pairing hook, dev and
  shipped instructions split, these documents trimmed: #766–#769.
