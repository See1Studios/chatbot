"""highlight.js loads only when a code block needs it (HIGHLIGHT_LAZY_v1, static/markdown.js): no script tag on the
page, no load for a message without code, one load for the first code block, then the block is highlighted. The
REAL functions run in node against a stub document.
Run: python3 -m unittest tests.test_highlight_lazy  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const code = src.slice(src.indexOf('let highlightLoadingPromise'), src.indexOf('async function renderMermaidIn'))
  + src.slice(src.indexOf('function highlightCodeIn'), src.indexOf('\n}\n', src.indexOf('function highlightCodeIn')) + 3);
const scripts = [];
const window = {};
const document = { createElement: () => ({}), head: { appendChild: (s) => scripts.push(s) } };
const block = (lang) => ({ className: lang ? 'language-' + lang : '', closest: () => ({ classList: { contains: () => false },
  closest: () => null, querySelector: () => null, appendChild() {} }) });
const container = (blocks) => ({ querySelectorAll: () => blocks });
const { highlightCodeIn } = new Function('window', 'document', 'hljs_',
  code.replace(/\bhljs\.highlightElement/g, 'window.hljs.highlightElement') + '; return { highlightCodeIn };')(window, document);
(async () => {
  const out = {};
  highlightCodeIn(container([])); out.noCode = scripts.length;
  const b = block('py'); highlightCodeIn(container([b])); highlightCodeIn(container([block()]));
  out.loads = scripts.length; out.src = scripts[0] && scripts[0].src;
  const seen = [];
  window.hljs = { highlightElement: (el) => seen.push(el.className) };
  scripts[0].onload();
  await new Promise(r => setTimeout(r, 10));
  out.highlighted = seen.slice();
  highlightCodeIn(container([block('js')])); out.afterLoad = { loads: scripts.length, highlighted: seen.length };
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class HighlightLazy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "markdown.js")], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_message_without_code_loads_nothing(self):
        self.assertEqual(self.o["noCode"], 0)

    def test_the_first_code_block_loads_it_once_then_it_highlights(self):
        self.assertEqual(self.o["loads"], 1, "two blocks before the load finished share one request")
        self.assertEqual(self.o["src"], "./vendor/highlight.min.js")
        self.assertEqual(sorted(self.o["highlighted"]), ["", "language-py"])
        self.assertEqual(self.o["afterLoad"], {"loads": 1, "highlighted": 3})

    def test_the_page_does_not_load_it_up_front(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("highlight.min.js", page)
        self.assertIn("highlight-github-dark.min.css", page, "the theme stays: it is small")


if __name__ == "__main__":
    unittest.main()
