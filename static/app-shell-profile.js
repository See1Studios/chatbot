// Profile: Companion Profile Screen (Redesign UX/S2)
// 3 Tabs Architecture:
// Tab 1: 'character' - Base persona & card settings (inline inspection & edit, expression strip)
// Tab 2: 'relationship' - Accumulated continuity (relation level, affection, memory.md)
// Tab 3: 'engine' - Engineering system controls (Provider, Model, Quota, Tokens)
// Telegram-style Master Image with Face Coordinate Crop & Pull-down Expander

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
    expand: '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
    close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    down: '<polyline points="6 9 12 15 18 9"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
  };
  const body = icons[name] || '';
  return `<svg viewBox="0 0 24 24" class="btn-icon-svg shell-svg-${name}" aria-hidden="true">${body}</svg>`;
}

// Resolve master high-resolution artwork URL for a character
function getMasterArtworkUrl(c) {
  if (c.focal && c.focal.master) return c.focal.master;
  if (c.stage_v && typeof BASE_PATH !== 'undefined') {
    return BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v;
  }
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

  // 2. Hero Section (Visual Foundation & Master Artwork)
  const hero = shellEl('div', 'shell-hero');
  const cover = shellEl('div', 'shell-hero-cover');
  const masterUrl = getMasterArtworkUrl(c);
  if (c.stage_v && typeof BASE_PATH !== 'undefined') {
    const stageUrl = BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v;
    cover.style.backgroundImage = 'url("' + stageUrl + '")';
    cover.classList.add('has-stage');
  } else if (masterUrl) {
    cover.style.backgroundImage = 'url("' + masterUrl + '")';
  }

  // Cover action: Click to open full Master Artwork viewer
  cover.title = typeof tr === 'function' ? (tr('profile.view_master') || 'View master artwork') : 'View master artwork';
  cover.addEventListener('click', (ev) => {
    if (ev.target.closest('.shell-hero-cover-btn')) return;
    openMasterArtworkViewer(panel, c);
  });

  // Pull-down indicator on cover
  const coverHint = shellEl('span', 'shell-hero-expand-hint');
  const hintText = typeof tr === 'function' ? (tr('profile.view_master') || 'Full Art') : 'Full Art';
  coverHint.innerHTML = profileIconSvg('expand') + ' <span>' + escapeHtml(hintText) + '</span>';
  cover.appendChild(coverHint);

  // Cover custom button: opens Focal Cropper directly
  const coverBtn = shellEl('button', 'shell-hero-cover-btn');
  coverBtn.type = 'button';
  coverBtn.title = typeof tr === 'function' ? (tr('profile.edit_focal') || 'Edit crop') : 'Edit crop';
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
  avatarWrap.title = 'View artwork / pull down';

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
  img.src = (focal.master) ? focal.master : (typeof characterOwnPortrait === 'function' ? characterOwnPortrait(c) : '');

  avatarClip.appendChild(img);

  // Presence Status Dot
  const presenceDot = shellEl('span', 'shell-hero-dot ' + (typeof isBusy !== 'undefined' && isBusy ? 'busy' : 'online'));

  // Quick focal target button on avatar corner
  const focalBtn = shellEl('button', 'shell-hero-focal-btn');
  focalBtn.type = 'button';
  focalBtn.title = typeof tr === 'function' ? (tr('profile.edit_focal') || 'Edit focal crop') : 'Edit focal crop';
  focalBtn.setAttribute('aria-label', 'Edit Face Crop');
  focalBtn.innerHTML = profileIconSvg('target');
  focalBtn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    openFocalEditor(panel, c);
  });

  avatarWrap.append(avatarClip, presenceDot, focalBtn);

  // Avatar click & pull-down drag gesture to open master artwork
  bindPullDownGesture(avatarWrap, () => openMasterArtworkViewer(panel, c));
  avatarClip.addEventListener('click', () => openMasterArtworkViewer(panel, c));

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

  // Persona Bio / Summary
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

  // 3. Segmented 3-Tab Control (character / relationship / engine)
  const tabNav = shellEl('div', 'shell-profile-nav shell-profile-nav-3');

  const tabCharBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'character' ? ' active' : ''));
  tabCharBtn.type = 'button';
  tabCharBtn.innerHTML = profileIconSvg('user') + ' ' + escapeHtml(typeof tr === 'function' ? (tr('card.title') || 'Character') : 'Character');

  const tabRelBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'relationship' ? ' active' : ''));
  tabRelBtn.type = 'button';
  tabRelBtn.innerHTML = profileIconSvg('bond') + ' ' + escapeHtml(typeof tr === 'function' ? (tr('profile.tab.persona') || 'Bond & Memory') : 'Bond & Memory');

  const tabEngBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'engine' ? ' active' : ''));
  tabEngBtn.type = 'button';
  tabEngBtn.innerHTML = profileIconSvg('settings') + ' ' + escapeHtml(typeof tr === 'function' ? (tr('profile.tab.engine') || 'Settings') : 'Settings');

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
  const sec = shellSection(typeof tr === 'function' ? (tr('team.sub.card') || 'Character Card') : 'Character Card');
  const headRow = shellEl('div', 'shell-inline-head');
  headRow.appendChild(shellEl('span', 'status-hint', typeof tr === 'function' ? (tr('card.title') || 'Base Persona') : 'Base Persona'));

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
    const fTags = shellFormField('Tags (comma separated)', 'text', (c.tags || []).join(', '));

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
    // Readonly Field Cards
    const list = shellEl('div', 'shell-field-list');
    list.appendChild(shellInfoRow(tr('card.name'), c.title || c.name || ''));
    if (c.user_title) list.appendChild(shellInfoRow(tr('card.user_title') || 'User Title', c.user_title));
    if (c.voice) list.appendChild(shellInfoRow(tr('profile.voice.sample') || 'Voice Preset', c.voice));
    if (c.role) list.appendChild(shellInfoRow('Role', c.role));
    if (c.description) list.appendChild(shellInfoRow(tr('card.description'), c.description, true));
    if (c.personality) list.appendChild(shellInfoRow(tr('card.personality'), c.personality, true));
    if (c.tags && c.tags.length) list.appendChild(shellInfoRow('Tags', c.tags.map(t => '#' + t).join(' ')));
    sec.appendChild(list);
  }

  holder.appendChild(sec);

  // Expression & Stage Gallery Mini-Strip
  const artSec = shellSection('Visuals & Art');
  const artStrip = shellEl('div', 'shell-art-strip');
  artStrip.appendChild(shellEl('div', 'status-hint', typeof tr === 'function' ? tr('common.loading') : 'Loading...'));
  artSec.appendChild(artStrip);
  holder.appendChild(artSec);
  loadArtMiniStrip(c.id, artStrip, panel, c);
}

// ------------------------------------------------------------------ Tab 2: Relationship & Memory
function renderRelationshipTab(holder, c) {
  // 1. Relationship facts
  if (typeof shellRelationSection === 'function') {
    const relSec = shellRelationSection(c);
    if (relSec) holder.appendChild(relSec);
  }

  // 2. Shared Memory Card
  const memSec = shellSection(typeof tr === 'function' ? (tr('team.sub.memory') || 'Shared Memory') : 'Shared Memory');
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
  if (typeof shellQuotaSection === 'function') holder.appendChild(shellQuotaSection());
  if (typeof shellBrainSection === 'function') holder.appendChild(shellBrainSection(c));
  if (typeof shellModelSection === 'function') holder.appendChild(shellModelSection());
  if (typeof shellContextSection === 'function') holder.appendChild(shellContextSection());
  if (typeof shellBrainUseSection === 'function') holder.appendChild(shellBrainUseSection(c));
  if (typeof shellDevDeleteButton === 'function') shellDevDeleteButton(holder, c);
}

// ------------------------------------------------------------------ Master Artwork Viewer (Telegram style)
function openMasterArtworkViewer(panel, c) {
  if (!panel || !c) return;
  const existing = panel.querySelector('.shell-master-viewer');
  if (existing) existing.remove();

  const viewer = shellEl('div', 'shell-master-viewer');
  const masterUrl = getMasterArtworkUrl(c);

  // Top control bar with pull-down handle and actions
  const topBar = shellEl('div', 'shell-master-viewer-top');
  const dragHandle = shellEl('div', 'shell-master-drag-handle');
  const pullLabel = typeof tr === 'function' ? (tr('profile.pull_down_close') || 'Pull down to close') : 'Pull down to close';
  dragHandle.innerHTML = profileIconSvg('down') + ' <span>' + escapeHtml(pullLabel) + '</span>';

  const actions = shellEl('div', 'shell-master-actions');
  const focalBtn = shellEl('button', 'art-btn art-btn-xs');
  focalBtn.type = 'button';
  const focalLabel = typeof tr === 'function' ? (tr('profile.edit_focal') || 'Edit Crop') : 'Edit Crop';
  focalBtn.innerHTML = profileIconSvg('target') + ' <span>' + escapeHtml(focalLabel) + '</span>';
  focalBtn.addEventListener('click', () => {
    viewer.remove();
    openFocalEditor(panel, c);
  });

  const closeBtn = shellEl('button', 'art-btn art-btn-xs');
  closeBtn.type = 'button';
  closeBtn.innerHTML = profileIconSvg('close');
  closeBtn.title = typeof tr === 'function' ? tr('common.close') : 'Close';
  closeBtn.addEventListener('click', () => viewer.remove());

  actions.append(focalBtn, closeBtn);
  topBar.append(dragHandle, actions);

  // Image Display Area
  const imgWrap = shellEl('div', 'shell-master-img-wrap');
  const img = document.createElement('img');
  img.className = 'shell-master-img';
  img.alt = c.name || '';
  img.src = masterUrl;
  imgWrap.appendChild(img);

  viewer.append(topBar, imgWrap);
  panel.appendChild(viewer);

  // Gesture: Pull down to dismiss
  bindPullDownGesture(viewer, () => viewer.remove());
}

// Bind smooth drag-down gesture to dismiss element
function bindPullDownGesture(element, onDismiss) {
  if (!element || !element.addEventListener) return;
  let startY = 0;
  let currentY = 0;
  let isDragging = false;

  const onStart = (y) => {
    startY = y;
    currentY = y;
    isDragging = true;
    element.classList.add('dragging');
  };

  const onMove = (y) => {
    if (!isDragging) return;
    const dy = y - startY;
    if (dy > 0) {
      currentY = y;
      element.style.transform = `translateY(${Math.min(dy, 240)}px)`;
      element.style.opacity = String(Math.max(0.3, 1 - dy / 300));
    }
  };

  const onEnd = () => {
    if (!isDragging) return;
    isDragging = false;
    element.classList.remove('dragging');
    const dy = currentY - startY;
    if (dy > 65) {
      element.style.transform = 'translateY(100%)';
      element.style.opacity = '0';
      setTimeout(() => onDismiss(), 180);
    } else {
      element.style.transform = '';
      element.style.opacity = '';
    }
  };

  // Pointer / Touch bindings
  element.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button, input, select')) return;
    onStart(e.clientY);
  });
  window.addEventListener('pointermove', (e) => onMove(e.clientY));
  window.addEventListener('pointerup', () => onEnd());
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
  const titleLabel = typeof tr === 'function' ? (tr('profile.focal_title') || 'Face Focal & Avatar Crop') : 'Face Focal & Avatar Crop';
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
  const prevLabel = shellEl('div', 'status-hint', 'Live Preview');
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
  const lblX = shellEl('label', '', 'X-Axis');
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
  const lblY = shellEl('label', '', 'Y-Axis');
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
  const lblZ = shellEl('label', '', 'Zoom');
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
  const srcSec = shellSection('Master Image Source');
  const srcPills = shellEl('div', 'shell-focal-sources');

  const defaultAvatarUrl = typeof characterOwnPortrait === 'function' ? characterOwnPortrait(c) : '';
  const stageUrl = (c.stage_v && typeof BASE_PATH !== 'undefined') ? (BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v) : '';

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

  addSourceChip('Default Avatar', defaultAvatarUrl);
  if (stageUrl) addSourceChip('Stage Art', stageUrl);

  // Load gallery slots from /art
  try {
    const artRes = await api('/api/characters/' + encodeURIComponent(c.id) + '/art');
    if (artRes && artRes.slots) {
      Object.keys(artRes.slots).forEach(k => {
        const s = artRes.slots[k];
        if (s && s.url) addSourceChip(s.label || k, s.url);
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
  const saveLabel = typeof tr === 'function' ? (tr('common.save') || 'Save') : 'Save';
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

      card.title = 'Click to set face focal point';
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
