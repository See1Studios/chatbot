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

const N = 'narration', D = 'dialogue', A = 'action';
const shape = (blocks) => blocks.map(x => x.kind + ':' + JSON.stringify(x.text));

const CASES = {
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
  list_stays_whole: () => shape(classifyBlocks('- 하나\n- 둘\n\n"그리고?"')),
  blank_input: () => shape(classifyBlocks('')),
  whitespace_only: () => shape(classifyBlocks('   \n\n  ')),
  inline_emphasis_inside_speech: () => shape(splitInline('"\u201C**중요해** 이거\u201D"')),
  bold_wrapping_an_action: () => shape(splitInline('**a *b* c**')),
  bold_wrapping_speech: () => shape(splitInline('**안쪽에 "말" 있음**')),
  bold_beside_an_action: () => shape(splitInline('**굵게** 말 *행동*')),
  multi_paragraph_keeps_order: () => shape(classifyBlocks('하나\n\n둘\n\n셋')),
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

    def test_a_continuation_line_is_quiet(self):
        out = run("quiet_block")
        self.assertEqual(out, {"q": [True, True], "n": False},
                         "a list item or a quote line must stay attached to the block above")


if __name__ == "__main__":
    unittest.main()
