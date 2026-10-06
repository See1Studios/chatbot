// app-characters.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// Multi-Provider plan: [{id, available, models}], fetched once at boot.
// available:false providers stay in the dropdown (so the option isn't a
// silent mystery) but disabled, rather than omitted -- matches the plan's
// "show it, disabled" choice.
// Multi-Provider plan: [{id, name, role, theme, icon, available, models}], fetched once at boot.
// available:false providers stay in the tray with grayscale + disabled
let providerCatalog = [];
const brandAvatarEl = document.getElementById('brandAvatar');
const providerTrayEl = document.getElementById('providerTray');
const brandNameEl = document.getElementById('brandName');
const brandRoleEl = document.getElementById('brandRole');
const brandProviderEl = document.getElementById('brandProvider');
// Names and forms of address come from the charter (AGENTS.md `title`) and the default character's card (name, `user_title`), never from code.
// The server plants window.__IDENTITY__ at <!--IDENTITY--> (else /api/identity is the fallback).
const IDENTITY = Object.assign({ title: 'Assistant', persona: '', user_title: '', voice: '', name: 'Assistant' }, window.__IDENTITY__ || {});
i18nReady.then(() => { if (!IDENTITY.user_title) IDENTITY.user_title = tr('common.user'); });   // the catalog's word, once it is in
function escapeRegExp(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function applyIdentity() {
  if (brandNameEl) brandNameEl.textContent = IDENTITY.title;          // the top title = the title (the post)
  if (brandAvatarEl) brandAvatarEl.alt = IDENTITY.name;                // the avatar = the persona (else the title)
}

// Providers that cannot be used (Free expired, limits used up) and why
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
  if (p && p.available === false) return tr('shell.provider_unavailable');
  if (p && p.login && providerAuthOk[pid] === false) return tr('shell.provider_login_needed');   // catalog says it has a CLI login
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
      addActivity(tr('shell.provider_restored', { provider: statusProviderName(fallback) }));
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
    inputEl.placeholder = blocked ? tr('shell.provider_blocked', { reason }) : (inputEl.getAttribute('data-base-ph') || '');
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
      banner.textContent = tr('shell.provider_banner', { provider: statusProviderName(pid), reason });
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
    brandAvatarEl.title = who + ' · ' + tr('shell.pick_character_click');
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
    brandRoleEl.setAttribute('aria-label', tr('shell.provider_label', { credit }));
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
// OWN_LOOK_v1 (operator, 2026-09-30): a character's picture follows ITS OWN provider -- the one picked now for the
// open character, the brain last used with it for the others (the server's talks, session_registry talks()) -- so
// switching the open talk's provider never repaints everyone else. Unknown = the character's plain avatar.
// Whether the look stays bound to the provider at all is undecided; this is the one place that binding is read.
let characterTalks = {};
function characterLook(c) {
  if (!c) return null;
  if (c.id === openCharacterId() && !(typeof roomOpenId === 'function' && roomOpenId())) {
    return providerCatalog.find(item => item.id === (providerEl ? providerEl.value : '')) || null;
  }
  const own = (characterTalks[c.id] || {}).provider || '';
  return own ? (providerCatalog.find(item => item.id === own) || { id: own }) : null;
}
function characterOwnPortrait(c) { return characterPortrait(c, characterLook(c)); }
async function loadCharacters() {
  try {
    const res = await api('/api/characters');
    characterCatalog = res.characters || [];
  } catch (_) {
    characterCatalog = [];
  }
  try { characterTalks = (await api('/api/sessions')).talks || characterTalks; } catch (_) { /* keep the last known */ }
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
      addActivity(res.error || tr('shell.provider_deferred'));
      return;
    }
    lastServerProvider = pid;
    lastServerModel = mid;
    if (opts.activity) addActivity(opts.activity);
    if (typeof shellProfileIsOpen === 'function' && shellProfileIsOpen()) shellProfileOpen();
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
    addActivity(tr('shell.provider_view_only', { provider: p.name || newProviderId, reason: blockReason, chat: statusProviderName(chatProvider()) }));
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
      addActivity(tr('shell.provider_ui_only', { provider: p.name || newProviderId }));
      return;
    }
    pendingProviderPersist = null;
    await persistSessionProvider({
      activity: tr('shell.provider_switched', { provider: p.name || newProviderId }),
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
    activity: tr('shell.provider_deferred_applied', { provider: want.provider || '' }),
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
  characterCatalog.forEach(c => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'provider-portrait-btn' + (c.id === openCharacterId() ? ' active' : '');
    btn.setAttribute('data-character-id', c.id);
    const label = c.name || c.title;
    btn.title = label + (c.title && c.title !== label ? ' · ' + c.title : '');
    const img = document.createElement('img');
    img.onerror = () => { img.onerror = null; img.src = initialAvatar(label); };
    img.src = characterOwnPortrait(c);
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
  if (typeof openSummonWizard === 'function') {
    const summon = document.createElement('button');
    summon.type = 'button';
    summon.className = 'tray-art-btn';
    const menuBtn = document.getElementById('summonOpenBtn');
    summon.textContent = (menuBtn && menuBtn.textContent.trim()) || 'Summon';
    summon.addEventListener('click', (e) => { e.stopPropagation(); toggleCharacterTray(false); openSummonWizard(); });
    characterTrayEl.appendChild(summon);
  }
  // ART_MANAGER_v1 (app-art.js): the open character's pictures -- gallery, icon, background, expressions
  if (typeof openArtManager === 'function' && currentCharacter()) {
    const art = document.createElement('button');
    art.type = 'button';
    art.className = 'tray-art-btn';
    art.textContent = typeof ART_TEXT !== 'undefined' ? ART_TEXT.title : 'art';
    art.addEventListener('click', (e) => { e.stopPropagation(); toggleCharacterTray(false); openArtManager(openCharacterId()); });
    characterTrayEl.appendChild(art);
  }
  // evt/E-2 (app-rooms.js): group rooms with several characters
  if (typeof openRooms === 'function' && characterCatalog.length > 1) {
    const rooms = document.createElement('button');
    rooms.type = 'button';
    rooms.className = 'tray-art-btn';
    rooms.textContent = typeof ROOM_TEXT !== 'undefined' ? ROOM_TEXT.title : 'rooms';
    rooms.addEventListener('click', (e) => { e.stopPropagation(); toggleCharacterTray(false); openRooms(); });
    characterTrayEl.appendChild(rooms);
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

// Opens the character's own WORK session; its newest session keeps the brain last used with it. Never the mode on
// screen (operator, 2026-09-30): private mode does not carry over to another character -- from a private talk the
// server would start a fresh private session for whoever was picked. Going private is done on purpose (the heart).
async function selectCharacter(c) {
  if (!c || c.id === openCharacterId()) return;
  try {
    const res = await api('/api/characters/' + encodeURIComponent(c.id) + '/session', {
      method: 'POST',
      body: JSON.stringify({ mode: 'work', from: sessionId })   // from: the room being left, for its private digest
    });
    if (res && res.session && res.session.id) {
      await applyModeSwitch(res);
      if (typeof loadVisualAdapterForCharacter === 'function') {
        loadVisualAdapterForCharacter(c);
      }
    }
  } catch (e) {
    addActivity(tr('shell.character_failed', { error: e.message || e }));
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
    o.value = ''; o.textContent = tr('common.default_value');
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
      const charName = (res.character && res.character.name) || tr('team.character');
      showCharacterToast(tr('team.st_imported', { name: charName }));
      if (typeof addActivity === 'function') {
        addActivity(tr('team.st_imported', { name: charName }));
      }
      return res;
    } else {
      const errMsg = (res && res.error) || tr('team.st_failed_plain');
      showCharacterToast(tr('team.st_failed', { error: errMsg }));
      if (typeof addActivity === 'function') {
        addActivity(tr('team.st_failed', { error: errMsg }), 'warn');
      }
      return res;
    }
  } catch (e) {
    let errMsg = (e && e.message) || String(e);
    try {
      const parsed = JSON.parse(errMsg);
      if (parsed.error) errMsg = parsed.error;
    } catch (_) {}
    showCharacterToast(tr('team.st_failed', { error: errMsg }));
    if (typeof addActivity === 'function') {
      addActivity(tr('team.st_failed', { error: errMsg }), 'warn');
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
          showCharacterToast(tr('team.st_png_only'));
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


