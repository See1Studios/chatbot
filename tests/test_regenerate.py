"""Another take on the companion's last answer (REGENERATE_v1, docs/plans/regenerate-swipe.md R1-R3): only the last
answer, never one whose turn did more than read (D3), at most five takes (D5); a brain that is sent the history each
call is asked the same question with the old answer taken out, a brain that keeps its own conversation gets one host
note -- neither is stored as the user's words; the takes live on the item and its text is the picked one.
Run: engine/run-tests.sh test_regenerate
"""
import json
import shutil
import subprocess
import threading
import unittest

import regenerate as R  # noqa: E402
from tests._paths import ENGINE, REPO  # noqa: E402


class Adapter:
    def __init__(self, rebuild):
        self.rebuild = rebuild

    def rebuilds_context(self):
        return self.rebuild


class Sess:
    def __init__(self, rebuild=False, busy=False):
        self.lock = threading.RLock()
        self.adapter = Adapter(rebuild)
        self.busy = busy
        self.history = [{"role": "user", "text": "hi", "ts": 1.0},
                        {"role": "assistant", "text": "first", "ts": 2.0, "choices": ["a"]}]
        self.events, self.sent, self.saved = [], [], 0
        self._regen = None
        self._turn_effects = False

    def _is_busy(self):
        return self.busy

    def _emit(self, ev):
        self.events.append(ev)

    def save_meta(self):
        self.saved += 1

    def _send_direct(self, text, notice=False, event_type=""):
        self.sent.append((text, notice, event_type))

    def answer(self, text, ts):   # what finalize_turn appends at the take's end
        self.history.append({"role": "assistant", "text": text, "ts": ts})


class Start(unittest.TestCase):
    def test_refused_while_answering_without_a_last_answer_or_after_effects(self):
        for sess, key in ((Sess(busy=True), "regen.busy"),):
            with self.assertRaises(R.RegenError) as c:
                R.start(sess)
            self.assertEqual(str(c.exception), key)
        s = Sess()
        s.history.append({"role": "user", "text": "more", "ts": 3.0})
        with self.assertRaises(R.RegenError):
            R.start(s)
        s = Sess()
        s.history.append({"role": "assistant", "text": "quota", "notice": "error", "ts": 3.0})
        with self.assertRaises(R.RegenError):
            R.start(s)
        s = Sess()
        s.history[-1]["effects"] = True
        with self.assertRaises(R.RegenError) as c:
            R.start(s)
        self.assertEqual(str(c.exception), "regen.effects")

    def test_a_brain_that_keeps_its_conversation_gets_a_host_note_and_the_take_merges(self):
        s = Sess(rebuild=False)
        R.start(s)
        self.assertEqual(s.sent, [(R.ANOTHER_TAKE, True, "regen")], "a note, not the user's words")
        self.assertEqual(len(s.history), 2, "nothing is taken out: the brain has seen it")
        s.answer("second", 5.0)
        R.after_turn(s, "result")
        self.assertEqual(len(s.history), 2)
        item = s.history[-1]
        self.assertEqual((item["text"], item["ts"], item["pick"]), ("second", 5.0, 1))
        self.assertEqual([a["text"] for a in item["alts"]], ["first", "second"])
        self.assertNotIn("choices", item, "the picked take's own choices")
        self.assertEqual(s.events[-1]["event"], "alts")
        self.assertEqual((s.events[-1]["count"], s.events[-1]["pick"]), (2, 1))

    def test_a_brain_sent_the_history_is_asked_again_without_the_old_answer(self):
        s = Sess(rebuild=True)
        R.start(s)
        self.assertEqual(s.sent, [("hi", True, "regen")])
        self.assertEqual([h["role"] for h in s.history], ["user"], "the next context ends at the question")
        s.answer("second", 5.0)
        R.after_turn(s, "result")
        self.assertEqual([h.get("text") for h in s.history], ["hi", "second"])
        self.assertEqual(len(s.history[-1]["alts"]), 2)

    def test_a_failed_take_puts_the_answer_back_before_its_notice(self):
        s = Sess(rebuild=True)
        R.start(s)
        s.history.append({"role": "assistant", "text": "no answer", "notice": "error", "ts": s._regen["at"] + 1})
        R.after_turn(s, "error")
        self.assertEqual([h.get("text") for h in s.history], ["hi", "first", "no answer"])
        self.assertIsNone(s._regen)

    def test_at_most_five_takes_the_oldest_goes(self):
        s = Sess()
        for n in range(7):
            R.start(s)
            s.answer("take%d" % n, 10.0 + n)
            R.after_turn(s, "result")
        alts = s.history[-1]["alts"]
        self.assertEqual(len(alts), R.MAX_ALTS)
        self.assertEqual(alts[-1]["text"], "take6")

    def test_a_turn_that_did_more_than_read_marks_its_own_answer_only(self):
        s = Sess()
        s.turn_started_at = 3.0          # the answer at ts 2.0 is an earlier turn's
        s._turn_effects = True
        R.after_turn(s, "interrupted")
        self.assertNotIn("effects", s.history[-1], "an earlier answer is never marked")
        s.answer("did things", 4.0)
        R.after_turn(s, "result")
        self.assertTrue(s.history[-1]["effects"])
        self.assertFalse(s._turn_effects, "counted again from the next answer on")


class ThinkHarder(unittest.TestCase):
    """#883 (demo-60s D5): chat runs on a quick brain; another take is the user's word that it missed, so that one take
    runs on the same brain's stronger model and the next message goes back. The engine never reads the answer."""

    def test_another_take_runs_once_on_the_stronger_model(self):
        s = Sess(rebuild=False)
        s.model, swaps = "fast-low", []
        s.adapter.stronger_model = lambda m: "fast-high" if m == "fast-low" else ""

        def swap(model, remember=True):
            swaps.append((model, remember))
            s.model = model
        s.maybe_swap_model = swap
        R.start(s)
        self.assertEqual(swaps, [("fast-high", False)], "not remembered as the user's brain choice")
        self.assertEqual(s._regen_restore, "fast-low")
        self.assertEqual(s.events[0].get("key"), "regen.stronger")
        R.start(Sess())   # a brain without a stronger sibling: nothing changes, no error

    def test_the_next_message_goes_back_and_a_restart_keeps_the_way_back(self):
        src = (ENGINE / "session_turn.py").read_text(encoding="utf-8")
        send = src[src.index("    def send(self, text: str"):]
        self.assertLess(send.index('restore = getattr(self, "_regen_restore", "")'), send.index("_emit_heavy_if_needed()"))
        self.assertIn('self.maybe_swap_model(restore, remember=False)', send)
        meta = (ENGINE / "session.py").read_text(encoding="utf-8")
        self.assertIn('"regen_restore": getattr(self, "_regen_restore", "") or ""', meta)
        self.assertIn('self._regen_restore = str(meta.get("regen_restore") or "")', meta)

    def test_agy_names_the_high_sibling_only_when_it_exists(self):
        import sys
        sys.path.insert(0, str(ENGINE))
        from providers.adapter_agy import AgyAdapter
        a = AgyAdapter()
        a.known_models = lambda: ["gemini-3.8-flash-low", "gemini-3.8-flash-high"]
        self.assertEqual(a.stronger_model("gemini-3.8-flash-low"), "gemini-3.8-flash-high")
        self.assertEqual(a.stronger_model("gemini-3.8-flash-high"), "")
        self.assertEqual(a.stronger_model("claude-opus-5-5-low"), "")


class Pick(unittest.TestCase):
    def test_a_pick_shows_that_take(self):
        s = Sess()
        R.start(s)
        s.answer("second", 5.0)
        R.after_turn(s, "result")
        out = R.pick(s, 0)
        self.assertEqual((s.history[-1]["text"], s.history[-1]["pick"], s.history[-1]["choices"]), ("first", 0, ["a"]))
        self.assertEqual((out["count"], out["pick"]), (2, 0))
        with self.assertRaises(R.RegenError):
            R.pick(s, 5)


class Wiring(unittest.TestCase):
    def test_the_session_marks_effects_merges_and_lets_the_take_run_a_whole_turn(self):
        turn = (ENGINE / "session_turn.py").read_text(encoding="utf-8")
        self.assertIn("if not (is_read_only(name) or str((params or {}).get(\"action\") or \"\") in regenerate.READ_ACTIONS):", turn)
        self.assertIn("regenerate.after_turn(self, outcome)", turn)
        self.assertIn('if notice and event_type not in ("handoff", "regen"):', turn)
        self.assertNotIn("self._turn_effects = False", turn, "reset where the answer is stamped (regenerate.after_turn)")

    def test_the_brain_says_how_it_keeps_context(self):
        from providers.adapter_base import AgentAdapter
        from providers.adapter_openai import OpenAIDialectAdapter
        self.assertFalse(AgentAdapter.rebuilds_context(object.__new__(AgentAdapter)))
        self.assertTrue(OpenAIDialectAdapter.rebuilds_context(object.__new__(OpenAIDialectAdapter)))
        server = (ENGINE / "server.py").read_text(encoding="utf-8")
        self.assertIn('("/api/sessions/*/regenerate", route_sessions.regenerate_take)', server)


PAGE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function el(tag) { return { tag, children: [], attrs: {}, className: '', textContent: '', disabled: false, listeners: {},
  append(...c) { this.children.push(...c); }, appendChild(c) { this.children.push(c); return c; },
  setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, f) { this.listeners[k] = f; },
  querySelector(sel) { return sel === '.regen-nav' ? (this.children.find(c => c.className === 'regen-nav') || null) : null; },
  remove() { this.gone = true; } }; }
const document = { createElement: el };
eval(src.replace(/^const REGEN_TEXT.*$/m, "const REGEN_TEXT = i18nTable('regen');"));
const node = el('div');
regenDraw(node, { count: 3, pick: 0 });
const nav = node.children[0];
const one = el('div'); regenDraw(one, { count: 1, pick: 0 });
console.log(JSON.stringify({ where: nav.children[1].textContent, prev: nav.children[0].disabled, next: nav.children[2].disabled,
  label: nav.children[2].attrs['aria-label'], single: one.children.length }));
"""


class Page(unittest.TestCase):
    def test_the_takes_show_under_the_answer(self):
        from tests.page_source import i18n_prelude
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        p = subprocess.run([node, "-e", i18n_prelude() + PAGE, str(REPO / "static" / "app-regen.js")], capture_output=True,
                           text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        ko = json.loads((REPO / "static" / "i18n" / "ko.json").read_text(encoding="utf-8"))
        self.assertEqual(out, {"where": "1/3", "prev": True, "next": False, "label": ko["regen.next"], "single": 0})

    def test_the_menu_offers_it_on_the_last_answer_only(self):
        mm = (REPO / "static" / "app-msgmenu.js").read_text(encoding="utf-8")
        self.assertIn("if (ctx.kind === 'theirs' && ctx.last && !ctx.busy && !ctx.room) rows.push({ k: 'regen'", mm)
        self.assertIn("last: typeof regenOffered === 'function' && regenOffered(el),", mm)
        sse = (REPO / "static" / "app-sse.js").read_text(encoding="utf-8")
        self.assertIn("if (type === 'alts' || type === 'regen_start') { regenEvent(type, data); return; }", sse)


if __name__ == "__main__":
    unittest.main()
