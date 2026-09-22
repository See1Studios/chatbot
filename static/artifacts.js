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

async function fetchArtifacts(silent) {
  if (!sessionId) return;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/artifacts');
    currentArtifacts = res.artifacts || [];
    artifactsTotal = res.total != null ? res.total : currentArtifacts.length;
    artifactsNextBefore = res.next_before || null;
    updateArtifactBadge();
    renderArtifacts();
  } catch (e) {
    if (!silent) addActivity('아티팩트 조회 실패: ' + (e.message || e));
  }
}

// 아티팩트 탭은 세션이 아니라 모든 세션 통틀어 최신순 -- 대화 탭의
// scroll-up-to-load-older(loadOlderHistory)와 같은 정책이지만, 대화는
// predecessor_session_id 체인을 걷는 것이고 이건 그냥 mtime 커서 페이지네이션
// (실장님 2026-09-18: "전체 세션 통틀어 최신순 무한 스크롤" -- 대화 탭 스크롤과는
// 무관하게 독립 동작으로 확인).
async function loadMoreArtifacts() {
  if (!sessionId || artifactsLoadingMore || !artifactsNextBefore) return;
  artifactsLoadingMore = true;
  const marker = document.createElement('div');
  marker.className = 'art-loading-marker';
  marker.textContent = '이전 아티팩트 불러오는 중…';
  if (artGrid) artGrid.appendChild(marker);
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/artifacts?before=' + encodeURIComponent(artifactsNextBefore));
    currentArtifacts = currentArtifacts.concat(res.artifacts || []);
    artifactsTotal = res.total != null ? res.total : artifactsTotal;
    artifactsNextBefore = res.next_before || null;
    renderArtifacts();
  } catch (e) {
    addActivity('아티팩트 추가 로드 실패: ' + (e.message || e));
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
    thumbWrap.title = '클릭하여 미리보기';

    if (item.kind === 'image') {
      const img = document.createElement('img');
      img.className = 'art-thumb';
      bindArtifactImg(img, item);
      thumbWrap.appendChild(img);
    } else {
      const icon = document.createElement('div');
      icon.className = 'art-file-icon';
      const iconChar = (item.kind === 'code') ? '💻' : '📄';
      icon.innerHTML = `<span style="font-size:2rem">${iconChar}</span><span class="art-file-ext">${escapeHtml(item.ext || 'FILE')}</span>`;
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
    viewBtn.textContent = '미리보기';
    viewBtn.onclick = () => openArtifactModal(item);

    const citeBtn = document.createElement('button');
    citeBtn.className = 'art-btn primary';
    citeBtn.type = 'button';
    citeBtn.textContent = '인용 💬';
    citeBtn.title = '채팅 입력창에 추가';
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
  if (inputEl.value.trim()) {
    inputEl.value = inputEl.value.trim() + '\n' + snippet + ' ';
  } else {
    inputEl.value = snippet + ' ';
  }
  closeArtifactModal();
  switchTab('chat');
  inputEl.focus();
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

async function openArtifactModal(item) {
  if (!item || !artModal) return;
  activeModalArtifact = item;
  modalCurrentText = '';
  const sizeLabel = item.size_human ? ` (${item.size_human})` : '';
  const displayLabel = item.label || item.name;
  if (modalTitle) {
    modalTitle.textContent = displayLabel + sizeLabel;
    modalTitle.onclick = async () => {
      const ok = await copyText(item.path || displayLabel);
      if (ok && typeof addActivity === 'function') addActivity('경로 복사 완료: ' + (item.path || displayLabel));
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
    } else if (item.is_text || item.kind === 'text') {
      modalBody.innerHTML = '<div style="color:var(--muted)">불러오는 중…</div>';
      try {
        let text = item.content;
        if (text == null && item.url) {
          const resp = await fetch(resolveArtifactUrl(item.url));
          if (!resp.ok) throw new Error(resp.statusText);
          text = await resp.text();
        }
        modalCurrentText = text || '';
        const isMd = (item.name || '').endsWith('.md') || (item.path || '').endsWith('.md');

        if (modalCopyBtn) {
          modalCopyBtn.style.display = 'inline-block';
          modalCopyBtn.textContent = '복사';
          modalCopyBtn.onclick = async () => {
            const ok = await copyText(modalCurrentText);
            modalCopyBtn.textContent = ok ? '완료!' : '실패';
            setTimeout(() => { if (modalCopyBtn) modalCopyBtn.textContent = '복사'; }, 1500);
          };
        }
        if (modalWrapBtn) {
          modalWrapBtn.style.display = isMd && modalMdMode === 'render' ? 'none' : 'inline-block';
          modalWrapBtn.textContent = modalIsWrap ? '줄바꿈 켜짐' : '줄바꿈 꺼짐';
          modalWrapBtn.onclick = () => {
            modalIsWrap = !modalIsWrap;
            modalWrapBtn.textContent = modalIsWrap ? '줄바꿈 켜짐' : '줄바꿈 꺼짐';
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
        modalBody.innerHTML = `<div style="color:var(--status-bad)">파일을 불러올 수 없습니다: ${escapeHtml(err.message)}</div>`;
      }
    } else {
      modalBody.innerHTML = '<div style="color:var(--muted);text-align:center;padding:2rem">미리보기를 지원하지 않는 파일 형식입니다.</div>';
    }
  }
  artModal.style.display = 'flex';
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
  if (modalTitle) modalTitle.textContent = '불러오는 중… (' + baseName + lineLabel + ')';
  if (modalDownload) modalDownload.style.display = 'none';
  if (modalCite) modalCite.style.display = 'none';
  if (modalBody) modalBody.innerHTML = '<div style="color:var(--muted)">파일을 읽는 중입니다…</div>';
  artModal.style.display = 'flex';
  try {
    const res = await api('/api/file/preview?path=' + encodeURIComponent(cleanPath));
    if (!res.ok) throw new Error(res.error || '접근이 거부되었거나 파일을 찾을 수 없습니다');
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
    if (modalTitle) modalTitle.textContent = '파일 미리보기 실패';
    if (modalBody) {
      modalBody.innerHTML = `<div style="color:var(--status-bad);text-align:center;padding:2rem">
        <div><strong>파일을 열 수 없습니다</strong></div>
        <div style="font-size:.85rem;color:var(--muted);margin-top:.5rem">${escapeHtml(err.message || String(err))}</div>
        <div style="font-size:.78rem;color:var(--muted);margin-top:.2rem">${escapeHtml(targetPath)}</div>
      </div>`;
    }
  }
}

function closeArtifactModal() {
  if (artModal) artModal.style.display = 'none';
  activeModalArtifact = null;
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
  if (e.key === 'Escape' && artModal && artModal.style.display !== 'none') {
    closeArtifactModal();
  }
});
