/* Theme + header overflow menu — extracted from app.js (monolith-split Phase 2). */
// Overflow menu for the header's controls & Theme switcher
const moreMenuBtn = document.getElementById('moreMenuBtn');
const moreMenuEl = document.getElementById('moreMenu');
function closeMoreMenu() {
  if (!moreMenuEl || moreMenuEl.hidden) return;
  moreMenuEl.hidden = true;
  if (moreMenuBtn) moreMenuBtn.setAttribute('aria-expanded', 'false');
}

// Theme Switcher Logic
const THEMES = ['lime', 'amber', 'cyan', 'emerald', 'violet', 'mono', 'spark'];
function applyTheme(themeName) {
  if (!THEMES.includes(themeName)) themeName = 'lime';
  document.documentElement.setAttribute('data-theme', themeName);
  try {
    localStorage.setItem('chatbot.themeColor', themeName);
  } catch(e){}
  const swatches = document.querySelectorAll('.theme-swatch');
  swatches.forEach(s => {
    s.classList.toggle('active', s.getAttribute('data-theme-choice') === themeName);
  });
}

const initialTheme = localStorage.getItem('chatbot.themeColor') || 'lime';
applyTheme(initialTheme);

if (moreMenuBtn && moreMenuEl) {
  moreMenuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const willOpen = moreMenuEl.hidden;
    moreMenuEl.hidden = !willOpen;
    moreMenuBtn.setAttribute('aria-expanded', String(willOpen));
  });
  document.addEventListener('click', (e) => {
    if (!moreMenuEl.hidden && !moreMenuEl.contains(e.target) && e.target !== moreMenuBtn) closeMoreMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !moreMenuEl.hidden) closeMoreMenu();
  });
  // Swatch click listeners
  moreMenuEl.querySelectorAll('.theme-swatch').forEach(swatch => {
    swatch.addEventListener('click', (e) => {
      e.stopPropagation();
      const chosen = swatch.getAttribute('data-theme-choice');
      applyTheme(chosen);
      addActivity(`테마 변경: ${chosen}`);
    });
  });
  // Menu item clicks
  const defibItem = document.getElementById('defibBtn');
  if (defibItem) {
    defibItem.addEventListener('click', closeMoreMenu);
  }
}
