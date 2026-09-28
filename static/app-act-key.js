// app-act-key.js -- ACT_KEY_v1: in private mode, Space on an empty composer starts an action ("/act "), since a
// leading space means nothing; Backspace on the bare "/act " takes it back (operator, 2026-09-28). The placeholder
// says so (app-turn.js refreshComposerPlaceholder). Declarations and document-level listeners only: it loads before
// app.js.

const ACT_PREFIX = '/act ';

function actKeyOn() {
  return Boolean(document.body && document.body.classList.contains('private-session'));
}

// True for "/act" with nothing after it: nothing to send yet.
function actBare(text) {
  return /^\/(?:act|action|me)$/.test(String(text || '').trim());
}

function actSet(el, text) {
  el.value = text;
  el.selectionStart = el.selectionEnd = text.length;
  if (typeof autoResizeInput === 'function') autoResizeInput();
  if (typeof updateSendButton === 'function') updateSendButton();
}

// What a key does to the box: 'start', 'undo', 'hold' (a bare action is not sent), or '' (the key is not ours).
function actKeyAction(e, value, on) {
  if (e.isComposing || e.keyCode === 229 || e.altKey || e.ctrlKey || e.metaKey) return '';
  if (on && e.key === ' ' && !e.shiftKey && value === '') return 'start';
  if (e.key === 'Backspace' && value === ACT_PREFIX) return 'undo';
  if (e.key === 'Enter' && !e.shiftKey && actBare(value)) return 'hold';
  return '';
}

document.addEventListener('keydown', (e) => {
  const el = e.target;
  if (!el || el.id !== 'input') return;
  const act = actKeyAction(e, el.value, actKeyOn());
  if (!act) return;
  e.preventDefault();
  if (act === 'hold') { e.stopPropagation(); return; }
  actSet(el, act === 'start' ? ACT_PREFIX : '');
}, true);

// The placeholder's Space hint follows the mode (/private toggles body.private-session).
if (typeof MutationObserver === 'function' && document.body) {
  let wasOn = actKeyOn();
  new MutationObserver(() => {
    const now = actKeyOn();
    if (now !== wasOn && typeof refreshComposerPlaceholder === 'function') { wasOn = now; refreshComposerPlaceholder(); }
  }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
}
