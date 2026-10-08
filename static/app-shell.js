// app-shell.js -- the messenger shell (docs/plans/ux-shell-roadmap.md 4.2.3, ux/S1-S4). Declarations only: app.js
// calls shellInit() once the page is up. It is the default; `?shell=1` brings the old page back for this browser,
// `?shell=2` returns (index.html sets html.shell2 before first paint), and the hub's compact frame keeps the old page.
// What it adds: a list of talks beside the chat -- one row per character, one per group room -- built from what the
// server already lists (/api/characters, /api/sessions, /api/rooms). Picking a row is the same call the character
// tray makes. On a narrow screen the list covers the chat and a row (or Back) slides between them.

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

// ux/S2 (UX11): the seven tabs go. What belongs to the open talk's character is reached from its profile card (the
// name or the picture in the header), what belongs to the whole app from the settings (the gear under the list).
// Layout (operator, 2026-09-30; the baseline is Telegram's web and mobile apps): on a wide screen the card is a
// full-height column on the right, like the list on the left, and opening it moves the talk aside; on a phone it
// is a screen of its own. A pane (the old tabs' content, opened with switchTab()) takes the middle in place of the
// talk -- list and detail: the card or the settings stay open beside it, and closing the pane brings the talk
// back. On a phone the same things are screens one after another, and Back returns to the one before. The talk's
// header and input bar belong to the talk only.
// Two switches, two questions (operator, 2026-10-01): "details" is how much of a talk's workings the chat shows
// (tokens, models, session marks); "developer mode" is whether the tools for working on the engine are offered
// at all -- the activity log and improvement (`dev` rows). Remembered in this browser, off by default.
const SHELL_DEV_KEY = 'pe.devMode';
function shellDevOn() { return Boolean(document.body && document.body.classList.contains('dev-mode')); }
function shellSetDev(on) {
  document.body.classList.toggle('dev-mode', Boolean(on));
  try { localStorage.setItem(SHELL_DEV_KEY, on ? '1' : '0'); } catch (_) { /* private window */ }
}
const SHELL_PANES = { artifacts: 'files', sessions: 'history', activity: 'log', status: 'accounts', team: 'characters', evolution: 'improve', appearance: 'appearance' };
const STATUS_SECTIONS = ['accounts', 'instructions', 'skills', 'mcp'];
const TEAM_SECTIONS = ['characters', 'roles', 'auto_react'];
function shellProfileRows(ctx) {
  // "pictures" is one place: the character's art screen shows them, takes uploads and asks for new ones (app-art.js)
  const rows = ctx.art ? [{ k: 'art', label: SHELL_TEXT.art }] : [];
  rows.push({ k: 'sessions', label: SHELL_TEXT.history }, { k: 'artifacts', label: SHELL_TEXT.files });
  if (ctx.manage) rows.push({ k: 'manage', label: SHELL_TEXT.manage });   // this character's part of the old team pane
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
  const rows = [
    { k: 'appearance', label: SHELL_TEXT.appearance },
    { k: 'accounts', label: SHELL_TEXT.accounts },
    { k: 'characters', label: SHELL_TEXT.characters },
    { k: 'roles', label: SHELL_TEXT.roles },
    { k: 'auto_react', label: SHELL_TEXT.auto_react },
    { k: 'instructions', label: SHELL_TEXT.instructions },
    { k: 'skills', label: SHELL_TEXT.skills },
    { k: 'mcp', label: SHELL_TEXT.mcp },
    { k: 'dev', label: SHELL_TEXT.dev, on: Boolean(ctx.dev) },
    { k: 'activity', label: SHELL_TEXT.log, dev: true },
    { k: 'evolution', label: SHELL_TEXT.improve, dev: true }
  ];
  if (ctx.revive) rows.push({ k: 'revive', label: SHELL_TEXT.revive });   // the dev install's host repair
  return rows;
}
const SHELL_ICONS = {
  appearance: '<circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>',
  accounts: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  characters: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  roles: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  auto_react: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  instructions: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>',
  skills: '<path d="M20.5 12.5a2.5 2.5 0 0 1-2.5 2.5h-1v1a2.5 2.5 0 0 1-5 0v-1H8a2.5 2.5 0 0 1-2.5-2.5v-4A2.5 2.5 0 0 1 8 6h4v1a2.5 2.5 0 0 0 5 0V6h1a2.5 2.5 0 0 1 2.5 2.5v4z"/>',
  mcp: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  dev: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  activity: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  evolution: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  revive: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  art: '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  sessions: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  artifacts: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  manage: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
};
function shellRowIcon(k) {
  const body = SHELL_ICONS[k];
  if (!body) return null;
  const svg = (document.createElementNS && document.createElementNS('http://www.w3.org/2000/svg', 'svg')) || document.createElement('svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'btn-icon-svg');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = body;
  return svg;
}
function shellRowButton(row) {
  const b = shellEl('button', 'shell-rowbtn' + (row.dev ? ' shell-dev' : '') + (row.on ? ' on' : ''));
  b.type = 'button';
  b.setAttribute('data-k', row.k);
  const left = shellEl('span', 'shell-rowbtn-left');
  left.style.display = 'inline-flex';
  left.style.alignItems = 'center';
  left.style.gap = '.6rem';
  const icon = shellRowIcon(row.k);
  if (icon) left.appendChild(icon);
  left.appendChild(shellEl('span', '', row.label));
  b.appendChild(left);
  if (row.k === 'dev') {
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
// The old team pane, in two (operator, 2026-10-01): what is one character's -- its card, roles and brains -- opens
// from that character's profile; what is shared -- role packs, the house memory, reactions, importing a card --
// stays in the settings. One pane, filtered: `only` is the character whose card alone is shown, or '' for the
// shared part. A block of the pane carries the character's id (app-team.js) or none.
function shellTeamShows(block, sec, only) {
  if (arguments.length === 2 && typeof block === 'string') {
    const onlyCid = sec;
    return onlyCid ? block === onlyCid : !block;
  }
  if (block && typeof block.getAttribute === 'function') {
    const cid = block.getAttribute('data-character-id') || '';
    if (only) return cid === only;
    const s = block.getAttribute('data-team-section') || '';
    return s === (sec || 'characters');
  }
  const cid = block || '';
  if (only) return cid === only;
  return sec ? (sec === 'characters' ? Boolean(cid) : false) : !cid;
}
function shellTeamFilter() {
  const pane = document.getElementById('teamPane'), list = document.getElementById('teamList');
  if (!pane || !list || !shellOn()) return;
  const only = shellState.teamOnly, sec = shellState.teamSection || 'characters';
  if (only) pane.setAttribute('data-shell-only', only); else pane.removeAttribute('data-shell-only');
  pane.setAttribute('data-shell-section', sec);
  Array.prototype.forEach.call(list.children, n => { n.hidden = !shellTeamShows(n, sec, only); });
  const charActions = document.getElementById('teamCharActions');
  if (charActions) charActions.hidden = Boolean(only || sec !== 'characters');
  const titleEl = document.getElementById('teamHeadTitle');
  if (titleEl) {
    titleEl.textContent = only ? (SHELL_TEXT.manage || '') : (SHELL_TEXT[sec] || SHELL_TEXT.team || '');
  }
  const hintEl = document.getElementById('teamHeadHint');
  if (hintEl) {
    if (only) hintEl.textContent = '';
    else if (sec === 'characters') hintEl.textContent = typeof tr === 'function' ? tr('team.hint') : '';
    else if (sec === 'roles') hintEl.textContent = typeof tr === 'function' ? tr('team.shared_hint') : '';
    else if (sec === 'auto_react') hintEl.textContent = (typeof AUTO_TEXT !== 'undefined' && AUTO_TEXT.hint) || (typeof tr === 'function' ? tr('team.auto.hint') : '');
  }
}
function shellGoTeam(cid, from) {
  shellState.teamOnly = cid || '';
  shellState.teamSection = '';
  shellTeamFilter();                 // what is drawn already, at once; loadTeam() redraws and the wrap filters again
  shellGoPane('team', from);
}
function shellGoTeamSection(sec, from) {
  shellState.teamOnly = '';
  shellState.teamSection = sec || 'characters';
  shellTeamFilter();
  shellGoPane('team', from);
}
function shellStatusShows(sec, only) { return only ? sec === only : true; }
function shellStatusFilter() {
  const p = document.getElementById('statusPane');
  if (!p || !shellOn()) return;
  const only = shellState.statusOnly || 'accounts', g = document.getElementById('statusConfigGroup');
  p.setAttribute('data-shell-only', only);
  if (g) g.hidden = true;
  Array.prototype.forEach.call(p.children, n => {
    if (n !== g) n.hidden = !shellStatusShows(n.getAttribute('data-status-section') || '', only);
  });
}
function shellGoStatus(sec, from) {
  shellState.statusOnly = sec || 'accounts';
  shellStatusFilter();
  shellGoPane('status', from);
}
function shellAppearanceDraw() {
  const p = document.getElementById('appearancePane');
  if (!p) return;
  const nowTheme = document.documentElement.getAttribute('data-theme') || '';
  const swatches = p.querySelectorAll('#appearanceThemeSwatches .theme-swatch');
  swatches.forEach(s => {
    const name = s.getAttribute('data-theme-choice');
    s.classList.toggle('active', name === nowTheme);
    if (typeof tr === 'function') {
      s.title = tr('theme.' + name);
      s.setAttribute('aria-label', s.title);
    }
    if (!s._bound) {
      s._bound = true;
      s.addEventListener('click', () => {
        if (typeof chooseTheme === 'function') chooseTheme(name);
        shellAppearanceDraw();
      });
    }
  });

  const isAdv = document.body.classList.contains('density-advanced');
  const densitySwitch = document.getElementById('appearanceDensitySwitch');
  const densityRow = document.getElementById('appearanceDensityRow');
  if (densitySwitch) {
    densitySwitch.classList.toggle('on', isAdv);
    densitySwitch.setAttribute('aria-checked', String(isAdv));
  }
  if (densityRow && !densityRow._bound) {
    densityRow._bound = true;
    densityRow.addEventListener('click', () => {
      if (typeof setDensity === 'function') setDensity(!document.body.classList.contains('density-advanced'));
      shellAppearanceDraw();
    });
  }

  const curSt = typeof getStreamStyle === 'function' ? getStreamStyle() : 'char';
  const streamBtn = document.getElementById('appearanceStreamBtn');
  const streamRow = document.getElementById('appearanceStreamRow');
  const streamHint = document.getElementById('appearanceStreamHint');
  const isLine = curSt === 'line';
  const label = isLine ? SHELL_TEXT.streamLine : SHELL_TEXT.streamChar;
  if (streamBtn) streamBtn.textContent = label || (isLine ? 'line' : 'char');
  if (streamHint) streamHint.textContent = label || '';
  if (streamRow && !streamRow._bound) {
    streamRow._bound = true;
    streamRow.addEventListener('click', () => {
      const next = (typeof getStreamStyle === 'function' ? getStreamStyle() : 'char') === 'line' ? 'char' : 'line';
      if (typeof setStreamStyle === 'function') setStreamStyle(next);
      shellAppearanceDraw();
    });
  }
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
  if (typeof roomOpenId === 'function' && roomOpenId()) {
    if (typeof roomProfileOpen === 'function') roomProfileOpen();
    return;
  }
  const c = typeof currentCharacter === 'function' ? currentCharacter() : null;
  if (!panel || !c) return;
  const rows = shellProfileRows({ art: typeof openArtManager === 'function', manage: typeof loadTeam === 'function' });
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
      else if (row.k === 'manage') shellGoTeam(c.id, 'profile');
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.profile, shellProfileClose, shellNarrow() ? '\u2039' : '\u2715'), card, list,
    shellBrainSection(c), shellModelSection(), shellContextSection());
  if (typeof shellQuotaSection === 'function') panel.insertBefore(shellQuotaSection(), list);
  if (typeof shellBrainUseSection === 'function') panel.appendChild(shellBrainUseSection(c));
  if (typeof shellDevDeleteButton === "function") shellDevDeleteButton(panel, c);
  shellMarkPane();
  column.classList.remove('behind');
  column.classList.add('open');
  document.body.classList.add('shell-profile-open');
}
// The row of the pane shown in the middle is marked in the card and in the settings.
function shellMarkPane() {
  let now = document.documentElement.dataset.tab || 'chat';
  if (now === 'team') now = shellState.teamOnly ? 'manage' : (shellState.teamSection || 'characters');
  else if (now === 'status') now = shellState.statusOnly || 'accounts';
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
function shellContextSection() {
  const title = typeof tr === 'function' ? tr('status.context.title') : 'Context';
  const box = shellSection(title);
  box.id = 'shellContextSection';
  const hint = shellEl('div', 'status-hint', typeof tr === 'function' ? tr('status.context.hint') : '');
  hint.style.margin = '0 0 .4rem';
  const list = shellEl('div', 'status-list');
  list.id = 'statusContext';
  box.append(hint, list);
  if (typeof loadContextNow === 'function') loadContextNow();
  return box;
}

function shellSettingsClose() { const p = document.getElementById('shellSettings'); if (p) p.classList.remove('open'); }
function shellSettingsOpen() {
  const panel = document.getElementById('shellSettings'), defib = document.getElementById('defibBtn');
  if (!panel) return;
  const rows = shellSettingsRows({ advanced: document.body.classList.contains('density-advanced'), dev: shellDevOn(),
    revive: Boolean(defib && defib.style.display !== 'none') });
  panel.textContent = '';
  const list = shellEl('div', 'shell-rows');
  rows.forEach(row => {
    const b = shellRowButton(row);
    b.addEventListener('click', () => {
      if (row.k === 'appearance') return shellGoPane('appearance', 'settings');
      if (TEAM_SECTIONS.includes(row.k)) return shellGoTeamSection(row.k, 'settings');
      if (STATUS_SECTIONS.includes(row.k)) return shellGoStatus(row.k, 'settings');
      if (SHELL_PANES[row.k]) return shellGoPane(row.k, 'settings');
      if (row.k === 'dev') {
        shellSetDev(!shellDevOn());
        // turned off while one of its panes is shown: back to the talk
        if (!shellDevOn() && (currentTab === 'activity' || currentTab === 'evolution')) { shellState.paneFrom = ''; switchTab('chat'); }
        shellSettingsOpen();
      }
      else if (row.k === 'revive') { shellSettingsClose(); defib.click(); }
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.settings, shellSettingsClose), list);
  shellMarkPane();
  panel.classList.add('open');
}

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

// Builds the card, the settings and the bar above a pane; the header's name and picture open the card.
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
  const menu = document.getElementById('shellMenu'), me = document.getElementById('shellUserBar');
  [menu, me].forEach(b => { if (b) { b.title = SHELL_TEXT.settings; b.addEventListener('click', () => shellSettingsOpen()); } });
  if (menu) menu.setAttribute('aria-label', SHELL_TEXT.menu);
  shellUserBarDraw();
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
    const appPane = document.getElementById('appearancePane');
    if (appPane) appPane.style.display = (now === 'appearance' ? 'flex' : 'none');
    if (now === 'appearance') shellAppearanceDraw();
    if (now === 'status') shellStatusFilter();
    if (now === 'team') shellTeamFilter();
    const title = now === 'art' ? SHELL_TEXT.art
      : now === 'appearance' ? SHELL_TEXT.appearance
      : now === 'team' && shellState.teamOnly ? SHELL_TEXT.manage
      : now === 'team' ? (SHELL_TEXT[shellState.teamSection || 'characters'] || SHELL_TEXT.characters)
      : now === 'status' ? (SHELL_TEXT[shellState.statusOnly || 'accounts'] || SHELL_TEXT.accounts)
      : SHELL_TEXT[SHELL_PANES[now]];
    shellSet(bar.querySelector('.shell-pane-title'), title || '');
    if (now !== 'art') shellArtGone();
    shellSet(back, shellNarrow() ? '\u2039' : '\u2715');      // a phone goes back, a wide screen closes the pane
    if (now !== 'chat' && shellNarrow() && shellProfileIsOpen()) shellProfileClose();   // not the one waiting behind
    shellMarkPane();
  };
  if (typeof loadTeam === 'function') {
    const team = loadTeam;
    loadTeam = async function () { const out = await team.apply(this, arguments); shellTeamFilter(); return out; };
  }
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
