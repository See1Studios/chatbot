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
          securityLevel: 'strict',
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

// HIGHLIGHT_LAZY_v1: highlight.js (125 KB, a sixth of the page's script) arrives only when a code block is on
// screen -- private talk almost never has one. Same pattern as mermaid above.
let highlightLoadingPromise = null;
function ensureHighlightLoaded() {
  if (window.hljs) return Promise.resolve(window.hljs);
  if (highlightLoadingPromise) return highlightLoadingPromise;
  highlightLoadingPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = './vendor/highlight.min.js';
    script.onload = () => (window.hljs ? resolve(window.hljs) : reject(new Error('hljs missing')));
    script.onerror = reject;
    document.head.appendChild(script);
  }).catch((err) => { highlightLoadingPromise = null; throw err; });   // a later block may try again
  return highlightLoadingPromise;
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
  if (!container) return;
  const blocks = container.querySelectorAll('pre code:not(.hljs)');
  if (!blocks.length) return;
  if (!window.hljs) {   // HIGHLIGHT_LAZY_v1
    ensureHighlightLoaded().then(() => highlightCodeIn(container)).catch(() => {});
    return;
  }
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

// FILE_LINKS_v1 (2026-09-28): a path in an answer opens the file preview. Agents write paths in backticks
// (`static/app-sse.js`, `docs/plans/INDEX.md:120`, `tickets.py::claim`) or bare (~/services/x.md), and only
// explicit markdown links used to work -- and not even those for ~/ or relative hrefs, which the sanitiser
// drops. Recognition is here; whether a file may be shown is only the server's allow-list (preview_guard.py).
// Links are added to the sanitised DOM with createElement/textContent, so nothing here reaches innerHTML.
const FILE_EXTS = 'py|js|mjs|ts|tsx|jsx|md|json|jsonl|css|html|sh|txt|yml|yaml|toml|ini|cfg|conf|csv|log|sql|xml|webp|png|jpe?g|gif|svg|pdf';
const FILE_REF = new RegExp(
  '^(?:file://)?((?:~|\\.{1,2})?/?(?:[\\w.@+-]+/)*[\\w.@+-]*\\.(?:' + FILE_EXTS + ')|(?:~/(?:[\\w.@+-]+/)*|/(?:[\\w.@+-]+/)+)[\\w.@+-]+)' +
  '(?:(?::|#L)(\\d+)(?:-L?(\\d+))?|::[\\w.]+)?$', 'i');
const NOT_FILES = /^(?:\/(?:api|chat|artifacts)\/|\/\/|[a-z][a-z0-9+.-]*:\/\/(?!\/)|www\.)/i;

// {path, start, end} for a string that is one file reference, else null. A bare name ("app.js") counts only
// where the caller says so (a code span), because in prose "e.g." or "v1.2" is not a file.
function parseFileRef(text, allowBareName) {
  const t = String(text || '').trim();
  if (!t || t.length > 400 || /\s/.test(t) || NOT_FILES.test(t)) return null;
  const m = FILE_REF.exec(t);
  if (!m) return null;
  const path = m[1];
  if (!allowBareName && path.indexOf('/') < 0) return null;
  if (/^\/[^/]+$/.test(path)) return null;               // "/foo" alone is more often a command than a file
  const start = m[2] ? parseInt(m[2], 10) : 0;
  const end = m[3] ? parseInt(m[3], 10) : start;
  return { path: path.replace(/^file:\/\//, ''), start, end };
}

function fileRefTarget(ref) {
  return ref.start ? ref.path + '#L' + ref.start + (ref.end !== ref.start ? '-' + ref.end : '') : ref.path;
}

// Kept for the markdown-link rewrite below: an href is a local file when it parses as one.
function isLocalOrFilePath(href) {
  return Boolean(parseFileRef(href, true)) && !/^https?:/i.test(href || '');
}

function makeFileLink(ref, labelNode) {
  const a = document.createElement('a');
  a.className = 'local-file-link';
  a.setAttribute('href', '#');
  a.setAttribute('data-path', fileRefTarget(ref));
  a.appendChild(labelNode);
  return a;
}

// Bare paths in prose: only ones with a slash (~/x, /a/b, dir/file.ext), split out of their text node.
const BARE_PATH = /(^|[\s(（「『"'])((?:file:\/\/)?(?:~\/|\.{0,2}\/)?(?:[\w.@+-]+\/)+[\w.@+-]+(?:(?::|#L)\d+(?:-L?\d+)?|::[\w.]+)?)/g;

// [{at, token, ref}] for the file paths in a run of prose, in order.
function findBarePaths(text) {
  const out = [];
  let m;
  BARE_PATH.lastIndex = 0;
  while ((m = BARE_PATH.exec(String(text || '')))) {
    const token = m[2].replace(/[.,;:!?)）」』"']+$/, '');   // sentence punctuation is not the path's
    const ref = parseFileRef(token, false);
    if (ref) out.push({ at: m.index + m[1].length, token, ref });
  }
  return out;
}

function linkifyFilePaths(container) {
  if (!container || typeof document === 'undefined') return;
  // 1. A code span that is exactly one path.
  container.querySelectorAll('code').forEach(code => {
    if (code.closest && (code.closest('pre') || code.closest('a'))) return;
    const ref = parseFileRef(code.textContent, true);
    const parent = code.parentNode;
    if (!ref || !parent) return;
    const next = code.nextSibling;
    parent.removeChild(code);
    parent.insertBefore(makeFileLink(ref, code), next);   // the link wraps the code span, which keeps its look
  });
  // 2. Bare paths in text, outside links, code and pre.
  const walk = (el) => {
    Array.from(el.childNodes).forEach(n => {
      if (n.nodeType === 1) {
        if (/^(A|CODE|PRE|BUTTON|SCRIPT|STYLE)$/i.test(n.tagName || '')) return;
        walk(n);
        return;
      }
      if (n.nodeType !== 3 || !n.nodeValue || n.nodeValue.indexOf('/') < 0) return;
      const text = n.nodeValue;
      const hits = findBarePaths(text);
      if (!hits.length) return;
      const frag = document.createDocumentFragment();
      let last = 0;
      hits.forEach(h => {
        frag.appendChild(document.createTextNode(text.slice(last, h.at)));
        frag.appendChild(makeFileLink(h.ref, document.createTextNode(h.token)));
        last = h.at + h.token.length;
      });
      frag.appendChild(document.createTextNode(text.slice(last)));
      n.parentNode.replaceChild(frag, n);
    });
  };
  walk(container);
}

function attachFileLinkInterceptors(container) {
  if (!container || typeof openFilePreviewModal !== 'function') return;
  linkifyFilePaths(container.querySelector ? (container.querySelector('.md') || container) : container);
  container.querySelectorAll('a.local-file-link:not(.file-link-bound)').forEach(a => {
    const target = a.getAttribute('data-path') || a.getAttribute('href') || '';
    if (!target || target === '#') return;
    a.classList.add('file-link-bound');
    a.title = (a.title ? a.title + ' ' : '') + '(클릭하여 파일 미리보기)';
    a.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openFilePreviewModal(target);
    });
  });
}

// Quick-reply chips. The agent ends a question with one line
//   <!--choices: 보기A | 보기B | 보기C-->
// (operator: "의견을 물을 때 마지막에 선택지 버튼"). The marker never shows as text:
// it is cut from the rendered/copied body, including a half-streamed one, and
// becomes buttons once the message is final. '|' instead of JSON so a stray
// quote from the model cannot break it.
// The body may not cross another `<!--`: a reply that quotes the syntax earlier keeps its text.
const CHOICES_TAIL = /\s*<!--\s*choices\s*:((?:(?!<!--)[\s\S])*?)-->\s*$/;
const CHOICES_OPEN = /\s*<!--\s*choices(?:(?!-->)[\s\S])*$/;
const CHOICES_MAX = 4;
const EXPRESSION_HEAD = /^\s*\[expression:\s*([a-zA-Z]+)\]\s*/;
const EXPRESSION_EMOJIS = {
  neutral: '😐 차분',
  joy: '😊 미소',
  shy: '😳 수줍음',
  serious: '🧐 진지',
  sorrow: '🥺 서운',
  tired: '😮‍💨 피곤'
};

function parseExpression(text) {
  const s = String(text || '');
  const m = EXPRESSION_HEAD.exec(s);
  if (m) {
    return { expression: m[1].toLowerCase(), text: s.slice(m[0].length) };
  }
  return { expression: null, text: s };
}

const THOUGHT_STATE_BLOCK = /```state\s*\{[\s\S]*?"thought":\s*"([^"]+)"[\s\S]*?\}\s*```/i;
const THOUGHT_STATE_ANY = /```state\s*\{[\s\S]*?\}\s*```/iy;
const THOUGHT_TAG = /<thought(?:\s+[^>]*)?>([\s\S]*?)<\/thought>/iy;
const THOUGHT_OPEN_TAG = /<thought(?:\s+[^>]*)?>/iy;
// A strictly partial tag at the very end: '<' .. '<thought' (no '>') -- only a stream cut looks like this.
const THOUGHT_PARTIAL = /<(?:t(?:h(?:o(?:u(?:g(?:h(?:t(?:\s[^>]*)?)?)?)?)?)?)?)?$/iy;
// Legacy corrupt fragments (#187): '<thoug' + U+FFFD, '<thoug...>', an orphan '</thought>', a name cut by a non-word char.
const THOUGHT_FRAGMENT = /(?:<\/?(?:thought|though|thoug|thou)(?:�+|\.\.\.>?|(?=[^\w\s<>]))|<\/thought\s*>|<(?:though|thoug|thou)>)\s*/iy;
const THOUGHT_FENCE_INFO = /thought(?![\w-])/iy;

function stickyAt(re, s, i) {
  re.lastIndex = i;
  return re.exec(s);
}

function backtickRun(s, i) {
  let j = i;
  while (s[j] === '`') j++;
  return j - i;
}

// Single pass: code (inline spans, fences other than ```thought) is copied verbatim and never read
// as a thought marker; complete <thought>..</thought> pairs, ```thought fences and ```state blocks
// move to `thought`; an unclosed marker or a partial tag at the end is hidden only while streaming.
function parseThought(text, streaming) {
  const s = String(text || '');
  const thoughts = [];
  let out = '';
  let i = 0;
  const addThought = t => { if (t && t.trim()) thoughts.push(t.trim()); };
  while (i < s.length) {
    const c = s[i];
    if (c === '`') {
      const n = backtickRun(s, i);
      const lineStart = s.lastIndexOf('\n', i - 1) + 1;
      if (n >= 3 && /^ {0,3}$/.test(s.slice(lineStart, i))) {
        const st = n === 3 && stickyAt(THOUGHT_STATE_ANY, s, i);
        if (st) {
          const sm = THOUGHT_STATE_BLOCK.exec(st[0]);
          if (sm) addThought(sm[1]);
          i += st[0].length;
          continue;
        }
        if (stickyAt(THOUGHT_FENCE_INFO, s, i + n)) {
          const bodyStart = i + n + 'thought'.length;
          const close = new RegExp('`{' + n + ',}', 'g');
          close.lastIndex = bodyStart;
          const cm = close.exec(s);
          if (cm) {
            addThought(s.slice(bodyStart, cm.index));
            i = cm.index + cm[0].length;
            continue;
          }
          if (streaming) {
            addThought(s.slice(bodyStart));
            break;
          }
          out += s.slice(i);
          break;
        }
        const eol = s.indexOf('\n', i);
        const close = new RegExp('\\n {0,3}`{' + n + ',}[ \\t]*(?=\\n|$)', 'g');
        close.lastIndex = eol < 0 ? s.length : eol;
        const cm = eol < 0 ? null : close.exec(s);
        const end = cm ? cm.index + cm[0].length : s.length;
        out += s.slice(i, end);
        i = end;
        continue;
      }
      const run = /`+/g;
      run.lastIndex = i + n;
      let m;
      while ((m = run.exec(s)) !== null && m[0].length !== n) { /* skip runs of other lengths */ }
      if (m) {
        out += s.slice(i, m.index + n);
        i = m.index + n;
      } else {
        // Unmatched opener is literal text; keep scanning after it.
        out += s.slice(i, i + n);
        i += n;
      }
      continue;
    }
    if (c === '<') {
      let m = stickyAt(THOUGHT_TAG, s, i);
      if (m) {
        addThought(m[1]);
        i += m[0].length;
        continue;
      }
      if ((m = stickyAt(THOUGHT_OPEN_TAG, s, i))) {
        if (streaming) {
          addThought(s.slice(i + m[0].length));
          break;
        }
        out += m[0];
        i += m[0].length;
        continue;
      }
      if (streaming && stickyAt(THOUGHT_PARTIAL, s, i)) break;
      if ((m = stickyAt(THOUGHT_FRAGMENT, s, i))) {
        i += m[0].length;
        continue;
      }
    }
    out += c;
    i++;
  }
  return { thought: thoughts.length ? thoughts.join('\n') : null, cleanText: out.trim() };
}

function stripOuterParens(s) {
  // Balanced outer (...) only — do not eat trailing ) of an inner "(act)" in "line" (act).
  let out = String(s || '').trim();
  while (out.length >= 2 && out[0] === '(' && out[out.length - 1] === ')') {
    let depth = 0, balanced = true;
    for (let i = 0; i < out.length; i++) {
      const ch = out[i];
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0 && i !== out.length - 1) { balanced = false; break; }
        if (depth < 0) { balanced = false; break; }
      }
    }
    if (!balanced || depth !== 0) break;
    out = out.slice(1, -1).trim();
  }
  return out;
}

function classifyChoicePayload(rawPayload) {
  // Normalize curly/smart quotes and fullwidth parens so pure (행동) still → /act.
  // #246: ALL choice clicks are ACTIONS. Dialogue on a chip is optional flavor baked
  // into the action (/act wire) — NOT plain say. Real speech = user typing.
  let s = String(rawPayload || '').trim();
  if (!s) return { kind: 'say', payload: '', isAction: false };
  s = s
    .replace(/[\u201C\u201D\u201E\u201F\u2033\u2036]/g, '"')
    .replace(/[\u2018\u2019\u201A\u201B\u2032\u2035]/g, "'")
    .replace(/\uFF08/g, '(').replace(/\uFF09/g, ')');
  // Combined: "user line" (action) — still action; flavor baked in
  const combo = /^"([^"]*)"\s*\(([\s\S]+)\)\s*$/.exec(s);
  if (combo) {
    const line = combo[1].trim();
    const act = stripOuterParens(combo[2].trim());
    if (!line) return { kind: 'action', payload: act, action: act, isAction: true };
    const payload = '"' + line + '" (' + act + ')';
    return { kind: 'action', payload, action: payload, isAction: true };
  }
  // Action-only: (action) — silent /act. Also accept * (action) * italics wrappers.
  // Outer wrap may enclose dialogue-flavor or combo: ("line") / ("line" (act)).
  const actOnly = /^\*?\s*\(([\s\S]+)\)\s*\*?\s*$/.exec(s);
  if (actOnly) {
    const inner = actOnly[1].trim();
    const nestedCombo = /^"([^"]*)"\s*\(([\s\S]+)\)\s*$/.exec(inner);
    if (nestedCombo) {
      const line = nestedCombo[1].trim();
      const act = stripOuterParens(nestedCombo[2].trim());
      if (!line) return { kind: 'action', payload: act, action: act, isAction: true };
      const payload = '"' + line + '" (' + act + ')';
      return { kind: 'action', payload, action: payload, isAction: true };
    }
    const nestedSay = /^"([^"]*)"\s*$/.exec(inner);
    if (nestedSay) {
      const payload = '"' + nestedSay[1].trim() + '"';
      return { kind: 'action', payload, action: payload, isAction: true };
    }
    const act = stripOuterParens(inner);
    return { kind: 'action', payload: act, action: act, isAction: true };
  }
  // Dialogue-flavor: "user line" — still action (flavor), not composer say
  const sayOnly = /^"([^"]*)"\s*$/.exec(s);
  if (sayOnly) {
    const payload = '"' + sayOnly[1].trim() + '"';
    return { kind: 'action', payload, action: payload, isAction: true };
  }
  // Legacy mismatched quotes
  if (/^["'].*["']$/.test(s)) {
    const payload = '"' + s.slice(1, -1).trim() + '"';
    return { kind: 'action', payload, action: payload, isAction: true };
  }
  const bare = stripOuterParens(s);
  return { kind: 'action', payload: bare, action: bare, isAction: true };
}

const CHOICE_LABEL_MAX = 28;

function truncateChoiceLabel(s, max = CHOICE_LABEL_MAX) {
  const cap = typeof max === 'number' ? max : 28;
  const str = String(s || '').trim();
  return str.length <= cap ? str : str.slice(0, cap - 1) + '…';
}

function parseChoiceItem(item) {
  const maxLabel = typeof CHOICE_LABEL_MAX !== 'undefined' ? CHOICE_LABEL_MAX : 28;
  const truncate = (s) => (typeof truncateChoiceLabel === 'function'
    ? truncateChoiceLabel(s, maxLabel)
    : (String(s || '').trim().length <= maxLabel ? String(s || '').trim() : String(s || '').trim().slice(0, maxLabel - 1) + '…'));
  const unwrapParens = typeof stripOuterParens === 'function' ? stripOuterParens : (s) => {
    let out = String(s || '').trim();
    while (out.length >= 2 && out[0] === '(' && out[out.length - 1] === ')') {
      let depth = 0, balanced = true;
      for (let i = 0; i < out.length; i++) {
        if (out[i] === '(') depth++;
        else if (out[i] === ')') { depth--; if ((depth === 0 && i !== out.length - 1) || depth < 0) { balanced = false; break; } }
      }
      if (!balanced || depth !== 0) break;
      out = out.slice(1, -1).trim();
    }
    return out;
  };

  if (item && typeof item === 'object') {
    const rawLabel = String(item.label || '').trim();
    const label = truncate(rawLabel);
    let kind = String(item.kind || (item.isAction ? 'action' : 'say')).trim();
    let payload = item.payload !== undefined ? String(item.payload).trim() : String(item.action || rawLabel || '').trim();
    // Re-classify string payloads that still carry private-mode forms
    if (kind !== 'command' && /^(?:"[\s\S]*"|[\s\S]*\([\s\S]*\))/.test(payload)) {
      const c = classifyChoicePayload(payload);
      kind = c.kind;
      payload = c.payload;
      return { label, kind, payload, action: payload, isAction: kind === 'action' };
    }
    return { label, kind, payload, action: payload, isAction: kind === 'action' || Boolean(item.isAction) };
  }
  const raw = String(item || '').trim();
  if (!raw) return null;
  // Support "Label -> Action" or "Label -> action: Action" or "Label -> command: Command"
  const arrowIdx = raw.indexOf('->');
  if (arrowIdx > 0) {
    const rawLabel = raw.slice(0, arrowIdx).trim();
    const label = truncate(rawLabel);
    let action = raw.slice(arrowIdx + 2).trim();
    if (action.toLowerCase().startsWith('action:')) {
      const act = action.slice(7).trim().replace(/^\(+|\)+$/g, '').trim();
      return { label, action: act, payload: act, kind: 'action', isAction: true };
    }
    if (action.toLowerCase().startsWith('command:')) {
      const cmd = action.slice(8).trim();
      return { label, action: cmd, payload: cmd, kind: 'command', isAction: false };
    }
    const c = classifyChoicePayload(action);
    return { label, action: c.payload, payload: c.payload, kind: c.kind, isAction: c.isAction };
  }
  // Support "Label: action: Action"
  const colonAction = /^(.*?):\s*action:\s*(.*)$/i.exec(raw);
  if (colonAction) {
    const label = truncate(colonAction[1].trim());
    return { label, action: colonAction[2].trim(), payload: colonAction[2].trim(), kind: 'action', isAction: true };
  }

  // Arrow-less action/dialogue pattern or long plain text
  const norm = raw
    .replace(/[\u201C\u201D\u201E\u201F\u2033\u2036]/g, '"')
    .replace(/[\u2018\u2019\u201A\u201B\u2032\u2035]/g, "'")
    .replace(/\uFF08/g, '(').replace(/\uFF09/g, ')');
  const clean = (/^\*[\s\S]*\*$/.test(norm) && norm.length >= 2) ? norm.slice(1, -1).trim() : norm;
  const unwrapped = unwrapParens(clean);
  const hadParens = unwrapped !== clean;

  // 1. Combo: "dialogue" (action) or ("dialogue" (action))
  const combo = /^"([^"]*)"\s*\(([\s\S]+)\)\s*$/.exec(unwrapped);
  if (combo && (combo[1].trim() || unwrapParens(combo[2].trim()))) {
    const line = combo[1].trim(), act = unwrapParens(combo[2].trim());
    const rawLabel = line || act, payload = line ? ('"' + line + '" (' + act + ')') : ('(' + act + ')');
    return { label: truncate(rawLabel), action: payload, payload, kind: 'action', isAction: true };
  }

  // 2. Dialogue-only: "dialogue" or ("dialogue") or 'dialogue'
  const sayOnly = /^["']([^"']*)["']\s*$/.exec(unwrapped);
  if (sayOnly && sayOnly[1].trim()) {
    const line = sayOnly[1].trim(), payload = '"' + line + '"';
    return { label: truncate(line), action: payload, payload, kind: 'action', isAction: true };
  }

  // 3. Action-only: (action)
  if (hadParens && unwrapped && !/^\d+$|^[a-zA-Z]$/.test(unwrapped)) {
    const payload = '(' + unwrapped + ')';
    return { label: truncate(unwrapped), action: payload, payload, kind: 'action', isAction: true };
  }

  // 4. Long plain text defense (prevent button blowout on mobile)
  if (raw.length > maxLabel) {
    return { label: truncate(raw), action: raw, payload: raw, kind: 'say', isAction: false };
  }

  return raw;
}

function splitChoices(src) {
  const s = String(src || '');
  const m = CHOICES_TAIL.exec(s);
  if (m) {
    const choices = m[1].split('|').map(x => parseChoiceItem(x)).filter(Boolean).slice(0, CHOICES_MAX);
    return { text: s.slice(0, m.index), choices };
  }
  return { text: s.replace(CHOICES_OPEN, ''), choices: [] };
}

function pickChoice(choice) {
  if (!choice || typeof inputEl === 'undefined' || !inputEl) return;
  // If the chip already carries a classified action/command, honor it (avoid re-parse flipping
  // bare action payloads without parens into the wrong path).
  let item;
  if (choice && typeof choice === 'object' && (choice.kind === 'action' || choice.isAction === true || choice.kind === 'command' || choice.kind === 'say')) {
    item = {
      label: String(choice.label || '').trim(),
      kind: String(choice.kind || (choice.isAction ? 'action' : 'say')).trim(),
      payload: String(choice.payload !== undefined ? choice.payload : (choice.action || choice.label || '')).trim(),
      action: String(choice.action || choice.payload || choice.label || '').trim(),
      isAction: Boolean(choice.isAction) || choice.kind === 'action',
    };
    if (item.kind === 'action') item.isAction = true;
  } else {
    const parsed = parseChoiceItem(choice);
    item = typeof parsed === 'object' && parsed ? parsed : { label: String(choice), action: String(choice), kind: 'say', payload: String(choice) };
  }
  const kind = item.kind || (item.isAction ? 'action' : 'say');
  const payload = item.payload || item.action || item.label;

  if (kind === 'action' || item.isAction) {
    // #246: choices (incl. dialogue-flavor / combo) always go as action — never flip to say.
    const reclass = classifyChoicePayload(payload);
    const act = String(reclass.kind === 'action' ? reclass.payload : payload);
    const bare = (typeof stripOuterParens === 'function') ? stripOuterParens(act) : act.replace(/^\(+|\)+$/g, '').trim();
    // Keep dialogue-flavor / combo payload intact (starts with quote); bare actions lose outer wraps.
    const wire = /^"/.test(String(act).trim()) ? String(act).trim() : bare;
    if (typeof sendAction === 'function') {
      sendAction(wire);
      return;
    }
    inputEl.value = '/act ' + wire;
    sendPickedChoice();
    return;
  }
  if (kind === 'command') {
    const cmdText = payload.startsWith('/') ? payload : ('/' + payload);
    const ticketCmd = typeof parseTicketCommand === 'function' ? parseTicketCommand(cmdText) : null;
    if (ticketCmd) {   // TICKET_BUTTONS_v1: the one decision path (app-evolution.js), no bubble
      if (typeof runTicketDecision === 'function') runTicketDecision(ticketCmd, typeof tapSendOpts === 'function' ? tapSendOpts() : undefined);
      return;
    }
    inputEl.value = cmdText;
    sendPickedChoice();
    return;
  }

  // default: say
  inputEl.value = payload || item.label;
  sendPickedChoice();
}

// A chip tap is not typing: on touch devices send without refocusing inputEl (no keyboard pop).
function sendPickedChoice() {
  if (typeof send !== 'function') return;
  send(typeof tapSendOpts === 'function' ? tapSendOpts() : undefined);
}

function getChoiceBarEl() {
  if (typeof document !== 'undefined' && document && typeof document.getElementById === 'function') {
    const el = document.getElementById('choiceBar');
    if (el) return el;
  }
  if (typeof choiceBarEl !== 'undefined' && choiceBarEl) {
    return choiceBarEl;
  }
  return null;
}

function renderChoiceChips(node, choices, isPrepend) {
  const md = node ? (node.querySelector('.md') || node) : null;
  if (md) md.querySelectorAll('.choice-chips').forEach(el => el.remove());

  const isPrependState = Boolean(isPrepend || (node && (node._prepend || (node.dataset && node.dataset.prepend === '1'))));
  let isNotLatestAssistant = false;
  if (typeof logEl !== 'undefined' && logEl && node) {
    let msgs = [];
    if (typeof logEl.querySelectorAll === 'function') {
      try { msgs = logEl.querySelectorAll('.msg.assistant:not(.system)'); } catch (_) {}
      if (!msgs || !msgs.length) {
        const all = logEl.querySelectorAll('.msg:not(.system)') || [];
        msgs = Array.prototype.filter.call(all, m => /\bassistant\b/.test(m.className || '') && !/\bsystem\b/.test(m.className || ''));
      }
    }
    if (msgs && msgs.length) {
      const last = msgs[msgs.length - 1];
      let inLog = (typeof logEl.contains === 'function') ? logEl.contains(node) : false;
      if (!inLog) { for (let i = 0; i < msgs.length; i++) { if (msgs[i] === node) { inLog = true; break; } } }
      if (inLog && node !== last) isNotLatestAssistant = true;
    }
  }
  const skipBar = isPrependState || isNotLatestAssistant;

  const bar = skipBar ? null : getChoiceBarEl();
  if (bar) {
    if (bar.classList && typeof bar.classList.remove === 'function') {
      bar.classList.remove('closing');
    }
    bar.textContent = '';
    bar.hidden = true;
    bar._owner = null;
  }
  if (!choices || !choices.length) return;
  if (skipBar) return;

  const card = document.createElement('div');
  card.className = 'choice-card';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'choice-close-btn';
  closeBtn.setAttribute('aria-label', '내 다음 행동 닫기');
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', (e) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    if (bar) {
      if (bar.classList && typeof bar.classList.add === 'function') {
        bar.classList.add('closing');
      }
      const hideBar = () => {
        bar.hidden = true;
        if (typeof updateScrollBottomButton === 'function') updateScrollBottomButton();
        if (bar.classList && typeof bar.classList.remove === 'function') {
          bar.classList.remove('closing');
        }
        bar.textContent = '';
        bar._owner = null;
      };
      if (typeof setTimeout === 'function') {
        setTimeout(hideBar, 180);
      } else {
        hideBar();
      }
    } else if (card) {
      if (card.classList && typeof card.classList.add === 'function') {
        card.classList.add('closing');
        if (typeof setTimeout === 'function') {
          setTimeout(() => { if (typeof card.remove === 'function') card.remove(); }, 180);
        } else {
          if (typeof card.remove === 'function') card.remove();
        }
      } else if (typeof card.remove === 'function') {
        card.remove();
      }
    }
  });
  card.appendChild(closeBtn);

  const row = document.createElement('div');
  row.className = 'choice-card-body choice-chips';
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', '내 다음 행동');
  choices.forEach(c => {
    const parsed = parseChoiceItem(c);
    if (!parsed) return;
    const item = typeof parsed === 'string' ? { label: parsed, action: parsed, isAction: false, kind: 'say' } : parsed;
    const isAct = item.isAction || item.kind === 'action';
    const isCmd = item.kind === 'command';
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'choice-chip' + (isAct ? ' choice-action' : '') + (isCmd ? ' choice-command' : '');
    b.textContent = (isAct ? '✦ ' : '') + item.label;
    b.addEventListener('click', () => pickChoice(item));
    row.appendChild(b);
  });
  card.appendChild(row);

  if (bar) {
    bar.appendChild(card);
    bar.hidden = false;
    bar._owner = node;   // the card lives outside the bubble, so syncChoiceChips asks the bar whose it is
  } else if (md) {
    md.appendChild(card);
  }
}

// Only the newest message may offer choices: once anything follows (the user's
// answer, a new turn's progress bubble), older chips are stale. Called after
// every insert so history loads and live turns end up the same.
function syncChoiceChips() {
  if (typeof logEl === 'undefined' || !logEl) return;
  const msgs = logEl.querySelectorAll('.msg:not(.system)');
  const last = msgs.length ? msgs[msgs.length - 1] : null;
  const bar = getChoiceBarEl();
  const hasChoicesOnLast = last && ((last._choices && last._choices.length) || last.querySelector('.choice-chips') || (bar && bar._owner === last));
  const isAssistant = last && (last.classList ? last.classList.contains('assistant') : /\bassistant\b/.test(last.className || ''));
  if (!last || !isAssistant || !hasChoicesOnLast) {
    if (bar) {
      if (bar.classList && typeof bar.classList.remove === 'function') {
        bar.classList.remove('closing');
      }
      bar.textContent = '';
      bar.hidden = true;
      if (typeof updateScrollBottomButton === 'function') updateScrollBottomButton();
      bar._owner = null;
    }
  }
  logEl.querySelectorAll('.choice-chips').forEach(row => {
    if (!last || !last.contains(row)) {
      if (row.parentElement && row.parentElement.className === 'choice-card') {
        row.parentElement.remove();
      } else {
        row.remove();
      }
    }
  });
}

// The emoji alone of an expression label (EXPRESSION_EMOJIS holds "emoji word").
function expressionEmoji(expression) {
  const label = EXPRESSION_EMOJIS[expression];
  return label ? label.split(' ')[0] : '\u{1F3AD}';
}

function paintExpressionBadge(node, rawText) {
  // STREAM_FLOW_v1: the expression is the one piece of post-processing cheap enough to keep while the answer is
  // still streaming, so the character keeps showing how it feels while it speaks.
  // BUBBLE_AVATAR_v1: no chip in the text any more -- the bubble carries the expression and the character's
  // picture above its run shows it (chat-log.css). Attributes on the bubble outlive the text's re-renders.
  const parsedExp = parseExpression(rawText);
  if (!parsedExp.expression) return;
  node.dataset.expression = parsedExp.expression;
  node.dataset.exp = expressionEmoji(parsedExp.expression);
}

// STREAM_FLOW_v1: the cheap projection of a still-growing answer -- strip what the model emits as
// markup and hide the thought block the way the UI hides it mid-sentence, but do no markdown
// parsing and no sanitising. That work belongs to the final render, once, not to every frame.
// CHOICES_LEAK_RESCUE_v1: a choices tool call a model wrote into its answer as text is taken out on the
// server when the turn ends (providers/adapter_base.py::rescue_leaked_choices). While the answer is still
// arriving it is hidden from where it starts, so the JSON is never typed out on screen.
const LEAKED_TOOL_CALL = /\s*(?:<\/?tool_call>[\s\S]*|\{\s*"(?:name|action)"\s*:\s*"choices"[\s\S]*)$/;
function hideLeakedToolCall(src) {
  return String(src || '').replace(LEAKED_TOOL_CALL, '');
}

function prepareStreamText(src) {
  let raw = hideLeakedToolCall(splitChoices(src || '').text);
  const parsedExp = parseExpression(raw);
  if (parsedExp.expression) raw = parsedExp.text;
  const parsedTh = parseThought(raw, true);
  if (parsedTh.thought || parsedTh.cleanText !== raw) raw = parsedTh.cleanText;
  return raw;
}

function postProcessAssistant(node, isFinal, rawText, usage, durationSeconds, skipFooter, servedModel, choices, isPrepend) {
  if (!node) return;
  const parts = splitChoices(rawText);
  rawText = parts.text;
  paintExpressionBadge(node, rawText);
  const parsedThought = parseThought(rawText, isFinal === false);
  if (parsedThought.thought) {
    const md = node.querySelector('.md') || node;
    let box = md.querySelector('.thought-box');
    let btn = md.querySelector('.thought-toggle');
    if (!box) {
      btn = document.createElement('button');
      btn.className = 'thought-toggle';
      btn.type = 'button';
      btn.textContent = '···';
      btn.title = '속마음 보기';
      box = document.createElement('div');
      box.className = 'thought-box';
      box.hidden = true;
      btn.addEventListener('click', () => {
        box.hidden = !box.hidden;
        btn.classList.toggle('active', !box.hidden);
        btn.title = box.hidden ? '속마음 보기' : '속마음 숨기기';
      });
      md.appendChild(btn);
      md.appendChild(box);
    }
    box.textContent = parsedThought.thought;
  }
  node.classList.toggle('streaming', !isFinal);
  if (isFinal) {
    attachCodeCopyButtons(node);
    attachImageLightbox(node);
    attachFileLinkInterceptors(node);
    const eventChoices = (node && node._choices && node._choices.length) ? node._choices : (choices && choices.length ? choices : null);
    const finalChoices = eventChoices || parts.choices;
    if (node && finalChoices && finalChoices.length) {
      node._choices = finalChoices;
    }
    const prependState = Boolean(isPrepend || (node && node._prepend));
    if (!skipFooter) renderChoiceChips(node, finalChoices, prependState);
    renderMermaidIn(node);
    highlightCodeIn(node);
    if (typeof renderMapsIn === 'function') renderMapsIn(node);
    // Client-side system notices (/help, /status, /clear, stop confirmation)
    // reuse the assistant bubble's markdown rendering but aren't real LLM
    // replies -- no token badge / copy / TTS chips belong on them (operator:
    // "시스템 메시지는 복사 스피커 등 추가 칩을 없애고 간결하게").
    if (!skipFooter) attachMessageFooter(node, rawText, usage, durationSeconds, servedModel);
  }
  if (typeof stageSync === 'function') stageSync(node.querySelector('.md'));   // STAGE_v1 (app-stage.js): face, thought
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
  const parsedExp = parseExpression(raw);
  if (parsedExp.expression) {
    raw = parsedExp.text;
  }
  const parsedTh = parseThought(raw, isFinal === false);
  if (parsedTh.thought || parsedTh.cleanText !== raw) {
    raw = parsedTh.cleanText;
  }
  // Fix CommonMark/marked edge-case where bold/italic ending in punctuation (", ), ], etc.)
  // immediately followed by Korean josa fails to parse (e.g. **"A"**는, **A(B)**를)
  raw = raw.replace(/\*\*([^*\n]+?)\*\*([가-힣])/g, '<strong>$1</strong>$2');
  raw = raw.replace(/(^|[^*])\*([^*\n]+?)\*([가-힣])/g, '$1<em>$2</em>$3');
  if (window.marked && typeof marked.parse === 'function') {
    try {
      let html = marked.parse(raw);
      html = html.replace(/<img\s+([^>]*?)src="([^"]+)"([^>]*?)>/g, (_, p1, u, p2) =>
        '<img ' + p1 + 'src="' + absArtifact(u) + '"' + p2 + ' loading="lazy">');
      html = html.replace(/<a\s+([^>]*?)href="([^"]+)"([^>]*?)>/g, (_, p1, href, p2) => {
        const ref = /^https?:/i.test(href) ? null : parseFileRef(href, true);
        if (ref) {
          // FILE_LINKS_v1: kept in data-path, which the sanitiser leaves alone; href would be dropped for ~/.
          return '<a ' + p1 + 'href="#" data-path="' + fileRefTarget(ref).replace(/"/g, '&quot;') + '" class="local-file-link"' + p2 + '>';
        }
        return '<a ' + p1 + 'href="' + href + '" target="_blank" rel="noopener"' + p2 + '>';
      });
      if (isFinal) {
        const dec = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
        html = html.replace(/<pre><code class="(?:language-)?mermaid">([\s\S]*?)<\/code><\/pre>/g, (_, c) =>
          '<div class="mermaid-wrap"><pre class="mermaid">' + dec(c) + '</pre></div>');
        html = html.replace(/<pre><code class="(?:language-)?map">([\s\S]*?)<\/code><\/pre>/g, (m, c) => typeof renderMapBlock === 'function' ? renderMapBlock(c) : m);
      }
      // Sanitize: block javascript: hrefs and inline event handlers.
      // ADD_ATTR keeps target/loading/rel/class attributes; class names like
      // "local-file-link" and "mermaid" survive because DOMPurify keeps class.
      if (window.DOMPurify) {
        html = DOMPurify.sanitize(html, {
          ADD_ATTR: ['target', 'loading', 'rel', 'data-lat', 'data-lon', 'data-zoom', 'data-marker'],
          ALLOWED_URI_REGEXP: /^(?:https?|mailto|\/|\.\/|#)/i,
        });
      } else {
        // DOMPurify absent (vendor file missing): refuse to inject unsanitized
        // HTML — fall back to escaped plain text so XSS is impossible.
        console.warn('renderMarkdown: DOMPurify not loaded; falling back to plain-text escape.');
        return html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }
      return html;
    } catch (e) {
      console.warn('marked parse error:', e);
    }
  }
  // Fallback: escape HTML special chars to prevent XSS.
  return renderPlainText(raw);
}

// PLAIN_RENDER_v1: escaping plus the inline forms -- bold, italics, inline and fenced code, images,
// links, line breaks -- with no markdown parse and no sanitiser pass. It is what the whole page
// falls back to when marked is unavailable, and it is also cheap enough to run on every frame of a
// stream, so a reply can look like its finished self while it is still arriving instead of showing
// raw **syntax** and then snapping to rendered markdown. Escaping first is what makes it safe to
// inject: nothing that was not produced by the rules below survives into the DOM.
function renderPlainText(raw) {
  function _esc(s) {
    return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  let t = (raw || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  t = t.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    const u = absArtifact(url.trim());
    return '<img src="' + _esc(u) + '" alt="' + _esc(alt) + '">';
  });
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
    const safeHref = /^(?:javascript)/i.test(href.trim()) ? '#' : href;
    return '<a href="' + _esc(safeHref) + '" target="_blank" rel="noopener">' + _esc(label) + '</a>';
  });
  t = t.replace(/```([\s\S]*?)```/g, (_, code) => '<pre><code>' + code + '</code></pre>');
  // A fence that is still open is the normal case mid-stream: the closing ``` has not arrived yet.
  // Treating the tail as code is what stops a code block from snapping from raw text into a
  // full-height box the instant the answer ends.
  t = t.replace(/```([\s\S]*)$/, (_, code) => '<pre><code>' + code + '</code></pre>');
  t = t.replace(/`([^`]+)`/g, (_, code) => '<code>' + code + '</code>');
  t = t.replace(/\*\*([^*]+)\*\*/g, (_, txt) => '<strong>' + txt + '</strong>');
  // Single-asterisk italics, which is how RENDER_PROTOCOL writes an action, so an action looks like
  // one from its first frame instead of only after the final parse. The shape is markdown's own
  // flanking rule in miniature: the opener is not followed by a space and the closer is not
  // preceded by one, which is what keeps `2 * 3 * 4` literal instead of eating its middle.
  t = t.replace(/(^|[^*])\*([^*\n]*\S)\*/g, '$1<em>$2</em>');
  t = t.replace(/\n/g, '<br>');
  return t;
}
