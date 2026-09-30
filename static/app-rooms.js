// app-rooms.js -- group rooms, the page half (docs/plans/character-events-and-rooms.md evt/E-2, evt/E-3). Declarations
// only. A room is a talk partner like a character: picking one (character tray, sessions tab) puts its talk into the
// main log (#log) and the main input sends to it, while the 1:1 session steps aside until one is opened again. Only
// the new-room form is a modal. The server half is room_chat.py (/api/rooms); the open room's talk is polled.

const ROOM_TEXT = {   // l10n-ok
  title: '단체방', add: '새 단체방', name: '방 이름', members: '멤버 (둘 이상)', strategy: '발언 방식', create: '만들기', cancel: '취소',   // l10n-ok
  natural: '자연스럽게 (부른 사람 먼저, 그다음 수다 성향)', list: '순서대로', manual: '부른(@) 사람만',   // l10n-ok
  placeholder: '메시지… @로 멤버를 부를 수 있어요', answering: '단체방이 답하는 중…', you: '나', failed: '실패: ',   // l10n-ok
  back: '← 1:1 대화로', count: '명', current: ' (현재)',   // l10n-ok
};
const ROOM_STRATEGIES = ['natural', 'list', 'manual'];
const ROOM_KEY = 'chatbot.roomId';   // the open room, so a reload comes back to it
// on: the main view is this room. last: the newest message drawn. back: the 1:1 session to return to.
let roomState = { rooms: [], on: false, id: '', room: null, names: {}, last: 0, busy: false, timer: 0, back: '', userTitle: '' };

function roomEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

// The room the main view shows, or ''.
function roomOpenId() { return roomState.on ? roomState.id : ''; }

// The @mention being typed at `caret`: {start, query, options} (member ids whose name starts with the query), or null.
function roomMentionAt(text, caret, names) {
  const before = String(text || '').slice(0, caret);
  const m = /(^|\s)@([^\s@]*)$/.exec(before);
  if (!m) return null;
  const query = m[2].toLowerCase();
  const options = Object.keys(names || {}).filter(id => String(names[id]).toLowerCase().startsWith(query));
  return { start: before.length - m[2].length - 1, query, options };
}

// The text with the mention being typed replaced by "@Name ".
function roomApplyMention(text, caret, name) {
  const at = roomMentionAt(text, caret, { x: name });
  if (!at) return { text, caret };
  const rest = String(text).slice(caret);
  const head = String(text).slice(0, at.start) + '@' + name + (/^\s/.test(rest) ? '' : ' ');
  return { text: head + rest, caret: head.length + (/^\s/.test(rest) ? 1 : 0) };
}

// How one message shows: who (name or the user's), whether it is the user's, and the text.
function roomMessageView(m, names, userTitle) {
  const mine = m.who === 'user';
  return { mine, who: mine ? (userTitle || ROOM_TEXT.you) : ((names || {})[m.who] || m.who), text: m.text || '', id: mine ? '' : m.who };
}

// The members line of the header and the lists: how many (ROOM_TEXT.count), then the names.
function roomMembersLabel(members, names) {
  const ids = members || [];
  return ids.length + ROOM_TEXT.count + ' · ' + ids.map(id => (names || {})[id] || id).join(', ');
}

// Member names from the character list, for a room whose talk is not loaded.
function roomCatalogNames(members) {
  const names = {};
  (members || []).forEach(id => {
    const c = (typeof characterCatalog !== 'undefined' ? characterCatalog : []).find(x => x.id === id);
    names[id] = c ? (c.name || c.title || id) : id;
  });
  return names;
}

async function roomsReload() {
  try {
    roomState.rooms = (await api('/api/rooms')).rooms || [];
  } catch (e) {
    roomState.rooms = [];
  }
}

// The room list again, into both places a room is picked from.
async function roomsRefresh() {
  await roomsReload();
  roomsTrayFill();
  roomsSessionsFill();
}

// ------------------------------------------------------------------------------------------ the room in the main view

// Opens the room in the main view. `quiet`: a failure (the room is gone) says nothing -- the reload path.
async function roomEnter(id, quiet) {
  let r;
  try {
    r = await api('/api/rooms/' + encodeURIComponent(id));
  } catch (e) {
    try { if (localStorage.getItem(ROOM_KEY) === id) localStorage.removeItem(ROOM_KEY); } catch (_) {}
    if (!quiet) await alertModal(ROOM_TEXT.failed + (e.message || e));
    return false;
  }
  roomClose();
  // The 1:1 session steps aside: with no sessionId its stream, sync loop and scrollback draw nothing into the room's
  // log, and nothing typed here can reach it. Its id stays in storage and in `back`.
  if (sessionId) roomState.back = sessionId;
  if (window.__chatEsTimer) { clearTimeout(window.__chatEsTimer); window.__chatEsTimer = null; }
  if (es) { try { es.close(); } catch (_) {} es = null; }
  sessionId = '';
  assistantNode = null; assistantBuf = '';
  setBusy(false);
  scrollbackSid = ''; scrollbackExhausted = true;
  scrollforwardSid = ''; scrollforwardExhausted = true;
  archiveBrowse = false; sessionNavPrevSid = ''; sessionNavNextSid = '';
  detachSessionBanner();
  logEl.innerHTML = '';
  if (typeof setSessionTokensFromHistory === 'function') setSessionTokensFromHistory([]);
  Object.assign(roomState, { on: true, id, last: 0, userTitle: (typeof IDENTITY !== 'undefined' && IDENTITY.user_title) || '' });
  try { localStorage.setItem(ROOM_KEY, id); } catch (_) {}
  document.body.classList.add('room-open');
  document.body.classList.remove('private-session');
  roomTake(r);
  roomHead();
  setMeta(ROOM_TEXT.title + ' · ' + r.room.name);
  switchTab('chat');
  scrollChatToBottom(true);
  roomsTrayFill();
  roomsSessionsFill();
  roomState.timer = setTimeout(roomPoll, roomState.busy ? 1500 : 5000);
  return true;
}

// The room leaves the main view; whoever opens a 1:1 session next draws it (app.js calls this before every one).
function roomClose() {
  clearTimeout(roomState.timer);
  roomState.timer = 0;
  if (!roomState.on) return;
  roomState.on = false;
  roomState.busy = false;
  try { localStorage.removeItem(ROOM_KEY); } catch (_) {}
  document.body.classList.remove('room-open');
  setProgress('', true);
  roomHead();
  roomMentionMenu();
  if (typeof refreshComposerPlaceholder === 'function') refreshComposerPlaceholder();
  updateSendButton();
  roomsSessionsFill();
}

// Back to the 1:1 session that was open before the room.
async function roomLeave() {
  let back = roomState.back;
  try { back = back || localStorage.getItem(SESSION_KEY) || ''; } catch (_) {}
  roomClose();
  try {
    if (back) { await openSession(back, 0, null, true); return; }
  } catch (_) { /* that session is gone: open whatever a fresh page would */ }
  await ensureSession();
}

// After a reload: the room that was open comes back (boot, after the 1:1 session is up).
async function roomRestore() {
  try {
    const id = localStorage.getItem(ROOM_KEY) || '';
    if (id) await roomEnter(id, true);
  } catch (_) { /* the 1:1 session stays open */ }
}

async function roomPoll() {
  clearTimeout(roomState.timer);
  const id = roomOpenId();
  if (!id) return;
  try {
    const r = await api('/api/rooms/' + encodeURIComponent(id) + '/after/' + roomState.last);
    if (roomOpenId() === id) roomTake(r);
  } catch (e) { /* keep polling: the server may be restarting */ }
  if (roomOpenId() !== id) return;
  clearTimeout(roomState.timer);   // a poll started by a send ran beside this one: one timer only
  roomState.timer = setTimeout(roomPoll, roomState.busy ? 1500 : 5000);
}

// One answer of /api/rooms/<id>: the room, its member names, whether it is answering, and the messages not drawn yet.
function roomTake(r) {
  roomState.room = r.room;
  roomState.names = r.names || {};
  roomState.busy = !!r.busy;
  const fresh = (r.messages || []).filter(m => m.n > roomState.last);
  fresh.forEach(roomDraw);
  if (fresh.length) {
    roomState.last = fresh[fresh.length - 1].n;
    roomMarkRuns();
  }
  roomBusyMark();
}

// One room message as a main bubble: the user's like any message of theirs, a member's with its own picture and name.
function roomDraw(m) {
  const v = roomMessageView(m, roomState.names, roomState.userTitle);
  if (v.mine) {
    if (typeof addUserEntry === 'function') addUserEntry(v.text, false, false, m.ts);
    else addChat('user', v.text, false, false, false, false, null, null, false, m.ts);
    return;
  }
  const node = addChat('assistant', v.text, true, false, false, false, null, null, false, m.ts);
  node.dataset.roomWho = v.id;
  node.style.setProperty('--char-avatar', 'url("' + (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '')
    + '/api/characters/' + encodeURIComponent(v.id) + '/avatar")');
  node.insertBefore(roomEl('div', 'room-who', v.who), node.firstChild);
}

// A member's picture and name open each run of its bubbles (rooms.css .room-lead), also right after another member's.
function roomMarkRuns() {
  logEl.querySelectorAll('.msg[data-room-who]').forEach(n => {
    const p = n.previousElementSibling;
    n.classList.toggle('room-lead', !(p && p.dataset && p.dataset.roomWho === n.dataset.roomWho));
  });
}

// While the room answers, the send button waits (the room takes one message at a time, #476) and the progress line
// says so. Also after every keystroke, because the main send button follows the text.
function roomBusyMark() {
  if (!roomOpenId()) return;
  if (progressEl && progressEl.hidden === roomState.busy) setProgress(roomState.busy ? ROOM_TEXT.answering : '', true);
  sendBtn.disabled = roomState.busy || !inputEl.value.trim();
  inputEl.placeholder = ROOM_TEXT.placeholder;
}

// The main send, when a room is open (app.js send()): the room API only, never the 1:1 turn.
async function roomSend(text, keepFocus) {
  const id = roomOpenId();
  if (!id || !text || roomState.busy) return;
  sendBtn.disabled = true;
  try {
    await api('/api/rooms/' + encodeURIComponent(id) + '/say', { method: 'POST', body: JSON.stringify({ text }) });
    inputEl.value = '';
    inputEl.style.height = '';
    if (typeof autoResizeInput === 'function') autoResizeInput();
    roomState.busy = true;
    await roomPoll();
  } catch (e) {
    await alertModal(ROOM_TEXT.failed + (e.message || e));
  } finally {
    roomComposerInput();
    if (keepFocus) inputEl.focus();
    else if (inputEl.blur) inputEl.blur();
  }
}

// The main input changed (app.js): the mention chips and the waiting send button follow.
function roomComposerInput() {
  roomMentionMenu();
  roomBusyMark();
}

// The members matching the @mention being typed, as chips above the composer; a tap completes the name.
function roomMentionMenu() {
  let bar = document.getElementById('roomMentions');
  const at = roomOpenId() ? roomMentionAt(inputEl.value, inputEl.selectionStart, roomState.names) : null;
  if (!bar) {
    const composer = inputEl.closest ? inputEl.closest('.composer') : null;
    if (!at || !composer) return;
    bar = roomEl('div', 'room-mentions');
    bar.id = 'roomMentions';
    composer.parentNode.insertBefore(bar, composer);
  }
  bar.textContent = '';
  bar.hidden = !(at && at.options.length);
  (at ? at.options : []).forEach(id => {
    const b = roomEl('button', 'room-mention', '@' + roomState.names[id]);
    b.type = 'button';
    b.addEventListener('pointerdown', (e) => e.preventDefault());   // the input keeps its focus, and a phone its keyboard
    b.addEventListener('click', () => {
      const r = roomApplyMention(inputEl.value, inputEl.selectionStart, roomState.names[id]);
      inputEl.value = r.text;
      inputEl.setSelectionRange(r.caret, r.caret);
      roomComposerInput();
    });
    bar.appendChild(b);
  });
}

// The header while a room is open: its name, its members, and the way back to the 1:1 talk (rooms.css hides the
// character's title and provider meanwhile; the avatar still opens the tray).
function roomHead() {
  let h = document.getElementById('roomHead');
  const title = document.getElementById('brandName');
  if (!h) {
    if (!roomState.on || !title || !title.parentNode) return;
    h = roomEl('div', 'room-head');
    h.id = 'roomHead';
    title.parentNode.appendChild(h);
  }
  h.textContent = '';
  h.hidden = !roomState.on;
  if (!roomState.on) return;
  h.appendChild(roomEl('strong', 'room-head-name', roomState.room.name));
  const sub = roomEl('div', 'sub room-head-sub');
  const who = roomEl('span', 'room-head-members', roomMembersLabel(roomState.room.members, roomState.names));
  who.title = who.textContent;
  const back = roomEl('button', 'room-back', ROOM_TEXT.back);
  back.type = 'button';
  back.addEventListener('click', () => roomLeave());
  sub.append(who, back);
  h.appendChild(sub);
}

// ------------------------------------------------------------------------------------------ where a room is picked

// The character tray (app.js calls this after every draw of it): the rooms sit with the characters. With a room open
// no character is the open one, and the one that was leads back to its 1:1 talk.
function roomsTrayFill() {
  const tray = document.getElementById('characterTray');
  if (!tray) return;
  tray.querySelectorAll('[data-room-id]').forEach(n => n.remove());
  const before = tray.querySelector('.tray-art-btn');
  roomState.rooms.forEach(r => {
    const b = roomEl('button', 'provider-portrait-btn room-portrait-btn' + (r.id === roomOpenId() ? ' active' : ''));
    b.type = 'button';
    b.setAttribute('data-room-id', r.id);
    b.title = ROOM_TEXT.title + ' · ' + r.name + ' · ' + roomMembersLabel(r.members, roomCatalogNames(r.members));
    const img = document.createElement('img');
    img.alt = r.name;
    if (typeof initialAvatar === 'function') img.src = initialAvatar(r.name);
    b.append(img, roomEl('span', 'provider-tooltip', r.name));
    b.addEventListener('click', (e) => { e.stopPropagation(); toggleCharacterTray(false); roomEnter(r.id); });
    tray.insertBefore(b, before);
  });
  const cur = roomOpenId() ? tray.querySelector('.provider-portrait-btn.active[data-character-id]') : null;
  if (cur) {
    cur.classList.remove('active');
    cur.addEventListener('click', () => roomLeave());
  }
}

// The sessions tab: the rooms are listed above the sessions and open the same way.
function roomsSessionsFill() {
  const list = document.getElementById('sessionsList');
  if (!list || !list.parentNode) return;
  let strip = document.getElementById('roomsStrip');
  if (!strip) {
    strip = roomEl('div', 'status-list rooms-strip');
    strip.id = 'roomsStrip';
    list.parentNode.insertBefore(strip, list);
  }
  strip.textContent = '';
  strip.hidden = !roomState.rooms.length;
  roomState.rooms.forEach(r => {
    const on = r.id === roomOpenId();
    const item = roomEl('div', 'status-item session-row' + (on ? ' current' : ''));
    item.setAttribute('data-room-id', r.id);
    const head = roomEl('div', 'status-item-head');
    head.append(roomEl('span', 'session-row-id', ROOM_TEXT.title + ' · ' + r.name + (on ? ROOM_TEXT.current : '')));
    item.append(head, roomEl('div', 'session-row-preview', roomMembersLabel(r.members, roomCatalogNames(r.members))));
    item.addEventListener('click', () => { if (on) switchTab('chat'); else roomEnter(r.id); });
    strip.appendChild(item);
  });
}

// ------------------------------------------------------------------------------------------ the new-room form (modal)

// The tray's room button: a new room. Picking its members and speaking order is the one thing left in a modal.
function openRooms() {
  closeRooms();
  const m = roomEl('div', 'modal-overlay rooms-overlay');
  m.id = 'roomsModal';
  m.addEventListener('click', (e) => { if (e.target === m) closeRooms(); });
  const card = roomEl('div', 'modal-card rooms');
  const head = roomEl('div', 'modal-head');
  head.appendChild(roomEl('strong', '', ROOM_TEXT.add));
  card.append(head, roomCreateForm());
  m.appendChild(card);
  document.body.appendChild(m);
}

function closeRooms() {
  const m = document.getElementById('roomsModal');
  if (m) m.remove();
}

function roomCreateForm() {
  const form = roomEl('div', 'rooms-form');
  const name = roomEl('input', 'room-name');
  name.placeholder = ROOM_TEXT.name;
  form.append(roomEl('label', 'status-hint', ROOM_TEXT.name), name, roomEl('label', 'status-hint', ROOM_TEXT.members));
  const picked = {};
  (typeof characterCatalog !== 'undefined' ? characterCatalog : []).forEach(c => {
    const row = roomEl('label', 'rooms-member');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.addEventListener('change', () => { picked[c.id] = box.checked; });
    row.append(box, roomEl('span', '', c.name || c.id));
    form.appendChild(row);
  });
  form.appendChild(roomEl('label', 'status-hint', ROOM_TEXT.strategy));
  const sel = document.createElement('select');
  ROOM_STRATEGIES.forEach(s => { const o = roomEl('option', '', ROOM_TEXT[s]); o.value = s; sel.appendChild(o); });
  form.appendChild(sel);
  const acts = roomEl('div', 'rooms-acts');
  const ok = roomEl('button', 'art-btn primary', ROOM_TEXT.create);
  ok.type = 'button';
  ok.addEventListener('click', async () => {
    try {
      const r = await api('/api/rooms', { method: 'POST', body: JSON.stringify({
        name: name.value.trim(), members: Object.keys(picked).filter(k => picked[k]), strategy: sel.value }) });
      closeRooms();
      await roomsReload();
      await roomEnter(r.room.id);
    } catch (e) {
      await alertModal(ROOM_TEXT.failed + (e.message || e));
    }
  });
  const cancel = roomEl('button', 'art-btn', ROOM_TEXT.cancel);
  cancel.type = 'button';
  cancel.addEventListener('click', closeRooms);
  acts.append(ok, cancel);
  form.appendChild(acts);
  return form;
}
