import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List

from session import AgySession


class FakeHttpAdapter:
    id = "fake_http"
    transport_kind = "http"
    keeps_stdin_open = False
    HTTP_TURN_TIMEOUT_SEC = 180

    def __init__(self, block_event: threading.Event):
        self.block_event = block_event

    def stream_turn(self, session: AgySession, messages: List[dict], seq: int = None, **kwargs) -> Iterator[dict]:
        # Hop 1: if seq == 1, block until released
        if seq == 1:
            self.block_event.wait(timeout=5.0)
            if seq is not None and getattr(session, "_turn_seq", None) != seq:
                return
            yield {"event": "delta", "text": "turn1-stale"}
            yield {
                "event": "result",
                "text": "turn1-stale",
                "ts": time.time(),
            }
        else:
            yield {"event": "delta", "text": "turn2-ok"}
            session.current_text = ""
            yield {
                "event": "result",
                "text": "turn2-ok",
                "ts": time.time(),
            }


class TestHttpTurnHijack(unittest.TestCase):
    def test_stale_http_turn_does_not_hijack_next_turn(self):
        block_event = threading.Event()
        adapter = FakeHttpAdapter(block_event)

        sess = AgySession.__new__(AgySession)
        sess.sid = "test-hijack"
        sess.adapter = adapter
        sess.lock = threading.RLock()
        sess.history = []
        sess.subscribers = []
        sess.busy = False
        sess.msg_queue = []
        sess.current_text = ""
        sess.last_progress = ""
        sess.turn_started_at = 0.0
        sess.pending_images = []
        sess._stderr_tail = []
        sess._turn_seq = 0
        sess._stop_requested = False
        sess._http_resp = None
        sess.meta_path = Path("/tmp/meta_hijack.json")
        sess.save_meta = lambda: None
        sess._append_log_event = lambda ev: None
        sess._emit = lambda ev: None
        sess._handle_events = lambda evs: [
            sess.history.append({"role": "assistant", "text": ev.get("text")})
            for ev in evs if ev.get("event") == "result"
        ]
        sess._history_to_openai_messages = lambda last_user_override="": [{"role": "user", "content": last_user_override}]

        # Start Turn 1
        sess._turn_seq += 1
        turn1_seq = sess._turn_seq
        sess.busy = True
        t1 = threading.Thread(target=sess._run_http_turn, args=("msg 1", turn1_seq))
        t1.start()

        # Call stop() on Turn 1
        sess._stop_requested = True

        # Send Turn 2
        sess._stop_requested = False
        sess._turn_seq += 1
        turn2_seq = sess._turn_seq
        sess.busy = True
        t2 = threading.Thread(target=sess._run_http_turn, args=("msg 2", turn2_seq))
        t2.start()
        t2.join(timeout=2.0)

        # Release blocked Turn 1
        block_event.set()
        t1.join(timeout=2.0)

        # Assert Turn 1 did not write into history
        assistant_entries = [h for h in sess.history if h.get("role") == "assistant"]
        self.assertEqual(len(assistant_entries), 1)
        self.assertEqual(assistant_entries[0]["text"], "turn2-ok")


if __name__ == "__main__":
    unittest.main()
