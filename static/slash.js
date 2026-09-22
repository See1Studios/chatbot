/* Slash commands / skills menu — extracted from app.js (monolith-split Phase 2). */
// --- Slash Commands & Skills Autocomplete Engine ---
const slashMenuEl = document.getElementById('slashMenu');
const slashBtnEl = document.getElementById('slashBtn');
let slashCatalog = {
  commands: [
    { name: "/btw", label: "샛길 질문", desc: "작업 중 즉시 경량 샛길 답변", template: "/btw " },
    { name: "/continue", label: "이어하기", desc: "현재 대화 요약 인계받아 새 세션", template: "/continue" },
    { name: "/new", label: "새 세션", desc: "완전한 새 대화 세션 시작", template: "/new" },
    { name: "/defib", label: "심폐소생", desc: "⚡ 호스트 전기충격·소생 (repair)", template: "/defib" },
    { name: "/status", label: "상태 확인", desc: "챗봇 및 NAS 시스템 상태 점검", template: "/status" },
    { name: "/review", label: "관찰 리뷰", desc: "열린 관찰과 미검토 후보를 함께 검토 (작업 시작 아님)", template: "관찰 리뷰를 해줘. observation 도구의 review로 열린 관찰과 미검토 후보를 받아서 나와 하나씩 검토하고, 정리(resolve)와 티켓 제안까지만 해. 끝나면 reviewed로 기록해줘. 작업은 시작하지 마." },
    { name: "/ticket", label: "티켓 결정", desc: "/ticket go|approve|decline|reopen 번호 — 결정은 에이전트에게 안 가고, go는 승인 뒤 착수 요청", template: "/ticket " },
    { name: "/clear", label: "화면 비우기", desc: "대화창 화면 로그 초기화", template: "/clear" },
    { name: "/compact", label: "세션 압축", desc: "대화 히스토리 수동 압축/요약", template: "/compact" },
    { name: "/help", label: "사용법", desc: "탭·단축키·슬래시 명령어 요약", template: "/help" },
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
      if (Array.isArray(data.commands) && data.commands.length) slashCatalog.commands = data.commands;
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
  
  const cmds = slashCatalog.commands.filter(c => 
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
    html += '<div class="slash-category">⚡ 기능 / 명령어</div>';
    cmds.forEach(c => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(c);
      html += `<div class="slash-item" data-idx="${idx}" role="option" aria-selected="false">
        <span class="slash-badge cmd">명령어</span>
        <span class="slash-name">${escapeHtml(c.name)}</span>
        <span class="slash-desc">${escapeHtml(c.desc || c.label)}</span>
      </div>`;
    });
  }

  if (pops.length) {
    html += '<div class="slash-category">🛠️ 추천 스킬</div>';
    pops.forEach(p => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(p);
      html += `<div class="slash-item" data-idx="${idx}" role="option" aria-selected="false">
        <span class="slash-badge skill">스킬</span>
        <span class="slash-name">${escapeHtml(p.name)}</span>
        <span class="slash-desc">${escapeHtml(p.desc || p.label)}</span>
      </div>`;
    });
  }

  if (otherSkills.length) {
    html += '<div class="slash-category">📦 전체 스킬 검색</div>';
    otherSkills.forEach(s => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(s);
      html += `<div class="slash-item" data-idx="${idx}" role="option" aria-selected="false">
        <span class="slash-badge skill">스킬</span>
        <span class="slash-name">/skill ${escapeHtml(s.name)}</span>
        <span class="slash-desc">${escapeHtml(s.desc || s.name)}</span>
      </div>`;
    });
  }

  if (!slashVisibleItems.length) {
    html = '<div class="slash-empty">일치하는 명령어 또는 스킬이 없습니다냥 ฅ</div>';
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
  if (inputEl && !String(inputEl.value || '').startsWith('/') && !String(inputEl.value || '').trim()) {
    inputEl.value = '/';
    autoResizeInput();
    updateSendButton();
  }
  const val = (inputEl && inputEl.value) || '';
  const q = val.startsWith('/') ? val.slice(1) : '';
  renderSlashMenu(q);
  slashIgnoreDismissUntil = Date.now() + 450;
  if (inputEl) {
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
  inputEl.focus();
  inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
}

function handleSlashKeydown(e) {
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
