"""Choices leave the answer's text (OUT_OF_BAND_CHOICES_v1, docs/plans/archive/2026/out-of-band-choices-actions.md 1a): the server
takes the trailing `<!--choices: …-->` out once, for every provider, so history, the CLI and the agent's context keep
clean text, and sends the items beside it; the page draws the chips from them.
Run: engine/run-tests.sh test_choices_channel
"""
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
from providers.adapter_base import split_choices  # noqa: E402
from providers.adapters import AgyAdapter  # noqa: E402
from tests.page_source import app_bundle  # noqa: E402
from tests.page_source import i18n_prelude  # noqa: E402


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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(app_bundle())], capture_output=True, text=True, timeout=30)
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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(app_bundle())], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), "선택해\n<!--choices: 동의 | 미소 -> (미소짓는다) | 승인 -> command: /ticket approve 10-->")

    def test_markdown_parse_choice_item(self):
        choices_file = ROOT / "static" / "markdown.js"
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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(choices_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out[0], {"label": "A", "kind": "action", "payload": "웃음", "action": "웃음", "isAction": True})   # parens stripped (#153)
        self.assertEqual(out[1], {"label": "B", "action": "/ticket approve 1", "payload": "/ticket approve 1", "kind": "command", "isAction": False})
        self.assertEqual(out[2], {"label": "C", "action": "끄덕임", "payload": "끄덕임", "kind": "action", "isAction": True})
        self.assertEqual(out[3], "일반 보기")

    def test_markdown_event_choices_take_priority_over_text(self):
        md_file = ROOT / "static" / "markdown.js"
        choices_file = ROOT / "static" / "app-choices.js"
        js = r"""
const fs = require('fs');
const choicesSrc = fs.readFileSync(process.argv[process.argv.length - 2], 'utf8');
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
global.EXPRESSION_HEAD = /^\s*\[expression:\s*([a-zA-Z]+)\]\s*/;
global.EXPRESSION_EMOJIS = {};
global.THOUGHT_STATE_BLOCK = /```state\s*\{[\s\S]*?"thought":\s*"([^"]+)"[\s\S]*?\}\s*```/i;
global.THOUGHT_STATE_ANY = /```state\s*\{[\s\S]*?\}\s*```/i;
global.THOUGHT_TAG = /<thought>([\s\S]*?)<\/thought>/i;
global.THOUGHT_BLOCK = /```thought\s*([\s\S]*?)```/i;

eval(choicesSrc);
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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(choices_file), str(md_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        self.assertEqual(res["eventFirst"], ["이벤트선택1", "이벤트선택2"])
        self.assertEqual(res["fallback"], ["본문선택A", "본문선택B"])

    def test_markdown_renders_choices_into_choice_bar_container(self):
        choices_file = ROOT / "static" / "app-choices.js"
        md_file = ROOT / "static" / "markdown.js"
        js = r"""
const fs = require('fs');
const md = fs.readFileSync(process.argv[process.argv.length - 2], 'utf8');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
eval(md.slice(md.indexOf('function stripOuterParens'), md.indexOf('function expressionEmoji')));

function el(tag) {
  return {
    tag, className: '', textContent: '', children: [], hidden: true,
    appendChild(c) { this.children.push(c); return c; },
    querySelectorAll() { return []; },
    querySelector() { return null; }
  };
}

global.choiceBarEl = el('div');
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

eval(src);

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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(md_file), str(choices_file)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        self.assertEqual(res["hidden"], False)
        self.assertEqual(res["cardClass"], "choice-card")
        self.assertEqual(res["chipCount"], 2)

    def test_sync_keeps_the_bar_its_newest_message_drew(self):
        """#148: the card sits in #choiceBar, outside the bubble. Choices drawn from the marker (result event, resync,
        history -- the paths a phone takes) set no _choices, and syncChoiceChips right after must not hide them."""
        choices_file = ROOT / "static" / "app-choices.js"
        md_file = ROOT / "static" / "markdown.js"
        js = r"""
const md = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const chips = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
const src = md.slice(md.indexOf('var CHOICES_TAIL'), md.indexOf('function expressionEmoji')) + '\n' + chips;
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
const api = new Function('logEl', 'choiceBarEl', 'document', src +
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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(md_file), str(choices_file)], capture_output=True, text=True, timeout=30)
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
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(app_bundle())], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"heldBeforeBubble": {"prevUntouched": True, "drawnEarly": 0},
                                                "taken": ["A", "B"], "droppedOnUserTurn": True})

    def test_back_to_work_closes_the_bar_and_is_not_said(self):
        """The stay chip is a page command. Clicking it clears the choice bar and does not send the label."""
        page = ROOT / "static" / "app-messages.js"
        choices = ROOT / "static" / "markdown.js"
        js = r"""
const fs = require('fs');
const files = process.argv.slice(1).filter(a => a.endsWith('.js'));
const page = fs.readFileSync(files[0], 'utf8');
const choicesSrc = fs.readFileSync(files[1], 'utf8');
eval(page.slice(page.indexOf('function textWithChoices'), page.indexOf('function addChat')));
eval(choicesSrc.slice(choicesSrc.indexOf('function stripOuterParens'), choicesSrc.indexOf('function splitChoices')));
function addEventListener() {}
const owner = { _choices: ['stay'] };
let scrolled = 0;
function updateScrollBottomButton() { scrolled += 1; }
const bar = { hidden: false, textContent: 'chips', _owner: owner };
const document = { getElementById(id) { return id === 'choiceBar' ? bar : null; } };
const sent = [];
var pickChoice = function (c) { sent.push(c.payload || c.label); };
eval(page.slice(page.indexOf('function dismissStayChips')));
installStayChoice();
installStayChoice();
const oldChip = { label: 'Back to work', label_key: 'choice.back_to_work' };
const drawn = textWithChoices({ text: '끝', choices: [oldChip] });
const raw = drawn.slice(drawn.indexOf('<!--choices:') + '<!--choices:'.length).replace('-->', '').trim();
const item = parseChoiceItem(raw);
pickChoice(item);
pickChoice({ label: '잠깐', kind: 'command', payload: '/move stairwell' });
pickChoice({ label: '일 계속하기', kind: 'say', payload: '일 계속하기' });
process.stdout.write(JSON.stringify({
  drawn, item, sent, hidden: bar.hidden, text: bar.textContent, choices: owner._choices, scrolled
}));
"""
        r = subprocess.run(["node", "-e", i18n_prelude() + js, str(page), str(choices)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["drawn"], "끝\n<!--choices: 일 계속하기 -> command: /stay-->")
        self.assertEqual(out["item"]["kind"], "command")
        self.assertEqual(out["item"]["payload"], "/stay")
        self.assertEqual(out["item"]["label"], "일 계속하기")
        self.assertEqual(out["sent"], ["/move stairwell", "일 계속하기"])
        self.assertTrue(out["hidden"])
        self.assertEqual(out["text"], "")
        self.assertIsNone(out["choices"])
        self.assertEqual(out["scrolled"], 1)

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
