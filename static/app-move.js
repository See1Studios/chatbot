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
  }
}

function moveCardClose() {
  if (moveCard) moveCard.remove();
  moveCard = null;
}

// A card in the talk (not a modal): a line and buttons, each naming its action. Esc or "stay" closes it.
function moveCardOpen(text, choices) {
  moveCardClose();
  const node = typeof addNotice === 'function' ? addNotice('info', text, null, true) : null;
  if (!node) return;
  node.classList.add('move-card');
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
  moveCard = node;
  const first = row.querySelector('button');
  if (first) first.focus();
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
    b.addEventListener('click', () => moveTo('office'));
    brand.appendChild(b);
  }
  moveOfficeSync();
  if (typeof MutationObserver === 'function' && document.body) {
    new MutationObserver(moveOfficeSync).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && moveCard) moveCardClose(); });
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
