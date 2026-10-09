"""OBSLOG_v1: logdigest.py findings and views, and the MCP allowlist for `chatbot-ctl.sh logs`.
Run: engine/run-tests.sh test_logdigest
"""
import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
from telemetry import logdigest  # noqa: E402
from telemetry import obslog  # noqa: E402

SID = "20260923-101010-abcdef"


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"
        self._old = (logdigest.LOG, logdigest.SESSIONS)
        logdigest.LOG = self.path
        logdigest.SESSIONS = Path(self.tmp.name) / "sessions"
        self.now = time.time()

    def tearDown(self):
        logdigest.LOG, logdigest.SESSIONS = self._old
        self.tmp.cleanup()

    def write(self, recs):
        with open(self.path, "a", encoding="utf-8") as f:
            for ago, rec in recs:
                rec = dict(rec)
                rec.setdefault("lvl", "info")
                rec.setdefault("pid", 1)
                rec["ts"] = obslog.iso_now(self.now - ago)
                f.write(json.dumps(rec) + "\n")

    def codes(self, d):
        return {f["code"] for f in d["findings"]}

    def test_the_injections_are_summed_up(self):
        # CONTEXT_LOG_v1: what went into the agents, by why and by mode
        self.write([(30, {"src": "chat", "evt": "context.inject", "why": "first", "mode": "work", "chars": 4783}),
                    (20, {"src": "chat", "evt": "context.inject", "why": "rules_changed", "mode": "work", "chars": 4800}),
                    (10, {"src": "chat", "evt": "context.inject", "why": "first", "mode": "private", "chars": 5563})])
        c = logdigest.digest(3600)["context"]
        self.assertEqual(c["injections"], 3)
        self.assertEqual(c["by_why"], {"first": 2, "rules_changed": 1})
        self.assertEqual(c["by_mode"], {"work": 2, "private": 1})
        self.assertEqual(c["max_chars"], 5563)

    def test_context_alerts_become_findings(self):
        # CONTEXT_ALERT_v1
        self.write([(20, {"src": "chat", "evt": "context.alert", "kind": "over_budget", "lvl": "warn"}),
                    (10, {"src": "chat", "evt": "context.alert", "kind": "leak", "lvl": "error"})])
        d = logdigest.digest(3600)
        self.assertEqual(d["context"]["alerts"], {"over_budget": 1, "leak": 1})
        sev = {f["code"]: f["severity"] for f in d["findings"]}
        self.assertEqual((sev["context_over_budget"], sev["context_leak"]), ("warn", "error"))

    def test_a_red_main_is_a_finding_until_a_green_check(self):
        # MAIN_WATCH_v1 (#825): 2026-10-08 four modules were red on main and only another agent's full run saw it
        self.write([(30 * 3600, {"src": "watch", "evt": "main.check", "ok": True, "sha": "aaa111", "failed": []}),
                    (20 * 3600, {"src": "watch", "evt": "main.check", "ok": False, "sha": "bbb222",
                                 "failed": ["test_x", "test_y"], "subject": "feat: x (Gemini)"})])
        d = logdigest.digest(6 * 3600)                     # the red check is older than the window: still found
        red = [f for f in d["findings"] if f["code"] == "main_red"]
        self.assertEqual(len(red), 1)
        self.assertEqual(d["findings"][0]["code"], "main_red")
        self.assertIn("test_x test_y", red[0]["title"])
        self.assertIn("aaa111..bbb222", red[0]["hint"])
        self.write([(3600, {"src": "watch", "evt": "main.check", "ok": True, "sha": "ccc333", "failed": []})])
        self.assertNotIn("main_red", self.codes(logdigest.digest(6 * 3600)))

    def test_text_errors_and_cut_routes_are_read_without_a_crash(self):
        # DIGEST_SHAPE_v1 (#831): git.commit_failed wrote err as text, obslog's cap cut routes to a "…" entry
        self.write([(60, {"src": "chat", "evt": "git.commit_failed", "lvl": "error", "err": "fatal: index.lock"}),
                    (50, {"src": "chat", "evt": "http.summary", "routes": {"GET /x": {"n": 3, "codes": {"2xx": 3}},
                                                                       "\u2026": "12 more"}})])
        d = logdigest.digest(3600)
        self.assertNotIn("AttributeError", " ".join(f["title"] for f in d["findings"]))
        self.assertIn("chat GET /x", str(d["http"]))                        # the uncut route still counts
        rows = list(logdigest.read_events(0))
        self.assertEqual(rows[0]["err"], {"msg": "fatal: index.lock"})
        self.assertEqual(list(rows[1]["routes"]), ["GET /x"])

    def test_clean_run_is_ok(self):
        self.write([(600, {"src": "chat", "evt": "proc.start"}), (300, {"src": "chat", "evt": "proc.heartbeat", "rss_mb": 50}),
                    (10, {"src": "chat", "evt": "proc.heartbeat", "rss_mb": 51})])
        d = logdigest.digest(3600)
        self.assertEqual(d["status"], "ok", d["findings"])

    def test_unclean_restart_and_silence(self):
        self.write([
            (7200, {"src": "chat", "evt": "proc.start", "pid": 1}),
            (3000, {"src": "chat", "evt": "proc.heartbeat", "pid": 1}),
            (2900, {"src": "chat", "evt": "proc.start", "pid": 2}),   # no proc.exit for pid 1
            (2800, {"src": "mcp", "evt": "proc.start", "pid": 3}),     # then nothing for 46 min
        ])
        d = logdigest.digest(3600)
        self.assertIn("unclean_restart", self.codes(d))
        self.assertIn("silent_process", self.codes(d))
        self.assertEqual(d["unclean_restarts"][0]["prev_pid"], 1)

    def test_a_stop_that_had_to_kill_is_a_forced_stop_not_a_crash(self):
        self.write([
            (600, {"src": "chat", "evt": "proc.start", "pid": 1}),
            (300, {"src": "ctl", "evt": "ctl.kill", "proc": "chat", "killed_pid": "1", "waited_s": 5}),
            (290, {"src": "chat", "evt": "proc.start", "pid": 2}),
        ])
        d = logdigest.digest(3600)
        self.assertIn("stop_forced", self.codes(d))
        self.assertNotIn("unclean_restart", self.codes(d))
        self.assertTrue(d["unclean_restarts"][0]["forced"])

    def test_an_overlapping_process_is_not_a_crash(self):
        self.write([
            (600, {"src": "mcp", "evt": "proc.start", "pid": 1}),
            (300, {"src": "mcp", "evt": "proc.heartbeat", "pid": 1}),
            (250, {"src": "mcp", "evt": "proc.start", "pid": 9}),   # a test server, alive a moment
            (249, {"src": "mcp", "evt": "proc.exit", "pid": 9}),
            (100, {"src": "mcp", "evt": "proc.exit", "pid": 1}),    # the real one exits cleanly
            (90, {"src": "mcp", "evt": "proc.start", "pid": 2}),
            (10, {"src": "mcp", "evt": "proc.heartbeat", "pid": 2}),
        ])
        self.assertNotIn("unclean_restart", self.codes(logdigest.digest(3600)))

    def test_a_live_servers_child_reaped_is_flagged(self):
        self.write([
            (600, {"src": "chat", "evt": "proc.start", "pid": 610}),
            (300, {"src": "ctl", "evt": "agent.reaped", "agent_pid": 1938, "ppid": 610, "reason": "unprotected-flash-low"}),
            (200, {"src": "ctl", "evt": "agent.reaped", "agent_pid": 77, "ppid": 1, "reason": "ppid1"}),  # a real orphan
        ])
        f = [x for x in logdigest.digest(3600)["findings"] if x["code"] == "agent_reaped_live"]
        self.assertEqual([x["evidence"]["agent_pid"] for x in f], [1938])

    def test_error_fingerprints_new_vs_known(self):
        err = {"type": "KeyError", "msg": "'x'", "fp": "abcdef1234", "where": "server.py:1:f", "trace": "Traceback..."}
        self.write([
            (90000, {"src": "chat", "evt": "http.error", "lvl": "error", "err": err}),
            (100, {"src": "chat", "evt": "http.error", "lvl": "error", "route": "POST /api/x", "err": err}),
            (50, {"src": "chat", "evt": "http.error", "lvl": "error", "route": "POST /api/x",
                  "err": dict(err, fp="9999999999", type="ValueError")}),
        ])
        d = logdigest.digest(3600)
        by_fp = {g["fp"]: g for g in d["errors"]}
        self.assertFalse(by_fp["abcdef1234"]["new"])
        self.assertTrue(by_fp["9999999999"]["new"])
        sev = {f["evidence"].get("fp"): f["severity"] for f in d["findings"] if f["code"] == "error_fp"}
        self.assertEqual(sev, {"abcdef1234": "warn", "9999999999": "error"})

    def test_http_summary_rates(self):
        self.write([(60, {"src": "chat", "evt": "http.summary", "routes": {
            "GET /api/usage": {"n": 100, "codes": {"2xx": 95, "5xx": 5}, "p50": 10, "p95": 3000, "max": 4000},
            "GET /api/sessions": {"n": 1000, "codes": {"2xx": 1000}, "p50": 5, "p95": 20, "max": 50}}})])
        d = logdigest.digest(3600)
        self.assertIn("http_5xx", self.codes(d))
        self.assertIn("http_slow", self.codes(d))
        self.assertEqual(d["http"]["total"], 1100)

    def test_ops_and_turns(self):
        recs = []
        for i in range(8):
            recs.append((3000 - i * 100, {"src": "ctl", "evt": "repair.begin", "caller": "api-defibrillate"}))
            recs.append((2990 - i * 100, {"src": "ctl", "evt": "repair.end", "ok": 0 if i == 0 else 1, "dur_s": 12}))
        for i in range(10):
            recs.append((500 - i, {"src": "chat", "evt": "turn.end", "provider": "agy", "sid": SID,
                                   "outcome": "error" if i < 4 else "result", "dur_s": 5}))
        self.write(recs)
        d = logdigest.digest(3600)
        c = self.codes(d)
        self.assertTrue({"repair_frequent", "repair_failed", "turn_failures"} <= c, c)
        self.assertEqual(d["ops"]["repair_callers"], {"api-defibrillate": 8})
        self.assertEqual(d["turns"]["by_provider"]["agy"]["fail_rate"], 0.4)

    def test_short_window_is_not_extrapolated(self):
        self.write([(60, {"src": "ctl", "evt": "repair.begin"}), (30, {"src": "ctl", "evt": "repair.begin"})])
        self.assertNotIn("repair_frequent", self.codes(logdigest.digest(600)))

    def test_views(self):
        sess = logdigest.SESSIONS / SID
        sess.mkdir(parents=True)
        (sess / "events.jsonl").write_text(json.dumps({"event": "error", "text": "died", "ts": self.now - 30}) + "\n")
        self.write([(40, {"src": "chat", "evt": "turn.start", "sid": SID, "rid": "aaaaaaaaaaaa"}),
                    (20, {"src": "chat", "evt": "turn.end", "sid": SID, "outcome": "error"})])
        buf = io.StringIO()
        with redirect_stdout(buf):
            logdigest.main(["--sid", SID, "--since", "1h"])
        out = buf.getvalue().splitlines()
        self.assertEqual([l.split()[4] for l in out], ["turn.start", "session.error", "turn.end"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            logdigest.main(["--rid", "aaaaaaaaaaaa", "--json"])
        self.assertEqual(json.loads(buf.getvalue())["evt"], "turn.start")
        buf = io.StringIO()
        with redirect_stdout(buf):
            logdigest.main(["--json"])
        self.assertIn("findings", json.loads(buf.getvalue()))

    def test_bad_lines_do_not_break_digest(self):
        self.path.write_text("not json\n")
        self.assertIn("log.bad_line", logdigest.digest(3600, include_all=True)["counts"]["by_evt"])


class CtlLogsAllowlistTests(unittest.TestCase):
    def setUp(self):
        import mcp_server
        self.refusal = mcp_server._ctl_refusal

    def test_allowed(self):
        for args in (["logs"], ["logs", "--since", "6h"], ["logs", "--sid", SID, "--json"],
                     ["logs", "--fp", "abcdef1234"], ["logs", "--evt", "http.error", "--since", "2d"]):
            self.assertIsNone(self.refusal(args), args)

    def test_refused(self):
        for args in (["logs", "-f"], ["logs", "--since"], ["logs", "--since", "6h;rm"], ["logs", "--sid", "../x"],
                     ["logs", "--follow"], ["logs", "x"]):
            self.assertIsNotNone(self.refusal(args), args)


if __name__ == "__main__":
    unittest.main()
