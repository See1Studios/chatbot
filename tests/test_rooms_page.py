"""Group rooms, the page half (static/app-rooms.js, plan evt/E-2 and evt/E-3): the @mention being typed and its
completion, how a message shows (the user's own vs a member's), the room in the main view (its talk in the main log
with the main bubbles, sending through the room API only, the 1:1 session stepping aside and coming back), and the
wiring (tray, sessions tab, page includes). The REAL functions run in node against a stub page.
Run: python3 -m unittest tests.test_rooms_page  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"

# The page around app-rooms.js, as little of it as the room needs: the 1:1 session's state (app.js), the log and
# the composer, and the calls it makes -- recorded, so the test can say what reached the 1:1 side and what did not.
PAGE = r"""
const setTimeout = () => 0, clearTimeout = () => {};   // the poll timer must not keep node alive
const mk = () => {
  const s = new Set();
  return { children: [], dataset: {}, style: { setProperty(k, v) { this[k] = v; } }, hidden: false, innerHTML: 'old', value: '',
    classList: { add: c => s.add(c), remove: c => s.delete(c), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), contains: c => s.has(c) },
    appendChild(c) { this.children.push(c); return c; }, append(...c) { this.children.push(...c); },
    insertBefore(c) { this.children.unshift(c); return c; }, addEventListener() {}, setAttribute() {},
    querySelectorAll: () => [], querySelector: () => null, remove() {}, focus() {}, blur() {}, setSelectionRange() {} };
};
const store = {};
const localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } };
const brandAvatar = mk(), brandAvatarWrap = mk();
brandAvatar.src = 'old-avatar.png';
const elById = { brandAvatar, brandAvatarWrap };
const document = { body: mk(), createElement: mk, getElementById: id => elById[id] || null };
const window = {};
const characterCatalog = [{ id: 'a', name: 'Kit', avatar_v: 1 }, { id: 'b', name: 'Kiki', avatar_v: 1 }];
const characterOwnPortrait = c => '/portraits/' + c.id;
const BASE_PATH = '';
const SESSION_KEY = 'chatbot.sessionId';
let sessionId = 's1', streamClosed = false, es = { close() { streamClosed = true; } };
let assistantNode = null, assistantBuf = '', scrollbackSid = 's1', scrollbackExhausted = false, scrollforwardSid = 's1',
  scrollforwardExhausted = false, archiveBrowse = true, sessionNavPrevSid = 's0', sessionNavNextSid = 's2';
const logEl = mk(), sendBtn = mk(), inputEl = mk(), progressEl = mk();
progressEl.hidden = true;
const drawn = [], calls = [], opened = [], progress = [];
const addChat = (role, text, isFinal, q, btw, prepend, usage, dur, sys, ts) => { const n = mk(); drawn.push({ role, text, ts, node: n }); return n; };
const setBusy = () => {}, setMeta = () => {}, switchTab = () => {}, scrollChatToBottom = () => {}, detachSessionBanner = () => {},
  updateSendButton = () => {}, alertModal = async () => {};
const setProgress = (msg) => { progress.push(msg); progressEl.hidden = !msg; };
const openSession = async (id) => { opened.push(id); sessionId = id; };
const ensureSession = async () => { opened.push('ensure'); };
let feed = { room: { id: 'room_1', name: 'Team', members: ['a', 'b'] }, names: { a: 'Kit', b: 'Kiki' }, busy: false, messages: [
  { n: 1, who: 'user', text: 'hi', ts: 1 }, { n: 2, who: 'a', text: 'yo', ts: 2 }, { n: 3, who: 'b', text: 'hey', ts: 3 }] };
const api = async (path, opts) => { calls.push(((opts && opts.method) || 'GET') + ' ' + path); return feed; };
"""

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + src + `;
return (async () => {
  const names = { a: 'Kit', b: 'Kiki', c: 'Ari' };
  const o = {
    ki: roomMentionAt('hello @Ki', 9, names),
    none: roomMentionAt('mail me@x', 9, names),
    start: roomMentionAt('@', 1, names),
    apply: roomApplyMention('hi @ki there', 6, 'Kiki'),
    applyEnd: roomApplyMention('hi @ki', 6, 'Kiki'),
    user: roomMessageView({ who: 'user', text: 'yo' }, names, '코치'),
    member: roomMessageView({ who: 'c', text: 'hey' }, names, '코치'),
    labels: ['natural', 'list', 'manual'].every(k => ROOM_TEXT[k]),
    membersLabel: roomMembersLabel(['a', 'c', 'zz'], names),
    before: roomOpenId(),
  };
  // the room takes the main view
  o.entered = await roomEnter('room_1');
  o.open = { id: roomOpenId(), sessionId, streamClosed, stored: localStorage.getItem(ROOM_KEY), marked: document.body.classList.contains('room-open'),
    logCleared: logEl.innerHTML === '', scrollback: [scrollbackSid, scrollbackExhausted, scrollforwardExhausted], past: [archiveBrowse, sessionNavNextSid] };
  // grh/A: the header avatar shows a card stack with the latest speaker's face
  o.cardStack = { isRoom: brandAvatarWrap.classList.contains('is-room'), src: brandAvatar.src };
  o.drawn = drawn.map(d => [d.role, d.text, d.ts]);
  o.memberNode = { who: drawn[1].node.dataset.roomWho, avatar: drawn[1].node.style['--char-avatar'], name: drawn[1].node.children[0].textContent };
  // a poll that overlaps what is drawn adds only the new message
  feed = Object.assign({}, feed, { messages: [feed.messages[2], { n: 4, who: 'a', text: 'more', ts: 4 }] });
  await roomPoll();
  o.afterPoll = drawn.map(d => d.text);
  o.cardStackAfterPoll = brandAvatar.src;   // grh/A: the latest speaker's face after a poll
  // sending: the room API, never the 1:1 session; then the send button waits while the room answers
  inputEl.value = '@Kit ping';
  feed = Object.assign({}, feed, { busy: true, messages: [{ n: 5, who: 'user', text: '@Kit ping', ts: 5 }] });
  await roomSend('@Kit ping', true);
  o.sent = { calls: calls.slice(), input: inputEl.value, lastDrawn: drawn[drawn.length - 1].text, progress: progress[progress.length - 1] };
  inputEl.value = 'again';
  roomComposerInput();
  o.waiting = sendBtn.disabled;
  const n = calls.length;
  await roomSend('again', true);
  o.refusedWhileBusy = calls.length === n;
  feed = Object.assign({}, feed, { busy: false, messages: [] });
  await roomPoll();
  o.free = { disabled: sendBtn.disabled, progress: progress[progress.length - 1] };
  // back to the 1:1 session that was open
  await roomLeave();
  o.left = { id: roomOpenId(), opened, stored: localStorage.getItem(ROOM_KEY), marked: document.body.classList.contains('room-open') };
  o.cardStackAfterLeave = brandAvatarWrap.classList.contains('is-room');   // grh/A: should be false
  o.avatarAfterLeave = brandAvatar.src;   // grh/A: should be restored to 'old-avatar.png'
  return o;
})();`);
run().then(o => console.log(JSON.stringify(o)));
"""


TYPING = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + 'const shellOn = () => true;' + src + `;
  roomState.names = { a: 'Kit' };
  roomTyping('a');
  const first = roomState.typing;
  const o = { made: drawn.length, live: first.dataset.live, who: first.dataset.roomWho, name: first.children[0].textContent };
  first.isConnected = true;
  roomTyping('a');
  o.kept = roomState.typing === first && drawn.length === 1;
  roomTyping('b');
  o.switched = roomState.typing !== first && roomState.typing.dataset.roomWho === 'b';
  roomTyping('');
  o.gone = roomState.typing === null;
  inputEl.value = 'hi'; inputEl.selectionStart = 2;
  roomMentionInsert('a');
  o.mention = inputEl.value;
  return o;`);
console.log(JSON.stringify(run()));
"""


EMPTY_ROOM = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + src + `;
return (async () => {
  feed = { room: { id: 'room_empty', name: 'Empty', members: ['a', 'b'] }, names: { a: 'Kit', b: 'Kiki' }, busy: false, messages: [] };
  await roomEnter('room_empty');
  const avatar = brandAvatar.src;
  await roomLeave();
  return { avatar };
})();`);
run().then(o => console.log(JSON.stringify(o)));
"""


UPDATE_AVATAR_ROOM = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + `
let updateBrandAvatarArg = null;
const providerEl = { value: 'agy' };
const updateBrandAvatar = (pid) => {
  updateBrandAvatarArg = pid;
  brandAvatar.src = '/portraits/char-' + pid + '.png';
};
` + src + `;
return (async () => {
  brandAvatar.src = 'old-avatar.png';
  brandAvatarWrap.classList.remove('is-room');
  feed = { room: { id: 'room_update', name: 'UpdateRoom', members: ['a', 'b'] }, names: { a: 'Kit', b: 'Kiki' }, busy: false,
           messages: [{ n: 1, who: 'a', text: 'hi', ts: 1 }] };
  await roomEnter('room_update');
  const enteredIsRoom = brandAvatarWrap.classList.contains('is-room');
  const enteredSrc = brandAvatar.src;
  await roomLeave();
  return {
    enteredIsRoom,
    enteredSrc,
    leftIsRoom: brandAvatarWrap.classList.contains('is-room'),
    leftSrc: brandAvatar.src,
    updateBrandAvatarArg,
  };
})();`);
run().then(o => console.log(JSON.stringify(o)));
"""


ROOM_CLOSE_DIRECT = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const run = new Function(process.argv[2] + `
let updateBrandAvatarArg = null;
const providerEl = { value: 'agy' };
const updateBrandAvatar = (pid) => {
  updateBrandAvatarArg = pid;
  brandAvatar.src = '/portraits/char-' + pid + '.png';
};
` + src + `;
return (async () => {
  brandAvatar.src = 'old-avatar.png';
  brandAvatarWrap.classList.remove('is-room');
  feed = { room: { id: 'room_close_test', name: 'CloseRoom', members: ['a', 'b'] }, names: { a: 'Kit', b: 'Kiki' }, busy: false,
           messages: [{ n: 1, who: 'b', text: 'hi', ts: 1 }] };
  await roomEnter('room_close_test');
  const onBefore = roomState.on;
  const isRoomBefore = brandAvatarWrap.classList.contains('is-room');
  const srcBefore = brandAvatar.src;
  roomClose();
  const onAfter = roomState.on;
  const isRoomAfter = brandAvatarWrap.classList.contains('is-room');
  const srcAfter = brandAvatar.src;
  return {
    onBefore,
    isRoomBefore,
    srcBefore,
    onAfter,
    isRoomAfter,
    srcAfter,
    updateBrandAvatarArg,
  };
})();`);
run().then(o => console.log(JSON.stringify(o)));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RoomTyping(unittest.TestCase):
    """Under the messenger shell the member answering shows with its face and typing dots; a face mentions it."""

    def test_the_answering_member_types_and_a_face_mentions(self):
        r = subprocess.run(["node", "-e", i18n_prelude() + TYPING, str(STATIC / "app-rooms.js"), PAGE], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((o["made"], o["live"], o["who"], o["name"]), (1, "1", "a", "Kit"))
        self.assertTrue(o["kept"])          # the same member still answering: the same node, not another
        self.assertTrue(o["switched"])      # the next member: its own node
        self.assertTrue(o["gone"])          # nobody answering: gone
        self.assertEqual(o["mention"], "hi @Kit ")

    def test_the_face_calls_the_member_in_a_room(self):
        stage = (STATIC / "app-stage.js").read_text(encoding="utf-8")
        self.assertIn("if (who && typeof roomMentionInsert === 'function') { roomMentionInsert(who); return; }", stage)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RoomsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(STATIC / "app-rooms.js"), PAGE], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_mention_being_typed_offers_matching_members(self):
        self.assertEqual((self.o["ki"]["query"], sorted(self.o["ki"]["options"]), self.o["ki"]["start"]), ("ki", ["a", "b"], 6))
        self.assertIsNone(self.o["none"], "an @ inside a word is not a mention")
        self.assertEqual(sorted(self.o["start"]["options"]), ["a", "b", "c"])

    def test_picking_a_member_completes_the_mention(self):
        self.assertEqual(self.o["apply"], {"text": "hi @Kiki there", "caret": 9}, "no doubled space")
        self.assertEqual(self.o["applyEnd"], {"text": "hi @Kiki ", "caret": 9})

    def test_the_user_s_own_message_and_a_member_s(self):
        self.assertEqual(self.o["user"], {"mine": True, "who": "코치", "text": "yo", "id": ""})
        self.assertEqual(self.o["member"], {"mine": False, "who": "Ari", "text": "hey", "id": "c"})
        self.assertTrue(self.o["labels"])
        self.assertEqual(self.o["membersLabel"], "3명 · Kit, Ari, zz", "count first, an unknown member by its id")

    def test_a_room_takes_the_main_view_and_the_one_to_one_session_steps_aside(self):
        self.assertEqual(self.o["before"], "")
        self.assertTrue(self.o["entered"])
        o = self.o["open"]
        self.assertEqual((o["id"], o["stored"], o["marked"], o["logCleared"]), ("room_1", "room_1", True, True))
        self.assertEqual((o["sessionId"], o["streamClosed"]), ("", True), "no 1:1 stream or sync draws into the room's log")
        self.assertEqual(o["scrollback"], ["", True, True], "scrolling up must not load the 1:1 session's older talk")
        self.assertEqual(o["past"], [False, ""], "a room is not a past session")

    def test_room_messages_are_main_bubbles(self):
        self.assertEqual(self.o["drawn"], [["user", "hi", 1], ["assistant", "yo", 2], ["assistant", "hey", 3]])
        m = self.o["memberNode"]
        self.assertEqual((m["who"], m["name"]), ("a", "Kit"))
        self.assertIn("/api/characters/a/avatar", m["avatar"], "each member's bubble carries its own picture")
        self.assertEqual(self.o["afterPoll"], ["hi", "yo", "hey", "more"], "an overlapping poll draws nothing twice")

    def test_sending_goes_to_the_room_only_and_waits_while_it_answers(self):
        s = self.o["sent"]
        self.assertIn("POST /api/rooms/room_1/say", s["calls"])
        self.assertFalse([c for c in s["calls"] if "/api/sessions" in c], "no 1:1 turn from a room")
        self.assertEqual((s["input"], s["lastDrawn"]), ("", "@Kit ping"))
        self.assertTrue(s["progress"], "the progress line says the room is answering")
        self.assertTrue(self.o["waiting"], "typing must not free the send button while the room answers (#476)")
        self.assertTrue(self.o["refusedWhileBusy"])
        self.assertEqual(self.o["free"], {"disabled": False, "progress": ""})

    def test_leaving_reopens_the_session_that_was_open(self):
        left = self.o["left"]
        self.assertEqual((left["id"], left["opened"], left["stored"], left["marked"]), ("", ["s1"], None, False))

    def test_card_stack_avatar_tracks_the_latest_speaker(self):
        """grh/A: room enter adds .is-room to #brandAvatarWrap, sets the latest speaker's face; leave removes it."""
        cs = self.o["cardStack"]
        self.assertTrue(cs["isRoom"], ".is-room class on brandAvatarWrap")
        # the feed has messages from a and b; b spoke last → its portrait
        self.assertEqual(cs["src"], "/portraits/b", "latest speaker's portrait after enter")
        # after a poll where 'a' is the latest speaker
        self.assertEqual(self.o["cardStackAfterPoll"], "/portraits/a", "updated to the new latest speaker")
        # after leaving the room, the card stack class is removed and 1:1 avatar restored
        self.assertFalse(self.o["cardStackAfterLeave"], ".is-room removed after leave")
        self.assertEqual(self.o["avatarAfterLeave"], "old-avatar.png", "restored 1:1 character avatar after leave")

    def test_empty_room_avatar_falls_back_to_first_member(self):
        r = subprocess.run(["node", "-e", i18n_prelude() + EMPTY_ROOM, str(STATIC / "app-rooms.js"), PAGE], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(o["avatar"], "/portraits/a", "fallback to first member's face when no messages")

    def test_room_leave_restores_avatar_via_update_brand_avatar_stub(self):
        """grh/A: when updateBrandAvatar is present, room leave calls it with providerEl.value and restores."""
        r = subprocess.run(["node", "-e", i18n_prelude() + UPDATE_AVATAR_ROOM, str(STATIC / "app-rooms.js"), PAGE], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(o["enteredIsRoom"], "card-stack enabled on enter")
        self.assertEqual(o["enteredSrc"], "/portraits/a", "speaker face displayed")
        self.assertFalse(o["leftIsRoom"], "card-stack removed on leave")
        self.assertEqual(o["updateBrandAvatarArg"], "agy", "updateBrandAvatar called with provider value")
        self.assertEqual(o["leftSrc"], "/portraits/char-agy.png", "restored avatar from updateBrandAvatar")

    def test_room_close_directly_removes_is_room_and_restores_avatar(self):
        """grh/A: calling roomClose() directly removes .is-room, clears roomState.on, and restores avatar."""
        r = subprocess.run(["node", "-e", i18n_prelude() + ROOM_CLOSE_DIRECT, str(STATIC / "app-rooms.js"), PAGE], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(o["onBefore"], "roomState.on active before close")
        self.assertTrue(o["isRoomBefore"], ".is-room active before close")
        self.assertFalse(o["onAfter"], "roomState.on false after close")
        self.assertFalse(o["isRoomAfter"], ".is-room removed after close")
        self.assertEqual(o["updateBrandAvatarArg"], "agy", "updateBrandAvatar called on direct roomClose")
        self.assertEqual(o["srcAfter"], "/portraits/char-agy.png", "avatar restored on direct roomClose")


class Wiring(unittest.TestCase):
    def setUp(self):
        self.rooms = (STATIC / "app-rooms.js").read_text(encoding="utf-8")
        self.app = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_the_page_loads_it_and_the_tray_opens_it(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("./app-rooms.js", page)
        self.assertIn("./rooms.css", page)
        self.assertLess(page.index("./app-rooms.js"), page.index("./app.js?"))
        self.assertIn("openRooms();", (STATIC / "app-characters.js").read_text(encoding="utf-8"))

    def test_the_talk_is_not_in_a_modal(self):
        css = (STATIC / "rooms.css").read_text(encoding="utf-8")
        for gone in ("room-log", "room-bubble", "room-input", "room-compose", "room-msg"):
            self.assertNotIn(gone, self.rooms, "the room talks in #log with the main bubbles and input")
            self.assertNotIn(gone, css)
        self.assertIn("addChat('assistant'", self.rooms)

    def test_the_main_send_hands_a_room_its_message_before_anything_else(self):
        send = self.app[self.app.index("async function send(opts)"):]
        branch = send.index("return roomSend(text, keepFocus);")
        self.assertLess(branch, send.index("if (text === '/clear')"), "commands are the 1:1 session's")
        self.assertLess(branch, send.index("/message'"), "no 1:1 turn")

    def test_opening_a_session_ends_the_room_and_rooms_are_picked_with_characters_and_sessions(self):
        self.assertIn("enterSession = function (id, opts) { roomClose(); return enterOneToOne(id, opts); };", self.app)
        self.assertIn("renderCharacterTray = function () { drawCharacterTray(); roomsTrayFill(); };", self.app)
        self.assertIn("await roomRestore();", self.app, "a reload comes back to the room that was open")
        self.assertIn("getElementById('characterTray')", self.rooms)
        self.assertIn("getElementById('sessionsList')", self.rooms)

    def test_what_a_room_does_not_take_is_hidden(self):
        css = (STATIC / "rooms.css").read_text(encoding="utf-8")
        for widget in ("#modelBtn", "#privateBtn", "#slashBtn", ".composer .inline-btn", "#sessionNav"):
            self.assertIn("body.room-open " + widget, css)

    def test_card_stack_avatar_css_and_js(self):
        """grh/A: the card-stack CSS targets #brandAvatarWrap.is-room and the JS toggles it."""
        css = (STATIC / "rooms.css").read_text(encoding="utf-8")
        self.assertIn("#brandAvatarWrap.is-room", css, "card-stack selector in rooms.css")
        self.assertIn("#brandAvatarWrap.is-room #brandAvatar", css, "direct brand avatar target in rooms.css")
        self.assertIn("::before", css)
        self.assertIn("::after", css)
        self.assertIn("roomHeaderAvatar", self.rooms, "avatar function in app-rooms.js")
        self.assertIn("roomLatestSpeaker", self.rooms)


if __name__ == "__main__":
    unittest.main()
