/* Slash commands / skills menu — extracted from app.js (monolith-split Phase 2). */
// --- Slash Commands & Skills Autocomplete Engine ---
const slashMenuEl = document.getElementById('slashMenu');
const slashBtnEl = document.getElementById('slashBtn');
let slashCatalog = {
  commands: [
    { name: "/act", key: "act", template: "/act " },
    { name: "/me", key: "me", template: "/me " },
    { name: "/btw", key: "btw", template: "/btw " },
    { name: "/continue", key: "continue", template: "/continue" },
    { name: "/new", key: "new", template: "/new" },
    { name: "/defib", key: "defib", template: "/defib" },
    { name: "/reboot", key: "reboot", template: "/defib" },
    { name: "/status", key: "status", template: "/status" },
    { name: "/review", key: "review", template: "Run an observation review: take the open observations and unreviewed candidates with the observation tool's review, go through them one by one with me, and only resolve them and propose tickets. Record it as reviewed when done. Do not start any work. Reply in my language." },
    { name: "/ticket", key: "ticket", template: "/ticket " },
    { name: "/ticket go", key: "ticket_go", template: "/ticket go " },
    { name: "/ticket approve", key: "ticket_approve", template: "/ticket approve " },
    { name: "/ticket decline", key: "ticket_decline", template: "/ticket decline " },
    { name: "/ticket reopen", key: "ticket_reopen", template: "/ticket reopen " },
    { name: "/ticket delegate", key: "ticket_delegate", template: "/ticket delegate " },
    { name: "/ticket merge", key: "ticket_merge", template: "/ticket merge " },
    { name: "/ticket rework", key: "ticket_rework", template: "/ticket rework " },
    { name: "/ticket replan", key: "ticket_replan", template: "/ticket replan " },
    { name: "/ticket discard", key: "ticket_discard", template: "/ticket discard " },
    { name: "/ticket disown", key: "ticket_disown", template: "/ticket disown " },
    { name: "/ticket unqueue", key: "ticket_unqueue", template: "/ticket unqueue " },
    { name: "/ticket allow", key: "ticket_allow", template: "/ticket allow " },
    { name: "/clear", key: "clear", template: "/clear" },
    { name: "/compact", key: "compact", template: "/compact" },
    { name: "/help", key: "help", template: "/help" },
  ],
  popular: [],
  skills: []
};

let slashVisibleItems = [];
let slashSelectedIndex = 0;

async function loadSlashSkills() {
  try {
    const data = await api('/api/skills');
    if (data && data.ok) {
      if (Array.isArray(data.commands) && data.commands.length) {
        // Server list wins per name; client-only commands (/act, /me, /ticket …) stay.
        const served = new Set(data.commands.map(c => c.name));
        slashCatalog.commands = data.commands.concat(slashCatalog.commands.filter(c => !served.has(c.name)));
      }
      if (Array.isArray(data.popular)) slashCatalog.popular = data.popular;
      if (Array.isArray(data.skills)) slashCatalog.skills = data.skills;
    }
  } catch (_) {}
}

function clearSlashMenuPos() {
  if (!slashMenuEl) return;
  slashMenuEl.style.position = '';
  slashMenuEl.style.left = '';
  slashMenuEl.style.width = '';
  slashMenuEl.style.right = '';
  slashMenuEl.style.bottom = '';
  slashMenuEl.style.top = '';
  slashMenuEl.style.maxHeight = '';
  slashMenuEl.style.zIndex = '';
}

function positionSlashMenu(menuEl) {
  const menu = menuEl || document.getElementById('slashMenu');   // the model menu reuses this placement
  if (!menu || menu.hidden) return;
  const composer = menu.closest('.composer') || menu.parentElement;
  if (!composer) return;
  const rect = composer.getBoundingClientRect();
  const vv = window.visualViewport;
  const viewTop = vv ? vv.offsetTop : 0;
  const gap = 8;
  const spaceAbove = Math.max(96, rect.top - viewTop - gap);
  const maxH = Math.min(280, spaceAbove);
  menu.style.position = 'fixed';
  menu.style.left = Math.max(0, rect.left) + 'px';
  menu.style.width = Math.max(160, rect.width) + 'px';
  menu.style.right = 'auto';
  menu.style.top = 'auto';
  menu.style.bottom = Math.max(gap, window.innerHeight - rect.top + gap) + 'px';
  menu.style.maxHeight = maxH + 'px';
  menu.style.zIndex = '200';
}

function hideSlashMenu() {
  if (!slashMenuEl) return;
  slashMenuEl.hidden = true;
  slashVisibleItems = [];
  slashSelectedIndex = 0;
  clearSlashMenuPos();
  if (slashBtnEl) {
    slashBtnEl.classList.remove('active');
    slashBtnEl.setAttribute('aria-expanded', 'false');
  }
}

function renderSlashMenu(query) {
  if (!slashMenuEl) return;
  const q = (query || '').toLowerCase().trim();
  
  // I18N_v1: a built-in command's label and description come from the catalog (slash.<key>.label / .desc) when shown
  const cmds = slashCatalog.commands.map(c => c.key ? Object.assign({}, c, { label: tr('slash.' + c.key + '.label'), desc: tr('slash.' + c.key + '.desc') }) : c).filter(c => 
    !q || c.name.toLowerCase().includes(q) || (c.label && c.label.toLowerCase().includes(q)) || (c.desc && c.desc.toLowerCase().includes(q))
  );

  const pops = slashCatalog.popular.filter(p => 
    !q || p.name.toLowerCase().includes(q) || (p.skill && p.skill.toLowerCase().includes(q)) || (p.label && p.label.toLowerCase().includes(q)) || (p.desc && p.desc.toLowerCase().includes(q))
  );

  const popSkillSet = new Set(slashCatalog.popular.map(p => p.skill));
  let otherSkills = [];
  if (q) {
    otherSkills = slashCatalog.skills.filter(s => 
      !popSkillSet.has(s.name) && (s.name.toLowerCase().includes(q) || (s.desc && s.desc.toLowerCase().includes(q)))
    ).slice(0, 10);
  }

  slashVisibleItems = [];
  let html = '';

  if (cmds.length) {
    html += '<div class="slash-category">' + escapeHtml(tr('slash.cat_commands')) + '</div>';
    cmds.forEach(c => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(c);
      html += `<div class="slash-item" data-idx="${idx}" role="option" aria-selected="false">
        <span class="slash-badge cmd">${escapeHtml(tr('slash.badge_cmd'))}</span>
        <span class="slash-name">${escapeHtml(c.name)}</span>
        <span class="slash-desc">${escapeHtml(c.desc || c.label)}</span>
      </div>`;
    });
  }

  if (pops.length) {
    html += '<div class="slash-category">' + escapeHtml(tr('slash.cat_popular')) + '</div>';
    pops.forEach(p => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(p);
      html += `<div class="slash-item" data-idx="${idx}" role="option" aria-selected="false">
        <span class="slash-badge skill">${escapeHtml(tr('slash.badge_skill'))}</span>
        <span class="slash-name">${escapeHtml(p.name)}</span>
        <span class="slash-desc">${escapeHtml(p.desc || p.label)}</span>
      </div>`;
    });
  }

  if (otherSkills.length) {
    html += '<div class="slash-category">' + escapeHtml(tr('slash.cat_all_skills')) + '</div>';
    otherSkills.forEach(s => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(s);
      html += `<div class="slash-item" data-idx="${idx}" role="option" aria-selected="false">
        <span class="slash-badge skill">${escapeHtml(tr('slash.badge_skill'))}</span>
        <span class="slash-name">/skill ${escapeHtml(s.name)}</span>
        <span class="slash-desc">${escapeHtml(s.desc || s.name)}</span>
      </div>`;
    });
  }

  if (!slashVisibleItems.length) {
    html = '<div class="slash-empty">' + escapeHtml(tr('slash.none')) + '</div>';
  }

  slashMenuEl.innerHTML = html;
  slashMenuEl.hidden = false;
  slashSelectedIndex = 0;
  updateSlashSelection();
  positionSlashMenu();
  if (slashBtnEl) {
    slashBtnEl.classList.add('active');
    slashBtnEl.setAttribute('aria-expanded', 'true');
  }
}

let slashIgnoreDismissUntil = 0;

function toggleSlashMenu() {
  if (!slashMenuEl) return;
  if (!slashMenuEl.hidden) {
    hideSlashMenu();
    return;
  }
  // touch: open the menu only -- no '/' typed in, no focus, so no keyboard pop
  const touch = typeof isTouchDevice === 'function' && isTouchDevice();
  if (!touch && inputEl && !String(inputEl.value || '').startsWith('/') && !String(inputEl.value || '').trim()) {
    inputEl.value = '/';
    autoResizeInput();
    updateSendButton();
  }
  const val = (inputEl && inputEl.value) || '';
  const q = val.startsWith('/') ? val.slice(1) : '';
  renderSlashMenu(q);
  slashIgnoreDismissUntil = Date.now() + 450;
  if (inputEl && !touch) {
    requestAnimationFrame(() => {
      if (slashMenuEl.hidden) return;
      inputEl.focus({ preventScroll: true });
      if (inputEl.value === '/') {
        try { inputEl.setSelectionRange(1, 1); } catch (_) {}
      }
    });
  }
}

function updateSlashSelection() {
  if (!slashMenuEl) return;
  const items = slashMenuEl.querySelectorAll('.slash-item');
  items.forEach((it, i) => {
    if (i === slashSelectedIndex) {
      it.classList.add('selected');
      it.setAttribute('aria-selected', 'true');
      it.scrollIntoView({ block: 'nearest' });
    } else {
      it.classList.remove('selected');
      it.setAttribute('aria-selected', 'false');
    }
  });
}

function applySlashItem(item) {
  if (!item || !inputEl) return;
  inputEl.value = item.template || (item.name ? item.name + (item.name.endsWith(' ') ? '' : ' ') : '');
  autoResizeInput();
  updateSendButton();
  hideSlashMenu();
  if (typeof isTouchDevice === 'function' && isTouchDevice()) {
    if (inputEl.blur) inputEl.blur();   // the template is filled in; the user taps the input to edit
    return;
  }
  inputEl.focus();
  inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
}

function handleSlashKeydown(e) {
  if (e.isComposing || e.keyCode === 229) return false;
  if (!slashMenuEl || slashMenuEl.hidden || slashVisibleItems.length === 0) return false;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    slashSelectedIndex = (slashSelectedIndex + 1) % slashVisibleItems.length;
    updateSlashSelection();
    return true;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    slashSelectedIndex = (slashSelectedIndex - 1 + slashVisibleItems.length) % slashVisibleItems.length;
    updateSlashSelection();
    return true;
  }
  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault();
    const selected = slashVisibleItems[slashSelectedIndex];
    if (selected) applySlashItem(selected);
    return true;
  }
  if (e.key === 'Escape') {
    e.preventDefault();
    hideSlashMenu();
    return true;
  }
  return false;
}

function setupSlashAutocomplete() {
  if (!inputEl || !slashMenuEl) return;
  loadSlashSkills();

  if (slashBtnEl) {
    slashBtnEl.setAttribute('aria-expanded', 'false');
    slashBtnEl.setAttribute('aria-haspopup', 'listbox');
    slashBtnEl.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSlashMenu();
    });
  }

  inputEl.addEventListener('input', () => {
    const val = inputEl.value;
    if (val.startsWith('/') && !val.includes(' ') && !val.includes('\n')) {
      renderSlashMenu(val.slice(1));
    } else {
      hideSlashMenu();
    }
  });

  let slashTouchStartY = 0;
  let slashTouchStartX = 0;
  let slashIsScrolling = false;

  slashMenuEl.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      slashTouchStartX = e.touches[0].clientX;
      slashTouchStartY = e.touches[0].clientY;
      slashIsScrolling = false;
    }
  }, { passive: true });

  slashMenuEl.addEventListener('touchmove', (e) => {
    if (e.touches.length === 1) {
      const dx = Math.abs(e.touches[0].clientX - slashTouchStartX);
      const dy = Math.abs(e.touches[0].clientY - slashTouchStartY);
      if (dx > 8 || dy > 8) {
        slashIsScrolling = true;
      }
    }
  }, { passive: true });

  slashMenuEl.addEventListener('click', (e) => {
    if (slashIsScrolling) {
      slashIsScrolling = false;
      return;
    }
    const itemEl = e.target.closest('.slash-item');
    if (!itemEl) return;
    e.preventDefault();
    const idx = parseInt(itemEl.dataset.idx, 10);
    if (!isNaN(idx) && slashVisibleItems[idx]) {
      applySlashItem(slashVisibleItems[idx]);
    }
  });

  document.addEventListener('pointerdown', (e) => {
    if (Date.now() < slashIgnoreDismissUntil) return;
    if (!slashMenuEl.hidden && !slashMenuEl.contains(e.target) && e.target !== inputEl && (!slashBtnEl || !slashBtnEl.contains(e.target))) {
      hideSlashMenu();
    }
  });
}

setupSlashAutocomplete();
