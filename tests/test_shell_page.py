"""The messenger shell, first slice (static/app-shell.js, plan ux/S1): the talk list's rows (one per character, one
per group room, newest first, a private talk never previewed), the one-line preview, the time label, the name filter,
what picking a row calls, and the switch (off unless ?shell=2 -- the page everyone uses must not change). The REAL
functions run in node against a stub page.
Run: python3 -m unittest tests.test_shell_page  (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "shell.css").read_text(encoding="utf-8")

PAGE = r"""
const setTimeout = () => 0, clearTimeout = () => {}, setInterval = () => 0;
const cls = new Set(['shell2']);
const classList = { add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c) };
const document = { documentElement: { classList }, getElementById: () => null, addEventListener() {}, hidden: false };
const pushed = [];
const window = { innerWidth: 400, addEventListener() {} }, history = { pushState: (s) => pushed.push(s) };
const calls = [];
let open = { character: 'a', room: '' };
const characterCatalog = [{ id: 'a', name: 'Kit', default: true }, { id: 'b', name: 'Kiki' }, { id: 'c', title: 'Ari' }];
const openCharacterId = () => open.character, roomOpenId = () => open.room;
const roomEnter = async (id) => { calls.push('roomEnter ' + id); }, roomLeave = async () => { calls.push('roomLeave'); };
const selectCharacter = async (c) => { calls.push('selectCharacter ' + c.id); };
const api = async () => ({ sessions: [] });
"""

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + src + `;
return (async () => {
  const chars = characterCatalog;
  const at = (y, m, d, h) => new Date(y, m, d, h, 5).getTime() / 1000;   // local time, so the day holds in any zone
  const sessions = [   // newest first, as /api/sessions gives them; '' is the default character
    { id: 's4', character: 'b', mode: 'private', updated_at: 400, preview: 'secret words' },
    { id: 's3', character: '', mode: 'work', updated_at: 300, preview: '[expression: joy] *waves* hello  there <!--choices: a | b-->' },
    { id: 's2', character: 'b', mode: 'work', updated_at: 200, preview: 'older work talk' },
  ];
  const rooms = [{ id: 'room_1', name: 'Team', members: ['a', 'b'], created: 350 }];
  const rows = shellRows(chars, sessions, rooms, { character: 'a', room: '', mode: 'work' });
  const o = {
    order: rows.map(r => r.kind + ':' + r.id),
    kiki: rows.find(r => r.id === 'b'),
    kit: rows.find(r => r.id === 'a'),
    ari: rows.find(r => r.id === 'c'),
    room: rows.find(r => r.id === 'room_1'),
    inRoom: shellRows(chars, sessions, rooms, { character: 'a', room: 'room_1', mode: 'work' }).filter(r => r.current).map(r => r.id),
    openPrivate: shellRows(chars, sessions, rooms, { character: 'a', room: '', mode: 'private' }).find(r => r.id === 'a'),
    filter: shellFilter(rows, ' ki ').map(r => r.name),
    preview: shellPreview('[expression: shy]\\n**bold** and \`code\`\\n\`\`\`thought\\nhidden\\n\`\`\`\\n<!--choices: x -> (y)-->'),
    cutComment: shellPreview('said <!--choices: never clos'),
    today: shellTime(at(2026, 8, 30, 9), at(2026, 8, 30, 18), 'en-US'),
    yesterday: shellTime(at(2026, 8, 29, 23), at(2026, 8, 30, 1), 'en-US'),
    older: shellTime(at(2026, 8, 20, 9), at(2026, 8, 30, 18), 'en-US'),
    lastYear: shellTime(at(2025, 8, 20, 9), at(2026, 8, 30, 18), 'en-US'),
    never: shellTime(0, 1),
    text: ['title', 'search', 'empty', 'private', 'room', 'newRoom', 'back', 'list', 'fresh'].every(k => SHELL_TEXT[k]),
  };
  // picking rows: the tray's calls
  await shellPick({ kind: 'character', id: 'b' });
  await shellPick({ kind: 'room', id: 'room_1' });
  open = { character: 'a', room: 'room_1' };
  await shellPick({ kind: 'room', id: 'room_1' });        // the open room: nothing to do
  await shellPick({ kind: 'character', id: 'a' });         // the character under the room: back to its 1:1 talk
  await shellPick({ kind: 'character', id: 'b' });
  o.calls = calls;
  // narrow: the list covers the chat; entering the chat from it adds one history step
  shellShowList();
  o.listShown = cls.has('shell-list');
  shellShowChat(); shellShowChat();
  o.chatShown = !cls.has('shell-list');
  o.pushed = pushed.length;
  // off: nothing draws, nothing starts
  cls.delete('shell2');
  o.off = [shellOn(), shellInit(), shellListDraw()];
  return o;
})();`);
run().then(o => console.log(JSON.stringify(o)));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ShellList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(["node", "-e", HARNESS, str(STATIC / "app-shell.js"), PAGE], capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        cls.o = json.loads(p.stdout)

    def test_one_row_per_character_and_room_newest_first(self):
        # Kiki's newest talk (400), the room (350), Kit (300), then Ari who has no talk yet
        self.assertEqual(self.o["order"], ["character:b", "room:room_1", "character:a", "character:c"])
        self.assertEqual(self.o["ari"]["preview"], "")
        self.assertEqual(self.o["ari"]["name"], "Ari")

    def test_the_default_character_owns_sessions_without_a_character(self):
        self.assertEqual(self.o["kit"]["at"], 300)
        self.assertTrue(self.o["kit"]["current"])

    def test_a_private_talk_is_never_previewed(self):
        kiki = self.o["kiki"]
        self.assertTrue(kiki["private"])
        self.assertEqual(kiki["preview"], "")
        self.assertNotIn("secret", json.dumps(kiki))
        # the open character in private mode is masked too, whatever its newest listed session says
        self.assertTrue(self.o["openPrivate"]["private"])
        self.assertEqual(self.o["openPrivate"]["preview"], "")

    def test_the_preview_is_one_clean_line(self):
        self.assertEqual(self.o["kit"]["preview"], "waves hello there")
        self.assertEqual(self.o["preview"], "bold and code")
        self.assertEqual(self.o["cutComment"], "said")      # the server cuts at 80 characters: a comment may not close

    def test_an_open_room_is_the_only_current_row(self):
        self.assertEqual(self.o["inRoom"], ["room_1"])
        self.assertEqual(self.o["room"]["members"], ["a", "b"])

    def test_the_filter_matches_names(self):
        self.assertEqual(self.o["filter"], ["Kiki", "Kit"])

    def test_time_label(self):
        self.assertRegex(self.o["today"], r"\d{1,2}:\d{2}")
        self.assertEqual(self.o["yesterday"], "yesterday")
        self.assertEqual(self.o["older"], "9/20")
        self.assertIn("2025", self.o["lastYear"])
        self.assertEqual(self.o["never"], "")

    def test_picking_a_row_makes_the_trays_calls(self):
        self.assertEqual(self.o["calls"], ["selectCharacter b", "roomEnter room_1", "roomLeave", "selectCharacter b"])

    def test_narrow_list_and_chat(self):
        self.assertTrue(self.o["listShown"])
        self.assertTrue(self.o["chatShown"])
        self.assertEqual(self.o["pushed"], 1)

    def test_words_are_in_one_table(self):
        self.assertTrue(self.o["text"])

    def test_off_does_nothing(self):
        self.assertEqual(self.o["off"], [False, None, None])


class ShellSwitch(unittest.TestCase):
    def test_the_page_is_unchanged_without_the_switch(self):
        self.assertNotRegex(HTML, r'<html[^>]*class="[^"]*shell2')
        self.assertIn("localStorage.getItem('chatbot.shell') === '2'", HTML)
        self.assertIn("q.get('compact') !== '1'", HTML)
        self.assertTrue(CSS.split("*/", 1)[1].lstrip().startswith("#shellList,#shellBack{display:none}"))
        # every rule that touches the existing page is under the switch
        for rule in re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
            for sel in rule.split(","):
                sel = sel.strip()
                if sel.startswith("@") or not sel or sel == "#shellList" or sel == "#shellBack":
                    continue
                self.assertTrue(sel.startswith("html.shell2") or sel.startswith(".shell-") or sel.startswith("#shellSearch"),
                                "shell.css styles the old page without the switch: %r" % sel)

    def test_wiring(self):
        self.assertIn('id="shellList"', HTML)
        self.assertIn('id="shellRooms"', HTML)
        self.assertIn('id="shellBack"', HTML)
        self.assertLess(HTML.index('src="./app-rooms.js'), HTML.index('src="./app-shell.js'))
        self.assertLess(HTML.index('src="./app-shell.js'), HTML.index('src="./app.js'))
        self.assertLess(HTML.index("rooms.css"), HTML.index("shell.css"))
        self.assertIn("shellInit()", (STATIC / "app.js").read_text(encoding="utf-8"))

    def test_the_list_words_are_not_in_the_page_source(self):
        aside = HTML[HTML.index('<aside id="shellList"'):HTML.index("</aside>")]
        self.assertNotRegex(aside, r"[가-힣]")


if __name__ == "__main__":
    unittest.main()
