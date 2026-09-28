// app-sse.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.

// A user line that is only "(지문)" / "((지문))" is a stage action, not speech: returns the bare
// action text ('' otherwise). send(), user_ack and history all route through this.
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

function actionTextOf(text) {
  // A user line that is only "(지문)" — including flavored ("대사") / ("대사" (행동)) — is a stage action.
  // Reject multi-wrap speech like "(a) 그리고 (b)".
  const s = String(text || '').trim();
  if (s.length < 3 || s[0] !== '(' || s[s.length - 1] !== ')') return '';
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '(') depth++;
    else if (s[i] === ')') {
      depth--;
      if (depth === 0 && i !== s.length - 1) return '';
      if (depth < 0) return '';
    }
  }
  if (depth !== 0) return '';
  return stripOuterParens(s);
}

// Draws a user history/ack entry: action lines as .msg.action, the rest as a user bubble.
function addUserEntry(text, isQueued, prepend, ts) {
  const act = actionTextOf(text);
  if (act) return addChat('action', '\u2726 ' + act, false, isQueued, false, prepend, null, null, false, ts);
  return addChat('user', text || '', false, isQueued, (text || '').startsWith('/btw'), prepend, null, null, false, ts);
}

// STREAM_FLOW_v1 (2026-09-28): a provider emits 50-200 tokens/s and the screen paints 60/s, so
// rendering the answer on every delta parsed the same growing document once per token and rebuilt
// the bubble every time -- the markdown pipeline, the sanitiser, the buttons, the chips, the scroll.
// Coalescing to one paint per animation frame is what makes the streaming text affordable to
// animate at all, and it is the same change that removes the O(n^2).
var streamPaintQueued = false;
var streamPaintCancel = null;

function scheduleStreamPaint(paint) {
  if (streamPaintQueued) return;   // one paint per frame, whatever the token rate
  streamPaintQueued = true;
  const run = function () {
    streamPaintQueued = false;
    streamPaintCancel = null;
    paint();
  };
  if (typeof window.requestAnimationFrame === 'function') {
    const h = window.requestAnimationFrame(run);
    streamPaintCancel = function () { window.cancelAnimationFrame(h); };
  } else {
    const t = setTimeout(run, 16);
    streamPaintCancel = function () { clearTimeout(t); };
  }
}

function cancelStreamPaint() {
  if (streamPaintCancel) streamPaintCancel();
  streamPaintQueued = false;
  streamPaintCancel = null;
}

function streamBody(node) {
  let md = node.querySelector('.md');
  if (!md) {
    md = document.createElement('div');
    md.className = 'md';
    node.appendChild(md);
  }
  md.classList.add('md-stream');
  return md;
}

// REVEAL_BLOCKS_v1 (2026-09-28): the answer is the finished thing while it is still arriving.
//
// Three complaints, one cause. A stream printed plain text and turned into markdown at the end, so
// the end was a swap. The entrance was applied to whatever one paint delivered, which measured at
// a median of ONE character, so there was nothing to see. And the text had no life in it while it
// was being written.
//
// A markdown block has an extent, and once that extent has arrived the block can never change. So
// a block is rendered the moment it closes -- the real render, marked and sanitised, the same call
// the final render makes -- and the per-frame work drops to the one block still being written. That
// is the whole trick: the cost is per block, not per frame. Re-parsing the entire document on every
// frame measured 0.4ms at 164 characters and 1.8ms at 2440, which was affordable but was solving a
// problem the block boundary removes outright.
//
// And then the bubble shook, and the text rose and fell -- and both were this code's fault.
//
// Delaying the APPEARANCE was the wrong half of the idea. It froze the block being written while a
// closed one waited, then put that same text on screen a second time as a real block, then took it
// away again: freeze, duplicate, shrink. Lagging the animation instead costs none of that, because
// nothing about the text moves. The block is in the right place at the right time, the reader can
// read it, and a beat later it settles.
//
// And nothing scales. scale() does not move layout but it does make the letters change size, and a
// bubble whose text keeps growing and shrinking reads as a bubble that cannot hold still. The
// per-kind vocabulary is built from translation and one gentle opacity dip instead, so the type is
// the same size at every frame of the motion.
//
// How long a block sits still before it settles. Long enough that the reader sees the text arrive
// first and the motion second; short enough to still feel like the same moment.
var STREAM_REVEAL_BEAT = 200;
// The extra room each block in a same-paint burst gets, so a coalesced catch-up cascades instead
// of landing as one flash.
var STREAM_REVEAL_STAGGER = 60;

// Marks a block as settling, one beat after it went on screen. The class comes off when the
// animation ends, so it can never replay and a later render cannot restart a motion the reader has
// already watched.
//
// `step` spreads out blocks that closed in the same paint, which is what a coalesced burst looks
// like. Without it three entrances fire on the same frame, and three entrances on the same frame
// is the strobe all over again.
function scheduleArrive(node, el, kind, step) {
  if (revealReducedMotion()) { el.setAttribute('data-kind', kind || 'narration'); return; }
  el.setAttribute('data-kind', kind || 'narration');
  const delay = STREAM_REVEAL_BEAT + (step || 0) * STREAM_REVEAL_STAGGER;
  node._arriveTimers = node._arriveTimers || [];
  const id = setTimeout(function () {
    node._arriveTimers = (node._arriveTimers || []).filter(function (t) { return t !== id; });
    markArrive(el, kind);
  }, delay);
  node._arriveTimers.push(id);
}

function clearArriveTimers(node) {
  (node._arriveTimers || []).forEach(clearTimeout);
  node._arriveTimers = [];
}

function revealReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Splits a growing answer into the blocks that are finished and the one still being written.
function setStreamingContent(node, text) {
  if (!node) return;
  // The body must exist before the badge: otherwise the first paint puts the badge on the node
  // instead of inside .md, and the second paint moves it.
  const md = streamBody(node);
  const shown = prepareStreamText(text);
  const prev = node._streamShown || '';
  // Not an append -- a resync rewrote the draft, or a thought block closed and retracted its text.
  // Start the body over rather than leaving a stale block in front of the new answer.
  if (shown.indexOf(prev) !== 0) resetStreamBody(node, md);
  const cut = revealBlocks(shown);
  // Fewer finished blocks than are on screen means the text shrank, which is the same situation.
  if (cut.blocks.length < (node._streamUnits || 0)) resetStreamBody(node, md);
  // The block being written is always the last child, so the existing caret -- a ::after on
  // .md > *:last-child (chat-composer.css) -- lands on it and keeps one caret instead of two. It is
  // created before the finished blocks so those can be inserted in front of it.
  let openEl = node._streamOpen;
  if (!openEl) {
    openEl = document.createElement('div');
    openEl.className = 'md-block open';
    md.appendChild(openEl);
    node._streamOpen = openEl;
  }
  // A closed block goes on screen at once, in order, exactly where it belongs. Only its motion waits.
  const from = node._streamUnits || 0;
  for (let i = from; i < cut.blocks.length; i++) {
    const box = buildBlock(cut.blocks[i], false);
    md.insertBefore(box, openEl);
    scheduleArrive(node, box, cut.blocks[i].kind, i - from);
  }
  node._streamUnits = cut.blocks.length;
  // The open block carries the kind being written, so a line that has an action and then speech
  // flows like speech while the speech is the part arriving.
  openEl.setAttribute('data-kind', unitKind(cut.open));
  // renderPlainText, not renderMarkdown: an incomplete block has no extent yet, and handing marked
  // a half-written list gives it nothing stable to keep. It is escaping plus a few regexes, and it
  // already renders bold, italics, code and an open fence, so what is on screen is close to final.
  openEl.innerHTML = cut.open ? renderPlainText(cut.open) : '';
  node._streamShown = shown;
  node.classList.add('streaming');
  // After the body, never before: the first paint writes over .md and would take the badge with it.
  // This is the order postProcessAssistant effectively runs in.
  paintExpressionBadge(node, text);
  scrollChatToBottom(false);
}

function resetStreamBody(node, md) {
  clearArriveTimers(node);
  md.textContent = '';
  node._streamUnits = 0;
  node._streamOpen = null;      // the old open element is detached with the rest of the body
}

function endStreamingContent(node) {
  if (!node) return;
  clearArriveTimers(node);
  // A block that was still waiting out its beat settles now rather than never. The text is on
  // screen either way -- the appearance was never the thing that waited -- so this is the motion
  // being caught up, not anything the reader is waiting for.
  const md = node.querySelector && node.querySelector('.md');
  if (md) {
    (md.children || []).forEach(function (c) {
      const cls = c.className || '';
      if (/\bmd-block\b/.test(cls) && !/\bopen\b/.test(cls)) markArrive(c, c.getAttribute('data-kind'));
    });
    md.classList.remove('md-stream');
  }
  node._streamShown = '';
  node._streamUnits = 0;
  node._streamOpen = null;
  node.classList.remove('streaming');
}

function bindEvents(sid) {
  if (window.__chatEsTimer) { clearTimeout(window.__chatEsTimer); window.__chatEsTimer = null; }
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
        setStreamingContent(assistantNode, assistantBuf);   // STREAM_FLOW_v1: still speaking
      }
      fetchArtifacts(true);
      return;
    }

    if (type === 'delta' || type === 'assistant' || type === 'provider_event' || type === 'message') {
      setBusy(true);
      if (!assistantNode) {
        assistantNode = addChat('assistant', '', false);
        assistantNode.dataset.live = '1';
      }
      if (assistantNode) delete assistantNode.dataset.progress;
      if (type === 'delta') {
        const offset = typeof data.offset === 'number' ? data.offset : null;
        if (offset !== null && offset < (assistantBuf || '').length) {
          // Stale or already-applied delta (e.g. resync poll delivered draft first)
          return;
        }
        assistantBuf = (assistantBuf || '') + text;
      } else if (text) {
        assistantBuf = text;
      }
      const paintNode = assistantNode;
      const paintBuf = assistantBuf || '작성 중…';
      scheduleStreamPaint(function () {
        // A turn that ended between the delta and this frame must not be painted into.
        if (!paintNode || paintNode.dataset.live !== '1') return;
        setStreamingContent(paintNode, paintBuf);
        updateTurnLive();
      });
      return;
    }

    if (type === 'result') {
      if (typeof loadWork === 'function') loadWork();   // a turn that delegated work shows its card now
      cancelStreamPaint();   // STREAM_FLOW_v1: a queued frame must not land on a finished message
      // QUOTA_SILENT_FIX_v1: result residual error
      if (text) assistantBuf = textWithChoices(data);   // the server took the choices out of the text
      if (assistantNode) delete assistantNode.dataset.progress;
      const doneNode = assistantNode;
      const doneBuf = assistantBuf;
      const residualErr = (data.error && !(doneBuf || '').trim()) ? String(data.error) : '';
      setBusy(false);
      setProgress('');
      const twin = data.ts ? findRenderedByTs('assistant', data.ts) : null;
      if (twin && twin !== doneNode) {
        if (doneNode) doneNode.remove();
      } else if (doneBuf && doneBuf.trim()) {
        // Answer won — ignore residual data.error (agy quota after successful stream).
        const node = doneNode || addChat('assistant', '', false);
        setAssistantContent(node, doneBuf, true, data.usage, data.duration_seconds, data.served_model);
        endStreamingContent(node);   // STREAM_FLOW_v1: the finished message is still; no motion
        if (data.ts) {
          node.dataset.ts = String(data.ts);
          node.dataset.syncRole = 'assistant';
        }
        delete node.dataset.live;
      } else if (residualErr || data.notice === 'error') {
        if (doneNode) doneNode.remove();
        addNotice((data.notice || 'error'), residualErr || text || '알 수 없는 오류', data.ts);
      } else if (doneNode) {
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
      // (operator: "내가 말을 하면 바로 새 세션으로 넘어가면서 내가 한 말을
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
          greeting: text || '새 채팅으로 전환했습니다. 이어서 진행합니다.',
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
      // NOTICE_UI_v1: host stop is its own notice bubble (no reply footer)
      addActivity('작업 중지: ' + (text || ''), 'system');
      const stopMsg = text || '작업이 중단되었습니다.';
      if (assistantNode) {
        clearTurnLive(assistantNode);
        if (assistantBuf && assistantBuf.trim() && assistantNode.dataset.progress !== '1') {
          markUntimed(assistantNode, assistantBuf);
          setAssistantContent(assistantNode, assistantBuf.trim(), true);
          delete assistantNode.dataset.live;
        } else {
          assistantNode.remove();
        }
      }
      addNotice((data.notice || 'stop'), stopMsg, data.ts);
      assistantNode = null; assistantBuf = '';
      setBusy(false);
      setProgress('');
      return;
    }

    if (type === 'interrupted') {
      addActivity(text || '진행 중인 작업 전환', 'system');
      if (assistantNode && assistantBuf && assistantBuf.trim()) {
        // Finalize partial output with an interrupted mark
        markUntimed(assistantNode, assistantBuf);
        setAssistantContent(assistantNode, assistantBuf.trim() + (data.reason === 'steer' ? '\n\n*(새 지시 반영을 위해 잠시 멈춤)*' : '\n\n*(새 지시로 전환)*'), true);
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
      addActivity(text || '새 지시 접수', 'system');
      setProgress('새 지시 접수 · 지금 단계가 끝나면 반영해요…');
      return;
    }

    if (type === 'user_ack') {
      // Broadcast to every window/tab on this shared session whenever a user
      // message actually gets sent to agy -- including from a message sent
      // by an EXACT one of the other windows. This window's own just-sent
      // message was already rendered optimistically at send() time (with a
      // client_mid tag), so only render here when the mid doesn't match
      // anything this window itself sent (operator: "다른 창에서 보낸 질의는
      // 안 보이네" -- previously this handler only ever un-queued this
      // window's own bubble and never rendered anyone else's).
      const mid = data.client_mid || '';
      const isMine = Boolean(mid) && myPendingMids.has(mid);
      // A resync can have drawn (or stamped) this message before its ack arrives.
      const drawn = Boolean(data.ts && (findRenderedByTs('user', data.ts) || findRenderedByTs('action', data.ts) || findRenderedByTs('btw-user', data.ts)));
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
        addUserEntry(text, false, false, data.ts);
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
        // SESSION_DESYNC_GAPFIX_v2 + NOTICE_UI_v1 + QUOTA_ERR_DEDUP_v1
        setBusy(false);
        setProgress('');
        if (assistantNode) {
          clearTurnLive(assistantNode);
          if (assistantBuf && assistantBuf.trim() && assistantNode.dataset.progress !== '1') {
            markUntimed(assistantNode, assistantBuf);
            setAssistantContent(assistantNode, assistantBuf.trim(), true);
            delete assistantNode.dataset.live;
            delete assistantNode.dataset.progress;
          } else {
            assistantNode.remove();
          }
        }
        const errBody = text || '알 수 없는 오류';
        const twinNotice = data.ts ? document.querySelector('.msg.notice-error[data-ts="' + String(data.ts) + '"]') : null;
        if (!twinNotice) addNotice((data.notice || 'error'), errBody, data.ts);
        if (data.ts) lastSyncedTs = Math.max(lastSyncedTs, data.ts);
        assistantNode = null; assistantBuf = '';
      }
      addActivity(line, kind, data.ts, detail);
      return;
    }

    if (type === 'provider_event' && data.payload) {
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
    window.__chatEsRetry = (window.__chatEsRetry || 0) + 1;
    if (window.__chatEsRetry > 20) {
      setProgress('서버 연결이 끊겼습니다 (20회 재시도 실패). 새로고침해 주세요.', true);
      addActivity('서버 연결 실패 (20회 재시도 실패). 새로고침이 필요합니다.', 'warn');
      return;
    }
    // SESSION_DESYNC_GAPFIX_v2: always log disconnect in Activity; only escalate
    // the in-chat progress chrome from the 2nd retry (idle SSE recycle is common).
    if (window.__chatEsRetry === 1) {
      addActivity('연결 끊김 · 재연결 시도…', 'warn');
    }
    if (window.__chatEsRetry >= 2) {
      setProgress('연결이 끊겼어요 · 다시 연결하는 중…');
      addActivity('연결 끊김 · 재연결 재시도 (' + window.__chatEsRetry + ')', 'warn');
    }
    if (window.__chatEsTimer) clearTimeout(window.__chatEsTimer);
    const wait = Math.min(15000, 800 * Math.pow(1.6, Math.min(window.__chatEsRetry, 8)));
    window.__chatEsTimer = setTimeout(() => {
      if (sessionId === sid) bindEvents(sid);
    }, wait);
  };
  es.onopen = () => {
    window.__chatEsRetry = 0;
    if (!isBusy) updateProcBadge('idle');
    setProgress('');
    resyncFromServer(sid);
    checkRevived();
  };
  startSessionSyncLoop();
}

// REVIVE_TOAST_v1 (#224): the first SSE open only records the server's boot_ts;
// a later open that sees a different one means the host restarted, so flash
// '소생 완료 ✦' in the progress bar. No boot_ts (older server) -> nothing.
let lastBootTs = null;
async function checkRevived() {
  let ts;
  try { ts = (await api('/healthz', { timeoutMs: 5000 })).boot_ts; } catch (_) { return; }
  if (!ts) return;
  const revived = lastBootTs !== null && ts !== lastBootTs;
  lastBootTs = ts;
  if (!revived) return;
  const msg = '소생 완료 ✦';
  setProgress(msg, true);
  setTimeout(() => {
    if (progressEl && !progressEl.hidden && progressEl.textContent.trim() === msg) setProgress('');
  }, 3000);
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
