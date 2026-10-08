"""Every CSS custom property the page uses without a fallback is defined somewhere (critique run 4, 2026-10-08: seven
rules said `color:var(--fg)`, a token no stylesheet defines; the browser fell back to the inherited colour, and the
detector read it as black on charcoal). A token set from script (`style.setProperty('--x', ...)`) counts as defined.
Run: engine/run-tests.sh test_css_tokens
"""
import re
import unittest

from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"


class CssTokens(unittest.TestCase):
    def test_no_undefined_token_without_a_fallback(self):
        css = {p: p.read_text(encoding="utf-8") for p in STATIC.rglob("*.css") if "vendor" not in p.parts}
        js = "".join(p.read_text(encoding="utf-8") for p in STATIC.glob("*.js"))
        defined = set(re.findall(r"(--[\w-]+)\s*:", "".join(css.values()))) | set(re.findall(r"setProperty\(\s*'(--[\w-]+)'", js))
        bad = sorted({"%s: %s" % (p.name, n) for p, text in css.items()
                      for n, fallback in re.findall(r"var\((--[\w-]+)\s*(,)?", text) if n not in defined and not fallback})
        self.assertEqual(bad, [], "define the token, use an existing one (--text, --muted, ...), or give var() a fallback")


if __name__ == "__main__":
    unittest.main()
