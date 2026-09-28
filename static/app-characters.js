// app-characters.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// Multi-Provider plan: [{id, available, models}], fetched once at boot.
// available:false providers stay in the dropdown (so the option isn't a
// silent mystery) but disabled, rather than omitted -- matches the plan's
// "표시하되 disabled" choice.
// Multi-Provider plan: [{id, name, role, theme, icon, available, models}], fetched once at boot.
// available:false providers stay in the tray with grayscale + disabled
let providerCatalog = [];
const brandAvatarEl = document.getElementById('brandAvatar');
const providerTrayEl = document.getElementById('providerTray');
const brandNameEl = document.getElementById('brandName');
const brandRoleEl = document.getElementById('brandRole');
const brandProviderEl = document.getElementById('brandProvider');
// 이름·호칭은 코드가 아니라 헌장(AGENTS.md `title`)과 기본 캐릭터 카드(이름, `user_title`)에서 온다.
// 서버가 <!--IDENTITY--> 자리에 window.__IDENTITY__를 심어 준다 (없으면 /api/identity로 폴백).
const IDENTITY = Object.assign({ title: 'Assistant', persona: '', user_title: '사용자', voice: '', name: 'Assistant' }, window.__IDENTITY__ || {});
function escapeRegExp(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function applyIdentity() {
  if (brandNameEl) brandNameEl.textContent = IDENTITY.title;          // 상단 제목 = 타이틀(직책)
  if (brandAvatarEl) brandAvatarEl.alt = IDENTITY.name;                // 아바타 = 페르소나(없으면 타이틀)
}

// 사용 불가(Free 만료/한도 소진) 제공자 및 비활성화 사유
const PROVIDER_DISABLED_REASONS = {
  // POLICY_v2 (2026-09-22): hard Free/Plus blocks removed.
  // AUTH_GATE_v1 still blocks use when unavailable or CLI auth ok===false.
  // Logged-in Claude Pro / Codex Plus become usable for chat.
};
function providerDisabledReason(pid) {
  return PROVIDER_DISABLED_REASONS[pid] || null;
}

// AUTH_GATE_v1: CLI login/policy may block *use* (chat/sessions/evolution)
// without blocking Status-tab selection. Auth map filled from /api/accounts.
let providerAuthOk = Object.create(null); // pid -> true|false|undefined

function providerUseBlockedReason(pid) {
  const policy = providerDisabledReason(pid);
  if (policy) return policy;
  const p = (Array.isArray(providerCatalog) ? providerCatalog : []).find(x => x.id === pid);
  if (p && p.available === false) return '미설치 또는 사용 불가';
  if (p && p.login && providerAuthOk[pid] === false) return '로그인 필요';   // catalog says it has a CLI login
  return null;
}

function isProviderUseBlocked(pid) {
  return Boolean(providerUseBlockedReason(pid));
}

let _authHealTried = false; // AUTH_HEAL_ONCE_v1: never yank provider while idle

async function refreshProviderAuthMap() {
  try {
    const res = await api('/api/accounts');
    const map = Object.create(null);
    const providers = (res && res.providers) || {};
    Object.keys(providers).forEach(pid => {
      const cur = providers[pid].current || {};
      if (typeof cur.ok === 'boolean') map[pid] = cur.ok;
    });
    providerAuthOk = map;
  } catch (_) {}
  // AUTH_HEAL_ONCE_v1: older builds could stick localStorage on a blocked id.
  // Heal at most once per page load — repeating this on every accounts poll
  // yanked Agy → Grok (first still-logged-in CLI) while the user sat idle.
  const curPid = chatProvider();
  if (!_authHealTried && curPid && providerUseBlockedReason(curPid)) {
    _authHealTried = true;
    const fallback = (Array.isArray(providerCatalog) ? providerCatalog : [])
      .map(p => p.id)
      .find(id => id && !providerUseBlockedReason(id));
    if (fallback && fallback !== curPid && providerEl) {
      providerEl.value = fallback;
      localStorage.setItem('chatbot.provider', fallback);
      updateBrandAvatar(fallback);
      populateModelsForProvider(fallback);
      addActivity('대화 제공자를 사용 가능한 ' + statusProviderName(fallback) + ' 로 복구했어요 (이전 선택이 사용 제한이었습니다).');
    }
  } else if (curPid && !providerUseBlockedReason(curPid)) {
    // Current choice is usable again — allow a future one-shot heal if it later sticks blocked.
    _authHealTried = false;
  }
  syncProviderUseGates();
  renderStatusPicker();
  renderProviderTray();
}

function syncProviderUseGates() {
  const pid = chatProvider();
  const reason = providerUseBlockedReason(pid);
  const blocked = Boolean(reason);
  const useTabs = [
    typeof tabChat !== 'undefined' ? tabChat : document.getElementById('tabChat'),
    typeof tabSessions !== 'undefined' ? tabSessions : document.getElementById('tabSessions'),
    typeof tabEvolution !== 'undefined' ? tabEvolution : document.getElementById('tabEvolution'),
  ].filter(Boolean);
  useTabs.forEach(btn => {
    if (!btn.getAttribute('data-base-title')) {
      btn.setAttribute('data-base-title', btn.getAttribute('title') || '');
    }
    btn.disabled = blocked;
    btn.classList.toggle('is-use-blocked', blocked);
    const base = btn.getAttribute('data-base-title') || '';
    btn.title = blocked ? (base + (base ? ' · ' : '') + reason) : base;
  });
  if (typeof inputEl !== 'undefined' && inputEl) {
    if (!inputEl.getAttribute('data-base-ph')) inputEl.setAttribute('data-base-ph', inputEl.placeholder || '');
    inputEl.disabled = blocked;
    inputEl.placeholder = blocked ? ('이 제공자는 사용할 수 없어요 — ' + reason) : (inputEl.getAttribute('data-base-ph') || '');
  }
  if (typeof sendBtn !== 'undefined' && sendBtn) {
    sendBtn.disabled = blocked || (typeof isBusy !== 'undefined' && isBusy);
  }
  if (blocked && typeof currentTab !== 'undefined' && (currentTab === 'chat' || currentTab === 'sessions' || currentTab === 'evolution')) {
    if (typeof switchTab === 'function') switchTab('status');
  }
  const banner = document.getElementById('providerUseBanner');
  if (banner) {
    if (blocked) {
      banner.hidden = false;
      banner.textContent = statusProviderName(pid) + ' · ' + reason + ' — 상태 탭에서 계정/로그아웃을 관리하세요.';
    } else {
      banner.hidden = true;
      banner.textContent = '';
    }
  }
}

function themeForProvider(p) {
  return (p && p.theme) || 'lime';   // each provider's theme comes from the catalog (providers.json / adapters)
}

const PORTRAIT_CACHE = 'v=12';
function portraitUrl(p) {
  const raw = (p && (p.icon || `/chat/providers/${p.id}.webp`)) || '/chat/persona/face-icon.webp';
  return String(raw).split('?')[0] + '?' + PORTRAIT_CACHE;
}

function providerCreditLabel(p) {
  if (!p) return '';
  const n = String(p.name || p.id);
  const names = [IDENTITY.persona, IDENTITY.title].filter(Boolean).map(escapeRegExp);
  const stripped = names.length
    ? n.replace(new RegExp('(?:' + names.join('|') + ')\\s*(?:\\(([^)]+)\\))?', 'g'), (_, inner) => inner || '').trim()
    : n.trim();
  return stripped || p.id;
}

const STAGE_BG_CACHE = 'v=1';
function updateStageBackground(providerId) {
  const pid = providerId || defaultProviderId;
  // the open character's own background for this brain (characters/<id>/stage/<provider>.webp, else stage.webp),
  // else the engine placeholder (ART_PLACEHOLDER_v1: the route never 404s); never another character's picture
  const ch = typeof currentCharacter === 'function' ? currentCharacter() : null;
  const candidate = ch
    ? BASE_PATH + '/api/characters/' + encodeURIComponent(ch.id) + '/stage?provider=' + encodeURIComponent(pid) + '&v=' + (ch.stage_v || 0)
    : `/chat/persona/providers/bg/${pid}.webp?${STAGE_BG_CACHE}`;
  const fallback = BASE_PATH + '/placeholders/stage.webp';
  const img = new Image();
  const ready = () => document.documentElement.classList.add('stage-ready');   // BOOT_CURTAIN_v1 (chat-log.css)
  img.onload = () => {
    document.documentElement.style.setProperty('--stage-bg-image', `url('${candidate}')`);
    ready();
  };
  img.onerror = () => {
    document.documentElement.style.setProperty('--stage-bg-image', `url('${fallback}')`);
    ready();
  };
  img.src = candidate;
}

function updateBrandAvatar(providerId) {
  const p = providerCatalog.find(item => item.id === providerId)
    || providerCatalog.find(item => item.id === defaultProviderId)
    || providerCatalog[0]
    || { id: '', name: '', role: '', theme: 'lime', icon: '' };
  const credit = providerCreditLabel(p);
  const ch = currentCharacter();
  const who = ch ? ch.name : IDENTITY.name;
  if (brandAvatarEl) {
    brandAvatarEl.onerror = () => { brandAvatarEl.onerror = null; brandAvatarEl.src = ch ? initialAvatar(who) : portraitUrl(p); };
    brandAvatarEl.src = characterPortrait(ch, p);
    // BUBBLE_AVATAR_v1: the same picture opens each run of the character's bubbles (chat-log.css)
    document.documentElement.style.setProperty('--char-avatar', 'url("' + brandAvatarEl.src.replace(/"/g, '%22') + '")');
    brandAvatarEl.alt = who;
    brandAvatarEl.title = `${who} · 캐릭터 선택 (클릭)`;
  }
  if (brandNameEl) {
    brandNameEl.textContent = ch ? (ch.title || ch.name) : IDENTITY.title;
  }
  if (brandProviderEl) {
    brandProviderEl.textContent = credit;
  } else if (brandRoleEl) {
    brandRoleEl.textContent = credit;
  }
  if (brandRoleEl) {
    brandRoleEl.title = credit;
    brandRoleEl.setAttribute('aria-label', `제공자 ${credit}`);
  }
  updateStageBackground(p.id);
  if (typeof loadVisualAdapterForCharacter === 'function') {
    loadVisualAdapterForCharacter(ch);
  }
}

// CHARACTER_PICKER_v1: the avatar picks the character; each character's picture follows the provider
// (characters/<id>/avatar/<provider>.webp, else avatar.webp, else its initial). The chatbot keeps the
// provider portraits.
let characterCatalog = [];
const characterTrayEl = document.getElementById('characterTray');
function currentCharacter() {
  return characterCatalog.find(c => c.id === openCharacterId()) || null;
}
function initialAvatar(name) {
  const ch = escapeHtml(Array.from(String(name || '?').trim())[0] || '?');
  return 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    + '<rect width="64" height="64" rx="32" fill="#2a2f3a"/><text x="32" y="42" font-size="28" text-anchor="middle" '
    + 'fill="#e6e8ee" font-family="sans-serif">' + ch + '</text></svg>');
}
function characterPortrait(c, p) {
  if (!c) return portraitUrl(p);
  // ART_PLACEHOLDER_v1: no picture yet is the engine placeholder from the same route; initials only if it fails
  // the page's base path, like every other API call (api()); without it the hub's /chat/ page got 404s
  return BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/avatar?provider=' + encodeURIComponent((p && p.id) || '')
    + '&v=' + c.avatar_v;
}
async function loadCharacters() {
  try {
    const res = await api('/api/characters');
    characterCatalog = res.characters || [];
  } catch (_) {
    characterCatalog = [];
  }
  if (typeof loadVisualAdapterForCharacter === 'function') {
    loadVisualAdapterForCharacter();
  }
}

function renderProviderTray() {
  if (!providerTrayEl) return;
  providerTrayEl.innerHTML = '';
  const currentPid = providerEl ? providerEl.value : (localStorage.getItem('chatbot.provider') || defaultProviderId);

  providerCatalog.forEach(p => {
    const btn = document.createElement('button');
    btn.type = 'button';
    const blockReason = providerUseBlockedReason(p.id);
    btn.className = 'provider-portrait-btn'
      + (p.id === currentPid ? ' active' : '')
      + (blockReason ? ' is-blocked-provider' : '');
    // Selectable even when blocked — use gates live on chat/sessions/evolution.
    btn.disabled = false;
    btn.setAttribute('data-provider-id', p.id);
    const credit = providerCreditLabel(p);
    btn.title = credit + (blockReason ? ' · ' + blockReason : '');

    const img = document.createElement('img');
    const who = currentCharacter();                 // the open character wearing this brain's wig
    img.onerror = () => { img.onerror = null; img.src = who ? initialAvatar(who.name || who.title) : '/chat/persona/face-icon.png'; };
    img.src = who ? characterPortrait(who, p) : portraitUrl(p);
    img.alt = credit;

    const tip = document.createElement('span');
    tip.className = 'provider-tooltip';
    tip.textContent = credit;

    btn.appendChild(img);
    btn.appendChild(tip);

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      // AUTH_GATE_v1: always allow selecting; use-gates lock chat/sessions/evolution.
      selectProvider(p.id);
      providerTrayEl.hidden = true;
    });

    providerTrayEl.appendChild(btn);
  });
}


function providerFieldsForSend(uiProvider, uiModel, serverProvider, serverModel) {
  const out = {};
  if (uiProvider && uiProvider !== serverProvider) out.provider = uiProvider;
  if (uiModel && uiModel !== serverModel) out.model = uiModel;
  return out;
}

function applySessionProvider(info) {
  if (!info || !info.provider) return false;
  if (localProviderEdit) return false;
  const pid = info.provider;
  const mid = info.model || '';
  const curPid = providerEl ? providerEl.value : (localStorage.getItem('chatbot.provider') || '');
  const curMid = modelEl ? modelEl.value : '';
  const providerChanged = pid !== curPid;
  const modelChanged = Boolean(mid) && mid !== curMid;
  lastServerProvider = pid;
  lastServerModel = mid || curMid;
  if (!providerChanged && !modelChanged) return false;
  if (providerEl) providerEl.value = pid;
  localStorage.setItem('chatbot.provider', pid);
  if (providerChanged) {
    updateBrandAvatar(pid);
    followChatProvider();
    populateModelsForProvider(pid, mid || undefined);
    renderProviderTray();
    const p = providerCatalog.find(item => item.id === pid);
    if (p && typeof applyTheme === 'function') applyTheme(themeForProvider(p));
  } else if (modelChanged) {
    populateModelsForProvider(pid, mid);
  }
  if (mid) {
    localStorage.setItem('chatbot.model', mid);
  }
  if (typeof syncModelUi === 'function') syncModelUi();
  return true;
}

async function persistSessionProvider(opts) {
  opts = opts || {};
  if (!sessionId) return;
  const pid = providerEl ? providerEl.value : '';
  const mid = modelEl ? modelEl.value : '';
  localProviderEdit++;
  try {
    const res = await api(`/api/sessions/${encodeURIComponent(sessionId)}/provider`, {
      method: 'POST',
      body: JSON.stringify({ provider: pid, model: mid }),
    });
    if (res && res.deferred) {
      pendingProviderPersist = { provider: pid, model: mid };
      addActivity(res.error || '제공자 전환을 작업 종료 후로 미뤘습니다.');
      return;
    }
    lastServerProvider = pid;
    lastServerModel = mid;
    if (opts.activity) addActivity(opts.activity);
  } catch (_) {
  } finally {
    localProviderEdit = Math.max(0, localProviderEdit - 1);
  }
}

let pendingProviderPersist = null; // { provider, model } while busy — apply when idle

async function selectProvider(newProviderId) {
  const p = providerCatalog.find(item => item.id === newProviderId);
  if (!p) return;
  const blockReason = providerUseBlockedReason(newProviderId);

  // AUTH_GATE_v1 / SNAP_FIX: a blocked provider must NOT replace the live chat
  // provider (or localStorage). Doing so made session resync pull the server
  // provider (e.g. Grok) back and look like "whatever I pick snaps to Grok".
  // Open it as Status view only.
  if (blockReason) {
    pendingProviderPersist = null;
    if (typeof setStatusViewProvider === 'function') setStatusViewProvider(newProviderId);
    if (typeof switchTab === 'function') switchTab('status');
    renderStatusPicker();
    renderProviderTray();
    addActivity('상태 조회로 열림: ' + (p.name || newProviderId) + ' — ' + blockReason + ' (대화 제공자는 ' + statusProviderName(chatProvider()) + ' 유지)');
    return;
  }

  localProviderEdit++;
  try {
    if (providerEl) {
      providerEl.value = newProviderId;
    }
    localStorage.setItem('chatbot.provider', newProviderId);

    // Update theme keycolor to match provider
    if (typeof applyTheme === 'function') {
      applyTheme(themeForProvider(p));
    }

    // Update avatar & title
    updateBrandAvatar(newProviderId);
    followChatProvider();
    populateModelsForProvider(newProviderId);
    localStorage.setItem('chatbot.model', modelEl.value);
    renderProviderTray();

    syncProviderUseGates();

    // PROVIDER_SWAP_DEFER_v1: never kill an in-flight turn just by picking a provider
    if (typeof isBusy !== 'undefined' && isBusy) {
      pendingProviderPersist = {
        provider: providerEl ? providerEl.value : newProviderId,
        model: modelEl ? modelEl.value : '',
      };
      addActivity('제공자 UI만 바꿈 — 진행 중 작업은 유지, 끝난 뒤·다음 메시지부터 적용: ' + (p.name || newProviderId));
      return;
    }
    pendingProviderPersist = null;
    await persistSessionProvider({
      activity: '제공자 전환: ' + (p.name || newProviderId),
    });
  } finally {
    localProviderEdit = Math.max(0, localProviderEdit - 1);
  }
}

async function flushPendingProviderPersist() {
  if (!pendingProviderPersist || (typeof isBusy !== 'undefined' && isBusy)) return;
  const want = pendingProviderPersist;
  pendingProviderPersist = null;
  if (providerEl && want.provider) providerEl.value = want.provider;
  if (modelEl && want.model) {
    populateModelsForProvider(want.provider, want.model);
  }
  await persistSessionProvider({
    activity: '미뤄 둔 제공자 전환 적용: ' + (want.provider || ''),
  });
}

function toggleProviderTray(force) {
  if (!providerTrayEl) return;
  const willShow = typeof force === 'boolean' ? force : providerTrayEl.hidden;
  if (willShow) { renderProviderTray(); toggleCharacterTray(false); }
  providerTrayEl.hidden = !willShow;
  if (brandProviderEl) brandProviderEl.setAttribute('aria-expanded', String(willShow));
}

function renderCharacterTray() {
  if (!characterTrayEl) return;
  characterTrayEl.innerHTML = '';
  const p = providerCatalog.find(item => item.id === (providerEl ? providerEl.value : '')) || providerCatalog[0];
  characterCatalog.forEach(c => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'provider-portrait-btn' + (c.id === openCharacterId() ? ' active' : '');
    btn.setAttribute('data-character-id', c.id);
    const label = c.name || c.title;
    btn.title = label + (c.title && c.title !== label ? ' · ' + c.title : '');
    const img = document.createElement('img');
    img.onerror = () => { img.onerror = null; img.src = initialAvatar(label); };
    img.src = characterPortrait(c, p);
    img.alt = label;
    const tip = document.createElement('span');
    tip.className = 'provider-tooltip';
    tip.textContent = label;
    btn.appendChild(img);
    btn.appendChild(tip);
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleCharacterTray(false);
      selectCharacter(c);
    });
    characterTrayEl.appendChild(btn);
  });
  // ART_MANAGER_v1 (app-art.js): the open character's pictures -- gallery, icon, background, expressions
  if (typeof openArtManager === 'function' && currentCharacter()) {
    const art = document.createElement('button');
    art.type = 'button';
    art.className = 'tray-art-btn';
    art.textContent = typeof ART_TEXT !== 'undefined' ? ART_TEXT.title : 'art';
    art.addEventListener('click', (e) => { e.stopPropagation(); toggleCharacterTray(false); openArtManager(openCharacterId()); });
    characterTrayEl.appendChild(art);
  }
}

function toggleCharacterTray(force) {
  if (!characterTrayEl) return;
  const willShow = typeof force === 'boolean' ? force : characterTrayEl.hidden;
  if (willShow) {
    renderCharacterTray();
    toggleProviderTray(false);
    // the list may be stale (a failed boot load, new characters or art): refresh it while the tray is open
    loadCharacters().then(() => { if (!characterTrayEl.hidden) renderCharacterTray(); updateBrandAvatar(providerEl ? providerEl.value : ''); });
  }
  characterTrayEl.hidden = !willShow;
  if (brandAvatarEl) brandAvatarEl.setAttribute('aria-expanded', String(willShow));
}

// Opens the character's own session in the current mode; its newest session keeps the brain last used with it
async function selectCharacter(c) {
  if (!c || c.id === openCharacterId()) return;
  try {
    const res = await api('/api/characters/' + encodeURIComponent(c.id) + '/session', {
      method: 'POST',
      body: JSON.stringify({ mode: sessionMode })
    });
    if (res && res.session && res.session.id) {
      await applyModeSwitch(res);
      if (typeof loadVisualAdapterForCharacter === 'function') {
        loadVisualAdapterForCharacter(c);
      }
    }
  } catch (e) {
    addActivity('캐릭터 전환 실패: ' + (e.message || e));
  }
}

function onTrayKey(el, fn) {
  if (!el) return;
  el.addEventListener('click', (e) => { e.stopPropagation(); fn(); });
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      fn();
    }
  });
}



function populateModelsForProvider(providerId, preferredModel) {
  // CODEX_DEFAULT_LUNA_v1: prefer saved model only if it belongs to this
  // provider; otherwise use server default_model (luna for Codex) or models[0].
  modelEl.innerHTML = '';
  const entry = providerCatalog.find(p => p.id === providerId);
  const models = (entry && entry.models) || [];
  models.forEach(m => {
    const o = document.createElement('option');
    o.value = m; o.textContent = m;
    modelEl.appendChild(o);
  });
  if (!models.length) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = '(기본값)';
    modelEl.appendChild(o);
  }
  const fallback = (entry && entry.default_model && models.includes(entry.default_model))
    ? entry.default_model
    : (models[0] || '');
  if (preferredModel && models.includes(preferredModel)) {
    modelEl.value = preferredModel;
  } else if (fallback) {
    modelEl.value = fallback;
  }
  if (typeof syncModelUi === 'function') syncModelUi();
}

// ------------------------------------------------------------------------ ST Character Card Importer

function showCharacterToast(msg) {
  if (typeof setProgress === 'function') {
    setProgress(msg, true);
    setTimeout(() => {
      if (typeof progressEl !== 'undefined' && progressEl && !progressEl.hidden && progressEl.textContent.includes(msg)) {
        setProgress('');
      }
    }, 3500);
  } else if (typeof toast === 'function') {
    toast(msg);
  }
}

async function importStCard(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file, file.name || 'card.png');

  try {
    const res = await api('/api/characters/import', {
      method: 'POST',
      body: formData,
      headers: {},
    });
    if (res && (res.success || res.ok)) {
      if (typeof loadCharacters === 'function') await loadCharacters();
      if (typeof loadTeam === 'function') {
        try { await loadTeam(); } catch (_) {}
      }
      if (typeof renderCharacterTray === 'function') renderCharacterTray();
      const charName = (res.character && res.character.name) || '캐릭터';
      showCharacterToast('ST 카드 가져오기 완료: ' + charName);
      if (typeof addActivity === 'function') {
        addActivity('ST 카드 가져오기 성공: ' + charName);
      }
      return res;
    } else {
      const errMsg = (res && res.error) || '가져오기 실패';
      showCharacterToast('ST 카드 가져오기 실패: ' + errMsg);
      if (typeof addActivity === 'function') {
        addActivity('ST 카드 가져오기 실패: ' + errMsg, 'warn');
      }
      return res;
    }
  } catch (e) {
    let errMsg = (e && e.message) || String(e);
    try {
      const parsed = JSON.parse(errMsg);
      if (parsed.error) errMsg = parsed.error;
    } catch (_) {}
    showCharacterToast('ST 카드 가져오기 실패: ' + errMsg);
    if (typeof addActivity === 'function') {
      addActivity('ST 카드 가져오기 실패: ' + errMsg, 'warn');
    }
    throw e;
  }
}

function initStImportUi() {
  const fileInput = document.getElementById('stCardFileInput');
  const importBtn = document.getElementById('stCardImportBtn');
  const teamPane = document.getElementById('teamPane');

  if (importBtn && fileInput && !importBtn._stBound) {
    importBtn._stBound = true;
    importBtn.addEventListener('click', () => {
      fileInput.value = '';
      fileInput.click();
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) {
        importStCard(fileInput.files[0]);
      }
    });
  }

  if (teamPane && !teamPane._stDropBound) {
    teamPane._stDropBound = true;
    teamPane.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      teamPane.style.outline = '2px dashed var(--accent, #a3e635)';
      teamPane.style.outlineOffset = '-4px';
    });
    ['dragleave', 'dragend'].forEach(ev => {
      teamPane.addEventListener(ev, () => {
        teamPane.style.outline = '';
        teamPane.style.outlineOffset = '';
      });
    });
    teamPane.addEventListener('drop', (e) => {
      e.preventDefault();
      teamPane.style.outline = '';
      teamPane.style.outlineOffset = '';
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length > 0) {
        const file = files[0];
        if (file.name.toLowerCase().endsWith('.png') || file.type === 'image/png') {
          importStCard(file);
        } else {
          showCharacterToast('PNG 파일만 가져올 수 있어요');
        }
      }
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initStImportUi);
} else {
  initStImportUi();
}

// ------------------------------------------------------------------------ Visual Adapter Integration (Phase 3)

function ensureCharacterSprite() {
  if (typeof document === 'undefined') return null;
  let img = document.querySelector('.character-sprite');
  if (!img) {
    const container = document.querySelector('.stage') ||
                      document.querySelector('.stage-shell') ||
                      (document.getElementById('log') && document.getElementById('log').parentElement) ||
                      document.body;
    img = document.createElement('img');
    img.className = 'character-sprite';
    img.alt = 'Character Sprite';
    img.style.position = 'absolute';
    img.style.bottom = '0';
    img.style.right = '1.5rem';
    img.style.maxHeight = '70%';
    img.style.maxWidth = '45%';
    img.style.objectFit = 'contain';
    img.style.pointerEvents = 'none';
    img.style.zIndex = '0';
    img.style.opacity = '0';
    img.style.transition = 'opacity 0.2s ease';
    if (container) {
      container.appendChild(img);
    }
  }
  return img;
}

let visualAdapterRegistry = null;

async function initVisualAdapters() {
  try {
    const { AdapterRegistry } = await import('./visual-adapter.js');
    const { SpriteAdapter } = await import('./visual-sprite-adapter.js');
    visualAdapterRegistry = new AdapterRegistry();
    visualAdapterRegistry.register('sprite', SpriteAdapter);
    if (typeof window !== 'undefined') {
      window._adapterRegistry = visualAdapterRegistry;
    }
    const ch = typeof currentCharacter === 'function' ? currentCharacter() : null;
    if (ch) {
      await loadVisualAdapterForCharacter(ch);
    }
  } catch (_) {}
}

async function loadVisualAdapterForCharacter(char) {
  const c = char || (typeof currentCharacter === 'function' ? currentCharacter() : null);
  if (!c) return;
  ensureCharacterSprite();
  if (typeof window === 'undefined') return;
  try {
    if (!window._visualAdapter) {
      if (visualAdapterRegistry) {
        window._visualAdapter = visualAdapterRegistry.create('sprite');
      } else {
        const { SpriteAdapter } = await import('./visual-sprite-adapter.js');
        window._visualAdapter = new SpriteAdapter();
      }
    }
    if (window._visualAdapter && typeof window._visualAdapter.load === 'function') {
      await window._visualAdapter.load(c);
      if (typeof window._visualAdapter.setEmotion === 'function') {
        window._visualAdapter.setEmotion('default');
      }
    }
  } catch (_) {}
}

(function hookEventSourceForVisualEmotion() {
  if (typeof window === 'undefined' || !window.EventSource) return;
  const OrigES = window.EventSource;
  window.EventSource = function(...args) {
    const inst = new OrigES(...args);
    inst.addEventListener('message', (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data && (data.event === 'emotion' || data.type === 'emotion')) {
          const label = data.label || data.emotion || '';
          if (label && window._visualAdapter && typeof window._visualAdapter.setEmotion === 'function') {
            window._visualAdapter.setEmotion(label);
          }
        }
      } catch (_) {}
    });
    return inst;
  };
  window.EventSource.prototype = OrigES.prototype;
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initVisualAdapters);
} else {
  initVisualAdapters();
}


