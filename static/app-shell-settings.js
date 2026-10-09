// Profile drawer: a character's settings drawn from the server's list (character-settings cs/C). GET
// /api/characters/<id>/settings gives every setting with its tab, type, label and value; this draws the ones of a tab
// and sends back only what changed (PATCH) -- the server merges it into its own file and keeps the previous version.
// The page never writes a whole file. A new setting on the server shows here with no change to this file. Brains
// keep their own picker (shellBrainSection) and the face crop its editor, so they are not drawn here.

const SETTINGS_SKIP = { brain: true, focal: true };

async function shellSettingsPatch(cid, changes) {
  return api('/api/characters/' + encodeURIComponent(cid) + '/settings', { method: 'PATCH', body: JSON.stringify(changes) });
}

function shellSettingsText(f) {   // a value as read text
  const v = f.value;
  if (f.type === 'list' || f.type === 'roles') return (v || []).join(f.type === 'list' ? '\n' : ', ');
  if (f.type === 'bool') return tr(v ? 'common.on' : 'common.off');
  if (f.type === 'select') return tr('charset.opt.' + f.key + '.' + v);
  return String(v === null || v === undefined ? '' : v);
}

function shellSettingsInput(f) {   // {wrap, read()} -- the field's editor by type
  const wrap = shellEl('div', 'shell-field-wrap');
  wrap.appendChild(shellEl('label', 'shell-field-label', tr(f.label.key, f.label.vars || {})));
  let read;
  if (f.type === 'bool') {
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = Boolean(f.value);
    wrap.appendChild(box);
    read = () => box.checked;
  } else if (f.type === 'select') {
    const sel = document.createElement('select');
    sel.className = 'shell-field-input';
    (f.options || []).forEach(o => {
      const opt = document.createElement('option');
      opt.value = o;
      opt.textContent = tr('charset.opt.' + f.key + '.' + o);
      opt.selected = o === f.value;
      sel.appendChild(opt);
    });
    wrap.appendChild(sel);
    read = () => sel.value;
  } else if (f.type === 'roles') {
    const have = new Set(f.value || []);
    const boxes = (f.options || []).map(r => {
      const lab = shellEl('label', 'shell-field-check');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = have.has(r);
      box.value = r;
      lab.append(box, document.createTextNode(' ' + r));
      wrap.appendChild(lab);
      return box;
    });
    read = () => boxes.filter(b => b.checked).map(b => b.value);
  } else {
    const long = f.type === 'longtext' || f.type === 'list';
    const input = document.createElement(long ? 'textarea' : 'input');
    input.className = long ? 'shell-field-textarea' : 'shell-field-input';
    if (long) input.rows = f.type === 'list' ? 3 : 5;
    input.value = shellSettingsText(f);
    if (f.type === 'list') input.placeholder = tr('profile.settings.one_per_line');
    wrap.appendChild(input);
    read = () => f.type === 'list' ? input.value.split('\n').map(s => s.trim()).filter(Boolean) : input.value;
  }
  return { wrap, read };
}

function shellSettingsWhen(v) {   // "20261009220512" (or "...-1") -> "10-09 22:05:12"
  const m = /^\d{4}(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)/.exec(String(v || ''));
  return m ? m[1] + '-' + m[2] + ' ' + m[3] + ':' + m[4] + ':' + m[5] : String(v || '');
}

// cs/D: the setting's file as it was before each change; a version is restored with a second tap. A restore brings
// the whole file back (every setting kept in it), and the file as it is now is kept first, so it can be undone too.
async function shellSettingsVersions(row, f, c, onRestored) {
  const old = row.querySelector && row.querySelector('.shell-settings-versions');
  if (old) { old.remove(); return; }
  const box = shellEl('div', 'shell-settings-versions');
  row.appendChild(box);
  let vs = [];
  try {
    vs = (await api('/api/characters/' + encodeURIComponent(c.id) + '/settings/versions/' + encodeURIComponent(f.key))).versions || [];
  } catch (e) {
    box.appendChild(shellEl('div', 'status-hint', tr('profile.settings.failed', { error: e.message || e })));
    return;
  }
  if (!vs.length) {
    box.appendChild(shellEl('div', 'status-hint', tr('profile.settings.no_versions')));
    return;
  }
  box.appendChild(shellEl('div', 'status-hint', tr('profile.settings.restore_scope', { file: f.file || '' })));
  vs.forEach(v => {
    const b = shellEl('button', 'art-btn art-btn-xs', shellSettingsWhen(v.version));
    b.type = 'button';
    b.addEventListener('click', async () => {
      if (b.dataset.armed !== '1') {   // first tap: say what happens; second tap: do it
        b.dataset.armed = '1';
        b.textContent = tr('profile.settings.restore_confirm', { when: shellSettingsWhen(v.version) });
        return;
      }
      b.disabled = true;
      try {
        await api('/api/characters/' + encodeURIComponent(c.id) + '/settings/restore',
          { method: 'POST', body: JSON.stringify({ key: f.key, version: v.version }) });
        if (typeof profileToast === 'function') profileToast(tr('profile.settings.restored'));
        if (typeof onRestored === 'function') await onRestored();
      } catch (e) {
        b.disabled = false;
        box.appendChild(shellEl('div', 'status-hint', tr('profile.settings.failed', { error: e.message || e })));
      }
    });
    box.appendChild(b);
  });
}

function shellSettingsRow(f, c, onRestored) {   // the read view; a sensitive one stays folded until asked
  const row = shellEl('div', 'shell-info-row' + (f.type === 'longtext' || f.type === 'list' ? ' multiline' : ''));
  row.appendChild(shellEl('span', 'shell-info-label', tr(f.label.key, f.label.vars || {})));
  if (f.editable && c) {
    const hist = shellEl('button', 'art-btn art-btn-xs shell-settings-history', tr('profile.settings.history'));
    hist.type = 'button';
    hist.addEventListener('click', () => shellSettingsVersions(row, f, c, onRestored));
    row.appendChild(hist);
  }
  const text = shellSettingsText(f);
  const val = shellEl('span', 'shell-info-val', text || tr('profile.settings.empty'));
  if (f.sensitive && text) {
    val.hidden = true;
    const show = shellEl('button', 'art-btn art-btn-xs', tr('profile.settings.show'));
    show.type = 'button';
    show.addEventListener('click', () => { val.hidden = false; show.remove(); });
    row.appendChild(show);
  }
  row.appendChild(val);
  return row;
}

// The section of one tab ('character' | 'relationship' | 'settings'), filled when the list arrives.
function shellSettingsSection(c, tab, title, onSaved) {
  const sec = shellSection(title);
  sec.dataset.settingsTab = tab;
  const body = shellEl('div', 'shell-field-list');
  body.appendChild(shellEl('div', 'status-hint', tr('common.loading')));
  sec.appendChild(body);
  shellSettingsFill(sec, body, c, tab, onSaved, false);
  return sec;
}

async function shellSettingsFill(sec, body, c, tab, onSaved, editing) {
  let fields;
  try {
    fields = ((await api('/api/characters/' + encodeURIComponent(c.id) + '/settings')).fields || []).filter(f => f.tab === tab && !SETTINGS_SKIP[f.type]);
  } catch (e) {
    body.textContent = '';
    body.appendChild(shellEl('div', 'status-hint', tr('profile.settings.failed', { error: e.message || e })));
    return;
  }
  if (!sec.isConnected && sec.parentNode) return;
  body.textContent = '';
  const head = shellEl('div', 'shell-inline-head');
  const toggle = shellEl('button', 'art-btn art-btn-xs' + (editing ? '' : ' primary'), tr(editing ? 'common.cancel' : 'common.edit'));
  toggle.type = 'button';
  toggle.addEventListener('click', () => shellSettingsFill(sec, body, c, tab, onSaved, !editing));
  head.appendChild(toggle);
  body.appendChild(head);
  if (!editing) {
    const restored = async () => {
      if (typeof onSaved === 'function') await onSaved([]);   // the card may have changed: the hero redraws
      shellSettingsFill(sec, body, c, tab, onSaved, false);
    };
    fields.forEach(f => body.appendChild(shellSettingsRow(f, c, restored)));
    return;
  }
  const form = shellEl('div', 'shell-edit-form');
  const editors = fields.filter(f => f.editable).map(f => ({ f, ed: shellSettingsInput(f) }));
  editors.forEach(x => form.appendChild(x.ed.wrap));
  const note = shellEl('div', 'status-hint');
  const save = shellEl('button', 'art-btn art-btn-sm primary', tr('common.save'));
  save.type = 'button';
  save.addEventListener('click', async () => {
    const changes = {};
    editors.forEach(({ f, ed }) => {
      const v = ed.read();
      if (JSON.stringify(v) !== JSON.stringify(f.value === undefined ? null : f.value)) changes[f.key] = v;
    });
    if (!Object.keys(changes).length) return shellSettingsFill(sec, body, c, tab, onSaved, false);
    save.disabled = true;
    save.textContent = tr('common.saving');
    try {
      const res = await shellSettingsPatch(c.id, changes);
      const errs = Object.keys((res && res.errors) || {});
      if (errs.length) {
        note.textContent = tr('profile.settings.refused', { keys: errs.map(k => tr('charset.' + k)).join(', ') });
        save.disabled = false;
        save.textContent = tr('common.save');
        return;
      }
      if (typeof profileToast === 'function') profileToast(tr('profile.settings.saved'));
      if (typeof onSaved === 'function') await onSaved((res && res.changed) || []);
      shellSettingsFill(sec, body, c, tab, onSaved, false);
    } catch (e) {
      note.textContent = tr('profile.settings.failed', { error: e.message || e });
      save.disabled = false;
      save.textContent = tr('common.save');
    }
  });
  const actions = shellEl('div', 'shell-edit-actions');
  actions.appendChild(save);
  form.append(actions, note);
  body.appendChild(form);
}
