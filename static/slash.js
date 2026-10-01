/* Slash commands / skills menu — extracted from app.js (monolith-split Phase 2). */
// --- Slash Commands & Skills Autocomplete Engine ---
const slashMenuEl = document.getElementById('slashMenu');
const slashBtnEl = document.getElementById('slashBtn');
let slashCatalog = {
  commands: [
    { name: "/act", label: "행동 지문", desc: "말 대신 행동·상황 지문을 전달 (예: /act 차를 건넨다) — 별칭 /me", template: "/act " },
    { name: "/me", label: "행동 지문 (별칭)", desc: "/act 와 같음 (예: /me 기지개를 켠다)", template: "/me " },
    { name: "/btw", label: "샛길 질문", desc: "작업 중 즉시 경량 샛길 답변", template: "/btw " },
    { name: "/continue", label: "이어하기", desc: "현재 대화 요약 인계받아 새 세션", template: "/continue" },
    { name: "/new", label: "새 세션", desc: "완전한 새 대화 세션 시작", template: "/new" },
    { name: "/defib", label: "엔진 리부트", desc: "엔진 리부트 (repair/reboot)", template: "/defib" },
    { name: "/reboot", label: "엔진 리부트", desc: "/defib 와 같음 — 엔진 리부트 (repair/reboot)", template: "/defib" },   // l10n-ok
    { name: "/status", label: "상태 확인", desc: "챗봇 및 NAS 시스템 상태 점검", template: "/status" },
    { name: "/review", label: "관찰 리뷰", desc: "열린 관찰과 미검토 후보를 함께 검토 (작업 시작 아님)", template: "관찰 리뷰를 해줘. observation 도구의 review로 열린 관찰과 미검토 후보를 받아서 나와 하나씩 검토하고, 정리(resolve)와 티켓 제안까지만 해. 끝나면 reviewed로 기록해줘. 작업은 시작하지 마." },
    { name: "/ticket", label: "티켓 결정", desc: "/ticket <결정> 번호 — 화면에서 바로 처리, 에이전트에게는 안 감 (go만 착수 지시 전달)", template: "/ticket " },
    { name: "/ticket go", label: "티켓 착수", desc: "제안 상태면 승인한 뒤 에이전트에게 착수 지시 (예: /ticket go 152)", template: "/ticket go " },
    { name: "/ticket approve", label: "티켓 승인", desc: "제안된 작업 승인만 (착수는 안 함)", template: "/ticket approve " },
    { name: "/ticket decline", label: "티켓 폐기", desc: "제안된 작업 폐기 (진행 안 함)", template: "/ticket decline " },
    { name: "/ticket reopen", label: "티켓 재개", desc: "폐기·완료된 작업 다시 열기", template: "/ticket reopen " },
    { name: "/ticket delegate", label: "위임 실행", desc: "PD 계획의 [실행] — 스태프 작업 시작 (격리 워크트리)", template: "/ticket delegate " },
    { name: "/ticket merge", label: "위임 승인", desc: "검증 통과한 위임 결과 승인 → 반영 시작", template: "/ticket merge " },
    { name: "/ticket rework", label: "위임 반려", desc: "위임 결과 반려 + 사유 (예: /ticket rework 152 버튼 크기 다시)", template: "/ticket rework " },
    { name: "/ticket discard", label: "위임 폐기", desc: "위임 결과 버리기", template: "/ticket discard " },
    { name: "/ticket disown", label: "담당 해제", desc: "다른 에이전트가 잡은 작업을 넘겨받게 담당 해제", template: "/ticket disown " },
    { name: "/ticket unqueue", label: "대기 취소", desc: "잠금 대기 중인 위임 실행 취소", template: "/ticket unqueue " },
    { name: "/ticket allow", label: "경로 허용", desc: "스태프가 요청한 범위 밖 경로(NEED_PATH) 허용", template: "/ticket allow " },
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
    html += '<div class="slash-category">기능 / 명령어</div>';
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
    html += '<div class="slash-category">추천 스킬</div>';
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
    html += '<div class="slash-category">전체 스킬 검색</div>';
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
    html = '<div class="slash-empty">일치하는 명령어 또는 스킬이 없습니다</div>';
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
