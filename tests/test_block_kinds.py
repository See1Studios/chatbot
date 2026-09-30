"""The answer is made of kinds, and the UI can finally tell them apart (BLOCK_KINDS_v1).

The model emits distinct kinds -- *action*, "speech", a ```thought fence, a trailing choices
comment -- and the client parsed three of the four and dropped the other two into one anonymous
blob. These are the pure functions that say what a piece of text is, with no DOM and no styling:
what looks or moves is chat-log.css's business.

They are deliberately conservative. An ambiguous stretch stays narration, because a wrong split
damages reading while a missed split costs only the treatment. Every ambiguity below is a test.

Run: python3 -m unittest tests.test_block_kinds  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import app_bundle  # noqa: E402

CODE = Path(__file__).resolve().parent.parent
APP = app_bundle()

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('const BLOCK_NARRATION');
// Run to the end of the file this marker starts in, so blockIsQuiet comes along.
const b = src.indexOf('// ==== file:', a);
if (a < 0 || b < 0) throw new Error('BLOCK_KINDS markers missing');
eval(src.slice(a, b));

function makeEl(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    className: '',
    attributes: {},
    children: [],
    parentNode: null,
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return this.attributes[k] || null; },
    appendChild(child) {
      if (child.parentNode && child.parentNode.removeChild) {
        child.parentNode.removeChild(child);
      }
      this.children.push(child);
      child.parentNode = this;
      return child;
    },
    removeChild(child) {
      const idx = this.children.indexOf(child);
      if (idx >= 0) this.children.splice(idx, 1);
      child.parentNode = null;
      return child;
    },
    get firstChild() { return this.children[0] || null; },
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(val) {
      this._html = val;
      const m = /^\s*<([a-zA-Z0-9]+)[^>]*>([\s\S]*)<\/\1>\s*$/.exec(val);
      if (m) {
        const child = makeEl(m[1]);
        child.innerHTML = m[2];
        this.children = [child];
        child.parentNode = this;
      } else {
        this.children = [];
      }
    }
  };
  return el;
}
const document = { createElement: makeEl };
function renderMarkdown(t) { return '<p>' + t + '</p>'; }

const c = src.indexOf('function buildBlock(');
const d = src.indexOf('function renderTypedBody(', c);
if (c >= 0 && d >= 0) eval(src.slice(c, d));

const inspectBlock = (box) => ({
  kind: box.getAttribute('data-kind'),
  className: box.className,
  children: box.children.map(ch => ({
    tag: ch.tagName.toLowerCase(),
    kind: ch.getAttribute('data-kind'),
    className: ch.className,
    html: ch.innerHTML
  }))
});

const N = 'narration', D = 'dialogue', A = 'action';
const shape = (blocks) => blocks.map(x => x.kind + ':' + JSON.stringify(x.text));

const CASES = {
  build_block_mixed_line: () => {
    const block = classifyBlocks('*눈을 내리며* "이제 알겠어요." 그래, 그럴지도.')[0];
    return inspectBlock(buildBlock(block, true));
  },
  build_block_single_paragraph: () => {
    const block = classifyBlocks('창밖이 조용했다.')[0];
    return inspectBlock(buildBlock(block, true));
  },
  build_block_speech_paragraph: () => {
    const block = classifyBlocks('"왜 그랬어요?"')[0];
    return inspectBlock(buildBlock(block, true));
  },
  paragraph_kinds: () => shape(classifyBlocks('*고개를 기울였다*\n\n"왜 그랬어요?"\n\n창밖이 조용했다.')),
  mixed_one_line: () => shape(splitInline('*눈을 내리며* "이제 알겠어요." 그래, 그럴지도.')),
  action_only_line: () => shape(splitInline('*손끝이 떨렸다*')),
  speech_only_line: () => shape(splitInline('"\u201C왔어요\u201D"')),
  underline_action: () => shape(classifyBlocks('_한숨을 쉬었다_')),
  cjk_brackets: () => shape(classifyBlocks('\u300C여기 있나요\u300D')),
  code_fence_untouched: () => shape(classifyBlocks('본문\n\n```\n*이건 코드다*\n```\n\n끝')),
  code_with_quotes_untouched: () => shape(classifyBlocks('```py\nprint("hi")\n```')),
  odd_quotes_leave_whole: () => shape(splitInline('그가 말했다 "시작해" 그리고 멈췄다 "왜"')),
  unterminated_quote_leaves_whole: () => shape(splitInline('\u201C이게 다야')),
  stray_asterisk_is_text: () => shape(splitInline('2 * 3 = 6이라 했다')),
  empty_asterisks_are_text: () => shape(splitInline('**굵게** 라고 했다')),
  list_bullet_with_bold: () => shape(splitInline('* **질문**')),
  list_stays_whole: () => shape(classifyBlocks('- 하나\n- 둘\n\n"그리고?"')),
  blank_input: () => shape(classifyBlocks('')),
  whitespace_only: () => shape(classifyBlocks('   \n\n  ')),
  inline_emphasis_inside_speech: () => shape(splitInline('"\u201C**중요해** 이거\u201D"')),
  bold_wrapping_an_action: () => shape(splitInline('**a *b* c**')),
  bold_wrapping_speech: () => shape(splitInline('**안쪽에 "말" 있음**')),
  bold_beside_an_action: () => shape(splitInline('**굵게** 말 *행동*')),
  fence_flag: () => classifyBlocks('본문\n\n```py\nprint("hi")\n```'),
  runs_of_a_fence: () => shape(blockRuns(classifyBlocks('```py\nprint("hi")\n```')[0])),
  runs_of_prose: () => shape(blockRuns(classifyBlocks('*눈을 깜빡* "안녕" 끝')[0])),
  multi_paragraph_keeps_order: () => shape(classifyBlocks('하나\n\n둘\n\n셋')),
  // --- REVEAL_BLOCKS_v1: where a growing answer stops being finished ---
  reveal_a_paragraph: () => shape(revealBlocks('하나\n\n둘').blocks),
  reveal_grows: () => [4, 6, 7, 10].map(n => revealBlocks('*눈을*\n\n둘\n셋\n\n넷'.slice(0, n)).blocks.length),
  reveal_list_waits_for_its_end: () => shape(revealBlocks('- 하나\n- 둘').blocks),
  reveal_list_closes_at_a_blank: () => shape(revealBlocks('- 하나\n- 둘\n\n끝').blocks),
  reveal_list_open_tail: () => revealBlocks('- 하나\n- 둘\n\n끝').open,
  reveal_open_fence_is_not_closed: () => shape(revealBlocks('```py\nprint(1)').blocks),
  reveal_closed_fence_is: () => shape(revealBlocks('```py\nprint(1)\n```').blocks),
  reveal_table_waits_for_a_non_row: () => shape(revealBlocks('| a | b |\n|---|---|\n| 1 | 2 |\n끝').blocks),
  reveal_table_open_tail: () => revealBlocks('| a | b |\n|---|---|\n| 1 | 2 |\n끝').open,
  reveal_heading_is_one_line: () => shape(revealBlocks('## 제목\n\n본문').blocks),
  reveal_the_last_block_is_always_open: () => revealBlocks('하나\n\n둘\n\n셋').blocks.length,
  reveal_open_text: () => revealBlocks('하나\n\n둘째 문장').open,
  unit_kind_tracks_the_last_thing_written: () => ['*눈을', '*눈을 깜빡*', '"안녕', '"안녕"'].map(unitKind),
  // --- STAGE_v1 (ux/S5): actions leave the bubble, decided by shape alone ---
  stage_action_and_speech: () => shape(answerBlocks('*고개를 기울이며 웃는다* "오늘은 어땠어?"')),
  stage_several: () => shape(answerBlocks('*a* "b" *c* "d"')),
  stage_whole_action: () => shape(answerBlocks('*창밖을 본다*')),
  stage_emphasis_stays: () => shape(answerBlocks('이건 *정말* 중요해.')),
  stage_unquoted_prose_stays: () => shape(answerBlocks('*웃으며* 그래, 그렇게 하자.')),
  stage_speech_only_stays: () => shape(answerBlocks('"하나" "둘"')),
  stage_code_stays: () => shape(answerBlocks('```\n*a* "b"\n```')),
  stage_while_streaming: () => shape(revealBlocks('*웃는다* "안녕"\n\n끝').blocks),
  stage_layout: () => {
    const aug = (e) => {
      e.classList = { contains: c => e.className.split(' ').includes(c),
        add: c => { if (!e.classList.contains(c)) e.className = (e.className + ' ' + c).trim(); } };
      Object.defineProperty(e, 'previousElementSibling', { get() { const s = e.parentNode.children; return s[s.indexOf(e) - 1] || null; } });
      e.insertBefore = (n, ref) => { if (n.parentNode) n.parentNode.removeChild(n); e.children.splice(e.children.indexOf(ref), 0, n); n.parentNode = e; return n; };
      return e;
    };
    const real = document.createElement;
    document.createElement = (t) => aug(makeEl(t));
    const blk = (kind, open) => { const b = aug(makeEl('div')); b.className = 'md-block' + (open ? ' open' : ''); b.setAttribute('data-kind', kind); return b; };
    const msg = aug(makeEl('div')), md = aug(makeEl('div'));
    msg.appendChild(md);
    const view = () => md.children.map(c => c.classList.contains('md-say')
      ? '[' + c.children.map(x => x.getAttribute('data-kind')).join(' ') + ']'
      : c.getAttribute('data-kind') + (c.classList.contains('open') ? '~' : ''));
    const open = blk('narration', true);
    [blk('narration'), blk('dialogue'), open].forEach(b => md.appendChild(b));
    stageLayout(md);
    const plain = { view: view(), staged: msg.classList.contains('staged') };
    md.insertBefore(blk('action'), open); md.insertBefore(blk('dialogue'), open);
    stageLayout(md); const first = view();
    stageLayout(md); const again = view();
    md.insertBefore(blk('narration'), open); stageLayout(md); const joined = view();
    md.insertBefore(blk('action'), open); md.insertBefore(blk('narration'), open); stageLayout(md); const next = view();
    document.createElement = real;
    return { plain, first, again, joined, next, staged: msg.classList.contains('staged'), openStillInBody: open.parentNode === md,
      narr: md.children.filter(c => c.classList.contains('md-narr')).map(c => c.getAttribute('data-kind')), out: ['narration', 'dialogue', 'action'].filter(blockIsStaged) };
  },
  quiet_block: () => {
    const q = [blockIsQuiet({ text: '  ' }), blockIsQuiet({ text: '- 하나' })];
    const n = blockIsQuiet({ text: '본문' });
    return { q: q, n: n };
  },
};
console.log(JSON.stringify(CASES[process.argv[2]]()));
"""


def run(case):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not installed")
    proc = subprocess.run([node, "-e", HARNESS, str(APP), case], capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        raise AssertionError("node failed for %s: %s" % (case, proc.stderr.strip()[:600]))
    return json.loads(proc.stdout.strip().splitlines()[-1])


class Stage(unittest.TestCase):
    """STAGE_v1 (ux/S5): an action is narration between bubbles, not part of one. Shape decides, in every room."""

    def test_a_paragraph_of_actions_and_quoted_speech_is_taken_apart(self):
        self.assertEqual(run("stage_action_and_speech"),
                         ['action:"*고개를 기울이며 웃는다*"', 'dialogue:"\\"오늘은 어땠어?\\""'])
        self.assertEqual([x.split(":")[0] for x in run("stage_several")], ["action", "dialogue", "action", "dialogue"])
        self.assertEqual(run("stage_whole_action"), ['action:"*창밖을 본다*"'])

    def test_anything_else_stays_whole(self):
        # emphasis in a sentence, an action beside unquoted prose (the cut would be a guess), speech alone, code
        for case in ("stage_emphasis_stays", "stage_unquoted_prose_stays", "stage_speech_only_stays", "stage_code_stays"):
            out = run(case)
            self.assertEqual(len(out), 1, case)
            self.assertTrue(out[0].startswith("narration:"), case)

    def test_a_block_that_closes_while_streaming_is_staged_the_same(self):
        self.assertEqual([x.split(":")[0] for x in run("stage_while_streaming")], ["action", "dialogue"])

    def test_speech_runs_become_bubbles_around_the_actions(self):
        o = run("stage_layout")
        # no action: the answer is one bubble, as before
        self.assertEqual(o["plain"], {"view": ["narration", "dialogue", "narration~"], "staged": False})
        # an action arrives: what came before it is one bubble, what follows is the next
        self.assertEqual(o["first"], ["[narration dialogue]", "action", "[dialogue]", "narration~"])
        self.assertEqual(o["again"], o["first"])                                   # running it again changes nothing
        self.assertEqual(o["joined"], ["[narration dialogue]", "action", "[dialogue narration]", "narration~"])
        self.assertEqual(o["next"], ["[narration dialogue]", "action", "[dialogue narration]", "action", "[narration]", "narration~"])
        self.assertTrue(o["staged"])
        self.assertTrue(o["openStillInBody"])     # the block being written stays where the reveal inserts before it
        # which kinds leave the bubble is one list; layout follows a class, not the kind's name
        self.assertEqual(o["out"], ["action"])
        self.assertEqual(o["narr"], ["action", "action"])


class BlockKinds(unittest.TestCase):
    def test_a_paragraph_that_is_entirely_one_kind_is_that_kind(self):
        out = run("paragraph_kinds")
        self.assertEqual(out, [
            'action:"*고개를 기울였다*"',
            'dialogue:"\\"왜 그랬어요?\\""',
            'narration:"창밖이 조용했다."',
        ])

    def test_the_common_mixed_line_is_split_into_its_parts(self):
        # *action* "speech" narration on one line is what RENDER_PROTOCOL asks for; a paragraph-only
        # classifier would have thrown the whole line away as narration.
        out = run("mixed_one_line")
        self.assertEqual(out, [
            'action:"*눈을 내리며*"',
            'dialogue:"\\"이제 알겠어요.\\""',
            'narration:" 그래, 그럴지도."',
        ])

    def test_underline_and_cjk_brackets_are_recognised(self):
        self.assertEqual(run("underline_action"), ['action:"_한숨을 쉬었다_"'])
        self.assertEqual(run("cjk_brackets"), ['dialogue:"「여기 있나요」"'])

    def test_a_code_fence_is_never_classified(self):
        # *이건 코드다* and print("hi") would both be read as action/speech if the fence were not
        # carved out first.
        out = run("code_fence_untouched")
        self.assertEqual(out, [
            'narration:"본문"',
            'narration:"```\\n*이건 코드다*\\n```"',
            'narration:"끝"',
        ])
        self.assertEqual(run("code_with_quotes_untouched"), ['narration:"```py\\nprint(\\"hi\\")\\n```"'])

    def test_two_quoted_spans_on_one_line_are_two_spans(self):
        # Four quote marks is not ambiguous -- it is two spoken stretches, and reading them as one
        # would be worse than splitting. The ambiguous case is an unpaired one.
        out = run("odd_quotes_leave_whole")
        self.assertEqual(out, [
            'narration:"그가 말했다 "',
            'dialogue:"\\"시작해\\""',
            'narration:" 그리고 멈췄다 "',
            'dialogue:"\\"왜\\""',
        ])

    def test_an_unpaired_quote_leaves_the_whole_run_as_narration(self):
        out = run("unterminated_quote_leaves_whole")
        self.assertEqual(out, ['narration:"“이게 다야"'],
                         "a quote with no partner must not become half a sentence")

    def test_an_asterisk_that_is_arithmetic_or_emphasis_is_text(self):
        self.assertEqual(run("stray_asterisk_is_text"), ['narration:"2 * 3 = 6이라 했다"'])
        self.assertEqual(run("empty_asterisks_are_text"), ['narration:"**굵게** 라고 했다"'])

    def test_list_bullet_with_bold_is_not_split_as_action(self):
        self.assertEqual(run("list_bullet_with_bold"), ['narration:"* **질문**"'])

    def test_a_list_is_not_cut_into_beats(self):
        out = run("list_stays_whole")
        self.assertEqual(out, ['narration:"- 하나\\n- 둘"', 'dialogue:"\\"그리고?\\""'])

    def test_empty_input_yields_one_empty_narration_block(self):
        self.assertEqual(run("blank_input"), ['narration:""'])
        self.assertEqual(run("whitespace_only"), ['narration:"   \\n\\n  "'])

    def test_markdown_inside_speech_still_reads_as_speech(self):
        out = run("inline_emphasis_inside_speech")
        self.assertEqual(out, ['dialogue:"\\"“**중요해** 이거”\\""'],
                         "bold inside a spoken line must not break the span")

    def test_paragraph_order_is_preserved(self):
        self.assertEqual(run("multi_paragraph_keeps_order"),
                         ['narration:"하나"', 'narration:"둘"', 'narration:"셋"'])

    def test_bold_is_consumed_as_a_unit_and_nothing_inside_it_is_classified(self):
        # `**a *b* c**` is bold with an italic inside. Pulling the inner *b* out as an action of its
        # own leaves two dangling ** in the prose, which is louder damage than not classifying it.
        for case in ("bold_wrapping_an_action", "bold_wrapping_speech"):
            out = run(case)
            self.assertEqual(len(out), 1, "%s was split: %s" % (case, out))
            self.assertTrue(out[0].startswith("narration:"), "%s -> %s" % (case, out))
        self.assertEqual(run("bold_beside_an_action"),
                         ['narration:"**굵게** 말 "', 'action:"*행동*"'],
                         "bold next to an action is still an action")

    def test_a_quote_inside_a_code_block_is_a_string_literal(self):
        # A fence is carved out of classification, but the renderer splits a prose block inline --
        # and it used to inline-split the fence too, turning print("hi") into a spoken line. The
        # fence keeps its own flag so that cannot happen.
        blocks = run("fence_flag")
        self.assertEqual([b.get("fenced") for b in blocks], [None, True],
                         "only the fence is flagged; prose around it is not")
        self.assertEqual(run("runs_of_a_fence"),
                         ['narration:"```py\\nprint(\\"hi\\")\\n```"'],
                         "a fenced block must render as exactly one run")
        self.assertEqual(run("runs_of_prose"),
                         ['action:"*눈을 깜빡*"', 'dialogue:"\\"안녕\\""', 'narration:" 끝"'],
                         "prose still splits inline")

    def test_a_block_is_finished_only_when_its_extent_has_arrived(self):
        # The whole reveal rests on this. A block that has closed can never change again, which is
        # why it can be rendered once instead of re-parsed on every frame.
        self.assertEqual(run("reveal_a_paragraph"), ['narration:"하나"'],
                         "a paragraph needs the blank line after it")
        self.assertEqual(run("reveal_grows"), [0, 1, 1, 2],
                         "blocks appear one at a time as their extents complete")
        self.assertEqual(run("reveal_the_last_block_is_always_open"), 2,
                         "the last block has nothing after it yet, so it is still being written")

    def test_a_list_and_a_table_wait_for_the_line_that_ends_them(self):
        # Both keep taking rows, so neither is finished while it could still grow -- except a list
        # at the very end, which is why a trailing list appears with the final render instead.
        self.assertEqual(run("reveal_list_waits_for_its_end"), [],
                         "a list could still take another item")
        self.assertEqual(run("reveal_list_closes_at_a_blank"),
                         ['narration:"- 하나\\n- 둘"'])
        self.assertEqual(run("reveal_list_open_tail"), "끝")
        self.assertEqual(run("reveal_table_waits_for_a_non_row"),
                         ['narration:"| a | b |\\n|---|---|\\n| 1 | 2 |"'])
        self.assertEqual(run("reveal_table_open_tail"), "끝")

    def test_a_fence_closes_on_its_own_marks_and_not_on_a_blank_line(self):
        self.assertEqual(run("reveal_open_fence_is_not_closed"), [],
                         "a fence with no closing ``` yet could still take more lines")
        self.assertEqual(run("reveal_closed_fence_is"), ['narration:"```py\\nprint(1)\\n```"'])

    def test_a_heading_is_finished_at_its_own_newline(self):
        self.assertEqual(run("reveal_heading_is_one_line"), ['narration:"## 제목"'])

    def test_the_block_being_written_is_returned_whole(self):
        self.assertEqual(run("reveal_open_text"), "둘째 문장")

    def test_the_kind_being_written_is_the_last_thing_with_ink_on_it(self):
        # A line that has an action and then speech is being SPOKEN during, and the motion should
        # say so. A quote with no closing mark yet is still narration: a kind is only known once
        # its extent has arrived.
        self.assertEqual(run("unit_kind_tracks_the_last_thing_written"),
                         ["narration", "action", "narration", "dialogue"])

    def test_a_continuation_line_is_quiet(self):
        out = run("quiet_block")
        self.assertEqual(out, {"q": [True, True], "n": False},
                         "a list item or a quote line must stay attached to the block above")

    def test_build_block_mixed_line_unwraps_p_and_preserves_classes(self):
        out = run("build_block_mixed_line")
        self.assertEqual(out["kind"], "narration")
        self.assertEqual(out["className"], "md-block")
        self.assertEqual(len(out["children"]), 3)
        self.assertEqual(out["children"][0], {
            "tag": "span", "kind": "action", "className": "md-action", "html": "*눈을 내리며*"
        })
        self.assertEqual(out["children"][1], {
            "tag": "span", "kind": "dialogue", "className": "md-dialogue", "html": '"이제 알겠어요."'
        })
        self.assertEqual(out["children"][2], {
            "tag": "span", "kind": None, "className": "", "html": " 그래, 그럴지도."
        })

    def test_build_block_single_paragraph_preserves_block_tag(self):
        out = run("build_block_single_paragraph")
        self.assertEqual(out["kind"], "narration")
        self.assertEqual(len(out["children"]), 1)
        self.assertEqual(out["children"][0]["tag"], "p")
        self.assertEqual(out["children"][0]["html"], "창밖이 조용했다.")

    def test_build_block_speech_paragraph_preserves_dialogue_kind(self):
        out = run("build_block_speech_paragraph")
        self.assertEqual(out["kind"], "dialogue")
        self.assertEqual(len(out["children"]), 1)
        self.assertEqual(out["children"][0]["tag"], "p")
        self.assertEqual(out["children"][0]["html"], '"왜 그랬어요?"')


if __name__ == "__main__":
    unittest.main()

