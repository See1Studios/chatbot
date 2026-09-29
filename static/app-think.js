// app-think.js -- THINKING_VIEW_v1 (docs/plans/ux-shell-roadmap.md ux/L): the brain's own reasoning, shown the way
// LM Studio does -- a folding strip over the answer. Declarations only: it loads before app-sse.js, which calls it.
//
// Brains that stream their reasoning (grok `thought`, claude thinking_delta) send `thinking` events. The strip opens
// while they arrive, folds as soon as the answer starts, and stays folded on the finished message with how long it thought.
// Nothing is stored: a reload shows the answer alone. In private mode it starts folded -- the brain's reasoning is
// not the character speaking. A brain that thinks silently (agy) sends nothing here; the turn footer's clock
// (seconds so far) and the server's quiet notice (SILENT_NOTICE_v1) cover it.
const THINK_TEXT = { live: '생각 중', done: '생각', sec: '초' };   // l10n-ok

function thinkStrip(node, make) {
  let el = null;
  for (const c of node.children || []) if (c.classList && c.classList.contains('think')) el = c;
  if (el || !make) return el;
  el = document.createElement('details');
  el.className = 'think';
  el.open = typeof sessionMode === 'undefined' || sessionMode !== 'private';
  el.appendChild(document.createElement('summary'));
  const body = document.createElement('div');
  body.className = 'think-body';
  el.appendChild(body);
  el._t0 = Date.now();
  node.insertBefore(el, node.firstChild);
  return el;
}

function thinkLabel(el) {
  const secs = Math.max(0, Math.round((Date.now() - (el._t0 || Date.now())) / 1000));
  const sum = el.querySelector('summary');
  if (sum) sum.textContent = (el.dataset.live === '1' ? THINK_TEXT.live : THINK_TEXT.done) + ' · ' + secs + THINK_TEXT.sec;
}

// A chunk of reasoning for the live answer `node`.
function thinkAppend(node, text) {
  if (!node || !text) return;
  const el = thinkStrip(node, true);
  if (el.dataset.live !== '1') {
    el.dataset.live = '1';
    if (!el._tick) el._tick = setInterval(function () { thinkLabel(el); }, 1000);
  }
  const body = el.querySelector('.think-body');
  body.textContent += text;
  if (el.open) body.scrollTop = body.scrollHeight;
  thinkLabel(el);
}

// The answer started, or the turn ended: stop the clock and fold.
function thinkEnd(node) {
  const el = node && thinkStrip(node, false);
  if (!el || el.dataset.live !== '1') return;
  el.dataset.live = '0';
  if (el._tick) { clearInterval(el._tick); el._tick = null; }
  el.open = false;
  thinkLabel(el);
}
