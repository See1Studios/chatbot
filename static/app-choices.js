// Choice chips. Parsing lives in markdown.js, which loads after this file.

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
  window.getChoiceBarEl = getChoiceBarEl;
  window.isChoiceBarSuppressed = isChoiceBarSuppressed;
  window.setChoiceBarSuppressed = setChoiceBarSuppressed;
  window.isChoiceKeepEnabled = isChoiceKeepEnabled;
  window.resetChoiceBar = resetChoiceBar;
  window.syncLastChoices = syncLastChoices;
  window.renderChoiceChips = renderChoiceChips;
  window.syncChoiceChips = syncChoiceChips;
}
