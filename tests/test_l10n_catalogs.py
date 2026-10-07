"""I18N_v1 (docs/plans/localization.md l10n/C): the page's words come from static/i18n/<lang>.json by key. Every catalog
has the same keys; every key the page names literally (tr('x'), data-i18n*) is in them; tr() falls back to English, then
to the key; the language is ?lang=, then the one kept, then the browser's, then English. The REAL app-i18n.js runs in
node against stubs.
Run: ./run-tests.sh test_l10n_catalogs
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO
STATIC = ROOT / "static"
CATALOGS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((STATIC / "i18n").glob("*.json"))}


class Catalogs(unittest.TestCase):
    def test_the_first_languages_are_there_with_the_same_keys(self):
        self.assertTrue({"ko", "en"} <= set(CATALOGS))
        en = set(CATALOGS["en"])
        for lang, cat in CATALOGS.items():
            self.assertEqual(set(cat) ^ en, set(), "%s differs from en" % lang)
            self.assertEqual([k for k, v in cat.items() if not isinstance(v, str) or not v.strip()], [], lang)

    def test_every_key_the_page_names_is_in_the_catalog(self):
        used = set()
        for js in STATIC.glob("*.js"):
            used |= set(re.findall(r"\btr\(\s*'([a-z0-9_.]+)'\s*[,)]", js.read_text(encoding="utf-8")))
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        used |= set(re.findall(r'data-i18n(?:-title|-aria-label|-placeholder|-alt)?="([^"]+)"', html))
        for css in STATIC.glob("*.css"):   # words CSS draws: var(--t-css-x) reads the css.x key (app-i18n.js)
            used |= {"css." + v for v in re.findall(r"var\(--t-css-([a-z0-9-]+)", css.read_text(encoding="utf-8"))}
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(CATALOGS["en"])), [])

    def test_every_key_the_server_names_is_in_the_catalog(self):
        # l10n/F: i18n.msg / text / field name catalog keys; a key the page cannot show is a bug in every language
        root = ROOT
        files = list(root.glob("*.py")) + list(root.glob("providers/*.py"))
        rx = re.compile(r"""\bi18n\.(?:msg|text)\(\s*["']([a-z0-9_.-]+)["']|\bi18n\.field\(\s*["']\w+["']\s*,\s*["']([a-z0-9_.-]+)["']""")
        used = {a or b for p in files for a, b in rx.findall(p.read_text(encoding="utf-8"))}
        self.assertEqual(sorted(used - set(CATALOGS["en"])), [])

    def test_the_server_sends_the_key_its_values_and_english(self):
        import sys
        sys.path.insert(0, str(ENGINE))
        import i18n
        en = CATALOGS["en"]
        key = next(k for k, v in en.items() if "{" in v)
        name = re.search(r"\{(\w+)\}", en[key]).group(1)
        m = i18n.msg(key, **{name: "X"})
        self.assertEqual((m["key"], m["vars"]), (key, {name: "X"}))
        self.assertIn("X", m["text"])
        self.assertNotIn("{" + name + "}", m["text"])
        f = i18n.field("message", key, **{name: 7})
        self.assertEqual((f["message_key"], f["message_vars"][name]), (key, "7"))
        self.assertEqual(i18n.text("no.such.key"), "no.such.key")

    def test_a_placeholder_is_the_same_in_every_language(self):
        for key, text in CATALOGS["en"].items():
            want = set(re.findall(r"\{(\w+)\}", text))
            for lang, cat in CATALOGS.items():
                self.assertEqual(set(re.findall(r"\{(\w+)\}", cat[key])), want, "%s %s" % (lang, key))

    def test_no_page_code_names_a_local_tr(self):
        # a local `tr` would hide the catalog function in its scope (why it is not `t`: a hundred locals are `t`)
        rx = re.compile(r"\b(?:const|let|var)\s+tr\b|\(\s*tr\s*[,)]|,\s*tr\s*[,)]|\btr\s*=>")
        hits = ["%s:%d" % (p.name, i) for p in STATIC.glob("*.js")
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if rx.search(line)]
        self.assertEqual(hits, [])

    def test_page_code_never_fixes_a_locale(self):
        # dates, numbers, sorting and speech follow the page's language (I18N_LANG), never a fixed one
        rx = re.compile(r"""['"](?:[a-z]{2}-[A-Z]{2}|ko|ja|zh|en)['"]""")
        hits = ["%s:%d" % (p.name, i) for p in STATIC.glob("*.js") if p.name != "app-i18n.js"
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                if rx.search(line) and ("toLocale" in line or "localeCompare" in line or "Lang" in line or "lang" in line)]
        self.assertEqual(hits, [])

    def test_it_loads_first_and_boot_waits_for_it(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="./app-i18n.js'), html.index('src="./app-api.js'))
        self.assertIn("i18nReady.then(boot)", (STATIC / "app.js").read_text(encoding="utf-8"))


HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const cats = JSON.parse(process.argv[2]);
async function run(search, kept, langs) {
  const store = { 'chatbot.lang': kept };
  const doc = { documentElement: {}, querySelectorAll: () => [] };
  const env = {
    location: { search }, navigator: { languages: langs },
    localStorage: { getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; } },
    fetch: async url => { const l = url.split('/').pop().split('.')[0]; return { ok: !!cats[l], json: async () => cats[l] }; },
    document: doc };
  const names = Object.keys(env);
  const m = new Function(...names, src + '; return { tr, i18nReady, I18N_LANG };')(...names.map(k => env[k]));
  await m.i18nReady;
  return { lang: m.I18N_LANG, html: doc.documentElement.lang, kept: store['chatbot.lang'] || '',
    hello: m.tr('x.hello', { name: 'Kit' }), onlyEn: m.tr('x.only_en'), missing: m.tr('x.none') };
}
(async () => {
  console.log(JSON.stringify({
    asked: await run('?lang=ko', '', ['en-US']),
    kept: await run('', 'ko', ['en-US']),
    browser: await run('', '', ['fr-FR', 'ko-KR']),
    none: await run('', '', ['fr-FR']),
    odd: await run('?lang=xx', '', []) }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cats = {"en": {"x.hello": "Hello {name}", "x.only_en": "only English"}, "ko": {"x.hello": "{name} 안녕"}}  # l10n-ok
        r = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-i18n.js"), json.dumps(cats)],
                           capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_language_is_asked_then_kept_then_the_browsers_then_english(self):
        self.assertEqual([self.o[k]["lang"] for k in ("asked", "kept", "browser", "none", "odd")],
                         ["ko", "ko", "ko", "en", "en"])
        self.assertEqual(self.o["asked"]["kept"], "ko", "?lang= is kept for this browser")
        self.assertEqual(self.o["asked"]["html"], "ko", "<html lang> follows")

    def test_words_fall_back_to_english_then_to_the_key(self):
        ko = self.o["asked"]
        self.assertEqual((ko["hello"], ko["onlyEn"], ko["missing"]), ("Kit 안녕", "only English", "x.none"))  # l10n-ok
        self.assertEqual(self.o["none"]["hello"], "Hello Kit")


if __name__ == "__main__":
    unittest.main()
