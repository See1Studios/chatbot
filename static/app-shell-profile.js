// Profile: Companion Profile Screen (Redesign UX/S2)
// 3 Tabs Architecture:
// Tab 1: 'character' - Base persona & card settings
// Tab 2: 'relationship' - Accumulated continuity
// Tab 3: 'engine' - Engineering system controls
// Master Image with Face Coordinate Crop & Inline Editor

let shellProfileTab = 'character'; // 'character' | 'relationship' | 'engine'

// Unified SVG vector icons (theme-matched, replacing system emojis)
function profileIconSvg(name) {
  const icons = {
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    bond: '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    edit: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    mic: '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>',
    target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/>',
    close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
  };
  const body = icons[name] || '';
  return `<svg viewBox="0 0 24 24" class="btn-icon-svg shell-svg-${name}" aria-hidden="true">${body}</svg>`;
}

// Non-blocking toast notification helper
function profileToast(text) {
  if (typeof msgToast === 'function') {
    msgToast(text);
    return;
  }
  let t = document.getElementById('shellToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'shellToast';
    t.className = 'shell-toast';
    t.setAttribute('role', 'status');
    document.body.appendChild(t);
  }
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2000);
}

// Resolve master character artwork (distinct from background/stage wallpaper)
function getMasterArtworkUrl(c) {
  if (c && c.focal && c.focal.master) return c.focal.master;
  if (typeof characterOwnPortrait === 'function') {
    return characterOwnPortrait(c);
  }
  return '';
}

// Normalized focal crop object: { x: 50, y: 25, zoom: 1, master: '' }
function getCharacterFocal(c) {
  const f = (c && c.focal && typeof c.focal === 'object') ? c.focal : {};
  const x = Number(f.x !== undefined ? f.x : 50);
  const y = Number(f.y !== undefined ? f.y : 25);
  const zoom = Math.max(1, Math.min(3, Number(f.zoom !== undefined ? f.zoom : 1)));
  return {
    x: isNaN(x) ? 50 : Math.max(0, Math.min(100, x)),
    y: isNaN(y) ? 25 : Math.max(0, Math.min(100, y)),
    zoom: isNaN(zoom) ? 1 : zoom,
    master: f.master || ''
  };
}

function shellProfileDraw(panel, c, column) {
  if (!panel || !c) return;
  panel.textContent = '';

  // 1. Panel Header (Back / Close)
  const headTitle = typeof tr === 'function' ? tr('shelltext.profile') : 'Profile';
  const head = shellPanelHead(
    headTitle,
    shellProfileClose,
    typeof shellNarrow === 'function' && shellNarrow() ? '\u2039' : '\u2715'
  );

  // 2. Hero Section
  // Background cover strictly uses stage scene background (or neutral dark styling), NOT the character master image
  const hero = shellEl('div', 'shell-hero');
  const cover = shellEl('div', 'shell-hero-cover');
  if (c.stage_v && typeof BASE_PATH !== 'undefined') {
    const stageUrl = BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v;
    cover.style.backgroundImage = 'url("' + stageUrl + '")';
    cover.classList.add('has-stage');
  }
  const coverBtn = shellEl('button', 'shell-hero-cover-btn');
  coverBtn.type = 'button';
  coverBtn.innerHTML = profileIconSvg('target') + ' <span>' + (typeof tr === 'function' ? (tr('profile.cover.edit') || 'Cover') : 'Cover') + '</span>';
  coverBtn.title = typeof tr === 'function' ? (tr('profile.cover.edit') || 'Edit Cover Banner') : 'Edit Cover Banner';
  coverBtn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    openFocalEditor(panel, c, { mode: 'cover' });
  });
  cover.appendChild(coverBtn);

  // Hero Card with Focal Cropped Avatar (Compact HUD layout)
  const heroCard = shellEl('div', 'shell-hero-card');
  const avatarWrap = shellEl('div', 'shell-hero-avatar-wrap');

  const avatarClip = shellEl('div', 'shell-hero-avatar-clip');
  avatarClip.addEventListener('click', () => {
    openFocalEditor(panel, c, { mode: 'avatar' });
  });
  const img = document.createElement('img');
  img.className = 'shell-hero-avatar';
  img.alt = '';
  img.onerror = () => {
    img.onerror = null;
    img.src = typeof initialAvatar === 'function' ? initialAvatar(c.name || c.title) : '';
  };

  // Focal coordinates applied to avatar
  const focal = getCharacterFocal(c);
  img.style.objectPosition = `${focal.x}% ${focal.y}%`;
  img.style.transform = `scale(${focal.zoom})`;
  img.style.transformOrigin = `${focal.x}% ${focal.y}%`;
  img.src = focal.master || (typeof characterOwnPortrait === 'function' ? characterOwnPortrait(c) : '');

  avatarClip.appendChild(img);

  // Presence Status Dot
  const presenceDot = shellEl('span', 'shell-hero-dot ' + (typeof isBusy !== 'undefined' && isBusy ? 'busy' : 'online'));

  // Quick focal target button on avatar corner (sole entry point for focal crop)
  const focalBtn = shellEl('button', 'shell-hero-focal-btn');
  focalBtn.type = 'button';
  focalBtn.title = typeof tr === 'function' ? tr('profile.sec.focal') : 'Edit Face Focus';
  focalBtn.setAttribute('aria-label', 'Edit Face Crop');
  focalBtn.innerHTML = profileIconSvg('target');
  focalBtn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    openFocalEditor(panel, c, { mode: 'avatar' });
  });

  avatarWrap.append(avatarClip, presenceDot, focalBtn);

  const titleWrap = shellEl('div', 'shell-hero-info');
  const nameEl = shellEl('div', 'shell-hero-name', c.title || c.name || '');

  const badgeWrap = shellEl('div', 'shell-hero-badges');
  if (c.role) {
    badgeWrap.appendChild(shellEl('span', 'shell-hero-role-badge', c.role));
  }
  if (c.user_title) {
    const utChip = shellEl('span', 'shell-hero-usertitle-chip');
    utChip.innerHTML = profileIconSvg('message') + ' ' + escapeHtml(c.user_title);
    utChip.title = typeof tr === 'function' ? tr('card.user_title') : 'User Title';
    badgeWrap.appendChild(utChip);
  }
  if (c.voice) {
    const voiceChip = shellEl('span', 'shell-hero-voice-chip');
    voiceChip.innerHTML = profileIconSvg('mic') + ' ' + escapeHtml(c.voice);
    badgeWrap.appendChild(voiceChip);
  }
  const presenceChip = shellEl(
    'span',
    'shell-hero-presence',
    typeof shellPresenceText === 'function' && typeof sessionMode !== 'undefined'
      ? shellPresenceText(sessionMode, typeof isBusy !== 'undefined' && isBusy)
      : ''
  );
  badgeWrap.appendChild(presenceChip);

  titleWrap.append(nameEl, badgeWrap);
  heroCard.append(avatarWrap, titleWrap);

  // Persona Tags (sanitized prefix)
  const tags = Array.isArray(c.tags) ? c.tags.filter(Boolean) : [];
  if (tags.length) {
    const tagsEl = shellEl('div', 'shell-hero-tags');
    tags.slice(0, 6).forEach(tag => {
      tagsEl.appendChild(shellEl('span', 'shell-hero-tag', '#' + String(tag).replace(/^#+/, '')));
    });
    hero.append(cover, heroCard, tagsEl);
  } else {
    hero.append(cover, heroCard);
  }

  // 3. Segmented 3-Tab Control: character / relationship / settings
  const tabNav = shellEl('div', 'shell-profile-nav shell-profile-nav-3');
  tabNav.setAttribute('role', 'tablist');

  const tabCharLabel = typeof tr === 'function' ? tr('profile.tab.character') : 'Character';
  const tabCharBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'character' ? ' active' : ''));
  tabCharBtn.type = 'button';
  tabCharBtn.setAttribute('role', 'tab');
  tabCharBtn.setAttribute('aria-selected', shellProfileTab === 'character' ? 'true' : 'false');
  tabCharBtn.innerHTML = profileIconSvg('user') + ' ' + escapeHtml(tabCharLabel);

  const tabRelLabel = typeof tr === 'function' ? tr('profile.tab.relationship') : 'Relationship';
  const tabRelBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'relationship' ? ' active' : ''));
  tabRelBtn.type = 'button';
  tabRelBtn.setAttribute('role', 'tab');
  tabRelBtn.setAttribute('aria-selected', shellProfileTab === 'relationship' ? 'true' : 'false');
  tabRelBtn.innerHTML = profileIconSvg('bond') + ' ' + escapeHtml(tabRelLabel);

  const tabEngLabel = typeof tr === 'function' ? tr('profile.tab.settings') : 'Settings';
  const tabEngBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'engine' ? ' active' : ''));
  tabEngBtn.type = 'button';
  tabEngBtn.setAttribute('role', 'tab');
  tabEngBtn.setAttribute('aria-selected', shellProfileTab === 'engine' ? 'true' : 'false');
  tabEngBtn.innerHTML = profileIconSvg('settings') + ' ' + escapeHtml(tabEngLabel);

  tabNav.append(tabCharBtn, tabRelBtn, tabEngBtn);

  // 4. Tab 1: Character
  const charBody = shellEl('div', 'shell-tab-body shell-body-character' + (shellProfileTab === 'character' ? ' active' : ''));
  renderCharacterTab(charBody, c, panel, column);

  // 5. Tab 2: Relationship & Memory
  const relBody = shellEl('div', 'shell-tab-body shell-body-relationship' + (shellProfileTab === 'relationship' ? ' active' : ''));
  renderRelationshipTab(relBody, c);

  // 6. Tab 3: Engine & Settings
  const engBody = shellEl('div', 'shell-tab-body shell-body-engine' + (shellProfileTab === 'engine' ? ' active' : ''));
  renderEngineTab(engBody, c);

  // Non-destructive tab switching: toggle active class and ARIA state instantly
  const setTab = (t) => {
    shellProfileTab = t;
    tabCharBtn.classList.toggle('active', t === 'character');
    tabCharBtn.setAttribute('aria-selected', t === 'character' ? 'true' : 'false');
    tabRelBtn.classList.toggle('active', t === 'relationship');
    tabRelBtn.setAttribute('aria-selected', t === 'relationship' ? 'true' : 'false');
    tabEngBtn.classList.toggle('active', t === 'engine');
    tabEngBtn.setAttribute('aria-selected', t === 'engine' ? 'true' : 'false');
    charBody.classList.toggle('active', t === 'character');
    relBody.classList.toggle('active', t === 'relationship');
    engBody.classList.toggle('active', t === 'engine');
  };
  tabCharBtn.addEventListener('click', () => setTab('character'));
  tabRelBtn.addEventListener('click', () => setTab('relationship'));
  tabEngBtn.addEventListener('click', () => setTab('engine'));

  panel.append(head, hero, tabNav, charBody, relBody, engBody);
}

// ------------------------------------------------------------------ Tab 1: Character
function renderCharacterTab(holder, c, panel, column) {
  if (!holder || !c) return;
  holder.textContent = '';

  // character-settings cs/C: every card and display setting, drawn from the server's list and saved key by key
  const refresh = async () => {
    if (typeof loadCharacters === 'function') await loadCharacters();
    if (typeof updateBrandAvatar === 'function') updateBrandAvatar();
  };
  const sec = shellSettingsSection(c, 'character', tr('profile.sec.card'), refresh);
  holder.appendChild(sec);

  // Expression & Stage Gallery Mini-Strip
  const artSecTitle = typeof tr === 'function' ? tr('profile.sec.visuals') : 'Visuals & Expressions';
  const artSec = shellSection(artSecTitle);
  const artStrip = shellEl('div', 'shell-art-strip');
  artStrip.appendChild(shellEl('div', 'status-hint', typeof tr === 'function' ? tr('common.loading') : 'Loading...'));
  artSec.appendChild(artStrip);
  holder.appendChild(artSec);
  loadArtMiniStrip(c.id, artStrip, panel, c);
}

// ------------------------------------------------------------------ Tab 2: Relationship & Memory
function renderRelationshipTab(holder, c) {
  if (!holder || !c) return;
  holder.textContent = '';
  // 1. Relationship facts
  if (typeof shellRelationSection === 'function') {
    const relSec = shellRelationSection(c);
    if (relSec) holder.appendChild(relSec);
  }

  // 2. Memory, private memory (folded), the private room's settings: from the settings list (cs/C)
  holder.appendChild(shellSettingsSection(c, 'relationship', tr('profile.sec.pe')));   // what PE adds and keeps

  // 3. Quick Action Cards
  const rows = typeof shellProfileRows === 'function' ? shellProfileRows({
    art: false,
    manage: false
  }) : [];

  if (rows.length) {
    const mediaTitle = typeof tr === 'function' ? (tr('profile.section.media') || 'Records & Files') : 'Records & Files';
    const actionSec = shellSection(mediaTitle);
    const actionGrid = shellEl('div', 'shell-action-grid');
    rows.forEach(row => {
      const btn = shellEl('button', 'shell-action-card');
      btn.type = 'button';
      btn.setAttribute('data-k', row.k);
      const icon = typeof shellRowIcon === 'function' ? shellRowIcon(row.k) : null;
      const iconWrap = shellEl('div', 'shell-action-icon');
      if (icon) iconWrap.appendChild(icon);
      const label = shellEl('div', 'shell-action-label', row.label);
      btn.append(iconWrap, label);
      btn.addEventListener('click', () => {
        if (typeof SHELL_PANES !== 'undefined' && SHELL_PANES[row.k]) return shellGoPane(row.k, 'profile');
      });
      actionGrid.appendChild(btn);
    });
    actionSec.appendChild(actionGrid);
    holder.appendChild(actionSec);
  }
}

// ------------------------------------------------------------------ Tab 3: Engine
function renderEngineTab(holder, c) {
  if (!holder || !c) return;
  holder.textContent = '';
  if (typeof shellQuotaSection === 'function') holder.appendChild(shellQuotaSection());
  if (typeof shellBrainSection === 'function') holder.appendChild(shellBrainSection(c));
  if (typeof shellModelSection === 'function') holder.appendChild(shellModelSection());
  if (typeof shellContextSection === 'function') holder.appendChild(shellContextSection());
  if (typeof shellBrainUseSection === 'function') holder.appendChild(shellBrainUseSection(c));
  holder.appendChild(shellSettingsSection(c, 'settings', tr('profile.sec.system')));   // the mechanics: roles
  if (typeof shellDevDeleteButton === 'function') shellDevDeleteButton(holder, c);
}

// ------------------------------------------------------------------ Visual Focal Cropper & Master Editor
async function openFocalEditor(panel, c, opts = {}) {
  if (!panel || !c) return;
  const existing = panel.querySelector('.shell-focal-dialog');
  if (existing) existing.remove();

  const dialog = shellEl('div', 'shell-focal-dialog');
  const focal = getCharacterFocal(c);
  let mode = (opts && opts.mode === 'cover') ? 'cover' : 'avatar';
  let curX = focal.x;
  let curY = focal.y;
  let curZoom = focal.zoom;
  const defaultAvatarUrl = typeof characterOwnPortrait === 'function' ? characterOwnPortrait(c) : '';
  let curMaster = (opts && opts.master) || (mode === 'cover' && c.stage_v && typeof BASE_PATH !== 'undefined'
    ? BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v
    : focal.master) || defaultAvatarUrl || getMasterArtworkUrl(c);

  // 1. Dialog Header with Avatar / Cover Mode Switcher
  const head = shellEl('div', 'shell-focal-head');
  const title = shellEl('div', 'shell-focal-title');

  const tabs = shellEl('div', 'shell-focal-tabs');
  const tabAvatar = shellEl('button', 'shell-focal-tab' + (mode === 'avatar' ? ' active' : ''));
  tabAvatar.type = 'button';
  tabAvatar.textContent = typeof tr === 'function' ? (tr('profile.mode.avatar') || 'Avatar') : 'Avatar';

  const tabCover = shellEl('button', 'shell-focal-tab' + (mode === 'cover' ? ' active' : ''));
  tabCover.type = 'button';
  tabCover.textContent = typeof tr === 'function' ? (tr('profile.mode.cover') || 'Cover') : 'Cover';
  tabs.append(tabAvatar, tabCover);

  const updateTitle = () => {
    const lbl = mode === 'avatar'
      ? (typeof tr === 'function' ? tr('profile.sec.focal') : 'Edit Profile Face')
      : (typeof tr === 'function' ? (tr('profile.sec.cover') || 'Edit Cover Banner') : 'Edit Cover Banner');
    title.innerHTML = profileIconSvg('target') + ' <span>' + escapeHtml(lbl) + '</span>';
  };
  updateTitle();

  const closeDialog = () => {
    window.removeEventListener('keydown', onKeyDown, true);
    dialog.remove();
  };
  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      e.preventDefault();
      closeDialog();
    }
  };
  window.addEventListener('keydown', onKeyDown, true);

  const closeBtn = shellEl('button', 'art-btn art-btn-xs');
  closeBtn.type = 'button';
  closeBtn.innerHTML = profileIconSvg('close');
  closeBtn.title = typeof tr === 'function' ? tr('common.close') : 'Close';
  closeBtn.addEventListener('click', closeDialog);
  head.append(title, tabs, closeBtn);

  // 2. Interactive Direct Manipulation Stage
  const stage = shellEl('div', 'shell-focal-stage');
  const img = document.createElement('img');
  img.className = 'shell-focal-img';
  img.src = curMaster;
  img.draggable = false;

  const mask = shellEl('div', 'shell-focal-mask ' + (mode === 'avatar' ? 'mask-circle' : 'mask-rect'));
  const reticle = shellEl('div', 'shell-focal-reticle');
  mask.appendChild(reticle);
  stage.append(img, mask);

  const updateLayout = () => {
    const stageW = stage.clientWidth || 280;
    const stageH = stage.clientHeight || 220;
    const stageCenterX = stageW / 2;
    const stageCenterY = stageH / 2;

    const maskW = mode === 'avatar' ? 160 : 260;
    const maskH = mode === 'avatar' ? 160 : 96;
    mask.className = 'shell-focal-mask ' + (mode === 'avatar' ? 'mask-circle' : 'mask-rect');

    const natW = img.naturalWidth || 400;
    const natH = img.naturalHeight || 400;

    const baseScale = Math.max(maskW / natW, maskH / natH);
    const baseW = natW * baseScale;
    const baseH = natH * baseScale;

    const renderW = baseW * curZoom;
    const renderH = baseH * curZoom;

    let focalX = renderW * (curX / 100);
    let focalY = renderH * (curY / 100);

    const minFocalX = maskW / 2;
    const maxFocalX = Math.max(minFocalX, renderW - maskW / 2);
    const minFocalY = maskH / 2;
    const maxFocalY = Math.max(minFocalY, renderH - maskH / 2);

    focalX = Math.max(minFocalX, Math.min(maxFocalX, focalX));
    focalY = Math.max(minFocalY, Math.min(maxFocalY, focalY));

    curX = renderW > 0 ? (focalX / renderW) * 100 : 50;
    curY = renderH > 0 ? (focalY / renderH) * 100 : 50;

    img.style.width = `${renderW}px`;
    img.style.height = `${renderH}px`;
    img.style.left = `${stageCenterX - focalX}px`;
    img.style.top = `${stageCenterY - focalY}px`;

    if (zoomVal) zoomVal.textContent = `${curZoom.toFixed(1)}x`;
    if (zoomSlider) zoomSlider.value = String(Math.round(curZoom * 10));
  };
  img.onload = updateLayout;

  // Pointer drag and pinch gestures
  const pointers = new Map();
  let lastPinchDist = 0;

  stage.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    try { stage.setPointerCapture(e.pointerId); } catch (_) {}
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1) {
      stage.classList.add('is-dragging');
    } else if (pointers.size === 2) {
      const pts = Array.from(pointers.values());
      lastPinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    }
  });

  stage.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    const prev = pointers.get(e.pointerId);
    const dx = e.clientX - prev.x;
    const dy = e.clientY - prev.y;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (pointers.size === 2) {
      const pts = Array.from(pointers.values());
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (lastPinchDist > 0) {
        const factor = dist / lastPinchDist;
        curZoom = Math.max(1, Math.min(3.5, curZoom * factor));
        updateLayout();
      }
      lastPinchDist = dist;
      return;
    }

    if (pointers.size === 1) {
      const natW = img.naturalWidth || 400;
      const natH = img.naturalHeight || 400;
      const maskW = mode === 'avatar' ? 160 : 260;
      const maskH = mode === 'avatar' ? 160 : 96;
      const baseScale = Math.max(maskW / natW, maskH / natH);
      const rW = natW * baseScale * curZoom;
      const rH = natH * baseScale * curZoom;
      if (rW > 0) curX = Math.max(0, Math.min(100, curX - (dx / rW) * 100));
      if (rH > 0) curY = Math.max(0, Math.min(100, curY - (dy / rH) * 100));
      updateLayout();
    }
  });

  const onPointerEnd = (e) => {
    pointers.delete(e.pointerId);
    try { stage.releasePointerCapture(e.pointerId); } catch (_) {}
    if (pointers.size === 0) {
      stage.classList.remove('is-dragging');
    } else if (pointers.size === 1) {
      lastPinchDist = 0;
    }
  };
  stage.addEventListener('pointerup', onPointerEnd);
  stage.addEventListener('pointercancel', onPointerEnd);

  // Smooth wheel zoom
  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = -e.deltaY * 0.0015;
    curZoom = Math.max(1, Math.min(3.5, curZoom + delta));
    updateLayout();
  }, { passive: false });

  // Double-click toggle zoom / reset
  stage.addEventListener('dblclick', (e) => {
    e.preventDefault();
    curZoom = curZoom > 1.08 ? 1.0 : 2.0;
    curX = 50;
    curY = 50;
    updateLayout();
  });

  tabAvatar.addEventListener('click', () => {
    if (mode === 'avatar') return;
    mode = 'avatar';
    tabAvatar.classList.add('active');
    tabCover.classList.remove('active');
    updateTitle();
    updateLayout();
  });
  tabCover.addEventListener('click', () => {
    if (mode === 'cover') return;
    mode = 'cover';
    tabCover.classList.add('active');
    tabAvatar.classList.remove('active');
    updateTitle();
    updateLayout();
  });

  // 3. User Hint & Sleek Zoom Bar
  const hint = shellEl('div', 'shell-focal-hint',
    typeof tr === 'function' ? (tr('profile.focal.hint') || 'Drag to move · Scroll or pinch to zoom') : 'Drag to reposition · Scroll or pinch to zoom');

  const zoomBar = shellEl('div', 'shell-focal-zoom-bar');
  const zoomOutBtn = shellEl('button', 'art-btn art-btn-xs', '−');
  zoomOutBtn.type = 'button';
  zoomOutBtn.title = 'Zoom out';
  zoomOutBtn.addEventListener('click', () => {
    curZoom = Math.max(1, curZoom - 0.2);
    updateLayout();
  });

  const zoomSlider = document.createElement('input');
  zoomSlider.type = 'range';
  zoomSlider.min = '10';
  zoomSlider.max = '35';
  zoomSlider.value = String(Math.round(curZoom * 10));
  zoomSlider.setAttribute('aria-label', 'Zoom');
  zoomSlider.addEventListener('input', () => {
    curZoom = Number(zoomSlider.value) / 10;
    updateLayout();
  });

  const zoomInBtn = shellEl('button', 'art-btn art-btn-xs', '+');
  zoomInBtn.type = 'button';
  zoomInBtn.title = 'Zoom in';
  zoomInBtn.addEventListener('click', () => {
    curZoom = Math.min(3.5, curZoom + 0.2);
    updateLayout();
  });

  const zoomVal = shellEl('span', 'shell-focal-zoom-val', `${curZoom.toFixed(1)}x`);

  const resetBtn = shellEl('button', 'art-btn art-btn-xs', typeof tr === 'function' ? (tr('profile.focal.reset') || 'Reset') : 'Reset');
  resetBtn.type = 'button';
  resetBtn.title = 'Reset focus & zoom';
  resetBtn.addEventListener('click', () => {
    curZoom = 1.0;
    curX = 50;
    curY = 50;
    updateLayout();
  });
  zoomBar.append(zoomOutBtn, zoomSlider, zoomInBtn, zoomVal, resetBtn);

  // 4. Source Selector & Upload
  const srcSecTitle = typeof tr === 'function' ? tr('profile.sec.master_source') : 'Master Image Source';
  const srcSec = shellSection(srcSecTitle);
  const srcPills = shellEl('div', 'shell-focal-sources');

  const setMasterUrl = (url) => {
    curMaster = url;
    img.src = curMaster;
    curZoom = 1.0;
    curX = 50;
    curY = 50;
    updateLayout();
  };

  const addSourceChip = (name, url, isUpload = false) => {
    if (!url && !isUpload) return;
    const chip = shellEl('button', 'shell-focal-source-chip' + (curMaster === url ? ' active' : '') + (isUpload ? ' upload' : ''));
    chip.type = 'button';
    chip.textContent = name;
    chip.addEventListener('click', () => {
      srcPills.querySelectorAll('.shell-focal-source-chip').forEach(el => el.classList.remove('active'));
      chip.classList.add('active');
      setMasterUrl(url);
    });
    srcPills.appendChild(chip);
  };

  const uploadLabel = shellEl('label', 'shell-focal-source-chip upload');
  const uploadInput = document.createElement('input');
  uploadInput.type = 'file';
  uploadInput.accept = 'image/*';
  uploadInput.style.display = 'none';
  uploadLabel.textContent = typeof tr === 'function' ? (tr('profile.upload') || '+ Upload Photo') : '+ Upload Photo';
  uploadLabel.appendChild(uploadInput);

  uploadInput.addEventListener('change', async () => {
    const file = uploadInput.files && uploadInput.files[0];
    if (!file) return;
    uploadLabel.textContent = typeof tr === 'function' ? tr('common.saving') : 'Uploading...';
    try {
      const upRes = await fetch((typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/characters/' + encodeURIComponent(c.id) + '/art/upload', {
        method: 'POST',
        headers: { 'X-File-Name': file.name },
        body: file
      });
      const upData = await upRes.json();
      if (upData && upData.file) {
        const newUrl = (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/characters/' + encodeURIComponent(c.id) + '/gallery/' + encodeURIComponent(upData.file);
        addSourceChip(file.name.slice(0, 12), newUrl);
        setMasterUrl(newUrl);
      }
    } catch (err) {
      profileToast(err.message || 'Upload failed');
    } finally {
      uploadLabel.textContent = typeof tr === 'function' ? (tr('profile.upload') || '+ Upload Photo') : '+ Upload Photo';
      uploadInput.value = '';
    }
  });

  srcPills.appendChild(uploadLabel);
  addSourceChip(typeof tr === 'function' ? (tr('profile.mode.avatar') || 'Avatar') : 'Avatar', defaultAvatarUrl);

  if (c.stage_v && typeof BASE_PATH !== 'undefined') {
    const stageUrl = BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v;
    addSourceChip(typeof tr === 'function' ? (tr('profile.mode.cover') || 'Stage') : 'Stage', stageUrl);
  }

  try {
    const artRes = await api('/api/characters/' + encodeURIComponent(c.id) + '/art');
    if (artRes && artRes.slots) {
      Object.keys(artRes.slots).forEach(k => {
        const s = artRes.slots[k];
        if (s && s.url) addSourceChip(s.label || k, s.url);
      });
    }
    if (artRes && Array.isArray(artRes.gallery)) {
      artRes.gallery.slice(0, 8).forEach(g => {
        if (g && g.url) addSourceChip(g.file || 'gallery', g.url);
      });
    }
  } catch (_) {}

  srcSec.appendChild(srcPills);

  // 5. Actions (Cancel & Save)
  const actRow = shellEl('div', 'shell-edit-actions');
  const cancelBtn = shellEl('button', 'art-btn art-btn-sm');
  cancelBtn.type = 'button';
  cancelBtn.textContent = typeof tr === 'function' ? tr('common.cancel') : 'Cancel';
  cancelBtn.addEventListener('click', closeDialog);

  const saveBtn = shellEl('button', 'art-btn art-btn-sm primary');
  saveBtn.type = 'button';
  const saveLabel = typeof tr === 'function' ? (tr('profile.focal.save') || 'Save Focus') : 'Save Focus';
  saveBtn.innerHTML = profileIconSvg('check') + ' <span>' + escapeHtml(saveLabel) + '</span>';

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = typeof tr === 'function' ? tr('common.saving') : 'Saving...';
    try {
      if (mode === 'cover') {
        let assigned = false;
        if (typeof document !== 'undefined' && typeof document.createElement === 'function') {
          try {
            const canvas = document.createElement('canvas');
            canvas.width = 960;
            canvas.height = 360;
            const ctx = canvas.getContext ? canvas.getContext('2d') : null;
            if (ctx && img.naturalWidth && img.naturalHeight) {
              const natW = img.naturalWidth;
              const natH = img.naturalHeight;
              const maskW = 260, maskH = 96;
              const baseScale = Math.max(maskW / natW, maskH / natH);
              const rW = natW * baseScale * curZoom;
              const rH = natH * baseScale * curZoom;
              const focalX = rW * (curX / 100);
              const focalY = rH * (curY / 100);
              const cropW = (maskW / rW) * natW;
              const cropH = (maskH / rH) * natH;
              const cropX = Math.max(0, Math.min(natW - cropW, (focalX / rW) * natW - cropW / 2));
              const cropY = Math.max(0, Math.min(natH - cropH, (focalY / rH) * natH - cropH / 2));
              ctx.drawImage(img, cropX, cropY, cropW, cropH, 0, 0, canvas.width, canvas.height);
              if (typeof canvas.toBlob === 'function') {
                const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/webp', 0.9));
                if (blob) {
                  const fname = `stage_${Date.now()}.webp`;
                  const upRes = await fetch((typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/characters/' + encodeURIComponent(c.id) + '/art/upload', {
                    method: 'POST',
                    headers: { 'X-File-Name': fname },
                    body: blob
                  });
                  const upData = await upRes.json();
                  if (upData && upData.file) {
                    await api('/api/characters/' + encodeURIComponent(c.id) + '/art/assign', {
                      method: 'POST',
                      body: JSON.stringify({ from: upData.file, kind: 'background' })
                    });
                    assigned = true;
                  }
                }
              }
            }
          } catch (_) {}
        }
        if (!assigned && curMaster) {
          const m = curMaster.match(/\/gallery\/([^?]+)/);
          if (m) {
            await api('/api/characters/' + encodeURIComponent(c.id) + '/art/assign', {
              method: 'POST',
              body: JSON.stringify({ from: decodeURIComponent(m[1]), kind: 'background' })
            });
          }
        }
        c.stage_v = Date.now();
      } else {
        const focalObj = {
          x: Number(curX.toFixed(1)),
          y: Number(curY.toFixed(1)),
          zoom: Number(curZoom.toFixed(2)),
          master: curMaster === defaultAvatarUrl ? '' : curMaster
        };
        const res = await shellSettingsPatch(c.id, { 'display.focal': focalObj });
        if (res && res.errors && res.errors['display.focal']) throw new Error(res.errors['display.focal']);
        c.focal = focalObj;
      }

      if (typeof loadCharacters === 'function') await loadCharacters();
      closeDialog();
      const updated = typeof currentCharacter === 'function' ? currentCharacter() : c;
      shellProfileDraw(panel, updated || c);
    } catch (err) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = profileIconSvg('check') + ' <span>' + escapeHtml(saveLabel) + '</span>';
      profileToast(tr('card.cannot_save', { error: err.message || err }));
    }
  });

  actRow.append(cancelBtn, saveBtn);
  dialog.append(head, stage, hint, zoomBar, srcSec, actRow);
  panel.appendChild(dialog);
  updateLayout();
}
// Mini art gallery strip for character expressions & stage
async function loadArtMiniStrip(cid, stripEl, panel, c) {
  try {
    const res = await api('/api/characters/' + encodeURIComponent(cid) + '/art');
    stripEl.textContent = '';
    const slots = (res && res.slots) || {};
    const gallery = (res && res.gallery) || [];
    const items = [];

    // Collect available slots and gallery files
    Object.keys(slots).forEach(k => {
      const s = slots[k];
      if (s && s.url) items.push({ title: s.label || k, url: s.url });
    });
    gallery.slice(0, 8).forEach(g => {
      if (g && g.url && !items.find(it => it.url === g.url)) {
        items.push({ title: g.file || 'gallery', url: g.url });
      }
    });

    if (!items.length) {
      stripEl.appendChild(shellEl('div', 'status-hint', 'No visuals registered yet.'));
      return;
    }

    const scrollBox = shellEl('div', 'shell-art-carousel');
    items.forEach(it => {
      const card = shellEl('div', 'shell-art-thumb-card');
      const pic = document.createElement('img');
      pic.src = it.url;
      pic.alt = it.title;
      pic.className = 'shell-art-thumb';
      const cap = shellEl('span', 'shell-art-thumb-caption', it.title);
      card.append(pic, cap);

      card.title = 'Set focal crop';
      card.addEventListener('click', () => {
        if (panel && c) {
          openFocalEditor(panel, Object.assign({}, c, {
            focal: Object.assign({}, getCharacterFocal(c), { master: it.url })
          }));
        }
      });
      scrollBox.appendChild(card);
    });
    stripEl.appendChild(scrollBox);
  } catch (_) {
    stripEl.textContent = '';
    stripEl.appendChild(shellEl('div', 'status-hint', 'Could not load visuals.'));
  }
}
