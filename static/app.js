const SESSION_KEY = 'chatbot.sessionId';
const logEl = document.getElementById('log');
const activityEl = document.getElementById('activity');
const metaEl = document.getElementById('meta');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const stopBtn = document.getElementById('stopBtn');
const newBtn = document.getElementById('newSession');
const continueBtn = document.getElementById('continueSession');
const sessionBanner = document.getElementById('sessionBanner');
const sessionBannerContinue = document.getElementById('sessionBannerContinue');
const sessionBannerBtn = document.getElementById('sessionBannerNew');
const sessionBannerDismiss = document.getElementById('sessionBannerDismiss');
const micBtn = document.getElementById('micBtn');

// ---- STT (voice input) ----
const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
let isListening = false;
let voiceInputBaseText = '';

function initSpeechRecognition() {
  if (!SpeechRecognitionCtor) return null;
  const r = new SpeechRecognitionCtor();
  r.lang = 'ko-KR';
  r.continuous = false;
  r.interimResults = true;
  r.onresult = (ev) => {
    let finalText = '';
    let interimText = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const t = ev.results[i][0].transcript;
      if (ev.results[i].isFinal) finalText += t;
      else interimText += t;
    }
    if (inputEl) {
      const sep = voiceInputBaseText && !/\s$/.test(voiceInputBaseText) ? ' ' : '';
      inputEl.value = voiceInputBaseText + sep + finalText + interimText;
      inputEl.dispatchEvent(new Event('input'));
    }
    if (finalText) voiceInputBaseText = inputEl ? inputEl.value.replace(new RegExp(interimText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$'), '') : voiceInputBaseText;
  };
  r.onerror = (ev) => {
    if (ev.error !== 'no-speech' && ev.error !== 'aborted') {
      addActivity('음성 인식 오류: ' + ev.error, 'error');
    }
    stopListening();
  };
  r.onend = () => { stopListening(); };
  return r;
}

function startListening() {
  if (!SpeechRecognitionCtor) {
    alert('이 브라우저는 음성 입력(Web Speech API)을 지원하지 않습니다. Chrome을 이용해주세요.');
    return;
  }
  if (isListening) return;
  recognizer = recognizer || initSpeechRecognition();
  if (!recognizer) return;
  voiceInputBaseText = inputEl ? inputEl.value : '';
  try {
    recognizer.start();
    isListening = true;
    if (micBtn) { micBtn.classList.add('listening'); micBtn.title = '듣는 중… (클릭하면 중지)'; }
  } catch (_) { /* already started */ }
}

function stopListening() {
  isListening = false;
  if (micBtn) { micBtn.classList.remove('listening'); micBtn.title = '음성 입력'; }
  try { recognizer && recognizer.stop(); } catch (_) {}
}

if (micBtn) {
  if (!SpeechRecognitionCtor) {
    micBtn.style.opacity = '0.4';
    micBtn.title = '이 브라우저는 음성 입력을 지원하지 않습니다';
  }
  micBtn.addEventListener('click', () => {
    if (isListening) stopListening(); else startListening();
  });
}

// ---- TTS (read assistant replies aloud) ----
let ttsUtterance = null;
let ttsKoreanVoice = null;
function pickKoreanVoice() {
  if (!window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices() || [];
  return voices.find(v => v.lang && v.lang.toLowerCase().startsWith('ko')) || null;
}
if (window.speechSynthesis) {
  ttsKoreanVoice = pickKoreanVoice();
  window.speechSynthesis.onvoiceschanged = () => { ttsKoreanVoice = pickKoreanVoice() || ttsKoreanVoice; };
}

function stripMarkdownForSpeech(md) {
  let t = String(md || '');
  t = t.replace(/```[\s\S]*?```/g, ' 코드 블록 생략. ');
  t = t.replace(/!\[[^\]]*\]\([^)]+\)/g, ' 이미지 생략. ');
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  t = t.replace(/`([^`]+)`/g, '$1');
  t = t.replace(/^#{1,6}\s*/gm, '');
  t = t.replace(/\*\*([^*]+)\*\*/g, '$1');
  t = t.replace(/\*([^*]+)\*/g, '$1');
  t = t.replace(/^>\s?/gm, '');
  t = t.replace(/^[-*]\s+/gm, '');
  t = t.replace(/\|/g, ' ');
  t = t.replace(/-{3,}/g, ' ');
  return t.trim();
}

function speakText(rawText, btn) {
  if (!window.speechSynthesis) {
    alert('이 브라우저는 음성 출력(Web Speech API)을 지원하지 않습니다.');
    return;
  }
  const wasSpeaking = window.speechSynthesis.speaking;
  window.speechSynthesis.cancel();
  document.querySelectorAll('.tts-btn.speaking').forEach(b => { b.classList.remove('speaking'); b.textContent = '🔊'; });
  if (wasSpeaking && btn && btn.dataset.wasActive === '1') {
    btn.dataset.wasActive = '0';
    return;
  }
  const clean = stripMarkdownForSpeech(rawText);
  if (!clean) return;
  const utter = new SpeechSynthesisUtterance(clean);
  utter.lang = 'ko-KR';
  if (ttsKoreanVoice) utter.voice = ttsKoreanVoice;
  utter.rate = 1.05;
  if (btn) {
    btn.classList.add('speaking');
    btn.textContent = '⏹';
    btn.dataset.wasActive = '1';
  }
  utter.onend = utter.onerror = () => {
    if (btn) { btn.classList.remove('speaking'); btn.textContent = '🔊'; btn.dataset.wasActive = '0'; }
  };
  ttsUtterance = utter;
  window.speechSynthesis.speak(utter);
}

function formatTokenCount(n) {
  if (n == null || isNaN(n)) return '0';
  n = Number(n);
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n.toLocaleString();
}

function formatUsageTooltip(usage, duration) {
  if (!usage) return (duration != null && duration > 0) ? `소요 시간: ${Number(duration).toFixed(1)}초` : '';
  const total = Number(usage.total_tokens || 0).toLocaleString();
  const inp = Number(usage.input_tokens || 0).toLocaleString();
  const out = Number(usage.output_tokens || 0).toLocaleString();
  const think = usage.thinking_tokens ? Number(usage.thinking_tokens).toLocaleString() : null;
  const cache = usage.cache_read_tokens ? Number(usage.cache_read_tokens).toLocaleString() : null;

  let parts = [`총 ${total} 토큰 (입력 ${inp} · 출력 ${out}`];
  if (think) parts.push(`생각 ${think}`);
  if (cache) parts.push(`캐시 ${cache}`);
  let s = parts.join(' · ') + ')';
  if (duration != null && duration > 0) {
    s += ` · ${Number(duration).toFixed(1)}초`;
  }
  return s;
}

let sessionTokens = { total_tokens: 0, input_tokens: 0, output_tokens: 0, thinking_tokens: 0, turns: 0 };

function renderSessionTokensBadge() {
  const badge = document.getElementById('sessionTokenBadge');
  if (!badge) return;
  if (!sessionTokens.total_tokens || sessionTokens.total_tokens <= 0) {
    badge.style.display = 'none';
    return;
  }
  badge.style.display = 'inline-flex';
  badge.textContent = '⚡ 세션 누적: ' + formatTokenCount(sessionTokens.total_tokens) + ' 토큰';
  const inp = Number(sessionTokens.input_tokens || 0).toLocaleString();
  const out = Number(sessionTokens.output_tokens || 0).toLocaleString();
  const tot = Number(sessionTokens.total_tokens || 0).toLocaleString();
  const turns = sessionTokens.turns ? ` · ${sessionTokens.turns}회 턴` : '';
  badge.title = `세션 누적 사용량: 총 ${tot} 토큰 (입력 ${inp} · 출력 ${out}${sessionTokens.thinking_tokens ? ' · 생각 ' + Number(sessionTokens.thinking_tokens).toLocaleString() : ''})${turns}`;
}

function updateSessionTokens(usage) {
  if (!usage) return;
  sessionTokens.total_tokens += Number(usage.total_tokens || 0);
  sessionTokens.input_tokens += Number(usage.input_tokens || 0);
  sessionTokens.output_tokens += Number(usage.output_tokens || 0);
  sessionTokens.thinking_tokens += Number(usage.thinking_tokens || 0);
  sessionTokens.turns += 1;
  renderSessionTokensBadge();
}

function setSessionTokensFromHistory(history, apiUsage) {
  if (apiUsage && apiUsage.total_tokens) {
    sessionTokens = {
      total_tokens: Number(apiUsage.total_tokens || 0),
      input_tokens: Number(apiUsage.input_tokens || 0),
      output_tokens: Number(apiUsage.output_tokens || 0),
      thinking_tokens: Number(apiUsage.thinking_tokens || 0),
      turns: (history || []).filter(h => h.role === 'assistant' && h.usage).length,
    };
  } else {
    sessionTokens = { total_tokens: 0, input_tokens: 0, output_tokens: 0, thinking_tokens: 0, turns: 0 };
    (history || []).forEach(h => {
      const u = h.usage;
      if (u) {
        sessionTokens.total_tokens += Number(u.total_tokens || 0);
        sessionTokens.input_tokens += Number(u.input_tokens || 0);
        sessionTokens.output_tokens += Number(u.output_tokens || 0);
        sessionTokens.thinking_tokens += Number(u.thinking_tokens || 0);
        sessionTokens.turns += 1;
      }
    });
  }
  renderSessionTokensBadge();
}

function attachMessageFooter(node, rawText, usage, durationSeconds) {
  if (!node) return;
  let footer = node.querySelector('.msg-footer');
  if (!footer) {
    footer = document.createElement('div');
    footer.className = 'msg-footer';
    node.appendChild(footer);
  }

  // Token & duration badge
  if (usage || (durationSeconds != null && durationSeconds > 0)) {
    let badge = footer.querySelector('.token-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'token-badge';
      footer.prepend(badge);
    }
    const tokStr = usage && usage.total_tokens ? formatTokenCount(usage.total_tokens) : '';
    const durStr = durationSeconds != null && durationSeconds > 0 ? (Number(durationSeconds).toFixed(1) + 's') : '';
    let label = '⚡ ';
    if (tokStr && durStr) label += `${tokStr} · ${durStr}`;
    else if (tokStr) label += `${tokStr} 토큰`;
    else label += durStr;

    badge.textContent = label;
    badge.title = formatUsageTooltip(usage, durationSeconds);
  }

  // TTS button
  if (window.speechSynthesis && !footer.querySelector('.tts-btn')) {
    const btn = document.createElement('button');
    btn.className = 'tts-btn';
    btn.type = 'button';
    btn.title = '읽어주기';
    btn.textContent = '🔊';
    btn.onclick = () => speakText(rawText, btn);
    footer.appendChild(btn);
  }
}

function attachTtsButton(node, rawText) {
  attachMessageFooter(node, rawText, null, null);
}

function showSessionHeavyBanner(level, text) {
  if (!sessionBanner) return;
  const msg = text || '세션이 길어져서 느려질 수 있어요. 새 채팅을 권장합니다';
  sessionBanner.hidden = false;
  sessionBanner.dataset.level = level || 'soft';
  const msgEl = sessionBanner.querySelector('.session-banner-msg');
  if (msgEl) msgEl.textContent = msg;
  if (level === 'hard') sessionBanner.classList.add('hard');
  else sessionBanner.classList.remove('hard');
}
function hideSessionHeavyBanner() {
  if (!sessionBanner) return;
  sessionBanner.hidden = true;
}

const modelEl = document.getElementById('model');
const wrapEl = document.getElementById('appWrap');
const actToggle = document.getElementById('activityToggle');

// Artifact elements
const tabChat = document.getElementById('tabChat');
const tabArtifacts = document.getElementById('tabArtifacts');
const tabActivity = document.getElementById('tabActivity');
const tabStatus = document.getElementById('tabStatus');
const statusPaneEl = document.getElementById('statusPane');
const statusRefreshBtn = document.getElementById('statusRefreshBtn');
const statusRulesEl = document.getElementById('statusRules');
const statusSkillsEl = document.getElementById('statusSkills');
const statusSkillLibHintEl = document.getElementById('statusSkillLibHint');
const statusMcpEl = document.getElementById('statusMcp');
const statusHooksEl = document.getElementById('statusHooks');
const statusObserverEl = document.getElementById('statusObserver');
const mcpNameInput = document.getElementById('mcpNameInput');
const mcpUrlInput = document.getElementById('mcpUrlInput');
const mcpAddBtn = document.getElementById('mcpAddBtn');
const statusUsageEl = document.getElementById('statusUsage');
const usageCheckedAtEl = document.getElementById('usageCheckedAt');
const usageRefreshBtn = document.getElementById('usageRefreshBtn');
let statusLoaded = false;
const artBadge = document.getElementById('artBadge');
const artifactsEl = document.getElementById('artifacts');
const artGrid = document.getElementById('artGrid');
const artEmpty = document.getElementById('artEmpty');
const artRefreshBtn = document.getElementById('artRefreshBtn');
const artModal = document.getElementById('artModal');
const modalTitle = document.getElementById('modalTitle');
const modalBody = document.getElementById('modalBody');
const modalDownload = document.getElementById('modalDownload');
const modalCite = document.getElementById('modalCite');
const modalClose = document.getElementById('modalClose');

let sessionId = localStorage.getItem(SESSION_KEY)
  || localStorage.getItem('sphereAgySession')
  || localStorage.getItem('sphereAgyHubSession')
  || '';
let es = null;
let assistantNode = null;
let assistantBuf = '';
let isBusy = false;
let progressEl = document.getElementById('progress');

let currentTab = 'chat';
let currentArtifacts = [];
let currentArtFilter = 'all';
let activeModalArtifact = null;

function isInquiry(text) {
  const t = String(text || '').trim();
  if (!t) return false;
  if (t.startsWith('/btw ') || t.startsWith('/btw\n') || t === '/btw') return true;
  if (t.startsWith('/q ') || t.startsWith('/queue ') || t.startsWith('/next ')) return false;
  if (/[\?？]\s*$/.test(t)) return true;
  if (/^(what|why|how|where|when|who|is|are|can|could)\b/i.test(t)) return true;
  const qEndings = [
    "인가", "인가요", "는가", "는가요", "은가", "은가요",
    "나요", "나", "니", "냐", "냐고", "니까", "까", "까요",
    "는지", "은지", "는지요", "지요", "죠", "건가", "건가요",
    "어때", "어때요", "뭐해", "뭐하니", "뭐야", "을까", "ㄹ까"
  ];
  const cleanEnd = t.replace(/[.!~^;\s]+$/, '');
  for (const qe of qEndings) {
    if (cleanEnd.endsWith(qe)) return true;
  }
  if (t.length <= 40) {
    const qWords = ["어디", "어떻게", "얼마나", "언제", "왜", "무슨", "무엇", "몇", "진행상황", "진행 상태", "현재 상태"];
    for (const qw of qWords) {
      if (t.includes(qw)) return true;
    }
  }
  return false;
}

function updateSendButton() {
  if (!isBusy) {
    sendBtn.textContent = '보내기';
    sendBtn.classList.remove('btw-btn', 'queue-btn');
    return;
  }
  const val = inputEl.value.trim();
  if (!val) {
    sendBtn.textContent = '대기열';
    sendBtn.classList.remove('btw-btn');
    sendBtn.classList.add('queue-btn');
  } else if (isInquiry(val)) {
    sendBtn.textContent = '샛길 질문 ✦';
    sendBtn.classList.remove('queue-btn');
    sendBtn.classList.add('btw-btn');
  } else {
    sendBtn.textContent = '대기열 등록 ↵';
    sendBtn.classList.remove('btw-btn');
    sendBtn.classList.add('queue-btn');
  }
}

function setBusy(b) {
  isBusy = Boolean(b);
  if (stopBtn) {
    stopBtn.style.display = isBusy ? 'inline-block' : 'none';
  }
  if (isBusy) {
    inputEl.placeholder = '작업 진행 중… 질문(?)은 즉시 샛길 답변(/btw), 작업 지시는 대기열에 자동 추가';
  } else {
    inputEl.placeholder = '메시지를 입력… (또는 /btw <질문>)';
  }
  updateSendButton();
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function setProgress(msg) {
  // Put status in the assistant bubble instead of a separate bar / bare "...".
  if (progressEl) { progressEl.hidden = true; progressEl.textContent = ""; }
  const label = msg ? String(msg) : "";
  if (!label) return;
  if (!assistantNode) {
    assistantNode = addChat("assistant", label, false);
    assistantBuf = "";
    assistantNode.dataset.progress = "1";
  } else if (assistantNode.dataset.progress === "1" || !(assistantBuf || "").trim()) {
    const md = assistantNode.querySelector(".md") || assistantNode;
    md.textContent = label;
    assistantNode.dataset.progress = "1";
    logEl.scrollTop = logEl.scrollHeight;
  }
}

function shortToolLine(text) {
  let s = String(text || '').replace(/\s+/g, ' ').trim();
  if (!s) return '';
  if (s.length > 90) s = s.slice(0, 87) + '...';
  return s;
}

function setMeta(t) { metaEl.textContent = t; }

function absArtifact(u) {
  if (!u) return '';
  if (u.startsWith('http')) return u;
  return u.startsWith('/') ? u : '/' + u;
}

if (window.marked) {
  try {
    marked.setOptions({ gfm: true, breaks: true });
  } catch (_) {}
}
if (window.mermaid) {
  try {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      securityLevel: 'loose',
      fontFamily: 'Noto Sans KR, system-ui, sans-serif'
    });
  } catch (_) {}
}

let mermaidIdCounter = 0;
async function renderMermaidIn(container) {
  if (!window.mermaid || !container) return;
  const nodes = container.querySelectorAll('pre.mermaid:not([data-processed="true"])');
  if (!nodes || nodes.length === 0) return;
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
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = '완료!';
        setTimeout(() => { btn.textContent = '복사'; }, 1500);
      } catch (_) {
        btn.textContent = '실패';
      }
    };
    pre.appendChild(btn);
  });
}

function postProcessAssistant(node, isFinal, rawText) {
  if (!node) return;
  attachCodeCopyButtons(node);
  if (isFinal) {
    renderMermaidIn(node);
    attachTtsButton(node, rawText);
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
  let raw = dedupeMarkdownImages(String(src || ''));
  if (window.marked && typeof marked.parse === 'function') {
    try {
      let html = marked.parse(raw);
      html = html.replace(/<img\s+([^>]*?)src="([^"]+)"([^>]*?)>/g, (_, p1, u, p2) => {
        return '<img ' + p1 + 'src="' + absArtifact(u) + '"' + p2 + ' loading="lazy">';
      });
      html = html.replace(/<a\s+([^>]*?)href="([^"]+)"([^>]*?)>/g, (_, p1, href, p2) => {
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

function addBtw(query, answer) {
  const div = document.createElement('div');
  div.className = 'msg btw-card';
  const head = document.createElement('div');
  head.className = 'btw-head';
  head.innerHTML = '<span>✦ 샛길 응답 (/btw)</span>' + (query ? '<span class="btw-q">Q. ' + escapeHtml(query) + '</span>' : '');
  const body = document.createElement('div');
  body.className = 'btw-body md';
  body.innerHTML = renderMarkdown(answer || '', true);
  div.appendChild(head);
  div.appendChild(body);
  postProcessAssistant(body, true, answer);
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
  return div;
}

function addChat(role, text, isFinal, isQueued, isBtw) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  if (isQueued) div.classList.add('queued');
  if (isBtw) div.classList.add('btw-user');
  if (role === 'assistant') {
    const md = document.createElement('div');
    md.className = 'md';
    md.innerHTML = renderMarkdown(text || '', isFinal);
    div.appendChild(md);
    postProcessAssistant(div, isFinal, text);
  } else {
    div.textContent = text || '';
  }
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
  return div;
}

function setAssistantContent(node, text, isFinal) {
  if (!node) return;
  const md = node.querySelector('.md') || node;
  md.innerHTML = renderMarkdown(text || '', isFinal);
  postProcessAssistant(node, isFinal, text);
  logEl.scrollTop = logEl.scrollHeight;
}

function addActivity(line, kind) {
  if (!line) return;
  const row = document.createElement('div');
  row.className = 'act-row' + (kind ? ' act-' + kind : '');
  const ts = new Date().toLocaleTimeString('ko-KR', { hour12: false });
  row.textContent = '[' + ts + '] ' + line;
  activityEl.appendChild(row);
  activityEl.scrollTop = activityEl.scrollHeight;
}

let sessionTokenTotal = 0;
// Fresh (non-cache) input tokens per turn this session, for relative spike detection.
const turnFreshTokenHistory = [];
// Absolute floor: 2026-09-16 measured baseline is ~14-16K fresh input tokens for a
// trivial first turn (see docs/DEVLOG.md — the ADD_DIRS parent-vs-children bug pushed
// this to ~45K). Anything past this on its own is worth a look regardless of history.
const FRESH_TOKEN_WARN_ABS = 30000;

function logTurnUsage(usage, durationSeconds) {
  usage = usage || {};
  const total = usage.total_tokens || 0;
  const input = usage.input_tokens || 0;
  const cacheRead = usage.cache_read_tokens || 0;
  const fresh = Math.max(0, input - cacheRead);
  if (total) sessionTokenTotal += total;

  let warnReason = '';
  if (fresh > FRESH_TOKEN_WARN_ABS) {
    warnReason = '절대치 초과(>' + FRESH_TOKEN_WARN_ABS.toLocaleString('ko-KR') + ')';
  } else if (turnFreshTokenHistory.length >= 2) {
    const avg = turnFreshTokenHistory.reduce((a, b) => a + b, 0) / turnFreshTokenHistory.length;
    if (avg > 0 && fresh > avg * 2.5) {
      warnReason = '이 세션 평소(' + Math.round(avg).toLocaleString('ko-KR') + ')의 2.5배 이상';
    }
  }
  if (fresh > 0) turnFreshTokenHistory.push(fresh);

  const parts = [];
  if (total) parts.push((warnReason ? '⚠️ ' : '🔢 ') + '이번 턴 ' + total.toLocaleString('ko-KR') + '토큰');
  if (usage.input_tokens != null || usage.output_tokens != null) {
    parts.push('(입력 ' + input.toLocaleString('ko-KR') +
      ' · 출력 ' + (usage.output_tokens || 0).toLocaleString('ko-KR') +
      (usage.thinking_tokens ? ' · 사고 ' + usage.thinking_tokens.toLocaleString('ko-KR') : '') +
      (cacheRead ? ' · 캐시 ' + cacheRead.toLocaleString('ko-KR') : '') + ')');
  }
  if (durationSeconds != null) parts.push(Number(durationSeconds).toFixed(1) + '초');
  if (sessionTokenTotal) parts.push('· 세션 누계 ' + sessionTokenTotal.toLocaleString('ko-KR') + '토큰');
  if (warnReason) parts.push('— 토큰 사용량 이상 폭증 의심 (' + warnReason + ')');
  if (parts.length) addActivity(parts.join(' '), warnReason ? 'warn' : 'token');
}

function formatToolCallClient(name, args) {
  args = args || {};
  function clean(v) {
    if (v == null) return '';
    let s = String(v).trim();
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
      s = s.slice(1, -1).trim();
    }
    s = s.replace(/\/volume1\/homes\/me\//g, '');
    s = s.replace(/\/volume1\/web\//g, 'web/');
    return s;
  }
  const action = clean(args.toolAction || args.action);
  const summary = clean(args.toolSummary || args.summary || args.description);
  if (name === 'run_command') {
    const cmd = clean(args.CommandLine || args.command || args.cmd);
    let out = 'run_command: ' + cmd;
    if (summary && summary.toLowerCase() !== cmd.toLowerCase()) out += ' (' + summary + ')';
    else if (action && action.toLowerCase() !== cmd.toLowerCase()) out += ' (' + action + ')';
    return out;
  }
  if (name === 'view_file' || name === 'read_file') {
    const p = clean(args.AbsolutePath || args.TargetFile || args.path || args.file);
    const start = args.StartLine;
    const end = args.EndLine;
    const lines = (start || end) ? ` [L${start || ''}-${end || ''}]` : '';
    let out = 'view_file: ' + p + lines;
    if (summary) out += ' (' + summary + ')';
    else if (action) out += ' (' + action + ')';
    return out;
  }
  if (name === 'grep_search') {
    const q = clean(args.Query || args.query || args.pattern);
    const sp = clean(args.SearchPath || args.path);
    let out = `grep_search: '${q}' in ${sp || '.'}`;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'find_by_name') {
    const p = clean(args.Pattern || args.pattern);
    const sd = clean(args.SearchDirectory || args.directory || args.path);
    let out = `find_by_name: '${p}' in ${sd || '.'}`;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'list_dir') {
    const dp = clean(args.DirectoryPath || args.path || args.dir);
    let out = 'list_dir: ' + dp;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'replace_file_content' || name === 'edit_file') {
    const tf = clean(args.TargetFile || args.path || args.file);
    const inst = clean(args.Instruction || summary || action);
    let out = 'replace_file_content: ' + tf;
    if (inst) out += ' (' + inst + ')';
    return out;
  }
  if (name === 'write_to_file' || name === 'write_file') {
    const tf = clean(args.TargetFile || args.path || args.file);
    const desc = clean(args.Description || summary || action);
    let out = 'write_to_file: ' + tf;
    if (desc) out += ' (' + desc + ')';
    return out;
  }
  let target = '';
  for (const k of ['path', 'file', 'AbsolutePath', 'TargetFile', 'command', 'CommandLine', 'query', 'Query', 'pattern', 'url', 'Url', 'DirectoryPath']) {
    if (args[k]) { target = clean(args[k]); break; }
  }
  let out = name;
  if (target) out += ': ' + target;
  const d = summary || action;
  if (d && d.toLowerCase() !== target.toLowerCase()) out += ' (' + d + ')';
  return out;
}

function formatToolResultClient(content) {
  if (!content) return '';
  const lines = String(content).split('\n').map(l => l.trim()).filter(Boolean);
  const filtered = lines.filter(l => !l.startsWith('Created At:') && !l.startsWith('Completed At:'));
  if (!filtered.length) return '↳ 완료';
  let first = filtered[0];
  if (first.length > 120) first = first.slice(0, 117) + '...';
  return filtered.length > 1 ? `↳ ${first} (외 ${filtered.length - 1}줄)` : `↳ ${first}`;
}

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
  if (!r.ok) throw new Error(await r.text() || r.statusText);
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return r.json();
  return r.text();
}

async function maybeRedirectHardSession(id, info, depth) {
  depth = depth || 0;
  if (depth > 3) return null;
  const redir = (info && (info.redirect_session_id || info.successor_session_id)) || '';
  const hard = info && info.weight && info.weight.level === 'hard';
  if (!hard && !redir) return null;
  if (redir && redir !== id) {
    rememberSession(redir);
    addActivity('hard 세션 → successor로 이동: ' + redir);
    await openSession(redir, depth + 1);
    return redir;
  }
  if (hard && !redir) {
    addActivity('hard 세션에 successor 없음 → 새 세션');
    await createSession();
    return 'new';
  }
  return null;
}

function rememberSession(id) {
  sessionId = id || '';
  if (sessionId) {
    localStorage.setItem(SESSION_KEY, sessionId);
    localStorage.setItem('sphereAgySession', sessionId);
    localStorage.setItem('sphereAgyHubSession', sessionId);
  }
  const hubLink = document.getElementById('hubLink');
  if (hubLink) {
    const port80 = '//' + location.hostname + '/';
    hubLink.href = sessionId ? (port80 + '?session=' + encodeURIComponent(sessionId)) : port80;
  }
}

function switchTab(tab) {
  currentTab = tab;
  if (tabChat) tabChat.classList.toggle('on', tab === 'chat');
  if (tabArtifacts) tabArtifacts.classList.toggle('on', tab === 'artifacts');
  if (tabActivity) tabActivity.classList.toggle('on', tab === 'activity');
  if (tabStatus) tabStatus.classList.toggle('on', tab === 'status');

  if (logEl) logEl.style.display = (tab === 'chat') ? 'flex' : 'none';
  if (artifactsEl) artifactsEl.style.display = (tab === 'artifacts') ? 'flex' : 'none';
  if (activityEl) activityEl.style.display = (tab === 'activity') ? 'block' : 'none';
  if (statusPaneEl) statusPaneEl.style.display = (tab === 'status') ? 'flex' : 'none';

  if (tab === 'artifacts') {
    fetchArtifacts(true);
  } else if (tab === 'chat' && logEl) {
    logEl.scrollTop = logEl.scrollHeight;
  } else if (tab === 'activity' && activityEl) {
    activityEl.scrollTop = activityEl.scrollHeight;
  } else if (tab === 'status') {
    fetchSelfStatus();
    fetchUsage(false);
  }
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function fetchSelfStatus() {
  if (!statusPaneEl) return;
  try {
    const res = await api('/api/self-status');
    renderStatusRules(res.rules || []);
    renderStatusSkills(res.skills || []);
    if (statusSkillLibHintEl) {
      statusSkillLibHintEl.textContent = '호스트 전체 스킬 라이브러리(~/.agents/skills): ' + (res.host_skill_library_count || 0) + '개 (읽기 전용, 슬래시 명령어 피커에서 노출됨)';
    }
    renderStatusMcp(res.mcp || []);
    if (statusHooksEl) {
      const h = res.hooks || {};
      const p = res.plugins || {};
      statusHooksEl.textContent = (h.note || '') + (p.note ? '\n' + p.note : '');
    }
    if (statusObserverEl) {
      const o = res.task_observer || {};
      statusObserverEl.textContent = '열린 관찰(open): ' + (o.open_observations || 0) + ' / 전체 ' + (o.total_observations || 0) + '건 · 마지막 리뷰: ' + (o.last_review_date || 'never');
    }
    statusLoaded = true;
  } catch (e) {
    if (statusRulesEl) statusRulesEl.textContent = '상태 로드 실패: ' + e.message;
  }
}

async function fetchUsage(force) {
  if (!statusUsageEl) return;
  statusUsageEl.innerHTML = '<div class="status-hint">불러오는 중… (agy CLI 실제 호출이라 몇 초 걸릴 수 있어요)</div>';
  try {
    const res = await api('/api/usage' + (force ? '?force=1' : ''));
    renderStatusUsage(res);
  } catch (e) {
    statusUsageEl.innerHTML = '<div class="status-hint">사용량 로드 실패: ' + escapeHtml(e.message) + '</div>';
  }
}

function renderStatusUsage(res) {
  if (!statusUsageEl) return;
  if (!res || !res.ok) {
    statusUsageEl.innerHTML = '<div class="status-hint">조회 실패: ' + escapeHtml((res && res.error) || '알 수 없는 오류') + '</div>';
    if (usageCheckedAtEl) usageCheckedAtEl.textContent = '';
    return;
  }
  statusUsageEl.innerHTML = '';
  (res.rows || []).forEach(row => {
    const pct = parseInt(row.remaining_pct, 10);
    const pctSafe = isNaN(pct) ? 0 : Math.max(0, Math.min(100, pct));
    const item = document.createElement('div');
    item.className = 'status-item';
    let resetStr = row.reset_at;
    try { resetStr = new Date(row.reset_at).toLocaleString('ko-KR'); } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(row.group) + ' — ' + escapeHtml(row.limit_type) + '</span>' +
      '<span class="status-item-meta">' + escapeHtml(row.remaining_pct) + ' 남음</span>' +
      '</div>' +
      '<div class="usage-bar-track"><div class="usage-bar-fill' + (pctSafe <= 20 ? ' low' : '') + '" style="width:' + pctSafe + '%"></div></div>' +
      '<div class="status-item-preview">리셋: ' + escapeHtml(resetStr) + '</div>';
    statusUsageEl.appendChild(item);
  });
  if (usageCheckedAtEl) {
    const checked = res.checked_at ? new Date(res.checked_at * 1000).toLocaleTimeString('ko-KR') : '';
    usageCheckedAtEl.textContent = checked ? ('마지막 확인: ' + checked) : '';
  }
}

function renderStatusRules(rules) {
  if (!statusRulesEl) return;
  statusRulesEl.innerHTML = '';
  rules.forEach(r => {
    const item = document.createElement('div');
    item.className = 'status-item';
    const mtime = r.mtime ? new Date(r.mtime * 1000).toLocaleString('ko-KR') : '?';
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(r.name) + '</span>' +
      '<span class="status-item-meta">' + (r.size || 0) + ' bytes · ' + mtime + '</span>' +
      '<div class="status-item-actions"><button class="art-btn" data-edit-rule="' + escapeHtml(r.name) + '" type="button">편집</button></div>' +
      '</div>' +
      '<div class="status-item-preview" data-preview="' + escapeHtml(r.name) + '">' + escapeHtml(r.preview) + '</div>';
    statusRulesEl.appendChild(item);
  });
  statusRulesEl.querySelectorAll('[data-edit-rule]').forEach(btn => {
    btn.addEventListener('click', () => openRuleEditor(btn.getAttribute('data-edit-rule')));
  });
}

async function openRuleEditor(name) {
  const previewEl = statusRulesEl.querySelector('[data-preview="' + CSS.escape(name) + '"]');
  if (!previewEl) return;
  if (previewEl.dataset.editing === '1') return;
  previewEl.dataset.editing = '1';
  previewEl.innerHTML = '불러오는 중…';
  try {
    const res = await api('/api/rules/' + encodeURIComponent(name));
    const ta = document.createElement('textarea');
    ta.className = 'status-edit-area';
    ta.value = res.content || '';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'art-btn primary';
    saveBtn.type = 'button';
    saveBtn.textContent = '저장';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'art-btn';
    cancelBtn.type = 'button';
    cancelBtn.textContent = '취소';
    previewEl.innerHTML = '';
    previewEl.appendChild(ta);
    const row = document.createElement('div');
    row.style.display = 'flex';
    row.style.gap = '.4rem';
    row.style.marginTop = '.4rem';
    row.appendChild(saveBtn);
    row.appendChild(cancelBtn);
    previewEl.appendChild(row);
    cancelBtn.addEventListener('click', () => { delete previewEl.dataset.editing; fetchSelfStatus(); });
    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = '저장 중…';
      try {
        await api('/api/rules/' + encodeURIComponent(name), { method: 'PUT', body: JSON.stringify({ content: ta.value }) });
        addActivity(name + ' 저장됨 (백업 생성됨, 다음 새 세션부터 반영)');
        delete previewEl.dataset.editing;
        fetchSelfStatus();
      } catch (e) {
        saveBtn.disabled = false;
        saveBtn.textContent = '저장';
        alert('저장 실패: ' + e.message);
      }
    });
  } catch (e) {
    previewEl.textContent = '로드 실패: ' + e.message;
    delete previewEl.dataset.editing;
  }
}

function renderStatusSkills(skills) {
  if (!statusSkillsEl) return;
  statusSkillsEl.innerHTML = '';
  skills.forEach(s => {
    const item = document.createElement('div');
    item.className = 'status-item';
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(s.name) + '</span>' +
      '<button class="status-toggle ' + (s.enabled ? 'on' : 'off') + '" data-toggle-skill="' + escapeHtml(s.name) + '" type="button">' + (s.enabled ? 'ON' : 'OFF') + '</button>' +
      '</div>' +
      (s.desc ? '<div class="status-item-preview">' + escapeHtml(s.desc) + '</div>' : '');
    statusSkillsEl.appendChild(item);
  });
  statusSkillsEl.querySelectorAll('[data-toggle-skill]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.getAttribute('data-toggle-skill');
      btn.disabled = true;
      try {
        await api('/api/skills/' + encodeURIComponent(name) + '/toggle', { method: 'POST', body: '{}' });
        addActivity('스킬 ' + name + ' 토글됨 (다음 새 세션부터 반영)');
        fetchSelfStatus();
      } catch (e) {
        alert('토글 실패: ' + e.message);
        btn.disabled = false;
      }
    });
  });
}

function renderStatusMcp(mcpList) {
  if (!statusMcpEl) return;
  statusMcpEl.innerHTML = '';
  mcpList.forEach(m => {
    const item = document.createElement('div');
    item.className = 'status-item';
    const isCore = m.name === 'nas';
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(m.name) + (isCore ? ' (core)' : '') + '</span>' +
      (isCore ? '' : '<button class="art-btn" data-del-mcp="' + escapeHtml(m.name) + '" type="button">삭제</button>') +
      '</div>' +
      '<div class="status-item-preview">' + escapeHtml(m.serverUrl || '') + (m.disabled ? ' · disabled' : '') + '</div>';
    statusMcpEl.appendChild(item);
  });
  statusMcpEl.querySelectorAll('[data-del-mcp]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.getAttribute('data-del-mcp');
      if (!confirm(name + ' MCP 서버를 삭제할까요?')) return;
      try {
        await api('/api/mcp/' + encodeURIComponent(name), { method: 'DELETE' });
        addActivity('MCP ' + name + ' 삭제됨 (다음 새 세션부터 반영)');
        fetchSelfStatus();
      } catch (e) {
        alert('삭제 실패: ' + e.message);
      }
    });
  });
}

async function fetchArtifacts(silent) {
  if (!sessionId) return;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/artifacts');
    currentArtifacts = res.artifacts || [];
    updateArtifactBadge();
    renderArtifacts();
  } catch (e) {
    if (!silent) addActivity('아티팩트 조회 실패: ' + (e.message || e));
  }
}

function updateArtifactBadge() {
  if (!artBadge) return;
  const count = currentArtifacts.length;
  artBadge.textContent = count > 0 ? String(count) : '';
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
      img.src = item.url;
      img.alt = item.name;
      img.loading = 'lazy';
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

async function openArtifactModal(item) {
  if (!item || !artModal) return;
  activeModalArtifact = item;
  if (modalTitle) modalTitle.textContent = item.name + ' (' + (item.size_human || '') + ')';
  if (modalDownload) {
    modalDownload.href = item.url;
    modalDownload.setAttribute('download', item.name);
  }
  if (modalBody) {
    modalBody.innerHTML = '';
    if (item.kind === 'image') {
      const img = document.createElement('img');
      img.src = item.url;
      img.alt = item.name;
      modalBody.appendChild(img);
    } else {
      modalBody.innerHTML = '<div style="color:var(--muted)">불러오는 중…</div>';
      try {
        const resp = await fetch(item.url);
        if (!resp.ok) throw new Error(resp.statusText);
        const text = await resp.text();
        const pre = document.createElement('pre');
        pre.textContent = text;
        modalBody.innerHTML = '';
        modalBody.appendChild(pre);
      } catch (err) {
        modalBody.innerHTML = `<div style="color:var(--status-bad)">파일을 불러올 수 없습니다: ${escapeHtml(err.message)}</div>`;
      }
    }
  }
  artModal.style.display = 'flex';
}

function closeArtifactModal() {
  if (artModal) artModal.style.display = 'none';
  activeModalArtifact = null;
}

function bindEvents(sid) {
  if (es) { try { es.close(); } catch (_) {} es = null; }
  assistantNode = null; assistantBuf = '';
  es = new EventSource('/api/sessions/' + encodeURIComponent(sid) + '/events');
  es.onmessage = (ev) => {
    let data; try { data = JSON.parse(ev.data); } catch (_) { return; }
    const type = data.event || data.type || '';
    const text = data.text || data.message || data.content || '';

    if (type === 'image') {
      const u = absArtifact(data.url || text);
      if (u && !(assistantBuf || '').includes(u)) {
        if (!assistantNode) assistantNode = addChat('assistant', '', false);
        assistantBuf = (assistantBuf || '') + '\n\n![](' + u + ')\n';
        setAssistantContent(assistantNode, assistantBuf, false);
      }
      fetchArtifacts(true);
      return;
    }

    if (type === 'delta' || type === 'assistant' || type === 'agy' || type === 'message') {
      setBusy(true);
      if (!assistantNode) assistantNode = addChat('assistant', '', false);
      if (assistantNode) delete assistantNode.dataset.progress;
      if (type === 'delta') assistantBuf += text;
      else if (text) assistantBuf = text;
      setAssistantContent(assistantNode, assistantBuf || '작성 중…', false);
      return;
    }

    if (type === 'result') {
      if (text) assistantBuf = text;
      if (assistantNode) delete assistantNode.dataset.progress;
      if (assistantBuf && assistantBuf.trim()) {
        if (!assistantNode) assistantNode = addChat('assistant', '', false);
        setAssistantContent(assistantNode, assistantBuf, true);
      } else if (assistantNode) {
        // If nothing was generated or only empty progress was shown, remove empty assistant bubble
        assistantNode.remove();
      }
      if (data.usage || data.duration_seconds != null) logTurnUsage(data.usage, data.duration_seconds);
      assistantNode = null; assistantBuf = '';
      setBusy(false);
      fetchArtifacts(true);
      return;
    }

    if (type === 'session_heavy') {
      showSessionHeavyBanner(data.level || 'soft', text);
      addActivity('세션 길이 경고(' + (data.level || 'soft') + '): ' + (text || ''));
      return;
    }

    if (type === 'session_rotate') {
      const nid = data.new_session_id;
      addActivity('세션 자동 전환: ' + (text || '') + (nid ? ' → ' + nid : ''));
      showSessionHeavyBanner('hard', text || '세션이 길어져 새 채팅으로 전환합니다');
      if (nid) {
        rememberSession(nid);
        logEl.innerHTML = '';
        activityEl.innerHTML = '';
        addChat('assistant', text || '새 채팅으로 전환했습니다냥. 이어서 진행한다냥!', true);
        setMeta('세션 ' + nid + ' · (자동 전환)');
        bindEvents(nid);
        hideSessionHeavyBanner();
        fetchArtifacts(true);
      }
      setBusy(true);
      return;
    }

    if (type === 'stopped') {
      addActivity('작업 중지: ' + (text || ''));
      if (assistantNode && assistantNode.dataset.progress === '1') {
        assistantNode.remove();
      }
      assistantNode = null; assistantBuf = '';
      setBusy(false);
      setProgress('');
      return;
    }

    if (type === 'queued') {
      addActivity('대기열 등록 (대기: ' + (data.queue_len || 1) + '건)');
      return;
    }

    if (type === 'user_ack') {
      addActivity('대기열 작업 착수: ' + shortToolLine(text));
      const queuedNodes = logEl.querySelectorAll('.msg.user.queued');
      if (queuedNodes.length > 0) queuedNodes[0].classList.remove('queued');
      setBusy(true);
      return;
    }

    if (type === 'btw_start') {
      addActivity('샛길 질문(/btw) 처리 중: ' + shortToolLine(data.query || ''));
      return;
    }

    if (type === 'btw') {
      addBtw(data.query, data.text);
      addActivity('샛길 질문(/btw) 응답 완료');
      if (data.usage || data.duration_seconds != null) logTurnUsage(data.usage, data.duration_seconds);
      return;
    }

    if (type === 'tool' || type === 'system' || type === 'stderr' || type === 'error') {
      const line = (type === 'error' ? '오류: ' : '') + (text || JSON.stringify(data.error || data));
      const kind = data.kind || (type === 'tool' ? (line.startsWith('↳') ? 'result' : 'tool') : (type === 'stderr' ? 'warn' : type));
      if (type === 'tool') {
        const s = String(text || '').trim().toLowerCase();
        if (!s || s === 'tool' || s === 'tool: tool' || s === 'tool:tool') return;
        if (kind !== 'result' && !line.startsWith('↳')) {
          setProgress('작업 중 · ' + shortToolLine(text));
          setBusy(true);
        }
      } else if (type === 'system') {
        setProgress(shortToolLine(text) || '처리 중…');
        if (text && text.includes('started')) setBusy(true);
      } else if (type === 'error') {
        setProgress('오류 · ' + shortToolLine(text));
        setBusy(false);
      }
      addActivity(line, kind);
      if (type === 'error') { assistantNode = null; assistantBuf = ''; }
      return;
    }

    if (type === 'agy' && data.payload) {
      const p = data.payload;
      if (Array.isArray(p.tool_calls) && p.tool_calls.length) {
        for (const tc of p.tool_calls) {
          if (tc && tc.name) {
            const line = formatToolCallClient(tc.name, tc.args || tc.input);
            setProgress('작업 중 · ' + shortToolLine(line));
            setBusy(true);
            addActivity(line, 'tool');
          }
        }
        return;
      }
      if (p.type === 'GENERIC' && p.content) {
        const resLine = formatToolResultClient(p.content);
        addActivity(resLine, 'result');
        return;
      }
    }
  };
  es.onerror = () => {
    try { es.close(); } catch (_) {}
    es = null;
    setProgress('연결 끊김 · 재연결 중…');
    if (window.__agyEsTimer) clearTimeout(window.__agyEsTimer);
    window.__agyEsRetry = (window.__agyEsRetry || 0) + 1;
    const wait = Math.min(15000, 800 * Math.pow(1.6, Math.min(window.__agyEsRetry, 8)));
    window.__agyEsTimer = setTimeout(() => {
      if (sessionId === sid) bindEvents(sid);
    }, wait);
  };
  es.onopen = () => {
    window.__agyEsRetry = 0;
    setProgress('');
  };
}

async function openSession(id, _redirDepth) {
  const info = await api('/api/sessions/' + encodeURIComponent(id));
  const bounced = await maybeRedirectHardSession(id, info, _redirDepth || 0);
  if (bounced) return;
  rememberSession(id);
  setMeta('세션 ' + id + ' · ' + (info.model || ''));
  logEl.innerHTML = '';
  activityEl.innerHTML = '';
  (info.history || []).forEach(h => {
    if (h.role === 'btw') {
      addBtw(h.query, h.text);
    } else if (h.role === 'user') {
      const isB = (h.text || '').startsWith('/btw');
      addChat('user', h.text || '', false, Boolean(h.queued), isB);
    } else if (h.role === 'assistant') {
      addChat('assistant', h.text || '', true);
    }
  });
  setBusy(Boolean(info.busy));
  addActivity('세션 복원 ' + id);
  if (info.weight && info.weight.level && info.weight.level !== 'ok') {
    showSessionHeavyBanner(info.weight.level, info.weight.message_ko);
  } else {
    hideSessionHeavyBanner();
  }
  bindEvents(id);
  fetchArtifacts(true);
}

async function createSession() {
  const model = modelEl.value;
  const data = await api('/api/sessions', {method:'POST', body: JSON.stringify({model})});
  rememberSession(data.session.id);
  logEl.innerHTML = '';
  activityEl.innerHTML = '';
  setBusy(false);
  addChat('assistant', '다시 왔다냥! 실장님, 뭐부터 할까? ฅ', true);
  setMeta('세션 ' + sessionId + ' · ' + data.session.model);
  addActivity('새 세션 ' + sessionId);
  hideSessionHeavyBanner();
  bindEvents(sessionId);
  fetchArtifacts(true);
}

async function continueSession() {
  if (!sessionId) {
    await createSession();
    return;
  }
  const oldId = sessionId;
  setProgress('이전 대화 핵심 요약 및 인계 준비 중…');
  setBusy(true);
  try {
    const model = modelEl.value;
    const res = await api('/api/sessions/' + encodeURIComponent(oldId) + '/continue', {
      method: 'POST',
      body: JSON.stringify({ model })
    });
    if (res && res.ok && res.session) {
      const nid = res.session.id;
      rememberSession(nid);
      logEl.innerHTML = '';
      activityEl.innerHTML = '';
      addActivity('이전 세션(' + oldId + ') 맥락 인계 → 새 세션(' + nid + ')');
      const note = res.summary
        ? '\n\n> **[인계된 핵심 맥락]**\n> ' + res.summary.replace(/\n/g, '\n> ')
        : '';
      addChat('assistant', '이전 대화의 핵심 맥락을 인계받아 새 세션을 열었다냥! ฅ' + note + '\n\n무엇부터 이어서 진행할까?', true);
      setMeta('세션 ' + nid + ' · ' + (res.session.model || ''));
      hideSessionHeavyBanner();
      bindEvents(nid);
      fetchArtifacts(true);
    }
  } catch (e) {
    addActivity('세션 이어하기 오류: ' + (e.message || e));
    alert('세션 이어하기 실패: ' + (e.message || e));
  } finally {
    setBusy(false);
    setProgress('');
  }
}

async function ensureSession() {
  const sp = new URLSearchParams(location.search);
  const urlSid = sp.get('session');
  if (urlSid) {
    try { await openSession(urlSid); return; } catch (_) {}
  }
  try {
    const act = await api('/api/sessions/active');
    if (act && act.id) { await openSession(act.id); return; }
  } catch (_) {}
  if (sessionId) {
    try { await openSession(sessionId); return; }
    catch (_) {
      sessionId = '';
      localStorage.removeItem(SESSION_KEY);
      localStorage.removeItem('sphereAgySession');
      localStorage.removeItem('sphereAgyHubSession');
    }
  }
  try {
    const list = await api('/api/sessions');
    const latest = (list.sessions || [])[0];
    if (latest && latest.id) { await openSession(latest.id); return; }
  } catch (_) {}
  await createSession();
}

async function send() {
  const text = inputEl.value.trim();
  if (!text) return;

  if (text === '/clear') {
    inputEl.value = '';
    inputEl.style.height = '';
    logEl.innerHTML = '';
    activityEl.innerHTML = '';
    addChat('assistant', '대화 로그를 깨끗하게 비웠습니다냥 🐾', true);
    updateSendButton();
    return;
  }
  if (text === '/new') {
    inputEl.value = '';
    inputEl.style.height = '';
    updateSendButton();
    createSession().catch(e => addActivity(String(e.message || e)));
    return;
  }
  if (text === '/continue') {
    inputEl.value = '';
    inputEl.style.height = '';
    updateSendButton();
    continueSession().catch(e => addActivity(String(e.message || e)));
    return;
  }
  if (text === '/defib' || text === '/repair') {
    inputEl.value = '';
    inputEl.style.height = '';
    updateSendButton();
    defibrillateHost().catch(e => addActivity(String(e.message || e)));
    return;
  }
  if (text === '/status') {
    inputEl.value = '';
    inputEl.style.height = '';
    updateSendButton();
    addChat('user', '/status', false);
    try {
      const st = await api('/api/host/status');
      addChat('assistant', `호스트 상태: **${st.ok ? '정상 가동 중 ⚡' : '이상 감지'}** · 세션 ID: \`${sessionId || '없음'}\` · 모델: \`${modelEl.value}\``, true);
    } catch (e) {
      addChat('assistant', '상태 확인 실패: ' + e.message, true);
    }
    return;
  }

  if (!sessionId) await ensureSession();

  const isAutoBtw = isBusy && isInquiry(text);
  const isExplicitBtw = text.startsWith('/btw ') || text.startsWith('/btw\n') || text === '/btw';
  const isBtw = isAutoBtw || isExplicitBtw;

  sendBtn.disabled = true;

  if (isBtw) {
    addChat('user', text, false, false, true);
    addActivity('샛길 질문(/btw) 감지 · 처리 중…');
  } else if (isBusy) {
    addChat('user', text, false, true, false);
    addActivity('대기열 등록 (작업 완료 후 실행): ' + shortToolLine(text));
  } else {
    addChat('user', text, false, false, false);
    assistantNode = null; assistantBuf = '';
    setProgress('요청 보냄 · 대기 중…');
    setBusy(true);
  }

  inputEl.value = '';
  inputEl.style.height = '';
  autoResizeInput();
  updateSendButton();

  try {
    const msgRes = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/message', {
      method:'POST',
      body: JSON.stringify({text, model: modelEl.value})
    });
    if (msgRes && msgRes.rotated && msgRes.session && msgRes.session.id) {
      const nid = msgRes.session.id;
      addActivity('서버가 긴 세션을 새 채팅으로 인계 전환: ' + nid);
      rememberSession(nid);
      logEl.innerHTML = '';
      activityEl.innerHTML = '';
      addChat('user', text, false, false, false);
      const note = msgRes.handoff_summary
        ? '\n\n> **[인계된 핵심 맥락]**\n> ' + msgRes.handoff_summary.replace(/\n/g, '\n> ')
        : '';
      addChat('assistant', '세션이 길어져 이전 맥락을 인계받아 새 채팅으로 전환했습니다냥 ✦ 이어서 바로 답변할게요!' + note, true);
      setMeta('세션 ' + nid + ' · ' + (msgRes.session.model || ''));
      hideSessionHeavyBanner();
      bindEvents(nid);
      fetchArtifacts(true);
      setBusy(true);
    } else if (msgRes && msgRes.session && msgRes.session.weight && msgRes.session.weight.level !== 'ok') {
      showSessionHeavyBanner(msgRes.session.weight.level, msgRes.session.weight.message_ko);
    }
  } catch (e) {
    addActivity(String(e.message || e));
    if (!isBtw) setBusy(false);
  } finally {
    sendBtn.disabled = false;
    updateSendButton();
    inputEl.focus();
  }
}

async function boot() {
  try {
    const health = await api('/healthz');
    (health.models || []).forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = m;
      modelEl.appendChild(o);
    });
    const saved = localStorage.getItem('sphereAgyModel') || localStorage.getItem('chatbot.model');
    if (saved) modelEl.value = saved;
    modelEl.onchange = () => {
      localStorage.setItem('chatbot.model', modelEl.value);
      localStorage.setItem('sphereAgyModel', modelEl.value);
    };
  } catch (_) {}
  await ensureSession();
}

if (tabChat) tabChat.addEventListener('click', () => switchTab('chat'));
if (tabArtifacts) tabArtifacts.addEventListener('click', () => switchTab('artifacts'));
if (tabActivity) tabActivity.addEventListener('click', () => switchTab('activity'));
if (tabStatus) tabStatus.addEventListener('click', () => switchTab('status'));
if (statusRefreshBtn) statusRefreshBtn.addEventListener('click', () => fetchSelfStatus());
if (usageRefreshBtn) usageRefreshBtn.addEventListener('click', () => fetchUsage(true));
if (mcpAddBtn) mcpAddBtn.addEventListener('click', async () => {
  const name = (mcpNameInput && mcpNameInput.value || '').trim();
  const url = (mcpUrlInput && mcpUrlInput.value || '').trim();
  if (!name || !url) { alert('이름과 serverUrl을 모두 입력하세요.'); return; }
  mcpAddBtn.disabled = true;
  try {
    await api('/api/mcp', { method: 'POST', body: JSON.stringify({ name, serverUrl: url }) });
    addActivity('MCP ' + name + ' 추가됨 (다음 새 세션부터 반영)');
    if (mcpNameInput) mcpNameInput.value = '';
    if (mcpUrlInput) mcpUrlInput.value = '';
    fetchSelfStatus();
  } catch (e) {
    alert('추가 실패: ' + e.message);
  } finally {
    mcpAddBtn.disabled = false;
  }
});
if (actToggle) {
  actToggle.addEventListener('click', () => {
    if (currentTab === 'activity') switchTab('chat');
    else switchTab('activity');
  });
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

sendBtn.addEventListener('click', send);

if (stopBtn) {
  stopBtn.addEventListener('click', async () => {
    if (!sessionId) return;
    stopBtn.disabled = true;
    try {
      addActivity('작업 중지 요청…');
      await api('/api/sessions/' + encodeURIComponent(sessionId) + '/stop', { method: 'POST' });
      setBusy(false);
      if (assistantNode && assistantNode.dataset.progress === '1') {
        assistantNode.remove();
      }
      assistantNode = null; assistantBuf = '';
      addChat('assistant', '작업을 중지했습니다냥.', true);
    } catch (e) {
      addActivity('중지 오류: ' + (e.message || e));
    } finally {
      stopBtn.disabled = false;
    }
  });
}


async function waitHostBack(maxMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try {
      await api('/healthz');
      return true;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

async function defibrillateHost() {
  if (!confirm('전기충격(심폐소생)을 실행할까요?\n호스트가 재기동되며 몇 초 연결이 끊깁니다.')) return;
  setProgress('⚡ 전기충격 · 호스트 소생 중…');
  const btn = document.getElementById('defibBtn');
  if (btn) btn.disabled = true;
  try {
    try {
      await api('/api/host/defibrillate', { method: 'POST', body: '{}' });
    } catch (_) {
      /* server may die mid-response — expected */
    }
    addActivity('⚡ 전기충격 예약 — 호스트 재기동 대기');
    const ok = await waitHostBack(90000);
    if (!ok) {
      setProgress('소생 시간 초과 · 수동 새로고침 해보세요');
      addActivity('소생 실패/시간초과');
      return;
    }
    setProgress('소생 완료 · 세션 재연결…');
    await ensureSession();
    setProgress('⚡ 소생 완료');
    addActivity('⚡ 심폐소생 완료');
  } finally {
    if (btn) btn.disabled = false;
  }
}

newBtn.addEventListener('click', () => createSession().catch(e => addActivity(String(e.message || e))));
const defibBtn = document.getElementById('defibBtn');
if (defibBtn) defibBtn.addEventListener('click', () => defibrillateHost().catch(e => addActivity(String(e.message || e))));
if (continueBtn) {
  continueBtn.addEventListener('click', () => continueSession().catch(e => addActivity(String(e.message || e))));
}
if (sessionBannerContinue) {
  sessionBannerContinue.addEventListener('click', () => continueSession().catch(e => addActivity(String(e.message || e))));
}
if (sessionBannerBtn) {
  sessionBannerBtn.addEventListener('click', () => createSession().catch(e => addActivity(String(e.message || e))));
}
if (sessionBannerDismiss) {
  sessionBannerDismiss.addEventListener('click', () => hideSessionHeavyBanner());
}

function autoResizeInput() {
  if (!inputEl) return;
  const isMobile = window.innerWidth <= 640;
  const minH = isMobile ? 38 : 42;
  const maxH = isMobile ? 90 : 120;

  const val = inputEl.value;
  if (!val || val.trim() === '') {
    inputEl.style.height = minH + 'px';
    inputEl.style.overflowY = 'hidden';
    return;
  }

  inputEl.style.height = minH + 'px';
  const sh = inputEl.scrollHeight;

  if (sh <= minH + 4) {
    inputEl.style.height = minH + 'px';
    inputEl.style.overflowY = 'hidden';
  } else {
    const nextH = Math.min(sh, maxH);
    inputEl.style.height = nextH + 'px';
    inputEl.style.overflowY = sh > maxH ? 'auto' : 'hidden';
  }
}

function updateViewport() {
  const vv = window.visualViewport;
  const h = vv ? Math.round(vv.height) : window.innerHeight;
  document.documentElement.style.setProperty('--app-height', `${h}px`);
  if (window.scrollY !== 0) window.scrollTo(0, 0);
  if (logEl && currentTab === 'chat') {
    logEl.scrollTop = logEl.scrollHeight;
  }
}

if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', updateViewport);
  window.visualViewport.addEventListener('scroll', updateViewport);
}
window.addEventListener('resize', updateViewport);
window.addEventListener('orientationchange', () => setTimeout(updateViewport, 150));
window.addEventListener('scroll', () => {
  if (window.scrollY !== 0) window.scrollTo(0, 0);
});

// --- Slash Commands & Skills Autocomplete Engine ---
const slashMenuEl = document.getElementById('slashMenu');
const slashBtnEl = document.getElementById('slashBtn');
let slashCatalog = {
  commands: [
    { name: "/btw", label: "샛길 질문", desc: "작업 중 즉시 경량 샛길 답변", template: "/btw " },
    { name: "/continue", label: "이어하기", desc: "현재 대화 요약 인계받아 새 세션", template: "/continue" },
    { name: "/new", label: "새 세션", desc: "완전한 새 대화 세션 시작", template: "/new" },
    { name: "/defib", label: "심폐소생", desc: "⚡ 호스트 전기충격·소생 (repair)", template: "/defib" },
    { name: "/status", label: "상태 확인", desc: "챗봇 및 NAS 시스템 상태 점검", template: "/status" },
    { name: "/clear", label: "화면 비우기", desc: "대화창 화면 로그 초기화", template: "/clear" },
    { name: "/compact", label: "세션 압축", desc: "대화 히스토리 수동 압축/요약", template: "/compact" },
  ],
  popular: [
    { name: "/weather", skill: "korea-weather", label: "날씨 조회", desc: "한국 실시간 날씨 및 단기예보", template: "/skill korea-weather " },
    { name: "/geeknews", skill: "geeknews-search", label: "긱뉴스", desc: "최신 IT 트렌드 및 개발 소식 검색", template: "/skill geeknews-search " },
    { name: "/kopis", skill: "kopis-performance-search", label: "공연 정보", desc: "KOPIS 공연·뮤지컬·전시 검색", template: "/skill kopis-performance-search " },
    { name: "/news", skill: "naver-news-search", label: "네이버 뉴스", desc: "네이버 실시간 뉴스 검색", template: "/skill naver-news-search " },
    { name: "/shopping", skill: "naver-shopping-search", label: "네이버 쇼핑", desc: "네이버 쇼핑 최저가 검색", template: "/skill naver-shopping-search " },
    { name: "/delivery", skill: "delivery-tracking", label: "택배 배송", desc: "택배 배송 실시간 추적", template: "/skill delivery-tracking " },
    { name: "/daangn", skill: "daangn-used-goods-search", label: "당근마켓", desc: "당근마켓 중고 매물 검색", template: "/skill daangn-used-goods-search " },
    { name: "/lotto", skill: "lotto-results", label: "로또 번호", desc: "로또 당첨 번호 및 추첨 결과", template: "/skill lotto-results " },
    { name: "/stock", skill: "korean-stock-search", label: "주식 시세", desc: "국내 주식 시세 및 종목 정보", template: "/skill korean-stock-search " },
    { name: "/bus", skill: "express-bus-booking", label: "고속버스", desc: "고속·시외버스 예매 및 시간표", template: "/skill express-bus-booking " },
  ],
  skills: []
};

let slashVisibleItems = [];
let slashSelectedIndex = 0;

async function loadSlashSkills() {
  try {
    const data = await api('/api/skills');
    if (data && data.ok) {
      if (data.commands && data.commands.length) slashCatalog.commands = data.commands;
      if (data.popular && data.popular.length) slashCatalog.popular = data.popular;
      if (data.skills && data.skills.length) slashCatalog.skills = data.skills;
    }
  } catch (_) {}
}

function hideSlashMenu() {
  if (!slashMenuEl) return;
  slashMenuEl.hidden = true;
  slashVisibleItems = [];
  slashSelectedIndex = 0;
  if (slashBtnEl) slashBtnEl.classList.remove('active');
}

function renderSlashMenu(query) {
  if (!slashMenuEl) return;
  const q = (query || '').toLowerCase().trim();
  
  const cmds = slashCatalog.commands.filter(c => 
    !q || c.name.toLowerCase().includes(q) || (c.label && c.label.toLowerCase().includes(q)) || (c.desc && c.desc.toLowerCase().includes(q))
  );

  const pops = slashCatalog.popular.filter(p => 
    !q || p.name.toLowerCase().includes(q) || (p.skill && p.skill.toLowerCase().includes(q)) || (p.label && p.label.toLowerCase().includes(q)) || (p.desc && p.desc.toLowerCase().includes(q))
  );

  const popSkillSet = new Set(slashCatalog.popular.map(p => p.skill));
  let otherSkills = [];
  if (q) {
    otherSkills = slashCatalog.skills.filter(s => 
      !popSkillSet.has(s.name) && (s.name.toLowerCase().includes(q) || (s.desc && s.desc.toLowerCase().includes(q)))
    ).slice(0, 10);
  }

  slashVisibleItems = [];
  let html = '';

  if (cmds.length) {
    html += '<div class="slash-category">⚡ 기능 / 명령어</div>';
    cmds.forEach(c => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(c);
      html += `<div class="slash-item" data-idx="${idx}">
        <span class="slash-badge cmd">명령어</span>
        <span class="slash-name">${escapeHtml(c.name)}</span>
        <span class="slash-desc">${escapeHtml(c.desc || c.label)}</span>
      </div>`;
    });
  }

  if (pops.length) {
    html += '<div class="slash-category">🛠️ 추천 스킬</div>';
    pops.forEach(p => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(p);
      html += `<div class="slash-item" data-idx="${idx}">
        <span class="slash-badge skill">스킬</span>
        <span class="slash-name">${escapeHtml(p.name)}</span>
        <span class="slash-desc">${escapeHtml(p.desc || p.label)}</span>
      </div>`;
    });
  }

  if (otherSkills.length) {
    html += '<div class="slash-category">📦 전체 스킬 검색</div>';
    otherSkills.forEach(s => {
      const idx = slashVisibleItems.length;
      slashVisibleItems.push(s);
      html += `<div class="slash-item" data-idx="${idx}">
        <span class="slash-badge skill">스킬</span>
        <span class="slash-name">/skill ${escapeHtml(s.name)}</span>
        <span class="slash-desc">${escapeHtml(s.desc || s.name)}</span>
      </div>`;
    });
  }

  if (!slashVisibleItems.length) {
    html = '<div class="slash-empty">일치하는 명령어 또는 스킬이 없습니다냥 ฅ</div>';
  }

  slashMenuEl.innerHTML = html;
  slashMenuEl.hidden = false;
  slashSelectedIndex = 0;
  updateSlashSelection();
  if (slashBtnEl) slashBtnEl.classList.add('active');
}

function toggleSlashMenu() {
  if (!slashMenuEl) return;
  if (!slashMenuEl.hidden) {
    hideSlashMenu();
  } else {
    const val = (inputEl && inputEl.value) || '';
    const q = val.startsWith('/') ? val.slice(1) : '';
    renderSlashMenu(q);
    if (inputEl) inputEl.focus();
  }
}

function updateSlashSelection() {
  if (!slashMenuEl) return;
  const items = slashMenuEl.querySelectorAll('.slash-item');
  items.forEach((it, i) => {
    if (i === slashSelectedIndex) {
      it.classList.add('selected');
      it.scrollIntoView({ block: 'nearest' });
    } else {
      it.classList.remove('selected');
    }
  });
}

function applySlashItem(item) {
  if (!item || !inputEl) return;
  inputEl.value = item.template;
  autoResizeInput();
  updateSendButton();
  hideSlashMenu();
  inputEl.focus();
  inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
}

function handleSlashKeydown(e) {
  if (!slashMenuEl || slashMenuEl.hidden || slashVisibleItems.length === 0) return false;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    slashSelectedIndex = (slashSelectedIndex + 1) % slashVisibleItems.length;
    updateSlashSelection();
    return true;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    slashSelectedIndex = (slashSelectedIndex - 1 + slashVisibleItems.length) % slashVisibleItems.length;
    updateSlashSelection();
    return true;
  }
  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault();
    const selected = slashVisibleItems[slashSelectedIndex];
    if (selected) applySlashItem(selected);
    return true;
  }
  if (e.key === 'Escape') {
    e.preventDefault();
    hideSlashMenu();
    return true;
  }
  return false;
}

function setupSlashAutocomplete() {
  if (!inputEl || !slashMenuEl) return;
  loadSlashSkills();

  if (slashBtnEl) {
    slashBtnEl.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      toggleSlashMenu();
    });
  }

  inputEl.addEventListener('input', () => {
    const val = inputEl.value;
    if (val.startsWith('/') && !val.includes(' ') && !val.includes('\n')) {
      renderSlashMenu(val.slice(1));
    } else {
      hideSlashMenu();
    }
  });

  slashMenuEl.addEventListener('pointerdown', (e) => {
    const itemEl = e.target.closest('.slash-item');
    if (!itemEl) return;
    e.preventDefault();
    const idx = parseInt(itemEl.dataset.idx, 10);
    if (!isNaN(idx) && slashVisibleItems[idx]) {
      applySlashItem(slashVisibleItems[idx]);
    }
  });

  document.addEventListener('pointerdown', (e) => {
    if (!slashMenuEl.hidden && !slashMenuEl.contains(e.target) && e.target !== inputEl && (!slashBtnEl || !slashBtnEl.contains(e.target))) {
      hideSlashMenu();
    }
  });
}

inputEl.addEventListener('input', () => {
  updateSendButton();
  autoResizeInput();
});
inputEl.addEventListener('focus', () => {
  setTimeout(() => {
    updateViewport();
    if (logEl && currentTab === 'chat') {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }, 120);
});
inputEl.addEventListener('keydown', (e) => {
  if (handleSlashKeydown(e)) return;
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

setupSlashAutocomplete();
autoResizeInput();
boot().then(() => updateViewport());

