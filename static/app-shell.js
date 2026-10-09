// app-shell.js -- the messenger shell's talk list (docs/plans/ux-shell-roadmap.md 4.2.3, ux/S1-S4).
// Declarations only: app.js calls shellInit() once the page is up. The profile card, the settings
// and the panes they open live in app-shell-panes.js (loaded next). It is the default; `?shell=1`
// brings the old page back for this browser, `?shell=2` returns (index.html sets html.shell2 before
// first paint), and the hub's compact frame keeps the old page.

const SHELL_TEXT = i18nTable('shelltext');   // I18N_v1: words by key from the catalog
const SHELL_NARROW = 940;   // px, the same number as shell.css: below it the chat keeps the whole width it has today
// ready: the first load is in (rows drawn before it would show a guess, then jump). nodes: the rows on screen.
let shellState = { sessions: [], talks: null, filter: '', timer: 0, loading: false, ready: false, nodes: new Map(),
  pending: '', want: null, switching: false, paneFrom: '', teamOnly: '', teamSection: '', statusOnly: '' };   // pending: the row just picked, shown as open before it is

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
  shellUserBarDraw();
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
    // a room shows the face of whoever spoke last (its first member before anyone has), on a stack of cards (CSS)
    const face = r.kind === 'room' ? (r.who && r.who !== 'user' ? r.who : (r.members || [])[0]) : r.id;
    const c = chars.find(x => x.id === face) || null;
    const src = c ? characterOwnPortrait(c) : initialAvatar(r.name);   // its own provider's look (OWN_LOOK_v1)
    if (src !== n.src) {
      const img = n.img, name = r.name;
      n.src = src;
      img.onerror = () => { img.onerror = null; img.src = initialAvatar(name); };
      img.src = src;
    }
    let line = r.preview || SHELL_TEXT.fresh;
    if (r.private) line = '';
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
    // the card stays open across a switch and becomes the new talk's
    if (shellProfileIsOpen()) { if (typeof roomOpenId === 'function' && roomOpenId()) { if (typeof roomProfileOpen === 'function') roomProfileOpen(); } else shellProfileOpen(); }
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
  if (typeof msgReplyClear === 'function') msgReplyClear();   // a reply belongs to the talk it quotes
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
// While the character answers, the place stands alone and typing dots follow it (shell.css #shellPresence.busy):
// waiting is typing, and needs no words (operator, 2026-10-01).
// PRESENCE_TRUTH_v1: not "near" when no answer can come: provider blocked, process dead, stream failed twice (one
// drop is the idle recycle).
function shellLink() {
  if (typeof isProviderUseBlocked === 'function' && isProviderUseBlocked(chatProvider())) return 'linkBlocked';
  const b = document.getElementById('procBadge');
  if (b && b.classList.contains('dead')) return 'linkDead';
  return b && b.classList.contains('disconnected') && window.__chatEsRetry >= 1 ? 'linkAway' : '';
}
function shellPresenceText(mode, busy, link) {
  const place = mode === 'private' ? movePlaceNow() : SHELL_TEXT.office;
  return link ? place + ' · ' + SHELL_TEXT[link] : busy ? place : place + ' · ' + SHELL_TEXT.near;
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
  const link = shellLink(), busy = !link && typeof isBusy !== 'undefined' && isBusy;
  shellSet(el, shellPresenceText(typeof sessionMode !== 'undefined' ? sessionMode : 'work', busy, link));
  el.classList.toggle('busy', busy);
  el.classList.toggle('off', Boolean(link));
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

// Developer mode for this browser. shellInit reads it on boot; shellSetDev (app-shell-panes.js) writes it.
const SHELL_DEV_KEY = 'pe.devMode';

// The list's foot is the user's own bar: the title they are called by (it can arrive after boot), opening the settings.
function shellUserBarDraw() {
  const bar = document.getElementById('shellUserBar');
  if (!bar) return;
  const name = (typeof IDENTITY !== 'undefined' && IDENTITY.user_title) || SHELL_TEXT.you;
  const pic = bar.querySelector('.shell-user-avatar');
  if (pic && pic.dataset.name !== name && typeof initialAvatar === 'function') { pic.dataset.name = name; pic.src = initialAvatar(name); }
  shellSet(bar.querySelector('.shell-user-name'), name);
  const st = bar.querySelector('.shell-user-status'), away = shellLink() === 'linkAway';
  shellSet(st, away ? SHELL_TEXT.linkAway : SHELL_TEXT.online);
  if (st) st.classList.toggle('off', away);
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
  // the list is headed by the app's own name (index.html's application-name); a mark goes beside it once there is one
  const app = document.querySelector('meta[name="application-name"]');
  document.getElementById('shellListTitle').textContent = (app && app.getAttribute('content')) || SHELL_TEXT.title;
  if (search) {
    search.placeholder = SHELL_TEXT.search;
    search.setAttribute('aria-label', SHELL_TEXT.search);
    search.addEventListener('input', () => { shellState.filter = search.value; shellListDraw(); });
  }
  if (add) {
    add.title = SHELL_TEXT.newRoom;
    add.setAttribute('aria-label', SHELL_TEXT.newRoom);
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
  const busy = setBusy, badge = updateProcBadge, gates = syncProviderUseGates;   // PRESENCE_TRUTH_v1
  updateProcBadge = function () { badge.apply(this, arguments); shellPresence(); shellUserBarDraw(); };
  syncProviderUseGates = function () { gates.apply(this, arguments); shellPresence(); };
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
  if (typeof msgMenuInit === 'function') msgMenuInit();   // ux/S6: the message menu (app-msgmenu.js)
  let dev = '';
  try { dev = localStorage.getItem(SHELL_DEV_KEY) || ''; } catch (_) { /* private window */ }
  document.body.classList.toggle('dev-mode', dev === '1');
  if (typeof refreshComposerPlaceholder === 'function') refreshComposerPlaceholder();   // the Space hint (app-act-key.js)
}
