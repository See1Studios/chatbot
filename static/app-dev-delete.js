// Developer-mode only: remove one character folder. Not an archive and not a product farewell.
// Visible when body.dev-mode is on (pe.devMode, shellDevOn). The route also
// refuses unless the install edition is dev. Dialogs, rooms and sessions stay.
function shellDevDeleteReason(text) {
  const raw = String(text || '');
  if (raw.indexOf('home-character') >= 0) return tr('devdel.home');
  if (raw.indexOf('developer-edition-only') >= 0) return tr('devdel.dev_only');
  if (raw.indexOf('confirm-required') >= 0) return tr('devdel.confirm_needed');
  return tr('devdel.failed');
}

function shellDevDelete(c) {
  if (typeof shellDevOn !== 'function' || !shellDevOn() || !c || !c.id) return;
  const name = c.title || c.name || c.id;
  const ask = tr('devdel.ask', { name });
  if (!window.confirm(ask)) return;
  api('/api/characters/' + encodeURIComponent(c.id) + '/dev-delete', {
    method: 'POST',
    body: JSON.stringify({ confirm: true }),
  }).then(() => {
    if (typeof shellProfileClose === 'function') shellProfileClose();
    const chain = (typeof loadCharacters === 'function') ? loadCharacters() : Promise.resolve();
    return chain.then(() => {
      if (typeof shellListSoon === 'function') shellListSoon(0);
      const still = typeof openCharacterId === 'function' && openCharacterId() === c.id;
      if (!still || typeof characterCatalog === 'undefined' || typeof selectCharacter !== 'function') return null;
      const next = characterCatalog.find(x => x && x.id !== c.id);
      return next ? selectCharacter(next) : null;
    });
  }).catch(e => { window.alert(shellDevDeleteReason(e && e.message)); });
}

function shellDevDeleteButton(panel, c) {
  if (!panel || !c) return;
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'shell-rowbtn shell-dev shell-dev-delete';
  b.textContent = tr('devdel.button');
  b.addEventListener('click', () => shellDevDelete(c));
  panel.appendChild(b);
}
