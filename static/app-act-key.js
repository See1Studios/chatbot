// app-act-key.js -- ACT_KEY_v1: in private mode, Space on an empty composer starts an action ("/act "), since a
// leading space means nothing; Backspace on the bare "/act " takes it back (operator, 2026-09-28). Mobile IME
// keydown is Unidentified/229, so beforeinput insertText ' ' does the same (2026-09-30). The placeholder
// says so (app-turn.js refreshComposerPlaceholder). Declarations and document-level listeners only: it loads before
// app.js.

const ACT_PREFIX = '/act ';

function actKeyOn() {
  const b = document.body;
  if (!b) return false;
  if (b.classList.contains('private-session')) return true;
  // SHELL_v2 (ux/S4, UX12): under the messenger shell an action starts the same way in the work room -- "/act" is
  // a command there already. Not in a group room: its API takes plain text only.
  const root = document.documentElement;
  return Boolean(root && root.classList.contains('shell2') && !b.classList.contains('room-open'));
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

// Capture on #input: virtual keyboards never give e.key === ' '. After a desktop keydown already
// ran, value is no longer '' / ACT_PREFIX, so this does not fire twice.
document.addEventListener('beforeinput', (e) => {
  const el = e.target;
  if (!el || el.id !== 'input' || e.isComposing) return;
  if (e.inputType === 'insertText' && e.data === ' ' && el.value === '' && actKeyOn()) {
    e.preventDefault();
    actSet(el, ACT_PREFIX);
    return;
  }
  if (e.inputType === 'deleteContentBackward' && el.value === ACT_PREFIX) {
    e.preventDefault();
    actSet(el, '');
  }
}, true);

// The placeholder's Space hint follows the mode (/private toggles body.private-session).
if (typeof MutationObserver === 'function' && document.body) {
  let wasOn = actKeyOn();
  new MutationObserver(() => {
    const now = actKeyOn();
    if (now !== wasOn && typeof refreshComposerPlaceholder === 'function') { wasOn = now; refreshComposerPlaceholder(); }
  }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
}
