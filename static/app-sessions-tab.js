// app-sessions-tab.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
async function fetchSessionsList(retryCount = 0) {
  if (!sessionsListEl) return;
  sessionsListEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('common.loading') + (retryCount > 0 ? tr('sessions.retrying') : '')) + '</div>';
  try {
    const res = await api('/api/sessions');
    renderSessionsList(res.sessions || []);
  } catch (e) {
    if (retryCount < 1) {
      setTimeout(() => fetchSessionsList(retryCount + 1), 600);
      return;
    }
    sessionsListEl.innerHTML =
      '<div class="status-hint">' +
      escapeHtml(tr('sessions.load_failed', { error: e.message })) + ' ' +
      '<button type="button" class="btn-xs" style="margin-left:6px;cursor:pointer;" onclick="fetchSessionsList(0)">' + escapeHtml(tr('common.retry')) + ' ↻</button>' +
      '</div>';
  }
}

// SESSION_CHAR_TABS_v1 (2026-09-28): browse the session list per character. No backend change --
// /api/sessions already carries `character` and `character_name` on every row (session_registry.py)
// and every row already printed the name, so this only groups what the list was already showing.
// sessionCharacterLabel is the one resolver both the tab strip and the row go through, so a tab
// and its rows can never disagree about who a character is.
var SESSION_CHAR_TABS_KEY = 'pe_session_char_tabs';
var sessionCharFilter = localStorage.getItem(SESSION_CHAR_TABS_KEY) || '';
var sessionListCache = [];
const sessionCharTabsEl = document.getElementById('sessionCharTabs');

function sessionCharacterLabel(s) {
  // PRODUCT Brand Commitments: the card owns the name. Live catalog first, then what the server
  // resolved, then the bare id. A session with no character is the team default.
  const id = (s && s.character) || '';
  const c = characterCatalog.find(x => x.id === id);
  if (c && (c.name || c.title)) return c.name || c.title;
  if (s && s.character_name) return s.character_name;
  return id ? id.slice(0, 10) : tr('team.chip_default');
}

function sessionRowWho(s) {
  if (!s || !s.character) return '';
  return sessionCharacterLabel(s) + ' · ';
}

function sessionCharacterGroups(visible) {
  // The "all" group first, then one group per character in catalog order (the order team.json
  // sets), then anything left over sorted by name, so the strip does not reshuffle as counts change.
  // Counts come from `visible`, not the raw list, so a tab's number always matches the rows under it.
  const seen = new Map();
  visible.forEach(s => {
    const id = (s && s.character) || '';
    if (!seen.has(id)) seen.set(id, { id: id, label: sessionCharacterLabel(s), count: 0 });
    seen.get(id).count++;
  });
  const order = characterCatalog.map(c => c.id).filter(id => seen.has(id));
  const rest = Array.from(seen.keys()).filter(id => order.indexOf(id) < 0)
    .sort((a, b) => seen.get(a).label.localeCompare(seen.get(b).label, I18N_LANG));
  return [{ id: '', label: tr('common.all'), count: visible.length }]
    .concat(order.concat(rest).map(id => seen.get(id)));
}

function setSessionCharFilter(id) {
  sessionCharFilter = id || '';
  try { localStorage.setItem(SESSION_CHAR_TABS_KEY, sessionCharFilter); } catch (_) {}
}

function renderSessionCharTabs(groups) {
  if (!sessionCharTabsEl) return;
  // groups[0] is always the "all" group, so fewer than three entries means a single character --
  // and then the strip offers a choice between a list and itself. Stay out of the way.
  if (groups.length < 3) {
    if (sessionCharFilter) setSessionCharFilter('');   // a leftover filter for a strip we are hiding
    sessionCharTabsEl.innerHTML = '';
    sessionCharTabsEl.className = 'session-char-tabs';
    return;
  }
  sessionCharTabsEl.className = 'session-char-tabs on';
  sessionCharTabsEl.innerHTML = '';
  groups.forEach(g => {
    const on = g.id === sessionCharFilter;
    const b = document.createElement('button');
    b.className = 'session-char-tab' + (on ? ' on' : '');
    b.setAttribute('type', 'button');
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', on ? 'true' : 'false');
    b.setAttribute('data-char-id', g.id);
    b.textContent = g.label + ' (' + g.count + ')';
    b.addEventListener('click', () => {
      if (sessionCharFilter === g.id) return;
      setSessionCharFilter(g.id);
      renderSessionsList(sessionListCache);
    });
    sessionCharTabsEl.appendChild(b);
  });
}

function renderSessionsList(sessions) {
  if (!sessionsListEl) return;
  sessionListCache = sessions || [];
  sessionsListEl.innerHTML = '';
  // Hide empty throwaway sessions (e.g. repeated "new session" clicks nobody
  // typed into) -- they clutter the list with nothing useful to open --
  // but never hide the one currently open, even if it happens to be empty.
  const visible = sessionListCache.filter(s => s.preview || s.id === sessionId);
  if (!visible.length) {
    renderSessionCharTabs([]);
    sessionsListEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('sessions.none')) + '</div>';
    return;
  }
  const groups = sessionCharacterGroups(visible);
  // A filter whose character has no sessions left (all of them deleted) must not blank the list.
  if (!groups.some(g => g.id === sessionCharFilter)) setSessionCharFilter('');
  renderSessionCharTabs(groups);
  const shown = sessionCharFilter
    ? visible.filter(s => ((s && s.character) || '') === sessionCharFilter)
    : visible;
  if (!shown.length) {
    sessionsListEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('sessions.none_for_character')) + '</div>';
    return;
  }
  shown.forEach(s => {
    const isCurrent = s.id === sessionId;
    const item = document.createElement('div');
    item.className = 'status-item session-row' + (isCurrent ? ' current' : '');
    let when = s.updated_at || '';
    try { when = new Date(_scrollbackEpochMs(s.updated_at)).toLocaleString(I18N_LANG); } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="session-row-id">' + (s.mode === 'private' ? '🔒 ' : '') + escapeHtml(sessionRowWho(s)) + escapeHtml(s.id) + (isCurrent ? escapeHtml(tr('sessions.current')) : '') + '</span>' +
      '<span class="status-item-meta">' + escapeHtml(tr('sessions.turns', { n: s.turns || 0 })) + ' · ' + escapeHtml(s.model || '') + ' · ' + escapeHtml(when) + '</span>' +
      '<div class="status-item-actions">' +
      '<button class="session-import-btn" data-import-sid="' + escapeHtml(s.id) + '" type="button">' + getActionSvg('pin') + ' ' + escapeHtml(tr('session.import')) + '</button>' +
      '<button class="session-import-btn session-delete-btn" data-delete-sid="' + escapeHtml(s.id) + '" type="button">' + getActionSvg('trash', 'text-danger') + ' ' + escapeHtml(tr('common.delete')) + '</button>' +
      '</div>' +
      '</div>' +
      '<div class="session-row-preview">' + escapeHtml(s.preview || tr('sessions.no_preview')) + '</div>';
    item.addEventListener('click', (ev) => {
      if (ev.target.closest('[data-import-sid], [data-delete-sid]')) return;
      if (s.id !== sessionId) openSession(s.id, 0, null, true);
      switchTab('chat');
    });
    sessionsListEl.appendChild(item);
  });
  sessionsListEl.querySelectorAll('[data-import-sid]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      importSessionContext(btn.getAttribute('data-import-sid'));
    });
  });
  sessionsListEl.querySelectorAll('[data-delete-sid]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      deleteSession(btn.getAttribute('data-delete-sid'));
    });
  });
}

async function deleteSession(sid) {
  if (!sid) return;
  if (!(await confirmModal(tr('sessions.delete_confirm', { sid }), { confirmLabel: tr('common.delete') }))) return;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sid), { method: 'DELETE' });
    if (!res || res.ok === false) throw new Error((res && res.error) || tr('sessions.delete_failed_plain'));
    if (sid === sessionId) {
      // The session we're currently looking at just got deleted -- fall
      // back exactly the way a fresh page load would (ensureSession's own
      // active/localStorage/latest/create chain), instead of a separate,
      // narrower reimplementation of just its "latest or create" tail.
      rememberSession('');
      await ensureSession();
    }
    fetchSessionsList();
  } catch (e) {
    await alertModal(tr('sessions.delete_failed', { error: e.message || e }));
  }
}

// Fetches a read-only handover-style summary of an arbitrary (often archived)
// session and prefills the composer with it, labeled by source session id.
// Never auto-sends -- operator reviews/edits before it becomes part of the live
// conversation, and the target session itself is never modified.
async function importSessionContext(sid) {
  if (!sid) return;
  const prevPlaceholder = inputEl ? inputEl.placeholder : '';
  if (inputEl) inputEl.placeholder = tr('sessions.importing', { sid });
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sid) + '/summary');
    const summary = (res && res.summary) || tr('sessions.nothing_to_summarize');
    const note = tr('sessions.import_note', { sid }) + '\n' + summary + '\n\n';
    switchTab('chat');   // first: the input bar exists only on the chat tab (TAB_CHROME_v1), and a hidden box takes no focus
    if (inputEl) {
      inputEl.value = note + (inputEl.value || '');
      inputEl.focus();
      inputEl.style.height = 'auto';
      inputEl.style.height = inputEl.scrollHeight + 'px';
      updateSendButton();
    }
  } catch (e) {
    await alertModal(tr('sessions.import_failed', { error: e.message || e }));
  } finally {
    if (inputEl) inputEl.placeholder = prevPlaceholder;
  }
}

// STATUS_INSTRUCTIONS_v1: everything the agent reads as instructions, whole and scrollable, in the order it reaches
