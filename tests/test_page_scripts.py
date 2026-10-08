"""The page script stays in parts a person or a small model can read (APP_SPLIT_v1, monolith-split Phase 5; measured in
bytes since split/0, as in test_file_sizes), and the parts load in an order that works: every script index.html names
is run, in that order, in one global scope with a permissive fake browser, and nothing may fail at load (a part calling
into a later one, a name used before it is declared). Skipped when node is not installed.
Run: engine/run-tests.sh test_page_scripts
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"
MAX_BYTES = 43_000
CEILINGS = {"app-shell.js": 50_500}   # parts over the cap already: no growth (app-shell.js gained appearance & team menus & icons with #817)
BYTES_SLACK = 2_000

HARNESS = r"""
// Load the page's scripts in order in one global scope with a permissive fake browser; report load-time errors.
const fs = require('fs'), vm = require('vm');
const files = process.argv.slice(1).filter(a => a.endsWith('.js'));   // node -e: argv[1] is the first file
function stub(name) {
  const f = function () { return stub(name + '()'); };
  return new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => '';
      if (k === 'then') return undefined;
      if (k === Symbol.iterator) return function* () {};
      if (k === 'length') return 0;
      if (k === 'getItem') return () => null;
      if (k === 'matches') return false;
      if (k === 'pathname') return '/chat/';
      if (k === 'search' || k === 'hash' || k === 'value' || k === 'textContent' || k === 'innerHTML') return '';
      if (k in t && k !== 'name' && k !== 'call' && k !== 'apply' && k !== 'bind') return t[k];
      return stub(name + '.' + String(k));
    },
    set() { return true; }, apply() { return stub(name + '()'); }, construct() { return stub('new ' + name); },
    has() { return true; },
  });
}
const errors = [];
const ctx = { console, setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {},
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Map, Set, WeakMap, Symbol, Error, TypeError,
  URL, URLSearchParams, encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN, Intl, Proxy, Reflect,
  queueMicrotask, structuredClone: (x) => x, TextEncoder, TextDecoder, AbortController, performance };
for (const n of ['document', 'navigator', 'localStorage', 'sessionStorage', 'location', 'history', 'EventSource', 'fetch',
  'requestAnimationFrame', 'cancelAnimationFrame', 'matchMedia', 'getComputedStyle', 'MutationObserver', 'ResizeObserver',
  'IntersectionObserver', 'Image', 'Audio', 'speechSynthesis', 'SpeechSynthesisUtterance', 'marked', 'hljs', 'DOMPurify',
  'mermaid', 'visualViewport', 'Notification', 'Blob', 'FileReader', 'FormData', 'HTMLElement', 'Node', 'CustomEvent',
  'Event', 'KeyboardEvent', 'crypto', 'screen', 'alert', 'confirm', 'prompt', 'open', 'scrollTo', 'addEventListener',
  'removeEventListener', 'dispatchEvent', 'getSelection', 'innerWidth', 'innerHeight', 'devicePixelRatio', 'caches',
  'indexedDB', 'Worker', 'WebSocket', 'XMLHttpRequest', 'btoa', 'atob', 'CSS', 'ClipboardItem', 'Live2DCubismCore', 'PIXI']) ctx[n] = stub(n);
ctx.location = stub('location');
ctx.fetch = () => new Promise(() => {});
ctx.window = ctx; ctx.self = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
process.on('unhandledRejection', (e) => { if (e instanceof Error && /ReferenceError|before initialization|is not defined/.test(String(e))) errors.push('async ' + String(e)); });
for (const f of files) {
  try { vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f }); }
  catch (e) { errors.push(f + ': ' + e.constructor.name + ': ' + e.message + ' @ ' + String(e.stack).split('\n')[1]); }
}
setImmediate(() => { console.log(JSON.stringify(errors)); });
"""


def page_scripts():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return [STATIC / n for n in re.findall(r'<script src="\./([a-z0-9-]+\.js)', html)]


class PageScripts(unittest.TestCase):
    def test_every_part_stays_under_its_cap(self):
        for p in sorted(STATIC.glob("*.js")) + sorted(STATIC.glob("*.css")):
            n, limit = p.stat().st_size, CEILINGS.get(p.name, MAX_BYTES)
            self.assertLessEqual(n, limit, "%s is %d bytes (cap %d): split it by feature (docs/plans/archive/2026/monolith-split.md)"
                                 % (p.name, n, limit))

    def test_ceilings_are_only_for_parts_really_over_the_cap(self):
        for name, ceiling in CEILINGS.items():
            n = (STATIC / name).stat().st_size
            self.assertGreater(n, MAX_BYTES, "%s is under the cap now: drop its ceiling" % name)
            self.assertLessEqual(ceiling - n, BYTES_SLACK, "%s shrank to %d bytes: lower its ceiling" % (name, n))

    def test_every_part_is_loaded_and_before_app_js(self):
        names = [p.name for p in page_scripts()]
        parts = sorted(p.name for p in STATIC.glob("app-*.js"))
        self.assertEqual(sorted(n for n in names if n.startswith("app-")), parts)
        for n in parts:
            self.assertLess(names.index(n), names.index("app.js"), n)

    def test_every_stylesheet_part_is_linked(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        linked = re.findall(r'<link rel="stylesheet" href="\./(chat-[a-z-]+\.css)', html)
        self.assertEqual(sorted(linked), sorted(p.name for p in STATIC.glob("chat-*.css")))
        self.assertFalse((STATIC / "chat.css").exists(), "chat.css was split into chat-*.css (CSS_SPLIT_v1)")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_the_page_loads_without_errors(self):
        files = [str(p) for p in page_scripts()]
        r = subprocess.run(["node", "-e", HARNESS] + files, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), [])


if __name__ == "__main__":
    unittest.main()
