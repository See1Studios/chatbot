// app-recall.js -- RECALL_SENT_v1: Up and Down in the composer walk back through messages sent before, like a shell
// (operator, 2026-09-28). Declarations and document-level listeners only: it loads before app.js.
//
// Up starts only from an empty box, so editing a multi-line draft keeps its arrow keys. While a recalled message is
// shown unchanged, Up/Down keep walking; Down past the newest returns to the empty box. Any edit ends the walk.
// The open slash menu keeps its own arrow keys. History is per browser (localStorage), newest last.

const RECALL_KEY = 'pe.sentHistory';
const RECALL_MAX = 100;
let recallIdx = null;    // index into the history while walking, else null

function recallLoad() {
  try {
    const v = JSON.parse(localStorage.getItem(RECALL_KEY) || '[]');
    return Array.isArray(v) ? v.filter(x => typeof x === 'string') : [];
  } catch (_) {
    return [];
  }
}

function recallSave(items) {
  try { localStorage.setItem(RECALL_KEY, JSON.stringify(items.slice(-RECALL_MAX))); } catch (_) {}
}

function recallRemember(text) {
  const t = String(text || '').trim();
  recallIdx = null;
  if (!t) return;
  const items = recallLoad();
  if (items[items.length - 1] === t) return;
  items.push(t);
  recallSave(items);
}

// One step of the walk: the text to show, or null to leave the key to the textarea. dir is -1 (Up) or +1 (Down).
function recallStep(items, dir, value) {
  if (recallIdx !== null && value !== items[recallIdx]) recallIdx = null;   // edited: the walk is over
  if (dir < 0) {
    if (recallIdx === null) {
      if (value !== '' || !items.length) return null;
      recallIdx = items.length - 1;
    } else if (recallIdx > 0) {
      recallIdx -= 1;
    }
    return items[recallIdx];
  }
  if (recallIdx === null) return null;
  recallIdx += 1;
  if (recallIdx >= items.length) {
    recallIdx = null;
    return '';
  }
  return items[recallIdx];
}

function recallSlashOpen() {
  return typeof slashMenuEl !== 'undefined' && slashMenuEl && !slashMenuEl.hidden;
}

function recallShow(el, text) {
  el.value = text;
  el.selectionStart = el.selectionEnd = text.length;
  if (typeof clearRetry === 'function' && text) clearRetry();
  if (typeof autoResizeInput === 'function') autoResizeInput();
  if (typeof updateSendButton === 'function') updateSendButton();
}

// Capture phase, after app-retry.js has put a waiting message into an empty box, before app.js sends it.
document.addEventListener('click', (e) => {
  const btn = e.target && e.target.closest ? e.target.closest('#send') : null;
  if (btn && !btn.disabled) recallRemember((document.getElementById('input') || {}).value);
}, true);
document.addEventListener('keydown', (e) => {
  const el = e.target;
  if (!el || el.id !== 'input' || e.isComposing || e.keyCode === 229) return;
  if (e.altKey || e.ctrlKey || e.metaKey || recallSlashOpen()) return;
  if (e.key === 'Enter' && !e.shiftKey) {
    recallRemember(el.value);
  } else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.shiftKey) {
    const text = recallStep(recallLoad(), e.key === 'ArrowUp' ? -1 : 1, el.value);
    if (text === null) return;
    e.preventDefault();
    recallShow(el, text);
  }
}, true);
