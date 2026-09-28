// app-messages.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// ---- Smart auto-scroll management ----
// If the user has scrolled up to inspect previous conversation history,
// avoid hijacking their scroll position on incoming streaming chunks or tool events.
const SCROLL_BOTTOM_THRESHOLD = 140;

let isLogPinnedToBottom = true;
let isProgrammaticScroll = false;

function isUserNearBottom() {
  const el = (typeof logEl !== 'undefined' && logEl) ? logEl : (typeof document !== 'undefined' && document.getElementById ? document.getElementById('log') : null);
  if (!el) return true;
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
  return distance <= SCROLL_BOTTOM_THRESHOLD;
}

function updateScrollBottomButton(nearBottomOverride) {
  if (!scrollToBottomBtn || !logEl) return;
  if (currentTab !== 'chat' || document.body.classList.contains('keyboard-open')) {
    scrollToBottomBtn.hidden = true;
    return;
  }
  // Past-session browse: the current log bottom is not the latest conversation.
  if (viewingPastSession()) {
    scrollToBottomBtn.hidden = false;
    return;
  }
  const hasOverflow = logEl.scrollHeight > logEl.clientHeight + 40;
  const nearBottom = (nearBottomOverride !== undefined) ? nearBottomOverride : isUserNearBottom();
  scrollToBottomBtn.hidden = !hasOverflow || nearBottom;
}

function scrollChatToBottom(force = false) {
  const el = (typeof logEl !== 'undefined' && logEl) ? logEl : (typeof document !== 'undefined' && document.getElementById ? document.getElementById('log') : null);
  if (!el) return;
  if (force || isLogPinnedToBottom || isUserNearBottom()) {
    isProgrammaticScroll = true;
    el.scrollTop = el.scrollHeight;
    isProgrammaticScroll = false;
    isLogPinnedToBottom = true;
  }
  updateScrollBottomButton();
}

function handleMsgResize(entries) {
  if (typeof isKeyboardTransitioning === 'function' && isKeyboardTransitioning()) {
    return;
  }
  const el = (typeof logEl !== 'undefined' && logEl) ? logEl : (typeof document !== 'undefined' && document.getElementById ? document.getElementById('log') : null);
  if (!el) return;
  if (isLogPinnedToBottom) {
    isProgrammaticScroll = true;
    el.scrollTop = el.scrollHeight;
    isProgrammaticScroll = false;
  }
  updateScrollBottomButton();
}

let msgResizeObserver = null;
if (typeof ResizeObserver !== 'undefined') {
  msgResizeObserver = new ResizeObserver((entries) => {
    handleMsgResize(entries);
  });
}

function observeMessage(node) {
  if (!node) return;
  if (!msgResizeObserver && typeof ResizeObserver !== 'undefined') {
    msgResizeObserver = new ResizeObserver((entries) => {
      handleMsgResize(entries);
    });
  }
  if (msgResizeObserver) {
    msgResizeObserver.observe(node);
  }
}



// ---- TTS (read assistant replies aloud) ----
let ttsUtterance = null;
let ttsKoreanVoice = null;
function pickKoreanVoice() {
  if (!window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices() || [];
  return voices.find(v => v.lang && v.lang.toLowerCase().startsWith('ko')) || null;
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
    alertModal('이 브라우저는 음성 출력(Web Speech API)을 지원하지 않습니다.');
    return;
  }
  const wasSpeaking = window.speechSynthesis.speaking;
  window.speechSynthesis.cancel();
  document.querySelectorAll('.tts-btn.speaking').forEach(b => { b.classList.remove('speaking'); b.innerHTML = getActionSvg('speaker'); });
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
    btn.innerHTML = getActionSvg('stop');
    btn.dataset.wasActive = '1';
  }
  utter.onend = utter.onerror = () => {
    if (btn) { btn.classList.remove('speaking'); btn.innerHTML = getActionSvg('speaker'); btn.dataset.wasActive = '0'; }
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

// ---- Action SVG Helper (OpenHiggsfield / Sphere precision vector icons) ----
﻿function getActionSvg(name, extraClass) {
  // NOTICE_UI_v1: night-console stroke icons (Feather-style), no emoji chrome
  const cls = extraClass ? `action-icon-svg ${extraClass}` : 'action-icon-svg';
  const paths = {
    copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    speaker: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 3z"/>',
    alert: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    spark: '<path d="M12 2l1.6 6.4L20 10l-6.4 1.6L12 18l-1.6-6.4L4 10l6.4-1.6L12 2z"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    pin: '<line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  };
  const danger = (name === 'flame') ? ' text-danger' : (name === 'alert' ? ' text-warning' : '');
  const body = paths[name];
  if (!body) return '';
  return `<svg class="${cls}${danger}" viewBox="0 0 24 24">${body}</svg>`;
}

// NOTICE_UI_v1: host/system notices share night-console chrome, not LLM reply bubbles.
const NOTICE_KINDS = {
  info:   { icon: 'info',     label: '시스템' },
  status: { icon: 'settings', label: '상태' },
  warn:   { icon: 'alert',    label: '주의' },
  error:  { icon: 'alert',    label: '오류' },
  stop:   { icon: 'stop',     label: '중지' },
  ok:     { icon: 'check',    label: '완료' },
  help:   { icon: 'spark',    label: '도움말' },
};

function normalizeNoticeKind(isSystem) {
  if (isSystem === true) return 'info';
  if (typeof isSystem === 'string' && isSystem) {
    const k = String(isSystem).toLowerCase();
    return NOTICE_KINDS[k] ? k : 'info';
  }
  return '';
}

function inferNoticeKindFromText(text) {
  // NOTICE_FLAG_ONLY_v1: intentionally unused — classification is flag-only (h.notice / h.system)
  return '';
}

function stripNoticeChromeEmojis(text) {
  return String(text || '')
    .replace(/^[\p{Extended_Pictographic}\uFE0F\u200D]+/u, '')
    .replace(/^\s*[⚠🛑⏱⚡🧭📍🚨✨✦🐾📋💻📄💬📁📜⚙🗂🛠📦🔢✓✕↻]+/u, '')
    .replace(/\*\*작업 중단 알림\*\*\s*/g, '')
    .replace(/^---+\s*/gm, '')
    .trim();
}

function addNotice(kind, text, ts, ephemeral) {
  const k = normalizeNoticeKind(kind || 'info') || 'info';
  const body = stripNoticeChromeEmojis(text);
  const node = addChat('assistant', body, true, false, false, false, null, null, k, ts);
  if (ephemeral && node) node.dataset.ephemeral = '1';
  return node;
}


let sessionTokens = { total_tokens: 0, input_tokens: 0, output_tokens: 0, thinking_tokens: 0, turns: 0 };

function renderSessionTokensBadge() {
  const badge = document.getElementById('sessionTokenBadge');
  if (!badge) return;
  const occ = Number(sessionTokens.input_tokens || 0);
  const billed = Number(sessionTokens.total_tokens || 0);
  if (occ <= 0 && billed <= 0) {
    badge.style.display = 'none';
    return;
  }
  badge.style.display = 'inline-flex';
  badge.innerHTML = getActionSvg('zap') + ' <span>창 ' + formatTokenCount(occ) + (billed ? '<span class="token-billed"> · 과금 ' + formatTokenCount(billed) + '</span>' : '') + '</span>';
  const out = Number(sessionTokens.output_tokens || 0).toLocaleString();
  const turns = sessionTokens.turns ? ` · ${sessionTokens.turns}회 턴` : '';
  const detail = `창 점유 ${occ.toLocaleString()} (마지막 턴 입력) · 세션 과금 ${billed.toLocaleString()} (턴 total 합, 출력 ${out}${sessionTokens.thinking_tokens ? ' · 생각 ' + Number(sessionTokens.thinking_tokens).toLocaleString() : ''})${turns}. 캐시는 입력에서 빼지 않음.`;
  badge.title = detail;
  badge.setAttribute('aria-label', detail);
}

function updateSessionTokens(usage) {
  if (!usage) return;
  const tot = Number(usage.total_tokens || 0) || (Number(usage.input_tokens || 0) + Number(usage.output_tokens || 0));
  sessionTokens.total_tokens += tot;
  if (Number(usage.input_tokens || 0)) sessionTokens.input_tokens = Number(usage.input_tokens);
  sessionTokens.output_tokens += Number(usage.output_tokens || 0);
  sessionTokens.thinking_tokens += Number(usage.thinking_tokens || 0);
  sessionTokens.turns += 1;
  renderSessionTokensBadge();
}

function setSessionTokensFromHistory(history) {
  sessionTokens = { total_tokens: 0, input_tokens: 0, output_tokens: 0, thinking_tokens: 0, turns: 0 };
  (history || []).forEach(h => {
    const u = h.usage;
    if (!u) return;
    const tot = Number(u.total_tokens || 0) || (Number(u.input_tokens || 0) + Number(u.output_tokens || 0));
    sessionTokens.total_tokens += tot;
    if (Number(u.input_tokens || 0)) sessionTokens.input_tokens = Number(u.input_tokens);
    sessionTokens.output_tokens += Number(u.output_tokens || 0);
    sessionTokens.thinking_tokens += Number(u.thinking_tokens || 0);
    sessionTokens.turns += 1;
  });
  renderSessionTokensBadge();
}

function getUsageLevel(usage) {
  if (!usage) return 'normal';
  // Occupancy = this turn's prompt size. Do not use input-cache_read (cache
  // is not a subset of input) and do not use billed total (includes output).
  const occ = Number(usage.input_tokens || 0) || Number(usage.total_tokens || 0);
  if (occ >= 400000) return 'heavy';
  if (occ >= 150000) return 'warning';
  if (occ >= 80000) return 'moderate';
  return 'normal';
}

// navigator.clipboard.writeText() only exists in secure contexts (HTTPS or
// localhost) -- this host is served plain http:// on a LAN hostname
// (server.py binds 0.0.0.0, no TLS anywhere), so navigator.clipboard is
// undefined in the browser and every copy button (code blocks, this one)
// silently threw and landed in the catch block (operator: "눌러도 복사
// 안되네"). Falls back to the classic hidden-textarea + execCommand('copy')
// trick, which still works without a secure context.
async function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) { /* fall through to the legacy path below */ }
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (_) {
    return false;
  }
}

function shortServedModel(id) {
  const s = String(id || '').trim();
  if (!s) return '';
  const i = s.lastIndexOf('/');
  if (i < 0) return s;
  const tail = s.slice(i + 1);
  return /[.:-]/.test(tail) ? tail : s;
}

function attachMessageFooter(node, rawText, usage, durationSeconds, servedModel) {
  if (!node) return;
  clearTurnLive(node);
  let footer = node.querySelector('.msg-footer');
  if (!footer) {
    footer = document.createElement('div');
    footer.className = 'msg-footer';
    node.appendChild(footer);
  }

  const served = String(servedModel || node.dataset.servedModel || '').trim();
  if (served) node.dataset.servedModel = served;

  // Token & duration badge with visual caution tiers
  if (usage || (durationSeconds != null && durationSeconds > 0)) {
    let badge = footer.querySelector('.token-badge');
    if (!badge) {
      badge = document.createElement('span');
      footer.prepend(badge);
    }
    const level = getUsageLevel(usage);
    badge.className = 'token-badge token-' + level;

    // Apply caution effect to footer line based on token level
    footer.classList.remove('footer-normal', 'footer-moderate', 'footer-warning', 'footer-heavy');
    if (level === 'warning' || level === 'heavy') {
      footer.classList.add('footer-' + level);
    }

    const tokStr = usage && (usage.total_tokens || usage.input_tokens != null)
      ? formatTokenCount(usage.total_tokens || (Number(usage.input_tokens || 0) + Number(usage.output_tokens || 0)))
      : '';
    const durStr = durationSeconds != null && durationSeconds > 0 ? (Number(durationSeconds).toFixed(1) + 's') : '';

    let iconSvg = getActionSvg('zap');
    if (level === 'heavy') iconSvg = getActionSvg('flame');
    else if (level === 'warning') iconSvg = getActionSvg('alert');

    let textPart = '';
    if (tokStr && durStr) textPart = `${tokStr} · ${durStr}`;
    else if (tokStr) textPart = `${tokStr} 토큰`;
    else textPart = durStr;

    badge.innerHTML = iconSvg + (textPart ? ` <span>${textPart}</span>` : '');
    let tip = formatUsageTooltip(usage, durationSeconds);
    if (level === 'heavy') {
      tip = '[대용량 토큰 소모] 누적 컨텍스트가 매우 큽니다. 대화창의 "맥락 이어 새 대화"를 권장합니다.\n' + tip;
    } else if (level === 'warning') {
      tip = '[토큰 사용량 주의] 컨텍스트가 증가하고 있습니다.\n' + tip;
    }
    badge.title = tip;
    badge.setAttribute('aria-label', tip);
  }

  if (served) {
    let tag = footer.querySelector('.served-model');
    if (!tag) {
      tag = document.createElement('span');
      tag.className = 'served-model';
      footer.prepend(tag);
    }
    tag.textContent = shortServedModel(served);
    tag.title = served;
    tag.setAttribute('aria-label', '응답 모델 ' + served);
  }

  // Full-message copy button -- attachCodeCopyButtons only covers ```code```
  // fences; there was no way to grab a whole reply's raw markdown in one
  // click. Placed before the TTS button so it inherits `.tts-btn`'s
  // margin-left:auto (first right-side footer element gets pushed to the
  // edge; the rest just follow in flex order).
  if (rawText && !footer.querySelector('.copy-msg-btn')) {
    const btn = document.createElement('button');
    btn.className = 'tts-btn copy-msg-btn';
    btn.type = 'button';
    btn.title = btn.ariaLabel = '답변 전체 복사';
    btn.innerHTML = getActionSvg('copy');
    btn.onclick = async () => {
      const ok = await copyText(rawText);
      btn.innerHTML = ok ? getActionSvg('check', 'text-accent') : getActionSvg('x', 'text-danger');
      setTimeout(() => { btn.innerHTML = getActionSvg('copy'); }, 1500);
    };
    footer.appendChild(btn);
  }

  // TTS button
  if (window.speechSynthesis && !footer.querySelector('.tts-btn:not(.copy-msg-btn)')) {
    const btn = document.createElement('button');
    btn.className = 'tts-btn';
    btn.type = 'button';
    btn.title = btn.ariaLabel = '읽어주기';
    btn.innerHTML = getActionSvg('speaker');
    btn.onclick = () => speakText(rawText, btn);
    footer.appendChild(btn);
  }
}

function attachTtsButton(node, rawText, usage, durationSeconds, servedModel) {
  attachMessageFooter(node, rawText, usage, durationSeconds, servedModel);
}

function absArtifact(u) {
  if (!u) return '';
  if (u.startsWith('http')) return u;
  const trimmed = String(u).replace(/^\.\//, '');
  const relMedia = trimmed.match(/^(?:images|videos)\/([^/?#]+)$/i);
  if (relMedia && sessionId) {
    return BASE_PATH + '/artifacts/' + encodeURIComponent(sessionId) + '/brain/' + encodeURIComponent(relMedia[1]);
  }
  const full = trimmed.startsWith('/') ? trimmed : '/' + trimmed;
  return (BASE_PATH && full.startsWith(BASE_PATH)) ? full : (BASE_PATH + full);
}



function msgSyncKey(role, ts) {
  return String(role || '') + ':' + String(ts || '');
}

// Two writers draw the log: SSE events and resyncFromServer() (every 2.5s). Whichever
// arrives second must find the message already on screen and stop -- the server stamps
// every history entry and its event with the same ts, so role+ts is the identity.
// (operator: 샛길 카드가 두 장 / 내 말·답이 두 번 -- a late SSE event redrew what a resync
// had already put there.)
function findRenderedByTs(role, ts) {
  if (!logEl || !ts) return null;
  const key = msgSyncKey(role, ts);
  const nodes = logEl.querySelectorAll('.msg[data-ts]');
  for (let i = 0; i < nodes.length; i++) {
    if (msgSyncKey(nodes[i].dataset.syncRole || '', nodes[i].dataset.ts) === key) return nodes[i];
  }
  return null;
}

// A bubble the client closed itself (interrupt / stop / idle resync) has no ts, so a later
// resync would draw the server's copy of it again. Remember how it starts so that copy can
// be adopted instead of duplicated.
function markUntimed(node, rawText) {
  if (!node) return;
  const head = String(rawText || '').trim().slice(0, 80);
  if (!head) return;
  node.dataset.untimed = '1';
  node._rawHead = head;
}

function adoptUntimedAssistant(h) {
  if (!logEl || !h || !h.ts) return false;
  const text = String(h.text || '').trim();
  const nodes = logEl.querySelectorAll('.msg.assistant[data-untimed="1"]');
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (n._rawHead && text.startsWith(n._rawHead)) {
      n.dataset.ts = String(h.ts);
      n.dataset.syncRole = 'assistant';
      delete n.dataset.untimed;
      return true;
    }
  }
  return false;
}

// Same for the user's own bubble: a resync or an ack that finds an unstamped bubble with the
// same text stamps it instead of drawing a second one. It only stamps -- the bubble is already
// where the user put it, and re-placing it by ts made it jump away (to the top of the log)
// whenever no answer bubble was in flight when its ack arrived.
function adoptBareUserBubble(text, ts) {
  if (!logEl || !ts) return false;
  const bare = logEl.querySelectorAll('.msg.user:not([data-ts]), .msg.action:not([data-ts])');
  for (let i = 0; i < bare.length; i++) {
    const content = bare[i].textContent || '';
    if (content === (text || '') || (text && text.startsWith('(') && text.endsWith(')') && content === '✦ ' + text.slice(1, -1))) {
      bare[i].dataset.ts = String(ts);
      bare[i].dataset.syncRole = bare[i].classList.contains('action') ? 'action' : (bare[i].classList.contains('btw-user') ? 'btw-user' : 'user');
      return true;
    }
  }
  return false;
}

function inFlightAssistant() {
  if (!logEl) return null;
  // A system notice (greeting, /help, ...) has no ts either but is never a turn in flight:
  // treating it as one made placeMsgByTs() insert a message above the greeting, i.e. at the top.
  // Same for a bubble the client closed itself (data-untimed, waiting for its ts).
  return logEl.querySelector('.msg[data-live="1"]') || logEl.querySelector('.msg.assistant:not([data-ts]):not(.system):not([data-untimed])');
}

function placeMsgByTs(div, ts) {
  if (!logEl) return;
  observeMessage(div);
  if (ts) div.dataset.ts = String(ts);
  const live = inFlightAssistant();
  if (ts) {
    const tagged = logEl.querySelectorAll('.msg[data-ts]');
    for (let i = 0; i < tagged.length; i++) {
      const n = tagged[i];
      if (n === div) continue;
      if (Number(n.dataset.ts) > Number(ts)) {
        logEl.insertBefore(div, n);
        return;
      }
    }
  }
  if (live && live !== div) logEl.insertBefore(div, live);
  else {
    logEl.appendChild(div);
    scrollChatToBottom(div.classList.contains('user'));
  }
  parkSessionBanner();
}

function repairMsgOrder() {
  if (!logEl) return;
  for (let guard = 0; guard < 24; guard++) {
    let moved = false;
    const assistants = Array.prototype.slice.call(logEl.querySelectorAll('.msg.assistant'));
    for (let i = 0; i < assistants.length; i++) {
      const a = assistants[i];
      const live = a.dataset.live === '1';
      const aTs = Number(a.dataset.ts || 0);
      // A finished (non-live) message with no ts (e.g. an older scrollback
      // hop rendered before ts round-tripped through here) is unknown, not
      // "still streaming" -- treating it as ts=Infinity used to yank every
      // following user bubble in front of it on every pass, clumping a
      // whole backfilled session into "all questions, then all answers"
      // (operator 2026-09-18, right after a reload auto-backfilled scrollback).
      if (!live && !aTs) continue;
      let sib = a.nextElementSibling;
      while (sib && sib.classList.contains('msg') && sib.classList.contains('user')) {
        if (sib.classList.contains('queued')) break;
        const uTs = Number(sib.dataset.ts || 0);
        if (!live && !uTs) break; // no ts on either side -- nothing to safely correct
        if (live || uTs <= aTs) {
          const next = sib.nextElementSibling;
          logEl.insertBefore(sib, a);
          moved = true;
          sib = next;
          continue;
        }
        break;
      }
    }
    if (!moved) break;
  }
  parkSessionBanner();
}

// The user's /btw question is a client-only bubble: no ts, and the server neither stores nor
// acks it. So the answer card can't be ordered against it by ts, and the resync's
// repairMsgOrder() hoists ts-less user bubbles above a streaming answer -- which left the card
// ahead of its own question whenever the answer beat the next 2.5s tick (operator: "첫 질문은
// 질문 다음에 대답인데 그 다음 btw는 대답이 질문 전에"). Two rules make the order fixed:
//   1. the question goes above the streaming bubble from the start (where hoisting would put it)
//   2. the answer card is placed right after ITS question bubble, paired by the question text
function btwQueryOf(text) {
  return String(text || '').trim().replace(/^\/btw(?:\s+|$)/, '').trim();
}

function addBtwQuestionBubble(text) {
  const bubble = addChat('user', text, false, false, true);
  const live = logEl.querySelector('.msg[data-live="1"]');   // a real in-flight turn only
  if (live && live !== bubble) logEl.insertBefore(bubble, live);
  return bubble;
}

// Oldest still-unanswered question bubble with this text (the same question can be asked twice).
function findBtwQuestionBubble(query) {
  const q = String(query || '').trim();
  if (!q || !logEl) return null;
  const bubbles = logEl.querySelectorAll('.msg.user.btw-user:not([data-btw-answered])');
  for (let i = 0; i < bubbles.length; i++) {
    if (btwQueryOf(bubbles[i].textContent) === q) return bubbles[i];
  }
  return null;
}

function addBtw(query, answer, prepend, usage, durationSeconds, ts) {
  const div = document.createElement('div');
  div.className = 'msg btw-card';
  observeMessage(div);
  div.dataset.syncRole = 'btw';
  if (ts) div.dataset.ts = String(ts);
  const head = document.createElement('div');
  head.className = 'btw-head';
  const _btwIcon = typeof getActionSvg === 'function' ? getActionSvg('compass') : '';
  head.innerHTML = _btwIcon + '<span>샛길 응답 (/btw)</span>' + (query ? '<span class="btw-q">Q. ' + escapeHtml(query) + '</span>' : '');
  const body = document.createElement('div');
  body.className = 'btw-body md';
  body.innerHTML = renderMarkdown(answer || '', true);
  div.appendChild(head);
  div.appendChild(body);
  postProcessAssistant(body, true, answer, usage, durationSeconds);
  const qBubble = prepend ? null : findBtwQuestionBubble(query);
  if (qBubble) {
    qBubble.dataset.btwAnswered = '1';
    logEl.insertBefore(div, qBubble.nextSibling);   // null nextSibling = end of the log
    scrollChatToBottom(false);
  } else if (prepend) {
    logEl.insertBefore(div, logEl.firstChild);
  } else if (ts) {
    placeMsgByTs(div, ts);
  } else {
    logEl.appendChild(div);
    scrollChatToBottom(false);
  }
  parkSessionBanner();
  return div;
}

// OUT_OF_BAND_CHOICES_v1: the server takes an answer's choices out of its text and sends them beside it
// (`choices` on the history item and the result event). The chip renderer still reads a trailing marker, so the
// page puts it back only for drawing: it is never stored and never reaches the CLI or the agent.
function textWithChoices(h) {
  function choiceItemToMarker(x) {
    if (typeof x === 'string') return x.trim();
    if (x && typeof x === 'object' && x.label) {
      const lbl = String(x.label).trim();
      if (!lbl) return '';
      if (x.kind === 'action' || x.isAction) {
        let act = String(x.payload || x.action || lbl).trim();
        // #246: dialogue-flavor / combo stay as-is (still action on click). Bare acts → (행동).
        if (act && !/^"/.test(act)) {
          const bare = (typeof stripOuterParens === 'function') ? stripOuterParens(act) : act.replace(/^\(+|\)+$/g, '').trim();
          act = '(' + bare + ')';
        }
        return lbl + ' -> ' + act;
      }
      if (x.kind === 'command') {
        const cmd = String(x.payload || lbl).trim();
        return lbl + ' -> command: ' + cmd;
      }
      const p = String(x.payload || '').trim();
      return (p && p !== lbl) ? lbl + ' -> ' + p : lbl;
    }
    return '';
  }
  const text = (h && h.text) || '';
  const c = h && Array.isArray(h.choices) ? h.choices.map(choiceItemToMarker).filter(Boolean) : [];
  return c.length ? text + '\n<!--choices: ' + c.join(' | ') + '-->' : text;
}

// A choices event can beat the turn's first text chunk (the tool runs before the answer streams): it waits here
// for this turn's bubble instead of landing on the previous answer. addChat takes it; the next user turn drops it.
let pendingChoices = null;

function handleChoicesEvent(data) {
  if (!data) return;
  const choices = Array.isArray(data.choices) ? data.choices : (Array.isArray(data.items) ? data.items : null);
  if (!choices || !choices.length) return;
  if (typeof logEl === 'undefined' || !logEl) return;
  let target = (typeof assistantNode !== 'undefined' && assistantNode && assistantNode.isConnected) ? assistantNode : null;
  if (!target && typeof isBusy !== 'undefined' && isBusy) {
    pendingChoices = choices;
    return;
  }
  if (!target) {
    const assistants = logEl.querySelectorAll('.msg.assistant');
    if (assistants.length) target = assistants[assistants.length - 1];
  }
  if (!target) return;
  target._choices = choices;
  if (typeof renderChoiceChips === 'function') {
    renderChoiceChips(target, choices);
    if (typeof syncChoiceChips === 'function') syncChoiceChips();
  }
}

// Hook EventSource so choices events from SSE are delivered to handleChoicesEvent
(function hookEventSourceForChoices() {
  if (typeof window === 'undefined' || !window.EventSource) return;
  const OrigES = window.EventSource;
  window.EventSource = function(...args) {
    const inst = new OrigES(...args);
    inst.addEventListener('message', (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data && (data.event === 'choices' || data.type === 'choices')) {
          handleChoicesEvent(data);
        }
      } catch (_) {}
    });
    return inst;
  };
  window.EventSource.prototype = OrigES.prototype;
})();

function addChat(role, text, isFinal, isQueued, isBtw, prepend, usage, durationSeconds, isSystem, ts, servedModel, choices) {
  const div = document.createElement('div');
  observeMessage(div);
  // NOTICE_UI_v1: isSystem may be true or a notice kind string
  const noticeKind = normalizeNoticeKind(isSystem);
  div.className = 'msg ' + role + (noticeKind ? ' system notice-' + noticeKind : '');
  if (noticeKind) div.dataset.notice = noticeKind;
  if (isQueued) div.classList.add('queued');
  if (isBtw) div.classList.add('btw-user');
  div.dataset.syncRole = isBtw ? 'btw-user' : (role || '');
  if (ts) div.dataset.ts = String(ts);
  if (servedModel) div.dataset.servedModel = String(servedModel);
  if (role === 'user' && !prepend) pendingChoices = null;
  if (role === 'assistant' && !noticeKind && !prepend && !ts && !choices && pendingChoices) {
    choices = pendingChoices;
    pendingChoices = null;
  }
  if (choices) div._choices = choices;
  if (role === 'assistant') {
    if (noticeKind) {
      const meta = NOTICE_KINDS[noticeKind] || NOTICE_KINDS.info;
      const head = document.createElement('div');
      head.className = 'notice-head';
      head.innerHTML = getActionSvg(meta.icon) + '<span class="notice-label">' + meta.label + '</span>';
      div.appendChild(head);
    }
    const md = document.createElement('div');
    md.className = 'md';
    const bodyText = noticeKind ? stripNoticeChromeEmojis(text) : (text || '');
    renderTypedBody(md, bodyText, isFinal);
    div.appendChild(md);
    postProcessAssistant(div, isFinal, bodyText, usage, durationSeconds, Boolean(noticeKind), servedModel, choices || div._choices);
  } else {
    div.textContent = text || '';
  }
  if (role === 'user' && !prepend) currentSessionHasUser = true;
  if (prepend) {
    logEl.insertBefore(div, logEl.firstChild);
  } else if (ts) {
    placeMsgByTs(div, ts);
  } else {
    logEl.appendChild(div);
    // User's own message forces scroll to bottom; other events only scroll if already near bottom
    scrollChatToBottom(role === 'user');
  }
  parkSessionBanner();
  syncChoiceChips();
  return div;
}

// BLOCK_KINDS_v1: render a finished answer as the kinds it is made of. Everything stays inside one
// .md, so postProcessAssistant, the emotion badge, the thought box and the choice chips keep working
// exactly as before -- they look for .md, not for a flat blob. If classification surprises us in any
// way, the whole thing falls back to the single-blob render: a lost treatment is free, a broken
// conversation is not.
//
// Every finished answer gets blocks, including a plain one with no action and no speech. The blocks
// are what the entrance animation is applied to, so a short reply that happens to be one kind of
// sentence has to have them too -- an earlier version skipped them for that case and the animation
// simply could not appear on most replies.
function renderTypedBody(md, rawText, isFinal) {
  const body = rawText || '';
  try {
    const blocks = classifyBlocks(body);
    md.textContent = '';
    blocks.forEach((block, bi) => {
      const box = document.createElement('div');
      box.className = 'md-block';
      box.setAttribute('data-kind', block.kind);
      box.style.setProperty('--i', String(bi));       // a stagger, capped in the stylesheet
      const runs = blockRuns(block);
      runs.forEach((run) => {
        // Markdown in, HTML out: per run, so a list or a code fence inside the block still parses
        // exactly as it did when the block was one string.
        const holder = document.createElement(run.kind === 'narration' ? 'div' : 'span');
        if (run.kind !== 'narration') {
          holder.className = 'md-' + run.kind;
          holder.setAttribute('data-kind', run.kind);
        }
        holder.innerHTML = renderMarkdown(run.text, isFinal);
        while (holder.firstChild) box.appendChild(holder.firstChild);
      });
      md.appendChild(box);
    });
  } catch (e) {
    md.innerHTML = renderMarkdown(body, isFinal);   // a classifier surprise must not cost a reply
  }
}

function setAssistantContent(node, text, isFinal, usage, durationSeconds, servedModel, choices) {
  if (!node) return;
  if (servedModel) node.dataset.servedModel = String(servedModel);
  if (choices) node._choices = choices;
  const md = node.querySelector('.md') || node;
  renderTypedBody(md, text || '', isFinal);
  postProcessAssistant(node, isFinal, text, usage, durationSeconds, undefined, servedModel, choices || (node && node._choices));
  syncChoiceChips();
  scrollChatToBottom(false);
}
