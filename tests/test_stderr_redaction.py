import unittest
from types import SimpleNamespace
from pathlib import Path
from session import AgySession, _redact_line, _redact_text


class TestStderrRedaction(unittest.TestCase):
    def test_redact_line_and_text(self):
        self.assertTrue(_redact_line("Bearer 12345"))
        self.assertTrue(_redact_line("Authorization: secret"))
        self.assertTrue(_redact_line("Error with api_key in header"))
        self.assertTrue(_redact_line("refresh token expired"))
        self.assertTrue(_redact_line("token"))
        self.assertFalse(_redact_line("Just a regular error log"))

        multiline = "Line 1: regular log\nLine 2: Authorization: secret\nLine 3: finished."
        redacted = _redact_text(multiline)
        self.assertIn("Line 1: regular log", redacted)
        self.assertNotIn("Authorization", redacted)
        self.assertIn("Line 3: finished.", redacted)

    def test_to_public_debug_stderr_tail_redacts_credentials(self):
        sess = AgySession.__new__(AgySession)
        sess.sid = "test-stderr-sess"
        sess.proc = None
        sess.adapter = SimpleNamespace(transport_kind="process")
        sess.last_activity = 100.0
        sess.model = "test-model"
        sess.provider = "agy"
        sess.effort = ""
        sess.conversation_id = None
        sess.busy = False
        sess.msg_queue = []
        sess.current_text = ""
        sess.last_progress = ""
        sess.turn_started_at = 0.0
        sess.pending_images = []
        sess.created_at = 100.0
        sess.history = []
        sess.is_private = False
        sess.successor_session_id = None
        sess.predecessor_session_id = None
        sess.handoff_summary = ""
        sess.meta_path = Path("/tmp/nonexistent_meta.json")
        sess.weight = lambda: {"level": "light"}

        # Add both clean and sensitive lines
        sess._stderr_tail = [
            "Normal error line 1",
            "Error: Bearer abc123def456 secret token",
            "Normal error line 2",
        ]

        pub = sess.to_public()
        self.assertIn("debug_stderr_tail", pub)
        tail = pub["debug_stderr_tail"]
        self.assertIn("Normal error line 1", tail)
        self.assertIn("Normal error line 2", tail)
        for line in tail:
            self.assertNotIn("Bearer", line)
            self.assertNotIn("secret token", line)


if __name__ == "__main__":
    unittest.main()
