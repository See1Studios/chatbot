// Profile: Companion Profile Screen (Redesign UX/S2)
// 3 Tabs Architecture:
// Tab 1: 'character' - Base persona & card settings
// Tab 2: 'relationship' - Accumulated continuity
// Tab 3: 'engine' - Engineering system controls
// Master Image with Face Coordinate Crop & Inline Editor

let shellProfileTab = 'character'; // 'character' | 'relationship' | 'engine'
let shellProfileEditMode = false;

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

  // Cover action: directly opens Face Focal / Master Art editor
  const coverBtn = shellEl('button', 'shell-hero-cover-btn');
  coverBtn.type = 'button';
  coverBtn.title = typeof tr === 'function' ? tr('profile.sec.focal') : 'Edit Face Focus';
  coverBtn.setAttribute('aria-label', 'Edit Art');
  coverBtn.innerHTML = profileIconSvg('camera');
  coverBtn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    openFocalEditor(panel, c);
  });
  cover.appendChild(coverBtn);

  // Hero Card with Focal Cropped Avatar
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

  // Quick focal target button on avatar corner
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

  // Persona Bio / Summary (scrollable when long)
  const bioText = (c.description || c.personality || '').trim();
  if (bioText) {
    const bioEl = shellEl('div', 'shell-hero-bio', bioText);
    heroCard.appendChild(bioEl);
  }

  // Persona Tags
  const tags = Array.isArray(c.tags) ? c.tags.filter(Boolean) : [];
  if (tags.length) {
    const tagsEl = shellEl('div', 'shell-hero-tags');
    tags.slice(0, 6).forEach(tag => {
      tagsEl.appendChild(shellEl('span', 'shell-hero-tag', '#' + tag));
    });
    heroCard.appendChild(tagsEl);
  }

  hero.append(cover, heroCard);

  // 3. Segmented 3-Tab Control: character / relationship / settings
  const tabNav = shellEl('div', 'shell-profile-nav shell-profile-nav-3');

  const tabCharLabel = typeof tr === 'function' ? tr('profile.tab.character') : 'Character';
  const tabCharBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'character' ? ' active' : ''));
  tabCharBtn.type = 'button';
  tabCharBtn.innerHTML = profileIconSvg('user') + ' ' + escapeHtml(tabCharLabel);

  const tabRelLabel = typeof tr === 'function' ? tr('profile.tab.relationship') : 'Relationship';
  const tabRelBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'relationship' ? ' active' : ''));
  tabRelBtn.type = 'button';
  tabRelBtn.innerHTML = profileIconSvg('bond') + ' ' + escapeHtml(tabRelLabel);

  const tabEngLabel = typeof tr === 'function' ? tr('profile.tab.settings') : 'Settings';
  const tabEngBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'engine' ? ' active' : ''));
  tabEngBtn.type = 'button';
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

  // Tab switching events
  tabCharBtn.addEventListener('click', () => {
    shellProfileTab = 'character';
    shellProfileDraw(panel, c, column);
  });
  tabRelBtn.addEventListener('click', () => {
    shellProfileTab = 'relationship';
    shellProfileDraw(panel, c, column);
  });
  tabEngBtn.addEventListener('click', () => {
    shellProfileTab = 'engine';
    shellProfileDraw(panel, c, column);
  });

  panel.append(head, hero, tabNav, charBody, relBody, engBody);
}

// ------------------------------------------------------------------ Tab 1: Character
function renderCharacterTab(holder, c, panel, column) {
  if (!holder || !c) return;
  holder.textContent = '';

  const secTitle = typeof tr === 'function' ? tr('profile.sec.card') : 'Character Card';
  const sec = shellSection(secTitle);
  const headRow = shellEl('div', 'shell-inline-head');
  const baseInfoLabel = typeof tr === 'function' ? tr('profile.sec.base_info') : 'Base Info';
  headRow.appendChild(shellEl('span', 'status-hint', baseInfoLabel));

  const editToggleBtn = shellEl('button', 'art-btn art-btn-xs ' + (shellProfileEditMode ? '' : 'primary'));
  editToggleBtn.type = 'button';
  if (shellProfileEditMode) {
    editToggleBtn.textContent = typeof tr === 'function' ? tr('common.cancel') : 'Cancel';
  } else {
    editToggleBtn.innerHTML = profileIconSvg('edit') + ' ' + escapeHtml(typeof tr === 'function' ? tr('common.edit') : 'Edit');
  }

  editToggleBtn.addEventListener('click', () => {
    shellProfileEditMode = !shellProfileEditMode;
    renderCharacterTab(holder, c, panel, column);
  });
  headRow.appendChild(editToggleBtn);
  sec.appendChild(headRow);

  if (shellProfileEditMode) {
    // Inline Edit Form
    const form = shellEl('div', 'shell-edit-form');

    const fName = shellFormField(tr('card.name'), 'text', c.title || c.name || '');
    const fUserTitle = shellFormField(tr('card.user_title') || 'User Title', 'text', c.user_title || '', 'e.g. Master, Sensei');
    const fVoice = shellFormField(tr('profile.voice.sample') || 'Voice Preset', 'text', c.voice || '', 'e.g. ko-KR-Neural2-A');
    const fDesc = shellFormFieldArea(tr('card.description'), c.description || '');
    const fPers = shellFormFieldArea(tr('card.personality'), c.personality || '');
    const fTags = shellFormField('Tags', 'text', (c.tags || []).join(', '));

    const btnRow = shellEl('div', 'shell-edit-actions');
    const saveBtn = shellEl('button', 'art-btn art-btn-sm primary', typeof tr === 'function' ? tr('common.save') : 'Save');
    saveBtn.type = 'button';

    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = typeof tr === 'function' ? tr('common.saving') : 'Saving...';
      try {
        await saveCharacterInline(c.id, {
          name: fName.input.value.trim(),
          user_title: fUserTitle.input.value.trim(),
          voice: fVoice.input.value.trim(),
          description: fDesc.input.value.trim(),
          personality: fPers.input.value.trim(),
          tags: fTags.input.value.split(',').map(s => s.trim()).filter(Boolean),
        });
        shellProfileEditMode = false;
        if (typeof loadCharacters === 'function') await loadCharacters();
        if (typeof updateBrandAvatar === 'function') updateBrandAvatar();
        const updated = typeof currentCharacter === 'function' ? currentCharacter() : c;
        shellProfileDraw(panel, updated || c, column);
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.textContent = typeof tr === 'function' ? tr('common.save') : 'Save';
        alert((typeof tr === 'function' ? tr('card.cannot_save', { error: err.message || err }) : 'Save failed: ' + err.message));
      }
    });

    btnRow.appendChild(saveBtn);
    form.append(fName.wrap, fUserTitle.wrap, fVoice.wrap, fDesc.wrap, fPers.wrap, fTags.wrap, btnRow);
    sec.appendChild(form);
  } else {
    // Readonly Field Cards with scrollable long text (Role moved to Tab 3: Settings)
    const list = shellEl('div', 'shell-field-list');
    list.appendChild(shellInfoRow(tr('card.name'), c.title || c.name || ''));
    if (c.user_title) list.appendChild(shellInfoRow(tr('card.user_title') || 'User Title', c.user_title));
    if (c.voice) list.appendChild(shellInfoRow(tr('profile.voice.sample') || 'Voice Preset', c.voice));
    if (c.description) list.appendChild(shellInfoRow(tr('card.description'), c.description, true));
    if (c.personality) list.appendChild(shellInfoRow(tr('card.personality'), c.personality, true));
    if (c.tags && c.tags.length) list.appendChild(shellInfoRow('Tags', c.tags.map(t => '#' + t).join(' ')));
    sec.appendChild(list);
  }

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

  // 2. Shared Memory Card (scrollable)
  const memSecTitle = typeof tr === 'function' ? tr('profile.sec.memory') : 'Shared Memory';
  const memSec = shellSection(memSecTitle);
  const memCard = shellEl('div', 'shell-memory-card');
  const memHint = shellEl('div', 'status-hint', typeof tr === 'function' ? tr('common.loading') : 'Loading memory...');
  memCard.appendChild(memHint);
  memSec.appendChild(memCard);
  holder.appendChild(memSec);
  loadMemoryContent(c.id, memCard);

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
  // Role belongs in engineering/settings tab
  if (c.role) {
    const roleTitle = typeof tr === 'function' ? tr('profile.sec.role') : 'Assigned Role';
    const roleSec = shellSection(roleTitle);
    const roleList = shellEl('div', 'shell-field-list');
    roleList.appendChild(shellInfoRow(roleTitle, c.role));
    roleSec.appendChild(roleList);
    holder.appendChild(roleSec);
  }
  if (typeof shellQuotaSection === 'function') holder.appendChild(shellQuotaSection());
  if (typeof shellBrainSection === 'function') holder.appendChild(shellBrainSection(c));
  if (typeof shellModelSection === 'function') holder.appendChild(shellModelSection());
  if (typeof shellContextSection === 'function') holder.appendChild(shellContextSection());
  if (typeof shellBrainUseSection === 'function') holder.appendChild(shellBrainUseSection(c));
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
  const closeBtn = shellEl('button', 'art-btn art-btn-xs');
  closeBtn.type = 'button';
  closeBtn.innerHTML = profileIconSvg('close');
  closeBtn.title = typeof tr === 'function' ? tr('common.close') : 'Close';
  closeBtn.addEventListener('click', () => dialog.remove());
  head.append(title, closeBtn);

  // 2. Interactive Canvas Wrap
  const canvasWrap = shellEl('div', 'shell-focal-canvas-wrap');
  const canvasImg = document.createElement('img');
  canvasImg.className = 'shell-focal-canvas-img';
  canvasImg.src = curMaster;

  const reticle = shellEl('div', 'shell-focal-reticle');
  canvasWrap.append(canvasImg, reticle);

  // Update reticle position on canvas
  const updateReticle = () => {
    reticle.style.left = `${curX}%`;
    reticle.style.top = `${curY}%`;
    const rSize = Math.max(28, Math.min(80, Math.round(54 / curZoom)));
    reticle.style.width = `${rSize}px`;
    reticle.style.height = `${rSize}px`;
    updatePreviewAvatar();
  };

  // Canvas Click & Drag to reposition focal coordinates
  let isTargeting = false;
  const setPosFromPointer = (e) => {
    const rect = canvasWrap.getBoundingClientRect();
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
  window.addEventListener('pointermove', (e) => {
    if (isTargeting) setPosFromPointer(e);
  });
  window.addEventListener('pointerup', () => {
    isTargeting = false;
  });

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
  cancelBtn.addEventListener('click', () => dialog.remove());

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
      await saveCharacterInline(c.id, { focal: focalObj });
      c.focal = focalObj;
      if (typeof loadCharacters === 'function') await loadCharacters();
      dialog.remove();
      const updated = typeof currentCharacter === 'function' ? currentCharacter() : c;
      shellProfileDraw(panel, updated || c);
    } catch (err) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = profileIconSvg('check') + ' <span>' + escapeHtml(saveLabel) + '</span>';
      alert('Save failed: ' + (err.message || err));
    }
  });

  actRow.append(cancelBtn, saveBtn);

  dialog.append(head, canvasWrap, controls, srcSec, actRow);
  panel.appendChild(dialog);
  updateReticle();
}

// ------------------------------------------------------------------ Helpers
function shellFormField(label, type, val, placeholder) {
  const wrap = shellEl('div', 'shell-field-wrap');
  wrap.appendChild(shellEl('label', 'shell-field-label', label));
  const input = document.createElement('input');
  input.type = type || 'text';
  input.className = 'shell-field-input';
  input.value = val || '';
  if (placeholder) input.placeholder = placeholder;
  wrap.appendChild(input);
  return { wrap, input };
}

function shellFormFieldArea(label, val) {
  const wrap = shellEl('div', 'shell-field-wrap');
  wrap.appendChild(shellEl('label', 'shell-field-label', label));
  const input = document.createElement('textarea');
  input.className = 'shell-field-textarea';
  input.rows = 3;
  input.value = val || '';
  wrap.appendChild(input);
  return { wrap, input };
}

function shellInfoRow(label, val, multiline) {
  const row = shellEl('div', 'shell-info-row' + (multiline ? ' multiline' : ''));
  row.appendChild(shellEl('span', 'shell-info-label', label));
  row.appendChild(shellEl('span', 'shell-info-val', String(val || '-')));
  return row;
}

// Save character card inline via PUT /api/instructions/characters/<id>/card.json
async function saveCharacterInline(cid, patch) {
  const path = 'characters/' + cid + '/card.json';
  let cardObj = null;
  try {
    const res = await api('/api/instructions/' + encodeURIComponent(path));
    if (res && res.content) {
      cardObj = JSON.parse(res.content);
    }
  } catch (_) {
    cardObj = null;
  }
  if (!cardObj || !cardObj.data) {
    cardObj = { spec: 'chara_card_v2', spec_version: '2.0', data: {} };
  }
  const d = cardObj.data;
  if (patch.name !== undefined) d.name = patch.name;
  if (patch.description !== undefined) d.description = patch.description;
  if (patch.personality !== undefined) d.personality = patch.personality;
  if (patch.tags !== undefined) d.tags = patch.tags;

  if (!d.extensions || typeof d.extensions !== 'object') d.extensions = {};
  if (!d.extensions.chatbot || typeof d.extensions.chatbot !== 'object') d.extensions.chatbot = {};
  const disp = d.extensions.chatbot.display || {};
  if (patch.user_title !== undefined) disp.user_title = patch.user_title;
  if (patch.voice !== undefined) disp.voice = patch.voice;
  if (patch.focal !== undefined) disp.focal = patch.focal;
  d.extensions.chatbot.display = disp;

  await api('/api/instructions/' + encodeURIComponent(path), {
    method: 'PUT',
    body: JSON.stringify({ content: JSON.stringify(cardObj, null, 2) }),
  });
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

// Async load character memory.md
async function loadMemoryContent(cid, container) {
  try {
    const res = await api('/api/instructions/characters/' + encodeURIComponent(cid) + '/memory.md');
    container.textContent = '';
    const text = (res && res.content ? res.content.trim() : '');
    if (!text) {
      container.appendChild(shellEl('div', 'status-hint', 'No shared memory recorded yet.'));
      return;
    }
    const memBody = shellEl('div', 'shell-memory-body', text);
    container.appendChild(memBody);
  } catch (_) {
    container.textContent = '';
    container.appendChild(shellEl('div', 'status-hint', 'Memory not initialized yet.'));
  }
}
