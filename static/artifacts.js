/* Artifacts tab — extracted from app.js (monolith-split Phase 2). */
var artBadge = document.getElementById('artBadge');
var artifactsEl = document.getElementById('artifacts');
var artGrid = document.getElementById('artGrid');
var artEmpty = document.getElementById('artEmpty');
var artRefreshBtn = document.getElementById('artRefreshBtn');
var artModal = document.getElementById('artModal');
var modalTitle = document.getElementById('modalTitle');
var modalBody = document.getElementById('modalBody');
var modalDownload = document.getElementById('modalDownload');
var modalCite = document.getElementById('modalCite');
var modalClose = document.getElementById('modalClose');
var currentArtifacts = [];
var currentArtFilter = 'all';
var artifactsTotal = 0;
var artifactsNextBefore = null;
var artifactsLoadingMore = false;
var activeModalArtifact = null;
var lastArtifactTargetKey = '';

function activeArtifactOwner() {
  const rid = typeof roomOpenId === 'function' ? roomOpenId() : '';
  if (rid) return { type: 'room', id: rid, url: '/api/rooms/' + encodeURIComponent(rid) + '/artifacts' };
  const sid = typeof sessionId !== 'undefined' ? sessionId : '';
  if (sid) return { type: 'session', id: sid, url: '/api/sessions/' + encodeURIComponent(sid) + '/artifacts' };
  return null;
}

function checkArtifactTargetSwitch(target) {
  const key = target ? (target.type + ':' + target.id) : '';
  if (key !== lastArtifactTargetKey) {
    lastArtifactTargetKey = key;
    currentArtifacts = [];
    artifactsTotal = 0;
    artifactsNextBefore = null;
    artifactsLoadingMore = false;
    updateArtifactBadge();
    renderArtifacts();
    return true;
  }
  return false;
}

async function fetchArtifacts(silent) {
  const target = activeArtifactOwner();
  checkArtifactTargetSwitch(target);
  if (!target) return;
  const reqKey = target.type + ':' + target.id;
  try {
    const res = await api(target.url);
    const curOwner = activeArtifactOwner();
    const curKey = curOwner ? (curOwner.type + ':' + curOwner.id) : '';
    if (curKey !== reqKey) return;
    currentArtifacts = res.artifacts || [];
    artifactsTotal = res.total != null ? res.total : currentArtifacts.length;
    artifactsNextBefore = res.next_before || null;
    updateArtifactBadge();
    renderArtifacts();
  } catch (e) {
    const curOwner = activeArtifactOwner();
    const curKey = curOwner ? (curOwner.type + ':' + curOwner.id) : '';
    if (curKey !== reqKey) return;
    if (!silent && typeof failNotice === 'function') failNotice(tr('artifacts.load_failed'), e);
  }
}

// The artifacts tab is newest-first across all sessions -- the same policy as the chat tab's
// scroll-up-to-load-older (loadOlderHistory), but the chat walks the predecessor_session_id chain and this
// is plain mtime cursor paging (operator 2026-09-18: "newest first across all sessions, endless scroll" --
// checked to work apart from the chat tab's scroll; ticket #575 isolates it per room).
async function loadMoreArtifacts() {
  const target = activeArtifactOwner();
  if (!target || artifactsLoadingMore || !artifactsNextBefore) return;
  artifactsLoadingMore = true;
  const reqKey = target.type + ':' + target.id;
  const marker = document.createElement('div');
  marker.className = 'art-loading-marker';
  marker.textContent = tr('artifacts.loading_older');
  if (artGrid) artGrid.appendChild(marker);
  try {
    const sep = target.url.includes('?') ? '&' : '?';
    const res = await api(target.url + sep + 'before=' + encodeURIComponent(artifactsNextBefore));
    const curOwner = activeArtifactOwner();
    const curKey = curOwner ? (curOwner.type + ':' + curOwner.id) : '';
    if (curKey !== reqKey) return;
    currentArtifacts = currentArtifacts.concat(res.artifacts || []);
    artifactsTotal = res.total != null ? res.total : artifactsTotal;
    artifactsNextBefore = res.next_before || null;
    renderArtifacts();
  } catch (e) {
    const curOwner = activeArtifactOwner();
    const curKey = curOwner ? (curOwner.type + ':' + curOwner.id) : '';
    if (curKey === reqKey && typeof failNotice === 'function') {
      failNotice(tr('artifacts.more_failed'), e);
    }
  } finally {
    marker.remove();
    artifactsLoadingMore = false;
  }
}

if (artifactsEl) {
  artifactsEl.addEventListener('scroll', () => {
    if (currentTab !== 'artifacts') return;
    if (artifactsEl.scrollTop + artifactsEl.clientHeight >= artifactsEl.scrollHeight - 150) {
      loadMoreArtifacts();
    }
  });
}

function updateArtifactBadge() {
  if (!artBadge) return;
  const count = artifactsTotal;
  artBadge.textContent = count > 0 ? String(count) : '';
}

function resolveArtifactUrl(u) {
  if (!u) return '';
  if (/^(?:[a-z]+:)?\/\//i.test(u) || u.startsWith('data:') || u.startsWith('blob:')) return u;
  const base = (typeof BASE_PATH !== 'undefined' ? BASE_PATH : '').replace(/\/+$/, '');
  const clean = u.startsWith('/') ? u : '/' + u;
  return base ? (clean.startsWith(base + '/') ? clean : base + clean) : clean;
}

function artifactUrlFallbacks(item) {
  const name = (item && item.name) || '';
  const seen = new Set();
  const out = [];
  function add(u) {
    const resolved = resolveArtifactUrl(u);
    if (!resolved || seen.has(resolved)) return;
    seen.add(resolved);
    out.push(resolved);
  }
  add(item && item.url);
  if (name) {
    add('/persona/gallery/' + name);
    add('/artifacts/persona/' + name);
  }
  return out;
}

function bindArtifactImg(img, item) {
  const chain = artifactUrlFallbacks(item);
  let i = 0;
  img.alt = (item && item.name) || '';
  img.loading = 'lazy';
  img.onerror = function () {
    i += 1;
    while (i < chain.length && chain[i] === img.getAttribute('src')) i += 1;
    if (i >= chain.length) {
      img.onerror = null;
      return;
    }
    img.src = chain[i];
  };
  img.src = chain[0] || '';
}

function renderArtifacts() {
  if (!artGrid) return;
  artGrid.innerHTML = '';

  const filtered = currentArtifacts.filter(a => {
    if (currentArtFilter === 'image') return a.kind === 'image';
    if (currentArtFilter === 'document') return a.kind !== 'image';
    return true;
  });

  if (filtered.length === 0) {
    if (artEmpty) artEmpty.style.display = 'block';
    return;
  }
  if (artEmpty) artEmpty.style.display = 'none';

  for (const item of filtered) {
    const card = document.createElement('div');
    card.className = 'art-card';

    const thumbWrap = document.createElement('div');
    thumbWrap.className = 'art-thumb-wrap';
    thumbWrap.title = tr('artifacts.click_preview');

    if (item.kind === 'image') {
      const img = document.createElement('img');
      img.className = 'art-thumb';
      bindArtifactImg(img, item);
      thumbWrap.appendChild(img);
    } else {
      const icon = document.createElement('div');
      icon.className = 'art-file-icon';
      const iconName = (item.kind === 'code') ? 'code' : 'file';
      const svg = (typeof getActionSvg === 'function') ? getActionSvg(iconName) : '';
      icon.innerHTML = `${svg}<span class="art-file-ext">${escapeHtml(item.ext || 'FILE')}</span>`;
      thumbWrap.appendChild(icon);
    }
    thumbWrap.onclick = () => openArtifactModal(item);

    const info = document.createElement('div');
    info.className = 'art-info';
    info.innerHTML = `
      <div class="art-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
      <div class="art-sub">
        <span>${escapeHtml(item.size_human || '')}</span>
        <span>${escapeHtml(item.date || '')}</span>
      </div>
    `;

    const actions = document.createElement('div');
    actions.className = 'art-actions';

    const viewBtn = document.createElement('button');
    viewBtn.className = 'art-btn';
    viewBtn.type = 'button';
    viewBtn.textContent = tr('modal.render');
    viewBtn.onclick = () => openArtifactModal(item);

    const citeBtn = document.createElement('button');
    citeBtn.className = 'art-btn primary';
    citeBtn.type = 'button';
    citeBtn.textContent = tr('artifacts.cite');
    citeBtn.title = tr('artifacts.cite_hint');
    citeBtn.onclick = () => citeArtifact(item);

    actions.appendChild(viewBtn);
    actions.appendChild(citeBtn);

    card.appendChild(thumbWrap);
    card.appendChild(info);
    card.appendChild(actions);

    artGrid.appendChild(card);
  }
}

function citeArtifact(item) {
  if (!item) return;
  const snippet = item.kind === 'image'
    ? `![${item.stem || item.name}](${item.url})`
    : `[${item.name}](${item.url})`;
  const text = inputEl.value.trim() ? inputEl.value.trim() + '\n' + snippet + ' ' : snippet + ' ';
  closeArtifactModal();
  switchTab('chat');
  if (typeof fillComposer === 'function') fillComposer(text);   // FILL_COMPOSER_v1: the send button wakes
  else { inputEl.value = text; inputEl.focus(); }
}

var modalCopyBtn = document.getElementById('modalCopyBtn');
var modalWrapBtn = document.getElementById('modalWrapBtn');
var modalMdToggle = document.getElementById('modalMdToggle');
var modalViewRender = document.getElementById('modalViewRender');
var modalViewRaw = document.getElementById('modalViewRaw');
var modalIsWrap = true;
var modalCurrentText = '';
var modalMdMode = 'render';
var modalHighlightLines = null; // { start: number, end: number }

function buildCodeViewWithLines(text, hl) {
  const wrap = document.createElement('div');
  wrap.className = 'file-preview-wrap';
  const pre = document.createElement('pre');
  if (!modalIsWrap) pre.classList.add('nowrap');

  const lines = (text || '').split('\n');
  const lineNumDiv = document.createElement('div');
  lineNumDiv.className = 'line-numbers';

  const numElements = [];
  for (let idx = 1; idx <= lines.length; idx++) {
    const span = document.createElement('span');
    span.style.display = 'block';
    span.textContent = String(idx);
    if (hl && idx >= hl.start && idx <= hl.end) {
      span.className = 'ln-active';
    }
    lineNumDiv.appendChild(span);
  }

  const code = document.createElement('code');
  code.textContent = text || '';

  pre.appendChild(lineNumDiv);
  pre.appendChild(code);
  wrap.appendChild(pre);

  if (window.hljs) {
    try { hljs.highlightElement(code); } catch (_) {}
  } else if (typeof ensureHighlightLoaded === 'function') {   // HIGHLIGHT_LAZY_v1 (markdown.js)
    ensureHighlightLoaded().then(h => { try { h.highlightElement(code); } catch (_) {} }).catch(() => {});
  }

  // Scroll to highlight target line
  if (hl && hl.start) {
    setTimeout(() => {
      const targetSpan = lineNumDiv.children[hl.start - 1];
      if (targetSpan && pre) {
        pre.scrollTop = Math.max(0, targetSpan.offsetTop - pre.offsetTop - 50);
      }
    }, 50);
  }
  return wrap;
}

function renderModalTextContent(isMd) {
  if (!modalBody) return;
  modalBody.innerHTML = '';
  if (isMd && modalMdMode === 'render' && window.marked && !modalHighlightLines) {
    const wrap = document.createElement('div');
    wrap.className = 'file-preview-wrap';
    const mdDiv = document.createElement('div');
    mdDiv.className = 'file-preview-md';
    mdDiv.innerHTML = renderMarkdown(modalCurrentText || '', true);
    wrap.appendChild(mdDiv);
    modalBody.appendChild(wrap);
  } else {
    modalBody.appendChild(buildCodeViewWithLines(modalCurrentText, modalHighlightLines));
  }
}

// Unified helper: extract name/ext/kind from a URL string. Known text/code extensions get
// is_text: true for fetch preview; binary formats (video, audio, pdf, archive, etc.) get
// their own kind and is_text: false so the viewer never tries to fetch them as text.
function inferArtifactFromUrl(url) {
  let name;
  try { name = decodeURIComponent((url || '').split('?')[0].split('/').pop() || 'artifact'); }
  catch (_) { name = (url || '').split('?')[0].split('/').pop() || 'artifact'; }
  const ext = (name.match(/\.([a-z0-9]+)$/i) || [])[1] || '';
  const el = ext.toLowerCase();
  if (/^(png|jpe?g|gif|webp|svg|ico|bmp|tiff?)$/i.test(el)) return { name, ext, kind: 'image', is_text: false };
  if (/^(mp4|webm|mov|avi|mkv|flv|wmv|m4v|3gp)$/i.test(el)) return { name, ext, kind: 'video', is_text: false };
  if (/^(mp3|wav|ogg|flac|aac|wma|m4a|opus)$/i.test(el)) return { name, ext, kind: 'audio', is_text: false };
  if (el === 'pdf') return { name, ext, kind: 'pdf', is_text: false };
  if (/^(zip|tar|gz|bz2|7z|rar|xz|zst|tgz|whl|egg|deb|rpm)$/i.test(el)) return { name, ext, kind: 'other', is_text: false };
  if (/^(exe|dll|so|dylib|bin|dat|img|iso|dmg|wasm)$/i.test(el)) return { name, ext, kind: 'other', is_text: false };
  if (/^(py|js|mjs|ts|tsx|jsx|gd|sh|sql|css|html|java|c|cpp|h|hpp|rs|go|rb|php|swift|kt|scala|r|lua|pl|zig)$/i.test(el)) return { name, ext, kind: 'code', is_text: true };
  if (/^(json|jsonl|ya?ml|toml|ini|cfg|conf|xml|csv|txt|md|rst|log|env|properties|editorconfig|gitignore|dockerignore|makefile)$/i.test(el)) return { name, ext, kind: 'document', is_text: true };
  // Unknown extension: treat as other (binary-safe) — no text fetch
  if (el) return { name, ext, kind: 'other', is_text: false };
  // No extension at all: assume text document
  return { name, ext: '', kind: 'document', is_text: true };
}

async function openArtifactModal(item) {
  if (!item || !artModal) return;
  if (typeof item === 'string') {
    const url = item;
    item = { url, ...inferArtifactFromUrl(url) };
  } else if (item && typeof item === 'object' && !item.kind && item.url) {
    const inferred = inferArtifactFromUrl(item.url);
    // Keep caller-supplied name/ext if present; fill gaps from inference
    item = { ...inferred, ...item, kind: item.kind || inferred.kind, is_text: inferred.is_text };
    if (!item.ext) item.ext = inferred.ext;
  }
  if (item && item.url && typeof currentArtifacts !== 'undefined' && Array.isArray(currentArtifacts)) {
    const match = currentArtifacts.find(a => a && (a.url === item.url || (typeof resolveArtifactUrl === 'function' && resolveArtifactUrl(a.url) === resolveArtifactUrl(item.url))));
    if (match) item = { ...item, ...match };
  }
  activeModalArtifact = item;
  modalCurrentText = '';
  const sizeLabel = item.size_human ? ` (${item.size_human})` : '';
  const displayLabel = item.label || item.name;
  if (modalTitle) {
    modalTitle.textContent = displayLabel + sizeLabel;
    modalTitle.onclick = async () => {
      const ok = await copyText(item.path || displayLabel);
      if (ok && typeof addActivity === 'function') addActivity(tr('artifacts.path_copied', { path: item.path || displayLabel }));
    };
  }
  if (modalDownload) {
    const dUrl = resolveArtifactUrl(item.url || item.raw_url);
    modalDownload.href = dUrl || '#';
    modalDownload.setAttribute('download', item.name);
    modalDownload.style.display = dUrl ? 'inline-flex' : 'none';
  }
  if (modalCite) {
    modalCite.style.display = item.url ? 'inline-flex' : 'none';
  }

  // Reset toolbar buttons
  if (modalCopyBtn) modalCopyBtn.style.display = 'none';
  if (modalWrapBtn) modalWrapBtn.style.display = 'none';
  if (modalMdToggle) modalMdToggle.style.display = 'none';

  if (modalBody) {
    modalBody.innerHTML = '';
    if (item.kind === 'image') {
      const img = document.createElement('img');
      bindArtifactImg(img, item);
      modalBody.appendChild(img);
    } else if (item.is_text || item.kind === 'text' || item.kind === 'document' || item.kind === 'code') {
      modalBody.innerHTML = '<div style="color:var(--muted)">' + tr('common.loading') + '</div>';
      try {
        let text = item.content;
        if (text == null && item.url) {
          const resp = await fetch(resolveArtifactUrl(item.url));
          if (!resp.ok) throw new Error(resp.statusText);
          text = await resp.text();
        }
        modalCurrentText = text || '';
        const isMd = (item.name || '').endsWith('.md') || (item.path || '').endsWith('.md') || (item.url || '').split('?')[0].endsWith('.md');

        if (modalCopyBtn) {
          modalCopyBtn.style.display = 'inline-block';
          modalCopyBtn.textContent = tr('common.copy');
          modalCopyBtn.onclick = async () => {
            const ok = await copyText(modalCurrentText);
            modalCopyBtn.textContent = ok ? tr('artifacts.copied') : tr('common.failed');
            setTimeout(() => { if (modalCopyBtn) modalCopyBtn.textContent = tr('common.copy'); }, 1500);
          };
        }
        if (modalWrapBtn) {
          modalWrapBtn.style.display = isMd && modalMdMode === 'render' ? 'none' : 'inline-block';
          modalWrapBtn.textContent = modalIsWrap ? tr('modal.wrap_on') : tr('modal.wrap_off');
          modalWrapBtn.onclick = () => {
            modalIsWrap = !modalIsWrap;
            modalWrapBtn.textContent = modalIsWrap ? tr('modal.wrap_on') : tr('modal.wrap_off');
            renderModalTextContent(isMd);
          };
        }
        if (isMd && modalMdToggle) {
          modalMdToggle.style.display = 'inline-flex';
          modalMdMode = 'render';
          if (modalViewRender) {
            modalViewRender.classList.add('on');
            modalViewRender.onclick = () => {
              modalMdMode = 'render';
              modalViewRender.classList.add('on');
              if (modalViewRaw) modalViewRaw.classList.remove('on');
              if (modalWrapBtn) modalWrapBtn.style.display = 'none';
              renderModalTextContent(true);
            };
          }
          if (modalViewRaw) {
            modalViewRaw.classList.remove('on');
            modalViewRaw.onclick = () => {
              modalMdMode = 'raw';
              modalViewRaw.classList.add('on');
              if (modalViewRender) modalViewRender.classList.remove('on');
              if (modalWrapBtn) modalWrapBtn.style.display = 'inline-block';
              renderModalTextContent(true);
            };
          }
        }

        renderModalTextContent(isMd);
      } catch (err) {
        modalBody.innerHTML = `<div style="color:var(--status-bad)">${escapeHtml(tr('modal.load_failed', { error: err.message }))}</div>`;
      }
    } else {
      modalBody.innerHTML = '<div style="color:var(--muted);text-align:center;padding:2rem">' + tr('modal.unsupported') + '</div>';
    }
  }
  artModal.style.display = 'flex';
  artTakeFocus();
}

async function openFilePreviewModal(targetPath) {
  if (!artModal || !targetPath) return;
  activeModalArtifact = null;

  let cleanPath = targetPath;
  let hl = null;
  const hashIdx = targetPath.indexOf('#');
  if (hashIdx !== -1) {
    cleanPath = targetPath.slice(0, hashIdx);
    const hash = targetPath.slice(hashIdx);
    const m = hash.match(/#L(\d+)(?:-L?(\d+))?/i);
    if (m) {
      const s = parseInt(m[1], 10);
      const e = m[2] ? parseInt(m[2], 10) : s;
      hl = { start: Math.min(s, e), end: Math.max(s, e) };
    }
  }
  modalHighlightLines = hl;

  const baseName = cleanPath.split('/').pop() || cleanPath;
  const lineLabel = hl ? ` [L${hl.start}${hl.end !== hl.start ? '-' + hl.end : ''}]` : '';
  if (modalTitle) modalTitle.textContent = tr('modal.loading_file', { name: baseName + lineLabel });
  if (modalDownload) modalDownload.style.display = 'none';
  if (modalCite) modalCite.style.display = 'none';
  if (modalBody) modalBody.innerHTML = '<div style="color:var(--muted)">' + tr('modal.reading') + '</div>';
  artModal.style.display = 'flex';
  artTakeFocus();
  try {
    const res = await api('/api/file/preview?path=' + encodeURIComponent(cleanPath));
    if (!res.ok) throw new Error(res.error || tr('modal.denied'));
    openArtifactModal({
      name: res.name,
      label: (res.label || res.name) + lineLabel,
      kind: res.kind,
      is_text: res.is_text,
      content: res.content,
      raw_url: res.raw_url,
      size_human: res.size ? (res.size > 1048576 ? (res.size / 1048576).toFixed(1) + 'MB' : (res.size / 1024).toFixed(1) + 'KB') : '',
      url: res.raw_url,
    });
  } catch (err) {
    if (modalTitle) modalTitle.textContent = tr('modal.preview_failed');
    if (modalBody) {
      modalBody.innerHTML = `<div style="color:var(--status-bad);text-align:center;padding:2rem">
        <div><strong>${escapeHtml(tr('modal.cannot_open'))}</strong></div>
        <div style="font-size:.85rem;color:var(--muted);margin-top:.5rem">${escapeHtml(err.message || String(err))}</div>
        <div style="font-size:.78rem;color:var(--muted);margin-top:.2rem">${escapeHtml(targetPath)}</div>
      </div>`;
    }
  }
}

var artReturnFocus = null;

function artShown(el) {
  if (!el || el.disabled || el.hidden) return false;
  if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return false;
  if (el.style && el.style.display === 'none') return false;
  return true;
}

function artFocusables() {
  if (!artModal || typeof artModal.querySelectorAll !== 'function') return [];
  var nodes = artModal.querySelectorAll('button, a[href], input, textarea, select, [tabindex]');
  var out = [];
  for (var i = 0; i < nodes.length; i++) if (artShown(nodes[i])) out.push(nodes[i]);
  return out;
}

function artTakeFocus() {
  if (!artModal) return;
  var active = document.activeElement;
  var inside = !!(artModal.contains && active && artModal.contains(active));
  if (!inside && active && typeof active.focus === 'function') artReturnFocus = active;
  var list = artFocusables();
  var target = artShown(modalClose) ? modalClose : list[0];
  if (target && typeof target.focus === 'function') target.focus();
}

function artGiveFocusBack() {
  var back = artReturnFocus;
  artReturnFocus = null;
  if (!back || typeof back.focus !== 'function') return;
  if (typeof document.contains === 'function' && !document.contains(back)) return;
  try { back.focus(); } catch (e) {}
}

function closeArtifactModal() {
  if (artModal) artModal.style.display = 'none';
  activeModalArtifact = null;
  artGiveFocusBack();
}

document.querySelectorAll('.art-filter-btn[data-filter]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.art-filter-btn[data-filter]').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    currentArtFilter = btn.dataset.filter;
    renderArtifacts();
  });
});

if (artRefreshBtn) {
  artRefreshBtn.addEventListener('click', () => fetchArtifacts());
}

if (modalClose) {
  modalClose.addEventListener('click', closeArtifactModal);
}
if (modalCite) {
  modalCite.addEventListener('click', () => {
    if (activeModalArtifact) citeArtifact(activeModalArtifact);
  });
}
if (artModal) {
  artModal.addEventListener('click', (e) => {
    if (e.target === artModal) closeArtifactModal();
  });
}
window.addEventListener('keydown', (e) => {
  if (!artModal || !artModal.style || artModal.style.display === 'none') return;
  if (e.key === 'Escape') { closeArtifactModal(); return; }
  if (e.key !== 'Tab') return;
  var list = artFocusables();
  if (!list.length) { if (e.preventDefault) e.preventDefault(); return; }
  var i = list.indexOf(document.activeElement);
  var edge = e.shiftKey ? i <= 0 : (i < 0 || i >= list.length - 1);
  if (!edge) return;
  if (e.preventDefault) e.preventDefault();
  var dest = list[e.shiftKey ? list.length - 1 : 0];
  if (dest && dest.focus) dest.focus();
});

// Hook room lifecycle (roomEnter / roomClose) to trigger artifact drawer refresh and isolation
if (typeof roomEnter === 'function') {
  const _origRoomEnter = roomEnter;
  roomEnter = async function (...args) {
    const res = await _origRoomEnter.apply(this, args);
    if (res) {
      checkArtifactTargetSwitch(activeArtifactOwner());
      fetchArtifacts(true);
    }
    return res;
  };
}

if (typeof roomClose === 'function') {
  const _origRoomClose = roomClose;
  roomClose = function (...args) {
    const res = _origRoomClose.apply(this, args);
    checkArtifactTargetSwitch(activeArtifactOwner());
    fetchArtifacts(true);
    return res;
  };
}
