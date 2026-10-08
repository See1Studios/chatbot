// app-msgmenu.js -- the message menu (docs/plans/ux-shell-roadmap.md ux/S6, UX13). Declarations only; app-shell.js
// calls msgMenuInit() under the messenger shell. Right-click a bubble, or keep a finger on it, and a menu opens by
// it (a sheet from the bottom on a phone): a row of short acts for a character's lines, copy, send again. A text
// selection inside the bubble keeps the browser's own menu, so a part of a message can still be copied.
// A message whose turn failed is marked on its bubble with a way to send it again (RETRY_LAST_v1, app-retry.js).
// Deleting a message is not here yet: what it would erase (the record, the brain's memory) is its own decision.
//
// Reply (ux/S7): "reply" on any bubble puts a bar over the composer; the message then goes with a quote line in
// front of its text -- `> NAME: SNIPPET`, a blank line, the message -- which every brain reads as what it is,
// needs nothing from the server, and is kept in the record as it was sent. The user's bubble draws that line as
// a quote above the message (msgQuoteDraw), and pressing it scrolls to the line it quotes.

const MSG_TEXT = i18nTable('msgmenu');   // I18N_v1: words by key from the catalog
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
  if (ctx.kind === 'theirs' && !ctx.busy && !ctx.room) rows.push({ k: 'acts', acts: [0, 1, 2, 3].map(i => tr('msgmenu.act.' + (ctx.mode === 'private' ? 'private' : 'work') + '.' + i)) });   // what one does in reply, by room
  if (ctx.kind === 'theirs' && ctx.last && !ctx.busy && !ctx.room) rows.push({ k: 'regen', label: tr('regen.again') });   // REGENERATE_v1
  rows.push({ k: 'reply', label: MSG_TEXT.reply });
  rows.push({ k: 'copy', label: MSG_TEXT.copy });
  // an action goes again as an action; a group room takes plain text only
  if ((ctx.kind === 'mine' || (ctx.kind === 'act' && !ctx.room)) && !ctx.busy) rows.push({ k: 'resend', label: MSG_TEXT.resend });
  return rows;
}

// The words of a bubble as the user reads them: not the files under a line, the marks beside it, a footer.
function msgText(el) {
  const copy = el.cloneNode(true);
  copy.querySelectorAll('.attach-cards,.personal-mark,.msg-footer,.md-face,.md-typing,.thought-box,.thought-toggle,.msg-failnote,.stream-caret,.msg-quote')
    .forEach(n => n.remove());
  let t = String(copy.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
  if (msgKind(el) === 'act') t = t.replace(/^✦\s*/, '');
  return t;
}

// ---- reply
const MSG_SNIPPET_MAX = 80;
let msgReply = null;   // { name, snippet } while the reply bar is up

// One line of a bubble, short enough to quote.
function msgSnippet(text) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  return t.length > MSG_SNIPPET_MAX ? t.slice(0, MSG_SNIPPET_MAX - 1) + '\u2026' : t;
}
// The quote line a reply is sent with, and back: { name, snippet, rest } or null.
function msgQuoteLine(name, snippet) { return '> ' + (name ? name + ': ' : '') + snippet + '\n\n'; }
function msgQuoteParse(text) {
  const m = /^> ([^\n]{1,240})\n\n([\s\S]*)$/.exec(String(text || ''));
  if (!m) return null;
  const cut = m[1].indexOf(': ');
  return cut > 0 && cut <= 40
    ? { name: m[1].slice(0, cut), snippet: m[1].slice(cut + 2), rest: m[2] }
    : { name: '', snippet: m[1], rest: m[2] };
}
// Who said a bubble, by the name the chat shows.
function msgSpeaker(el, kind) {
  if (kind !== 'theirs') return (typeof IDENTITY !== 'undefined' && IDENTITY.user_title) || MSG_TEXT.me;
  const msg = el.closest ? el.closest('.msg') : null;
  const who = msg && msg.querySelector('.room-who');
  if (who && who.textContent.trim()) return who.textContent.trim();
  return typeof sessionCharacterName === 'function' ? sessionCharacterName() : '';
}

function msgReplyClear() {
  msgReply = null;
  const bar = document.getElementById('shellReply');
  if (bar) bar.hidden = true;
}
function msgReplyStart(el, kind, text) {
  msgReply = { name: msgSpeaker(el, kind), snippet: msgSnippet(text) };
  let bar = document.getElementById('shellReply');
  const composer = document.querySelector('.composer');
  if (!bar && composer) {
    bar = document.createElement('div');
    bar.id = 'shellReply';
    bar.className = 'shell-reply';
    const label = document.createElement('span');
    label.className = 'shell-reply-text';
    const x = document.createElement('button');
    x.type = 'button';
    x.textContent = '\u2715';
    x.title = MSG_TEXT.cancelReply;
    x.setAttribute('aria-label', MSG_TEXT.cancelReply);
    x.addEventListener('click', msgReplyClear);
    bar.append(label, x);
    composer.parentNode.insertBefore(bar, composer);
  }
  if (!bar) return;
  bar.querySelector('.shell-reply-text').textContent = '\u21A9 ' + (msgReply.name ? msgReply.name + ': ' : '') + msgReply.snippet;
  bar.hidden = false;
  if (inputEl) inputEl.focus();
}
// Just before a send reads the box: a plain message takes the quote line; a command or an action goes as it is.
function msgReplyApply() {
  if (!msgReply || !inputEl) return;
  const t = inputEl.value;
  if (!t.trim()) return;
  if (!t.trim().startsWith('/')) inputEl.value = msgQuoteLine(msgReply.name, msgReply.snippet) + t;
  msgReplyClear();
}
// The user's bubble with a quote line: the quote drawn above the message, pressing it finds the line it quotes.
function msgQuoteDraw(div) {
  const root = document.documentElement;
  if (!div || (root && root.classList && !root.classList.contains('shell2'))) return;
  const first = div.firstChild;
  if (!first || first.nodeType !== 3) return;
  const q = msgQuoteParse(first.nodeValue);
  if (!q) return;
  first.nodeValue = q.rest;
  const quote = document.createElement('button');
  quote.type = 'button';
  quote.className = 'msg-quote';
  if (q.name) { const b = document.createElement('b'); b.textContent = q.name; quote.appendChild(b); }
  quote.appendChild(document.createTextNode(q.snippet));
  quote.addEventListener('click', () => msgQuoteFind(div, q.snippet));
  div.insertBefore(quote, first);
}
function msgQuoteFind(from, snippet) {
  const log = typeof logEl !== 'undefined' ? logEl : document.getElementById('log');
  if (!log) return;
  const want = String(snippet || '').replace(/\u2026$/, '');
  const all = Array.prototype.slice.call(log.querySelectorAll('.md-say, .md-narr, .msg.user, .msg.action'));
  const before = all.slice(0, Math.max(0, all.indexOf(from)));
  for (let i = before.length - 1; i >= 0; i--) {
    if (msgSnippet(msgText(before[i])).replace(/\u2026$/, '').startsWith(want)) {
      before[i].scrollIntoView({ block: 'center' });
      before[i].classList.add('msg-flash');
      setTimeout(() => before[i].classList.remove('msg-flash'), 1300);
      return;
    }
  }
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
  const items = msgMenuItems({ kind, busy: typeof isBusy !== 'undefined' && isBusy, room, last: typeof regenOffered === 'function' && regenOffered(el),
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
      if (it.k === 'regen') { regenStart(); return; }
      if (it.k === 'copy') { if (await copyText(text)) msgToast(MSG_TEXT.copied); return; }
      if (it.k === 'reply') { msgReplyStart(el, kind, text); return; }
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
  // a reply takes its quote line just before the send reads the box (after app-retry.js has filled an empty box)
  document.addEventListener('click', (e) => {
    const b = e.target && e.target.closest ? e.target.closest('#send') : null;
    if (b && !b.disabled) msgReplyApply();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (!e.target || e.target.id !== 'input' || e.isComposing || e.keyCode === 229) return;
    if (e.key === 'Enter' && !e.shiftKey) msgReplyApply();
    else if (e.key === 'Escape' && msgReply) msgReplyClear();
  }, true);
  // a send takes the offer inside app-retry.js without clearRetry(): look again once it has gone out
  document.addEventListener('click', (e) => { if (e.target && e.target.closest && e.target.closest('#send')) setTimeout(msgMarkFailed, 0); });
  document.addEventListener('keydown', (e) => { if (e.target && e.target.id === 'input' && e.key === 'Enter') setTimeout(msgMarkFailed, 0); });
}
