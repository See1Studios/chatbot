// app-shell.js -- the messenger shell, first slice (docs/plans/ux-shell-roadmap.md 4.2.3, ux/S1). Declarations only:
// app.js calls shellInit() once the page is up. Behind a switch: `?shell=2` turns it on for this browser, `?shell=1`
// off (index.html sets html.shell2 before first paint), so the page everyone else uses does not change.
// What it adds: a list of talks beside the chat -- one row per character, one per group room -- built from what the
// server already lists (/api/characters, /api/sessions, /api/rooms). Picking a row is the same call the character
// tray makes. On a narrow screen the list covers the chat and a row (or Back) slides between them.

const SHELL_TEXT = {   // l10n-ok
  title: '대화', search: '이름 검색', empty: '찾는 대화가 없습니다.', private: '사적 대화 중', room: '단체방',   // l10n-ok
  newRoom: '새 단체방', back: '목록으로', list: '대화방 목록', fresh: '아직 나눈 말이 없습니다.', you: '나',   // l10n-ok
};
const SHELL_NARROW = 940;   // px, the same number as shell.css: below it the chat keeps the whole width it has today
let shellState = { sessions: [], talks: null, filter: '', timer: 0, loading: false };

function shellOn() { return document.documentElement.classList.contains('shell2'); }
function shellNarrow() { return window.innerWidth <= SHELL_NARROW; }

// What a row shows of the last message: one line, without the marks the chat itself never shows (the expression
// tag, hidden comments such as the choices line, thought blocks) and without markdown's asterisks and backticks.
function shellPreview(text) {
  return String(text || '')
    .replace(/<!--[\s\S]*?(-->|$)/g, ' ')
    .replace(/```thought[\s\S]*?(```|$)/g, ' ')
    .replace(/\[expression:[^\]]*\]/gi, ' ')
    .replace(/[*`_#>]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// When the last message was, the way a talk list says it: the time today, "yesterday", else the date. `at` and `now`
// are epoch seconds; the words come from Intl, so they follow the browser's language.
function shellTime(at, now, locale) {
  if (!at) return '';
  const d = new Date(at * 1000), n = new Date((now || Date.now() / 1000) * 1000);
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(n) - day(d)) / 86400000);
  if (days <= 0) return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(d);
  if (days === 1) return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(-1, 'day');
  return new Intl.DateTimeFormat(locale, d.getFullYear() === n.getFullYear()
    ? { month: 'numeric', day: 'numeric' } : { year: 'numeric', month: 'numeric', day: 'numeric' }).format(d);
}

// The rows, newest talk first. A character's row shows its newest WORK talk: `talks` is the server's
// {character id: {at, preview}} (session_registry talks()); a server without it falls back to the newest work
// session among `sessions` (/api/sessions, 40 at most). Private talk is never previewed -- the list is what someone
// beside you sees (private-security.md T1) -- and a row says "private" only when it is the room open right now:
// the mode belongs to the open talk, not to the character. `open` is {character, room, mode}.
function shellRows(characters, sessions, rooms, open, talks) {
  open = open || {};
  const def = (characters.find(c => c.default) || {}).id || '';
  const rows = characters.map((c, i) => {
    const s = talks ? null : (sessions || []).find(x => (x.character || def) === c.id && (x.mode || 'work') === 'work' && x.turns !== 0);
    const t = talks ? talks[c.id] : (s && { at: s.updated_at, preview: s.preview });
    const current = !open.room && open.character === c.id;
    const priv = current && open.mode === 'private';
    return { kind: 'character', id: c.id, name: c.name || c.title || c.id, at: t ? t.at : 0, order: i,
      private: priv, preview: priv || !t ? '' : shellPreview(t.preview), current };
  });
  (rooms || []).forEach((r, i) => rows.push({ kind: 'room', id: r.id, name: r.name, at: (r.last && r.last.at) || r.created || 0,
    order: characters.length + i, private: false, preview: r.last ? shellPreview(r.last.text) : '', who: r.last ? r.last.who : '',
    members: r.members || [], current: open.room === r.id }));
  return rows.sort((a, b) => (b.at - a.at) || (a.order - b.order));
}

function shellFilter(rows, q) {
  q = String(q || '').trim().toLowerCase();
  return q ? rows.filter(r => r.name.toLowerCase().includes(q)) : rows;
}

function shellEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function shellOpenNow() {
  return { character: typeof openCharacterId === 'function' ? openCharacterId() : '',
    room: typeof roomOpenId === 'function' ? roomOpenId() : '', mode: typeof sessionMode !== 'undefined' ? sessionMode : 'work' };
}

function shellListDraw() {
  const box = document.getElementById('shellRooms');
  if (!box || !shellOn()) return;
  const chars = typeof characterCatalog !== 'undefined' ? characterCatalog : [];
  const rooms = typeof roomState !== 'undefined' ? roomState.rooms : [];
  const rows = shellFilter(shellRows(chars, shellState.sessions, rooms, shellOpenNow(), shellState.talks), shellState.filter);
  const add = document.getElementById('shellNewRoom');
  if (add) add.hidden = !(typeof openRooms === 'function' && chars.length > 1);   // a room needs two members
  box.textContent = '';
  if (!rows.length) { box.appendChild(shellEl('div', 'shell-empty', SHELL_TEXT.empty)); return; }
  rows.forEach(r => {
    const b = shellEl('button', 'shell-row' + (r.current ? ' current' : '') + (r.kind === 'room' ? ' is-room' : ''));
    b.type = 'button';
    b.setAttribute('role', 'listitem');
    b.setAttribute('data-kind', r.kind);
    b.setAttribute('data-id', r.id);
    if (r.current) b.setAttribute('aria-current', 'true');
    const img = document.createElement('img');
    img.className = 'shell-row-avatar';
    img.alt = '';
    img.onerror = () => { img.onerror = null; img.src = initialAvatar(r.name); };
    const c = r.kind === 'character' ? chars.find(x => x.id === r.id) : null;
    img.src = c ? characterOwnPortrait(c) : initialAvatar(r.name);   // its own provider's look (OWN_LOOK_v1)
    let line = r.preview || SHELL_TEXT.fresh, cls = 'shell-row-preview';
    if (r.private) { line = SHELL_TEXT.private; cls += ' is-private'; }
    else if (r.kind === 'room') {
      const names = roomCatalogNames(r.members);
      line = r.preview ? (r.who === 'user' ? SHELL_TEXT.you : (names[r.who] || '')) + ': ' + r.preview
        : SHELL_TEXT.room + ' · ' + roomMembersLabel(r.members, names);
    }
    b.append(img, shellEl('span', 'shell-row-name', r.name), shellEl('span', 'shell-row-time', r.kind === 'room' && !r.who ? '' : shellTime(r.at)),
      shellEl('span', cls, line));
    b.addEventListener('click', () => shellPick(r));
    box.appendChild(b);
  });
}

// The list again from the server. Quiet on failure: the rows already drawn stay.
async function shellListRefresh() {
  if (!shellOn() || shellState.loading) return;
  shellState.loading = true;
  try {
    const [s] = await Promise.all([api('/api/sessions'), typeof roomsReload === 'function' ? roomsReload() : null]);
    shellState.sessions = (s && s.sessions) || [];
    shellState.talks = (s && s.talks) || null;
    if (shellState.talks && typeof characterTalks !== 'undefined') characterTalks = shellState.talks;
  } catch (_) { /* keep what is drawn */ }
  shellState.loading = false;
  shellListDraw();
}
function shellListSoon(ms) {
  clearTimeout(shellState.timer);
  shellState.timer = setTimeout(shellListRefresh, ms || 300);
}

// A row is picked. The open character's row leads back from a room. Another character always opens in its WORK
// room, whatever room is open now (selectCharacter): the mode belongs to the open talk.
async function shellPick(r) {
  shellShowChat();
  if (r.kind === 'room') { if (roomOpenId() !== r.id) await roomEnter(r.id); return; }
  if (roomOpenId() && r.id === openCharacterId()) { await roomLeave(); return; }
  const c = characterCatalog.find(x => x.id === r.id);
  if (c) await selectCharacter(c);
}

// Narrow screens show one pane. The list is an overlay above the chat (the chat stays laid out, so its scroll
// position and the keyboard handling are untouched). Entering the chat adds a history step, so the system Back
// button returns to the list instead of leaving the page.
function shellShowList() {
  document.documentElement.classList.add('shell-list');
  shellListRefresh();
}
function shellShowChat() {
  const was = document.documentElement.classList.contains('shell-list');
  document.documentElement.classList.remove('shell-list');
  if (was && shellNarrow()) { try { history.pushState({ shell: 'chat' }, ''); } catch (_) {} }
}

// Called once by app.js after boot. Wraps the three places the open talk changes (a 1:1 session opens, a room
// opens or closes) and the end of a turn, so the list follows without those files knowing about it.
function shellInit() {
  if (!shellOn()) return;
  const list = document.getElementById('shellList'), back = document.getElementById('shellBack');
  const search = document.getElementById('shellSearch'), add = document.getElementById('shellNewRoom');
  if (!list) return;
  list.setAttribute('aria-label', SHELL_TEXT.list);
  document.getElementById('shellListTitle').textContent = SHELL_TEXT.title;
  if (search) {
    search.placeholder = SHELL_TEXT.search;
    search.setAttribute('aria-label', SHELL_TEXT.search);
    search.addEventListener('input', () => { shellState.filter = search.value; shellListDraw(); });
  }
  if (add) {
    add.textContent = '+ ' + SHELL_TEXT.newRoom;
    add.addEventListener('click', () => openRooms());
  }
  if (back) {
    back.hidden = false;
    back.title = SHELL_TEXT.back;
    back.setAttribute('aria-label', SHELL_TEXT.back);
    back.addEventListener('click', () => shellShowList());
  }
  window.addEventListener('popstate', () => { if (shellNarrow()) shellShowList(); });
  const openOne = enterSession;
  enterSession = function () { const out = openOne.apply(this, arguments); shellListSoon(); return out; };
  if (typeof roomEnter === 'function') {
    const enter = roomEnter, close = roomClose;
    roomEnter = async function () { const ok = await enter.apply(this, arguments); shellListSoon(); return ok; };
    roomClose = function () { close.apply(this, arguments); shellListSoon(); };
  }
  const brand = updateBrandAvatar;   // the open talk's provider changed: its row's picture follows (OWN_LOOK_v1)
  updateBrandAvatar = function () { brand.apply(this, arguments); shellListDraw(); };
  const busy = setBusy;
  setBusy = function (b) { const was = isBusy; busy.apply(this, arguments); if (was && !b) shellListSoon(1500); };
  // the heart (or /private) flips body.private-session: the open row's private mark follows at once
  if (typeof MutationObserver === 'function' && document.body) {
    let was = document.body.classList.contains('private-session');
    new MutationObserver(() => {
      const now = document.body.classList.contains('private-session');
      if (now !== was) { was = now; shellListDraw(); }
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
  setInterval(() => { if (!document.hidden) shellListRefresh(); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) shellListRefresh(); });
  shellListRefresh();
}
