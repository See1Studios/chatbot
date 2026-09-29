// app-flow.js -- CHAT_FLOW_v1 (docs/plans/ux-shell-roadmap.md 4.2.1b, ux/D2): the conversation's time, shown the
// way a companion would. Declarations and one document-level observer only: it loads before app.js.
//
// - Day dividers before the first message of each local day: "today", "yesterday", "Saturday, September 27" in the
//   page's language, made by Intl (no words in this file). A message still arriving (no time yet) counts as now.
// - Sessions are the brain's memory windows, not the relationship: their scrollback dividers show only in the
//   advanced density (body.density-advanced, align/K); switching or importing a session is in the sessions tab too.
// - A run of the user's bubbles sent within FLOW_GROUP_SEC sits close together (.cont), messenger-style.
// Every render path (live stream, sync, scrollback) changes #log's children, so one observer redraws the marks on
// the next frame and no path has to remember to call it; a timer redraws at local midnight on an idle page.
const FLOW_GROUP_SEC = 300;

function flowDayKey(ms) {
  const d = new Date(ms);
  return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
}

function flowDayLabel(ms, nowMs, lang) {
  const startOf = (t) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const diff = Math.round((startOf(ms) - startOf(nowMs)) / 86400000);
  if (diff === 0 || diff === -1) {
    try { return new Intl.RelativeTimeFormat(lang, { numeric: 'auto' }).format(diff, 'day'); } catch (_) { /* below */ }
  }
  const opts = { month: 'long', day: 'numeric', weekday: 'long' };
  if (new Date(ms).getFullYear() !== new Date(nowMs).getFullYear()) opts.year = 'numeric';
  try { return new Intl.DateTimeFormat(lang, opts).format(new Date(ms)); } catch (_) { return new Date(ms).toDateString(); }
}

// items: [{role, ts}] in page order, ts in seconds (0 = not stamped yet)
// -> {dividers: [{before: index, label}], cont: [indexes of user bubbles that continue a run]}
function planFlow(items, nowMs, lang) {
  const dividers = [];
  const cont = [];
  let lastDay = null;
  let prev = null;
  items.forEach((it, i) => {
    const ms = it.ts ? it.ts * 1000 : nowMs;
    const key = flowDayKey(ms);
    if (key !== lastDay) {
      dividers.push({ before: i, label: flowDayLabel(ms, nowMs, lang) });
      lastDay = key;
      prev = null;
    }
    if (prev && it.role === 'user' && prev.role === 'user' && Math.abs(ms - prev.ms) <= FLOW_GROUP_SEC * 1000) cont.push(i);
    prev = { role: it.role, ms };
  });
  return { dividers, cont };
}

function flowMessages(log) {
  return Array.from(log.children).filter(n => n.classList.contains('msg')
    && !n.classList.contains('scrollback-marker') && !n.classList.contains('day-divider'));
}

function applyFlow(log) {
  if (!log) return;
  const nodes = flowMessages(log);
  // keep what the reader is looking at where it is: the first message on screen, and its distance from the top
  const anchor = nodes.find(n => n.offsetTop + n.offsetHeight > log.scrollTop) || null;
  const anchorTop = anchor ? anchor.offsetTop - log.scrollTop : 0;
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 4;
  const lang = document.documentElement.lang || navigator.language || 'ko';
  const plan = planFlow(nodes.map(n => ({ role: n.classList.contains('user') ? 'user' : 'other',
                                          ts: Number(n.dataset.ts || 0) })), Date.now(), lang);
  log.querySelectorAll(':scope > .day-divider').forEach(d => d.remove());
  nodes.forEach(n => n.classList.remove('cont'));
  plan.cont.forEach(i => nodes[i].classList.add('cont'));
  plan.dividers.forEach(d => {
    const el = document.createElement('div');
    el.className = 'day-divider';
    el.setAttribute('role', 'separator');
    el.textContent = d.label;
    log.insertBefore(el, nodes[d.before]);
  });
  if (atBottom) log.scrollTop = log.scrollHeight;
  else if (anchor) log.scrollTop = anchor.offsetTop - anchorTop;
}

function startChatFlow() {
  const log = document.getElementById('log');
  if (!log || typeof MutationObserver === 'undefined') return;
  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      applyFlow(log);
      observer.takeRecords();   // our own dividers are not a new render
    });
  });
  observer.observe(log, { childList: true });
  applyFlow(log);
  // an idle page left open past midnight: "today" becomes "yesterday" without waiting for the next message
  const atMidnight = () => {
    setTimeout(() => { applyFlow(log); observer.takeRecords(); atMidnight(); }, msToNextMidnight(Date.now()) + 1000);
  };
  atMidnight();
}

// CHAT_DENSITY_v1 (operator 2026-09-29, the first piece of align/K's densities): the "details" switch in the "..."
// menu. Off, the chat is the conversation: no token or model meters on bubbles, no session dividers, the copy/read
// buttons only on hover. On (body.density-advanced), everything as before. Remembered in this browser only.
const DENSITY_KEY = 'pe.density';

function setDensity(advanced) {
  document.body.classList.toggle('density-advanced', Boolean(advanced));
  const btn = document.getElementById('densityBtn');
  if (btn) btn.setAttribute('aria-checked', advanced ? 'true' : 'false');
  try { localStorage.setItem(DENSITY_KEY, advanced ? 'advanced' : 'simple'); } catch (_) { /* private window */ }
}

function startDensity() {
  let saved = '';
  try { saved = localStorage.getItem(DENSITY_KEY) || ''; } catch (_) { /* private window */ }
  setDensity(saved === 'advanced');
  const btn = document.getElementById('densityBtn');
  if (btn) btn.addEventListener('click', () => setDensity(!document.body.classList.contains('density-advanced')));
}

// milliseconds from `nowMs` to the next local midnight
function msToNextMidnight(nowMs) {
  const d = new Date(nowMs);
  d.setHours(24, 0, 0, 0);
  return d.getTime() - nowMs;
}

if (typeof document !== 'undefined' && document.addEventListener) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startChatFlow);
    document.addEventListener('DOMContentLoaded', startDensity);
  } else {
    startChatFlow();
    startDensity();
  }
}
