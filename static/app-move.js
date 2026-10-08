// app-move.js: moving between places (PLACE_MOVE_v1, docs/plans/private-mode.md §8.8, W6). The destination decides
// the room: the office is the work room, every place on the list is a private one -- the engine settles it from
// `/move <place>`. Ways in: the user's own "move" menu (plus menu; already two steps, no confirm) and the engine's
// move chip, which asks first with a door card (one tap) -- nothing of the private room is loaded before "move".
// Leaving is one tap: "to the office" in the header. The heart and /private stay for dev mode (shell.css).
const MOVE_TEXT = i18nTable('move');
let moveBusy = false, movePlaces = null, moveCard = null;

function movePlaceLabel(p) {
  const k = p && p.id ? 'place.' + p.id : '';
  return k && tr(k) !== k ? tr(k) : String((p && p.name) || '');
}

async function moveLoadPlaces() {
  if (movePlaces || typeof sessionId === 'undefined' || !sessionId) return movePlaces || [];
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/places');
    movePlaces = Array.isArray(res && res.places) ? res.places : [];
  } catch (e) {
    if (typeof failNotice === 'function') failNotice(MOVE_TEXT.places_failed, e);
    return [];
  }
  return movePlaces;
}

// The one way a move is made on the page: the switch route answers with the room to open (applyModeSwitch).
async function moveTo(dest) {
  if (moveBusy || typeof sessionId === 'undefined' || !sessionId || !dest) return;
  moveBusy = true;
  moveCardClose();
  document.documentElement.classList.add('shell-switching');   // the talk fades and the run line shows: it is moving
  try {
    const clientMid = _newClientMid();   // ROOM_SYNC_v1: the room_moved broadcast is ours, not a move to follow
    myPendingMids.add(clientMid);
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/message', {
      method: 'POST', body: JSON.stringify({ text: '/move ' + dest, client_mid: clientMid })
    });
    if (res && res.session && res.session.id) await applyModeSwitch(res);
  } catch (e) {
    if (typeof failNotice === 'function') failNotice(tr('session.mode_failed'), e);
  } finally {
    moveBusy = false;
    document.documentElement.classList.remove('shell-switching');
  }
}

function moveCardClose() {
  if (moveCard) moveCard.remove();
  moveCard = null;
}

// The door between places: its own card at the end of the talk -- not a system notice (no head, no swipe away) -- the
// question as its title, then buttons that each name their action. Esc or "stay" closes it (critique run 4).
function moveCardOpen(text, choices) {
  moveCardClose();
  const log = typeof logEl !== 'undefined' ? logEl : document.getElementById('log');
  if (!log) return;
  const node = document.createElement('div'), title = document.createElement('div');
  node.className = 'move-card';
  node.setAttribute('role', 'group');
  node.setAttribute('aria-label', text);
  title.className = 'move-card-title';
  title.textContent = text;
  node.appendChild(title);
  const row = document.createElement('div');
  row.className = 'move-card-actions';
  choices.forEach(c => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = c.stay ? 'ghost' : 'primary';
    b.textContent = c.label;
    b.addEventListener('click', () => (c.stay ? moveCardClose() : moveTo(c.dest)));
    row.appendChild(b);
  });
  node.appendChild(row);
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
  moveCard = node;
  // focus is on "stay": an Enter or Space typed after the tap must not open the private room (critique run 4, §8.8)
  const stay = Array.from(row.querySelectorAll('button')).find(b => b.className === 'ghost');
  if (stay) stay.focus();
}

// The engine's move chip ("/move <place>" from a marked personal turn): ask first.
function moveDoor(cmdText) {
  const dest = String(cmdText || '').replace(/^\/move\s+/i, '').trim();
  if (!dest) return;
  if (dest.toLowerCase() === 'office') { moveTo(dest); return; }
  const known = (movePlaces || []).find(p => p.id === dest || p.name === dest);
  const place = known ? movePlaceLabel(known) : dest;
  moveCardOpen(tr('move.door', { place }), [{ label: MOVE_TEXT.go, dest }, { label: MOVE_TEXT.stay, stay: true }]);
}

// The user's own move: the plus menu's "move" opens the list of places; picking one is the decision.
async function moveMenu() {
  const list = await moveLoadPlaces();
  if (!list.length) return;
  moveCardOpen(MOVE_TEXT.where, list.map(p => ({ label: movePlaceLabel(p), dest: p.id || p.name }))
    .concat([{ label: MOVE_TEXT.stay, stay: true }]));
}

// The place this private visit is at, as the header says it (PLACE_MOVE_v1): its catalog word, else its own name,
// else "private room" when the visit has none. Muted, not the accent (shell.css): the desk screen should not shout it.
function movePlaceNow() {
  const p = window.sessionPlace;
  return (p && movePlaceLabel(p)) || tr('shelltext.privateRoom');
}

function moveShown() {
  const priv = document.body.classList.contains('private-session');
  const group = typeof roomOpenId === 'function' && roomOpenId();   // a group room's visit is ux/O (§8.8)
  return { menu: !priv && !group, office: priv };
}

function moveOfficeSync() {
  const b = document.getElementById('shellOffice');
  if (b) b.hidden = !moveShown().office;
}

function moveInit() {
  const brand = document.querySelector('header .brand');
  if (brand && !document.getElementById('shellOffice')) {
    const b = document.createElement('button');
    b.id = 'shellOffice';
    b.type = 'button';
    b.className = 'ghost';
    b.textContent = MOVE_TEXT.office;
    b.title = MOVE_TEXT.office_key;
    b.addEventListener('click', () => moveTo('office'));
    brand.appendChild(b);
  }
  moveOfficeSync();
  if (typeof MutationObserver === 'function' && document.body) {
    new MutationObserver(moveOfficeSync).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && moveCard) moveCardClose();
    // Alt+O: back to the office at once, whatever the keyboard layout (e.code, not the typed letter)
    if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyO' && moveShown().office) { e.preventDefault(); moveTo('office'); }
  });
  // the plus menu gets "move" in the work room: added after the shell draws its own items
  if (typeof shellPlusOpen === 'function') {
    const open = shellPlusOpen;
    shellPlusOpen = function () {
      open.apply(this, arguments);
      const menu = document.getElementById('shellPlusMenu');
      if (!menu || !moveShown().menu) return;
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      b.textContent = MOVE_TEXT.menu;
      b.addEventListener('click', () => { if (typeof shellPlusClose === 'function') shellPlusClose(); moveMenu(); });
      menu.appendChild(b);
    };
  }
  const enter = typeof enterSession === 'function' ? enterSession : null;   // another talk: its own places
  if (enter) enterSession = function () { movePlaces = null; moveCardClose(); return enter.apply(this, arguments); };
}
