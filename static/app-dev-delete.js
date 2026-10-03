// Developer-mode only: remove one character folder. Not an archive and not a product farewell.
// Visible when body.dev-mode is on (pe.devMode, shellDevOn). The route also
// refuses unless the install edition is dev. Dialogs, rooms and sessions stay.
function shellDevDeleteReason(text) {
  const raw = String(text || '');
  if (raw.indexOf('home-character') >= 0) return '기본 캐릭터는 지우지 않습니다.'; // l10n-ok
  if (raw.indexOf('developer-edition-only') >= 0) return '개발자 설치에서만 지울 수 있습니다.'; // l10n-ok
  if (raw.indexOf('confirm-required') >= 0) return '확인 후에만 지웁니다.'; // l10n-ok
  return '삭제하지 못했습니다.'; // l10n-ok
}

function shellDevDelete(c) {
  if (typeof shellDevOn !== 'function' || !shellDevOn() || !c || !c.id) return;
  const name = c.title || c.name || c.id;
  const ask = name + ' 폴더를 지울까요?\n카드, 기억, 외형, 상태만 지우고 대화 기록은 남깁니다.'; // l10n-ok
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
  b.textContent = '이 캐릭터 삭제'; // l10n-ok
  b.addEventListener('click', () => shellDevDelete(c));
  panel.appendChild(b);
}
