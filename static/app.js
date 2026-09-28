// QUOTA_ERR_DEDUP_v1
// QUOTA_SILENT_FIX_v1
// PROVIDER_SWAP_DEFER_v1
// Dynamically detect base path from current URL pathname (stripping trailing filename like index.html or trailing slash)
const BASE_PATH = (() => {
  const p = window.location.pathname;
  // Remove filename if present (e.g. /chat/index.html -> /chat)
  const dir = p.replace(/\/[^\/]*\.[^\/]+$/, '');
  // Strip trailing slash if present (e.g. /chat/ -> /chat, / -> '')
  return dir.replace(/\/+$/, '') || '';
})();
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
const privateBtn = document.getElementById('privateBtn');
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
// SESSION_SPLIT_v1: the open session's mode. Work and private talk are separate sessions; "latest", scrollback
// and the live-follow logic stay inside the open mode.
let sessionMode = 'work';
// CHARACTER_PICKER_v1: whose sessions are open ("" = the chatbot itself, else a character id)
let sessionCharacter = '';
// TEAM_ROLES_v2: every session names its character; '' only until the first one opens, and means the default
if (privateBtn) privateBtn.addEventListener('click', togglePrivateMode);
let historyLoadHoldUntil = 0;

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
      addActivity('기기 환경 및 위치 정보 동기화 켜짐', 'system');
    } else {
      cachedCoords = null;
      coordPromise = null;
      addActivity('기기 환경 및 위치 정보 동기화 꺼짐');
    }
  });
}
if (scrollToBottomBtn) {
  scrollToBottomBtn.addEventListener('click', () => { goToLatestConversation(); });
}
if (window.speechSynthesis) {
  ttsKoreanVoice = pickKoreanVoice();
  window.speechSynthesis.onvoiceschanged = () => { ttsKoreanVoice = pickKoreanVoice() || ttsKoreanVoice; };
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

// The new-session suggestion banner is permanently off (#197): it covered the
// chat mid-conversation. Weight data is still recorded; the banner never shows.
function syncSessionActions() {
  if (!sessionBanner) return;
  sessionBanner.hidden = true;
  detachSessionBanner();
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
const tabEvolution = document.getElementById('tabEvolution');
const evolutionPaneEl = document.getElementById('evolutionPane');
const tabTeam = document.getElementById('tabTeam');
const teamPaneEl = document.getElementById('teamPane');
const sessionsPaneEl = document.getElementById('sessionsPane');
const sessionsListEl = document.getElementById('sessionsList');
const sessionsRefreshBtn = document.getElementById('sessionsRefreshBtn');
const statusPaneEl = document.getElementById('statusPane');
const statusRefreshBtn = document.getElementById('statusRefreshBtn');

// Compact mode (?compact=1): this exact same page, embedded in a small
// iframe from the Hub FAB popup, instead of maintaining a second ~950-line
// FAB-only implementation that drifts out of sync with this one (operator:
// "본체의 compact한 버전이니까" -- share everything, design/layout only
// differs). Keeps 대화/아티팩트/로그/세션 (operator: "위에 공간이 많이 남았으니
// 로그도 노출해도 될 것 같네" / "아티팩트도" -- there's headroom for them
// after all), drops only 상태 (host-admin, not a casual-popup concern), the
// "← Hub" link (meaningless inside an iframe already sitting on
// the Hub page), and the defib button (host-repair action).
const isCompactMode = new URLSearchParams(location.search).get('compact') === '1';
if (isCompactMode) document.documentElement.classList.add('compact-mode');
const bootProviderIntent = new URLSearchParams(location.search).get('provider');
const bootCharacterIntent = new URLSearchParams(location.search).get('character');
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
const statusInstructionsEl = document.getElementById('statusInstructions');
const statusSkillsEl = document.getElementById('statusSkills');
const statusSkillLibHintEl = document.getElementById('statusSkillLibHint');
const statusMcpEl = document.getElementById('statusMcp');
const statusHooksEl = document.getElementById('statusHooks');
const statusObserverEl = document.getElementById('statusObserver');
const statusObsBoxEl = document.getElementById('statusObsBox');
const statusTicketBoxEl = document.getElementById('statusTicketBox');
const ticketBarEl = document.getElementById('ticketBar');
const choiceBarEl = document.getElementById('choiceBar');
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

// PROVIDER_NEUTRAL_v1: storage keys used to carry one provider's name. Move them once, then forget
// the old ones -- a browser that last ran the old page keeps its session and model.
(function migrateStorageKeys() {
  const moves = [['sphereAgySession', SESSION_KEY], ['sphereAgyHubSession', SESSION_KEY], ['sphereAgyModel', 'chatbot.model']];
  try {
    moves.forEach(([oldKey, newKey]) => {
      const v = localStorage.getItem(oldKey);
      if (v === null) return;
      if (!localStorage.getItem(newKey)) localStorage.setItem(newKey, v);
      localStorage.removeItem(oldKey);
    });
  } catch (_) { /* storage blocked: nothing to move */ }
})();
// The server's default provider (GET /api/providers); no provider is special in this page.
var defaultProviderId = '';
var sessionId = localStorage.getItem(SESSION_KEY) || '';
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

if (activityEl) {
  activityEl.addEventListener('scroll', () => {
    if (currentTab !== 'activity') return;
    if (activityEl.scrollTop < 120 && activityEl.scrollHeight > activityEl.clientHeight + 20) {
      loadMoreLog();
    }
  });
}
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
      actCopyBtn.textContent = '복사됨';
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

if (logEl) {
  logEl.addEventListener('scroll', () => {
    // scroll events arrive async: during a keyboard transition they are layout shifts, not the user
    if (typeof isProgrammaticScroll !== 'undefined' && !isProgrammaticScroll && !isKeyboardTransitioning()) {
      if (typeof isUserNearBottom === 'function') {
        isLogPinnedToBottom = isUserNearBottom();
      }
    }
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
// Touch devices pop the virtual keyboard on every inputEl.focus(); taps on chips,
// actions and skill buttons must not do that (MOBILE_KEYBOARD_FOCUS_v1).
function isTouchDevice() {
  return Boolean(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
}
// send() options for a tap that is not typing: keep the keyboard shut on touch.
function tapSendOpts() {
  return { keepFocus: !isTouchDevice() };
}
function sendAction(actionText) {
  if (!inputEl || typeof send !== 'function') return;
  inputEl.value = '/act ' + String(actionText || '').trim();
  send(tapSendOpts());
}
async function send(opts) {
  // a click handler passes an Event here -- only a plain { keepFocus } counts
  const keepFocus = !(opts && opts.keepFocus === false);
  const text = inputEl.value.trim();
  if (!text) return;

  if (text === '/clear') {
    inputEl.value = '';
    inputEl.style.height = '';
    detachSessionBanner();
    logEl.innerHTML = '';
    activityEvents = [];
    if (activityEl) activityEl.innerHTML = '';
    addNotice('ok', '대화 로그를 깨끗하게 비웠습니다.');
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
      addNotice(st.ok ? 'status' : 'warn', `호스트 상태: **${st.ok ? '정상 가동 중' : '이상 감지'}** · 세션 ID: \`${sessionId || '없음'}\` · 모델: \`${modelEl.value}\``);
    } catch (e) {
      addNotice('error', '상태 확인 실패: ' + e.message);
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
    addChat('user', text, false);   // typed by hand, so it stays on screen; a button does not (TICKET_BUTTONS_v1)
    if (await runTicketDecision(ticketCmd, opts)) return;   // [진행] went on as an ordinary message
    currentSessionHasUser = hadUser;
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
    addNotice('help',
      IDENTITY.title + ' 사용법 요약입니다.\n\n' +
      '**탭** (숫자는 `Alt+숫자`로 바로 전환)\n' +
      '- `Alt+1` 대화 · `Alt+2` 세션 · `Alt+3` 로그 · `Alt+4` 아티팩트 · `Alt+5` 상태 · `Alt+6` 개선\n\n' +
      '**어디서나 되는 것**\n' +
      '- `/` 키: 바로 컴포저로 이동해서 슬래시 메뉴 열기\n' +
      '- 헤더의 `⋯` 버튼: 테마 색상 선택, 호스트 소생(repair)\n' +
      '- 대화가 한 턴 이상이면 채팅창 아래에 새 대화·이어가기 버튼이 뜬다. 세션이 길어지면 거기서 바로 갈아탈 수 있다\n' +
      '- `세션` 탭에서도 새 세션을 열 수 있다\n\n' +
      '**슬래시 명령어**\n' +
      '- `/btw <질문>` 작업 중 샛길 질문 · `/continue` 맥락 요약 인계 새 세션 · `/new` 완전 새 세션\n' +
      '- `/act <행동>` (별칭 `/me`) 말 대신 행동·상황 지문 전달\n' +
      '- `/private on|off` 사적 대화 전환 · `/review` 관찰 리뷰\n' +
      '- `/status` 상태 확인 · `/clear` 화면 비우기 · `/compact` 대화 압축 · `/defib` 호스트 소생\n\n' +
      '**작업 결정** (`/ticket <결정> 번호`, 에이전트에게 안 가고 바로 처리)\n' +
      '- `go` 승인+착수 · `approve` 승인 · `decline` 폐기 · `reopen` 재개\n' +
      '- 위임: `delegate` 실행 · `merge` 승인 · `rework 번호 사유` 반려 · `discard` 폐기 · `allow` 경로 허용\n\n' +
      '**스킬**: `/`만 눌러도 켜 둔 워크스페이스 스킬이 메뉴에 뜨고, `/skill 이름`으로 검색할 수 있다\n\n' +
      '더 궁금한 게 있으면 그냥 물어보세요!');
    currentSessionHasUser = hadUser;
    return;
  }

  if (!sessionId) await ensureSession();

  const isAutoBtw = isBusy && isInquiry(text);
  const isExplicitBtw = text.startsWith('/btw ') || text.startsWith('/btw\n') || text === '/btw';
  const isBtw = isAutoBtw || isExplicitBtw;
  // "/act x", "(x)" and "((x))" are all one action; strip only balanced outer parens so
  // flavored combo '"line" (act)' keeps its inner group (#246).
  const actionText = /^\/(?:act|action|me)\s+\S/.test(text)
    ? (typeof stripOuterParens === 'function'
        ? stripOuterParens(text.replace(/^\/(?:act|action|me)\s+/, '').trim())
        : text.replace(/^\/(?:act|action|me)\s+/, '').trim().replace(/^\(+|\)+$/g, '').trim())
    : actionTextOf(text);
  const isAction = Boolean(actionText);

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
  } else if (isAction) {
    addChat('action', '✦ ' + actionText, false, false, false);
    assistantNode = null; assistantBuf = '';
    setBusy(true);
    setProgress('행동 전달 · 대기 중…');
  } else if (isBusy) {
    // Steer: show the message at once, but leave the streaming answer alone -- the agent keeps
    // working until the current step ends. The server's 'interrupted' event (which comes when the
    // turn is actually cut, immediately for providers that cannot steer) closes the bubble.
    addChat('user', text, false, false, false);
    addActivity('새 지시 전달: ' + shortToolLine(text), 'system');
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
      text: isAction ? ('(' + actionText + ')') : text,
      client_mid: clientMid
    };
    // Structured action: type + raw text; `text` keeps the (…) form until the server reads `type`.
    if (isAction) Object.assign(payload, { type: 'action', action_text: actionText });
    Object.assign(payload, providerFieldsForSend(
      providerEl ? providerEl.value : '',
      modelEl ? modelEl.value : '',
      lastServerProvider,
      lastServerModel
    ));
    const ctx = await getClientContext();
    if (ctx) payload.client_context = ctx;
    const msgRes = await api('/api/sessions/' + encodeURIComponent(sessionId) + '/message', {
      method:'POST',
      body: JSON.stringify(payload)
    });
    if (msgRes && msgRes.switched !== undefined && msgRes.session && msgRes.session.id) {
      setBusy(false);
      setProgress('');
      await applyModeSwitch(msgRes);
    } else if (msgRes && msgRes.rotated && msgRes.session && msgRes.session.id) {
      const nid = msgRes.session.id;
      addActivity('서버가 긴 세션을 새 채팅으로 인계 전환: ' + nid);
      // Seamless in-flow handoff (operator: "세션 간 경계가 느껴지지 않게") --
      // the message this branch is handling is already visible on screen
      // (send()'s own optimistic addChat at the top of this function, well
      // before this POST resolved), so don't clear the log or re-add it --
      // that clear-then-refill was the actual bug (operator: "내가 말을
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
    if (keepFocus) inputEl.focus();
    else if (inputEl.blur) inputEl.blur();
  }
}
applyIdentity();
if (!window.__IDENTITY__) {  // 정적으로 서빙돼 서버가 심어 주지 못한 경우
  fetch(BASE_PATH + '/api/identity').then(r => r.json()).then(j => { Object.assign(IDENTITY, j); applyIdentity(); }).catch(() => {});
}
window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d) return;
  try {
    if (new URL(e.origin).hostname !== location.hostname) return;
  } catch (_) {
    return;
  }
  // Same host-only guard for both intents: the hub's persona FAB posts a character, the provider
  // tray a provider. An id or a name both resolve, because the hub knows a name and the app knows
  // the id; selectCharacter() re-checks the id itself, so a no-op post is harmless.
  if (d.type === 'chatbot-select-provider' && d.provider) {
    selectProvider(d.provider);
  } else if (d.type === 'chatbot-select-character' && d.character) {
    const targetChar = characterCatalog.find(c => c.id === d.character || c.name === d.character);
    if (targetChar) selectCharacter(targetChar);
  }
});
onTrayKey(brandAvatarEl, () => toggleCharacterTray());
onTrayKey(brandProviderEl, () => toggleProviderTray());
document.addEventListener('click', (e) => {
  if (providerTrayEl && !providerTrayEl.hidden && !providerTrayEl.contains(e.target) && e.target !== brandProviderEl) {
    toggleProviderTray(false);
  }
  if (characterTrayEl && !characterTrayEl.hidden && !characterTrayEl.contains(e.target) && e.target !== brandAvatarEl) {
    toggleCharacterTray(false);
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (providerTrayEl && !providerTrayEl.hidden) toggleProviderTray(false);
  if (characterTrayEl && !characterTrayEl.hidden) toggleCharacterTray(false);
});
async function boot() {
  try {
    const res = await api('/api/providers');
    providerCatalog = res.providers || [];
    providerCatalog.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id;
      const blockReason = providerUseBlockedReason(p.id);
      o.textContent = (p.name || p.id) + (blockReason ? ' (제한)' : '');
      // Keep selectable so tray/status can focus a blocked provider.
      o.disabled = false;
      if (providerEl) providerEl.appendChild(o);
    });
    defaultProviderId = res.default || '';
    let savedProvider = localStorage.getItem('chatbot.provider') || defaultProviderId;
    if (providerEl && Array.from(providerEl.options).some(o => o.value === savedProvider)) {
      providerEl.value = savedProvider;
    }
    const currentEntry = providerCatalog.find(p => p.id === savedProvider);
    if (currentEntry && typeof applyTheme === 'function') {
      applyTheme(themeForProvider(currentEntry));
    }
    await loadCharacters();
    updateBrandAvatar(savedProvider);
    renderProviderTray();

    const savedModel = localStorage.getItem('chatbot.model');
    populateModelsForProvider(savedProvider, savedModel);

    if (providerEl) {
      providerEl.onchange = () => {
        selectProvider(providerEl.value);
      };
    }
    // AUTH_GATE_v1: learn CLI login state so logged-out providers look blocked but stay selectable.
    refreshProviderAuthMap();
    modelEl.onchange = () => {
      localStorage.setItem('chatbot.model', modelEl.value);
        if (typeof syncModelUi === 'function') syncModelUi();
      // PROVIDER_SWAP_DEFER_v1: same gate as selectProvider() — never kill an
      // in-flight turn just by picking a model.
      if (typeof isBusy !== 'undefined' && isBusy) {
        pendingProviderPersist = {
          provider: providerEl ? providerEl.value : '',
          model: modelEl.value,
        };
        addActivity('모델 UI만 바꿈 — 진행 중 작업은 유지, 끝난 뒤·다음 메시지부터 적용: ' + modelEl.value);
        return;
      }
      pendingProviderPersist = null;
      persistSessionProvider({ activity: '모델 전환: ' + modelEl.value });
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
  // The hub's persona links pass ?character= the way they pass ?provider=, so a character can be
  // deep-linked. It is read after loadCharacters() and ensureSession() above, so the catalog is full
  // and openCharacterId() is this session's character rather than the default's -- without that the
  // guard below would compare against the wrong one and switch needlessly.
  if (bootCharacterIntent) {
    const targetChar = characterCatalog.find(c => c.id === bootCharacterIntent || c.name === bootCharacterIntent);
    if (targetChar && targetChar.id !== openCharacterId()) {
      await selectCharacter(targetChar);
    }
  }
}

if (tabChat) tabChat.addEventListener('click', () => switchTab('chat'));
if (tabArtifacts) tabArtifacts.addEventListener('click', () => switchTab('artifacts'));
if (tabActivity) tabActivity.addEventListener('click', () => switchTab('activity'));
if (tabStatus) tabStatus.addEventListener('click', () => switchTab('status'));
if (tabEvolution) tabEvolution.addEventListener('click', () => switchTab('evolution'));
if (tabTeam) tabTeam.addEventListener('click', () => switchTab('team'));
if (tabSessions) tabSessions.addEventListener('click', () => switchTab('sessions'));
const evolutionRefreshBtn = document.getElementById('evolutionRefreshBtn');
if (evolutionRefreshBtn) evolutionRefreshBtn.addEventListener('click', () => fetchEvolution());

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
loadWork();
setInterval(loadWork, 15000);
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
const TAB_SHORTCUTS = { '1': 'chat', '2': 'sessions', '3': 'activity', '4': 'artifacts', '5': 'status', '6': 'evolution', '7': 'team' };
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
// SEND_KEEPS_KEYBOARD_v1: pressing the button must not take focus from the input -- on a phone that dropped the
// keyboard, and send() then focused the input again and raised it. Same as #modelBtn; the click still fires.
sendBtn.addEventListener('pointerdown', (e) => e.preventDefault());

if (stopBtn) {
  stopBtn.addEventListener('click', async () => {
    if (!sessionId) return;
    stopBtn.disabled = true;
    const noticeBefore = lastStopNoticeAt;
    try {
      addActivity('작업 중지 요청…');
      await api('/api/sessions/' + encodeURIComponent(sessionId) + '/stop', { method: 'POST' });
      setBusy(false);
      if (assistantNode && assistantNode.dataset.progress === '1') {
        assistantNode.remove();
      }
      assistantNode = null; assistantBuf = '';
      // STOP_NOTICE_ONCE_v1: the server's 'stopped' event (app-sse.js) is the notice every window sees; this one
      // stands in only when that event never came (the stream was down).
      setTimeout(() => {
        if (lastStopNoticeAt !== noticeBefore) return;
        const b = addNotice('stop', '작업을 중지했습니다.', null, true);
        if (b) b.dataset.ephemeral = '1';   // SESSION_DESYNC_GAPFIX_v2
      }, STOP_NOTICE_WAIT_MS);
    } catch (e) {
      addActivity('중지 오류: ' + (e.message || e));
    } finally {
      stopBtn.disabled = false;
    }
  });
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
  if (typeof markKeyboardTransition === 'function') {
    markKeyboardTransition(350);
  }
  setTimeout(updateViewport, 120);
});
inputEl.addEventListener('blur', () => {
  if (typeof markKeyboardTransition === 'function') {
    markKeyboardTransition(250);
  }
  setTimeout(updateViewport, 120);
});
inputEl.addEventListener('keydown', (e) => {
  if (e.isComposing || e.keyCode === 229) return;
  if (handleSlashKeydown(e)) return;
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

autoResizeInput();
// BOOT_CURTAIN_v1 (chat-base.css): the page appears once boot has drawn it -- two frames after, so the last layout
// (history, scroll, the model tag) is painted while still hidden. A boot that hangs does not keep it hidden.
const BOOT_CURTAIN_MAX_MS = 4000;
function liftBootCurtain() { document.documentElement.classList.remove('booting'); }
setTimeout(liftBootCurtain, BOOT_CURTAIN_MAX_MS);
boot().then(() => updateViewport()).catch(() => {}).finally(() => {
  requestAnimationFrame(() => requestAnimationFrame(liftBootCurtain));
});


