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


def _lum(hexv):
    v = hexv.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    ch = [int(v[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ThemeContrast(unittest.TestCase):
    """critique run 4: the mono theme's --muted (#5c5c5c) on its card was about 2.9:1 -- list previews and times."""
    def test_muted_text_passes_aa_on_the_card_in_every_theme(self):
        css = re.sub(r"/\*.*?\*/", "", (STATIC / "chat-base.css").read_text(encoding="utf-8"), flags=re.S)
        blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        root = next(body for sel, body in blocks if sel.strip() == ":root" and "--bg-card" in body)
        get = lambda body, name: (re.search(r"%s:\s*(#[0-9a-fA-F]{3,6})\b" % re.escape(name), body) or [None, None])[1]
        base_bg, base_muted = get(root, "--bg-card"), get(root, "--muted")
        checked = 0
        for sel, body in blocks:
            muted, bg = get(body, "--muted"), get(body, "--bg-card")
            if not muted and not bg:
                continue
            muted, bg = muted or base_muted, bg or base_bg
            self.assertGreaterEqual(round(_ratio(muted, bg), 2), 4.5, "%s: --muted %s on --bg-card %s" % (sel.strip()[:40], muted, bg))
            checked += 1
        self.assertGreater(checked, 1)


if __name__ == "__main__":
    unittest.main()
