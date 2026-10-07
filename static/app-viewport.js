// app-viewport.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
function autoResizeInput() {
  if (!inputEl) return;
  // Min/max come from the stylesheet (#input, the <=640px block, the keyboard/short-screen block), so
  // this can't drift from it again. It used to keep its own 38/42 and 90/120: the input was 38px
  // while the CSS said 36 (32 with the keyboard up) and the buttons next to it were 44 (32), and it
  // fell back to the CSS value after a slash command cleared the inline height. (operator: the bottom widgets'
  // heights differ a little from case to case.)
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

// Keyboard tracking from the viewport height.
// It judges by the change in viewport height instead of a _prevKeyboardOpen state machine, so raising or
// lowering only the keyboard while the focus stays works too.
let _composerMode = '';         // narrow/wide + keyboard-open of the last updateViewport (input height follows the CSS for it)
let _prevVvHeight = 0;          // the previous visualViewport height
let _savedScrollTop = null;     // scrollTop kept when the keyboard opens (only when not pinned to the bottom)
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
// model button, with a mouse and a physical keyboard. (operator: the FAB text box height differs / the layout shakes on focus.)
function keyboardOpenState(narrow, short, focused, touch) {
  return Boolean(narrow && (short || (focused && touch)));
}

// Keyboard up/down: a pinned log (isLogPinnedToBottom, the single truth since #211) snaps to the bottom; an
// unpinned one keeps its reading position. Every write goes through the isProgrammaticScroll guard, so the
// log's scroll listener does not take it for a user scroll.
function holdLogPosition(opening) {
  if (isLogPinnedToBottom || isLogAtBottom(logEl)) {
    isLogPinnedToBottom = true;
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

  // Mobile on-screen keyboard state (a narrow width whose height shrank, or the input has focus)
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
    const delta = _prevVvHeight > 0 ? h - _prevVvHeight : 0; // positive = the viewport grew (keyboard closed), negative = it shrank (keyboard opened)
    if (keyboardFlipped || Math.abs(delta) > 60) {
      if (!keyboardFlipped) markKeyboardTransition(300);
      holdLogPosition(keyboardFlipped ? isKeyboardOpen : delta < 0);
    }
    // clientHeight is still moving: the pinned state, not a fresh measurement, decides the button
    updateScrollBottomButton(isLogPinnedToBottom);
  }

  _prevVvHeight = h;
}

// BOTTOM_PULL_REFRESH_v1 (#423): mobile touch pull-up gesture at the bottom of the chat log
let _bottomPullInitDone = false;
let _bottomPullTouchAtBottom = false;
let _bottomPullStartY = 0;
let _bottomPullStartX = 0;
let _bottomPullActive = false;
let _bottomPullRefreshing = false;
const BOTTOM_PULL_THRESHOLD = 150;

// The one "is this log scrolled to its true bottom" check (2px slack for subpixel layout). With no argument it
// measures the chat log; a log with nothing to scroll counts as at the bottom.
function isLogAtBottom(el) {
  if (el === undefined) el = (typeof logEl !== 'undefined') ? logEl : null;
  if (!el) return false;
  return (el.scrollTop + el.clientHeight >= el.scrollHeight - 2);
}

// Does the log on screen hold the channel's active tip -- the live session (liveSessionId, else the newer
// session nav points at)? Either the open session is the tip, or the last rendered message carries the tip's sid.
function containsActiveTip() {
  const tip = (typeof liveSessionId !== 'undefined' && liveSessionId) ||
    (typeof sessionNavNextSid !== 'undefined' && sessionNavNextSid) || '';
  if (!tip) return true;
  if (typeof sessionId !== 'undefined' && sessionId === tip) return true;
  if (typeof logEl === 'undefined' || !logEl || typeof logEl.querySelectorAll !== 'function') return false;
  const marked = logEl.querySelectorAll('.msg[data-sid]');
  const last = marked.length ? marked[marked.length - 1] : null;
  return Boolean(last && last.dataset && last.dataset.sid === tip);
}

function isTouchContext() {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) return true;
  if ('ontouchstart' in window) return true;
  if (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0) return true;
  if (typeof window.innerWidth === 'number' && window.innerWidth <= 640) return true;
  return false;
}

function calcDampedPull(dy) {
  if (dy <= 0) return 0;
  if (dy <= BOTTOM_PULL_THRESHOLD) {
    return Math.round(dy * 0.45);
  }
  return Math.min(84, Math.round(BOTTOM_PULL_THRESHOLD * 0.45 + (dy - BOTTOM_PULL_THRESHOLD) * 0.25));
}

function initBottomPullRefresh(customLog) {
  const targetLog = customLog || (typeof logEl !== 'undefined' && logEl ? logEl : (typeof document !== 'undefined' && document.getElementById ? document.getElementById('log') : null));
  if (!targetLog || typeof targetLog.addEventListener !== 'function') return;

  const container = (targetLog && targetLog.parentElement) ||
    (typeof document !== 'undefined' && document.querySelector ? document.querySelector('.stage') : null) ||
    targetLog;
  if (!container || typeof container.appendChild !== 'function') return;

  if (_bottomPullInitDone && !customLog) return;
  _bottomPullInitDone = true;

  let indicatorEl = (typeof document !== 'undefined' && document.getElementById ? document.getElementById('bottomPullIndicator') : null) ||
    (container && container.querySelector ? container.querySelector('#bottomPullIndicator') : null);

  if (!indicatorEl && typeof document !== 'undefined' && document.createElement) {
    indicatorEl = document.createElement('div');
    indicatorEl.id = 'bottomPullIndicator';
    indicatorEl.className = 'bottom-pull-indicator';
    indicatorEl.setAttribute('aria-hidden', 'true');
    indicatorEl.innerHTML = '<div class="bottom-pull-content">' +
      '<span class="bottom-pull-icon" aria-hidden="true">↻</span>' +
      '<span class="bottom-pull-label">' + tr('viewport.pull') + '</span>' +
      '</div>';
    container.appendChild(indicatorEl);
  }

  const iconEl = indicatorEl ? indicatorEl.querySelector('.bottom-pull-icon') : null;
  const labelEl = indicatorEl ? indicatorEl.querySelector('.bottom-pull-label') : null;

  function resetPullState(animated) {
    _bottomPullTouchAtBottom = false;
    _bottomPullActive = false;

    const currentLog = (typeof logEl !== 'undefined' && logEl) ? logEl : targetLog;
    if (indicatorEl) {
      if (animated) {
        indicatorEl.style.transition = 'transform 0.25s cubic-bezier(0.2, 0, 0, 1), opacity 0.25s ease';
      } else {
        indicatorEl.style.transition = '';
      }
      indicatorEl.classList.remove('ready');
      indicatorEl.classList.remove('refreshing');
      indicatorEl.style.transform = '';
      indicatorEl.style.opacity = '0';
      if (iconEl) iconEl.style.transform = '';
      if (labelEl) labelEl.textContent = tr('viewport.pull');
    }

    if (currentLog) {
      if (animated) {
        currentLog.style.transition = 'transform 0.25s cubic-bezier(0.2, 0, 0, 1)';
      } else {
        currentLog.style.transition = '';
      }
      currentLog.style.transform = '';
    }

    if (animated && typeof setTimeout === 'function') {
      setTimeout(() => {
        if (!_bottomPullActive && !_bottomPullRefreshing) {
          if (indicatorEl) indicatorEl.style.transition = '';
          if (currentLog) currentLog.style.transition = '';
        }
      }, 260);
    }
  }

  function handleTouchStart(e) {
    if (typeof currentTab !== 'undefined' && currentTab !== 'chat') return;
    if (!isTouchContext()) return;
    if (!e.touches || e.touches.length !== 1) return;
    if (_bottomPullRefreshing) return;

    const currentLog = (typeof logEl !== 'undefined' && logEl) ? logEl : targetLog;
    if (!currentLog) return;

    const atBottom = isLogAtBottom(currentLog);
    if (!atBottom) {
      _bottomPullTouchAtBottom = false;
      _bottomPullActive = false;
      return;
    }

    _bottomPullTouchAtBottom = true;
    _bottomPullActive = false;
    _bottomPullStartY = e.touches[0].clientY;
    _bottomPullStartX = e.touches[0].clientX;
  }

  function handleTouchMove(e) {
    if (!_bottomPullTouchAtBottom || _bottomPullRefreshing) return;
    if (!e.touches || e.touches.length !== 1) return;

    const touchY = e.touches[0].clientY;
    const touchX = e.touches[0].clientX;
    const dy = _bottomPullStartY - touchY;
    const dx = Math.abs(touchX - _bottomPullStartX);

    if (dy < 0) {
      if (_bottomPullActive) {
        resetPullState(true);
      }
      if (dy < -5) {
        _bottomPullTouchAtBottom = false;
      }
      return;
    }

    if (!_bottomPullActive) {
      if (dx > dy) {
        _bottomPullTouchAtBottom = false;
        return;
      }
      if (dy <= 6) return;
      _bottomPullActive = true;
    }

    if (e.cancelable) {
      e.preventDefault();
    }

    const rawPull = dy - 6;
    const distance = calcDampedPull(rawPull);
    const isReady = rawPull >= BOTTOM_PULL_THRESHOLD;

    const currentLog = (typeof logEl !== 'undefined' && logEl) ? logEl : targetLog;
    if (indicatorEl) {
      const indHeight = indicatorEl.offsetHeight || 56;
      indicatorEl.style.transition = 'none';
      indicatorEl.style.opacity = String(Math.min(1, Math.max(0.1, distance / 24)));
      indicatorEl.style.transform = `translate3d(0, ${Math.max(0, indHeight - distance)}px, 0)`;

      if (isReady) {
        indicatorEl.classList.add('ready');
        if (iconEl) iconEl.style.transform = 'rotate(180deg)';
        if (labelEl) labelEl.textContent = tr('viewport.release');
      } else {
        indicatorEl.classList.remove('ready');
        const progress = Math.min(1, Math.max(0, rawPull / BOTTOM_PULL_THRESHOLD));
        const rot = Math.round(progress * 180);
        if (iconEl) iconEl.style.transform = `rotate(${rot}deg)`;
        if (labelEl) labelEl.textContent = tr('viewport.pull');
      }
    }

    if (currentLog) {
      currentLog.style.transition = 'none';
      currentLog.style.transform = `translate3d(0, -${distance}px, 0)`;
    }
  }

  function handleTouchEnd() {
    if (!_bottomPullActive || _bottomPullRefreshing) {
      _bottomPullTouchAtBottom = false;
      _bottomPullActive = false;
      return;
    }

    if (indicatorEl && indicatorEl.classList.contains('ready')) {
      _bottomPullRefreshing = true;
      _bottomPullActive = false;
      _bottomPullTouchAtBottom = false;

      indicatorEl.classList.remove('ready');
      indicatorEl.classList.add('refreshing');
      if (labelEl) labelEl.textContent = tr('viewport.refreshing');
      if (iconEl) iconEl.style.transform = '';

      indicatorEl.style.transition = 'transform 0.2s cubic-bezier(0.2, 0, 0, 1), opacity 0.2s ease';
      indicatorEl.style.transform = 'translate3d(0, 0, 0)';
      indicatorEl.style.opacity = '1';

      const currentLog = (typeof logEl !== 'undefined' && logEl) ? logEl : targetLog;
      if (currentLog) {
        currentLog.style.transition = 'transform 0.2s cubic-bezier(0.2, 0, 0, 1)';
        currentLog.style.transform = 'translate3d(0, -52px, 0)';
      }

      if (typeof setTimeout === 'function') {
        setTimeout(() => {
          if (typeof window !== 'undefined' && window.location && typeof window.location.reload === 'function') {
            window.location.reload();
          }
        }, 350);
      }
    } else {
      resetPullState(true);
    }
  }

  function handleTouchCancel() {
    resetPullState(true);
  }

  targetLog.addEventListener('touchstart', handleTouchStart, { passive: true });
  targetLog.addEventListener('touchmove', handleTouchMove, { passive: false });
  targetLog.addEventListener('touchend', handleTouchEnd, { passive: true });
  targetLog.addEventListener('touchcancel', handleTouchCancel, { passive: true });

  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('touchend', handleTouchEnd, { passive: true });
    window.addEventListener('touchcancel', handleTouchCancel, { passive: true });
  }

  initBottomPullRefresh.reset = function () {
    _bottomPullInitDone = false;
    _bottomPullTouchAtBottom = false;
    _bottomPullActive = false;
    _bottomPullRefreshing = false;
    resetPullState(false);
  };
}

initBottomPullRefresh.isAtBottom = isLogAtBottom;

if (typeof window !== 'undefined') {
  window.initBottomPullRefresh = initBottomPullRefresh;
  window.containsActiveTip = containsActiveTip;
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initBottomPullRefresh());
  } else {
    initBottomPullRefresh();
  }
}
