// app-choices.js -- quick-reply chips, parsing, state tracking and action bar.
// Extracted from markdown.js to isolate widget concerns and respect bundle budgets.

var CHOICES_TAIL = /\s*<!--\s*choices\s*:((?:(?!<!--)[\s\S])*?)-->\s*$/;
var CHOICES_OPEN = /\s*<!--\s*choices(?:(?!-->)[\s\S])*$/;
var CHOICES_MAX = 4;
var CHOICE_LABEL_MAX = 28;

function stripOuterParens(s) {
  // Balanced outer (...) only — do not eat trailing ) of an inner "(act)" in "line" (act).
  let out = String(s || '').trim();
  while (out.length >= 2 && out[0] === '(' && out[out.length - 1] === ')') {
    let depth = 0, balanced = true;
    for (let i = 0; i < out.length; i++) {
      const ch = out[i];
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0 && i !== out.length - 1) { balanced = false; break; }
        if (depth < 0) { balanced = false; break; }
      }
    }
    if (!balanced || depth !== 0) break;
    out = out.slice(1, -1).trim();
  }
  return out;
}

function truncateChoiceLabel(s, max = CHOICE_LABEL_MAX) {
  const cap = typeof max === 'number' ? max : 28;
  const str = String(s || '').trim();
  return str.length <= cap ? str : str.slice(0, cap - 1) + '…';
}

function classifyChoicePayload(rawPayload) {
  // Normalize quotes and parens; all choice clicks are actions (#246).
  let s = String(rawPayload || '').trim();
  if (!s) return { kind: 'say', payload: '', isAction: false };
  s = s
    .replace(/[\u201C\u201D\u201E\u201F\u2033\u2036]/g, '"')
    .replace(/[\u2018\u2019\u201A\u201B\u2032\u2035]/g, "'")
    .replace(/\uFF08/g, '(').replace(/\uFF09/g, ')');
  // Combined: "user line" (action) — still action; flavor baked in
  const combo = /^"([^"]*)"\s*\(([\s\S]+)\)\s*$/.exec(s);
  if (combo) {
    const line = combo[1].trim();
    const act = stripOuterParens(combo[2].trim());
    if (!line) return { kind: 'action', payload: act, action: act, isAction: true };
    const payload = '"' + line + '" (' + act + ')';
    return { kind: 'action', payload, action: payload, isAction: true };
  }
  // Action-only: (action) — silent /act. Also accept * (action) * italics wrappers.
  const actOnly = /^\*?\s*\(([\s\S]+)\)\s*\*?\s*$/.exec(s);
  if (actOnly) {
    const inner = actOnly[1].trim();
    const nestedCombo = /^"([^"]*)"\s*\(([\s\S]+)\)\s*$/.exec(inner);
    if (nestedCombo) {
      const line = nestedCombo[1].trim();
      const act = stripOuterParens(nestedCombo[2].trim());
      if (!line) return { kind: 'action', payload: act, action: act, isAction: true };
      const payload = '"' + line + '" (' + act + ')';
      return { kind: 'action', payload, action: payload, isAction: true };
    }
    const nestedSay = /^"([^"]*)"\s*$/.exec(inner);
    if (nestedSay) {
      const payload = '"' + nestedSay[1].trim() + '"';
      return { kind: 'action', payload, action: payload, isAction: true };
    }
    const act = stripOuterParens(inner);
    return { kind: 'action', payload: act, action: act, isAction: true };
  }
  // Dialogue-flavor: "user line" — still action (flavor), not composer say
  const sayOnly = /^"([^"]*)"\s*$/.exec(s);
  if (sayOnly) {
    const payload = '"' + sayOnly[1].trim() + '"';
    return { kind: 'action', payload, action: payload, isAction: true };
  }
  // Legacy mismatched quotes
  if (/^["'].*["']$/.test(s)) {
    const payload = '"' + s.slice(1, -1).trim() + '"';
    return { kind: 'action', payload, action: payload, isAction: true };
  }
  const bare = stripOuterParens(s);
  return { kind: 'action', payload: bare, action: bare, isAction: true };
}

function parseChoiceItem(item) {
  const maxLabel = typeof CHOICE_LABEL_MAX !== 'undefined' ? CHOICE_LABEL_MAX : 28;
  const truncate = (s) => truncateChoiceLabel(s, maxLabel);
  const unwrapParens = stripOuterParens;

  if (item && typeof item === 'object') {
    const rawLabel = String(item.label || '').trim();
    const label = truncate(rawLabel);
    let kind = String(item.kind || (item.isAction ? 'action' : 'say')).trim();
    let payload = item.payload !== undefined ? String(item.payload).trim() : String(item.action || rawLabel || '').trim();
    // Re-classify string payloads that still carry private-mode forms
    if (kind !== 'command' && /^(?:"[\s\S]*"|[\s\S]*\([\s\S]*\))/.test(payload)) {
      const c = classifyChoicePayload(payload);
      kind = c.kind;
      payload = c.payload;
      return { label, kind, payload, action: payload, isAction: kind === 'action' };
    }
    return { label, kind, payload, action: payload, isAction: kind === 'action' || Boolean(item.isAction) };
  }
  const raw = String(item || '').trim();
  if (!raw) return null;
  // Support "Label -> Action" or "Label -> action: Action" or "Label -> command: Command"
  const arrowIdx = raw.indexOf('->');
  if (arrowIdx > 0) {
    const rawLabel = raw.slice(0, arrowIdx).trim();
    const label = truncate(rawLabel);
    let action = raw.slice(arrowIdx + 2).trim();
    if (action.toLowerCase().startsWith('action:')) {
      const act = action.slice(7).trim().replace(/^\(+|\)+$/g, '').trim();
      return { label, action: act, payload: act, kind: 'action', isAction: true };
    }
    if (action.toLowerCase().startsWith('command:')) {
      const cmd = action.slice(8).trim();
      return { label, action: cmd, payload: cmd, kind: 'command', isAction: false };
    }
    const c = classifyChoicePayload(action);
    return { label, action: c.payload, payload: c.payload, kind: c.kind, isAction: c.isAction };
  }
  // Support "Label: action: Action"
  const colonAction = /^(.*?):\s*action:\s*(.*)$/i.exec(raw);
  if (colonAction) {
    const label = truncate(colonAction[1].trim());
    return { label, action: colonAction[2].trim(), payload: colonAction[2].trim(), kind: 'action', isAction: true };
  }

  // Arrow-less action/dialogue pattern or long plain text
  const norm = raw
    .replace(/[\u201C\u201D\u201E\u201F\u2033\u2036]/g, '"')
    .replace(/[\u2018\u2019\u201A\u201B\u2032\u2035]/g, "'")
    .replace(/\uFF08/g, '(').replace(/\uFF09/g, ')');
  const clean = (/^\*[\s\S]*\*$/.test(norm) && norm.length >= 2) ? norm.slice(1, -1).trim() : norm;
  const unwrapped = unwrapParens(clean);
  const hadParens = unwrapped !== clean;

  // 1. Combo: "dialogue" (action) or ("dialogue" (action))
  const combo = /^"([^"]*)"\s*\(([\s\S]+)\)\s*$/.exec(unwrapped);
  if (combo && (combo[1].trim() || unwrapParens(combo[2].trim()))) {
    const line = combo[1].trim(), act = unwrapParens(combo[2].trim());
    const rawLabel = line || act, payload = line ? ('"' + line + '" (' + act + ')') : ('(' + act + ')');
    return { label: truncate(rawLabel), action: payload, payload, kind: 'action', isAction: true };
  }

  // 2. Dialogue-only: "dialogue" or ("dialogue") or 'dialogue'
  const sayOnly = /^["']([^"']*)["']\s*$/.exec(unwrapped);
  if (sayOnly && sayOnly[1].trim()) {
    const line = sayOnly[1].trim(), payload = '"' + line + '"';
    return { label: truncate(line), action: payload, payload, kind: 'action', isAction: true };
  }

  // 3. Action-only: (action)
  if (hadParens && unwrapped && !/^\d+$|^[a-zA-Z]$/.test(unwrapped)) {
    const payload = '(' + unwrapped + ')';
    return { label: truncate(unwrapped), action: payload, payload, kind: 'action', isAction: true };
  }

  // 4. Long plain text defense (prevent button blowout on mobile)
  if (raw.length > maxLabel) {
    return { label: truncate(raw), action: raw, payload: raw, kind: 'say', isAction: false };
  }

  return raw;
}

function splitChoices(src) {
  const s = String(src || '');
  const m = CHOICES_TAIL.exec(s);
  if (m) {
    const choices = m[1].split('|').map(x => parseChoiceItem(x)).filter(Boolean).slice(0, CHOICES_MAX);
    return { text: s.slice(0, m.index), choices };
  }
  return { text: s.replace(CHOICES_OPEN, ''), choices: [] };
}

function pickChoice(choice) {
  if (!choice || typeof inputEl === 'undefined' || !inputEl) return;
  // If the chip already carries a classified action/command, honor it (avoid re-parse flipping
  // bare action payloads without parens into the wrong path).
  let item;
  if (choice && typeof choice === 'object' && (choice.kind === 'action' || choice.isAction === true || choice.kind === 'command' || choice.kind === 'say')) {
    item = {
      label: String(choice.label || '').trim(),
      kind: String(choice.kind || (choice.isAction ? 'action' : 'say')).trim(),
      payload: String(choice.payload !== undefined ? choice.payload : (choice.action || choice.label || '')).trim(),
      action: String(choice.action || choice.payload || choice.label || '').trim(),
      isAction: Boolean(choice.isAction) || choice.kind === 'action',
    };
    if (item.kind === 'action') item.isAction = true;
  } else {
    const parsed = parseChoiceItem(choice);
    item = typeof parsed === 'object' && parsed ? parsed : { label: String(choice), action: String(choice), kind: 'say', payload: String(choice) };
  }
  const kind = item.kind || (item.isAction ? 'action' : 'say');
  const payload = item.payload || item.action || item.label;

  if (kind === 'action' || item.isAction) {
    // #246: choices (incl. dialogue-flavor / combo) always go as action — never flip to say.
    const reclass = classifyChoicePayload(payload);
    const act = String(reclass.kind === 'action' ? reclass.payload : payload);
    const bare = (typeof stripOuterParens === 'function') ? stripOuterParens(act) : act.replace(/^\(+|\)+$/g, '').trim();
    // Keep dialogue-flavor / combo payload intact (starts with quote); bare actions lose outer wraps.
    const wire = /^"/.test(String(act).trim()) ? String(act).trim() : bare;
    if (typeof sendAction === 'function') {
      sendAction(wire);
      return;
    }
    inputEl.value = '/act ' + wire;
    sendPickedChoice();
    return;
  }
  if (kind === 'command') {
    const cmdText = payload.startsWith('/') ? payload : ('/' + payload);
    if (/^\/move\s/i.test(cmdText) && typeof moveDoor === 'function') return moveDoor(cmdText);   // PLACE_MOVE_v1
    const inc = typeof parseIncidentCommand === 'function' && parseIncidentCommand(cmdText);   // il/E
    if (inc) return runIncidentDecision(inc);
    const ticketCmd = typeof parseTicketCommand === 'function' ? parseTicketCommand(cmdText) : null;
    if (ticketCmd) {   // TICKET_BUTTONS_v1: the one decision path (app-evolution.js), no bubble
      if (typeof runTicketDecision === 'function') runTicketDecision(ticketCmd, typeof tapSendOpts === 'function' ? tapSendOpts() : undefined);
      return;
    }
    inputEl.value = cmdText;
    sendPickedChoice();
    return;
  }

  // default: say
  inputEl.value = payload || item.label;
  sendPickedChoice();
}

// A chip tap is not typing: on touch devices send without refocusing inputEl (no keyboard pop).
function sendPickedChoice() {
  if (typeof send !== 'function') return;
  send(typeof tapSendOpts === 'function' ? tapSendOpts() : undefined);
}

function getChoiceBarEl() {
  if (typeof document !== 'undefined' && document && typeof document.getElementById === 'function') {
    const el = document.getElementById('choiceBar');
    if (el) return el;
  }
  if (typeof choiceBarEl !== 'undefined' && choiceBarEl) {
    return choiceBarEl;
  }
  return null;
}

var _suppressChoiceBar = false;
function isChoiceBarSuppressed() { return Boolean(_suppressChoiceBar); }
function setChoiceBarSuppressed(on) { _suppressChoiceBar = Boolean(on); }
function isChoiceKeepEnabled() {
  try { return typeof localStorage !== 'undefined' && localStorage ? (localStorage.getItem('pe_chat_keep_choices') !== '0') : true; } catch (_) { return true; }
}
function resetChoiceBar() {
  const bar = getChoiceBarEl();
  if (bar) {
    if (bar.classList && typeof bar.classList.remove === 'function') bar.classList.remove('closing');
    bar.textContent = ''; bar.hidden = true; bar._owner = null;
    if (typeof updateScrollBottomButton === 'function') updateScrollBottomButton();
  }
}
function syncLastChoices() {
  if (!isChoiceKeepEnabled()) { resetChoiceBar(); return; }
  if (typeof logEl === 'undefined' || !logEl) return;
  const msgs = logEl.querySelectorAll('.msg:not(.system)');
  const last = msgs.length ? msgs[msgs.length - 1] : null;
  const isAssistant = last && (last.classList ? last.classList.contains('assistant') : /\bassistant\b/.test(last.className || ''));
  if (last && isAssistant && last._choices && last._choices.length) renderChoiceChips(last, last._choices);
  else resetChoiceBar();
  syncChoiceChips();
}

function renderChoiceChips(node, choices, isPrepend) {
  const md = node ? (node.querySelector('.md') || node) : null;
  if (md) md.querySelectorAll('.choice-chips').forEach(el => el.remove());

  if (!isChoiceKeepEnabled()) {
    resetChoiceBar();
    return;
  }
  if (isChoiceBarSuppressed()) {
    return;
  }

  const isPrependState = Boolean(isPrepend || (node && (node._prepend || (node.dataset && node.dataset.prepend === '1'))));
  let isNotLatestAssistant = false;
  if (typeof logEl !== 'undefined' && logEl && node) {
    let msgs = [];
    if (typeof logEl.querySelectorAll === 'function') {
      try { msgs = logEl.querySelectorAll('.msg.assistant:not(.system)'); } catch (_) {}
      if (!msgs || !msgs.length) {
        const all = logEl.querySelectorAll('.msg:not(.system)') || [];
        msgs = Array.prototype.filter.call(all, m => /\bassistant\b/.test(m.className || '') && !/\bsystem\b/.test(m.className || ''));
      }
    }
    if (msgs && msgs.length) {
      const last = msgs[msgs.length - 1];
      let inLog = (typeof logEl.contains === 'function') ? logEl.contains(node) : false;
      if (!inLog) { for (let i = 0; i < msgs.length; i++) { if (msgs[i] === node) { inLog = true; break; } } }
      if (inLog && node !== last) isNotLatestAssistant = true;
    }
  }
  const skipBar = isPrependState || isNotLatestAssistant;

  const bar = skipBar ? null : getChoiceBarEl();
  if (bar) {
    if (bar.classList && typeof bar.classList.remove === 'function') {
      bar.classList.remove('closing');
    }
    bar.textContent = '';
    bar.hidden = true;
    bar._owner = null;
  }
  if (!choices || !choices.length) return;
  if (skipBar) return;

  const card = document.createElement('div');
  card.className = 'choice-card';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'choice-close-btn';
  closeBtn.setAttribute('aria-label', (typeof tr === 'function') ? tr('md.next_actions_close') : 'Close');
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', (e) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    if (bar) {
      if (bar.classList && typeof bar.classList.add === 'function') {
        bar.classList.add('closing');
      }
      const hideBar = () => {
        bar.hidden = true;
        if (typeof updateScrollBottomButton === 'function') updateScrollBottomButton();
        if (bar.classList && typeof bar.classList.remove === 'function') {
          bar.classList.remove('closing');
        }
        bar.textContent = '';
        bar._owner = null;
      };
      if (typeof setTimeout === 'function') {
        setTimeout(hideBar, 180);
      } else {
        hideBar();
      }
    } else if (card) {
      if (card.classList && typeof card.classList.add === 'function') {
        card.classList.add('closing');
        if (typeof setTimeout === 'function') {
          setTimeout(() => { if (typeof card.remove === 'function') card.remove(); }, 180);
        } else {
          if (typeof card.remove === 'function') card.remove();
        }
      } else if (typeof card.remove === 'function') {
        card.remove();
      }
    }
  });
  card.appendChild(closeBtn);

  const row = document.createElement('div');
  row.className = 'choice-card-body choice-chips';
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', (typeof tr === 'function') ? tr('md.next_actions') : 'Next actions');
  choices.forEach(c => {
    const parsed = parseChoiceItem(c);
    if (!parsed) return;
    const item = typeof parsed === 'string' ? { label: parsed, action: parsed, isAction: false, kind: 'say' } : parsed;
    const isAct = item.isAction || item.kind === 'action';
    const isCmd = item.kind === 'command';
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'choice-chip' + (isAct ? ' choice-action' : '') + (isCmd ? ' choice-command' : '');
    b.textContent = (isAct ? '✦ ' : '') + item.label;
    b.addEventListener('click', () => pickChoice(item));
    row.appendChild(b);
  });
  card.appendChild(row);

  if (bar) {
    bar.appendChild(card);
    bar.hidden = false;
    bar._owner = node;   // the card lives outside the bubble, so syncChoiceChips asks the bar whose it is
  } else if (md) {
    md.appendChild(card);
  }
}

// Keep choice chips only on newest assistant message.
function syncChoiceChips() {
  if (typeof logEl === 'undefined' || !logEl) return;
  if (!isChoiceKeepEnabled()) {
    resetChoiceBar();
    logEl.querySelectorAll('.choice-chips').forEach(row => {
      if (row.parentElement && row.parentElement.className === 'choice-card') {
        row.parentElement.remove();
      } else {
        row.remove();
      }
    });
    return;
  }
  if (isChoiceBarSuppressed()) return;
  const msgs = logEl.querySelectorAll('.msg:not(.system)');
  const last = msgs.length ? msgs[msgs.length - 1] : null;
  const bar = getChoiceBarEl();
  const hasChoicesOnLast = last && ((last._choices && last._choices.length) || last.querySelector('.choice-chips') || (bar && bar._owner === last));
  const isAssistant = last && (last.classList ? last.classList.contains('assistant') : /\bassistant\b/.test(last.className || ''));
  if (!last || !isAssistant || !hasChoicesOnLast) {
    if (bar) {
      if (bar.classList && typeof bar.classList.remove === 'function') {
        bar.classList.remove('closing');
      }
      bar.textContent = '';
      bar.hidden = true;
      if (typeof updateScrollBottomButton === 'function') updateScrollBottomButton();
      bar._owner = null;
    }
  }
  logEl.querySelectorAll('.choice-chips').forEach(row => {
    if (!last || !last.contains(row)) {
      if (row.parentElement && row.parentElement.className === 'choice-card') {
        row.parentElement.remove();
      } else {
        row.remove();
      }
    }
  });
}

if (typeof window !== 'undefined') {
  window.CHOICES_TAIL = CHOICES_TAIL;
  window.CHOICES_OPEN = CHOICES_OPEN;
  window.CHOICES_MAX = CHOICES_MAX;
  window.CHOICE_LABEL_MAX = CHOICE_LABEL_MAX;
  window.truncateChoiceLabel = truncateChoiceLabel;
  window.stripOuterParens = stripOuterParens;
  window.classifyChoicePayload = classifyChoicePayload;
  window.parseChoiceItem = parseChoiceItem;
  window.splitChoices = splitChoices;
  window.pickChoice = pickChoice;
  window.sendPickedChoice = sendPickedChoice;
  window.getChoiceBarEl = getChoiceBarEl;
  window.isChoiceBarSuppressed = isChoiceBarSuppressed;
  window.setChoiceBarSuppressed = setChoiceBarSuppressed;
  window.isChoiceKeepEnabled = isChoiceKeepEnabled;
  window.resetChoiceBar = resetChoiceBar;
  window.syncLastChoices = syncLastChoices;
  window.renderChoiceChips = renderChoiceChips;
  window.syncChoiceChips = syncChoiceChips;
}
