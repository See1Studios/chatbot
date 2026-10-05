"""No new import cycle between engine modules (monolith-split split/D). Two modules that import each other -- at the top
or inside a function -- have no layer that comes first: identity.py once imported characters inside 11 functions only
because characters imported identity back for one helper. The pairs below are known, each with why it stays; a pair
not listed fails, and a listed pair that is gone must be dropped (the list only shrinks).
Run: python3 -m unittest tests.test_import_cycles  (from services/chatbot)
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KNOWN = {
    ("mcp_server", "nas_mcp_host"): "the host plugin takes envelope helpers back from the tool server, which loads it last",
    ("media_handler", "session"): "media paths are read from session at call time, so tests that move them reach here",
    ("preview_guard", "server"): "preview roots are read from server at call time, so tests that move them reach here",
    ("private_engine", "threshold"): "the private room's note and its tension stage, each read when a turn needs it",
    ("providers.account_login", "providers.accounts"): "a pending login's pid is spared when strays are reaped",
    ("session", "session_turn"): "mixin of AgentSession; reads session's names at call time (split/C)",
    ("session", "session_view"): "mixin of AgentSession; reads session's names at call time (split/C)",
}


def modules():
    return sorted(list(ROOT.glob("*.py")) + list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").glob("*.py")))


def name(p: Path) -> str:
    return p.stem if p.parent == ROOT else "%s.%s" % (p.parent.name, p.stem)


def imports() -> dict:
    """{module: modules of this repo it imports anywhere in its body}."""
    local = {name(p) for p in modules()}
    out = {}
    for p in modules():
        me, found = name(p), set()
        for x in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            targets = []
            if isinstance(x, ast.Import):
                targets = [a.name for a in x.names]
            elif isinstance(x, ast.ImportFrom) and x.level == 0 and x.module:
                targets = [x.module] + ["%s.%s" % (x.module, a.name) for a in x.names]
            elif (isinstance(x, ast.Call) and getattr(x.func, "id", "") == "__import__" and x.args
                  and isinstance(x.args[0], ast.Constant)):
                targets = [x.args[0].value]
            found.update(t for t in targets if t in local and t != me)
        out[me] = found
    return out


class ImportCycles(unittest.TestCase):
    def test_no_pair_of_modules_imports_each_other_beyond_the_known_ones(self):
        dep = imports()
        pairs = {tuple(sorted((a, b))) for a in dep for b in dep[a] if a in dep.get(b, ())}
        new = sorted(pairs - set(KNOWN))
        self.assertEqual(new, [], "these modules import each other: let the lower layer stop importing the upper "
                                  "(move what it needs down), or list the pair in KNOWN with why")
        gone = sorted(set(KNOWN) - pairs)
        self.assertEqual(gone, [], "no longer a cycle: drop it from KNOWN")

    def test_characters_is_below_identity(self):
        dep = imports()
        self.assertIn("characters", dep["identity"])
        self.assertNotIn("identity", dep["characters"])


if __name__ == "__main__":
    unittest.main()
