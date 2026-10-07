#!/usr/bin/env python3
"""SillyTavern PNG character card export (tools/st_export.py).

Port of ST-CardGen ``server/src/domain/cards/png.ts``: drop existing card text
chunks and insert one base64 ``chara`` tEXt chunk immediately before IEND.

png.ts removes tEXt only. This also removes ``chara`` / ``ccv3`` zTXt and iTXt
chunks. ``tools/st_import.py`` reads those types and prefers ``ccv3``, so a
leftover compressed chunk would hide the card just written.

The bytes are ``card.json`` as stored (the Chara V2 object ``card_gen`` writes).
This module does not invent a second card shape. ``role`` / ``roles`` / ``tools`` /
``skills`` inside ``extensions.chatbot`` are removed on the way out, the same keys
``st_import`` drops on the way in, so a PNG cannot smuggle a roster grant.
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.st_import import GRANT_KEYS, make_slug  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TEXT_TYPES = (b"tEXt", b"zTXt", b"iTXt")
_CARD_KEYWORDS = ("chara", "ccv3")
_MASTER_NAMES = ("avatar_master.png", "avatar.png")
Chunk = Tuple[bytes, bytes]


def parse_png_chunks(png_bytes: bytes) -> List[Chunk]:
    """Every chunk in a PNG (type, data), without checking CRCs."""
    if not png_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG: missing standard PNG signature")
    offset, total, chunks = 8, len(png_bytes), []
    while offset + 8 <= total:
        length = struct.unpack(">I", png_bytes[offset:offset + 4])[0]
        ctype = png_bytes[offset + 4:offset + 8]
        end = offset + 8 + length
        if end + 4 > total:
            break
        chunks.append((ctype, png_bytes[offset + 8:end]))
        offset = end + 4
    return chunks


def encode_png(chunks: Sequence[Chunk]) -> bytes:
    """A PNG signature plus chunks, each with a fresh CRC."""
    parts = [PNG_SIGNATURE]
    for ctype, data in chunks:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        parts.append(struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc))
    return b"".join(parts)


def chunk_keyword(chunk_type: bytes, data: bytes) -> str:
    """Latin-1 keyword of a tEXt / zTXt / iTXt chunk, or "" when it has none."""
    if chunk_type not in _TEXT_TYPES or b"\x00" not in data:
        return ""
    try:
        return data.split(b"\x00", 1)[0].decode("latin-1").strip().lower()
    except Exception:
        return ""


def _is_card_chunk(chunk: Chunk) -> bool:
    return chunk_keyword(chunk[0], chunk[1]) in _CARD_KEYWORDS


def embed_card_into_png(png_bytes: bytes, card_json: str) -> bytes:
    """``png.ts`` ``embedCardIntoPng``: one ``chara`` tEXt chunk placed before IEND."""
    if not isinstance(card_json, str) or not card_json:
        raise ValueError("Empty character data")
    chunks = [c for c in parse_png_chunks(png_bytes) if not _is_card_chunk(c)]
    payload = base64.b64encode(card_json.encode("utf-8"))
    chara = (b"tEXt", b"chara\x00" + payload)
    iend = next((i for i, (ctype, _) in enumerate(chunks) if ctype == b"IEND"), -1)
    if iend < 0:
        raise ValueError("Invalid PNG: missing IEND chunk")
    chunks.insert(iend, chara)
    return encode_png(chunks)


def extract_card_from_png(png_bytes: bytes) -> str:
    """``png.ts`` ``extractCardFromPng``: the first readable ``chara`` tEXt body."""
    for ctype, data in parse_png_chunks(png_bytes):
        if ctype != b"tEXt" or chunk_keyword(ctype, data) != "chara":
            continue
        text = data.split(b"\x00", 1)[1]
        try:
            decoded = base64.b64decode(text).decode("utf-8")
        except Exception:
            continue
        if decoded:
            return decoded
    raise ValueError("No character data")


def without_grants(card: dict) -> dict:
    """A copy of ``card`` whose ``extensions.chatbot`` has no roster-grant keys."""
    if not isinstance(card, dict):
        raise ValueError("card.json must be a JSON object")
    card = json.loads(json.dumps(card))
    nodes = [card]
    data = card.get("data")
    if isinstance(data, dict):
        nodes.append(data)
    for node in nodes:
        ext = node.get("extensions")
        ours = ext.get("chatbot") if isinstance(ext, dict) else None
        if isinstance(ours, dict):
            ext["chatbot"] = {k: v for k, v in ours.items() if k not in GRANT_KEYS}
    return card


def load_card(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read card.json: %s" % exc)
    return without_grants(raw)


def card_json_text(card: dict) -> str:
    return json.dumps(without_grants(card), ensure_ascii=False)


def master_image(folder: Path) -> Path:
    for name in _MASTER_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    raise ValueError("no master image in %s (looked for %s)" % (folder, ", ".join(_MASTER_NAMES)))


def output_name(card: dict) -> str:
    data = card.get("data") if isinstance(card.get("data"), dict) else card
    name = str(data.get("name") or "") if isinstance(data, dict) else ""
    return make_slug(name) + ".png"


def export_files(card_path: Path, image_path: Path, out_path: Path, force: bool = False) -> Path:
    """Write ``out_path``: ``image_path`` with ``card_path`` embedded as ``chara``."""
    out_path = Path(out_path)
    if out_path.exists() and not force:
        raise ValueError("output exists: %s (pass --force)" % out_path)
    png = Path(image_path).read_bytes()
    packed = embed_card_into_png(png, card_json_text(load_card(card_path)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(packed)
    return out_path


def _inputs(args) -> Tuple[Path, Path]:
    if args.dir:
        if args.card or args.image:
            raise ValueError("pass --dir or --card with --image, not both")
        folder = Path(args.dir)
        card = folder / "card.json"
        if not card.is_file():
            raise ValueError("no card.json in %s" % folder)
        return card, master_image(folder)
    if not args.card or not args.image:
        raise ValueError("pass --dir, or both --card and --image")
    return Path(args.card), Path(args.image)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Package card.json into a SillyTavern PNG (chara tEXt before IEND)."
    )
    parser.add_argument("--card", help="Path to card.json")
    parser.add_argument("--image", help="Master PNG (avatar_master.png)")
    parser.add_argument("--dir", help="Character folder with card.json and a master PNG")
    parser.add_argument("-o", "--out", help="Output PNG (default: ./<slug>.png)")
    parser.add_argument("--force", action="store_true", help="Overwrite the output file")
    args = parser.parse_args(argv)
    try:
        card_path, image_path = _inputs(args)
        out = Path(args.out) if args.out else Path.cwd() / output_name(load_card(card_path))
        export_files(card_path, image_path, out, force=args.force)
    except (ValueError, OSError) as exc:
        print("[st_export] Error: %s" % exc, file=sys.stderr)
        return 1
    print("[st_export] Wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
