/* Model picker -- a short icon button + menu instead of a wide <select>, and a composer
   placeholder that always names the model in use.
   (실장님: 모바일에서 모델 선택이 폭을 차지해서 -- 짧은 버튼, 탭과 같은 스타일의 아이콘, 현재 모델은
   placeholder로 명확히.)
   <select id="model"> (app.js: modelEl) stays in the DOM, hidden, as the single source of truth:
   everything that sends or saves a model still reads modelEl.value, so this file only
   changes how it is chosen and shown. */
const modelBtnEl = document.getElementById('modelBtn');
const modelMenuEl = document.getElementById('modelMenu');

function modelLabel(value) {
  return String(value || '').trim() || '기본 모델';
}

// Pure: what the composer placeholder says. The model comes first, so on a narrow screen the
// ellipsis that textarea::placeholder already has cuts the hint, never the model.
function composerPlaceholder(model, opts) {
  const o = opts || {};
  const m = modelLabel(model);
  if (typeof o.busySec === 'number') {
    return o.compact
      ? `${m} · 작업 중 (${o.busySec}초)… (? 질문 / 지시는 다음 단계에 반영)`
      : `${m} · 작업 진행 중 (${o.busySec}초)… 질문(?)은 즉시 샛길 답변(/btw), 작업 지시는 지금 단계가 끝나는 대로 반영`;
  }
  return o.compact
    ? `${m} · 메시지 입력… (/ 또는 /btw)`
    : `${m} · 메시지를 입력… (/ 명령어·스킬, /btw <질문>)`;
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

setupModelPicker();
