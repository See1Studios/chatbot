// Profile: the quota of the model in use, pinned under the name card (QUOTA_VIEW_v1). The adapter shapes the view
// (/api/usage?model=); this only fetches and shows it, with quotaNow() from app-status-usage.js. Split from app-shell.js
// (size cap); shellProfileOpen adds it when this file is loaded. Stays hidden until there is something to show:
// a provider with no usage report, a failed call, or a panel closed meanwhile adds nothing.
function shellQuotaSection() {
  const box = shellEl('div', 'shell-quota');
  box.hidden = true;
  const model = typeof modelEl !== 'undefined' && modelEl ? modelEl.value : '';
  shellFillQuota(box, typeof chatProvider === 'function' ? chatProvider() : '', model);
  return box;
}
async function shellFillQuota(box, provider, model) {
  if (!provider || typeof quotaNow !== 'function') return;
  try {
    const q = new URLSearchParams({ provider });
    if (model) q.set('model', model);
    const res = await api('/api/usage?' + q.toString(), { timeoutMs: 55000 });   // a cold CLI report takes tens of seconds
    const now = quotaNow(res, provider, model);
    if (!now || !box.isConnected) return;   // no limits to show, or the panel was rebuilt meanwhile
    box.textContent = '';
    box.appendChild(now);
    box.hidden = false;
  } catch (e) { /* the quota is extra: the card stays as it was */ }
}
