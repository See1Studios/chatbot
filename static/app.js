const BASE_PATH = window.location.pathname.startsWith('/chat') ? '/chat' : '';
const SESSION_KEY = 'chatbot.sessionId';
const logEl = document.getElementById('log');
const activityPaneEl = document.getElementById('activityPane');
const activityEl = document.getElementById('activity');
const actSearchInput = document.getElementById('actSearchInput');
const actCopyBtn = document.getElementById('actCopyBtn');
const actRefreshBtn = document.getElementById('actRefreshBtn');
const metaEl = document.getElementById('meta');
var inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const stopBtn = document.getElementById('stopBtn');
const geoBtn = document.getElementById('geoBtn');
const sessionBanner = document.getElementById('sessionBanner');
const sessionBannerContinue = document.getElementById('sessionBannerContinue');
const sessionBannerBtn = document.getElementById('sessionBannerNew');
const sessionBannerDismiss = document.getElementById('sessionBannerDismiss');
const scrollToBottomBtn = document.getElementById('scrollToBottomBtn');
let currentSessionHasUser = false;
let sessionActionsDismissed = false;
let sessionNavPrevSid = '';
let sessionNavNextSid = '';
let liveSessionId = '';
let archiveBrowse = false;
let historyLoadHoldUntil = 0;

// ---- Browser & Device Context (GPS, timezone, device type) ----
const GEO_ENABLED_KEY = 'chatbot.geoEnabled';
let geoEnabled = localStorage.getItem(GEO_ENABLED_KEY) === 'true';
let cachedCoords = null;

function updateGeoButtonState() {
  if (!geoBtn) return;
  geoBtn.classList.toggle('active', geoEnabled);
  geoBtn.setAttribute('aria-pressed', String(geoEnabled));
  geoBtn.title = geoEnabled
    ? '기기 환경 및 위치 정보 동기화 활성 중 (클릭하여 끄기)'
    : '기기 환경 및 위치 정보 동기화 (클릭하여 켜기)';
}

function fetchCoordinates() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    pos => {
      cachedCoords = {
        lat: Number(pos.coords.latitude.toFixed(4)),
        lon: Number(pos.coords.longitude.toFixed(4)),
      };
    },
    err => {
      // Permission denied or unavailable; keep fallback or null
      cachedCoords = null;
    },
    { timeout: 5000, maximumAge: 60000 }
  );
}

if (geoBtn) {
  updateGeoButtonState();
  if (geoEnabled) fetchCoordinates();
  geoBtn.addEventListener('click', () => {
    geoEnabled = !geoEnabled;
    try {
      localStorage.setItem(GEO_ENABLED_KEY, String(geoEnabled));
    } catch(e) {}
    updateGeoButtonState();
    if (geoEnabled) {
      fetchCoordinates();
      addActivity('기기 환경 및 위치 정보 동기화 켜짐 📍');
    } else {
      cachedCoords = null;
      addActivity('기기 환경 및 위치 정보 동기화 꺼짐');
    }
  });
}

function getClientContext() {
  if (!geoEnabled) return null;
  const isMobile = Boolean(/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent));
  let timezone = '';
  try {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch(e) {}
  const ctx = {
    is_mobile: isMobile,
    device: isMobile ? '모바일' : '데스크톱',
  };
  if (timezone) ctx.timezone = timezone;
  if (cachedCoords) {
    ctx.lat = cachedCoords.lat;
    ctx.lon = cachedCoords.lon;
  }
  return ctx;
}

// ---- Smart auto-scroll management ----
// If the user has scrolled up to inspect previous conversation history,
// avoid hijacking their scroll position on incoming streaming chunks or tool events.
const SCROLL_BOTTOM_THRESHOLD = 140;

function isUserNearBottom() {
  if (!logEl) return true;
  const distance = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
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
  if (!logEl) return;
  if (force || isUserNearBottom()) {
    logEl.scrollTop = logEl.scrollHeight;
  }
  updateScrollBottomButton();
}

if (scrollToBottomBtn) {
  scrollToBottomBtn.addEventListener('click', () => { goToLatestConversation(); });
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
function getActionSvg(name, extraClass) {
  const cls = extraClass ? `action-icon-svg ${extraClass}` : 'action-icon-svg';
  switch (name) {
    case 'copy':
      return `<svg class="${cls}" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
    case 'check':
      return `<svg class="${cls}" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`;
    case 'speaker':
      return `<svg class="${cls}" viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>`;
    case 'stop':
      return `<svg class="${cls}" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>`;
    case 'zap':
      return `<svg class="${cls}" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`;
    case 'flame':
      return `<svg class="${cls} text-danger" viewBox="0 0 24 24"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 3z"/></svg>`;
    case 'alert':
      return `<svg class="${cls} text-warning" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
    case 'pin':
      return `<svg class="${cls}" viewBox="0 0 24 24"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z"/></svg>`;
    case 'trash':
      return `<svg class="${cls}" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`;
    default:
      return '';
  }
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
// silently threw and landed in the catch block (실장님: "눌러도 복사
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
      tip = '🚨 [대용량 토큰 소모] 누적 컨텍스트가 매우 큽니다. 대화창의 "맥락 이어 새 대화"를 권장합니다.\n' + tip;
    } else if (level === 'warning') {
      tip = '⚠️ [토큰 사용량 주의] 컨텍스트가 증가하고 있습니다.\n' + tip;
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
      btn.innerHTML = ok ? getActionSvg('check', 'text-accent') : '✕';
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

function detachSessionBanner() {
  if (!sessionBanner || sessionBanner.parentNode !== logEl) return;
  const host = document.getElementById('progress');
  if (host && host.parentNode) host.parentNode.insertBefore(sessionBanner, host);
}

function parkSessionBanner() {
  if (!sessionBanner || !logEl) return;
  if (sessionBanner.hidden && sessionBanner.parentNode !== logEl) return;
  if (logEl.lastElementChild !== sessionBanner) logEl.appendChild(sessionBanner);
}

function applySessionActionMode(mode, text) {
  if (!sessionBanner) return;
  sessionBanner.dataset.mode = mode;
  sessionBanner.classList.toggle('hard', mode === 'hard');
  const msgEl = sessionBanner.querySelector('.session-banner-msg');
  if (sessionBannerContinue) {
    sessionBannerContinue.className = (mode === 'quiet') ? 'ghost' : 'primary';
    sessionBannerContinue.textContent = (mode === 'quiet') ? '맥락 이어가기' : '맥락 이어 새 대화 ✦';
  }
  if (sessionBannerBtn) {
    sessionBannerBtn.textContent = (mode === 'quiet') ? '새 대화' : '완전 새 세션';
  }
  if (msgEl) {
    msgEl.textContent = (mode === 'quiet')
      ? ''
      : (text || (mode === 'hard'
        ? '세션이 길어져 새 채팅으로 전환하는 게 좋다냥'
        : '세션이 길어져서 느려질 수 있어요. 새 채팅을 권장합니다'));
  }
}

function syncSessionActions() {
  if (!sessionBanner) return;
  const weight = sessionBanner.dataset.level || 'ok';
  const needsPrompt = (weight === 'hard') || (weight === 'soft' && !sessionActionsDismissed);
  if (isBusy) {
    sessionBanner.hidden = true;
    return;
  }
  if (!currentSessionHasUser && !needsPrompt) {
    sessionBanner.hidden = true;
    return;
  }
  if (sessionActionsDismissed && weight !== 'hard') {
    sessionBanner.hidden = true;
    return;
  }
  let mode = 'quiet';
  let text = sessionBanner.dataset.message || '';
  if (weight === 'hard') mode = 'hard';
  else if (weight === 'soft' && !sessionActionsDismissed) mode = 'soft';
  applySessionActionMode(mode, text);
  sessionBanner.hidden = false;
  parkSessionBanner();
  if (logEl && typeof currentTab !== 'undefined' && currentTab === 'chat') {
    const room = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
    if (room < 96) logEl.scrollTop = logEl.scrollHeight;
  }
}

function showSessionHeavyBanner(level, text) {
  if (!sessionBanner) return;
  sessionBanner.dataset.level = level || 'soft';
  sessionBanner.dataset.message = text || '';
  if (level === 'hard') sessionActionsDismissed = false;
  syncSessionActions();
}
function hideSessionHeavyBanner() {
  sessionActionsDismissed = true;
  syncSessionActions();
}

const modelEl = document.getElementById('model');
const providerEl = document.getElementById('provider');
// Session provider/model on the server is SSOT across devices.
// localStorage is a cache; a stale picker must not overwrite the live session.
let lastServerProvider = '';
let lastServerModel = '';
let localProviderEdit = 0;
const wrapEl = document.getElementById('appWrap');
const actToggle = document.getElementById('activityToggle');

// Artifact elements
const tabChat = document.getElementById('tabChat');
const tabArtifacts = document.getElementById('tabArtifacts');
const tabActivity = document.getElementById('tabActivity');
const tabStatus = document.getElementById('tabStatus');
const tabSessions = document.getElementById('tabSessions');
const sessionsPaneEl = document.getElementById('sessionsPane');
const sessionsListEl = document.getElementById('sessionsList');
const sessionsRefreshBtn = document.getElementById('sessionsRefreshBtn');
const statusPaneEl = document.getElementById('statusPane');
const statusRefreshBtn = document.getElementById('statusRefreshBtn');

// Compact mode (?compact=1): this exact same page, embedded in a small
// iframe from the Hub FAB popup, instead of maintaining a second ~950-line
// FAB-only implementation that drifts out of sync with this one (실장님:
// "본체의 compact한 버전이니까" -- share everything, design/layout only
// differs). Keeps 대화/아티팩트/로그/세션 (실장님: "위에 공간이 많이 남았으니
// 로그도 노출해도 될 것 같네" / "아티팩트도" -- there's headroom for them
// after all), drops only 상태 (host-admin, not a casual-popup concern), the
// "← Hub" link (meaningless inside an iframe already sitting on
// the Hub page), and the defib button (host-repair action).
const isCompactMode = new URLSearchParams(location.search).get('compact') === '1';
if (isCompactMode) document.documentElement.classList.add('compact-mode');
const bootProviderIntent = new URLSearchParams(location.search).get('provider');
function applyCompactMode() {
  if (!isCompactMode) return;
  const hub = document.getElementById('hubLink');
  if (hub) hub.style.display = 'none';
  if (tabStatus) tabStatus.style.display = 'none';
  const defib = document.getElementById('defibBtn');
  if (defib) defib.style.display = 'none';
  // The host-repair item is hidden above and the theme picker is not a popup
  // concern -- hide the ⋯ trigger itself.
  const moreBtn = document.getElementById('moreMenuBtn');
  if (moreBtn) moreBtn.style.display = 'none';
}
applyCompactMode();
const statusMemoryEl = document.getElementById('statusMemory');
const statusRulesEl = document.getElementById('statusRules');
const statusSkillsEl = document.getElementById('statusSkills');
const statusSkillLibHintEl = document.getElementById('statusSkillLibHint');
const statusMcpEl = document.getElementById('statusMcp');
const statusHooksEl = document.getElementById('statusHooks');
const statusObserverEl = document.getElementById('statusObserver');
const statusObsBoxEl = document.getElementById('statusObsBox');
const statusTicketBoxEl = document.getElementById('statusTicketBox');
const ticketBarEl = document.getElementById('ticketBar');
const mcpNameInput = document.getElementById('mcpNameInput');
const mcpUrlInput = document.getElementById('mcpUrlInput');
const mcpAddBtn = document.getElementById('mcpAddBtn');
const statusUsageEl = document.getElementById('statusUsage');
const usageCheckedAtEl = document.getElementById('usageCheckedAt');
const usageRefreshBtn = document.getElementById('usageRefreshBtn');
const statusAccountsEl = document.getElementById('statusAccounts');
const statusProviderTitleEl = document.getElementById('statusProviderTitle');
const statusPickerEl = document.getElementById('statusProviderPicker');
const statusProcsEl = document.getElementById('statusProcs');
const statusProcsSummaryEl = document.getElementById('statusProcsSummary');
const statusProcListEl = document.getElementById('statusProcList');
let statusLoaded = false;
const confirmModalEl = document.getElementById('confirmModal');
const confirmModalMsgEl = document.getElementById('confirmModalMsg');
const confirmModalOkBtn = document.getElementById('confirmModalOk');
const confirmModalCancelBtn = document.getElementById('confirmModalCancel');

var sessionId = localStorage.getItem(SESSION_KEY)
  || localStorage.getItem('sphereAgySession')
  || localStorage.getItem('sphereAgyHubSession')
  || '';
let es = null;
let assistantNode = null;
let assistantBuf = '';
let isBusy = false;
let lastSyncedTs = 0; // ts of newest history item known to be rendered; drives SSE-reconnect resync
// Scroll-up-to-load-more state: walks the predecessor_session_id chain one hop
// at a time as the user nears the top of #log, so older (rotated-away)
// sessions read like one continuous conversation without ever being fed back
// into agy's actual context.
let scrollbackSid = '';
let scrollbackExhausted = false;
let scrollbackLoading = false;
// Scroll-down-to-load-newer (scrollforward) state: walks successor_session_id /
// chronologically-newer sessions when scrolling downwards in an older session archive.
let scrollforwardSid = '';
let scrollforwardExhausted = true;
let scrollforwardLoading = false;
let scrollforwardVisited = new Set();

// Tags this window's own outgoing messages so the shared session's user_ack
// broadcast (received by every window/tab subscribed to the same session)
// can tell "my own just-sent message, already rendered" apart from "another
// window sent this, render it now".
const myPendingMids = new Set();
function _newClientMid() {
  if (window.crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
}
// Guards against cycles in the chronological-fallback chain (observed:
// two sessions with near-identical mtimes can each resolve to the other
// as "next older" depending on exactly when each is read) -- never revisit
// a session id already walked in this scrollback chain.
let scrollbackVisited = new Set();
let progressEl = document.getElementById('progress');

var currentTab = 'chat';
let activityNextBefore = null; // ts cursor for the log tab's next older page
let activityLoadingMore = false;
let activityLogFetched = false; // backfill once per session view, not on every tab switch

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
    sendBtn.textContent = '보내기';
    sendBtn.classList.remove('btw-btn');
    sendBtn.classList.add('queue-btn');
  } else if (isInquiry(val)) {
    sendBtn.textContent = '샛길 질문 ✦';
    sendBtn.classList.remove('queue-btn');
    sendBtn.classList.add('btw-btn');
  } else {
    sendBtn.textContent = '🧭 끼워 넣기 ↵';
    sendBtn.classList.remove('btw-btn', 'queue-btn');
  }
}

let turnTimer = null;
let turnStartedAt = 0;
let lastProgressDetail = '';
let busyHeartbeatTimer = null;

function updateProcBadge(state, detail) {
  const badge = document.getElementById('procBadge');
  const textEl = document.getElementById('procBadgeText');
  if (!badge || !textEl) return;
  badge.className = 'proc-badge ' + state;
  // Status chrome stays persona-neutral. 냥체 is the current 냥피디 voice,
  // not a shell label — persona can change.
  if (state === 'running') {
    textEl.textContent = '작업 중';
    const sec = turnStartedAt ? Math.max(0, Math.floor((Date.now() - turnStartedAt) / 1000)) : 0;
    badge.title = `${sec}초째 작업 중` + (detail ? ` · ${detail}` : '');
  } else if (state === 'dead') {
    textEl.textContent = '프로세스 중단';
    badge.title = textEl.textContent;
  } else if (state === 'disconnected') {
    textEl.textContent = '다시 연결하는 중…';
    badge.title = textEl.textContent;
  } else {
    textEl.textContent = '대기 중';
    badge.title = '에이전트 프로세스 실시간 상태';
  }
}

function startTurnTimer() {
  if (turnTimer) clearInterval(turnTimer);
  turnStartedAt = Date.now();
  updateProcBadge('running', lastProgressDetail);
  updateTurnLive();
  turnTimer = setInterval(() => {
    if (!isBusy) {
      clearInterval(turnTimer);
      turnTimer = null;
      return;
    }
    const sec = Math.max(0, Math.floor((Date.now() - turnStartedAt) / 1000));
    updateProcBadge('running', lastProgressDetail);
    updateTurnLive();
    refreshComposerPlaceholder(sec);
  }, 1000);

  // Background watchdog heartbeat: every 3 seconds, poll session status to detect dead proc or finished turns
  if (busyHeartbeatTimer) clearInterval(busyHeartbeatTimer);
  busyHeartbeatTimer = setInterval(async () => {
    if (!isBusy || !sessionId) {
      clearInterval(busyHeartbeatTimer);
      busyHeartbeatTimer = null;
      return;
    }
    try {
      const res = await fetch(`${BASE_PATH}/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        if (!data) return;
        if (data.alive === false && isBusy) {
          console.warn('[Heartbeat] Detected dead backend process during turn!');
          clearInterval(busyHeartbeatTimer);
          busyHeartbeatTimer = null;
          setBusy(false);
          updateProcBadge('dead');
          setProgress('⚠️ 백엔드 프로세스가 중단되었습니다냥.', true);
          addActivity('오류: 백엔드 프로세스가 예기치 않게 종료되었습니다.', 'error');
        } else if (data.busy === false && isBusy) {
          // Backend finished the turn, but client missed the SSE 'result' event (e.g. background sleep)
          console.info('[Heartbeat] Backend turn completed; resyncing state...');
          await resyncFromServer(sessionId);
          // If still marked busy after resync, force clear
          if (isBusy && !data.busy) {
            setBusy(false);
            stopTurnTimer();
          }
        }
      }
    } catch (_) {}
  }, 3000);
}

function stopTurnTimer() {
  if (turnTimer) {
    clearInterval(turnTimer);
    turnTimer = null;
  }
  if (busyHeartbeatTimer) {
    clearInterval(busyHeartbeatTimer);
    busyHeartbeatTimer = null;
  }
  turnStartedAt = 0;
  lastProgressDetail = '';
  updateProcBadge('idle');
  if (progressEl) {
    progressEl.hidden = true;
    progressEl.textContent = "";
  }
}

function parkStopBtn() {
  const host = document.getElementById('turnChromeHost');
  if (stopBtn && host && stopBtn.parentElement !== host) {
    host.appendChild(stopBtn);
  }
  if (stopBtn) stopBtn.style.display = 'none';
}

function ensureTurnFooter(node) {
  if (!node) return null;
  let footer = node.querySelector('.msg-footer');
  if (!footer) {
    footer = document.createElement('div');
    footer.className = 'msg-footer';
    node.appendChild(footer);
  }
  let live = footer.querySelector('.turn-live');
  if (!live) {
    live = document.createElement('span');
    live.className = 'turn-live';
    live.innerHTML = '<span class="dot"></span><span class="turn-live-text"></span>';
    footer.prepend(live);
  }
  return footer;
}

function placeStopBtn() {
  if (!stopBtn) return;
  if (!isBusy) {
    parkStopBtn();
    return;
  }
  stopBtn.style.display = 'inline-flex';
  const onChat = currentTab === 'chat' && assistantNode && assistantNode.isConnected;
  if (onChat) {
    const footer = ensureTurnFooter(assistantNode);
    if (footer && stopBtn.parentElement !== footer) footer.appendChild(stopBtn);
  } else {
    const meta = document.getElementById('meta');
    if (meta && stopBtn.parentElement !== meta) meta.appendChild(stopBtn);
  }
}

function updateTurnLive() {
  if (!isBusy) return;
  if (!assistantNode || !assistantNode.isConnected) {
    placeStopBtn();
    return;
  }
  const footer = ensureTurnFooter(assistantNode);
  const live = footer && footer.querySelector('.turn-live');
  const textEl = live && live.querySelector('.turn-live-text');
  if (textEl) {
    const sec = turnStartedAt ? Math.max(0, Math.floor((Date.now() - turnStartedAt) / 1000)) : 0;
    let label = sec + '초째';
    if (lastProgressDetail) label += ' · ' + lastProgressDetail;
    else label += ' 작업 중';
    textEl.textContent = label;
    live.title = label;
  }
  placeStopBtn();
}

function clearTurnLive(node) {
  if (!node) return;
  node.querySelectorAll('.turn-live').forEach(el => el.remove());
  if (stopBtn && node.contains(stopBtn)) parkStopBtn();
}

// The composer placeholder always leads with the model in use (실장님: 모델 select를 짧은 버튼으로 줄이는
// 대신 현재 모델은 placeholder로 명확히). The text itself is composerPlaceholder() in model-picker.js.
function refreshComposerPlaceholder(busySec) {
  if (!inputEl || typeof composerPlaceholder !== 'function') return;
  let sec = null;
  if (typeof busySec === 'number') sec = busySec;
  else if (isBusy && turnStartedAt) sec = Math.max(0, Math.floor((Date.now() - turnStartedAt) / 1000));
  inputEl.placeholder = composerPlaceholder(modelEl ? modelEl.value : '', { compact: window.innerWidth <= 600, busySec: sec });
}

function setBusy(b) {
  isBusy = Boolean(b);
  if (isBusy) {
    if (!turnTimer) startTurnTimer();
    updateTurnLive();
  } else {
    stopTurnTimer();
    clearTurnLive(assistantNode);
    parkStopBtn();
    refreshComposerPlaceholder();
  }
  updateSendButton();
  syncSessionActions();
}

function setProgress(msg, asHost) {
  const label = msg ? String(msg) : "";
  lastProgressDetail = label.replace(/^작업 중 · /, '').replace(/^처리 중…/, '');
  if (isBusy) {
    updateProcBadge('running', lastProgressDetail);
  }
  const useBubble = isBusy && !asHost;
  if (progressEl) {
    if (useBubble || !label) {
      progressEl.hidden = true;
      progressEl.textContent = "";
    } else {
      progressEl.hidden = false;
      progressEl.innerHTML = getActionSvg('zap') + ' <span>' + escapeHtml(label) + '</span>';
    }
  }
  if (useBubble) {
    if (!assistantNode) {
      assistantNode = addChat("assistant", "", false);
      assistantBuf = "";
      assistantNode.dataset.progress = "1";
      assistantNode.dataset.live = "1";
    }
    updateTurnLive();
  }
}

function shortToolLine(text) {
  let s = String(text || '').replace(/\s+/g, ' ').trim();
  if (!s) return '';
  if (s.length > 90) s = s.slice(0, 87) + '...';
  return s;
}

function setMeta(t) {
  const txt = document.getElementById('metaSessionText');
  if (txt) {
    txt.textContent = t;
  } else if (metaEl) {
    metaEl.textContent = t;
  }
}

function absArtifact(u) {
  if (!u) return '';
  if (u.startsWith('http')) return u;
  const trimmed = String(u).replace(/^\.\//, '');
  const grokRel = trimmed.match(/^(?:images|videos)\/([^/?#]+)$/i);
  if (grokRel && sessionId) {
    return BASE_PATH + '/artifacts/' + encodeURIComponent(sessionId) + '/brain/' + encodeURIComponent(grokRel[1]);
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
// (실장님: 샛길 카드가 두 장 / 내 말·답이 두 번 -- a late SSE event redrew what a resync
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
  const bare = logEl.querySelectorAll('.msg.user:not([data-ts])');
  for (let i = 0; i < bare.length; i++) {
    if ((bare[i].textContent || '') === (text || '')) {
      bare[i].dataset.ts = String(ts);
      bare[i].dataset.syncRole = bare[i].classList.contains('btw-user') ? 'btw-user' : 'user';
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
      // (실장님 2026-09-18, right after a reload auto-backfilled scrollback).
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
// ahead of its own question whenever the answer beat the next 2.5s tick (실장님: "첫 질문은
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
  div.dataset.syncRole = 'btw';
  if (ts) div.dataset.ts = String(ts);
  const head = document.createElement('div');
  head.className = 'btw-head';
  head.innerHTML = '<span>✦ 샛길 응답 (/btw)</span>' + (query ? '<span class="btw-q">Q. ' + escapeHtml(query) + '</span>' : '');
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

function addChat(role, text, isFinal, isQueued, isBtw, prepend, usage, durationSeconds, isSystem, ts, servedModel) {
  const div = document.createElement('div');
  div.className = 'msg ' + role + (isSystem ? ' system' : '');
  if (isQueued) div.classList.add('queued');
  if (isBtw) div.classList.add('btw-user');
  div.dataset.syncRole = isBtw ? 'btw-user' : (role || '');
  if (ts) div.dataset.ts = String(ts);
  if (servedModel) div.dataset.servedModel = String(servedModel);
  if (role === 'assistant') {
    const md = document.createElement('div');
    md.className = 'md';
    md.innerHTML = renderMarkdown(text || '', isFinal);
    div.appendChild(md);
    postProcessAssistant(div, isFinal, text, usage, durationSeconds, isSystem, servedModel);
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

function setAssistantContent(node, text, isFinal, usage, durationSeconds, servedModel) {
  if (!node) return;
  if (servedModel) node.dataset.servedModel = String(servedModel);
  const md = node.querySelector('.md') || node;
  md.innerHTML = renderMarkdown(text || '', isFinal);
  postProcessAssistant(node, isFinal, text, usage, durationSeconds, undefined, servedModel);
  syncChoiceChips();
  scrollChatToBottom(false);
}

let activityEvents = []; // [{ id, line, kind, ts, detail }]
let activityFilter = 'all';
let activitySearchQuery = '';

function matchesActivityFilter(item) {
  if (activityFilter === 'tool') {
    if (item.kind !== 'tool' && item.kind !== 'result') return false;
  } else if (activityFilter === 'system') {
    if (item.kind !== 'system') return false;
  } else if (activityFilter === 'warn_error') {
    if (item.kind !== 'warn' && item.kind !== 'error') return false;
  } else if (activityFilter === 'token') {
    if (item.kind !== 'token') return false;
  }
  if (activitySearchQuery) {
    const q = activitySearchQuery.toLowerCase();
    const l = (item.line || '').toLowerCase();
    const d = (item.detail || '').toLowerCase();
    if (!l.includes(q) && !d.includes(q)) return false;
  }
  return true;
}

function renderActivityRow(item) {
  const row = document.createElement('div');
  const hasDetail = Boolean(item.detail && item.detail.trim());
  row.className = 'act-row' + (item.kind ? ' act-' + item.kind : '') + (hasDetail ? ' has-detail' : '');
  if (item.ts) row.dataset.ts = String(item.ts);
  row.dataset.id = item.id;

  const head = document.createElement('div');
  head.className = 'act-row-head';

  const tsSpan = document.createElement('span');
  tsSpan.className = 'act-ts';
  const d = item.ts ? new Date(item.ts * 1000) : new Date();
  tsSpan.textContent = '[' + d.toLocaleTimeString('ko-KR', { hour12: false }) + ']';

  const textSpan = document.createElement('span');
  textSpan.className = 'act-text';
  textSpan.textContent = item.line;

  head.appendChild(tsSpan);
  head.appendChild(textSpan);

  if (hasDetail) {
    const toggleSpan = document.createElement('span');
    toggleSpan.className = 'act-expand-toggle';
    toggleSpan.textContent = '▸ 상세';
    head.appendChild(toggleSpan);

    const detailBox = document.createElement('pre');
    detailBox.className = 'act-detail-box';
    detailBox.textContent = item.detail;
    detailBox.style.display = 'none';

    row.appendChild(head);
    row.appendChild(detailBox);

    row.addEventListener('click', (e) => {
      // Don't toggle if user is selecting text in detail box
      if (window.getSelection() && window.getSelection().toString().length > 0 && e.target === detailBox) {
        return;
      }
      const isOpen = detailBox.style.display !== 'none';
      detailBox.style.display = isOpen ? 'none' : 'block';
      toggleSpan.textContent = isOpen ? '▸ 상세' : '▾ 접기';
    });
  } else {
    row.appendChild(head);
  }

  return row;
}

function renderAllActivity() {
  if (!activityEl) return;
  const prevScroll = activityEl.scrollHeight - activityEl.scrollTop;
  activityEl.innerHTML = '';
  const filtered = activityEvents.filter(matchesActivityFilter);
  if (!filtered.length) {
    const empty = document.createElement('div');
    empty.className = 'act-row';
    empty.style.color = 'var(--muted)';
    empty.style.padding = '1rem 0';
    empty.textContent = activitySearchQuery ? '검색 결과가 없습니다냥.' : '기록된 활동 로그가 없습니다냥.';
    activityEl.appendChild(empty);
    return;
  }
  const frag = document.createDocumentFragment();
  filtered.forEach(item => {
    frag.appendChild(renderActivityRow(item));
  });
  activityEl.appendChild(frag);
  activityEl.scrollTop = activityEl.scrollHeight - prevScroll;
}

let _actIdCounter = 1;
function addActivity(line, kind, ts, detail) {
  if (!line) return;
  const item = {
    id: 'act_' + (_actIdCounter++),
    line,
    kind,
    ts: ts || Date.now() / 1000,
    detail: detail || ''
  };
  activityEvents.push(item);
  if (activityEvents.length > 1000) {
    activityEvents.shift();
  }
  if (!activityEl) return;
  if (matchesActivityFilter(item)) {
    const atBottom = (activityEl.scrollHeight - activityEl.scrollTop - activityEl.clientHeight) < 40;
    activityEl.appendChild(renderActivityRow(item));
    if (atBottom || currentTab !== 'activity') {
      activityEl.scrollTop = activityEl.scrollHeight;
    }
  }
}

function prependActivity(line, kind, ts, detail) {
  if (!line) return;
  const item = {
    id: 'act_' + (_actIdCounter++),
    line,
    kind,
    ts: ts || Date.now() / 1000,
    detail: detail || ''
  };
  activityEvents.unshift(item);
  if (activityEvents.length > 1000) {
    activityEvents.pop();
  }
  if (!activityEl) return;
  if (matchesActivityFilter(item)) {
    activityEl.insertBefore(renderActivityRow(item), activityEl.firstChild);
  }
}

// Persisted events (server.py PERSISTED_LOG_KINDS) rendered for the log
// tab's own history -- mirrors bindEvents()'s live 'tool'/'system'/'error'
// formatting so a backfilled row reads the same as it did live. 'result' and
// 'user_ack' are skipped here -- those are already visible as chat bubbles,
// not activity-log lines.
function formatPersistedLogEvent(ev) {
  const type = ev.event;
  const text = ev.text || '';
  const detail = ev.detail || '';
  if (type === 'tool' || type === 'system' || type === 'stderr' || type === 'error') {
    const line = (type === 'error' ? '오류: ' : '') + (text || JSON.stringify(ev.error || ev));
    const s = String(text || '').trim().toLowerCase();
    if (type === 'tool' && (!s || s === 'tool' || s === 'tool: tool' || s === 'tool:tool')) return null;
    const kind = ev.kind || (type === 'tool' ? (line.startsWith('↳') ? 'result' : 'tool') : (type === 'stderr' ? 'warn' : type));
    return { line, kind, detail };
  }
  if (type === 'queued') return { line: '대기열 등록 (대기: ' + (ev.queue_len || 1) + '건)', kind: 'system', detail };
  if (type === 'steer_queued') return { line: '🧭 새 지시 접수 (반영 대기: ' + (ev.queue_len || 1) + '건)', kind: 'system', detail };
  if (type === 'stopped') return { line: '작업 중지: ' + text, kind: 'system', detail };
  if (type === 'session_rotate') return { line: '세션 자동 전환: ' + text, kind: 'system', detail };
  if (type === 'session_heavy') return { line: '세션 길이 경고(' + (ev.level || 'soft') + '): ' + text, kind: 'warn', detail };
  if (type === 'btw_start') return { line: '샛길 질문(/btw) 처리 중: ' + shortToolLine(ev.query || ''), kind: 'tool', detail };
  if (type === 'btw') return { line: '샛길 질문(/btw) 응답 완료', kind: 'result', detail };
  if (type === 'image') return { line: '이미지 생성: ' + (ev.name || ev.url || ''), kind: 'result', detail };
  return null;
}

async function fetchLog() {
  if (!sessionId || activityLogFetched) return;
  activityLogFetched = true;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/log');
    activityNextBefore = res.next_before || null;
    (res.events || []).slice().reverse().forEach(ev => {
      const f = formatPersistedLogEvent(ev);
      if (f) addActivity(f.line, f.kind, ev.ts, f.detail);
    });
  } catch (e) {
    // 로그 히스토리는 부가 기능 -- 조회 실패해도 조용히 넘어감
  }
}

// 아티팩트 탭과 같은 커서 페이지네이션이지만, 로그 탭은 대화 탭처럼 위로
// 스크롤할 때 옛 기록을 불러온다 (실장님 2026-09-18: "위로 스크롤해서
// 로딩해가며 보여주는 것처럼 아티팩트와 로그도").
async function loadMoreLog() {
  if (!sessionId || activityLoadingMore || !activityNextBefore) return;
  activityLoadingMore = true;
  const prevScrollHeight = activityEl.scrollHeight;
  const prevScrollTop = activityEl.scrollTop;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/log?before=' + encodeURIComponent(activityNextBefore));
    activityNextBefore = res.next_before || null;
    (res.events || []).forEach(ev => {
      const f = formatPersistedLogEvent(ev);
      if (f) prependActivity(f.line, f.kind, ev.ts, f.detail);
    });
    activityEl.scrollTop = prevScrollTop + (activityEl.scrollHeight - prevScrollHeight);
  } catch (e) {
    // silent -- same rationale as fetchLog
  } finally {
    activityLoadingMore = false;
  }
}

if (activityEl) {
  activityEl.addEventListener('scroll', () => {
    if (currentTab !== 'activity') return;
    if (activityEl.scrollTop < 120 && activityEl.scrollHeight > activityEl.clientHeight + 20) {
      loadMoreLog();
    }
  });
}

// Activity toolbar event handlers
document.querySelectorAll('.act-filter-btn[data-filter]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.act-filter-btn[data-filter]').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    activityFilter = btn.getAttribute('data-filter') || 'all';
    renderAllActivity();
  });
});

if (actSearchInput) {
  actSearchInput.addEventListener('input', () => {
    activitySearchQuery = actSearchInput.value.trim();
    renderAllActivity();
  });
}

if (actCopyBtn) {
  actCopyBtn.addEventListener('click', async () => {
    const filtered = activityEvents.filter(matchesActivityFilter);
    if (!filtered.length) {
      alertModal('복사할 활동 로그가 없습니다.');
      return;
    }
    const textToCopy = filtered.map(item => {
      const d = item.ts ? new Date(item.ts * 1000) : new Date();
      const timeStr = '[' + d.toLocaleTimeString('ko-KR', { hour12: false }) + ']';
      let out = timeStr + ' ' + item.line;
      if (item.detail) {
        out += '\n  ' + item.detail.split('\n').join('\n  ');
      }
      return out;
    }).join('\n');

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(textToCopy);
      } else {
        const ta = document.createElement('textarea');
        ta.value = textToCopy;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      const prevText = actCopyBtn.textContent;
      actCopyBtn.textContent = '복사됨 ✓';
      setTimeout(() => { actCopyBtn.textContent = prevText; }, 1800);
    } catch (e) {
      alertModal('클립보드 복사 실패: ' + e.message);
    }
  });
}

if (actRefreshBtn) {
  actRefreshBtn.addEventListener('click', () => {
    activityEvents = [];
    activityLogFetched = false;
    activityNextBefore = null;
    if (activityEl) activityEl.innerHTML = '';
    fetchLog();
  });
}

let sessionTokenTotal = 0;
// Fresh (non-cache) input tokens per turn this session, for relative spike detection.
const turnFreshTokenHistory = [];
// Absolute floor: 2026-09-16 measured baseline is ~14-16K fresh input tokens for a
// trivial first turn (see docs/DEVLOG.md — the ADD_DIRS parent-vs-children bug pushed
// this to ~45K). Anything past this on its own is worth a look regardless of history.
const OCCUPANCY_WARN_ABS = 150000;

function logTurnUsage(usage, durationSeconds) {
  usage = usage || {};
  const total = usage.total_tokens || 0;
  const input = usage.input_tokens || 0;
  const cacheRead = usage.cache_read_tokens || 0;
  if (total) sessionTokenTotal += total;
  if (total || input) updateSessionTokens(usage);

  let warnReason = '';
  if (input >= OCCUPANCY_WARN_ABS) {
    warnReason = '창 점유 ' + input.toLocaleString('ko-KR') + ' (soft 임계)';
  } else if (turnFreshTokenHistory.length >= 2) {
    const avg = turnFreshTokenHistory.reduce((a, b) => a + b, 0) / turnFreshTokenHistory.length;
    if (avg > 0 && input > avg * 2.5) {
      warnReason = '이 세션 평소 창(' + Math.round(avg).toLocaleString('ko-KR') + ')의 2.5배';
    }
  }
  if (input > 0) turnFreshTokenHistory.push(input);

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
    if (!cmd) return ''; // args not populated yet (streaming) - skip, don't show a bare "run_command:"
    let out = 'run_command: ' + cmd;
    if (summary && summary.toLowerCase() !== cmd.toLowerCase()) out += ' (' + summary + ')';
    else if (action && action.toLowerCase() !== cmd.toLowerCase()) out += ' (' + action + ')';
    return out;
  }
  if (name === 'view_file' || name === 'read_file') {
    const p = clean(args.AbsolutePath || args.TargetFile || args.path || args.file);
    if (!p) return '';
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
    if (!q) return '';
    const sp = clean(args.SearchPath || args.path);
    let out = `grep_search: '${q}' in ${sp || '.'}`;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'find_by_name') {
    const p = clean(args.Pattern || args.pattern);
    if (!p) return '';
    const sd = clean(args.SearchDirectory || args.directory || args.path);
    let out = `find_by_name: '${p}' in ${sd || '.'}`;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'list_dir') {
    const dp = clean(args.DirectoryPath || args.path || args.dir);
    if (!dp) return '';
    let out = 'list_dir: ' + dp;
    if (summary) out += ' (' + summary + ')';
    return out;
  }
  if (name === 'replace_file_content' || name === 'edit_file') {
    const tf = clean(args.TargetFile || args.path || args.file);
    if (!tf) return '';
    const inst = clean(args.Instruction || summary || action);
    let out = 'replace_file_content: ' + tf;
    if (inst) out += ' (' + inst + ')';
    return out;
  }
  if (name === 'write_to_file' || name === 'write_file') {
    const tf = clean(args.TargetFile || args.path || args.file);
    if (!tf) return '';
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
  const url = (BASE_PATH && path.startsWith('/') && !path.startsWith(BASE_PATH)) ? (BASE_PATH + path) : path;
  const r = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
  if (!r.ok) throw new Error(await r.text() || r.statusText);
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return r.json();
  return r.text();
}

async function maybeRedirectHardSession(id, info, depth) {
  depth = depth || 0;
  if (depth > 3) return null;
  const hard = Boolean(info && info.weight && info.weight.level === 'hard');
  if (!hard) return null;
  const redir = (info && (info.redirect_session_id || info.successor_session_id)) || '';
  if (redir && redir !== id) {
    rememberSession(redir);
    addActivity('hard 세션 → successor로 이동: ' + redir);
    await openSession(redir, depth + 1, {
      level: 'hard',
      message_ko: '열려던 대화가 너무 길어져서 자동으로 이어진 세션이에요냥 — 예전 대화 내용은 그대로 보존됩니다.',
    });
    return redir;
  }
  if (hard && !redir) {
    // Auto-redirect on open must land every window/tab on the SAME
    // successor -- a plain createSession() here (old behavior) never links
    // back to `id`, so each window that loaded this hard session before any
    // of them finished would mint its own disconnected new chat (실장님:
    // "창을 여러 개 열었더니 각자 다른 새 세션이 시작되고 예전 세션 내용이
    // 안 나옴"). sticky:true asks the server to reuse an already-usable
    // successor instead of forking again -- safe even if two windows race,
    // since the server resolves it under that session's own lock.
    try {
      const res = await api('/api/sessions/' + encodeURIComponent(id) + '/continue', {
        method: 'POST',
        body: JSON.stringify({ model: modelEl.value, sticky: true })
      });
      if (res && res.ok && res.session && res.session.id) {
        const nid = res.session.id;
        rememberSession(nid);
        addActivity('hard 세션 → 자동 이어하기 successor로 이동: ' + nid + (res.reused ? ' (기존 재사용)' : ' (신규)'));
        await openSession(nid, depth + 1, {
          level: 'hard',
          message_ko: '열려던 대화가 너무 길어져서 자동으로 이어진 세션이에요냥 — 예전 대화 내용은 그대로 보존됩니다.',
        });
        return nid;
      }
    } catch (e) {
      addActivity('자동 이어하기 실패, 새 세션으로 대체: ' + (e.message || e));
    }
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
  if (tabChat) { tabChat.classList.toggle('on', tab === 'chat'); tabChat.setAttribute('aria-selected', String(tab === 'chat')); }
  if (tabArtifacts) { tabArtifacts.classList.toggle('on', tab === 'artifacts'); tabArtifacts.setAttribute('aria-selected', String(tab === 'artifacts')); }
  if (tabActivity) { tabActivity.classList.toggle('on', tab === 'activity'); tabActivity.setAttribute('aria-selected', String(tab === 'activity')); }
  if (tabStatus) { tabStatus.classList.toggle('on', tab === 'status'); tabStatus.setAttribute('aria-selected', String(tab === 'status')); }
  if (tabSessions) { tabSessions.classList.toggle('on', tab === 'sessions'); tabSessions.setAttribute('aria-selected', String(tab === 'sessions')); }

  if (logEl) logEl.style.display = (tab === 'chat') ? 'flex' : 'none';
  const artifactsPane = document.getElementById('artifacts');
  if (artifactsPane) artifactsPane.style.display = (tab === 'artifacts') ? 'flex' : 'none';
  if (activityPaneEl) activityPaneEl.style.display = (tab === 'activity') ? 'flex' : 'none';
  else if (activityEl) activityEl.style.display = (tab === 'activity') ? 'block' : 'none';
  if (statusPaneEl) statusPaneEl.style.display = (tab === 'status') ? 'flex' : 'none';
  if (sessionsPaneEl) sessionsPaneEl.style.display = (tab === 'sessions') ? 'flex' : 'none';

  if (tab === 'artifacts') {
    fetchArtifacts(true);
  } else if (tab === 'chat' && logEl) {
    scrollChatToBottom(false);
  } else if (tab === 'activity' && activityEl) {
    activityEl.scrollTop = activityEl.scrollHeight;
  } else if (tab === 'status') {
    fetchSelfStatus();
    renderStatusPicker();
    fetchAccounts();
    fetchUsage(false);
  } else if (tab === 'sessions') {
    fetchSessionsList();
  }
  updateScrollBottomButton();
  placeStopBtn();
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---- observation manager (status tab) ----
// Everything below puts text into nodes with textContent only: observation and candidate text is written by
// agents, so it is data, never markup.
const OBS_STATUS_LABEL = { open: '열림', parked: '보류', actioned: '완료', declined: '기각', superseded: '대체됨' };

function obsNode(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

function obsSet(box, kids) {
  box.textContent = '';
  kids.forEach(k => box.appendChild(k));
}

function obsErrorText(e) {
  try { const j = JSON.parse(e.message); if (j && j.error) return j.error; } catch (_) { /* not JSON */ }
  return String((e && e.message) || e).slice(0, 200);
}

async function loadObservations() {
  if (!statusObsBoxEl) return;
  let res;
  try {
    res = await api('/api/observations');
  } catch (e) {
    obsSet(statusObsBoxEl, [obsNode('div', 'status-hint', '관찰 관리를 아직 쓸 수 없어요 (호스트를 소생하면 열려요): ' + obsErrorText(e))]);
    return;
  }
  renderObservations(res);
}

function renderObservations(res) {
  const items = res.observations || [];
  const active = items.filter(o => o.status === 'open' || o.status === 'parked');
  const closed = items.filter(o => o.status !== 'open' && o.status !== 'parked');
  const kids = [];
  if (!active.length) kids.push(obsNode('div', 'status-hint', '열린 관찰이 없어요.'));
  active.forEach(o => kids.push(renderObservationRow(o)));
  if (closed.length) {
    kids.push(obsNode('div', 'status-hint', '오늘 처리됨: ' + closed.map(o => '#' + o.id + ' ' + o.title + ' (' + (OBS_STATUS_LABEL[o.status] || o.status) + ')').join(' · ')));
  }
  kids.push(renderCandidates(res));
  kids.push(renderReviewControls(res));
  obsSet(statusObsBoxEl, kids);
}

function renderObservationRow(o) {
  const row = obsNode('div', 'obs-row');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + o.id));
  head.appendChild(obsNode('span', 'obs-title', o.title || '(제목 없음)'));
  head.appendChild(obsNode('span', 'obs-badge ' + o.status, OBS_STATUS_LABEL[o.status] || o.status));
  row.appendChild(head);
  row.appendChild(obsNode('div', 'obs-meta', [o.area, o.date, o.status === 'parked' && o.parked_until ? '보류 ~ ' + o.parked_until : ''].filter(Boolean).join(' · ')));
  const actions = obsNode('div', 'obs-actions');
  const viewBtn = obsNode('button', 'art-btn', '보기');
  const doBtn = obsNode('button', 'art-btn primary', '처리');
  viewBtn.type = 'button';
  doBtn.type = 'button';
  actions.appendChild(viewBtn);
  actions.appendChild(doBtn);
  row.appendChild(actions);
  const detail = obsNode('pre', 'obs-body');
  detail.hidden = true;
  row.appendChild(detail);
  const formHost = obsNode('div', 'obs-formhost');
  row.appendChild(formHost);
  viewBtn.addEventListener('click', async () => {
    if (!detail.hidden) { detail.hidden = true; return; }
    if (!detail.textContent) {
      detail.textContent = '불러오는 중…';
      try {
        const d = await api('/api/observations/' + o.id);
        detail.textContent = (d.observation && d.observation.body) || '(본문 없음)';
      } catch (e) {
        detail.textContent = '불러오기 실패: ' + obsErrorText(e);
      }
    }
    detail.hidden = false;
  });
  doBtn.addEventListener('click', () => {
    if (formHost.children.length) { formHost.textContent = ''; return; }
    formHost.appendChild(renderResolveForm(o, formHost));
  });
  return row;
}

function renderResolveForm(o, host) {
  const form = obsNode('div', 'obs-form');
  const sel = obsNode('select');
  [['actioned', '완료 (고쳤어요)'], ['declined', '기각 (안 고쳐요)'], ['superseded', '대체됨 (다른 것으로 해결)'], ['parked', '보류 (나중에)']].forEach(pair => {
    const op = obsNode('option', null, pair[1]);
    op.value = pair[0];
    sel.appendChild(op);
  });
  const reason = obsNode('input');
  reason.type = 'text';
  reason.placeholder = '사유 한 줄 (필수)';
  reason.maxLength = 300;
  const until = obsNode('input');
  until.type = 'date';
  until.value = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  until.hidden = true;
  sel.addEventListener('change', () => { until.hidden = sel.value !== 'parked'; });
  const btns = obsNode('div', 'obs-actions');
  const save = obsNode('button', 'art-btn primary', '저장');
  const cancel = obsNode('button', 'art-btn', '취소');
  save.type = 'button';
  cancel.type = 'button';
  cancel.addEventListener('click', () => { host.textContent = ''; });
  save.addEventListener('click', async () => {
    const why = reason.value.trim();
    if (!why) { if (reason.focus) reason.focus(); return; }
    save.disabled = true;
    save.textContent = '저장 중…';
    try {
      const body = { status: sel.value, resolution: why };
      if (sel.value === 'parked') body.until = until.value;
      await api('/api/observations/' + o.id + '/resolve', { method: 'POST', body: JSON.stringify(body) });
      addActivity('관찰 #' + o.id + ' → ' + (OBS_STATUS_LABEL[sel.value] || sel.value));
      fetchSelfStatus();
    } catch (e) {
      save.disabled = false;
      save.textContent = '저장';
      await alertModal('처리 실패: ' + obsErrorText(e));
    }
  });
  btns.appendChild(save);
  btns.appendChild(cancel);
  [sel, reason, until, btns].forEach(n => form.appendChild(n));
  return form;
}

function renderCandidates(res) {
  const wrap = obsNode('div', 'obs-cands');
  const n = res.unreviewed_candidates || 0;
  wrap.appendChild(obsNode('div', 'obs-meta', '미검토 후보 ' + n + '건 — 호스트가 자동으로 모은 힌트예요. 작업 지시가 아니에요.'));
  if (!n) return wrap;
  const list = obsNode('div', 'obs-candlist');
  list.hidden = true;
  (res.candidates || []).forEach(c => {
    list.appendChild(obsNode('div', 'obs-cand', [c.ts, c.signal, c.provider, c.user ? '“' + c.user + '”' : '', c.ref].filter(Boolean).join(' · ')));
  });
  const toggle = obsNode('button', 'art-btn', '후보 보기');
  toggle.type = 'button';
  toggle.addEventListener('click', () => {
    list.hidden = !list.hidden;
    toggle.textContent = list.hidden ? '후보 보기' : '후보 접기';
  });
  wrap.appendChild(toggle);
  wrap.appendChild(list);
  return wrap;
}

function renderReviewControls(res) {
  const wrap = obsNode('div', 'obs-review');
  wrap.appendChild(obsNode('div', 'obs-meta', '마지막 리뷰: ' + (res.last_review || 'never')));
  const btn = obsNode('button', 'art-btn', '리뷰 완료 기록');
  btn.type = 'button';
  const host = obsNode('div', 'obs-formhost');
  btn.addEventListener('click', () => {
    if (host.children.length) { host.textContent = ''; return; }
    const form = obsNode('div', 'obs-form');
    const summary = obsNode('input');
    summary.type = 'text';
    summary.placeholder = '무엇을 검토했고 어떻게 처리했는지 한 줄 (필수)';
    summary.maxLength = 300;
    const go = obsNode('button', 'art-btn primary', '기록');
    go.type = 'button';
    go.addEventListener('click', async () => {
      const text = summary.value.trim();
      if (!text) { if (summary.focus) summary.focus(); return; }
      go.disabled = true;
      try {
        await api('/api/observations/reviewed', { method: 'POST', body: JSON.stringify({ summary: text }) });
        addActivity('관찰 리뷰 기록됨');
        fetchSelfStatus();
      } catch (e) {
        go.disabled = false;
        await alertModal('리뷰 기록 실패: ' + obsErrorText(e));
      }
    });
    form.appendChild(summary);
    form.appendChild(go);
    host.appendChild(form);
  });
  wrap.appendChild(btn);
  wrap.appendChild(host);
  return wrap;
}
// Tickets: the buttons only type the operator's command into the chat box (`/ticket approve 3`); pressing Enter
// runs it in the page (see send()) -- it never goes to the agent, and the agent has no way to decide a ticket.
const TICKET_STATUS_LABEL = { proposed: '제안됨', approved: '승인됨', declined: '폐기됨', wontfix: '보류(사람 필요)', done: '완료' };
const TICKET_DECISIONS = {
  proposed: [['go', '승인+진행'], ['approve', '승인'], ['decline', '폐기']],
  approved: [['go', '진행'], ['decline', '폐기']],
  wontfix: [['reopen', '재개']],
};
const TICKET_DECISION_WORD = { approve: '승인', decline: '폐기', reopen: '재개', go: '진행' };

function ticketDecisionText(t, action) {
  return '/ticket ' + action + ' ' + t.id;
}

function parseTicketCommand(text) {
  const m = /^\/ticket\s+(go|approve|decline|reopen)\s+#?(\d{1,6})$/.exec(String(text || '').trim());
  return m ? { action: m[1], id: Number(m[2]) } : null;
}

// `/ticket go N`: approve it if it still waits for that (the operator's decision), then hand the agent the obvious
// instruction as an ordinary message -- the sentence nobody wants to type. Returns { message, prompt }.
function ticketGoPrompt(t) {
  return '티켓 #' + t.id + ' 진행해줘. ticket 도구로 claim해서 이 티켓의 대상(' + (t.target || '') + ')만 고치고, 끝나면 release로 결과(done/gate_failed/failed)를 기록해. 범위 밖은 건드리지 마.';
}

async function goTicket(cmd) {
  const cur = (await api('/api/tickets/' + cmd.id)).ticket || {};
  let message = '';
  if (cur.status === 'proposed') message = await decideTicket({ action: 'approve', id: cmd.id });
  else if (cur.status !== 'approved') throw new Error(JSON.stringify({ ok: false, error: '티켓 #' + cmd.id + '은(는) ' + (TICKET_STATUS_LABEL[cur.status] || cur.status) + ' 상태라 진행할 수 없어요' }));
  return { message, prompt: ticketGoPrompt(cur) };
}

async function decideTicket(cmd) {
  const res = await api('/api/tickets/' + cmd.id + '/' + cmd.action, { method: 'POST', body: JSON.stringify({}) });
  const t = res.ticket || {};
  return '티켓 #' + cmd.id + ' ' + TICKET_DECISION_WORD[cmd.action] + ' 처리했어요 → ' + (TICKET_STATUS_LABEL[t.status] || t.status || '');
}

async function loadTickets() {
  if (!statusTicketBoxEl && !ticketBarEl) return;
  let res;
  try {
    res = await api('/api/tickets');
  } catch (e) {
    if (statusTicketBoxEl) obsSet(statusTicketBoxEl, [obsNode('div', 'status-hint', '티켓 목록을 아직 볼 수 없어요 (호스트를 소생하면 열려요): ' + obsErrorText(e))]);
    if (ticketBarEl) { ticketBarEl.textContent = ''; ticketBarEl.hidden = true; }
    return;
  }
  renderTickets(res);
}

// The same buttons, where the operator already is: a strip above the composer while a ticket waits for a decision.
const TICKET_BAR_MAX = 3;
function fillTicketCommand(t, action) {
  inputEl.value = ticketDecisionText(t, action);
  switchTab('chat');
  if (inputEl.focus) inputEl.focus();
}

function renderTicketBar(waiting) {
  if (!ticketBarEl) return;
  ticketBarEl.textContent = '';
  ticketBarEl.hidden = !waiting.length;
  waiting.slice(0, TICKET_BAR_MAX).forEach(t => {
    const chip = obsNode('div', 'ticket-chip');
    chip.appendChild(obsNode('span', 'ticket-chip-title', '#' + t.id + ' ' + (t.title || '')));
    TICKET_DECISIONS[t.status].forEach(pair => {
      const btn = obsNode('button', 'art-btn' + (pair[0] === 'go' ? ' primary' : ''), pair[1]);
      btn.type = 'button';
      btn.addEventListener('click', () => fillTicketCommand(t, pair[0]));
      chip.appendChild(btn);
    });
    ticketBarEl.appendChild(chip);
  });
  if (waiting.length > TICKET_BAR_MAX) ticketBarEl.appendChild(obsNode('span', 'obs-meta', '+' + (waiting.length - TICKET_BAR_MAX) + '건 더 (상태 탭)'));
}

function renderTickets(res) {
  const rows = (res.tickets || []).filter(t => TICKET_DECISIONS[t.status]);
  renderTicketBar(rows);
  if (!statusTicketBoxEl) return;
  const kids = [obsNode('div', 'obs-meta', '티켓 — 결정은 운영자만 해요. 버튼은 채팅창에 명령을 넣어 줘요. Enter를 눌러야 실행돼요. 진행은 승인(필요하면)까지 하고 에이전트에게 착수를 요청해요.')];
  if (!rows.length) kids.push(obsNode('div', 'status-hint', '결정을 기다리는 티켓이 없어요.'));
  rows.forEach(t => kids.push(renderTicketRow(t)));
  obsSet(statusTicketBoxEl, kids);
}

function renderTicketRow(t) {
  const row = obsNode('div', 'obs-row');
  const head = obsNode('div', 'obs-head');
  head.appendChild(obsNode('span', 'obs-id', '#' + t.id));
  head.appendChild(obsNode('span', 'obs-title', t.title || '(제목 없음)'));
  head.appendChild(obsNode('span', 'obs-badge ' + t.status, TICKET_STATUS_LABEL[t.status] || t.status));
  row.appendChild(head);
  row.appendChild(obsNode('div', 'obs-meta', [t.target, '시도 ' + (t.attempts || 0) + '회', (t.evidence || []).length + '개 근거'].filter(Boolean).join(' · ')));
  const actions = obsNode('div', 'obs-actions');
  TICKET_DECISIONS[t.status].forEach(pair => {
    const btn = obsNode('button', 'art-btn' + (pair[0] === 'approve' ? ' primary' : ''), pair[1]);
    btn.type = 'button';
    btn.addEventListener('click', () => fillTicketCommand(t, pair[0]));
    actions.appendChild(btn);
  });
  row.appendChild(actions);
  return row;
}
// ---- end observation manager ----

async function fetchSelfStatus() {
  if (!statusPaneEl) return;
  try {
    const res = await api('/api/self-status');
    renderStatusMemory(res.memory || null);
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
      const o = res.observation || {};
      statusObserverEl.textContent = '열린 관찰(open): ' + (o.open_observations || 0) + ' / 전체 ' + (o.total_observations || 0) + '건 · 미검토 후보: ' + (o.unreviewed_candidates || 0) + '건 · 마지막 리뷰: ' + (o.last_review_date || 'never');
    }
    loadObservations();
    loadTickets();
    statusLoaded = true;
  } catch (e) {
    if (statusRulesEl) statusRulesEl.textContent = '상태 로드 실패: ' + e.message;
  }
}

// 상태 탭은 "지금 쓰는 프로바이더" 한 곳만 보여 준다: 계정 → 사용량 → 프로세스.
// 서버가 토큰 파일의 이메일과 각 agy 프로세스가 인증한 계정을 대조해 stale 여부를
// 계산해 준다 -- 여기서는 그리기만 한다.
const ACCT_OWNER_LABEL = { session: '세션', standby: '대기(standby)', 'chatbot-other': '챗봇 임시', external: '외부' };

// 상태 탭이 보여 주는 제공자. 기본은 지금 대화 중인 제공자를 따라가고, 칩으로 다른 제공자를
// "보기만" 할 수 있다 -- selectProvider()를 부르지 않으므로 서버 세션(제공자·conversation_id)은 그대로다.
let statusViewProvider = null;
function chatProvider() { return providerEl ? providerEl.value : 'agy'; }
function currentStatusProvider() { return statusViewProvider || chatProvider(); }

// 상단 브랜드 영역과 같은 표기(agy=Antigravity). 제공자 이름은 벤더이지 페르소나가 아니다.
function statusProviderName(id) {
  const e = Array.isArray(providerCatalog) ? providerCatalog.find(p => p.id === id) : null;
  return providerCreditLabel(e || { id });
}

function renderStatusPicker() {
  if (!statusPickerEl) return;
  statusPickerEl.innerHTML = '';
  const viewing = currentStatusProvider(), chat = chatProvider();
  (Array.isArray(providerCatalog) ? providerCatalog : []).forEach(p => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'art-filter-btn' + (p.id === viewing ? ' on' : '') + (p.id === chat ? ' is-chat' : '');
    b.textContent = providerCreditLabel(p);
    const disReason = providerDisabledReason(p.id);
    b.title = (p.id === chat ? '지금 대화 중인 제공자' : '상태만 봅니다 — 대화의 제공자는 바뀌지 않아요') + (disReason ? ' · ' + disReason : '');
    b.setAttribute('aria-pressed', String(p.id === viewing));
    b.disabled = p.available === false;
    if (disReason) b.classList.add('is-disabled-provider');
    b.addEventListener('click', () => setStatusViewProvider(p.id));
    statusPickerEl.appendChild(b);
  });
}

// 다른 제공자의 상태를 보기만 한다 (대화 세션은 건드리지 않는다).
function setStatusViewProvider(id) {
  statusViewProvider = (id === chatProvider()) ? null : id;
  refreshProviderStatus();
}

// 대화의 제공자가 (코드로) 바뀌면 select의 onchange가 안 돌므로 여기서 직접 다시 그린다. 보기 전용 선택은 대화를 따라간다.
function followChatProvider() {
  statusViewProvider = null;
  refreshProviderStatus();
}

function refreshProviderStatus() {
  if (currentTab !== 'status') return;
  renderStatusPicker();
  fetchAccounts();
  fetchUsage(false);
}

function fmtAge(sec) {
  if (sec == null) return '?';
  if (sec < 90) return sec + '초';
  if (sec < 5400) return Math.round(sec / 60) + '분';
  if (sec < 172800) return (sec / 3600).toFixed(1) + '시간';
  return (sec / 86400).toFixed(1) + '일';
}

async function fetchAccounts() {
  if (!statusAccountsEl) return;
  const provider = currentStatusProvider();
  if (statusProviderTitleEl) statusProviderTitleEl.textContent = statusProviderName(provider) + (statusViewProvider ? ' · 보기 전용' : '');
  statusAccountsEl.innerHTML = '<div class="status-hint">불러오는 중…</div>';
  try {
    const res = await api('/api/accounts?provider=' + encodeURIComponent(provider));
    if (currentStatusProvider() !== provider) return;  // 응답이 늦는 사이 프로바이더가 바뀜
    renderAccounts(res, provider);
  } catch (e) {
    statusAccountsEl.innerHTML = '<div class="status-hint">계정 정보 로드 실패: ' + escapeHtml(e.message) + '</div>';
    if (statusProcsEl) statusProcsEl.hidden = true;
  }
}

function acctProcRow(p, hasEvidence) {
  const item = document.createElement('div');
  item.className = 'status-item' + (p.stale ? ' acct-warn' : '');
  const owner = ACCT_OWNER_LABEL[p.owner] || p.owner;
  let badge;
  if (p.account) {
    badge = '<span class="acct-badge ' + (p.stale ? 'stale' : 'ok') + '">' + escapeHtml(p.account) + (p.stale ? ' · 옛 계정' : '') + '</span>';
  } else if (p.predates_change) {
    badge = '<span class="acct-badge warn">로그인 변경 전에 시작됨</span>';
  } else {
    badge = '<span class="acct-badge">' + (hasEvidence ? '계정 불명(로그 없음)' : '계정 알 수 없음') + '</span>';
  }
  const who = p.sid ? ' ' + escapeHtml(p.sid) : '';
  item.innerHTML =
    '<div class="status-item-head"><span class="status-item-name">pid ' + p.pid + ' · ' + escapeHtml(owner) + who + '</span>' + badge + '</div>' +
    '<div class="status-item-preview">경과 ' + escapeHtml(fmtAge(p.age_sec)) + ' · tty ' + escapeHtml(p.tty) +
    ' · 부모 ' + escapeHtml(p.parent || '?') + '(' + p.ppid + ')' + (p.busy ? ' · 작업 중' : '') + '\n' + escapeHtml(p.cmd) + '</div>';
  if (p.kill_cmd) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'art-filter-btn';
    btn.textContent = '종료 명령 복사: ' + p.kill_cmd;
    btn.addEventListener('click', () => copyText(p.kill_cmd).then(() => { btn.textContent = '복사됨 ✓'; }, () => { btn.textContent = p.kill_cmd; }));
    item.appendChild(btn);
  }
  return item;
}

// 계정: 현재 로그인 + 마지막 계정 변경 + (agy) 자동 재시작 기록
function renderAccounts(res, provider) {
  if (!statusAccountsEl) return;
  statusAccountsEl.innerHTML = '';
  const pv = (res.providers || {})[provider];
  if (!pv) {
    // API 키 방식(omniroute 등): 로그인 계정도 CLI 프로세스도 없다
    statusAccountsEl.innerHTML = '<div class="status-hint">이 프로바이더는 로그인 계정이 없어요 (API 키 방식).</div>';
    if (statusProcsEl) statusProcsEl.hidden = true;
    return;
  }
  const when = s => s ? new Date(s * 1000).toLocaleString('ko-KR') : '?';
  const cur = pv.current || {};
  const box = document.createElement('div');
  box.className = 'status-item';
  if (cur.ok) {
    const exp = cur.expires_at ? ' · 액세스 토큰 만료 ' + when(cur.expires_at) : '';
    const disReason = providerDisabledReason(provider);
    const badge = disReason
      ? ' <span class="acct-badge stale">⚠ 사용 불가 (' + escapeHtml(disReason) + ')</span>'
      : '';
    box.innerHTML =
      '<div class="status-item-meta">로그인 계정' + (cur.plan ? ' · ' + escapeHtml(cur.plan) : '') + badge + '</div>' +
      '<div class="acct-current">' + escapeHtml(cur.email) + '</div>' +
      '<div class="status-item-preview">' + escapeHtml(cur.source || '') +
      (cur.file_mtime ? '\n파일 갱신 ' + escapeHtml(when(cur.file_mtime)) : '') + escapeHtml(exp) + '</div>';
  } else {
    box.innerHTML = '<div class="status-item-meta">로그인 계정</div><div class="acct-current">' +
      escapeHtml(cur.error || '알 수 없음') + '</div>';
  }
  if (pv.changed_from && pv.changed_at && (Date.now() / 1000 - pv.changed_at) < 7 * 86400) {
    const chg = document.createElement('div');
    chg.className = 'status-item-preview';
    chg.textContent = '계정 변경 관측: ' + pv.changed_from + ' → ' + (cur.email || '?') + ' (' + when(pv.changed_at) + ')';
    box.appendChild(chg);
  }
  statusAccountsEl.appendChild(box);

  const auto = res.auto_recycle || {};
  if (provider === 'agy' && auto.total > 0 && auto.last_at) {
    const note = document.createElement('div');
    note.className = 'status-hint';
    note.textContent = '자동 재시작: 마지막 ' + new Date(auto.last_at * 1000).toLocaleTimeString('ko-KR') + '에 유휴 agy ' +
      auto.last_count + '개 (계정 변경 감지) · 누적 ' + auto.total + '개' + (auto.enabled === false ? ' · 현재 꺼짐' : '');
    statusAccountsEl.appendChild(note);
  }
  renderProcs(pv);
}

// 프로세스: 목록이 길어 사용량을 밀어내지 않도록 접이식. 옛 계정 경고가 있으면 자동으로 펼친다.
function renderProcs(pv) {
  if (!statusProcsEl || !statusProcListEl) return;
  const procs = pv.processes || [];
  const hasEvidence = pv.account_evidence === 'log';
  const stale = pv.stale_count || 0;
  const predates = pv.predates_count || 0;
  statusProcsEl.hidden = false;
  if (statusProcsSummaryEl) {
    statusProcsSummaryEl.innerHTML = '프로세스 ' + procs.length + '개' +
      (stale ? ' <span class="acct-badge stale">⚠ 옛 계정 ' + stale + '개</span>' : '') +
      (predates ? ' <span class="acct-badge warn">로그인 변경 전 시작 ' + predates + '개</span>' : '');
  }
  if (stale) statusProcsEl.open = true;  // 경고는 접어 두지 않는다
  statusProcListEl.innerHTML = '';

  if (stale > 0) {
    const ownedStale = procs.filter(p => p.stale && (p.owner === 'session' || p.owner === 'standby')).length;
    const warn = document.createElement('div');
    warn.className = 'status-item acct-warn';
    warn.innerHTML =
      '<div class="status-item-name">⚠ 옛 계정으로 인증된 agy 프로세스 ' + stale + '개</div>' +
      '<div class="status-item-preview">이 프로세스가 토큰을 refresh하면 방금 한 로그인이 옛 계정으로 되돌아갈 수 있어요. ' +
      '외부 프로세스는 종료 명령을 복사해서 직접 실행하세요.</div>';
    if (ownedStale) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'art-filter-btn';
      btn.textContent = '챗봇 소유 ' + ownedStale + '개 재시작 (유휴 세션·대기만)';
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const r = await api('/api/accounts/recycle', { method: 'POST', body: JSON.stringify({}) });
          if (r.skipped_busy && r.skipped_busy.length) alert('작업 중인 세션 ' + r.skipped_busy.length + '개는 건너뛰었어요. 끝난 뒤 다시 눌러 주세요.');
        } catch (e) { alert('재시작 실패: ' + e.message); }
        fetchAccounts();
      });
      warn.appendChild(btn);
    }
    statusProcListEl.appendChild(warn);
  }
  if (predates > 0 && pv.changed_at) {
    const note = document.createElement('div');
    note.className = 'status-hint';
    note.textContent = '계정 변경(' + new Date(pv.changed_at * 1000).toLocaleString('ko-KR') + ' 관측) 이전에 시작된 프로세스 ' + predates +
      '개 — 이 CLI는 프로세스별 계정을 알 수 없어, 옛 자격을 들고 있는지는 시간 기준으로만 표시해요.';
    statusProcListEl.appendChild(note);
  }
  if (!procs.length) {
    const none = document.createElement('div');
    none.className = 'status-hint';
    none.textContent = '실행 중인 프로세스 없음';
    statusProcListEl.appendChild(none);
  }
  procs.forEach(p => statusProcListEl.appendChild(acctProcRow(p, hasEvidence)));
}

async function fetchUsage(force) {
  if (!statusUsageEl) return;
  const provider = currentStatusProvider();
  statusUsageEl.innerHTML = '<div class="status-hint">불러오는 중… (' + escapeHtml(provider) + ' CLI 실제 호출이라 몇 초 걸릴 수 있어요)</div>';
  try {
    const params = new URLSearchParams({provider});
    if (force) params.set('force', '1');
    const res = await api('/api/usage?' + params.toString());
    if (currentStatusProvider() !== provider) return;  // 응답이 늦는 사이 보는 제공자가 바뀜
    renderStatusUsage(res);
  } catch (e) {
    statusUsageEl.innerHTML = '<div class="status-hint">사용량 로드 실패: ' + escapeHtml(e.message) + '</div>';
  }
}

function renderStatusUsage(res) {
  if (!statusUsageEl) return;
  if (!res || !res.ok) {
    // supported:false (Multi-Provider plan Phase 0.5) -- this provider has no
    // one-shot rate-limit report at all (codex as of this writing), not an
    // error worth alarming over.
    const msg = (res && res.supported === false)
      ? (res.error || '이 프로바이더는 사용량 조회를 지원하지 않습니다')
      : '조회 실패: ' + ((res && res.error) || '알 수 없는 오류');
    statusUsageEl.innerHTML = '<div class="status-hint">' + escapeHtml(msg) + '</div>';
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
    try {
      const d = new Date(row.reset_at);
      if (!isNaN(d.getTime())) resetStr = d.toLocaleString('ko-KR');
    } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="status-item-name">' + escapeHtml(row.group) + ' — ' + escapeHtml(row.limit_type) + '</span>' +
      '<span class="status-item-meta">' + escapeHtml(row.remaining_pct) + ' 남음</span>' +
      '</div>' +
      '<div class="usage-bar-track"><div class="usage-bar-fill' + (pctSafe <= 20 ? ' low' : '') + '" style="transform:scaleX(' + (pctSafe / 100) + ')"></div></div>' +
      '<div class="status-item-preview">리셋: ' + escapeHtml(resetStr) + '</div>';
    statusUsageEl.appendChild(item);
  });
  if (usageCheckedAtEl) {
    const checked = res.checked_at ? new Date(res.checked_at * 1000).toLocaleTimeString('ko-KR') : '';
    usageCheckedAtEl.textContent = checked ? ('마지막 확인: ' + checked) : '';
  }
}

async function fetchSessionsList(retryCount = 0) {
  if (!sessionsListEl) return;
  sessionsListEl.innerHTML = '<div class="status-hint">불러오는 중…' + (retryCount > 0 ? ' (재시도 중)' : '') + '</div>';
  try {
    const res = await api('/api/sessions');
    renderSessionsList(res.sessions || []);
  } catch (e) {
    if (retryCount < 1) {
      setTimeout(() => fetchSessionsList(retryCount + 1), 600);
      return;
    }
    sessionsListEl.innerHTML =
      '<div class="status-hint">' +
      '세션 목록 로드 실패: ' + escapeHtml(e.message) + ' ' +
      '<button type="button" class="btn-xs" style="margin-left:6px;cursor:pointer;" onclick="fetchSessionsList(0)">다시 시도 ↻</button>' +
      '</div>';
  }
}

function renderSessionsList(sessions) {
  if (!sessionsListEl) return;
  sessionsListEl.innerHTML = '';
  // Hide empty throwaway sessions (e.g. repeated "새 세션" clicks nobody
  // typed into) -- they clutter the list with nothing useful to open --
  // but never hide the one currently open, even if it happens to be empty.
  const visible = sessions.filter(s => s.preview || s.id === sessionId);
  if (!visible.length) {
    sessionsListEl.innerHTML = '<div class="status-hint">세션이 없습니다.</div>';
    return;
  }
  visible.forEach(s => {
    const isCurrent = s.id === sessionId;
    const item = document.createElement('div');
    item.className = 'status-item session-row' + (isCurrent ? ' current' : '');
    let when = s.updated_at || '';
    try { when = new Date(s.updated_at).toLocaleString('ko-KR'); } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="session-row-id">' + escapeHtml(s.id) + (isCurrent ? ' (현재)' : '') + '</span>' +
      '<span class="status-item-meta">' + (s.turns || 0) + '턴 · ' + escapeHtml(s.model || '') + ' · ' + escapeHtml(when) + '</span>' +
      '<div class="status-item-actions">' +
      '<button class="session-import-btn" data-import-sid="' + escapeHtml(s.id) + '" type="button">' + getActionSvg('pin') + ' 가져오기</button>' +
      '<button class="session-import-btn session-delete-btn" data-delete-sid="' + escapeHtml(s.id) + '" type="button">' + getActionSvg('trash', 'text-danger') + ' 삭제</button>' +
      '</div>' +
      '</div>' +
      '<div class="session-row-preview">' + escapeHtml(s.preview || '(내용 없음)') + '</div>';
    item.addEventListener('click', (ev) => {
      if (ev.target.closest('[data-import-sid], [data-delete-sid]')) return;
      if (s.id !== sessionId) openSession(s.id, 0, null, true);
      switchTab('chat');
    });
    sessionsListEl.appendChild(item);
  });
  sessionsListEl.querySelectorAll('[data-import-sid]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      importSessionContext(btn.getAttribute('data-import-sid'));
    });
  });
  sessionsListEl.querySelectorAll('[data-delete-sid]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      deleteSession(btn.getAttribute('data-delete-sid'));
    });
  });
}

async function deleteSession(sid) {
  if (!sid) return;
  if (!(await confirmModal('세션 ' + sid + '을(를) 완전히 삭제할까요? 대화 기록과 생성된 이미지가 전부 사라지며 되돌릴 수 없습니다.', { confirmLabel: '삭제' }))) return;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sid), { method: 'DELETE' });
    if (!res || res.ok === false) throw new Error((res && res.error) || '삭제 실패');
    if (sid === sessionId) {
      // The session we're currently looking at just got deleted -- fall
      // back exactly the way a fresh page load would (ensureSession's own
      // active/localStorage/latest/create chain), instead of a separate,
      // narrower reimplementation of just its "latest or create" tail.
      rememberSession('');
      await ensureSession();
    }
    fetchSessionsList();
  } catch (e) {
    await alertModal('세션 삭제 실패: ' + (e.message || e));
  }
}

// Fetches a read-only handover-style summary of an arbitrary (often archived)
// session and prefills the composer with it, labeled by source session id.
// Never auto-sends -- 실장님 reviews/edits before it becomes part of the live
// conversation, and the target session itself is never modified.
async function importSessionContext(sid) {
  if (!sid) return;
  const prevPlaceholder = inputEl ? inputEl.placeholder : '';
  if (inputEl) inputEl.placeholder = '세션 ' + sid + ' 요약 가져오는 중…';
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sid) + '/summary');
    const summary = (res && res.summary) || '(요약할 내용이 없습니다)';
    const note = '[이전 세션 ' + sid + ' 내용 참고]\n' + summary + '\n\n';
    if (inputEl) {
      inputEl.value = note + (inputEl.value || '');
      inputEl.focus();
      inputEl.style.height = 'auto';
      inputEl.style.height = inputEl.scrollHeight + 'px';
      updateSendButton();
    }
    switchTab('chat');
  } catch (e) {
    await alertModal('세션 요약 가져오기 실패: ' + (e.message || e));
  } finally {
    if (inputEl) inputEl.placeholder = prevPlaceholder;
  }
}

function renderStatusMemory(mem) {
  if (!statusMemoryEl) return;
  statusMemoryEl.innerHTML = '';
  if (!mem) {
    statusMemoryEl.innerHTML = '<div class="status-hint">저장된 장기 기억 파일(data/workspace/memory/MEMORY.md)이 없습니다.</div>';
    return;
  }
  const item = document.createElement('div');
  item.className = 'status-item';
  const mtime = mem.mtime ? new Date(mem.mtime * 1000).toLocaleString('ko-KR') : '?';
  item.innerHTML =
    '<div class="status-item-head">' +
    '<span class="status-item-name">' + escapeHtml(mem.name) + '</span>' +
    '<span class="status-item-meta">' + (mem.size || 0) + ' bytes · ' + mtime + ' (읽기 전용)</span>' +
    '<div class="status-item-actions"><button class="art-btn" id="memToggleBtn" type="button">전체 보기</button></div>' +
    '</div>' +
    '<div class="status-item-preview" id="memPreviewBox" style="white-space:pre-wrap;font-family:inherit;max-height:160px;overflow-y:auto">' + escapeHtml(mem.content || '(내용 없음)') + '</div>';
  statusMemoryEl.appendChild(item);

  const btn = item.querySelector('#memToggleBtn');
  const box = item.querySelector('#memPreviewBox');
  if (btn && box) {
    let expanded = false;
    btn.addEventListener('click', () => {
      expanded = !expanded;
      box.style.maxHeight = expanded ? 'none' : '160px';
      btn.textContent = expanded ? '접기' : '전체 보기';
    });
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
        await alertModal('저장 실패: ' + e.message);
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
      '<button class="status-toggle ' + (s.enabled ? 'on' : 'off') + '" data-toggle-skill="' + escapeHtml(s.name) + '" type="button" title="' + (s.enabled ? '스킬 끄기' : '스킬 켜기') + '">' +
      '<span class="status-toggle-label" style="font-size:.75rem;color:var(--muted)">' + (s.enabled ? 'ON' : 'OFF') + '</span>' +
      '<span class="switch-ui"></span>' +
      '</button>' +
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
        await alertModal('토글 실패: ' + e.message);
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
      if (!(await confirmModal(name + ' MCP 서버를 삭제할까요?', { confirmLabel: '삭제' }))) return;
      try {
        await api('/api/mcp/' + encodeURIComponent(name), { method: 'DELETE' });
        addActivity('MCP ' + name + ' 삭제됨 (다음 새 세션부터 반영)');
        fetchSelfStatus();
      } catch (e) {
        await alertModal('삭제 실패: ' + e.message);
      }
    });
  });
}



// Styled replacement for window.confirm() -- destructive actions (session
// delete, MCP server delete, host defibrillate) used the browser's native
// dialog, which drops unstyled OS chrome into an otherwise fully-skinned
// dark UI and, worse, can't be dismissed with the same Escape reflex every
// other overlay in this app supports (impeccable critique P1, 2026-09-17).
// Falls back to window.confirm if the modal markup is somehow missing.
function confirmModal(message, opts) {
  opts = opts || {};
  const isAlert = !!opts.alert;
  if (!confirmModalEl || !confirmModalMsgEl || !confirmModalOkBtn || !confirmModalCancelBtn) {
    if (isAlert) { window.alert(message); return Promise.resolve(true); }
    return Promise.resolve(window.confirm(message));
  }
  return new Promise(resolve => {
    confirmModalMsgEl.textContent = message;
    confirmModalOkBtn.textContent = opts.confirmLabel || '확인';
    confirmModalCancelBtn.textContent = opts.cancelLabel || '취소';
    confirmModalCancelBtn.style.display = isAlert ? 'none' : '';
    confirmModalOkBtn.className = (isAlert || opts.danger === false) ? 'primary' : 'danger';
    confirmModalEl.style.display = 'flex';
    const cleanup = (result) => {
      confirmModalEl.style.display = 'none';
      confirmModalCancelBtn.style.display = '';
      confirmModalOkBtn.removeEventListener('click', onOk);
      confirmModalCancelBtn.removeEventListener('click', onCancel);
      confirmModalEl.removeEventListener('click', onOverlay);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const onOk = () => cleanup(true);
    const onCancel = () => cleanup(isAlert);
    const onOverlay = (e) => { if (e.target === confirmModalEl) cleanup(isAlert); };
    const onKey = (e) => {
      if (e.key === 'Escape') { cleanup(isAlert); return; }
      if (e.key === 'Tab') {
        e.preventDefault();
        if (isAlert) { confirmModalOkBtn.focus(); return; }
        (document.activeElement === confirmModalOkBtn ? confirmModalCancelBtn : confirmModalOkBtn).focus();
      }
    };
    confirmModalOkBtn.addEventListener('click', onOk);
    confirmModalCancelBtn.addEventListener('click', onCancel);
    confirmModalEl.addEventListener('click', onOverlay);
    document.addEventListener('keydown', onKey);
    confirmModalOkBtn.focus();
  });
}

function alertModal(message) {
  return confirmModal(message, { alert: true, danger: false, confirmLabel: '확인' });
}

function bindEvents(sid) {
  if (es) { try { es.close(); } catch (_) {} es = null; }
  const live = logEl && logEl.querySelector('.msg[data-live="1"]');
  if (live && live.isConnected) assistantNode = live;
  else { assistantNode = null; assistantBuf = ''; }
  es = new EventSource(BASE_PATH + '/api/sessions/' + encodeURIComponent(sid) + '/events');
  es.onmessage = (ev) => {
    let data; try { data = JSON.parse(ev.data); } catch (_) { return; }
    const type = data.event || data.type || '';
    const text = data.text || data.message || data.content || '';

    if (type === 'image') {
      const u = absArtifact(data.url || text);
      if (u && !(assistantBuf || '').includes(u)) {
        if (!assistantNode) {
          assistantNode = addChat('assistant', '', false);
          assistantNode.dataset.live = '1';
        }
        assistantBuf = (assistantBuf || '') + '\n\n![](' + u + ')\n';
        setAssistantContent(assistantNode, assistantBuf, false);
      }
      fetchArtifacts(true);
      return;
    }

    if (type === 'delta' || type === 'assistant' || type === 'agy' || type === 'message') {
      setBusy(true);
      if (!assistantNode) {
        assistantNode = addChat('assistant', '', false);
        assistantNode.dataset.live = '1';
      }
      if (assistantNode) delete assistantNode.dataset.progress;
      if (type === 'delta') assistantBuf += text;
      else if (text) assistantBuf = text;
      setAssistantContent(assistantNode, assistantBuf || '작성 중…', false);
      updateTurnLive();
      return;
    }

    if (type === 'result') {
      if (text) assistantBuf = text;
      if (assistantNode) delete assistantNode.dataset.progress;
      const doneNode = assistantNode;
      const doneBuf = assistantBuf;
      setBusy(false);
      // A resync may already have drawn this very answer (same ts) before the event got here.
      const twin = data.ts ? findRenderedByTs('assistant', data.ts) : null;
      if (twin && twin !== doneNode) {
        if (doneNode) doneNode.remove();
      } else if (doneBuf && doneBuf.trim()) {
        const node = doneNode || addChat('assistant', '', false);
        setAssistantContent(node, doneBuf, true, data.usage, data.duration_seconds, data.served_model);
        if (data.ts) {
          node.dataset.ts = String(data.ts);
          node.dataset.syncRole = 'assistant';
        }
        delete node.dataset.live;
      } else if (doneNode) {
        // If nothing was generated or only empty progress was shown, remove empty assistant bubble
        doneNode.remove();
      }
      if (data.usage || data.duration_seconds != null) logTurnUsage(data.usage, data.duration_seconds);
      if (data.ts) lastSyncedTs = Math.max(lastSyncedTs, data.ts);
      assistantNode = null; assistantBuf = '';
      repairMsgOrder();
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
      // This event is broadcast on the OLD session -- including to the
      // very tab whose send() just triggered the rotation, since that tab
      // is still subscribed to the old session's SSE stream at this exact
      // moment. That tab's send() already handles the transition itself
      // via the /message POST response (with the user's own message
      // already on screen, seamlessly). Re-handling it here too raced that
      // response -- and since this event fires earlier server-side (before
      // the successor's spawn/send even runs), it usually rendered FIRST,
      // wiping the just-sent message from view and making it look lost
      // (실장님: "내가 말을 하면 바로 새 세션으로 넘어가면서 내가 한 말을
      // 또 해야 되는 상황이 생겨"). client_mid tells us which case this is.
      const isMine = Boolean(data.client_mid) && myPendingMids.has(data.client_mid);
      if (isMine) {
        myPendingMids.delete(data.client_mid);
        return;
      }
      addActivity('세션 자동 전환: ' + (text || '') + (nid ? ' → ' + nid : ''));
      if (nid) {
        enterSession(nid, {
          scrollback: 'self',
          greeting: text || '새 채팅으로 전환했습니다냥. 이어서 진행한다냥!',
          metaLabel: '(자동 전환)',
          weight: { level: 'hard', message_ko: text || '세션이 길어져 새 채팅으로 전환합니다' },
        });
      } else {
        showSessionHeavyBanner('hard', text || '세션이 길어져 새 채팅으로 전환합니다');
      }
      setBusy(true);
      return;
    }

    if (type === 'stopped') {
      addActivity('작업 중지: ' + (text || ''));
      const stopMsg = '🛑 **작업 중단 알림**\n\n' + (text || '작업이 중단되었습니다냥.');
      if (assistantNode) {
        clearTurnLive(assistantNode);
        if (assistantBuf && assistantBuf.trim() && assistantNode.dataset.progress !== '1') {
          markUntimed(assistantNode, assistantBuf);
          setAssistantContent(assistantNode, assistantBuf.trim() + '\n\n---\n' + stopMsg, true);
          delete assistantNode.dataset.live;
        } else {
          assistantNode.remove();
          addChat('assistant', stopMsg, true, false, false, false, null, null, true, data.ts);
        }
      } else {
        addChat('assistant', stopMsg, true, false, false, false, null, null, true, data.ts);
      }
      assistantNode = null; assistantBuf = '';
      setBusy(false);
      setProgress('');
      return;
    }

    if (type === 'interrupted') {
      addActivity('⚡ ' + (text || '진행 중인 작업 전환'));
      if (assistantNode && assistantBuf && assistantBuf.trim()) {
        // Finalize partial output with an interrupted mark
        markUntimed(assistantNode, assistantBuf);
        setAssistantContent(assistantNode, assistantBuf.trim() + (data.reason === 'steer' ? '\n\n*(🧭 새 지시 반영을 위해 잠시 멈춤)*' : '\n\n*(⚡ 새 지시로 전환)*'), true);
        delete assistantNode.dataset.live;
      } else if (assistantNode && assistantNode.dataset.progress === '1') {
        assistantNode.remove();
      }
      assistantNode = null; assistantBuf = '';
      setProgress('새 지시 반영 중…');
      return;
    }

    if (type === 'queued') {
      addActivity('대기열 등록 (대기: ' + (data.queue_len || 1) + '건)');
      return;
    }

    if (type === 'steer_queued') {
      addActivity('🧭 ' + (text || '새 지시 접수'));
      setProgress('새 지시 접수 · 지금 단계가 끝나면 반영해요…');
      return;
    }

    if (type === 'user_ack') {
      // Broadcast to every window/tab on this shared session whenever a user
      // message actually gets sent to agy -- including from a message sent
      // by an EXACT one of the other windows. This window's own just-sent
      // message was already rendered optimistically at send() time (with a
      // client_mid tag), so only render here when the mid doesn't match
      // anything this window itself sent (실장님: "다른 창에서 보낸 질의는
      // 안 보이네" -- previously this handler only ever un-queued this
      // window's own bubble and never rendered anyone else's).
      const mid = data.client_mid || '';
      const isMine = Boolean(mid) && myPendingMids.has(mid);
      // A resync can have drawn (or stamped) this message before its ack arrives.
      const drawn = Boolean(data.ts && (findRenderedByTs('user', data.ts) || findRenderedByTs('btw-user', data.ts)));
      if (isMine) {
        myPendingMids.delete(mid);
        const queuedNodes = logEl.querySelectorAll('.msg.user.queued');
        if (queuedNodes.length > 0) {
          queuedNodes[0].classList.remove('queued');
          addActivity('대기열 작업 착수: ' + shortToolLine(text));
        }
        if (!drawn && data.ts && !adoptBareUserBubble(text, data.ts)) {
          const bare = logEl.querySelectorAll('.msg.user:not([data-ts])');
          if (bare.length) {
            const n = bare[bare.length - 1];
            n.dataset.ts = String(data.ts);
            n.dataset.syncRole = 'user';
          }
        }
      } else if (!drawn && !adoptBareUserBubble(text, data.ts)) {
        addChat('user', text, false, false, (text || '').startsWith('/btw'), false, null, null, false, data.ts);
      }
      if (data.ts) lastSyncedTs = Math.max(lastSyncedTs, data.ts);
      repairMsgOrder();
      setBusy(true);
      return;
    }

    if (type === 'btw_start') {
      addActivity('샛길 질문(/btw) 처리 중: ' + shortToolLine(data.query || ''));
      return;
    }

    if (type === 'btw') {
      // The card may already be there: a resync that ran between the server's save and this
      // event draws it from history, and drawing it again made two cards.
      if (!(data.ts && findRenderedByTs('btw', data.ts))) {
        addBtw(data.query, data.text, false, data.usage, data.duration_seconds, data.ts);
      }
      addActivity('샛길 질문(/btw) 응답 완료');
      if (data.usage || data.duration_seconds != null) logTurnUsage(data.usage, data.duration_seconds);
      if (data.ts) lastSyncedTs = Math.max(lastSyncedTs, data.ts);
      return;
    }

    if (type === 'tool' || type === 'system' || type === 'stderr' || type === 'error') {
      const line = (type === 'error' ? '오류: ' : '') + (text || JSON.stringify(data.error || data));
      const kind = data.kind || (type === 'tool' ? (line.startsWith('↳') ? 'result' : 'tool') : (type === 'stderr' ? 'warn' : type));
      const detail = data.detail || '';
      if (type === 'tool') {
        const s = String(text || '').trim().toLowerCase();
        if (!s || s === 'tool' || s === 'tool: tool' || s === 'tool:tool') return;
        if (kind !== 'result' && !line.startsWith('↳')) {
          setBusy(true);
          setProgress('작업 중 · ' + shortToolLine(text));
        }
      } else if (type === 'system') {
        if (text && text.includes('started')) setBusy(true);
        setProgress(shortToolLine(text) || '처리 중…');
      } else if (type === 'error') {
        setProgress('오류 · ' + shortToolLine(text));
        setBusy(false);
      }
      addActivity(line, kind, data.ts, detail);
      if (type === 'error') { assistantNode = null; assistantBuf = ''; }
      return;
    }

    if (type === 'agy' && data.payload) {
      const p = data.payload;
      if (Array.isArray(p.tool_calls) && p.tool_calls.length) {
        for (const tc of p.tool_calls) {
          if (tc && tc.name) {
            const rawArgs = tc.args || tc.input;
            const line = formatToolCallClient(tc.name, rawArgs);
            setBusy(true);
            if (!line) continue; // args not populated yet (streaming) - wait for the complete call
            setProgress('작업 중 · ' + shortToolLine(line));
            const detailStr = (rawArgs && typeof rawArgs === 'object') ? JSON.stringify(rawArgs, null, 2) : '';
            addActivity(line, 'tool', data.ts, detailStr);
          }
        }
        return;
      }
      if (p.type === 'GENERIC' && p.content) {
        const resLine = formatToolResultClient(p.content);
        const rawContent = String(p.content || '').trim();
        const detailStr = (rawContent.length > resLine.length || rawContent.includes('\n')) ? rawContent : '';
        addActivity(resLine, 'result', data.ts, detailStr);
        return;
      }
    }
  };
  es.onerror = () => {
    try { es.close(); } catch (_) {}
    es = null;
    updateProcBadge('disconnected');
    window.__agyEsRetry = (window.__agyEsRetry || 0) + 1;
    // First reconnect is usually the idle SSE recycle or a mobile blip —
    // don't flash "연결이 끊겼다냥" over a turn that's still running.
    if (window.__agyEsRetry >= 2) setProgress('연결이 끊겼다냥 · 다시 연결하는 중…');
    if (window.__agyEsTimer) clearTimeout(window.__agyEsTimer);
    const wait = Math.min(15000, 800 * Math.pow(1.6, Math.min(window.__agyEsRetry, 8)));
    window.__agyEsTimer = setTimeout(() => {
      if (sessionId === sid) bindEvents(sid);
    }, wait);
  };
  es.onopen = () => {
    window.__agyEsRetry = 0;
    if (!isBusy) updateProcBadge('idle');
    setProgress('');
    resyncFromServer(sid);
  };
  startSessionSyncLoop();
}

// Shared "we're now looking at session `id`" transition. openSession,
// createSession, continueSession, the SSE session_rotate handler, and
// send()'s mid-turn hard-rotate branch all used to repeat this same
// clear-log/reset-scrollback/greet/setMeta/bindEvents/fetchArtifacts
// sequence by hand (2026-09-17 refactor pass) -- each call site now only
// supplies what's actually different about it via opts:
//   scrollback: 'self' to anchor scrollback at `id` itself (openSession,
//     continueSession, session_rotate), a specific other session id --
//     including '' -- to anchor at instead (createSession's "완전 새 세션"
//     points at whatever was open right before it), or omitted entirely to
//     leave scrollback/lastSyncedTs untouched (send()'s rotate branch never
//     reset these even before this consolidation -- preserved as-is rather
//     than changed as a drive-by fix; see DEVLOG).
//   history: existing messages to render (openSession only).
//   userEcho / greeting: chat bubbles to add after clearing (the message
//     just sent, and/or a assistant greeting/handoff note).
//   activityAfter: an activity-log line to add after clearing.
//   metaLabel: the part of the meta line after "세션 <id> · ".
//   weight: pass through to the heavy-session banner check; omitted means
//     always hide it (matches every non-openSession call site).
//   busy: explicit busy state; omitted means don't touch it at all (only
//     continueSession relies on this, since its own try/finally already
//     manages busy across the whole operation, success or failure).
//   preserveLog: true to skip clearing #log/#activity entirely -- used by
//     send()'s in-flow hard-rotate so a message sent mid-conversation
//     doesn't flash-clear the screen it's already visible on (the message
//     was already rendered optimistically by send() before this ever runs).
//     Only makes sense combined with no history/userEcho/greeting, since
//     nothing gets wiped for them to render into a "fresh" view.
function enterSession(id, opts) {
  opts = opts || {};
  rememberSession(id);
  if (!opts.preserveLog) {
    detachSessionBanner();
    logEl.innerHTML = '';
    activityEvents = [];
    if (activityEl) activityEl.innerHTML = '';
    activityNextBefore = null;
    activityLogFetched = false;
    currentSessionHasUser = Boolean((opts.history || []).some(h => h.role === 'user'));
    sessionActionsDismissed = false;
  } else if (!opts.weight || !opts.weight.level || opts.weight.level === 'ok') {
    sessionActionsDismissed = false;
  }
  if (opts.userEcho) currentSessionHasUser = true;

  if (opts.scrollback !== undefined) {
    // syncedTs (used by send()'s preserveLog rotate branch): the new
    // session already has one bit of history -- the message just sent,
    // already visible on screen from send()'s own optimistic render --
    // seed lastSyncedTs to its real ts instead of 0 so the new SSE
    // connection's resyncFromServer() doesn't treat it as "missed" and
    // render a duplicate copy of it.
    lastSyncedTs = opts.syncedTs != null ? opts.syncedTs : 0;
    if (opts.scrollback === 'self') {
      scrollbackSid = id;
      scrollbackExhausted = false;
      scrollbackVisited = new Set([id]);

      scrollforwardSid = id;
      scrollforwardExhausted = false;
      scrollforwardVisited = new Set([id]);
    } else {
      scrollbackSid = opts.scrollback;
      scrollbackExhausted = !opts.scrollback;
      scrollbackVisited = new Set();

      scrollforwardSid = '';
      scrollforwardExhausted = true;
      scrollforwardVisited = new Set();
    }
  }

  if (opts.history) {
    opts.history.forEach(h => {
      if (h.role === 'btw') {
        addBtw(h.query, h.text, false, h.usage, h.duration_seconds, h.ts);
      } else if (h.role === 'user') {
        addChat('user', h.text || '', false, Boolean(h.queued), (h.text || '').startsWith('/btw'), false, null, null, false, h.ts);
      } else if (h.role === 'assistant') {
        addChat('assistant', h.text || '', true, false, false, false, h.usage, h.duration_seconds, false, h.ts, h.served_model);
      }
      lastSyncedTs = Math.max(lastSyncedTs, h.ts || 0);
    });
    // Each addChat() call already scrolls to bottom as it's added, but
    // that's measured against scrollHeight *at that instant* -- an
    // assistant message with an image (common: 냥피디 generates a lot of
    // these) grows taller once the image finishes loading, after the last
    // addChat already ran, leaving the view short of the true bottom
    // (실장님: "냥피디 창이 처음 열릴 때 가장 최근 메시지까지 이동하지
    // 않고 있어"). Re-pin now and once more shortly after, by which point
    // any images have almost certainly finished loading.
    logEl.scrollTop = logEl.scrollHeight;
    setTimeout(() => { logEl.scrollTop = logEl.scrollHeight; }, 200);
    setSessionTokensFromHistory(opts.history);
  } else {
    setSessionTokensFromHistory([]);
  }

  if (opts.userEcho) addChat('user', opts.userEcho, false, false, false);
  if (opts.greeting) addChat('assistant', opts.greeting, true);
  if (opts.activityAfter) addActivity(opts.activityAfter);

  // Moved out of the `opts.history` branch above: createSession()/
  // continueSession() set up scrollback (opts.scrollback) too but never pass
  // opts.history (a brand-new session has none yet), so this never used to
  // run for them -- their only content is the short greeting bubble, which
  // never overflows the viewport on its own, so there was no scrollbar to
  // manually scroll-near-top with in the first place. The scroll listener's
  // own overflow guard (see below) now also refuses to backfill from a
  // spurious clamp-to-zero scroll event, so without this, a brand-new
  // session had no way at all to pull in older sessions' content -- from
  // 실장님's side that read as "예전 세션 내용들이 다 사라져버렸는걸".
  // Running it here for every scrollback-tracked entry (not just
  // history-restoring ones) chain-loads previous sessions until the
  // viewport is filled, same as opening an existing short session already did.
  if (opts.scrollback !== undefined) setTimeout(maybeBackfillScrollback, 0);

  setMeta('세션 ' + id + ' · ' + (opts.metaLabel || ''));
  updateSessionNav(id, opts.sessionInfo);

  if (sessionBanner) {
    if (opts.weight && opts.weight.level) {
      sessionBanner.dataset.level = opts.weight.level;
      sessionBanner.dataset.message = opts.weight.message_ko || '';
    } else if (!opts.preserveLog) {
      sessionBanner.dataset.level = 'ok';
      sessionBanner.dataset.message = '';
    }
  }

  if (opts.busy !== undefined) setBusy(Boolean(opts.busy));
  else syncSessionActions();

  bindEvents(id);
  fetchArtifacts(true);
  fetchLog();
}

async function openSession(id, _redirDepth, bannerOverride, noRedirect) {
  const info = await api('/api/sessions/' + encodeURIComponent(id));
  if (!noRedirect) {
    const bounced = await maybeRedirectHardSession(id, info, _redirDepth || 0);
    if (bounced) return;
  }
  if (liveSessionId && id !== liveSessionId) archiveBrowse = true;
  else {
    archiveBrowse = false;
    if (isLiveSid(id)) liveSessionId = liveSessionId || id;
  }
  enterSession(id, {
    scrollback: 'self',
    sessionInfo: info,
    history: info.history || [],
    metaLabel: info.model || '',
    // bannerOverride (set only by maybeRedirectHardSession's own bounce
    // paths) forces the hard-session banner to show here even though this
    // freshly-landed-on session's own weight is 'ok' -- the point is to
    // explain to the user, in the 대화 tab itself, that they were just
    // auto-redirected here from a different session (previously this was
    // only ever logged to the non-default 로그 tab via addActivity, which
    // read as an unexplained context switch -- 2026 impeccable critique P0).
    weight: bannerOverride || info.weight,
    busy: info.busy,
    activityAfter: '세션 복원 ' + id,
  });
  applySessionProvider(info);
}

// Re-syncs the live view against server history + in-flight draft.
// SSE can go zombie on a backgrounded phone, so this also runs on a
// visibility/poll loop — not only on EventSource onopen. Missed items
// are keyed by role+ts and inserted in timestamp order (before any
// live streaming bubble) so a late user_ack cannot land under the answer.
let resyncInFlight = false;
async function resyncFromServer(sid) {
  if (!sid || sid !== sessionId) return;
  if (resyncInFlight) return;
  resyncInFlight = true;
  try {
    let info;
    try { info = await api('/api/sessions/' + encodeURIComponent(sid)); } catch (_) { return; }
    if (!info || info.id !== sid || sid !== sessionId) return;

    const seen = new Set();
    logEl.querySelectorAll('.msg[data-ts]').forEach(n => {
      seen.add(msgSyncKey(n.dataset.syncRole || '', n.dataset.ts));
    });

    let added = 0;
    (info.history || []).forEach(h => {
      if (!h.ts) return;
      const role = h.role || '';
      const k = msgSyncKey(role, h.ts);
      if (seen.has(k)) {
        lastSyncedTs = Math.max(lastSyncedTs, h.ts);
        return;
      }
      if (role === 'assistant' && assistantNode && assistantNode.dataset.live === '1') {
        setAssistantContent(assistantNode, h.text || '', true, h.usage, h.duration_seconds, h.served_model);
        assistantNode.dataset.ts = String(h.ts);
        assistantNode.dataset.syncRole = 'assistant';
        delete assistantNode.dataset.live;
        delete assistantNode.dataset.progress;
        assistantNode = null;
        assistantBuf = '';
        seen.add(k);
        lastSyncedTs = Math.max(lastSyncedTs, h.ts);
        added++;
        return;
      }
      if (role === 'btw') {
        addBtw(h.query, h.text, false, h.usage, h.duration_seconds, h.ts);
      } else if (role === 'user') {
        const bare = Array.prototype.slice.call(logEl.querySelectorAll('.msg.user:not([data-ts])'));
        const match = bare.find(function (n) { return (n.textContent || '') === (h.text || ''); });
        if (match) {
          match.dataset.ts = String(h.ts);
          match.dataset.syncRole = 'user';
          placeMsgByTs(match, h.ts);
        } else {
          addChat('user', h.text || '', false, Boolean(h.queued), (h.text || '').startsWith('/btw'), false, null, null, false, h.ts);
        }
      } else if (role === 'assistant') {
        // the client already closed this one itself (interrupt/stop) and has it, ts-less, on screen
        if (adoptUntimedAssistant(h)) {
          seen.add(k);
          lastSyncedTs = Math.max(lastSyncedTs, h.ts);
          return;
        }
        addChat('assistant', h.text || '', true, false, false, false, h.usage, h.duration_seconds, false, h.ts, h.served_model);
      } else {
        return;
      }
      seen.add(k);
      lastSyncedTs = Math.max(lastSyncedTs, h.ts);
      added++;
    });

    if (info.busy) {
      setBusy(true);
      if (info.last_progress) setProgress('작업 중 · ' + shortToolLine(info.last_progress));
      const draft = info.current_text || '';
      if (draft) {
        if (!assistantNode) {
          assistantNode = addChat('assistant', '', false);
          assistantNode.dataset.live = '1';
        }
        if (draft.length >= (assistantBuf || '').length) {
          assistantBuf = draft;
          setAssistantContent(assistantNode, assistantBuf, false);
        }
      }
    } else {
      // Server is NOT busy
      if (assistantNode && assistantNode.dataset.live === '1') {
        // If there's an active live bubble that wasn't finalized by history loop
        if (assistantBuf && assistantBuf.trim()) {
          markUntimed(assistantNode, assistantBuf);
          setAssistantContent(assistantNode, assistantBuf, true);
          delete assistantNode.dataset.live;
          delete assistantNode.dataset.progress;
        } else {
          assistantNode.remove();
        }
        assistantNode = null;
        assistantBuf = '';
      }
      // myPendingMids is deliberately NOT cleared here: an idle server does not mean my sent
      // message is done -- during a steer respawn the server is idle until it writes the
      // message and acks it, and clearing turned my own ack into "someone else's" (a 2nd bubble).
      if (isBusy) {
        setBusy(false);
      }
    }

    repairMsgOrder();

    if (added) {
      addActivity('동기화: 놓친 메시지 ' + added + '건 반영', 'system');
      fetchArtifacts(true);
    }
    // Chat history already syncs here; provider chrome used to stay on
    // this device's localStorage until a full reload.
    if (typeof applySessionProvider === 'function') applySessionProvider(info);
  } finally {
    resyncInFlight = false;
  }
}

function startSessionSyncLoop() {
  if (window.__sessionSyncTimer) return;
  window.__sessionSyncTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return;
    if (!sessionId) return;
    followLiveIfNeeded().then(() => {
      resyncFromServer(sessionId);
    }).catch(() => {});
    if (es && es.readyState === EventSource.CLOSED) bindEvents(sessionId);
  }, 2500);
  if (!window.__sessionSyncVis) {
    window.__sessionSyncVis = true;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible' || !sessionId) return;
      if (!es || es.readyState === EventSource.CLOSED) bindEvents(sessionId);
      else resyncFromServer(sessionId);
    });
    window.addEventListener('pageshow', () => {
      if (!sessionId) return;
      if (!es || es.readyState === EventSource.CLOSED) bindEvents(sessionId);
      else resyncFromServer(sessionId);
    });
  }
}

// Loads one predecessor-session hop of history and prepends it above the
// current top of #log, walking scrollbackSid back one link at a time. Never
// feeds anything back into agy's context -- purely a read-only archive view.
// Resolves the "previous session" for scrollback purposes: the real
// predecessor_session_id when set, or -- for an explicit "완전 새 세션" reset,
// which intentionally has no predecessor link -- the chronologically-next-
// older session overall, purely as a browsing convenience (never affects
// agy context). Returns '' when there's truly nothing older.
// GET /api/sessions/:id returns updated_at as an epoch-seconds float
// (file mtime), while GET /api/sessions (list) returns it as an ISO
// string from meta.json -- two different pre-existing endpoints, two
// different formats. Normalize both to epoch-ms before comparing.
function _scrollbackEpochMs(v) {
  if (typeof v === 'number') return v * 1000;
  const t = Date.parse(v);
  return isNaN(t) ? 0 : t;
}

async function resolveScrollbackFallback(sid, updatedAt, visited) {
  const cur = _scrollbackEpochMs(updatedAt);
  try {
    const list = await api('/api/sessions');
    const valid = (list.sessions || []).filter(s => s.id !== sid && !visited.has(s.id) && (s.preview || (s.turns && s.turns > 0)));
    let cands = valid.filter(s => s.updated_at && (!cur || _scrollbackEpochMs(s.updated_at) < cur))
      .sort((a, b) => _scrollbackEpochMs(b.updated_at) - _scrollbackEpochMs(a.updated_at));
    if (cands.length) return cands[0].id;
    cands = valid.filter(s => s.id < sid).sort((a, b) => b.id.localeCompare(a.id));
    return cands.length ? cands[0].id : '';
  } catch (_) {
    return '';
  }
}

async function loadOlderHistory() {
  if (scrollbackLoading || scrollbackExhausted || !scrollbackSid) return;
  scrollbackLoading = true;
  const marker = document.createElement('div');
  marker.className = 'msg scrollback-marker';
  marker.textContent = '이전 대화 불러오는 중…';
  logEl.insertBefore(marker, logEl.firstChild);
  const prevScrollHeight = logEl.scrollHeight;
  const prevScrollTop = logEl.scrollTop;
  try {
    // Skip transparently through any hop(s) that turn out to have no real
    // content (e.g. a chain of back-to-back "새 세션" resets nobody typed
    // into) instead of showing an empty divider for each one.
    let lastKnownTs = 0; // last hop's updated_at we actually saw -- used to
    // anchor the fallback search when the NEXT hop turns out to be deleted
    for (let hops = 0; hops < 20; hops++) {
      // openSession() pre-seeds this with the session it just rendered in
      // full via its own forEach, specifically so this first hop can reuse
      // it as the fallback anchor WITHOUT re-rendering the same messages a
      // second time.
      const alreadyRendered = scrollbackVisited.has(scrollbackSid);
      scrollbackVisited.add(scrollbackSid);
      let info;
      try {
        info = await api('/api/sessions/' + encodeURIComponent(scrollbackSid) + '?full=1');
      } catch (_) {
        // This session was deleted (실장님's new 🗑 삭제 button) -- route
        // around the dead link instead of aborting the whole scrollback.
        const fallback = await resolveScrollbackFallback(scrollbackSid, lastKnownTs, scrollbackVisited);
        if (fallback) {
          scrollbackSid = fallback;
          continue;
        }
        scrollbackExhausted = true;
        const cap = document.createElement('div');
        cap.className = 'msg scrollback-marker';
        cap.textContent = '── 대화 시작 (더 이전 기록 없음) ──';
        logEl.insertBefore(cap, logEl.firstChild);
        break;
      }
      lastKnownTs = _scrollbackEpochMs(info.updated_at) || lastKnownTs;
      const hist = info.history || [];
      let nextSid = info.predecessor_session_id || '';
      if (nextSid && scrollbackVisited.has(nextSid)) nextSid = ''; // cycle guard
      if (!nextSid) nextSid = await resolveScrollbackFallback(scrollbackSid, info.updated_at, scrollbackVisited);

      const showThisHop = hist.length && !alreadyRendered;
      if (showThisHop) {
        for (let i = hist.length - 1; i >= 0; i--) {
          const h = hist[i];
          if (h.role === 'btw') {
            addBtw(h.query, h.text, true, h.usage, h.duration_seconds, h.ts);
          } else if (h.role === 'user') {
            addChat('user', h.text || '', false, Boolean(h.queued), (h.text || '').startsWith('/btw'), true, null, null, false, h.ts);
          } else if (h.role === 'assistant') {
            addChat('assistant', h.text || '', true, false, false, true, h.usage, h.duration_seconds, false, h.ts, h.served_model);
          }
        }
        const divider = document.createElement('div');
        divider.className = 'msg scrollback-marker';
        divider.innerHTML = '── 세션 ' + escapeHtml(scrollbackSid) + ' ──' +
          ' <button class="session-switch-btn" data-switch-sid="' + escapeHtml(scrollbackSid) + '" type="button">이 세션으로 전환</button>' +
          ' <button class="session-import-btn" data-import-sid="' + escapeHtml(scrollbackSid) + '" type="button">' + getActionSvg('pin') + ' 가져오기</button>';
        logEl.insertBefore(divider, logEl.firstChild);
        divider.querySelectorAll('[data-switch-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openSession(btn.getAttribute('data-switch-sid'), 0, null, true);
          });
        });
        divider.querySelectorAll('[data-import-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            importSessionContext(btn.getAttribute('data-import-sid'));
          });
        });
      }

      if (nextSid) {
        scrollbackSid = nextSid;
        if (showThisHop) break; // showed something this call -- let the user see it before loading more
        // else: this hop was empty or already-rendered, loop again and skip past it silently
      } else {
        scrollbackExhausted = true;
        const cap = document.createElement('div');
        cap.className = 'msg scrollback-marker';
        cap.textContent = '── 대화 시작 (더 이전 기록 없음) ──';
        logEl.insertBefore(cap, logEl.firstChild);
        break;
      }
    }
    marker.remove();
    logEl.scrollTop = prevScrollTop + (logEl.scrollHeight - prevScrollHeight);
  } catch (_) {
    marker.remove();
  }
  scrollbackLoading = false;
  // A short/freshly-rotated session's history often doesn't fill the
  // viewport at all, so there's nothing to physically scroll and the
  // 'scroll' listener below never fires even though older content exists.
  // Chain-backfill until there's enough content to actually scroll, or the
  // predecessor chain runs out.
  maybeBackfillScrollback();
}

function maybeBackfillScrollback() {
  if (currentTab !== 'chat' || scrollbackExhausted || scrollbackLoading || !logEl) return;
  if (logEl.scrollHeight <= logEl.clientHeight + 20) {
    loadOlderHistory();
  }
}

async function resolveScrollforwardFallback(sid, updatedAt, visited) {
  try {
    const list = await api('/api/sessions');
    const valid = (list.sessions || []).filter(s => s.id !== sid && !visited.has(s.id) && (s.preview || (s.turns && s.turns > 0)));
    const cands = valid.filter(s => s.id > sid).sort((a, b) => a.id.localeCompare(b.id));
    return cands.length ? cands[0].id : '';
  } catch (_) {
    return '';
  }
}

async function loadNewerHistory() {
  if (scrollforwardLoading || scrollforwardExhausted || !scrollforwardSid) return;
  scrollforwardLoading = true;
  const marker = document.createElement('div');
  marker.className = 'msg scrollback-marker scrollforward-marker';
  marker.textContent = '다음 대화 불러오는 중…';
  logEl.appendChild(marker);
  try {
    let lastKnownTs = 0;
    for (let hops = 0; hops < 20; hops++) {
      const alreadyRendered = scrollforwardVisited.has(scrollforwardSid);
      scrollforwardVisited.add(scrollforwardSid);
      let info;
      try {
        info = await api('/api/sessions/' + encodeURIComponent(scrollforwardSid) + '?full=1');
      } catch (_) {
        const fallback = await resolveScrollforwardFallback(scrollforwardSid, lastKnownTs, scrollforwardVisited);
        if (fallback) {
          scrollforwardSid = fallback;
          continue;
        }
        scrollforwardExhausted = true;
        const cap = document.createElement('div');
        cap.className = 'msg scrollback-marker';
        cap.textContent = '── 최신 대화 (더 이후 기록 없음) ──';
        logEl.appendChild(cap);
        break;
      }
      lastKnownTs = _scrollbackEpochMs(info.updated_at) || lastKnownTs;
      const hist = info.history || [];
      let nextSid = info.successor_session_id || '';
      if (nextSid && scrollforwardVisited.has(nextSid)) nextSid = '';
      if (!nextSid) nextSid = await resolveScrollforwardFallback(scrollforwardSid, info.updated_at, scrollforwardVisited);

      const showThisHop = hist.length && !alreadyRendered;
      if (showThisHop) {
        const divider = document.createElement('div');
        divider.className = 'msg scrollback-marker';
        divider.innerHTML = '── 세션 ' + escapeHtml(scrollforwardSid) + ' (이후 대화) ──' +
          ' <button class="session-switch-btn" data-switch-sid="' + escapeHtml(scrollforwardSid) + '" type="button">이 세션으로 전환</button>' +
          ' <button class="session-import-btn" data-import-sid="' + escapeHtml(scrollforwardSid) + '" type="button">' + getActionSvg('pin') + ' 가져오기</button>';
        logEl.appendChild(divider);
        divider.querySelectorAll('[data-switch-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openSession(btn.getAttribute('data-switch-sid'));
          });
        });
        divider.querySelectorAll('[data-import-sid]').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            importSessionContext(btn.getAttribute('data-import-sid'));
          });
        });

        hist.forEach(h => {
          if (h.role === 'btw') {
            addBtw(h.query, h.text, false, h.usage, h.duration_seconds, h.ts);
          } else if (h.role === 'user') {
            addChat('user', h.text || '', false, Boolean(h.queued), (h.text || '').startsWith('/btw'), false, null, null, false, h.ts);
          } else if (h.role === 'assistant') {
            addChat('assistant', h.text || '', true, false, false, false, h.usage, h.duration_seconds, false, h.ts, h.served_model);
          }
        });
      }

      if (nextSid) {
        scrollforwardSid = nextSid;
        if (showThisHop) break;
      } else {
        scrollforwardExhausted = true;
        const cap = document.createElement('div');
        cap.className = 'msg scrollback-marker';
        cap.textContent = '── 최신 대화 (더 이후 기록 없음) ──';
        logEl.appendChild(cap);
        break;
      }
    }
  } catch (_) {
    scrollforwardExhausted = true;
  } finally {
    marker.remove();
    scrollforwardLoading = false;
    updateScrollBottomButton();
  }
}

async function updateSessionNav(id, sessionInfo) {
  const prevBtn = document.getElementById('sessionNavPrev');
  const nextBtn = document.getElementById('sessionNavNext');
  const latestBtn = document.getElementById('sessionNavLatest');
  const pastBadge = document.getElementById('pastSessionBadge');
  if (!prevBtn || !nextBtn) return;

  sessionNavPrevSid = '';
  sessionNavNextSid = '';

  if (!id) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    if (latestBtn) latestBtn.hidden = true;
    if (pastBadge) pastBadge.style.display = 'none';
    updateScrollBottomButton();
    return;
  }

  try {
    let info = sessionInfo;
    if (!info || info.id !== id) {
      info = await api('/api/sessions/' + encodeURIComponent(id));
    }
    const updatedAt = info ? info.updated_at : null;

    let prevSid = (info && info.predecessor_session_id) || '';
    if (!prevSid) {
      prevSid = await resolveScrollbackFallback(id, updatedAt, new Set([id]));
    }
    sessionNavPrevSid = prevSid;
    prevBtn.disabled = !prevSid;
    prevBtn.title = prevSid ? ('이전 세션 (과거): ' + prevSid) : '더 이전 세션 없음';

    let nextSid = (info && info.successor_session_id) || '';
    if (!nextSid) {
      nextSid = await resolveScrollforwardFallback(id, updatedAt, new Set([id]));
    }
    if (nextSid && nextSid <= id) nextSid = '';
    sessionNavNextSid = nextSid;
    nextBtn.disabled = !nextSid;
    nextBtn.title = nextSid ? ('다음 세션 (미래): ' + nextSid) : '최신 세션 (더 이후 세션 없음)';

    if (latestBtn) {
      latestBtn.hidden = !viewingPastSession();
      if (nextSid) latestBtn.title = '최신 세션으로 점프';
    }
    if (pastBadge) {
      pastBadge.style.display = viewingPastSession() ? 'inline-flex' : 'none';
    }
    updateScrollBottomButton();
  } catch (_) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    if (latestBtn) latestBtn.hidden = true;
    if (pastBadge) pastBadge.style.display = 'none';
    updateScrollBottomButton();
  }
}

// ---- latest-conversation jump ----
function isLiveSid(sid) {
  return /^\d{8}-\d{6}-/.test(String(sid || ''));
}

function viewingPastSession() {
  if (archiveBrowse && liveSessionId && liveSessionId !== sessionId) return true;
  return Boolean(sessionNavNextSid) && sessionNavNextSid > (sessionId || '');
}

async function resolveLatestSessionId() {
  const ids = [];
  try {
    const list = await api('/api/sessions');
    for (const s of (list.sessions || [])) {
      if (s && isLiveSid(s.id)) ids.push(s.id);
    }
  } catch (_) {}
  try {
    const act = await api('/api/sessions/active');
    if (act && isLiveSid(act.id)) ids.push(act.id);
  } catch (_) {}
  if (liveSessionId && isLiveSid(liveSessionId)) ids.push(liveSessionId);
  if (sessionNavNextSid && isLiveSid(sessionNavNextSid)) ids.push(sessionNavNextSid);
  let best = '';
  for (const id of ids) {
    if (!best || id > best) best = id;
  }
  if (!best) return sessionId || '';
  let id = best;
  const seen = new Set([id]);
  for (let hops = 0; hops < 40; hops++) {
    let info;
    try { info = await api('/api/sessions/' + encodeURIComponent(id)); }
    catch (_) { return id; }
    const next = (info && info.successor_session_id) || '';
    if (!next || seen.has(next) || !isLiveSid(next)) return id;
    seen.add(next);
    id = next;
  }
  return id;
}

function pinChatToBottom() {
  historyLoadHoldUntil = Date.now() + 600;
  if (!logEl) {
    updateScrollBottomButton(true);
    return;
  }
  if (typeof logEl.scrollTo === 'function') {
    logEl.scrollTo({ top: logEl.scrollHeight, behavior: 'auto' });
  } else {
    logEl.scrollTop = logEl.scrollHeight;
  }
  updateScrollBottomButton(true);
}

async function goToLatestConversation() {
  const latestId = await resolveLatestSessionId();
  if (latestId) liveSessionId = latestId;
  archiveBrowse = false;
  if (latestId && latestId !== sessionId) {
    await openSession(latestId);
    pinChatToBottom();
    return 'jump';
  }
  pinChatToBottom();
  return 'scroll';
}

async function followLiveIfNeeded() {
  if (archiveBrowse) return false;
  const latestId = await resolveLatestSessionId();
  if (latestId) liveSessionId = latestId;
  if (latestId && latestId !== sessionId) {
    await openSession(latestId);
    return true;
  }
  return false;
}
// ---- end latest-conversation jump ----


if (logEl) {
  logEl.addEventListener('scroll', () => {
    if (currentTab === 'chat' && Date.now() >= historyLoadHoldUntil) {
      if (logEl.scrollTop < 120 && logEl.scrollHeight > logEl.clientHeight + 20) {
        loadOlderHistory();
      }
      const distance = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
      if (distance < 120 && logEl.scrollHeight > logEl.clientHeight + 40 && !scrollforwardExhausted && !scrollforwardLoading && scrollforwardSid) {
        loadNewerHistory();
      }
    }
    updateScrollBottomButton();
  });

  logEl.addEventListener('wheel', (e) => {
    if (currentTab === 'chat' && Date.now() >= historyLoadHoldUntil && e.deltaY > 0 && !scrollforwardExhausted && !scrollforwardLoading && scrollforwardSid) {
      const distance = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
      if (distance < 30) {
        loadNewerHistory();
      }
    }
  }, { passive: true });
}

async function createSession() {
  const prevSessionId = sessionId; // "완전 새 세션" has no real predecessor_session_id link
  // (intentional -- no handoff summary should leak into agy's context), but
  // 실장님 still wants to be able to scroll up into whatever was open right
  // before it. Point scrollback at that browser-previous session directly;
  // it'll keep walking that session's own real predecessor chain from there.
  const model = modelEl.value;
  const provider = providerEl ? providerEl.value : 'agy';
  const data = await api('/api/sessions', {method:'POST', body: JSON.stringify({model, provider})});
  const label = (data.session.provider && data.session.provider !== 'agy')
    ? data.session.provider + (data.session.model ? ':' + data.session.model : '')
    : data.session.model;
  liveSessionId = data.session.id;
  archiveBrowse = false;
  enterSession(data.session.id, {
    scrollback: prevSessionId,
    greeting: '다시 왔다냥! ' + IDENTITY.user_title + ', 뭐부터 할까? ฅ',
    metaLabel: label,
    busy: false,
    activityAfter: '새 세션 ' + data.session.id,
  });
  applySessionProvider(data.session);
}

async function continueSession() {
  if (!sessionId) {
    await createSession();
    return;
  }
  const oldId = sessionId;
  setBusy(true);
  setProgress('이전 대화 핵심 요약 및 인계 준비 중…');
  try {
    const model = modelEl.value;
    const res = await api('/api/sessions/' + encodeURIComponent(oldId) + '/continue', {
      method: 'POST',
      body: JSON.stringify({ model })
    });
    if (res && res.ok && res.session) {
      const nid = res.session.id;
      const note = res.summary
        ? '\n\n> **[인계된 핵심 맥락]**\n> ' + res.summary.replace(/\n/g, '\n> ')
        : '';
      liveSessionId = nid;
      archiveBrowse = false;
      enterSession(nid, {
        scrollback: 'self',
        greeting: '이전 대화의 핵심 맥락을 인계받아 새 세션을 열었다냥! ฅ' + note + '\n\n무엇부터 이어서 진행할까?',
        metaLabel: res.session.model || '',
        activityAfter: '이전 세션(' + oldId + ') 맥락 인계 → 새 세션(' + nid + ')',
      });
      applySessionProvider(res.session);
    }
  } catch (e) {
    addActivity('세션 이어하기 오류: ' + (e.message || e));
    await alertModal('세션 이어하기 실패: ' + (e.message || e));
  } finally {
    setBusy(false);
    setProgress('');
  }
}

async function ensureSession() {
  const sp = new URLSearchParams(location.search);
  const urlSid = sp.get('session');
  if (urlSid) {
    try {
      try { liveSessionId = await resolveLatestSessionId(); } catch (_) {}
      await openSession(urlSid);
      return;
    } catch (_) {}
  }
  try {
    const latestId = await resolveLatestSessionId();
    if (latestId) {
      liveSessionId = latestId;
      archiveBrowse = false;
      await openSession(latestId);
      return;
    }
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
  await createSession();
}

async function send() {
  const text = inputEl.value.trim();
  if (!text) return;

  if (text === '/clear') {
    inputEl.value = '';
    inputEl.style.height = '';
    detachSessionBanner();
    logEl.innerHTML = '';
    activityEvents = [];
    if (activityEl) activityEl.innerHTML = '';
    addChat('assistant', '대화 로그를 깨끗하게 비웠습니다냥 🐾', true, false, false, false, null, null, true);
    syncSessionActions();
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
    const hadUser = currentSessionHasUser;
    addChat('user', '/status', false);
    try {
      const st = await api('/api/host/status');
      addChat('assistant', `호스트 상태: **${st.ok ? '정상 가동 중 ⚡' : '이상 감지'}** · 세션 ID: \`${sessionId || '없음'}\` · 모델: \`${modelEl.value}\``, true, false, false, false, null, null, true);
    } catch (e) {
      addChat('assistant', '상태 확인 실패: ' + e.message, true, false, false, false, null, null, true);
    }
    currentSessionHasUser = hadUser;
    return;
  }
  const ticketCmd = parseTicketCommand(text);
  if (ticketCmd) {
    // The operator's own decision, made in the page: never sent to the agent.
    inputEl.value = '';
    inputEl.style.height = '';
    updateSendButton();
    const hadUser = currentSessionHasUser;
    addChat('user', text, false);
    try {
      if (ticketCmd.action === 'go') {
        const go = await goTicket(ticketCmd);
        if (go.message) addChat('assistant', go.message, true, false, false, false, null, null, true);
        loadTickets();
        inputEl.value = go.prompt;
        return send();   // an ordinary message to the agent from here on
      }
      addChat('assistant', await decideTicket(ticketCmd), true, false, false, false, null, null, true);
    } catch (e) {
      addChat('assistant', '티켓 결정 실패: ' + obsErrorText(e), true, false, false, false, null, null, true);
    }
    currentSessionHasUser = hadUser;
    loadTickets();
    return;
  }
  if (text === '/help') {
    // Purely client-side, no agy round-trip -- there was previously no
    // help/onboarding affordance anywhere in the app (impeccable critique
    // P3, 2026-09-17).
    inputEl.value = '';
    inputEl.style.height = '';
    updateSendButton();
    const hadUser = currentSessionHasUser;
    addChat('user', '/help', false);
    addChat('assistant',
      IDENTITY.title + ' 사용법 요약이다냥 ✦\n\n' +
      '**탭** (숫자는 `Alt+숫자`로 바로 전환)\n' +
      '- `Alt+1` 💬 대화 · `Alt+2` 📁 아티팩트 · `Alt+3` 📜 로그 · `Alt+4` ⚙ 상태 · `Alt+5` 🗂 세션\n\n' +
      '**어디서나 되는 것**\n' +
      '- `/` 키: 바로 컴포저로 이동해서 슬래시 메뉴 열기\n' +
      '- 헤더의 `⋯` 버튼: 테마 색상 선택, ⚡ 소생(호스트 재기동)\n' +
      '- 대화가 한 턴 이상이면 채팅창 아래에 새 대화·이어가기 버튼이 뜬다냥. 세션이 길어지면 거기서 바로 갈아탈 수 있다냥\n' +
      '- `세션` 탭에서도 새 세션을 열 수 있다냥\n\n' +
      '**슬래시 명령어**\n' +
      '- `/btw <질문>` 작업 중 샛길 질문 · `/continue` 맥락 요약 인계 새 세션 · `/new` 완전 새 세션\n' +
      '- `/status` 상태 확인 · `/clear` 화면 비우기 · `/compact` 대화 압축 · `/defib` 호스트 소생\n' +
      '- 이 외에 `/`만 눌러도 뜨는 메뉴에 날씨·뉴스·주식 등 스킬 단축어들도 있다냥\n\n' +
      '더 궁금한 거 있으면 그냥 물어봐도 된다냥!',
      true, false, false, false, null, null, true);
    currentSessionHasUser = hadUser;
    return;
  }

  if (!sessionId) await ensureSession();

  const isAutoBtw = isBusy && isInquiry(text);
  const isExplicitBtw = text.startsWith('/btw ') || text.startsWith('/btw\n') || text === '/btw';
  const isBtw = isAutoBtw || isExplicitBtw;

  sendBtn.disabled = true;

  // Tag this send so the shared session's user_ack broadcast (which every
  // window/tab on this session receives) knows this window already rendered
  // it, instead of skipping it in every OTHER window too.
  const clientMid = _newClientMid();
  myPendingMids.add(clientMid);
  // ids are random and never reused, so a stale one is harmless -- just keep the set bounded
  if (myPendingMids.size > 50) myPendingMids.delete(myPendingMids.values().next().value);

  if (isBtw) {
    addBtwQuestionBubble(text);
    addActivity('샛길 질문(/btw) 감지 · 처리 중…');
  } else if (isBusy) {
    // Steer: show the message at once, but leave the streaming answer alone -- the agent keeps
    // working until the current step ends. The server's 'interrupted' event (which comes when the
    // turn is actually cut, immediately for providers that cannot steer) closes the bubble.
    addChat('user', text, false, false, false);
    addActivity('🧭 새 지시 전달: ' + shortToolLine(text));
    setBusy(true);
    setProgress('새 지시 접수 · 지금 단계가 끝나면 반영해요…');
  } else {
    addChat('user', text, false, false, false);
    assistantNode = null; assistantBuf = '';
    setBusy(true);
    setProgress('요청 보냄 · 대기 중…');
  }

  inputEl.value = '';
  inputEl.style.height = '';
  autoResizeInput();
  updateSendButton();

  try {
    const payload = {
      text,
      client_mid: clientMid
    };
    Object.assign(payload, providerFieldsForSend(
      providerEl ? providerEl.value : '',
      modelEl ? modelEl.value : '',
      lastServerProvider,
      lastServerModel
    ));
    const ctx = getClientContext();
    if (ctx) payload.client_context = ctx;
    const msgRes = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/message', {
      method:'POST',
      body: JSON.stringify(payload)
    });
    if (msgRes && msgRes.rotated && msgRes.session && msgRes.session.id) {
      const nid = msgRes.session.id;
      addActivity('서버가 긴 세션을 새 채팅으로 인계 전환: ' + nid);
      // Seamless in-flow handoff (실장님: "세션 간 경계가 느껴지지 않게") --
      // the message this branch is handling is already visible on screen
      // (send()'s own optimistic addChat at the top of this function, well
      // before this POST resolved), so don't clear the log or re-add it --
      // that clear-then-refill was the actual bug (실장님: "내가 말을
      // 하면 바로 새 세션으로 넘어가면서 내가 한 말을 또 해야 되는 상황이
      // 생겨"), and even fixed, a wipe-and-rebuild still reads as a visible
      // seam. The handoff summary still reaches the model (server injects
      // it into the new session's first turn either way); it doesn't need
      // to be re-shown here to feel present. syncedTs anchors the new
      // session's resync point at the message already on screen, so its
      // own SSE connection doesn't duplicate it.
      const hist = (msgRes.session.history || []);
      const syncedTs = hist.length ? (hist[hist.length - 1].ts || 0) : 0;
      enterSession(nid, {
        preserveLog: true,
        scrollback: 'self',
        syncedTs,
        metaLabel: msgRes.session.model || '',
        busy: true,
      });
      applySessionProvider(msgRes.session);
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

// Multi-Provider plan: [{id, available, models}], fetched once at boot.
// available:false providers stay in the dropdown (so the option isn't a
// silent mystery) but disabled, rather than omitted -- matches the plan's
// "표시하되 disabled" choice.
// Multi-Provider plan: [{id, name, role, theme, icon, available, models}], fetched once at boot.
// available:false providers stay in the tray with grayscale + disabled
let providerCatalog = [];
const brandAvatarEl = document.getElementById('brandAvatar');
const providerTrayEl = document.getElementById('providerTray');
const brandNameEl = document.getElementById('brandName');
const brandRoleEl = document.getElementById('brandRole');
const brandProviderEl = document.getElementById('brandProvider');
// 이름·호칭은 코드가 아니라 지침 파일(AGENTS.md `title`, PERSONA.md `persona`/`user_title`)에서 온다.
// 서버가 <!--IDENTITY--> 자리에 window.__IDENTITY__를 심어 준다 (없으면 /api/identity로 폴백).
const IDENTITY = Object.assign({ title: 'Assistant', persona: '', user_title: '사용자', voice: '', name: 'Assistant' }, window.__IDENTITY__ || {});
function escapeRegExp(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function applyIdentity() {
  if (brandNameEl) brandNameEl.textContent = IDENTITY.title;          // 상단 제목 = 타이틀(직책)
  if (brandAvatarEl) brandAvatarEl.alt = IDENTITY.name;                // 아바타 = 페르소나(없으면 타이틀)
}
applyIdentity();
if (!window.__IDENTITY__) {  // 정적으로 서빙돼 서버가 심어 주지 못한 경우
  fetch(BASE_PATH + '/api/identity').then(r => r.json()).then(j => { Object.assign(IDENTITY, j); applyIdentity(); }).catch(() => {});
}
const PROVIDER_CREDIT = {
  agy: 'Antigravity',
  claude: 'Claude',
  grok: 'Grok',
  codex: 'Codex',
  omniroute: 'OmniRoute',
  openrouter: 'OpenRouter',
};

// 사용 불가(Free 만료/한도 소진) 제공자 및 비활성화 사유
const PROVIDER_DISABLED_REASONS = {
  claude: 'Free 계정 전환으로 사용 불가 (Pro 만료)',
  codex: '사용량 한도 소진으로 사용 불가 (Plus 필요)',
};
function providerDisabledReason(pid) {
  return PROVIDER_DISABLED_REASONS[pid] || null;
}

function themeForProvider(p) {
  if (p && p.id === 'grok') return 'mono';
  if (p && p.id === 'agy') return 'spark';
  if (p && p.id === 'openrouter') return 'lime';
  return (p && p.theme) || 'lime';
}

const PORTRAIT_CACHE = 'v=12';
function portraitUrl(p) {
  const raw = (p && (p.icon || `/chat/persona/providers/${p.id}.webp`)) || '/chat/persona/providers/agy.webp';
  return String(raw).split('?')[0] + '?' + PORTRAIT_CACHE;
}

function providerCreditLabel(p) {
  if (!p) return 'Antigravity';
  if (PROVIDER_CREDIT[p.id]) return PROVIDER_CREDIT[p.id];
  const n = String(p.name || p.id);
  const names = [IDENTITY.persona, IDENTITY.title].filter(Boolean).map(escapeRegExp);
  const stripped = names.length
    ? n.replace(new RegExp('(?:' + names.join('|') + ')\\s*(?:\\(([^)]+)\\))?', 'g'), (_, inner) => inner || '').trim()
    : n.trim();
  return stripped || p.id;
}

const STAGE_BG_CACHE = 'v=1';
function updateStageBackground(providerId) {
  const pid = providerId || 'agy';
  const candidate = `/chat/persona/providers/bg/${pid}.webp?${STAGE_BG_CACHE}`;
  const fallback = `/chat/persona/bg-studio.webp?v=1`;
  const img = new Image();
  img.onload = () => {
    document.documentElement.style.setProperty('--stage-bg-image', `url('${candidate}')`);
  };
  img.onerror = () => {
    document.documentElement.style.setProperty('--stage-bg-image', `url('${fallback}')`);
  };
  img.src = candidate;
}

function updateBrandAvatar(providerId) {
  const p = providerCatalog.find(item => item.id === providerId) || {
    id: 'agy',
    name: 'Antigravity',
    role: 'Google Antigravity',
    theme: 'lime',
    icon: '/chat/persona/providers/agy.webp'
  };
  const credit = providerCreditLabel(p);
  if (brandAvatarEl) {
    brandAvatarEl.src = portraitUrl(p);
    brandAvatarEl.alt = IDENTITY.name;
    brandAvatarEl.title = `${IDENTITY.name} · ${credit} · 제공자 변경 (클릭)`;
  }
  if (brandNameEl) {
    brandNameEl.textContent = IDENTITY.title;
  }
  if (brandProviderEl) {
    brandProviderEl.textContent = credit;
  } else if (brandRoleEl) {
    brandRoleEl.textContent = credit;
  }
  if (brandRoleEl) {
    brandRoleEl.title = credit;
    brandRoleEl.setAttribute('aria-label', `제공자 ${credit}`);
  }
  updateStageBackground(p.id);
}

function renderProviderTray() {
  if (!providerTrayEl) return;
  providerTrayEl.innerHTML = '';
  const currentPid = providerEl ? providerEl.value : (localStorage.getItem('chatbot.provider') || 'agy');

  providerCatalog.forEach(p => {
    const btn = document.createElement('button');
    btn.type = 'button';
    const disReason = providerDisabledReason(p.id);
    const isUsable = p.available && !disReason;
    btn.className = 'provider-portrait-btn' + (p.id === currentPid ? ' active' : '') + (isUsable ? '' : ' disabled');
    btn.disabled = !isUsable;
    btn.setAttribute('data-provider-id', p.id);
    const credit = providerCreditLabel(p);
    btn.title = credit + (disReason ? ' · ' + disReason : (p.available ? '' : ' (미설치)'));

    const img = document.createElement('img');
    img.src = portraitUrl(p);
    img.alt = credit;
    img.onerror = () => { img.src = '/chat/persona/face-icon.png'; };

    const tip = document.createElement('span');
    tip.className = 'provider-tooltip';
    tip.textContent = credit;

    btn.appendChild(img);
    btn.appendChild(tip);

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!p.available || providerDisabledReason(p.id)) return;
      selectProvider(p.id);
      providerTrayEl.hidden = true;
    });

    providerTrayEl.appendChild(btn);
  });
}

window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || d.type !== 'chatbot-select-provider' || !d.provider) return;
  try {
    if (new URL(e.origin).hostname !== location.hostname) return;
  } catch (_) {
    return;
  }
  selectProvider(d.provider);
});

function providerFieldsForSend(uiProvider, uiModel, serverProvider, serverModel) {
  const out = {};
  if (uiProvider && uiProvider !== serverProvider) out.provider = uiProvider;
  if (uiModel && uiModel !== serverModel) out.model = uiModel;
  return out;
}

function applySessionProvider(info) {
  if (!info || !info.provider) return false;
  if (localProviderEdit) return false;
  const pid = info.provider;
  const mid = info.model || '';
  const curPid = providerEl ? providerEl.value : (localStorage.getItem('chatbot.provider') || '');
  const curMid = modelEl ? modelEl.value : '';
  const providerChanged = pid !== curPid;
  const modelChanged = Boolean(mid) && mid !== curMid;
  lastServerProvider = pid;
  lastServerModel = mid || curMid;
  if (!providerChanged && !modelChanged) return false;
  if (providerEl) providerEl.value = pid;
  localStorage.setItem('chatbot.provider', pid);
  if (providerChanged) {
    updateBrandAvatar(pid);
    followChatProvider();
    populateModelsForProvider(pid, mid || undefined);
    renderProviderTray();
    const p = providerCatalog.find(item => item.id === pid);
    if (p && typeof applyTheme === 'function') applyTheme(themeForProvider(p));
  } else if (modelChanged) {
    populateModelsForProvider(pid, mid);
  }
  if (mid) {
    localStorage.setItem('chatbot.model', mid);
    localStorage.setItem('sphereAgyModel', mid);
  }
  if (typeof syncModelUi === 'function') syncModelUi();
  return true;
}

async function persistSessionProvider(opts) {
  opts = opts || {};
  if (!sessionId) return;
  const pid = providerEl ? providerEl.value : '';
  const mid = modelEl ? modelEl.value : '';
  localProviderEdit++;
  try {
    await api(`/api/sessions/${encodeURIComponent(sessionId)}/provider`, {
      method: 'POST',
      body: JSON.stringify({ provider: pid, model: mid }),
    });
    lastServerProvider = pid;
    lastServerModel = mid;
    if (opts.activity) addActivity(opts.activity);
  } catch (_) {
  } finally {
    localProviderEdit = Math.max(0, localProviderEdit - 1);
  }
}

async function selectProvider(newProviderId) {
  const p = providerCatalog.find(item => item.id === newProviderId);
  if (!p || !p.available || providerDisabledReason(newProviderId)) return;

  if (providerEl) {
    providerEl.value = newProviderId;
  }
  localStorage.setItem('chatbot.provider', newProviderId);

  // Update theme keycolor to match provider
  if (typeof applyTheme === 'function') {
    applyTheme(themeForProvider(p));
  }

  // Update avatar & title
  updateBrandAvatar(newProviderId);
  followChatProvider();
  populateModelsForProvider(newProviderId);
  localStorage.setItem('chatbot.model', modelEl.value);
  localStorage.setItem('sphereAgyModel', modelEl.value);
  renderProviderTray();

  await persistSessionProvider({
    activity: '제공자 전환: ' + (p.name || newProviderId),
  });
}

function toggleProviderTray(force) {
  if (!providerTrayEl) return;
  const willShow = typeof force === 'boolean' ? force : providerTrayEl.hidden;
  if (willShow) renderProviderTray();
  providerTrayEl.hidden = !willShow;
  if (brandAvatarEl) {
    brandAvatarEl.setAttribute('aria-expanded', String(willShow));
  }
}

if (brandAvatarEl) {
  brandAvatarEl.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleProviderTray();
  });
  brandAvatarEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      toggleProviderTray();
    }
  });
}

document.addEventListener('click', (e) => {
  if (providerTrayEl && !providerTrayEl.hidden) {
    if (!providerTrayEl.contains(e.target) && e.target !== brandAvatarEl) {
      toggleProviderTray(false);
    }
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && providerTrayEl && !providerTrayEl.hidden) {
    toggleProviderTray(false);
  }
});

function populateModelsForProvider(providerId, preferredModel) {
  modelEl.innerHTML = '';
  const entry = providerCatalog.find(p => p.id === providerId);
  const models = (entry && entry.models) || [];
  models.forEach(m => {
    const o = document.createElement('option');
    o.value = m; o.textContent = m;
    modelEl.appendChild(o);
  });
  if (!models.length) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = '(기본값)';
    modelEl.appendChild(o);
  }
  if (preferredModel && models.includes(preferredModel)) {
    modelEl.value = preferredModel;
  }
  if (typeof syncModelUi === 'function') syncModelUi();
}

async function boot() {
  try {
    const res = await api('/api/providers');
    providerCatalog = res.providers || [];
    providerCatalog.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id;
      const disReason = providerDisabledReason(p.id);
      o.textContent = (p.name || p.id) + (disReason ? ' (사용 불가)' : '');
      o.disabled = !p.available || Boolean(disReason);
      if (providerEl) providerEl.appendChild(o);
    });
    let savedProvider = localStorage.getItem('chatbot.provider') || res.default || 'agy';
    if (providerDisabledReason(savedProvider)) {
      savedProvider = 'agy';
      localStorage.setItem('chatbot.provider', 'agy');
    }
    if (providerEl && Array.from(providerEl.options).some(o => o.value === savedProvider)) {
      providerEl.value = savedProvider;
    }
    const currentEntry = providerCatalog.find(p => p.id === savedProvider);
    if (currentEntry && typeof applyTheme === 'function') {
      applyTheme(themeForProvider(currentEntry));
    }
    updateBrandAvatar(savedProvider);
    renderProviderTray();

    const savedModel = localStorage.getItem('sphereAgyModel') || localStorage.getItem('chatbot.model');
    populateModelsForProvider(savedProvider, savedModel);

    if (providerEl) {
      providerEl.onchange = () => {
        selectProvider(providerEl.value);
      };
    }
    modelEl.onchange = () => {
      localStorage.setItem('chatbot.model', modelEl.value);
      localStorage.setItem('sphereAgyModel', modelEl.value);
      if (typeof syncModelUi === 'function') syncModelUi();
      persistSessionProvider();
    };
  } catch (_) {}
  await ensureSession();
  // Hub FAB passes ?provider= because openSession() otherwise overwrites
  // the tray pick with the already-active session's provider.
  if (bootProviderIntent) {
    const cur = providerEl ? providerEl.value : '';
    if (bootProviderIntent !== cur) {
      await selectProvider(bootProviderIntent);
    }
  }
}

if (tabChat) tabChat.addEventListener('click', () => switchTab('chat'));
if (tabArtifacts) tabArtifacts.addEventListener('click', () => switchTab('artifacts'));
if (tabActivity) tabActivity.addEventListener('click', () => switchTab('activity'));
if (tabStatus) tabStatus.addEventListener('click', () => switchTab('status'));
if (tabSessions) tabSessions.addEventListener('click', () => switchTab('sessions'));

const sessionNavPrev = document.getElementById('sessionNavPrev');
const sessionNavNext = document.getElementById('sessionNavNext');
const sessionNavLatest = document.getElementById('sessionNavLatest');

if (sessionNavPrev) {
  sessionNavPrev.addEventListener('click', () => {
    if (sessionNavPrevSid) openSession(sessionNavPrevSid, 0, null, true);
  });
}
if (sessionNavNext) {
  sessionNavNext.addEventListener('click', () => {
    if (sessionNavNextSid) openSession(sessionNavNextSid, 0, null, true);
  });
}
if (sessionNavLatest) {
  sessionNavLatest.addEventListener('click', () => { goToLatestConversation(); });
}

window.addEventListener('keydown', (e) => {
  if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;
    if (e.key === 'ArrowLeft' && sessionNavPrevSid && sessionNavPrev && !sessionNavPrev.disabled) {
      e.preventDefault();
      openSession(sessionNavPrevSid, 0, null, true);
    } else if (e.key === 'ArrowRight' && sessionNavNextSid && sessionNavNext && !sessionNavNext.disabled) {
      e.preventDefault();
      openSession(sessionNavNextSid, 0, null, true);
    }
  }
});

if (sessionsRefreshBtn) sessionsRefreshBtn.addEventListener('click', () => fetchSessionsList());
if (statusRefreshBtn) statusRefreshBtn.addEventListener('click', () => { fetchSelfStatus(); fetchAccounts(); });
// Waiting tickets are shown above the composer, so they are looked up at start and now and then, not only on the status tab.
loadTickets();
setInterval(loadTickets, 60000);
if (usageRefreshBtn) usageRefreshBtn.addEventListener('click', () => fetchUsage(true));
if (mcpAddBtn) mcpAddBtn.addEventListener('click', async () => {
  const name = (mcpNameInput && mcpNameInput.value || '').trim();
  const url = (mcpUrlInput && mcpUrlInput.value || '').trim();
  if (!name || !url) { await alertModal('이름과 serverUrl을 모두 입력하세요.'); return; }
  mcpAddBtn.disabled = true;
  try {
    await api('/api/mcp', { method: 'POST', body: JSON.stringify({ name, serverUrl: url }) });
    addActivity('MCP ' + name + ' 추가됨 (다음 새 세션부터 반영)');
    if (mcpNameInput) mcpNameInput.value = '';
    if (mcpUrlInput) mcpUrlInput.value = '';
    fetchSelfStatus();
  } catch (e) {
    await alertModal('추가 실패: ' + e.message);
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



// Tab-switch + jump-to-composer shortcuts -- previously Enter-to-send and
// Escape were the only keyboard affordances anywhere in the app, thin for a
// tool built for one person's daily use (impeccable critique P1, 2026-09-17).
// Alt+N, not Ctrl/Cmd+N: the latter is already the browser's own "switch to
// tab N" shortcut and the page would never even see that keydown.
const TAB_SHORTCUTS = { '1': 'chat', '2': 'artifacts', '3': 'activity', '4': 'status', '5': 'sessions' };
function isEditableTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}
window.addEventListener('keydown', (e) => {
  if (e.altKey && !e.ctrlKey && !e.metaKey && TAB_SHORTCUTS[e.key]) {
    e.preventDefault();
    switchTab(TAB_SHORTCUTS[e.key]);
    return;
  }
  // '/' from outside any editable field jumps straight to the composer and
  // opens the slash menu, matching how '/' already behaves once you're
  // already typing in it.
  if (e.key === '/' && !e.altKey && !e.ctrlKey && !e.metaKey && !isEditableTarget(e.target)) {
    e.preventDefault();
    switchTab('chat');
    inputEl.focus();
    if (!inputEl.value) {
      inputEl.value = '/';
      inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    }
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
      addChat('assistant', '작업을 중지했습니다냥.', true, false, false, false, null, null, true);
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
  if (!(await confirmModal('전기충격(심폐소생)을 실행할까요?\n호스트가 재기동되며 몇 초 연결이 끊깁니다.', { confirmLabel: '실행', danger: false }))) return;
  setProgress('⚡ 전기충격 · 호스트 소생 중…', true);
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
      setProgress('소생 시간 초과 · 수동 새로고침 해보세요', true);
      addActivity('소생 실패/시간초과');
      return;
    }
    setProgress('소생 완료 · 세션 재연결…', true);
    await ensureSession();
    setProgress('⚡ 소생 완료', true);
    addActivity('⚡ 심폐소생 완료');
  } finally {
    if (btn) btn.disabled = false;
  }
}

const defibBtn = document.getElementById('defibBtn');
if (defibBtn) defibBtn.addEventListener('click', () => defibrillateHost().catch(e => addActivity(String(e.message || e))));


if (sessionBannerContinue) {
  sessionBannerContinue.addEventListener('click', () => continueSession().catch(e => addActivity(String(e.message || e))));
}
if (sessionBannerBtn) {
  sessionBannerBtn.addEventListener('click', () => createSession().catch(e => addActivity(String(e.message || e))));
}
if (sessionBannerDismiss) {
  sessionBannerDismiss.addEventListener('click', () => hideSessionHeavyBanner());
}
const sessionsNewBtn = document.getElementById('sessionsNewBtn');
const sessionsContinueBtn = document.getElementById('sessionsContinueBtn');
if (sessionsNewBtn) {
  sessionsNewBtn.addEventListener('click', () => {
    createSession().then(() => switchTab('chat')).catch(e => addActivity(String(e.message || e)));
  });
}
if (sessionsContinueBtn) {
  sessionsContinueBtn.addEventListener('click', () => {
    continueSession().then(() => switchTab('chat')).catch(e => addActivity(String(e.message || e)));
  });
}



function autoResizeInput() {
  if (!inputEl) return;
  // Min/max come from the stylesheet (#input, the <=640px block, the keyboard/short-screen block), so
  // this can't drift from it again. It used to keep its own 38/42 and 90/120: the input was 38px
  // while the CSS said 36 (32 with the keyboard up) and the buttons next to it were 44 (32), and it
  // fell back to the CSS value after a slash command cleared the inline height. (실장님: 하단 위젯들
  // 높이가 상황에 따라 조금씩 다름.)
  const cs = window.getComputedStyle(inputEl);
  const minH = parseFloat(cs.minHeight) || 42;
  const maxH = parseFloat(cs.maxHeight) || 120;   // 'none' -> NaN -> fallback

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

// 뷰포트 높이 기반 키보드 추적.
// _prevKeyboardOpen 상태 머신 대신 viewport height 변화량으로 판단하므로
// 포커스를 유지한 채 키보드만 올/내려도 올바르게 동작한다.
let _composerMode = '';         // narrow/wide + keyboard-open of the last updateViewport (input height follows the CSS for it)
let _prevVvHeight = 0;          // 직전 visualViewport 높이
let _savedScrollTop = null;     // 키보드 열릴 때 보존한 scrollTop
let _wasNearBottomBeforeKeyboard = true; // 키보드 열리기 직전의 nearBottom 상태

// Is the on-screen keyboard (probably) up? A short viewport says so on any device. "The input has focus"
// only says so when there IS an on-screen keyboard -- i.e. a touch device. On a desktop FAB (an iframe
// 420px wide) it used to count too: clicking the text box shrank the row and hid the header, tabs and
// model button, with a mouse and a physical keyboard. (실장님: FAB 텍스트창 높이가 달라 / 포커스하면 레이아웃이 흔들려.)
function keyboardOpenState(narrow, short, focused, touch) {
  return Boolean(narrow && (short || (focused && touch)));
}

function updateViewport() {
  const vv = window.visualViewport;
  const h = vv ? Math.round(vv.height) : window.innerHeight;
  document.documentElement.style.setProperty('--app-height', `${h}px`);
  if (window.scrollY !== 0) window.scrollTo(0, 0);

  // 모바일 가상키보드 상태 감지 (좁은 너비에서 높이가 줄어들었거나 input에 포커스된 경우)
  const isNarrow = window.innerWidth <= 640;
  const isShort = h < 520;
  const isInputFocused = document.activeElement === inputEl;
  const isTouch = Boolean(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  const isKeyboardOpen = keyboardOpenState(isNarrow, isShort, isInputFocused, isTouch);
  document.body.classList.toggle('keyboard-open', Boolean(isKeyboardOpen));
  // the composer's CSS heights depend on both -- re-measure the input when either flips
  const composerMode = (isNarrow ? 'n' : 'w') + (isKeyboardOpen ? 'k' : '-');
  if (composerMode !== _composerMode) {
    _composerMode = composerMode;
    autoResizeInput();
  }

  const liveSlashMenu = document.getElementById('slashMenu');
  if (liveSlashMenu && !liveSlashMenu.hidden) positionSlashMenu();

  if (logEl && currentTab === 'chat' && isNarrow && _prevVvHeight > 0) {
    const delta = h - _prevVvHeight; // 양수 = viewport 커짐(키보드 닫힘), 음수 = 작아짐(키보드 열림)

    if (delta < -60) {
      // 키보드 열림(또는 내렸다가 다시 올라옴): 보던 위치를 저장하고,
      // 바닥 근처였으면 새 높이에 맞춰 snap.
      _savedScrollTop = logEl.scrollTop;
      if (_wasNearBottomBeforeKeyboard) {
        logEl.scrollTop = logEl.scrollHeight;
      }
      // 읽던 중이었으면 저장한 scrollTop 그대로 → 변경 없음
    } else if (delta > 60 && _savedScrollTop !== null) {
      // 키보드 닫힘: viewport 높이가 복원됨.
      // 바닥 근처였으면 snap, 아니었으면 저장된 위치로 복원.
      if (_wasNearBottomBeforeKeyboard) {
        logEl.scrollTop = logEl.scrollHeight;
      } else {
        logEl.scrollTop = _savedScrollTop;
      }
      _savedScrollTop = null;
      // 버튼 가시성: clientHeight 복원 직후 isUserNearBottom()은 부정확하므로
      // 키보드 열리기 전 상태(_wasNearBottomBeforeKeyboard)로 직접 결정
      updateScrollBottomButton(_wasNearBottomBeforeKeyboard);
      _prevVvHeight = h;
      return;
    }
    updateScrollBottomButton();
  }

  _prevVvHeight = h;
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



inputEl.addEventListener('input', () => {
  updateSendButton();
  autoResizeInput();
});
inputEl.addEventListener('focus', () => {
  // 키보드가 열리기 직전(clientHeight가 줄기 전)의 nearBottom 상태를 기록.
  // _savedScrollTop이 null일 때(완전히 닫힌 상태)만 갱신 —
  // 키보드를 내렸다 다시 올리는 중간 상태에서 덮어쓰지 않기 위함.
  if (_savedScrollTop === null) {
    _wasNearBottomBeforeKeyboard = isUserNearBottom();
  }
  setTimeout(updateViewport, 120);
});
inputEl.addEventListener('blur', () => {
  setTimeout(updateViewport, 120);
});
inputEl.addEventListener('keydown', (e) => {
  if (handleSlashKeydown(e)) return;
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

autoResizeInput();
boot().then(() => updateViewport());

