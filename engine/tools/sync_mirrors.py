#!/usr/bin/env python3
"""Sync Korean mirror documents (*.ko.md) from English standing documents (*.md)

Uses Google free translation endpoint (translate.googleapis.com) with:
1. Markdown structure preservation (code blocks, inline code, table formatting protected)
2. SHA-256 caching: only translates when the English source file hash changes
3. Machine-translation disclaimer header:
   <!-- AUTO-GENERATED MIRROR FROM {source} (source_sha256: {hash}) — DO NOT EDIT MANUALLY -->
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Documents eligible for Korean mirroring (*.md -> *.ko.md)
DEFAULT_MIRROR_TARGETS = [
    "CONCEPT.md",
    "PRODUCT.md",
    "RULES.md",
]

HEADER_RE = re.compile(
    r"^<!-- AUTO-GENERATED MIRROR FROM (?P<src>[^\s]+) \(source_sha256: (?P<sha>[0-9a-fA-F]{64})\)[^>]*-->"
)


def calc_sha256(content: str) -> str:
    """Compute sha256 hex digest of UTF-8 content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_mirror_hash(mirror_text: str) -> Optional[str]:
    """Extract source_sha256 from the mirror document header if present."""
    for line in mirror_text.splitlines()[:5]:
        m = HEADER_RE.match(line.strip())
        if m:
            return m.group("sha").lower()
    return None


def make_mirror_header(source_name: str, sha256_hash: str) -> str:
    """Format the standard machine-translation disclaimer header."""
    return (
        f"<!-- AUTO-GENERATED MIRROR FROM {source_name} "
        f"(source_sha256: {sha256_hash}) — DO NOT EDIT MANUALLY -->\n\n"
    )


def translate_text_chunk(text: str, timeout: int = 10, retries: int = 2) -> str:
    """Call Google free translation endpoint for a single chunk of text."""
    if not text.strip():
        return text

    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=en&tl=ko&dt=t&q=" + urllib.parse.quote(text)
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                segments = []
                if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    for seg in data[0]:
                        if seg and isinstance(seg, list) and len(seg) > 0 and seg[0]:
                            segments.append(seg[0])
                return "".join(segments)
        except Exception as e:
            if attempt == retries:
                raise RuntimeError(f"Translation failed after {retries + 1} attempts: {e}") from e
            time.sleep(1.0)
    return text


def mask_markdown(content: str) -> Tuple[str, Dict[str, str]]:
    """Mask markdown code blocks and inline code with placeholders to protect them from translation."""
    replacements: Dict[str, str] = {}
    counter = 0

    # 1. Mask fenced code blocks (``` ... ``` or ```` ... ````)
    def mask_code_block(match: re.Match) -> str:
        nonlocal counter
        key = f"XZCODEBLOCK{counter}ZX"
        counter += 1
        replacements[key] = match.group(0)
        return key

    # Match multiline code blocks
    content = re.sub(r"(?ms)^(`{3,}[^\n]*\n.*?\n`{3,})$", mask_code_block, content)

    # 2. Mask inline code (`...`)
    def mask_inline_code(match: re.Match) -> str:
        nonlocal counter
        key = f"XZINLINE{counter}ZX"
        counter += 1
        replacements[key] = match.group(0)
        return key

    content = re.sub(r"`[^`\n]+`", mask_inline_code, content)
    return content, replacements


def unmask_markdown(content: str, replacements: Dict[str, str]) -> str:
    """Restore masked markdown placeholders."""
    for key, original in replacements.items():
        # Allow optional surrounding whitespace that translation API may introduce
        pattern = re.compile(rf"\s*{re.escape(key)}\s*")
        content = pattern.sub(original, content)
    return content


def translate_markdown(content: str) -> str:
    """Translate markdown text to Korean while preserving markdown structures."""
    masked, replacements = mask_markdown(content)
    paragraphs = masked.split("\n\n")

    translated_paragraphs = []
    chunk_buffer: List[str] = []
    chunk_len = 0

    def flush_chunk(buffer: List[str]) -> List[str]:
        if not buffer:
            return []
        joined = "\n\n".join(buffer)
        translated = translate_text_chunk(joined)
        res = translated.split("\n\n")
        # Ensure returned count matches buffer count
        if len(res) != len(buffer):
            # Fallback to paragraph-by-paragraph translation if paragraph boundaries shifted
            res = [translate_text_chunk(p) for p in buffer]
        return res

    for p in paragraphs:
        # If paragraph is purely a code block placeholder or empty, flush buffer first and pass through
        stripped = p.strip()
        if not stripped or (stripped.startswith("XZCODEBLOCK") and stripped.endswith("ZX")):
            if chunk_buffer:
                translated_paragraphs.extend(flush_chunk(chunk_buffer))
                chunk_buffer = []
                chunk_len = 0
            translated_paragraphs.append(p)
            continue

        if chunk_len + len(p) > 2000 and chunk_buffer:
            translated_paragraphs.extend(flush_chunk(chunk_buffer))
            chunk_buffer = []
            chunk_len = 0

        chunk_buffer.append(p)
        chunk_len += len(p)

    if chunk_buffer:
        translated_paragraphs.extend(flush_chunk(chunk_buffer))

    translated_doc = "\n\n".join(translated_paragraphs)
    return unmask_markdown(translated_doc, replacements)


def sync_file(
    source_file: Path,
    mirror_file: Path,
    check_only: bool = False,
    force: bool = False,
) -> Tuple[str, str]:
    """Sync a single source file to its mirror file.

    Returns: (status, message)
      status: 'ok', 'skipped', 'stale', 'error'
    """
    if not source_file.exists():
        return "error", f"Source file not found: {source_file}"

    src_content = source_file.read_text(encoding="utf-8")
    src_hash = calc_sha256(src_content)

    if mirror_file.exists() and not force:
        mirror_content = mirror_file.read_text(encoding="utf-8")
        existing_hash = read_mirror_hash(mirror_content)
        if existing_hash == src_hash:
            return "skipped", f"Up-to-date: {mirror_file.name} matches {source_file.name} ({src_hash[:8]})"
        if check_only:
            return "stale", f"Out-of-date: {mirror_file.name} differs from {source_file.name}"

    if check_only:
        return "stale", f"Missing: {mirror_file.name} does not exist"

    # Translate and write
    translated = translate_markdown(src_content)
    header = make_mirror_header(source_file.name, src_hash)
    final_output = header + translated.lstrip()

    mirror_file.write_text(final_output, encoding="utf-8")
    return "ok", f"Synchronized {mirror_file.name} from {source_file.name} ({src_hash[:8]})"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Korean mirror markdown documents (*.ko.md)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether mirrors are up-to-date without modifying them (exit 1 if stale)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force retranslation even if sha256 matches",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific files to sync (default: standing docs)",
    )

    args = parser.parse_args(argv)

    targets = args.files or DEFAULT_MIRROR_TARGETS
    has_stale = False
    has_error = False

    for target in targets:
        src_path = Path(target)
        if not src_path.is_absolute():
            src_path = REPO_ROOT / src_path

        # Determine mirror path: <name>.md -> <name>.ko.md
        if src_path.name.endswith(".ko.md"):
            continue
        if not src_path.name.endswith(".md"):
            continue

        stem = src_path.name[:-3]
        mirror_name = f"{stem}.ko.md"
        mirror_path = src_path.parent / mirror_name

        status, msg = sync_file(src_path, mirror_path, check_only=args.check, force=args.force)
        print(f"[{status.upper()}] {msg}")

        if status == "stale":
            has_stale = True
        elif status == "error":
            has_error = True

    if has_error:
        return 2
    if args.check and has_stale:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
