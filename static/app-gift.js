// app-gift.js -- giving a gift in private mode (docs/plans/composer-plus-menu.md plus/F, plus/G).
//
// + → Give a gift opens the gift picker: the catalog, this character's affection and how many gifts are left today.
// Picking one asks the server to judge it (gifts.py: the character's likes against the gift's tags, never the
// model), shows the result as a toast, then sends the giving as an action (sendAction). The server appends its
// note to that action, so the character reacts to the verdict; on screen the note is a gift chip, not text.

const GIFT_TEXT = {
  title: '선물하기', left: (n) => '오늘 남은 선물 ' + n + '번', none: '오늘은 더 줄 수 없어요. 내일 또 건네 주세요.',   // l10n-ok
  give: (g) => g.icon + ' ' + g.name + '을(를) 건넨다', close: '닫기', failed: '선물 실패: ',   // l10n-ok
  toast: (r) => r.gift.icon + ' ' + r.label + ' · 호감도 ' + (r.delta >= 0 ? '+' : '') + r.delta + ' · Lv.' + r.level + ' ' + r.title,   // l10n-ok
};
const GIFT_NOTE = /\n*\[Gift - host note: the user gave you (\S+) ([^(]+?) \([^)]*\)\.[^\]]*\]\s*$/;

// {text, gift: {icon, name}|null}: the message without the host note, and the gift it names.
function splitGiftNote(text) {
  const s = String(text || '');
  const m = GIFT_NOTE.exec(s);
  if (!m) return { text: s, gift: null };
  return { text: s.slice(0, m.index).replace(/\s+$/, ''), gift: { icon: m[1], name: m[2].trim() } };
}

function renderGiftChip(bubble, gift) {
  if (!bubble || !gift || bubble.querySelector('.gift-chip')) return;
  const chip = document.createElement('span');
  chip.className = 'gift-chip';
  chip.textContent = gift.icon + ' ' + gift.name;
  bubble.appendChild(chip);
}

function giftToast(text) {
  let t = document.getElementById('giftToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'giftToast';
    t.className = 'gift-toast';
    t.setAttribute('role', 'status');
    document.body.appendChild(t);
  }
  t.textContent = text;
  t.classList.remove('show');
  void t.offsetWidth;                                  // restart the entrance
  t.classList.add('show');
  clearTimeout(giftToast._timer);
  giftToast._timer = setTimeout(() => t.classList.remove('show'), 3200);
}

function closeGiftPicker() {
  const p = document.getElementById('giftPicker');
  if (p) p.remove();
}

async function openGiftPicker() {
  if (typeof sessionId === 'undefined' || !sessionId) return;
  closeGiftPicker();
  let data;
  try {
    data = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/gifts');
  } catch (e) {
    if (typeof addActivity === 'function') addActivity(GIFT_TEXT.failed + (e.message || e), 'warn');
    return;
  }
  const wrap = document.createElement('div');
  wrap.id = 'giftPicker';
  wrap.className = 'gift-picker';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-label', GIFT_TEXT.title);
  const head = document.createElement('div');
  head.className = 'gift-head';
  const title = document.createElement('span');
  const a = data.affection || {};
  title.textContent = '💗 Lv.' + a.level + ' ' + a.title + ' · ' + GIFT_TEXT.left(a.left_today);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'gift-close';
  close.setAttribute('aria-label', GIFT_TEXT.close);
  close.textContent = '✕';
  close.addEventListener('click', closeGiftPicker);
  head.appendChild(title);
  head.appendChild(close);
  wrap.appendChild(head);
  const grid = document.createElement('div');
  grid.className = 'gift-grid';
  (data.gifts || []).forEach(g => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'gift-item';
    b.disabled = !a.left_today;
    const icon = document.createElement('span');
    icon.className = 'gift-icon';
    icon.textContent = g.icon;
    const name = document.createElement('span');
    name.className = 'gift-name';
    name.textContent = g.name;
    b.appendChild(icon);
    b.appendChild(name);
    b.addEventListener('click', () => giveGift(g));
    grid.appendChild(b);
  });
  wrap.appendChild(grid);
  if (!a.left_today) {
    const none = document.createElement('div');
    none.className = 'gift-none';
    none.textContent = GIFT_TEXT.none;
    wrap.appendChild(none);
  }
  const composer = document.querySelector('.composer');
  (composer && composer.parentNode ? composer.parentNode : document.body).insertBefore(wrap, composer || null);
}

async function giveGift(g) {
  closeGiftPicker();
  let res;
  try {
    res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/gift',
      { method: 'POST', body: JSON.stringify({ gift: g.id }) });
  } catch (e) {
    if (typeof addActivity === 'function') addActivity(GIFT_TEXT.failed + (e.message || e), 'warn');
    return;
  }
  if (!res || !res.ok) return;
  giftToast(GIFT_TEXT.toast(res.result));
  if (typeof sendAction === 'function') sendAction(GIFT_TEXT.give(g));
  // send() draws the action bubble before its first await, so it is the log's last child now
  const log = document.getElementById('log');
  if (log && log.lastElementChild) renderGiftChip(log.lastElementChild, g);
}
