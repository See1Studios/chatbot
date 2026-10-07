// app-session.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
function defaultCharacterId() {
  const d = (typeof characterCatalog !== 'undefined' ? characterCatalog : []).find(c => c.default);
  return d ? d.id : '';
}
function openCharacterId() { return sessionCharacter || defaultCharacterId(); }
function sessionCharacterName(cid) {
  const targetId = cid || openCharacterId();
  const c = (typeof characterCatalog !== 'undefined' ? characterCatalog : []).find(x => x.id === targetId);
  return c ? (c.name || c.title || '') : '';
}
function sameSessionMode(s) {
  return ((s && s.mode) || 'work') === sessionMode && ((s && s.character) || defaultCharacterId()) === openCharacterId();
}

// /private on|off (typed or the heart button): the other mode's session opens with its own history; nothing
// goes to the agent
async function applyModeSwitch(res) {
  const target = res.session;
  sessionMode = target.mode === 'private' ? 'private' : 'work';
  sessionCharacter = target.character || '';
  liveSessionId = target.id;
  archiveBrowse = false;
  await openSession(target.id, 0, null, true);
  addActivity(tr(sessionMode === 'private' ? 'session.to_private' : 'session.to_work', { sid: target.id }), 'system');
  // SCENE_v1 (private-mode.md §8.4-8.5): a room switch is a scene change -- the host's scene line goes as an
  // action, so the character reacts first instead of waiting for the user
  if (res.scene && typeof sendAction === 'function') sendAction(res.scene);
}

function updatePrivateBtn() {
  if (!privateBtn) return;
  const on = sessionMode === 'private';
  privateBtn.classList.toggle('active', on);
  privateBtn.setAttribute('aria-pressed', String(on));
  privateBtn.title = on ? tr('composer.private_off') : tr('composer.private_on');
}

async function togglePrivateMode() {
  if (!sessionId || !privateBtn || privateBtn.disabled) return;
  privateBtn.disabled = true;
  try {
    const clientMid = _newClientMid();   // ROOM_SYNC_v1: the room_moved broadcast is ours, not a move to follow
    myPendingMids.add(clientMid);
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/message', {
      method: 'POST',
      body: JSON.stringify({ text: sessionMode === 'private' ? '/private off' : '/private on', client_mid: clientMid })
    });
    if (res && res.session && res.session.id) await applyModeSwitch(res);
  } catch (e) {
    addActivity(tr('session.mode_failed', { error: e.message || e }));
  } finally {
    privateBtn.disabled = false;
  }
}
function enterSession(id, opts) {
  opts = opts || {};
  rememberSession(id);
  if (!opts.preserveLog) {
    detachSessionBanner();
    logEl.innerHTML = '';
    activityEvents = [];
    if (activityEl) activityEl.innerHTML = '';
    activityNextBefore = null;
    activityLogFetched = false;
    currentSessionHasUser = Boolean((opts.history || []).some(h => h.role === 'user'));
    sessionActionsDismissed = false;
  } else if (!opts.weight || !opts.weight.level || opts.weight.level === 'ok') {
    sessionActionsDismissed = false;
  }
  if (opts.userEcho) currentSessionHasUser = true;

  if (opts.scrollback !== undefined) {
    // syncedTs (used by send()'s preserveLog rotate branch): the new
    // session already has one bit of history -- the message just sent,
    // already visible on screen from send()'s own optimistic render --
    // seed lastSyncedTs to its real ts instead of 0 so the new SSE
    // connection's resyncFromServer() doesn't treat it as "missed" and
    // render a duplicate copy of it.
    lastSyncedTs = opts.syncedTs != null ? opts.syncedTs : 0;
    if (opts.scrollback === 'self') {
      scrollbackSid = id;
      scrollbackExhausted = false;
      scrollbackVisited = new Set([id]);

      scrollforwardSid = id;
      scrollforwardExhausted = false;
      scrollforwardVisited = new Set([id]);
    } else {
      scrollbackSid = opts.scrollback;
      scrollbackExhausted = !opts.scrollback;
      scrollbackVisited = new Set();

      scrollforwardSid = '';
      scrollforwardExhausted = true;
      scrollforwardVisited = new Set();
    }
  }

  if (opts.history) {
    // QUOTA_SILENT_FIX_v1: drop notice:error twins sharing ts with a real reply
    const hist = (opts.history || []).filter(h => {
      if (h.role !== 'assistant' || h.notice !== 'error' || !h.ts) return true;
      return !(opts.history || []).some(o => o !== h && o.role === 'assistant' && !o.notice && o.ts === h.ts && String(o.text || '').trim());
    });
    hist.forEach(h => {
      // EMPTY_BUBBLE_FIX_v1: skip empty history — never paint hollow bubbles
      if (h.role !== 'btw' && !(String(h.text || '').trim())) return;
      if (h.role === 'btw') {
        addBtw(h.query, h.text, false, h.usage, h.duration_seconds, h.ts);
      } else if (h.role === 'user') {
        addUserEntry(h.text, Boolean(h.queued), false, h.ts);
      } else if (h.role === 'assistant') {
        // QUOTA_ERR_DEDUP_v1: history notice via addNotice
        const nk = h.notice || (h.system ? (typeof h.system === 'string' ? h.system : 'info') : ''); // NOTICE_FLAG_ONLY_v1: no text inference
        if (nk) addNotice(nk, h.text || '', h.ts);
        else addChat('assistant', textWithChoices(h), true, false, false, false, h.usage, h.duration_seconds, false, h.ts, h.served_model);
      }
      lastSyncedTs = Math.max(lastSyncedTs, h.ts || 0);
    });
    // Each addChat() call already scrolls to bottom as it's added, but
    // that's measured against scrollHeight *at that instant* -- an
    // assistant message with an image (common: image responses generate a lot of
    // these) grows taller once the image finishes loading, after the last
    // addChat already ran, leaving the view short of the true bottom
    // (scrollpin guard: ensure viewport reaches bottom after image load).
    // Re-pin now and once more shortly after, by which point
    // any images have almost certainly finished loading.
    logEl.scrollTop = logEl.scrollHeight;
    setTimeout(() => { logEl.scrollTop = logEl.scrollHeight; }, 200);
    setSessionTokensFromHistory(opts.history);
  } else {
    setSessionTokensFromHistory([]);
  }

  if (opts.userEcho) addChat('user', opts.userEcho, false, false, false);
  if (opts.sessionMarker) {   // CHAT_FLOW_v1: a new conversation the user started; its id in the advanced density only
    const marker = document.createElement('div');
    marker.className = 'msg scrollback-marker flow-line new-talk';
    marker.textContent = tr('session.new_chat');
    const id = document.createElement('span');
    id.className = 'flow-id';
    id.textContent = opts.sessionMarker;
    marker.appendChild(id);
    logEl.appendChild(marker);
  }
  if (opts.greeting) addChat('assistant', opts.greeting, true);
  // Host-generated copy (not LLM output) goes in as a system notice, never an assistant turn.
  if (opts.notice) addNotice('info', opts.notice);
  if (opts.activityAfter) addActivity(opts.activityAfter);

  // Moved out of the `opts.history` branch above: createSession()/
  // continueSession() set up scrollback (opts.scrollback) too but never pass
  // opts.history (a brand-new session has none yet), so this never used to
  // run for them -- their only content is the short greeting bubble, which
  // never overflows the viewport on its own, so there was no scrollbar to
  // manually scroll-near-top with in the first place. The scroll listener's
  // own overflow guard (see below) now also refuses to backfill from a
  // spurious clamp-to-zero scroll event, so without this, a brand-new
  // session had no way at all to pull in older sessions' content -- from
  // the user's side that read as previous session content being gone.
  // Running it here for every scrollback-tracked entry (not just
  // history-restoring ones) chain-loads previous sessions until the
  // viewport is filled, same as opening an existing short session already did.
  if (opts.scrollback !== undefined) setTimeout(maybeBackfillScrollback, 0);

  document.body.classList.toggle('private-session', sessionMode === 'private');
  updatePrivateBtn();
  const chName = sessionCharacterName((opts.sessionInfo && opts.sessionInfo.character) || sessionCharacter);
  const chPrefix = chName ? (chName + ' · ') : '';
  setMeta((sessionMode === 'private' ? tr('session.private_prefix') : '') + chPrefix + tr('session.meta', { sid: id }) + (opts.metaLabel || ''));
  updateSessionNav(id, opts.sessionInfo);

  if (sessionBanner) {
    if (opts.weight && opts.weight.level) {
      sessionBanner.dataset.level = opts.weight.level;
      sessionBanner.dataset.message = trField(opts.weight, 'message');
    } else if (!opts.preserveLog) {
      sessionBanner.dataset.level = 'ok';
      sessionBanner.dataset.message = '';
    }
  }

  if (opts.busy !== undefined) setBusy(Boolean(opts.busy));
  else syncSessionActions();

  bindEvents(id);
  fetchArtifacts(true);
  fetchLog();
}

async function openSession(id, _redirDepth, bannerOverride, noRedirect) {
  const info = await api('/api/sessions/' + encodeURIComponent(id));
  if (!noRedirect) {
    const bounced = await maybeRedirectHardSession(id, info, _redirDepth || 0);
    if (bounced) return;
  }
  const infoMode = info && info.mode === 'private' ? 'private' : 'work';
  const infoCharacter = (info && info.character) || '';
  if (infoMode !== sessionMode || infoCharacter !== sessionCharacter) {
    // opened a session of another mode or character: that one's tip becomes live
    sessionMode = infoMode;
    sessionCharacter = infoCharacter;
    liveSessionId = '';
  }
  if (liveSessionId && id !== liveSessionId) archiveBrowse = true;
  else {
    archiveBrowse = false;
    if (isLiveSid(id)) liveSessionId = liveSessionId || id;
  }
  enterSession(id, {
    scrollback: 'self',
    sessionInfo: info,
    history: info.history || [],
    metaLabel: info.model || '',
    // bannerOverride (set only by maybeRedirectHardSession's own bounce
    // paths) forces the hard-session banner to show here even though this
    // freshly-landed-on session's own weight is 'ok' -- the point is to
    // explain to the user, in the chat tab itself, that they were just
    // auto-redirected here from a different session (previously this was
    // only ever logged to the non-default log tab via addActivity, which
    // read as an unexplained context switch -- 2026 impeccable critique P0).
    weight: bannerOverride || info.weight,
    busy: info.busy,
    activityAfter: tr('session.restored', { sid: id }),
  });
  applySessionProvider(info);
  updateBrandAvatar(info.provider || (providerEl ? providerEl.value : ''));
}

// Re-syncs the live view against server history + in-flight draft.
// SSE can go zombie on a backgrounded phone, so this also runs on a
// visibility/poll loop — not only on EventSource onopen. Missed items
// are keyed by role+ts and inserted in timestamp order (before any
// live streaming bubble) so a late user_ack cannot land under the answer.
let resyncInFlight = false;
// SYNC_THROTTLE_v1: the stream carries every change, so with it open the poll is only a safety net -- every
// SYNC_SAFETY_MS, or after SYNC_STALL_MS of silence while a turn runs (a stream that died quietly). With the
// stream closed, every tick as before. It used to fetch the whole session (and the session list) every 2.5s.
const SYNC_SAFETY_MS = 30000;
const SYNC_STALL_MS = 10000;
let lastSyncAt = 0;
function syncDue(now, streamOpen, busy, lastSync, lastStream) {
  if (!streamOpen) return true;
  if (now - lastSync >= SYNC_SAFETY_MS) return true;
  return Boolean(busy) && now - Math.max(lastSync, lastStream) >= SYNC_STALL_MS;
}
async function resyncFromServer(sid) {
  if (!sid || sid !== sessionId) return;
  if (resyncInFlight) return;
  resyncInFlight = true;
  lastSyncAt = Date.now();
  try {
    let info;
    try { info = await api('/api/sessions/' + encodeURIComponent(sid)); } catch (_) { return; }
    if (!info || info.id !== sid || sid !== sessionId) return;

    const seen = new Set();
    logEl.querySelectorAll('.msg[data-ts]').forEach(n => {
      const r = n.dataset.syncRole || '';
      seen.add(msgSyncKey(r === 'action' ? 'user' : r, n.dataset.ts));   // an action line is the server's user entry
    });

    let added = 0;
    (info.history || []).forEach(h => {
      if (!h.ts) return;
      const role = h.role || '';
      // EMPTY_BUBBLE_FIX_v1: skip empty history
      if (role !== 'btw' && !(String(h.text || '').trim())) return;
      // QUOTA_SILENT_FIX_v1
      if (role === 'assistant' && h.notice === 'error' && h.ts) {
        const twinReply = (info.history || []).some(o => o !== h && o.role === 'assistant' && !o.notice && o.ts === h.ts && String(o.text || '').trim());
        if (twinReply) return;
      }
      const k = msgSyncKey(role, h.ts);
      if (seen.has(k)) {
        lastSyncedTs = Math.max(lastSyncedTs, h.ts);
        return;
      }
      if (role === 'assistant' && assistantNode && assistantNode.dataset.live === '1') {
        setAssistantContent(assistantNode, textWithChoices(h), true, h.usage, h.duration_seconds, h.served_model);
        assistantNode.dataset.ts = String(h.ts);
        assistantNode.dataset.syncRole = 'assistant';
        delete assistantNode.dataset.live;
        delete assistantNode.dataset.progress;
        assistantNode = null;
        assistantBuf = '';
        seen.add(k);
        lastSyncedTs = Math.max(lastSyncedTs, h.ts);
        added++;
        return;
      }
      if (role === 'btw') {
        addBtw(h.query, h.text, false, h.usage, h.duration_seconds, h.ts);
      } else if (role === 'user') {
        const act = actionTextOf(h.text);
        const bare = Array.prototype.slice.call(logEl.querySelectorAll(act ? '.msg.action:not([data-ts])' : '.msg.user:not([data-ts])'));
        const want = act ? '\u2726 ' + act : (h.text || '');
        const match = bare.find(function (n) { return (n.textContent || '') === want; });
        if (match) {
          match.dataset.ts = String(h.ts);
          match.dataset.syncRole = act ? 'action' : 'user';
          placeMsgByTs(match, h.ts);
        } else {
          addUserEntry(h.text, Boolean(h.queued), false, h.ts);
        }
      } else if (role === 'assistant') {
        // the client already closed this one itself (interrupt/stop) and has it, ts-less, on screen
        if (adoptUntimedAssistant(h)) {
          seen.add(k);
          lastSyncedTs = Math.max(lastSyncedTs, h.ts);
          return;
        }
        const nk = h.notice || (h.system ? (typeof h.system === 'string' ? h.system : 'info') : ''); // NOTICE_FLAG_ONLY_v1: no text inference
        if (nk) addChat('assistant', textWithChoices(h), true, false, false, false, null, null, nk, h.ts, null);
        else addChat('assistant', textWithChoices(h), true, false, false, false, h.usage, h.duration_seconds, false, h.ts, h.served_model);
      } else {
        return;
      }
      seen.add(k);
      lastSyncedTs = Math.max(lastSyncedTs, h.ts);
      added++;
    });

    if (info.busy) {
      setBusy(true);
      if (info.last_progress) setProgress(tr('chat.working', { text: shortToolLine(trField(info, 'last_progress')) }));
      const draft = info.current_text || '';
      if (draft) {
        if (!assistantNode) {
          assistantNode = addChat('assistant', '', false);
          assistantNode.dataset.live = '1';
        }
        if (draft.length >= (assistantBuf || '').length) {
          assistantBuf = draft;
          // STREAM_FLOW_v1: the sync poll also writes the live body, on a timer, while the turn
          // runs. Rendering it through the final path is what erased the flowing text: it replaced
          // the bubble wholesale and took the reveal spans with it.
          revealTarget(assistantNode, assistantBuf);   // CHAR_REVEAL_v1: through the letter clock
        }
      }
    } else {
      // Server is NOT busy — SESSION_DESYNC_GAPFIX_v2
      try {
        logEl.querySelectorAll('.msg[data-progress="1"]').forEach(function (n) {
          if (n !== assistantNode) n.remove();
        });
      } catch (_) {}
      if (assistantNode && assistantNode.dataset.live === '1') {
        if (assistantBuf && assistantBuf.trim() && assistantNode.dataset.progress !== '1') {
          markUntimed(assistantNode, assistantBuf);
          setAssistantContent(assistantNode, assistantBuf, true);
          endStreamingContent(assistantNode);   // STREAM_FLOW_v1: nothing is left moving
          delete assistantNode.dataset.live;
          delete assistantNode.dataset.progress;
        } else {
          assistantNode.remove();
        }
        assistantNode = null;
        assistantBuf = '';
      }
      setProgress('');
      // myPendingMids is deliberately NOT cleared here: an idle server does not mean my sent
      // message is done -- during a steer respawn the server is idle until it writes the
      // message and acks it, and clearing turned my own ack into "someone else's" (a 2nd bubble).
      if (isBusy) {
        setBusy(false);
      }
    }

    repairMsgOrder();

    if (added) {
      addActivity(tr('session.synced', { n: added }), 'system');
      fetchArtifacts(true);
    }
    // Chat history already syncs here; provider chrome used to stay on
    // this device's localStorage until a full reload.
    if (typeof applySessionProvider === 'function') applySessionProvider(info);
  } finally {
    resyncInFlight = false;
  }
}

function startSessionSyncLoop() {
  if (window.__sessionSyncTimer) return;
  window.__sessionSyncTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return;
    if (!sessionId) return;
    const open = Boolean(es) && es.readyState === EventSource.OPEN;
    if (!syncDue(Date.now(), open, isBusy, lastSyncAt, lastStreamAt)) return;
    lastSyncAt = Date.now();
    followLiveIfNeeded().then(() => {
      resyncFromServer(sessionId);
    }).catch(() => {});
    if (es && es.readyState === EventSource.CLOSED) bindEvents(sessionId);
  }, 2500);
  if (!window.__sessionSyncVis) {
    window.__sessionSyncVis = true;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible' || !sessionId) return;
      if (!es || es.readyState === EventSource.CLOSED) bindEvents(sessionId);
      else resyncFromServer(sessionId);
    });
    window.addEventListener('pageshow', () => {
      if (!sessionId) return;
      if (!es || es.readyState === EventSource.CLOSED) bindEvents(sessionId);
      else resyncFromServer(sessionId);
    });
  }
}

// Loads one predecessor-session hop of history and prepends it above the
// current top of #log, walking scrollbackSid back one link at a time. Never
// feeds anything back into agy's context -- purely a read-only archive view.
// Resolves the "previous session" for scrollback purposes: the real
// predecessor_session_id when set, or -- for an explicit "completely new session" reset,
// which intentionally has no predecessor link -- the chronologically-next-
// older session overall, purely as a browsing convenience (never affects
// agy context). Returns '' when there's truly nothing older.
// GET /api/sessions/:id returns updated_at as an epoch-seconds float
// (file mtime), while GET /api/sessions (list) returns it as an ISO
// string from meta.json -- two different pre-existing endpoints, two
// different formats. Normalize both to epoch-ms before comparing.
function _scrollbackEpochMs(v) {
  // SESSION_LIST_DATE_FIX_v1: list may send ISO string; detail/mtime may send epoch seconds
  if (v == null || v === '') return 0;
  if (typeof v === 'number' && isFinite(v)) {
    // seconds if looks like unix seconds (< year 2100 in ms threshold)
    return v < 1e12 ? Math.round(v * 1000) : Math.round(v);
  }
  const s = String(v).trim();
  if (/^\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    return n < 1e12 ? Math.round(n * 1000) : Math.round(n);
  }
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : 0;
}

async function resolveScrollbackFallback(sid, updatedAt, visited) {
  const cur = _scrollbackEpochMs(updatedAt);
  try {
    const list = await api('/api/sessions');
    const valid = (list.sessions || []).filter(s => s.id !== sid && !visited.has(s.id) && sameSessionMode(s) && (s.preview || (s.turns && s.turns > 0)));
    let cands = valid.filter(s => s.updated_at && (!cur || _scrollbackEpochMs(s.updated_at) < cur))
      .sort((a, b) => _scrollbackEpochMs(b.updated_at) - _scrollbackEpochMs(a.updated_at));
    if (cands.length) return cands[0].id;
    cands = valid.filter(s => s.id < sid).sort((a, b) => b.id.localeCompare(a.id));
    return cands.length ? cands[0].id : '';
  } catch (_) {
    return '';
  }
}

async function loadOlderHistory() {
  if (scrollbackLoading || scrollbackExhausted || !scrollbackSid) return;
  scrollbackLoading = true;
  logEl.querySelectorAll('.scrollback-retry').forEach(n => n.remove());
  const marker = document.createElement('div');
  marker.className = 'msg scrollback-marker';
  marker.textContent = tr('session.loading_older');
  logEl.insertBefore(marker, logEl.firstChild);
  const prevScrollHeight = logEl.scrollHeight;
  const prevScrollTop = logEl.scrollTop;
  try {
    // Skip transparently through any hop(s) that turn out to have no real
    // content (e.g. a chain of back-to-back "new session" resets nobody typed
    // into) instead of showing an empty divider for each one.
    let lastKnownTs = 0; // last hop's updated_at we actually saw -- used to
    // anchor the fallback search when the NEXT hop turns out to be deleted
    for (let hops = 0; hops < 20; hops++) {
      // openSession() pre-seeds this with the session it just rendered in
      // full via its own forEach, specifically so this first hop can reuse
      // it as the fallback anchor WITHOUT re-rendering the same messages a
      // second time.
      const alreadyRendered = scrollbackVisited.has(scrollbackSid);
      scrollbackVisited.add(scrollbackSid);
      let info;
      try {
        info = await api('/api/sessions/' + encodeURIComponent(scrollbackSid) + '?full=1', { timeoutMs: 60000 });
      } catch (e) {
        if (e && (e.name === 'AbortError' || e.name === 'TypeError')) {
          // Slow or offline, not deleted: the session is busy (a handoff holds its lock). Routing around it here
          // jumped to an unrelated older session (2026-10-03). Keep the link and try again on the next scroll.
          scrollbackVisited.delete(scrollbackSid);
          marker.textContent = tr('session.older_failed');
          marker.classList.add('flow-line', 'scrollback-retry');
          scrollbackLoading = false;
          return;
        }
        // This session was deleted (operator's new 🗑 delete button) -- route
        // around the dead link instead of aborting the whole scrollback.
        const fallback = await resolveScrollbackFallback(scrollbackSid, lastKnownTs, scrollbackVisited);
        if (fallback) {
          scrollbackSid = fallback;
          continue;
        }
        scrollbackExhausted = true;
        const cap = document.createElement('div');
        cap.className = 'msg scrollback-marker flow-line';   // CHAT_FLOW_v1: one divider style
        cap.textContent = tr('session.start_of_talk');
        logEl.insertBefore(cap, logEl.firstChild);
        break;
      }
      lastKnownTs = _scrollbackEpochMs(info.updated_at) || lastKnownTs;
      const hist = info.history || [];
      let nextSid = info.predecessor_session_id || '';
      if (nextSid && scrollbackVisited.has(nextSid)) nextSid = ''; // cycle guard
      if (!nextSid) nextSid = await resolveScrollbackFallback(scrollbackSid, info.updated_at, scrollbackVisited);

      const showThisHop = hist.length && !alreadyRendered;
      if (showThisHop) {
        for (let i = hist.length - 1; i >= 0; i--) {
          const h = hist[i];
          if (h.role === 'btw') {
            addBtw(h.query, h.text, true, h.usage, h.duration_seconds, h.ts);
          } else if (h.role === 'user') {
            addUserEntry(h.text, Boolean(h.queued), true, h.ts);
          } else if (h.role === 'assistant') {
            const nk = h.notice || (h.system ? (typeof h.system === 'string' ? h.system : 'info') : ''); // NOTICE_FLAG_ONLY_v1: no text inference
            if (nk) addChat('assistant', textWithChoices(h), true, false, false, true, null, null, nk, h.ts, null);
            else addChat('assistant', textWithChoices(h), true, false, false, true, h.usage, h.duration_seconds, false, h.ts, h.served_model);
          }
        }
        const divider = document.createElement('div');
        divider.className = 'msg scrollback-marker session-divider';   // CHAT_FLOW_v1: advanced density only
        divider.innerHTML = '── ' + escapeHtml(tr('session.divider', { sid: scrollbackSid })) + ' ──' +
          ' <button class="session-switch-btn" data-switch-sid="' + escapeHtml(scrollbackSid) + '" type="button">' + escapeHtml(tr('session.switch_here')) + '</button>' +
          ' <button class="session-import-btn" data-import-sid="' + escapeHtml(scrollbackSid) + '" type="button">' + getActionSvg('pin') + ' ' + escapeHtml(tr('session.import')) + '</button>';
        logEl.insertBefore(divider, logEl.firstChild);
        divider.querySelectorAll('[data-switch-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openSession(btn.getAttribute('data-switch-sid'), 0, null, true);
          });
        });
        divider.querySelectorAll('[data-import-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            importSessionContext(btn.getAttribute('data-import-sid'));
          });
        });
      }

      if (nextSid) {
        scrollbackSid = nextSid;
        if (showThisHop) break; // showed something this call -- let the user see it before loading more
        // else: this hop was empty or already-rendered, loop again and skip past it silently
      } else {
        scrollbackExhausted = true;
        const cap = document.createElement('div');
        cap.className = 'msg scrollback-marker flow-line';   // CHAT_FLOW_v1: one divider style
        cap.textContent = tr('session.start_of_talk');
        logEl.insertBefore(cap, logEl.firstChild);
        break;
      }
    }
    if (typeof officeFit === 'function') officeFit();   // a coworker dm whose time this hop reached shows now
    marker.remove();
    logEl.scrollTop = prevScrollTop + (logEl.scrollHeight - prevScrollHeight);
  } catch (_) {
    marker.remove();
  }
  scrollbackLoading = false;
  // A short/freshly-rotated session's history often doesn't fill the
  // viewport at all, so there's nothing to physically scroll and the
  // 'scroll' listener below never fires even though older content exists.
  // Chain-backfill until there's enough content to actually scroll, or the
  // predecessor chain runs out.
  maybeBackfillScrollback();
}

function maybeBackfillScrollback() {
  if (currentTab !== 'chat' || scrollbackExhausted || scrollbackLoading || !logEl) return;
  if (logEl.scrollHeight <= logEl.clientHeight + 20) {
    loadOlderHistory();
  }
}

async function resolveScrollforwardFallback(sid, updatedAt, visited) {
  try {
    const list = await api('/api/sessions');
    const valid = (list.sessions || []).filter(s => s.id !== sid && !visited.has(s.id) && sameSessionMode(s) && (s.preview || (s.turns && s.turns > 0)));
    const cands = valid.filter(s => s.id > sid).sort((a, b) => a.id.localeCompare(b.id));
    return cands.length ? cands[0].id : '';
  } catch (_) {
    return '';
  }
}

async function loadNewerHistory() {
  if (scrollforwardLoading || scrollforwardExhausted || !scrollforwardSid) return;
  scrollforwardLoading = true;
  const marker = document.createElement('div');
  marker.className = 'msg scrollback-marker scrollforward-marker';
  marker.textContent = tr('session.loading_newer');
  logEl.appendChild(marker);
  try {
    let lastKnownTs = 0;
    for (let hops = 0; hops < 20; hops++) {
      const alreadyRendered = scrollforwardVisited.has(scrollforwardSid);
      scrollforwardVisited.add(scrollforwardSid);
      let info;
      try {
        info = await api('/api/sessions/' + encodeURIComponent(scrollforwardSid) + '?full=1');
      } catch (_) {
        const fallback = await resolveScrollforwardFallback(scrollforwardSid, lastKnownTs, scrollforwardVisited);
        if (fallback) {
          scrollforwardSid = fallback;
          continue;
        }
        // End of forward chain -- no end-cap (operator: it showed even in the latest talk
        // and was worth nothing). Just stop loading newer hops.
        scrollforwardExhausted = true;
        break;
      }
      lastKnownTs = _scrollbackEpochMs(info.updated_at) || lastKnownTs;
      const hist = info.history || [];
      let nextSid = info.successor_session_id || '';
      if (nextSid && scrollforwardVisited.has(nextSid)) nextSid = '';
      if (!nextSid) nextSid = await resolveScrollforwardFallback(scrollforwardSid, info.updated_at, scrollforwardVisited);

      const showThisHop = hist.length && !alreadyRendered;
      if (showThisHop) {
        const divider = document.createElement('div');
        divider.className = 'msg scrollback-marker session-divider';   // CHAT_FLOW_v1: advanced density only
        divider.innerHTML = '── ' + escapeHtml(tr('session.divider_later', { sid: scrollforwardSid })) + ' ──' +
          ' <button class="session-switch-btn" data-switch-sid="' + escapeHtml(scrollforwardSid) + '" type="button">' + escapeHtml(tr('session.switch_here')) + '</button>' +
          ' <button class="session-import-btn" data-import-sid="' + escapeHtml(scrollforwardSid) + '" type="button">' + getActionSvg('pin') + ' ' + escapeHtml(tr('session.import')) + '</button>';
        logEl.appendChild(divider);
        divider.querySelectorAll('[data-switch-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openSession(btn.getAttribute('data-switch-sid'));
          });
        });
        divider.querySelectorAll('[data-import-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            importSessionContext(btn.getAttribute('data-import-sid'));
          });
        });

        hist.forEach(h => {
          if (h.role === 'btw') {
            addBtw(h.query, h.text, false, h.usage, h.duration_seconds, h.ts);
          } else if (h.role === 'user') {
            addUserEntry(h.text, Boolean(h.queued), false, h.ts);
          } else if (h.role === 'assistant') {
            const nk = h.notice || (h.system ? (typeof h.system === 'string' ? h.system : 'info') : ''); // NOTICE_FLAG_ONLY_v1: no text inference
            if (nk) addChat('assistant', textWithChoices(h), true, false, false, false, null, null, nk, h.ts, null);
            else addChat('assistant', textWithChoices(h), true, false, false, false, h.usage, h.duration_seconds, false, h.ts, h.served_model);
          }
        });
      }

      if (nextSid) {
        scrollforwardSid = nextSid;
        if (showThisHop) break;
      } else {
        // End of forward chain -- no end-cap (operator: it showed even in the latest talk
        // and was worth nothing). Just stop loading newer hops.
        scrollforwardExhausted = true;
        break;
      }
    }
  } catch (_) {
    scrollforwardExhausted = true;
  } finally {
    marker.remove();
    scrollforwardLoading = false;
    updateScrollBottomButton();
  }
}

async function updateSessionNav(id, sessionInfo) {
  const prevBtn = document.getElementById('sessionNavPrev');
  const nextBtn = document.getElementById('sessionNavNext');
  const latestBtn = document.getElementById('sessionNavLatest');
  const pastBadge = document.getElementById('pastSessionBadge');
  if (!prevBtn || !nextBtn) return;

  sessionNavPrevSid = '';
  sessionNavNextSid = '';

  if (!id) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    if (latestBtn) latestBtn.hidden = true;
    if (pastBadge) pastBadge.style.display = 'none';
    updateScrollBottomButton();
    return;
  }

  try {
    let info = sessionInfo;
    if (!info || info.id !== id) {
      info = await api('/api/sessions/' + encodeURIComponent(id));
    }
    const updatedAt = info ? info.updated_at : null;

    let prevSid = (info && info.predecessor_session_id) || '';
    if (!prevSid) {
      prevSid = await resolveScrollbackFallback(id, updatedAt, new Set([id]));
    }
    sessionNavPrevSid = prevSid;
    prevBtn.disabled = !prevSid;
    prevBtn.title = prevSid ? tr('session.prev_title', { sid: prevSid }) : tr('session.no_prev');

    let nextSid = (info && info.successor_session_id) || '';
    if (!nextSid) {
      nextSid = await resolveScrollforwardFallback(id, updatedAt, new Set([id]));
    }
    if (nextSid && nextSid <= id) nextSid = '';
    sessionNavNextSid = nextSid;
    nextBtn.disabled = !nextSid;
    nextBtn.title = nextSid ? tr('session.next_title', { sid: nextSid }) : tr('session.no_next');

    if (latestBtn) {
      latestBtn.hidden = !viewingPastSession();
      if (nextSid) latestBtn.title = tr('session.latest_jump');
    }
    if (pastBadge) {
      pastBadge.style.display = viewingPastSession() ? 'inline-flex' : 'none';
    }
    updateScrollBottomButton();
  } catch (_) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    if (latestBtn) latestBtn.hidden = true;
    if (pastBadge) pastBadge.style.display = 'none';
    updateScrollBottomButton();
  }
}

// ---- latest-conversation jump ----
function isLiveSid(sid) {
  return /^\d{8}-\d{6}-/.test(String(sid || ''));
}

function viewingPastSession() {
  if (archiveBrowse && liveSessionId && liveSessionId !== sessionId) return true;
  return Boolean(sessionNavNextSid) && sessionNavNextSid > (sessionId || '');
}

async function resolveLatestSessionId() {
  const ids = [liveSessionId, sessionNavNextSid];
  try {
    for (const s of ((await api('/api/sessions')).sessions || [])) if (s && sameSessionMode(s)) ids.push(s.id);
  } catch (_) {}
  if (sessionMode === 'work' && openCharacterId() === defaultCharacterId()) {
    try { ids.push((await api('/api/sessions/active') || {}).id); } catch (_) {}
  }
  let id = ids.filter(isLiveSid).sort().pop();
  if (!id) return sessionId || '';
  // walk successor links (a handoff the list has not caught up with yet); an empty tip falls back to the last
  // session with turns so it never reads as "could not load the talk"
  const seen = new Set();
  let lastWithTurns = '';
  while (!seen.has(id) && seen.size < 40) {
    seen.add(id);
    let info;
    try { info = await api('/api/sessions/' + encodeURIComponent(id)); } catch (_) { break; }
    const turns = (info && Array.isArray(info.history)) ? info.history.length : 0;
    if (turns > 0) lastWithTurns = id;
    const next = (info && info.successor_session_id) || '';
    if (!isLiveSid(next) || seen.has(next)) return (turns === 0 && lastWithTurns) || id;
    id = next;
  }
  return lastWithTurns || id;
}

function pinChatToBottom() {
  historyLoadHoldUntil = Date.now() + 600;
  if (!logEl) {
    updateScrollBottomButton(true);
    return;
  }
  if (typeof logEl.scrollTo === 'function') {
    logEl.scrollTo({ top: logEl.scrollHeight, behavior: 'auto' });
  } else {
    logEl.scrollTop = logEl.scrollHeight;
  }
  updateScrollBottomButton(true);
}

async function goToLatestConversation() {
  // The log already holds the live tip as far as this page knows: pin at once, without waiting for the network --
  // but still ask the server, because the tip may have moved where this page cannot see it (a rotation in another
  // tab or device, or no live session known at all); a newer one is then opened (review of #506).
  if (typeof containsActiveTip === 'function' && containsActiveTip()) {
    archiveBrowse = false;
    pinChatToBottom();
    const here = sessionId;
    resolveLatestSessionId().then(async (id) => {
      if (!id || sessionId !== here) return;   // the user moved on meanwhile: leave them where they are
      liveSessionId = id;
      if (id !== sessionId) { await openSession(id); pinChatToBottom(); }
    }).catch(() => { /* offline: the pinned log stays */ });
    return 'scroll';
  }
  const latestId = await resolveLatestSessionId();
  if (latestId) liveSessionId = latestId;
  archiveBrowse = false;
  if (latestId && latestId !== sessionId) {
    await openSession(latestId);
    pinChatToBottom();
    return 'jump';
  }
  pinChatToBottom();
  return 'scroll';
}

async function followLiveIfNeeded() {
  if (archiveBrowse) return false;
  const latestId = await resolveLatestSessionId();
  if (latestId) liveSessionId = latestId;
  if (latestId && latestId !== sessionId) {
    await openSession(latestId);
    return true;
  }
  return false;
}
// ---- end latest-conversation jump ----



async function createSession() {
  const prevSessionId = sessionId; // a "completely new session" has no real predecessor_session_id link
  // (intentional -- no handoff summary should leak into agy's context), but
  // operator still wants to be able to scroll up into whatever was open right
  // before it. Point scrollback at that browser-previous session directly;
  // it'll keep walking that session's own real predecessor chain from there.
  const model = modelEl.value;
  const provider = providerEl ? providerEl.value : defaultProviderId;
  const data = await api('/api/sessions', {method:'POST', body: JSON.stringify({model, provider, mode: sessionMode, character: sessionCharacter})});
  const label = (data.session.provider && data.session.provider !== defaultProviderId)
    ? data.session.provider + (data.session.model ? ':' + data.session.model : '')
    : data.session.model;
  liveSessionId = data.session.id;
  archiveBrowse = false;
  enterSession(data.session.id, {
    scrollback: prevSessionId,
    sessionMarker: data.session.id,
    metaLabel: label,
    busy: false,
    activityAfter: tr('session.new_activity', { sid: data.session.id }),
  });
  applySessionProvider(data.session);
}

async function continueSession() {
  if (!sessionId) {
    await createSession();
    return;
  }
  const oldId = sessionId;
  setBusy(true);
  setProgress(tr('session.continue_preparing'));
  try {
    const model = modelEl.value;
    const res = await api('/api/sessions/' + encodeURIComponent(oldId) + '/continue', {
      method: 'POST',
      body: JSON.stringify({ model }),
      timeoutMs: CONTINUE_TIMEOUT_MS,
    });
    if (res && res.ok && res.session) {
      const nid = res.session.id;
      const note = res.summary
        ? '\n\n> **' + tr('session.handover_head') + '**\n> ' + res.summary.replace(/\n/g, '\n> ')
        : '';
      liveSessionId = nid;
      archiveBrowse = false;
      enterSession(nid, {
        scrollback: 'self',
        notice: tr('session.continued') + note,
        metaLabel: res.session.model || '',
        activityAfter: tr('session.continued_activity', { old: oldId, sid: nid }),
      });
      applySessionProvider(res.session);
    }
  } catch (e) {
    addActivity(tr('session.continue_error', { error: e.message || e }));
    await alertModal(tr('session.continue_failed', { error: e.message || e }));
  } finally {
    setBusy(false);
    setProgress('');
  }
}

// SESSION_OPEN_v1 (#424): opening the latest session swallowed every error and fell through to a brand-new, empty
// session, so a refresh sometimes showed an empty chat (fourteen empty sessions on 2026-09-29, none from the host,
// which answered every request). Now only a session that is really gone ("session not found") is skipped, and a
// new session is made only when there is nothing to open. Any other failure is reported (page.error), tried once
// more, and then shown with a retry -- the conversation is never hidden behind an empty one.
const SESSION_OPEN_TEXT = i18nTable('session.open');

function sessionGone(e) { return /session not found/.test(String((e && e.message) || e || '')); }

async function openUnlessGone(id) {
  try { await openSession(id); return true; } catch (e) { if (sessionGone(e)) return false; throw e; }
}

async function ensureSession() {
  const sp = new URLSearchParams(location.search);
  const urlSid = sp.get('session');
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      if (urlSid) {
        try { liveSessionId = await resolveLatestSessionId(); } catch (_) {}
        if (await openUnlessGone(urlSid)) return;
      }
      if (sessionId) {
        if (await openUnlessGone(sessionId)) return;
        sessionId = '';
        localStorage.removeItem(SESSION_KEY);
      }
      const latestId = await resolveLatestSessionId();
      if (latestId) {
        liveSessionId = latestId;
        archiveBrowse = false;
        if (await openUnlessGone(latestId)) return;
      }
      await createSession();   // nothing to open: the one case for a new, empty session
      return;
    } catch (e) {
      if (typeof reportClientError === 'function') reportClientError(e, 'ensureSession attempt ' + attempt);
      if (attempt === 2) { showSessionOpenFailure(); return; }
      await new Promise(r => setTimeout(r, 800));
    }
  }
}

function showSessionOpenFailure() {
  const node = typeof addNotice === 'function' ? addNotice('error', SESSION_OPEN_TEXT.fail) : null;
  if (!node) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ghost';
  btn.textContent = SESSION_OPEN_TEXT.retry;
  btn.addEventListener('click', () => { node.remove(); ensureSession(); });
  node.appendChild(btn);
}
