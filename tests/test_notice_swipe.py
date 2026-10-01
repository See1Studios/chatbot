"""Swipe-to-dismiss on system notices (static/app-messages.js attachNoticeSwipe, #516) must not take the notice's own
controls: a press on a button inside is the button's, and the pointer is captured only once the move is a sideways
swipe -- captured from the press, the click went to the notice and the open-failure notice's retry button never
answered (review of #516). The REAL function runs in node against a stub element.
Run: python3 -m unittest tests.test_notice_swipe  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest

from tests.page_source import app_bundle

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function attachNoticeSwipe(');
const b = src.indexOf('\nfunction ', a + 10);
eval(src.slice(a, b));
const handlers = {}, cls = new Set(), captured = [];
const el = {
  classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), contains: c => cls.has(c) },
  style: { setProperty() {}, cssText: '' }, offsetWidth: 300,
  addEventListener: (t, f) => { (handlers[t] = handlers[t] || []).push(f); },
  setPointerCapture: (id) => captured.push(id), remove() {},
};
const fire = (t, e) => (handlers[t] || []).forEach(f => f(e));
attachNoticeSwipe(el);
const button = { closest: () => button }, plain = { closest: () => null };
const o = {};
fire('pointerdown', { button: 0, target: button, clientX: 0, clientY: 0, pointerId: 1 });
o.onButton = { swiping: cls.has('swiping'), captured: captured.slice() };
fire('pointerdown', { button: 0, target: plain, clientX: 0, clientY: 0, pointerId: 2 });
o.pressed = { swiping: cls.has('swiping'), captured: captured.slice() };
fire('pointermove', { clientX: 3, clientY: 1, pointerId: 2 });
o.tiny = captured.slice();
fire('pointermove', { clientX: 30, clientY: 2, pointerId: 2 });
o.sideways = captured.slice();
fire('pointerup', { pointerId: 2 });
captured.length = 0;
fire('pointerdown', { button: 0, target: plain, clientX: 0, clientY: 0, pointerId: 3 });
fire('pointermove', { clientX: 1, clientY: 30, pointerId: 3 });
o.scroll = { swiping: cls.has('swiping'), captured: captured.slice() };
console.log(JSON.stringify(o));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NoticeSwipe(unittest.TestCase):
    def test_controls_inside_keep_their_clicks(self):
        p = subprocess.run(["node", "-e", HARNESS, str(app_bundle())], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr[-1500:])
        o = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(o["onButton"], {"swiping": False, "captured": []})   # the retry button's own press
        self.assertEqual(o["pressed"], {"swiping": True, "captured": []})     # not captured on the press
        self.assertEqual(o["tiny"], [])
        self.assertEqual(o["sideways"], [2])                                  # captured once it is a swipe
        self.assertEqual(o["scroll"], {"swiping": False, "captured": []})     # an up-down move is a scroll


if __name__ == "__main__":
    unittest.main()
