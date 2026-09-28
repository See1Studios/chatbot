// app-attach.js -- the small button inside the message box (docs/plans/composer-plus-menu.md plus/B, plus/D).
//
// Giving something is part of the message, so the button sits inside the input, not beside it: in work mode it
// attaches one file, in private mode it opens the gift picker (app-gift.js). A file is uploaded the moment it is
// attached (pick, drag and drop, or paste) and waits on the server as the session's pending attachment; the next
// message carries it (chat_upload.take_pending), so the send path in app.js is unchanged. While a file is attached
// the button becomes that file's icon (click: take it back); once the message goes, the file shows on its bubble.
// The list inside a message is agent-facing text; on screen it is a card (splitAttachmentBlock).

const ATTACH_MAX_BYTES = 20 * 1024 * 1024;
// Any header starting "[Attached files" is ours (chat_upload.ATTACH_HEAD; older messages keep an older wording).
const ATTACH_HEAD_RE = /\[Attached files[^\]\n]*\]/g;
// On-screen words, one place (localization l10n/C moves them into the catalog).
const ATTACH_TEXT = {
  attach: '파일 첨부', gift: '선물하기', remove: '클릭하여 첨부 취소', uploading: '올리는 중…',   // l10n-ok
  preview: '클릭하여 파일 미리보기', failed: '첨부 실패: ', one: '파일은 하나만 첨부할 수 있어요.',   // l10n-ok
  tooBig: '파일이 너무 큽니다 (최대 20 MB)', privateNo: '사적 모드에서는 파일 대신 선물을 건넬 수 있어요.',   // l10n-ok
  blind: '이 모델은 이미지를 볼 수 없어요 — 이미지를 보는 모델로 바꿔 주세요',   // l10n-ok
};
let attachItem = null;         // {label, state: 'uploading'|'ready'|'error', file: server item, error}
let attachSees = null;         // can the chosen model look at the attached image (null: not asked yet)
let attachSightKey = '';       // the provider|model it was asked for

function attachImageReady() {
  return Boolean(attachItem && attachItem.state === 'ready' && attachItem.file && /^image\//.test(attachItem.file.mime || ''));
}

// The placeholder's hint (app-turn.js refreshComposerPlaceholder): said where the reader is already looking, not in
// a toast. Asked again whenever the provider or model changes while an image is attached.
function composerHint() {
  if (!attachImageReady()) return '';
  const key = (typeof providerEl !== 'undefined' && providerEl ? providerEl.value : '') + '|' + (typeof modelEl !== 'undefined' && modelEl ? modelEl.value : '');
  if (key !== attachSightKey) {
    attachSightKey = key;
    attachSees = null;
    attachCheckSight(key);
  }
  return attachSees === false ? ATTACH_TEXT.blind : '';
}

async function attachCheckSight(key) {
  const [provider, model] = key.split('|');
  let sees = true;
  try {
    const r = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/sees-images?provider='
      + encodeURIComponent(provider) + '&model=' + encodeURIComponent(model));
    sees = r.sees !== false;
  } catch (_) {}
  if (key !== attachSightKey) return;                  // the model changed again meanwhile
  attachSees = sees;
  if (typeof refreshComposerPlaceholder === 'function') refreshComposerPlaceholder();
}

// {text, files: [{path, mime, size}]}: the message without its attachment list, and the list.
function splitAttachmentBlock(text) {
  const s = String(text || '');
  const heads = Array.from(s.matchAll(ATTACH_HEAD_RE));
  if (!heads.length) return { text: s, files: [] };
  const last = heads[heads.length - 1];
  const at = last.index;
  const files = [];
  const rest = s.slice(at + last[0].length).split('\n').filter(l => l.trim());
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

// Line icons in the page's own style (the tab icons: 24 grid, 2px stroke, round joins).
const ICON_PATHS = {
  clip: '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  gift: '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  text: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  film: '<rect x="2" y="3" width="20" height="18" rx="2"/><line x1="7" y1="3" x2="7" y2="21"/><line x1="17" y1="3" x2="17" y2="21"/><line x1="2" y1="12" x2="22" y2="12"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  table: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/>',
  archive: '<polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  loading: '<path d="M21 12a9 9 0 1 1-6.22-8.56"/>',
  alert: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
};
function iconSvg(key, cls) {
  return '<svg class="line-icon ' + (cls || '') + '" viewBox="0 0 24 24" aria-hidden="true">' + (ICON_PATHS[key] || ICON_PATHS.file) + '</svg>';
}

// One icon per kind of file, so the button says what is attached before anyone reads a name.
function attachIcon(name, mime) {
  const n = String(name || '').toLowerCase();
  const m = String(mime || '').toLowerCase();
  if (m.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg|bmp)$/.test(n)) return 'image';
  if (m.startsWith('audio/') || /\.(mp3|wav|ogg|m4a|flac)$/.test(n)) return 'music';
  if (m.startsWith('video/') || /\.(mp4|mov|webm|mkv)$/.test(n)) return 'film';
  if (/\.(csv|xlsx?|tsv)$/.test(n)) return 'table';
  if (/\.(zip|7z|tar|gz|rar)$/.test(n)) return 'archive';
  if (/\.(py|js|ts|tsx|jsx|json|sh|css|html|java|c|cpp|go|rs|rb|php)$/.test(n)) return 'code';
  if (m === 'application/pdf' || m.startsWith('text/') || /\.(pdf|md|txt|docx?|hwpx?|rtf)$/.test(n)) return 'text';
  return 'file';
}

function renderAttachmentCards(bubble, files) {
  if (!bubble || !files || !files.length || bubble.querySelector('.attach-cards')) return;
  const box = document.createElement('div');
  box.className = 'attach-cards';
  files.forEach(f => {
    const name = f.label || attachDisplayName(f.path);
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'attach-card';
    card.title = ATTACH_TEXT.preview;
    const icon = document.createElement('span');
    icon.className = 'attach-card-icon';
    icon.innerHTML = iconSvg(attachIcon(name, f.mime));   // constant markup, no user text
    const label = document.createElement('span');
    label.className = 'attach-card-name';
    label.textContent = name;
    card.appendChild(icon);
    const size = document.createElement('span');
    size.className = 'attach-card-size';
    size.textContent = f.size || '';
    // An image shows itself on the bubble (operator, 2026-09-28): a thumbnail from the file preview route, which
    // the server's allow-list guards like every other preview.
    if (attachIcon(name, f.mime) === 'image') {
      const img = document.createElement('img');
      img.className = 'attach-thumb';
      img.alt = name;
      img.loading = 'lazy';
      img.src = (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/file/raw?path=' + encodeURIComponent(f.path);
      img.addEventListener('error', () => { img.remove(); card.classList.remove('has-thumb'); });
      card.classList.add('has-thumb');
      card.appendChild(img);
    }
    card.appendChild(label);
    card.appendChild(size);
    card.addEventListener('click', (e) => {
      e.stopPropagation();
      if (typeof openFilePreviewModal === 'function') openFilePreviewModal(f.path);
    });
    box.appendChild(card);
  });
  bubble.appendChild(box);
}

function inlineMode() {
  return (typeof sessionMode !== 'undefined' && sessionMode === 'private') ? 'private' : 'work';
}

// True while a file is still on its way up: sending now would leave it for the next message.
function attachBusy() {
  return Boolean(attachItem && attachItem.state === 'uploading');
}

function redrawInlineButton() {
  const btn = document.getElementById('inlineBtn');
  if (!btn) return;
  btn.classList.remove('attached', 'uploading', 'error');
  if (inlineMode() === 'private') {
    btn.innerHTML = iconSvg('gift');
    btn.title = ATTACH_TEXT.gift;
    btn.setAttribute('aria-label', ATTACH_TEXT.gift);
  } else if (!attachItem) {
    btn.innerHTML = iconSvg('clip');
    btn.title = ATTACH_TEXT.attach;
    btn.setAttribute('aria-label', ATTACH_TEXT.attach);
  } else {
    const it = attachItem;
    btn.classList.add(it.state === 'ready' ? 'attached' : it.state);
    const face = it.state === 'uploading' ? 'loading' : it.state === 'error' ? 'alert' : attachIcon(it.label, it.file && it.file.mime);
    // the file's icon, and on hover an x: clicking takes the file back (constant markup, no user text)
    btn.innerHTML = iconSvg(face, 'face') + iconSvg('x', 'undo');
    const detail = it.state === 'uploading' ? ATTACH_TEXT.uploading : it.state === 'error' ? (it.error || '') : (it.file ? it.file.size_human : '');
    btn.title = it.label + (detail ? ' · ' + detail : '') + '\n' + ATTACH_TEXT.remove;
    btn.setAttribute('aria-label', it.label + ', ' + ATTACH_TEXT.remove);
  }
  if (typeof updateSendButton === 'function') updateSendButton();
  if (typeof refreshComposerPlaceholder === 'function') refreshComposerPlaceholder();
}

async function attachRemove() {
  const it = attachItem;
  attachItem = null;
  redrawInlineButton();
  if (it && it.file && typeof sessionId !== 'undefined' && sessionId) {
    try {
      await api('/api/sessions/' + encodeURIComponent(sessionId) + '/upload/remove',
        { method: 'POST', body: JSON.stringify({ name: it.file.name }) });
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
  if (attachItem !== item) {
    // replaced or taken back while it was uploading: remove the orphan from the server too
    if (item.state === 'ready') {
      api('/api/sessions/' + encodeURIComponent(sessionId) + '/upload/remove',
        { method: 'POST', body: JSON.stringify({ name: item.file.name }) }).catch(() => {});
    }
    return;
  }
  redrawInlineButton();
}

async function attachFiles(list) {
  const files = Array.from(list || []);
  if (!files.length) return;
  if (inlineMode() !== 'work') {
    if (typeof addActivity === 'function') addActivity(ATTACH_TEXT.privateNo, 'warn');
    return;
  }
  if (typeof sessionId === 'undefined' || !sessionId) return;
  if (files.length > 1 && typeof addActivity === 'function') addActivity(ATTACH_TEXT.one, 'warn');
  const file = files[0];
  if (attachItem) await attachRemove();                // one file: a new one replaces the old
  const item = { label: file.name || 'file', state: 'uploading' };
  attachItem = item;
  attachSightKey = '';
  if (file.size > ATTACH_MAX_BYTES) {
    item.state = 'error';
    item.error = ATTACH_TEXT.tooBig;
    redrawInlineButton();
    return;
  }
  redrawInlineButton();
  attachUpload(file, item);
}

function attachPick() {
  let input = document.getElementById('attachFileInput');
  if (!input) {
    input = document.createElement('input');
    input.type = 'file';
    input.id = 'attachFileInput';
    input.hidden = true;
    input.addEventListener('change', () => { attachFiles(input.files); input.value = ''; });
    document.body.appendChild(input);
  }
  input.click();
}

function initInlineButton() {
  const input = document.getElementById('input');
  if (!input || !input.parentNode || document.getElementById('inlineBtn')) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.id = 'inlineBtn';
  btn.className = 'inline-btn';
  // A sibling right after the textarea, drawn inside its right edge (chat-composer.css): wrapping the textarea
  // would break the phone layout, which orders the composer's children.
  input.parentNode.insertBefore(btn, input.nextSibling);
  input.classList.add('has-inline-btn');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (inlineMode() === 'private') { if (typeof openGiftPicker === 'function') openGiftPicker(); return; }
    if (attachItem) attachRemove(); else attachPick();
  });
  redrawInlineButton();
  // The mode can change under us (/private toggles body.private-session); the button follows it.
  if (typeof MutationObserver === 'function') {
    let wasPrivate = document.body.classList.contains('private-session');
    new MutationObserver(() => {
      const now = document.body.classList.contains('private-session');
      if (now !== wasPrivate) { wasPrivate = now; redrawInlineButton(); }
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  // Drag and drop anywhere on the page while the chat is open; the overlay says where it will go.
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  const onChat = () => typeof currentTab === 'undefined' || currentTab === 'chat';
  const clear = () => document.body.classList.remove('attach-drop', 'attach-drop-ok', 'attach-drop-no');
  document.addEventListener('dragenter', (e) => {
    if (!hasFiles(e) || !onChat()) return;
    depth++;
    document.body.classList.add('attach-drop', inlineMode() === 'work' ? 'attach-drop-ok' : 'attach-drop-no');
  });
  document.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) clear();
  });
  document.addEventListener('dragover', (e) => { if (hasFiles(e) && onChat()) e.preventDefault(); });
  document.addEventListener('drop', (e) => {
    if (!hasFiles(e) || !onChat()) return;
    e.preventDefault();
    depth = 0;
    clear();
    attachFiles(e.dataTransfer.files);
  });
  // A pasted screenshot or file is an attachment; pasted text stays text.
  input.addEventListener('paste', (e) => {
    const files = e.clipboardData && e.clipboardData.files;
    if (files && files.length) { e.preventDefault(); attachFiles(files); }
  });
  // Enter while the file is still uploading would send without it; the send button is disabled then too.
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && attachBusy()) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  // The message went: the attached file moves from the button onto its bubble.
  const log = document.getElementById('log');
  if (log && typeof MutationObserver === 'function') {
    new MutationObserver((records) => {
      if (!attachItem || attachItem.state !== 'ready') return;
      records.forEach(r => r.addedNodes.forEach(n => {
        // this window's own new bubble: a live one carries no time stamp yet (history and resync bubbles do), and
        // it need not be the log's last child -- progress and turn chrome are appended right after it
        if (!attachItem || n.nodeType !== 1 || !n.classList || !n.classList.contains('user') || (n.dataset && n.dataset.ts)) return;
        renderAttachmentCards(n, [{ path: attachItem.file.path, label: attachItem.label, mime: attachItem.file.mime,
                                    size: attachItem.file.size_human }]);
        attachItem = null;                              // the server already sent it with this message
        redrawInlineButton();
      }));
    }).observe(log, { childList: true });
  }
}

if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('DOMContentLoaded', initInlineButton);
}
