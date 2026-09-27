// app-viewport.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
function autoResizeInput() {
  if (!inputEl) return;
  // Min/max come from the stylesheet (#input, the <=640px block, the keyboard/short-screen block), so
  // this can't drift from it again. It used to keep its own 38/42 and 90/120: the input was 38px
  // while the CSS said 36 (32 with the keyboard up) and the buttons next to it were 44 (32), and it
  // fell back to the CSS value after a slash command cleared the inline height. (operator: 하단 위젯들
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
let _savedScrollTop = null;     // 키보드 열릴 때 보존한 scrollTop (바닥 고정이 아닐 때만)
let _isKeyboardTransitioning = false;
let _keyboardTransitionTimer = null;

function markKeyboardTransition(duration = 300) {
  _isKeyboardTransitioning = true;
  if (_keyboardTransitionTimer) clearTimeout(_keyboardTransitionTimer);
  if (typeof setTimeout === 'function') {
    _keyboardTransitionTimer = setTimeout(() => {
      _isKeyboardTransitioning = false;
      _keyboardTransitionTimer = null;
      // the layout has settled (the .msg resizes were skipped meanwhile): land a pinned log at the true bottom once
      if (typeof isLogPinnedToBottom !== 'undefined' && isLogPinnedToBottom && typeof scrollChatToBottom === 'function') {
        scrollChatToBottom(true);
      }
    }, duration);
  } else {
    _isKeyboardTransitioning = false;
  }
}

function isKeyboardTransitioning() {
  return Boolean(_isKeyboardTransitioning);
}

// Is the on-screen keyboard (probably) up? A short viewport says so on any device. "The input has focus"
// only says so when there IS an on-screen keyboard -- i.e. a touch device. On a desktop FAB (an iframe
// 420px wide) it used to count too: clicking the text box shrank the row and hid the header, tabs and
// model button, with a mouse and a physical keyboard. (operator: FAB 텍스트창 높이가 달라 / 포커스하면 레이아웃이 흔들려.)
function keyboardOpenState(narrow, short, focused, touch) {
  return Boolean(narrow && (short || (focused && touch)));
}

// Keyboard up/down: a pinned log (isLogPinnedToBottom, the single truth since #211) snaps to the bottom; an
// unpinned one keeps its reading position. Every write goes through the isProgrammaticScroll guard, so the
// log's scroll listener does not take it for a user scroll.
function holdLogPosition(opening) {
  if (isLogPinnedToBottom) {
    _savedScrollTop = null;
    scrollChatToBottom(true);
    return;
  }
  if (opening) {
    if (_savedScrollTop === null) _savedScrollTop = logEl.scrollTop;
  } else if (_savedScrollTop !== null) {
    isProgrammaticScroll = true;
    logEl.scrollTop = _savedScrollTop;
    isProgrammaticScroll = false;
    _savedScrollTop = null;
  }
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
  const prevKeyboardOpen = document.body.classList.contains('keyboard-open');
  const isKeyboardOpen = keyboardOpenState(isNarrow, isShort, isInputFocused, isTouch);
  const keyboardFlipped = prevKeyboardOpen !== isKeyboardOpen;
  // every real flip (a height change or just focus on a touch device) resizes .msg via body.keyboard-open
  if (keyboardFlipped) markKeyboardTransition(350);
  document.body.classList.toggle('keyboard-open', Boolean(isKeyboardOpen));
  // the composer's CSS heights depend on both -- re-measure the input when either flips
  const composerMode = (isNarrow ? 'n' : 'w') + (isKeyboardOpen ? 'k' : '-');
  if (composerMode !== _composerMode) {
    _composerMode = composerMode;
    autoResizeInput();
  }

  const liveSlashMenu = document.getElementById('slashMenu');
  if (liveSlashMenu && !liveSlashMenu.hidden) positionSlashMenu();

  if (logEl && currentTab === 'chat' && isNarrow) {
    const delta = _prevVvHeight > 0 ? h - _prevVvHeight : 0; // 양수 = viewport 커짐(키보드 닫힘), 음수 = 작아짐(키보드 열림)
    if (keyboardFlipped || Math.abs(delta) > 60) {
      if (!keyboardFlipped) markKeyboardTransition(300);
      holdLogPosition(keyboardFlipped ? isKeyboardOpen : delta < 0);
    }
    // clientHeight is still moving: the pinned state, not a fresh measurement, decides the button
    updateScrollBottomButton(isLogPinnedToBottom);
  }

  _prevVvHeight = h;
}
