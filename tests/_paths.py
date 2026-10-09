"""Where the tests find things (LAYOUT_v1, docs/plans/repo-layout.md): REPO is the repository root (static/,
templates/, tests/, docs/, the entry files), ENGINE the engine folder (code, providers/, tools/, engine_data/,
settings, scripts). The same rule as repo_layout.py, which test_code_layout keeps equal. No test computes either
from its own __file__.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine" if (REPO / "engine").is_dir() else REPO


# The engine's code folders, the one list every guard reads (2026-10-09: seven guards kept their own copy, so a new
# package would slip out of the ones that missed it). A new folder goes here and in protected_paths.json.
CODE_DIRS = ("", "character_settings", "health", "providers", "telemetry", "tools")


def code_files(dirs=CODE_DIRS):
    """The engine's Python files in `dirs` (default: every code folder)."""
    return sorted(p for d in dirs for p in (ENGINE / d).glob("*.py"))


def rel(path) -> str:
    """A file's name as the tests' tables write it: engine files relative to the engine folder (`host_config.py`,
    `tools/x.py`), everything else relative to the repo (`static/app.js`)."""
    p = Path(path).resolve()
    base = ENGINE if ENGINE in p.parents else REPO
    return p.relative_to(base).as_posix()
