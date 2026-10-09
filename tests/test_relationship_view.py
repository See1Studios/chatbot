"""#875: a character's profile shows the relationship as the engine reads it -- a list of {label, value} lines from
items.FACT_SOURCES, drawn as they come (the private session's data is rough; a new source needs no page change).
Run: engine/run-tests.sh test_relationship_view
"""
import json
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402
sys.path.insert(0, str(ENGINE))
import items  # noqa: E402

STATIC = REPO / "static"


class View(unittest.TestCase):
    def test_every_source_s_lines_are_listed_and_a_broken_one_is_left_out(self):
        def good(cid):
            return [items._fact("profile.rel.gifts_left", 3)]

        def broken(cid):
            raise RuntimeError("rough data")
        with mock.patch.object(items, "FACT_SOURCES", (broken, good)):
            view = items.relationship_view("c1")
        self.assertEqual(view, {"facts": [{"label": {"key": "profile.rel.gifts_left", "vars": {}}, "value": 3}]})

    def test_the_route_names_a_character_and_refuses_anything_else(self):
        self.assertEqual(items.handle_get("/api/characters/no such/relationship"), None, "not this route")
        code, body = items.handle_get("/api/characters/nope/relationship")
        self.assertEqual((code, body["ok"]), (404, False))

    def test_every_label_and_line_has_words_in_both_catalogs(self):
        src = (ENGINE / "items.py").read_text(encoding="utf-8")
        import re
        keys = set(re.findall(r'"(profile\.rel\.[a-z_]+)"', src)) | {"profile.rel.title", "profile.rel.hint"}
        for lang in ("ko", "en"):
            cat = json.loads((STATIC / "i18n" / ("%s.json" % lang)).read_text(encoding="utf-8"))
            self.assertEqual(sorted(k for k in keys if k not in cat), [], lang)


JS = r"""
const fs = require('fs');
eval(fs.readFileSync(process.argv[1], 'utf8'));
const made = [];
function shellEl(tag, cls, text) { const n = { tag, cls, text, kids: [], hidden: false, isConnected: true,
  append(...k) { this.kids.push(...k); }, appendChild(k) { this.kids.push(k); } }; made.push(n); return n; }
function shellSection(title) { const b = shellEl('div', 'shell-section'); b.appendChild(shellEl('div', 't', title)); return b; }
async function api() { return { facts: [
  { label: { key: 'profile.rel.level', vars: {} }, value: { key: 'profile.rel.level_value', vars: { level: 1, title: 'X' } } },
  { label: { key: 'profile.rel.gifts_left', vars: {} }, value: 3 },
  { label: { key: 'some.future.fact', vars: {} }, value: 'plain' } ] }; }
(async () => {
  const box = shellRelationSection({ id: 'c1' });
  const hiddenAtFirst = box.hidden;
  await new Promise(r => setTimeout(r, 10));
  const rows = made.filter(n => n.cls === 'status-item-head').map(r => r.kids.map(k => k.text));
  console.log(JSON.stringify({ hiddenAtFirst, shown: !box.hidden, rows }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Page(unittest.TestCase):
    def test_the_profile_draws_whatever_lines_come(self):
        p = subprocess.run(["node", "-e", i18n_prelude() + JS, str(STATIC / "app-shell-relation.js")],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr[-600:])
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(out["hiddenAtFirst"])
        self.assertTrue(out["shown"])
        self.assertEqual(out["rows"][0], ["관계 단계", "Lv.1 X"])
        self.assertEqual(out["rows"][1], ["오늘 남은 선물", "3"])
        self.assertEqual(out["rows"][2], ["some.future.fact", "plain"], "a new source needs no page change")

    def test_the_profile_loads_it(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="./app-shell-quota.js'), html.index('src="./app-shell-relation.js'))
        self.assertIn("shellRelationSection(c)", (STATIC / "app-shell-panes.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
