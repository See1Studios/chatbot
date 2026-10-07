#!/usr/bin/env python3
"""tools/card_gen.py – character card generation & refinement tool.

Port of ST-CardGen ``routes/character.ts`` domain and business logic to Python:
  - Generates Chara V2 cards + extensions.chatbot from one-line ideas.
  - Surgically fills missing fields (pick_missing_keys, filter_patch_to_missing).
  - Selectively regenerates target fields with UUID regen_nonce and a 3-attempt
    substantive change verification loop (equal_normalized).
  - Weaves visual.md conforming to Private Engine visual lock sheet specs.
  - Creates <workspace>/characters/<id>/ package structure.

Pure stdlib where possible; integrates with card_prompt.py and card_parse.py.
See docs/plans/archive/2026/character-generation-system.md §1.4 & §2 for architecture.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import card_parse  # noqa: E402
import card_prompt  # noqa: E402
import platform_compat  # noqa: E402

# ── Canonical Field Synonyms & Mappings ─────────────────────────────

ALIAS_MAP: Dict[str, str] = {
    "first_mes": "first_message",
    "mes_example": "message_examples",
}
CANONICAL_TO_CHARA_V2: Dict[str, str] = {
    "first_message": "first_mes",
    "message_examples": "mes_example",
}

DEFAULT_STYLE_ANCHOR = (
    "clean thin line art, crisp cel shading, subtle flat color tones, "
    "soft studio key lighting, high-end 2D anime illustration"
)
DEFAULT_NEGATIVE_LOCK = (
    "bad anatomy, bad hands, 3d render, photorealistic, watermark, text"
)


# ── Internal Path & ID Helpers ─────────────────────────────────────

def _get_characters_dir(ws: Optional[Union[str, Path]] = None) -> Path:
    """Return characters directory path, defaulting to workspace."""
    if ws is not None:
        return Path(ws) / "characters"
    try:
        import characters
        return characters.characters_dir()
    except Exception:
        from host_config import WORKSPACE
        return WORKSPACE / "characters"


def _new_character_id() -> str:
    """Generate a new TypeID identifier for characters."""
    try:
        import characters
        return characters.new_id()
    except Exception:
        import secrets
        import time
        b32 = "0123456789abcdefghjkmnpqrstvwxyz"
        ms = int(time.time() * 1000)
        r = secrets.randbits(74)
        rand_a, rand_b = (r >> 62) & 0xFFF, r & ((1 << 62) - 1)
        raw_uuid = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
        suffix = "".join(b32[(raw_uuid >> (5 * (25 - i))) & 31] for i in range(26))
        return f"char_{suffix}"


# ── Card Data Accessors ────────────────────────────────────────────

def is_chara_v2(card: Any) -> bool:
    """Return True if card adheres to Chara V2 wrapper structure."""
    return (
        isinstance(card, dict)
        and card.get("spec") == "chara_card_v2"
        and isinstance(card.get("data"), dict)
    )


def get_card_data(card: Dict[str, Any]) -> Dict[str, Any]:
    """Return the inner data dict if card is a Chara V2 wrapper, else card itself."""
    if is_chara_v2(card):
        return card["data"]
    return card


def get_field_value(data: Dict[str, Any], key: str) -> Any:
    """Get field value from dict, checking canonical, alias names, and extensions.chatbot."""
    if not isinstance(data, dict):
        return None

    if key in data:
        return data[key]
    alias = ALIAS_MAP.get(key)
    if alias and alias in data:
        return data[alias]
    reverse_alias = CANONICAL_TO_CHARA_V2.get(key)
    if reverse_alias and reverse_alias in data:
        return data[reverse_alias]

    ext = data.get("extensions")
    if isinstance(ext, dict):
        chatbot = ext.get("chatbot")
        if isinstance(chatbot, dict):
            if key in chatbot:
                return chatbot[key]
            if alias and alias in chatbot:
                return chatbot[alias]
            if reverse_alias and reverse_alias in chatbot:
                return chatbot[reverse_alias]

    inner = data.get("data")
    if isinstance(inner, dict):
        return get_field_value(inner, key)

    return None


def is_field_empty(val: Any) -> bool:
    """Check whether a field value is empty or missing."""
    if val is None:
        return True
    if isinstance(val, str):
        return not val.strip()
    if isinstance(val, (list, tuple, dict, set)):
        return len(val) == 0
    return False


# ── Filtering & Missing Field Logic (routes/character.ts port) ──────

def pick_missing_keys(
    card: Dict[str, Any],
    keys: Optional[Sequence[str]] = None,
) -> List[str]:
    """Identify keys that are empty or missing in the card.

    Checks keys in ``keys`` (defaults to ``card_prompt.CARD_FIELDS``).
    Operates transparently on flat card dicts or Chara V2 packages.
    """
    data = get_card_data(card)
    candidates = keys if keys is not None else card_prompt.CARD_FIELDS
    missing: List[str] = []
    for k in candidates:
        val = get_field_value(data, k)
        if is_field_empty(val):
            missing.append(k)
    return missing


def filter_patch_to_missing(
    patch: Dict[str, Any],
    missing_keys: Sequence[str],
) -> Dict[str, Any]:
    """Filter patch dict so it contains only keys from missing_keys with non-empty values.

    Drops any extraneous or hallucinated fields to prevent card corruption.
    Normalises aliases to match the requested missing key.
    """
    clean: Dict[str, Any] = {}
    for key in missing_keys:
        val = get_field_value(patch, key)
        if not is_field_empty(val):
            clean[key] = val
    return clean


def filter_patch_to_targets(
    patch: Dict[str, Any],
    target_keys: Sequence[str],
) -> Dict[str, Any]:
    """Filter patch dict so it contains only keys in target_keys with non-empty values."""
    clean: Dict[str, Any] = {}
    for key in target_keys:
        val = get_field_value(patch, key)
        if not is_field_empty(val):
            clean[key] = val
    return clean


# ── Normalisation & Equality Check (equalNormalized port) ──────────

def _normalize_string(val: str) -> str:
    """Normalize string by collapsing all whitespace into a single space and trimming."""
    return re.sub(r"\s+", " ", val).strip()


def equal_normalized(a: Any, b: Any) -> bool:
    """Compare two values for substantive semantic equality after normalization.

    Handles strings, lists, dicts, and None/empty equivalencies.
    """
    if is_field_empty(a) and is_field_empty(b):
        return True
    if is_field_empty(a) != is_field_empty(b):
        return False

    if isinstance(a, str) and isinstance(b, str):
        return _normalize_string(a) == _normalize_string(b)

    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(equal_normalized(x, y) for x, y in zip(a, b))

    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(equal_normalized(a[k], b[k]) for k in a)

    return a == b


# ── Orchestration & LLM Calling ────────────────────────────────────

def _parse_llm_response(raw: str) -> Dict[str, Any]:
    """Parse raw LLM output into a dictionary using JSON or tagged fallback."""
    parsed = card_parse.try_parse_json(raw)
    if isinstance(parsed, dict):
        return parsed
    sections = card_parse.parse_tagged_sections(raw)
    if sections:
        return card_parse.build_character_from_tagged(sections)
    return {}


def regenerate_fields(
    idea: str,
    card: Dict[str, Any],
    target_keys: Sequence[str],
    llm_call: Callable[[str, str], str],
    *,
    profile: str = "detailed",
    max_retries: int = 3,
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
    raise_on_failure: bool = False,
) -> Dict[str, Any]:
    """Regenerate specific target keys with substantive change verification.

    Performs up to max_retries attempts, injecting a UUID regen_nonce into each
    prompt. Verifies that at least one target key has substantively changed
    using equal_normalized. Returns the filtered patch dict.
    """
    if not target_keys:
        return {}

    existing_data = get_card_data(card)
    last_patch: Dict[str, Any] = {}

    for _ in range(max_retries):
        regen_nonce = str(uuid.uuid4())
        sys_prompt, user_prompt = card_prompt.build_regenerate_prompt(
            idea,
            existing_data,
            list(target_keys),
            profile=profile,
            regen_nonce=regen_nonce,
            overrides=overrides,
        )
        raw = llm_call(sys_prompt, user_prompt)
        parsed = _parse_llm_response(raw)
        filtered = filter_patch_to_targets(parsed, target_keys)
        last_patch = filtered

        any_different = False
        for key in target_keys:
            if key in filtered:
                old_val = get_field_value(existing_data, key)
                new_val = filtered[key]
                if not equal_normalized(old_val, new_val):
                    any_different = True
                    break

        if any_different:
            return filtered

    if raise_on_failure:
        raise RuntimeError(
            f"Failed to produce substantially different fields after {max_retries} attempts"
        )
    return last_patch


def fill_missing_fields(
    idea: str,
    card: Dict[str, Any],
    llm_call: Callable[[str, str], str],
    *,
    missing_keys: Optional[Sequence[str]] = None,
    profile: str = "detailed",
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """Fill missing or empty fields of an existing card.

    Identifies missing keys via pick_missing_keys, queries LLM,
    and returns a filtered patch containing only the filled missing keys.
    """
    existing_data = get_card_data(card)
    missing = pick_missing_keys(existing_data, missing_keys)
    if not missing:
        return {}

    sys_prompt, user_prompt = card_prompt.build_fill_missing_prompt(
        idea,
        existing_data,
        missing,
        profile=profile,
        overrides=overrides,
    )
    raw = llm_call(sys_prompt, user_prompt)
    parsed = _parse_llm_response(raw)
    return filter_patch_to_missing(parsed, missing)


def generate_card_data(
    idea: str,
    llm_call: Callable[[str, str], str],
    *,
    profile: str = "detailed",
    use_default_negative: bool = True,
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """Generate raw character card fields from an idea string using LLM."""
    sys_prompt, user_prompt = card_prompt.build_character_gen_prompt(
        idea,
        profile=profile,
        overrides=overrides,
        use_default_negative=use_default_negative,
    )
    raw = llm_call(sys_prompt, user_prompt)
    data = card_parse.parse_character_response(raw)
    if use_default_negative and is_field_empty(data.get("negative_prompt")):
        data["negative_prompt"] = card_prompt.DEFAULT_NEGATIVE_PROMPT
    return data


# ── Card & Visual Weaving (PE Specs) ───────────────────────────────

def _format_message_examples(val: Any) -> str:
    """Format dialogue examples into a single string for Chara V2 mes_example."""
    if isinstance(val, str):
        return val
    if isinstance(val, (list, tuple)):
        return "\n\n".join(str(x) for x in val if str(x).strip())
    return ""


def apply_patch(card: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply filtered patch dict to card, respecting Chara V2 vs flat card schemas.

    - For Chara V2 cards:
      * Maps canonical keys (first_message -> first_mes, message_examples -> mes_example).
      * Formats message_examples to string via _format_message_examples.
      * Writes image_prompt and negative_prompt to data.extensions.chatbot.
      * Removes extraneous canonical keys from data top-level.
    - For flat cards:
      * Preserves existing key names (or patch keys if not present).
    """
    if not isinstance(card, dict) or not isinstance(patch, dict):
        return card

    if is_chara_v2(card):
        data = card["data"]
        ext = data.setdefault("extensions", {})
        chatbot = ext.setdefault("chatbot", {})

        for k, v in patch.items():
            if k in ("image_prompt", "negative_prompt"):
                chatbot[k] = str(v).strip() if isinstance(v, str) else v
                data.pop(k, None)
                continue

            v2_key = CANONICAL_TO_CHARA_V2.get(k, k)
            if v2_key == "mes_example":
                data["mes_example"] = _format_message_examples(v).strip()
                data.pop("message_examples", None)
            elif v2_key == "first_mes":
                data["first_mes"] = str(v).strip() if isinstance(v, str) else v
                data.pop("first_message", None)
            elif v2_key == "tags" and isinstance(v, str):
                data["tags"] = [t.strip() for t in v.split(",") if t.strip()]
            elif v2_key == "alternate_greetings" and isinstance(v, str):
                data["alternate_greetings"] = [v.strip()] if v.strip() else []
            elif isinstance(v, str):
                data[v2_key] = v.strip()
            else:
                data[v2_key] = v
        return card

    for k, v in patch.items():
        target_key = k
        if k not in card:
            alias = ALIAS_MAP.get(k)
            rev = CANONICAL_TO_CHARA_V2.get(k)
            if alias and alias in card:
                target_key = alias
            elif rev and rev in card:
                target_key = rev

        if target_key in ("mes_example", "message_examples"):
            card[target_key] = _format_message_examples(v).strip()
        elif isinstance(v, str):
            card[target_key] = v.strip()
        else:
            card[target_key] = v

    return card


def build_chara_v2_card(
    fields: Dict[str, Any],
    *,
    user_title: str = "코치",  # l10n-ok
    voice: str = "",
    role: str = "",
    creator: str = "card_gen",
    character_version: str = "1.0",
    extra_extensions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap raw character fields into Chara V2 specification with extensions.chatbot."""
    ext_chatbot: Dict[str, Any] = {
        "display": {
            "user_title": user_title,
            "voice": voice,
        },
    }
    if role:
        ext_chatbot["role"] = role
    if not is_field_empty(fields.get("image_prompt")):
        ext_chatbot["image_prompt"] = str(fields["image_prompt"]).strip()
    if not is_field_empty(fields.get("negative_prompt")):
        ext_chatbot["negative_prompt"] = str(fields["negative_prompt"]).strip()

    extensions: Dict[str, Any] = {"chatbot": ext_chatbot}
    if extra_extensions:
        for k, v in extra_extensions.items():
            if k == "chatbot" and isinstance(v, dict):
                extensions["chatbot"].update(v)
            else:
                extensions[k] = v

    alt_greetings = fields.get("alternate_greetings") or []
    if isinstance(alt_greetings, str):
        alt_greetings = [alt_greetings.strip()] if alt_greetings.strip() else []

    tags = fields.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    first_mes = str(fields.get("first_mes") or fields.get("first_message") or "")
    mes_ex = _format_message_examples(fields.get("mes_example") or fields.get("message_examples") or "")

    data: Dict[str, Any] = {
        "name": str(fields.get("name") or "").strip(),
        "description": str(fields.get("description") or "").strip(),
        "personality": str(fields.get("personality") or "").strip(),
        "scenario": str(fields.get("scenario") or "").strip(),
        "first_mes": first_mes.strip(),
        "mes_example": mes_ex.strip(),
        "creator_notes": str(fields.get("creator_notes") or "").strip(),
        "system_prompt": str(fields.get("system_prompt") or "").strip(),
        "post_history_instructions": str(fields.get("post_history_instructions") or "").strip(),
        "alternate_greetings": list(alt_greetings),
        "tags": list(tags),
        "creator": creator,
        "character_version": character_version,
        "extensions": extensions,
    }

    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": data,
    }


def build_visual_md(
    name: str,
    cid: str,
    *,
    card: Optional[Dict[str, Any]] = None,
    style_anchor: str = "",
    character_anchor: str = "",
    negative_lock: str = "",
) -> str:
    """Generate visual lock sheet conforming to PE visual.md anchor specification."""
    display_name = (name or cid).strip() or "character"
    card_data = get_card_data(card or {})

    style = (style_anchor or DEFAULT_STYLE_ANCHOR).strip()

    char_anchor = character_anchor.strip()
    if not char_anchor and card_data:
        char_anchor = card_prompt.build_image_prompt(card_data)
    if not char_anchor:
        char_anchor = display_name

    neg_lock = negative_lock.strip()
    if not neg_lock and card_data:
        neg_val = card_data.get("negative_prompt") or get_field_value(card_data, "negative_prompt")
        if not is_field_empty(neg_val):
            neg_lock = str(neg_val).strip()
    if not neg_lock:
        neg_lock = DEFAULT_NEGATIVE_LOCK

    return f"""# {display_name} visual lock sheet

Format and procedure: skill `character-art`. The page uses this folder (`avatar.webp`).
Voice and manner are in the card, not here.

## Locks
- Generated by card_gen from prompt idea.
- Base look: Reference `avatar_master.png`.

## Prompt Specification (SSOT)
Modern anime standard (thin clean lineart, crisp cel shading):

### 1. Style Anchor
- `{style}`

### 2. Character Anchor ({display_name})
- `{char_anchor}`

### 3. Generation Rule
- **Master Image Required:** Once `avatar_master.png` is approved, NEVER generate new expressions or outfits from scratch with pure text prompts.
- **Reference-based Inpainting / I2I:** All expressions, wigs, and gestures MUST use `avatar_master.png` as the reference image, modifying only the target region.

### 4. Framing & Composition
- **avatar.webp (512x512):** `full-bleed close-up, front-facing, face centered, 56px circle crop safe`
- **sprites/bust (1024x1024):** `medium close-up, cut at shoulders, centered, transparent background`
- **sprites/full (1024x2048):** `full body shot, standing grounded 2% from bottom, centered, transparent background`

### 5. Negative Lock
- `{neg_lock}`

## Wigs (optional)
| Brain | Hair (cut + dye) | Outfit |
|---|---|---|

## Sprites (optional)
| Framing | Labels made | Notes |
|---|---|---|

## Rejected

## Open
"""


# ── Directory Package Creation ─────────────────────────────────────

def save_character_package(
    card_dict: Dict[str, Any],
    visual_md: str,
    *,
    ws: Optional[Union[str, Path]] = None,
    cid: Optional[str] = None,
) -> Dict[str, Any]:
    """Create <workspace>/characters/<id>/ package with card.json and visual.md."""
    char_id = cid or _new_character_id()
    char_dir = _get_characters_dir(ws) / char_id
    char_dir.mkdir(parents=True, exist_ok=True)

    card_file = char_dir / "card.json"
    card_json_text = json.dumps(card_dict, ensure_ascii=False, indent=2) + "\n"
    platform_compat.write_text(card_file, card_json_text, encoding="utf-8")

    visual_file = char_dir / "visual.md"
    platform_compat.write_text(visual_file, visual_md, encoding="utf-8")

    return {
        "id": char_id,
        "dir": str(char_dir),
        "card_path": str(card_file),
        "visual_path": str(visual_file),
        "card": card_dict,
    }


# ── Top-Level Orchestration Flow ───────────────────────────────────

def orchestrate_card_generation(
    idea: str,
    llm_call: Callable[[str, str], str],
    *,
    profile: str = "detailed",
    ws: Optional[Union[str, Path]] = None,
    dry_run: bool = False,
    user_title: str = "코치",  # l10n-ok
    voice: str = "",
    use_default_negative: bool = True,
    overrides: Optional[Dict[str, Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """Execute complete character generation workflow from idea to package."""
    raw_fields = generate_card_data(
        idea,
        llm_call,
        profile=profile,
        use_default_negative=use_default_negative,
        overrides=overrides,
    )

    missing = pick_missing_keys(raw_fields)
    if missing:
        patch = fill_missing_fields(
            idea,
            raw_fields,
            llm_call,
            missing_keys=missing,
            profile=profile,
            overrides=overrides,
        )
        raw_fields.update(patch)

    card = build_chara_v2_card(raw_fields, user_title=user_title, voice=voice)
    cid = _new_character_id()
    name = card["data"]["name"] or cid
    visual_text = build_visual_md(name, cid, card=raw_fields)

    if dry_run:
        return {
            "id": cid,
            "dir": None,
            "card_path": None,
            "visual_path": None,
            "card": card,
            "visual_md": visual_text,
        }

    pkg = save_character_package(card, visual_text, ws=ws, cid=cid)
    pkg["visual_md"] = visual_text
    return pkg


# ── Default LLM Adapter Runner ─────────────────────────────────────

def _call_provider_adapter(sys_prompt: str, user_prompt: str, provider: Optional[str] = None) -> str:
    """Invoke provider adapter synchronously using session or adapter directly."""
    from host_config import DEFAULT_PROVIDER
    from providers.adapters import get_adapter
    prov_name = provider or DEFAULT_PROVIDER
    adapter_cls = get_adapter(prov_name)
    adapter = adapter_cls()
    if hasattr(adapter, "complete_chat"):
        return adapter.complete_chat(sys_prompt, user_prompt)
    if hasattr(adapter, "run_turn_sync"):
        return adapter.run_turn_sync(sys_prompt, user_prompt)
    raise NotImplementedError(f"Adapter for provider {prov_name!r} does not support standalone completion")


# ── CLI Interface ──────────────────────────────────────────────────

def _load_card_file(path_str: str) -> Dict[str, Any]:
    """Load JSON card from disk."""
    p = Path(path_str)
    if not p.is_file():
        raise FileNotFoundError(f"Card file not found: {path_str}")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_updated_card(path_str: str, updated_card: Dict[str, Any]) -> None:
    """Save updated card dict back to disk."""
    p = Path(path_str)
    platform_compat.write_text(p, json.dumps(updated_card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for card_gen."""
    parser = argparse.ArgumentParser(
        description="Character card generation and refinement tool (tools/card_gen.py)."
    )
    parser.add_argument("idea", nargs="?", default="", help="Character concept / idea")
    parser.add_argument("--profile", default="detailed", choices=["short", "detailed", "verbose"])
    parser.add_argument("--card", default=None, help="Path to existing card.json for fill-missing or regenerate")
    parser.add_argument("--fill-missing", action="store_true", help="Fill missing keys in existing card")
    parser.add_argument("--regenerate", default=None, help="Comma-separated target keys to regenerate")
    parser.add_argument("--dry-run", action="store_true", help="Print card to stdout without writing files")
    parser.add_argument("--workspace", default=None, help="Target workspace path")
    parser.add_argument("--provider", default=None, help="LLM provider name")
    parser.add_argument("--input-file", default=None, help="Use mock/pre-saved LLM response from file")

    args = parser.parse_args(argv)

    if args.input_file:
        raw_content = Path(args.input_file).read_text(encoding="utf-8")
        llm_fn: Callable[[str, str], str] = lambda s, u: raw_content
    else:
        llm_fn = lambda s, u: _call_provider_adapter(s, u, provider=args.provider)

    try:
        if args.fill_missing:
            if not args.card:
                parser.error("--fill-missing requires --card <path>")
            card = _load_card_file(args.card)
            patch = fill_missing_fields(args.idea, card, llm_fn, profile=args.profile)
            if not args.dry_run:
                apply_patch(card, patch)
                _save_updated_card(args.card, card)
            print(json.dumps(patch, ensure_ascii=False, indent=2))
            return 0

        if args.regenerate:
            if not args.card:
                parser.error("--regenerate requires --card <path>")
            targets = [k.strip() for k in args.regenerate.split(",") if k.strip()]
            card = _load_card_file(args.card)
            patch = regenerate_fields(
                args.idea,
                card,
                targets,
                llm_fn,
                profile=args.profile,
                raise_on_failure=True,
            )
            if not args.dry_run:
                apply_patch(card, patch)
                _save_updated_card(args.card, card)
            print(json.dumps(patch, ensure_ascii=False, indent=2))
            return 0

        if not args.idea:
            parser.error("Concept idea is required for generation")

        res = orchestrate_card_generation(
            args.idea,
            llm_fn,
            profile=args.profile,
            ws=args.workspace,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print(json.dumps(res["card"], ensure_ascii=False, indent=2))
        else:
            print(f"[card_gen] Created character '{res['id']}' at {res['dir']}")
        return 0

    except Exception as e:
        print(f"[card_gen] Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
