// app-handoffs.js -- handoffs on the page (HANDOFF_BOARD_v1): the open ones, and the ones just closed, as cards above
// the work cards, each open one with a cancel button (HANDOFF_CANCEL_v1). Declarations only; loadWork refreshes it.
const HANDOFF_STATE_LABEL = {  // l10n-ok
  sent: '대기', running: '진행 중', waiting: '맡긴 일 기다림', resume: '이어서 할 차례',  // l10n-ok
  done: '완료', partial: '부분 완료', failed: '실패', cancelled: '취소됨',  // l10n-ok
};

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
  head.appendChild(obsNode('span', 'work-title', h.from + ' → ' + h.to + ' (' + h.role + ')'));  // l10n-ok
  head.appendChild(obsNode('span', 'obs-badge ' + h.state, HANDOFF_STATE_LABEL[h.state] || h.state));
  if (h.open) {
    const stop = obsNode('button', 'art-btn art-btn-xs', '취소');  // l10n-ok
    stop.type = 'button';
    stop.style.marginLeft = 'auto';
    stop.addEventListener('click', () => cancelHandoff(h, stop));
    head.appendChild(stop);
  }
  card.appendChild(head);
  const age = h.since ? workElapsed(Date.now() / 1000 - h.since) : '';
  card.appendChild(obsNode('div', 'handoff-task', (age ? age + ' · ' : '') + (h.task || '')));
  if (h.outcome) card.appendChild(obsNode('div', 'handoff-outcome', h.outcome));
  return card;
}

async function cancelHandoff(h, btn) {
  if (!confirm('넘기기 #' + h.id + '을(를) 취소할까요? 진행 중이면 그 턴이 멈춥니다.')) return;  // l10n-ok
  btn.disabled = true;
  try {
    await api('/api/handoffs/' + h.id + '/cancel', { method: 'POST', body: JSON.stringify({ reason: '운영자가 화면에서 취소' }) });  // l10n-ok
    addNotice('ok', '넘기기 #' + h.id + ' 취소');  // l10n-ok
  } catch (e) {
    addNotice('error', '넘기기 취소 실패: ' + obsErrorText(e));  // l10n-ok
  }
  loadHandoffs();
}
