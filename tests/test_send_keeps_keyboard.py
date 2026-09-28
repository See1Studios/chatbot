"""Tapping send keeps the phone keyboard up (SEND_KEEPS_KEYBOARD_v1, static/app.js): the send button's pointerdown
is cancelled so focus never leaves the input -- before, focus moved to the button (keyboard down) and send() put it
back (keyboard up). The click that sends still fires. The REAL listener runs in node against a stub button.
Run: python3 -m unittest tests.test_send_keeps_keyboard  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "static" / "app.js"

HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const a = src.indexOf("sendBtn.addEventListener('click', send);");
const b = src.indexOf('\n', src.indexOf("sendBtn.addEventListener('pointerdown'", a));
const handlers = {};
const sendBtn = { addEventListener: (t, f) => { handlers[t] = f; } };
new Function('sendBtn', 'send', src.slice(a, b))(sendBtn, () => {});
let prevented = false;
handlers.pointerdown({ preventDefault: () => { prevented = true; }, pointerType: 'touch' });
console.log(JSON.stringify({ prevented, click: typeof handlers.click }));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SendKeepsKeyboard(unittest.TestCase):
    def test_pressing_send_does_not_move_focus_and_the_click_still_sends(self):
        r = subprocess.run(["node", "-e", HARNESS, str(APP)], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(json.loads(r.stdout), {"prevented": True, "click": "function"})


if __name__ == "__main__":
    unittest.main()
