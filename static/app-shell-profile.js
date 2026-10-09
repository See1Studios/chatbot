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

  // Hero Card with Focal Cropped Avatar (Compact HUD layout)
  const heroCard = shellEl('div', 'shell-hero-card');
  const avatarWrap = shellEl('div', 'shell-hero-avatar-wrap');

  const avatarClip = shellEl('div', 'shell-hero-avatar-clip');
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
    openFocalEditor(panel, c);
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
async function openFocalEditor(panel, c) {
  if (!panel || !c) return;
  const existing = panel.querySelector('.shell-focal-dialog');
  if (existing) existing.remove();

  const dialog = shellEl('div', 'shell-focal-dialog');
  const focal = getCharacterFocal(c);
  let curX = focal.x;
  let curY = focal.y;
  let curZoom = focal.zoom;
  let curMaster = focal.master || getMasterArtworkUrl(c);

  // 1. Dialog Header
  const head = shellEl('div', 'shell-focal-head');
  const title = shellEl('div', 'shell-focal-title');
  const titleLabel = typeof tr === 'function' ? tr('profile.sec.focal') : 'Edit Face Focus';
  title.innerHTML = profileIconSvg('target') + ' <span>' + escapeHtml(titleLabel) + '</span>';
  // Safe dialog cleanup
  const closeDialog = () => {
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
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
  head.append(title, closeBtn);

  // 2. Interactive Canvas Wrap
  const canvasWrap = shellEl('div', 'shell-focal-canvas-wrap');
  const canvasImg = document.createElement('img');
  canvasImg.className = 'shell-focal-canvas-img';
  canvasImg.src = curMaster;

  const reticle = shellEl('div', 'shell-focal-reticle');
  canvasWrap.append(canvasImg, reticle);

  // Update reticle position on canvas (accounting for image letterbox offset)
  const updateReticle = () => {
    const wrapRect = canvasWrap.getBoundingClientRect();
    const imgRect = canvasImg.getBoundingClientRect();
    if (wrapRect.width && imgRect.width) {
      const offsetX = (imgRect.left - wrapRect.left) + (imgRect.width * (curX / 100));
      const offsetY = (imgRect.top - wrapRect.top) + (imgRect.height * (curY / 100));
      reticle.style.left = `${offsetX}px`;
      reticle.style.top = `${offsetY}px`;
    } else {
      reticle.style.left = `${curX}%`;
      reticle.style.top = `${curY}%`;
    }
    const rSize = Math.max(28, Math.min(80, Math.round(54 / curZoom)));
    reticle.style.width = `${rSize}px`;
    reticle.style.height = `${rSize}px`;
    updatePreviewAvatar();
  };
  canvasImg.onload = updateReticle;

  // Canvas Click & Drag to reposition focal coordinates
  let isTargeting = false;
  const setPosFromPointer = (e) => {
    const rect = canvasImg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const px = Math.max(0, Math.min(100, Math.round(((e.clientX - rect.left) / rect.width) * 100)));
    const py = Math.max(0, Math.min(100, Math.round(((e.clientY - rect.top) / rect.height) * 100)));
    curX = px;
    curY = py;
    sliderX.value = String(curX);
    valX.textContent = `${curX}%`;
    sliderY.value = String(curY);
    valY.textContent = `${curY}%`;
    updateReticle();
  };

  canvasWrap.addEventListener('pointerdown', (e) => {
    isTargeting = true;
    setPosFromPointer(e);
  });
  const onPointerMove = (e) => {
    if (isTargeting) setPosFromPointer(e);
  };
  const onPointerUp = () => {
    isTargeting = false;
  };
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);

  // 3. Controls & Live Preview Box
  const controls = shellEl('div', 'shell-focal-controls');

  // Preview Row
  const prevRow = shellEl('div', 'shell-focal-preview-row');
  const prevBox = shellEl('div', 'shell-focal-preview-box');
  const prevAvWrap = shellEl('div', 'shell-focal-preview-avatar');
  const prevImg = document.createElement('img');
  prevImg.src = curMaster;
  prevAvWrap.appendChild(prevImg);
  const prevLabel = shellEl('div', 'status-hint', typeof tr === 'function' ? tr('profile.focal.preview') : 'Live Preview');
  prevBox.append(prevAvWrap, prevLabel);
  prevRow.appendChild(prevBox);

  const updatePreviewAvatar = () => {
    prevImg.src = curMaster;
    prevImg.style.objectPosition = `${curX}% ${curY}%`;
    prevImg.style.transform = `scale(${curZoom})`;
    prevImg.style.transformOrigin = `${curX}% ${curY}%`;
  };

  // Slider X
  const rowX = shellEl('div', 'shell-focal-slider-row');
  const lblXText = typeof tr === 'function' ? tr('profile.focal.x') : 'X-Axis';
  const lblX = shellEl('label', '', lblXText);
  const sliderX = document.createElement('input');
  sliderX.type = 'range';
  sliderX.min = '0';
  sliderX.max = '100';
  sliderX.value = String(curX);
  const valX = shellEl('span', 'focal-val', `${curX}%`);
  sliderX.addEventListener('input', () => {
    curX = Number(sliderX.value);
    valX.textContent = `${curX}%`;
    updateReticle();
  });
  rowX.append(lblX, sliderX, valX);

  // Slider Y
  const rowY = shellEl('div', 'shell-focal-slider-row');
  const lblYText = typeof tr === 'function' ? tr('profile.focal.y') : 'Y-Axis';
  const lblY = shellEl('label', '', lblYText);
  const sliderY = document.createElement('input');
  sliderY.type = 'range';
  sliderY.min = '0';
  sliderY.max = '100';
  sliderY.value = String(curY);
  const valY = shellEl('span', 'focal-val', `${curY}%`);
  sliderY.addEventListener('input', () => {
    curY = Number(sliderY.value);
    valY.textContent = `${curY}%`;
    updateReticle();
  });
  rowY.append(lblY, sliderY, valY);

  // Slider Zoom
  const rowZ = shellEl('div', 'shell-focal-slider-row');
  const lblZText = typeof tr === 'function' ? tr('profile.focal.zoom') : 'Zoom';
  const lblZ = shellEl('label', '', lblZText);
  const sliderZ = document.createElement('input');
  sliderZ.type = 'range';
  sliderZ.min = '10';
  sliderZ.max = '25';
  sliderZ.value = String(Math.round(curZoom * 10));
  const valZ = shellEl('span', 'focal-val', `${curZoom.toFixed(1)}x`);
  sliderZ.addEventListener('input', () => {
    curZoom = Number(sliderZ.value) / 10;
    valZ.textContent = `${curZoom.toFixed(1)}x`;
    updateReticle();
  });
  rowZ.append(lblZ, sliderZ, valZ);

  controls.append(prevRow, rowX, rowY, rowZ);

  // 4. Master Image Source Selector
  const srcSecTitle = typeof tr === 'function' ? tr('profile.sec.master_source') : 'Master Image Source';
  const srcSec = shellSection(srcSecTitle);
  const srcPills = shellEl('div', 'shell-focal-sources');

  const defaultAvatarUrl = typeof characterOwnPortrait === 'function' ? characterOwnPortrait(c) : '';

  const addSourceChip = (name, url) => {
    if (!url) return;
    const chip = shellEl('button', 'shell-focal-source-chip' + (curMaster === url ? ' active' : ''));
    chip.type = 'button';
    chip.textContent = name;
    chip.addEventListener('click', () => {
      srcPills.querySelectorAll('.shell-focal-source-chip').forEach(el => el.classList.remove('active'));
      chip.classList.add('active');
      curMaster = url;
      canvasImg.src = curMaster;
      prevImg.src = curMaster;
      updateReticle();
    });
    srcPills.appendChild(chip);
  };

  addSourceChip('Avatar', defaultAvatarUrl);

  // Load gallery slots from /art
  try {
    const artRes = await api('/api/characters/' + encodeURIComponent(c.id) + '/art');
    if (artRes && artRes.slots) {
      Object.keys(artRes.slots).forEach(k => {
        const s = artRes.slots[k];
        if (s && s.url && !s.url.includes('/stage')) addSourceChip(s.label || k, s.url);
      });
    }
    if (artRes && Array.isArray(artRes.gallery)) {
      artRes.gallery.slice(0, 6).forEach(g => {
        if (g && g.url) addSourceChip(g.file || 'gallery', g.url);
      });
    }
  } catch (_) {}

  srcSec.appendChild(srcPills);

  // 5. Save & Actions Row
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
      const focalObj = {
        x: curX,
        y: curY,
        zoom: Number(curZoom.toFixed(2)),
        master: curMaster === defaultAvatarUrl ? '' : curMaster
      };
      const res = await shellSettingsPatch(c.id, { 'display.focal': focalObj });   // cs/C: merged by the server
      if (res && res.errors && res.errors['display.focal']) throw new Error(res.errors['display.focal']);
      c.focal = focalObj;
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

  dialog.append(head, canvasWrap, controls, srcSec, actRow);
  panel.appendChild(dialog);
  updateReticle();
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
