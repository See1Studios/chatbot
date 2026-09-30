// app-status.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
async function fetchSelfStatus() {
  if (!statusPaneEl) return;
  try {
    const res = await api('/api/self-status');
    loadInstructions();
    renderStatusSkills(res.skills || []);
    if (statusSkillLibHintEl) {
      statusSkillLibHintEl.textContent = '호스트 스킬 라이브러리 ' + (res.host_skill_library_count || 0) + '개 (읽기 전용)';
    }
    renderStatusMcp(res.mcp || []);
    renderStatusHooks(res.hooks || {}, res.plugins || {});
    // observation/tickets live on Evolution tab (STATUS_EVOLUTION_TAB_v1)
    statusLoaded = true;
  } catch (e) {
    if (statusInstructionsEl) statusInstructionsEl.textContent = '상태 로드 실패: ' + e.message;
  }
}

// 상태 탭은 "지금 쓰는 프로바이더" 한 곳만 보여 준다: 계정 → 사용량 → 프로세스.
// 서버가 토큰 파일의 이메일과 각 agy 프로세스가 인증한 계정을 대조해 stale 여부를
// 계산해 준다 -- 여기서는 그리기만 한다.
const ACCT_OWNER_LABEL = { session: '세션', standby: '대기(standby)', worker: '위임 작업자', 'chatbot-other': '챗봇 임시', external: '외부' };

// 상태 탭이 보여 주는 제공자. 기본은 지금 대화 중인 제공자를 따라가고, 칩으로 다른 제공자를
// "보기만" 할 수 있다 -- selectProvider()를 부르지 않으므로 서버 세션(제공자·conversation_id)은 그대로다.
let statusViewProvider = null;
function chatProvider() { return providerEl ? providerEl.value : defaultProviderId; }
function currentStatusProvider() { return statusViewProvider || chatProvider(); }

// 상단 브랜드 영역과 같은 표기(agy=Antigravity). 제공자 이름은 벤더이지 페르소나가 아니다.
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
    b.title = (p.id === chat ? '지금 대화 중인 제공자' : '상태 조회 — 대화 제공자는 바꾸지 않아요')
      + (blockReason ? ' · ' + blockReason : '');
    b.setAttribute('aria-pressed', String(p.id === viewing));
    // Always selectable: blocked providers are still viewable on Status.
    b.disabled = false;
    b.addEventListener('click', () => setStatusViewProvider(p.id));
    statusPickerEl.appendChild(b);
  });
}

// 다른 제공자의 상태를 보기만 한다 (대화 세션은 건드리지 않는다).
function setStatusViewProvider(id) {
  statusViewProvider = (id === chatProvider()) ? null : id;
  refreshProviderStatus();
}

// 대화의 제공자가 (코드로) 바뀌면 select의 onchange가 안 돌므로 여기서 직접 다시 그린다. 상태 조회 선택은 대화를 따라간다.
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
  if (sec < 90) return sec + '초';
  if (sec < 5400) return Math.round(sec / 60) + '분';
  if (sec < 172800) return (sec / 3600).toFixed(1) + '시간';
  return (sec / 86400).toFixed(1) + '일';
}

async function fetchAccounts() {
  if (!statusAccountsEl) return;
  const provider = currentStatusProvider();
  if (statusProviderTitleEl) statusProviderTitleEl.textContent = statusProviderName(provider) + (statusViewProvider ? ' · 대화와 다른 제공자' : '');
  // LOGIN_PASTE_KEEP_v2: detach in-flight login panel before wipe so paste/URL survive refresh.
  const keepLogin = statusAccountsEl.querySelector('.login-panel[data-provider="' + provider + '"]');
  if (keepLogin) keepLogin.remove();
  statusAccountsEl.innerHTML = '<div class="status-hint">불러오는 중…</div>';
  try {
    const res = await api('/api/accounts?provider=' + encodeURIComponent(provider));
    if (currentStatusProvider() !== provider) return;  // 응답이 늦는 사이 프로바이더가 바뀜
    renderAccounts(res, provider);
    if (keepLogin && (_loginPollTimers[provider] || ((_loginPanelState[provider] || {}).state === 'pending'))) {
      statusAccountsEl.appendChild(keepLogin);
    }
  } catch (e) {
    statusAccountsEl.innerHTML = '<div class="status-hint">계정 정보 로드 실패: ' + escapeHtml(e.message) + '</div>';
    if (statusProcsEl) statusProcsEl.hidden = true;
  }
}

function acctProcRow(p, hasEvidence) {
  const item = document.createElement('div');
  item.className = 'status-item' + (p.stale ? ' acct-warn' : '');
  const owner = ACCT_OWNER_LABEL[p.owner] || p.owner;
  let badge;
  if (p.account) {
    badge = '<span class="acct-badge ' + (p.stale ? 'stale' : 'ok') + '">' + escapeHtml(p.account) + (p.stale ? ' · 옛 계정' : '') + '</span>';
  } else if (p.predates_change) {
    badge = '<span class="acct-badge warn">로그인 변경 전에 시작됨</span>';
  } else {
    badge = '<span class="acct-badge">' + (hasEvidence ? '계정 불명(로그 없음)' : '계정 알 수 없음') + '</span>';
  }
  const who = p.sid ? ' ' + escapeHtml(p.sid) : '';
  item.innerHTML =
    '<div class="status-item-head"><span class="status-item-name">pid ' + p.pid + ' · ' + escapeHtml(owner) + who + '</span>' + badge + '</div>' +
    '<div class="status-item-preview">경과 ' + escapeHtml(fmtAge(p.age_sec)) + ' · tty ' + escapeHtml(p.tty) +
    ' · 부모 ' + escapeHtml(p.parent || '?') + '(' + p.ppid + ')' + (p.busy ? ' · 작업 중' : '') + '\n' + escapeHtml(p.cmd) + '</div>';
  if (p.kill_cmd) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'art-filter-btn';
    btn.textContent = '종료 명령 복사: ' + p.kill_cmd;
    btn.addEventListener('click', () => copyText(p.kill_cmd).then(() => { btn.textContent = '복사됨'; }, () => { btn.textContent = p.kill_cmd; }));
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
  if (mode === 'oauth_paste') return 'OAuth → 코드 붙여넣기';
  if (mode === 'oauth_callback') return '브라우저 OAuth (localhost 콜백)';
  if (mode === 'device_code') return '디바이스 코드 인증';
  return mode || '';
}

function buildLoginPanel(provider) {
  const panel = document.createElement('div');
  panel.className = 'login-panel';
  panel.dataset.provider = provider;
  panel.innerHTML =
    '<div class="login-panel-head"><strong>로그인</strong> <span class="login-panel-mode"></span></div>' +
    '<div class="login-panel-msg status-hint">준비 중…</div>' +
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
  if (msgEl) msgEl.textContent = st.message_ko || '';
  if (errEl) {
    if (st.error && (st.state === 'failed' || st.state === 'superseded')) {
      errEl.hidden = false;
      errEl.textContent = st.error;
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
    btn.textContent = '복사';
    btn.addEventListener('click', () => copyText(value).then(() => {
      btn.textContent = '복사됨';
      setTimeout(() => { btn.textContent = '복사'; }, 1200);
    }, () => { btn.textContent = '실패'; }));
    row.appendChild(lab);
    row.appendChild(val);
    row.appendChild(btn);
    fields.appendChild(row);
  };

  addCopyRow('인증 URL', st.authorize_url, true);
  if (st.verification_uri && st.verification_uri !== st.authorize_url) {
    addCopyRow('확인 URL', st.verification_uri, true);
  }
  addCopyRow('확인 코드', st.user_code, false);
  if (st.callback_port) {
    addCopyRow('콜백 포트', String(st.callback_port), false);
  }

  if (st.mode === 'oauth_paste' && st.state === 'pending') {
    const row = document.createElement('div');
    row.className = 'login-row login-paste';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'login-code-input';
    input.placeholder = '인증 코드 붙여넣기';
    input.autocomplete = 'off';
    const submit = document.createElement('button');
    submit.type = 'button';
    submit.className = 'art-btn';
    submit.textContent = '제출';
    const doSubmit = async () => {
      const code = (input.value || '').trim();
      if (!code) { alert('코드를 입력해 주세요.'); return; }
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
          alert((r.error || r.message_ko || '코드 제출 실패'));
        } else if (r.message_ko) {
          const msgEl = panel.querySelector('.login-panel-msg');
          if (msgEl) msgEl.textContent = r.message_ko;
        }
      } catch (e) {
        alert('코드 제출 실패: ' + e.message);
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
    cancelBtn.textContent = '취소';
    cancelBtn.addEventListener('click', () => cancelLogin(st.provider, st.login_id, panel));
    actions.appendChild(cancelBtn);
    if (st.expires_in != null) {
      const ttl = document.createElement('span');
      ttl.className = 'status-hint';
      ttl.textContent = '남은 시간 약 ' + Math.max(0, Math.round(st.expires_in / 60)) + '분';
      actions.appendChild(ttl);
    }
  } else if (st.state === 'succeeded') {
    const ok = document.createElement('span');
    ok.className = 'status-hint';
    ok.textContent = '완료 — 계정 새로고침 중…';
    actions.appendChild(ok);
  } else if (st.state === 'failed' || st.state === 'cancelled') {
    const again = document.createElement('button');
    again.type = 'button';
    again.className = 'art-btn';
    again.textContent = '다시 시도';
    again.addEventListener('click', () => startLogin(st.provider, panel));
    actions.appendChild(again);
  }
}

async function onLoginSucceeded(provider, st) {
  stopLoginPoll(provider);
  addActivity((statusProviderName(provider) || provider) + ' 로그인 완료', 'system');
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
  addActivity((statusProviderName(provider) || provider) + ' 로그인 취소', 'system');
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
          addActivity((statusProviderName(provider) || provider) + ' 로그인 실패: ' + (st.error || ''), 'warn');
        } else if (st.state === 'superseded') {
          addActivity((statusProviderName(provider) || provider) + ' 로그인 시도가 다른 곳에서 새로 시작한 시도로 대체됐어요', 'warn');
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
  panel.querySelector('.login-panel-msg').textContent = '로그인 시작 중…';
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
      addActivity((statusProviderName(provider) || provider) + ' 로그인 시작 (' + loginModeHint(st.mode) + ')', 'system');
    } else if (st.state === 'succeeded') {
      onLoginSucceeded(provider, st);
    } else if (!st.ok) {
      alert('로그인 시작 실패: ' + (st.error || 'unknown'));
    }
  } catch (e) {
    alert('로그인 시작 실패: ' + e.message);
    if (panel && panel.parentNode) panel.remove();
  }
}


async function logoutAccount(provider, email, btn) {
  const label = statusProviderName(provider) || provider;
  const who = email ? (' (' + email + ')') : '';
  if (!confirm(label + who + ' 에서 로그아웃할까요?\n\n이 호스트의 해당 CLI 인증이 해제됩니다. 진행 중인 대화가 있으면 프로세스를 다시 띄워야 할 수 있어요.')) {
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const r = await api('/api/accounts/logout', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    });
    if (r.note || r.message_ko) {
      alert(r.note || r.message_ko);
    } else if (!r.ok) {
      alert('로그아웃 실패: ' + (r.error || 'unknown'));
    }
  } catch (e) {
    alert('로그아웃 실패: ' + e.message);
  }
  await refreshProviderAuthMap();
  fetchAccounts();
}

// 계정: 현재 로그인 + 마지막 계정 변경 + (agy) 자동 재시작 기록
function renderAccounts(res, provider) {
  if (!statusAccountsEl) return;
  statusAccountsEl.innerHTML = '';
  const pv = (res.providers || {})[provider];
  if (!pv) {
    // API 키 방식(omniroute 등): 로그인 계정도 CLI 프로세스도 없다
    statusAccountsEl.innerHTML = '<div class="status-hint">이 프로바이더는 로그인 계정이 없어요 (API 키 방식).</div>';
    if (statusProcsEl) statusProcsEl.hidden = true;
    return;
  }
  const when = s => s ? new Date(s * 1000).toLocaleString('ko-KR') : '?';
  const cur = pv.current || {};
  const box = document.createElement('div');
  box.className = 'status-item';
  if (cur.ok) {
    const exp = cur.expires_at ? ' · 액세스 토큰 만료 ' + when(cur.expires_at) : '';
    const disReason = providerDisabledReason(provider);
    const badge = disReason
      ? ' <span class="acct-badge stale">사용 불가 (' + escapeHtml(disReason) + ')</span>'
      : '';
    box.innerHTML =
      '<div class="status-item-meta">로그인 계정' + (cur.plan ? ' · ' + escapeHtml(cur.plan) : '') + badge + '</div>' +
      '<div class="acct-current">' + escapeHtml(cur.email) + '</div>' +
      '<div class="status-item-preview">' + escapeHtml(cur.source || '') +
      (cur.file_mtime ? '\n파일 갱신 ' + escapeHtml(when(cur.file_mtime)) : '') + escapeHtml(exp) + '</div>';
  } else {
    box.innerHTML = '<div class="status-item-meta">로그인 계정</div><div class="acct-current">' +
      escapeHtml(cur.error || '알 수 없음') + '</div>';
  }
  if (pv.changed_from && pv.changed_at && (Date.now() / 1000 - pv.changed_at) < 7 * 86400) {
    const chg = document.createElement('div');
    chg.className = 'status-item-preview';
    chg.textContent = '계정 변경 관측: ' + pv.changed_from + ' → ' + (cur.email || '?') + ' (' + when(pv.changed_at) + ')';
    box.appendChild(chg);
  }
  // ACCOUNTS_LOGIN_v1: logout when logged in; login button + panel when not.
  const actions = document.createElement('div');
  actions.className = 'status-item-actions';
  if (cur.ok) {
    const logoutBtn = document.createElement('button');
    logoutBtn.type = 'button';
    logoutBtn.className = 'danger';
    logoutBtn.textContent = '로그아웃';
    logoutBtn.title = statusProviderName(provider) + ' CLI 로그아웃';
    logoutBtn.addEventListener('click', () => logoutAccount(provider, cur.email, logoutBtn));
    actions.appendChild(logoutBtn);
  } else {
    const loginHint = document.createElement('span');
    loginHint.className = 'status-hint';
    loginHint.textContent = '로그인되지 않음 — 대화/세션/개선은 잠겨 있어요.';
    actions.appendChild(loginHint);
    const loginBtn = document.createElement('button');
    loginBtn.type = 'button';
    loginBtn.className = 'art-btn';
    loginBtn.textContent = '로그인';
    loginBtn.title = statusProviderName(provider) + ' CLI 로그인';
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

  const auto = res.auto_recycle || {};
  if (provider === 'agy' && auto.total > 0 && auto.last_at) {
    const note = document.createElement('div');
    note.className = 'status-hint';
    note.textContent = '자동 재시작: 마지막 ' + new Date(auto.last_at * 1000).toLocaleTimeString('ko-KR') + '에 유휴 agy ' +
      auto.last_count + '개 (계정 변경 감지) · 누적 ' + auto.total + '개' + (auto.enabled === false ? ' · 현재 꺼짐' : '');
    statusAccountsEl.appendChild(note);
  }
  renderProcs(pv);
}

// 프로세스: 목록이 길어 사용량을 밀어내지 않도록 접이식. 옛 계정 경고가 있으면 자동으로 펼친다.
function renderProcs(pv) {
  if (!statusProcsEl || !statusProcListEl) return;
  const procs = pv.processes || [];
  const hasEvidence = pv.account_evidence === 'log';
  const stale = pv.stale_count || 0;
  const predates = pv.predates_count || 0;
  statusProcsEl.hidden = false;
  if (statusProcsSummaryEl) {
    statusProcsSummaryEl.innerHTML = '프로세스 ' + procs.length + '개' +
      (stale ? ' <span class="acct-badge stale">옛 계정 ' + stale + '개</span>' : '') +
      (predates ? ' <span class="acct-badge warn">로그인 변경 전 시작 ' + predates + '개</span>' : '');
  }
  if (stale) statusProcsEl.open = true;  // 경고는 접어 두지 않는다
  statusProcListEl.innerHTML = '';

  if (stale > 0) {
    const ownedStale = procs.filter(p => p.stale && (p.owner === 'session' || p.owner === 'standby')).length;
    const warn = document.createElement('div');
    warn.className = 'status-item acct-warn';
    warn.innerHTML =
      '<div class="status-item-name">옛 계정으로 인증된 agy 프로세스 ' + stale + '개</div>' +
      '<div class="status-item-preview">이 프로세스가 토큰을 refresh하면 방금 한 로그인이 옛 계정으로 되돌아갈 수 있어요. ' +
      '외부 프로세스는 종료 명령을 복사해서 직접 실행하세요.</div>';
    if (ownedStale) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'art-filter-btn';
      btn.textContent = '챗봇 소유 ' + ownedStale + '개 재시작 (유휴 세션·대기만)';
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const r = await api('/api/accounts/recycle', { method: 'POST', body: JSON.stringify({}) });
          if (r.skipped_busy && r.skipped_busy.length) alert('작업 중인 세션 ' + r.skipped_busy.length + '개는 건너뛰었어요. 끝난 뒤 다시 눌러 주세요.');
        } catch (e) { alert('재시작 실패: ' + e.message); }
        fetchAccounts();
      });
      warn.appendChild(btn);
    }
    statusProcListEl.appendChild(warn);
  }
  if (predates > 0 && pv.changed_at) {
    const note = document.createElement('div');
    note.className = 'status-hint';
    note.textContent = '계정 변경(' + new Date(pv.changed_at * 1000).toLocaleString('ko-KR') + ' 관측) 이전에 시작된 프로세스 ' + predates +
      '개 — 이 CLI는 프로세스별 계정을 알 수 없어, 옛 자격을 들고 있는지는 시간 기준으로만 표시해요.';
    statusProcListEl.appendChild(note);
  }
  if (!procs.length) {
    const none = document.createElement('div');
    none.className = 'status-hint';
    none.textContent = '실행 중인 프로세스 없음';
    statusProcListEl.appendChild(none);
  }
  procs.forEach(p => statusProcListEl.appendChild(acctProcRow(p, hasEvidence)));
}

async function fetchUsage(force, retryCount) {
  // USAGE_v1: after CLI login the first /cost|app-server call often races auth
  // settle; client default api() timeout (12s) was also shorter than the CLI
  // (30–45s). Retry once + longer timeout; server also retries + avoids
  // long-caching failures.
  if (!statusUsageEl) return;
  retryCount = retryCount || 0;
  const provider = currentStatusProvider();
  statusUsageEl.innerHTML = '<div class="status-hint">불러오는 중… (' + escapeHtml(provider)
    + (retryCount > 0 ? ', 재시도' : '') + ')</div>';
  try {
    const params = new URLSearchParams({provider});
    if (force || retryCount > 0) params.set('force', '1');
    const res = await api('/api/usage?' + params.toString(), { timeoutMs: 55000 });
    if (currentStatusProvider() !== provider) return;
    if ((!res || !res.ok) && res && res.supported !== false && retryCount < 1) {
      setTimeout(() => fetchUsage(true, retryCount + 1), 800);
      return;
    }
    renderStatusUsage(res);
  } catch (e) {
    if (retryCount < 1) {
      setTimeout(() => fetchUsage(true, retryCount + 1), 800);
      return;
    }
    statusUsageEl.innerHTML = '<div class="status-hint">사용량 로드 실패: ' + escapeHtml(e.message) + '</div>';
  }
}

function renderStatusUsage(res) {
  if (!statusUsageEl) return;
  if (!res || !res.ok) {
    // supported:false (Multi-Provider plan Phase 0.5) -- this provider has no
    // one-shot rate-limit report at all (codex as of this writing), not an
    // error worth alarming over.
    const msg = (res && res.supported === false)
      ? (res.error || '이 프로바이더는 사용량 조회를 지원하지 않습니다')
      : '조회 실패: ' + ((res && res.error) || '알 수 없는 오류');
    statusUsageEl.innerHTML = '<div class="status-hint">' + escapeHtml(msg) + '</div>';
    if (usageCheckedAtEl) usageCheckedAtEl.textContent = '';
    return;
  }
  statusUsageEl.innerHTML = '';
  (res.rows || []).forEach(row => {
    const pct = parseInt(row.remaining_pct, 10);
    const pctSafe = isNaN(pct) ? 0 : Math.max(0, Math.min(100, pct));
    const item = document.createElement('div');
    item.className = 'status-item';
    let resetStr = row.reset_at;
    try {
      const d = new Date(row.reset_at);
      if (!isNaN(d.getTime())) resetStr = d.toLocaleString('ko-KR');
    } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(row.group) + ' — ' + escapeHtml(row.limit_type) + '</span>' +
      '<span class="status-item-meta">' + escapeHtml(row.remaining_pct) + ' 남음</span>' +
      '</div>' +
      '<div class="usage-bar-track"><div class="usage-bar-fill' + (pctSafe <= 20 ? ' low' : '') + '" style="transform:scaleX(' + (pctSafe / 100) + ')"></div></div>' +
      '<div class="status-item-preview">리셋: ' + escapeHtml(resetStr) + '</div>';
    statusUsageEl.appendChild(item);
  });
  if (usageCheckedAtEl) {
    const checked = res.checked_at ? new Date(res.checked_at * 1000).toLocaleTimeString('ko-KR') : '';
    usageCheckedAtEl.textContent = checked ? ('마지막 확인: ' + checked) : '';
  }
}

// the agent (every turn / when needed). Editable only where the protected-path registry allows (the server decides);
// read-only items say why.
const INSTRUCTION_LAYER_LABEL = { always: '매 턴 들어가는 것', on_demand: '필요할 때 읽는 것', private: '사적 세션에서만 읽는 것' };

async function loadInstructions() {
  if (!statusInstructionsEl) return;
  let res;
  try {
    res = await api('/api/instructions');
  } catch (e) {
    statusInstructionsEl.textContent = '지침을 불러오지 못했어요 (소생 필요할 수 있음): ' + (e.message || e);
    return;
  }
  const items = res.items || [];
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
  head.appendChild(obsNode('span', 'instr-badge ' + (x.editable ? 'rw' : 'ro'), x.editable ? '편집 가능' : '읽기 전용'));
  head.appendChild(obsNode('span', 'status-item-meta', (x.size || 0) + ' B'));
  item.appendChild(head);
  const meta = [x.path || '자동 생성', x.mtime ? new Date(x.mtime * 1000).toLocaleString('ko-KR') : ''].filter(Boolean).join(' · ');
  const metaRow = obsNode('div', 'status-item-head');
  metaRow.appendChild(obsNode('span', 'status-item-meta', meta));
  const actions = obsNode('div', 'status-item-actions');
  metaRow.appendChild(actions);
  item.appendChild(metaRow);
  if (!x.editable && x.reason) item.appendChild(obsNode('div', 'instr-reason', x.reason));
  const body = obsNode('pre', 'instr-body', x.content || '(비어 있음)');
  item.appendChild(body);
  if (x.editable) {
    const edit = obsNode('button', 'art-btn art-btn-xs', '편집');
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
  const save = obsNode('button', 'art-btn art-btn-xs primary', '저장');
  save.type = 'button';
  const cancel = obsNode('button', 'art-btn art-btn-xs', '취소');
  cancel.type = 'button';
  actions.appendChild(save);
  actions.appendChild(cancel);
  cancel.addEventListener('click', () => { loadInstructions(); if (currentTab === 'team') loadTeam(); });
  save.addEventListener('click', async () => {
    save.disabled = true;
    save.textContent = '저장 중…';
    try {
      await api('/api/instructions/' + encodeURIComponent(x.id), { method: 'PUT', body: JSON.stringify({ content: ta.value }) });
      addActivity(x.title + ' 저장됨 · ' + (x.layer === 'always' ? '다음 턴부터 반영' : '다음에 읽을 때 반영'));
      loadInstructions();
      if (currentTab === 'team') loadTeam();
    } catch (e) {
      save.disabled = false;
      save.textContent = '저장';
      await alertModal('저장 실패: ' + (e.message || e));
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
      '<button class="status-toggle ' + (s.enabled ? 'on' : 'off') + '" data-toggle-skill="' + escapeHtml(s.name) + '" type="button" title="' + (s.enabled ? '스킬 끄기' : '스킬 켜기') + '">' +
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
        addActivity('스킬 ' + name + ' 토글됨 (다음 새 세션부터 반영)');
        fetchSelfStatus();
      } catch (e) {
        await alertModal('토글 실패: ' + e.message);
        btn.disabled = false;
      }
    });
  });
}

function renderStatusMcp(mcpList) {
  if (!statusMcpEl) return;
  statusMcpEl.innerHTML = '';
  if (!mcpList.length) {
    statusMcpEl.innerHTML = '<div class="status-hint">등록된 MCP 서버가 없어요.</div>';
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
      (isCore ? '' : '<button class="art-btn" data-del-mcp="' + escapeHtml(m.name) + '" type="button">삭제</button>');
    item.appendChild(head);
    const preview = document.createElement('div');
    preview.className = 'status-item-preview';
    preview.textContent = (m.serverUrl || '') + (m.disabled ? ' · disabled' : '') +
      (count ? (' · 도구 ' + count + '개') : ' · 도구 목록 없음');
    item.appendChild(preview);
    const details = document.createElement('details');
    details.className = 'status-tools';
    const summary = document.createElement('summary');
    summary.textContent = count ? ('도구 목록 (' + count + ')') : '도구 목록 (비어 있음)';
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
        ? '도구 정의를 불러오지 못했어요.'
        : '원격 서버 tools/list 응답이 없거나 아직 연결되지 않았어요.';
      details.appendChild(hint);
    }
    item.appendChild(details);
    statusMcpEl.appendChild(item);
  });
  statusMcpEl.querySelectorAll('[data-del-mcp]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.getAttribute('data-del-mcp');
      if (!(await confirmModal(name + ' MCP 서버를 삭제할까요?', { confirmLabel: '삭제' }))) return;
      try {
        await api('/api/mcp/' + encodeURIComponent(name), { method: 'DELETE' });
        addActivity('MCP ' + name + ' 삭제됨 (다음 새 세션부터 반영)');
        fetchSelfStatus();
      } catch (e) {
        await alertModal('삭제 실패: ' + e.message);
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
  head.textContent = '워크스페이스 훅 ' + configured.length + '개' +
    (hooks.path ? (' · ' + String(hooks.path).split('/').slice(-3).join('/')) : '');
  box.appendChild(head);
  const details = document.createElement('details');
  details.className = 'status-tools';
  const summary = document.createElement('summary');
  summary.textContent = configured.length ? ('훅 상세 (' + configured.length + ')') : '훅 상세 (설정 없음)';
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
        d.textContent = '이벤트: ' + ev.join(', ');
        li.appendChild(d);
      }
      ul.appendChild(li);
    });
    details.appendChild(ul);
  } else {
    const hint = document.createElement('div');
    hint.className = 'status-hint';
    hint.textContent = 'hooks.json이 비어 있어요. 프로바이더 훅 대신 호스트 관찰/티켓 루프를 씁니다.';
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
