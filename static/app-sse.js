// app-sse.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.

// STOP_NOTICE_ONCE_v1: when the server last said a turn was stopped; the stop button (app.js) waits this long for it.
let lastStopNoticeAt = 0;
const STOP_NOTICE_WAIT_MS = 1500;
// SYNC_THROTTLE_v1: when the stream last delivered anything; the sync poll (app-session.js) leans on it.
let lastStreamAt = 0;

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
  // plus/G: an item's host note rides after the action; it is a chip on screen, not part of the words
  const g = typeof splitItemNote === 'function' ? splitItemNote(text) : { text: text, item: null };
  const act = actionTextOf(g.text);
  const node = act
    ? addChat('action', '\u2726 ' + act, false, isQueued, false, prepend, null, null, false, ts)
    : addChat('user', g.text || '', false, isQueued, (g.text || '').startsWith('/btw'), prepend, null, null, false, ts);
  if (g.item && typeof renderItemChip === 'function') renderItemChip(node, g.item);
  return node;
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
// The motion is not here: it belongs to the letters (CHAR_REVEAL_v1, below), which arrive one by
// one on their own clock. This function only draws a prefix of the answer as blocks.
function revealReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Splits a growing answer into the blocks that are finished and the one still being written.
// `badgeSrc`: when given, `text` is already the display text (the letter clock passes a prefix of it)
// and the raw answer is only for the emotion badge.
function setStreamingContent(node, text, badgeSrc) {
  if (!node) return;
  // The body must exist before the badge: otherwise the first paint puts the badge on the node
  // instead of inside .md, and the second paint moves it.
  const md = streamBody(node);
  const shown = badgeSrc === undefined ? prepareStreamText(text) : String(text || '');
  const prev = node._streamShown || '';
  // Not an append -- a resync rewrote the draft, or a thought block closed and retracted its text.
  // Start the body over rather than leaving a stale block in front of the new answer.
  if (shown.indexOf(prev) !== 0) resetStreamBody(node, md);
  const cut = revealBlocks(shown);
  // The finished blocks on screen must still be the first ones of this cut. Fewer means the text shrank; a
  // different one means a paragraph handed over early (OPEN_PREFIX_v1) closed as something else. Same situation.
  const sig = cut.blocks.map(function (b) { return b.kind + '\u0001' + b.text; });
  const had = node._streamSig || [];
  if (sig.length < had.length || had.some(function (s, i) { return s !== sig[i]; })) resetStreamBody(node, md);
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
  // A closed block goes on screen at once, in order, exactly where it belongs.
  const from = node._streamUnits || 0;
  for (let i = from; i < cut.blocks.length; i++) {
    md.insertBefore(buildBlock(cut.blocks[i], false), openEl);
  }
  node._streamUnits = cut.blocks.length;
  node._streamSig = sig;
  // The open block carries the kind being written, so a line that has an action and then speech
  // flows like speech while the speech is the part arriving.
  openEl.setAttribute('data-kind', typeof openKind === 'function' ? openKind(cut.open) : unitKind(cut.open));
  // renderPlainText, not renderMarkdown: an incomplete block has no extent yet, and handing marked
  // a half-written list gives it nothing stable to keep. It is escaping plus a few regexes, and it
  // already renders bold, italics, code and an open fence, so what is on screen is close to final.
  openEl.innerHTML = cut.open ? renderPlainText(closeOpenMarks(cut.open)) : '';
  // STAGE_v1 (app-stage.js): every frame is laid out the way the finished answer will be -- face, narration, bubbles
  if (typeof stageLayout === 'function') stageLayout(md);
  node._streamShown = shown;
  node.classList.add('streaming');
  // After the body, never before: the first paint writes over .md and would take the badge with it.
  // This is the order postProcessAssistant effectively runs in.
  paintExpressionBadge(node, badgeSrc === undefined ? text : badgeSrc);
  placeStreamCaret(md);
  scrollChatToBottom(false);
}

// STREAM_CARET_v1: the caret is an element put right after the last letter on screen, on every paint.
// It used to be a ::after on the last block, which collided with the open block's own ::after (the
// flowing rule, position:absolute) and was drawn at the block's top-left corner -- and an open block
// that had just emptied put it alone on a new line. Placed after the text, it follows the letters
// across blocks; placed after a moving letter rather than inside it, it does not scale with it.
function placeStreamCaret(md) {
  const old = md.querySelector('.stream-caret');
  if (old) old.remove();
  const last = streamLastText(md);
  if (!last || !last.parentNode) return;
  let host = last.parentNode, ref = last.nextSibling;
  if (/\brv-l\b/.test(host.className || '') && host.parentNode) { ref = host.nextSibling; host = host.parentNode; }
  const caret = document.createElement('span');
  caret.className = 'stream-caret';
  caret.setAttribute('aria-hidden', 'true');
  host.insertBefore(caret, ref || null);
}

function streamLastText(el) {
  for (let i = el.childNodes.length - 1; i >= 0; i--) {
    const c = el.childNodes[i];
    if (c.nodeType === 3) { if (c.nodeValue && c.nodeValue.trim()) return c; continue; }
    if (c.nodeType !== 1 || /\b(exp-badge|stream-caret)\b/.test(c.className || '')) continue;
    const t = streamLastText(c);
    if (t) return t;
  }
  return null;
}

// An emphasis still open at the end of the text being written is drawn as closed, so its letters are
// bold or italic from the first one instead of showing ** that vanish when the closer arrives -- a
// jump the reader sees as the bubble changing size. A single * only counts when it opens a word (the
// same flanking rule renderPlainText uses), so 2 * 3 stays arithmetic.
function closeOpenMarks(text) {
  let t = String(text || '');
  if ((t.match(/\*\*/g) || []).length % 2) t = t.replace(/(\s*)$/, '**$1');
  const singles = t.replace(/\*\*/g, '');
  const lastLine = singles.slice(singles.lastIndexOf('\n') + 1);
  const opens = (lastLine.match(/(^|[^*])\*(?=\S)/g) || []).length;
  const closes = (lastLine.match(/\S\*(?!\*)/g) || []).length;
  if (opens > closes && /\S\s*$/.test(t)) t = t.replace(/(\s*)$/, '*$1');
  return t;
}

function resetStreamBody(node, md) {
  md.textContent = '';
  node._streamUnits = 0;
  node._streamSig = [];
  node._streamOpen = null;      // the old open element is detached with the rest of the body
}

function endStreamingContent(node) {
  if (!node) return;
  const caret = node.querySelector && node.querySelector('.stream-caret');
  if (caret) caret.remove();
  node._streamShown = '';
  node._streamUnits = 0;
  node._streamOpen = null;
  node.classList.remove('streaming');
  const md = node.querySelector && node.querySelector('.md');
  if (md) md.classList.remove('md-stream');
}

// CHAR_REVEAL_v1 (2026-09-28): letters arrive one by one, fading and growing in, while the answer
// streams. Three things had kept it from working, and each has its own piece here.
//
// 1. The text arrives in bursts the network chooses. A clock (revealTick) lets it out at an even pace
//    instead: never slower than REVEAL_MIN_CPS, and in proportion to the backlog, so a long burst
//    speeds up and eases out rather than falling behind.
// 2. The block being written is re-rendered every frame, which would restart any animation on it.
//    So every letter remembers when it was born (rv.times, by its position in the rendered text),
//    and a letter's span is given animation-delay = -age: re-created, it carries on where it was.
// 3. A block that closes, and the final render, used to move again. Neither does now: a closed block
//    keeps the letters' clock, and the final render waits until the last letter has settled.
//
// Letters are counted in the rendered text, not the markdown source, so ** and the like cost nothing.
// Reduced motion skips the clock and the spans entirely.
var REVEAL_MS = 320;            // one letter's entrance; chat-log.css .rv-l uses the same
var REVEAL_MIN_CPS = 28;        // letters per second while the model is still speaking
var REVEAL_CATCHUP_MS = 450;    // pace = backlog / this: a burst eases out, shrinking ~2/3 per 450ms
var REVEAL_FINISH_MS = 300;     // the same after the result, a little faster
var REVEAL_FORCE_MS = 4000;     // a hidden tab gets no frames; the final render must not wait on it

function revealNow() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

function revealGraphemes(s) {
  const t = String(s || '');
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    return Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(t), (x) => x.segment);
  }
  return Array.from(t);
}

function revealFrame(fn) {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(fn);
  } else {
    setTimeout(fn, 16);
  }
}

// The whole answer so far. Called on every delta, image and sync poll; the clock does the drawing.
function revealTarget(node, text) {
  if (!node) return;
  if (revealReducedMotion()) { setStreamingContent(node, text); return; }
  let rv = node._rv;
  if (!rv || rv.dead) rv = node._rv = { src: '', gs: [], shown: 0, times: [], carry: 0, last: 0, born: 0, running: false, finish: null };
  // The letters are those of the DISPLAY text: the expression tag, the choices and a thought block
  // never arrive letter by letter. The raw answer is kept for the badge.
  rv.raw = String(text || '');
  const src = prepareStreamText(rv.raw);
  if (src === rv.src) return;
  if (src.indexOf(rv.src) === 0) {
    // An append. The last letter may have been cut mid-grapheme, so it is segmented again with the rest.
    const tail = rv.gs.length ? rv.gs.pop() : '';
    rv.gs.push.apply(rv.gs, revealGraphemes(tail + src.slice(rv.src.length)));
  } else {
    // A rewrite (a resync, a retracted thought). What still matches stays on screen without moving again.
    const gs = revealGraphemes(src);
    let k = 0;
    while (k < rv.shown && k < gs.length && gs[k] === rv.gs[k]) k++;
    rv.gs = gs;
    rv.shown = k;
    rv.times = [];
    setStreamingContent(node, gs.slice(0, k).join(''), rv.raw);
    revealLetters(node, rv, -Infinity);
  }
  rv.src = src;
  revealRun(node, rv);
}

// The result arrived: let the rest out quickly, then hand over to the final render.
function revealFinish(node, text, done) {
  if (!node || revealReducedMotion() || !node._rv || node._rv.dead) { done(); return; }
  revealTarget(node, text);
  const rv = node._rv;
  rv.finish = done;
  setTimeout(function () { revealComplete(node, rv); }, REVEAL_FORCE_MS);
  revealRun(node, rv);
}

// The bubble fits its text, so any reflow would shrink and regrow it. While letters arrive it may
// widen but never narrow; the final render lets go.
function revealHoldWidth(node, rv) {
  const w = node.offsetWidth;
  if (typeof w !== 'number' || w <= (rv.width || 0) || !node.style) return;
  rv.width = w;
  node.style.minWidth = 'min(' + w + 'px, 100%)';
}

function revealComplete(node, rv) {
  if (rv.completed) return;
  rv.completed = true;
  if (node.style) node.style.minWidth = '';
  rv.dead = true;
  if (node._rv === rv) node._rv = null;
  if (rv.finish) rv.finish();
}

function revealRun(node, rv) {
  if (rv.running) return;
  rv.running = true;
  revealFrame(function () { revealTick(node, rv); });
}

function revealTick(node, rv) {
  rv.running = false;
  if (rv.dead) { if (rv.finish && !rv.completed) revealComplete(node, rv); return; }
  if (!node.isConnected && node.isConnected !== undefined) { revealComplete(node, rv); return; }
  const now = revealNow();
  const dt = rv.last ? Math.min(100, now - rv.last) : 16;
  rv.last = now;
  const backlog = rv.gs.length - rv.shown;
  if (backlog > 0) {
    const cps = Math.max(REVEAL_MIN_CPS, backlog * 1000 / (rv.finish ? REVEAL_FINISH_MS : REVEAL_CATCHUP_MS));
    rv.carry += cps * dt / 1000;
    let step = Math.floor(rv.carry);
    if (step < 1 && !rv.shown) step = 1;               // the first letter never waits
    if (step > 0) {
      rv.carry -= step;
      rv.shown = Math.min(rv.gs.length, rv.shown + step);
      setStreamingContent(node, rv.gs.slice(0, rv.shown).join(''), rv.raw);
      revealLetters(node, rv, now);
      revealHoldWidth(node, rv);
    }
  }
  if (rv.shown < rv.gs.length) { revealRun(node, rv); return; }
  if (now - rv.born < REVEAL_MS) { revealRun(node, rv); return; }   // let the last letters settle
  revealLetters(node, rv, now);                         // and turn them back into plain text
  if (rv.finish) revealComplete(node, rv);
  else rv.last = 0;                                     // idle until the next delta wakes it
}

// Give every letter younger than REVEAL_MS a span that continues its entrance, and turn a span whose
// entrance is over back into plain text, so a long answer does not carry a span per letter.
// `now` = -Infinity marks every letter present as already arrived (a rewrite keeps what it kept).
function revealLetters(node, rv, now) {
  const md = node.querySelector && node.querySelector('.md');
  if (!md) return;
  let index = 0;
  const visit = function (el) {
    for (let i = 0; i < el.childNodes.length; i++) {
      const c = el.childNodes[i];
      if (c.nodeType === 1) {
        const cls = c.className || '';
        if (/\b(exp-badge|stream-caret)\b/.test(cls)) continue;   // not part of the text
        if (/\brv-l\b/.test(cls)) {                    // a letter already carrying its motion
          if (now - c._rvBorn >= REVEAL_MS) { el.replaceChild(document.createTextNode(c.textContent), c); }
          index++;
          continue;
        }
        visit(c);
        continue;
      }
      if (c.nodeType !== 3 || !c.nodeValue) continue;
      const gs = revealGraphemes(c.nodeValue);
      const ages = [];
      let young = false;
      for (let k = 0; k < gs.length; k++) {
        if (!gs[k].trim()) { ages.push(null); continue; }
        if (rv.times[index] === undefined) {
          rv.times[index] = now;
          if (now > rv.born) rv.born = now;
        }
        const age = now - rv.times[index];
        ages.push(age);
        if (age < REVEAL_MS) young = true;
        index++;
      }
      if (!young) continue;
      const frag = document.createDocumentFragment();
      let word = null;
      let parts = 0;
      gs.forEach(function (g, k) {
        if (ages[k] === null) { word = null; frag.appendChild(document.createTextNode(g)); parts++; return; }
        if (!word) { word = document.createElement('span'); word.className = 'rv-w'; frag.appendChild(word); parts++; }
        if (ages[k] >= REVEAL_MS) { word.appendChild(document.createTextNode(g)); return; }
        const l = document.createElement('span');
        l.className = 'rv-l';
        l.style.animationDelay = (-Math.round(ages[k])) + 'ms';
        l._rvBorn = now - ages[k];
        l.textContent = g;
        word.appendChild(l);
      });
      el.replaceChild(frag, c);
      i += parts - 1;                                   // step over what was just put in its place
    }
  };
  visit(md);
  placeStreamCaret(md);   // the text nodes it sat beside may just have been re-wrapped
}

function bindEvents(sid) {
  if (window.__chatEsTimer) { clearTimeout(window.__chatEsTimer); window.__chatEsTimer = null; }
  if (es) { try { es.close(); } catch (_) {} es = null; }
  const live = logEl && logEl.querySelector('.msg[data-live="1"]');
  if (live && live.isConnected) assistantNode = live;
  else { assistantNode = null; assistantBuf = ''; }
  es = new EventSource(BASE_PATH + '/api/sessions/' + encodeURIComponent(sid) + '/events');
  es.onmessage = (ev) => {
    lastStreamAt = Date.now();   // SYNC_THROTTLE_v1
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
        revealTarget(assistantNode, assistantBuf);   // STREAM_FLOW_v1: still speaking (CHAR_REVEAL_v1 clock)
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
      if (typeof thinkEnd === 'function') thinkEnd(assistantNode);   // THINKING_VIEW_v1: the answer started
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
      // An empty answer so far (a work turn sends its first deltas before any text): the old page says so in words;
      // the messenger shell draws nothing, and the typing dots beside the face stay (app-stage.js stageTyping).
      const paintBuf = assistantBuf || (typeof shellOn === 'function' && shellOn() ? '' : '작성 중…');
      scheduleStreamPaint(function () {
        // A turn that ended between the delta and this frame must not be painted into.
        if (!paintNode || paintNode.dataset.live !== '1') return;
        revealTarget(paintNode, paintBuf);   // CHAR_REVEAL_v1: the letter clock draws it
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
      if (typeof thinkEnd === 'function') thinkEnd(assistantNode);
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
        if (typeof retryAnswered === 'function') retryAnswered();
        const node = doneNode || addChat('assistant', '', false);
        // Stamped now, so a resync recognises this bubble while its last letters are still arriving.
        if (data.ts) {
          node.dataset.ts = String(data.ts);
          node.dataset.syncRole = 'assistant';
        }
        delete node.dataset.live;
        const usage = data.usage, secs = data.duration_seconds, served = data.served_model;
        // CHAR_REVEAL_v1: the final render waits for the last letter, or it would cut the reveal short.
        revealFinish(node, doneBuf, function () {
          setAssistantContent(node, doneBuf, true, usage, secs, served);
          endStreamingContent(node);   // STREAM_FLOW_v1: the finished message is still; no motion
          // The letters already arrived; the last block must not arrive a second time.
          if (node.querySelectorAll) node.querySelectorAll('.md-block.arrive').forEach(function (b) { b.classList.remove('arrive'); });
        });
      } else if (residualErr || data.notice === 'error') {
        if (doneNode) doneNode.remove();
        addNotice((data.notice || 'error'), residualErr || text || '알 수 없는 오류', data.ts);
        if (typeof offerRetry === 'function') offerRetry();   // RETRY_LAST_v1
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

    if (type === 'room_moved') {
      // ROOM_SYNC_v1 (2026-09-30): another window moved this room (work <-> private). Follow it, so this window
      // cannot offer the old room's move a second time. The window that moved knows its own client_mid and sends
      // the scene line itself; a follower sends none.
      if (data.client_mid && myPendingMids.has(data.client_mid)) { myPendingMids.delete(data.client_mid); return; }
      if (data.to && data.to !== sessionId && typeof applyModeSwitch === 'function') {
        applyModeSwitch({ session: { id: data.to, mode: data.mode, character: data.character } });
      }
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
      lastStopNoticeAt = Date.now();   // STOP_NOTICE_ONCE_v1: the stop button's own notice stands down
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
      } else if (assistantNode) {
        // No text yet. The stop button may sit in the typing dots: park it before its holder goes. A bubble that
        // holds what the brain was thinking keeps it (folded, not live); one with nothing in it goes, no ghost.
        if (typeof parkStopBtn === 'function') parkStopBtn();
        const strip = typeof thinkStrip === 'function' ? thinkStrip(assistantNode, false) : null;
        if (strip) {
          if (typeof thinkEnd === 'function') thinkEnd(assistantNode);
          delete assistantNode.dataset.live;
        } else {
          assistantNode.remove();
        }
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

    // THINKING_VIEW_v1: the brain's reasoning goes into a folding strip over the answer (app-think.js)
    if (type === 'thinking') {
      setBusy(true);
      if (!assistantNode) {
        assistantNode = addChat('assistant', '', false);
        assistantNode.dataset.live = '1';
      }
      if (typeof thinkAppend === 'function') thinkAppend(assistantNode, text);
      return;
    }

    // SILENT_NOTICE_v1: the server says the turn has been quiet a while; it goes on (not an error, no bubble)
    if (type === 'progress') { setProgress(text || ''); return; }
    if (type === 'office') { if (typeof officeDraw === 'function') officeDraw(data.msg); return; }   // inbox/E

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
        if (typeof thinkEnd === 'function') thinkEnd(assistantNode);
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
        if (typeof offerRetry === 'function') offerRetry();   // RETRY_LAST_v1
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
    if (typeof officeLoad === 'function') officeLoad();   // coworkers' turns at this desk, again after a restart (inbox/E)
  };
  startSessionSyncLoop();
}

// REVIVE_TOAST_v1 (#224): the first SSE open only records the server's boot_ts;
// a later open that sees a different one means the host restarted, so flash
// '엔진 리부트 완료 ✦' in the progress bar. No boot_ts (older server) -> nothing.
let lastBootTs = null;
async function checkRevived() {
  let ts, fp;
  try { const h = await api('/healthz', { timeoutMs: 5000 }); ts = h.boot_ts; fp = h.static; } catch (_) { return; }
  if (!ts) return;
  const revived = lastBootTs !== null && ts !== lastBootTs;
  lastBootTs = ts;
  if (!revived) { if (typeof notePageAssets === 'function') notePageAssets(fp); return; }
  if (typeof reloadIfAssetsChanged === 'function' && reloadIfAssetsChanged(fp)) return;   // ASSET_RELOAD_v1
  const msg = '엔진 리부트 완료 ✦';
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
