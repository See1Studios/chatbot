// app-msgmenu.js -- the message menu (docs/plans/ux-shell-roadmap.md ux/S6, UX13). Declarations only; app-shell.js
// calls msgMenuInit() under the messenger shell. Right-click a bubble, or keep a finger on it, and a menu opens by
// it (a sheet from the bottom on a phone): a row of short acts for a character's lines, copy, send again. A text
// selection inside the bubble keeps the browser's own menu, so a part of a message can still be copied.
// A message whose turn failed is marked on its bubble with a way to send it again (RETRY_LAST_v1, app-retry.js).
// Deleting a message is not here yet: what it would erase (the record, the brain's memory) is its own decision.

const MSG_TEXT = {   // l10n-ok
  copy: '복사', copied: '복사했어요', resend: '다시 보내기', failed: '보내지 못했어요', menu: '메시지',   // l10n-ok
  // an act is sent as an action (/act): the row is what one does in reply, and it differs by room   // l10n-ok
  acts: { work: ['웃는다', '끄덕인다', '엄지를 든다', '어깨를 토닥인다'], private: ['웃는다', '머리를 쓰다듬는다', '손을 잡는다', '빤히 본다'] },   // l10n-ok
};
const MSG_PRESS_MS = 450;

// What a bubble is: 'mine' (the user's line), 'act' (the user's action line), 'theirs' (a character's bubble or
// narration), or '' (not a message this menu serves: a system notice, anything else).
function msgKind(el) {
  if (!el || !el.classList) return '';
  if (el.classList.contains('md-say') || el.classList.contains('md-narr')) return 'theirs';
  if (el.classList.contains('msg') && el.classList.contains('user')) return 'mine';
  if (el.classList.contains('msg') && el.classList.contains('action')) return 'act';
  return '';
}

// The menu's rows. ctx: { kind, busy, room (a group room is open), mode ('work' | 'private') }.
function msgMenuItems(ctx) {
  const rows = [];
  if (ctx.kind === 'theirs' && !ctx.busy && !ctx.room) rows.push({ k: 'acts', acts: MSG_TEXT.acts[ctx.mode === 'private' ? 'private' : 'work'] });
  rows.push({ k: 'copy', label: MSG_TEXT.copy });
  // an action goes again as an action; a group room takes plain text only
  if ((ctx.kind === 'mine' || (ctx.kind === 'act' && !ctx.room)) && !ctx.busy) rows.push({ k: 'resend', label: MSG_TEXT.resend });
  return rows;
}

// The words of a bubble as the user reads them: not the files under a line, the marks beside it, a footer.
function msgText(el) {
  const copy = el.cloneNode(true);
  copy.querySelectorAll('.attach-cards,.personal-mark,.msg-footer,.md-face,.md-typing,.thought-box,.thought-toggle,.msg-failnote,.stream-caret')
    .forEach(n => n.remove());
  let t = String(copy.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
  if (msgKind(el) === 'act') t = t.replace(/^✦\s*/, '');
  return t;
}

// What goes to the composer to send a bubble again.
function msgResendText(kind, text) { return kind === 'act' ? '/act ' + text : text; }

// Which of the user's bubbles (their texts, oldest first) the waiting retry is: the newest one that matches, or -1.
// The offer keeps an action as "/act x"; its bubble reads "x".
function msgFailedIndex(lines, hint) {
  const h = String(hint || '').trim();
  if (!h) return -1;
  const bare = h.replace(/^\/(?:act|action|me)\s+/, '');
  for (let i = lines.length - 1; i >= 0; i--) if (lines[i] === h || lines[i] === bare) return i;
  return -1;
}

function msgToast(text) {
  let t = document.getElementById('shellToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'shellToast';
    t.className = 'shell-toast';
    t.setAttribute('role', 'status');
    document.body.appendChild(t);
  }
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 1400);
}

function msgMenuClose() {
  const m = document.getElementById('shellMsgMenu');
  if (m) m.hidden = true;
  const s = document.getElementById('shellMsgScrim');
  if (s) s.hidden = true;
  document.querySelectorAll('.msg-pressed').forEach(n => n.classList.remove('msg-pressed'));
}

function msgMenuOpen(el, x, y) {
  const kind = msgKind(el);
  if (!kind) return;
  let menu = document.getElementById('shellMsgMenu'), scrim = document.getElementById('shellMsgScrim');
  if (!menu) {
    scrim = document.createElement('div');
    scrim.id = 'shellMsgScrim';
    scrim.className = 'shell-msg-scrim';
    scrim.addEventListener('click', msgMenuClose);
    menu = document.createElement('div');
    menu.id = 'shellMsgMenu';
    menu.className = 'shell-msg-menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', MSG_TEXT.menu);
    document.body.append(scrim, menu);
  }
  const room = typeof roomOpenId === 'function' && Boolean(roomOpenId());
  const items = msgMenuItems({ kind, busy: typeof isBusy !== 'undefined' && isBusy, room,
    mode: typeof sessionMode !== 'undefined' ? sessionMode : 'work' });
  const text = msgText(el);
  menu.textContent = '';
  items.forEach(it => {
    if (it.k === 'acts') {
      const row = document.createElement('div');
      row.className = 'shell-msg-acts';
      it.acts.forEach(a => {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = a;
        b.addEventListener('click', () => { msgMenuClose(); if (typeof sendAction === 'function') sendAction(a); });
        row.appendChild(b);
      });
      menu.appendChild(row);
      return;
    }
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'shell-msg-item';
    b.setAttribute('role', 'menuitem');
    b.textContent = it.label;
    b.addEventListener('click', async () => {
      msgMenuClose();
      if (it.k === 'copy') { if (await copyText(text)) msgToast(MSG_TEXT.copied); return; }
      if (it.k === 'resend' && inputEl) {
        inputEl.value = msgResendText(kind, text);
        if (typeof autoResizeInput === 'function') autoResizeInput();
        if (typeof updateSendButton === 'function') updateSendButton();
        if (typeof send === 'function') send();
      }
    });
    menu.appendChild(b);
  });
  el.classList.add('msg-pressed');
  // a phone: a sheet from the bottom over a dimmed page; a pointer: a menu by the pointer, kept on screen
  const sheet = window.innerWidth <= 640;
  menu.classList.toggle('sheet', sheet);
  scrim.classList.toggle('dim', sheet);
  scrim.hidden = false;
  menu.hidden = false;
  if (sheet) { menu.style.left = ''; menu.style.top = ''; return; }
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
  menu.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + 'px';
  const first = menu.querySelector('button');
  if (first) first.focus({ preventScroll: true });
}

// The user's bubble that failed carries a note under it with a way to send it again. Recomputed whenever the
// retry offer may have changed; the offer itself stays app-retry.js's.
function msgMarkFailed() {
  const log = typeof logEl !== 'undefined' ? logEl : document.getElementById('log');
  if (!log) return;
  log.querySelectorAll('.msg-failnote').forEach(n => n.remove());
  log.querySelectorAll('.msg.failed').forEach(n => n.classList.remove('failed'));
  const hint = typeof retryHint === 'function' ? retryHint() : '';
  if (!hint) return;
  const mine = Array.prototype.slice.call(log.querySelectorAll('.msg.user, .msg.action'));
  const i = msgFailedIndex(mine.map(msgText), hint);
  if (i < 0) return;
  const bubble = mine[i];
  bubble.classList.add('failed');
  const note = document.createElement('div');
  note.className = 'msg-failnote';
  note.appendChild(document.createTextNode(MSG_TEXT.failed + ' · '));
  const again = document.createElement('button');
  again.type = 'button';
  again.textContent = MSG_TEXT.resend;
  // the empty send takes the offer (app-retry.js), exactly as Enter on the empty box does
  again.addEventListener('click', () => { const b = document.getElementById('send'); if (b && !b.disabled) b.click(); });
  note.appendChild(again);
  bubble.parentNode.insertBefore(note, bubble.nextSibling);
}

function msgMenuInit() {
  const log = document.getElementById('log');
  if (!log) return;
  const target = (e) => {
    const el = e.target && e.target.closest ? e.target.closest('.md-say, .md-narr, .msg.user, .msg.action') : null;
    return el && log.contains(el) && !(el.closest('.msg') || el).classList.contains('system') ? el : null;
  };
  log.addEventListener('contextmenu', (e) => {
    const el = target(e);
    if (!el) return;
    const sel = window.getSelection && window.getSelection();
    if (sel && !sel.isCollapsed && el.contains(sel.anchorNode)) return;   // a selection: the browser's own menu copies it
    e.preventDefault();
    msgMenuOpen(el, e.clientX, e.clientY);
  });
  let press = null;
  log.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse') return;
    const el = target(e);
    if (!el) return;
    const x = e.clientX, y = e.clientY;
    press = { x, y, timer: setTimeout(() => { press = null; msgMenuOpen(el, x, y); }, MSG_PRESS_MS) };
  });
  const cancel = () => { if (press) { clearTimeout(press.timer); press = null; } };
  log.addEventListener('pointermove', (e) => { if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > 8) cancel(); });
  ['pointerup', 'pointercancel', 'scroll'].forEach(ev => log.addEventListener(ev, cancel, { passive: true }));
  log.addEventListener('scroll', msgMenuClose, { passive: true });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') msgMenuClose(); });
  // the failed mark follows the retry offer
  if (typeof offerRetry === 'function') {
    const offer = offerRetry;
    offerRetry = function () { offer.apply(this, arguments); msgMarkFailed(); };
  }
  if (typeof clearRetry === 'function') {
    const clear = clearRetry;
    clearRetry = function () { clear.apply(this, arguments); msgMarkFailed(); };
  }
  // a send takes the offer inside app-retry.js without clearRetry(): look again once it has gone out
  document.addEventListener('click', (e) => { if (e.target && e.target.closest && e.target.closest('#send')) setTimeout(msgMarkFailed, 0); });
  document.addEventListener('keydown', (e) => { if (e.target && e.target.id === 'input' && e.key === 'Enter') setTimeout(msgMarkFailed, 0); });
}
