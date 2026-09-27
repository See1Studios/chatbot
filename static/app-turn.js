// app-turn.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
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
    sendBtn.textContent = '샛길 질문';
    sendBtn.classList.remove('queue-btn');
    sendBtn.classList.add('btw-btn');
  } else {
    sendBtn.textContent = '끼워 넣기';
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
  // Status chrome stays persona-neutral. A character's speech style (e.g. a verbal tic) is its voice,
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
  } else if (activeWorkRun) {   // the chat waits while an expert works (DELEGATION_CLARITY_v1)
    const r = activeWorkRun;
    badge.className = 'proc-badge running delegated';
    textEl.textContent = workRunWho(r) + ' 작업 중' + (r.started ? ' · ' + workElapsed(Date.now() / 1000 - r.started) : '');
    badge.title = '#' + r.ticket + ' ' + (r.title || '') + ' · ' + (WORK_PHASE_LABEL[r.phase] || r.phase);
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
          setProgress('백엔드 프로세스가 중단되었습니다.', true);
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

// The composer placeholder always leads with the model in use (operator: 모델 select를 짧은 버튼으로 줄이는
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

  if (!isBusy && typeof flushPendingProviderPersist === 'function') {
    setTimeout(() => { flushPendingProviderPersist(); }, 0);
  }
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
