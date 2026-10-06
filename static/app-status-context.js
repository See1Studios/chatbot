// app-status-context.js -- the status tab's "what went into this conversation" (CONTEXT_PANEL_v1, layered-context-
// architecture lca/E), split from app-status.js (size cap). Declarations only; fetchSelfStatus calls loadContextNow.
// CONTEXT_PANEL_v1 (layered-context-architecture lca/E): what went into the open conversation's agent -- the last
// whole bundle, then what was added after it (changed memory, matched lore), item by item with sizes.
const CONTEXT_LAYER_NAME = {
  charter: '집 규칙(헌장)', private_charter: '집 규칙(사적용)', lore_before: '세계 설정(앞)', lore_after: '세계 설정(뒤)',  // l10n-ok
  persona: '캐릭터', private_persona: '캐릭터', roles: '맡은 역할 규칙', private_rules: '사적 규칙', private_protocol: '사적 진행 규칙',  // l10n-ok
  skills: '스킬 목록', house_memory: '집 기억', own_memory: '자기 기억', private_memory: '사적 기억', names: '이름 변경',  // l10n-ok
  status: '자기개선 상태', lore_match: '대화에 걸린 세계 설정',  // l10n-ok
};
const CONTEXT_WHY = { first: '첫 턴에 통째로', rules_changed: '규칙이 바뀌어 통째로', refresh: '바뀐 기억만 덧붙임', lore: '걸린 설정만 덧붙임' };  // l10n-ok

async function loadContextNow() {
  const el = document.getElementById('statusContext');
  if (!el) return;
  const sid = typeof sessionId !== 'undefined' ? sessionId : '';
  if (!sid) { el.textContent = '열린 대화가 없어요.'; return; }  // l10n-ok
  let res;
  try {
    res = await api('/api/sessions/' + encodeURIComponent(sid) + '/context');
  } catch (e) {
    el.textContent = '불러오지 못했어요: ' + (e.message || e);  // l10n-ok
    return;
  }
  const recs = res.records || [];
  el.textContent = '';
  let whole = -1;   // the last whole bundle; what came after it is what the agent has on top
  recs.forEach((r, i) => { if (r.why === 'first' || r.why === 'rules_changed') whole = i; });
  const shown = whole >= 0 ? recs.slice(whole) : recs;
  if (!shown.length) { el.textContent = '아직 기록이 없어요. 이 대화의 다음 턴부터 남습니다.'; return; }  // l10n-ok
  shown.forEach(r => el.appendChild(contextRecord(r)));
}

function contextRecord(r) {
  const item = obsNode('details', 'status-item ctx-item');
  const head = obsNode('summary', 'ctx-head');
  const when = r.ts ? new Date(r.ts * 1000).toLocaleTimeString('ko-KR') : '';
  head.textContent = (CONTEXT_WHY[r.why] || r.why) + ' · ' + Number(r.chars || 0).toLocaleString('ko-KR') + '자' + (when ? ' · ' + when : '');  // l10n-ok
  item.appendChild(head);
  (r.layers || []).forEach(x => {
    item.appendChild(obsNode('div', 'ctx-layer', (CONTEXT_LAYER_NAME[x.id] || x.id) + ' ' + Number(x.chars || 0).toLocaleString('ko-KR') + '자'));  // l10n-ok
  });
  if (r.why === 'first' || r.why === 'rules_changed') item.open = true;
  return item;
}
