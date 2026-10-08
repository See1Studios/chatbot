// app-evolution.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// ---- observation manager (status tab) ----
// Everything below puts text into nodes with textContent only: observation and candidate text is written by
// agents, so it is data, never markup.
const OBS_STATUS_LABEL = i18nTable('obs.status');   // I18N_v1: names by id, from the catalog

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
  if (s === 'operator' || /^operator\b/.test(s)) return (id.user_title || tr('common.user')) + s.replace(/^operator/, '').replace(/^ \((\w+)\)/, '($1)');
  const m = s.match(/^chat-agent(?::(.+))?$/);
  if (m) return (id.name || id.persona || id.title || 'agent') + (m[1] ? '·' + m[1] : '');
  return s;
}

function actorBadge(who, prefix) {
  if (!who) return null;
  const b = obsNode('span', 'obs-badge obs-actor', (prefix || '') + actorLabel(who));
  b.title = tr('evo.actor_title');
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
    obsSet(statusObsBoxEl, [obsNode('div', 'status-hint', tr('evo.no_issue_api', { error: obsErrorText(e) }))]);
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
  openSec.appendChild(obsNode('div', 'evo-sec-head', tr('evo.waiting') + (active.length ? ' · ' + active.length : '')));
  if (!active.length) {
    openSec.appendChild(obsNode('div', 'evo-empty', tr('evo.no_waiting_issues')));
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
  const head = evoToggleHead(tr('evo.history'), '', { open: obsHistoryOpen });
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
      obsSet(body, [obsNode('div', 'status-hint', tr('evo.history_failed', { error: obsErrorText(e) }))]);
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
    if (!rows.length) rows.push(obsNode('div', 'evo-empty', tr('evo.no_history')));
    if (res.pages > 1) {
      const pager = obsNode('div', 'evo-pager');
      const prev = obsNode('button', 'art-btn art-btn-xs', tr('common.prev'));
      const next = obsNode('button', 'art-btn art-btn-xs', tr('common.next'));
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
  head.appendChild(obsNode('span', 'obs-title', o.title || tr('common.untitled')));
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
  head.appendChild(obsNode('span', 'obs-title', o.title || tr('common.untitled')));
  head.appendChild(obsNode('span', 'obs-badge ' + o.status, OBS_STATUS_LABEL[o.status] || o.status));
  const rec = actorBadge(o.actor, tr('evo.logged_by'));
  if (rec) head.appendChild(rec);
  const actions = obsNode('div', 'obs-actions obs-actions-inline');
  const viewBtn = obsNode('button', 'art-btn art-btn-xs', tr('common.view'));
  const doBtn = obsNode('button', 'art-btn art-btn-xs primary', tr('evo.handle'));
  viewBtn.type = 'button';
  doBtn.type = 'button';
  actions.appendChild(viewBtn);
  actions.appendChild(doBtn);
  head.appendChild(actions);
  row.appendChild(head);
  const metaBits = [o.area, o.date, o.status === 'parked' && o.parked_until ? tr('evo.parked_until', { date: o.parked_until }) : ''].filter(Boolean);
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
      detail.textContent = tr('common.loading');
      try {
        const d = await api('/api/observations/' + o.id);
        detail.textContent = (d.observation && d.observation.body) || tr('evo.no_body');
      } catch (err) {
        detail.textContent = tr('common.load_failed', { error: obsErrorText(err) });
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
  ['actioned', 'declined', 'superseded', 'parked'].map(s => [s, OBS_STATUS_LABEL[s]]).forEach(pair => {
    const op = obsNode('option', null, pair[1]);
    op.value = pair[0];
    sel.appendChild(op);
  });
  const reason = obsNode('input');
  reason.type = 'text';
  reason.placeholder = tr('evo.reason_required');
  reason.maxLength = 300;
  const until = obsNode('input');
  until.type = 'date';
  until.value = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  until.hidden = true;
  sel.addEventListener('change', () => { until.hidden = sel.value !== 'parked'; });
  const btns = obsNode('div', 'obs-actions');
  const save = obsNode('button', 'art-btn art-btn-xs primary', tr('common.save'));
  const cancel = obsNode('button', 'art-btn art-btn-xs', tr('common.cancel'));
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
      addActivity(tr('evo.issue_moved', { id: o.id, status: OBS_STATUS_LABEL[sel.value] || sel.value }));
      if (typeof fetchEvolution === 'function') fetchEvolution(); else fetchSelfStatus();
    } catch (e) {
      save.disabled = false;
      save.textContent = tr('common.save');
      await alertModal(tr('evo.handle_failed', { error: obsErrorText(e) }));
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
    wrap.appendChild(obsNode('div', 'evo-sec-head', tr('evo.hints')));
    wrap.appendChild(obsNode('div', 'evo-empty', tr('evo.no_hints')));
    return wrap;
  }
  const head = evoToggleHead(tr('evo.hints'), n, { open: false });
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
  const head = evoToggleHead(tr('evo.review'), null, { open: false });
  const body = obsNode('div', 'evo-fold');
  body.appendChild(obsNode('div', 'obs-meta', tr('evo.last_review', { date: res.last_review || tr('evo.never') })));
  const form = obsNode('div', 'obs-form');
  const summary = obsNode('input');
  summary.type = 'text';
  summary.placeholder = tr('evo.review_line');
  summary.maxLength = 300;
  const go = obsNode('button', 'art-btn art-btn-xs primary', tr('evo.log_button'));
  go.type = 'button';
  go.addEventListener('click', async () => {
    const text = summary.value.trim();
    if (!text) { if (summary.focus) summary.focus(); return; }
    go.disabled = true;
    try {
      await api('/api/observations/reviewed', { method: 'POST', body: JSON.stringify({ summary: text }) });
      addActivity(tr('evo.review_logged'));
      if (typeof fetchEvolution === 'function') fetchEvolution(); else fetchSelfStatus();
    } catch (e) {
      go.disabled = false;
      await alertModal(tr('evo.review_failed', { error: obsErrorText(e) }));
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
const TICKET_STATUS_LABEL = i18nTable('ticket.status');
// DELEGATION_WIRING_v1: `delegate` hands the ticket to the worktree runner ([Run]); an awaiting_merge ticket lands
// or is dropped by the operator ([Land] / [Discard]). BUTTON_LOGIC_v1: one verb, one meaning; no ticket shows more
// than three. [action, catalog key of its button]; ticketDecisionsFor gives [action, word].
const TICKET_DECISIONS = {
  proposed: [['delegate', 'ticket.button.delegate'], ['decline', 'ticket.button.decline']],
  approved: [['delegate', 'ticket.button.delegate'], ['decline', 'ticket.button.decline']],
  awaiting_merge: [['merge', 'ticket.button.merge'], ['rework', 'ticket.button.rework'], ['discard', 'ticket.button.discard']],
  wontfix: [['reopen', 'ticket.button.reopen']],
};
const TICKET_DECISION_WORD = i18nTable('ticket.word');
// Delegation API refusal reasons (English, from the server) -> one short line in the page's language.
const DELEGATION_REFUSAL = [
  [/uncommitted leftover in ([^;]+)/, (m) => tr('ticket.refused.leftover', { files: m[1].trim() })],
  [/not a plan waiting for \[/, () => tr('ticket.refused.not_waiting')],
  [/lock is held|held by another ticket/, () => tr('ticket.refused.locked')],
  [/^no such ticket/, () => tr('ticket.not_found')],
];

function delegationRefusalText(e) {
  let reason = String((e && e.message) || e || '');
  try { const j = JSON.parse(reason); if (j && j.error) reason = String(j.error); } catch (_) { /* raw text */ }
  for (const [re, line] of DELEGATION_REFUSAL) {
    const m = re.exec(reason);
    if (m) return line(m);
  }
  return tr('ticket.refused.other', { reason: reason.length > 120 ? reason.slice(0, 120) + '…' : reason });
}
// PD_PLAN_v1: the operator's two confirmations on a PD plan -- [Run] (`delegate`) and [Approve]/[Rework]/[Discard].
const DELEGATION_ACTION = { delegate: 'go', merge: 'merge', rework: 'rework', discard: 'discard', unqueue: 'unqueue', allow: 'allow',
  replan: 'replan' };
// BUTTON_LOGIC_v1: a work card's buttons come from the server (`actions`); its ids are the delegation API's, and
// only `go` is named otherwise in the page's command words.
const WORK_ACTION_COMMAND = { go: 'delegate' };
const TICKET_PRIMARY = ['delegate', 'approve', 'merge'];

// LEASE_SCOPE_v1: one author per file. The live leases come with /api/tickets; a ticket another agent opened to do
// itself (`owner`, not the chat's own) is not offered to the chat -- the operator can hand it over ([Unassign]).
let ticketLeases = [];
function ticketOwnedElsewhere(t) {
  return Boolean(t && t.owner && !String(t.owner).startsWith('chat-agent'));
}
function ticketDecisionsFor(t) {
  let pairs = TICKET_DECISIONS[t.status] || [];
  if (ticketOwnedElsewhere(t) && (t.status === 'approved' || t.status === 'proposed')) {
    pairs = [['disown', 'ticket.button.disown'], ['decline', 'ticket.button.decline']];
    if (t.status === 'proposed') pairs.unshift(['approve', 'ticket.button.approve']);   // let that agent do it
  }
  return pairs.map(([action, key]) => [action, tr(key)]);
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
  return tr('ticket.lease_wait', { ticket: l.ticket, paths: l.paths && l.paths.length ? l.paths.slice(0, 2).join(', ') : tr('ticket.lease_all'),
    until: String(l.until || '').slice(11, 16) });
}
function leaseWaitBadgeText(l) {
  return tr('ticket.lease_wait', { ticket: l.ticket, paths: '', until: String(l.until || '').slice(11, 16) }).replace(/\s{2,}/g, ' ').replace(/\s+~$/, '').trim();
}

function ticketDecisionText(t, action) {
  return '/ticket ' + action + ' ' + t.id;
}

function parseTicketCommand(text) {
  const t = String(text || '').trim();
  // [Rework] / [Edit plan]: the comment follows the number; with none yet it stays in the page, never reaching the
  // agent (#715). /ticket replan is page-only too: a structured request to the PD (BUTTON_LOGIC_v1).
  const rw = /^\/ticket\s+(rework|replan)\s+#?(\d{1,6})(?:\s+([\s\S]+))?$/.exec(t);
  if (rw) return { action: rw[1], id: Number(rw[2]), comment: (rw[3] || '').trim() };
  const m = /^\/ticket\s+(go|approve|decline|reopen|delegate|merge|discard|disown|unqueue|allow)\s+#?(\d{1,6})$/.exec(t);
  if (!m) return null;
  // BUTTON_LOGIC_v1: a typed `/ticket go N` is [Run] -- the engine runs it; no message asks the model to decide
  return { action: m[1] === 'go' ? 'delegate' : m[1], id: Number(m[2]) };
}

async function decideTicket(cmd) {
  if (DELEGATION_ACTION[cmd.action]) {
    try {
      const r = await api('/api/delegations/' + cmd.id + '/' + DELEGATION_ACTION[cmd.action], { method: 'POST', body: JSON.stringify({ comment: cmd.comment || '' }) });
      loadWork();
      if (r && r.healed) {
        return tr('ticket.healed', { id: cmd.id, status: TICKET_STATUS_LABEL[r.status] || r.status });
      }
      if (r && r.requested) return tr('work.replan_sent', { id: cmd.id });   // BUTTON_LOGIC_v1: the PD re-plans
      if (r && r.queued) {
        const b = r.blocked_by || {};
        return tr('ticket.queued', { id: cmd.id, ticket: b.ticket, paths: (b.paths || []).join(', '), until: String(b.until || '').slice(11, 16) });
      }
      return tr('ticket.decided_work', { id: cmd.id, word: TICKET_DECISION_WORD[cmd.action] || cmd.action });
    } catch (e) {
      loadWork();
      try {
        const got = await api('/api/tickets/' + cmd.id);
        const ts = (got && got.ticket && got.ticket.status) || '';
        if (['done', 'declined', 'wontfix'].includes(ts)) {
          await dismissWorkCard({ ticket: cmd.id, phase: 'declined' });
          return tr('ticket.healed_card', { id: cmd.id, status: TICKET_STATUS_LABEL[ts] || ts });
        }
      } catch (_) {}
      throw new Error(delegationRefusalText(e));
    }
  }
  const res = await api('/api/tickets/' + cmd.id + '/' + cmd.action, { method: 'POST', body: JSON.stringify({}) });
  const tk = res.ticket || {};
  return tr('ticket.decided', { id: cmd.id, word: TICKET_DECISION_WORD[cmd.action] || cmd.action, status: TICKET_STATUS_LABEL[tk.status] || tk.status || '' });
}

async function loadTickets() {
  if (!statusTicketBoxEl && !ticketBarEl) return;
  let res;
  try {
    res = await api('/api/tickets');
  } catch (e) {
    if (statusTicketBoxEl) obsSet(statusTicketBoxEl, [obsNode('div', 'status-hint', tr('ticket.no_api', { error: obsErrorText(e) }))]);
    if (ticketBarEl) { ticketBarEl.textContent = ''; ticketBarEl.hidden = true; }
    return;
  }
  renderTickets(res);
}

// The same buttons, where the operator already is: a strip above the composer while a ticket waits for a decision.
const TICKET_BAR_MAX = 3;
// TICKET_BUTTONS_v1 (operator, 2026-09-29: send on the press, and no bubble at all): a decision
// button acts at once, like a choice chip -- no text in the box, no bubble, only the notice. [Rework] still waits for
// the comment to be typed after it.
// Throwing work away is the one decision a stray tap should not make: it asks first.
const TICKET_ASK_FIRST = ['decline', 'discard'];
// The decisions that carry the operator's words: the button writes the command, the reason follows it.
const TICKET_NEEDS_REASON = ['rework', 'replan'];
// `ask` is the server's word for a work card's button (BUTTON_LOGIC_v1); a ticket row asks by TICKET_ASK_FIRST.
async function fillTicketCommand(tk, action, ask) {
  switchTab('chat');
  if (TICKET_NEEDS_REASON.includes(action)) { fillComposer(ticketDecisionText(tk, action) + ' '); return; }
  if ((ask == null ? TICKET_ASK_FIRST.includes(action) : ask) && typeof confirmModal === 'function'
      && !(await confirmModal(tr('ticket.confirm.' + action, { id: tk.id })))) return;
  await runTicketDecision({ action, id: tk.id }, typeof tapSendOpts === 'function' ? tapSendOpts() : undefined);
}

// The operator's decision on a ticket, made in the page and never sent to the agent (BUTTON_LOGIC_v1: not even [Run]).
async function runTicketDecision(cmd, opts) {
  if (TICKET_NEEDS_REASON.includes(cmd.action) && !cmd.comment) {   // the reason is what the worker or PD gets: ask
    addNotice('warn', tr(cmd.action === 'rework' ? 'ticket.rework_needs_reason' : 'work.replan_needs_reason', { id: cmd.id }));
    inputEl.value = '/ticket ' + cmd.action + ' ' + cmd.id + ' ';
    if (typeof updateSendButton === 'function') updateSendButton();
    inputEl.focus();
    return false;
  }
  try {
    addNotice('ok', await decideTicket(cmd));
  } catch (e) {
    addNotice('error', tr('ticket.decision_failed', { error: obsErrorText(e) }));
  }
  loadTickets();
  return false;
}

// Who owns it (another agent) or what it waits for (a live lease on its files), as a small badge; null for neither.
function ticketStateBadge(t) {
  if (ticketOwnedElsewhere(t)) return obsNode('span', 'obs-badge owner', tr('ticket.owner', { owner: t.owner }));
  const b = (t.status === 'approved' || t.status === 'proposed') ? ticketBlocker(t) : null;
  if (!b) return null;
  const badge = obsNode('span', 'obs-badge queued', leaseWaitBadgeText(b));
  badge.title = leaseWaitText(b);
  return badge;
}

function renderTicketBar(waiting) {
  if (!ticketBarEl) return;
  waiting = waiting.filter(t => !['awaiting_merge','wontfix'].includes(t.status) && !workCardIds.has(t.id));   // shown apart
  ticketBarEl.textContent = '';
  ticketBarEl.hidden = !waiting.length;
  waiting.slice(0, TICKET_BAR_MAX).forEach(t => {
    const chip = obsNode('div', 'ticket-chip');
    chip.appendChild(obsNode('span', 'ticket-chip-title', '#' + t.id + ' ' + (t.title || '')));
    const wait = ticketStateBadge(t);
    if (wait) chip.appendChild(wait);
    ticketDecisionsFor(t).forEach(pair => {
      const btn = obsNode('button', 'art-btn' + (TICKET_PRIMARY.includes(pair[0]) ? ' primary' : ''), pair[1]);
      btn.type = 'button';
      btn.addEventListener('click', () => fillTicketCommand(t, pair[0]));   // TICKET_BUTTONS_v1: the one path
      chip.appendChild(btn);
    });
    ticketBarEl.appendChild(chip);
  });
  if (waiting.length > TICKET_BAR_MAX) ticketBarEl.appendChild(obsNode('span', 'obs-meta', tr('ticket.more_in_tab', { n: waiting.length - TICKET_BAR_MAX })));
}

// DELEGATION_WIRING_v1: work cards -- one per delegated run, above the composer while it runs, waits for the
// operator's merge, or has an ending the operator has not seen. The two characters' exchange is folded: the last
// pair shows, the rest opens on demand. Names on the lines are the run's own (display values from identity).
const WORK_PHASE_LABEL = i18nTable('work.phase');
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
  return workNames[t.role] || t.role || tr('work.worker');
}   // ticket -> phase seen on the previous poll; null until the first poll

function workElapsed(sec) {
  sec = Math.max(0, Math.floor(sec));
  return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
}

// A run that ends while the page is open says so in the chat, so nobody has to watch the card.
function announceWorkEnding(r) {
  const head = tr('work.head', { id: r.ticket, title: r.title || '' });
  if (r.phase === 'done') addNotice('ok', tr('work.ended.done', { head }) + (r.tier >= 2 ? tr('work.ended.restart_hint') : ''));
  else if (r.phase === 'awaiting_merge') addNotice('ok', tr('work.ended.awaiting_merge', { head }));
  else if (r.phase === 'stalled') addNotice('warn', tr('work.ended.stalled', { head }));
  else addNotice('warn', head + ' — ' + (WORK_PHASE_LABEL[r.phase] || r.phase) + (r.reason ? ': ' + r.reason : ''));
}

function renderWorkCard(r) {
  const card = obsNode('div', 'work-card phase-' + r.phase);
  const open = workOpen.has(r.ticket);
  const head = obsNode('div', 'work-head clickable');
  head.title = open ? tr('work.collapse') : tr('work.expand');
  head.appendChild(obsNode('span', 'obs-id', '#' + r.ticket));
  head.appendChild(obsNode('span', 'work-title', r.title || ''));
  head.appendChild(obsNode('span', 'obs-badge ' + r.phase, WORK_PHASE_LABEL[r.phase] || r.phase));
  head.appendChild(obsNode('span', 'work-toggle-icon', open ? '▲' : '▼'));
  if (!r.active) {
    const closeBtn = obsNode('button', 'art-btn art-btn-xs', '✕');
    closeBtn.type = 'button';
    closeBtn.title = tr('work.close_card');
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
    if (e.target.closest('button')) return;
    if (open) workOpen.delete(r.ticket);
    else workOpen.add(r.ticket);
    loadWork();
  });
  card.appendChild(head);

  // 2. details (only when open)
  if (open) {
    const details = obsNode('div', 'work-details');
    const metaParts = [];
    if (r.active && r.phase === 'writing' && r.timeout_sec && r.phase_since) {
      metaParts.push('⏱ ' + workElapsed(Date.now() / 1000 - r.phase_since) + ' / ' + workElapsed(r.timeout_sec));
    } else if (r.active && r.started) {
      metaParts.push('⏱ ' + workElapsed(Date.now() / 1000 - r.started));
    }
    if (r.active && typeof r.files_changed === 'number') metaParts.push(tr('work.files', { n: r.files_changed }));
    if (r.active && r.tasks_total > 1 && r.task) metaParts.push(tr('work.step', { n: r.task, total: r.tasks_total }));
    if (r.active && r.round) metaParts.push(tr('work.round', { n: r.round }));
    if (r.active && r.brain) metaParts.push('🧠 ' + r.brain.split('/').pop());
    if (r.phase === 'queued' && r.blocked_by && r.blocked_by.ticket) {
      const until = String(r.blocked_by.until || '').slice(11, 16);
      metaParts.push(tr('work.after', { ticket: r.blocked_by.ticket }) + (until ? ' (~' + until + ')' : ''));
    }

    if (metaParts.length) {
      details.appendChild(obsNode('div', 'work-meta-row', metaParts.join(' · ')));
    }

    // the plan (tasks, paths it needs)
    if (r.tasks && r.tasks.length) {
      const list = obsNode('ol', 'work-plan');
      r.tasks.forEach(t => list.appendChild(obsNode('li', '', (workNames[t.role] || t.role) + ' — ' + t.title + (t.paths && t.paths.length ? ' (' + t.paths.join(', ') + ')' : ''))));
      details.appendChild(list);
    }

    if (r.phase === 'paused' && (r.need_paths || []).length) {
      const list = obsNode('ul', 'work-plan need-paths');
      r.need_paths.forEach(n => list.appendChild(obsNode('li', n.operator_only ? 'operator-only' : '',
        tr('work.need_path', { path: n.path }) + (n.operator_only ? tr('work.operator_only') : '') + (n.why ? ' — ' + n.why : ''))));
      details.appendChild(list);
    }

    // WORK_TALK_v1: the talk is in the two characters' dm; the card keeps the PD's verdict
    const rv = r.review || {};
    if (rv.verdict) details.appendChild(obsNode('div', 'work-verdict' + (rv.verdict === 'PASS' ? ' pass' : ''),
      tr('work.verdict', { verdict: rv.verdict }) + (rv.advisory ? tr('work.advisory') : '') + (rv.fix && rv.verdict !== 'PASS' ? ' — ' + rv.fix : '')));

    if (r.reason && WORK_ENDED.includes(r.phase)) details.appendChild(obsNode('div', 'obs-meta', r.reason));
    card.appendChild(details);
  }

  // 3. action buttons (always shown, bottom right)
  const actions = obsNode('div', 'work-actions');
  const button = (label, primary, onClick) => {
    const btn = obsNode('button', 'art-btn art-btn-xs' + (primary ? ' primary' : ''), label);
    btn.type = 'button';
    btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
    actions.appendChild(btn);
  };

  // BUTTON_LOGIC_v1: which buttons, in which order, is the server's (delegation.WORK_ACTIONS): the page only draws
  // them -- a Tier 3 path request has no [Allow] (#381), a landed-but-open ticket has [Close] (MERGED_CLOSE_v1)
  (r.actions || []).forEach(a => {
    const cmd = WORK_ACTION_COMMAND[a.id] || a.id;
    button(tr(a.label), Boolean(a.primary), () => fillTicketCommand({ id: r.ticket }, cmd, Boolean(a.confirm)));
  });
  // ART_MANAGER_v1: a finished job that drew into a character's gallery opens it there (app-art.js)
  const drewFor = typeof artGalleryCharacter === 'function' && !['awaiting_go', 'queued', 'running'].includes(r.phase)
    ? artGalleryCharacter(r.paths) : '';
  if (drewFor) button(typeof ART_TEXT !== 'undefined' ? ART_TEXT.gallery : 'gallery', true, () => openArtManager(drewFor, 'gallery'));
  if (r.phase === 'done' && r.tier >= 2) {
    const zap = obsNode('button', 'art-btn art-btn-xs primary', tr('work.restart'));
    zap.type = 'button';
    zap.addEventListener('click', (e) => { e.stopPropagation(); switchTab('chat'); inputEl.value = '/defib'; send(tapSendOpts()); });
    actions.appendChild(zap);
  }
  if (WORK_ENDED.includes(r.phase)) {
    const ok = obsNode('button', 'art-btn art-btn-xs', tr('common.ok'));
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
  if (typeof loadHandoffs === 'function') loadHandoffs();   // HANDOFF_BOARD_v1: refreshed with the work cards
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
  const prevWorkBarScroll = workBarEl.scrollTop;
  workBarEl.textContent = '';
  workBarEl.hidden = !shown.length;
  shown.forEach(r => {
    const card = workBarEl.appendChild(renderWorkCard(r));
    card.dataset.ticket = r.ticket;
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
  head.appendChild(obsNode('span', 'obs-title', t.title || tr('common.untitled')));
  head.appendChild(obsNode('span', 'obs-badge ' + t.status, TICKET_STATUS_LABEL[t.status] || t.status));
  const by = actorBadge(t.closed_by || t.worked_by || t.actor);
  if (by) head.appendChild(by);
  row.appendChild(head);
  const ev = (t.evidence || []).join(', ');
  const appr = t.approved_by ? tr('ticket.approved_by', { who: actorLabel(t.approved_by) }) : '';
  const meta = [String(t.updated || '').slice(5, 16), appr, (t.paths || []).slice(0, 4).join(', '), ev ? tr('ticket.evidence', { ev }) : ''].filter(Boolean).join(' · ');
  if (meta) row.appendChild(obsNode('div', 'obs-meta', meta));
  return row;
}

// WORK_NOW_v1 (#417): a ticket someone holds -- an agent outside the chat (Claude Code, a CLI) or a delegated run --
// showed nowhere: not a decision, not finished. #416 was invisible, and #387's leftover lease held files with no trace.
const WORK_NOW_TEXT = i18nTable('work.now');

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
  const kids = [obsNode('div', 'evo-sec-head', tr('ticket.waiting_head'))];
  if (!rows.length) kids.push(obsNode('div', 'evo-empty', tr('ticket.none_to_decide')));
  else kids.push(obsNode('div', 'obs-meta', tr('ticket.buttons_hint')));
  rows.forEach(t => kids.push(renderTicketRow(t)));
  const now = inProgressRows(all, ticketLeases);
  if (now.length) {
    kids.push(obsNode('div', 'evo-sec-head', WORK_NOW_TEXT.head + ' ' + now.length));
    now.forEach(w => kids.push(renderInProgressRow(w)));
  }
  const done = recentDoneTickets(all);
  if (done.length) {
    const head = evoToggleHead(tr('ticket.recent_done', { days: DONE_DAYS }), done.length, { open: false });
    const list = obsNode('div', 'evo-fold');
    done.slice(0, DONE_MAX).forEach(t => list.appendChild(renderDoneRow(t)));
    if (done.length > DONE_MAX) list.appendChild(obsNode('div', 'obs-meta', tr('common.more', { n: done.length - DONE_MAX })));
    evoBindToggle(head, list);
    kids.push(head, list);
  }
  obsSet(statusTicketBoxEl, kids);
}

function renderTicketRow(t) {
  const row = obsNode('div', 'obs-row obs-row-compact');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + t.id));
  head.appendChild(obsNode('span', 'obs-title', t.title || tr('common.untitled')));
  head.appendChild(obsNode('span', 'obs-badge ' + t.status, TICKET_STATUS_LABEL[t.status] || t.status));
  const prop = actorBadge(t.actor, tr('ticket.proposed_by'));
  if (prop) head.appendChild(prop);
  const wait = ticketStateBadge(t);
  if (wait) head.appendChild(wait);
  const actions = obsNode('div', 'obs-actions obs-actions-inline');
  ticketDecisionsFor(t).forEach(pair => {
    const btn = obsNode('button', 'art-btn art-btn-xs' + (TICKET_PRIMARY.includes(pair[0]) ? ' primary' : ''), pair[1]);
    btn.type = 'button';
    btn.addEventListener('click', () => fillTicketCommand(t, pair[0]));
    actions.appendChild(btn);
  });
  head.appendChild(actions);
  row.appendChild(head);
  const meta = [t.target, (t.attempts ? tr('ticket.attempts', { n: t.attempts }) : '')].filter(Boolean).join(' · ');
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
        tr('evo.summary.issues', { n: o.open_observations || 0 })
        + ((o.unreviewed_candidates || 0) ? tr('evo.summary.hints', { n: o.unreviewed_candidates }) : '')
        + (o.last_review_date ? tr('evo.summary.review', { date: o.last_review_date }) : '');
    }
  } catch (e) {
    if (statusObserverEl) statusObserverEl.textContent = tr('evo.summary_failed', { error: e.message || e });
  }
  loadObservations();
  loadTickets();
}
