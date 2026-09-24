// app-team.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
const teamListEl = document.getElementById('teamList');

async function loadTeam() {
  if (!teamListEl) return;
  let team, instr;
  try {
    [team, instr] = await Promise.all([api('/api/experts'), api('/api/instructions')]);
  } catch (e) {
    teamListEl.textContent = '팀 정보를 불러오지 못했어요 (소생 필요할 수 있음): ' + (e.message || e);
    return;
  }
  const files = {};
  (instr.items || []).forEach(x => { files[x.id] = x; });
  teamListEl.textContent = '';
  (team.experts || []).forEach(ex => teamListEl.appendChild(renderTeamCard(ex, team, files)));
  // TEAM_ROLES_v2: what a role is (its pack) and what everyone reads (the house memory), after the characters
  const shared = obsNode('div', 'status-item team-card');
  shared.appendChild(obsNode('div', 'status-item-head', '역할 팩 · 집 기억'));
  shared.appendChild(obsNode('div', 'status-hint', '역할은 캐릭터가 아니라 역할 팩(지침·스킬·도구 권한)이 정합니다. 누가 어떤 역할을 맡는지는 각 캐릭터의 [역할]에서 바꿉니다.'));
  (team.roles || []).forEach(r => {
    [['roles/' + r.role + '/role.md', '역할 팩 ' + r.title + (r.tools.length ? ' (권한: ' + r.tools.join(', ') + ')' : '')],
     ['roles/' + r.role + '/procedure.md', r.title + ' 절차']].forEach(([id, title]) => {
      if (files[id]) {
        const sub = renderInstruction(Object.assign({}, files[id], { title }), false);
        sub.classList.add('team-sub');
        shared.appendChild(sub);
      }
    });
  });
  if (files['MEMORY.md']) {
    const sub = renderInstruction(Object.assign({}, files['MEMORY.md'], { title: '집 기억 (모든 캐릭터가 읽음)' }), false);
    sub.classList.add('team-sub');
    shared.appendChild(sub);
  }
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
  def.title = ex.default ? '다른 캐릭터를 기본으로 정하면 바뀝니다' : '앱을 열면 이 캐릭터와 대화합니다';
  defLabel.append(def, document.createTextNode(' 기본 캐릭터 (앱을 열면 대화하는 상대)'));
  box.appendChild(defLabel);
  actions.textContent = '';
  const save = obsNode('button', 'art-btn art-btn-xs', '저장');
  save.type = 'button';
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await saveTeam(team, ex, (team.roles || []).map(r => r.role).filter(r => picked.has(r)), def.checked && !ex.default);
    } catch (e) {
      save.disabled = false;
      box.appendChild(obsNode('div', 'status-hint', '저장 실패: ' + (e.message || e)));
    }
  });
  const cancel = obsNode('button', 'art-btn art-btn-xs', '취소');
  cancel.type = 'button';
  cancel.addEventListener('click', () => loadTeam());
  actions.append(save, cancel);
}

function brainText(b) {
  return b.provider + ' / ' + (b.model || '기본 모델') + (b.timeout ? ' · ' + b.timeout + '초 제한' : '');
}

function renderTeamCard(ex, team, files) {
  const card = obsNode('div', 'status-item team-card');
  const head = obsNode('div', 'status-item-head');
  head.appendChild(obsNode('span', 'status-item-name', ex.name + (ex.title ? ' · ' + ex.title : '')));
  const chips = obsNode('span', 'team-role-chips');
  if (ex.default) chips.appendChild(obsNode('span', 'team-chip team-chip-default', '기본'));
  (ex.roles || []).forEach(r => chips.appendChild(obsNode('span', 'team-chip', roleTitle(team, r))));
  if (!(ex.roles || []).length) chips.appendChild(obsNode('span', 'team-chip team-chip-none', '역할 없음'));
  head.appendChild(chips);
  const actions = obsNode('div', 'status-item-actions');
  head.appendChild(actions);
  card.appendChild(head);
  const roleBox = obsNode('div', 'team-role-box');
  card.appendChild(roleBox);
  if (team.team_editable) {
    const rb = obsNode('button', 'art-btn art-btn-xs', '역할');
    rb.type = 'button';
    rb.addEventListener('click', () => editRoles(ex, team, roleBox, actions));
    actions.appendChild(rb);
  }
  const brains = obsNode('div', 'team-brains');
  const chain = ex.chain || [];
  if (!chain.length) brains.appendChild(obsNode('div', 'status-hint', '두뇌 목록 없음: 기본 설정(환경변수)으로 일합니다'));
  chain.forEach((b, i) => {
    const row = obsNode('div', 'team-brain');
    row.appendChild(obsNode('span', 'team-n', String(i + 1)));
    row.appendChild(obsNode('span', '', brainText(b)));
    brains.appendChild(row);
  });
  card.appendChild(brains);
  if (ex.editable) {
    const edit = obsNode('button', 'art-btn art-btn-xs', '두뇌');
    edit.type = 'button';
    edit.addEventListener('click', () => editBrains(ex, team, brains, actions));
    actions.appendChild(edit);
  }
  const subs = [['characters/' + ex.id + '/card.json', '캐릭터 카드'], ['characters/' + ex.id + '/memory.md', '기억'],
    ['characters/' + ex.id + '/private-memory.md', '사적 기억'], ['characters/' + ex.id + '/visual.md', '외형 락']];
  subs.forEach(([id, title]) => {
    if (files[id]) {
      const sub = renderInstruction(Object.assign({}, files[id], { title }), false);
      sub.classList.add('team-sub');
      card.appendChild(sub);
    } else if (title === '기억') {
      card.appendChild(obsNode('div', 'status-hint team-sub', '기억: 아직 없음 (맡은 작업에서 배운 점이 쌓입니다)'));
    }
  });
  return card;
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
      sel.addEventListener('change', () => { b.provider = sel.value; draw(); });
      const model = document.createElement('input');
      model.className = 'team-model';
      model.placeholder = '기본 모델';
      model.value = b.model || '';
      const listId = 'teamModels-' + ex.id + '-' + i;
      model.setAttribute('list', listId);
      const dl = document.createElement('datalist');
      dl.id = listId;
      ((team.models || {})[b.provider] || []).forEach(m => { const o = document.createElement('option'); o.value = m; dl.appendChild(o); });
      model.addEventListener('input', () => { b.model = model.value.trim(); });
      const to = document.createElement('input');
      to.className = 'team-timeout';
      to.type = 'number';
      to.min = '0';
      to.max = '3600';
      to.placeholder = '제한(초)';
      to.title = '이 두뇌를 기다릴 최대 시간(초). 비우면 기본값. 멈추는 모델을 빨리 포기하게 합니다.';
      to.value = b.timeout || '';
      to.addEventListener('input', () => { b.timeout = Number(to.value) || 0; });
      row.append(sel, model, dl, to);
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
      const add = obsNode('button', 'art-btn art-btn-xs', '+ 두뇌 추가');
      add.type = 'button';
      add.addEventListener('click', () => { rows.push({ provider: (team.providers || [])[0] || '', model: '' }); draw(); });
      brains.appendChild(add);
    }
  };
  draw();
  actions.textContent = '';
  const save = obsNode('button', 'art-btn art-btn-xs primary', '저장');
  save.type = 'button';
  const cancel = obsNode('button', 'art-btn art-btn-xs', '취소');
  cancel.type = 'button';
  actions.append(save, cancel);
  cancel.addEventListener('click', loadTeam);
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api('/api/experts/' + encodeURIComponent(ex.id) + '/brain', { method: 'PUT', body: JSON.stringify({ chain: rows }) });
      addActivity(ex.name + ' 두뇌 순서 저장됨 · 다음 작업부터 반영');
      loadTeam();
    } catch (e) {
      save.disabled = false;
      await alertModal('저장 실패: ' + (e.message || e));
    }
  });
}
