// app-retry.js -- RETRY_LAST_v1: a message whose turn failed waits in the composer placeholder; pressing send (or
// Enter) on an empty box sends it again, typing anything else drops it (operator, 2026-09-28). Declarations and
// document-level listeners only: it loads before app.js, so it never names app.js bindings at load time.
//
// Failures that offer a retry: the POST /message itself failed (app-api.js raises 'api-failed'), or the turn came
// back with an error and no answer (app-sse.js calls offerRetry). An answer settles the message (retryAnswered).
// The offer belongs to one session and ends when the session changes.

const RETRY_MAX = 40;
let retryLast = null;    // { text, sid } -- the last message this window sent, until it is answered
let retryOffer = null;   // { text, sid } -- shown in the placeholder, sent by an empty send

// Only what reads as a message is worth sending again; commands like /new or /clear are not.
function retryWorthy(text) {
  const t = String(text || '').trim();
  if (!t) return false;
  return !t.startsWith('/') || /^\/(?:act|action|me)\s/.test(t);
}

function retryShort(text, max) {
  const first = String(text || '').trim().split('\n')[0];
  const n = max || RETRY_MAX;
  return first.length > n ? first.slice(0, n - 1) + '…' : first;
}

function retryCurrentSid() {
  return typeof sessionId === 'string' ? sessionId : '';
}

// The text waiting to be sent again in this session, or ''.
function retryHint() {
  if (!retryOffer || retryOffer.sid !== retryCurrentSid()) return '';
  return retryOffer.text;
}

function retryRefresh() {
  if (typeof refreshComposerPlaceholder === 'function') refreshComposerPlaceholder();
  if (typeof updateSendButton === 'function') updateSendButton();
}

// Called when a turn fails: the last sent message becomes the offer (text given explicitly wins).
function offerRetry(text) {
  const t = text != null ? String(text).trim() : (retryLast && retryLast.sid === retryCurrentSid() ? retryLast.text : '');
  if (!retryWorthy(t)) return;
  retryOffer = { text: t, sid: retryCurrentSid() };
  retryRefresh();
}

function clearRetry() {
  if (!retryOffer) return;
  retryOffer = null;
  retryRefresh();
}

function retryAnswered() {
  retryLast = null;
}

// A send is starting: an empty box takes the offer; whatever goes out becomes the message a failure would offer.
function retryOnSend(inputEl) {
  if (!inputEl) return;
  if (!inputEl.value.trim() && retryHint() && !(typeof isBusy !== 'undefined' && isBusy)) inputEl.value = retryOffer.text;
  const t = inputEl.value.trim();
  if (!t) return;
  retryOffer = null;
  retryLast = retryWorthy(t) ? { text: t, sid: retryCurrentSid() } : retryLast;
}

// Capture phase, so the offer is in the box before app.js's own send handlers read it.
document.addEventListener('click', (e) => {
  const btn = e.target && e.target.closest ? e.target.closest('#send') : null;
  if (btn && !btn.disabled) retryOnSend(document.getElementById('input'));
}, true);
document.addEventListener('keydown', (e) => {
  if (!e.target || e.target.id !== 'input' || e.isComposing || e.keyCode === 229) return;
  if (e.key === 'Enter' && !e.shiftKey) retryOnSend(e.target);
  else if (e.key === 'Escape' && !e.target.value.trim()) clearRetry();
}, true);
document.addEventListener('input', (e) => {
  if (e.target && e.target.id === 'input' && e.target.value.trim()) clearRetry();
});
document.addEventListener('api-failed', (e) => {
  const d = e.detail || {};
  if (/\/message$/.test(d.path || '') && String(d.method || '').toUpperCase() === 'POST') offerRetry();
});

// qfr/C (QUOTA_STATE_v1): a send held because this brain is out of quota comes back as a notice with other brains of
// the provider the engine found usable. Each button switches to that model and sends the held message again: the
// offer above already holds it, and an empty send takes the offer.
function quotaSwitchButtons(node, models) {
  (models || []).slice(0, 2).forEach((m) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ghost notice-action';
    b.textContent = tr('quota.switch_to', { model: m });
    b.addEventListener('click', () => {
      if (typeof pickModel === 'function') pickModel(m);
      node.querySelectorAll('button').forEach((x) => { x.disabled = true; });
      const input = document.getElementById('input'), send = document.getElementById('send');
      if (input && !input.value.trim() && retryHint() && send) setTimeout(() => send.click(), 0);   // after the switch persisted
    });
    node.appendChild(b);
  });
}

// NOTICE_ACTIONS_v1: a failure notice says one plain line; the engine's raw error goes under 'details' and one or two
// buttons offer the way on. Which ones is decided by the notice's key -- the engine's fact, never its wording.
const NOTICE_BRAIN_KEYS = ['srv.quota_exhausted', 'srv.quota_or_provider', 'srv.quota_or_provider_closed', 'srv.claude_limit',
  'srv.api_failed'];

function noticeButton(node, label, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'ghost notice-action';
  b.textContent = label;
  b.addEventListener('click', () => { node.querySelectorAll('button').forEach((x) => { x.disabled = true; }); onClick(); });
  node.appendChild(b);
}

function noticeResend() {
  const input = document.getElementById('input'), send = document.getElementById('send');
  if (input && !input.value.trim() && retryHint() && send) send.click();   // an empty send takes the offer
}

function noticeActions(node, data) {
  const raw = String(data.error || (data.vars && data.vars.error) || '').trim();
  if (raw && typeof noticeDetail === 'function') noticeDetail(node, raw);
  if (data.suggest && data.suggest.length) { quotaSwitchButtons(node, data.suggest); return; }   // qfr/C: they resend too
  if (NOTICE_BRAIN_KEYS.includes(data.key) && typeof shellProfileOpen === 'function') {
    noticeButton(node, tr('notice.pick_brain'), () => shellProfileOpen());
  }
  if (retryHint()) noticeButton(node, tr('notice.resend'), noticeResend);
}

// The stream gave up after its retries: a notice in the talk with the one way back, not a line in the progress bar.
function connLost() {
  if (typeof addActivity === 'function') addActivity(tr('chat.conn_failed'), 'warn');
  const node = typeof addNotice === 'function' ? addNotice('error', tr('chat.conn_lost')) : null;
  if (node) noticeButton(node, tr('notice.reload'), () => location.reload());
}
