// app-rooms.js -- group rooms, the page half (docs/plans/character-events-and-rooms.md evt/E-2). Declarations only;
// opened from the character tray. The server half is room_chat.py (/api/rooms): several characters answer in turn,
// @mentions pick who speaks first. This view polls the room's talk while it is open.

const ROOM_TEXT = {   // l10n-ok
  title: '단체방', rooms: '방', add: '+ 새 방', none: '방이 없어요 — 새 방을 만들어 보세요', pick: '왼쪽에서 방을 고르세요',   // l10n-ok
  name: '방 이름', members: '멤버 (둘 이상)', strategy: '발언 방식', create: '만들기', cancel: '취소', close: '닫기',   // l10n-ok
  natural: '자연스럽게 (부른 사람 먼저, 그다음 수다 성향)', list: '순서대로', manual: '부른(@) 사람만',   // l10n-ok
  placeholder: '메시지… @로 멤버를 부를 수 있어요', send: '보내기', answering: '답하는 중…', you: '나', failed: '실패: ',   // l10n-ok
};
const ROOM_STRATEGIES = ['natural', 'list', 'manual'];
let roomState = { rooms: [], id: '', room: null, names: {}, messages: [], busy: false, timer: 0, userTitle: '' };

function roomEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

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

async function openRooms() {
  roomState.userTitle = (typeof IDENTITY !== 'undefined' && IDENTITY.user_title) || '';
  await roomsReload();
  renderRooms();
}

function closeRooms() {
  clearTimeout(roomState.timer);
  roomState.timer = 0;
  const m = document.getElementById('roomsModal');
  if (m) m.remove();
}

async function roomsReload() {
  try {
    roomState.rooms = (await api('/api/rooms')).rooms || [];
  } catch (e) {
    roomState.rooms = [];
  }
}

async function roomOpen(id) {
  roomState.id = id;
  roomState.messages = [];
  await roomPoll(true);
}

async function roomPoll(render) {
  clearTimeout(roomState.timer);
  if (!roomState.id || !document.getElementById('roomsModal')) return;
  const after = roomState.messages.length ? roomState.messages[roomState.messages.length - 1].n : 0;
  try {
    const r = await api('/api/rooms/' + encodeURIComponent(roomState.id) + '/after/' + after);
    roomState.room = r.room;
    roomState.names = r.names || {};
    roomState.busy = !!r.busy;
    const fresh = r.messages || [];
    roomState.messages = roomState.messages.concat(fresh);
    if (render || fresh.length) renderRooms();
    else roomBusyMark();
  } catch (e) { /* keep polling: the server may be restarting */ }
  roomState.timer = setTimeout(() => roomPoll(false), roomState.busy ? 1500 : 5000);
}

function roomBusyMark() {
  const mark = document.getElementById('roomBusy');
  if (mark) mark.hidden = !roomState.busy;
  const send = document.getElementById('roomSend');
  if (send) send.disabled = roomState.busy;
}

function renderRooms() {
  let m = document.getElementById('roomsModal');
  const draft = m && m.querySelector('.room-input') ? m.querySelector('.room-input').value : '';
  if (!m) {
    m = roomEl('div', 'modal-overlay rooms-overlay');
    m.id = 'roomsModal';
    m.addEventListener('click', (e) => { if (e.target === m) closeRooms(); });
    document.body.appendChild(m);
  }
  m.textContent = '';
  const card = roomEl('div', 'modal-card rooms');
  const head = roomEl('div', 'modal-head');
  head.appendChild(roomEl('strong', '', ROOM_TEXT.title + (roomState.room ? ' · ' + roomState.room.name : '')));
  const close = roomEl('button', 'art-btn art-btn-xs', ROOM_TEXT.close);
  close.type = 'button';
  close.addEventListener('click', closeRooms);
  head.appendChild(close);
  card.appendChild(head);
  const body = roomEl('div', 'rooms-body');
  body.appendChild(roomList());
  body.appendChild(roomState.id === '+' ? roomCreateForm() : roomChat(draft));
  card.appendChild(body);
  m.appendChild(card);
  const log = m.querySelector('.room-log');
  if (log) log.scrollTop = log.scrollHeight;
}

function roomList() {
  const side = roomEl('div', 'rooms-list');
  const add = roomEl('button', 'art-btn art-btn-xs primary', ROOM_TEXT.add);
  add.type = 'button';
  add.addEventListener('click', () => { clearTimeout(roomState.timer); roomState.id = '+'; roomState.room = null; renderRooms(); });
  side.appendChild(add);
  if (!roomState.rooms.length) side.appendChild(roomEl('div', 'status-hint', ROOM_TEXT.none));
  roomState.rooms.forEach(r => {
    const b = roomEl('button', 'rooms-item' + (r.id === roomState.id ? ' active' : ''), r.name);
    b.type = 'button';
    b.title = (r.members || []).length + '';
    b.addEventListener('click', () => roomOpen(r.id));
    side.appendChild(b);
  });
  return side;
}

function roomCreateForm() {
  const form = roomEl('div', 'rooms-main rooms-form');
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
      await roomsReload();
      await roomOpen(r.room.id);
    } catch (e) {
      await alertModal(ROOM_TEXT.failed + (e.message || e));
    }
  });
  const cancel = roomEl('button', 'art-btn', ROOM_TEXT.cancel);
  cancel.type = 'button';
  cancel.addEventListener('click', () => { roomState.id = ''; renderRooms(); });
  acts.append(ok, cancel);
  form.appendChild(acts);
  return form;
}

function roomChat(draft) {
  const main = roomEl('div', 'rooms-main');
  if (!roomState.id) {
    main.appendChild(roomEl('div', 'status-hint', ROOM_TEXT.pick));
    return main;
  }
  const log = roomEl('div', 'room-log');
  roomState.messages.forEach(m => {
    const v = roomMessageView(m, roomState.names, roomState.userTitle);
    const row = roomEl('div', 'room-msg' + (v.mine ? ' mine' : ''));
    if (!v.mine) {
      const img = document.createElement('img');
      img.className = 'room-avatar';
      img.alt = '';
      img.src = (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/characters/' + encodeURIComponent(v.id) + '/avatar';
      row.appendChild(img);
    }
    const bubble = roomEl('div', 'room-bubble');
    bubble.appendChild(roomEl('div', 'room-who', v.who));
    bubble.appendChild(roomEl('div', 'room-text', v.text));
    row.appendChild(bubble);
    log.appendChild(row);
  });
  main.appendChild(log);
  const busy = roomEl('div', 'status-hint room-busy', ROOM_TEXT.answering);
  busy.id = 'roomBusy';
  busy.hidden = !roomState.busy;
  main.appendChild(busy);
  const bar = roomEl('div', 'room-compose');
  const input = roomEl('textarea', 'room-input');
  input.rows = 2;
  input.placeholder = ROOM_TEXT.placeholder;
  input.value = draft || '';
  const menu = roomEl('div', 'room-mentions');
  const showMenu = () => {
    menu.textContent = '';
    const at = roomMentionAt(input.value, input.selectionStart, roomState.names);
    (at ? at.options : []).forEach(id => {
      const b = roomEl('button', 'art-btn art-btn-xs', '@' + roomState.names[id]);
      b.type = 'button';
      b.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const r = roomApplyMention(input.value, input.selectionStart, roomState.names[id]);
        input.value = r.text;
        input.setSelectionRange(r.caret, r.caret);
        showMenu();
      });
      menu.appendChild(b);
    });
  };
  input.addEventListener('input', showMenu);
  const send = roomEl('button', 'art-btn primary', ROOM_TEXT.send);
  send.type = 'button';
  send.id = 'roomSend';
  send.disabled = roomState.busy;   // the room answers one message at a time
  const go = async () => {
    const text = input.value.trim();
    if (!text || roomState.busy) return;
    send.disabled = true;
    try {
      await api('/api/rooms/' + encodeURIComponent(roomState.id) + '/say', { method: 'POST', body: JSON.stringify({ text }) });
      input.value = '';
      roomState.busy = true;
      await roomPoll(true);
    } catch (e) {
      await alertModal(ROOM_TEXT.failed + (e.message || e));
    } finally {
      send.disabled = roomState.busy;
    }
  };
  send.addEventListener('click', go);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); } });
  bar.append(input, send);
  main.append(menu, bar);
  return main;
}
