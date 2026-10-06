// app-office.js -- a coworker's turn in a character's work window (docs/plans/unified-message-inbox.md inbox/E, D8,
// D12). Declarations only: it loads before app.js. The 1:1 is the character's desk in the office everyone shares, so
// what a coworker says to it shows as that coworker's own face bubble, what it does as a centre stage direction, and
// what the character itself sent as one "→ name" line -- all placed by time among the 1:1's own messages. The dm
// records stay on the server (dialog_log); nothing here is written into the 1:1's history. A private talk and a
// meeting room's screen show none of it.

const OFFICE_TEXT = { to: '→ ' };

function officeKey(m) { return String(m.dialog_id) + '#' + String(m.n); }

function officeShown(m) {
  const key = officeKey(m);
  const nodes = logEl ? logEl.querySelectorAll('.msg[data-office]') : [];
  for (let i = 0; i < nodes.length; i++) if (nodes[i].dataset.office === key) return nodes[i];
  return null;
}

function officeHere() {
  if (typeof sessionMode !== 'undefined' && sessionMode === 'private') return false;       // an undisturbed place
  if (typeof roomOpenId === 'function' && roomOpenId()) return false;                      // a meeting room's own screen
  return true;
}

// One dm message into #log; null when it is not for this screen or already drawn.
function officeDraw(m) {
  if (!m || !logEl || !officeHere() || officeShown(m)) return null;
  let node;
  if (m.mine) {
    const said = m.kind === 'action' ? '(' + m.text + ')' : m.text;
    node = addChat('action', OFFICE_TEXT.to + m.to_name + ': ' + said, false, false, false, false, null, null, false, m.ts);
  } else if (m.kind === 'action') {
    node = addChat('action', '✦ ' + m.who_name + ' — ' + m.text, false, false, false, false, null, null, false, m.ts);
  } else {
    node = addChat('assistant', m.text, true, false, false, false, null, null, false, m.ts);
    node.dataset.roomWho = m.who;   // the face and name of a run, as in a meeting room (rooms.css .room-lead)
    node.style.setProperty('--char-avatar', 'url("' + (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '')
      + '/api/characters/' + encodeURIComponent(m.who) + '/avatar")');
    node.insertBefore(roomEl('div', 'room-who', m.who_name), node.firstChild);
  }
  node.dataset.office = officeKey(m);
  node.dataset.syncRole = 'office';   // never the 1:1's own message to the sync (findRenderedByTs)
  if (typeof roomMarkRuns === 'function') roomMarkRuns();
  return node;
}

// A dm older than every 1:1 message on screen waits, hidden, until scrollback reaches its time: placed by time among
// only what is loaded, it sat above the loaded window and older sessions were then prepended over it, so yesterday's
// dm showed between two of today's turns (2026-10-04). Run after each draw and each scrollback hop.
function officeFit() {
  if (!logEl) return;
  let oldest = Infinity;
  logEl.querySelectorAll('.msg[data-ts]').forEach(n => {
    const t = Number(n.dataset.ts);
    if (!n.dataset.office && t && t < oldest) oldest = t;
  });
  const more = typeof scrollbackExhausted === 'undefined' || !scrollbackExhausted;
  logEl.querySelectorAll('.msg[data-office]').forEach(n => {
    const t = Number(n.dataset.ts || 0);
    n.hidden = more && (oldest === Infinity || t < oldest);
    if (!n.hidden && typeof placeMsgByTs === 'function') placeMsgByTs(n, t);
  });
}

// The character's dms, drawn into the 1:1 just opened -- run on every stream open, so a host restart redraws them --
// then the host is told the window is open: a coworker's turn not yet heard gets the character's reaction (D11).
async function officeLoad() {
  if (!officeHere() || !sessionCharacter || (typeof archiveBrowse !== 'undefined' && archiveBrowse)) return;
  const want = sessionCharacter;
  let data;
  try { data = await api('/api/office?character=' + encodeURIComponent(want)); } catch (_) { return; }
  if (want !== sessionCharacter) return;   // switched while it loaded
  ((data && data.messages) || []).forEach(officeDraw);
  officeFit();
  try { await api('/api/office/opened?character=' + encodeURIComponent(want)); } catch (_) {}
}
