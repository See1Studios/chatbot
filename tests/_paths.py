"""Where the tests find things (LAYOUT_v1, docs/plans/repo-layout.md): REPO is the repository root (static/,
templates/, tests/, docs/, the entry files), ENGINE the engine folder (code, providers/, tools/, engine_data/,
settings, scripts). The same rule as repo_layout.py, which test_code_layout keeps equal. No test computes either
from its own __file__.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine" if (REPO / "engine").is_dir() else REPO
