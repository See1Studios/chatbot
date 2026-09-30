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
  const talks = { b: { at: 400, preview: 'kiki at work' }, a: { at: 300, preview: '[expression: joy] *waves* hello  there <!--choices: a | b-->' } };
  const rooms = [{ id: 'room_1', name: 'Team', members: ['a', 'b'], created: 100, last: { at: 350, who: 'b', text: '*nods* on it' } },
    { id: 'room_2', name: 'Quiet', members: ['a', 'c'], created: 50, last: null }];
  const rows = shellRows(chars, [], rooms, { character: 'a', room: '', mode: 'work' }, talks);
  // a server that does not send talks yet: the newest WORK session among the 40 listed ('' = the default character)
  const sessions = [
    { id: 's5', character: 'b', mode: 'private', turns: 4, updated_at: 500, preview: 'secret words' },
    { id: 's4', character: 'b', mode: 'work', turns: 0, updated_at: 450, preview: '' },
    { id: 's3', character: '', mode: 'work', turns: 2, updated_at: 300, preview: 'kit old server' },
    { id: 's2', character: 'b', mode: 'work', turns: 6, updated_at: 200, preview: 'older work talk' },
  ];
  const old = shellRows(chars, sessions, [], { character: 'a', room: '', mode: 'work' }, null);
  const o = {
    order: rows.map(r => r.kind + ':' + r.id),
    kiki: rows.find(r => r.id === 'b'),
    kit: rows.find(r => r.id === 'a'),
    ari: rows.find(r => r.id === 'c'),
    room: rows.find(r => r.id === 'room_1'),
    quiet: rows.find(r => r.id === 'room_2'),
    old: old.map(r => [r.id, r.at, r.preview, r.private]),
    inRoom: shellRows(chars, [], rooms, { character: 'a', room: 'room_1', mode: 'work' }, talks).filter(r => r.current).map(r => r.id),
    openPrivate: shellRows(chars, [], rooms, { character: 'a', room: '', mode: 'private' }, talks),
    filter: shellFilter(rows, ' ki ').map(r => r.name),
    preview: shellPreview('[expression: shy]\\n**bold** and \`code\`\\n\`\`\`thought\\nhidden\\n\`\`\`\\n<!--choices: x -> (y)-->'),
    cutComment: shellPreview('said <!--choices: never clos'),
    today: shellTime(at(2026, 8, 30, 9), at(2026, 8, 30, 18), 'en-US'),
    yesterday: shellTime(at(2026, 8, 29, 23), at(2026, 8, 30, 1), 'en-US'),
    older: shellTime(at(2026, 8, 20, 9), at(2026, 8, 30, 18), 'en-US'),
    lastYear: shellTime(at(2025, 8, 20, 9), at(2026, 8, 30, 18), 'en-US'),
    never: shellTime(0, 1),
    text: ['title', 'search', 'empty', 'private', 'room', 'newRoom', 'back', 'list', 'fresh', 'you'].every(k => SHELL_TEXT[k]),
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
        # Kiki's work talk (400), the room's last message (350), Kit (300), the silent room (created 50), then Ari
        self.assertEqual(self.o["order"], ["character:b", "room:room_1", "character:a", "room:room_2", "character:c"])
        self.assertEqual(self.o["ari"]["preview"], "")
        self.assertEqual(self.o["ari"]["name"], "Ari")
        self.assertEqual(self.o["kiki"]["preview"], "kiki at work")
        self.assertTrue(self.o["kit"]["current"])

    def test_private_is_said_only_of_the_room_open_now(self):
        # a character that visited its private room earlier is not "in private": the mode belongs to the open talk
        self.assertFalse(self.o["kiki"]["private"])
        rows = {r["id"]: r for r in self.o["openPrivate"]}
        self.assertTrue(rows["a"]["private"])
        self.assertEqual(rows["a"]["preview"], "")                 # and the open private room is never previewed
        self.assertFalse(rows["b"]["private"])

    def test_without_talks_the_newest_work_session_is_used(self):
        # the private session (500) and the empty one (450) are skipped; private words never reach a row
        self.assertEqual(self.o["old"], [["a", 300, "kit old server", False], ["b", 200, "older work talk", False], ["c", 0, "", False]])

    def test_a_room_shows_its_last_message(self):
        room = self.o["room"]
        self.assertEqual((room["who"], room["preview"], room["at"]), ("b", "nods on it", 350))
        self.assertEqual((self.o["quiet"]["who"], self.o["quiet"]["preview"], self.o["quiet"]["at"]), ("", "", 50))

    def test_the_preview_is_one_clean_line(self):
        self.assertEqual(self.o["kit"]["preview"], "waves hello there")
        self.assertEqual(self.o["preview"], "bold and code")
        self.assertEqual(self.o["cutComment"], "said")      # the server cuts at 80 characters: a comment may not close

    def test_an_open_room_is_the_only_current_row(self):
        self.assertEqual(self.o["inRoom"], ["room_1"])
        self.assertEqual(self.o["room"]["members"], ["a", "b"])

    def test_the_hub_chip_is_gone_under_the_switch(self):
        self.assertIn("html.shell2 #hubLink{display:none}", CSS)
        self.assertNotIn("shell-hub", CSS + (STATIC / "app-shell.js").read_text(encoding="utf-8"))

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

    def test_private_mode_never_carries_over_to_another_character(self):
        # list and tray both go through selectCharacter, which asks for the work room whatever is on screen
        src = (STATIC / "app-characters.js").read_text(encoding="utf-8")
        body = src[src.index("async function selectCharacter(c)"):src.index("function onTrayKey")]
        self.assertIn("mode: 'work'", body)
        self.assertNotIn("sessionMode", body)

    def test_narrow_list_and_chat(self):
        self.assertTrue(self.o["listShown"])
        self.assertTrue(self.o["chatShown"])
        self.assertEqual(self.o["pushed"], 1)

    def test_words_are_in_one_table(self):
        self.assertTrue(self.o["text"])

    def test_off_does_nothing(self):
        self.assertEqual(self.o["off"], [False, None, None])


LOOK = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const part = src.slice(src.indexOf('let characterTalks'), src.indexOf('async function loadCharacters'));
const run = new Function(`
  let open = 'a', room = '', picked = 'brain-x';
  const openCharacterId = () => open, roomOpenId = () => room, providerEl = { get value() { return picked; } };
  const providerCatalog = [{ id: 'brain-x' }, { id: 'brain-y' }];
  const characterPortrait = (c, p) => c.id + '@' + ((p && p.id) || '');
` + part + `
  characterTalks = { a: { provider: 'brain-y' }, b: { provider: 'brain-y' }, c: { provider: 'gone' }, d: { provider: '' } };
  const all = () => ['a', 'b', 'c', 'd', 'e'].map(id => characterOwnPortrait({ id }));
  const o = { first: all() };
  picked = 'brain-y'; o.afterSwitch = all();           // the open talk changes provider: only its own row follows
  picked = 'brain-x'; room = 'room_1'; o.inRoom = all();   // a room is open: nobody is "the open character"
  return o;`);
console.log(JSON.stringify(run()));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class OwnLook(unittest.TestCase):
    """OWN_LOOK_v1: a character's picture follows its own provider, never the open talk's."""

    def test_each_character_keeps_its_own_providers_look(self):
        p = subprocess.run(["node", "-e", LOOK, str(STATIC / "app-characters.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        o = json.loads(p.stdout)
        # a: the open one, the provider picked now. b: the brain last used with it. c: a provider no longer in the
        # catalog still names its picture. d, e: unknown -> the plain avatar.
        self.assertEqual(o["first"], ["a@brain-x", "b@brain-y", "c@gone", "d@", "e@"])
        self.assertEqual(o["afterSwitch"], ["a@brain-y", "b@brain-y", "c@gone", "d@", "e@"])
        self.assertEqual(o["inRoom"][0], "a@brain-y")     # from its own talk, not the picker

    def test_tray_and_list_use_it(self):
        chars = (STATIC / "app-characters.js").read_text(encoding="utf-8")
        tray = chars[chars.index("function renderCharacterTray()"):chars.index("function toggleCharacterTray")]
        self.assertIn("characterOwnPortrait(c)", tray)
        self.assertIn("characterOwnPortrait(c)", (STATIC / "app-shell.js").read_text(encoding="utf-8"))


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
