// app-api.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
async function api(path, opts) {
  const url = (BASE_PATH && path.startsWith('/') && !path.startsWith(BASE_PATH)) ? (BASE_PATH + path) : path;
  opts = opts || {};
  // BOOT_HANG_FIX_v1: default timeout so /api/sessions/active cannot freeze boot forever
  const timeoutMs = opts.timeoutMs != null ? opts.timeoutMs : 12000;
  const { timeoutMs: _drop, ...fetchOpts } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  if (fetchOpts.signal) {
    fetchOpts.signal.addEventListener('abort', () => ctrl.abort(), { once: true });
  }
  try {
    const r = await fetch(url, Object.assign({
      headers: { 'Content-Type': 'application/json' },
      signal: ctrl.signal,
    }, fetchOpts));
    if (!r.ok) throw new Error(await r.text() || r.statusText);
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) return r.json();
    return r.text();
  } finally {
    clearTimeout(timer);
  }
}

async function maybeRedirectHardSession(id, info, depth) {
  depth = depth || 0;
  if (depth > 3) return null;
  const hard = Boolean(info && info.weight && info.weight.level === 'hard');
  if (!hard) return null;
  const redir = (info && (info.redirect_session_id || info.successor_session_id)) || '';
  if (redir && redir !== id) {
    rememberSession(redir);
    addActivity('hard 세션 → successor로 이동: ' + redir);
    await openSession(redir, depth + 1, {
      level: 'hard',
      message_ko: '열려던 대화가 너무 길어져서 자동으로 이어진 세션이에요 — 예전 대화 내용은 그대로 보존됩니다.',
    });
    return redir;
  }
  if (hard && !redir) {
    // Auto-redirect on open must land every window/tab on the SAME
    // successor -- a plain createSession() here (old behavior) never links
    // back to `id`, so each window that loaded this hard session before any
    // of them finished would mint its own disconnected new chat (operator:
    // "창을 여러 개 열었더니 각자 다른 새 세션이 시작되고 예전 세션 내용이
    // 안 나옴"). sticky:true asks the server to reuse an already-usable
    // successor instead of forking again -- safe even if two windows race,
    // since the server resolves it under that session's own lock.
    try {
      const res = await api('/api/sessions/' + encodeURIComponent(id) + '/continue', {
        method: 'POST',
        body: JSON.stringify({ model: modelEl.value, sticky: true })
      });
      if (res && res.ok && res.session && res.session.id) {
        const nid = res.session.id;
        rememberSession(nid);
        addActivity('hard 세션 → 자동 이어하기 successor로 이동: ' + nid + (res.reused ? ' (기존 재사용)' : ' (신규)'));
        await openSession(nid, depth + 1, {
          level: 'hard',
          message_ko: '열려던 대화가 너무 길어져서 자동으로 이어진 세션이에요 — 예전 대화 내용은 그대로 보존됩니다.',
        });
        return nid;
      }
    } catch (e) {
      addActivity('자동 이어하기 실패, 새 세션으로 대체: ' + (e.message || e));
    }
    await createSession();
    return 'new';
  }
  return null;
}

function rememberSession(id) {
  sessionId = id || '';
  if (sessionId) {
    localStorage.setItem(SESSION_KEY, sessionId);
  }
  const hubLink = document.getElementById('hubLink');
  if (hubLink) {
    const port80 = '//' + location.hostname + '/';
    hubLink.href = sessionId ? (port80 + '?session=' + encodeURIComponent(sessionId)) : port80;
  }
}

function switchTab(tab) {
  currentTab = tab;
  if ((tab === 'chat' || tab === 'sessions' || tab === 'evolution') && isProviderUseBlocked(chatProvider())) {
    tab = 'status';
    currentTab = 'status';
  }
  if (tabChat) { tabChat.classList.toggle('on', tab === 'chat'); tabChat.setAttribute('aria-selected', String(tab === 'chat')); }
  if (tabArtifacts) { tabArtifacts.classList.toggle('on', tab === 'artifacts'); tabArtifacts.setAttribute('aria-selected', String(tab === 'artifacts')); }
  if (tabActivity) { tabActivity.classList.toggle('on', tab === 'activity'); tabActivity.setAttribute('aria-selected', String(tab === 'activity')); }
  if (tabStatus) { tabStatus.classList.toggle('on', tab === 'status'); tabStatus.setAttribute('aria-selected', String(tab === 'status')); }
  if (tabSessions) { tabSessions.classList.toggle('on', tab === 'sessions'); tabSessions.setAttribute('aria-selected', String(tab === 'sessions')); }
  if (tabEvolution) { tabEvolution.classList.toggle('on', tab === 'evolution'); tabEvolution.setAttribute('aria-selected', String(tab === 'evolution')); }
  if (tabTeam) { tabTeam.classList.toggle('on', tab === 'team'); tabTeam.setAttribute('aria-selected', String(tab === 'team')); }

  if (logEl) logEl.style.display = (tab === 'chat') ? 'flex' : 'none';
  const artifactsPane = document.getElementById('artifacts');
  if (artifactsPane) artifactsPane.style.display = (tab === 'artifacts') ? 'flex' : 'none';
  if (activityPaneEl) activityPaneEl.style.display = (tab === 'activity') ? 'flex' : 'none';
  else if (activityEl) activityEl.style.display = (tab === 'activity') ? 'block' : 'none';
  if (statusPaneEl) statusPaneEl.style.display = (tab === 'status') ? 'flex' : 'none';
  if (sessionsPaneEl) sessionsPaneEl.style.display = (tab === 'sessions') ? 'flex' : 'none';
  if (evolutionPaneEl) evolutionPaneEl.style.display = (tab === 'evolution') ? 'flex' : 'none';
  if (teamPaneEl) teamPaneEl.style.display = (tab === 'team') ? 'flex' : 'none';

  if (tab === 'artifacts') {
    fetchArtifacts(true);
  } else if (tab === 'chat' && logEl) {
    scrollChatToBottom(false);
  } else if (tab === 'activity' && activityEl) {
    activityEl.scrollTop = activityEl.scrollHeight;
  } else if (tab === 'status') {
    fetchSelfStatus();
    renderStatusPicker();
    fetchAccounts();
    fetchUsage(false);
  } else if (tab === 'evolution') {
    fetchEvolution();
  } else if (tab === 'team') {
    loadTeam();
  } else if (tab === 'sessions') {
    fetchSessionsList();
  }
  updateScrollBottomButton();
  placeStopBtn();
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function waitHostBack(maxMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try {
      await api('/healthz');
      return true;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

async function defibrillateHost() {
  if (!(await confirmModal('전기충격(심폐소생)을 실행할까요?\n호스트가 재기동되며 몇 초 연결이 끊깁니다.', { confirmLabel: '실행', danger: false }))) return;
  setProgress('전기충격 · 호스트 소생 중…', true);
  const btn = document.getElementById('defibBtn');
  if (btn) btn.disabled = true;
  try {
    try {
      await api('/api/host/defibrillate', { method: 'POST', body: '{}' });
    } catch (_) {
      /* server may die mid-response — expected */
    }
    addActivity('전기충격 예약 — 호스트 재기동 대기', 'system');
    const ok = await waitHostBack(90000);
    if (!ok) {
      setProgress('소생 시간 초과 · 수동 새로고침 해보세요', true);
      addActivity('소생 실패/시간초과');
      return;
    }
    setProgress('소생 완료 · 세션 재연결…', true);
    await ensureSession();
    setProgress('소생 완료', true);
    addActivity('심폐소생 완료', 'ok');
  } finally {
    if (btn) btn.disabled = false;
  }
}
