"""Tests for streaming text style settings and line reveal mode (ticket #627).

Validates:
- Stream style toggle ('char' | 'line') and persistence in localStorage
- Settings panel UI integration in shellSettingsRows
- Line reveal streaming animation, pacing, and finish behaviour
- CSS classes and keyframes for line reveal in chat-log.css
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import app_bundle
from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

CODE = REPO
APP = app_bundle()
MARKDOWN = CODE / "static" / "markdown.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');

// LocalStorage mock
const store = {};
const localStorage = {
  getItem: (k) => (store[k] !== undefined ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
  clear: () => { for (const k in store) delete store[k]; }
};
global.localStorage = localStorage;

// Block markers for app-sse.js
const a = src.indexOf('var streamPaintQueued');
const b = src.indexOf('\nfunction bindEvents(sid)');
if (a < 0 || b < 0) throw new Error('STREAM_FLOW block markers missing');
const code = src.slice(a, b);

// Block classifier from app-blocks.js
const ba = src.indexOf('const BLOCK_NARRATION');
const bb = src.indexOf('// ==== file:', ba);
if (ba < 0 || bb < 0) throw new Error('BLOCK_KINDS markers missing');
eval(src.slice(ba, bb));

// Extract SHELL_TEXT and shellSettingsRows from app-shell.js
const sa = src.indexOf('const SHELL_TEXT =');
const sb = src.indexOf('function shellRowButton', sa);
if (sa >= 0 && sb >= 0) {
  eval(src.slice(sa, sb));
}

function makeNode(type, value, tag) {
  const n = { nodeType: type, nodeValue: value == null ? null : value, tag: tag || null,
              childNodes: [], className: '', parentNode: null,
              style: { setProperty(k, v) { this[k] = v; } } };
  Object.defineProperty(n, 'firstChild', { get() { return n.childNodes[0] || null; } });
  Object.defineProperty(n, 'children', { get() { return n.childNodes.filter(c => c.nodeType === 1); } });
  Object.defineProperty(n, 'nextSibling', { get() {
    const p = n.parentNode; if (!p) return null;
    const i = p.childNodes.indexOf(n); return i < 0 ? null : (p.childNodes[i + 1] || null);
  } });
  n.classList = { add() {}, remove() {}, contains() { return false; } };
  return n;
}

function el(tag) {
  const e = makeNode(1, null, tag);
  Object.assign(e, {
    tag, className: '', attrs: {}, dataset: {}, handlers: {},
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
    appendChild(c) { return this.insertBefore(c, null); },
    insertBefore(c, ref) {
      if (c.parentNode) {
        const pc = c.parentNode.childNodes;
        const ci = pc.indexOf(c);
        if (ci >= 0) pc.splice(ci, 1);
      }
      const i = ref ? e.childNodes.indexOf(ref) : -1;
      e.childNodes.splice(i < 0 ? e.childNodes.length : i, 0, c);
      c.parentNode = e;
      return c;
    },
    replaceChild(frag, old) {
      const i = e.childNodes.indexOf(old);
      if (i < 0) return old;
      e.childNodes.splice.apply(e.childNodes, [i, 1].concat(frag.parts || [frag]));
      (frag.parts || [frag]).forEach(x => { x.parentNode = e; });
      old.parentNode = null;
      return old;
    },
    all(sel) {
      const isClass = sel.startsWith('.');
      const target = isClass ? sel.slice(1) : sel.toLowerCase();
      const out = [];
      (function walk(n) {
        for (const c of n.children) {
          const match = isClass
            ? (c.className || '').split(' ').includes(target)
            : String(c.tagName || c.tag || '').toLowerCase() === target;
          if (match) out.push(c);
          walk(c);
        }
      })(e);
      return out;
    },
    querySelector(sel) { return e.all(sel)[0] || null; },
    querySelectorAll(sel) { return e.all(sel); },
  });
  e.remove = function () {
    if (e.parentNode) {
      const pc = e.parentNode.childNodes;
      const i = pc.indexOf(e);
      if (i >= 0) pc.splice(i, 1);
    }
    e.parentNode = null;
  };
  Object.defineProperty(e, 'textContent', {
    get() { return (e._text || '') + e.childNodes.map(c => c.nodeType === 3 ? c.nodeValue : c.textContent || '').join(''); },
    set(v) { e._text = ''; e.childNodes = []; if (v !== '' && v != null) { const t = makeNode(3, String(v)); t.parentNode = e; e.childNodes.push(t); } },
  });
  let html = null;
  Object.defineProperty(e, 'innerHTML', {
    get() { return html === null ? e.textContent : html; },
    set(v) {
      html = v; e._text = '';
      e.childNodes = [];
      if (!v) return;
      parseHtmlInto(e, String(v));
    },
  });
  return e;
}

function visibleText(h) {
  return String(h == null ? '' : h)
    .replace(/<br\s*\/?>/g, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}

function parseHtmlInto(parent, str) {
  const tagRegex = /<(\/?[a-zA-Z0-9-]+)([^>]*)>|([^<]+)/g;
  let m;
  const stack = [parent];
  while ((m = tagRegex.exec(str)) !== null) {
    if (m[3]) {
      const txt = visibleText(m[3]);
      if (txt) {
        const tn = makeNode(3, txt);
        tn.parentNode = stack[stack.length - 1];
        stack[stack.length - 1].childNodes.push(tn);
      }
    } else if (m[1]) {
      const tag = m[1].toLowerCase();
      if (tag === 'br') {
        const br = el('br');
        br.parentNode = stack[stack.length - 1];
        stack[stack.length - 1].childNodes.push(br);
      } else if (tag.startsWith('/')) {
        if (stack.length > 1) stack.pop();
      } else {
        const node = el(tag);
        const attrs = m[2] || '';
        const clsMatch = attrs.match(/class=["']([^"']+)["']/i);
        if (clsMatch) node.className = clsMatch[1];
        node.parentNode = stack[stack.length - 1];
        stack[stack.length - 1].childNodes.push(node);
        if (!/^(img|input|hr|meta|link)$/i.test(tag)) {
          stack.push(node);
        }
      }
    }
  }
}

const document = {
  createElement: el,
  createTextNode: (v) => makeNode(3, v),
  createDocumentFragment: () => ({ parts: [], appendChild(n) { this.parts.push(n); return n; } }),
};
let frames = [];
const window = {
  requestAnimationFrame(cb) { frames.push(cb); return frames.length; },
  cancelAnimationFrame() {},
  matchMedia: (q) => ({ matches: /reduce/.test(q) ? REDUCE_MOTION : false }),
};
let REDUCE_MOTION = false;
let timers = [];
let clock = 0;
global.setTimeout = (fn, ms) => { timers.push({ at: clock + (ms || 0), fn }); return timers.length; };
global.clearTimeout = (id) => { if (timers[id - 1]) timers[id - 1].fn = null; };

const advance = (ms) => {
  const until = clock + ms;
  let fired = 0;
  for (;;) {
    const due = timers.filter(t => t.fn && t.at <= until).sort((x, y) => x.at - y.at)[0];
    if (!due) break;
    const run = due.fn; due.fn = null;
    run(); fired++; clock = due.at;
  }
  clock = until;
  return fired;
};

function scrollChatToBottom() {}
function markArrive(el, kind) {
  el.setAttribute('data-kind', kind || 'narration');
}
function buildBlock(block, isFinal) {
  const box = document.createElement('div');
  box.className = 'md-block';
  box.setAttribute('data-kind', block.kind || 'narration');
  const holder = document.createElement(block.kind === 'dialogue' ? 'span' : 'div');
  holder.className = 'md-' + (block.kind || 'narration');
  holder.innerHTML = block.text;
  box.appendChild(holder);
  return box;
}
function parseExpression(text) { return { expression: '', text: text || '' }; }
function parseThought(text, streaming) { return { thought: '', cleanText: text || '' }; }
function splitChoices(src) { return { text: src, choices: [] }; }
function paintExpressionBadge() {}
function prepareStreamText(src) { return src || ''; }

// Load renderPlainText from markdown.js
const md = fs.readFileSync(process.argv[3], 'utf8');
const ra = md.indexOf('function renderPlainText');
if (ra < 0) throw new Error('renderPlainText missing from markdown.js');
const rb = md.indexOf('\n}', md.indexOf('return t;', ra)) + 2;
function absArtifact(p) { return p; }
eval(md.slice(ra, rb));

eval(code);
revealNow = () => clock;

const flush = () => { const q = frames; frames = []; q.forEach(f => f()); return q.length; };
const play = (ms) => { const until = clock + ms; while (clock < until) { clock += 16; flush(); } };
const newBubble = () => { const n = el('div'); n.className = 'msg assistant'; n.dataset.live = '1'; return n; };
const body = (n) => n.querySelector('.md');
const text = (n) => {
  const b = body(n);
  if (!b) return '';
  const parts = [];
  if (b._text) parts.push(b._text);
  b.children.forEach(c => parts.push(c.textContent));
  return parts.join('');
};

const CASES = {
  default_and_toggle_style: () => {
    localStorage.clear();
    const initial = getStreamStyle();
    setStreamStyle('line');
    const afterLine = getStreamStyle();
    const inStore = localStorage.getItem('pe.streamStyle');
    setStreamStyle('char');
    const afterChar = getStreamStyle();
    localStorage.setItem('pe.streamStyle', 'invalid_style');
    const afterGarbage = getStreamStyle();
    return { initial, afterLine, inStore, afterChar, afterGarbage };
  },
  shell_settings_options: () => {
    const rowsChar = shellSettingsRows({ streamStyle: 'char' });
    const rowChar = rowsChar.find(r => r.k === 'streamStyle') || null;
    const rowsLine = shellSettingsRows({ streamStyle: 'line' });
    const rowLine = rowsLine.find(r => r.k === 'streamStyle') || null;
    return {
      charLabel: rowChar ? rowChar.label : null,
      charDetail: rowChar ? rowChar.detail : null,
      lineDetail: rowLine ? rowLine.detail : null,
    };
  },
  line_reveal_streaming: () => {
    setStreamStyle('line');
    const n = newBubble();
    const full = '첫 번째 줄입니다\n두 번째 줄입니다\n세 번째 줄입니다';
    revealTarget(n, full);
    play(16);
    const firstContent = text(n);
    const firstLength = firstContent.length;
    const firstLines = (n.querySelectorAll('.rv-line') || []).length;
    play(3000);
    const endText = text(n);
    const settledLines = (n.querySelectorAll('.rv-line') || []).length;
    setStreamStyle('char');
    return { firstContent, firstLength, firstLines, endText, settledLines, expectedFirst: '첫 번째 줄입니다'.length };
  },
  line_reveal_finish: () => {
    setStreamStyle('line');
    const n = newBubble();
    const full = '하나\n둘\n셋';
    revealTarget(n, '하나\n');
    let done = 0;
    revealFinish(n, full, () => { done++; });
    const immediate = done;
    play(3000);
    setStreamStyle('char');
    return { immediate, done, shown: text(n) };
  },
  line_reveal_reduced_motion: () => {
    setStreamStyle('line');
    REDUCE_MOTION = true;
    const n = newBubble();
    revealTarget(n, '한 번에 모두 출력\n두 번째 줄');
    const out = { text: text(n), lines: (n.querySelectorAll('.rv-line') || []).length };
    REDUCE_MOTION = false;
    setStreamStyle('char');
    return out;
  },
  line_reveal_fade_in_classes: () => {
    setStreamStyle('line');
    const n = newBubble();
    revealTarget(n, '새로운 첫 번째 줄');
    play(16);
    const firstLines = n.querySelectorAll('.rv-line');
    const firstLineAttached = firstLines.length > 0;
    const firstLineText = firstLineAttached ? firstLines[0].textContent : '';
    const hasDelay = firstLineAttached && typeof firstLines[0].style.animationDelay === 'string';
    play(500);
    const midSettled = (n.querySelectorAll('.rv-line') || []).length;
    revealTarget(n, '새로운 첫 번째 줄\n새로운 두 번째 줄');
    play(200);
    const secondLines = n.querySelectorAll('.rv-line');
    const secondLineAttached = secondLines.length > 0;
    const secondLineText = secondLineAttached ? secondLines[0].textContent : '';
    play(500);
    const finalSettled = (n.querySelectorAll('.rv-line') || []).length;
    setStreamStyle('char');
    return {
      firstLineAttached,
      firstLineText,
      hasDelay,
      midSettled,
      secondLineAttached,
      secondLineText,
      finalSettled,
    };
  },
  line_reveal_nested_containers: () => {
    setStreamStyle('line');
    const n = newBubble();
    const md = el('div');
    md.className = 'md';
    n.appendChild(md);
    const block = el('div');
    block.className = 'md-block';
    block.setAttribute('data-kind', 'narration');
    block.innerHTML = '<div class="md-narration"><span>첫 번째 중첩 줄</span><br><span>두 번째 중첩 줄</span></div>';
    md.appendChild(block);
    const rv = {
      src: '', gs: [], shown: 0, times: [], carry: 0, last: 0, born: clock, running: false, finish: null,
      style: 'line', lines: ['첫 번째 중첩 줄', '두 번째 중첩 줄'], linesShown: 2, lineTimes: [], lastLineText: ''
    };
    n._rv = rv;
    revealLines(n, rv, clock);
    const rvLines = n.querySelectorAll('.rv-line');
    const lineCount = rvLines.length;
    const lineTexts = rvLines.map(l => l.textContent);
    play(500);
    revealLines(n, rv, clock);
    const settledCount = (n.querySelectorAll('.rv-line') || []).length;
    const finalContent = text(n);
    setStreamStyle('char');
    return { lineCount, lineTexts, settledCount, finalContent };
  },
  line_reveal_multiblock_markdown: () => {
    setStreamStyle('line');
    const n = newBubble();
    const full = '완료 블록 첫 줄\n완료 블록 둘째 줄\n새로운 진행 줄';
    revealTarget(n, full);
    play(20);
    const rvLines = n.querySelectorAll('.rv-line');
    const activeCount = rvLines.length;
    const activeTexts = rvLines.map(l => l.textContent);
    play(3000);
    const finalSettled = (n.querySelectorAll('.rv-line') || []).length;
    const allText = text(n);
    setStreamStyle('char');
    return { activeCount, activeTexts, finalSettled, allText };
  },
};

console.log(JSON.stringify(CASES[process.argv[2]]()));
"""


def run_node(case):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not installed")
    proc = subprocess.run([node, "-e", i18n_prelude() + HARNESS, str(APP), case, str(MARKDOWN)],
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        raise AssertionError("node failed for %s: %s" % (case, proc.stderr.strip()[:600]))
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStreamStyle(unittest.TestCase):
    def test_stream_style_default_and_toggle(self):
        out = run_node("default_and_toggle_style")
        self.assertEqual(out["initial"], "char", "default style must be char")
        self.assertEqual(out["afterLine"], "line", "style must toggle to line")
        self.assertEqual(out["inStore"], "line", "style must persist in localStorage")
        self.assertEqual(out["afterChar"], "char", "style must toggle back to char")
        self.assertEqual(out["afterGarbage"], "char", "invalid or stale value must fall back to char")

    def test_shell_settings_shows_stream_style_option(self):
        out = run_node("shell_settings_options")
        self.assertIsNotNone(out["charLabel"], "streamStyle option must exist in settings rows")
        self.assertEqual(out["charDetail"], "글자 단위", "char mode detail label")
        self.assertEqual(out["lineDetail"], "줄 단위", "line mode detail label")

    def test_line_reveal_streaming(self):
        out = run_node("line_reveal_streaming")
        self.assertEqual(out["firstLength"], out["expectedFirst"],
                         "first frame in line mode must reveal the whole first line, not just 1 character")
        self.assertGreater(out["firstLines"], 0, "line reveal must create .rv-line elements")
        self.assertEqual(out["settledLines"], 0, "completed line reveals must settle and unwrap spans")
        self.assertIn("첫 번째 줄입니다", out["endText"])
        self.assertIn("세 번째 줄입니다", out["endText"])

    def test_line_reveal_finish_callbacks(self):
        out = run_node("line_reveal_finish")
        self.assertEqual(out["immediate"], 0, "revealFinish should not complete immediately")
        self.assertEqual(out["done"], 1, "revealFinish must invoke done callback after completion")
        self.assertIn("하나", out["shown"])
        self.assertIn("셋", out["shown"])

    def test_line_reveal_reduced_motion(self):
        out = run_node("line_reveal_reduced_motion")
        self.assertIn("한 번에 모두 출력", out["text"])
        self.assertEqual(out["lines"], 0, "reduced motion must not animate or create .rv-line elements")

    def test_chat_log_css_contains_line_reveal_rules(self):
        css = (CODE / "static" / "chat-log.css").read_text(encoding="utf-8")
        self.assertIn(".rv-line", css, "chat-log.css must define .rv-line")
        self.assertIn("@keyframes line-in", css, "chat-log.css must define line-in keyframes")
        compact = re.sub(r"\s+", "", css)
        self.assertIn(".rv-line{animation:none}", compact, "rv-line animation must be disabled under reduced-motion")

    def test_line_reveal_fade_in_transition_style(self):
        css = (CODE / "static" / "chat-log.css").read_text(encoding="utf-8")
        compact = re.sub(r"\s+", "", css)
        self.assertIn("will-change:opacity,transform", compact,
                      "rv-line must configure will-change for smooth hardware-accelerated fade-in")
        self.assertIn("@keyframesline-in{0%{opacity:0;transform:translateY(4px)}60%{opacity:1}100%{opacity:1;transform:none}}",
                      compact, "line-in keyframes must define smooth opacity fade-in with intermediate 60% settle and subtle translateY motion")
        self.assertIn("cubic-bezier(0.16,1,0.3,1)", compact,
                      "line-in must use fluid ease-out cubic-bezier timing")

    def test_line_reveal_new_line_node_classes(self):
        out = run_node("line_reveal_fade_in_classes")
        self.assertTrue(out["firstLineAttached"], "line mode must attach .rv-line class to newly added line node")
        self.assertEqual(out["firstLineText"], "새로운 첫 번째 줄", "first line span must contain new line text")
        self.assertTrue(out["hasDelay"], "rv-line element must configure animationDelay for smooth entrance")
        self.assertEqual(out["midSettled"], 0, "first line .rv-line span must unwrap after line reveal duration")
        self.assertTrue(out["secondLineAttached"], "second incoming line must attach .rv-line span while first is settled")
        self.assertEqual(out["secondLineText"], "새로운 두 번째 줄", "second line span must contain new second line text")
        self.assertEqual(out["finalSettled"], 0, "all completed line reveals must settle and unwrap .rv-line spans")

    def test_line_reveal_nested_containers_traversal(self):
        out = run_node("line_reveal_nested_containers")
        self.assertEqual(out["lineCount"], 2, "revealLines must traverse nested containers and attach .rv-line to each line")
        self.assertEqual(out["lineTexts"], ["첫 번째 중첩 줄", "두 번째 중첩 줄"], "each rv-line span must wrap correct line text")
        self.assertEqual(out["settledCount"], 0, "completed line reveals must settle and unwrap .rv-line spans")
        self.assertIn("첫 번째 중첩 줄", out["finalContent"])
        self.assertIn("두 번째 중첩 줄", out["finalContent"])

    def test_line_reveal_multiblock_markdown_containers(self):
        out = run_node("line_reveal_multiblock_markdown")
        self.assertGreater(out["activeCount"], 0, "line reveal must attach .rv-line spans in nested markdown structures")
        self.assertEqual(out["finalSettled"], 0, "all line reveals must settle cleanly")
        self.assertIn("완료 블록 첫 줄", out["allText"])
        self.assertIn("완료 블록 둘째 줄", out["allText"])
        self.assertIn("새로운 진행 줄", out["allText"])


if __name__ == "__main__":
    unittest.main()
