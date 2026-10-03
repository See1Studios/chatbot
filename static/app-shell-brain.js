// Profile: the brain each mode uses for this character (card default or a remembered override), with a reset.
// Split from app-shell.js (size cap); shellProfileOpen adds it when this file is loaded.
const SHELL_BRAIN_TEXT = {   // l10n-ok
  useBrain: '쓰는 두뇌',   // l10n-ok
  brainNone: '정해진 두뇌 없음',   // l10n-ok
  brainMissing: '두뇌 기록을 불러오지 못했습니다',   // l10n-ok
  loading: '불러오는 중',   // l10n-ok
  modeWork: '업무',   // l10n-ok
  modePrivate: '사적',   // l10n-ok
  brainPicked: '직접 고름 · ',   // l10n-ok
  brainDefault: '기본 · ',   // l10n-ok
  brainReset: '기본값으로',   // l10n-ok
  brainResetFail: '기본값으로 되돌리지 못했습니다',   // l10n-ok
};
function shellBrainLabel(b) {
  if (!b || !b.provider) return SHELL_BRAIN_TEXT.brainNone;
  return b.provider + (b.model ? ' · ' + b.model : '');
}
function shellBrainUseSection(c) {
  const box = shellSection(SHELL_BRAIN_TEXT.useBrain), hold = shellEl('div', 'shell-rows');
  hold.appendChild(shellEl('div', 'shell-card-sub', SHELL_BRAIN_TEXT.loading));
  box.appendChild(hold);
  shellFillBrainUse(c, hold);
  return box;
}
async function shellFillBrainUse(c, hold) {
  let body = null;
  try { body = await api('/api/experts'); }
  catch (e) {
    hold.textContent = '';
    hold.appendChild(shellEl('div', 'shell-card-sub', SHELL_BRAIN_TEXT.brainMissing));
    return;
  }
  const ex = ((body && body.experts) || []).find(row => row.id === c.id) || {};
  const use = ex.brain_use || {}, defaults = use.defaults || {}, override = use.override || {};
  hold.textContent = '';
  [['work', SHELL_BRAIN_TEXT.modeWork], ['private', SHELL_BRAIN_TEXT.modePrivate]].forEach(([mode, label]) => {
    const picked = override[mode] && override[mode].provider ? override[mode] : null;
    const row = shellEl('div', 'shell-rowbtn');
    row.appendChild(shellEl('span', '', label + ' · ' + (picked ? SHELL_BRAIN_TEXT.brainPicked : SHELL_BRAIN_TEXT.brainDefault) + shellBrainLabel(picked || defaults[mode])));
    if (picked) {
      const b = shellEl('button', 'shell-rowbtn', SHELL_BRAIN_TEXT.brainReset);
      b.type = 'button';
      b.addEventListener('click', async () => {
        b.disabled = true;
        try {
          const res = await api('/api/experts/' + encodeURIComponent(c.id) + '/brain-use', {
            method: 'PUT', body: JSON.stringify({ mode: mode, reset: true })});
          if (res && res.session && typeof sessionId !== 'undefined' && res.session.id === sessionId
              && typeof applySessionProvider === 'function') applySessionProvider(res.session);
          shellProfileOpen();
        } catch (err) {
          b.disabled = false;
          if (typeof addActivity === 'function') addActivity(SHELL_BRAIN_TEXT.brainResetFail);
        }
      });
      row.appendChild(b);
    }
    hold.appendChild(row);
  });
}
