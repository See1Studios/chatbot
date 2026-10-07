"""Where the engine's code is, and where the repository root is (LAYOUT_v1, docs/plans/repo-layout.md layout/B).

The repo root holds the entry files, the dev guidance and folders (static/, templates/, tests/, docs/); the engine's
code, its settings and scripts live in the engine folder. Until the move (layout/C) the two are the same folder; after
it the engine folder is `<repo>/engine`. Nothing else in the code computes either path: every module asks here, so
the move changes no constant. Standard library only (a core module: core_modules.json).
"""
from __future__ import annotations

from pathlib import Path

ENGINE_DIR_NAME = "engine"


def repo_of(engine) -> Path:
    """The repository root that holds this engine folder."""
    engine = Path(engine)
    return engine.parent if engine.name == ENGINE_DIR_NAME else engine


def engine_of(repo) -> Path:
    """The engine folder of a repository root (the root itself before the move, or in a test's throwaway root)."""
    repo = Path(repo)
    return repo / ENGINE_DIR_NAME if (repo / ENGINE_DIR_NAME).is_dir() else repo


def engine_rel(repo, name) -> str:
    """A file of the engine folder as a repo-relative path (`engine/run-tests.sh`, or `run-tests.sh` when flat)."""
    return (engine_of(repo) / name).relative_to(Path(repo)).as_posix()


ENGINE = Path(__file__).resolve().parent   # code, providers/, tools/, engine_data/, settings, scripts
REPO = repo_of(ENGINE)                     # entry files, RULES.md, CODEMAP.md, static/, templates/, tests/, docs/
STATIC = REPO / "static"
TEMPLATES = REPO / "templates"
