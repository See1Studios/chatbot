// app-status.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
async function fetchSelfStatus() {
  if (!statusPaneEl) return;
  try {
    const res = await api('/api/self-status');
    loadInstructions();
    loadContextNow();
    renderStatusSkills(res.skills || []);
    if (statusSkillLibHintEl) {
      statusSkillLibHintEl.textContent = tr('status.skill_lib', { n: res.host_skill_library_count || 0 });
    }
    renderStatusMcp(res.mcp || []);
    renderStatusHooks(res.hooks || {}, res.plugins || {});
    // observation/tickets live on Evolution tab (STATUS_EVOLUTION_TAB_v1)
    statusLoaded = true;
  } catch (e) {
    if (statusInstructionsEl) statusInstructionsEl.textContent = tr('status.load_failed', { error: e.message });
  }
}

// The status tab shows one provider, the one in use: account -> usage -> processes.
// The server matches the token file's email against the account each agy process signed in with and works out
// whether it is stale -- this only draws it.
const ACCT_OWNER_LABEL = i18nTable('status.owner');

// The provider the status tab shows: by default the conversation's; a chip shows another provider's status
// "to look only" -- selectProvider() is not called, so the server session (provider, conversation_id) stays.
let statusViewProvider = null;
function chatProvider() { return providerEl ? providerEl.value : defaultProviderId; }
function currentStatusProvider() { return statusViewProvider || chatProvider(); }

// Named as in the brand area at the top (agy=Antigravity). A provider's name is the vendor's, not a persona's.
function statusProviderName(id) {
  const e = Array.isArray(providerCatalog) ? providerCatalog.find(p => p.id === id) : null;
  return providerCreditLabel(e || { id });
}

function renderStatusPicker() {
  if (!statusPickerEl) return;
  statusPickerEl.innerHTML = '';
  const viewing = currentStatusProvider(), chat = chatProvider();
  (Array.isArray(providerCatalog) ? providerCatalog : []).forEach(p => {
    const b = document.createElement('button');
    b.type = 'button';
    const blockReason = providerUseBlockedReason(p.id);
    b.className = 'art-filter-btn'
      + (p.id === viewing ? ' on' : '')
      + (p.id === chat ? ' is-chat' : '')
      + (blockReason ? ' is-blocked-provider' : '');
    b.textContent = providerCreditLabel(p);
    b.title = (p.id === chat ? tr('status.provider.chatting') : tr('status.provider.view_only'))
      + (blockReason ? ' · ' + blockReason : '');
    b.setAttribute('aria-pressed', String(p.id === viewing));
    // Always selectable: blocked providers are still viewable on Status.
    b.disabled = false;
    b.addEventListener('click', () => setStatusViewProvider(p.id));
    statusPickerEl.appendChild(b);
  });
}

// Shows another provider's status only (the conversation's session is not touched).
function setStatusViewProvider(id) {
  statusViewProvider = (id === chatProvider()) ? null : id;
  refreshProviderStatus();
}

// When the conversation's provider changes in code the select's onchange does not run, so redraw here; the view follows the conversation.
function followChatProvider() {
  statusViewProvider = null;
  refreshProviderStatus();
}

function refreshProviderStatus() {
  if (currentTab !== 'status') return;
  renderStatusPicker();
  fetchAccounts();
  fetchUsage(false);
}

function fmtAge(sec) {
  if (sec == null) return '?';
  if (sec < 90) return tr('status.age.sec', { n: sec });
  if (sec < 5400) return tr('status.age.min', { n: Math.round(sec / 60) });
  if (sec < 172800) return tr('status.age.hour', { n: (sec / 3600).toFixed(1) });
  return tr('status.age.day', { n: (sec / 86400).toFixed(1) });
}

async function fetchAccounts() {
  if (!statusAccountsEl) return;
  const provider = currentStatusProvider();
  if (statusProviderTitleEl) statusProviderTitleEl.textContent = statusProviderName(provider) + (statusViewProvider ? tr('status.provider.other_suffix') : '');
  // LOGIN_PASTE_KEEP_v2: detach in-flight login panel before wipe so paste/URL survive refresh.
  const keepLogin = statusAccountsEl.querySelector('.login-panel[data-provider="' + provider + '"]');
  if (keepLogin) keepLogin.remove();
  statusAccountsEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('common.loading')) + '</div>';
  try {
    const res = await api('/api/accounts?provider=' + encodeURIComponent(provider));
    if (currentStatusProvider() !== provider) return;  // the provider changed while the answer was on its way
    renderAccounts(res, provider);
    if (keepLogin && (_loginPollTimers[provider] || ((_loginPanelState[provider] || {}).state === 'pending'))) {
      statusAccountsEl.appendChild(keepLogin);
    }
  } catch (e) {
    statusAccountsEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('status.acct.load_failed', { error: e.message })) + '</div>';
    if (statusProcsEl) statusProcsEl.hidden = true;
  }
}

function acctProcRow(p, hasEvidence) {
  const item = document.createElement('div');
  item.className = 'status-item' + (p.stale ? ' acct-warn' : '');
  const owner = ACCT_OWNER_LABEL[p.owner] || p.owner;
  let badge;
  if (p.account) {
    badge = '<span class="acct-badge ' + (p.stale ? 'stale' : 'ok') + '">' + escapeHtml(p.account) + (p.stale ? escapeHtml(tr('status.proc.old_account_suffix')) : '') + '</span>';
  } else if (p.predates_change) {
    badge = '<span class="acct-badge warn">' + escapeHtml(tr('status.proc.predates')) + '</span>';
  } else {
    badge = '<span class="acct-badge">' + escapeHtml(hasEvidence ? tr('status.proc.account_unknown_nolog') : tr('status.proc.account_unknown')) + '</span>';
  }
  const who = p.sid ? ' ' + escapeHtml(p.sid) : '';
  item.innerHTML =
    '<div class="status-item-head"><span class="status-item-name">pid ' + p.pid + ' · ' + escapeHtml(owner) + who + '</span>' + badge + '</div>' +
    '<div class="status-item-preview">' + escapeHtml(tr('status.proc.line', { age: fmtAge(p.age_sec), tty: p.tty, parent: p.parent || '?', ppid: p.ppid })) +
    (p.busy ? escapeHtml(tr('status.proc.busy_suffix')) : '') + '\n' + escapeHtml(p.cmd) + '</div>';
  if (p.kill_cmd) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'art-filter-btn';
    btn.textContent = tr('status.proc.copy_kill', { cmd: p.kill_cmd });
    btn.addEventListener('click', () => copyText(p.kill_cmd).then(() => { btn.textContent = tr('common.copied'); }, () => { btn.textContent = p.kill_cmd; }));
    item.appendChild(btn);
  }
  return item;
}



// ACCOUNTS_LOGIN_v2 — Status-tab CLI login panel (agy/claude/codex/grok)
const _loginPollTimers = {};
const _loginPanelState = {}; // provider -> last status payload

function stopLoginPoll(provider) {
  if (_loginPollTimers[provider]) {
    clearInterval(_loginPollTimers[provider]);
    delete _loginPollTimers[provider];
  }
}

function loginModeHint(mode) {
  if (mode === 'oauth_paste') return tr('status.login.mode.oauth_paste');
  if (mode === 'oauth_callback') return tr('status.login.mode.oauth_callback');
  if (mode === 'device_code') return tr('status.login.mode.device_code');
  return mode || '';
}

function buildLoginPanel(provider) {
  const panel = document.createElement('div');
  panel.className = 'login-panel';
  panel.dataset.provider = provider;
  panel.innerHTML =
    '<div class="login-panel-head"><strong>' + escapeHtml(tr('status.login.title')) + '</strong> <span class="login-panel-mode"></span></div>' +
    '<div class="login-panel-msg status-hint">' + escapeHtml(tr('status.login.preparing')) + '</div>' +
    '<div class="login-panel-fields"></div>' +
    '<div class="login-panel-actions"></div>' +
    '<div class="login-panel-err" hidden></div>';
  return panel;
}

function renderLoginFields(panel, st) {
  const fields = panel.querySelector('.login-panel-fields');
  const modeEl = panel.querySelector('.login-panel-mode');
  const msgEl = panel.querySelector('.login-panel-msg');
  const errEl = panel.querySelector('.login-panel-err');
  if (!fields) return;
  // LOGIN_PASTE_KEEP_v2: 2s status poll must not wipe an in-progress paste.
  const prevInput = fields.querySelector('.login-code-input');
  const keepPaste = {
    value: prevInput ? prevInput.value : '',
    focused: !!(prevInput && document.activeElement === prevInput),
    selStart: prevInput ? prevInput.selectionStart : null,
    selEnd: prevInput ? prevInput.selectionEnd : null,
  };
  const samePending = (
    st.state === 'pending'
    && st.mode === 'oauth_paste'
    && panel.dataset.loginId === String(st.login_id || '')
    && panel.dataset.authUrl === String(st.authorize_url || '')
    && !!prevInput
  );
  if (modeEl) modeEl.textContent = st.mode ? ('· ' + loginModeHint(st.mode)) : '';
  if (msgEl) msgEl.textContent = [trField(st, 'message'), trField(st, 'tip')].filter(Boolean).join(' ');
  if (errEl) {
    if (st.error && (st.state === 'failed' || st.state === 'superseded')) {
      errEl.hidden = false;
      errEl.textContent = trField(st, 'error');
    } else {
      errEl.hidden = true;
      errEl.textContent = '';
    }
  }
  if (samePending) {
    // URL/login_id unchanged — leave the paste row alone.
    return;
  }
  fields.innerHTML = '';
  panel.dataset.loginId = String(st.login_id || '');
  panel.dataset.authUrl = String(st.authorize_url || '');

  const addCopyRow = (label, value, isUrl) => {
    if (!value) return;
    const row = document.createElement('div');
    row.className = 'login-row';
    const lab = document.createElement('div');
    lab.className = 'login-label';
    lab.textContent = label;
    const val = document.createElement(isUrl ? 'a' : 'code');
    val.className = 'login-value';
    if (isUrl) {
      val.href = value;
      val.target = '_blank';
      val.rel = 'noopener noreferrer';
      val.textContent = value;
    } else {
      val.textContent = value;
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ghost login-copy';
    btn.textContent = tr('common.copy');
    btn.addEventListener('click', () => copyText(value).then(() => {
      btn.textContent = tr('common.copied');
      setTimeout(() => { btn.textContent = tr('common.copy'); }, 1200);
    }, () => { btn.textContent = tr('common.failed'); }));
    row.appendChild(lab);
    row.appendChild(val);
    row.appendChild(btn);
    fields.appendChild(row);
  };

  addCopyRow(tr('status.login.auth_url'), st.authorize_url, true);
  if (st.verification_uri && st.verification_uri !== st.authorize_url) {
    addCopyRow(tr('status.login.verify_url'), st.verification_uri, true);
  }
  addCopyRow(tr('status.login.user_code'), st.user_code, false);
  if (st.callback_port) {
    addCopyRow(tr('status.login.callback_port'), String(st.callback_port), false);
  }

  if (st.mode === 'oauth_paste' && st.state === 'pending') {
    const row = document.createElement('div');
    row.className = 'login-row login-paste';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'login-code-input';
    input.placeholder = tr('status.login.paste_code');
    input.autocomplete = 'off';
    const submit = document.createElement('button');
    submit.type = 'button';
    submit.className = 'art-btn';
    submit.textContent = tr('common.submit');
    const doSubmit = async () => {
      const code = (input.value || '').trim();
      if (!code) { alert(tr('status.login.enter_code')); return; }
      submit.disabled = true;
      try {
        const r = await api('/api/accounts/login/complete', {
          method: 'POST',
          body: JSON.stringify({ provider: st.provider, login_id: st.login_id, code }),
          timeoutMs: 30000,
        });
        _loginPanelState[st.provider] = r;
        renderLoginFields(panel, r);
        updateLoginActions(panel, r);
        if (r.state === 'succeeded') {
          onLoginSucceeded(st.provider, r);
        } else if (!r.ok || r.state === 'failed') {
          alert(trField(r, 'error') || trField(r, 'message') || tr('status.login.submit_failed'));
        } else if (trField(r, 'message')) {
          const msgEl = panel.querySelector('.login-panel-msg');
          if (msgEl) msgEl.textContent = trField(r, 'message');
        }
      } catch (e) {
        alert(tr('status.login.submit_failed_error', { error: e.message }));
      } finally {
        submit.disabled = false;
      }
    };
    submit.addEventListener('click', doSubmit);
    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); doSubmit(); }
    });
    if (keepPaste.value) input.value = keepPaste.value;
    row.appendChild(input);
    row.appendChild(submit);
    fields.appendChild(row);
    if (keepPaste.focused) {
      input.focus();
      try {
        if (keepPaste.selStart != null && keepPaste.selEnd != null) {
          input.setSelectionRange(keepPaste.selStart, keepPaste.selEnd);
        }
      } catch (e) {}
    }
  }
}

function updateLoginActions(panel, st) {
  const actions = panel.querySelector('.login-panel-actions');
  if (!actions) return;
  actions.innerHTML = '';
  if (st.state === 'pending') {
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'ghost';
    cancelBtn.textContent = tr('common.cancel');
    cancelBtn.addEventListener('click', () => cancelLogin(st.provider, st.login_id, panel));
    actions.appendChild(cancelBtn);
    if (st.expires_in != null) {
      const ttl = document.createElement('span');
      ttl.className = 'status-hint';
      ttl.textContent = tr('status.login.time_left', { n: Math.max(0, Math.round(st.expires_in / 60)) });
      actions.appendChild(ttl);
    }
  } else if (st.state === 'succeeded') {
    const ok = document.createElement('span');
    ok.className = 'status-hint';
    ok.textContent = tr('status.login.done_refreshing');
    actions.appendChild(ok);
  } else if (st.state === 'failed' || st.state === 'cancelled') {
    const again = document.createElement('button');
    again.type = 'button';
    again.className = 'art-btn';
    again.textContent = tr('common.retry');
    again.addEventListener('click', () => startLogin(st.provider, panel));
    actions.appendChild(again);
  }
}

async function onLoginSucceeded(provider, st) {
  stopLoginPoll(provider);
  addActivity(tr('status.login.activity_done', { provider: statusProviderName(provider) || provider }), 'system');
  try { await refreshProviderAuthMap(); } catch (e) {}
  // CODEX_MODELS_v1: refresh catalog so models/available update without reload.
  try {
    const res = await api('/api/providers');
    providerCatalog = res.providers || providerCatalog;
    if (providerEl && providerEl.value === provider) {
      populateModelsForProvider(provider, modelEl ? modelEl.value : null);
    }
    renderProviderTray();
  } catch (e) {}
  fetchAccounts();
  // USAGE_v1: force usage refresh after auth settles (do not leave a stale miss).
  setTimeout(() => {
    if (currentTab === 'status' && currentStatusProvider() === provider) fetchUsage(true);
  }, 1500);
}

async function cancelLogin(provider, loginId, panel) {
  stopLoginPoll(provider);
  try {
    await api('/api/accounts/login/cancel', {
      method: 'POST',
      body: JSON.stringify({ provider, login_id: loginId || undefined }),
    });
  } catch (e) {}
  if (panel && panel.parentNode) panel.remove();
  addActivity(tr('status.login.activity_cancelled', { provider: statusProviderName(provider) || provider }), 'system');
  fetchAccounts();
}

function startLoginPoll(provider, panel, loginId) {
  stopLoginPoll(provider);
  const qs = 'provider=' + encodeURIComponent(provider) + (loginId ? '&login_id=' + encodeURIComponent(loginId) : '');
  _loginPollTimers[provider] = setInterval(async () => {
    try {
      const st = await api('/api/accounts/login/status?' + qs, { timeoutMs: 15000 });
      _loginPanelState[provider] = st;
      if (!panel.isConnected) { stopLoginPoll(provider); return; }
      renderLoginFields(panel, st);
      updateLoginActions(panel, st);
      if (st.state === 'succeeded') {
        onLoginSucceeded(provider, st);
      } else if (st.state === 'failed' || st.state === 'cancelled' || st.state === 'idle' || st.state === 'superseded') {
        stopLoginPoll(provider);
        if (st.state === 'failed') {
          addActivity(tr('status.login.activity_failed', { provider: statusProviderName(provider) || provider, error: trField(st, 'error') }), 'warn');
        } else if (st.state === 'superseded') {
          addActivity(tr('status.login.activity_superseded', { provider: statusProviderName(provider) || provider }), 'warn');
        }
      }
    } catch (e) {
      // keep polling through transient errors
    }
  }, 2000);
}

async function startLogin(provider, existingPanel) {
  let panel = existingPanel;
  const host = statusAccountsEl;
  if (!panel) {
    panel = buildLoginPanel(provider);
    if (host) host.appendChild(panel);
  }
  panel.querySelector('.login-panel-msg').textContent = tr('status.login.starting');
  try {
    const st = await api('/api/accounts/login/start', {
      method: 'POST',
      body: JSON.stringify({ provider }),
      timeoutMs: 25000,
    });
    _loginPanelState[provider] = st;
    renderLoginFields(panel, st);
    updateLoginActions(panel, st);
    if (st.state === 'pending') {
      startLoginPoll(provider, panel, st.login_id);
      addActivity(tr('status.login.activity_started', { provider: statusProviderName(provider) || provider, mode: loginModeHint(st.mode) }), 'system');
    } else if (st.state === 'succeeded') {
      onLoginSucceeded(provider, st);
    } else if (!st.ok) {
      alert(tr('status.login.start_failed', { error: trField(st, 'error') || 'unknown' }));
    }
  } catch (e) {
    alert(tr('status.login.start_failed', { error: e.message }));
    if (panel && panel.parentNode) panel.remove();
  }
}


async function logoutAccount(provider, email, btn) {
  const label = statusProviderName(provider) || provider;
  const who = email ? (' (' + email + ')') : '';
  if (!confirm(tr('status.logout.confirm', { who: label + who }))) {
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const r = await api('/api/accounts/logout', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    });
    if (r.note || trField(r, 'message')) {
      alert(r.note || trField(r, 'message'));
    } else if (!r.ok) {
      alert(tr('status.logout.failed', { error: r.error || 'unknown' }));
    }
  } catch (e) {
    alert(tr('status.logout.failed', { error: e.message }));
  }
  await refreshProviderAuthMap();
  fetchAccounts();
}

// PROFILE_SWITCH_v1: saved agy sign-ins and one-click switching. Usage is a snapshot from when the account was last active (PROFILE_USAGE_v1).
async function loadProfiles(provider) {
  try {
    const res = await api('/api/accounts/profiles?model=' + encodeURIComponent(statusModel()));
    if (currentStatusProvider() !== provider || !res.ok || !(res.profiles || []).length) return;
    const wrap = document.createElement('div');
    wrap.className = 'status-item';
    wrap.innerHTML = '<div class="status-item-meta">' + escapeHtml(tr('status.profiles.head')) + '</div>';
    res.profiles.forEach(p => {
      const row = document.createElement('div');
      row.className = 'acct-prof';
      const rows = (p.usage && p.usage.rows) || [];
      const view = p.usage && p.usage.view;
      const usage = view ? escapeHtml(view.headline) : rows.slice(0, 3).map(r => escapeHtml(trField(r, 'group')) + ' ' + escapeHtml(trField(r, 'remaining_pct'))).join(' · ') + (rows.length > 3 ? ' +' + (rows.length - 3) : '');
      const seen = p.usage ? escapeHtml(tr('status.ago', { age: fmtAge(Date.now() / 1000 - p.usage.checked_at) })) : '';
      row.innerHTML = '<div class="acct-prof-main"><div class="acct-prof-email">' + escapeHtml(p.email) + (p.active ? ' <span class="acct-badge ok">' + escapeHtml(tr('status.profiles.active')) + '</span>' : '') + '</div>' +
        '<div class="acct-prof-usage">' + (usage ? usage + '<span class="acct-prof-seen"> · ' + seen + '</span>' : escapeHtml(tr('status.profiles.no_usage'))) + '</div></div>';
      if (!p.active) {
        const btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'art-btn acct-prof-btn';
        btn.textContent = tr('status.profiles.switch');
        btn.addEventListener('click', () => switchProfile(provider, p.email, btn));
        row.appendChild(btn);
      }
      wrap.appendChild(row);
    });
    statusAccountsEl.appendChild(wrap);
  } catch (_) { /* the list is extra: the account card stays as it is */ }
}

async function switchProfile(provider, email, btn) {
  if (!confirm(tr('status.profiles.confirm', { email }))) return;
  if (btn) btn.disabled = true;
  try {
    const r = await api('/api/accounts/switch', { method: 'POST', body: JSON.stringify({ target: email }) });
    if (!r.ok) alert(tr('status.profiles.failed', { error: r.error || 'unknown' }));
  } catch (e) {
    alert(tr('status.profiles.failed', { error: e.message }));
  }
  await refreshProviderAuthMap();
  fetchAccounts();
  if (typeof fetchUsage === 'function') fetchUsage(true);
}

// Account: the current sign-in + the last account change + (agy) automatic restarts
function renderAccounts(res, provider) {
  if (!statusAccountsEl) return;
  statusAccountsEl.innerHTML = '';
  const pv = (res.providers || {})[provider];
  if (!pv) {
    // API-key providers (omniroute and the like): no sign-in account and no CLI process
    statusAccountsEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('status.acct.api_key')) + '</div>';
    if (statusProcsEl) statusProcsEl.hidden = true;
    return;
  }
  const when = s => s ? new Date(s * 1000).toLocaleString(I18N_LANG) : '?';
  const cur = pv.current || {};
  const box = document.createElement('div');
  box.className = 'status-item';
  if (cur.ok) {
    const exp = cur.expires_at ? tr('status.acct.token_expires', { when: when(cur.expires_at) }) : '';
    const disReason = providerDisabledReason(provider);
    const badge = disReason
      ? ' <span class="acct-badge stale">' + escapeHtml(tr('status.acct.unusable', { reason: disReason })) + '</span>'
      : '';
    box.innerHTML =
      '<div class="status-item-meta">' + escapeHtml(tr('status.acct.signed_in')) + (cur.plan ? ' · ' + escapeHtml(cur.plan) : '') + badge + '</div>' +
      '<div class="acct-current">' + escapeHtml(cur.email) + '</div>' +
      '<div class="status-item-preview">' + escapeHtml(cur.source || '') +
      (cur.file_mtime ? '\n' + escapeHtml(tr('status.acct.file_updated', { when: when(cur.file_mtime) })) : '') + escapeHtml(exp) + '</div>';
  } else {
    box.innerHTML = '<div class="status-item-meta">' + escapeHtml(tr('status.acct.signed_in')) + '</div><div class="acct-current">' +
      escapeHtml(trField(cur, 'error') || tr('common.unknown')) + '</div>';
  }
  if (pv.changed_from && pv.changed_at && (Date.now() / 1000 - pv.changed_at) < 7 * 86400) {
    const chg = document.createElement('div');
    chg.className = 'status-item-preview';
    chg.textContent = tr('status.acct.changed', { from: pv.changed_from, to: cur.email || '?', when: when(pv.changed_at) });
    box.appendChild(chg);
  }
  // ACCOUNTS_LOGIN_v1: logout when logged in; login button + panel when not.
  const actions = document.createElement('div');
  actions.className = 'status-item-actions';
  if (cur.ok) {
    const logoutBtn = document.createElement('button');
    logoutBtn.type = 'button';
    logoutBtn.className = 'danger';
    logoutBtn.textContent = tr('status.logout.button');
    logoutBtn.title = tr('status.logout.title', { provider: statusProviderName(provider) });
    logoutBtn.addEventListener('click', () => logoutAccount(provider, cur.email, logoutBtn));
    actions.appendChild(logoutBtn);
  } else {
    const loginHint = document.createElement('span');
    loginHint.className = 'status-hint';
    loginHint.textContent = tr('status.login.signed_out');
    actions.appendChild(loginHint);
    const loginBtn = document.createElement('button');
    loginBtn.type = 'button';
    loginBtn.className = 'art-btn';
    loginBtn.textContent = tr('status.login.button');
    loginBtn.title = tr('status.login.title_cli', { provider: statusProviderName(provider) });
    loginBtn.addEventListener('click', () => {
      // Avoid stacking panels
      const prev = statusAccountsEl && statusAccountsEl.querySelector('.login-panel[data-provider="' + provider + '"]');
      if (prev) prev.remove();
      startLogin(provider);
    });
    actions.appendChild(loginBtn);
  }
  box.appendChild(actions);
  statusAccountsEl.appendChild(box);
  if (provider === 'agy') loadProfiles(provider);

  const auto = res.auto_recycle || {};
  if (provider === 'agy' && auto.total > 0 && auto.last_at) {
    const note = document.createElement('div');
    note.className = 'status-hint';
    note.textContent = tr('status.acct.auto_restart', { time: fmtTime(auto.last_at * 1000), n: auto.last_count, total: auto.total })
      + (auto.enabled === false ? tr('status.acct.auto_off') : '');
    statusAccountsEl.appendChild(note);
  }
  renderProcs(pv);
}

// Processes: folded so a long list does not push usage away; it opens by itself when an old-account warning shows.
function renderProcs(pv) {
  if (!statusProcsEl || !statusProcListEl) return;
  const procs = pv.processes || [];
  const hasEvidence = pv.account_evidence === 'log';
  const stale = pv.stale_count || 0;
  const predates = pv.predates_count || 0;
  statusProcsEl.hidden = false;
  if (statusProcsSummaryEl) {
    statusProcsSummaryEl.innerHTML = escapeHtml(tr('status.proc.count', { n: procs.length })) +
      (stale ? ' <span class="acct-badge stale">' + escapeHtml(tr('status.proc.stale_count', { n: stale })) + '</span>' : '') +
      (predates ? ' <span class="acct-badge warn">' + escapeHtml(tr('status.proc.predates_count', { n: predates })) + '</span>' : '');
  }
  if (stale) statusProcsEl.open = true;  // a warning is never folded away
  statusProcListEl.innerHTML = '';

  if (stale > 0) {
    const ownedStale = procs.filter(p => p.stale && (p.owner === 'session' || p.owner === 'standby')).length;
    const warn = document.createElement('div');
    warn.className = 'status-item acct-warn';
    warn.innerHTML =
      '<div class="status-item-name">' + escapeHtml(tr('status.proc.stale_head', { n: stale })) + '</div>' +
      '<div class="status-item-preview">' + escapeHtml(tr('status.proc.stale_hint')) + '</div>';
    if (ownedStale) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'art-filter-btn';
      btn.textContent = tr('status.proc.recycle', { n: ownedStale });
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const r = await api('/api/accounts/recycle', { method: 'POST', body: JSON.stringify({}) });
          if (r.skipped_busy && r.skipped_busy.length) alert(tr('status.proc.skipped_busy', { n: r.skipped_busy.length }));
        } catch (e) { alert(tr('status.proc.recycle_failed', { error: e.message })); }
        fetchAccounts();
      });
      warn.appendChild(btn);
    }
    statusProcListEl.appendChild(warn);
  }
  if (predates > 0 && pv.changed_at) {
    const note = document.createElement('div');
    note.className = 'status-hint';
    note.textContent = tr('status.proc.predates_note', { when: new Date(pv.changed_at * 1000).toLocaleString(I18N_LANG), n: predates });
    statusProcListEl.appendChild(note);
  }
  if (!procs.length) {
    const none = document.createElement('div');
    none.className = 'status-hint';
    none.textContent = tr('status.proc.none');
    statusProcListEl.appendChild(none);
  }
  procs.forEach(p => statusProcListEl.appendChild(acctProcRow(p, hasEvidence)));
}

// the agent (every turn / when needed). Editable only where the protected-path registry allows (the server decides);
// read-only items say why.
const INSTRUCTION_LAYER_LABEL = i18nTable('status.instr.layer');

async function loadInstructions() {
  if (!statusInstructionsEl) return;
  let res;
  try {
    res = await api('/api/instructions');
  } catch (e) {
    statusInstructionsEl.textContent = tr('status.instr.load_failed', { error: e.message || e });
    return;
  }
  const items = (res.items || []).filter(x => x.scope ? x.scope === 'system' : (!x.id.startsWith('characters/') && !x.id.startsWith('roles/')));
  statusInstructionsEl.textContent = '';
  ['always', 'on_demand', 'private'].forEach(layer => {
    const group = items.filter(x => x.layer === layer);
    if (!group.length) return;
    statusInstructionsEl.appendChild(obsNode('div', 'instr-layer', INSTRUCTION_LAYER_LABEL[layer]));
    group.forEach(x => statusInstructionsEl.appendChild(renderInstruction(x)));
  });
}

// One line each (title · badge · size), the whole text on click: the status tab stays short (STATUS_TEAM_TAB_v1).
function renderInstruction(x, open) {
  const item = obsNode('details', 'status-item instr-item');
  if (open) item.open = true;
  const head = obsNode('summary', 'status-item-head');
  head.appendChild(obsNode('span', 'status-item-name', x.title));
  head.appendChild(obsNode('span', 'instr-badge ' + (x.editable ? 'rw' : 'ro'), x.editable ? tr('status.instr.editable') : tr('status.instr.readonly')));
  head.appendChild(obsNode('span', 'status-item-meta', (x.size || 0) + ' B'));
  item.appendChild(head);
  const meta = [x.path || tr('status.instr.generated'), x.mtime ? new Date(x.mtime * 1000).toLocaleString(I18N_LANG) : ''].filter(Boolean).join(' · ');
  const metaRow = obsNode('div', 'status-item-head');
  metaRow.appendChild(obsNode('span', 'status-item-meta', meta));
  const actions = obsNode('div', 'status-item-actions');
  metaRow.appendChild(actions);
  item.appendChild(metaRow);
  if (!x.editable && x.reason) item.appendChild(obsNode('div', 'instr-reason', x.reason));
  const body = obsNode('pre', 'instr-body', x.content || tr('status.instr.empty'));
  item.appendChild(body);
  if (x.editable) {
    const edit = obsNode('button', 'art-btn art-btn-xs', tr('common.edit'));
    edit.type = 'button';
    edit.addEventListener('click', () => editInstruction(x, body, actions));
    actions.appendChild(edit);
  }
  return item;
}

function editInstruction(x, body, actions) {
  const ta = document.createElement('textarea');
  ta.className = 'status-edit-area';
  ta.value = x.content || '';
  body.replaceWith(ta);
  actions.textContent = '';
  const save = obsNode('button', 'art-btn art-btn-xs primary', tr('common.save'));
  save.type = 'button';
  const cancel = obsNode('button', 'art-btn art-btn-xs', tr('common.cancel'));
  cancel.type = 'button';
  actions.appendChild(save);
  actions.appendChild(cancel);
  cancel.addEventListener('click', () => { loadInstructions(); if (currentTab === 'team') loadTeam(); });
  save.addEventListener('click', async () => {
    save.disabled = true;
    save.textContent = tr('common.saving');
    try {
      await api('/api/instructions/' + encodeURIComponent(x.id), { method: 'PUT', body: JSON.stringify({ content: ta.value }) });
      addActivity(tr('status.instr.saved', { title: x.title, when: x.layer === 'always' ? tr('status.instr.next_turn') : tr('status.instr.next_read') }));
      loadInstructions();
      if (currentTab === 'team') loadTeam();
    } catch (e) {
      save.disabled = false;
      save.textContent = tr('common.save');
      await alertModal(tr('common.save_failed', { error: e.message || e }));
    }
  });
}

// STATUS_TEAM_TAB_v1: the PD and its experts. Each card: the brain list (used top-down; quota, limits or silence
// hand the turn to the next) and the character file. The operator edits brains here; the PD cannot.
function renderStatusSkills(skills) {
  if (!statusSkillsEl) return;
  statusSkillsEl.innerHTML = '';
  skills.forEach(s => {
    const item = document.createElement('div');
    item.className = 'status-item';
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(s.name) + '</span>' +
      '<button class="status-toggle ' + (s.enabled ? 'on' : 'off') + '" data-toggle-skill="' + escapeHtml(s.name) + '" type="button" title="' + escapeHtml(s.enabled ? tr('status.skill.off') : tr('status.skill.on')) + '">' +
      '<span class="status-toggle-label" style="font-size:.75rem;color:var(--muted)">' + (s.enabled ? 'ON' : 'OFF') + '</span>' +
      '<span class="switch-ui"></span>' +
      '</button>' +
      '</div>' +
      (s.desc ? '<div class="status-item-preview">' + escapeHtml(s.desc) + '</div>' : '');
    statusSkillsEl.appendChild(item);
  });
  statusSkillsEl.querySelectorAll('[data-toggle-skill]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.getAttribute('data-toggle-skill');
      btn.disabled = true;
      try {
        await api('/api/skills/' + encodeURIComponent(name) + '/toggle', { method: 'POST', body: '{}' });
        addActivity(tr('status.skill.toggled', { name }));
        fetchSelfStatus();
      } catch (e) {
        await alertModal(tr('status.skill.toggle_failed', { error: e.message }));
        btn.disabled = false;
      }
    });
  });
}

function renderStatusMcp(mcpList) {
  if (!statusMcpEl) return;
  statusMcpEl.innerHTML = '';
  if (!mcpList.length) {
    statusMcpEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('status.mcp.none')) + '</div>';
    return;
  }
  mcpList.forEach(m => {
    const item = document.createElement('div');
    item.className = 'status-item';
    const isCore = m.name === 'nas';
    const tools = Array.isArray(m.tools) ? m.tools : [];
    const count = (typeof m.tool_count === 'number') ? m.tool_count : tools.length;
    const head = document.createElement('div');
    head.className = 'status-item-head';
    head.innerHTML =
      '<span class="status-item-name">' + escapeHtml(m.name) + (isCore ? ' (core)' : '') + '</span>' +
      (isCore ? '' : '<button class="art-btn" data-del-mcp="' + escapeHtml(m.name) + '" type="button">' + escapeHtml(tr('common.delete')) + '</button>');
    item.appendChild(head);
    const preview = document.createElement('div');
    preview.className = 'status-item-preview';
    preview.textContent = (m.serverUrl || '') + (m.disabled ? ' · disabled' : '') +
      (count ? tr('status.mcp.tools', { n: count }) : tr('status.mcp.no_tools'));
    item.appendChild(preview);
    const details = document.createElement('details');
    details.className = 'status-tools';
    const summary = document.createElement('summary');
    summary.textContent = count ? tr('status.mcp.tool_list', { n: count }) : tr('status.mcp.tool_list_empty');
    details.appendChild(summary);
    if (tools.length) {
      const ul = document.createElement('ul');
      ul.className = 'status-tool-list';
      tools.forEach(t => {
        const li = document.createElement('li');
        li.className = 'status-tool-row';
        const n = document.createElement('code');
        n.className = 'status-tool-name';
        n.textContent = t.name || '';
        li.appendChild(n);
        if (t.description) {
          const d = document.createElement('div');
          d.className = 'status-tool-desc';
          d.textContent = t.description;
          li.appendChild(d);
        }
        ul.appendChild(li);
      });
      details.appendChild(ul);
    } else {
      const hint = document.createElement('div');
      hint.className = 'status-hint';
      hint.textContent = isCore
        ? tr('status.mcp.core_failed')
        : tr('status.mcp.remote_none');
      details.appendChild(hint);
    }
    item.appendChild(details);
    statusMcpEl.appendChild(item);
  });
  statusMcpEl.querySelectorAll('[data-del-mcp]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.getAttribute('data-del-mcp');
      if (!(await confirmModal(tr('status.mcp.delete_confirm', { name }), { confirmLabel: tr('common.delete') }))) return;
      try {
        await api('/api/mcp/' + encodeURIComponent(name), { method: 'DELETE' });
        addActivity(tr('status.mcp.deleted', { name }));
        fetchSelfStatus();
      } catch (e) {
        await alertModal(tr('common.delete_failed', { error: e.message }));
      }
    });
  });
}

function renderStatusHooks(hooks, plugins) {
  if (!statusHooksEl) return;
  statusHooksEl.innerHTML = '';
  hooks = hooks || {};
  plugins = plugins || {};
  const note = document.createElement('div');
  note.className = 'status-hint';
  note.textContent = hooks.note || '';
  statusHooksEl.appendChild(note);
  if (plugins.note) {
    const pn = document.createElement('div');
    pn.className = 'status-hint';
    pn.textContent = plugins.note;
    statusHooksEl.appendChild(pn);
  }
  const events = Array.isArray(hooks.supported_events) ? hooks.supported_events : [];
  if (events.length) {
    const chipRow = document.createElement('div');
    chipRow.className = 'status-hook-events';
    events.forEach(ev => {
      const chip = document.createElement('span');
      chip.className = 'status-hook-chip';
      chip.textContent = ev;
      chipRow.appendChild(chip);
    });
    statusHooksEl.appendChild(chipRow);
  }
  const configured = Array.isArray(hooks.configured) ? hooks.configured : [];
  const box = document.createElement('div');
  box.className = 'status-item';
  const head = document.createElement('div');
  head.className = 'status-item-meta';
  head.textContent = tr('status.hooks.count', { n: configured.length }) +
    (hooks.path ? (' · ' + String(hooks.path).split('/').slice(-3).join('/')) : '');
  box.appendChild(head);
  const details = document.createElement('details');
  details.className = 'status-tools';
  const summary = document.createElement('summary');
  summary.textContent = configured.length ? tr('status.hooks.detail', { n: configured.length }) : tr('status.hooks.detail_none');
  details.appendChild(summary);
  if (configured.length) {
    const ul = document.createElement('ul');
    ul.className = 'status-tool-list';
    configured.forEach(h => {
      const li = document.createElement('li');
      li.className = 'status-tool-row';
      const n = document.createElement('code');
      n.className = 'status-tool-name';
      n.textContent = (h.name || '') + (h.enabled === false ? ' (off)' : '');
      li.appendChild(n);
      const ev = Array.isArray(h.events) ? h.events : [];
      if (ev.length) {
        const d = document.createElement('div');
        d.className = 'status-tool-desc';
        d.textContent = tr('status.hooks.events', { list: ev.join(', ') });
        li.appendChild(d);
      }
      ul.appendChild(li);
    });
    details.appendChild(ul);
  } else {
    const hint = document.createElement('div');
    hint.className = 'status-hint';
    hint.textContent = tr('status.hooks.empty');
    details.appendChild(hint);
  }
  box.appendChild(details);
  statusHooksEl.appendChild(box);
}



// Styled replacement for window.confirm() -- destructive actions (session
// delete, MCP server delete, host defibrillate) used the browser's native
// dialog, which drops unstyled OS chrome into an otherwise fully-skinned
// dark UI and, worse, can't be dismissed with the same Escape reflex every
// other overlay in this app supports (impeccable critique P1, 2026-09-17).
// Falls back to window.confirm if the modal markup is somehow missing.
