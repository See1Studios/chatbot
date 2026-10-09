// Profile: Companion Profile Screen (Redesign UX/S2)
// Presents Hero Persona & Intimacy (Tab 1) and Brain & Engine Settings (Tab 2).
let shellProfileTab = 'persona';

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
  const hero = shellEl('div', 'shell-hero');
  const cover = shellEl('div', 'shell-hero-cover');
  if (c.stage_v && typeof BASE_PATH !== 'undefined') {
    const stageUrl = BASE_PATH + '/api/characters/' + encodeURIComponent(c.id) + '/stage?v=' + c.stage_v;
    cover.style.backgroundImage = 'url("' + stageUrl + '")';
    cover.classList.add('has-stage');
  }

  const heroCard = shellEl('div', 'shell-hero-card');
  const avatarWrap = shellEl('div', 'shell-hero-avatar-wrap');
  const img = document.createElement('img');
  img.className = 'shell-hero-avatar';
  img.alt = '';
  img.onerror = () => {
    img.onerror = null;
    img.src = typeof initialAvatar === 'function' ? initialAvatar(c.name || c.title) : '';
  };
  img.src = typeof characterOwnPortrait === 'function' ? characterOwnPortrait(c) : '';

  const presenceDot = shellEl('span', 'shell-hero-dot ' + (typeof isBusy !== 'undefined' && isBusy ? 'busy' : 'online'));
  avatarWrap.append(img, presenceDot);

  const titleWrap = shellEl('div', 'shell-hero-info');
  const nameEl = shellEl('div', 'shell-hero-name', c.title || c.name || '');

  const badgeWrap = shellEl('div', 'shell-hero-badges');
  if (c.role) {
    badgeWrap.appendChild(shellEl('span', 'shell-hero-role-badge', c.role));
  }
  if (c.voice) {
    const voiceChip = shellEl('span', 'shell-hero-voice-chip', '🎙️ ' + c.voice);
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

  // 3. Segmented Tab Control
  const tabNav = shellEl('div', 'shell-profile-nav');
  const tabPersonaBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'persona' ? ' active' : ''));
  tabPersonaBtn.type = 'button';
  const personaText = typeof tr === 'function' ? tr('profile.tab.persona') : 'Persona & Bond';
  tabPersonaBtn.innerHTML = '<span aria-hidden="true">🌸</span> ' + escapeHtml(personaText);

  const tabEngineBtn = shellEl('button', 'shell-tab-btn' + (shellProfileTab === 'engine' ? ' active' : ''));
  tabEngineBtn.type = 'button';
  const engineText = typeof tr === 'function' ? tr('profile.tab.engine') : 'Brain & Engine';
  tabEngineBtn.innerHTML = '<span aria-hidden="true">⚙️</span> ' + escapeHtml(engineText);

  tabNav.append(tabPersonaBtn, tabEngineBtn);

  // 4. Tab 1: Persona & Relationship Body
  const personaBody = shellEl('div', 'shell-tab-body shell-body-persona' + (shellProfileTab === 'persona' ? ' active' : ''));

  // Relationship Section
  if (typeof shellRelationSection === 'function') {
    const relSec = shellRelationSection(c);
    if (relSec) personaBody.appendChild(relSec);
  }

  // Action Cards (Art, Sessions, Artifacts, Manage)
  const rows = typeof shellProfileRows === 'function' ? shellProfileRows({
    art: typeof openArtManager === 'function',
    manage: typeof loadTeam === 'function'
  }) : [];

  if (rows.length) {
    const mediaTitle = typeof tr === 'function' ? tr('profile.section.media') : 'Memories & Archive';
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
        if (row.k === 'art' && typeof shellGoArt === 'function') shellGoArt(c.id);
        else if (row.k === 'manage' && typeof shellGoTeam === 'function') shellGoTeam(c.id, 'profile');
      });
      actionGrid.appendChild(btn);
    });
    actionSec.appendChild(actionGrid);
    personaBody.appendChild(actionSec);
  }

  // 5. Tab 2: Brain & Engine Body
  const engineBody = shellEl('div', 'shell-tab-body shell-body-engine' + (shellProfileTab === 'engine' ? ' active' : ''));

  if (typeof shellQuotaSection === 'function') engineBody.appendChild(shellQuotaSection());
  if (typeof shellBrainSection === 'function') engineBody.appendChild(shellBrainSection(c));
  if (typeof shellModelSection === 'function') engineBody.appendChild(shellModelSection());
  if (typeof shellContextSection === 'function') engineBody.appendChild(shellContextSection());
  if (typeof shellBrainUseSection === 'function') engineBody.appendChild(shellBrainUseSection(c));
  if (typeof shellDevDeleteButton === 'function') shellDevDeleteButton(engineBody, c);

  // Tab switching events
  tabPersonaBtn.addEventListener('click', () => {
    shellProfileTab = 'persona';
    tabPersonaBtn.classList.add('active');
    tabEngineBtn.classList.remove('active');
    personaBody.classList.add('active');
    engineBody.classList.remove('active');
  });

  tabEngineBtn.addEventListener('click', () => {
    shellProfileTab = 'engine';
    tabEngineBtn.classList.add('active');
    tabPersonaBtn.classList.remove('active');
    engineBody.classList.add('active');
    personaBody.classList.remove('active');
  });

  panel.append(head, hero, tabNav, personaBody, engineBody);
}
