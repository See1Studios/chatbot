#!/usr/bin/env python3
"""Sync Korean mirror documents (*.ko.md) from English standing documents (*.md)

Uses Google free translation endpoint (translate.googleapis.com) with:
1. Markdown structure preservation (code blocks, inline code, table formatting protected)
2. A glossary (GLOSSARY): the project's own terms go through as fixed Korean words, not the translator's guess
   ("agent" came back as "counselor", "lore" as "story")
3. SHA-256 caching: only translates when the English source file hash changes
5. Translation memory (MIRROR_TM_v1): only the paragraphs that changed go to the translator. The source the mirror
   was made from is found in git by its hash, and its paragraphs pair with the mirror's. A one-line rule used to
   resend the whole document (dozens of requests) and the endpoint answered 429 for hours (2026-10-08).
4. Machine-translation disclaimer header:
   <!-- AUTO-GENERATED MIRROR FROM {source} (source_sha256: {hash}) — DO NOT EDIT MANUALLY -->

The mirrors let the operator follow what changed; rough wording is fine, a changed meaning is not. Agents never read
them. The pre-commit hook syncs the staged standing documents; offline it warns and the commit goes on (the full
suite's freshness test then names the stale mirror).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Documents eligible for Korean mirroring (*.md -> *.ko.md). The one list: the pre-commit hook reads it too.
DEFAULT_MIRROR_TARGETS = [
    "VISION.md",
    "PRODUCT.md",
    "RULES.md",
]

# English term -> the fixed Korean word (engine_data/mirror_glossary.json): the translator never sees these terms.
GLOSSARY = json.loads((Path(__file__).resolve().parent.parent / "engine_data" / "mirror_glossary.json")
                      .read_text(encoding="utf-8"))["terms"]
GLOSSARY_RE = re.compile(
    r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in sorted(GLOSSARY, key=len, reverse=True)) + r")(?:e?s)?(?![\w-])",
    re.IGNORECASE,
)
_GLOSSARY_LOWER = {k.lower(): v for k, v in GLOSSARY.items()}

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


PACE_SEC = 0.5             # between requests: the free endpoint limits bursts
BACKOFF_SEC = (2, 8, 30)   # waits before each retry; 429 is a rate limit that passes
_last_call = [0.0]


def translate_text_chunk(text: str, timeout: int = 10, retries: int = len(BACKOFF_SEC)) -> str:
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
        time.sleep(max(0.0, _last_call[0] + PACE_SEC - time.time()))
        _last_call[0] = time.time()
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
            time.sleep(BACKOFF_SEC[min(attempt, len(BACKOFF_SEC) - 1)])
    return text


CODEBLOCK_RE = re.compile(r"(?ms)^(`{3,}[^\n]*\n.*?\n`{3,})$")


def mask_markdown(content: str) -> Tuple[str, Dict[str, str]]:
    """Put placeholders where the translator must not touch: fenced code, inline code, link targets, and the
    glossary's terms (whose placeholder comes back as the fixed word). Returns the masked text and key -> text."""
    replacements: Dict[str, str] = {}
    counter = 0

    def keep(kind: str, text: str) -> str:
        nonlocal counter
        key = f"XZ{kind}{counter}ZX"
        counter += 1
        replacements[key] = text
        return key

    content = CODEBLOCK_RE.sub(lambda m: keep("CODEBLOCK", m.group(0)), content)
    content = re.sub(r"`[^`\n]+`", lambda m: keep("INLINE", m.group(0)), content)
    content = re.sub(r"\]\([^)\s]+\)", lambda m: keep("LINK", m.group(0)), content)

    def term(m: re.Match) -> str:
        word = m.group(0).lower()
        base = word if word in _GLOSSARY_LOWER else word[:-2] if word[:-2] in _GLOSSARY_LOWER else word[:-1]
        return keep("G", _GLOSSARY_LOWER[base])

    content = GLOSSARY_RE.sub(term, content)
    return content, replacements


def unmask_markdown(content: str, replacements: Dict[str, str]) -> str:
    """Restore the placeholders. Only the key is replaced: the spaces around it are the sentence's (stripping them
    glued `code` to the words beside it)."""
    for key in sorted(replacements, key=len, reverse=True):   # XZG12ZX before XZG1ZX
        word = replacements[key]
        if key.startswith("XZG"):
            content = re.sub(re.escape(key) + r"(은|는|이|가|을|를|과|와)(?=[\s.,;:)!?]|$)",   # l10n-ok
                             lambda m: word + _particle(word, m.group(1)), content)
        content = content.replace(key, word)
    return content


# The translator picks a particle for the placeholder, not for the word put back: fit the one attached right after it
# to whether the word ends in a final consonant (a topic, subject, object or "and" particle pair).
_PARTICLES = {"은": "는", "이": "가", "을": "를", "과": "와"}   # l10n-ok: with / without a final consonant


def _particle(word: str, particle: str) -> str:
    last = word[-1]
    if not "\uac00" <= last <= "\ud7a3":
        return particle   # a Latin name: the translator's choice stands
    final = (ord(last) - 0xAC00) % 28 != 0
    pair = next((a, b) for a, b in _PARTICLES.items() if particle in (a, b))
    return pair[0] if final else pair[1]


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


def paragraphs(content: str) -> List[str]:
    """The paragraphs as translate_markdown splits them: at blank lines, a fenced block (blank lines inside) is one."""
    blocks: List[str] = []

    def hold(m: re.Match) -> str:
        blocks.append(m.group(0))
        return "XZB%dZX" % (len(blocks) - 1)

    masked = CODEBLOCK_RE.sub(hold, content)
    return [re.sub(r"XZB(\d+)ZX", lambda m: blocks[int(m.group(1))], p) for p in masked.split("\n\n")]


def source_at(source_file: Path, sha: str, depth: int = 50) -> Optional[str]:
    """The source text whose hash is `sha` (what the mirror was made from): HEAD or one of the last `depth` commits
    of the file. None outside git or when it is not found."""
    def run(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(source_file.parent), *a], capture_output=True, text=True, timeout=30)

    try:
        log = run("log", "--format=%H", "-n", str(depth), "--", source_file.name)
        for commit in log.stdout.split() if log.returncode == 0 else []:
            old = run("show", "%s:./%s" % (commit, source_file.name))
            if old.returncode == 0 and calc_sha256(old.stdout) == sha:
                return old.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def translation_memory(source_file: Path, mirror_text: str) -> Dict[str, str]:
    """Source paragraph -> its Korean paragraph, from the mirror and the source it was made from; {} when they do not
    pair up (then the whole document is translated, as before)."""
    sha = read_mirror_hash(mirror_text)
    old = source_at(source_file, sha) if sha else None
    if old is None:
        return {}
    src, mir = paragraphs(old), paragraphs(mirror_text[len(make_mirror_header(source_file.name, sha)):])
    if len(src) != len(mir) or len(src) < 2:   # 0/1: no paragraph structure to trust
        return {}
    memory = dict(zip(src, mir))
    for s, m in zip(src, mir):   # a table is one paragraph: its rows pair up too, so one new row sends one row
        if s.count("\n") == m.count("\n") and "\n" in s:
            memory.update((a, b) for a, b in zip(s.split("\n"), m.split("\n")) if a not in memory)
    return memory


def translate_with_memory(content: str, memory: Dict[str, str]) -> str:
    """translate_markdown, but a paragraph the memory knows is reused; the rest go in one batch."""
    if not memory:
        return translate_markdown(content)
    paras = paragraphs(content)

    def known(p: str) -> bool:   # the paragraph, or every line of it
        return p in memory or not p.strip() or all(l in memory or not l.strip() for l in p.split("\n"))

    whole = [p for p in paras if not known(p) and not any(l in memory for l in p.split("\n") if l.strip())]
    lines = [l for p in paras if not known(p) and p not in whole for l in p.split("\n")
             if l.strip() and l not in memory]
    todo = list(dict.fromkeys(whole + lines))
    if todo:
        cores = [t.strip("\n") for t in todo]   # an edge newline would cross into the next item of the batch
        done = paragraphs(translate_markdown("\n\n".join(cores)))
        if len(done) != len(cores):   # the translator moved a boundary: one at a time
            done = [translate_markdown(c) for c in cores]
        memory = dict(memory, **{t: t[:len(t) - len(t.lstrip("\n"))] + d + t[len(t.rstrip("\n")):]
                                 for t, d in zip(todo, done)})

    def put(p: str) -> str:
        return memory[p] if p in memory else "\n".join(memory.get(l, l) for l in p.split("\n"))

    return "\n\n".join(put(p) for p in paras)


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

    memory: Dict[str, str] = {}
    if mirror_file.exists() and not force:
        mirror_content = mirror_file.read_text(encoding="utf-8")
        existing_hash = read_mirror_hash(mirror_content)
        if existing_hash == src_hash:
            return "skipped", f"Up-to-date: {mirror_file.name} matches {source_file.name} ({src_hash[:8]})"
        if check_only:
            return "stale", f"Out-of-date: {mirror_file.name} differs from {source_file.name}"
        memory = translation_memory(source_file, mirror_content)

    if check_only:
        return "stale", f"Missing: {mirror_file.name} does not exist"

    # Translate and write
    translated = translate_with_memory(src_content, memory)
    header = make_mirror_header(source_file.name, src_hash)
    final_output = header + translated.lstrip()

    with open(str(mirror_file), "w", encoding="utf-8", newline="\n") as fh:   # LF on every OS
        fh.write(final_output)
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
