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

function parseChoiceItem(item) {
  if (item && typeof item === 'object') {
    const label = String(item.label || '').trim();
    const kind = String(item.kind || (item.isAction ? 'action' : 'say')).trim();
    const payload = item.payload !== undefined ? String(item.payload).trim() : (item.action || label);
    return {
      label,
      kind,
      payload,
      action: payload,
      isAction: kind === 'action' || Boolean(item.isAction),
    };
  }
  const raw = String(item || '').trim();
  if (!raw) return null;
  // Support "Label -> Action" or "Label -> action: Action" or "Label -> command: Command"
  const arrowIdx = raw.indexOf('->');
  if (arrowIdx > 0) {
    const label = raw.slice(0, arrowIdx).trim();
    let action = raw.slice(arrowIdx + 2).trim();
    let isCommand = false;
    if (action.toLowerCase().startsWith('action:')) {
      action = action.slice(7).trim();
    } else if (action.toLowerCase().startsWith('command:')) {
      action = action.slice(8).trim();
      isCommand = true;
    }
    return {
      label,
      action,
      payload: action,
      kind: isCommand ? 'command' : 'action',
      isAction: !isCommand,
    };
  }
  // Support "Label: action: Action"
  const colonAction = /^(.*?):\s*action:\s*(.*)$/i.exec(raw);
  if (colonAction) {
    return { label: colonAction[1].trim(), action: colonAction[2].trim(), payload: colonAction[2].trim(), kind: 'action', isAction: true };
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
  const parsed = parseChoiceItem(choice);
  const item = typeof parsed === 'object' && parsed ? parsed : { label: String(choice), action: String(choice), kind: 'say', payload: String(choice) };
  const kind = item.kind || (item.isAction ? 'action' : 'say');
  const payload = item.payload || item.action || item.label;

  if (kind === 'action') {
    const act = String(payload).replace(/^\(+|\)+$/g, '').trim();   // "(x)" payload must not become "((x))"
    if (typeof sendAction === 'function') {
      sendAction(act);
      return;
    }
    inputEl.value = '/act ' + act;
    sendPickedChoice();
    return;
  }

  if (kind === 'command') {
    const cmdText = payload.startsWith('/') ? payload : ('/' + payload);
    const ticketCmd = typeof parseTicketCommand === 'function' ? parseTicketCommand(cmdText) : null;
    if (ticketCmd) {
      if (ticketCmd.action === 'go') {
        if (typeof goTicket === 'function') {
          goTicket(ticketCmd).then(go => {
            if (go && go.message && typeof addNotice === 'function') addNotice('ok', go.message);
            if (typeof loadTickets === 'function') loadTickets();
            inputEl.value = (go && go.prompt) || '';
            sendPickedChoice();
          }).catch(e => {
            if (typeof addNotice === 'function') addNotice('error', '작업 진행 실패: ' + (typeof obsErrorText === 'function' ? obsErrorText(e) : e));
          });
        }
        return;
      }
      if (typeof decideTicket === 'function') {
        decideTicket(ticketCmd).then(msg => {
          if (typeof addNotice === 'function') addNotice('ok', msg);
          if (typeof loadTickets === 'function') loadTickets();
        }).catch(e => {
          if (typeof addNotice === 'function') addNotice('error', '작업 결정 실패: ' + (typeof obsErrorText === 'function' ? obsErrorText(e) : e));
        });
      }
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

function renderChoiceChips(node, choices) {
  const wasNearBottom = (typeof isUserNearBottom === 'function') ? isUserNearBottom() : true;
  const md = node ? (node.querySelector('.md') || node) : null;
  if (md) md.querySelectorAll('.choice-chips').forEach(el => el.remove());
  const bar = getChoiceBarEl();
  if (bar) {
    if (bar.classList && typeof bar.classList.remove === 'function') {
      bar.classList.remove('closing');
    }
    bar.textContent = '';
    bar.hidden = true;
    bar._owner = null;
  }
  if (!choices || !choices.length) {
    if (wasNearBottom) { if (typeof scrollChatToBottom === 'function') scrollChatToBottom(true); } else if (typeof updateScrollBottomButton === 'function') { updateScrollBottomButton(); }
    return;
  }

  const card = document.createElement('div');
  card.className = 'choice-card';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'choice-close-btn';
  closeBtn.setAttribute('aria-label', '선택지 닫기');
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
  row.setAttribute('aria-label', '선택지');
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
  if (wasNearBottom) { if (typeof scrollChatToBottom === 'function') scrollChatToBottom(true); } else if (typeof updateScrollBottomButton === 'function') { updateScrollBottomButton(); }
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

function postProcessAssistant(node, isFinal, rawText, usage, durationSeconds, skipFooter, servedModel, choices) {
  if (!node) return;
  const parts = splitChoices(rawText);
  rawText = parts.text;
  const parsedExp = parseExpression(rawText);
  if (parsedExp.expression) {
    const md = node.querySelector('.md') || node;
    let badge = node.querySelector('.exp-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'badge exp-badge';
      md.insertBefore(badge, md.firstChild);
    }
    badge.textContent = EXPRESSION_EMOJIS[parsedExp.expression] || ('🎭 ' + parsedExp.expression);
  }
  const parsedThought = parseThought(rawText, isFinal === false);
  if (parsedThought.thought) {
    const md = node.querySelector('.md') || node;
    let box = md.querySelector('.thought-box');
    let btn = md.querySelector('.thought-toggle');
    if (!box) {
      btn = document.createElement('button');
      btn.className = 'thought-toggle';
      btn.type = 'button';
      btn.textContent = '속마음 보기';
      box = document.createElement('div');
      box.className = 'thought-box';
      box.hidden = true;
      btn.addEventListener('click', () => {
        box.hidden = !box.hidden;
        btn.textContent = box.hidden ? '속마음 보기' : '속마음 숨기기';
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
    if (!skipFooter) renderChoiceChips(node, finalChoices);
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
      // Sanitize: block javascript: hrefs and inline event handlers.
      // ADD_ATTR keeps target/loading/rel/class attributes; class names like
      // "local-file-link" and "mermaid" survive because DOMPurify keeps class.
      if (window.DOMPurify) {
        html = DOMPurify.sanitize(html, {
          ADD_ATTR: ['target', 'loading', 'rel'],
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
  function _esc(s) {
    return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  let t = raw.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    const u = absArtifact(url.trim());
    return '<img src="' + _esc(u) + '" alt="' + _esc(alt) + '">';
  });
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
    const safeHref = /^(?:javascript)/i.test(href.trim()) ? '#' : href;
    return '<a href="' + _esc(safeHref) + '" target="_blank" rel="noopener">' + _esc(label) + '</a>';
  });
  t = t.replace(/```([\s\S]*?)```/g, (_, code) => '<pre><code>' + code.replace(/</g,'&lt;') + '</code></pre>');
  t = t.replace(/`([^`]+)`/g, (_, code) => '<code>' + _esc(code) + '</code>');
  t = t.replace(/\*\*([^*]+)\*\*/g, (_, txt) => '<strong>' + _esc(txt) + '</strong>');
  t = t.replace(/\n/g, '<br>');
  return t;
}
