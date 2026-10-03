// Homecoming / unsummon wizard (sp/N). One confirm, one farewell, then archive tip.
// Entry: bottom of the character profile panel (app-shell.js). Never tray/team, never one-click.
var unsummonUi = null;

function closeUnsummon() {
  var old = document.getElementById('unsummonOverlay');
  if (old && old.parentNode) old.parentNode.removeChild(old);
  unsummonUi = null;
}

function unsummonAfterClose(nextId) {
  var chain = (typeof loadCharacters === 'function') ? loadCharacters() : Promise.resolve();
  Promise.resolve(chain).then(function () {
    if (typeof renderCharacterTray === 'function') renderCharacterTray();
    if (typeof shellProfileOpen === 'function') {
      try { shellProfileOpen(); } catch (_) {}
    }
    if (typeof shellListSoon === 'function') shellListSoon(0);
    if (!nextId || typeof characterCatalog === 'undefined') return;
    var found = null;
    for (var i = 0; i < characterCatalog.length; i++) {
      if (characterCatalog[i].id === nextId) found = characterCatalog[i];
    }
    if (found && typeof selectCharacter === 'function') selectCharacter(found);
  });
}

function paintUnsummon() {
  if (!unsummonUi) return;
  var spec = unsummonUi.spec;
  var root = document.getElementById('unsummonOverlay');
  if (!root) {
    root = document.createElement('div');
    root.id = 'unsummonOverlay';
    root.className = 'summon-overlay';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    document.body.appendChild(root);
  }
  while (root.firstChild) root.removeChild(root.firstChild);
  var card = document.createElement('div');
  card.className = 'summon-card';
  var title = document.createElement('h2');
  title.className = 'summon-title';
  var prompt = document.createElement('p');
  prompt.className = 'summon-prompt';
  var body = document.createElement('div');
  var actions = document.createElement('div');
  actions.className = 'summon-actions';
  card.appendChild(title);
  card.appendChild(prompt);
  card.appendChild(body);
  card.appendChild(actions);
  root.appendChild(card);

  if (unsummonUi.busy) {
    title.textContent = spec.waiting || '...';
    return;
  }
  if (unsummonUi.result) {
    var ok = !!unsummonUi.result.ok;
    var nextId = ok ? unsummonUi.result.default : null;
    title.textContent = ok ? (spec.result_title || '') : (spec.failed || 'failed');
    prompt.textContent = ok ? (unsummonUi.result.farewell || '') : (unsummonUi.result.error || '');
    if (ok && unsummonUi.result.undo) {
      var tip = document.createElement('p');
      tip.className = 'summon-prompt';
      tip.textContent = unsummonUi.result.undo;
      body.appendChild(tip);
    }
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'primary';
    close.textContent = spec.close || 'Close';
    close.addEventListener('click', function () {
      closeUnsummon();
      if (ok) unsummonAfterClose(nextId);
    });
    actions.appendChild(close);
    return;
  }

  var step = (spec.steps || [])[0] || {};
  var name = unsummonUi.name || '';
  title.textContent = step.title || spec.result_title || '';
  prompt.textContent = String(step.prompt || '').split('{name}').join(name);
  var summary = document.createElement('div');
  summary.className = 'summon-summary';
  summary.textContent = name;
  body.appendChild(summary);

  var cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'art-filter-btn';
  cancel.textContent = spec.cancel || 'Cancel';
  cancel.addEventListener('click', closeUnsummon);
  actions.appendChild(cancel);

  var go = document.createElement('button');
  go.type = 'button';
  go.className = 'primary';
  go.textContent = spec.confirm_btn || 'Go';
  go.addEventListener('click', unsummonGo);
  actions.appendChild(go);
}

function unsummonGo() {
  if (!unsummonUi || unsummonUi.busy) return;
  unsummonUi.busy = true;
  unsummonUi.result = null;
  paintUnsummon();
  api('/api/characters/' + encodeURIComponent(unsummonUi.id) + '/unsummon', {
    method: 'POST',
    body: JSON.stringify({ confirm: true }),
    timeoutMs: 20000
  }).then(function (data) {
    if (!unsummonUi) return;
    unsummonUi.busy = false;
    unsummonUi.result = data || { ok: false };
    paintUnsummon();
  }).catch(function (err) {
    if (!unsummonUi) return;
    unsummonUi.busy = false;
    unsummonUi.result = { ok: false, error: (err && err.message) || '' };
    paintUnsummon();
  });
}

function openUnsummonWizard(character) {
  if (!character || !character.id) return;
  api('/api/unsummon', { timeoutMs: 8000 }).then(function (spec) {
    unsummonUi = {
      spec: spec || {},
      id: character.id,
      name: character.name || character.title || character.id,
      busy: false,
      result: null
    };
    paintUnsummon();
  }).catch(function () {
    if (typeof showCharacterToast === 'function') showCharacterToast('Unsummon');
  });
}
// Profile footer button (sp/N); app-shell.js calls it when this file is loaded.
function unsummonProfileButton(panel, c) {
  const home = shellEl('button', 'art-filter-btn shell-unsummon', '소환 해제');   // l10n-ok
  home.type = 'button';
  home.addEventListener('click', () => openUnsummonWizard(c));
  panel.appendChild(home);
}
