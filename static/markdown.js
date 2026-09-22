/* Markdown / mermaid / highlight — extracted from app.js (monolith-split Phase 2). */
if (window.marked) {
  try {
    marked.setOptions({ gfm: true, breaks: true });
  } catch (_) {}
}
let mermaidIdCounter = 0;
let mermaidLoadingPromise = null;

function ensureMermaidLoaded() {
  if (window.mermaid) return Promise.resolve(window.mermaid);
  if (mermaidLoadingPromise) return mermaidLoadingPromise;
  mermaidLoadingPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = './vendor/mermaid.min.js';
    script.onload = () => {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'loose',
          fontFamily: 'Noto Sans KR, system-ui, sans-serif'
        });
      } catch (_) {}
      resolve(window.mermaid);
    };
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return mermaidLoadingPromise;
}

async function renderMermaidIn(container) {
  if (!container) return;
  const nodes = container.querySelectorAll('pre.mermaid:not([data-processed="true"])');
  if (!nodes || nodes.length === 0) return;
  try {
    await ensureMermaidLoaded();
  } catch (err) {
    console.warn('Failed to load mermaid on demand:', err);
    return;
  }
  if (!window.mermaid) return;
  for (const el of nodes) {
    el.setAttribute('data-processed', 'true');
    const code = el.textContent.trim();
    if (!code) continue;
    const id = 'mermaid-' + (++mermaidIdCounter);
    try {
      const res = await mermaid.render(id, code);
      const svg = (res && res.svg) ? res.svg : res;
      if (svg) {
        const wrap = el.closest('.mermaid-wrap') || el.parentElement;
        if (wrap) wrap.innerHTML = svg;
        else el.outerHTML = svg;
      }
    } catch (err) {
      console.warn('Mermaid render error:', err);
      const errEl = document.getElementById('d' + id) || document.getElementById(id);
      if (errEl) errEl.remove();
      el.className = 'code';
    }
  }
}

function attachCodeCopyButtons(container) {
  if (!container) return;
  const pres = container.querySelectorAll('pre:not(.has-copy)');
  pres.forEach(pre => {
    if (pre.querySelector('.mermaid') || pre.classList.contains('mermaid')) return;
    pre.classList.add('has-copy');
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.type = 'button';
    btn.textContent = '복사';
    btn.onclick = async () => {
      const code = pre.querySelector('code');
      const text = (code || pre).innerText;
      const ok = await copyText(text);
      btn.textContent = ok ? '완료!' : '실패';
      setTimeout(() => { btn.textContent = '복사'; }, 1500);
    };
    pre.appendChild(btn);
  });
}

function highlightCodeIn(container) {
  // Gated to isFinal only (like renderMermaidIn) -- re-highlighting on every
  // streaming delta would re-run hljs over the whole block on each tick and
  // can momentarily mis-highlight code that's still mid-fence.
  if (!container || !window.hljs) return;
  const blocks = container.querySelectorAll('pre code:not(.hljs)');
  blocks.forEach(block => {
    const pre = block.closest('pre');
    if (!pre || pre.classList.contains('mermaid') || pre.closest('.mermaid-wrap')) return;
    try {
      hljs.highlightElement(block);
      // Read the language back off the class hljs itself just set --
      // covers both an explicit ```lang fence and hljs's own auto-detection,
      // so the badge is always accurate instead of only showing up for
      // explicitly-labeled fences.
      const m = block.className.match(/language-([\w+-]+)/);
      if (m && !pre.querySelector('.code-lang')) {
        const tag = document.createElement('span');
        tag.className = 'code-lang';
        tag.textContent = m[1];
        pre.appendChild(tag);
      }
    } catch (_) {}
  });
}

function openImageLightbox(url, alt) {
  if (!url) return;
  const name = (alt || url.split('/').pop() || '이미지').split('?')[0];
  openArtifactModal({ name, kind: 'image', url, size_human: '' });
}

function attachImageLightbox(container) {
  if (!container) return;
  container.querySelectorAll('img:not(.lightbox-bound)').forEach(img => {
    img.classList.add('lightbox-bound');
    img.addEventListener('click', () => openImageLightbox(img.currentSrc || img.src, img.alt));
  });
}

function isLocalOrFilePath(href) {
  if (!href) return false;
  if (href.startsWith('file://')) return true;
  if (href.startsWith('/') && !href.startsWith('//') && !href.startsWith('/api/') && !href.startsWith('/chat/')) {
    // Check if looks like a local file path
    return href.startsWith('/volume1/') || href.startsWith('/var/') || href.startsWith('/home/') || href.startsWith('/tmp/');
  }
  if (href.startsWith('~/')) return true;
  return false;
}

function attachFileLinkInterceptors(container) {
  if (!container || typeof openFilePreviewModal !== 'function') return;
  container.querySelectorAll('a:not(.file-link-bound)').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (isLocalOrFilePath(href)) {
      a.classList.add('file-link-bound');
      a.title = (a.title ? a.title + ' ' : '') + '(클릭하여 파일 미리보기)';
      a.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openFilePreviewModal(href);
      });
    }
  });
}

// Quick-reply chips. The agent ends a question with one line
//   <!--choices: 보기A | 보기B | 보기C-->
// (실장님: "의견을 물을 때 마지막에 선택지 버튼"). The marker never shows as text:
// it is cut from the rendered/copied body, including a half-streamed one, and
// becomes buttons once the message is final. '|' instead of JSON so a stray
// quote from the model cannot break it.
const CHOICES_TAIL = /\s*<!--\s*choices\s*:([^<>]*)-->\s*$/;
const CHOICES_OPEN = /\s*<!--\s*choices[^<>]*$/;
const CHOICES_MAX = 4;
function splitChoices(src) {
  const s = String(src || '');
  const m = CHOICES_TAIL.exec(s);
  if (m) {
    const choices = m[1].split('|').map(x => x.trim()).filter(Boolean).slice(0, CHOICES_MAX);
    return { text: s.slice(0, m.index), choices };
  }
  return { text: s.replace(CHOICES_OPEN, ''), choices: [] };
}

function pickChoice(label) {
  if (!label || typeof inputEl === 'undefined' || !inputEl || typeof send !== 'function') return;
  inputEl.value = label;
  send();
}

function renderChoiceChips(node, choices) {
  const md = node.querySelector('.md') || node;
  md.querySelectorAll('.choice-chips').forEach(el => el.remove());
  if (!choices.length) return;
  const row = document.createElement('div');
  row.className = 'choice-chips';
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', '선택지');
  choices.forEach(label => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'choice-chip';
    b.textContent = label;
    b.addEventListener('click', () => pickChoice(label));
    row.appendChild(b);
  });
  md.appendChild(row);
}

// Only the newest message may offer choices: once anything follows (the user's
// answer, a new turn's progress bubble), older chips are stale. Called after
// every insert so history loads and live turns end up the same.
function syncChoiceChips() {
  if (typeof logEl === 'undefined' || !logEl) return;
  const msgs = logEl.querySelectorAll('.msg:not(.system)');
  const last = msgs.length ? msgs[msgs.length - 1] : null;
  logEl.querySelectorAll('.choice-chips').forEach(row => {
    if (!last || !last.contains(row)) row.remove();
  });
}

function postProcessAssistant(node, isFinal, rawText, usage, durationSeconds, skipFooter, servedModel) {
  if (!node) return;
  const parts = splitChoices(rawText);
  rawText = parts.text;
  node.classList.toggle('streaming', !isFinal);
  if (isFinal) {
    attachCodeCopyButtons(node);
    attachImageLightbox(node);
    attachFileLinkInterceptors(node);
    if (!skipFooter) renderChoiceChips(node, parts.choices);
    renderMermaidIn(node);
    highlightCodeIn(node);
    // Client-side system notices (/help, /status, /clear, stop confirmation)
    // reuse the assistant bubble's markdown rendering but aren't real LLM
    // replies -- no token badge / copy / TTS chips belong on them (실장님:
    // "시스템 메시지는 복사 스피커 등 추가 칩을 없애고 간결하게").
    if (!skipFooter) attachMessageFooter(node, rawText, usage, durationSeconds, servedModel);
  }
}

function dedupeMarkdownImages(md) {
  if (!md) return md;
  const seen = new Set();
  return md.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
    const cleanUrl = url.trim().split('?')[0];
    const base = cleanUrl.split('/').pop().toLowerCase();
    if (seen.has(base)) return '';
    seen.add(base);
    return match;
  });
}

function renderMarkdown(src, isFinal) {
  let raw = dedupeMarkdownImages(splitChoices(src).text);
  // Fix CommonMark/marked edge-case where bold ending in punctuation/parenthesis immediately followed by Korean josa fails to parse (e.g. **A(B)**를)
  raw = raw.replace(/(\*\*[^*\n]+?\))\*\*([가-힣])/g, '<strong>$1</strong>$2').replace(/<strong>\*\*/g, '<strong>');
  if (window.marked && typeof marked.parse === 'function') {
    try {
      let html = marked.parse(raw);
      html = html.replace(/<img\s+([^>]*?)src="([^"]+)"([^>]*?)>/g, (_, p1, u, p2) => {
        return '<img ' + p1 + 'src="' + absArtifact(u) + '"' + p2 + ' loading="lazy">';
      });
      html = html.replace(/<a\s+([^>]*?)href="([^"]+)"([^>]*?)>/g, (_, p1, href, p2) => {
        if (isLocalOrFilePath(href)) {
          return '<a ' + p1 + 'href="' + href + '" class="local-file-link"' + p2 + '>';
        }
        return '<a ' + p1 + 'href="' + href + '" target="_blank" rel="noopener"' + p2 + '>';
      });
      if (isFinal) {
        html = html.replace(/<pre><code class="(?:language-)?mermaid">([\s\S]*?)<\/code><\/pre>/g, (_, code) => {
          const decoded = code.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
          return '<div class="mermaid-wrap"><pre class="mermaid">' + decoded + '</pre></div>';
        });
      }
      return html;
    } catch (e) {
      console.warn('marked parse error:', e);
    }
  }
  let t = raw.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    const u = absArtifact(url.trim());
    return '<img src="' + u + '" alt="' + (alt || '') + '">';
  });
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  t = t.replace(/```([\s\S]*?)```/g, (_, code) => '<pre><code>' + code.replace(/</g,'&lt;') + '</code></pre>');
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/\n/g, '<br>');
  return t;
}
