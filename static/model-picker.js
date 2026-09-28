/* Model picker -- a short icon button + menu instead of a wide <select>, and a composer
   placeholder that always names the model in use.
   (operator: 모바일에서 모델 선택이 폭을 차지해서 -- 짧은 버튼, 탭과 같은 스타일의 아이콘, 현재 모델은
   placeholder로 명확히.)
   <select id="model"> (app.js: modelEl) stays in the DOM, hidden, as the single source of truth:
   everything that sends or saves a model still reads modelEl.value, so this file only
   changes how it is chosen and shown. */
const modelBtnEl = document.getElementById('modelBtn');
const modelMenuEl = document.getElementById('modelMenu');

function modelLabel(value) {
  return String(value || '').trim() || '기본 모델';
}

// Pure: what the composer placeholder says -- only what to do; the model sits in the corner tag (MODEL_TAG_v1).
// Short on purpose (operator, 2026-09-28). A hint -- e.g. the model cannot see the attached image
// (app-attach.js composerHint) -- takes the place of the instruction, since it is what matters now.
function composerPlaceholder(opts) {
  const o = opts || {};
  // RETRY_LAST_v1: a failed message waits here; Enter on the empty box sends it again (app-retry.js)
  if (o.retry && typeof o.busySec !== 'number') return `↻ 다시 보내기: ${retryShort(o.retry, o.compact ? 18 : 40)}`;   // l10n-ok
  if (o.hint) return o.hint;
  if (typeof o.busySec === 'number') return `작업 중 (${o.busySec}초)…`;   // l10n-ok
  if (o.actKey) return '메시지 입력… (Space: 행동)';   // l10n-ok ACT_KEY_v1
  return '메시지 입력…';   // l10n-ok
}

function modelChoices() {
  if (typeof modelEl === 'undefined' || !modelEl) return [];
  return Array.prototype.map.call(modelEl.options, o => ({ value: o.value, label: o.textContent || modelLabel(o.value) }));
}

function renderModelMenu(menu, choices, current, onPick) {
  menu.innerHTML = '';
  choices.forEach(c => {
    const on = c.value === current;
    const isFree = c.value.endsWith(':free') || c.value.includes(':free');
    const item = document.createElement('div');
    item.className = 'slash-item' + (on ? ' selected' : '');
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', on ? 'true' : 'false');
    item.tabIndex = 0;
    if (isFree) {
      const badge = document.createElement('span');
      badge.className = 'slash-badge free';
      badge.textContent = 'FREE';
      item.appendChild(badge);
    }
    const name = document.createElement('span');
    name.className = 'slash-name';
    name.textContent = c.label;
    const mark = document.createElement('span');
    mark.className = 'slash-desc';
    mark.textContent = on ? '✓ 사용 중' : '';
    item.appendChild(name);
    item.appendChild(mark);
    item.addEventListener('click', () => onPick(c.value));
    item.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onPick(c.value);
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const sib = e.key === 'ArrowDown' ? item.nextSibling : item.previousSibling;
        if (sib && sib.focus) sib.focus();
      }
    });
    menu.appendChild(item);
  });
}

function isModelMenuOpen() {
  return !!modelMenuEl && !modelMenuEl.hidden;
}

function hideModelMenu() {
  if (!modelMenuEl) return;
  modelMenuEl.hidden = true;
  // undo the inline placement slash.js's positionSlashMenu() applied
  ['position', 'left', 'width', 'right', 'bottom', 'top', 'maxHeight', 'zIndex'].forEach(k => { modelMenuEl.style[k] = ''; });
  if (modelBtnEl) {
    modelBtnEl.classList.remove('active');
    modelBtnEl.setAttribute('aria-expanded', 'false');
  }
}

function showModelMenu(viaKeyboard) {
  if (!modelMenuEl || typeof modelEl === 'undefined' || !modelEl) return;
  if (typeof hideSlashMenu === 'function') hideSlashMenu();   // one popup at a time
  renderModelMenu(modelMenuEl, modelChoices(), modelEl.value, pickModel);
  modelMenuEl.hidden = false;
  if (typeof positionSlashMenu === 'function') positionSlashMenu(modelMenuEl);
  if (modelBtnEl) {
    modelBtnEl.classList.add('active');
    modelBtnEl.setAttribute('aria-expanded', 'true');
  }
  if (viaKeyboard) {   // the menu is not next to the button in tab order: move focus into it
    const cur = modelMenuEl.querySelector('.selected') || modelMenuEl.querySelector('.slash-item');
    if (cur && cur.focus) cur.focus();
  }
}

function toggleModelMenu(viaKeyboard) {
  if (isModelMenuOpen()) hideModelMenu();
  else showModelMenu(Boolean(viaKeyboard));
}

function pickModel(value) {
  if (typeof modelEl !== 'undefined' && modelEl && modelEl.value !== value) {
    modelEl.value = value;
    modelEl.dispatchEvent(new Event('change'));   // app.js's onchange persists the choice
  }
  hideModelMenu();
  syncModelUi();
}

// Button title/aria-label + placeholder follow the model in use. Called whenever the model list is
// rebuilt (provider switch) or the value changes.
function syncModelUi() {
  const hasModel = typeof modelEl !== 'undefined' && modelEl;
  const label = modelLabel(hasModel ? modelEl.value : '');
  if (modelBtnEl) {
    const t = `모델 선택 (현재: ${label})`;
    modelBtnEl.title = t;
    modelBtnEl.setAttribute('aria-label', t);
  }
  // before boot has filled the list there is nothing to name yet -- keep the static placeholder
  if (hasModel && modelEl.options && modelEl.options.length && typeof refreshComposerPlaceholder === 'function') {
    refreshComposerPlaceholder();
  }
}

function setupModelPicker() {
  if (!modelBtnEl || !modelMenuEl) return;
  // pointerdown + preventDefault like the "/" button: opening the menu must not steal focus from
  // the input (and pop the on-screen keyboard down/up)
  modelBtnEl.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    e.stopPropagation();
    toggleModelMenu(false);
  });
  // Enter/Space on the focused button arrive as a click with detail 0 (no pointer involved)
  modelBtnEl.addEventListener('click', (e) => {
    if (e.detail === 0) toggleModelMenu(true);
  });
  document.addEventListener('pointerdown', (e) => {
    if (isModelMenuOpen() && !modelMenuEl.contains(e.target) && !modelBtnEl.contains(e.target)) hideModelMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isModelMenuOpen()) {
      hideModelMenu();
      modelBtnEl.focus();
    }
  });
  if (typeof inputEl !== 'undefined' && inputEl) inputEl.addEventListener('input', hideModelMenu);
  window.addEventListener('resize', () => {
    if (isModelMenuOpen() && typeof positionSlashMenu === 'function') positionSlashMenu(modelMenuEl);
  });
  // crossing the phone breakpoint changes which placeholder text applies
  if (window.matchMedia) {
    const mq = window.matchMedia('(max-width: 600px)');
    const onMq = () => syncModelUi();
    if (mq.addEventListener) mq.addEventListener('change', onMq);
    else if (mq.addListener) mq.addListener(onMq);
  }
  syncModelUi();
}

// MODEL_TAG_v2: the model button (#modelBtn) sits in the composer's right corner, left of the inline button
// (operator, 2026-09-28/29). The empty box shows the model's name when it takes at most a third of the box, else the
// icon; typing, a short screen and an open phone keyboard leave the icon (chat-composer.css). The input keeps clear
// of it (--model-tag-w). Placed from the input's box, since the phone composer reorders its children.
const MODEL_TAG_ROOM = 0.35;
function placeModelTag(btn, input, model) {
  if (!btn || !input) return;
  const name = btn.querySelector ? btn.querySelector('.model-name') : null;
  if (name) name.textContent = modelLabel(model);
  const box = input.offsetParent;
  if (box) {
    const inset = input.classList.contains('has-inline-btn') ? 44 : 10;
    const h = input.offsetHeight;
    btn.style.right = Math.max(0, box.clientWidth - input.offsetLeft - input.offsetWidth + inset) + 'px';
    btn.style.top = (input.offsetTop + h - Math.min(h / 2, 21)) + 'px';   // on the last line, like the send button
  }
  if (input.value) return;                       // typing: CSS shows the icon; the empty-box width stays as it was
  btn.classList.remove('icon-only');
  if (btn.offsetWidth > input.offsetWidth * MODEL_TAG_ROOM) btn.classList.add('icon-only');
  input.style.setProperty('--model-tag-w', (btn.offsetWidth ? btn.offsetWidth + 6 : 0) + 'px');
}

function refreshModelTag() {
  if (modelBtnEl && typeof inputEl !== 'undefined') placeModelTag(modelBtnEl, inputEl, typeof modelEl !== 'undefined' && modelEl ? modelEl.value : '');
}

function setupModelTag() {
  if (!modelBtnEl || typeof inputEl === 'undefined' || !inputEl) return;
  window.addEventListener('resize', refreshModelTag);
  if (typeof ResizeObserver === 'function') new ResizeObserver(refreshModelTag).observe(inputEl);
  refreshModelTag();
}

setupModelPicker();
setupModelTag();
