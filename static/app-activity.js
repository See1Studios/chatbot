// app-activity.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
let activityEvents = []; // [{ id, line, kind, ts, detail }]
let activityFilter = 'all';
let activitySearchQuery = '';

function matchesActivityFilter(item) {
  if (activityFilter === 'tool') {
    if (item.kind !== 'tool' && item.kind !== 'result') return false;
  } else if (activityFilter === 'system') {
    if (item.kind !== 'system') return false;
  } else if (activityFilter === 'warn_error') {
    if (item.kind !== 'warn' && item.kind !== 'error') return false;
  } else if (activityFilter === 'token') {
    if (item.kind !== 'token') return false;
  }
  if (activitySearchQuery) {
    const q = activitySearchQuery.toLowerCase();
    const l = (item.line || '').toLowerCase();
    const d = (item.detail || '').toLowerCase();
    if (!l.includes(q) && !d.includes(q)) return false;
  }
  return true;
}

function renderActivityRow(item) {
  const row = document.createElement('div');
  const hasDetail = Boolean(item.detail && item.detail.trim());
  row.className = 'act-row' + (item.kind ? ' act-' + item.kind : '') + (hasDetail ? ' has-detail' : '');
  if (item.ts) row.dataset.ts = String(item.ts);
  row.dataset.id = item.id;

  const head = document.createElement('div');
  head.className = 'act-row-head';

  const tsSpan = document.createElement('span');
  tsSpan.className = 'act-ts';
  const d = item.ts ? new Date(item.ts * 1000) : new Date();
  tsSpan.textContent = '[' + d.toLocaleTimeString('ko-KR', { hour12: false }) + ']';

  const textSpan = document.createElement('span');
  textSpan.className = 'act-text';
  textSpan.textContent = item.line;

  head.appendChild(tsSpan);
  head.appendChild(textSpan);

  if (hasDetail) {
    const toggleSpan = document.createElement('span');
    toggleSpan.className = 'act-expand-toggle';
    toggleSpan.textContent = tr('activity.more');
    head.appendChild(toggleSpan);

    const detailBox = document.createElement('pre');
    detailBox.className = 'act-detail-box';
    detailBox.textContent = item.detail;
    detailBox.style.display = 'none';

    row.appendChild(head);
    row.appendChild(detailBox);

    row.addEventListener('click', (e) => {
      // Don't toggle if user is selecting text in detail box
      if (window.getSelection() && window.getSelection().toString().length > 0 && e.target === detailBox) {
        return;
      }
      const isOpen = detailBox.style.display !== 'none';
      detailBox.style.display = isOpen ? 'none' : 'block';
      toggleSpan.textContent = isOpen ? tr('activity.more') : tr('activity.less');
    });
  } else {
    row.appendChild(head);
  }

  return row;
}

function renderAllActivity() {
  if (!activityEl) return;
  const prevScroll = activityEl.scrollHeight - activityEl.scrollTop;
  activityEl.innerHTML = '';
  const filtered = activityEvents.filter(matchesActivityFilter);
  if (!filtered.length) {
    const empty = document.createElement('div');
    empty.className = 'act-row';
    empty.style.color = 'var(--muted)';
    empty.style.padding = '1rem 0';
    empty.textContent = activitySearchQuery ? tr('activity.no_match') : tr('activity.empty');
    activityEl.appendChild(empty);
    return;
  }
  const frag = document.createDocumentFragment();
  filtered.forEach(item => {
    frag.appendChild(renderActivityRow(item));
  });
  activityEl.appendChild(frag);
  activityEl.scrollTop = activityEl.scrollHeight - prevScroll;
}

let _actIdCounter = 1;
function addActivity(line, kind, ts, detail) {
  if (!line) return;
  const item = {
    id: 'act_' + (_actIdCounter++),
    line,
    kind,
    ts: ts || Date.now() / 1000,
    detail: detail || ''
  };
  activityEvents.push(item);
  if (activityEvents.length > 1000) {
    activityEvents.shift();
  }
  if (!activityEl) return;
  if (matchesActivityFilter(item)) {
    const atBottom = (activityEl.scrollHeight - activityEl.scrollTop - activityEl.clientHeight) < 40;
    activityEl.appendChild(renderActivityRow(item));
    if (atBottom || currentTab !== 'activity') {
      activityEl.scrollTop = activityEl.scrollHeight;
    }
  }
}

function prependActivity(line, kind, ts, detail) {
  if (!line) return;
  const item = {
    id: 'act_' + (_actIdCounter++),
    line,
    kind,
    ts: ts || Date.now() / 1000,
    detail: detail || ''
  };
  activityEvents.unshift(item);
  if (activityEvents.length > 1000) {
    activityEvents.pop();
  }
  if (!activityEl) return;
  if (matchesActivityFilter(item)) {
    activityEl.insertBefore(renderActivityRow(item), activityEl.firstChild);
  }
}

// Persisted events (server.py PERSISTED_LOG_KINDS) rendered for the log
// tab's own history -- mirrors bindEvents()'s live 'tool'/'system'/'error'
// formatting so a backfilled row reads the same as it did live. 'result' and
// 'user_ack' are skipped here -- those are already visible as chat bubbles,
// not activity-log lines.
function formatPersistedLogEvent(ev) {
  trEvent(ev);   // I18N_v1: a stored server event shows in the page's language
  const type = ev.event;
  const text = ev.text || '';
  const detail = ev.detail || '';
  if (type === 'tool' || type === 'system' || type === 'stderr' || type === 'error') {
    const line = (type === 'error' ? tr('chat.error_prefix') : '') + (text || JSON.stringify(ev.error || ev));
    const s = String(text || '').trim().toLowerCase();
    if (type === 'tool' && (!s || s === 'tool' || s === 'tool: tool' || s === 'tool:tool')) return null;
    const kind = ev.kind || (type === 'tool' ? (line.startsWith('↳') ? 'result' : 'tool') : (type === 'stderr' ? 'warn' : type));
    return { line, kind, detail };
  }
  if (type === 'queued') return { line: tr('chat.queued', { n: ev.queue_len || 1 }), kind: 'system', detail };
  if (type === 'steer_queued') return { line: tr('activity.steer_queued', { n: ev.queue_len || 1 }), kind: 'system', detail };
  if (type === 'stopped') return { line: tr('chat.stopped_activity', { text }), kind: 'system', detail };
  if (type === 'session_rotate') return { line: tr('chat.auto_rotated', { text }), kind: 'system', detail };
  if (type === 'session_heavy') return { line: tr('chat.heavy_warning', { level: ev.level || 'soft', text }), kind: 'warn', detail };
  if (type === 'btw_start') return { line: tr('chat.btw_working', { text: shortToolLine(ev.query || '') }), kind: 'tool', detail };
  if (type === 'btw') return { line: tr('chat.btw_done'), kind: 'result', detail };
  if (type === 'image') return { line: tr('activity.image', { name: ev.name || ev.url || '' }), kind: 'result', detail };
  return null;
}

async function fetchLog() {
  if (!sessionId || activityLogFetched) return;
  activityLogFetched = true;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/log');
    activityNextBefore = res.next_before || null;
    (res.events || []).slice().reverse().forEach(ev => {
      const f = formatPersistedLogEvent(ev);
      if (f) addActivity(f.line, f.kind, ev.ts, f.detail);
    });
  } catch (e) {
    // the log history is extra: a failed fetch passes quietly
  }
}

// The same cursor paging as the artifacts tab, but the log tab, like the chat tab, loads older records
// as you scroll up (operator 2026-09-18: "load as I scroll up, for artifacts and the log too").
async function loadMoreLog() {
  if (!sessionId || activityLoadingMore || !activityNextBefore) return;
  activityLoadingMore = true;
  const prevScrollHeight = activityEl.scrollHeight;
  const prevScrollTop = activityEl.scrollTop;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/log?before=' + encodeURIComponent(activityNextBefore));
    activityNextBefore = res.next_before || null;
    (res.events || []).forEach(ev => {
      const f = formatPersistedLogEvent(ev);
      if (f) prependActivity(f.line, f.kind, ev.ts, f.detail);
    });
    activityEl.scrollTop = prevScrollTop + (activityEl.scrollHeight - prevScrollHeight);
  } catch (e) {
    // silent -- same rationale as fetchLog
  } finally {
    activityLoadingMore = false;
  }
}


// Activity toolbar event handlers




let sessionTokenTotal = 0;
// Fresh (non-cache) input tokens per turn this session, for relative spike detection.
const turnFreshTokenHistory = [];
// Absolute floor: 2026-09-16 measured baseline is ~14-16K fresh input tokens for a
// trivial first turn (see docs/DEVLOG.md — the ADD_DIRS parent-vs-children bug pushed
// this to ~45K). Anything past this on its own is worth a look regardless of history.
const OCCUPANCY_WARN_ABS = 150000;

function logTurnUsage(usage, durationSeconds) {
  usage = usage || {};
  const total = usage.total_tokens || 0;
  const input = usage.input_tokens || 0;
  const cacheRead = usage.cache_read_tokens || 0;
  if (total) sessionTokenTotal += total;
  if (total || input) updateSessionTokens(usage);

  let warnReason = '';
  if (input >= OCCUPANCY_WARN_ABS) {
    warnReason = tr('activity.warn_window', { n: fmtNumber(input) });
  } else if (turnFreshTokenHistory.length >= 2) {
    const avg = turnFreshTokenHistory.reduce((a, b) => a + b, 0) / turnFreshTokenHistory.length;
    if (avg > 0 && input > avg * 2.5) {
      warnReason = tr('activity.warn_spike', { n: fmtNumber(Math.round(avg)) });
    }
  }
  if (input > 0) turnFreshTokenHistory.push(input);

  const parts = [];
  if (total) parts.push(tr('activity.turn_tokens', { n: fmtNumber(total) }) + (warnReason ? tr('activity.caution') : ''));
  if (usage.input_tokens != null || usage.output_tokens != null) {
    parts.push(tr('activity.tokens_detail', { inp: fmtNumber(input), out: fmtNumber(usage.output_tokens || 0),
      think: usage.thinking_tokens ? tr('activity.thinking_suffix', { n: fmtNumber(usage.thinking_tokens) }) : '',
      cache: cacheRead ? tr('activity.cache_suffix', { n: fmtNumber(cacheRead) }) : '' }));
  }
  if (durationSeconds != null) parts.push(tr('usage.seconds', { s: Number(durationSeconds).toFixed(1) }));
  if (sessionTokenTotal) parts.push(tr('activity.session_total', { n: fmtNumber(sessionTokenTotal) }));
  if (warnReason) parts.push(tr('activity.spike', { reason: warnReason }));
  if (parts.length) addActivity(parts.join(' '), warnReason ? 'warn' : 'token');
}

function formatToolCallClient(name, args) {
  args = args || {};
  function clean(v) {
    if (v == null) return '';
    let s = String(v).trim();
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
      s = s.slice(1, -1).trim();
    }
    s = s.replace(/\/(?:volume1\/homes|home)\/[^\/]+\//g, '');
    s = s.replace(/\/volume1\/web\//g, 'web/');
    return s;
  }
  const action = clean(args.toolAction || args.action);
  const summary = clean(args.toolSummary || args.summary || args.description);
  if (name === 'run_command') {
    const cmd = clean(args.CommandLine || args.command || args.cmd);
    if (!cmd) return ''; // args not populated yet (streaming) - skip, don't show a bare "run_command:"
    let out = 'run_command: ' + cmd;
    if (summary && summary.toLowerCase() !== cmd.toLowerCase()) out += ' (' + summary + ')';
    else if (action && action.toLowerCase() !== cmd.toLowerCase()) out += ' (' + action + ')';
    return out;
  }
  if (name === 'view_file' || name === 'read_file') {
    const p = clean(args.AbsolutePath || args.TargetFile || args.path || args.file);
    if (!p) return '';
    const start = args.StartLine;
    const end = args.EndLine;
    const lines = (start || end) ? ` [L${start || ''}-${end || ''}]` : '';
    let out = 'view_file: ' + p + lines;
    if (summary) out += ' (' + summary + ')';
    else if (action) out += ' (' + action + ')';
    return out;
  }
  if (name === 'grep_search') {
    const q = clean(args.Query || args.query || args.pattern);
    if (!q) return '';
    const sp = clean(args.SearchPath || args.path);
    let out = `grep_search: '${q}' in ${sp || '.'}`;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'find_by_name') {
    const p = clean(args.Pattern || args.pattern);
    if (!p) return '';
    const sd = clean(args.SearchDirectory || args.directory || args.path);
    let out = `find_by_name: '${p}' in ${sd || '.'}`;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'list_dir') {
    const dp = clean(args.DirectoryPath || args.path || args.dir);
    if (!dp) return '';
    let out = 'list_dir: ' + dp;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'replace_file_content' || name === 'edit_file') {
    const tf = clean(args.TargetFile || args.path || args.file);
    if (!tf) return '';
    const inst = clean(args.Instruction || summary || action);
    let out = 'replace_file_content: ' + tf;
    if (inst) out += ' (' + inst + ')';
    return out;
  }
  if (name === 'write_to_file' || name === 'write_file') {
    const tf = clean(args.TargetFile || args.path || args.file);
    if (!tf) return '';
    const desc = clean(args.Description || summary || action);
    let out = 'write_to_file: ' + tf;
    if (desc) out += ' (' + desc + ')';
    return out;
  }
  let target = '';
  for (const k of ['path', 'file', 'AbsolutePath', 'TargetFile', 'command', 'CommandLine', 'query', 'Query', 'pattern', 'url', 'Url', 'DirectoryPath']) {
    if (args[k]) { target = clean(args[k]); break; }
  }
  let out = name;
  if (target) out += ': ' + target;
  const d = summary || action;
  if (d && d.toLowerCase() !== target.toLowerCase()) out += ' (' + d + ')';
  return out;
}

function formatToolResultClient(content) {
  if (!content) return '';
  const lines = String(content).split('\n').map(l => l.trim()).filter(Boolean);
  const filtered = lines.filter(l => !l.startsWith('Created At:') && !l.startsWith('Completed At:'));
  if (!filtered.length) return '↳ ' + tr('activity.done');
  let first = filtered[0];
  if (first.length > 120) first = first.slice(0, 117) + '...';
  return filtered.length > 1 ? '↳ ' + first + tr('activity.more_lines', { n: filtered.length - 1 }) : '↳ ' + first;
}
