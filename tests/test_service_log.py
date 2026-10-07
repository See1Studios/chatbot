"""OBSLOG_UI_v1: GET /api/service-log (로그 탭 → 서비스) and its static wiring.
Run: python3 -m unittest tests.test_service_log  (from services/chatbot)
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import logdigest  # noqa: E402
import obslog  # noqa: E402
import server  # noqa: E402
import platform_compat  # noqa: E402  (exclusive port on Windows, #409)

SID = "20260923-101010-abcdef"


class ServiceLogApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = platform_compat.http_server(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "events.jsonl"
        self._old = (logdigest.LOG, logdigest.SESSIONS)
        logdigest.LOG = self.log
        logdigest.SESSIONS = Path(self.tmp.name) / "sessions"
        server._SERVICE_LOG_CACHE.clear()
        now = time.time()
        recs = [
            (now - 120, {"src": "chat", "evt": "proc.start", "lvl": "info"}),
            (now - 100, {"src": "chat", "evt": "http.summary", "lvl": "info", "routes": {"GET /x": {"n": 5}}}),
            (now - 90, {"src": "chat", "evt": "turn.start", "lvl": "info", "sid": SID}),
            (now - 60, {"src": "chat", "evt": "http.error", "lvl": "error", "sid": SID, "route": "POST /api/x",
                        "err": {"type": "KeyError", "msg": "'x'", "fp": "abcdef1234", "trace": "T" * 9000}}),
            (now - 30, {"src": "ctl", "evt": "repair.begin", "lvl": "warn", "caller": "api-defibrillate"}),
        ]
        with open(self.log, "w", encoding="utf-8") as f:
            for t, r in recs:
                r["ts"] = obslog.iso_now(t)
                r["pid"] = 1
                f.write(json.dumps(r) + "\n")

    def tearDown(self):
        logdigest.LOG, logdigest.SESSIONS = self._old
        server._SERVICE_LOG_CACHE.clear()
        self.tmp.cleanup()

    def get(self, q):
        with urlopen("http://127.0.0.1:%d/api/service-log%s" % (self.port, q), timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_service_view_lists_problems_and_ops_newest_first(self):
        d = self.get("?since=1h")
        self.assertTrue(d["ok"] and d["log_exists"])
        self.assertEqual([e["evt"] for e in d["events"]], ["repair.begin", "http.error", "proc.start"])
        self.assertLessEqual(len(d["events"][1]["err"]["trace"]), 2000)
        self.assertIn(d["digest"]["status"], ("ok", "warn", "error"))
        self.assertTrue(any(f["code"] == "error_fp" for f in d["digest"]["findings"]))

    def test_session_view_is_the_merged_timeline(self):
        d = self.get("?since=1h&sid=" + SID)
        self.assertEqual([e["evt"] for e in d["events"]], ["http.error", "turn.start"])

    def test_malformed_digest_errors_and_events_are_skipped(self):
        real_digest, real_read = logdigest.digest, logdigest.read_events
        logdigest.digest = lambda s: {"status": "error", "errors": ["boom", None, {"fp": "abc", "sample_trace": "x"}]}
        logdigest.read_events = lambda t: ["junk", 7] + list(real_read(t))
        try:
            d = self.get("?since=1h")
        finally:
            logdigest.digest, logdigest.read_events = real_digest, real_read
        self.assertEqual(d["digest"]["errors"], [{"fp": "abc", "sample_trace": "x"}])
        self.assertEqual([e["evt"] for e in d["events"]], ["repair.begin", "http.error", "proc.start"])

    def test_bad_parameters_are_400(self):
        for q in ("?since=forever", "?since=1h&sid=../../etc"):
            with self.assertRaises(HTTPError) as cm:
                self.get(q)
            self.assertEqual(cm.exception.code, 400)


class HostSignalTickTest(unittest.TestCase):
    """HOST_SIGNALS_v1.1: the service collects host candidates; doctor (the watchdog) runs no service code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.log = base / "events.jsonl"
        self.ws = base / "workspace"
        (self.ws / "skill-observations").mkdir(parents=True)
        self._old = (logdigest.LOG, logdigest.HOST_SIGNAL_STAMP, logdigest.OBS_ROOT, server.WORKSPACE)
        logdigest.LOG = self.log
        logdigest.HOST_SIGNAL_STAMP = base / ".stamp"
        server.WORKSPACE = self.ws
        err = {"type": "KeyError", "msg": "x", "fp": "abcdef1234"}
        self.log.write_text(json.dumps({"ts": obslog.iso_now(time.time() - 60), "lvl": "error", "src": "chat", "pid": 1,
                                        "evt": "http.error", "err": err}) + "\n", encoding="utf-8")

    def tearDown(self):
        logdigest.LOG, logdigest.HOST_SIGNAL_STAMP, logdigest.OBS_ROOT, server.WORKSPACE = self._old
        self.tmp.cleanup()

    def test_tick_records_then_throttles(self):
        self.assertEqual(server._host_signal_tick(), 1)
        rows = (self.ws / "skill-observations" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(rows[0])["signal"], "host:error_fp")
        self.assertEqual(server._host_signal_tick(), 0)   # hourly

    def test_doctor_runs_no_service_code_for_signals(self):
        ctl = (ENGINE / "chatbot-ctl.sh").read_text(encoding="utf-8")
        doctor = ctl.split("cmd_doctor() {", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("logdigest", doctor)
        self.assertNotIn("to-candidates", doctor)


class StaticWiringTest(unittest.TestCase):
    def test_log_tab_has_the_service_view(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="svcLogBtn"', html)
        self.assertIn('id="svcLog"', html)
        self.assertIn("service-log.js?v=", html)
        js = (ROOT / "static" / "service-log.js").read_text(encoding="utf-8")
        self.assertIn("/api/service-log", js)
        self.assertNotIn("innerHTML =", js.replace("pane.innerHTML = ''", ""))  # text only, no HTML injection


if __name__ == "__main__":
    unittest.main()
