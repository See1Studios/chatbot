// app-item.js -- items in private mode, picked from a coverflow (docs/plans/composer-plus-menu.md plus/F, plus/G).
//
// The button inside the message box opens the item picker: the catalog as a coverflow (the item in the middle is the
// one in hand; neighbours tilt away), with this character's affection and how many gifts are left today. The middle
// item shows what can be done with it -- give it, use it, or both (operator, 2026-09-28: a whip is not given). The
// server judges it (items.py: the character's likes against the item's tags, never the model), a toast says how a
// gift landed, then the action is sent (sendAction); the server's note rides on it, so the character reacts to the
// verdict, and on screen the note is an item chip, not text.

const ITEM_TEXT = {
  title: '아이템', give: '건네기', use: '쓰기', close: '닫기', failed: '아이템 실패: ',   // l10n-ok
  left: (n) => '오늘 건넬 수 있는 횟수 ' + n, none: '오늘은 더 건넬 수 없어요',   // l10n-ok
  gave: (it) => it.icon + ' ' + it.name + '을(를) 건넨다', prev: '이전 아이템', next: '다음 아이템',   // l10n-ok
  toast: (r) => r.item.icon + ' ' + r.label + ' · 호감도 ' + (r.delta >= 0 ? '+' : '') + r.delta + ' · Lv.' + r.level + ' ' + r.title,   // l10n-ok
};
// "[Gift - host note" is how gifts were written before items (history keeps them).
const ITEM_NOTE = /\n*\[(?:Gift|Item) - host note: the user (?:gave you|uses) (\S+) ([^(]+?) \([^)]*\)[^\]]*\]\s*$/;

// {text, item: {icon, name}|null}: the message without the host note, and the item it names.
function splitItemNote(text) {
  const s = String(text || '');
  const m = ITEM_NOTE.exec(s);
  if (!m) return { text: s, item: null };
  return { text: s.slice(0, m.index).replace(/\s+$/, ''), item: { icon: m[1], name: m[2].trim() } };
}

function renderItemChip(bubble, item) {
  if (!bubble || !item || bubble.querySelector('.item-chip')) return;
  const chip = document.createElement('span');
  chip.className = 'item-chip';
  chip.textContent = item.icon + ' ' + item.name;
  bubble.appendChild(chip);
}

function itemToast(text) {
  let t = document.getElementById('itemToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'itemToast';
    t.className = 'item-toast';
    t.setAttribute('role', 'status');
    document.body.appendChild(t);
  }
  t.textContent = text;
  t.classList.remove('show');
  void t.offsetWidth;                                  // restart the entrance
  t.classList.add('show');
  clearTimeout(itemToast._timer);
  itemToast._timer = setTimeout(() => t.classList.remove('show'), 3200);
}

// Where the card d places from the middle sits: the middle one faces the reader, the others turn away and shrink.
function flowStyle(d, reduced) {
  const a = Math.abs(d);
  if (a > 3) return { hidden: true };
  const rot = reduced || d === 0 ? 0 : (d < 0 ? 45 : -45);
  const scale = d === 0 ? 1 : Math.max(0.6, 0.82 - (a - 1) * 0.1);
  return {
    hidden: false,
    transform: 'translateX(' + (d * 58) + '%) rotateY(' + rot + 'deg) scale(' + scale + ')',
    z: 100 - a,
    opacity: d === 0 ? 1 : Math.max(0.3, 0.75 - (a - 1) * 0.2),
  };
}

function closeItemPicker() {
  const p = document.getElementById('itemPicker');
  if (p) p.remove();
  document.removeEventListener('keydown', itemPickerKeys, true);
}

let itemFlow = null;   // {items, cur, affection}

function itemPickerKeys(e) {
  if (!itemFlow) return;
  if (e.key === 'ArrowLeft') { e.preventDefault(); moveItemFlow(-1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); moveItemFlow(1); }
  else if (e.key === 'Escape') { e.preventDefault(); closeItemPicker(); }
}

function moveItemFlow(step, to) {
  if (!itemFlow || !itemFlow.items.length) return;
  const n = itemFlow.items.length;
  itemFlow.cur = typeof to === 'number' ? to : Math.max(0, Math.min(n - 1, itemFlow.cur + step));
  drawItemFlow();
}

function drawItemFlow() {
  const wrap = document.getElementById('itemPicker');
  if (!wrap || !itemFlow) return;
  const reduced = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  wrap.querySelectorAll('.item-card').forEach((card) => {
    const st = flowStyle(Number(card.dataset.i) - itemFlow.cur, reduced);
    card.hidden = st.hidden;
    if (st.hidden) return;
    card.style.transform = st.transform;
    card.style.zIndex = String(st.z);
    card.style.opacity = String(st.opacity);
    card.classList.toggle('current', Number(card.dataset.i) === itemFlow.cur);
  });
  const it = itemFlow.items[itemFlow.cur];
  wrap.querySelector('.item-name').textContent = it ? it.icon + ' ' + it.name : '';
  wrap.querySelector('.item-use').textContent = it && it.actions.includes('use') ? it.use : '';
  const acts = wrap.querySelector('.item-actions-main');
  acts.textContent = '';
  (it ? it.actions : []).forEach((action) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'item-act' + (action === 'give' ? ' primary' : '');
    b.textContent = ITEM_TEXT[action];
    b.disabled = action === 'give' && !itemFlow.affection.left_today;
    b.addEventListener('click', () => actOnItem(it, action));
    acts.appendChild(b);
  });
  wrap.querySelector('.item-prev').disabled = itemFlow.cur <= 0;
  wrap.querySelector('.item-next').disabled = itemFlow.cur >= itemFlow.items.length - 1;
}

async function openItemPicker() {
  if (typeof sessionId === 'undefined' || !sessionId) return;
  closeItemPicker();
  let data;
  try {
    data = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/items');
  } catch (e) {
    if (typeof addActivity === 'function') addActivity(ITEM_TEXT.failed + (e.message || e), 'warn');
    return;
  }
  const a = data.affection || {};
  itemFlow = { items: data.items || [], cur: 0, affection: a };
  const wrap = document.createElement('div');
  wrap.id = 'itemPicker';
  wrap.className = 'item-picker';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-label', ITEM_TEXT.title);

  const head = document.createElement('div');
  head.className = 'item-head';
  const title = document.createElement('span');
  title.textContent = '💗 Lv.' + a.level + ' ' + a.title + ' · ' + (a.left_today ? ITEM_TEXT.left(a.left_today) : ITEM_TEXT.none);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'item-close';
  close.setAttribute('aria-label', ITEM_TEXT.close);
  close.textContent = '✕';
  close.addEventListener('click', closeItemPicker);
  head.appendChild(title);
  head.appendChild(close);
  wrap.appendChild(head);

  const flow = document.createElement('div');
  flow.className = 'item-flow';
  flow.tabIndex = 0;
  itemFlow.items.forEach((it, i) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'item-card';
    card.dataset.i = String(i);
    card.setAttribute('aria-label', it.name);
    const img = document.createElement('img');
    img.alt = '';
    img.src = (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/items/' + encodeURIComponent(it.id) + '/image';
    card.appendChild(img);
    if (!it.has_image) {                               // the placeholder is generic: the emoji says which item
      const glyph = document.createElement('span');
      glyph.className = 'item-glyph';
      glyph.textContent = it.icon;
      card.appendChild(glyph);
    }
    card.addEventListener('click', () => moveItemFlow(0, i));
    flow.appendChild(card);
  });
  // wheel and swipe move one item at a time
  let wheelAt = 0;
  flow.addEventListener('wheel', (e) => {
    e.preventDefault();
    const now = Date.now();
    if (now - wheelAt < 180) return;
    wheelAt = now;
    moveItemFlow((e.deltaY || e.deltaX) > 0 ? 1 : -1);
  }, { passive: false });
  let downX = null;
  flow.addEventListener('pointerdown', (e) => { downX = e.clientX; });
  flow.addEventListener('pointerup', (e) => {
    if (downX === null) return;
    const dx = e.clientX - downX;
    downX = null;
    if (Math.abs(dx) > 40) moveItemFlow(dx < 0 ? 1 : -1);
  });
  wrap.appendChild(flow);

  const info = document.createElement('div');
  info.className = 'item-info';
  const name = document.createElement('div');
  name.className = 'item-name';
  const use = document.createElement('div');
  use.className = 'item-use';
  info.appendChild(name);
  info.appendChild(use);
  wrap.appendChild(info);

  const actions = document.createElement('div');
  actions.className = 'item-actions';
  const prev = document.createElement('button');
  prev.type = 'button';
  prev.className = 'item-prev';
  prev.setAttribute('aria-label', ITEM_TEXT.prev);
  prev.textContent = '‹';
  prev.addEventListener('click', () => moveItemFlow(-1));
  const main = document.createElement('div');
  main.className = 'item-actions-main';
  const next = document.createElement('button');
  next.type = 'button';
  next.className = 'item-next';
  next.setAttribute('aria-label', ITEM_TEXT.next);
  next.textContent = '›';
  next.addEventListener('click', () => moveItemFlow(1));
  actions.appendChild(prev);
  actions.appendChild(main);
  actions.appendChild(next);
  wrap.appendChild(actions);

  const composer = document.querySelector('.composer');
  (composer && composer.parentNode ? composer.parentNode : document.body).insertBefore(wrap, composer || null);
  document.addEventListener('keydown', itemPickerKeys, true);
  drawItemFlow();
  flow.focus();
}

async function actOnItem(it, action) {
  closeItemPicker();
  let res;
  try {
    res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/item',
      { method: 'POST', body: JSON.stringify({ item: it.id, action }) });
  } catch (e) {
    if (typeof addActivity === 'function') addActivity(ITEM_TEXT.failed + (e.message || e), 'warn');
    return;
  }
  if (!res || !res.ok) return;
  if (action === 'give') itemToast(ITEM_TEXT.toast(res.result));
  if (typeof sendAction === 'function') sendAction(action === 'give' ? ITEM_TEXT.gave(it) : it.use);
  // send() draws the action bubble before its first await, so it is the log's last child now
  const log = document.getElementById('log');
  if (log && log.lastElementChild) renderItemChip(log.lastElementChild, it);
}
