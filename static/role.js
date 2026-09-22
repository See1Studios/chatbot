/* Role Studio SPA — Phase 1 */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let roles = [];
let activeSlug = null;
let editing = {};   // draft of the currently shown card

// ── DOM refs ───────────────────────────────────────────────────────────────
const charListEl     = document.getElementById('charList');
const emptyStateEl   = document.getElementById('emptyState');
const detailContentEl= document.getElementById('detailContent');
const detailActionsEl= document.getElementById('detailActions');
const addBtnEl       = document.getElementById('addBtn');
const saveBtnEl      = document.getElementById('saveBtn');
const deleteBtnEl    = document.getElementById('deleteBtn');
const openChatBtnEl  = document.getElementById('openChatBtn');
const toastEl        = document.getElementById('toast');

// ── Util ───────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let toastTimer;
function toast(msg, ms = 2200) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
}

const BASE_PATH = (() => {
  const p = window.location.pathname;
  const dir = p.replace(/\/[^\/]*\.[^\/]+$/, '');
  return dir.replace(/\/+$/, '') || '';
})();

async function api(path, opts = {}) {
  const url = path.startsWith('/') ? BASE_PATH + path : path;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return res.json();
}

// ── Load list ──────────────────────────────────────────────────────────────
async function loadRoles() {
  charListEl.innerHTML = '<div class="rs-empty" style="height:80px;font-size:0.8rem">불러오는 중…</div>';
  try {
    const data = await api('/api/roles');
    roles = (data.roles || []);
    renderList();
    if (activeSlug) {
      const still = roles.find(r => r.slug === activeSlug);
      if (still) selectRole(still.slug);
    }
  } catch (e) {
    charListEl.innerHTML = '<div class="rs-empty" style="height:80px;font-size:0.8rem;color:#f87171">로드 실패냥 ฅ</div>';
  }
}

// ── Render list ────────────────────────────────────────────────────────────
function renderList() {
  if (!roles.length) {
    charListEl.innerHTML = '<div class="rs-empty" style="height:100px;font-size:0.8rem">캐릭터가 없냥. 새로 만들어보자냥! ✦</div>';
    return;
  }
  charListEl.innerHTML = roles.map(r => `
    <div class="rs-char-item${r.slug === activeSlug ? ' active' : ''}" data-slug="${esc(r.slug)}">
      <div class="rs-avatar">${r.has_image
        ? `<img src="/api/roles/${esc(r.slug)}/image?t=${Date.now()}" alt="${esc(r.name)}" loading="lazy">`
        : avatarEmoji(r.slug)}</div>
      <div class="rs-char-meta">
        <div class="rs-char-name">${esc(r.name)}</div>
        <div class="rs-char-desc">${esc(r.description)}</div>
      </div>
    </div>
  `).join('');
  charListEl.querySelectorAll('.rs-char-item').forEach(el => {
    el.addEventListener('click', () => selectRole(el.dataset.slug));
  });
}

function avatarEmoji(slug) {
  const map = { yerin: '🌸', siwoo: '☕', iris: '⚡' };
  return map[slug] || '🎭';
}

// ── Select & show detail ───────────────────────────────────────────────────
async function selectRole(slug) {
  activeSlug = slug;
  renderList();   // re-render list to highlight
  emptyStateEl.style.display = 'none';
  detailContentEl.style.display = 'none';
  detailActionsEl.style.display = 'none';
  detailContentEl.innerHTML = '<div class="rs-empty" style="height:120px;font-size:0.8rem">불러오는 중…</div>';
  detailContentEl.style.display = '';

  try {
    const data = await api(`/api/roles/${encodeURIComponent(slug)}`);
    if (!data.ok) { toast('캐릭터 로드 실패냥'); return; }
    const r = data.role;
    editing = JSON.parse(JSON.stringify(r));   // deep copy as draft
    renderDetail(r);
    detailActionsEl.style.display = '';
  } catch (e) {
    toast('로드 오류: ' + e.message);
  }
}

// ── Render detail ──────────────────────────────────────────────────────────
function renderDetail(r) {
  const state   = (r._session && r._session.state) || r.state || {};
  const persona = r.persona || {};
  const affinity = state.affinity ?? 0;
  const stress   = state.stress   ?? 0;
  const act      = state.act      ?? 1;
  const mood     = state.mood     ?? '—';
  const turnCount= (r._session && r._session.turn_count) || 0;

  // Affinity gauge: -100~100 → 0~100%
  const affPct = Math.round(((affinity + 100) / 200) * 100);
  const stressPct = Math.min(100, Math.max(0, stress));

  const actLabels = ['서먹한 관계', '신뢰 형성', '깊은 유대'];

  detailContentEl.innerHTML = `
    <!-- Card header: avatar + name + desc -->
    <div class="rs-card-header">
      <div class="rs-card-avatar-wrap">
        ${r.image_url
          ? `<div class="rs-card-avatar"><img src="${esc(r.image_url)}?t=${Date.now()}" alt="${esc(r.name)}"></div>`
          : `<div class="rs-avatar-placeholder" id="imgPlaceholder">
               <span class="icon">🖼️</span>
               <span>이미지 없음</span>
             </div>`
        }
      </div>
      <div class="rs-card-title-area">
        <div class="rs-field">
          <label class="rs-label">이름</label>
          <input class="rs-input" id="fieldName" value="${esc(r.name)}" placeholder="캐릭터 이름">
        </div>
        <div class="rs-field">
          <label class="rs-label">소개</label>
          <input class="rs-input" id="fieldDesc" value="${esc(r.description)}" placeholder="한 줄 소개">
        </div>
      </div>
    </div>

    <!-- SimCore status -->
    <div class="rs-simcore">
      <div class="rs-simcore-title">⚙️ SimCore 상태 <span style="font-weight:400;color:var(--text-muted)">(${turnCount}턴 대화)</span></div>
      <div class="rs-gauge-row">
        <span class="rs-gauge-label">호감도</span>
        <div class="rs-gauge-track"><div class="rs-gauge-fill affinity" style="width:${affPct}%"></div></div>
        <span class="rs-gauge-val">${affinity}</span>
      </div>
      <div class="rs-gauge-row">
        <span class="rs-gauge-label">스트레스</span>
        <div class="rs-gauge-track"><div class="rs-gauge-fill stress" style="width:${stressPct}%"></div></div>
        <span class="rs-gauge-val">${stress}</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
        <span class="rs-gauge-label">기분</span>
        <span class="rs-mood-chip">✨ ${esc(mood)}</span>
      </div>
      <div style="margin-top:10px">
        <span class="rs-gauge-label" style="display:inline-block;margin-bottom:4px">Act</span>
        <div class="rs-act-pills">
          ${actLabels.map((l, i) => `<span class="rs-act-pill${act === i+1 ? ' active' : ''}">Act ${i+1} · ${esc(l)}</span>`).join('')}
        </div>
      </div>
    </div>

    <!-- Persona editing -->
    <div class="rs-field">
      <label class="rs-label">역할 (Role)</label>
      <input class="rs-input" id="fieldRole" value="${esc(persona.role || '')}" placeholder="예: 시스템 분석 보조 연구원">
    </div>
    <div class="rs-field">
      <label class="rs-label">말투 / 톤 (Tone)</label>
      <textarea class="rs-textarea" id="fieldTone" rows="3">${esc(persona.tone || '')}</textarea>
    </div>
    <div class="rs-field">
      <label class="rs-label">배경 설정 (Background)</label>
      <textarea class="rs-textarea" id="fieldBg" rows="3">${esc(persona.background || '')}</textarea>
    </div>
  `;

  // Bind input → editing draft
  bindField('fieldName',  v => { editing.name = v; });
  bindField('fieldDesc',  v => { editing.description = v; });
  bindField('fieldRole',  v => { editing.persona = editing.persona || {}; editing.persona.role = v; });
  bindField('fieldTone',  v => { editing.persona = editing.persona || {}; editing.persona.tone = v; });
  bindField('fieldBg',    v => { editing.persona = editing.persona || {}; editing.persona.background = v; });
}

function bindField(id, setter) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener('input', () => setter(el.value));
}

// ── Save ───────────────────────────────────────────────────────────────────
async function saveRole() {
  if (!activeSlug) return;
  saveBtnEl.disabled = true;
  saveBtnEl.textContent = '저장 중…';
  try {
    const payload = {
      slug: editing.slug || activeSlug,
      name: editing.name || activeSlug,
      version: editing.version || '1.0.0',
      description: editing.description || '',
      state: editing.state || {},
      persona: editing.persona || {},
      guidelines: editing.guidelines || [],
    };
    const data = await api(`/api/roles/${encodeURIComponent(activeSlug)}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (data.ok) {
      toast('✅ 저장 완료냥!');
      await loadRoles();
    } else {
      toast('저장 실패: ' + (data.error || '?'));
    }
  } catch (e) {
    toast('오류: ' + e.message);
  } finally {
    saveBtnEl.disabled = false;
    saveBtnEl.textContent = '저장';
  }
}

// ── Delete ─────────────────────────────────────────────────────────────────
async function deleteRole() {
  if (!activeSlug) return;
  const r = roles.find(r => r.slug === activeSlug);
  if (!confirm(`"${r ? r.name : activeSlug}" 캐릭터를 삭제할까냥? 되돌릴 수 없냥.`)) return;
  try {
    const data = await api(`/api/roles/${encodeURIComponent(activeSlug)}`, { method: 'DELETE' });
    if (data.ok) {
      toast('🗑️ 삭제 완료냥');
      activeSlug = null;
      emptyStateEl.style.display = '';
      detailContentEl.style.display = 'none';
      detailActionsEl.style.display = 'none';
      await loadRoles();
    } else {
      toast('삭제 실패: ' + (data.error || '?'));
    }
  } catch (e) {
    toast('오류: ' + e.message);
  }
}

// ── New character ──────────────────────────────────────────────────────────
function startNew() {
  const slug = prompt('캐릭터 ID를 입력하세요 (영소문자, _ 만 가능)\n예: soyeon');
  if (!slug) return;
  const clean = slug.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_');
  if (!clean) { alert('유효하지 않은 ID냥'); return; }
  editing = {
    slug: clean,
    name: clean,
    version: '1.0.0',
    description: '',
    state: { affinity: 0, stress: 10, mood: '차분함', act: 1, turn_count: 0, current_location: '미정' },
    persona: { role: '', tone: '', background: '', speech_style: [] },
    guidelines: [],
    image_url: null,
  };
  // optimistically insert
  if (!roles.find(r => r.slug === clean)) {
    roles.unshift({ slug: clean, name: clean, description: '새 캐릭터', state: editing.state, persona: editing.persona, has_image: false });
  }
  activeSlug = clean;
  renderList();
  emptyStateEl.style.display = 'none';
  detailContentEl.style.display = '';
  renderDetail(editing);
  detailActionsEl.style.display = '';
  toast('새 캐릭터 초안 생성! 저장 버튼으로 확정하세냥 ✦');
}

// ── Open chat ──────────────────────────────────────────────────────────────
function openChat() {
  if (!activeSlug) return;
  const r = roles.find(r => r.slug === activeSlug);
  const name = r ? r.name : activeSlug;
  // navigate to main chat with /role prefilled
  const url = `${BASE_PATH}/?role=${encodeURIComponent(activeSlug)}`;
  window.location.href = url;
}

// ── Event bindings ─────────────────────────────────────────────────────────
addBtnEl.addEventListener('click', startNew);
saveBtnEl.addEventListener('click', saveRole);
deleteBtnEl.addEventListener('click', deleteRole);
openChatBtnEl.addEventListener('click', openChat);

// ── Init ───────────────────────────────────────────────────────────────────
loadRoles();
