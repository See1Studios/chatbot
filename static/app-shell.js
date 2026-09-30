// app-shell.js -- the messenger shell (docs/plans/ux-shell-roadmap.md 4.2.3, ux/S1-S4). Declarations only: app.js
// calls shellInit() once the page is up. It is the default; `?shell=1` brings the old page back for this browser,
// `?shell=2` returns (index.html sets html.shell2 before first paint), and the hub's compact frame keeps the old page.
// What it adds: a list of talks beside the chat -- one row per character, one per group room -- built from what the
// server already lists (/api/characters, /api/sessions, /api/rooms). Picking a row is the same call the character
// tray makes. On a narrow screen the list covers the chat and a row (or Back) slides between them.

const SHELL_TEXT = {   // l10n-ok
  title: '대화', search: '이름 검색', empty: '찾는 대화가 없습니다.', private: '사적 대화 중', room: '단체방',   // l10n-ok
  newRoom: '새 단체방', back: '목록으로', list: '대화방 목록', fresh: '아직 나눈 말이 없습니다.', you: '나',   // l10n-ok
  office: '사무실', privateRoom: '사적인 방', near: '곁에 있음', thinking: '생각에 잠김', brain: '두뇌',   // l10n-ok
  more: '더 보기', act: '행동',   // l10n-ok
  profile: '프로필', settings: '설정', back2: '뒤로', close: '닫기', details: '자세히 보기', theme: '테마',   // l10n-ok
  files: '주고받은 파일', history: '대화 기록', art: '그림', model: '모델', log: '활동 로그',   // l10n-ok
  accounts: '계정 · 상태', team: '캐릭터 관리', improve: '개선', revive: '호스트 소생',   // l10n-ok
};
const SHELL_NARROW = 940;   // px, the same number as shell.css: below it the chat keeps the whole width it has today
// ready: the first load is in (rows drawn before it would show a guess, then jump). nodes: the rows on screen.
let shellState = { sessions: [], talks: null, filter: '', timer: 0, loading: false, ready: false, nodes: new Map(),
  pending: '', want: null, switching: false, paneFrom: '' };   // pending: the row just picked, shown as open before it is

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
  if (!box || !shellOn() || !shellState.ready) return;
  const chars = typeof characterCatalog !== 'undefined' ? characterCatalog : [];
  const rooms = typeof roomState !== 'undefined' ? roomState.rooms : [];
  const rows = shellFilter(shellRows(chars, shellState.sessions, rooms, shellOpenNow(), shellState.talks), shellState.filter);
  if (shellState.pending) rows.forEach(r => { r.current = (r.kind + ':' + r.id) === shellState.pending; if (!r.current) r.private = false; });
  const add = document.getElementById('shellNewRoom');
  if (add) add.hidden = !(typeof openRooms === 'function' && chars.length > 1);   // a room needs two members
  // Rows are kept and updated in place (keyed by kind and id): a redraw that changes nothing touches nothing, and a
  // picture is loaded again only when its address changed -- redrawing everything made the pictures flicker.
  const nodes = shellState.nodes, seen = new Set();
  let empty = box.querySelector('.shell-empty');
  if (!rows.length) {
    nodes.forEach(n => n.b.remove());
    nodes.clear();
    if (!empty) box.appendChild(shellEl('div', 'shell-empty', SHELL_TEXT.empty));
    return;
  }
  if (empty) empty.remove();
  rows.forEach((r, i) => {
    const key = r.kind + ':' + r.id;
    seen.add(key);
    let n = nodes.get(key);
    if (!n) {
      n = { b: shellEl('button', 'shell-row'), img: document.createElement('img'), name: shellEl('span', 'shell-row-name'),
        time: shellEl('span', 'shell-row-time'), line: shellEl('span', 'shell-row-preview'), src: '', row: r };
      n.b.type = 'button';
      n.b.setAttribute('role', 'listitem');
      n.b.setAttribute('data-kind', r.kind);
      n.b.setAttribute('data-id', r.id);
      n.img.className = 'shell-row-avatar';
      n.img.alt = '';
      n.b.append(n.img, n.name, n.time, n.line);
      const node = n;
      n.b.addEventListener('click', () => shellPick(node.row));
      nodes.set(key, n);
    }
    n.row = r;
    const c = r.kind === 'character' ? chars.find(x => x.id === r.id) : null;
    const src = c ? characterOwnPortrait(c) : initialAvatar(r.name);   // its own provider's look (OWN_LOOK_v1)
    if (src !== n.src) {
      const img = n.img, name = r.name;
      n.src = src;
      img.onerror = () => { img.onerror = null; img.src = initialAvatar(name); };
      img.src = src;
    }
    let line = r.preview || SHELL_TEXT.fresh;
    if (r.private) line = SHELL_TEXT.private;
    else if (r.kind === 'room') {
      const names = roomCatalogNames(r.members);
      line = r.preview ? (r.who === 'user' ? SHELL_TEXT.you : (names[r.who] || '')) + ': ' + r.preview
        : SHELL_TEXT.room + ' · ' + roomMembersLabel(r.members, names);
    }
    shellSet(n.name, r.name);
    shellSet(n.time, r.kind === 'room' && !r.who ? '' : shellTime(r.at));
    shellSet(n.line, line);
    shellSetClass(n.line, 'shell-row-preview' + (r.private ? ' is-private' : ''));
    shellSetClass(n.b, 'shell-row' + (r.current ? ' current' : '') + (r.kind === 'room' ? ' is-room' : ''));
    if (r.current) n.b.setAttribute('aria-current', 'true'); else n.b.removeAttribute('aria-current');
    if (box.children[i] !== n.b) box.insertBefore(n.b, box.children[i] || null);
  });
  nodes.forEach((n, key) => { if (!seen.has(key)) { n.b.remove(); nodes.delete(key); } });
}
function shellSet(el, text) { if (el.textContent !== text) el.textContent = text; }
function shellSetClass(el, cls) { if (el.className !== cls) el.className = cls; }

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
  shellState.ready = true;
  shellListDraw();
}
function shellListSoon(ms) {
  clearTimeout(shellState.timer);
  shellState.timer = setTimeout(shellListRefresh, ms || 300);
}

// A row is picked. The pick shows at once -- the row is marked, the header takes the name and picture, the old talk
// fades out under a thin running line -- and the switch itself (the server call, the history, the pictures) runs
// behind it (operator, 2026-09-30: selecting must feel light; what is being processed is shown apart from it).
// Picks made while a switch runs are not queued one by one: when it ends, only the newest is opened.
async function shellPick(r) {
  shellShowChat();
  shellState.want = r;
  shellPending(r);
  if (shellState.switching) return;
  shellState.switching = true;
  try {
    while (shellState.want) {
      const next = shellState.want;
      shellState.want = null;
      try { await shellOpen(next); } catch (_) { /* the talk that was open stays */ }
    }
  } finally {
    shellState.switching = false;
    shellState.pending = '';
    document.documentElement.classList.remove('shell-switching');
    shellListDraw();
    // the card stays open across a switch and becomes the new talk's (a group room has none)
    if (shellProfileIsOpen()) { if (typeof roomOpenId === 'function' && roomOpenId()) shellProfileClose(); else shellProfileOpen(); }
  }
}
function shellPending(r) {
  shellState.pending = r.kind + ':' + r.id;
  const open = shellOpenNow();
  const same = r.kind === 'room' ? open.room === r.id : (!open.room && open.character === r.id);
  if (!same) document.documentElement.classList.add('shell-switching');
  const c = r.kind === 'character' && typeof characterCatalog !== 'undefined' ? characterCatalog.find(x => x.id === r.id) : null;
  const name = document.getElementById('brandName'), pic = document.getElementById('brandAvatar');
  if (c && !same && name) name.textContent = c.title || c.name || '';
  if (c && !same && pic) pic.src = characterOwnPortrait(c);
  shellListDraw();
}
// The switch itself. The open character's row leads back from a room. Another character always opens in its WORK
// room, whatever room is open now (selectCharacter): the mode belongs to the open talk.
async function shellOpen(r) {
  shellState.paneFrom = '';
  const col = document.getElementById('shellProfile');
  if (col && col.classList.contains('behind')) shellProfileClose();   // its pane is being left for another talk
  if (typeof currentTab !== 'undefined' && currentTab !== 'chat') switchTab('chat');   // a pane was open: back to the talk
  if (r.kind === 'room') { if (roomOpenId() !== r.id) await roomEnter(r.id); return; }
  if (roomOpenId() && r.id === openCharacterId()) { await roomLeave(); return; }
  const c = characterCatalog.find(x => x.id === r.id);
  if (c) await selectCharacter(c);
}

// The header's second line (ux/S3, UX15): where the talk is and what the character is doing, in place of the
// provider's name. The private room's own place name is not known to the page yet (private-mode.md W3).
function shellPresenceText(mode, busy) {
  return (mode === 'private' ? '\u2665 ' + SHELL_TEXT.privateRoom : SHELL_TEXT.office) + ' · ' + (busy ? SHELL_TEXT.thinking : SHELL_TEXT.near);
}
function shellPresence() {
  const role = document.getElementById('brandRole');
  if (!role || !shellOn()) return;
  let el = document.getElementById('shellPresence');
  if (!el) {
    el = shellEl('span', 'shell-presence');
    el.id = 'shellPresence';
    role.insertBefore(el, role.firstChild);
  }
  shellSet(el, shellPresenceText(typeof sessionMode !== 'undefined' ? sessionMode : 'work', typeof isBusy !== 'undefined' && isBusy));
}

// The composer in the simple density (ux/S4, UX12): plus, the box, send. What the row used to carry is reached
// through the plus menu -- the buttons themselves stay in the page (hidden by shell.css) and the menu presses them,
// so their own code, labels and states are the one source. `ctx` is what those buttons say right now.
function shellPlusList(ctx) {
  const out = [{ k: 'act', label: SHELL_TEXT.act }];
  if (ctx.attach) out.push({ k: 'attach', label: ctx.attach });            // a file in the work room, an item in the private one
  if (!ctx.private && ctx.geo) out.push({ k: 'geo', label: ctx.geo.label, on: Boolean(ctx.geo.on) });
  if (!ctx.private && ctx.slash) out.push({ k: 'slash', label: ctx.slash });   // private mode has neither (chat-features.css)
  return out;
}
function shellPlusClose() {
  const menu = document.getElementById('shellPlusMenu'), plus = document.getElementById('shellPlus');
  if (menu) menu.hidden = true;
  if (plus) plus.setAttribute('aria-expanded', 'false');
}
function shellPlusOpen() {
  const menu = document.getElementById('shellPlusMenu'), plus = document.getElementById('shellPlus');
  const composer = menu && menu.parentNode;
  if (!composer) return;
  const label = (el) => (el ? (el.getAttribute('aria-label') || el.title || '') : '');
  const btn = { attach: composer.querySelector('.inline-btn'), geo: document.getElementById('geoBtn'), slash: document.getElementById('slashBtn') };
  const items = shellPlusList({ private: document.body.classList.contains('private-session'), attach: label(btn.attach),
    geo: btn.geo ? { label: label(btn.geo), on: btn.geo.getAttribute('aria-pressed') === 'true' } : null, slash: label(btn.slash) });
  menu.textContent = '';
  items.forEach(it => {
    const b = shellEl('button', it.on ? 'shell-plus-on' : '', it.label + (it.on ? ' \u2713' : ''));
    b.type = 'button';
    b.setAttribute('role', 'menuitem');
    b.addEventListener('click', () => {
      shellPlusClose();
      if (it.k === 'act') { actSet(inputEl, ACT_PREFIX); inputEl.focus(); return; }
      // after this click has finished: the pressed button's own menu must not be closed by this click's bubbling.
      // The command button opens on pointerdown (slash.js), which click() does not fire: call what it calls.
      setTimeout(() => {
        if (it.k === 'slash' && typeof toggleSlashMenu === 'function') toggleSlashMenu();
        else btn[it.k].click();
      }, 0);
    });
    menu.appendChild(b);
  });
  menu.hidden = false;
  if (plus) plus.setAttribute('aria-expanded', 'true');
}
function shellComposerInit() {
  const composer = document.querySelector('.composer'), priv = document.getElementById('privateBtn');
  const brand = document.querySelector('header .brand');
  if (composer && !document.getElementById('shellPlus')) {
    const plus = shellEl('button', 'ghost', '+'), menu = shellEl('div', 'shell-plus-menu');
    plus.id = 'shellPlus';
    plus.type = 'button';
    plus.title = SHELL_TEXT.more;
    plus.setAttribute('aria-label', SHELL_TEXT.more);
    plus.setAttribute('aria-haspopup', 'menu');
    plus.setAttribute('aria-expanded', 'false');
    menu.id = 'shellPlusMenu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    plus.addEventListener('click', (e) => { e.stopPropagation(); if (menu.hidden) shellPlusOpen(); else shellPlusClose(); });
    document.addEventListener('click', shellPlusClose);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') shellPlusClose(); });
    composer.insertBefore(plus, composer.firstChild);
    composer.appendChild(menu);
  }
  // the private switch moves up beside the name: it is about this talk's room, not about the message being typed
  if (priv && brand && !document.getElementById('shellHeart')) {
    const heart = shellEl('button', 'ghost');
    heart.id = 'shellHeart';
    heart.type = 'button';
    const icon = priv.querySelector('svg');
    if (icon) heart.appendChild(icon.cloneNode(true));
    heart.addEventListener('click', () => { if (!priv.disabled) priv.click(); });
    brand.appendChild(heart);
  }
  shellHeartSync();
}
function shellHeartSync() {
  const heart = document.getElementById('shellHeart'), priv = document.getElementById('privateBtn');
  if (!heart || !priv) return;
  heart.setAttribute('aria-pressed', String(document.body.classList.contains('private-session')));
  heart.title = priv.title;
  heart.setAttribute('aria-label', priv.getAttribute('aria-label') || priv.title);
}

// ux/S2 (UX11): the seven tabs go. What belongs to the open talk's character is reached from its profile card (the
// name or the picture in the header), what belongs to the whole app from the settings (the gear under the list).
// Layout (operator, 2026-09-30; the baseline is Telegram's web and mobile apps): on a wide screen the card is a
// full-height column on the right, like the list on the left, and opening it moves the talk aside; on a phone it
// is a screen of its own. A pane (the old tabs' content, opened with switchTab()) takes the middle in place of the
// talk -- list and detail: the card or the settings stay open beside it, and closing the pane brings the talk
// back. On a phone the same things are screens one after another, and Back returns to the one before. The talk's
// header and input bar belong to the talk only. `adv` rows show in the advanced density only.
const SHELL_PANES = { artifacts: 'files', sessions: 'history', activity: 'log', status: 'accounts', team: 'team', evolution: 'improve' };
function shellProfileRows(ctx) {
  // "pictures" is one place: the character's art screen shows them, takes uploads and asks for new ones (app-art.js)
  const rows = ctx.art ? [{ k: 'art', label: SHELL_TEXT.art }] : [];
  rows.push({ k: 'sessions', label: SHELL_TEXT.history }, { k: 'artifacts', label: SHELL_TEXT.files });
  return rows;
}
// The brain and the model are managed in the card itself (operator, 2026-09-30), not by sending the user back to
// the talk's pickers. One option per provider -- the character as that brain draws it -- and per model of the
// provider picked now. A provider whose use is blocked stays pickable, as in the tray: picking it shows why.
function shellBrainOptions(catalog, current, blockedReason, label) {
  return (catalog || []).map(p => {
    const why = blockedReason ? blockedReason(p.id) : '';
    return { id: p.id, label: label ? label(p) : (p.name || p.id), current: p.id === current, blocked: Boolean(why), why: why || '' };
  });
}
function shellModelOptions(choices, current) {
  return (choices || []).map(m => ({ value: m.value, label: m.label || m.value, current: m.value === current }));
}
function shellSettingsRows(ctx) {
  const rows = [{ k: 'details', label: SHELL_TEXT.details, on: Boolean(ctx.advanced) }, { k: 'theme', label: SHELL_TEXT.theme },
    { k: 'status', label: SHELL_TEXT.accounts }, { k: 'team', label: SHELL_TEXT.team },
    { k: 'activity', label: SHELL_TEXT.log, adv: true }, { k: 'evolution', label: SHELL_TEXT.improve, adv: true }];
  if (ctx.revive) rows.push({ k: 'revive', label: SHELL_TEXT.revive });   // the dev install's host repair
  return rows;
}
function shellRowButton(row) {
  const b = shellEl('button', 'shell-rowbtn' + (row.adv ? ' shell-adv' : '') + (row.on ? ' on' : ''));
  b.type = 'button';
  b.setAttribute('data-k', row.k);
  b.appendChild(shellEl('span', '', row.label));
  if (row.k === 'details') {
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-checked', String(Boolean(row.on)));
    b.appendChild(shellEl('span', 'switch-ui'));
  } else if (row.detail) b.appendChild(shellEl('small', '', row.detail));
  return b;
}
function shellPanelHead(title, onClose, glyph) {
  const head = shellEl('div', 'shell-panel-head'), x = shellEl('button', 'ghost', glyph || '\u2039');
  x.type = 'button';
  x.title = SHELL_TEXT.close;
  x.setAttribute('aria-label', SHELL_TEXT.close);
  x.addEventListener('click', onClose);
  head.append(x, shellEl('strong', '', title));
  return head;
}
// A pane opens as a screen of the talk column. `from` is where its Back leads: the card it was opened from, or the
// settings (which stay open beside it on a wide screen; on a narrow one Back shows the list they cover).
function shellGoPane(tab, from) {
  shellState.paneFrom = from || '';
  // A phone shows one screen at a time (wide, the card stays beside the pane). Going forward from the card, the
  // card steps aside to the LEFT and waits there, so Back brings it in from the left -- the way the arrow points.
  if (shellNarrow()) {
    const col = document.getElementById('shellProfile');
    if (from === 'profile' && col && col.classList.contains('open')) col.classList.add('behind');
    else shellProfileClose();
  }
  shellShowChat();
  // the history is this character's own: the old tab's character strip is hidden under the shell (shell.css)
  if (tab === 'sessions' && typeof setSessionCharFilter === 'function') setSessionCharFilter(openCharacterId());
  switchTab(tab);
}
// The pictures are a pane like the others (operator: it was built differently and came up like a modal). 'art' is
// no old tab, so switchTab('art') leaves the middle empty; the art manager (app-art.js) draws into an #artManager
// it finds, so one is put in the stage first -- without the modal's classes -- and it fills that instead of making
// its own overlay. The pane's bar is its header. Leaving the pane removes it (the switchTab wrap below).
async function shellGoArt(cid) {
  shellGoPane('art', 'profile');
  const stage = document.querySelector('.stage');
  if (stage && !document.getElementById('artManager')) {
    const host = shellEl('div', 'art-mgr-overlay shell-art');
    host.id = 'artManager';
    stage.appendChild(host);
  }
  await openArtManager(cid);
}
function shellArtGone() {
  const m = document.getElementById('artManager');
  if (m && m.classList.contains('shell-art')) m.remove();
}
function shellPaneBack() {
  const from = shellState.paneFrom;
  shellState.paneFrom = '';
  switchTab('chat');
  if (!shellNarrow()) return;                  // wide: the card or the settings never left
  if (from === 'profile') shellProfileOpen();
  else if (from === 'settings') shellShowList();
}

// open = on screen; "behind" = stepped aside to the left while a pane it opened is shown (phone only)
function shellProfileIsOpen() {
  const p = document.getElementById('shellProfile');
  return Boolean(p && p.classList.contains('open') && !p.classList.contains('behind'));
}
function shellProfileClose() {
  const p = document.getElementById('shellProfile');
  if (p) p.classList.remove('open', 'behind');
  if (document.body) document.body.classList.remove('shell-profile-open');
}
function shellProfileOpen() {
  const column = document.getElementById('shellProfile'), panel = column && column.firstChild;   // the fixed-width inside
  const c = typeof currentCharacter === 'function' ? currentCharacter() : null;
  if (!panel || !c || (typeof roomOpenId === 'function' && roomOpenId())) return;   // a group room has no card yet
  const rows = shellProfileRows({ art: typeof openArtManager === 'function' });
  panel.textContent = '';
  const card = shellEl('div', 'shell-card'), img = document.createElement('img'), list = shellEl('div', 'shell-rows');
  img.alt = '';
  img.onerror = () => { img.onerror = null; img.src = initialAvatar(c.name || c.title); };
  img.src = characterOwnPortrait(c);
  card.append(img, shellEl('div', 'shell-card-name', c.title || c.name || ''),
    shellEl('div', 'shell-card-sub', shellPresenceText(sessionMode, isBusy)));
  rows.forEach(row => {
    const b = shellRowButton(row);
    b.addEventListener('click', () => {
      if (SHELL_PANES[row.k]) return shellGoPane(row.k, 'profile');
      if (row.k === 'art') shellGoArt(c.id);
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.profile, shellProfileClose, shellNarrow() ? '\u2039' : '\u2715'), card, list,
    shellBrainSection(c), shellModelSection());
  shellMarkPane();
  column.classList.remove('behind');
  column.classList.add('open');
  document.body.classList.add('shell-profile-open');
}
// The row of the pane shown in the middle is marked in the card and in the settings.
function shellMarkPane() {
  const now = document.documentElement.dataset.tab || 'chat';
  document.querySelectorAll('.shell-rowbtn[data-k]').forEach(b => b.classList.toggle('current', b.getAttribute('data-k') === now));
}
function shellSection(title) {
  const box = shellEl('div', 'shell-section');
  box.appendChild(shellEl('div', 'shell-section-title', title));
  return box;
}
function shellBrainSection(c) {
  const box = shellSection(SHELL_TEXT.brain), grid = shellEl('div', 'shell-brains');
  const now = providerEl ? providerEl.value : '';
  shellBrainOptions(providerCatalog, now, providerUseBlockedReason, providerCreditLabel).forEach(o => {
    const b = shellEl('button', 'shell-brain' + (o.current ? ' current' : '') + (o.blocked ? ' blocked' : ''));
    const pic = document.createElement('img');
    b.type = 'button';
    b.title = o.label + (o.why ? ' · ' + o.why : '');
    if (o.current) b.setAttribute('aria-current', 'true');
    pic.alt = '';
    pic.onerror = () => { pic.onerror = null; pic.src = initialAvatar(c.name || c.title); };
    pic.src = characterPortrait(c, { id: o.id });
    b.append(pic, shellEl('span', '', o.label));
    // picking a blocked one opens its status pane (selectProvider), which closes the card; otherwise the card redraws
    b.addEventListener('click', async () => { if (!o.current) { await selectProvider(o.id); if (currentTab === 'chat') shellProfileOpen(); } });
    grid.appendChild(b);
  });
  box.appendChild(grid);
  return box;
}
function shellModelSection() {
  const box = shellSection(SHELL_TEXT.model), list = shellEl('div', 'shell-models');
  const has = typeof modelEl !== 'undefined' && modelEl && typeof modelChoices === 'function';
  shellModelOptions(has ? modelChoices() : [], has ? modelEl.value : '').forEach(o => {
    const b = shellEl('button', 'shell-rowbtn shell-model' + (o.current ? ' current' : ''), o.label);
    b.type = 'button';
    if (o.current) b.setAttribute('aria-current', 'true');
    b.addEventListener('click', () => { if (!o.current) { pickModel(o.value); shellProfileOpen(); } });
    list.appendChild(b);
  });
  box.appendChild(list);
  box.hidden = !list.children.length;
  return box;
}

function shellSettingsClose() { const p = document.getElementById('shellSettings'); if (p) p.classList.remove('open'); }
function shellSettingsOpen() {
  const panel = document.getElementById('shellSettings'), defib = document.getElementById('defibBtn');
  if (!panel) return;
  const rows = shellSettingsRows({ advanced: document.body.classList.contains('density-advanced'),
    revive: Boolean(defib && defib.style.display !== 'none') });
  panel.textContent = '';
  const list = shellEl('div', 'shell-rows');
  rows.forEach(row => {
    if (row.k === 'theme') {
      const box = shellEl('div', 'shell-theme'), sw = shellEl('div', 'shell-swatches');
      const now = document.documentElement.getAttribute('data-theme');
      (typeof THEMES !== 'undefined' ? THEMES : []).forEach(name => {
        const s = shellEl('button', 'theme-swatch' + (name === now ? ' active' : ''));
        s.type = 'button';
        s.title = name;
        s.setAttribute('aria-label', name);
        s.setAttribute('data-theme-choice', name);
        s.addEventListener('click', () => applyTheme(name));
        sw.appendChild(s);
      });
      box.append(shellEl('span', '', row.label), sw);
      list.appendChild(box);
      return;
    }
    const b = shellRowButton(row);
    b.addEventListener('click', () => {
      if (SHELL_PANES[row.k]) return shellGoPane(row.k, 'settings');
      if (row.k === 'details') { setDensity(!document.body.classList.contains('density-advanced')); shellSettingsOpen(); }
      else if (row.k === 'revive') { shellSettingsClose(); defib.click(); }
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.settings, shellSettingsClose), list);
  shellMarkPane();
  panel.classList.add('open');
}

// Builds the card, the settings, the gear and the bar above a pane; the header's name and picture open the card.
function shellPanelsInit() {
  const list = document.getElementById('shellList'), foot = list && list.querySelector('.shell-list-foot');
  const stage = document.querySelector('.stage-shell'), wrap = document.getElementById('appWrap');   // wrap = the talk column
  if (!list || !foot || !stage || !wrap || document.getElementById('shellProfile')) return;
  const profile = shellEl('aside', 'shell-profile'), settings = shellEl('div', 'shell-settings');
  profile.id = 'shellProfile';
  profile.setAttribute('aria-label', SHELL_TEXT.profile);
  settings.id = 'shellSettings';
  profile.appendChild(shellEl('div', 'shell-profile-in'));
  document.body.appendChild(profile);          // the last column of the page (shell.css), beside the talk
  list.appendChild(settings);
  const gear = shellEl('button', 'shell-gear', '\u2699');
  gear.id = 'shellGear';
  gear.type = 'button';
  gear.title = SHELL_TEXT.settings;
  gear.setAttribute('aria-label', SHELL_TEXT.settings);
  gear.addEventListener('click', () => shellSettingsOpen());
  foot.appendChild(gear);
  const bar = shellEl('div', 'shell-pane-bar'), back = shellEl('button', 'ghost', '\u2039');
  bar.id = 'shellPaneBar';
  back.type = 'button';
  back.title = SHELL_TEXT.back2;
  back.setAttribute('aria-label', SHELL_TEXT.back2);
  back.addEventListener('click', () => shellPaneBack());
  bar.append(back, shellEl('strong', 'shell-pane-title'));
  wrap.insertBefore(bar, stage);
  const tab = switchTab;
  switchTab = function (t) {
    tab.apply(this, arguments);
    const now = document.documentElement.dataset.tab || t;
    shellSet(bar.querySelector('.shell-pane-title'), SHELL_TEXT[SHELL_PANES[now]] || (now === 'art' ? SHELL_TEXT.art : ''));
    if (now !== 'art') shellArtGone();
    shellSet(back, shellNarrow() ? '\u2039' : '\u2715');      // a phone goes back, a wide screen closes the pane
    if (now !== 'chat' && shellNarrow() && shellProfileIsOpen()) shellProfileClose();   // not the one waiting behind
    shellMarkPane();
  };
  // The art manager closes itself when it hands a request to the talk (its "ask" button): the pane goes with it.
  if (typeof closeArtManager === 'function') {
    const closeArt = closeArtManager;
    closeArtManager = function () {
      closeArt.apply(this, arguments);
      if (currentTab !== 'art') return;
      shellState.paneFrom = '';
      shellProfileClose();
      switchTab('chat');
    };
  }
  // The picture used to open the tray (app.js onTrayKey). Caught on the way down, before that listener: the wrap
  // also holds the provider tray, so only the picture itself is taken.
  const pic = document.getElementById('brandAvatar'), picWrap = document.getElementById('brandAvatarWrap');
  const title = document.querySelector('header .brand-title');
  const toggle = () => { if (shellProfileIsOpen()) shellProfileClose(); else shellProfileOpen(); };
  if (pic && picWrap) {
    picWrap.addEventListener('click', (e) => { if (e.target === pic) { e.stopPropagation(); toggle(); } }, true);
    picWrap.addEventListener('keydown', (e) => {
      if (e.target === pic && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.stopPropagation(); toggle(); }
    }, true);
  }
  if (title) title.addEventListener('click', (e) => { if (!e.target.closest('button')) toggle(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { shellProfileClose(); shellSettingsClose(); } });
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
  enterSession = function () { const out = openOne.apply(this, arguments); shellListSoon(); shellPresence(); return out; };
  if (typeof roomEnter === 'function') {
    const enter = roomEnter, close = roomClose;
    roomEnter = async function () { const ok = await enter.apply(this, arguments); shellListSoon(); return ok; };
    roomClose = function () { close.apply(this, arguments); shellListSoon(); };
  }
  const brand = updateBrandAvatar;   // the open talk's provider changed: its row's picture follows (OWN_LOOK_v1)
  updateBrandAvatar = function () { brand.apply(this, arguments); shellListDraw(); };
  const busy = setBusy;
  setBusy = function (b) { const was = isBusy; busy.apply(this, arguments); shellPresence(); if (was && !b) shellListSoon(1500); };
  // the heart (or /private) flips body.private-session: the open row's private mark follows at once
  if (typeof MutationObserver === 'function' && document.body) {
    let was = document.body.classList.contains('private-session');
    new MutationObserver(() => {
      const now = document.body.classList.contains('private-session');
      if (now !== was) { was = now; shellListDraw(); shellPresence(); shellHeartSync(); shellPlusClose(); }
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
  setInterval(() => { if (!document.hidden) shellListRefresh(); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) shellListRefresh(); });
  // The first load waits for boot to open its talk (the wrap above asks for it then): before that the provider
  // and the open character are not settled and the rows would be drawn twice. The timer is the fallback.
  shellListSoon(4000);
  shellPresence();
  shellComposerInit();
  shellPanelsInit();
  if (typeof refreshComposerPlaceholder === 'function') refreshComposerPlaceholder();   // the Space hint (app-act-key.js)
}
