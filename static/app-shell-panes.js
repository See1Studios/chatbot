// app-shell-panes.js -- the shell's drawer: the profile card, the settings, and the panes they open
// (files, history, art, team, status, appearance). Split from app-shell.js (size cap). The talk list
// and entering a talk stay in app-shell.js, which loads first and owns SHELL_TEXT, shellState and shellEl.
// app.js calls shellInit, which calls shellPanelsInit once these functions exist.

// ux/S2 (UX11): what belongs to the open talk's character is reached from its profile card,
// what belongs to the whole app from settings. Details and developer mode are remembered per browser.
// The key itself lives in app-shell.js (shellInit reads it on boot; shellSetDev writes it).

function shellDevOn() { return Boolean(document.body && document.body.classList.contains('dev-mode')); }
function shellSetDev(on) {
  document.body.classList.toggle('dev-mode', Boolean(on));
  try { localStorage.setItem(SHELL_DEV_KEY, on ? '1' : '0'); } catch (_) { /* private window */ }
}
const SHELL_PANES = { artifacts: 'files', sessions: 'history', activity: 'log', status: 'accounts', team: 'characters', evolution: 'improve', appearance: 'appearance', chat_settings: 'chat_settings' };
const STATUS_SECTIONS = ['accounts', 'instructions', 'skills', 'mcp'];
const TEAM_SECTIONS = ['characters', 'roles', 'auto_react'];
function shellProfileRows(ctx) {
  // "pictures" is one place: the character's art screen shows them, takes uploads and asks for new ones (app-art.js)
  const rows = ctx.art ? [{ k: 'art', label: SHELL_TEXT.art }] : [];
  rows.push({ k: 'sessions', label: SHELL_TEXT.history }, { k: 'artifacts', label: SHELL_TEXT.files });
  if (ctx.manage) rows.push({ k: 'manage', label: SHELL_TEXT.manage });   // this character's part of the old team pane
  return rows;
}
// The brain and the model are managed in the card itself (operator, 2026-09-30), not by sending the user back to
// the talk's pickers. One option per provider -- the character as that brain draws it -- and per model of the
// provider picked now. A provider whose use is blocked stays pickable, as in the tray: picking it shows why.
function shellBrainOptions(catalog, current, blockedReason, label) {
  return (catalog || []).map(p => {
    const why = blockedReason ? blockedReason(p.id) : '';
    return { id: p.id, label: label ? label(p) : (p.name || p.id), current: p.id === current, blocked: Boolean(why), why: why || '' };
  });
}
function shellModelOptions(choices, current) {
  return (choices || []).map(m => ({ value: m.value, label: m.label || m.value, current: m.value === current }));
}
function shellSettingsRows(ctx) {
  const rows = [
    { k: 'appearance', label: SHELL_TEXT.appearance },
    { k: 'chat_settings', label: SHELL_TEXT.chat_settings },
    { k: 'push', label: SHELL_TEXT.notifications, on: Boolean(ctx.push) },
    { k: 'characters', label: SHELL_TEXT.characters, div: true },
    { k: 'roles', label: SHELL_TEXT.roles },
    { k: 'auto_react', label: SHELL_TEXT.auto_react },
    { k: 'accounts', label: SHELL_TEXT.accounts, div: true },
    { k: 'instructions', label: SHELL_TEXT.instructions },
    { k: 'skills', label: SHELL_TEXT.skills },
    { k: 'mcp', label: SHELL_TEXT.mcp },
    { k: 'dev', label: SHELL_TEXT.dev, on: Boolean(ctx.dev), div: true },
    { k: 'activity', label: SHELL_TEXT.log, dev: true },
    { k: 'evolution', label: SHELL_TEXT.improve, dev: true }
  ];
  if (ctx.revive) rows.push({ k: 'revive', label: SHELL_TEXT.revive, div: true });   // the dev install's host repair
  return rows;
}
const SHELL_ICONS = {
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  appearance: '<circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>',
  chat_settings: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  accounts: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  characters: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  roles: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  auto_react: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  instructions: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>',
  skills: '<path d="M20.5 12.5a2.5 2.5 0 0 1-2.5 2.5h-1v1a2.5 2.5 0 0 1-5 0v-1H8a2.5 2.5 0 0 1-2.5-2.5v-4A2.5 2.5 0 0 1 8 6h4v1a2.5 2.5 0 0 0 5 0V6h1a2.5 2.5 0 0 1 2.5 2.5v4z"/>',
  mcp: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  push: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  dev: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  activity: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  evolution: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  revive: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  art: '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  sessions: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  artifacts: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  manage: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
};
function shellRowIcon(k) {
  const body = SHELL_ICONS[k];
  if (!body) return null;
  const svg = (document.createElementNS && document.createElementNS('http://www.w3.org/2000/svg', 'svg')) || document.createElement('svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'btn-icon-svg');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = body;
  return svg;
}
function shellRowButton(row) {
  const b = shellEl('button', 'shell-rowbtn' + (row.dev ? ' shell-dev' : '') + (row.on ? ' on' : ''));
  b.type = 'button';
  b.setAttribute('data-k', row.k);
  const left = shellEl('span', 'shell-rowbtn-left');
  left.style.display = 'inline-flex';
  left.style.alignItems = 'center';
  left.style.gap = '.6rem';
  const icon = shellRowIcon(row.k);
  if (icon) left.appendChild(icon);
  left.appendChild(shellEl('span', '', row.label));
  b.appendChild(left);
  if (row.k === 'dev' || row.k === 'push') {
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-checked', String(Boolean(row.on)));
    b.appendChild(shellEl('span', 'switch-ui'));
  } else if (row.detail) b.appendChild(shellEl('small', '', row.detail));
  return b;
}
function shellPanelHead(title, onClose, glyph) {
  const head = shellEl('div', 'shell-panel-head'), x = shellEl('button', 'ghost', glyph || '\u2039');
  x.type = 'button';
  x.title = SHELL_TEXT.close;
  x.setAttribute('aria-label', SHELL_TEXT.close);
  x.addEventListener('click', onClose);
  head.append(x, shellEl('strong', '', title));
  return head;
}
// A pane opens as a screen of the talk column. `from` is where its Back leads: the card it was opened from, or the
// settings (which stay open beside it on a wide screen; on a narrow one Back shows the list they cover).
function shellGoPane(tab, from) {
  shellState.paneFrom = from || '';
  // A phone shows one screen at a time (wide, the card stays beside the pane). Going forward from the card, the
  // card steps aside to the LEFT and waits there, so Back brings it in from the left -- the way the arrow points.
  if (shellNarrow()) {
    const col = document.getElementById('shellProfile');
    if (from === 'profile' && col && col.classList.contains('open')) col.classList.add('behind');
    else shellProfileClose();
  }
  shellShowChat();
  // the history is this character's own: the old tab's character strip is hidden under the shell (shell.css)
  if (tab === 'sessions' && typeof setSessionCharFilter === 'function') setSessionCharFilter(openCharacterId());
  switchTab(tab);
}
// The pictures are a pane like the others (operator: it was built differently and came up like a modal). 'art' is
// no old tab, so switchTab('art') leaves the middle empty; the art manager (app-art.js) draws into an #artManager
// it finds, so one is put in the stage first -- without the modal's classes -- and it fills that instead of making
// its own overlay. The pane's bar is its header. Leaving the pane removes it (the switchTab wrap below).
async function shellGoArt(cid) {
  shellGoPane('art', 'profile');
  const stage = document.querySelector('.stage');
  if (stage && !document.getElementById('artManager')) {
    const host = shellEl('div', 'art-mgr-overlay shell-art');
    host.id = 'artManager';
    stage.appendChild(host);
  }
  await openArtManager(cid);
}
// The old team pane, in two (operator, 2026-10-01): what is one character's -- its card, roles and brains -- opens
// from that character's profile; what is shared -- role packs, the house memory, reactions, importing a card --
// stays in the settings. One pane, filtered: `only` is the character whose card alone is shown, or '' for the
// shared part. A block of the pane carries the character's id (app-team.js) or none.
function shellTeamShows(block, sec, only) {
  if (arguments.length === 2 && typeof block === 'string') {
    const onlyCid = sec;
    return onlyCid ? block === onlyCid : !block;
  }
  if (block && typeof block.getAttribute === 'function') {
    const cid = block.getAttribute('data-character-id') || '';
    if (only) return cid === only;
    const s = block.getAttribute('data-team-section') || '';
    return s === (sec || 'characters');
  }
  const cid = block || '';
  if (only) return cid === only;
  return sec ? (sec === 'characters' ? Boolean(cid) : false) : !cid;
}
function shellTeamFilter() {
  const pane = document.getElementById('teamPane'), list = document.getElementById('teamList');
  if (!pane || !list || !shellOn()) return;
  const only = shellState.teamOnly, sec = shellState.teamSection || 'characters';
  if (only) pane.setAttribute('data-shell-only', only); else pane.removeAttribute('data-shell-only');
  pane.setAttribute('data-shell-section', sec);
  Array.prototype.forEach.call(list.children, n => { n.hidden = !shellTeamShows(n, sec, only); });
  const charActions = document.getElementById('teamCharActions');
  if (charActions) charActions.hidden = Boolean(only || sec !== 'characters');
  const roleActions = document.getElementById('teamRoleActions');
  if (roleActions) roleActions.hidden = Boolean(only || sec !== 'roles');
  const titleEl = document.getElementById('teamHeadTitle');
  if (titleEl) {
    titleEl.textContent = only ? (SHELL_TEXT.manage || '') : (SHELL_TEXT[sec] || SHELL_TEXT.team || '');
  }
  const hintEl = document.getElementById('teamHeadHint');
  if (hintEl) {
    if (only) hintEl.textContent = '';
    else if (sec === 'characters') hintEl.textContent = typeof tr === 'function' ? tr('team.hint') : '';
    else if (sec === 'roles') hintEl.textContent = typeof tr === 'function' ? tr('team.shared_hint') : '';
    else if (sec === 'auto_react') hintEl.textContent = (typeof AUTO_TEXT !== 'undefined' && AUTO_TEXT.hint) || (typeof tr === 'function' ? tr('team.auto.hint') : '');
  }
}
function shellGoTeam(cid, from) {
  shellState.teamOnly = cid || '';
  shellState.teamSection = '';
  shellTeamFilter();                 // what is drawn already, at once; loadTeam() redraws and the wrap filters again
  shellGoPane('team', from);
}
function shellGoTeamSection(sec, from) {
  shellState.teamOnly = '';
  shellState.teamSection = sec || 'characters';
  shellTeamFilter();
  shellGoPane('team', from);
}
function shellStatusShows(sec, only) { return only ? sec === only : true; }
function shellStatusFilter() {
  const p = document.getElementById('statusPane');
  if (!p || !shellOn()) return;
  const only = shellState.statusOnly || 'accounts', g = document.getElementById('statusConfigGroup');
  p.setAttribute('data-shell-only', only);
  if (g) g.hidden = true;
  Array.prototype.forEach.call(p.children, n => {
    if (n !== g) n.hidden = !shellStatusShows(n.getAttribute('data-status-section') || '', only);
  });
}
function shellGoStatus(sec, from) {
  shellState.statusOnly = sec || 'accounts';
  shellStatusFilter();
  shellGoPane('status', from);
}
function shellAppearanceDraw() {
  const p = document.getElementById('appearancePane');
  if (!p) return;
  const nowTheme = document.documentElement.getAttribute('data-theme') || '';
  const swatches = p.querySelectorAll('#appearanceThemeSwatches .theme-swatch');
  swatches.forEach(s => {
    const name = s.getAttribute('data-theme-choice');
    s.classList.toggle('active', name === nowTheme);
    s.setAttribute('aria-checked', String(name === nowTheme));
    s.setAttribute('aria-pressed', String(name === nowTheme));
    if (typeof tr === 'function') {
      s.title = tr('theme.' + name);
      s.setAttribute('aria-label', s.title);
    }
    if (!s._bound) {
      s._bound = true;
      s.addEventListener('click', () => {
        if (typeof chooseTheme === 'function') chooseTheme(name);
        shellAppearanceDraw();
      });
    }
  });

  const isAdv = document.body.classList.contains('density-advanced');
  const densitySwitch = document.getElementById('appearanceDensitySwitch');
  const densityRow = document.getElementById('appearanceDensityRow');
  if (densitySwitch) {
    densitySwitch.classList.toggle('on', isAdv);
    densitySwitch.setAttribute('aria-checked', String(isAdv));
  }
  if (densityRow && !densityRow._bound) {
    densityRow._bound = true;
    densityRow.addEventListener('click', () => {
      if (typeof setDensity === 'function') setDensity(!document.body.classList.contains('density-advanced'));
      shellAppearanceDraw();
    });
  }

  const curSt = typeof getStreamStyle === 'function' ? getStreamStyle() : 'char';
  const streamBtn = document.getElementById('appearanceStreamBtn');
  const streamRow = document.getElementById('appearanceStreamRow');
  const streamHint = document.getElementById('appearanceStreamHint');
  const isLine = curSt === 'line';
  const label = isLine ? SHELL_TEXT.streamLine : SHELL_TEXT.streamChar;
  if (streamBtn) streamBtn.textContent = label || (isLine ? 'line' : 'char');
  if (streamHint) streamHint.textContent = label || '';
  if (streamRow && !streamRow._bound) {
    streamRow._bound = true;
    streamRow.addEventListener('click', () => {
      const next = (typeof getStreamStyle === 'function' ? getStreamStyle() : 'char') === 'line' ? 'char' : 'line';
      if (typeof setStreamStyle === 'function') setStreamStyle(next);
      shellAppearanceDraw();
    });
  }
}
var CHAT_KEEP_CHOICES_KEY = 'pe_chat_keep_choices';
function isChoiceKeepEnabled() {
  try { return typeof localStorage !== 'undefined' && localStorage ? (localStorage.getItem(CHAT_KEEP_CHOICES_KEY) !== '0') : true; } catch (_) { return true; }
}
function setChoiceKeepEnabled(on) {
  try { if (typeof localStorage !== 'undefined' && localStorage) localStorage.setItem(CHAT_KEEP_CHOICES_KEY, on ? '1' : '0'); } catch (_) {}
}
function shellChatSettingsEnsure() {
  let p = document.getElementById('chatSettingsPane');
  if (p) return p;
  const stage = (document.querySelector && document.querySelector('.stage')) || document.body;
  if (!stage) return null;
  p = shellEl('div', 'shell-settings-pane');
  p.id = 'chatSettingsPane';
  p.setAttribute('role', 'tabpanel');
  p.setAttribute('aria-labelledby', 'chatSettingsHeading');
  const sec = shellEl('section', 'status-section');
  const h2 = shellEl('h2', 'status-head-row');
  h2.id = 'chatSettingsHeading';
  const icon = shellRowIcon('chat_settings');
  if (icon) h2.appendChild(icon);
  h2.appendChild(shellEl('span', '', SHELL_TEXT.chat_settings || ''));
  sec.appendChild(h2);
  const list = shellEl('div', 'status-list');
  const item = shellEl('div', 'status-item');
  item.id = 'chatKeepChoicesRow';
  item.style.cssText = 'display:flex;flex-direction:row;align-items:center;justify-content:space-between;gap:1rem;cursor:pointer';
  const textWrap = shellEl('div', '');
  textWrap.style.cssText = 'flex:1 1 auto;min-width:0';
  const nameEl = shellEl('div', 'status-item-name', SHELL_TEXT.keepChoices || '');
  nameEl.id = 'chatKeepChoicesLabel';
  const hintEl = shellEl('div', 'status-hint', SHELL_TEXT.keepChoicesHint || '');
  hintEl.id = 'chatKeepChoicesHint';
  textWrap.append(nameEl, hintEl);
  const sw = shellEl('button', 'status-toggle');
  sw.id = 'chatKeepChoicesSwitch';
  sw.type = 'button';
  sw.setAttribute('role', 'switch');
  sw.appendChild(shellEl('span', 'switch-ui'));
  item.append(textWrap, sw);
  list.appendChild(item);
  sec.appendChild(list);
  p.appendChild(sec);
  stage.appendChild(p);
  return p;
}
function shellChatSettingsDraw() {
  const p = shellChatSettingsEnsure();
  if (!p) return;
  const on = typeof isChoiceKeepEnabled === 'function' ? isChoiceKeepEnabled() : true;
  const sw = document.getElementById('chatKeepChoicesSwitch'), row = document.getElementById('chatKeepChoicesRow');
  if (sw) { sw.classList.toggle('on', on); sw.setAttribute('aria-checked', String(on)); }
  if (row && !row._bound) {
    row._bound = true;
    row.addEventListener('click', () => {
      const cur = typeof isChoiceKeepEnabled === 'function' ? isChoiceKeepEnabled() : true;
      const next = !cur;
      if (typeof setChoiceKeepEnabled === 'function') setChoiceKeepEnabled(next);
      if (!next) {
        if (typeof resetChoiceBar === 'function') resetChoiceBar();
        else if (typeof window !== 'undefined' && typeof window.resetChoiceBar === 'function') window.resetChoiceBar();
      } else {
        if (typeof syncLastChoices === 'function') syncLastChoices();
        else if (typeof window !== 'undefined' && typeof window.syncLastChoices === 'function') window.syncLastChoices();
      }
      shellChatSettingsDraw();
    });
  }
}
if (typeof window !== 'undefined') {
  window.setChoiceKeepEnabled = setChoiceKeepEnabled;
  window.shellChatSettingsDraw = shellChatSettingsDraw;
}
async function shellUserPaneDraw() {
  const p = document.getElementById('userPane');
  if (!p) return;
  const preview = document.getElementById('userAvatarPreview');
  const input = document.getElementById('userAvatarInput');
  const changeBtn = document.getElementById('userAvatarChangeBtn');
  const removeBtn = document.getElementById('userAvatarRemoveBtn');
  const editor = document.getElementById('userMdEditor');
  const saveBtn = document.getElementById('userMdSaveBtn');
  const msg = document.getElementById('userSaveMsg');

  const getName = () => (typeof IDENTITY !== 'undefined' && IDENTITY.user_title) || SHELL_TEXT.you;

  if (!p._bound) {
    p._bound = true;
    if (changeBtn && input) {
      changeBtn.addEventListener('click', () => input.click());
    }
    if (input) {
      input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        try {
          if (changeBtn) changeBtn.disabled = true;
          const res = await api('/api/user/avatar', {
            method: 'POST',
            headers: { 'Content-Type': file.type || 'image/jpeg' },
            body: file,
          });
          if (res && res.ok) {
            window.__USER_AVATAR__ = res.avatar_url;
            if (preview) preview.src = res.avatar_url;
            if (removeBtn) removeBtn.style.display = 'inline-block';
            if (typeof shellUserBarDraw === 'function') shellUserBarDraw();
            if (msg) {
              msg.textContent = typeof tr === 'function' ? tr('user.photo_updated') : 'Photo updated.';
              setTimeout(() => { if (msg) msg.textContent = ''; }, 3000);
            }
          } else {
            throw new Error((res && res.error) || 'Upload failed');
          }
        } catch (err) {
          if (msg) msg.textContent = typeof tr === 'function' ? tr('user.save_failed', { error: err.message || err }) : 'Error: ' + err.message;
        } finally {
          if (changeBtn) changeBtn.disabled = false;
          input.value = '';
        }
      });
    }
    if (removeBtn) {
      removeBtn.addEventListener('click', async () => {
        try {
          removeBtn.disabled = true;
          const res = await api('/api/user/avatar', { method: 'DELETE' });
          if (res && res.ok) {
            window.__USER_AVATAR__ = null;
            if (removeBtn) removeBtn.style.display = 'none';
            if (preview && typeof initialAvatar === 'function') {
              preview.src = initialAvatar(getName());
            }
            if (typeof shellUserBarDraw === 'function') shellUserBarDraw();
            if (msg) {
              msg.textContent = typeof tr === 'function' ? tr('user.photo_removed') : 'Photo removed.';
              setTimeout(() => { if (msg) msg.textContent = ''; }, 3000);
            }
          } else {
            throw new Error((res && res.error) || 'Delete failed');
          }
        } catch (err) {
          if (msg) msg.textContent = typeof tr === 'function' ? tr('user.save_failed', { error: err.message || err }) : 'Error: ' + err.message;
        } finally {
          removeBtn.disabled = false;
        }
      });
    }
    if (saveBtn && editor) {
      saveBtn.addEventListener('click', async () => {
        try {
          saveBtn.disabled = true;
          const res = await api('/api/user', {
            method: 'PUT',
            body: JSON.stringify({ user_md: editor.value }),
          });
          if (res && res.ok) {
            if (msg) {
              msg.textContent = typeof tr === 'function' ? tr('user.saved') : 'Saved.';
              setTimeout(() => { if (msg) msg.textContent = ''; }, 3000);
            }
          } else {
            throw new Error((res && res.error) || 'Save failed');
          }
        } catch (err) {
          if (msg) msg.textContent = typeof tr === 'function' ? tr('user.save_failed', { error: err.message || err }) : 'Error: ' + err.message;
        } finally {
          saveBtn.disabled = false;
        }
      });
    }
  }

  try {
    const data = await api('/api/user');
    if (data && data.ok) {
      if (editor) editor.value = data.user_md || '';
      if (data.has_avatar && data.avatar_url) {
        window.__USER_AVATAR__ = data.avatar_url;
        if (preview) preview.src = data.avatar_url;
        if (removeBtn) removeBtn.style.display = 'inline-block';
      } else {
        window.__USER_AVATAR__ = null;
        if (preview && typeof initialAvatar === 'function') preview.src = initialAvatar(getName());
        if (removeBtn) removeBtn.style.display = 'none';
      }
      if (typeof shellUserBarDraw === 'function') shellUserBarDraw();
    }
  } catch (err) {
    if (msg) msg.textContent = typeof tr === 'function' ? tr('user.save_failed', { error: err.message || err }) : 'Error: ' + err.message;
  }
}
function shellArtGone() {
  const m = document.getElementById('artManager');
  if (m && m.classList.contains('shell-art')) m.remove();
}
function shellPaneBack() {
  const from = shellState.paneFrom;
  shellState.paneFrom = '';
  switchTab('chat');
  if (!shellNarrow()) return;                  // wide: the card or the settings never left
  if (from === 'profile') shellProfileOpen();
  else if (from === 'settings') shellShowList();
}

// open = on screen; "behind" = stepped aside left while a pane it opened is shown (phone only)
function shellProfileIsOpen() {
  const p = document.getElementById('shellProfile');
  return Boolean(p && p.classList.contains('open') && !p.classList.contains('behind'));
}
function shellProfileClose() {
  const p = document.getElementById('shellProfile');
  if (p) p.classList.remove('open', 'behind');
  if (document.body) document.body.classList.remove('shell-profile-open');
}
function shellProfileOpen() {
  const column = document.getElementById('shellProfile'), panel = column && column.firstChild;   // the fixed-width inside
  if (typeof roomOpenId === 'function' && roomOpenId()) {
    if (typeof roomProfileOpen === 'function') roomProfileOpen();
    return;
  }
  const c = typeof currentCharacter === 'function' ? currentCharacter() : null;
  if (!panel || !c) return;
  if (typeof shellProfileDraw === 'function') {
    shellProfileDraw(panel, c, column);
  } else {
    const rows = shellProfileRows({ art: typeof openArtManager === 'function', manage: typeof loadTeam === 'function' });
    panel.textContent = '';
    const card = shellEl('div', 'shell-card'), img = document.createElement('img'), list = shellEl('div', 'shell-rows');
    img.alt = '';
    img.onerror = () => { img.onerror = null; img.src = initialAvatar(c.name || c.title); };
    img.src = characterOwnPortrait(c);
    card.append(img, shellEl('div', 'shell-card-name', c.title || c.name || ''),
      shellEl('div', 'shell-card-sub', shellPresenceText(sessionMode, isBusy)));
    rows.forEach(row => {
      const b = shellRowButton(row);
      b.addEventListener('click', () => {
        if (SHELL_PANES[row.k]) return shellGoPane(row.k, 'profile');
        if (row.k === 'art') shellGoArt(c.id);
        else if (row.k === 'manage') shellGoTeam(c.id, 'profile');
      });
      list.appendChild(b);
    });
    panel.append(shellPanelHead(SHELL_TEXT.profile, shellProfileClose, shellNarrow() ? '\u2039' : '\u2715'), card, list,
      shellBrainSection(c), shellModelSection(), shellContextSection(),
      typeof shellRelationSection == 'function' ? shellRelationSection(c) : '');
    if (typeof shellQuotaSection === 'function') panel.insertBefore(shellQuotaSection(), list);
    if (typeof shellBrainUseSection === 'function') panel.appendChild(shellBrainUseSection(c));
    if (typeof shellDevDeleteButton === "function") shellDevDeleteButton(panel, c);
  }
  shellMarkPane();
  column.classList.remove('behind');
  column.classList.add('open');
  document.body.classList.add('shell-profile-open');
}
// The row of the pane shown in the middle is marked in the card and the settings.
function shellMarkPane() {
  let now = document.documentElement.dataset.tab || 'chat';
  if (now === 'team') now = shellState.teamOnly ? 'manage' : (shellState.teamSection || 'characters');
  else if (now === 'status') now = shellState.statusOnly || 'accounts';
  document.querySelectorAll('.shell-rowbtn[data-k], .shell-action-card[data-k]').forEach(b => b.classList.toggle('current', b.getAttribute('data-k') === now));
}
function shellSection(title) {
  const box = shellEl('div', 'shell-section');
  box.appendChild(shellEl('div', 'shell-section-title', title));
  return box;
}
function shellBrainSection(c) {
  const box = shellSection(SHELL_TEXT.brain), grid = shellEl('div', 'shell-brains');
  const now = providerEl ? providerEl.value : '';
  shellBrainOptions(providerCatalog, now, providerUseBlockedReason, providerCreditLabel).forEach(o => {
    const b = shellEl('button', 'shell-brain' + (o.current ? ' current' : '') + (o.blocked ? ' blocked' : ''));
    const pic = document.createElement('img');
    b.type = 'button';
    b.title = o.label + (o.why ? ' · ' + o.why : '');
    if (o.current) b.setAttribute('aria-current', 'true');
    pic.alt = '';
    pic.onerror = () => { pic.onerror = null; pic.src = initialAvatar(c.name || c.title); };
    pic.src = characterPortrait(c, { id: o.id });
    b.append(pic, shellEl('span', '', o.label));
    // picking a blocked one opens its status pane (selectProvider), which closes the card; otherwise the card redraws
    b.addEventListener('click', async () => { if (!o.current) { await selectProvider(o.id); if (currentTab === 'chat') shellProfileOpen(); } });
    grid.appendChild(b);
  });
  box.appendChild(grid);
  return box;
}
function shellModelSection() {
  const box = shellSection(SHELL_TEXT.model), list = shellEl('div', 'shell-models');
  const has = typeof modelEl !== 'undefined' && modelEl && typeof modelChoices === 'function';
  shellModelOptions(has ? modelChoices() : [], has ? modelEl.value : '').forEach(o => {
    const b = shellEl('button', 'shell-rowbtn shell-model' + (o.current ? ' current' : ''), o.label);
    b.type = 'button';
    if (o.current) b.setAttribute('aria-current', 'true');
    b.addEventListener('click', () => { if (!o.current) { pickModel(o.value); shellProfileOpen(); } });
    list.appendChild(b);
  });
  box.appendChild(list);
  box.hidden = !list.children.length;
  return box;
}
function shellContextSection() {
  const title = typeof tr === 'function' ? tr('status.context.title') : 'Context';
  const box = shellSection(title);
  box.id = 'shellContextSection';
  const hint = shellEl('div', 'status-hint', typeof tr === 'function' ? tr('status.context.hint') : '');
  hint.style.margin = '0 0 .4rem';
  const list = shellEl('div', 'status-list');
  list.id = 'statusContext';
  box.append(hint, list);
  if (typeof loadContextNow === 'function') loadContextNow();
  return box;
}

function shellSettingsClose() { const p = document.getElementById('shellSettings'); if (p) p.classList.remove('open'); }
function shellSettingsOpen() {
  const panel = document.getElementById('shellSettings'), defib = document.getElementById('defibBtn');
  if (!panel) return;
  const pushOn = typeof isPushEnabled === 'function' ? isPushEnabled() : (localStorage.getItem('chatbot.pushEnabled') === 'true');
  const baseRows = shellSettingsRows({ advanced: document.body.classList.contains('density-advanced'), dev: shellDevOn(),
    revive: Boolean(defib && defib.style.display !== 'none'), push: pushOn });
  const rows = [
    { k: 'user', label: SHELL_TEXT.user || (typeof tr === 'function' ? tr('shelltext.user') : 'User') },
    ...baseRows
  ];
  panel.textContent = '';
  const list = shellEl('div', 'shell-rows');
  rows.forEach(row => {
    if (row.div) {
      const hr = shellEl('hr', 'shell-divider' + (row.dev ? ' shell-dev' : ''));
      list.appendChild(hr);
    }
    const b = shellRowButton(row);
    b.addEventListener('click', () => {
      if (row.k === 'user') return shellGoPane('user', 'settings');
      if (row.k === 'appearance') return shellGoPane('appearance', 'settings');
      if (row.k === 'chat_settings') return shellGoPane('chat_settings', 'settings');
      if (TEAM_SECTIONS.includes(row.k)) return shellGoTeamSection(row.k, 'settings');
      if (STATUS_SECTIONS.includes(row.k)) return shellGoStatus(row.k, 'settings');
      if (SHELL_PANES[row.k]) return shellGoPane(row.k, 'settings');
      if (row.k === 'push') return (window.togglePushNotification || (() => {}))(!row.on, shellSettingsOpen);
      if (row.k === 'dev') {
        shellSetDev(!shellDevOn());
        // turned off while one of its panes is shown: back to the talk
        if (!shellDevOn() && (currentTab === 'activity' || currentTab === 'evolution')) { shellState.paneFrom = ''; switchTab('chat'); }
        shellSettingsOpen();
      }
      else if (row.k === 'revive') { shellSettingsClose(); defib.click(); }
    });
    list.appendChild(b);
  });
  panel.append(shellPanelHead(SHELL_TEXT.settings, shellSettingsClose), list);
  shellMarkPane();
  panel.classList.add('open');
}

// Builds the card, the settings and the bar above a pane; the header's name and picture open the card.
function shellPanelsInit() {
  const list = document.getElementById('shellList'), foot = list && list.querySelector('.shell-list-foot');
  const stage = document.querySelector('.stage-shell'), wrap = document.getElementById('appWrap');   // wrap = the talk column
  if (!list || !foot || !stage || !wrap || document.getElementById('shellProfile')) return;
  const profile = shellEl('aside', 'shell-profile'), settings = shellEl('div', 'shell-settings');
  profile.id = 'shellProfile';
  profile.setAttribute('aria-label', SHELL_TEXT.profile);
  settings.id = 'shellSettings';
  profile.appendChild(shellEl('div', 'shell-profile-in'));
  document.body.appendChild(profile);          // the last column of the page (shell.css), beside the talk
  list.appendChild(settings);
  const menu = document.getElementById('shellMenu'), me = document.getElementById('shellUserBar');
  [menu, me].forEach(b => { if (b) { b.title = SHELL_TEXT.settings; b.addEventListener('click', () => shellSettingsOpen()); } });
  if (menu) menu.setAttribute('aria-label', SHELL_TEXT.menu);
  if (me) {
    me.title = SHELL_TEXT.user || (typeof tr === 'function' ? tr('shelltext.user') : 'User');
    me.setAttribute('aria-label', me.title);
    me.addEventListener('click', (e) => {
      e.stopImmediatePropagation();
      shellSettingsClose();
      shellGoPane('user', 'list');
    }, true);
  }
  shellUserBarDraw();
  const bar = shellEl('div', 'shell-pane-bar'), back = shellEl('button', 'ghost', '\u2039');
  bar.id = 'shellPaneBar';
  back.type = 'button';
  back.title = SHELL_TEXT.back2;
  back.setAttribute('aria-label', SHELL_TEXT.back2);
  back.addEventListener('click', () => shellPaneBack());
  bar.append(back, shellEl('strong', 'shell-pane-title'));
  wrap.insertBefore(bar, stage);
  const tab = switchTab;
  switchTab = function (t) {
    tab.apply(this, arguments);
    const now = document.documentElement.dataset.tab || t;
    const appPane = document.getElementById('appearancePane');
    if (appPane) appPane.style.display = (now === 'appearance' ? 'flex' : 'none');
    if (now === 'appearance') shellAppearanceDraw();
    const chatPane = document.getElementById('chatSettingsPane');
    if (chatPane) chatPane.style.display = (now === 'chat_settings' ? 'flex' : 'none');
    if (now === 'chat_settings') shellChatSettingsDraw();
    const userPane = document.getElementById('userPane');
    if (userPane) userPane.style.display = (now === 'user' ? 'flex' : 'none');
    if (now === 'user') shellUserPaneDraw();
    if (now === 'status') shellStatusFilter();
    if (now === 'team') shellTeamFilter();
    const title = now === 'art' ? SHELL_TEXT.art
      : now === 'appearance' ? SHELL_TEXT.appearance
      : now === 'chat_settings' ? (SHELL_TEXT.chat_settings || '')
      : now === 'user' ? (SHELL_TEXT.user || (typeof tr === 'function' ? tr('shelltext.user') : 'User'))
      : now === 'team' && shellState.teamOnly ? SHELL_TEXT.manage
      : now === 'team' ? (SHELL_TEXT[shellState.teamSection || 'characters'] || SHELL_TEXT.characters)
      : now === 'status' ? (SHELL_TEXT[shellState.statusOnly || 'accounts'] || SHELL_TEXT.accounts)
      : SHELL_TEXT[SHELL_PANES[now]];
    shellSet(bar.querySelector('.shell-pane-title'), title || '');
    if (now !== 'art') shellArtGone();
    shellSet(back, shellNarrow() ? '\u2039' : '\u2715');      // a phone goes back, a wide screen closes the pane
    if (now !== 'chat' && shellNarrow() && shellProfileIsOpen()) shellProfileClose();   // not the one waiting behind
    shellMarkPane();
  };
  if (typeof loadTeam === 'function') {
    const team = loadTeam;
    loadTeam = async function () { const out = await team.apply(this, arguments); shellTeamFilter(); return out; };
  }
  // The art manager closes itself when it hands a request to the talk (its "ask" button): the pane goes with it.
  if (typeof closeArtManager === 'function') {
    const closeArt = closeArtManager;
    closeArtManager = function () {
      closeArt.apply(this, arguments);
      if (currentTab !== 'art') return;
      shellState.paneFrom = '';
      shellProfileClose();
      switchTab('chat');
    };
  }
  // The picture used to open the tray (app.js onTrayKey). Caught on the way down, before that listener: the wrap
  // also holds the provider tray, so only the picture itself is taken.
  const pic = document.getElementById('brandAvatar'), picWrap = document.getElementById('brandAvatarWrap');
  const title = document.querySelector('header .brand-title');
  const toggle = () => { if (shellProfileIsOpen()) shellProfileClose(); else shellProfileOpen(); };
  if (pic && picWrap) {
    picWrap.addEventListener('click', (e) => { if (e.target === pic) { e.stopPropagation(); toggle(); } }, true);
    picWrap.addEventListener('keydown', (e) => {
      if (e.target === pic && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.stopPropagation(); toggle(); }
    }, true);
  }
  if (title) title.addEventListener('click', (e) => { if (!e.target.closest('button')) toggle(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { shellProfileClose(); shellSettingsClose(); } });
}
