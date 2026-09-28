"""The streaming answer is painted, not re-rendered, and it arrives a line at a time.

Two properties, both learned the hard way.

STREAM_FLOW_v1: a provider emits far more tokens than a screen paints frames, and the old path
re-parsed the whole growing answer with marked + DOMPurify and rebuilt the bubble on every single
delta. This runs the real block out of the concatenated page bundle against a stub DOM and asserts
the properties that matter -- one paint per frame no matter the token rate, no markdown machinery on
the streaming path, a body that restarts when a resync rewrites the draft, and a finished message
with nothing left moving.

REVEAL_UNIT_v1: the entrance used to be applied to the arriving chunk, which is one paint's worth
of text. Measured against a real reply at a real token rate, the median chunk was one character and
the best case two, with four to seven 150ms fades overlapping at once -- invisible, and unchanged at
30fps. The unit is now a finished line: a unit that has not finished is not on screen at all, and
the caret stands in for it. The tests here pin that unit size, because "the animation is too small
to see" is a property of the code, not a matter of taste, and it is exactly what two rounds of
eyeballing got wrong.

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
# markdown.js is not part of the app-*.js bundle the stub DOM loads, so the cheap renderer the
# streaming path now uses is sliced straight out of its real source. Testing a copy of it would test
# the copy.
MARKDOWN = CODE / "static" / "markdown.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('var streamPaintQueued');
const b = src.indexOf('\nfunction bindEvents(sid)');
if (a < 0 || b < 0) throw new Error('STREAM_FLOW block markers missing');
const code = src.slice(a, b);

function el(tag) {
  const e = {
    tag, className: '', children: [], attrs: {}, dataset: {}, handlers: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    // className and classList are one thing in a browser. The stub used to keep them apart, which
    // hid every assertion about a class the code adds rather than assigns.
    classList: {
      _set() { return new Set((e.className || '').split(' ').filter(Boolean)); },
      _put(s) { e.className = [...s].join(' '); },
      add(...c) { const s = this._set(); c.forEach(x => s.add(x)); this._put(s); },
      remove(...c) { const s = this._set(); c.forEach(x => s.delete(x)); this._put(s); },
      contains(c) { return this._set().has(c); },
    },
    addEventListener(t, f) { e.handlers[t] = f; },
    appendChild(c) { e.children.push(c); return c; },
    // insertBefore used to shove to the front regardless of the reference node, which happened to be
    // right only while the reveal appended at the end. The reveal inserts each finished unit in
    // front of the open one, so the reference has to be honoured.
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
  // A real element's textContent is a text node; children only holds elements. Both have to be
  // modelled or the first characters vanish from the assertion.
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
// The streaming path writes HTML, and an assertion on textContent has to mean the visible text.
function visibleText(h) {
  return String(h == null ? '' : h)
    .replace(/<br\s*\/?>/g, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}

const document = { createElement: el };
let frames = [];                      // queued animation-frame callbacks
const window = {
  requestAnimationFrame(cb) { frames.push(cb); return frames.length; },
  cancelAnimationFrame() {},
};
const scrolls = [];
function scrollChatToBottom() { scrolls.push(1); }

// Tripwires: the streaming path must never reach the expensive machinery.
let markedCalls = 0, purifyCalls = 0, renderMarkdownCalls = 0, postProcessCalls = 0;
const marked = { parse() { markedCalls++; return '<p>MARKDOWN</p>'; } };
const DOMPurify = { sanitize(h) { purifyCalls++; return h; } };
function renderMarkdown() { renderMarkdownCalls++; return '<p>FULL</p>'; }
function postProcessAssistant() { postProcessCalls++; }
function markArrive(el) {             // app-messages.js's helper, which the reveal calls
  el.classList.add('arrive');
  el.addEventListener('animationend', function () { el.classList.remove('arrive'); }, { once: true });
}

// The two cheap helpers the streaming path is allowed to use, with the real shapes.
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
function paintExpressionBadge(node, rawText) {           // markdown.js's extracted helper
  const parsed = parseExpression(rawText);
  if (!parsed.expression) return;
  const md = node.querySelector('.md') || node;
  let badge = node.querySelector('.exp-badge');
  if (!badge) { badge = document.createElement('span'); badge.className = 'badge exp-badge'; md.insertBefore(badge); }
  badge.textContent = EXPRESSION_EMOJIS[parsed.expression] || parsed.expression;
}
function prepareStreamText(src) {                        // markdown.js's extracted helper
  let raw = splitChoices(src || '').text;
  const p = parseExpression(raw);
  if (p.expression) raw = p.text;
  const t = parseThought(raw, true);
  if (t.thought || t.cleanText !== raw) raw = t.cleanText;
  return raw;
}

// PLAIN_RENDER_v1, the real one.
const md = fs.readFileSync(process.argv[3], 'utf8');
const ra = md.indexOf('function renderPlainText');
if (ra < 0) throw new Error('renderPlainText missing from markdown.js');
const rb = md.indexOf('\n}', md.indexOf('return t;', ra)) + 2;
function absArtifact(p) { return p; }        // markdown.js's helper; no artifacts in this text
eval(md.slice(ra, rb));

eval(code);

const flush = () => { const q = frames; frames = []; q.forEach(f => f()); return q.length; };
const newBubble = () => { const n = el('div'); n.className = 'msg assistant'; n.dataset.live = '1'; return n; };
const body = (n) => n.querySelector('.md');
const units = (n) => body(n).children.filter(c => /\bflow\b/.test(c.className));
const text = (n) => {
  const b = body(n);
  const parts = [];
  if (b._text) parts.push(b._text);
  b.children.filter(c => !/\bexp-badge\b/.test(c.className)).forEach(c => parts.push(c.textContent));
  return parts.join('');
};
const htmlOf = (n) => body(n).children.filter(c => !/\bexp-badge\b/.test(c.className))
  .map(c => c.innerHTML).join('');
const LINES = 20, WIDTH = 10;
const FULL = Array.from({ length: LINES }, () => '가'.repeat(WIDTH)).join('\n');

const CASES = {
  coalesces: () => {
    const n = newBubble();
    // The paint reads the buffer when the frame runs, not the value at the moment it was
    // scheduled -- that is how app-sse.js does it, and it is the whole point: 219 deltas, one
    // paint, and the paint shows everything that arrived.
    let paintBuf = '';
    for (let i = 1; i <= FULL.length; i++) {
      paintBuf = FULL.slice(0, i);
      scheduleStreamPaint(() => setStreamingContent(n, paintBuf));
    }
    const framesQueued = frames.length;
    flush();
    const all = units(n);
    return { deltas: FULL.length, frames_queued: framesQueued, chars: text(n).length,
             arrived: all.filter(c => /\barrive\b/.test(c.className)).length, total: all.length };
  },
  no_heavy_path: () => {
    const n = newBubble();
    for (let i = 1; i <= 50; i++) setStreamingContent(n, 'x'.repeat(i) + '\n');
    flush();
    return { marked: markedCalls, purify: purifyCalls, renderMarkdown: renderMarkdownCalls,
             postProcess: postProcessCalls, shown: text(n).length, scrolls: scrolls.length };
  },
  unit_appears_only_when_finished: () => {
    const n = newBubble();
    setStreamingContent(n, '하나');
    const mid = units(n).map(c => c.className);
    setStreamingContent(n, '하나\n둘');
    return { mid, done: units(n).map(c => c.className), shown: text(n) };
  },
  the_open_unit_is_last_and_hosts_the_caret: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n둘\n셋');
    const kids = body(n).children;
    return { last: kids[kids.length - 1].className, last_is_open: /\bopen\b/.test(kids[kids.length - 1].className) };
  },
  each_unit_animates_exactly_once: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n');
    const el0 = units(n)[0];
    const before = el0.className;
    const listened = typeof el0.handlers['animationend'];
    el0.handlers['animationend']();          // the browser fires this; the stub does not
    return { before, listened, after: el0.className };
  },
  the_unit_is_bigger_than_a_chunk: () => {
    // The measurement that started this: a chunk was one character, which is why nothing was seen.
    const n = newBubble();
    setStreamingContent(n, FULL);
    const sizes = units(n).map(u => u.textContent.length).filter(s => s > 0);
    return { count: sizes.length, min: Math.min(...sizes), max: Math.max(...sizes) };
  },
  paragraph_unit: () => {
    STREAM_REVEAL_UNIT = 'paragraph';
    const n = newBubble();
    setStreamingContent(n, '하나\n둘\n\n셋\n넷\n\n오');
    const out = { shown: text(n), kinds: units(n).map(c => c.textContent) };
    STREAM_REVEAL_UNIT = 'line';
    return out;
  },
  a_long_unbroken_run_is_shown: () => {
    const n = newBubble();
    const long = '가'.repeat(STREAM_REVEAL_MAX + 20);
    setStreamingContent(n, long);
    const short = '가'.repeat(10);
    const m = newBubble();
    setStreamingContent(m, short);
    return { long_shown: text(n).length, short_shown: text(m).length };
  },
  rewrite_restarts_the_body: () => {
    const n = newBubble();
    setStreamingContent(n, '하나\n둘\n셋');
    const before = text(n);
    setStreamingContent(n, '처음부터\n다시');
    return { before, after: text(n), units: n._streamUnits, children: body(n).children.length,
             streaming: n.classList.contains('streaming') };
  },
  equal_text_does_not_touch_dom: () => {
    const n = newBubble();
    setStreamingContent(n, '같은내용\n');
    const before = body(n).children.length;
    setStreamingContent(n, '같은내용\n');
    return { before, after: body(n).children.length };
  },
  stripped_tags: () => {
    const n = newBubble();
    setStreamingContent(n, '[expression: joy]안녕\n');
    const b = n.querySelector('.exp-badge');
    return { shown: text(n), badge: b ? b.textContent : null };
  },
  hides_thought: () => {
    const n = newBubble();
    setStreamingContent(n, '보이는말\n```thought\n숨겨질말\n```');
    return { shown: text(n).replace(/\n/g, '\\n') };
  },
  caret_class_on: () => {
    const n = newBubble();
    setStreamingContent(n, '말하는중');
    return { streaming: n.classList.contains('streaming'), md_stream: body(n).classList.contains('md-stream') };
  },
  finished_is_still: () => {
    const n = newBubble();
    setStreamingContent(n, '다 끝났어\n마지막');
    endStreamingContent(n);
    return { streaming: n.classList.contains('streaming'), md_stream: body(n).classList.contains('md-stream'),
             shown: text(n), remembered: n._streamShown, units: n._streamUnits, open: n._streamOpen };
  },
  cancel_stops_the_frame: () => {
    const n = newBubble();
    scheduleStreamPaint(function () { setStreamingContent(n, '늦게도착\n끝'); });
    const queued = frames.length;
    cancelStreamPaint();
    const after = frames.length;
    return { queued, after, shown: text(n) };
  },
  // --- PLAIN_RENDER_v1: a revealed unit is already the finished shape ---
  bold_while_streaming: () => {
    const n = newBubble();
    setStreamingContent(n, '**중요**한 일\n');
    return { shown: text(n), html: htmlOf(n) };
  },
  action_italic_while_streaming: () => {
    const n = newBubble();
    setStreamingContent(n, '*고개를 기울이며*\n');
    return { shown: text(n), html: htmlOf(n) };
  },
  open_code_fence_while_streaming: () => {
    const n = newBubble();
    setStreamingContent(n, '```py\nprint(1)\n```\n');
    return { html: htmlOf(n), tags: units(n).map(c => c.tag) };
  },
  markup_cannot_inject: () => {
    const n = newBubble();
    setStreamingContent(n, '<img src=x onerror=alert(1)>\n');
    return { shown: text(n), html: htmlOf(n) };
  },
  arithmetic_asterisks_stay_literal: () => {
    const n = newBubble();
    setStreamingContent(n, '2 * 3 * 4 라고 했다\n');
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
    # --- STREAM_FLOW_v1: the cost of showing a stream ---

    def test_two_hundred_deltas_cost_one_frame(self):
        out = run("coalesces")
        # The whole point: a 200-token answer must not schedule 200 paints before a frame runs.
        self.assertEqual(out["frames_queued"], 1,
                         "%d deltas queued %d paints" % (out["deltas"], out["frames_queued"]))
        self.assertEqual(out["total"], 20, "twenty finished lines plus the open one")
        self.assertEqual(out["arrived"], 19, "the twentieth line is still being written")
        self.assertEqual(out["chars"], 19 * 10)

    def test_the_streaming_path_never_touches_markdown_or_sanitising(self):
        out = run("no_heavy_path")
        self.assertEqual((out["marked"], out["purify"], out["renderMarkdown"], out["postProcess"]), (0, 0, 0, 0),
                         "the streaming path reached the heavy render -- this is the O(n^2) again")
        self.assertEqual(out["shown"], 50, "every finished line must still render while streaming")

    def test_a_unit_joins_the_dom_only_once_it_is_finished(self):
        out = run("unit_appears_only_when_finished")
        self.assertEqual(out["mid"], ["flow open"],
                         "a line still being written must not be in the DOM yet")
        self.assertEqual(out["done"], ["flow arrive", "flow open"])
        self.assertEqual(out["shown"], "하나")

    def test_the_open_unit_is_the_last_child_so_the_caret_finds_it(self):
        out = run("the_open_unit_is_last_and_hosts_the_caret")
        self.assertTrue(out["last_is_open"], "the caret is a ::after on .md > *:last-child")
        self.assertEqual(out["last"], "flow open")

    def test_each_unit_animates_exactly_once(self):
        out = run("each_unit_animates_exactly_once")
        self.assertEqual(out["before"], "flow arrive")
        self.assertTrue(out["listened"], "the class has to come off, or a later render replays it")
        self.assertEqual(out["after"], "flow")

    def test_the_animating_unit_is_a_line_and_not_a_chunk(self):
        # This is the assertion that would have caught it. The entrance used to run on whatever one
        # paint delivered -- median one character, best case two -- and no frame rate changes that.
        out = run("the_unit_is_bigger_than_a_chunk")
        self.assertEqual(out["count"], 19)
        self.assertEqual((out["min"], out["max"]), (10, 10),
                         "a unit must be a whole line, not a fragment of one")

    def test_a_paragraph_can_be_the_unit_instead(self):
        out = run("paragraph_unit")
        # A paragraph unit keeps its single newlines; renderPlainText has turned them into <br>.
        self.assertEqual(out["kinds"], ["하나\n둘", "셋\n넷", ""],
                         "'line' and 'paragraph' are one branch on one constant")
        self.assertEqual(out["shown"], "하나\n둘셋\n넷")

    def test_a_long_unbroken_run_is_not_left_invisible(self):
        # The safety valve. Without it, one very long sentence is a blinking cursor and nothing else.
        out = run("a_long_unbroken_run_is_shown")
        self.assertEqual(out["long_shown"], 260, "a run past the cap has to show its text")
        self.assertEqual(out["short_shown"], 0, "a short run stays hidden until it is finished")

    def test_a_rewritten_draft_restarts_the_body(self):
        out = run("rewrite_restarts_the_body")
        self.assertEqual(out["before"], "하나둘", "two finished lines before the rewrite")
        self.assertEqual(out["after"], "처음부터", "the stale lines must not sit in front of the new answer")
        self.assertEqual(out["units"], 1, "the count restarts: one new line is already finished")
        self.assertEqual(out["children"], 2, "the one finished line and the open one, nothing stale")
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
        replaced the bubble and took the reveal spans with it. This pins the rule so the next writer
        added to this region cannot reintroduce it.
        """
        import re
        offenders = []
        for name in ("app-sse.js", "app-session.js"):
            text = (CODE / "static" / name).read_text(encoding="utf-8")
            for no, line in enumerate(text.splitlines(), 1):
                if re.search(r"setAssistantContent\([^)]*,\s*false\s*\)", line):
                    offenders.append("%s:%d: %s" % (name, no, line.strip()[:70]))
        self.assertEqual(offenders, [],
                         "a live render still goes through the final path, which erases the flow: %s" % offenders)

    def test_a_finished_message_is_left_completely_still(self):
        out = run("finished_is_still")
        self.assertFalse(out["streaming"], "the finished message is still motion")
        self.assertFalse(out["md_stream"])
        self.assertEqual(out["remembered"], "")
        self.assertEqual(out["units"], 0, "the count has to reset with the rest of the streaming state")
        self.assertIsNone(out["open"], "the open element is detached by the final render")

    # --- PLAIN_RENDER_v1: a revealed unit is already the finished shape ---

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
        self.assertEqual(set(out["tags"]), set(["div"]),
                         "a <pre> inside a <span> is invalid nesting")

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
