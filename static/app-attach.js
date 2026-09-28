// app-attach.js -- the composer's + menu and file attachments (docs/plans/composer-plus-menu.md plus/B, plus/D).
//
// + opens the items of the current mode: work mode attaches files, private mode will give gifts (plus/F). A file
// is uploaded the moment it is attached (pick, drag and drop, or paste) and waits on the server as the session's
// pending attachment; the next message carries the list (chat_upload.take_pending), so the send path in app.js
// is unchanged. The tray above the composer shows the files; once the message goes, they move onto its bubble.
// The list inside a message is agent-facing text; on screen it is cards (splitAttachmentBlock).

const ATTACH_MAX = 10;
const ATTACH_MAX_BYTES = 20 * 1024 * 1024;
const ATTACH_HEAD = '[Attached files - read them with your file tools]';
// On-screen words, one place (localization l10n/C moves them into the catalog).
const ATTACH_TEXT = {
  file: '파일 첨부', gift: '선물하기', soon: '준비 중', open: '건넬 것 고르기',   // l10n-ok
  preview: '클릭하여 파일 미리보기', cancel: ' 첨부 취소', failed: '첨부 실패: ',   // l10n-ok
  tooBig: '파일이 너무 큽니다 (최대 20 MB)', max: (n) => '한 번에 ' + n + '개까지 첨부할 수 있어요.',   // l10n-ok
  privateNo: '사적 모드에서는 파일 대신 + 에서 선물을 건넬 수 있어요.',   // l10n-ok
};
let attachItems = [];          // {label, size, state: 'uploading'|'ready'|'error', file: server item, el}

const PLUS_ITEMS = {
  work: [{ id: 'file', icon: '📎', label: ATTACH_TEXT.file, run: () => attachPick() }],
  private: [{ id: 'gift', icon: '🎁', label: ATTACH_TEXT.gift, run: () => openGiftPicker() }],   // app-gift.js
};

function plusMode() {
  return (typeof sessionMode !== 'undefined' && sessionMode === 'private') ? 'private' : 'work';
}

// {text, files: [{path, mime, size}]}: the message without its attachment list, and the list.
function splitAttachmentBlock(text) {
  const s = String(text || '');
  const at = s.lastIndexOf(ATTACH_HEAD);
  if (at < 0) return { text: s, files: [] };
  const files = [];
  const rest = s.slice(at + ATTACH_HEAD.length).split('\n').filter(l => l.trim());
  for (const line of rest) {
    const m = /^- (.+) \(([^,()]+), ([^()]+)\)$/.exec(line.trim());
    if (!m) return { text: s, files: [] };          // not our list after all: show the text as it is
    files.push({ path: m[1], mime: m[2], size: m[3] });
  }
  return { text: s.slice(0, at).replace(/\s+$/, ''), files };
}

// The stored name carries a time stamp for uniqueness; the reader wants the name they attached.
function attachDisplayName(path) {
  const base = String(path || '').split('/').pop() || '';
  return base.replace(/^\d{8}-\d{6}(?:-\d+)?-/, '');
}

function renderAttachmentCards(bubble, files) {
  if (!bubble || !files || !files.length || bubble.querySelector('.attach-cards')) return;
  const box = document.createElement('div');
  box.className = 'attach-cards';
  files.forEach(f => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'attach-card';
    card.title = ATTACH_TEXT.preview;
    const name = document.createElement('span');
    name.className = 'attach-card-name';
    name.textContent = '📎 ' + (f.label || attachDisplayName(f.path));
    const size = document.createElement('span');
    size.className = 'attach-card-size';
    size.textContent = f.size || f.size_human || '';
    card.appendChild(name);
    card.appendChild(size);
    card.addEventListener('click', (e) => {
      e.stopPropagation();
      if (typeof openFilePreviewModal === 'function') openFilePreviewModal(f.path);
    });
    box.appendChild(card);
  });
  bubble.appendChild(box);
}

function attachTrayEl() {
  let tray = document.getElementById('attachTray');
  if (!tray) {
    const composer = document.querySelector('.composer');
    if (!composer || !composer.parentNode) return null;
    tray = document.createElement('div');
    tray.id = 'attachTray';
    tray.className = 'attach-tray';
    tray.hidden = true;
    composer.parentNode.insertBefore(tray, composer);
  }
  return tray;
}

function attachRedraw() {
  const tray = attachTrayEl();
  if (!tray) return;
  tray.textContent = '';
  attachItems.forEach(item => {
    const chip = document.createElement('span');
    chip.className = 'attach-chip ' + item.state;
    const label = document.createElement('span');
    label.className = 'attach-chip-name';
    label.textContent = (item.state === 'uploading' ? '⏳ ' : item.state === 'error' ? '⚠ ' : '📎 ') + item.label;
    label.title = item.error || item.label;
    const size = document.createElement('span');
    size.className = 'attach-chip-size';
    size.textContent = item.file ? item.file.size_human : '';
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'attach-chip-x';
    x.setAttribute('aria-label', item.label + ATTACH_TEXT.cancel);
    x.textContent = '✕';
    x.addEventListener('click', () => attachRemove(item));
    chip.appendChild(label);
    chip.appendChild(size);
    chip.appendChild(x);
    tray.appendChild(chip);
  });
  tray.hidden = attachItems.length === 0;
}

async function attachRemove(item) {
  attachItems = attachItems.filter(x => x !== item);
  attachRedraw();
  if (item.file && typeof sessionId !== 'undefined' && sessionId) {
    try {
      await api('/api/sessions/' + encodeURIComponent(sessionId) + '/upload/remove',
        { method: 'POST', body: JSON.stringify({ name: item.file.name }) });
    } catch (_) {}
  }
}

async function attachUpload(file, item) {
  try {
    const url = (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/sessions/'
      + encodeURIComponent(sessionId) + '/upload';
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name) },
      body: file,
    });
    const res = await r.json().catch(() => ({}));
    if (!r.ok || !res.ok) throw new Error(res.error || r.statusText);
    item.file = res.file;
    item.state = 'ready';
  } catch (e) {
    item.state = 'error';
    item.error = String(e.message || e);
    if (typeof addActivity === 'function') addActivity(ATTACH_TEXT.failed + item.label + ' — ' + item.error, 'warn');
  }
  attachRedraw();
}

function attachFiles(list) {
  const files = Array.from(list || []);
  if (!files.length) return;
  if (plusMode() !== 'work') {
    if (typeof addActivity === 'function') addActivity(ATTACH_TEXT.privateNo, 'warn');
    return;
  }
  if (typeof sessionId === 'undefined' || !sessionId) return;
  files.forEach(file => {
    if (attachItems.length >= ATTACH_MAX) {
      if (typeof addActivity === 'function') addActivity(ATTACH_TEXT.max(ATTACH_MAX), 'warn');
      return;
    }
    const item = { label: file.name || 'file', state: 'uploading' };
    attachItems.push(item);
    if (file.size > ATTACH_MAX_BYTES) {
      item.state = 'error';
      item.error = ATTACH_TEXT.tooBig;
      return;
    }
    attachUpload(file, item);
  });
  attachRedraw();
}

function attachPick() {
  let input = document.getElementById('attachFileInput');
  if (!input) {
    input = document.createElement('input');
    input.type = 'file';
    input.id = 'attachFileInput';
    input.multiple = true;
    input.hidden = true;
    input.addEventListener('change', () => { attachFiles(input.files); input.value = ''; });
    document.body.appendChild(input);
  }
  input.click();
}

function plusMenuToggle(btn, force) {
  let menu = document.getElementById('plusMenu');
  const open = force !== undefined ? force : !(menu && !menu.hidden);
  if (!open) { if (menu) menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); return; }
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'plusMenu';
    menu.className = 'plus-menu';
    menu.setAttribute('role', 'menu');
    btn.parentNode.insertBefore(menu, btn.nextSibling);
  }
  menu.textContent = '';
  PLUS_ITEMS[plusMode()].forEach(it => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'plus-item';
    b.setAttribute('role', 'menuitem');
    b.disabled = Boolean(it.soon);
    b.textContent = it.icon + ' ' + it.label + (it.soon ? ' · ' + it.soon : '');
    b.addEventListener('click', () => { plusMenuToggle(btn, false); if (it.run) it.run(); });
    menu.appendChild(b);
  });
  menu.hidden = false;
  btn.setAttribute('aria-expanded', 'true');
}

function initPlusMenu() {
  const composer = document.querySelector('.composer');
  const input = document.getElementById('input');
  if (!composer || !input || document.getElementById('plusBtn')) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.id = 'plusBtn';
  btn.className = 'plus-btn';
  btn.setAttribute('aria-label', ATTACH_TEXT.open);
  btn.setAttribute('aria-haspopup', 'menu');
  btn.setAttribute('aria-expanded', 'false');
  btn.textContent = '+';
  btn.addEventListener('click', (e) => { e.stopPropagation(); plusMenuToggle(btn); });
  composer.insertBefore(btn, input);
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('plusMenu');
    if (menu && !menu.hidden && !menu.contains(e.target)) plusMenuToggle(btn, false);
  });

  // Drag and drop anywhere on the page while the chat is open; the overlay says where it will go.
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  const onChat = () => typeof currentTab === 'undefined' || currentTab === 'chat';
  document.addEventListener('dragenter', (e) => {
    if (!hasFiles(e) || !onChat()) return;
    depth++;
    document.body.classList.add('attach-drop', plusMode() === 'work' ? 'attach-drop-ok' : 'attach-drop-no');
  });
  document.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) document.body.classList.remove('attach-drop', 'attach-drop-ok', 'attach-drop-no');
  });
  document.addEventListener('dragover', (e) => { if (hasFiles(e) && onChat()) e.preventDefault(); });
  document.addEventListener('drop', (e) => {
    if (!hasFiles(e) || !onChat()) return;
    e.preventDefault();
    depth = 0;
    document.body.classList.remove('attach-drop', 'attach-drop-ok', 'attach-drop-no');
    attachFiles(e.dataTransfer.files);
  });
  // A pasted screenshot or file is an attachment; pasted text stays text.
  input.addEventListener('paste', (e) => {
    const files = e.clipboardData && e.clipboardData.files;
    if (files && files.length) { e.preventDefault(); attachFiles(files); }
  });

  // The message went: the files the server attached to it move from the tray onto its bubble.
  const log = document.getElementById('log');
  if (log && typeof MutationObserver === 'function') {
    new MutationObserver((records) => {
      const ready = attachItems.filter(x => x.state === 'ready');
      if (!ready.length) return;
      records.forEach(r => r.addedNodes.forEach(n => {
        if (n.nodeType !== 1 || !n.classList || !n.classList.contains('user') || n !== log.lastElementChild) return;
        renderAttachmentCards(n, ready.map(x => ({ path: x.file.path, label: x.label, size: x.file.size_human })));
        attachItems = attachItems.filter(x => !ready.includes(x));
        attachRedraw();
      }));
    }).observe(log, { childList: true });
  }
}

if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('DOMContentLoaded', initPlusMenu);
}
