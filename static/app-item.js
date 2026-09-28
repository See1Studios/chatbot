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

// Where a card d places from the middle sits -- the old Mac Cover Flow (operator, 2026-09-28): the middle one faces
// the reader; past it a clear gap, then the others turned about 70 degrees and packed close like records on a
// shelf, full size but darker. d need not be whole: while a drag or a wheel is under way the flow sits between items,
// and the card crossing the gap turns as it comes.
const FLOW_GAP = 80;     // % of a card from the middle to the first card beside it
const FLOW_STACK = 24;   // % of a card between neighbours in a stack
const FLOW_TURN = 70;    // degrees a side card is turned
function flowStyle(d, reduced) {
  const a = Math.abs(d);
  if (a > 6.5) return { hidden: true };
  const r = (v, k) => (Math.round(v * k) / k) || 0;      // short numbers, and never "-0"
  const side = d < 0 ? -1 : 1;
  const into = Math.min(1, a);                          // 0 in the middle, 1 once in a stack
  const x = side * (a <= 1 ? a * FLOW_GAP : FLOW_GAP + (a - 1) * FLOW_STACK);
  const rot = reduced ? 0 : -side * into * FLOW_TURN;
  const scale = 1 - into * 0.12;
  const shade = 1 - into * 0.35 - Math.max(0, a - 1) * 0.06;
  return {
    hidden: false,
    transform: 'translateX(' + r(x, 100) + '%) rotateY(' + r(rot, 100) + 'deg) scale(' + r(scale, 1000) + ')',
    z: 100 - Math.round(a * 10),
    shade: r(Math.max(0.35, shade), 1000),
  };
}

// One frame of the wheel's glide: a quarter of the way to where the wheel points, and exactly there once close.
function wheelEase(pos, target) {
  const next = pos + (target - pos) * 0.25;
  return Math.abs(target - next) < 0.004 ? target : next;
}

// Where a released drag comes to rest: where it is plus a glide in proportion to the release speed (items per ms),
// on a whole item. A quick flick crosses several; a slow let-go stays on the nearest.
function flingTarget(pos, velocity, n) {
  return Math.max(0, Math.min(n - 1, Math.round(pos + velocity * 280)));
}

function closeItemPicker() {
  const p = document.getElementById('itemPicker');
  if (p) p.remove();
  document.removeEventListener('keydown', itemPickerKeys, true);
}

let itemFlow = null;   // {items, cur: the item in hand, pos: where the flow sits (between items while moving), affection}

function itemPickerKeys(e) {
  if (!itemFlow) return;
  if (e.key === 'ArrowLeft') { e.preventDefault(); moveItemFlow(-1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); moveItemFlow(1); }
  else if (e.key === 'Escape') { e.preventDefault(); closeItemPicker(); }
}

function moveItemFlow(step, to) {
  if (!itemFlow || !itemFlow.items.length) return;
  const n = itemFlow.items.length;
  const from = itemFlow.pos;
  itemFlow.cur = typeof to === 'number' ? to : Math.max(0, Math.min(n - 1, itemFlow.cur + step));
  itemFlow.pos = itemFlow.cur;
  // a longer glide takes a little longer, so a fling reads as momentum, not a jump
  const wrap = document.getElementById('itemPicker');
  if (wrap) wrap.style.setProperty('--flow-dur', Math.min(0.9, 0.3 + 0.07 * Math.abs(itemFlow.pos - from)) + 's');
  drawItemFlow();
}

function drawItemFlow() {
  const wrap = document.getElementById('itemPicker');
  if (!wrap || !itemFlow) return;
  const reduced = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  wrap.querySelectorAll('.item-card').forEach((card) => {
    const st = flowStyle(Number(card.dataset.i) - itemFlow.pos, reduced);
    card.hidden = st.hidden;
    if (st.hidden) return;
    card.style.transform = st.transform;
    card.style.zIndex = String(st.z);
    card.style.filter = 'brightness(' + st.shade + ')';
    card.classList.toggle('current', Number(card.dataset.i) === Math.round(itemFlow.pos));
  });
  const near = Math.max(0, Math.min(itemFlow.items.length - 1, Math.round(itemFlow.pos)));
  wrap.querySelectorAll('.item-card.current').forEach(c => { if (Number(c.dataset.i) !== near) c.classList.remove('current'); });
  const it = itemFlow.items[near];
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
  itemFlow = { items: data.items || [], cur: 0, pos: 0, affection: a };
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
    card.addEventListener('click', () => { if (Date.now() >= suppressClickUntil) moveItemFlow(0, i); });
    flow.appendChild(card);
  });
  // Drag and wheel move the flow continuously; letting go glides on with the release speed, then rests on an item.
  const STEP_PX = 80;                                  // this many pixels of drag is one item
  const n = itemFlow.items.length;
  const clampPos = (p) => Math.max(-0.4, Math.min(n - 1 + 0.4, p));
  let drag = null, suppressClickUntil = 0, wheelTimer = null;
  flow.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, pos: itemFlow.pos, moved: false, samples: [{ t: e.timeStamp, x: e.clientX }] };
    if (flow.setPointerCapture) { try { flow.setPointerCapture(e.pointerId); } catch (_) {} }
  });
  flow.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) > 6) { drag.moved = true; wrap.classList.add('dragging'); }
    if (!drag.moved) return;
    itemFlow.pos = clampPos(drag.pos - dx / STEP_PX);
    drag.samples.push({ t: e.timeStamp, x: e.clientX });
    drag.samples = drag.samples.filter(p => e.timeStamp - p.t < 100);
    drawItemFlow();
  });
  const release = (e) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    wrap.classList.remove('dragging');
    if (!d.moved) return;
    suppressClickUntil = Date.now() + 250;             // the click that ends a drag is not a pick
    const first = d.samples[0], last = d.samples[d.samples.length - 1];
    const v = last.t > first.t ? -(last.x - first.x) / (last.t - first.t) / STEP_PX : 0;
    moveItemFlow(0, flingTarget(itemFlow.pos, v, n));
  };
  flow.addEventListener('pointerup', release);
  flow.addEventListener('pointercancel', release);
  // The wheel sets where the flow is heading; every frame the flow eases part of the way there (wheelEase). A mouse
  // notch jumps a whole step at once, and drawn straight away it skipped every frame in between (operator,
  // 2026-09-28). When the wheel stops, the target becomes the nearest item and the flow eases onto it.
  let wheelTarget = null, wheelFrame = 0;
  const wheelStep = () => {
    wheelFrame = 0;
    if (!itemFlow || wheelTarget === null || !wrap.isConnected) return;
    itemFlow.pos = wheelEase(itemFlow.pos, wheelTarget);
    const resting = itemFlow.pos === wheelTarget && wheelTarget === Math.round(wheelTarget) && !wheelTimer;
    drawItemFlow();
    if (resting) {
      wheelTarget = null;
      wrap.classList.remove('dragging');
      itemFlow.cur = itemFlow.pos;
      return;
    }
    wheelFrame = requestAnimationFrame(wheelStep);
  };
  flow.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    const unit = e.deltaMode === 1 ? 40 : (e.deltaMode === 2 ? 400 : 1);   // lines, pages, pixels
    wheelTarget = clampPos((wheelTarget === null ? itemFlow.pos : wheelTarget) + delta * unit / 150);
    wrap.classList.add('dragging');                    // the frames animate it; CSS easing would lag behind
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => {                    // the wheel stopped: head for the nearest item
      wheelTimer = null;
      if (wheelTarget !== null) wheelTarget = Math.max(0, Math.min(n - 1, Math.round(wheelTarget)));
      if (!wheelFrame) wheelFrame = requestAnimationFrame(wheelStep);
    }, 140);
    if (!wheelFrame) wheelFrame = requestAnimationFrame(wheelStep);
  }, { passive: false });
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
