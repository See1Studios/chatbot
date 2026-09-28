"""The answer is the finished thing while it is still arriving (REVEAL_BLOCKS_v1).

Three complaints had one cause, and this is the file that holds the line on it.

A stream printed plain text and turned into markdown at the end, so the end was a swap rather than
an arrival. The entrance used to run on whatever one paint delivered, which measured at a median of
one character and was therefore invisible at any frame rate. And nothing moved while the text was
being written.

A markdown block has an extent, and once that extent has arrived the block can never change again.
So a block is rendered the moment it closes -- the same render the final pass makes -- and the
per-frame work drops to the single block still being written. The cost is per BLOCK, not per frame,
which is the property worth asserting: two hundred deltas that close twenty blocks must produce
twenty renders, not two hundred and not one.

Run: python3 -m unittest tests.test_streaming_text  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import app_bundle  # noqa: E402

CODE = Path(__file__).resolve().parent.parent
APP = app_bundle()
# markdown.js is not part of the app-*.js bundle the stub DOM loads, so the cheap renderer the open
# block uses is sliced straight out of its real source. Testing a copy of it would test the copy.
MARKDOWN = CODE / "static" / "markdown.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('var streamPaintQueued');
const b = src.indexOf('\nfunction bindEvents(sid)');
if (a < 0 || b < 0) throw new Error('STREAM_FLOW block markers missing');
const code = src.slice(a, b);

// The real block classifier, out of the bundle: the reveal boundary and the kind being written are
// the whole mechanism, and a stubbed version of them would test the stub.
const ba = src.indexOf('const BLOCK_NARRATION');
const bb = src.indexOf('// ==== file:', ba);
if (ba < 0 || bb < 0) throw new Error('BLOCK_KINDS markers missing');
eval(src.slice(ba, bb));

function el(tag) {
  const e = {
    tag, className: '', children: [], attrs: {}, dataset: {}, handlers: {},
    // className and classList are one thing in a browser. The stub used to keep them apart, which
    // hid every assertion about a class the code adds rather than assigns.
    classList: {
      _set() { return new Set((e.className || '').split(' ').filter(Boolean)); },
      _put(s) { e.className = [...s].join(' '); },
      add(...c) { const s = this._set(); c.forEach(x => s.add(x)); this._put(s); },
      remove(...c) { const s = this._set(); c.forEach(x => s.delete(x)); this._put(s); },
      contains(c) { return this._set().has(c); },
    },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(t, f) { e.handlers[t] = f; },
    appendChild(c) { e.children.push(c); return c; },
    insertBefore(c, ref) {
      const i = e.children.indexOf(ref);
      e.children.splice(i < 0 ? e.children.length : i, 0, c);
      return c;
    },
    all(sel) {
      const cls = sel.replace(/^\./, '');
      const out = [];
      (function walk(n) { for (const c of n.children) { if ((c.className || '').split(' ').includes(cls)) out.push(c); walk(c); } })(e);
      return out;
    },
    querySelector(sel) { return e.all(sel)[0] || null; },
    querySelectorAll(sel) { return e.all(sel); },
  };
  e.remove = function () { if (e.parentNode) { e.parentNode.children = e.parentNode.children.filter(x => x !== e); } e.parentNode = null; };
  Object.defineProperty(e, 'textContent', {
    get() { return (e._text || '') + e.children.map(c => c.textContent || '').join(''); },
    set(v) { e._text = v; e.children = []; },
  });
  let html = null;
  Object.defineProperty(e, 'innerHTML', {
    get() { return html === null ? e.textContent : html; },
    set(v) { html = v; e._text = visibleText(v); e.children = []; },
  });
  return e;
}

// A browser parses innerHTML into child nodes; the stub cannot, so it reproduces what the reader
// would see instead: <br> is a line break and the four escaped entities come back as themselves.
function visibleText(h) {
  return String(h == null ? '' : h)
    .replace(/<br\s*\/?>/g, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}

const document = { createElement: el };
let frames = [];
const window = {
  requestAnimationFrame(cb) { frames.push(cb); return frames.length; },
  cancelAnimationFrame() {},
  // The reveal is one beat behind the text, so the tests have to be able to wind the clock
  // themselves rather than wait on it.
  matchMedia: (q) => ({ matches: /reduce/.test(q) ? REDUCE_MOTION : false }),
};
let REDUCE_MOTION = false;
let timers = [];
let clock = 0;
global.setTimeout = (fn, ms) => { timers.push({ at: clock + (ms || 0), fn }); return timers.length; };
global.clearTimeout = (id) => { if (timers[id - 1]) timers[id - 1].fn = null; };
// Run every timer due within `ms` of now, in order, and return how many fired.
const advance = (ms) => {
  const until = clock + ms;
  let fired = 0;
  for (;;) {
    const due = timers.filter(t => t.fn && t.at <= until).sort((x, y) => x.at - y.at)[0];
    if (!due) break;
    const run = due.fn; due.fn = null;   // one shot, or the loop refires it forever
    run(); fired++; clock = due.at;
  }
  clock = until;
  return fired;
};
const scrolls = [];
function scrollChatToBottom() { scrolls.push(1); }

// marked and the sanitiser are never reached: a closed block is one renderMarkdown call, and the
// stub counts them, which is the number the test asserts on.
let markedCalls = 0, purifyCalls = 0, renderMarkdownCalls = 0, postProcessCalls = 0;
const marked = { parse() { markedCalls++; return '<p>MARKDOWN</p>'; } };
const DOMPurify = { sanitize(h) { purifyCalls++; return h; } };
function renderMarkdown(t) { renderMarkdownCalls++; return '<p>' + t + '</p>'; }
function postProcessAssistant() { postProcessCalls++; }

// app-messages.js's helpers. buildBlock is stood in for, because the real one moves parsed nodes
// around and the stub cannot parse -- what matters here is WHICH renderer a block went through.
function markArrive(el, kind) {
  el.setAttribute('data-kind', kind || 'narration');
  el.classList.add('arrive');
  el.addEventListener('animationend', function () { el.classList.remove('arrive'); }, { once: true });
}
function buildBlock(block, isFinal) {
  const box = document.createElement('div');
  box.className = 'md-block';
  box.setAttribute('data-kind', block.kind);
  // The real one renders each run; the stub cannot parse the result, but it must still pay the
  // call, because "one renderMarkdown per run" is the cost the test is about.
  blockRuns(block).forEach(run => { renderMarkdown(run.text); });
  box._text = block.text;
  box._viaBlockRenderer = true;
  return box;
}

const EXPRESSION_EMOJIS = { joy: '\u{1F60A}', sad: '\u{1F622}' };
function splitChoices(src) { return { text: src.replace(/\s*<!--\s*choices\s*:[\s\S]*?-->\s*$/, ''), choices: [] }; }
function parseExpression(text) {
  const m = /^\s*\[expression:\s*(\w+)\]/.exec(text || '');
  return m ? { expression: m[1], text: text.slice(m[0].length) } : { expression: '', text: text || '' };
}
function parseThought(text, streaming) {
  if (!streaming) return { thought: '', cleanText: text || '' };
  return { thought: '', cleanText: (text || '').replace(/```thought[\s\S]*?```/g, '') };
}
function paintExpressionBadge(node, rawText) {
  const parsed = parseExpression(rawText);
  if (!parsed.expression) return;
  const md = node.querySelector('.md') || node;
  let badge = node.querySelector('.exp-badge');
  if (!badge) { badge = document.createElement('span'); badge.className = 'badge exp-badge'; md.insertBefore(badge); }
  badge.textContent = EXPRESSION_EMOJIS[parsed.expression] || parsed.expression;
}
function prepareStreamText(src) {
  let raw = splitChoices(src || '').text;
  const p = parseExpression(raw);
  if (p.expression) raw = p.text;
  const t = parseThought(raw, true);
  if (t.thought || t.cleanText !== raw) raw = t.cleanText;
  return raw;
}

// PLAIN_RENDER_v1, the real one -- only the block being written uses it.
const md = fs.readFileSync(process.argv[3], 'utf8');
const ra = md.indexOf('function renderPlainText');
if (ra < 0) throw new Error('renderPlainText missing from markdown.js');
const rb = md.indexOf('\n}', md.indexOf('return t;', ra)) + 2;
function absArtifact(p) { return p; }
eval(md.slice(ra, rb));

eval(code);

const flush = () => { const q = frames; frames = []; q.forEach(f => f()); return q.length; };
const newBubble = () => { const n = el('div'); n.className = 'msg assistant'; n.dataset.live = '1'; return n; };
const body = (n) => n.querySelector('.md');
const blocks = (n) => body(n).children.filter(c => /\bmd-block\b/.test(c.className));
const landed = (n) => blocks(n).filter(c => /\barrive\b/.test(c.className));
const openOf = (n) => blocks(n).filter(c => /\bopen\b/.test(c.className))[0] || null;
const text = (n) => {
  const b = body(n);
  const parts = [];
  if (b._text) parts.push(b._text);
  b.children.filter(c => !/\bexp-badge\b/.test(c.className)).forEach(c => parts.push(c.textContent));
  return parts.join('');
};
const htmlOf = (n) => body(n).children.filter(c => !/\bexp-badge\b/.test(c.className))
  .map(c => c.innerHTML).join('');

// Twenty paragraphs of ten characters, the shape an answer of this protocol actually has.
const PARAS = 20, WIDTH = 10;
const FULL = Array.from({ length: PARAS }, () => '가'.repeat(WIDTH)).join('\n\n');

const CASES = {
  coalesces: () => {
    const n = newBubble();
    // The paint reads the buffer when the frame runs, not the value at the moment it was
    // scheduled -- that is how app-sse.js does it, and it is the whole point: every delta, one
    // paint, and the paint shows everything that arrived.
    let paintBuf = '';
    for (let i = 1; i <= FULL.length; i++) {
      paintBuf = FULL.slice(0, i);
      scheduleStreamPaint(() => setStreamingContent(n, paintBuf));
    }
    const framesQueued = frames.length;
    flush();
    advance(6000);
    return { deltas: FULL.length, frames_queued: framesQueued, chars: text(n).length,
             landed: landed(n).length, blocks: blocks(n).length };
  },
  cost_is_per_block_not_per_frame: () => {
    // The invariant that replaced "never render markdown while streaming": two hundred deltas
    // closing twenty blocks cost twenty renders, not two hundred and not one.
    const n = newBubble();
    let paintBuf = '';
    for (let i = 1; i <= FULL.length; i++) {
      paintBuf = FULL.slice(0, i);
      scheduleStreamPaint(() => setStreamingContent(n, paintBuf));
    }
    flush();
    advance(6000);
    return { deltas: FULL.length, renders: renderMarkdownCalls, marked: markedCalls,
             purify: purifyCalls, postProcess: postProcessCalls, landed: landed(n).length };
  },
  a_closed_block_uses_the_real_renderer: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n\n둘');
    advance(2000);
    const done = blocks(n).filter(c => c._viaBlockRenderer);
    const open = openOf(n);
    return { closed: done.map(c => c.textContent), closed_kinds: done.map(c => c.getAttribute('data-kind')),
             open_text: open ? open.textContent : null, open_is_plain: open ? !open._viaBlockRenderer : null };
  },
  the_open_block_is_visible_and_does_not_animate: () => {
    const n = newBubble();
    setStreamingContent(n, '다 쓰이는 중');
    const open = openOf(n);
    return { text: text(n), cls: open ? open.className : null,
             kind: open ? open.getAttribute('data-kind') : null,
             landed: landed(n).length };
  },
  the_open_block_is_last_so_the_caret_finds_it: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n\n둘\n\n셋');
    advance(2000);
    const kids = body(n).children;
    return { last_is_open: /\bopen\b/.test(kids[kids.length - 1].className) };
  },
  the_open_block_carries_the_kind_being_written: () => {
    const seen = [];
    for (const t of ['*눈을', '*눈을 깜빡*', '"안녕', '"안녕"']) {
      const b = newBubble();
      setStreamingContent(b, t);
      seen.push(openOf(b) ? openOf(b).getAttribute('data-kind') : null);
    }
    return seen;
  },
  each_block_animates_exactly_once: () => {
    const n = newBubble();
    setStreamingContent(n, '*고개를*\n\n둘');
    advance(2000);
    const el0 = landed(n)[0];
    const before = el0.className;
    const listened = typeof el0.handlers['animationend'];
    el0.handlers['animationend']();          // the browser fires this; the stub does not
    return { before, listened, after: el0.className, kind: el0.getAttribute('data-kind') };
  },
  a_block_is_a_whole_block_and_not_a_fragment: () => {
    const n = newBubble();
    setStreamingContent(n, FULL);
    advance(6000);
    const sizes = landed(n).map(c => c.textContent.length);
    return { count: sizes.length, min: Math.min(...sizes), max: Math.max(...sizes) };
  },
  // --- the beat: the appearance lags the text, one block at a time ---
  the_appearance_lags_the_text: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n\n둘\n\n셋\n\n넷');
    const marks = [];
    marks.push(landed(n).length);                       // closed but not on screen yet
    advance(1); marks.push(landed(n).length);           // a timer of 200ms has not come due
    advance(199); marks.push(landed(n).length);
    advance(1); marks.push(landed(n).length);           // the first tick
    advance(1000); marks.push(landed(n).length);
    return marks;
  },
  the_order_is_kept_while_it_lags: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n\n둘\n\n셋');
    advance(6000);
    return landed(n).map(c => c.textContent);
  },
  the_open_text_waits_for_its_turn: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n\n아직 쓰는 중');
    const before = openOf(n).textContent;
    advance(6000);
    return { before, after: openOf(n).textContent };
  },
  a_backlog_drains_faster_than_one_per_beat: () => {
    const n = newBubble();
    setStreamingContent(n, FULL);
    const queued = (n._streamQueue || []).length;
    const firstDelay = timers.filter(t => t.fn).map(t => t.at - clock)[0];
    let spent = 0;
    while ((n._streamQueue || []).length && spent < 30000) { spent += advance(60); }
    return { queued, firstDelay, drain_ms: spent, total: landed(n).length };
  },
  reduced_motion_gets_no_beat: () => {
    REDUCE_MOTION = true;
    const n = newBubble();
    setStreamingContent(n, '하나\n\n둘\n\n셋');
    // No .arrive, because there is no animation -- but on screen, and with no timer pending.
    const out = { on_screen: blocks(n).length, pending: (n._streamQueue || []).length,
                  timers: timers.filter(t => t.fn).length };
    REDUCE_MOTION = false;
    return out;
  },
  rewrite_restarts_the_body: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n\n둘\n\n셋');
    advance(6000);
    const before = text(n);
    setStreamingContent(n, '처음부터\n\n다시');
    const justAfter = { text: text(n), blocks: blocks(n).length, units: n._streamUnits };
    advance(2000);
    return { before, justAfter, after: text(n), blocks: blocks(n).length,
             streaming: n.classList.contains('streaming') };
  },
  equal_text_does_not_touch_dom: () => {
    const n = newBubble();
    setStreamingContent(n, '같은내용\n\n둘째');
    advance(2000);
    const before = body(n).children.length;
    setStreamingContent(n, '같은내용\n\n둘째');
    return { before, after: body(n).children.length };
  },
  stripped_tags: () => {
    const n = newBubble();
    setStreamingContent(n, '[expression: joy]안녕');
    const b = n.querySelector('.exp-badge');
    return { shown: text(n), badge: b ? b.textContent : null };
  },
  hides_thought: () => {
    const n = newBubble();
    setStreamingContent(n, '보이는말\n```thought\n숨겨질말\n```');
    advance(2000);
    return { shown: text(n).replace(/\n/g, '\\n') };
  },
  caret_class_on: () => {
    const n = newBubble();
    setStreamingContent(n, '말하는중');
    return { streaming: n.classList.contains('streaming'), md_stream: body(n).classList.contains('md-stream') };
  },
  finished_is_still: () => {
    const n = newBubble();
    setStreamingContent(n, '다 끝났어\n\n마지막');
    endStreamingContent(n);
    return { streaming: n.classList.contains('streaming'), md_stream: body(n).classList.contains('md-stream'),
             // A turn that ends with a backlog must not leave the last paragraph invisible: the
             // entrance is dropped, not the text.
             shown: text(n), remembered: n._streamShown, units: n._streamUnits, open: n._streamOpen,
             queue: n._streamQueue.length, timer: n._streamTimer };
  },
  cancel_stops_the_frame: () => {
    const n = newBubble();
    scheduleStreamPaint(function () { setStreamingContent(n, '늦게도착\n\n끝'); });
    const queued = frames.length;
    cancelStreamPaint();
    const after = frames.length;
    return { queued, after, shown: text(n) };
  },
  // --- PLAIN_RENDER_v1: the block being written is already close to its finished shape ---
  bold_while_streaming: () => {
    const n = newBubble();
    setStreamingContent(n, '**중요**한 일');
    return { shown: text(n), html: htmlOf(n) };
  },
  action_italic_while_streaming: () => {
    const n = newBubble();
    setStreamingContent(n, '*고개를 기울이며*');
    return { shown: text(n), html: htmlOf(n) };
  },
  open_code_fence_while_streaming: () => {
    const n = newBubble();
    setStreamingContent(n, '```py\nprint(1)');
    return { html: htmlOf(n), tag: openOf(n) ? openOf(n).tag : null };
  },
  markup_cannot_inject: () => {
    const n = newBubble();
    setStreamingContent(n, '<img src=x onerror=alert(1)>');
    return { shown: text(n), html: htmlOf(n) };
  },
  arithmetic_asterisks_stay_literal: () => {
    const n = newBubble();
    setStreamingContent(n, '2 * 3 * 4 라고 했다');
    return { shown: text(n), html: htmlOf(n) };
  },
};
console.log(JSON.stringify(CASES[process.argv[2]]()));
"""


def run(case):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not installed")
    proc = subprocess.run([node, "-e", HARNESS, str(APP), case, str(MARKDOWN)],
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        raise AssertionError("node failed for %s: %s" % (case, proc.stderr.strip()[:600]))
    return json.loads(proc.stdout.strip().splitlines()[-1])


class StreamingText(unittest.TestCase):
    # --- REVEAL_BLOCKS_v1: the cost and the shape of the reveal ---

    def test_two_hundred_deltas_cost_one_frame(self):
        out = run("coalesces")
        self.assertEqual(out["frames_queued"], 1,
                         "%d deltas queued %d paints" % (out["deltas"], out["frames_queued"]))
        self.assertEqual(out["blocks"], 20, "twenty paragraphs plus the open one")
        self.assertEqual(out["landed"], 19, "the twentieth paragraph is still being written")
        self.assertEqual(out["chars"], 20 * 10, "the open block is visible, not withheld")

    def test_the_cost_is_one_render_per_block_and_not_per_frame(self):
        out = run("cost_is_per_block_not_per_frame")
        # This replaced "the streaming path never touches markdown", which was true when a block
        # could not be told from a chunk and false the moment one could. The number that matters is
        # the shape, not the absolute: two hundred-odd deltas closing twenty blocks must cost
        # twenty renders, not one per delta.
        self.assertEqual(out["renders"], out["landed"],
                         "%d deltas cost %d renders for %d blocks"
                         % (out["deltas"], out["renders"], out["landed"]))
        self.assertEqual(out["renders"], 19)
        self.assertLess(out["renders"], out["deltas"] // 10,
                        "the cost has to track the block count, not the delta count")
        self.assertEqual((out["marked"], out["purify"], out["postProcess"]), (0, 0, 0),
                         "the render has to be the one renderMarkdown makes, not marked directly")

    def test_a_closed_block_is_rendered_as_markdown_and_the_open_one_is_not(self):
        out = run("a_closed_block_uses_the_real_renderer")
        self.assertEqual(out["closed"], ["하나"], "one paragraph is closed, the other is not")
        self.assertEqual(out["closed_kinds"], ["narration"])
        self.assertEqual(out["open_text"], "둘")
        self.assertTrue(out["open_is_plain"],
                        "an incomplete block goes through the cheap renderer, not marked")

    def test_the_open_block_is_visible_and_does_not_animate(self):
        out = run("the_open_block_is_visible_and_does_not_animate")
        self.assertEqual(out["text"], "다 쓰이는 중",
                         "the block being written must be on screen; withholding it was a "
                         "compromise the block boundary made unnecessary")
        self.assertEqual(out["landed"], 0, "an entrance on text already on screen is the flicker")
        self.assertIn("open", out["cls"])

    def test_the_open_block_is_the_last_child_so_the_caret_finds_it(self):
        out = run("the_open_block_is_last_so_the_caret_finds_it")
        self.assertTrue(out["last_is_open"], "the caret is a ::after on .md > *:last-child")

    def test_the_open_block_carries_the_kind_being_written(self):
        out = run("the_open_block_carries_the_kind_being_written")
        # The motion says what is being written, not what dominates the line: an action that has
        # become speech flows as speech, because the speech is the part still arriving. A quote with
        # no closing mark yet is narration -- a kind is only known once its extent has arrived, and
        # guessing where a sentence was meant to end is how a stray quote mark gets left on screen.
        self.assertEqual(out, ["narration", "action", "narration", "dialogue"])

    def test_each_block_animates_exactly_once(self):
        out = run("each_block_animates_exactly_once")
        self.assertEqual(out["before"], "md-block arrive")
        self.assertTrue(out["listened"], "the class has to come off, or a later render replays it")
        self.assertEqual(out["after"], "md-block")
        self.assertEqual(out["kind"], "action", "the landing is chosen by kind, not one size for all")

    def test_the_animating_unit_is_a_whole_block(self):
        # The assertion that would have caught the original: the entrance used to run on whatever
        # one paint delivered -- median one character -- and no frame rate changes that.
        out = run("a_block_is_a_whole_block_and_not_a_fragment")
        self.assertEqual(out["count"], 19)
        self.assertEqual((out["min"], out["max"]), (10, 10))

    # --- the beat: the appearance lags the text, one block at a time ---

    def test_the_appearance_lags_the_text_by_about_a_beat(self):
        # Racing the stream is what made it strobe: a fade firing on every block closure overlaps the
        # next one, and half-finished fades stacked on each other read as shimmer. Putting the
        # appearance a beat behind means the text is already still and readable when it moves, and
        # exactly one entrance is ever in flight.
        out = run("the_appearance_lags_the_text")
        self.assertEqual(out[0], 0, "three closed blocks, none on screen yet")
        self.assertEqual(out[1], 0, "the first tick is 200ms out")
        self.assertEqual(out[2], 2, "by 200ms the backlog is draining, at the floor not the beat")
        self.assertEqual(out[4], 3)

    def test_the_order_is_kept_while_it_lags(self):
        self.assertEqual(run("the_order_is_kept_while_it_lags"), ["하나", "둘"])

    def test_the_block_being_written_waits_for_its_turn(self):
        # Otherwise the tail of the answer sits above the middle of it for a beat, and the text
        # arrives out of order -- which is the one thing the lag must not cost.
        out = run("the_open_text_waits_for_its_turn")
        self.assertEqual(out["before"], "", "a queued block comes before the open one, so it waits")
        self.assertEqual(out["after"], "아직 쓰는 중")

    def test_a_backlog_drains_at_the_floor_and_not_at_the_beat(self):
        out = run("a_backlog_drains_faster_than_one_per_beat")
        self.assertEqual(out["queued"], 19)
        self.assertEqual(out["firstDelay"], 55,
                         "a burst must not turn into a 200ms-per-block crawl")
        self.assertEqual(out["total"], 19)
        self.assertLess(out["drain_ms"], 19 * 200, "the lag has to stay bounded on a long answer")

    def test_reduced_motion_gets_no_beat_at_all(self):
        # There is no animation to smooth out, so the beat would be pure latency for someone who
        # asked for none.
        out = run("reduced_motion_gets_no_beat")
        self.assertEqual(out["on_screen"], 3, "everything is on screen at once")
        self.assertEqual(out["pending"], 0)
        self.assertEqual(out["timers"], 0, "no reveal timer may be left running")

    def test_a_rewritten_draft_restarts_the_body(self):
        out = run("rewrite_restarts_the_body")
        self.assertEqual(out["before"], "하나둘셋", "two closed paragraphs and the open third")
        self.assertEqual(out["justAfter"]["text"], "", "the stale text is gone at once")
        self.assertEqual(out["justAfter"]["blocks"], 1, "only the fresh open block, nothing stale")
        self.assertEqual(out["justAfter"]["units"], 1, "the count restarts from the new answer")
        self.assertEqual(out["after"], "처음부터다시", "and the new answer then arrives in order")
        self.assertEqual(out["blocks"], 2, "one closed paragraph and the open one, nothing stale")
        self.assertTrue(out["streaming"], "the caret class must survive a rewrite")
    def test_an_unchanged_buffer_does_not_touch_the_dom(self):
        out = run("equal_text_does_not_touch_dom")
        self.assertEqual(out["before"], out["after"])

    def test_the_expression_badge_appears_while_still_streaming(self):
        out = run("stripped_tags")
        self.assertEqual(out["shown"], "안녕", "the tag must be stripped from the visible text")
        self.assertEqual(out["badge"], "\U0001F60A")

    def test_a_thought_block_stays_hidden_until_the_message_ends(self):
        out = run("hides_thought")
        self.assertEqual(out["shown"], "보이는말")

    def test_the_existing_cursor_class_is_set_during_streaming(self):
        out = run("caret_class_on")
        self.assertTrue(out["streaming"], "no .streaming class means the existing caret never shows")
        self.assertTrue(out["md_stream"])

    def test_every_live_render_goes_through_the_streaming_paint(self):
        """A live region has more than one writer.

        The delta branch was converted first and the flow still did not show: the sync poll and the
        image event also write the live body, on timers, and rendering either through the final path
        replaced the bubble and took the reveal with it. This pins the rule so the next writer added
        to this region cannot reintroduce it.
        """
        import re
        offenders = []
        for name in ("app-sse.js", "app-session.js"):
            text = (CODE / "static" / name).read_text(encoding="utf-8")
            for no, line in enumerate(text.splitlines(), 1):
                if re.search(r"setAssistantContent\([^)]*,\s*false\s*\)", line):
                    offenders.append("%s:%d: %s" % (name, no, line.strip()[:70]))
        self.assertEqual(offenders, [],
                         "a live render still goes through the final path, which erases the reveal: %s" % offenders)

    def test_a_finished_message_is_left_completely_still(self):
        out = run("finished_is_still")
        self.assertFalse(out["streaming"], "the finished message is still motion")
        self.assertFalse(out["md_stream"])
        self.assertEqual(out["remembered"], "")
        self.assertEqual(out["units"], 0, "the count has to reset with the rest of the streaming state")
        self.assertIsNone(out["open"], "the open element is detached by the final render")
        # A turn that ends with a backlog, or ends badly with no `result` to rebuild the body, must
        # not leave the last paragraph of the answer permanently invisible. The motion is dropped,
        # not the text.
        self.assertEqual(out["shown"], "다 끝났어마지막")
        self.assertEqual((out["queue"], out["timer"]), (0, None))

    # --- PLAIN_RENDER_v1: the block being written is already close to its finished shape ---

    def test_bold_is_bold_while_it_is_still_streaming(self):
        out = run("bold_while_streaming")
        self.assertIn("<strong>중요</strong>", out["html"],
                      "raw ** arriving mid-stream is exactly the swap the operator felt")
        self.assertEqual(out["shown"], "중요한 일")

    def test_an_action_is_italic_while_it_is_still_streaming(self):
        out = run("action_italic_while_streaming")
        self.assertIn("<em>고개를 기울이며</em>", out["html"],
                      "RENDER_PROTOCOL writes actions in single asterisks; they must read as actions")
        self.assertEqual(out["shown"], "고개를 기울이며")

    def test_a_code_fence_is_a_code_block_before_it_is_closed(self):
        out = run("open_code_fence_while_streaming")
        self.assertIn("<pre><code>", out["html"],
                      "a fence with no closing ``` yet is the normal mid-stream state")
        self.assertEqual(out["tag"], "div", "a <pre> inside a <span> is invalid nesting")

    def test_rendering_while_streaming_cannot_inject_markup(self):
        out = run("markup_cannot_inject")
        # The input has no markdown in it, so the renderer must produce no tags at all -- every
        # angle bracket it emitted would be one it invented. Escaping first is the whole safety
        # argument for putting HTML on the streaming path.
        self.assertNotIn("<", out["html"], "escaping has to happen before any tag is written")
        self.assertEqual(out["shown"], "<img src=x onerror=alert(1)>")

    def test_a_stray_asterisk_pair_is_not_mistaken_for_italics(self):
        out = run("arithmetic_asterisks_stay_literal")
        self.assertNotIn("<em>", out["html"], "2 * 3 * 4 is arithmetic, not emphasis")
        self.assertEqual(out["shown"], "2 * 3 * 4 라고 했다")


if __name__ == "__main__":
    unittest.main()
