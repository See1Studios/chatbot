"""A brand-new session opens with a quiet centered divider, not the assistant greeting bubble (#160).
continueSession shows its handoff note as a system notice, not an assistant turn (#196).
Run: python3 -m unittest tests.test_session_marker  (from services/chatbot)
"""
import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / 'static' / 'app-session.js').read_text(encoding='utf-8')


def func_body(name):
    start = SRC.index('function ' + name + '(')
    nxt = re.search(r'\n(?:async )?function \w+\(', SRC[start + 1:])
    return SRC[start:start + 1 + nxt.start()] if nxt else SRC[start:]


def enter_call(body):
    start = body.index('enterSession(')
    return body[start:body.index('});', start)]


class SessionMarkerTest(unittest.TestCase):
    def test_create_session_passes_marker_not_greeting(self):
        call = enter_call(func_body('createSession'))
        self.assertIn("sessionMarker: data.session.id", call)   # #421: the divider names it; the id is advanced-only
        self.assertNotIn('greeting:', call)

    def test_enter_session_renders_marker_as_divider(self):
        body = func_body('enterSession')
        block = body[body.index('if (opts.sessionMarker)'):]
        block = block[:block.index('}') + 1]
        self.assertIn("className = 'msg scrollback-marker flow-line", block)   # the day divider's look (#421)
        self.assertIn('textContent = opts.sessionMarker', block)
        self.assertNotIn('innerHTML', block)
        self.assertIn('logEl.appendChild(marker)', block)

    def test_continue_session_shows_handoff_as_notice(self):
        call = enter_call(func_body('continueSession'))
        self.assertIn('notice:', call)
        self.assertNotIn('greeting:', call)


if __name__ == '__main__':
    unittest.main()
