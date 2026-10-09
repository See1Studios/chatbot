// app-api.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
async function api(path, opts) {
  const url = (BASE_PATH && path.startsWith('/') && !path.startsWith(BASE_PATH)) ? (BASE_PATH + path) : path;
  opts = opts || {};
  // BOOT_HANG_FIX_v1: default timeout so /api/sessions/active cannot freeze boot forever. 0 waits for the server's own
  // answer: only a real failure (an error status, a dropped connection) ends it.
  const timeoutMs = opts.timeoutMs != null ? opts.timeoutMs : 12000;
  const { timeoutMs: _drop, ...fetchOpts } = opts;
  const ctrl = new AbortController();
  const timer = timeoutMs > 0 ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
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
  // FAIL_NOTICE_v1: the old tab page sends a blocked provider to its status tab; shell2 keeps the talk (the input is
  // off) and says how to recover in it (syncBlockedNotice)
  const shell2 = typeof shellOn === 'function' && shellOn();
  if (!shell2 && (tab === 'chat' || tab === 'sessions' || tab === 'evolution') && isProviderUseBlocked(chatProvider())) {
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

// REBOOT_HUD_v3 (#872): 7-stage cinematic reboot sequence (blur-in -> terminal pop-in -> kernel torrent ->
// success surge -> terminal exit -> progressive blur dissolve out).
function showRebootOverlay() {
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const overlay = el('div', 'reboot-overlay'), term = el('div', 'reboot-terminal');
  const head = el('div', 'reboot-head'), headLeft = el('div', 'reboot-head-left');
  const telem = el('div', 'reboot-telemetry'), screen = el('div', 'reboot-screen');
  const torrent = el('div', 'reboot-torrent'), body = el('div', 'reboot-body'), cursor = el('span', 'reboot-cursor');
  const badge = el('span', 'reboot-badge', 'BOOTING');

  overlay.setAttribute('role', 'status');
  overlay.setAttribute('aria-live', 'polite');

  term.append(el('i', 'reboot-bracket tl'), el('i', 'reboot-bracket tr'),
              el('i', 'reboot-bracket bl'), el('i', 'reboot-bracket br'));

  headLeft.append(el('i', 'reboot-dot r'), el('i', 'reboot-dot y'), el('i', 'reboot-dot g'),
                  el('span', 'reboot-title', 'DEFIBRILLATE SEQUENCE // CORE:3011'));
  head.append(headLeft, badge);

  const telemLeft = el('div', 'reboot-telemetry-item');
  const pulseTrack = el('div', 'reboot-pulse-track');
  pulseTrack.append(el('div', 'reboot-pulse-bar'));
  telemLeft.append(el('span', null, 'RESONANCE:'), pulseTrack);
  const telemRight = el('div', 'reboot-telemetry-item', 'STATE: ACTIVE_PING · PROBE: ON');
  telem.append(telemLeft, telemRight);

  body.append(cursor);
  screen.append(torrent, body);
  term.append(head, telem, screen);
  overlay.append(term);
  document.body.append(overlay);

  // Stages 1 & 2: Progressive backdrop blur in, then terminal pop-in
  requestAnimationFrame(() => {
    overlay.classList.add('blur-in');
    setTimeout(() => {
      if (overlay.isConnected) term.classList.add('term-in');
    }, 160);
  });

  const KERNEL_LOGS = [
    '0x7FFA8920 [KERNEL] RECLAIM_DAEMON_SOCKET(3011)',
    '0x7FFA8934 [SYSCALL] SIG_HALT BROADCAST → WORKER_POOL',
    '0x7FFA8948 [VMM] PURGE_TRANSIENT_BUFFERS 64MB OK',
    '0x7FFA895C [NET] LISTENER_REBIND AF_INET 0.0.0.0:3011',
    '0x7FFA8970 [CRYPTO] SECP256R1 VAPID VAULT RE-ARMED',
    '0x7FFA8984 [OBSLOG] EVENTS_STREAM FLUSH /events.jsonl',
    '0x7FFA8998 [ENGINE] RECONFIG_ADAPTERS: AGY/GEMINI/CLAUDE',
    '0x7FFA89AC [ROUTER] DISPATCH_TABLE RESEED ROUTES=44',
    '0x7FFA89C0 [SYS] SYNCHRONIZE_WATCHDOG_TICK (5000ms)',
    '0x7FFA89D4 [IO] ATOMIC_SNAPSHOT RESTORE METADATA',
    '0x7FFA89E8 [IPC] PROBE_CHALLENGE → SOCKET_ACCEPT',
    '0x7FFA89FC [CORE] VOLTAGE_STABILIZED RES_FACTOR=1.00',
    '0x7FFA8A10 [MEM] REALLOC_PAGE_TABLES BOUNDS_CHECK_OK',
    '0x7FFA8A24 [DAEMON] HEARTBEAT_PROBE RESPONDED 200_OK',
    '0x7FFA8A38 [FIBER] RESTORE_CONTEXT_REGISTERS IP=0x3011'
  ];
  let kIdx = 0;
  const torrentTimer = setInterval(() => {
    if (!torrent.isConnected) { clearInterval(torrentTimer); return; }
    const line = el('div', 'reboot-torrent-line', KERNEL_LOGS[kIdx % KERNEL_LOGS.length] + ' [' + (Math.random() * 999 | 0) + 'ms]');
    torrent.append(line);
    kIdx++;
    while (torrent.children.length > 14) torrent.firstElementChild.remove();
  }, 75);

  let closed = false;
  // Stages 5 -> 6 -> 7: Power surge flash -> Terminal exit -> Progressive blur dissolve out
  const close = () => {
    if (closed) return;
    closed = true;
    clearInterval(torrentTimer);
    badge.textContent = 'ONLINE';
    badge.classList.add('ok');

    // Stage 5: Power Surge Flash (screen flash)
    overlay.classList.add('surge');

    // Stage 6: Terminal Exit transition
    setTimeout(() => {
      term.classList.remove('term-in');
      term.classList.add('term-out');
    }, 320);

    // Stage 7: Progressive backdrop blur dissolve back to clear UI
    setTimeout(() => {
      overlay.classList.remove('blur-in');
      overlay.classList.add('blur-out');
    }, 560);

    // Final cleanup after blur dissolve is fully finished
    setTimeout(() => {
      overlay.remove();
    }, 1050);
  };

  return {
    log(text, tone) {
      if (closed) return;
      if (tone === 'cyan') { badge.textContent = 'CONNECTING'; }
      if (tone === 'ok') { badge.textContent = 'SYNCED'; badge.classList.add('ok'); }
      if (tone === 'err') { badge.textContent = 'HALTED'; badge.classList.remove('ok'); }
      body.insertBefore(el('div', 'reboot-line' + (tone ? ' ' + tone : ''), text), cursor);
    },
    close,
    fail() {
      clearInterval(torrentTimer);
      badge.textContent = 'HALTED';
      const btn = el('button', 'reboot-close', 'CLOSE CONSOLE');
      btn.type = 'button';
      btn.addEventListener('click', () => {
        term.classList.add('term-out');
        setTimeout(() => overlay.classList.add('blur-out'), 140);
        setTimeout(() => overlay.remove(), 560);
      });
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
