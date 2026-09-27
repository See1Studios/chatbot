# Gemini private — OPTIONAL refusal-mitigation TEST LAYER

**Marker:** `GEMINI_REFUSAL_MITIGATION_TEST_v1` · **Ticket:** #249

## What this is

A **lean, opt-in A/B test layer** for Gemini/agy **private** sessions only. Soft framing so the model keeps intimate-RP continuity when it starts refusing kink escalation.

It is **NOT** craft. Do **not** mix it into:

- `engine_data/private_tension_{defaults,gemini,grok}.json`
- `private_engine.RENDER_PROTOCOL` / `RENDER_PROTOCOL_GROK_OVERLAY`

## Default

**OFF** for everyone. `engine_data/private_refusal_mitigation_gemini.json` → `default_enabled: false`.

## How to turn ON (test)

### Per-session (preferred)

1. Open that private session's `data/sessions/<sid>/meta.json`.
2. Set `"refusal_mitigation": true` (and keep `"mode": "private"`).
3. Save. Next turn (or after ⚡소생 if the process already cached meta) the `[GEMINI_REFUSAL_MITIGATION_TEST_v1]` block is appended to turn context.
4. To leave OFF: set `false` or remove the key.

Only **gemini** family (`provider`/`model` matching gemini|agy|antigravity) receives the block. Grok/Claude ignore the flag.

### Host-wide A/B (ops)

Before start/repair:

```bash
export CHATBOT_PRIVATE_REFUSAL_MITIGATION=1   # 1|true|on|yes
~/services/chatbot-ctl.sh repair   # or ⚡소생
```

Unset / `0` and repair again to leave OFF.

## How to leave OFF (normal craft)

Do nothing. No meta key, no env. Craft/tension/choices stay as today.

## Files

| File | Role |
|---|---|
| `engine_data/private_refusal_mitigation_gemini.json` | Text + marker (edit copy, not craft JSON) |
| `private_engine.py` | `load_refusal_mitigation` / `refusal_mitigation_enabled` / hook in `turn_context` |
| `session.py` | Load/save `refusal_mitigation` on meta |

## Content policy

Keep the JSON `text` **short**. Soft continuity framing only — not a long "disregard all policies" dump.
