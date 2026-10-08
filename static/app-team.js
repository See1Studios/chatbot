// app-team.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
const teamListEl = document.getElementById('teamList');
const TEAM_TEXT = i18nTable('team.text');
const AUTO_TEXT = i18nTable('team.auto');   // evt/D auto reactions

async function loadTeam() {
  if (!teamListEl) return;
  let team, instr;
  try {
    [team, instr] = await Promise.all([api('/api/experts'), api('/api/instructions')]);
  } catch (e) {
    teamListEl.textContent = tr('team.load_failed', { error: e.message || e });
    return;
  }
  const files = {};
  (instr.items || []).forEach(x => { files[x.id] = x; });
  teamListEl.textContent = '';
  (team.experts || []).forEach(ex => teamListEl.appendChild(renderTeamCard(ex, team, files)));
  if (team.auto_react && team.auto_react.choices) teamListEl.appendChild(renderAutoReact(team.auto_react));
  // TEAM_ROLES_v2: what a role is (its pack)
  const shared = obsNode('div', 'status-item team-card');
  shared.setAttribute('data-team-section', 'roles');
  shared.appendChild(obsNode('div', 'status-item-head', tr('team.shared_head')));
  shared.appendChild(obsNode('div', 'status-hint', tr('team.shared_hint')));
  (team.roles || []).forEach(r => {
    // pew/R: ROLE.md / PROCEDURE.md, or the old lower-case names on a pack written before
    const pick = name => files['roles/' + r.role + '/' + name.toUpperCase()] || files['roles/' + r.role + '/' + name];
    [['role.md', tr('team.role_pack', { title: r.title }) + (r.tools.length ? tr('team.role_tools', { tools: r.tools.join(', ') }) : '')],
     ['procedure.md', tr('team.procedure', { title: r.title })]].forEach(([name, title]) => {
      const file = pick(name);
      if (file) {
        const sub = renderInstruction(Object.assign({}, file, { title }), false);
        sub.classList.add('team-sub');
        shared.appendChild(sub);
      }
    });
  });
  teamListEl.appendChild(shared);
}

function roleTitle(team, role) {
  const r = (team.roles || []).find(x => x.role === role);
  return r ? r.title : role;
}

// The roster is edited whole: this character's roles (and whether it is the default) replace its entry
async function saveTeam(team, ex, roles, makeDefault) {
  const members = {};
  (team.experts || []).forEach(e => { members[e.id] = e.id === ex.id ? roles : (e.roles || []); });
  const current = (team.experts || []).find(e => e.default);
  const payload = { default: makeDefault ? ex.id : (current ? current.id : ex.id), members };
  await api('/api/experts/team', { method: 'PUT', body: JSON.stringify(payload) });
  await loadTeam();
  if (typeof loadCharacters === 'function') await loadCharacters();
}

function editRoles(ex, team, box, actions) {
  box.textContent = '';
  const picked = new Set(ex.roles || []);
  (team.roles || []).forEach(r => {
    const label = obsNode('label', 'team-role-pick');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = picked.has(r.role);
    cb.addEventListener('change', () => { cb.checked ? picked.add(r.role) : picked.delete(r.role); });
    label.append(cb, document.createTextNode(' ' + r.title + (r.tools.length ? ' (' + r.tools.join(', ') + ')' : '')));
    box.appendChild(label);
  });
  const defLabel = obsNode('label', 'team-role-pick');
  const def = document.createElement('input');
  def.type = 'checkbox';
  def.checked = Boolean(ex.default);
  def.disabled = Boolean(ex.default);
  def.title = ex.default ? tr('team.default_change_hint') : tr('team.default_hint');
  defLabel.append(def, document.createTextNode(' ' + tr('team.default_label')));
  box.appendChild(defLabel);
  actions.textContent = '';
  const save = obsNode('button', 'art-btn art-btn-xs', tr('common.save'));
  save.type = 'button';
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await saveTeam(team, ex, (team.roles || []).map(r => r.role).filter(r => picked.has(r)), def.checked && !ex.default);
    } catch (e) {
      save.disabled = false;
      box.appendChild(obsNode('div', 'status-hint', tr('common.save_failed', { error: e.message || e })));
    }
  });
  const cancel = obsNode('button', 'art-btn art-btn-xs', tr('common.cancel'));
  cancel.type = 'button';
  cancel.addEventListener('click', () => loadTeam());
  actions.append(save, cancel);
}

function brainText(b) {
  return b.provider + ' / ' + (b.model || tr('team.default_model')) + (b.timeout ? tr('team.timeout', { n: b.timeout }) : '');
}

// The auto-reaction settings (evt/D): which events make a character speak first, and the limits. Off by default.
function autoReactBody(cfg, picked, perHour, quietFrom, quietTo) {
  return { auto: (cfg.choices || []).filter(t => picked[t]), per_hour: Number(perHour) || 0,
           quiet: [Number(quietFrom) || 0, Number(quietTo) || 0] };
}

function renderAutoReact(cfg) {
  const card = obsNode('div', 'status-item team-card');
  card.setAttribute('data-team-section', 'auto_react');
  card.appendChild(obsNode('div', 'status-item-head', AUTO_TEXT.head));
  card.appendChild(obsNode('div', 'status-hint', AUTO_TEXT.hint));
  const picked = {};
  (cfg.choices || []).forEach(t => {
    picked[t] = (cfg.auto || []).includes(t);
    const row = obsNode('label', 'team-brain');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = picked[t];
    box.addEventListener('change', () => { picked[t] = box.checked; });
    row.append(box, obsNode('span', '', AUTO_TEXT[t] || t));
    card.appendChild(row);
  });
  const num = (value, min, max) => { const n = document.createElement('input'); n.type = 'number'; n.min = String(min); n.max = String(max); n.value = String(value); n.className = 'team-timeout'; return n; };
  const perHour = num(cfg.per_hour, 0, 20), from = num((cfg.quiet || [0, 8])[0], 0, 24), to = num((cfg.quiet || [0, 8])[1], 0, 24);
  const limits = obsNode('div', 'team-brain');
  limits.append(obsNode('span', '', AUTO_TEXT.perHour), perHour, obsNode('span', '', AUTO_TEXT.quiet), from, obsNode('span', '', '–'), to);
  card.appendChild(limits);
  const save = obsNode('button', 'art-btn art-btn-xs primary', AUTO_TEXT.save);
  save.type = 'button';
  save.addEventListener('click', async () => {
    try {
      await api('/api/experts/auto-react', { method: 'PUT', body: JSON.stringify(autoReactBody(cfg, picked, perHour.value, from.value, to.value)) });
      addActivity(AUTO_TEXT.saved);
    } catch (e) {
      await alertModal(AUTO_TEXT.failed + (e.message || e));
    }
  });
  card.appendChild(save);
  return card;
}

function renderTeamCard(ex, team, files) {
  const card = obsNode('div', 'status-item team-card');
  card.setAttribute('data-character-id', ex.id || '');   // the shell shows one character's card from its profile (app-shell.js)
  card.setAttribute('data-team-section', 'characters');
  const head = obsNode('div', 'status-item-head');
  head.appendChild(obsNode('span', 'status-item-name', ex.name + (ex.title ? ' · ' + ex.title : '')));
  const chips = obsNode('span', 'team-role-chips');
  if (ex.default) chips.appendChild(obsNode('span', 'team-chip team-chip-default', tr('team.chip_default')));
  (ex.roles || []).forEach(r => chips.appendChild(obsNode('span', 'team-chip', roleTitle(team, r))));
  if (!(ex.roles || []).length) chips.appendChild(obsNode('span', 'team-chip team-chip-none', tr('team.no_roles')));
  head.appendChild(chips);
  const actions = obsNode('div', 'status-item-actions');
  head.appendChild(actions);
  card.appendChild(head);
  const roleBox = obsNode('div', 'team-role-box');
  card.appendChild(roleBox);
  if (team.team_editable) {
    const rb = obsNode('button', 'art-btn art-btn-xs', tr('team.roles_button'));
    rb.type = 'button';
    rb.addEventListener('click', () => editRoles(ex, team, roleBox, actions));
    actions.appendChild(rb);
  }
  const brains = obsNode('div', 'team-brains');
  const chain = ex.chain || [];
  if (!chain.length) brains.appendChild(obsNode('div', 'status-hint', tr('team.no_brains')));
  chain.forEach((b, i) => {
    const row = obsNode('div', 'team-brain');
    row.appendChild(obsNode('span', 'team-n', String(i + 1)));
    row.appendChild(obsNode('span', '', brainText(b)));
    brains.appendChild(row);
  });
  const spare = teamSpareSlot(chain.length);
  if (spare) brains.appendChild(spare);
  card.appendChild(brains);
  if (ex.editable) {
    const edit = obsNode('button', 'art-btn art-btn-xs', tr('team.brains_button'));
    edit.type = 'button';
    edit.addEventListener('click', () => editBrains(ex, team, brains, actions));
    actions.appendChild(edit);
  }
  // [file, catalog key of its title]; the branch below keys on the key, never on the shown word
  const subs = [['characters/' + ex.id + '/card.json', 'team.sub.card'], ['characters/' + ex.id + '/memory.md', 'team.sub.memory'],
    ['characters/' + ex.id + '/private-memory.md', 'team.sub.private_memory'], ['characters/' + ex.id + '/visual.md', 'team.sub.visual']];
  subs.forEach(([id, key]) => {
    const title = tr(key);
    if (files[id]) {
      const isCard = id.endsWith('/card.json') || id === 'card.json';
      const sub = isCard
        ? renderCardEditor(Object.assign({}, files[id], { title }), false)
        : renderInstruction(Object.assign({}, files[id], { title }), false);
      sub.classList.add('team-sub');
      card.appendChild(sub);
    } else if (key === 'team.sub.memory') {
      card.appendChild(obsNode('div', 'status-hint team-sub', tr('team.memory_empty')));
    }
  });
  return card;
}

// A lone brain has no fallback: show the empty next slot, so the operator sees one can be added (the brains editor).
// The runner moves to the next brain when one does not answer (quota, capacity, a stalled stream).
function teamSpareSlot(n) {
  if (n !== 1) return null;
  const row = obsNode('div', 'team-brain team-brain-spare');
  row.appendChild(obsNode('span', 'team-n', '2'));
  row.appendChild(obsNode('span', '', TEAM_TEXT.spare));
  return row;
}

function editBrains(ex, team, brains, actions) {
  const rows = (ex.chain && ex.chain.length ? ex.chain : [{ provider: (team.providers || [])[0] || '', model: '' }])
    .map(b => Object.assign({}, b));
  const draw = () => {
    brains.textContent = '';
    rows.forEach((b, i) => {
      const row = obsNode('div', 'team-brain');
      row.appendChild(obsNode('span', 'team-n', String(i + 1)));
      const sel = document.createElement('select');
      (team.providers || []).forEach(p => { const o = obsNode('option', '', p); o.value = p; if (p === b.provider) o.selected = true; sel.appendChild(o); });
      sel.addEventListener('change', () => { b.provider = sel.value; b.model = ''; draw(); });
      // a <select>, not a datalist: mobile browsers hide datalist suggestions that do not match the typed value
      const known = (team.models || {})[b.provider] || [];
      const pick = document.createElement('select');
      pick.className = 'team-model';
      pick.style.cssText = 'flex:1 1 9rem;min-width:7rem';
      [['', tr('team.default_model')]].concat(known.map(m => [m, m]), [['\u0000custom', tr('team.custom_model')]]).forEach(([v, label]) => {
        const o = obsNode('option', '', label); o.value = v; pick.appendChild(o);
      });
      const custom = b.model && !known.includes(b.model);
      pick.value = custom ? '\u0000custom' : (b.model || '');
      const typed = document.createElement('input');
      typed.className = 'team-model';
      typed.placeholder = tr('team.model_name');
      typed.value = custom ? b.model : '';
      typed.hidden = !custom;
      typed.addEventListener('input', () => { b.model = typed.value.trim(); });
      pick.addEventListener('change', () => {
        const isCustom = pick.value === '\u0000custom';
        typed.hidden = !isCustom;
        b.model = isCustom ? typed.value.trim() : pick.value;
        if (isCustom && typed.focus) typed.focus();
      });
      const to = document.createElement('input');
      to.className = 'team-timeout';
      to.type = 'number';
      to.min = '0';
      to.max = '3600';
      to.placeholder = tr('team.timeout_placeholder');
      to.title = tr('team.timeout_hint');
      to.value = b.timeout || '';
      to.addEventListener('input', () => { b.timeout = Number(to.value) || 0; });
      row.append(sel, pick, typed, to);
      [['↑', () => { if (i > 0) { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; draw(); } }],
       ['↓', () => { if (i < rows.length - 1) { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; draw(); } }],
       ['✕', () => { if (rows.length > 1) { rows.splice(i, 1); draw(); } }]].forEach(([label, fn]) => {
        const btn = obsNode('button', 'art-btn art-btn-xs', label);
        btn.type = 'button';
        btn.addEventListener('click', fn);
        row.appendChild(btn);
      });
      brains.appendChild(row);
    });
    if (rows.length < 6) {
      const add = obsNode('button', 'art-btn art-btn-xs', tr('team.add_brain'));
      add.type = 'button';
      add.addEventListener('click', () => { rows.push({ provider: (team.providers || [])[0] || '', model: '' }); draw(); });
      brains.appendChild(add);
    }
  };
  draw();
  actions.textContent = '';
  const save = obsNode('button', 'art-btn art-btn-xs primary', tr('common.save'));
  save.type = 'button';
  const cancel = obsNode('button', 'art-btn art-btn-xs', tr('common.cancel'));
  cancel.type = 'button';
  actions.append(save, cancel);
  cancel.addEventListener('click', loadTeam);
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api('/api/experts/' + encodeURIComponent(ex.id) + '/brain', { method: 'PUT', body: JSON.stringify({ chain: rows }) });
      addActivity(tr('team.brains_saved', { name: ex.name }));
      loadTeam();
    } catch (e) {
      save.disabled = false;
      await alertModal(tr('common.save_failed', { error: e.message || e }));
    }
  });
}

function renderCardEditor(x, open) {
  const item = obsNode('details', 'status-item instr-item card-editor-item');
  if (open) item.open = true;

  const head = obsNode('summary', 'status-item-head');
  head.appendChild(obsNode('span', 'status-item-name', x.title));
  head.appendChild(obsNode('span', 'instr-badge ' + (x.editable ? 'rw' : 'ro'), x.editable ? tr('status.instr.editable') : tr('status.instr.readonly')));
  const sizeSpan = obsNode('span', 'status-item-meta', (x.size || 0) + ' B');
  head.appendChild(sizeSpan);
  item.appendChild(head);

  const meta = [x.path || tr('status.instr.generated'), x.mtime ? new Date(x.mtime * 1000).toLocaleString(I18N_LANG) : ''].filter(Boolean).join(' · ');
  const metaRow = obsNode('div', 'status-item-head');
  metaRow.appendChild(obsNode('span', 'status-item-meta', meta));
  const headActions = obsNode('div', 'status-item-actions');
  metaRow.appendChild(headActions);
  item.appendChild(metaRow);

  if (!x.editable && x.reason) item.appendChild(obsNode('div', 'instr-reason', x.reason));

  const editorWrap = obsNode('div', 'card-editor');

  const tabRow = obsNode('div', 'card-editor-tabs');
  const btnProps = obsNode('button', 'art-btn art-btn-xs card-tab-btn', tr('card.edit_fields'));
  btnProps.type = 'button';
  const btnRaw = obsNode('button', 'art-btn art-btn-xs card-tab-btn', tr('card.edit_raw'));
  btnRaw.type = 'button';
  tabRow.append(btnProps, btnRaw);
  editorWrap.appendChild(tabRow);

  const alertBox = obsNode('div', 'card-editor-alert');
  alertBox.hidden = true;
  editorWrap.appendChild(alertBox);

  const formPane = obsNode('div', 'card-editor-form');
  const rawPane = obsNode('div', 'card-raw-pane');

  const row1 = obsNode('div', 'card-field-row');

  const fName = obsNode('div', 'card-field');
  fName.appendChild(obsNode('label', '', tr('card.name')));
  const inputName = document.createElement('input');
  inputName.type = 'text';
  inputName.className = 'card-input';
  inputName.placeholder = tr('card.name_placeholder');
  inputName.disabled = !x.editable;
  fName.appendChild(inputName);

  const fUserTitle = obsNode('div', 'card-field');
  fUserTitle.appendChild(obsNode('label', '', tr('card.user_title')));
  const inputUserTitle = document.createElement('input');
  inputUserTitle.type = 'text';
  inputUserTitle.className = 'card-input';
  inputUserTitle.placeholder = tr('card.user_title_placeholder');
  inputUserTitle.disabled = !x.editable;
  fUserTitle.appendChild(inputUserTitle);

  const fVoice = obsNode('div', 'card-field');
  fVoice.appendChild(obsNode('label', '', tr('card.voice')));
  const inputVoice = document.createElement('input');
  inputVoice.type = 'text';
  inputVoice.className = 'card-input';
  inputVoice.placeholder = tr('card.voice_placeholder');
  inputVoice.disabled = !x.editable;
  fVoice.appendChild(inputVoice);

  row1.append(fName, fUserTitle, fVoice);
  formPane.appendChild(row1);

  const fPers = obsNode('div', 'card-field full');
  fPers.appendChild(obsNode('label', '', tr('card.personality')));
  const inputPers = document.createElement('textarea');
  inputPers.className = 'card-textarea';
  inputPers.rows = 3;
  inputPers.placeholder = tr('card.personality_placeholder');
  inputPers.disabled = !x.editable;
  fPers.appendChild(inputPers);
  formPane.appendChild(fPers);

  const fDesc = obsNode('div', 'card-field full');
  fDesc.appendChild(obsNode('label', '', tr('card.description')));
  const inputDesc = document.createElement('textarea');
  inputDesc.className = 'card-textarea';
  inputDesc.rows = 4;
  inputDesc.placeholder = tr('card.description_placeholder');
  inputDesc.disabled = !x.editable;
  fDesc.appendChild(inputDesc);
  formPane.appendChild(fDesc);

  const fSys = obsNode('div', 'card-field full');
  fSys.appendChild(obsNode('label', '', tr('card.rules')));
  const inputSys = document.createElement('textarea');
  inputSys.className = 'card-textarea';
  inputSys.rows = 4;
  inputSys.placeholder = tr('card.rules_placeholder');
  inputSys.disabled = !x.editable;
  fSys.appendChild(inputSys);
  formPane.appendChild(fSys);

  const rawTextarea = document.createElement('textarea');
  rawTextarea.className = 'status-edit-area';
  rawTextarea.disabled = !x.editable;
  rawPane.appendChild(rawTextarea);

  editorWrap.appendChild(formPane);
  editorWrap.appendChild(rawPane);

  let parsedCard = null;

  function populateFields(card) {
    if (!card || !card.data) return;
    const d = card.data;
    const disp = (d.extensions && d.extensions.chatbot && d.extensions.chatbot.display) || {};
    inputName.value = d.name || '';
    inputUserTitle.value = disp.user_title || '';
    inputVoice.value = disp.voice || '';
    inputPers.value = d.personality || '';
    inputDesc.value = d.description || '';
    inputSys.value = d.system_prompt || '';
  }

  function updateParsedCardFromFields() {
    if (!parsedCard || typeof parsedCard !== 'object') {
      parsedCard = { spec: 'chara_card_v2', spec_version: '2.0', data: {} };
    }
    if (!parsedCard.data || typeof parsedCard.data !== 'object') {
      parsedCard.data = {};
    }
    const d = parsedCard.data;
    d.name = inputName.value.trim();
    if (!d.extensions || typeof d.extensions !== 'object') d.extensions = {};
    if (!d.extensions.chatbot || typeof d.extensions.chatbot !== 'object') d.extensions.chatbot = {};
    if (!d.extensions.chatbot.display || typeof d.extensions.chatbot.display !== 'object') d.extensions.chatbot.display = {};
    d.extensions.chatbot.display.user_title = inputUserTitle.value.trim();
    d.extensions.chatbot.display.voice = inputVoice.value.trim();
    d.personality = inputPers.value;
    d.description = inputDesc.value;
    d.system_prompt = inputSys.value;
  }

  function initFromContent(content) {
    let ok = false;
    try {
      const obj = JSON.parse(content || '{}');
      if (obj && typeof obj === 'object' && obj.spec === 'chara_card_v2' && obj.data && typeof obj.data === 'object') {
        parsedCard = obj;
        ok = true;
      }
    } catch (_) {
      ok = false;
    }
    rawTextarea.value = content || '';
    if (ok) {
      populateFields(parsedCard);
      formPane.hidden = false;
      rawPane.hidden = true;
      btnProps.classList.add('active');
      btnRaw.classList.remove('active');
      alertBox.hidden = true;
      alertBox.textContent = '';
    } else {
      parsedCard = null;
      formPane.hidden = true;
      rawPane.hidden = false;
      btnRaw.classList.add('active');
      btnProps.classList.remove('active');
      alertBox.hidden = false;
      alertBox.textContent = tr('card.not_v2');
    }
  }

  initFromContent(x.content || '');

  btnProps.addEventListener('click', () => {
    if (!rawPane.hidden) {
      try {
        const obj = JSON.parse(rawTextarea.value);
        if (!obj || typeof obj !== 'object' || obj.spec !== 'chara_card_v2' || !obj.data || typeof obj.data !== 'object') {
          throw new Error(tr('card.need_v2'));
        }
        parsedCard = obj;
        populateFields(parsedCard);
        alertBox.hidden = true;
        alertBox.textContent = '';
      } catch (err) {
        alertBox.hidden = false;
        alertBox.textContent = tr('card.parse_error', { error: err.message || err });
        if (typeof alertModal === 'function') {
          alertModal(tr('card.cannot_switch', { error: err.message || err }));
        }
        return;
      }
      rawPane.hidden = true;
      formPane.hidden = false;
      btnProps.classList.add('active');
      btnRaw.classList.remove('active');
    }
  });

  btnRaw.addEventListener('click', () => {
    if (!formPane.hidden) {
      updateParsedCardFromFields();
      rawTextarea.value = JSON.stringify(parsedCard, null, 2);
      formPane.hidden = true;
      rawPane.hidden = false;
      btnRaw.classList.add('active');
      btnProps.classList.remove('active');
    }
  });

  const saveButtons = [];

  function setSaving(saving) {
    saveButtons.forEach(btn => {
      btn.disabled = saving;
      btn.textContent = saving ? tr('common.saving') : tr('common.save');
    });
  }

  async function doSave() {
    let contentToSave;
    if (!formPane.hidden) {
      updateParsedCardFromFields();
      contentToSave = JSON.stringify(parsedCard, null, 2);
    } else {
      try {
        const obj = JSON.parse(rawTextarea.value);
        if (!obj || typeof obj !== 'object' || obj.spec !== 'chara_card_v2' || !obj.data || typeof obj.data !== 'object') {
          throw new Error(tr('card.need_v2'));
        }
        parsedCard = obj;
        populateFields(parsedCard);
        contentToSave = rawTextarea.value;
      } catch (err) {
        if (typeof alertModal === 'function') {
          await alertModal(tr('card.cannot_save', { error: err.message || err }));
        }
        return;
      }
    }

    setSaving(true);
    try {
      const res = await api('/api/instructions/' + encodeURIComponent(x.id), {
        method: 'PUT',
        body: JSON.stringify({ content: contentToSave }),
      });
      x.content = contentToSave;
      if (res && res.bytes) {
        x.size = res.bytes;
        sizeSpan.textContent = res.bytes + ' B';
      }
      if (typeof addActivity === 'function') {
        addActivity(tr('status.instr.saved', { title: x.title, when: x.layer === 'always' ? tr('status.instr.next_turn') : tr('status.instr.next_read') }));
      }
      rawTextarea.value = contentToSave;
      if (parsedCard) populateFields(parsedCard);
      if (typeof loadInstructions === 'function') loadInstructions();
      if (typeof loadTeam === 'function') await loadTeam();
    } catch (e) {
      setSaving(false);
      if (typeof alertModal === 'function') {
        await alertModal(tr('common.save_failed', { error: e.message || e }));
      }
    }
  }

  function doCancel() {
    if (typeof loadTeam === 'function') {
      loadTeam();
    } else if (typeof loadInstructions === 'function') {
      loadInstructions();
    } else {
      initFromContent(x.content || '');
    }
  }

  if (x.editable) {
    const headSave = obsNode('button', 'art-btn art-btn-xs primary', tr('common.save'));
    headSave.type = 'button';
    headSave.addEventListener('click', doSave);
    const headCancel = obsNode('button', 'art-btn art-btn-xs', tr('common.cancel'));
    headCancel.type = 'button';
    headCancel.addEventListener('click', doCancel);
    saveButtons.push(headSave);
    headActions.append(headSave, headCancel);

    const bottomActions = obsNode('div', 'card-editor-actions');
    const bottomSave = obsNode('button', 'art-btn art-btn-xs primary', tr('common.save'));
    bottomSave.type = 'button';
    bottomSave.addEventListener('click', doSave);
    const bottomCancel = obsNode('button', 'art-btn art-btn-xs', tr('common.cancel'));
    bottomCancel.type = 'button';
    bottomCancel.addEventListener('click', doCancel);
    saveButtons.push(bottomSave);
    bottomActions.append(bottomSave, bottomCancel);
    editorWrap.appendChild(bottomActions);
  }

  item.appendChild(editorWrap);
  return item;
}

if (typeof renderInstruction === 'function') {
  const _origRenderInstruction = renderInstruction;
  renderInstruction = function(x, open) {
    const isCard = x && ((x.id && (x.id.endsWith('/card.json') || x.id === 'card.json')) ||
                         (x.path && x.path.endsWith('/card.json')));
    if (isCard) {
      return renderCardEditor(x, open);
    }
    return _origRenderInstruction(x, open);
  };
}
