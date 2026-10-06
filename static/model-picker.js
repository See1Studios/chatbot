/* Model picker -- a short icon button + menu instead of a wide <select>, and a composer
   placeholder that always names the model in use.
   (operator: on mobile the model select took the width -- a short button with a tab-style icon, and the
   current model plainly in the placeholder.)
   <select id="model"> (app.js: modelEl) stays in the DOM, hidden, as the single source of truth:
   everything that sends or saves a model still reads modelEl.value, so this file only
   changes how it is chosen and shown. */
const modelBtnEl = document.getElementById('modelBtn');
const modelMenuEl = document.getElementById('modelMenu');

function modelLabel(value) {
  return String(value || '').trim() || tr('team.default_model');
}

// Pure: what the composer placeholder says -- only what to do; the model sits in the corner tag (MODEL_TAG_v1).
// Short on purpose (operator, 2026-09-28). A hint -- e.g. the model cannot see the attached image
// (app-attach.js composerHint) -- takes the place of the instruction, since it is what matters now.
function composerPlaceholder(opts) {
  const o = opts || {};
  // RETRY_LAST_v1: a failed message waits here; Enter on the empty box sends it again (app-retry.js)
  if (o.retry && typeof o.busySec !== 'number') return '↻ ' + tr('composer.retry', { text: retryShort(o.retry, o.compact ? 18 : 40) });
  if (o.hint) return o.hint;
  if (typeof o.busySec === 'number') return tr('composer.busy', { s: o.busySec });
  if (o.actKey) return tr('composer.placeholder_act');   // ACT_KEY_v1
  return tr('composer.placeholder_short');
}

function modelChoices() {
  if (typeof modelEl === 'undefined' || !modelEl) return [];
  return Array.prototype.map.call(modelEl.options, o => ({ value: o.value, label: o.textContent || modelLabel(o.value) }));
}

// MODEL_MENU_v2: a long list (OpenRouter/OmniRoute: hundreds, ids like vendor/model:free) gets a search box, the
// last models used on top and folding groups by vendor; a short list stays one flat list. Names are cut in the
// middle because the tail (-high, -thinking) is what tells variants apart; the full id is the item's title.
const MODEL_MENU_GROUP_MIN = 12;
const MODEL_NAME_MAX = 30;
const MODEL_RECENT_MAX = 5;
const MODEL_RECENT_KEY = 'chat.recentModels';

// openrouter/qwen/x -> openrouter; gemini-3.1-pro -> gemini (the part before the first '/' or '-')
function modelVendor(value) {
  const v = String(value || '');
  const i = v.search(/[/-]/);
  return i > 0 ? v.slice(0, i) : 'other';
}

// vendor/ and :free are shown elsewhere (group title, FREE badge): the name keeps only the model
function modelShort(value) {
  const v = String(value || '');
  const i = v.indexOf('/');
  return (i > 0 ? v.slice(i + 1) : v).replace(/:free\b/, '');
}

function shortenMiddle(text, max) {
  const t = String(text || '');
  if (t.length <= max) return t;
  const tail = Math.ceil((max - 1) / 3);
  return t.slice(0, max - 1 - tail) + '…' + t.slice(t.length - tail);
}

function groupModels(choices) {
  const groups = [];
  choices.forEach(c => {
    const v = modelVendor(c.value);
    let g = groups.find(x => x.vendor === v);
    if (!g) groups.push(g = { vendor: v, items: [] });
    g.items.push(c);
  });
  return groups;
}

// every whitespace-separated word of the query must appear in the id or the label
function modelMatches(c, query) {
  const hay = (c.value + ' ' + c.label).toLowerCase();
  return String(query || '').toLowerCase().split(/\s+/).filter(Boolean).every(w => hay.includes(w));
}

function modelRecent() {
  try {
    const r = JSON.parse(localStorage.getItem(MODEL_RECENT_KEY) || '[]');
    return Array.isArray(r) ? r : [];
  } catch (_) { return []; }
}

function rememberModel(value) {
  if (!value) return;
  try {
    localStorage.setItem(MODEL_RECENT_KEY, JSON.stringify([value].concat(modelRecent().filter(v => v !== value)).slice(0, MODEL_RECENT_MAX)));
  } catch (_) { /* storage blocked: the recent list is a convenience */ }
}

// nav(item, +1|-1): where an arrow key goes; null = the item's DOM siblings (the flat list)
function modelItem(c, current, onPick, nav, text) {
  const on = c.value === current;
  const isFree = c.value.includes(':free');
  const item = document.createElement('div');
  item.className = 'slash-item' + (on ? ' selected' : '');
  item.setAttribute('role', 'option');
  item.setAttribute('aria-selected', on ? 'true' : 'false');
  item.tabIndex = 0;
  item.title = c.value;
  if (isFree) {
    const badge = document.createElement('span');
    badge.className = 'slash-badge free';
    badge.textContent = 'FREE';
    item.appendChild(badge);
  }
  const name = document.createElement('span');
  name.className = 'slash-name';
  name.textContent = text;
  const mark = document.createElement('span');
  mark.className = 'slash-desc';
  mark.textContent = on ? '✓ ' + tr('status.profiles.active') : '';
  item.appendChild(name);
  item.appendChild(mark);
  item.addEventListener('click', () => onPick(c.value));
  item.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onPick(c.value);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const dir = e.key === 'ArrowDown' ? 1 : -1;
      if (nav) return nav(item, dir);
      const sib = dir > 0 ? item.nextSibling : item.previousSibling;
      if (sib && sib.focus) sib.focus();
    }
  });
  return item;
}

function renderModelMenu(menu, choices, current, onPick) {
  menu.innerHTML = '';
  if (choices.length <= MODEL_MENU_GROUP_MIN) {
    choices.forEach(c => menu.appendChild(modelItem(c, current, onPick, null, shortenMiddle(c.label, MODEL_NAME_MAX))));
    return;
  }
  const rows = [];   // focusable rows in DOM order: {el, sec, body, head}
  const shown = r => !r.sec.hidden && !(r.head ? false : (r.body.hidden || r.el.hidden));
  const nav = (el, dir) => {
    const vis = rows.filter(shown);
    const at = vis.findIndex(r => r.el === el);
    const to = vis[at + dir];
    if (to) to.el.focus();
    else if (dir < 0) search.focus();
  };
  const text = c => shortenMiddle(c.label === c.value ? modelShort(c.value) : c.label, MODEL_NAME_MAX);
  const search = document.createElement('input');
  search.type = 'text';
  search.className = 'model-search';
  search.placeholder = tr('model.search_placeholder');
  search.setAttribute('aria-label', tr('model.search'));
  search.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const first = rows.find(shown);
      if (first) first.el.focus();
    }
  });
  menu.appendChild(search);
  const secs = [];   // {sec, body, open, items:[{c, el}]}
  const addSec = (title, list, open, head) => {
    const sec = document.createElement('div');
    sec.className = 'model-sec';
    const body = document.createElement('div');
    const s = { sec, body, open, head: null, items: [] };
    const sync = () => {
      body.hidden = !(search.value.trim() ? true : s.open);
      if (s.head) {
        s.head.setAttribute('aria-expanded', s.open ? 'true' : 'false');
        s.head.firstChild.textContent = (s.open ? '▾ ' : '▸ ') + title;
      }
    };
    if (head) {
      const h = document.createElement('div');
      h.className = 'model-group-head';
      h.tabIndex = 0;
      h.setAttribute('role', 'button');
      const label = document.createElement('span');
      const count = document.createElement('span');
      count.className = 'model-group-count';
      count.textContent = String(list.length);
      h.appendChild(label);
      h.appendChild(count);
      const toggle = () => { s.open = !s.open; sync(); };
      h.addEventListener('click', toggle);
      h.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); nav(h, e.key === 'ArrowDown' ? 1 : -1); }
      });
      s.head = h;
      sec.appendChild(h);
      rows.push({ el: h, sec, body, head: true });
    } else {
      const t = document.createElement('div');
      t.className = 'slash-category';
      t.textContent = title;
      sec.appendChild(t);
    }
    list.forEach(c => {
      const el = modelItem(c, current, onPick, nav, text(c));
      body.appendChild(el);
      s.items.push({ c, el });
      rows.push({ el, sec, body, head: false });
    });
    sec.appendChild(body);
    menu.appendChild(sec);
    s.sync = sync;
    sync();
    secs.push(s);
    return s;
  };
  const byValue = new Map(choices.map(c => [c.value, c]));
  const recent = modelRecent().map(v => byValue.get(v)).filter(Boolean);
  const recentSec = recent.length ? addSec(tr('model.recent'), recent, true, false) : null;
  groupModels(choices).forEach(g => addSec(g.vendor, g.items, g.items.some(c => c.value === current), true));
  const empty = document.createElement('div');
  empty.className = 'slash-empty';
  empty.textContent = tr('model.none');
  empty.hidden = true;
  menu.appendChild(empty);
  search.addEventListener('input', () => {
    const q = search.value.trim();
    let any = false;
    secs.forEach(s => {
      let hit = 0;
      s.items.forEach(x => { x.el.hidden = q ? !modelMatches(x.c, q) : false; if (!x.el.hidden) hit++; });
      s.sec.hidden = Boolean(q) && (s === recentSec || !hit);   // a query searches the groups, not the shortcut list
      if (!s.sec.hidden) any = true;
      s.sync();
    });
    empty.hidden = any;
  });
}

function isModelMenuOpen() {
  return !!modelMenuEl && !modelMenuEl.hidden;
}

function hideModelMenu() {
  if (!modelMenuEl) return;
  modelMenuEl.hidden = true;
  // undo the inline placement slash.js's positionSlashMenu() applied
  ['position', 'left', 'width', 'right', 'bottom', 'top', 'maxHeight', 'zIndex'].forEach(k => { modelMenuEl.style[k] = ''; });
  if (modelBtnEl) {
    modelBtnEl.classList.remove('active');
    modelBtnEl.setAttribute('aria-expanded', 'false');
  }
}

function showModelMenu(viaKeyboard) {
  if (!modelMenuEl || typeof modelEl === 'undefined' || !modelEl) return;
  if (typeof hideSlashMenu === 'function') hideSlashMenu();   // one popup at a time
  renderModelMenu(modelMenuEl, modelChoices(), modelEl.value, pickModel);
  modelMenuEl.hidden = false;
  if (typeof positionSlashMenu === 'function') positionSlashMenu(modelMenuEl);
  if (modelBtnEl) {
    modelBtnEl.classList.add('active');
    modelBtnEl.setAttribute('aria-expanded', 'true');
  }
  if (viaKeyboard) {   // the menu is not next to the button in tab order: move focus into it
    const cur = modelMenuEl.querySelector('.selected') || modelMenuEl.querySelector('.slash-item');
    if (cur && cur.focus) cur.focus();
  }
}

function toggleModelMenu(viaKeyboard) {
  if (isModelMenuOpen()) hideModelMenu();
  else showModelMenu(Boolean(viaKeyboard));
}

function pickModel(value) {
  rememberModel(value);
  if (typeof modelEl !== 'undefined' && modelEl && modelEl.value !== value) {
    modelEl.value = value;
    modelEl.dispatchEvent(new Event('change'));   // app.js's onchange persists the choice
  }
  hideModelMenu();
  syncModelUi();
}

// Button title/aria-label + placeholder follow the model in use. Called whenever the model list is
// rebuilt (provider switch) or the value changes.
function syncModelUi() {
  const hasModel = typeof modelEl !== 'undefined' && modelEl;
  const label = modelLabel(hasModel ? modelEl.value : '');
  if (modelBtnEl) {
    const t = tr('model.pick_current', { label });
    modelBtnEl.title = t;
    modelBtnEl.setAttribute('aria-label', t);
  }
  // before boot has filled the list there is nothing to name yet -- keep the static placeholder
  if (hasModel && modelEl.options && modelEl.options.length && typeof refreshComposerPlaceholder === 'function') {
    refreshComposerPlaceholder();
  }
}

function setupModelPicker() {
  if (!modelBtnEl || !modelMenuEl) return;
  // pointerdown + preventDefault like the "/" button: opening the menu must not steal focus from
  // the input (and pop the on-screen keyboard down/up)
  modelBtnEl.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    e.stopPropagation();
    toggleModelMenu(false);
  });
  // Enter/Space on the focused button arrive as a click with detail 0 (no pointer involved)
  modelBtnEl.addEventListener('click', (e) => {
    if (e.detail === 0) toggleModelMenu(true);
  });
  document.addEventListener('pointerdown', (e) => {
    if (isModelMenuOpen() && !modelMenuEl.contains(e.target) && !modelBtnEl.contains(e.target)) hideModelMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isModelMenuOpen()) {
      hideModelMenu();
      modelBtnEl.focus();
    }
  });
  if (typeof inputEl !== 'undefined' && inputEl) inputEl.addEventListener('input', hideModelMenu);
  window.addEventListener('resize', () => {
    if (isModelMenuOpen() && typeof positionSlashMenu === 'function') positionSlashMenu(modelMenuEl);
  });
  // crossing the phone breakpoint changes which placeholder text applies
  if (window.matchMedia) {
    const mq = window.matchMedia('(max-width: 600px)');
    const onMq = () => syncModelUi();
    if (mq.addEventListener) mq.addEventListener('change', onMq);
    else if (mq.addListener) mq.addListener(onMq);
  }
  syncModelUi();
}

// MODEL_TAG_v2: the model button (#modelBtn) sits in the composer's right corner, left of the inline button
// (operator, 2026-09-28/29). The empty box shows the model's name when it takes at most a third of the box, else the
// icon; typing, a short screen and an open phone keyboard leave the icon (chat-composer.css). The input keeps clear
// of it (--model-tag-w). Placed from the input's box, since the phone composer reorders its children.
const MODEL_TAG_ROOM = 0.35;
function placeModelTag(btn, input, model) {
  if (!btn || !input) return;
  const name = btn.querySelector ? btn.querySelector('.model-name') : null;
  if (name) name.textContent = modelLabel(model);
  const box = input.offsetParent;
  if (box) {
    const inset = input.classList.contains('has-inline-btn') ? 44 : 10;
    const h = input.offsetHeight;
    btn.style.right = Math.max(0, box.clientWidth - input.offsetLeft - input.offsetWidth + inset) + 'px';
    btn.style.top = (input.offsetTop + h - Math.min(h / 2, 21)) + 'px';   // on the last line, like the send button
  }
  if (input.value) return;                       // typing: CSS shows the icon; the empty-box width stays as it was
  btn.classList.remove('icon-only');
  if (btn.offsetWidth > input.offsetWidth * MODEL_TAG_ROOM) btn.classList.add('icon-only');
  input.style.setProperty('--model-tag-w', (btn.offsetWidth ? btn.offsetWidth + 6 : 0) + 'px');
}

function refreshModelTag() {
  if (modelBtnEl && typeof inputEl !== 'undefined') placeModelTag(modelBtnEl, inputEl, typeof modelEl !== 'undefined' && modelEl ? modelEl.value : '');
}

function setupModelTag() {
  if (!modelBtnEl || typeof inputEl === 'undefined' || !inputEl) return;
  window.addEventListener('resize', refreshModelTag);
  if (typeof ResizeObserver === 'function') new ResizeObserver(refreshModelTag).observe(inputEl);
  refreshModelTag();
}

setupModelPicker();
setupModelTag();
