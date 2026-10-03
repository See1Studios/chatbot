"""Choices leave the answer's text (OUT_OF_BAND_CHOICES_v1, docs/plans/out-of-band-choices-actions.md 1a): the server
takes the trailing `<!--choices: …-->` out once, for every provider, so history, the CLI and the agent's context keep
clean text, and sends the items beside it; the page draws the chips from them.
Run: python3 -m unittest tests.test_choices_channel  (from services/chatbot)
"""
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from providers.adapter_base import split_choices  # noqa: E402
from providers.adapters import AgyAdapter  # noqa: E402
from tests.page_source import app_bundle  # noqa: E402


def fake_session():
    s = types.SimpleNamespace(current_text="", pending_images=[], history=[], turn_started_at=0, provider="agy",
                              model="m", served_model="")
    s._rewrite_artifact_paths = lambda t: t
    s._append_images_markdown = lambda t, since=None: t
    s.save_meta = lambda: None
    return s


class ServerSplits(unittest.TestCase):
    def test_the_last_marker_leaves_the_text(self):
        self.assertEqual(split_choices("답이야\n<!--choices: 좋아 | 싫어-->"), ("답이야", ["좋아", "싫어"]))
        self.assertEqual(split_choices("a <!--choices: x--> b <!--choices: 1 | 2 -> (웃는다)-->"),
                         ("a <!--choices: x--> b", ["1", "2 -> (웃는다)"]))

    def test_a_marker_left_mid_answer_on_its_own_line_is_taken_out(self):
        # 2026-09-30: marker, then a tool call, then more text in the same turn -- the marker was shown raw
        text = "계획이다냥.\n\n<!--choices: 반영 | 튜닝 | 다듬기-->\n카드를 올렸다냥!"
        self.assertEqual(split_choices(text), ("계획이다냥.\n\n카드를 올렸다냥!", ["반영", "튜닝", "다듬기"]))
        both = "a\n<!--choices: old-->\nb\n<!--choices: new | two-->"
        self.assertEqual(split_choices(both), ("a\nb", ["new", "two"]))

    def test_a_marker_in_a_code_fence_stays(self):
        text = "문법:\n```\n<!--choices: A | B-->\n```\n끝"
        self.assertEqual(split_choices(text), (text, []))

    def test_a_quoted_marker_or_none_keeps_the_text(self):
        for text in ("인용 `<!--choices: a-->` 이후 본문", "그냥 답", "<!--choices:   -->"):
            self.assertEqual(split_choices(text), (text, []))

    def test_at_most_four_short_items(self):
        _, items = split_choices("x <!--choices: " + " | ".join(["가" * 200] * 6) + "-->")
        self.assertEqual((len(items), len(items[0])), (4, 120))

    def test_the_turn_keeps_clean_text_and_carries_the_items(self):
        s = fake_session()
        s.current_text = "어떻게 할까?\n<!--choices: 진행 | 보류-->"
        ev = AgyAdapter().finalize_turn(session=s, text="", raw_usage=None)
        self.assertEqual((ev["text"], ev["choices"]), ("어떻게 할까?", ["진행", "보류"]))
        self.assertEqual((s.history[-1]["text"], s.history[-1]["choices"]), ("어떻게 할까?", ["진행", "보류"]))

    def test_no_choices_no_field(self):
        s = fake_session()
        s.current_text = "그냥 답"
        ev = AgyAdapter().finalize_turn(session=s, text="", raw_usage=None)
        self.assertNotIn("choices", ev)
        self.assertNotIn("choices", s.history[-1])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageDrawsFromItems(unittest.TestCase):
    def test_the_marker_is_rebuilt_only_for_drawing(self):
        js = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function textWithChoices'), b = src.indexOf('function addChat', a);
eval(src.slice(a, b));
process.stdout.write(JSON.stringify([textWithChoices({ text: 'a', choices: ['x', 'y -> (웃음)'] }),
  textWithChoices({ text: 'b' }), textWithChoices({ text: 'c', choices: [' ', 3] })]));
"""
        r = subprocess.run(["node", "-e", js, str(app_bundle())], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["a\n<!--choices: x | y -> (웃음)-->", "b", "c"])

    def test_text_with_choices_handles_structured_items(self):
        js = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function textWithChoices'), b = src.indexOf('function addChat', a);
eval(src.slice(a, b));
const items = [
  { label: '동의', kind: 'say' },
  { label: '미소', kind: 'action', payload: '(미소짓는다)' },
  { label: '승인', kind: 'command', payload: '/ticket approve 10' }
];
process.stdout.write(JSON.stringify(textWithChoices({ text: '선택해', choices: items })));
"""
        r = subprocess.run(["node", "-e", js, str(app_bundle())], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), "선택해\n<!--choices: 동의 | 미소 -> (미소짓는다) | 승인 -> command: /ticket approve 10-->")

    def test_markdown_parse_choice_item(self):
        md_file = ROOT / "static" / "markdown.js"
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function stripOuterParens'), b = src.indexOf('function splitChoices', a);   // + its helpers (#243)
eval(src.slice(a, b));
const r1 = parseChoiceItem({ label: 'A', kind: 'action', payload: '(웃음)' });
const r2 = parseChoiceItem('B -> command: /ticket approve 1');
const r3 = parseChoiceItem('C -> (끄덕임)');
const r4 = parseChoiceItem('일반 보기');
process.stdout.write(JSON.stringify([r1, r2, r3, r4]));
"""
        r = subprocess.run(["node", "-e", js, str(md_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out[0], {"label": "A", "kind": "action", "payload": "웃음", "action": "웃음", "isAction": True})   # parens stripped (#153)
        self.assertEqual(out[1], {"label": "B", "action": "/ticket approve 1", "payload": "/ticket approve 1", "kind": "command", "isAction": False})
        self.assertEqual(out[2], {"label": "C", "action": "끄덕임", "payload": "끄덕임", "kind": "action", "isAction": True})
        self.assertEqual(out[3], "일반 보기")

    def test_markdown_event_choices_take_priority_over_text(self):
        md_file = ROOT / "static" / "markdown.js"
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
// Mock DOM
let renderedChoices = null;
global.renderChoiceChips = function(node, choices) { renderedChoices = choices; };
global.renderMermaidIn = function() {};
global.highlightCodeIn = function() {};
global.attachCodeCopyButtons = function() {};
global.attachImageLightbox = function() {};
global.attachFileLinkInterceptors = function() {};
global.attachMessageFooter = function() {};
global.CHOICES_TAIL = /\s*<!--\s*choices\s*:((?:(?!<!--)[\s\S])*?)-->\s*$/;
global.CHOICES_OPEN = /\s*<!--\s*choices(?:(?!-->)[\s\S])*$/;
global.CHOICES_MAX = 4;
global.EXPRESSION_HEAD = /^\s*\[expression:\s*([a-zA-Z]+)\]\s*/;
global.EXPRESSION_EMOJIS = {};
global.THOUGHT_STATE_BLOCK = /```state\s*\{[\s\S]*?"thought":\s*"([^"]+)"[\s\S]*?\}\s*```/i;
global.THOUGHT_STATE_ANY = /```state\s*\{[\s\S]*?\}\s*```/i;
global.THOUGHT_TAG = /<thought>([\s\S]*?)<\/thought>/i;
global.THOUGHT_BLOCK = /```thought\s*([\s\S]*?)```/i;

const a = src.indexOf('function parseExpression'), b = src.indexOf('function dedupeMarkdownImages', a);
eval(src.slice(a, b));
renderChoiceChips = function(node, choices) { renderedChoices = choices; };

const nodeWithEvent = { classList: { toggle() {} }, querySelector() { return null; }, _choices: ['이벤트선택1', '이벤트선택2'] };
postProcessAssistant(nodeWithEvent, true, '답변\n<!--choices: 본문선택A | 본문선택B-->', null, null, false, null);
const firstRun = renderedChoices;

const nodeWithoutEvent = { classList: { toggle() {} }, querySelector() { return null; } };
postProcessAssistant(nodeWithoutEvent, true, '답변\n<!--choices: 본문선택A | 본문선택B-->', null, null, false, null);
const secondRun = renderedChoices;

process.stdout.write(JSON.stringify({ eventFirst: firstRun, fallback: secondRun }));
"""
        r = subprocess.run(["node", "-e", js, str(md_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        self.assertEqual(res["eventFirst"], ["이벤트선택1", "이벤트선택2"])
        self.assertEqual(res["fallback"], ["본문선택A", "본문선택B"])

    def test_markdown_renders_choices_into_choice_bar_container(self):
        md_file = ROOT / "static" / "markdown.js"
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');

function el(tag) {
  return {
    tag, className: '', textContent: '', children: [], hidden: true,
    appendChild(c) { this.children.push(c); return c; },
    querySelectorAll() { return []; },
    querySelector() { return null; }
  };
}

global.choiceBarEl = el('div');
global.CHOICES_TAIL = /\s*<!--\s*choices\s*:((?:(?!<!--)[\s\S])*?)-->\s*$/;
global.CHOICES_OPEN = /\s*<!--\s*choices(?:(?!-->)[\s\S])*$/;
global.CHOICES_MAX = 4;
global.document = {
  createElement(tag) {
    return {
      tag, className: '', textContent: '', children: [], attrs: {}, handlers: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(t, f) { this.handlers[t] = f; },
      appendChild(c) { this.children.push(c); return c; },
      remove() {}
    };
  }
};

const a = src.indexOf('function stripOuterParens'), b = src.indexOf('function postProcessAssistant', a);
eval(src.slice(a, b));

renderChoiceChips(null, ['선택1', '선택2']);
const card = choiceBarEl.children[0] || {};
const body = card.children ? card.children[1] : null;
const chipCount = body ? body.children.length : 0;

process.stdout.write(JSON.stringify({
  hidden: choiceBarEl.hidden,
  cardClass: card.className,
  chipCount
}));
"""
        r = subprocess.run(["node", "-e", js, str(md_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        self.assertEqual(res["hidden"], False)
        self.assertEqual(res["cardClass"], "choice-card")
        self.assertEqual(res["chipCount"], 2)

    def test_sync_keeps_the_bar_its_newest_message_drew(self):
        """#148: the card sits in #choiceBar, outside the bubble. Choices drawn from the marker (result event, resync,
        history -- the paths a phone takes) set no _choices, and syncChoiceChips right after must not hide them."""
        md_file = ROOT / "static" / "markdown.js"
        js = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
function el(tag) {
  return { tag, className: '', textContent: '', children: [], attrs: {}, hidden: true, parent: null,
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {},
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); },
    contains(o) { for (let n = o; n; n = n.parent) if (n === this) return true; return false; },
    querySelectorAll(sel) {
      if (sel === '.msg:not(.system)') return this.children.filter(c => /\bmsg\b/.test(c.className));
      const cls = sel.slice(1), out = [];
      (function walk(n) { n.children.forEach(c => { if (c.className.split(' ').includes(cls)) out.push(c); walk(c); }); })(this);
      return out;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; } };
}
const logEl = el('div'), choiceBarEl = el('div');
const a = src.indexOf('const CHOICES_TAIL'), b = src.indexOf('function postProcessAssistant');
const api = new Function('logEl', 'choiceBarEl', 'document', src.slice(a, b) +
  ';return { splitChoices, renderChoiceChips, syncChoiceChips };')(logEl, choiceBarEl, { createElement: el });
function msg(cls) { const m = el('div'); m.className = cls; const md = el('div'); md.className = 'md'; m.appendChild(md); logEl.appendChild(m); return m; }
const m = msg('msg assistant');
api.renderChoiceChips(m, api.splitChoices('골라\n<!--choices: A | B-->').choices);
api.syncChoiceChips();
const kept = !choiceBarEl.hidden && choiceBarEl.children.length === 1;
msg('msg user');
api.syncChoiceChips();
process.stdout.write(JSON.stringify({ kept, clearedAfterUser: choiceBarEl.hidden }));
"""
        r = subprocess.run(["node", "-e", js, str(md_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"kept": True, "clearedAfterUser": True})

    def test_choices_event_before_the_first_chunk_waits_for_the_bubble(self):
        """#148: a `choices` SSE event that beats the turn's first text chunk is held for the new bubble, not put on
        the previous answer; a new user turn drops what no bubble took."""
        js = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('let pendingChoices'), b = src.indexOf('function setAssistantContent', a);
function el() {
  return { className: '', dataset: {}, classList: { add() {} }, isConnected: true, children: [],
    appendChild(c) { this.children.push(c); return c; },
    querySelectorAll(sel) { return sel === '.msg.assistant' ? this.children.filter(c => /\bassistant\b/.test(c.className)) : []; } };
}
const logEl = el();
const drawn = [];
const deps = {
  logEl, document: { createElement: el }, normalizeNoticeKind: () => '', NOTICE_KINDS: {}, getActionSvg: () => '',
  stripNoticeChromeEmojis: t => t, renderMarkdown: t => t, parkSessionBanner() {}, scrollChatToBottom() {},
  placeMsgByTs() {}, syncChoiceChips() {}, renderChoiceChips(n, c) { drawn.push(c); }, observeMessage() {},
  postProcessAssistant(node, isFinal, text, u, d, s, m, choices) { if (isFinal) drawn.push(choices); },
};
const names = Object.keys(deps);
const api = new Function(...names, 'let assistantNode = null; let isBusy = true; let currentSessionHasUser = false;\n' +
  src.slice(a, b) + ';return { handleChoicesEvent, addChat, get pending() { return pendingChoices; } };')(...names.map(k => deps[k]));
const prev = api.addChat('assistant', '지난 답', true);
drawn.length = 0;
api.handleChoicesEvent({ event: 'choices', choices: ['A', 'B'] });
const heldBeforeBubble = { prevUntouched: !prev._choices, drawnEarly: drawn.length };
const bubble = api.addChat('assistant', '', false);
const taken = bubble._choices;
api.handleChoicesEvent({ event: 'choices', choices: ['stale'] });
api.addChat('user', '다음 질문', false);
const next = api.addChat('assistant', '', false);
process.stdout.write(JSON.stringify({ heldBeforeBubble, taken, droppedOnUserTurn: next._choices === undefined && api.pending === null }));
"""
        r = subprocess.run(["node", "-e", js, str(app_bundle())], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"heldBeforeBubble": {"prevUntouched": True, "drawnEarly": 0},
                                                "taken": ["A", "B"], "droppedOnUserTurn": True})

    def test_keyboard_open_sizes_the_bars_from_the_visible_height(self):
        """#148: with the phone keyboard up .wrap is --app-height tall and clips; #workBar's 40vh (layout viewport)
        could fill it and push #choiceBar under the clip, so both bars are capped by --app-height there."""
        import re
        css = (ROOT / "static" / "chat-responsive.css").read_text(encoding="utf-8")
        for sel in ("#workBar", "#choiceBar"):
            m = re.search(r"body\.keyboard-open " + re.escape(sel) + r"\{([^}]*)\}", css)
            self.assertIsNotNone(m, sel)
            self.assertIn("max-height:calc(var(--app-height", m.group(1), sel)


if __name__ == "__main__":
    unittest.main()
