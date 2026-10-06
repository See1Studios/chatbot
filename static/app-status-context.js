// app-status-context.js -- the status tab's "what went into this conversation" (CONTEXT_PANEL_v1, layered-context-
// architecture lca/E), split from app-status.js (size cap). Declarations only; fetchSelfStatus calls loadContextNow.
// CONTEXT_PANEL_v1 (layered-context-architecture lca/E): what went into the open conversation's agent -- the last
// whole bundle, then what was added after it (changed memory, matched lore), item by item with sizes.
// Names by key (I18N_v1): context.layer.<layer id>, context.why.<why>.

async function loadContextNow() {
  const el = document.getElementById('statusContext');
  if (!el) return;
  const sid = typeof sessionId !== 'undefined' ? sessionId : '';
  if (!sid) { el.textContent = t('context.none_open'); return; }
  let res;
  try {
    res = await api('/api/sessions/' + encodeURIComponent(sid) + '/context');
  } catch (e) {
    el.textContent = t('context.load_failed', { error: e.message || e });
    return;
  }
  const recs = res.records || [];
  el.textContent = '';
  let whole = -1;   // the last whole bundle; what came after it is what the agent has on top
  recs.forEach((r, i) => { if (r.why === 'first' || r.why === 'rules_changed') whole = i; });
  const shown = whole >= 0 ? recs.slice(whole) : recs;
  if (!shown.length) { el.textContent = t('context.no_records'); return; }
  shown.forEach(r => el.appendChild(contextRecord(r)));
}

function contextRecord(r) {
  const item = obsNode('details', 'status-item ctx-item');
  const head = obsNode('summary', 'ctx-head');
  const when = r.ts ? fmtTime(r.ts * 1000) : '';
  head.textContent = t('context.why.' + r.why) + ' · ' + t('context.chars', { n: fmtNumber(r.chars) }) + (when ? ' · ' + when : '');
  item.appendChild(head);
  (r.layers || []).forEach(x => {
    item.appendChild(obsNode('div', 'ctx-layer', t('context.layer.' + x.id) + ' ' + t('context.chars', { n: fmtNumber(x.chars) })));
  });
  if (r.why === 'first' || r.why === 'rules_changed') item.open = true;
  return item;
}
