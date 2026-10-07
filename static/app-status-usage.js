// The status tab's usage report and the quota of the model in use (USAGE_v1, QUOTA_VIEW_v1). Split from app-status.js
// (size cap); the profile card's quota (app-shell-quota.js) shows quotaNow() from here too.

// QUOTA_VIEW_v1: the model in use belongs to the chat provider; another provider viewed here has none
function statusModel() {
  return (typeof modelEl !== 'undefined' && modelEl && currentStatusProvider() === chatProvider()) ? modelEl.value : '';
}

// The adapter's own reading of the quota of the model in use (res.view), as pills; a figure that is no percentage is text only.
function quotaNow(res, provider, model) {
  const v = res && res.view;
  if (!v || !(v.windows || []).length) return null;
  provider = provider || currentStatusProvider();
  if (model === undefined) model = statusModel();
  const el = document.createElement('div');
  el.className = 'quota-now';
  const head = document.createElement('div');
  head.className = 'quota-now-head';
  head.textContent = provider + (model ? ' \u00b7 ' + model : '') + (v.scope ? ' \u00b7 ' + v.scope : '');
  const pills = document.createElement('div');
  pills.className = 'quota-pills';
  v.windows.forEach(w => {
    const pill = document.createElement('span');
    pill.className = 'quota-pill' + (typeof w.pct === 'number' && w.pct <= 20 ? ' low' : '');
    pill.textContent = (w.label ? w.label + ' ' : '') + w.text;
    if (w.reset_at) pill.title = w.reset_at;
    pills.appendChild(pill);
  });
  el.appendChild(head);
  el.appendChild(pills);
  return el;
}

async function fetchUsage(force, retryCount) {
  // USAGE_v1: after CLI login the first /cost|app-server call often races auth
  // settle; client default api() timeout (12s) was also shorter than the CLI
  // (30–45s). Retry once + longer timeout; server also retries + avoids
  // long-caching failures.
  if (!statusUsageEl) return;
  retryCount = retryCount || 0;
  const provider = currentStatusProvider();
  statusUsageEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('usage.loading', { provider })
    + (retryCount > 0 ? tr('usage.retry_suffix') : '')) + '</div>';
  try {
    const params = new URLSearchParams({provider});
    if (force || retryCount > 0) params.set('force', '1');
    if (statusModel()) params.set('model', statusModel());
    const res = await api('/api/usage?' + params.toString(), { timeoutMs: 55000 });
    if (currentStatusProvider() !== provider) return;
    if ((!res || !res.ok) && res && res.supported !== false && retryCount < 1) {
      setTimeout(() => fetchUsage(true, retryCount + 1), 800);
      return;
    }
    renderStatusUsage(res);
  } catch (e) {
    if (retryCount < 1) {
      setTimeout(() => fetchUsage(true, retryCount + 1), 800);
      return;
    }
    statusUsageEl.innerHTML = '<div class="status-hint">' + escapeHtml(tr('usage.load_failed', { error: e.message })) + '</div>';
  }
}

function renderStatusUsage(res) {
  if (!statusUsageEl) return;
  if (!res || !res.ok) {
    // supported:false (Multi-Provider plan Phase 0.5) -- this provider has no
    // one-shot rate-limit report at all (codex as of this writing), not an
    // error worth alarming over.
    const msg = (res && res.supported === false)
      ? (trField(res, 'error') || tr('usage.unsupported'))
      : tr('usage.query_failed', { error: trField(res, 'error') || tr('common.unknown_error') });
    statusUsageEl.innerHTML = '<div class="status-hint">' + escapeHtml(msg) + '</div>';
    if (usageCheckedAtEl) usageCheckedAtEl.textContent = '';
    return;
  }
  statusUsageEl.innerHTML = '';
  const now = quotaNow(res);
  if (now) statusUsageEl.appendChild(now);
  (res.rows || []).forEach(row => {
    const pct = parseInt(row.remaining_pct, 10);
    const pctSafe = isNaN(pct) ? 0 : Math.max(0, Math.min(100, pct));
    const item = document.createElement('div');
    item.className = 'status-item';
    let resetStr = trField(row, 'reset_at');   // words by key, or a time to format
    try {
      const d = new Date(row.reset_at);
      if (!row.reset_at_key && !isNaN(d.getTime())) resetStr = d.toLocaleString(I18N_LANG);
    } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(trField(row, 'group')) + ' — ' + escapeHtml(trField(row, 'limit_type')) + '</span>' +
      '<span class="status-item-meta">' + escapeHtml(tr('usage.left', { pct: trField(row, 'remaining_pct') })) + '</span>' +
      '</div>' +
      '<div class="usage-bar-track"><div class="usage-bar-fill' + (pctSafe <= 20 ? ' low' : '') + '" style="transform:scaleX(' + (pctSafe / 100) + ')"></div></div>' +
      '<div class="status-item-preview">' + escapeHtml(tr('usage.reset', { when: resetStr })) + '</div>';
    statusUsageEl.appendChild(item);
  });
  if (usageCheckedAtEl) {
    const checked = res.checked_at ? new Date(res.checked_at * 1000).toLocaleTimeString(I18N_LANG) : '';
    usageCheckedAtEl.textContent = checked ? tr('usage.checked', { when: checked }) : '';
  }
}
