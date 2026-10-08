import tempfile
from pathlib import Path
from unittest.mock import patch

from engine.tools import sync_mirrors


def test_calc_sha256():
    text = "Hello, world!"
    h = sync_mirrors.calc_sha256(text)
    assert len(h) == 64
    assert h == sync_mirrors.calc_sha256(text)


def test_read_mirror_hash():
    header = "<!-- AUTO-GENERATED MIRROR FROM TEST.md (source_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef) — DO NOT EDIT MANUALLY -->\n\n# Body"
    extracted = sync_mirrors.read_mirror_hash(header)
    assert extracted == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    no_header = "# Plain Markdown\nNo auto-generated header here."
    assert sync_mirrors.read_mirror_hash(no_header) is None


def test_mask_and_unmask_markdown():
    doc = (
        "# Heading\n\n"
        "Here is `inline code` and text.\n\n"
        "```python\n"
        "def foo():\n"
        "    return 42\n"
        "```\n\n"
        "Another line with `another_inline`."
    )
    masked, replacements = sync_mirrors.mask_markdown(doc)
    assert "def foo():" not in masked
    assert "`inline code`" not in masked
    assert len(replacements) == 3

    unmasked = sync_mirrors.unmask_markdown(masked, replacements)
    assert unmasked == doc


def test_sync_file_skips_when_hash_matches():
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "TEST.md"
        src.write_text("# Test\nContent", encoding="utf-8")
        src_hash = sync_mirrors.calc_sha256(src.read_text(encoding="utf-8"))

        mirror = Path(tmpdir) / "TEST.ko.md"
        header = sync_mirrors.make_mirror_header("TEST.md", src_hash)
        mirror.write_text(header + "# 테스트\n내용", encoding="utf-8")

        status, msg = sync_mirrors.sync_file(src, mirror)
        assert status == "skipped"
        assert "matches" in msg


def test_sync_file_check_only_detects_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "TEST.md"
        src.write_text("# Test\nNew Content", encoding="utf-8")

        mirror = Path(tmpdir) / "TEST.ko.md"
        old_hash = "0" * 64
        header = sync_mirrors.make_mirror_header("TEST.md", old_hash)
        mirror.write_text(header + "# 테스트\n옛 내용", encoding="utf-8")

        status, msg = sync_mirrors.sync_file(src, mirror, check_only=True)
        assert status == "stale"
        assert "differs" in msg


def test_standing_docs_mirrors_up_to_date():
    """Verify that all default mirror targets are up-to-date with their source documents."""
    for target in sync_mirrors.DEFAULT_MIRROR_TARGETS:
        src = sync_mirrors.REPO_ROOT / target
        if not src.exists():
            continue
        stem = src.name[:-3]
        mirror = src.parent / f"{stem}.ko.md"
        assert mirror.exists(), f"Mirror missing for {target}: expected {mirror.name}"
        status, msg = sync_mirrors.sync_file(src, mirror, check_only=True)
        assert status == "skipped", f"Mirror {mirror.name} is out of date: {msg}"
