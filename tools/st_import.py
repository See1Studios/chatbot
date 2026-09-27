#!/usr/bin/env python3
"""SillyTavern PNG character card parser & importer (tools/st_import.py).

Parses SillyTavern PNG character cards (V2/V3 spec) into See1 card.json format,
creates character directories (<workspace>/characters/<id>/), saves avatar master PNG,
generates avatar.webp, and creates visual.md lock sheet templates.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Add project root to sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PREFIX = "char"
_B32 = "0123456789abcdefghjkmnpqrstvwxyz"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------------ ID & Paths

def uuid7(now_ms: Optional[int] = None, rand: Optional[int] = None) -> int:
    """A UUIDv7 as a 128-bit int (RFC 9562): 48-bit Unix ms, version 7, variant 10, 74 random bits."""
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    r = secrets.randbits(74) if rand is None else rand
    rand_a, rand_b = (r >> 62) & 0xFFF, r & ((1 << 62) - 1)
    return (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b


def encode_typeid(n: int) -> str:
    """A 128-bit UUID as the 26-character TypeID suffix in Crockford base32."""
    return "".join(_B32[(n >> (5 * (25 - i))) & 31] for i in range(26))


def new_character_id(prefix: str = PREFIX) -> str:
    """Generate a new TypeID matching characters.py specification."""
    try:
        import characters
        return characters.new_id(prefix)
    except Exception:
        return f"{prefix}_{encode_typeid(uuid7())}"


def make_slug(name: str) -> str:
    """Generate a slug from name (lowercase, alphanumeric, hyphen)."""
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return clean or "character"


def get_characters_dir(ws: Optional[Union[str, Path]] = None) -> Path:
    """Return characters directory path, defaulting to workspace."""
    if ws is not None:
        return Path(ws) / "characters"
    try:
        import characters
        return characters.characters_dir()
    except Exception:
        return _ROOT / "data" / "workspace" / "characters"


# ------------------------------------------------------------------------ PNG Parsing

def extract_chara_raw(png_bytes: bytes) -> bytes:
    """Extract raw 'chara' text chunk bytes from a PNG image using pure Python (struct, zlib)."""
    if not png_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG: missing standard PNG signature")

    offset = 8
    total_len = len(png_bytes)
    chara_bytes = None

    while offset + 8 <= total_len:
        chunk_len = struct.unpack(">I", png_bytes[offset:offset + 4])[0]
        chunk_type = png_bytes[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_len

        if data_end + 4 > total_len:
            break

        chunk_data = png_bytes[data_start:data_end]

        if chunk_type == b"tEXt":
            if b"\x00" in chunk_data:
                keyword, text_val = chunk_data.split(b"\x00", 1)
                if keyword.lower() == b"chara":
                    chara_bytes = text_val
                    break
        elif chunk_type == b"zTXt":
            if b"\x00" in chunk_data:
                keyword, rest = chunk_data.split(b"\x00", 1)
                if keyword.lower() == b"chara" and len(rest) > 1:
                    try:
                        chara_bytes = zlib.decompress(rest[1:])
                        break
                    except Exception:
                        pass
        elif chunk_type == b"iTXt":
            if b"\x00" in chunk_data:
                keyword, rest = chunk_data.split(b"\x00", 1)
                if keyword.lower() == b"chara" and len(rest) >= 2:
                    comp_flag = rest[0]
                    parts = rest[2:].split(b"\x00", 2)
                    if len(parts) == 3:
                        text_part = parts[2]
                        if comp_flag == 1:
                            try:
                                text_part = zlib.decompress(text_part)
                            except Exception:
                                pass
                        chara_bytes = text_part
                        break

        offset = data_end + 4
        if chunk_type == b"IEND":
            break

    if chara_bytes is None:
        raise ValueError("No 'chara' text chunk found in PNG")

    return chara_bytes


def extract_st_card(png_bytes: bytes) -> dict:
    """Extract and parse SillyTavern character card JSON from PNG bytes."""
    chara_raw = extract_chara_raw(png_bytes).strip()

    # Handle potential base64 padding issues
    missing_padding = len(chara_raw) % 4
    if missing_padding:
        chara_raw += b"=" * (4 - missing_padding)

    try:
        decoded = base64.b64decode(chara_raw).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        # Fallback to direct UTF-8 if raw unencoded JSON
        try:
            return json.loads(chara_raw.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Failed to decode chara chunk data as JSON: {e}")


# ------------------------------------------------------------------------ Card Conversion

def convert_st_card(raw: dict) -> dict:
    """Convert SillyTavern V2/V3 card dict into See1 card.json structure."""
    if not isinstance(raw, dict):
        raise ValueError(f"Expected dict, got {type(raw).__name__}")

    # V3 or standard V2 with 'data' container
    source = raw.get("data") if isinstance(raw.get("data"), dict) else raw

    def get_str(*keys: str, default: str = "") -> str:
        for k in keys:
            v = source.get(k)
            if v is not None:
                return str(v)
            v = raw.get(k)
            if v is not None:
                return str(v)
        return default

    name = get_str("name")
    description = get_str("description")
    personality = get_str("personality")
    scenario = get_str("scenario")
    first_mes = get_str("first_mes")
    mes_example = get_str("mes_example")
    creator_notes = get_str("creator_notes", "creatorcomment", "comment")
    system_prompt = get_str("system_prompt")
    post_history_instructions = get_str("post_history_instructions")
    creator = get_str("creator")
    character_version = get_str("character_version")

    # alternate_greetings: list of strings
    raw_alt = source.get("alternate_greetings")
    if raw_alt is None:
        raw_alt = raw.get("alternate_greetings")
    if isinstance(raw_alt, list):
        alternate_greetings = [str(x) for x in raw_alt]
    elif isinstance(raw_alt, str) and raw_alt.strip():
        alternate_greetings = [raw_alt.strip()]
    else:
        alternate_greetings = []

    # tags: list of strings
    raw_tags = source.get("tags")
    if raw_tags is None:
        raw_tags = raw.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(x) for x in raw_tags]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [x.strip() for x in raw_tags.split(",") if x.strip()]
    else:
        tags = []

    # extensions: dict
    raw_ext = source.get("extensions")
    if raw_ext is None:
        raw_ext = raw.get("extensions")
    if isinstance(raw_ext, dict):
        extensions = dict(raw_ext)
    else:
        extensions = {}

    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": description,
            "personality": personality,
            "scenario": scenario,
            "first_mes": first_mes,
            "mes_example": mes_example,
            "creator_notes": creator_notes,
            "system_prompt": system_prompt,
            "post_history_instructions": post_history_instructions,
            "alternate_greetings": alternate_greetings,
            "tags": tags,
            "creator": creator,
            "character_version": character_version,
            "extensions": extensions,
        },
    }


def make_visual_md(name: str, char_id: str) -> str:
    """Generate default visual.md template for imported character."""
    display_name = name or char_id
    return f"""# {display_name} visual lock sheet

Format and procedure: skill `character-art`. The page uses this folder (`avatar.webp`).
Voice and manner are in the card, not here.

## Locks
- Imported from SillyTavern character card.
- Base look: Reference `avatar_master.png`.

## Prompt Specification (SSOT)
Modern anime standard (thin clean lineart, crisp cel shading):

### 1. Style Anchor
- `clean thin line art, crisp cel shading, subtle flat color tones, soft studio key lighting, high-end 2D anime illustration`

### 2. Character Anchor ({display_name})
- `{display_name}`

### 3. Generation Rule
- **Master Image Required:** Once `avatar_master.png` is approved, NEVER generate new expressions or outfits from scratch with pure text prompts.
- **Reference-based Inpainting / I2I:** All expressions, wigs, and gestures MUST use `avatar_master.png` as the reference image, modifying only the target region.

### 4. Framing & Composition
- **avatar.webp (512x512):** `full-bleed close-up, front-facing, face centered, 56px circle crop safe`
- **sprites/bust (1024x1024):** `medium close-up, cut at shoulders, centered, transparent background`
- **sprites/full (1024x2048):** `full body shot, standing grounded 2% from bottom, centered, transparent background`

### 5. Negative Lock
- `bad anatomy, bad hands, 3d render, photorealistic, watermark, text`

## Wigs (optional)
| Brain | Hair (cut + dye) | Outfit |
|---|---|---|

## Sprites (optional)
| Framing | Labels made | Notes |
|---|---|---|

## Rejected

## Open
"""


# ------------------------------------------------------------------------ Import Logic & API

def import_st_png_bytes(
    png_bytes: bytes,
    ws: Optional[Union[str, Path]] = None,
    dry_run: bool = False,
) -> dict:
    """Import SillyTavern PNG card bytes into See1 character format and directory structure.

    Exposed at module level for HTTP API handlers and CLI tools.
    """
    raw_card = extract_st_card(png_bytes)
    card = convert_st_card(raw_card)

    name = card["data"]["name"] or "Unnamed"
    slug = make_slug(name)
    cid = new_character_id()

    char_dir = get_characters_dir(ws) / cid

    if not dry_run:
        char_dir.mkdir(parents=True, exist_ok=True)

        # 1. card.json
        card_file = char_dir / "card.json"
        card_file.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 2. avatar_master.png (original raw PNG preserved)
        master_png = char_dir / "avatar_master.png"
        master_png.write_bytes(png_bytes)

        # 3. avatar.webp (512x512 standard format for See1)
        avatar_webp = char_dir / "avatar.webp"
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(png_bytes)) as img:
                img_conv = img.convert("RGBA" if ("A" in img.mode or "transparency" in img.info) else "RGB")
                if img_conv.size != (512, 512):
                    resample = getattr(Image, "Resampling", Image).LANCZOS
                    img_conv = img_conv.resize((512, 512), resample)
                img_conv.save(avatar_webp, "WEBP")
        except Exception:
            pass

        # 4. visual.md
        visual_file = char_dir / "visual.md"
        visual_file.write_text(make_visual_md(name, cid), encoding="utf-8")

    return {
        "id": cid,
        "name": name,
        "slug": slug,
        "dir": str(char_dir),
        "path": str(char_dir),
        "card": card,
        "spec": card["spec"],
        "spec_version": card["spec_version"],
        "data": card["data"],
    }


def import_st_path(
    path: Union[str, Path],
    ws: Optional[Union[str, Path]] = None,
    dry_run: bool = False,
) -> List[dict]:
    """Import a single PNG file or a directory of PNG files."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")

    results = []
    if target.is_dir():
        png_files = sorted(p for p in target.glob("*.png") if p.is_file())
        for png_file in png_files:
            data = png_file.read_bytes()
            res = import_st_png_bytes(data, ws=ws, dry_run=dry_run)
            res["source_file"] = str(png_file)
            results.append(res)
    else:
        data = target.read_bytes()
        res = import_st_png_bytes(data, ws=ws, dry_run=dry_run)
        res["source_file"] = str(target)
        results.append(res)

    return results


# ------------------------------------------------------------------------ PNG Builder Helper

def create_st_png_bytes(card_data: dict, width: int = 1, height: int = 1) -> bytes:
    """Create a valid PNG image byte sequence with a SillyTavern 'chara' tEXt chunk."""
    sig = PNG_SIGNATURE
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    payload = base64.b64encode(json.dumps(card_data, ensure_ascii=False).encode("utf-8"))
    text_data = b"chara\x00" + payload
    text_crc = zlib.crc32(b"tEXt" + text_data)
    text_chunk = struct.pack(">I", len(text_data)) + b"tEXt" + text_data + struct.pack(">I", text_crc)

    row = b"\x00" + (b"\xff\xff\xff" * width)
    raw_pixels = row * height
    idat_content = zlib.compress(raw_pixels)
    idat_crc = zlib.crc32(b"IDAT" + idat_content)
    idat = struct.pack(">I", len(idat_content)) + b"IDAT" + idat_content + struct.pack(">I", idat_crc)

    iend_crc = zlib.crc32(b"IEND")
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    return sig + ihdr + text_chunk + idat + iend


# ------------------------------------------------------------------------ CLI

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import SillyTavern PNG character cards (V2/V3) into See1 format."
    )
    parser.add_argument("path", help="Path to a PNG file or directory containing PNG files")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate without saving to disk")
    parser.add_argument("--workspace", default=None, help="Custom workspace path")

    args = parser.parse_args(argv)

    try:
        results = import_st_path(args.path, ws=args.workspace, dry_run=args.dry_run)
        if not results:
            print(f"[st_import] No PNG files found in {args.path}")
            return 0

        prefix = "[DRY RUN] " if args.dry_run else ""
        for r in results:
            print(f"[st_import] {prefix}Imported '{r['name']}' (id: {r['id']}, slug: {r['slug']})")
            if not args.dry_run:
                print(f"            Directory: {r['dir']}")
                print(f"            card.json, avatar_master.png, avatar.webp, visual.md created.")
        return 0
    except Exception as e:
        print(f"[st_import] Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
