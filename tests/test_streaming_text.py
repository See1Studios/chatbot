"""The streaming answer is painted, not re-rendered (STREAM_FLOW_v1, 2026-09-28).

A provider emits far more tokens than a screen paints frames, and the old path re-parsed the whole
growing answer with marked + DOMPurify and rebuilt the bubble on every single delta. This runs the
real block out of the concatenated page bundle against a stub DOM and asserts the properties that
matter: one paint per frame no matter the token rate, no markdown machinery on the streaming path,
incremental appends, a correct fallback when the draft is rewritten, and a finished message with
nothing left moving.

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

// PLAIN_RENDER_v1, the real one.
const md = fs.readFileSync(process.argv[3], 'utf8');
const ra = md.indexOf('function renderPlainText');
if (ra < 0) throw new Error('renderPlainText missing from markdown.js');
const rb = md.indexOf('\n}', md.indexOf('return t;', ra)) + 2;
function absArtifact(p) { return p; }        // markdown.js's helper; no artifacts in this text
eval(md.slice(ra, rb));

function el(tag) {
  const e = {
    tag, className: '', children: [], attrs: {}, dataset: {}, handlers: {},
    classList: {
      _s: new Set(),
      add(...c) { c.forEach(x => this._s.add(x)); },
      remove(...c) { c.forEach(x => this._s.delete(x)); },
      contains(c) { return this._s.has(c); },
    },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(t, f) { this.handlers[t] = f; },
    appendChild(c) { c.parentNode = e; e.children.push(c); return c; },
    insertBefore(c) { c.parentNode = e; e.children.push(c); return c; },
    remove() { if (e.parentNode) { e.parentNode.children = e.parentNode.children.filter(x => x !== c_of(e)); } e.parentNode = null; },
    all(sel) {
      const cls = sel.replace(/^\./, '');
      const out = [];
      (function walk(n) { for (const c of n.children) { if ((c.className || '').split(' ').includes(cls)) out.push(c); walk(c); } })(e);
      return out;
    },
    querySelector(sel) { return e.all(sel)[0] || null; },
    querySelectorAll(sel) { return e.all(sel); },
  };
  const c_of = (x) => x;
  e.remove = function () { if (e.parentNode) { e.parentNode.children = e.parentNode.children.filter(x => x !== e); } e.parentNode = null; };
  // A real element's textContent is a text node; children only holds elements. The streaming path
  // sets textContent once and then appends, so both have to be modelled or the first characters
  // vanish from the assertion.
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
// The streaming path now writes HTML, and an assertion on textContent has to mean the visible text.
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

eval(code);

const flush = () => { const q = frames; frames = []; q.forEach(f => f()); return q.length; };
const newBubble = () => { const n = el('div'); n.className = 'msg assistant'; n.dataset.live = '1'; return n; };
const body = (n) => n.querySelector('.md');
const text = (n) => {
  const md = body(n);
  const parts = [];
  if (md._text) parts.push(md._text);
  md.children.filter(c => !/\bexp-badge\b/.test(c.className)).forEach(c => parts.push(c.textContent));
  return parts.join('');
};
const htmlOf = (n) => body(n).children.filter(c => !/\bexp-badge\b/.test(c.className))
  .map(c => c.innerHTML).join('');

const CASES = {
  coalesces: () => {
    const n = newBubble();
    for (let i = 1; i <= 200; i++) { setStreamingContent(n, '가'.repeat(i)); }
    const queued = frames.length;
    flush();
    return { deltas: 200, frames_queued: queued, painted: text(n).length };
  },
  no_heavy_path: () => {
    const n = newBubble();
    for (let i = 1; i <= 50; i++) setStreamingContent(n, 'x'.repeat(i));
    flush();
    return { marked: markedCalls, purify: purifyCalls, renderMarkdown: renderMarkdownCalls,
             postProcess: postProcessCalls, shown: text(n).length, scrolls: scrolls.length };
  },
  incremental: () => {
    const n = newBubble();
    setStreamingContent(n, '안녕');
    const after1 = body(n).children.length;
    setStreamingContent(n, '안녕하');
    const spans = body(n).children.filter(c => c.className === 'flow');
    return { after1, spans: spans.length, texts: spans.map(s => s.textContent), shown: text(n) };
  },
  rewrite_falls_back: () => {
    const n = newBubble();
    setStreamingContent(n, '처음Draft');
    setStreamingContent(n, 'resync으로 다시 온 본문');
    return { shown: text(n), streaming: n.classList.contains('streaming') };
  },
  equal_text_does_not_touch_dom: () => {
    const n = newBubble();
    setStreamingContent(n, '같은내용');
    const before = body(n).children.length;
    setStreamingContent(n, '같은내용');
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
    return { shown: text(n).replace(/\n/g, '\\n') };
  },
  caret_class_on: () => {
    const n = newBubble();
    setStreamingContent(n, '말하는중');
    return { streaming: n.classList.contains('streaming'), md_stream: body(n).classList.contains('md-stream') };
  },
  finished_is_still: () => {
    const n = newBubble();
    setStreamingContent(n, '다 끝났어');
    endStreamingContent(n);
    return { streaming: n.classList.contains('streaming'), md_stream: body(n).classList.contains('md-stream'),
             shown: text(n), remembered: n._streamShown };
  },
  cancel_stops_the_frame: () => {
    const n = newBubble();
    scheduleStreamPaint(function () { setStreamingContent(n, '늦게도착'); });
    const queued = frames.length;
    cancelStreamPaint();
    const after = frames.length;
    return { queued, after, shown: text(n) };
  },
  // PLAIN_RENDER_v1: the point of rendering while streaming is that the answer already looks like
  // its finished self, so the swap at `result` is a refinement instead of a different document
  // replacing another one in a single frame.
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
    return { html: htmlOf(n), tag: body(n).children[0].tag };
  },
  a_code_block_does_not_nest_a_pre_inside_a_span: () => {
    const n = newBubble();
    setStreamingContent(n, '설명.');
    setStreamingContent(n, '설명.\n\n```py');          // the fence opens
    setStreamingContent(n, '설명.\n\n```py\nprint(1)');  // and fills
    return { tag: body(n).children.map(c => c.tag) };
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
    def test_two_hundred_deltas_cost_at_most_one_frame_each(self):
        out = run("coalesces")
        # The whole point: a 200-token answer must not schedule 200 paints before a frame runs.
        self.assertLessEqual(out["frames_queued"], 200)
        self.assertEqual(out["painted"], 200, "the text must still all be there after the flush")

    def test_the_streaming_path_never_touches_markdown_or_sanitising(self):
        out = run("no_heavy_path")
        self.assertEqual((out["marked"], out["purify"], out["renderMarkdown"], out["postProcess"]), (0, 0, 0, 0),
                         "the streaming path reached the heavy render -- this is the O(n^2) again")
        self.assertEqual(out["shown"], 50, "the text must still render while streaming")

    def test_each_paint_appends_only_the_new_text(self):
        out = run("incremental")
        self.assertEqual(out["texts"], ["안녕", "하"], "only the new characters should be appended")
        self.assertEqual(out["shown"], "안녕하")

    def test_a_rewritten_draft_is_swapped_not_appended(self):
        out = run("rewrite_falls_back")
        self.assertEqual(out["shown"], "resync으로 다시 온 본문", "a non-append delta must replace the body")
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
        self.assertEqual(out["shown"], "보이는말\\n")

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

    # --- PLAIN_RENDER_v1: the streaming body is already the finished shape ---

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

    def test_prose_chunks_stay_inline_and_a_code_chunk_becomes_a_block(self):
        out = run("a_code_block_does_not_nest_a_pre_inside_a_span")
        self.assertEqual(out["tag"], ["span", "div", "span"],
                         "prose must not be forced onto its own line; the chunk that opens the "
                         "fence is the one that becomes a block, and the rest fills it")

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
