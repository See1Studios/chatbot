// app-regen.js: another take on the companion's last answer, and the takes under it (REGENERATE_v1,
// docs/plans/regenerate-swipe.md). The engine decides everything -- which answer may be taken again, how the brain is
// asked, which take counts; the page asks, clears the old bubble when the take starts (the new one streams in its
// place) and draws < n/m > under the answer.
const REGEN_TEXT = i18nTable('regen');

function regenLastAnswer() {
  const all = typeof logEl !== 'undefined' && logEl ? logEl.querySelectorAll('.msg.assistant:not(.system)') : [];
  return all.length ? all[all.length - 1] : null;
}

// The message menu offers "another take" on the last answer only (D1); the engine refuses one it cannot undo (D3).
function regenOffered(el) {
  const msg = el && el.closest ? el.closest('.msg') : null;
  return Boolean(msg && msg === regenLastAnswer());
}

function regenReason(e) {
  try { const k = JSON.parse(String((e && e.message) || '')).error_key; if (k) return tr(k); } catch (_) {}
  return REGEN_TEXT.failed;
}

async function regenStart() {
  if (typeof sessionId === 'undefined' || !sessionId) return;
  try {
    await api('/api/sessions/' + encodeURIComponent(sessionId) + '/regenerate', { method: 'POST', body: '{}' });
  } catch (e) {
    if (typeof failNotice === 'function') failNotice(regenReason(e), '');
  }
}

async function regenPick(n) {
  try {
    const v = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/pick', { method: 'POST', body: JSON.stringify({ pick: n }) });
    regenEvent('alts', v);
  } catch (e) {
    if (typeof failNotice === 'function') failNotice(regenReason(e), '');
  }
}

// < n/m > under the answer that has more than one take.
function regenDraw(node, v) {
  if (!node || !v) return;
  const old = node.querySelector('.regen-nav');
  if (old) old.remove();
  const count = Number(v.alts ? v.alts.length : v.count) || 0, at = Number(v.pick) || 0;
  if (count < 2) return;
  const nav = document.createElement('div');
  nav.className = 'regen-nav';
  const btn = (label, aria, to) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ghost';
    b.textContent = label;
    b.setAttribute('aria-label', aria);
    b.disabled = to < 0 || to >= count;
    b.addEventListener('click', () => regenPick(to));
    return b;
  };
  const where = document.createElement('span');
  where.textContent = (at + 1) + '/' + count;
  nav.append(btn('‹', REGEN_TEXT.prev, at - 1), where, btn('›', REGEN_TEXT.next, at + 1));
  node.appendChild(nav);
}

// From the stream: a take started (its old bubble goes; the new one streams in its place), or the takes changed.
function regenEvent(type, data) {
  const ts = data && data.ts != null ? String(data.ts) : '';
  const node = ts && typeof logEl !== 'undefined' && logEl ? logEl.querySelector('.msg[data-ts="' + ts + '"]') : null;
  if (type === 'regen_start') { if (node) node.remove(); return; }
  if (!node) return;
  if (typeof setAssistantContent === 'function' && typeof textWithChoices === 'function') {
    setAssistantContent(node, textWithChoices({ text: data.text, choices: data.choices }), true);
  }
  regenDraw(node, data);
}
