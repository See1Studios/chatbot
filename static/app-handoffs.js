// app-handoffs.js -- handoffs on the page (HANDOFF_BOARD_v1): the open ones, and the ones just closed, as cards above
// the work cards, each open one with a cancel button (HANDOFF_CANCEL_v1). Declarations only; loadWork refreshes it.

async function loadHandoffs() {
  const bar = document.getElementById('handoffBar');
  if (!bar) return;
  let res;
  try {
    res = await api('/api/handoffs');
  } catch (e) {
    return;   // the cards are extra: keep what is shown
  }
  const list = res.handoffs || [];
  bar.textContent = '';
  bar.hidden = !list.length;
  list.forEach(h => bar.appendChild(handoffCard(h)));
}

function handoffCard(h) {
  const card = obsNode('div', 'work-card handoff-card handoff-' + h.state);
  const head = obsNode('div', 'work-head');
  head.appendChild(obsNode('span', 'obs-id', '↪#' + h.id));
  head.appendChild(obsNode('span', 'work-title', h.from + ' → ' + h.to + ' (' + h.role + ')'));
  head.appendChild(obsNode('span', 'obs-badge ' + h.state, t('handoff.state.' + h.state)));
  if (h.open) {
    const stop = obsNode('button', 'art-btn art-btn-xs', t('handoff.cancel'));
    stop.type = 'button';
    stop.style.marginLeft = 'auto';
    stop.addEventListener('click', () => cancelHandoff(h, stop));
    head.appendChild(stop);
  }
  card.appendChild(head);
  const age = h.since ? workElapsed(Date.now() / 1000 - h.since) : '';
  const task = (age ? age + ' · ' : '') + (h.task || '');
  if (!h.result) {
    card.appendChild(obsNode('div', 'handoff-task', task));
    return card;
  }
  const more = obsNode('details', 'handoff-more');   // the result as written, opened from the task line
  more.appendChild(obsNode('summary', 'handoff-task', task));
  more.appendChild(obsNode('div', 'handoff-result', h.result));
  card.appendChild(more);
  return card;
}

async function cancelHandoff(h, btn) {
  if (!confirm(t('handoff.cancel_confirm', { id: h.id }))) return;
  btn.disabled = true;
  try {
    await api('/api/handoffs/' + h.id + '/cancel', { method: 'POST', body: JSON.stringify({ reason: 'cancelled by the operator on the page' }) });   // a ledger record: English, like every engine reason
    addNotice('ok', t('handoff.cancelled', { id: h.id }));
  } catch (e) {
    addNotice('error', t('handoff.cancel_failed', { error: obsErrorText(e) }));
  }
  loadHandoffs();
}
