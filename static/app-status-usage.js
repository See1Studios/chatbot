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
  statusUsageEl.innerHTML = '<div class="status-hint">불러오는 중… (' + escapeHtml(provider)
    + (retryCount > 0 ? ', 재시도' : '') + ')</div>';
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
    statusUsageEl.innerHTML = '<div class="status-hint">사용량 로드 실패: ' + escapeHtml(e.message) + '</div>';
  }
}

function renderStatusUsage(res) {
  if (!statusUsageEl) return;
  if (!res || !res.ok) {
    // supported:false (Multi-Provider plan Phase 0.5) -- this provider has no
    // one-shot rate-limit report at all (codex as of this writing), not an
    // error worth alarming over.
    const msg = (res && res.supported === false)
      ? (res.error || '이 프로바이더는 사용량 조회를 지원하지 않습니다')
      : '조회 실패: ' + ((res && res.error) || '알 수 없는 오류');
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
    let resetStr = row.reset_at;
    try {
      const d = new Date(row.reset_at);
      if (!isNaN(d.getTime())) resetStr = d.toLocaleString('ko-KR');
    } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(row.group) + ' — ' + escapeHtml(row.limit_type) + '</span>' +
      '<span class="status-item-meta">' + escapeHtml(row.remaining_pct) + ' 남음</span>' +
      '</div>' +
      '<div class="usage-bar-track"><div class="usage-bar-fill' + (pctSafe <= 20 ? ' low' : '') + '" style="transform:scaleX(' + (pctSafe / 100) + ')"></div></div>' +
      '<div class="status-item-preview">리셋: ' + escapeHtml(resetStr) + '</div>';
    statusUsageEl.appendChild(item);
  });
  if (usageCheckedAtEl) {
    const checked = res.checked_at ? new Date(res.checked_at * 1000).toLocaleTimeString('ko-KR') : '';
    usageCheckedAtEl.textContent = checked ? ('마지막 확인: ' + checked) : '';
  }
}
