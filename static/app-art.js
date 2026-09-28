// app-art.js -- the art manager modal (docs/plans/character-art-manager.md am/C). v0, to be shaped by use (operator,
// 2026-09-29: build it rough, then carve). Declarations only; opened from the character tray and from a finished work card
// whose result landed in a character's gallery.
//
// Tabs follow Character Card V3 asset kinds: gallery (candidates, e.g. what a delegated artist drew), icon,
// background, emotion. A slot shows its own picture, or what it falls back to (ART_NAMES_v1), or the placeholder.
// Putting a gallery picture in a slot is the approval step; the server fits and converts it (art_manager.py).

const ART_TEXT = {
  title: '그림', gallery: '갤러리', icon: '아이콘', background: '배경', emotion: '표정',   // l10n-ok
  own: '내 그림', placeholder: '기본', upload: '올리기', remove: '치우기', close: '닫기',   // l10n-ok
  asIcon: '아이콘으로', asBackground: '배경으로', asEmotion: '표정으로…', empty: '갤러리가 비었어요 — 올리거나 위임으로 그려 받으세요',   // l10n-ok
  askEmotion: '표정 이름 (neutral, joy, sadness … 또는 joy.giggle 같은 세부 이름)', askRemove: '이 칸의 그림을 갤러리로 돌려놓을까요?',   // l10n-ok
  done: '반영했어요', failed: '실패: ', noCharacter: '캐릭터를 먼저 고르세요', drop: '여기에 놓으면 갤러리로 올라가요',   // l10n-ok
  bust: '상반신', full: '전신',   // l10n-ok
};
const ART_TABS = ['gallery', 'icon', 'background', 'emotion'];
let artState = { cid: '', name: '', data: null, tab: 'gallery', framing: 'bust', msg: '' };

function artUrl(u) {
  return (typeof BASE_PATH !== 'undefined' && BASE_PATH && u.startsWith('/') && !u.startsWith(BASE_PATH)) ? BASE_PATH + u : u;
}

function artEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

async function openArtManager(cid, tab) {
  const ch = cid ? { id: cid } : (typeof currentCharacter === 'function' ? currentCharacter() : null);
  if (!ch || !ch.id) { if (typeof addNotice === 'function') addNotice('warn', ART_TEXT.noCharacter); return; }
  const known = (typeof characterCatalog !== 'undefined' ? characterCatalog : []).find(c => c.id === ch.id);
  artState = { cid: ch.id, name: (known && known.name) || ch.name || '', data: null, tab: tab || 'gallery', framing: 'bust', msg: '' };
  await artReload();
}

async function artReload(msg) {
  try {
    artState.data = await api('/api/characters/' + encodeURIComponent(artState.cid) + '/art');
    artState.msg = msg || '';
  } catch (e) {
    artState.msg = ART_TEXT.failed + (e.message || e);
  }
  renderArtManager();
}

function closeArtManager() {
  const m = document.getElementById('artManager');
  if (m) m.remove();
}

// The name a slot falls back to, from the file it shows ("sprites/bust/joy.giggle.webp" -> "joy.giggle").
function artShownName(shows) {
  return String(shows || '').split('/').pop().replace(/\.(webp|png)$/, '');
}

function artSlotBadge(slot) {
  if (slot.own) return [ART_TEXT.own, 'own'];
  if (slot.placeholder) return [ART_TEXT.placeholder, 'ph'];
  return ['→ ' + artShownName(slot.shows), 'falls'];
}

function renderArtManager() {
  let m = document.getElementById('artManager');
  if (!m) {
    m = artEl('div', 'modal-overlay art-mgr-overlay');
    m.id = 'artManager';
    m.addEventListener('click', (e) => { if (e.target === m) closeArtManager(); });
    document.body.appendChild(m);
  }
  m.textContent = '';
  const card = artEl('div', 'modal-card art-mgr');
  const head = artEl('div', 'modal-head');
  head.appendChild(artEl('strong', '', (artState.name ? artState.name + ' · ' : '') + ART_TEXT.title));
  const close = artEl('button', 'art-btn art-btn-xs', ART_TEXT.close);
  close.type = 'button';
  close.addEventListener('click', closeArtManager);
  head.appendChild(close);
  card.appendChild(head);

  const tabs = artEl('div', 'art-mgr-tabs');
  ART_TABS.forEach(t => {
    const b = artEl('button', 'art-mgr-tab' + (t === artState.tab ? ' active' : ''), ART_TEXT[t]);
    b.type = 'button';
    b.addEventListener('click', () => { artState.tab = t; renderArtManager(); });
    tabs.appendChild(b);
  });
  if (artState.tab === 'emotion') {
    ['bust', 'full'].forEach(f => {
      const b = artEl('button', 'art-mgr-tab small' + (f === artState.framing ? ' active' : ''), ART_TEXT[f]);
      b.type = 'button';
      b.addEventListener('click', () => { artState.framing = f; renderArtManager(); });
      tabs.appendChild(b);
    });
  }
  card.appendChild(tabs);

  const body = artEl('div', 'art-mgr-body');
  const d = artState.data || {};
  if (artState.tab === 'gallery') {
    const items = d.gallery || [];
    if (!items.length) body.appendChild(artEl('div', 'art-mgr-empty', ART_TEXT.empty));
    items.forEach(g => body.appendChild(artGalleryCard(g)));
  } else {
    const slots = artState.tab === 'emotion' ? ((d.emotion || {})[artState.framing] || []) : (d[artState.tab] || []);
    slots.forEach(s => body.appendChild(artSlotCard(s)));
  }
  artDropZone(body);
  card.appendChild(body);

  const foot = artEl('div', 'art-mgr-foot');
  const up = artEl('button', 'art-btn primary', ART_TEXT.upload);
  up.type = 'button';
  const input = artEl('input');
  input.type = 'file';
  input.accept = 'image/png,image/webp,image/jpeg';
  input.multiple = true;
  input.hidden = true;
  input.addEventListener('change', () => artUpload(Array.from(input.files || [])));
  up.addEventListener('click', () => input.click());
  foot.appendChild(up);
  foot.appendChild(input);
  const note = artEl('span', 'art-mgr-msg', artState.msg || (d.problems || []).join(' · '));
  foot.appendChild(note);
  card.appendChild(foot);
  m.appendChild(card);
}

function artPicture(url) {
  const img = artEl('img');
  img.loading = 'lazy';
  img.src = artUrl(url);
  img.alt = '';
  img.addEventListener('click', () => window.open(img.src, '_blank', 'noopener'));
  return img;
}

function artSlotCard(slot) {
  const c = artEl('div', 'art-slot' + (slot.own ? '' : ' empty'));
  c.appendChild(artPicture(slot.url));
  const row = artEl('div', 'art-slot-row');
  row.appendChild(artEl('span', 'art-slot-name', slot.brain ? slot.brain : slot.name));
  const [label, kind] = artSlotBadge(slot);
  row.appendChild(artEl('span', 'art-slot-badge ' + kind, label));
  c.appendChild(row);
  if (slot.own) {
    const rm = artEl('button', 'art-btn art-btn-xs', ART_TEXT.remove);
    rm.type = 'button';
    rm.addEventListener('click', async () => {
      if (typeof confirmModal === 'function' && !(await confirmModal(ART_TEXT.askRemove))) return;
      artPost('remove', { kind: slot.kind, name: slot.name, framing: slot.framing, brain: slot.brain });
    });
    c.appendChild(rm);
  }
  return c;
}

function artGalleryCard(g) {
  const c = artEl('div', 'art-slot');
  c.appendChild(artPicture(g.url));
  c.appendChild(artEl('div', 'art-slot-name', g.file));
  const acts = artEl('div', 'art-slot-acts');
  const put = (label, body) => {
    const b = artEl('button', 'art-btn art-btn-xs', label);
    b.type = 'button';
    b.addEventListener('click', () => {
      const args = typeof body === 'function' ? body() : body;
      if (args) artPost('assign', Object.assign({ from: g.file }, args));
    });
    acts.appendChild(b);
  };
  put(ART_TEXT.asIcon, { kind: 'icon' });
  put(ART_TEXT.asBackground, { kind: 'background' });
  put(ART_TEXT.asEmotion, () => {
    const name = (window.prompt(ART_TEXT.askEmotion, 'neutral') || '').trim().toLowerCase();
    return name ? { kind: 'emotion', name, framing: artState.framing } : null;
  });
  c.appendChild(acts);
  return c;
}

async function artPost(action, body) {
  try {
    await api('/api/characters/' + encodeURIComponent(artState.cid) + '/art/' + action, { method: 'POST', body: JSON.stringify(body) });
    await artReload(ART_TEXT.done);
    artRefreshPage();
  } catch (e) {
    artState.msg = ART_TEXT.failed + artError(e);
    renderArtManager();
  }
}

function artError(e) {
  try { return JSON.parse(e.message).error || e.message; } catch (_) { return String((e && e.message) || e); }
}

async function artUpload(files) {
  for (const f of files) {
    try {
      const r = await fetch(BASE_PATH + '/api/characters/' + encodeURIComponent(artState.cid) + '/art/upload', {
        method: 'POST', headers: { 'X-File-Name': encodeURIComponent(f.name), 'Content-Type': f.type || 'application/octet-stream' }, body: f });
      if (!r.ok) throw new Error(await r.text());
    } catch (e) {
      artState.msg = ART_TEXT.failed + artError(e);
    }
  }
  artState.tab = 'gallery';
  await artReload(artState.msg);
}

function artDropZone(el) {
  el.addEventListener('dragover', (e) => { e.preventDefault(); el.classList.add('drop'); el.dataset.hint = ART_TEXT.drop; });
  el.addEventListener('dragleave', () => el.classList.remove('drop'));
  el.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();   // not the chat's own attach drop (app-attach.js)
    el.classList.remove('drop');
    const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []).filter(f => /^image\//.test(f.type));
    if (files.length) artUpload(files);
  });
}

// The page shows the character's pictures too (header avatar, bubble avatars, stage): re-read them.
function artRefreshPage() {
  if (typeof loadCharacters !== 'function') return;
  loadCharacters().then(() => {
    const pid = typeof providerEl !== 'undefined' && providerEl ? providerEl.value : '';
    if (typeof updateBrandAvatar === 'function') updateBrandAvatar(pid);
    if (typeof updateStageBackground === 'function') updateStageBackground(pid);
    if (typeof loadVisualAdapterForCharacter === 'function') loadVisualAdapterForCharacter();
  });
}

// A path a finished job wrote into a character's gallery -> that character, so its card can open the modal there.
function artGalleryCharacter(paths) {
  for (const p of paths || []) {
    const m = /characters\/(char_[a-z0-9]+)\/gallery\//.exec(String(p));
    if (m) return m[1];
  }
  return '';
}
