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
// a small DOM for the list: enough to see which rows exist, in what order, and how often a picture is loaded
const srcSets = [];
const mkEl = (tag) => {
  const e = { tag, children: [], parent: null, attrs: {}, className: '', textContent: '', _src: '',
    append(...c) { c.forEach(x => this.insertBefore(x, null)); }, appendChild(c) { return this.insertBefore(c, null); },
    insertBefore(c, ref) { if (c.parent) c.remove(); const i = ref ? this.children.indexOf(ref) : this.children.length; this.children.splice(i, 0, c); c.parent = this; return c; },
    remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } },
    querySelector(sel) { return this.children.find(c => ('.' + c.className) === sel) || null; },
    setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, addEventListener() {} };
  Object.defineProperty(e, 'src', { get() { return e._src; }, set(v) { e._src = v; srcSets.push(v); } });
  return e;
};
const box = mkEl('div');
const document = { documentElement: { classList }, getElementById: (id) => (id === 'shellRooms' ? box : null), createElement: mkEl,
  addEventListener() {}, hidden: false };
const roomState = { rooms: [] }, look = {};
const characterOwnPortrait = (c) => c.id + '@' + (look[c.id] || ''), initialAvatar = (name) => 'initial:' + name;
const roomCatalogNames = () => ({ a: 'Kit', b: 'Kiki' }), roomMembersLabel = (m) => m.join(',');
const pushed = [];
const window = { innerWidth: 400, addEventListener() {} }, history = { pushState: (s) => pushed.push(s) };
const calls = [];
let open = { character: 'a', room: '' };
const characterCatalog = [{ id: 'a', name: 'Kit', default: true }, { id: 'b', name: 'Kiki' }, { id: 'c', title: 'Ari' }];
const openCharacterId = () => open.character, roomOpenId = () => open.room;
const roomEnter = async (id) => { calls.push('roomEnter ' + id); }, roomLeave = async () => { calls.push('roomLeave'); };
const selectCharacter = async (c) => { calls.push('selectCharacter ' + c.id); };
let currentTab = 'chat';
const switchTab = (t) => { currentTab = t; };
let sessionFilter = '';
const setSessionCharFilter = (id) => { sessionFilter = id; };
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
    presence: [shellPresenceText('work', false), shellPresenceText('work', true), shellPresenceText('private', false)],
    profile: shellProfileRows({ art: true, manage: true }),
    teamShows: [shellTeamShows('kit', 'kit'), shellTeamShows('ari', 'kit'), shellTeamShows('', 'kit'), shellTeamShows('kit', ''), shellTeamShows('', '')],
    profileBare: shellProfileRows({ art: false }).map(r => r.k),
    brains: shellBrainOptions([{ id: 'x', name: 'X' }, { id: 'y', name: 'Y' }], 'y', (id) => (id === 'x' ? 'no login' : ''), (p) => p.name + '!'),
    models: shellModelOptions([{ value: 'm1', label: 'One' }, { value: 'm2' }], 'm2'),
    noModels: shellModelOptions(null, ''),
    settings: shellSettingsRows({ advanced: true, dev: false, revive: true }),
    settingsShipped: shellSettingsRows({ advanced: false, revive: false }).map(r => r.k),
    panes: SHELL_PANES,
    plusWork: shellPlusList({ private: false, attach: 'file', geo: { label: 'geo', on: true }, slash: 'cmd' }),
    plusPrivate: shellPlusList({ private: true, attach: 'item', geo: { label: 'geo', on: false }, slash: 'cmd' }),
    plusBare: shellPlusList({ private: false, attach: '', geo: null, slash: '' }).map(x => x.k),
    text: ['title', 'search', 'empty', 'private', 'room', 'newRoom', 'back', 'list', 'fresh', 'you', 'office', 'privateRoom', 'near', 'thinking', 'brain', 'more', 'act',
      'profile', 'settings', 'back2', 'close', 'dev', 'details', 'theme', 'files', 'history', 'art', 'model', 'log', 'accounts', 'team', 'manage', 'improve', 'revive'].every(k => SHELL_TEXT[k]),
  };
  // drawing: nothing before the first load; then rows are kept and updated in place
  shellListDraw();
  o.beforeReady = box.children.length;
  shellState.ready = true; shellState.talks = talks; roomState.rooms = rooms;
  shellListDraw();
  const first = box.children.slice(), n1 = srcSets.length;
  o.drawn = first.map(n => n.attrs['data-kind'] + ':' + n.attrs['data-id'] + (n.attrs['aria-current'] ? '*' : ''));
  o.firstLoads = n1;
  o.roomLine = first[1].children[3].textContent;
  shellListDraw();
  o.redrawLoads = srcSets.length - n1;
  look.b = 'y';
  shellListDraw();
  o.lookLoads = srcSets.slice(n1);
  shellState.talks = Object.assign({}, talks, { a: { at: 999, preview: 'now' } });
  shellListDraw();
  o.moved = box.children.map(n => n.attrs['data-id']);
  o.sameNodes = box.children.length === first.length && box.children.every(n => first.includes(n));
  o.movedLoads = srcSets.length - n1 - 1;
  roomState.rooms = [];
  shellListDraw();
  o.afterRoomsGone = box.children.map(n => n.attrs['data-id']);
  shellState.filter = 'zzz';
  shellListDraw();
  o.emptyShown = [box.children.length, box.children[0].className];
  shellState.filter = '';
  // picking rows: the tray's calls
  await shellPick({ kind: 'character', id: 'b' });
  await shellPick({ kind: 'room', id: 'room_1' });
  open = { character: 'a', room: 'room_1' };
  await shellPick({ kind: 'room', id: 'room_1' });        // the open room: nothing to do
  await shellPick({ kind: 'character', id: 'a' });         // the character under the room: back to its 1:1 talk
  await shellPick({ kind: 'character', id: 'b' });
  o.calls = calls.slice();
  // a pick shows at once, the switch runs behind it, and of the picks made meanwhile only the newest is opened
  open = { character: 'a', room: '' };
  calls.length = 0;
  const running = shellPick({ kind: 'character', id: 'b' });
  o.atOnce = { switching: cls.has('shell-switching'), pending: shellState.pending,
    current: box.children.filter(n => n.attrs['aria-current']).map(n => n.attrs['data-id']) };
  shellPick({ kind: 'character', id: 'c' });
  shellPick({ kind: 'room', id: 'room_9' });
  o.pendingNewest = shellState.pending;
  await running;
  o.rapid = calls.slice();
  o.settled = { switching: cls.has('shell-switching'), pending: shellState.pending };
  shellPick({ kind: 'character', id: 'a' });                // the open talk again: nothing fades
  o.samePick = cls.has('shell-switching');
  await new Promise(r => setImmediate(r));
  calls.length = 0; calls.push(...o.calls);
  // a pane is a screen: Back leads to where it was opened from
  {
    const opened = [];
    const realOpen = shellProfileOpen, realList = shellShowList;
    shellProfileOpen = () => opened.push('profile');
    shellShowList = () => opened.push('list');
    open = { character: 'b', room: '' };
    o.paneBack = [];
    shellGoPane('sessions', 'profile'); o.paneBack.push([currentTab, sessionFilter, shellState.paneFrom]);
    shellPaneBack(); o.paneBack.push([currentTab, opened.pop() || '']);
    shellGoPane('activity', 'settings'); o.paneBack.push([currentTab, shellState.paneFrom]);
    shellPaneBack(); o.paneBack.push([currentTab, opened.pop() || '']);           // narrow: the list the settings cover
    shellGoPane('status'); shellPaneBack(); o.paneBack.push([currentTab, opened.pop() || '']);
    const realClose = shellProfileClose;
    let closed = 0;
    shellProfileClose = () => { closed++; };
    window.innerWidth = 1400;
    shellGoPane('sessions', 'profile');
    o.paneWide = { closedForPane: closed, tab: currentTab };
    shellPaneBack();
    o.paneWide.afterClose = [currentTab, opened.pop() || ''];
    window.innerWidth = 400;
    shellProfileClose = realClose;
    shellProfileOpen = realOpen; shellShowList = realList;
    open = { character: 'a', room: 'room_1' };
  }
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

    def test_rows_are_drawn_once_the_first_load_is_in_and_then_kept(self):
        o = self.o
        self.assertEqual(o["beforeReady"], 0)
        self.assertEqual(o["drawn"], ["character:b", "room:room_1", "character:a*", "room:room_2", "character:c"])
        self.assertEqual(o["roomLine"], "Kiki: nods on it")
        self.assertEqual(o["firstLoads"], 5)                  # one picture per row
        self.assertEqual(o["redrawLoads"], 0)                 # the same list again loads nothing
        self.assertEqual(o["lookLoads"], ["b@y"])             # a changed look reloads that row only
        self.assertEqual(o["moved"], ["a", "b", "room_1", "room_2", "c"])   # a newer talk moves its row up
        self.assertTrue(o["sameNodes"])                       # ... the same elements, not new ones
        self.assertEqual(o["movedLoads"], 0)
        self.assertEqual(o["afterRoomsGone"], ["a", "b", "c"])
        self.assertEqual(o["emptyShown"], [1, "shell-empty"])

    def test_picking_a_row_makes_the_trays_calls(self):
        self.assertEqual(self.o["calls"], ["selectCharacter b", "roomEnter room_1", "roomLeave", "selectCharacter b"])

    def test_a_pick_shows_at_once_and_the_newest_pick_wins(self):
        o = self.o
        self.assertEqual(o["atOnce"], {"switching": True, "pending": "character:b", "current": ["b"]})
        self.assertEqual(o["pendingNewest"], "room:room_9")
        self.assertEqual(o["rapid"], ["selectCharacter b", "roomEnter room_9"])     # c was picked over, never opened
        self.assertEqual(o["settled"], {"switching": False, "pending": ""})
        self.assertFalse(o["samePick"])

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

    def test_the_header_says_place_and_presence(self):
        idle, busy, private = self.o["presence"]
        self.assertRegex(idle, r"^\S+ · .+")
        self.assertNotEqual(idle, busy)                       # a turn in progress changes what the character is doing
        self.assertEqual(idle.split(" · ")[0], busy.split(" · ")[0])
        self.assertTrue(private.startswith("\u2665 "))
        self.assertNotEqual(private.split(" · ")[0], idle.split(" · ")[0])

    def test_the_seven_tabs_have_a_new_home(self):
        o = self.o
        # every old tab but the chat itself is reachable: the talk's own things from its card, the app's from settings
        card = [r["k"] for r in o["profile"]]
        gear = [r["k"] for r in o["settings"]]
        self.assertEqual(card, ["art", "sessions", "artifacts", "manage"])      # the character's own things
        self.assertEqual(gear, ["details", "theme", "status", "team", "dev", "activity", "evolution", "revive"])
        self.assertEqual(sorted(k for k in card + gear if k in o["panes"]), sorted(o["panes"]))
        # the team pane is in two: one character's card from its profile, the shared part from the settings
        self.assertEqual(o["teamShows"], [True, False, False, False, True])
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("shellGoTeam(c.id, 'profile')", src)
        self.assertIn("shellGoTeam('', 'settings')", src)
        self.assertIn("card.setAttribute('data-character-id', ex.id || '')", (STATIC / "app-team.js").read_text(encoding="utf-8"))
        self.assertEqual(sorted(o["panes"]), ["activity", "artifacts", "evolution", "sessions", "status", "team"])
        # the log and improvement are developer mode's -- a switch of its own, apart from "details"
        self.assertEqual([r["k"] for r in o["profile"] + o["settings"] if r.get("dev")], ["activity", "evolution"])
        self.assertFalse([r for r in o["profile"] + o["settings"] if r.get("adv")])
        switches = {r["k"]: r["on"] for r in o["settings"] if "on" in r}
        self.assertEqual(switches, {"details": True, "dev": False})
        self.assertIn("html.shell2 body:not(.dev-mode) .shell-dev{display:none}", CSS)
        self.assertIn("const SHELL_DEV_KEY = 'pe.devMode';", src)
        self.assertIn("document.body.classList.toggle('dev-mode', dev === '1');", src)      # off unless this browser turned it on
        self.assertTrue(o["settings"][0]["on"])
        self.assertEqual(o["profileBare"], ["sessions", "artifacts"])

    def test_the_card_manages_the_brain_and_the_model_itself(self):
        o = self.o
        self.assertEqual(o["brains"], [{"id": "x", "label": "X!", "current": False, "blocked": True, "why": "no login"},
                                       {"id": "y", "label": "Y!", "current": True, "blocked": False, "why": ""}])
        self.assertEqual(o["models"], [{"value": "m1", "label": "One", "current": False}, {"value": "m2", "label": "m2", "current": True}])
        self.assertEqual(o["noModels"], [])
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        card = src[src.index("function shellProfileOpen()"):src.index("function shellSettingsClose()")]
        self.assertIn("await selectProvider(o.id)", card)          # the calls the old pickers make
        self.assertIn("pickModel(o.value)", card)
        self.assertNotIn("toggleProviderTray", card)               # ... without leaving the card for them
        self.assertNotIn("showModelMenu", card)
        self.assertEqual(o["settingsShipped"], ["details", "theme", "status", "team", "dev", "activity", "evolution"])

    def test_the_tab_bar_is_hidden_and_a_pane_leads_back(self):
        self.assertIn("html.shell2 header .bar{display:none}", CSS)
        self.assertIn('html.shell2[data-tab]:not([data-tab="chat"]) .shell-pane-bar{display:flex}', CSS)
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("back.addEventListener('click', () => shellPaneBack())", src)
        self.assertIn("if (typeof currentTab !== 'undefined' && currentTab !== 'chat') switchTab('chat');", src)   # a pick returns to the talk
        self.assertIn("document.documentElement.dataset.tab = tab;", (STATIC / "app-api.js").read_text(encoding="utf-8"))

    def test_the_card_and_the_panes_are_screens_of_the_talk_column(self):
        # the talk's header, session row and input bar belong to the talk only (operator, 2026-09-30)
        pane = 'html.shell2[data-tab]:not([data-tab="chat"]) '
        self.assertIn(pane + "header," + pane + ".meta," + pane + "#sessionBanner{display:none !important}", CSS)
        self.assertIn(':root[data-tab]:not([data-tab="chat"]) .composer', (STATIC / "chat-panes.css").read_text(encoding="utf-8"))
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        # the card: a full-height column beside the talk that opens by moving it (wide), over its edge (medium),
        # a screen of its own (phone)
        self.assertIn("document.body.appendChild(profile);", src)
        self.assertIn(".shell-profile{flex:0 0 0;", CSS)
        self.assertIn(".shell-profile.open{flex-basis:340px;", CSS)
        self.assertIn("transition:flex-basis .22s", CSS)
        self.assertRegex(CSS, r"@media \(max-width: 1279px\) \{\s*\.shell-profile\{position:fixed;")
        self.assertIn("  .shell-profile{width:100%;z-index:95;", CSS)
        self.assertIn(".shell-profile-in > *{flex-shrink:0}", CSS)                  # a long model list scrolls, never squeezes
        # the history is the open character's own; pictures open as a screen above the card
        self.assertIn("setSessionCharFilter(openCharacterId())", src)
        self.assertIn("html.shell2 #sessionCharTabs,html.shell2 #roomsStrip{display:none !important}", CSS)
        self.assertNotIn("#artManager{left:", CSS)                                  # not a restyled modal any more
        o = self.o
        # a phone: one screen after another, Back returns to the one before
        self.assertEqual(o["paneBack"], [["sessions", "b", "profile"], ["chat", "profile"], ["activity", "settings"], ["chat", "list"], ["chat", ""]])
        # a wide screen: list and detail -- the card is not closed for a pane, and closing the pane reopens nothing
        self.assertEqual(o["paneWide"], {"closedForPane": 0, "tab": "sessions", "afterClose": ["chat", ""]})

    def test_the_pictures_are_a_pane_like_the_others(self):
        # the art manager draws into an #artManager it finds: the shell puts one in the stage, without the modal class
        art = (STATIC / "app-art.js").read_text(encoding="utf-8")
        self.assertIn("let m = document.getElementById('artManager');", art)
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        go = src[src.index("async function shellGoArt"):src.index("function shellArtGone")]
        self.assertIn("shellGoPane('art', 'profile');", go)
        self.assertIn("shellEl('div', 'art-mgr-overlay shell-art')", go)
        self.assertNotIn("modal-overlay", go)
        self.assertLess(go.index("stage.appendChild(host)"), go.index("await openArtManager(cid)"))
        self.assertIn("if (now !== 'art') shellArtGone();", src)                   # leaving the pane removes it
        self.assertIn(".shell-art .modal-head{display:none}", CSS)                  # the pane bar is its header
        self.assertIn("now === 'art' ? SHELL_TEXT.art", src)

    def test_phone_transitions_follow_the_arrows(self):
        # forward enters from the right; a screen left behind waits on the left and returns from there
        self.assertIn("background:var(--bg-card);transform:translateX(102%);", CSS)             # settings
        self.assertIn("  .shell-profile.open.behind{transform:translateX(-102%);", CSS)         # the card behind a pane
        self.assertIn("html.shell2 #shellList{position:relative;overflow:hidden;", CSS)          # settings slide inside the list
        self.assertRegex(CSS, r"html\.shell2 #shellList\{position:fixed;inset:0;z-index:90;[^}]*transform:translateX\(-100%\)")
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("col.classList.add('behind')", src)
        self.assertIn("column.classList.remove('behind');", src)
        self.assertIn("p.classList.remove('open', 'behind')", src)

    def test_the_plus_menu_lists_what_the_row_carried(self):
        work = self.o["plusWork"]
        self.assertEqual([x["k"] for x in work], ["act", "attach", "geo", "slash"])
        self.assertEqual([x["label"] for x in work][1:], ["file", "geo", "cmd"])     # the buttons' own labels
        self.assertTrue(work[2]["on"])
        # private mode has no commands and no location (as the old row), and the box hands over an item, not a file
        self.assertEqual([[x["k"], x["label"]] for x in self.o["plusPrivate"]][1:], [["attach", "item"]])
        self.assertEqual(self.o["plusBare"], ["act"])

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
    def test_the_shell_is_the_default_and_the_old_page_is_one_switch_away(self):
        # on unless this browser asked for the old page (?shell=1) or it is the hub's compact frame; a browser
        # whose storage cannot be read still gets the default
        self.assertNotRegex(HTML, r'<html[^>]*class="[^"]*shell2')
        head = HTML[HTML.index("// SHELL_v2"):HTML.index("</script>", HTML.index("// SHELL_v2"))]
        self.assertIn("old = localStorage.getItem('chatbot.shell') === '1';", head)
        self.assertIn("compact = q.get('compact') === '1';", head)
        self.assertIn("if (!old && !compact) document.documentElement.classList.add('shell2');", head)
        self.assertLess(head.index("} catch(e){}"), head.index("if (!old && !compact)"))

    def test_the_old_page_is_untouched_by_the_shells_rules(self):
        self.assertTrue(CSS.split("*/", 1)[1].lstrip().startswith("#shellList,#shellBack{display:none}"))
        # every rule that touches the existing page is under the switch
        for rule in re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
            for sel in rule.split(","):
                sel = sel.strip()
                if sel.startswith("@") or not sel or sel in ("#shellList", "#shellBack", "0%", "100%"):
                    continue
                self.assertTrue(sel.startswith("html.shell2") or sel.startswith(".shell-") or sel.startswith("#shellSearch"),
                                "shell.css styles the old page without the switch: %r" % sel)

    def test_the_header_rows_of_the_old_page_are_the_advanced_densitys(self):
        for sel in ("#brandRole .brand-provider", ".meta > :not(.turn-stop-btn)"):
            self.assertIn("html.shell2 body:not(.density-advanced) " + sel + "{display:none", CSS)
        # the stop button can be parked in that row (app-turn.js placeStopBtn): it must stay reachable
        self.assertIn(".meta:not(:has(> .turn-stop-btn)){display:none}", CSS)
        self.assertIn("meta.appendChild(stopBtn)", (STATIC / "app-turn.js").read_text(encoding="utf-8"))
        self.assertIn("html.shell2 #characterTray{display:none !important}", CSS)   # the list picks, the card keeps the rest

    def test_the_simple_composer_hides_the_old_row_but_keeps_an_attached_file(self):
        for btn in ("#privateBtn", "#slashBtn", "#geoBtn", "#modelBtn"):
            self.assertIn("html.shell2 body:not(.density-advanced) " + btn, CSS)
        self.assertIn(".composer .inline-btn:not(.attached):not(.uploading):not(.error){display:none}", CSS)
        self.assertIn("html.shell2 body.density-advanced #shellPlus,html.shell2 body.room-open #shellPlus{display:none}", CSS)
        self.assertIn("html.shell2 body.density-advanced #shellHeart,html.shell2 body.room-open #shellHeart{display:none}", CSS)
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("if (!priv.disabled) priv.click()", src)      # the heart presses the real switch

    def test_the_plus_menu_opens_commands_the_way_the_button_does(self):
        # the command button listens to pointerdown, which a scripted click() never fires (#487: nothing opened)
        slash = (STATIC / "slash.js").read_text(encoding="utf-8")
        self.assertIn("slashBtnEl.addEventListener('pointerdown'", slash)
        self.assertNotIn("slashBtnEl.addEventListener('click'", slash)
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("if (it.k === 'slash' && typeof toggleSlashMenu === 'function') toggleSlashMenu();", src)
        # the other two buttons act on click
        self.assertIn("geoBtn.addEventListener('click'", (STATIC / "app.js").read_text(encoding="utf-8"))

    def test_the_list_is_headed_by_the_apps_name(self):
        self.assertRegex(HTML, r'<meta name="application-name" content="[^"]+" />')
        src = (STATIC / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("""document.querySelector('meta[name="application-name"]')""", src)

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
