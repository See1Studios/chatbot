// OBSLOG_UI_v1: 로그 탭 → "서비스". The same logs/events.jsonl that agents read through
// `chatbot-ctl.sh logs`, shown for people: findings first, then state, then recent events.
// Data: GET /api/service-log?since=24h[&sid=...] (server.py _service_log → logdigest.py).
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
    return isNaN(d) ? String(ts) : d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
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
    bar.appendChild(el('span', 'svc-badge svc-badge-' + st, st === 'loading' ? '불러오는 중' : st.toUpperCase()));
    ['1h', '24h', '7d'].forEach((w) => {
      const b = el('button', 'act-filter-btn' + (w === since ? ' on' : ''), w);
      b.type = 'button';
      b.addEventListener('click', () => { since = w; load(); });
      bar.appendChild(b);
    });
    const sesBtn = el('button', 'act-filter-btn' + (onlySession ? ' on' : ''), '이 세션만');
    sesBtn.type = 'button';
    sesBtn.disabled = !currentSid();
    sesBtn.addEventListener('click', () => { onlySession = !onlySession; load(); });
    bar.appendChild(sesBtn);
    const cp = el('button', 'act-filter-btn', '복사');
    cp.type = 'button';
    cp.addEventListener('click', copy);
    bar.appendChild(cp);
    pane.appendChild(bar);
    if (!data) return;
    if (!data.ok) { pane.appendChild(el('div', 'svc-empty', '서비스 로그를 불러오지 못했습니다: ' + (data.error || ''))); return; }
    if (!data.log_exists) { pane.appendChild(el('div', 'svc-empty', '아직 logs/events.jsonl 이 없습니다 (서버 재시작 후 기록 시작).')); return; }
    const d = data.digest;

    const fs = el('section', 'svc-sec');
    fs.appendChild(el('h4', null, '발견 사항 ' + d.findings.length));
    if (!d.findings.length) fs.appendChild(el('div', 'svc-ok', '이상 없음'));
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
      box.appendChild(kv('시작', p.starts + '회'));
      box.appendChild(kv('uptime', hb.uptime_s != null ? Math.round(hb.uptime_s / 60) + '분' : '-'));
      box.appendChild(kv('rss', p.rss_mb ? p.rss_mb.last + 'MB (max ' + p.rss_mb.max + ')' : '-'));
      if (hb.sessions != null) box.appendChild(kv('세션', hb.sessions + ' / busy ' + (hb.busy || []).length + ' / 에이전트 ' + hb.agent_procs));
      box.appendChild(kv('마지막', hhmm(p.last_event)));
      ss.appendChild(box);
    });
    const ops = d.ops || {};
    const ob = el('div', 'svc-card');
    ob.appendChild(el('h4', null, '운영'));
    ob.appendChild(kv('repair', ops.repairs + '회' + (ops.repair_failed ? ' (실패 ' + ops.repair_failed + ')' : '')));
    ob.appendChild(kv('호출자', JSON.stringify(ops.repair_callers || {})));
    ob.appendChild(kv('probe', JSON.stringify(ops.doctor_probe || {})));
    ob.appendChild(kv('정리된 프로세스', JSON.stringify(ops.reaped || {})));
    ss.appendChild(ob);
    const tb = el('div', 'svc-card');
    tb.appendChild(el('h4', null, '턴'));
    const tp = (d.turns && d.turns.by_provider) || {};
    if (!Object.keys(tp).length) tb.appendChild(kv('-', '기록 없음'));
    Object.keys(tp).forEach((prov) => {
      const t = tp[prov];
      tb.appendChild(kv(prov, t.total + '턴, 실패 ' + Math.round(t.fail_rate * 100) + '%, p50 ' + t.p50_s + 's'));
    });
    ss.appendChild(tb);
    pane.appendChild(ss);

    const es = el('section', 'svc-sec');
    es.appendChild(el('h4', null, (onlySession ? '이 세션 타임라인' : '최근 경고·오류·운영 이벤트') + ' (' + data.events.length + ')'));
    const shown = data.events.filter((e) => matches(eventLine(e)));
    if (!shown.length) es.appendChild(el('div', 'svc-empty', '표시할 이벤트가 없습니다.'));
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
    const lines = ['서비스 로그 ' + since + ' 상태=' + d.status];
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
