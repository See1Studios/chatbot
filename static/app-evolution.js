// app-evolution.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// ---- observation manager (status tab) ----
// Everything below puts text into nodes with textContent only: observation and candidate text is written by
// agents, so it is data, never markup.
const OBS_STATUS_LABEL = { open: '열림', parked: '보류', actioned: '완료', declined: '기각', superseded: '대체됨' };

function obsNode(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

// ACTOR_ATTRIBUTION_v1: who did it. Stored as role ids ('claude-code', 'grok', 'chat-agent:agy',
// 'operator'); the persona's name and its word for the user are display only, from the identity
// files (NAME_NEUTRAL_v1).
function actorLabel(who) {
  const id = window.__IDENTITY__ || {};
  const s = String(who || '');
  if (s === 'operator' || /^operator\b/.test(s)) return (id.user_title || '사용자') + s.replace(/^operator/, '').replace(/^ \((\w+)\)/, '($1)');
  const m = s.match(/^chat-agent(?::(.+))?$/);
  if (m) return (id.name || id.persona || id.title || 'agent') + (m[1] ? '·' + m[1] : '');
  return s;
}

function actorBadge(who, prefix) {
  if (!who) return null;
  const b = obsNode('span', 'obs-badge obs-actor', (prefix || '') + actorLabel(who));
  b.title = '처리 주체';
  return b;
}

function obsSet(box, kids) {
  box.textContent = '';
  kids.forEach(k => box.appendChild(k));
}

function obsErrorText(e) {
  try { const j = JSON.parse(e.message); if (j && j.error) return j.error; } catch (_) { /* not JSON */ }
  return String((e && e.message) || e).slice(0, 200);
}

async function loadObservations() {
  if (!statusObsBoxEl) return;
  let res;
  try {
    res = await api('/api/observations');
  } catch (e) {
    obsSet(statusObsBoxEl, [obsNode('div', 'status-hint', '이슈 API 없음 (엔진 리부트 필요): ' + obsErrorText(e))]);
    return;
  }
  renderObservations(res);
}


function evoToggleHead(title, count, opts) {
  // EVOLUTION_UI_v2: one disclosure pattern — click the whole header
  opts = opts || {};
  const head = obsNode('div', 'evo-sec-head evo-sec-toggle');
  head.appendChild(obsNode('span', 'evo-sec-title', title));
  if (count != null && count !== '') head.appendChild(obsNode('span', 'evo-count', String(count)));
  head.appendChild(obsNode('span', 'evo-chev', opts.open ? '▴' : '▾'));
  if (opts.open) head.classList.add('open');
  return head;
}

function evoBindToggle(head, body) {
  body.classList.add('evo-fold');
  if (head.classList.contains('open')) body.classList.add('open');
  head.addEventListener('click', (e) => {
    if (e.target.closest('button, a, input, select, textarea')) return;
    const open = body.classList.toggle('open');
    head.classList.toggle('open', open);
    const chev = head.querySelector('.evo-chev');
    if (chev) chev.textContent = open ? '▴' : '▾';
  });
}


function renderObservations(res) {
  // EVOLUTION_UI_v2: compact cards + unified header toggles
  const items = res.observations || [];
  const active = items.filter(o => o.status === 'open' || o.status === 'parked');
  const kids = [];

  const openSec = obsNode('div', 'evo-sec');
  openSec.appendChild(obsNode('div', 'evo-sec-head', '대기 중' + (active.length ? ' · ' + active.length : '')));
  if (!active.length) {
    openSec.appendChild(obsNode('div', 'evo-empty', '대기 중 이슈 없음'));
  } else {
    active.forEach(o => openSec.appendChild(renderObservationRow(o)));
  }
  kids.push(openSec);

  kids.push(renderObservationHistory());

  kids.push(renderCandidates(res));
  kids.push(renderReviewControls(res));
  obsSet(statusObsBoxEl, kids);
}

// OBS_HISTORY_v1: every resolved observation (in the log or archived) as one paged history, newest first.
// The page stays where the user left it across refreshes of the tab.
let obsHistoryPage = 1;
let obsHistoryOpen = false;
function renderObservationHistory() {
  const sec = obsNode('div', 'evo-sec');
  const head = evoToggleHead('처리 이력', '', { open: obsHistoryOpen });
  const body = obsNode('div', 'evo-fold');
  evoBindToggle(head, body);
  head.addEventListener('click', () => { obsHistoryOpen = head.classList.contains('open'); });
  sec.appendChild(head);
  sec.appendChild(body);
  const load = async (page) => {
    let res;
    try {
      res = await api('/api/observations/history/' + page);
    } catch (e) {
      obsSet(body, [obsNode('div', 'status-hint', '이력을 불러오지 못했어요: ' + obsErrorText(e))]);
      return;
    }
    obsHistoryPage = res.page;
    const count = head.querySelector('.evo-count') || head.insertBefore(obsNode('span', 'evo-count', ''), head.querySelector('.evo-chev'));
    count.textContent = String(res.total);
    const rows = (res.items || []).map(o => {
      const row = renderClosedObservationRow(o);
      const when = o.resolved || o.date;
      if (when) row.querySelector('.obs-head').appendChild(obsNode('span', 'obs-when', when));
      return row;
    });
    if (!rows.length) rows.push(obsNode('div', 'evo-empty', '처리한 이슈 없음'));
    if (res.pages > 1) {
      const pager = obsNode('div', 'evo-pager');
      const prev = obsNode('button', 'art-btn art-btn-xs', '이전');
      const next = obsNode('button', 'art-btn art-btn-xs', '다음');
      prev.type = next.type = 'button';
      prev.disabled = res.page <= 1;
      next.disabled = res.page >= res.pages;
      prev.addEventListener('click', () => load(res.page - 1));
      next.addEventListener('click', () => load(res.page + 1));
      pager.append(prev, obsNode('span', 'evo-page', res.page + ' / ' + res.pages), next);
      rows.push(pager);
    }
    obsSet(body, rows);
  };
  load(obsHistoryPage);
  return sec;
}

function renderClosedObservationRow(o) {
  const row = obsNode('div', 'obs-row obs-row-done obs-row-compact');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + o.id));
  head.appendChild(obsNode('span', 'obs-title', o.title || '(제목 없음)'));
  head.appendChild(obsNode('span', 'obs-badge ' + o.status, OBS_STATUS_LABEL[o.status] || o.status));
  const by = actorBadge(o.resolved_by || o.actor);
  if (by) head.appendChild(by);
  row.appendChild(head);
  return row;
}

function renderObservationRow(o) {
  const row = obsNode('div', 'obs-row obs-row-compact');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + o.id));
  head.appendChild(obsNode('span', 'obs-title', o.title || '(제목 없음)'));
  head.appendChild(obsNode('span', 'obs-badge ' + o.status, OBS_STATUS_LABEL[o.status] || o.status));
  const rec = actorBadge(o.actor, '기록 ');
  if (rec) head.appendChild(rec);
  const actions = obsNode('div', 'obs-actions obs-actions-inline');
  const viewBtn = obsNode('button', 'art-btn art-btn-xs', '보기');
  const doBtn = obsNode('button', 'art-btn art-btn-xs primary', '처리');
  viewBtn.type = 'button';
  doBtn.type = 'button';
  actions.appendChild(viewBtn);
  actions.appendChild(doBtn);
  head.appendChild(actions);
  row.appendChild(head);
  const metaBits = [o.area, o.date, o.status === 'parked' && o.parked_until ? '보류 ~ ' + o.parked_until : ''].filter(Boolean);
  if (metaBits.length) row.appendChild(obsNode('div', 'obs-meta', metaBits.join(' · ')));
  const detail = obsNode('pre', 'obs-body');
  detail.hidden = true;
  row.appendChild(detail);
  const formHost = obsNode('div', 'obs-formhost');
  row.appendChild(formHost);
  viewBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!detail.hidden) { detail.hidden = true; return; }
    if (!detail.textContent) {
      detail.textContent = '불러오는 중…';
      try {
        const d = await api('/api/observations/' + o.id);
        detail.textContent = (d.observation && d.observation.body) || '(본문 없음)';
      } catch (err) {
        detail.textContent = '불러오기 실패: ' + obsErrorText(err);
      }
    }
    detail.hidden = false;
  });
  doBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (formHost.children.length) { formHost.textContent = ''; return; }
    formHost.appendChild(renderResolveForm(o, formHost));
  });
  return row;
}

function renderResolveForm(o, host) {
  const form = obsNode('div', 'obs-form');
  const sel = obsNode('select');
  [['actioned', '완료'], ['declined', '기각'], ['superseded', '대체됨'], ['parked', '보류']].forEach(pair => {
    const op = obsNode('option', null, pair[1]);
    op.value = pair[0];
    sel.appendChild(op);
  });
  const reason = obsNode('input');
  reason.type = 'text';
  reason.placeholder = '사유 (필수)';
  reason.maxLength = 300;
  const until = obsNode('input');
  until.type = 'date';
  until.value = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  until.hidden = true;
  sel.addEventListener('change', () => { until.hidden = sel.value !== 'parked'; });
  const btns = obsNode('div', 'obs-actions');
  const save = obsNode('button', 'art-btn art-btn-xs primary', '저장');
  const cancel = obsNode('button', 'art-btn art-btn-xs', '취소');
  save.type = 'button';
  cancel.type = 'button';
  cancel.addEventListener('click', () => { host.textContent = ''; });
  save.addEventListener('click', async () => {
    const why = reason.value.trim();
    if (!why) { if (reason.focus) reason.focus(); return; }
    save.disabled = true;
    save.textContent = '…';
    try {
      const body = { status: sel.value, resolution: why };
      if (sel.value === 'parked') body.until = until.value;
      await api('/api/observations/' + o.id + '/resolve', { method: 'POST', body: JSON.stringify(body) });
      addActivity('이슈 #' + o.id + ' → ' + (OBS_STATUS_LABEL[sel.value] || sel.value));
      if (typeof fetchEvolution === 'function') fetchEvolution(); else fetchSelfStatus();
    } catch (e) {
      save.disabled = false;
      save.textContent = '저장';
      await alertModal('처리 실패: ' + obsErrorText(e));
    }
  });
  btns.appendChild(save);
  btns.appendChild(cancel);
  [sel, reason, until, btns].forEach(n => form.appendChild(n));
  return form;
}

function renderCandidates(res) {
  const wrap = obsNode('div', 'evo-sec obs-cands');
  const n = res.unreviewed_candidates || 0;
  if (!n) {
    wrap.appendChild(obsNode('div', 'evo-sec-head', '힌트'));
    wrap.appendChild(obsNode('div', 'evo-empty', '새 힌트 없음'));
    return wrap;
  }
  const head = evoToggleHead('힌트', n, { open: false });
  const list = obsNode('div', 'evo-fold');
  (res.candidates || []).forEach(c => {
    const card = obsNode('div', 'obs-cand obs-row-compact');
    const top = obsNode('div', 'obs-cand-top');
    top.appendChild(obsNode('span', 'obs-cand-signal', c.signal || 'signal'));
    if (c.provider) top.appendChild(obsNode('span', 'obs-badge', c.provider));
    card.appendChild(top);
    if (c.user) card.appendChild(obsNode('div', 'obs-cand-user', '“' + c.user + '”'));
    else if (c.summary) card.appendChild(obsNode('div', 'obs-cand-user', c.summary));  // host:<code> (HOST_SIGNALS_v1)
    const foot = [c.ts, c.ref].filter(Boolean).join(' · ');
    if (foot) card.appendChild(obsNode('div', 'obs-meta', foot));
    list.appendChild(card);
  });
  evoBindToggle(head, list);
  wrap.appendChild(head);
  wrap.appendChild(list);
  return wrap;
}

function renderReviewControls(res) {
  const wrap = obsNode('div', 'evo-sec obs-review');
  const head = evoToggleHead('점검', null, { open: false });
  const body = obsNode('div', 'evo-fold');
  body.appendChild(obsNode('div', 'obs-meta', '마지막 점검: ' + (res.last_review || '아직 없음')));
  const form = obsNode('div', 'obs-form');
  const summary = obsNode('input');
  summary.type = 'text';
  summary.placeholder = '점검 한 줄 (필수)';
  summary.maxLength = 300;
  const go = obsNode('button', 'art-btn art-btn-xs primary', '기록');
  go.type = 'button';
  go.addEventListener('click', async () => {
    const text = summary.value.trim();
    if (!text) { if (summary.focus) summary.focus(); return; }
    go.disabled = true;
    try {
      await api('/api/observations/reviewed', { method: 'POST', body: JSON.stringify({ summary: text }) });
      addActivity('점검 기록됨');
      if (typeof fetchEvolution === 'function') fetchEvolution(); else fetchSelfStatus();
    } catch (e) {
      go.disabled = false;
      await alertModal('점검 기록 실패: ' + obsErrorText(e));
    }
  });
  form.appendChild(summary);
  form.appendChild(go);
  body.appendChild(form);
  evoBindToggle(head, body);
  wrap.appendChild(head);
  wrap.appendChild(body);
  return wrap;
}


// Tickets: the buttons only type the operator's command into the chat box (`/ticket approve 3`); pressing Enter
// runs it in the page (see send()) -- it never goes to the agent, and the agent has no way to decide a ticket.
const TICKET_STATUS_LABEL = { proposed: '제안됨', approved: '승인됨', in_progress: '진행 중', awaiting_merge: '병합 대기',
  declined: '폐기됨', wontfix: '보류(사람 필요)', done: '완료' };
// DELEGATION_WIRING_v1: `delegate` hands the ticket to the worktree runner ([맡겨]); an awaiting_merge ticket lands
// or is dropped by the operator ([병합·⚡] / [폐기]). Same rule as above: the button types, Enter decides.
const TICKET_DECISIONS = {
  proposed: [['go', '승인+진행'], ['delegate', '실행'], ['approve', '승인'], ['decline', '폐기']],
  approved: [['go', '진행'], ['delegate', '실행'], ['decline', '폐기']],
  awaiting_merge: [['merge', '승인'], ['rework', '반려'], ['discard', '폐기']],
  wontfix: [['reopen', '재개']],
};
const TICKET_DECISION_WORD = { approve: '승인', decline: '폐기', reopen: '재개', go: '진행', delegate: '실행', merge: '승인(반영 시작)', rework: '반려', discard: '폐기', disown: '담당 해제', unqueue: '대기 취소', allow: '경로 허용', close: '티켓 닫기' };
// Delegation API refusal reasons (English, from the server) -> one short Korean line. [pattern, (match) => line].
const DELEGATION_REFUSAL_KO = [
  [/uncommitted leftover in ([^;]+)/, (m) => '실행 거절: 커밋 안 된 파일이 남아 있어요 (' + m[1].trim() + ')'],
  [/not a plan waiting for \[실행\]/, () => '실행 거절: [실행] 대기 중인 계획이 아니에요'],
  [/lock is held|held by another ticket/, () => '실행 거절: 다른 작업이 같은 파일을 쓰는 중이에요'],
  [/^no such ticket/, () => '작업을 찾을 수 없어요'],
];

function delegationRefusalText(e) {
  let reason = String((e && e.message) || e || '');
  try { const j = JSON.parse(reason); if (j && j.error) reason = String(j.error); } catch (_) { /* raw text */ }
  for (const [re, line] of DELEGATION_REFUSAL_KO) {
    const m = re.exec(reason);
    if (m) return line(m);
  }
  return '실행 거절: ' + (reason.length > 120 ? reason.slice(0, 120) + '…' : reason);
}
// PD_PLAN_v1: the operator's two confirmations on a PD plan -- [실행] (`delegate`) and [승인]/[반려]/[폐기].
const DELEGATION_ACTION = { delegate: 'go', merge: 'merge', rework: 'rework', discard: 'discard', unqueue: 'unqueue', allow: 'allow' };

// LEASE_SCOPE_v1: one author per file. The live leases come with /api/tickets; a ticket another agent opened to do
// itself (`owner`, not the chat's own) is not offered to the chat -- the operator can hand it over ([담당 해제]).
let ticketLeases = [];
function ticketOwnedElsewhere(t) {
  return Boolean(t && t.owner && !String(t.owner).startsWith('chat-agent'));
}
function ticketDecisionsFor(t) {
  const pairs = TICKET_DECISIONS[t.status] || [];
  if (ticketOwnedElsewhere(t) && (t.status === 'approved' || t.status === 'proposed')) return [['disown', '담당 해제'], ['decline', '폐기']];
  return pairs;
}
function leasePathsOverlap(a, b) {
  if (!a.length || !b.length) return true;   // no files = every file
  return a.some(x => b.some(y => {
    const xs = String(x).replace(/\/+$/, ''), ys = String(y).replace(/\/+$/, '');
    return xs === ys || xs.startsWith(ys + '/') || ys.startsWith(xs + '/');
  }));
}
function ticketPaths(t) {
  if (t.paths && t.paths.length) return t.paths;
  const tgt = String(t.target || '').trim();
  return (tgt.includes('/') && !tgt.includes(' ') && !tgt.startsWith('/')) ? [tgt] : [];
}
// The live lease that keeps `t` waiting, or null.
function ticketBlocker(t) {
  const mine = ticketPaths(t);
  return ticketLeases.find(l => l.ticket !== t.id && leasePathsOverlap(mine, l.paths || [])) || null;
}
function leaseWaitText(l) {
  return '잠금 대기 · #' + l.ticket + (l.paths && l.paths.length ? ' ' + l.paths.slice(0, 2).join(', ') : ' (전체)') + ' ~' + String(l.until || '').slice(11, 16);
}

function ticketDecisionText(t, action) {
  return '/ticket ' + action + ' ' + t.id;
}

function parseTicketCommand(text) {
  const t = String(text || '').trim();
  const rw = /^\/ticket\s+rework\s+#?(\d{1,6})\s+([\s\S]+)$/.exec(t);   // [반려]: the comment follows the number
  if (rw) return { action: 'rework', id: Number(rw[1]), comment: rw[2].trim() };
  const m = /^\/ticket\s+(go|approve|decline|reopen|delegate|merge|discard|disown|unqueue|allow)\s+#?(\d{1,6})$/.exec(t);
  return m ? { action: m[1], id: Number(m[2]) } : null;
}

// `/ticket go N`: approve it if it still waits for that (the operator's decision), then hand the agent the obvious
// instruction as an ordinary message -- the sentence nobody wants to type. Returns { message, prompt }.
function ticketGoPrompt(t) {
  return '작업 #' + t.id + ' 진행해줘 (대상: ' + (t.target || '') + '). 맡길 담당자가 있으면 delegate로 계획을 올리고 확인만 해 — 그 계획이 #' + t.id +
    '을(를) 대신한다고 알려줘. 담당자가 없거나 대상이 Tier 3이면 ticket 도구로 claim해서 대상만 직접 고치고, 끝나면 release로 결과(done/gate_failed/failed)를 기록해. 범위 밖은 건드리지 마.';
}

async function goTicket(cmd) {
  const cur = (await api('/api/tickets/' + cmd.id)).ticket || {};
  const refuse = (msg) => { throw new Error(JSON.stringify({ ok: false, error: msg })); };
  if (ticketOwnedElsewhere(cur)) refuse('작업 #' + cmd.id + '은(는) ' + cur.owner + ' 담당이에요. 넘기려면 [담당 해제]');
  try { ticketLeases = (await api('/api/tickets')).leases || []; } catch (_) { /* the claim still checks */ }
  const blocker = ticketBlocker(cur);
  if (blocker) refuse('작업 #' + cmd.id + ' ' + leaseWaitText(blocker) + ' — 끝나면 다시 눌러 주세요');
  let message = '';
  if (cur.status === 'proposed') message = await decideTicket({ action: 'approve', id: cmd.id });
  else if (cur.status !== 'approved') refuse('작업 #' + cmd.id + '은(는) ' + (TICKET_STATUS_LABEL[cur.status] || cur.status) + ' 상태라 진행할 수 없어요');
  return { message, prompt: ticketGoPrompt(cur) };
}

async function decideTicket(cmd) {
  if (DELEGATION_ACTION[cmd.action]) {
    try {
      const r = await api('/api/delegations/' + cmd.id + '/' + DELEGATION_ACTION[cmd.action], { method: 'POST', body: JSON.stringify({ comment: cmd.comment || '' }) });
      loadWork();
      if (r && r.healed) {
        return '작업 #' + cmd.id + '은(는) 이미 ' + (TICKET_STATUS_LABEL[r.status] || r.status) + ' 상태여서 작업 카드를 정리했어요';
      }
      if (r && r.queued) {
        const b = r.blocked_by || {};
        return '작업 #' + cmd.id + ' 실행 대기 — #' + b.ticket + '이(가) ' + (b.paths || []).join(', ') + '를 쓰는 중이라, 끝나면(~' + String(b.until || '').slice(11, 16) + ') 자동으로 시작해요';
      }
      return '작업 #' + cmd.id + ' ' + TICKET_DECISION_WORD[cmd.action] + ' → 작업 카드에서 진행 확인';
    } catch (e) {
      loadWork();
      try {
        const tr = await api('/api/tickets/' + cmd.id);
        const ts = (tr && tr.ticket && tr.ticket.status) || '';
        if (['done', 'declined', 'wontfix'].includes(ts)) {
          await dismissWorkCard({ ticket: cmd.id, phase: 'declined' });
          return '작업 #' + cmd.id + '은(는) 이미 ' + (TICKET_STATUS_LABEL[ts] || ts) + ' 상태여서 카드를 정리했어요';
        }
      } catch (_) {}
      throw new Error(delegationRefusalText(e));
    }
  }
  const res = await api('/api/tickets/' + cmd.id + '/' + cmd.action, { method: 'POST', body: JSON.stringify({}) });
  const t = res.ticket || {};
  return '작업 #' + cmd.id + ' ' + TICKET_DECISION_WORD[cmd.action] + ' 처리했어요 → ' + (TICKET_STATUS_LABEL[t.status] || t.status || '');
}

async function loadTickets() {
  if (!statusTicketBoxEl && !ticketBarEl) return;
  let res;
  try {
    res = await api('/api/tickets');
  } catch (e) {
    if (statusTicketBoxEl) obsSet(statusTicketBoxEl, [obsNode('div', 'status-hint', '작업 API 없음 (엔진 리부트 필요): ' + obsErrorText(e))]);
    if (ticketBarEl) { ticketBarEl.textContent = ''; ticketBarEl.hidden = true; }
    return;
  }
  renderTickets(res);
}

// The same buttons, where the operator already is: a strip above the composer while a ticket waits for a decision.
const TICKET_BAR_MAX = 3;
// TICKET_BUTTONS_v1 (operator, 2026-09-29: send on the press, and no bubble at all): a decision
// button acts at once, like a choice chip -- no text in the box, no bubble, only the notice. [반려] still waits for
// the comment to be typed after it.
// Throwing work away is the one decision a stray tap should not make: it asks first.
const TICKET_ASK_FIRST = ['decline', 'discard'];
async function fillTicketCommand(t, action) {
  switchTab('chat');
  if (action === 'rework') { fillComposer(ticketDecisionText(t, action) + ' '); return; }
  if (TICKET_ASK_FIRST.includes(action) && typeof confirmModal === 'function'
      && !(await confirmModal('작업 #' + t.id + '을(를) ' + TICKET_DECISION_WORD[action] + '할까요?'))) return;   // l10n-ok
  await runTicketDecision({ action, id: t.id }, typeof tapSendOpts === 'function' ? tapSendOpts() : undefined);
}

// The operator's decision on a ticket, made in the page and never sent to the agent -- except [진행], which then
// hands the agent its instruction as an ordinary message. Resolves true when it sent that message.
async function runTicketDecision(cmd, opts) {
  try {
    if (cmd.action === 'go') {
      const go = await goTicket(cmd);
      if (go.message) addNotice('ok', go.message);
      loadTickets();
      inputEl.value = go.prompt;
      await send(opts);
      return true;
    }
    addNotice('ok', await decideTicket(cmd));
  } catch (e) {
    addNotice('error', '작업 결정 실패: ' + obsErrorText(e));   // l10n-ok: moved from app.js send()
  }
  loadTickets();
  return false;
}

// Who owns it (another agent) or what it waits for (a live lease on its files), as a small badge; null for neither.
function ticketStateBadge(t) {
  if (ticketOwnedElsewhere(t)) return obsNode('span', 'obs-badge owner', '담당 ' + t.owner);
  const b = (t.status === 'approved' || t.status === 'proposed') ? ticketBlocker(t) : null;
  return b ? obsNode('span', 'obs-badge queued', leaseWaitText(b)) : null;
}

function renderTicketBar(waiting) {
  if (!ticketBarEl) return;
  waiting = waiting.filter(t => t.status !== 'awaiting_merge' && t.status !== 'wontfix' && !workCardIds.has(t.id));   // a work card carries merge; a parked ticket stays on the improve tab
  ticketBarEl.textContent = '';
  ticketBarEl.hidden = !waiting.length;
  waiting.slice(0, TICKET_BAR_MAX).forEach(t => {
    const chip = obsNode('div', 'ticket-chip');
    chip.appendChild(obsNode('span', 'ticket-chip-title', '#' + t.id + ' ' + (t.title || '')));
    const wait = ticketStateBadge(t);
    if (wait) chip.appendChild(wait);
    ticketDecisionsFor(t).forEach(pair => {
      const btn = obsNode('button', 'art-btn' + (pair[0] === 'go' ? ' primary' : ''), pair[1]);
      btn.type = 'button';
      btn.addEventListener('click', () => fillTicketCommand(t, pair[0]));   // TICKET_BUTTONS_v1: the one path
      chip.appendChild(btn);
    });
    ticketBarEl.appendChild(chip);
  });
  if (waiting.length > TICKET_BAR_MAX) ticketBarEl.appendChild(obsNode('span', 'obs-meta', '+' + (waiting.length - TICKET_BAR_MAX) + '건 더 (개선 탭)'));
}

// DELEGATION_WIRING_v1: work cards -- one per delegated run, above the composer while it runs, waits for the
// operator's merge, or has an ending the operator has not seen. The two characters' exchange is folded: the last
// pair shows, the rest opens on demand. Names on the lines are the run's own (display values from identity).
const WORK_PHASE_LABEL = {
  starting: '시작 중', running: '준비 중', writing: '작업 중', gates: '테스트 중', review: '리뷰 중', merging: '병합 중',
  awaiting_go: '실행 대기', queued: '잠금 대기', paused: '경로 요청', awaiting_merge: '최종 확인 대기', done: '완료', failed: '실패', gate_failed: '탈락',
  declined: '폐기됨', stalled: '멈춤', 'merged-ticket-open': '병합됨(티켓 열림)', base_broken: '기반 고장',
};
const WORK_ENDED = ['done', 'failed', 'gate_failed', 'declined', 'stalled', 'merged-ticket-open', 'base_broken'];
const workBarEl = document.getElementById('workBar');
let workPollTimer = null;
let workCardIds = new Set();   // tickets shown as work cards: the ticket bar leaves them out
let workNames = {};            // role id ('' = the PD) -> display name, from the server's identity files
const workOpen = new Set();
let workLastPhase = null;
let activeWorkRun = null;   // the delegated run working now, or null
const workDismissed = new Set();

async function dismissWorkCard(r) {
  if (!r || !r.ticket) return;
  workDismissed.add(r.ticket);
  try {
    if (WORK_ENDED.includes(r.phase)) {
      await api('/api/delegations/' + r.ticket + '/seen', { method: 'POST', body: JSON.stringify({}) });
    } else if (r.phase === 'awaiting_go' || r.phase === 'paused') {
      await api('/api/delegations/' + r.ticket + '/discard', { method: 'POST', body: JSON.stringify({}) });
    } else if (r.phase === 'queued') {
      try { await api('/api/delegations/' + r.ticket + '/unqueue', { method: 'POST', body: JSON.stringify({}) }); } catch (_) {}
      await api('/api/delegations/' + r.ticket + '/discard', { method: 'POST', body: JSON.stringify({}) });
    } else {
      await api('/api/delegations/' + r.ticket + '/seen', { method: 'POST', body: JSON.stringify({}) });
    }
  } catch (_) {
    try { await api('/api/delegations/' + r.ticket + '/seen', { method: 'POST', body: JSON.stringify({}) }); } catch (_) {}
  }
  loadWork();
}

// The ✕ close button: hide the card locally only, never discard server-side.
// Ended runs are marked seen so they stay hidden after a reload.
function hideWorkCard(r, card) {
  if (!r || !r.ticket) return;
  workDismissed.add(r.ticket);
  if (card && card.remove) card.remove();
  if (WORK_ENDED.includes(r.phase)) {
    api('/api/delegations/' + r.ticket + '/seen', { method: 'POST', body: JSON.stringify({}) }).catch(() => {});
  }
  loadWork();
}

// Who works on a run now: the current task's expert, by display name.
function workRunWho(r) {
  const t = (r.tasks || [])[Math.max(0, (r.task || 1) - 1)] || {};
  return workNames[t.role] || t.role || '작업자';
}   // ticket -> phase seen on the previous poll; null until the first poll

function workElapsed(sec) {
  sec = Math.max(0, Math.floor(sec));
  return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
}

// A run that ends while the page is open says so in the chat, so nobody has to watch the card.
function announceWorkEnding(r) {
  const head = '작업 #' + r.ticket + ' ' + (r.title || '');
  if (r.phase === 'done') addNotice('ok', head + ' — 반영했어요' + (r.tier >= 2 ? ' · ⚡ 엔진 리부트하면 적용돼요' : ''));
  else if (r.phase === 'awaiting_merge') addNotice('ok', head + ' — PD 확인 끝. 카드에서 [승인]하거나 [반려]해 주세요');
  else if (r.phase === 'stalled') addNotice('warn', head + ' — 실행이 멈췄어요 (카드에서 폐기할 수 있어요)');
  else addNotice('warn', head + ' — ' + (WORK_PHASE_LABEL[r.phase] || r.phase) + (r.reason ? ': ' + r.reason : ''));
}

function workLine(ln) {
  const row = obsNode('div', 'work-line' + (ln.role === 'reviewer' ? ' reviewer' : ''));
  const header = obsNode('div', 'work-line-header');
  header.appendChild(obsNode('span', 'work-who', (ln.name || ln.role || '') + (ln.verdict ? ' · ' + ln.verdict : '')));
  if (ln.brain) {
    const brainSpan = obsNode('span', 'work-brain', ln.brain.split('/').pop() + (ln.skipped && ln.skipped.length ? ' ↩' : ''));
    brainSpan.title = ln.brain + (ln.skipped && ln.skipped.length ? ' (대체: ' + ln.skipped.join(' → ') + ' 불가)' : '');
    header.appendChild(brainSpan);
  }
  row.appendChild(header);
  row.appendChild(obsNode('div', 'work-said', ln.text || '…'));
  return row;
}

function renderWorkCard(r) {
  const card = obsNode('div', 'work-card phase-' + r.phase);
  const open = workOpen.has(r.ticket);
  
  // 1. 헤더: #ID + 제목 (길어도 잘 보임) + 상태 배지 + 토글 화살표
  const head = obsNode('div', 'work-head clickable');
  head.title = open ? '클릭하여 상세 접기' : '클릭하여 상세 펼치기';
  head.appendChild(obsNode('span', 'obs-id', '#' + r.ticket));
  head.appendChild(obsNode('span', 'work-title', r.title || ''));

  // 간결한 상태 배지 (한눈에 알아볼 수 있는 핵심 상태만)
  head.appendChild(obsNode('span', 'obs-badge ' + r.phase, WORK_PHASE_LABEL[r.phase] || r.phase));

  // 펼침/접힘 인디케이터
  const toggleIcon = obsNode('span', 'work-toggle-icon', open ? '▲' : '▼');
  head.appendChild(toggleIcon);

  // 고아 카드 및 비활성 카드 UI 닫기 수단
  if (!r.active) {
    const closeBtn = obsNode('button', 'art-btn art-btn-xs', '✕');
    closeBtn.type = 'button';
    closeBtn.title = '카드 닫기';
    closeBtn.style.padding = '0 .3rem';
    closeBtn.style.lineHeight = '1';
    closeBtn.style.marginLeft = 'auto';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      hideWorkCard(r, card);
    });
    head.appendChild(closeBtn);
  }

  head.addEventListener('click', (e) => {
    // 액션 버튼 클릭 시 토글 방지
    if (e.target.closest('button')) return;
    if (open) workOpen.delete(r.ticket);
    else workOpen.add(r.ticket);
    loadWork();
  });
  card.appendChild(head);

  // 2. 상세 영역 (펼쳐졌을 때만 표시)
  if (open) {
    const details = obsNode('div', 'work-details');

    // 상세 메타데이터 줄: 경과/제한시간, 파일 수, 라운드, 작업자(모델), 락 대기 정보
    const metaParts = [];
    if (r.active && r.phase === 'writing' && r.timeout_sec && r.phase_since) {
      metaParts.push('⏱ ' + workElapsed(Date.now() / 1000 - r.phase_since) + ' / ' + workElapsed(r.timeout_sec));
    } else if (r.active && r.started) {
      metaParts.push('⏱ ' + workElapsed(Date.now() / 1000 - r.started));
    }
    if (r.active && typeof r.files_changed === 'number') metaParts.push('📁 파일 ' + r.files_changed + '개');
    if (r.active && r.tasks_total > 1 && r.task) metaParts.push('단계 ' + r.task + '/' + r.tasks_total);
    if (r.active && r.round) metaParts.push(r.round + '라운드');
    if (r.active && r.brain) metaParts.push('🧠 ' + r.brain.split('/').pop());
    if (r.phase === 'queued' && r.blocked_by && r.blocked_by.ticket) {
      const until = String(r.blocked_by.until || '').slice(11, 16);
      metaParts.push('선행 #' + r.blocked_by.ticket + (until ? ' (~' + until + ')' : ''));
    }

    if (metaParts.length) {
      details.appendChild(obsNode('div', 'work-meta-row', metaParts.join(' · ')));
    }

    // 작업 계획 (Tasks / Need paths)
    if (r.tasks && r.tasks.length) {
      const list = obsNode('ol', 'work-plan');
      r.tasks.forEach(t => list.appendChild(obsNode('li', '', (workNames[t.role] || t.role) + ' — ' + t.title + (t.paths && t.paths.length ? ' (' + t.paths.join(', ') + ')' : ''))));
      details.appendChild(list);
    }

    if (r.phase === 'paused' && (r.need_paths || []).length) {
      const list = obsNode('ul', 'work-plan need-paths');
      r.need_paths.forEach(n => list.appendChild(obsNode('li', n.operator_only ? 'operator-only' : '',
        '경로 필요: ' + n.path + (n.operator_only ? ' [운영자만 수정 가능]' : '') + (n.why ? ' — ' + n.why : ''))));
      details.appendChild(list);
    }

    // 대화 내역 전체
    const lines = r.transcript || [];
    if (lines.length) {
      const logBox = obsNode('div', 'work-transcript');
      lines.forEach(ln => logBox.appendChild(workLine(ln)));
      details.appendChild(logBox);
    }

    if (r.reason && WORK_ENDED.includes(r.phase)) details.appendChild(obsNode('div', 'obs-meta', r.reason));
    card.appendChild(details);
  }

  // 3. 액션 버튼 (항상 카드 우측하단에 노출되어 즉시 클릭 가능)
  const actions = obsNode('div', 'work-actions');
  const button = (label, primary, onClick) => {
    const btn = obsNode('button', 'art-btn art-btn-xs' + (primary ? ' primary' : ''), label);
    btn.type = 'button';
    btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
    actions.appendChild(btn);
  };

  if (r.phase === 'awaiting_go') {
    button('실행', true, () => fillTicketCommand({ id: r.ticket }, 'delegate'));
    button('계획 수정', false, () => { switchTab('chat'); fillComposer('#' + r.ticket + ' 계획 수정: '); });
    button('취소', false, async () => {
      await dismissWorkCard(r);
      addNotice('info', '작업 #' + r.ticket + ' 계획을 취소하고 카드를 닫았어요');
    });
  }
  if (r.phase === 'paused' && (r.need_paths || []).length) {
    // #381: a Tier 3 request can never be allowed, so no allow button -- the operator changes that file or discards
    if (!r.need_paths.some(n => n.operator_only)) button('경로 허용', true, () => fillTicketCommand({ id: r.ticket }, 'allow'));
    button('폐기', false, () => fillTicketCommand({ id: r.ticket }, 'discard'));
  }
  // #387: landed, but the ticket stayed open and holds its files: stays on screen until closed (MERGED_CLOSE_v1)
  if (r.phase === 'merged-ticket-open') button(TICKET_DECISION_WORD.close, true, () => fillTicketCommand({ id: r.ticket }, 'merge'));
  // BASE_CHECK_v1: the work is kept; once the base is fixed, the same plan runs on from it
  if (r.phase === 'base_broken') button(TICKET_DECISION_WORD.delegate, true, () => fillTicketCommand({ id: r.ticket }, 'delegate'));
  if (r.phase === 'queued') {
    button('대기 취소', false, () => fillTicketCommand({ id: r.ticket }, 'unqueue'));
  }
  if (r.phase === 'awaiting_merge') {
    TICKET_DECISIONS.awaiting_merge.forEach(pair => button(pair[1], pair[0] === 'merge', () => fillTicketCommand({ id: r.ticket }, pair[0])));
  }
  if (r.phase === 'stalled' && r.stalled_in === 'merging') {
    button('승인 다시', true, () => fillTicketCommand({ id: r.ticket }, 'merge'));
  }
  // ART_MANAGER_v1: a finished job that drew into a character's gallery opens it there (app-art.js)
  const drewFor = typeof artGalleryCharacter === 'function' && !['awaiting_go', 'queued', 'running'].includes(r.phase)
    ? artGalleryCharacter(r.paths) : '';
  if (drewFor) button(typeof ART_TEXT !== 'undefined' ? ART_TEXT.gallery : 'gallery', true, () => openArtManager(drewFor, 'gallery'));
  if (r.phase === 'done' && r.tier >= 2) {
    const zap = obsNode('button', 'art-btn art-btn-xs primary', '⚡ 리부트');
    zap.type = 'button';
    zap.addEventListener('click', (e) => { e.stopPropagation(); switchTab('chat'); inputEl.value = '/defib'; send(tapSendOpts()); });
    actions.appendChild(zap);
  }
  if (WORK_ENDED.includes(r.phase)) {
    const ok = obsNode('button', 'art-btn art-btn-xs', '확인');
    ok.type = 'button';
    ok.addEventListener('click', async (e) => {
      e.stopPropagation();
      try { await api('/api/delegations/' + r.ticket + '/seen', { method: 'POST', body: JSON.stringify({}) }); } catch (e) { /* the card stays */ }
      loadWork();
    });
    actions.appendChild(ok);
  }
  if (actions.childNodes.length) card.appendChild(actions);
  return card;
}

async function loadWork() {
  if (!workBarEl) return;
  let res;
  try {
    res = await api('/api/delegations');
  } catch (e) {
    workBarEl.textContent = '';
    workBarEl.hidden = true;
    return;
  }
  const runs = res.runs || [];
  workNames = res.names || workNames;
  if (workLastPhase) {
    runs.forEach(r => {
      const before = workLastPhase.get(r.ticket);
      if (before !== r.phase && (WORK_ENDED.includes(r.phase) || r.phase === 'awaiting_merge')) announceWorkEnding(r);
    });
  }
  workLastPhase = new Map(runs.map(r => [r.ticket, r.phase]));
  activeWorkRun = runs.find(r => r.active) || null;   // the chat's badge says who is working (DELEGATION_CLARITY_v1)
  if (!isBusy) updateProcBadge('idle');
  const shown = runs.filter(r => !workDismissed.has(r.ticket) && (r.active || r.phase === 'awaiting_go' || r.phase === 'queued' || r.phase === 'paused' || r.phase === 'awaiting_merge' || r.phase === 'merged-ticket-open' || (WORK_ENDED.includes(r.phase) && !r.seen)));
  const ids = new Set(shown.map(r => r.ticket));
  const changed = ids.size !== workCardIds.size || [...ids].some(id => !workCardIds.has(id));
  workCardIds = ids;
  if (changed) loadTickets();
  // The 3s poll rebuilds the cards; keep each transcript's scroll (or its stick-to-bottom) across the rebuild.
  const prevScrolls = new Map();
  workBarEl.querySelectorAll('.work-card').forEach(card => {
    const box = card.querySelector('.work-transcript');
    if (box) prevScrolls.set(card.dataset.ticket, { scrollTop: box.scrollTop, atBottom: box.scrollHeight - box.scrollTop - box.clientHeight < 25 });
  });
  const prevWorkBarScroll = workBarEl.scrollTop;
  workBarEl.textContent = '';
  workBarEl.hidden = !shown.length;
  shown.forEach(r => {
    const card = workBarEl.appendChild(renderWorkCard(r));
    card.dataset.ticket = r.ticket;
    const box = card.querySelector('.work-transcript');
    const saved = box && prevScrolls.get(card.dataset.ticket);
    if (saved) box.scrollTop = saved.atBottom ? box.scrollHeight : saved.scrollTop;
  });
  workBarEl.scrollTop = prevWorkBarScroll;
  const busy = shown.some(r => r.active);
  if (busy && !workPollTimer) workPollTimer = setInterval(loadWork, 3000);
  if (!busy && workPollTimer) { clearInterval(workPollTimer); workPollTimer = null; }
}

// EVO_TAB_HISTORY_v1: finished work, newest first (tickets closed in the last DONE_DAYS days).
const DONE_DAYS = 7;
const DONE_MAX = 30;

function recentDoneTickets(all) {
  const since = Date.now() - DONE_DAYS * 86400000;
  return all
    .filter(t => t.status === 'done' || t.status === 'declined' || t.status === 'wontfix')
    .filter(t => { const d = Date.parse(String(t.updated || '').replace(' ', 'T')); return !isNaN(d) && d >= since; })
    .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')));
}

function renderDoneRow(t) {
  const row = obsNode('div', 'obs-row obs-row-compact');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + t.id));
  head.appendChild(obsNode('span', 'obs-title', t.title || '(제목 없음)'));
  head.appendChild(obsNode('span', 'obs-badge ' + t.status, TICKET_STATUS_LABEL[t.status] || t.status));
  const by = actorBadge(t.closed_by || t.worked_by || t.actor);
  if (by) head.appendChild(by);
  row.appendChild(head);
  const ev = (t.evidence || []).join(', ');
  const appr = t.approved_by ? '승인 ' + actorLabel(t.approved_by) : '';
  const meta = [String(t.updated || '').slice(5, 16), appr, (t.paths || []).slice(0, 4).join(', '), ev ? '근거 ' + ev : ''].filter(Boolean).join(' · ');
  if (meta) row.appendChild(obsNode('div', 'obs-meta', meta));
  return row;
}

// WORK_NOW_v1 (#417): a ticket someone holds -- an agent outside the chat (Claude Code, a CLI) or a delegated run --
// showed nowhere: not a decision, not finished. #416 was invisible, and #387's leftover lease held files with no trace.
const WORK_NOW_TEXT = { head: '진행 중인 작업', lock: '잠금', until: '까지', free: '잠금 없음(만료)' };   // l10n-ok

// The in-progress tickets with who holds them, the files their live lease holds and until when; newest first.
function inProgressRows(all, leases) {
  const byTicket = {};
  (leases || []).forEach(l => { byTicket[l.ticket] = l; });
  return (all || []).filter(t => t.status === 'in_progress').map(t => {
    const l = byTicket[t.id];
    return { id: t.id, title: t.title || '', holder: (l && l.actor) || t.worked_by || t.owner || '',
             paths: l ? (l.paths || []) : [], until: l ? String(l.until || '').slice(11, 16) : '' };
  }).sort((a, b) => b.id - a.id);
}

function renderInProgressRow(w) {
  const row = obsNode('div', 'obs-row obs-row-compact');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + w.id));
  head.appendChild(obsNode('span', 'obs-title', w.title));
  head.appendChild(obsNode('span', 'obs-badge in_progress', TICKET_STATUS_LABEL.in_progress));
  const by = actorBadge(w.holder);
  if (by) head.appendChild(by);
  row.appendChild(head);
  const meta = w.until
    ? WORK_NOW_TEXT.lock + ' ' + (w.paths.length ? w.paths.slice(0, 4).join(', ') : '*') + ' · ' + w.until + ' ' + WORK_NOW_TEXT.until
    : WORK_NOW_TEXT.free;
  row.appendChild(obsNode('div', 'obs-meta', meta));
  return row;
}

function renderTickets(res) {
  const all = res.tickets || [];
  ticketLeases = res.leases || [];
  const rows = all.filter(t => TICKET_DECISIONS[t.status]);
  renderTicketBar(rows);
  if (!statusTicketBoxEl) return;
  const kids = [obsNode('div', 'evo-sec-head', '대기 중 작업')];
  if (!rows.length) kids.push(obsNode('div', 'evo-empty', '지금 결정할 작업이 없어요.'));
  else kids.push(obsNode('div', 'obs-meta', '버튼 → 채팅 명령 · Enter 실행'));
  rows.forEach(t => kids.push(renderTicketRow(t)));
  const now = inProgressRows(all, ticketLeases);
  if (now.length) {
    kids.push(obsNode('div', 'evo-sec-head', WORK_NOW_TEXT.head + ' ' + now.length));
    now.forEach(w => kids.push(renderInProgressRow(w)));
  }
  const done = recentDoneTickets(all);
  if (done.length) {
    const head = evoToggleHead('최근 ' + DONE_DAYS + '일 처리', done.length, { open: false });
    const list = obsNode('div', 'evo-fold');
    done.slice(0, DONE_MAX).forEach(t => list.appendChild(renderDoneRow(t)));
    if (done.length > DONE_MAX) list.appendChild(obsNode('div', 'obs-meta', '+' + (done.length - DONE_MAX) + '건 더'));
    evoBindToggle(head, list);
    kids.push(head, list);
  }
  obsSet(statusTicketBoxEl, kids);
}

function renderTicketRow(t) {
  const row = obsNode('div', 'obs-row obs-row-compact');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + t.id));
  head.appendChild(obsNode('span', 'obs-title', t.title || '(제목 없음)'));
  head.appendChild(obsNode('span', 'obs-badge ' + t.status, TICKET_STATUS_LABEL[t.status] || t.status));
  const prop = actorBadge(t.actor, '제안 ');
  if (prop) head.appendChild(prop);
  const wait = ticketStateBadge(t);
  if (wait) head.appendChild(wait);
  const actions = obsNode('div', 'obs-actions obs-actions-inline');
  ticketDecisionsFor(t).forEach(pair => {
    const btn = obsNode('button', 'art-btn art-btn-xs' + (pair[0] === 'approve' || pair[0] === 'go' ? ' primary' : ''), pair[1]);
    btn.type = 'button';
    btn.addEventListener('click', () => fillTicketCommand(t, pair[0]));
    actions.appendChild(btn);
  });
  head.appendChild(actions);
  row.appendChild(head);
  const meta = [t.target, (t.attempts ? '시도 ' + t.attempts : '')].filter(Boolean).join(' · ');
  if (meta) row.appendChild(obsNode('div', 'obs-meta', meta));
  return row;
}
// ---- end observation manager ----


async function fetchEvolution() {
  // STATUS_EVOLUTION_TAB_v1: RSE pane (observations + tickets)
  try {
    const res = await api('/api/self-status');
    if (statusObserverEl) {
      const o = res.observation || {};
      statusObserverEl.textContent =
        '대기 이슈 ' + (o.open_observations || 0) + '건'
        + ((o.unreviewed_candidates || 0) ? ' · 힌트 ' + o.unreviewed_candidates + '건' : '')
        + (o.last_review_date ? ' · 최근 점검 ' + o.last_review_date : '');
    }
  } catch (e) {
    if (statusObserverEl) statusObserverEl.textContent = '요약 로드 실패: ' + (e.message || e);
  }
  loadObservations();
  loadTickets();
}
