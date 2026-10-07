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
    if (ct.includes('application/json')) return trHistory(await r.json());   // I18N_v1: stored server lines
    return r.text();
  } catch (e) {
    // RETRY_LAST_v1: app-retry.js offers a failed message again
    document.dispatchEvent(new CustomEvent('api-failed', { detail: { path, method: fetchOpts.method || 'GET' } }));
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// The handoff summary is up to two model calls (agy /compact, then the dialogue fallback, 45 s each). Giving up at the
// default 12 s made the page open an unlinked new session while the server still finished the linked one (2026-10-03).
const CONTINUE_TIMEOUT_MS = 150000;

async function maybeRedirectHardSession(id, info, depth) {
  depth = depth || 0;
  if (depth > 3) return null;
  const hard = Boolean(info && info.weight && info.weight.level === 'hard');
  if (!hard) return null;
  const redir = (info && (info.redirect_session_id || info.successor_session_id)) || '';
  if (redir && redir !== id) {
    rememberSession(redir);
    addActivity(tr('api.hard_redirect', { sid: redir }));
    await openSession(redir, depth + 1, {
      level: 'hard',
      message_ko: tr('api.hard_continued'),
    });
    return redir;
  }
  if (hard && !redir) {
    // Auto-redirect on open must land every window/tab on the SAME
    // successor -- a plain createSession() here (old behavior) never links
    // back to `id`, so each window that loaded this hard session before any
    // of them finished would mint its own disconnected new chat (operator:
    // "with several windows open each started its own new session and the old talk
    // did not show"). sticky:true asks the server to reuse an already-usable
    // successor instead of forking again -- safe even if two windows race,
    // since the server resolves it under that session's own lock.
    try {
      const res = await api('/api/sessions/' + encodeURIComponent(id) + '/continue', {
        method: 'POST',
        body: JSON.stringify({ model: modelEl.value, sticky: true }),
        timeoutMs: CONTINUE_TIMEOUT_MS,
      });
      if (res && res.ok && res.session && res.session.id) {
        const nid = res.session.id;
        rememberSession(nid);
        addActivity(tr('api.hard_continue', { sid: nid }) + (res.reused ? tr('api.reused') : tr('api.fresh')));
        await openSession(nid, depth + 1, {
          level: 'hard',
          message_ko: tr('api.hard_continued'),
        });
        return nid;
      }
    } catch (e) {
      addActivity(tr('api.continue_failed', { error: e.message || e }));
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
  document.documentElement.dataset.tab = tab;   // TAB_CHROME_v1 (chat-panes.css): scene and input bar on chat only
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

async function waitHostBack(maxMs = 90000, beforeBootTs = null) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try {
      const h = await api('/healthz');
      // the old server may still answer before it exits: only a new boot_ts means the restart landed
      if (beforeBootTs == null || (h && h.boot_ts != null && h.boot_ts !== beforeBootTs)) return true;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

// REBOOT_HUD_v1 (#508): the engine reboot plays as a dark-glass terminal over the page. log() adds a line,
// close() fades it out, fail() leaves it up with a close button (the host did not come back).
function showRebootOverlay() {
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const overlay = el('div', 'reboot-overlay'), term = el('div', 'reboot-terminal'), head = el('div', 'reboot-head');
  const body = el('div', 'reboot-body'), cursor = el('span', 'reboot-cursor');
  overlay.setAttribute('role', 'status');
  overlay.setAttribute('aria-live', 'polite');
  head.append(el('i', 'reboot-dot r'), el('i', 'reboot-dot y'), el('i', 'reboot-dot g'),
              el('span', 'reboot-title', 'PRIVATE ENGINE // REBOOT CONSOLE'));
  body.append(cursor);
  term.append(head, body);
  overlay.append(term);
  document.body.append(overlay);
  requestAnimationFrame(() => overlay.classList.add('open'));
  const close = () => { overlay.classList.remove('open'); setTimeout(() => overlay.remove(), 320); };
  return {
    log(text, tone) { body.insertBefore(el('div', 'reboot-line' + (tone ? ' ' + tone : ''), text), cursor); },
    close,
    fail() {
      const btn = el('button', 'reboot-close', 'CLOSE');
      btn.type = 'button';
      btn.addEventListener('click', close);
      term.append(btn);
      btn.focus();
    },
  };
}

// ASSET_RELOAD_v1: an open page keeps the code it loaded across a host restart. /healthz reports the page code's
// fingerprint (`static`); the first one seen is this page's own, and a restart that brought a different one reloads
// the page -- under the restart overlay when the button did it -- keeping the unsent draft for the reloaded page.
let pageAssetsFp = null;
const RELOAD_DRAFT_KEY = 'chatbot.reloadDraft';

function notePageAssets(fp) {
  if (fp && pageAssetsFp === null) pageAssetsFp = fp;
}

function reloadIfAssetsChanged(fp) {
  if (!fp || pageAssetsFp === null || fp === pageAssetsFp) { notePageAssets(fp); return false; }
  try {
    const draft = typeof inputEl !== 'undefined' && inputEl ? inputEl.value : '';
    if (draft) sessionStorage.setItem(RELOAD_DRAFT_KEY, draft);
  } catch (_) {}
  window.location.reload();
  return true;
}

function restoreReloadDraft() {
  try {
    const draft = sessionStorage.getItem(RELOAD_DRAFT_KEY);
    sessionStorage.removeItem(RELOAD_DRAFT_KEY);
    if (draft && typeof inputEl !== 'undefined' && inputEl && !inputEl.value) inputEl.value = draft;
  } catch (_) {}
}

async function defibrillateHost() {
  if (!(await confirmModal(tr('api.defib_confirm'), { confirmLabel: tr('api.defib_button'), danger: false }))) return;
  setProgress(tr('api.defib_running'), true);
  const btn = document.getElementById('defibBtn');
  if (btn) btn.disabled = true;
  const hud = showRebootOverlay();
  let done = false;
  try {
    hud.log('[ENGINE] Reboot initiated…');
    let beforeBootTs = null;
    try {
      const before = await api('/healthz', { timeoutMs: 5000 });
      beforeBootTs = before.boot_ts ?? null;
      notePageAssets(before.static);
    } catch (_) {}
    try {
      await api('/api/host/defibrillate', { method: 'POST', body: '{}' });
    } catch (_) {
      /* server may die mid-response — expected */
    }
    addActivity(tr('api.defib_scheduled'), 'system');
    hud.log('[DAEMON] Waiting for host socket (:3011)…', 'cyan');
    hud.log('[SOCKET] Handshake pinging • • •', 'cyan');
    const ok = await waitHostBack(90000, beforeBootTs);
    if (!ok) {
      hud.log('[ERROR] Timeout — the host did not answer in 90s.', 'err');
      hud.log('Reload the page by hand once the host is up.');
      hud.fail();
      done = true;
      setProgress(tr('api.defib_timeout'), true);
      addActivity(tr('api.defib_failed'));
      return;
    }
    try {
      if (reloadIfAssetsChanged((await api('/healthz', { timeoutMs: 5000 })).static)) {
        hud.log('[UI] New page code — reloading…', 'cyan');
        done = true;
        return;
      }
    } catch (_) {}
    setProgress(tr('api.defib_reconnecting'), true);
    await ensureSession();
    hud.log('[ONLINE] Core restored · Session linked ✦', 'ok');
    done = true;
    setTimeout(hud.close, 1200);
    setProgress(tr('api.defib_done'), true);
    addActivity(tr('api.defib_done'), 'ok');
  } finally {
    if (!done) hud.close();
    if (btn) btn.disabled = false;
  }
}

// CLIENT_ERRORS_v1 (#424): the page's errors go to the host log (page.error), so an empty chat after a refresh
// leaves a trace. Name, the start of the message, where, the top of the stack -- never a message's text. At most
// CLIENT_ERROR_MAX a load, fire and forget.
const CLIENT_ERROR_MAX = 10;
let clientErrorsSent = 0;
function reportClientError(err, context) {
  if (clientErrorsSent >= CLIENT_ERROR_MAX) return;
  clientErrorsSent++;
  try {
    const e = err || {};
    const body = { name: String(e.name || typeof e), message: String(e.message || e).slice(0, 200),
                   where: String(e.filename ? e.filename + ':' + e.lineno + ':' + e.colno : '').slice(0, 200),
                   stack: String(e.stack || '').split('\n').slice(0, 6).join('\n').slice(0, 600),
                   context: String(context || '').slice(0, 80) };
    fetch(BASE_PATH + '/api/client-error', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify(body) }).catch(() => {});
  } catch (_) { /* reporting must never throw */ }
}
if (typeof window !== 'undefined' && window.addEventListener) {
  window.addEventListener('error', (ev) => reportClientError(ev.error || { name: 'Error', message: ev.message,
    filename: ev.filename, lineno: ev.lineno, colno: ev.colno }, 'window.onerror'));
  window.addEventListener('unhandledrejection', (ev) => reportClientError(ev.reason, 'unhandledrejection'));
}
