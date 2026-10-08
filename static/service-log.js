// OBSLOG_UI_v1: log tab → "Service". The same logs/events.jsonl that agents read through
// `chatbot-ctl.sh logs`, shown for people: findings first, then state, then recent events.
// Data: GET /api/service-log?since=24h[&sid=...] (server.py _service_log → telemetry/logdigest.py).
(function () {
  const btn = document.getElementById('svcLogBtn');
  const pane = document.getElementById('svcLog');
  const activity = document.getElementById('activity');
  const copyBtn = document.getElementById('actCopyBtn');
  const refreshBtn = document.getElementById('actRefreshBtn');
  const searchInput = document.getElementById('actSearchInput');
  if (!btn || !pane || !activity) return;

  const base = (typeof BASE_PATH === 'string') ? BASE_PATH : '';
  let active = false;
  let since = '24h';
  let onlySession = false;
  let data = null;
  let timer = null;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const hhmm = (ts) => {
    if (!ts) return '';
    const d = new Date(ts);
    return isNaN(d) ? String(ts) : d.toLocaleString(I18N_LANG, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  };
  const currentSid = () => (typeof sessionId !== 'undefined' && sessionId) ? sessionId : '';
  const SKIP = new Set(['ts', 'lvl', 'src', 'evt', 'pid', 'msg', 'err']);

  function eventLine(e) {
    const bits = [];
    for (const k of Object.keys(e)) {
      if (SKIP.has(k)) continue;
      const v = e[k];
      if (v == null || v === '' || (Array.isArray(v) && !v.length)) continue;
      bits.push(k + '=' + (typeof v === 'object' ? JSON.stringify(v) : v));
    }
    let line = e.evt + '  ' + bits.join(' ');
    if (e.msg) line += '  | ' + e.msg;
    if (e.err) line += '  | ' + e.err.type + ': ' + e.err.msg + (e.err.where ? ' @' + e.err.where : '');
    return line;
  }

  function matches(text) {
    const q = (searchInput && searchInput.value || '').trim().toLowerCase();
    return !q || text.toLowerCase().includes(q);
  }

  function row(e) {
    const line = eventLine(e);
    const r = el('div', 'act-row svc-ev svc-' + (e.lvl || 'info'));
    const head = el('div', 'act-row-head');
    head.appendChild(el('span', 'act-ts', '[' + hhmm(e.ts) + ']'));
    head.appendChild(el('span', 'svc-src', e.src || ''));
    head.appendChild(el('span', 'act-text', line));
    r.appendChild(head);
    const detail = e.err && e.err.trace ? e.err.trace : JSON.stringify(e, null, 1);
    const box = el('pre', 'act-detail-box', detail);
    box.style.display = 'none';
    r.classList.add('has-detail');
    r.appendChild(box);
    r.addEventListener('click', (ev) => {
      if (window.getSelection && window.getSelection().toString() && ev.target === box) return;
      box.style.display = box.style.display === 'none' ? 'block' : 'none';
    });
    return r;
  }

  function kv(label, value) {
    const d = el('div', 'svc-kv');
    d.appendChild(el('span', 'svc-k', label));
    d.appendChild(el('span', 'svc-v', value));
    return d;
  }

  function render() {
    pane.innerHTML = '';
    const bar = el('div', 'svc-bar');
    const st = data && data.digest ? data.digest.status : 'loading';
    bar.appendChild(el('span', 'svc-badge svc-badge-' + st, st === 'loading' ? tr('svc.loading') : st.toUpperCase()));
    ['1h', '24h', '7d'].forEach((w) => {
      const b = el('button', 'act-filter-btn' + (w === since ? ' on' : ''), w);
      b.type = 'button';
      b.addEventListener('click', () => { since = w; load(); });
      bar.appendChild(b);
    });
    const sesBtn = el('button', 'act-filter-btn' + (onlySession ? ' on' : ''), tr('svc.only_session'));
    sesBtn.type = 'button';
    sesBtn.disabled = !currentSid();
    sesBtn.addEventListener('click', () => { onlySession = !onlySession; load(); });
    bar.appendChild(sesBtn);
    const cp = el('button', 'act-filter-btn', tr('common.copy'));
    cp.type = 'button';
    cp.addEventListener('click', copy);
    bar.appendChild(cp);
    pane.appendChild(bar);
    if (!data) return;
    if (!data.ok) { pane.appendChild(el('div', 'svc-empty', tr('svc.load_failed', { error: data.error || '' }))); return; }
    if (!data.log_exists) { pane.appendChild(el('div', 'svc-empty', tr('svc.no_log'))); return; }
    const d = data.digest;

    const fs = el('section', 'svc-sec');
    fs.appendChild(el('h4', null, tr('svc.findings', { n: d.findings.length })));
    if (!d.findings.length) fs.appendChild(el('div', 'svc-ok', tr('svc.all_clear')));
    d.findings.forEach((f) => {
      const c = el('div', 'svc-finding svc-' + f.severity);
      c.appendChild(el('div', 'svc-f-title', '[' + f.severity.toUpperCase() + '] ' + f.title));
      c.appendChild(el('div', 'svc-f-hint', '→ ' + f.hint));
      fs.appendChild(c);
    });
    pane.appendChild(fs);

    const ss = el('section', 'svc-sec svc-grid');
    Object.keys(d.processes || {}).forEach((src) => {
      const p = d.processes[src];
      const hb = p.last_heartbeat || {};
      const box = el('div', 'svc-card');
      box.appendChild(el('h4', null, src));
      box.appendChild(kv('pid', String(p.last_pid ?? '-')));
      box.appendChild(kv(tr('svc.starts'), tr('svc.times', { n: p.starts })));
      box.appendChild(kv('uptime', hb.uptime_s != null ? tr('status.age.min', { n: Math.round(hb.uptime_s / 60) }) : '-'));
      box.appendChild(kv('rss', p.rss_mb ? p.rss_mb.last + 'MB (max ' + p.rss_mb.max + ')' : '-'));
      if (hb.sessions != null) box.appendChild(kv(tr('svc.sessions'), tr('svc.sessions_value', { n: hb.sessions, busy: (hb.busy || []).length, agents: hb.agent_procs })));
      box.appendChild(kv(tr('svc.last'), hhmm(p.last_event)));
      ss.appendChild(box);
    });
    const ops = d.ops || {};
    const ob = el('div', 'svc-card');
    ob.appendChild(el('h4', null, tr('svc.ops')));
    ob.appendChild(kv('repair', tr('svc.times', { n: ops.repairs }) + (ops.repair_failed ? tr('svc.failed_count', { n: ops.repair_failed }) : '')));
    ob.appendChild(kv(tr('svc.callers'), JSON.stringify(ops.repair_callers || {})));
    ob.appendChild(kv('probe', JSON.stringify(ops.doctor_probe || {})));
    ob.appendChild(kv(tr('svc.reaped'), JSON.stringify(ops.reaped || {})));
    ss.appendChild(ob);
    const tb = el('div', 'svc-card');
    tb.appendChild(el('h4', null, tr('svc.turns')));
    const tp = (d.turns && d.turns.by_provider) || {};
    if (!Object.keys(tp).length) tb.appendChild(kv('-', tr('svc.no_records')));
    Object.keys(tp).forEach((prov) => {
      const t = tp[prov];
      tb.appendChild(kv(prov, tr('svc.turn_stats', { n: t.total, fail: Math.round(t.fail_rate * 100), p50: t.p50_s })));
    });
    ss.appendChild(tb);
    pane.appendChild(ss);

    const es = el('section', 'svc-sec');
    es.appendChild(el('h4', null, (onlySession ? tr('svc.session_timeline') : tr('svc.recent_events')) + ' (' + data.events.length + ')'));
    const shown = data.events.filter((e) => matches(eventLine(e)));
    if (!shown.length) es.appendChild(el('div', 'svc-empty', tr('svc.no_events')));
    shown.forEach((e) => es.appendChild(row(e)));
    pane.appendChild(es);
  }

  async function load() {
    if (!active) return;
    const sid = onlySession ? currentSid() : '';
    const url = base + '/api/service-log?since=' + encodeURIComponent(since) + (sid ? '&sid=' + encodeURIComponent(sid) : '');
    try {
      const r = await fetch(url, { cache: 'no-store' });
      data = await r.json();
    } catch (err) {
      data = { ok: false, error: String(err) };
    }
    if (active) render();
  }

  async function copy() {
    if (!data || !data.ok) return;
    const d = data.digest;
    const lines = [tr('svc.copy_head', { since, status: d.status })];
    d.findings.forEach((f) => lines.push('[' + f.severity.toUpperCase() + '] ' + f.title + '\n  → ' + f.hint));
    data.events.filter((e) => matches(eventLine(e))).forEach((e) => lines.push('[' + hhmm(e.ts) + '] ' + e.src + ' ' + eventLine(e)));
    try { await navigator.clipboard.writeText(lines.join('\n')); } catch (_) { /* clipboard blocked: ignore */ }
  }

  function enter() {
    active = true;
    document.querySelectorAll('.act-filter-btn[data-filter]').forEach((b) => b.classList.remove('on'));
    btn.classList.add('on');
    activity.style.display = 'none';
    if (copyBtn) copyBtn.style.display = 'none';
    pane.style.display = '';
    data = null;
    render();
    load();
    clearInterval(timer);
    timer = setInterval(() => { if (active && !document.hidden && pane.offsetParent) load(); }, 60000);
  }

  function leave() {
    if (!active) return;
    active = false;
    clearInterval(timer);
    btn.classList.remove('on');
    pane.style.display = 'none';
    activity.style.display = '';
    if (copyBtn) copyBtn.style.display = '';
  }

  btn.addEventListener('click', () => (active ? load() : enter()));
  document.querySelectorAll('.act-filter-btn[data-filter]').forEach((b) => b.addEventListener('click', leave));
  if (refreshBtn) refreshBtn.addEventListener('click', () => { if (active) load(); });
  if (searchInput) searchInput.addEventListener('input', () => { if (active && data) render(); });
})();
