"""Quick-reply chips: an agent's trailing <!--choices: A | B--> becomes buttons.
Runs the REAL splitChoices / renderChoiceChips / syncChoiceChips / pickChoice (extracted
from static/markdown.js) in node against a stub DOM. Skipped when node is not installed.
Run: python3 -m unittest tests.test_choice_chips  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

MD = Path(__file__).resolve().parent.parent / "static" / "markdown.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('const CHOICES_TAIL'), b = src.indexOf('function postProcessAssistant');
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);

function el(tag) {
  const e = { tag, className: '', textContent: '', children: [], attrs: {}, handlers: {}, parent: null,
    scrollHeight: 0, scrollTop: 0, clientHeight: 0,
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(t, f) { this.handlers[t] = f; },
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); this.parent = null; },
    contains(o) { for (let n = o; n; n = n.parent) if (n === this) return true; return false; },
    all(sel) {
      const cls = sel.replace('.', ''); const out = [];
      (function walk(n) { n.children.forEach(c => { if ((c.className || '').split(' ').includes(cls)) out.push(c); walk(c); }); })(this);
      return out;
    },
    querySelectorAll(sel) { return this.all(sel); },
    querySelector(sel) { return this.all(sel)[0] || null; },
  };
  return e;
}
const logEl = el('div');
// the one selector the stub cannot express: every message div in the log that is not a system notice
const plainQuery = logEl.querySelectorAll;
logEl.querySelectorAll = function (sel) {
  if (sel === '.msg:not(.system)') return this.children.filter(c => /\bmsg\b/.test(c.className) && !/\bsystem\b/.test(c.className));
  return plainQuery.call(this, sel);
};
const sent = [];
const inputEl = { value: '' };
const send = () => { sent.push(inputEl.value); };

const choiceBar = el('div');
choiceBar.classList = { add() {}, remove() {} };
let choiceBarAttached = false;
const doc = {
  createElement: el,
  getElementById: (id) => (id === 'choiceBar' && choiceBarAttached ? choiceBar : null),
};

const scrollCalls = [];
let nearBottom = true;
const isUserNearBottom = () => nearBottom;
const scrollChatToBottom = (force) => { scrollCalls.push(['scrollChatToBottom', force]); };
const updateScrollBottomButton = () => { scrollCalls.push(['updateScrollBottomButton']); };

const body = code + `
  return { splitChoices, renderChoiceChips, syncChoiceChips, pickChoice, parseExpression, parseThought };`;
const api = new Function(
  'logEl', 'inputEl', 'send', 'document',
  'isUserNearBottom', 'scrollChatToBottom', 'updateScrollBottomButton',
  body
)(logEl, inputEl, send, doc, isUserNearBottom, scrollChatToBottom, updateScrollBottomButton);

const out = {};
out.plain = api.splitChoices('그냥 답변');
out.full = api.splitChoices('어느 쪽이 좋을까냥?\n\n<!--choices: A. UI 개선 | B. 토큰 최적화-->');
out.trailingWs = api.splitChoices('질문\n<!--choices: 예|아니오-->  \n');
out.capped = api.splitChoices('q <!--choices: 1|2|3|4|5|6-->').choices;
out.emptyItems = api.splitChoices('q <!--choices: a||  | b-->').choices;
out.streamingHalf = api.splitChoices('질문\n<!--choices: A | B');
out.streamingOpenOnly = api.splitChoices('질문\n<!--choices');
out.midText = api.splitChoices('앞 <!--choices: x--> 뒤 내용');
out.otherComment = api.splitChoices('a <!-- note -->').text;
out.quotedThenTail = api.splitChoices('본문에 `<!--choices: 라벨 -> (행동)-->`을 쓰면\n뒤 문단\n\n<!--choices: 예 | 아니오-->');
out.quotedOnly = api.splitChoices('예시 `<!--choices: A | B-->` 뒤 문단');
out.actionChoices = api.splitChoices('어느 쪽?\n<!--choices: 다가가기 -> 조용히 다가간다 | 인사하기-->');
out.parsedExp = api.parseExpression('[expression: joy] 반갑다냥!');
out.parsedThoughtState = api.parseThought('안녕!\n```state\n{"thought": "반가운 마음"}\n```');
out.parsedThoughtTag = api.parseThought('안녕!\n<thought>내면 독백</thought>');
// rule 3: an unclosed tag / partial tag is hidden only while streaming (2nd arg true)
out.parsedThoughtOpen = api.parseThought('안녕! <thought>아직 안 끝난 속마음', true);
out.parsedThoughtPartialTag = api.parseThought('안녕! <thoug', true);
out.parsedThoughtPartialTagWithTail = api.parseThought('안녕! <thoug뒷이야기가 이어짐');
out.parsedThoughtBareLt = api.parseThought('안녕 <');
out.parsedThoughtMath = api.parseThought('1 < 2');
out.parsedThoughtChoices = api.parseThought('질문\n<!--choices: A | B-->');
out.parsedThoughtChoicesOpen = api.parseThought('질문\n<!--choices');
out.parsedThoughtPartialDots = api.parseThought('안녕! <thoug...');
out.parsedThoughtCorruptDots = api.parseThought('안녕! <thoug...> 뒷이야기');
out.parsedThoughtCorruptThoughtDots = api.parseThought('안녕! <thought...> 뒷이야기');
out.parsedThoughtOrphanClose = api.parseThought('안녕! </thought> 뒷이야기');
out.parsedThoughtSessionEvent = api.parseThought('[expression: shy]\n<thoug없이 거세게 몰아치는 충격');
out.parsedThoughtSessionRepl = api.parseThought('[expression: shy]\n<thoug\ufffd\ufffd한 침대 위로');
out.parsedThoughtCodeLt = api.parseThought('count<thought_count');
out.parsedThoughtMultiTag = api.parseThought('<thought>하나</thought>본문<thought>둘</thought>');
// #189: code is never a thought marker; unclosed markers hide only while streaming
const quotedTag = '태그는 `<thought>` 이렇게 써.\n뒤 문단도 남아야 해';
out.quotedTagFinal = api.parseThought(quotedTag, false);
out.quotedTagStreaming = api.parseThought(quotedTag, true);
const quotedFence = '` ```thought ` 로 열고 ` ``` ` 로 닫아.\n끝';
out.quotedFenceFinal = api.parseThought(quotedFence, false);
// companion (regression guard): an unmatched backtick stays literal and scanning goes on
out.unmatchedThenTag = api.parseThought('`로 시작 <thought>x</thought> 끝', false);
// companion (regression guard)
out.fenceBlock = api.parseThought('안녕!\n```thought\n속마음\n```\n뒤', false);
const openFence = '안녕!\n```thought\n반쯤 쓴';
out.openFenceStreaming = api.parseThought(openFence, true);
// companion (regression guard)
out.openFenceFinal = api.parseThought(openFence, false);
// companion (regression guard)
out.plainWordsFinal = api.parseThought('I thought th tho though it was fine', false);
// companion (regression guard)
out.plainWordsStreaming = api.parseThought('I thought th tho though it was fine', true);
out.bareLtStreaming = api.parseThought('안녕 <', true);
out.openTagNoFlag = api.parseThought('안녕! <thought>미완', undefined);

// chips: only the newest message keeps them
function msg(cls) { const m = el('div'); m.className = cls; const md = el('div'); md.className = 'md'; m.appendChild(md); logEl.appendChild(m); return m; }
const m1 = msg('msg assistant'), m2 = msg('msg assistant');
api.renderChoiceChips(m1, ['A', 'B']);
api.renderChoiceChips(m2, ['C', 'D', 'E']);
api.syncChoiceChips();
out.afterTwo = { m1: m1.all('.choice-chips').length, m2: m2.all('.choice-chips').length,
                 labels: m2.all('.choice-chip').map(x => x.textContent) };
const u = msg('msg user');
api.syncChoiceChips();
out.afterUser = { m2: m2.all('.choice-chips').length };
// a system notice after the message must not steal "newest"
const m3 = msg('msg assistant'); api.renderChoiceChips(m3, ['Z']);
msg('msg assistant system');
api.syncChoiceChips();
out.systemIgnored = m3.all('.choice-chips').length;
// click sends the label
m3.all('.choice-chip')[0].handlers.click();
out.sent = sent.slice();

// action chip rendering and click
const m4 = msg('msg assistant');
api.renderChoiceChips(m4, out.actionChoices.choices);
out.actionRender = {
  chips: m4.all('.choice-chip').map(c => ({ text: c.textContent, isAction: (c.className || '').includes('choice-action') }))
};
m4.all('.choice-chip')[0].handlers.click();
out.actionSent = inputEl.value;

api.renderChoiceChips(m3, []);
out.cleared = m3.all('.choice-chips').length;

// choiceBar attach and cleanup
choiceBarAttached = true;
const m5 = msg('msg assistant');
api.renderChoiceChips(m5, ['Option 1', 'Option 2']);
const barVisible = !choiceBar.hidden;
api.renderChoiceChips(m5, []);
const barHidden = choiceBar.hidden;

// Generalized sticky-bottom scroll with shared ResizeObserver (#211)
const path = require('path');
const messagesPath = path.resolve(path.dirname(process.argv[process.argv.length - 1]), 'app-messages.js');
const messagesCode = fs.readFileSync(messagesPath, 'utf8');

class FakeResizeObserver {
  constructor(cb) {
    this.cb = cb;
    FakeResizeObserver.observedList = this.observed = [];
    FakeResizeObserver.instance = this;
  }
  observe(target) {
    if (!this.observed.includes(target)) this.observed.push(target);
  }
  unobserve(target) {
    this.observed = this.observed.filter(t => t !== target);
  }
  disconnect() {
    this.observed = [];
  }
  trigger() {
    this.cb(this.observed.map(target => ({ target })));
  }
}
FakeResizeObserver.observedList = [];

const testLogEl = el('div');
testLogEl.scrollHeight = 600;
testLogEl.clientHeight = 400;
testLogEl.scrollTop = 200;

const testScrollBtn = el('button');
testScrollBtn.hidden = true;

let isKbTransitioning = false;

const testDoc = {
  createElement: el,
  getElementById: (id) => (id === 'log' ? testLogEl : (id === 'scrollToBottomBtn' ? testScrollBtn : null)),
  body: { classList: { contains: () => false, toggle: () => {} } },
};

const msgApi = new Function(
  'document', 'ResizeObserver', 'logEl', 'scrollToBottomBtn', 'currentTab', 'isKeyboardTransitioning', 'viewingPastSession',
  messagesCode + `
  return {
    isUserNearBottom,
    scrollChatToBottom,
    updateScrollBottomButton,
    handleMsgResize,
    observeMessage,
    getIsLogPinnedToBottom: () => isLogPinnedToBottom,
    setIsLogPinnedToBottom: (v) => { isLogPinnedToBottom = v; },
  };`
)(testDoc, FakeResizeObserver, testLogEl, testScrollBtn, 'chat', () => isKbTransitioning, () => false);

// 1. Observe a message bubble as it is added
const bubble = el('div');
bubble.className = 'msg assistant';
msgApi.observeMessage(bubble);
testLogEl.appendChild(bubble);

// When pinned before growth: asserts log stays pinned
testLogEl.scrollHeight = 1000;
msgApi.handleMsgResize();
const resizePinned = {
  scrollTop: testLogEl.scrollTop,
  scrollHeight: testLogEl.scrollHeight,
  btnHidden: testScrollBtn.hidden,
};

// 2. When user scrolled away from bottom: asserts log stays put
testLogEl.scrollTop = 150;
msgApi.setIsLogPinnedToBottom(false);
msgApi.updateScrollBottomButton();
testLogEl.scrollHeight = 1500;
msgApi.handleMsgResize();
const resizeScrolledAway = {
  scrollTop: testLogEl.scrollTop,
  scrollHeight: testLogEl.scrollHeight,
  btnHidden: testScrollBtn.hidden,
};

// 3. Mid keyboard-open transition: must not re-pin
testLogEl.scrollTop = 1500;
msgApi.setIsLogPinnedToBottom(true);
isKbTransitioning = true;
testLogEl.scrollHeight = 2000;
msgApi.handleMsgResize();
const resizeMidKeyboard = {
  scrollTop: testLogEl.scrollTop,
};

out.stickyScroll = {
  barVisible,
  barHidden,
  observedBubble: FakeResizeObserver.observedList.includes(bubble),
  resizePinned,
  resizeScrolledAway,
  resizeMidKeyboard,
};

console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ChoiceChips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(MD)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_plain_text_is_untouched(self):
        self.assertEqual(self.o["plain"], {"text": "그냥 답변", "choices": []})

    def test_trailing_marker_becomes_choices_and_leaves_the_body_clean(self):
        self.assertEqual(self.o["full"]["choices"], ["A. UI 개선", "B. 토큰 최적화"])
        self.assertEqual(self.o["full"]["text"], "어느 쪽이 좋을까냥?")
        self.assertEqual(self.o["trailingWs"], {"text": "질문", "choices": ["예", "아니오"]})

    def test_at_most_four_and_no_empty_labels(self):
        self.assertEqual(self.o["capped"], ["1", "2", "3", "4"])
        self.assertEqual(self.o["emptyItems"], ["a", "b"])

    def test_half_streamed_marker_never_shows(self):
        self.assertEqual(self.o["streamingHalf"], {"text": "질문", "choices": []})
        self.assertEqual(self.o["streamingOpenOnly"], {"text": "질문", "choices": []})

    def test_only_a_trailing_marker_counts(self):
        self.assertEqual(self.o["midText"]["choices"], [])
        self.assertIn("<!--choices: x-->", self.o["midText"]["text"])
        self.assertEqual(self.o["otherComment"], "a <!-- note -->")

    def test_a_quoted_marker_in_the_body_is_kept_and_only_the_last_counts(self):
        self.assertEqual(self.o["quotedThenTail"]["choices"], ["예", "아니오"])
        self.assertEqual(self.o["quotedThenTail"]["text"], "본문에 `<!--choices: 라벨 -> (행동)-->`을 쓰면\n뒤 문단")
        self.assertEqual(self.o["quotedOnly"], {"text": "예시 `<!--choices: A | B-->` 뒤 문단", "choices": []})

    def test_only_the_newest_message_keeps_its_chips(self):
        self.assertEqual(self.o["afterTwo"], {"m1": 0, "m2": 1, "labels": ["C", "D", "E"]})
        self.assertEqual(self.o["afterUser"], {"m2": 0})
        self.assertEqual(self.o["systemIgnored"], 1)

    def test_click_sends_the_label_and_empty_choices_clear_the_row(self):
        self.assertEqual(self.o["sent"], ["Z"])
        self.assertEqual(self.o["cleared"], 0)

    def test_action_choices_and_expressions(self):
        self.assertEqual(self.o["parsedExp"], {"expression": "joy", "text": "반갑다냥!"})
        self.assertEqual(self.o["parsedThoughtState"], {"thought": "반가운 마음", "cleanText": "안녕!"})
        self.assertEqual(self.o["parsedThoughtTag"], {"thought": "내면 독백", "cleanText": "안녕!"})
        chips = self.o["actionRender"]["chips"]
        self.assertEqual(chips[0], {"text": "✦ 다가가기", "isAction": True})
        self.assertEqual(chips[1], {"text": "인사하기", "isAction": False})
        self.assertEqual(self.o["actionSent"], "/act 조용히 다가간다")

    def test_dangling_or_partial_thought_tag_is_hidden(self):
        self.assertNotIn("<thought", self.o["parsedThoughtOpen"]["cleanText"])
        self.assertNotIn("<thoug", self.o["parsedThoughtOpen"]["cleanText"])
        self.assertEqual(self.o["parsedThoughtOpen"]["thought"], "아직 안 끝난 속마음")
        self.assertEqual(self.o["parsedThoughtOpen"]["cleanText"], "안녕!")

        self.assertNotIn("<thought", self.o["parsedThoughtPartialTag"]["cleanText"])
        self.assertNotIn("<thoug", self.o["parsedThoughtPartialTag"]["cleanText"])
        self.assertIsNone(self.o["parsedThoughtPartialTag"]["thought"])
        self.assertEqual(self.o["parsedThoughtPartialTag"]["cleanText"], "안녕!")

    def test_thought_open_does_not_swallow_bare_lt_text_or_choices(self):
        self.assertIsNone(self.o["parsedThoughtBareLt"]["thought"])
        self.assertEqual(self.o["parsedThoughtBareLt"]["cleanText"], "안녕 <")

        self.assertIsNone(self.o["parsedThoughtMath"]["thought"])
        self.assertEqual(self.o["parsedThoughtMath"]["cleanText"], "1 < 2")

        self.assertIsNone(self.o["parsedThoughtChoices"]["thought"])
        self.assertEqual(self.o["parsedThoughtChoices"]["cleanText"], "질문\n<!--choices: A | B-->")

        self.assertIsNone(self.o["parsedThoughtChoicesOpen"]["thought"])
        self.assertEqual(self.o["parsedThoughtChoicesOpen"]["cleanText"], "질문\n<!--choices")

        self.assertIsNone(self.o["parsedThoughtPartialTagWithTail"]["thought"])
        self.assertEqual(self.o["parsedThoughtPartialTagWithTail"]["cleanText"], "안녕! 뒷이야기가 이어짐")
        self.assertNotIn("<thoug", self.o["parsedThoughtPartialTagWithTail"]["cleanText"])

    def test_corrupt_thought_fragment_recovery(self):
        self.assertEqual(self.o["parsedThoughtPartialDots"], {"thought": None, "cleanText": "안녕!"})
        self.assertEqual(self.o["parsedThoughtCorruptDots"], {"thought": None, "cleanText": "안녕! 뒷이야기"})
        self.assertEqual(self.o["parsedThoughtCorruptThoughtDots"], {"thought": None, "cleanText": "안녕! 뒷이야기"})
        self.assertEqual(self.o["parsedThoughtOrphanClose"], {"thought": None, "cleanText": "안녕! 뒷이야기"})
        self.assertEqual(self.o["parsedThoughtSessionEvent"], {"thought": None, "cleanText": "[expression: shy]\n없이 거세게 몰아치는 충격"})
        self.assertEqual(self.o["parsedThoughtSessionRepl"], {"thought": None, "cleanText": "[expression: shy]\n한 침대 위로"})
        self.assertEqual(self.o["parsedThoughtCodeLt"], {"thought": None, "cleanText": "count<thought_count"})
        self.assertEqual(self.o["parsedThoughtMultiTag"], {"thought": "하나\n둘", "cleanText": "본문"})

    def test_code_is_never_a_thought_marker(self):
        # rule 1: a quoted <thought> in inline code keeps the whole body, final or streaming
        body = "태그는 `<thought>` 이렇게 써.\n뒤 문단도 남아야 해"
        self.assertEqual(self.o["quotedTagFinal"], {"thought": None, "cleanText": body})
        self.assertEqual(self.o["quotedTagStreaming"], {"thought": None, "cleanText": body})
        # rule 1: ```thought and ``` inside code spans do not open/close a thought fence
        self.assertEqual(self.o["quotedFenceFinal"], {"thought": None, "cleanText": "` ```thought ` 로 열고 ` ``` ` 로 닫아.\n끝"})
        # rule 1+2: the lone backtick is copied, the real pair after it is still removed (companion)
        self.assertEqual(self.o["unmatchedThenTag"], {"thought": "x", "cleanText": "`로 시작  끝"})

    def test_thought_fence_and_streaming_only_hiding(self):
        # rule 2 (companion)
        self.assertEqual(self.o["fenceBlock"], {"thought": "속마음", "cleanText": "안녕!\n\n뒤"})
        # rule 3: unclosed ```thought hidden while streaming, shown verbatim once final (final is companion)
        self.assertEqual(self.o["openFenceStreaming"], {"thought": "반쯤 쓴", "cleanText": "안녕!"})
        self.assertEqual(self.o["openFenceFinal"], {"thought": None, "cleanText": "안녕!\n```thought\n반쯤 쓴"})
        # rule 3: a bare trailing '<' is a possible tag start only mid-stream
        self.assertEqual(self.o["bareLtStreaming"], {"thought": None, "cleanText": "안녕"})
        # rule 5 (companion): plain th/tho/though words are body text in both modes
        words = {"thought": None, "cleanText": "I thought th tho though it was fine"}
        self.assertEqual(self.o["plainWordsFinal"], words)
        self.assertEqual(self.o["plainWordsStreaming"], words)

    def test_omitted_is_final_shows_body(self):
        # rule 3: no streaming flag means not streaming, so an unclosed tag stays visible
        self.assertEqual(self.o["openTagNoFlag"], {"thought": None, "cleanText": "안녕! <thought>미완"})
        # both callers map only an explicit isFinal === false to streaming
        src = MD.read_text(encoding="utf-8")
        self.assertIn("parseThought(rawText, isFinal === false)", src)
        self.assertIn("parseThought(raw, isFinal === false)", src)

    def test_bubble_resize_sticky_bottom(self):
        sticky = self.o["stickyScroll"]
        self.assertTrue(sticky["observedBubble"])
        self.assertTrue(sticky["barVisible"])
        self.assertTrue(sticky["barHidden"])

        # 1. Bubble grows when pinned: log stays pinned to bottom
        self.assertEqual(sticky["resizePinned"]["scrollTop"], sticky["resizePinned"]["scrollHeight"])
        self.assertTrue(sticky["resizePinned"]["btnHidden"])

        # 2. Bubble grows when user had scrolled up: scroll position stays put
        self.assertEqual(sticky["resizeScrolledAway"]["scrollTop"], 150)
        self.assertFalse(sticky["resizeScrolledAway"]["btnHidden"])

        # 3. Bubble grows mid keyboard-open transition: does not re-pin
        self.assertEqual(sticky["resizeMidKeyboard"]["scrollTop"], 1500)



    def test_private_choice_forms_say_action_combo(self):
        """Private forms: (action)->/act; \"line\"->say; \"line\" (act)->user speech+action not /act."""
        if not shutil.which("node"):
            self.skipTest("node not installed")
        js = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a0 = src.indexOf('function stripOuterParens');
const a = src.indexOf('function classifyChoicePayload');
const b = src.indexOf('function splitChoices');
if (a < 0 || b < 0) throw new Error('markers');
eval(src.slice(a0 >= 0 ? a0 : a, b));
const act = classifyChoicePayload('(조용히 끌어안는다)');
const say = classifyChoicePayload('"조금만 더 가까이"');
const combo = classifyChoicePayload('"자기, 여기" (귀에 숨을 흘린다)');
const charLeak = classifyChoicePayload('"하읏… 안 돼" (몸을 떤다)');
const curlyAct = classifyChoicePayload('（조용히 끌어안는다）');
const smartCombo = classifyChoicePayload('\u201C자기, 여기\u201D (귀에 숨을 흘린다)');
const bareAct = classifyChoicePayload('허리를 바짝 붙인다');
console.log(JSON.stringify({act, say, combo, charLeak, curlyAct, smartCombo, bareAct}));
"""
        r = subprocess.run(
            ["node", "-e", js, str(MD)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads(r.stdout)
        self.assertEqual(o["act"]["kind"], "action")
        self.assertTrue(o["act"]["isAction"])
        self.assertEqual(o["say"]["kind"], "action")
        self.assertTrue(o["say"]["isAction"])
        self.assertIn("조금만 더 가까이", o["say"]["payload"])
        self.assertEqual(o["combo"]["kind"], "action")
        self.assertTrue(o["combo"]["isAction"])
        self.assertIn("자기, 여기", o["combo"]["payload"])
        self.assertIn("귀에 숨을", o["combo"]["payload"])
        self.assertEqual(o["curlyAct"]["kind"], "action")
        self.assertTrue(o["curlyAct"]["isAction"])
        self.assertEqual(o["smartCombo"]["kind"], "action")
        self.assertTrue(o["smartCombo"]["isAction"])
        self.assertEqual(o["bareAct"]["kind"], "action")
        self.assertTrue(o["bareAct"]["isAction"])


if __name__ == "__main__":
    unittest.main()
