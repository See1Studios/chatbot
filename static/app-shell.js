// app-shell.js -- the messenger shell, first slice (docs/plans/ux-shell-roadmap.md 4.2.3, ux/S1). Declarations only:
// app.js calls shellInit() once the page is up. Behind a switch: `?shell=2` turns it on for this browser, `?shell=1`
// off (index.html sets html.shell2 before first paint), so the page everyone else uses does not change.
// What it adds: a list of talks beside the chat -- one row per character, one per group room -- built from what the
// server already lists (/api/characters, /api/sessions, /api/rooms). Picking a row is the same call the character
// tray makes. On a narrow screen the list covers the chat and a row (or Back) slides between them.

const SHELL_TEXT = {   // l10n-ok
  title: '대화', search: '이름 검색', empty: '찾는 대화가 없습니다.', private: '사적 대화 중', room: '단체방',   // l10n-ok
  newRoom: '새 단체방', back: '목록으로', list: '대화방 목록', fresh: '아직 나눈 말이 없습니다.', you: '나',   // l10n-ok
  office: '사무실', privateRoom: '사적인 방', near: '곁에 있음', thinking: '생각에 잠김', brain: '두뇌 바꾸기',   // l10n-ok
  more: '더 보기', act: '행동',   // l10n-ok
  profile: '프로필', settings: '설정', toChat: '대화로', close: '닫기', details: '자세히 보기', theme: '테마',   // l10n-ok
  files: '그림 · 파일', history: '대화 기록', art: '그림 관리', model: '모델', log: '활동 로그',   // l10n-ok
  accounts: '계정 · 상태', team: '캐릭터 관리', improve: '개선', revive: '호스트 소생',   // l10n-ok
};
const SHELL_NARROW = 940;   // px, the same number as shell.css: below it the chat keeps the whole width it has today
// ready: the first load is in (rows drawn before it would show a guess, then jump). nodes: the rows on screen.
let shellState = { sessions: [], talks: null, filter: '', timer: 0, loading: false, ready: false, nodes: new Map(),
  pending: '', want: null, switching: false };   // pending: the row just picked, shown as open before it is

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
  shellProfileClose();
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

// ux/S2 (UX11): the seven tabs go. What belongs to the open talk is reached from its profile card (the name or the
// picture in the header), what belongs to the whole app from the settings (the gear under the list). The panes are
// the old ones, opened with switchTab() as the tabs did; a bar above a pane leads back to the talk. `adv` rows show
// in the advanced density only.
const SHELL_PANES = { artifacts: 'files', sessions: 'history', activity: 'log', status: 'accounts', team: 'team', evolution: 'improve' };
function shellProfileRows(ctx) {
  const rows = [{ k: 'artifacts', label: SHELL_TEXT.files }, { k: 'sessions', label: SHELL_TEXT.history }];
  if (ctx.art) rows.push({ k: 'art', label: SHELL_TEXT.art });
  rows.push({ k: 'brain', label: SHELL_TEXT.brain, detail: ctx.provider || '' });
  if (ctx.model) rows.push({ k: 'model', label: SHELL_TEXT.model, detail: ctx.model });
  rows.push({ k: 'activity', label: SHELL_TEXT.log, adv: true });
  return rows;
}
function shellSettingsRows(ctx) {
  const rows = [{ k: 'details', label: SHELL_TEXT.details, on: Boolean(ctx.advanced) }, { k: 'theme', label: SHELL_TEXT.theme },
    { k: 'status', label: SHELL_TEXT.accounts }, { k: 'team', label: SHELL_TEXT.team }, { k: 'evolution', label: SHELL_TEXT.improve, adv: true }];
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
function shellPanelHead(title, onClose) {
  const head = shellEl('div', 'shell-panel-head'), x = shellEl('button', 'ghost', '\u2039');
  x.type = 'button';
  x.title = SHELL_TEXT.close;
  x.setAttribute('aria-label', SHELL_TEXT.close);
  x.addEventListener('click', onClose);
  head.append(x, shellEl('strong', '', title));
  return head;
}
function shellGoPane(tab) {
  shellProfileClose();
  shellSettingsClose();
  shellShowChat();
  switchTab(tab);
}

function shellProfileClose() { const p = document.getElementById('shellProfile'); if (p) p.classList.remove('open'); }
function shellProfileOpen() {
  const panel = document.getElementById('shellProfile');
  const c = typeof currentCharacter === 'function' ? currentCharacter() : null;
  if (!panel || !c || (typeof roomOpenId === 'function' && roomOpenId())) return;   // a group room has no card yet
  const prov = providerCatalog.find(x => x.id === (providerEl ? providerEl.value : ''));
  const rows = shellProfileRows({ art: typeof openArtManager === 'function', provider: prov ? providerCreditLabel(prov) : '',
    model: typeof modelEl !== 'undefined' && modelEl && modelEl.value && typeof modelLabel === 'function' ? modelLabel(modelEl.value) : '' });
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
      if (SHELL_PANES[row.k]) return shellGoPane(row.k);
      shellProfileClose();
      if (row.k === 'art') openArtManager(openCharacterId());
      // the trays close on any click outside them: open after this click is over
      else if (row.k === 'brain') setTimeout(() => toggleProviderTray(true), 0);
      else if (row.k === 'model' && typeof showModelMenu === 'function') setTimeout(() => showModelMenu(false), 0);
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.profile, shellProfileClose), card, list);
  panel.classList.add('open');
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
      if (SHELL_PANES[row.k]) return shellGoPane(row.k);
      if (row.k === 'details') { setDensity(!document.body.classList.contains('density-advanced')); shellSettingsOpen(); }
      else if (row.k === 'revive') { shellSettingsClose(); defib.click(); }
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.settings, shellSettingsClose), list);
  panel.classList.add('open');
}

// Builds the card, the settings, the gear and the bar above a pane; the header's name and picture open the card.
function shellPanelsInit() {
  const list = document.getElementById('shellList'), foot = list && list.querySelector('.shell-list-foot');
  const stage = document.querySelector('.stage-shell'), wrap = document.getElementById('appWrap');
  if (!list || !foot || !stage || !wrap || document.getElementById('shellProfile')) return;
  const profile = shellEl('aside', 'shell-profile'), settings = shellEl('div', 'shell-settings');
  profile.id = 'shellProfile';
  profile.setAttribute('aria-label', SHELL_TEXT.profile);
  settings.id = 'shellSettings';
  stage.appendChild(profile);
  list.appendChild(settings);
  const gear = shellEl('button', 'shell-gear', '\u2699');
  gear.id = 'shellGear';
  gear.type = 'button';
  gear.title = SHELL_TEXT.settings;
  gear.setAttribute('aria-label', SHELL_TEXT.settings);
  gear.addEventListener('click', () => shellSettingsOpen());
  foot.appendChild(gear);
  const bar = shellEl('div', 'shell-pane-bar'), back = shellEl('button', 'ghost', '\u2039 ' + SHELL_TEXT.toChat);
  bar.id = 'shellPaneBar';
  back.type = 'button';
  back.addEventListener('click', () => switchTab('chat'));
  bar.append(back, shellEl('strong', 'shell-pane-title'));
  wrap.insertBefore(bar, stage);
  const tab = switchTab;
  switchTab = function (t) {
    tab.apply(this, arguments);
    const now = document.documentElement.dataset.tab || t;
    shellSet(bar.querySelector('.shell-pane-title'), SHELL_TEXT[SHELL_PANES[now]] || '');
    if (now !== 'chat') shellProfileClose();
  };
  // The picture used to open the tray (app.js onTrayKey). Caught on the way down, before that listener: the wrap
  // also holds the provider tray, so only the picture itself is taken.
  const pic = document.getElementById('brandAvatar'), picWrap = document.getElementById('brandAvatarWrap');
  const title = document.querySelector('header .brand-title');
  const toggle = () => { const p = document.getElementById('shellProfile'); if (p.classList.contains('open')) shellProfileClose(); else shellProfileOpen(); };
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
