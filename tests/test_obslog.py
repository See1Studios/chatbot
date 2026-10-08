"""OBSLOG_v1: structured event log (obslog.py).
Run: engine/run-tests.sh test_obslog
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
CODE = REPO
sys.path.insert(0, str(ENGINE))
from telemetry import obslog  # noqa: E402
import platform_compat  # noqa: E402  (exclusive port on Windows, #409)


def lines(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"
        obslog.configure("test", path=self.path, mirror="error")
        obslog._dedup.clear()
        obslog._fp_state.clear()
        obslog._http.clear()
        obslog.unbind()

    def tearDown(self):
        obslog._state["path"] = None
        self.tmp.cleanup()


class EventTests(Base):
    def test_line_shape(self):
        obslog.event("unit.hello", msg="hi", sid="20260923-101010-abcdef", n=3)
        (rec,) = lines(self.path)
        self.assertEqual(list(rec)[:5], ["ts", "lvl", "src", "evt", "pid"])
        self.assertEqual((rec["src"], rec["evt"], rec["lvl"], rec["n"]), ("test", "unit.hello", "info", 3))
        self.assertRegex(rec["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$")

    def test_redaction_keys_and_values(self):
        obslog.event("unit.secret", api_key="abc123456789", headers={"Authorization": "Bearer zzzzzzzzzzzz"},
                     msg="call with token=supersecretvalue and sk-ABCDEFGHIJKLMNOPQRST and Bearer eyJhbGciOiJIUzI1NiJ9.aaaaaaaaaaaa.bbbbbbbb")
        raw = self.path.read_text(encoding="utf-8")
        for leak in ("abc123456789", "zzzzzzzzzzzz", "supersecretvalue", "ABCDEFGHIJKLMNOPQRST", "eyJhbGci"):
            self.assertNotIn(leak, raw)

    def test_caps_long_strings(self):
        obslog.event("unit.big", blob="x" * 50000)
        self.assertLess(self.path.stat().st_size, 3000)

    def test_dedup_folds_repeats(self):
        for _ in range(5):
            obslog.event("unit.dup", lvl="warn", dedup="k", dedup_window=60)
        self.assertEqual(len(lines(self.path)), 1)
        obslog._dedup["unit.dup|k"][0] -= 120  # window passed
        obslog.event("unit.dup", lvl="warn", dedup="k", dedup_window=60)
        self.assertEqual(lines(self.path)[-1]["repeat"], 4)

    def test_error_storm_keeps_history(self):
        def boom():
            raise ValueError("storm")
        for _ in range(50):
            try:
                boom()
            except ValueError:
                obslog.exception("unit.storm")
        recs = lines(self.path)
        self.assertEqual(len(recs), obslog.FP_MAX_PER_WINDOW)
        self.assertIn("trace", recs[0]["err"])
        self.assertTrue(all("trace" not in r["err"] and r["err"]["trace_omitted"] for r in recs[1:]))
        obslog.flush_suppressed()
        last = lines(self.path)[-1]
        self.assertEqual((last["evt"], last["count"], last["of_evt"], last["err"]["fp"]),
                         ("log.suppressed", 30, "unit.storm", recs[0]["err"]["fp"]))
        obslog.flush_suppressed()
        self.assertEqual(lines(self.path)[-1]["evt"], "log.suppressed")  # nothing new settled twice
        self.assertEqual(len(lines(self.path)), obslog.FP_MAX_PER_WINDOW + 1)
        from telemetry import logdigest
        old = logdigest.LOG
        logdigest.LOG = self.path
        try:
            (g,) = logdigest.digest(3600)["errors"]
        finally:
            logdigest.LOG = old
        self.assertEqual((g["count"], g["suppressed"]), (50, 30))

    def test_bind_context(self):
        obslog.bind(rid="r1", sid="s1")
        obslog.event("unit.ctx")
        obslog.unbind()
        obslog.event("unit.noctx")
        a, b = lines(self.path)
        self.assertEqual((a["rid"], a["sid"]), ("r1", "s1"))
        self.assertNotIn("rid", b)

    def test_exception_fingerprint_is_stable(self):
        def boom():
            raise KeyError("x")
        fps = []
        for _ in range(2):
            try:
                boom()
            except KeyError:
                fps.append(obslog.exception("unit.err")["err"]["fp"])
        self.assertEqual(fps[0], fps[1])
        rec = lines(self.path)[0]
        self.assertEqual(rec["err"]["type"], "KeyError")
        self.assertIn("boom", rec["err"]["where"])
        self.assertIn("Traceback", rec["err"]["trace"])

    def test_rotation(self):
        old = obslog.MAX_BYTES
        obslog.MAX_BYTES = 2000
        try:
            for i in range(60):
                obslog.event("unit.fill", i=i, pad="y" * 100)
        finally:
            obslog.MAX_BYTES = old
        self.assertTrue(self.path.with_name("events.jsonl.1").exists())
        total = sum(len(lines(p)) for p in [self.path] + [self.path.with_name("events.jsonl.%d" % i) for i in range(1, 6)])
        self.assertGreater(total, 10)
        for p in self.path.parent.glob("events.jsonl*"):
            if p.suffix != ".lock":
                lines(p)  # every file still parses line by line

    def test_unconfigured_is_memory_only(self):
        obslog._state["path"] = None
        rec = obslog.event("unit.mem")
        self.assertEqual(rec["evt"], "unit.mem")
        self.assertIs(obslog.RECENT[-1], rec)
        self.assertFalse(self.path.exists())

    def test_no_path_means_no_file(self):
        env_old = os.environ.pop("CHATBOT_OBSLOG_PATH", None)
        try:
            obslog.configure("test")
            self.assertIsNone(obslog._state["path"])
            obslog.event("unit.nowhere")
            self.assertFalse(obslog.DEFAULT_PATH.with_name("never").exists())
        finally:
            if env_old is not None:
                os.environ["CHATBOT_OBSLOG_PATH"] = env_old

    def test_started_process_does_not_leak_the_path_to_children(self):
        env = dict(os.environ, CHATBOT_OBSLOG_PATH=str(self.path), CHATBOT_CALLER="cli-test",
                   CHATBOT_OBSLOG_SUMMARY_SEC="3600")
        code = ("from telemetry import obslog; import os, subprocess, sys; obslog.start_process('unit'); "
                "print(subprocess.check_output([sys.executable, '-c', "
                "'import os; print(os.environ.get(\"CHATBOT_OBSLOG_PATH\"), os.environ.get(\"CHATBOT_CALLER\"))'], text=True).strip())")
        out = subprocess.run([sys.executable, "-c", code], cwd=str(CODE), env=env, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "None None")
        start = next(r for r in lines(self.path) if r["evt"] == "proc.start")
        self.assertEqual(start["caller"], "cli-test")

    def test_never_raises(self):
        obslog.configure("test", path=Path(self.tmp.name) / "nodir" / "x" / "\0bad", mirror="error")
        obslog.event("unit.bad", obj=object())  # unwritable path, unserialisable value
        self.assertGreaterEqual(obslog.stats()["write_errors"], 1)

    def test_route_of(self):
        self.assertEqual(obslog.route_of("/api/sessions/20260922-180815-864823/log"), "/api/sessions/:sid/log")
        self.assertEqual(obslog.route_of("/persona/providers/agy.webp"), "/persona/*.webp")
        self.assertEqual(obslog.route_of("/app.js"), "/*.js")
        self.assertEqual(obslog.route_of("/api/tickets/12"), "/api/tickets/:n")

    def test_cli_emit(self):
        env = dict(os.environ, CHATBOT_OBSLOG_PATH=str(self.path), CHATBOT_CALLER="cli-test")
        subprocess.run([sys.executable, str(ENGINE / "telemetry" / "obslog.py"), "emit", "--evt", "repair.begin", "--lvl", "warn",
                        "ok=1", "dur_s=2.5", "--msg", "hello"], env=env, check=True)
        rec = lines(self.path)[-1]
        self.assertEqual((rec["src"], rec["evt"], rec["lvl"], rec["ok"], rec["dur_s"], rec["caller"], rec["msg"]),
                         ("ctl", "repair.begin", "warn", 1, 2.5, "cli-test", "hello"))


class _H(obslog.HTTPLogMixin, BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path.startswith("/boom"):
                raise RuntimeError("kaboom")
            if self.path.startswith("/missing"):
                raise FileNotFoundError("nope")
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except Exception:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class HTTPTests(Base):
    def setUp(self):
        super().setUp()
        self.srv = platform_compat.http_server(("127.0.0.1", 0), _H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.headers.get("X-Request-Id")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("X-Request-Id")

    def test_success_is_summarised_errors_are_written(self):
        for _ in range(3):
            self.assertEqual(self.get("/ok")[0], 200)
        code, rid = self.get("/boom")
        self.assertEqual(code, 500)
        self.assertEqual(self.get("/missing")[0], 404)
        req = urllib.request.Request(self.base + "/api/x", data=b"{}", method="POST")
        urllib.request.urlopen(req, timeout=5).read()
        import time
        time.sleep(0.2)
        recs = lines(self.path)
        evts = [r["evt"] for r in recs]
        self.assertNotIn("GET /ok", [r.get("route") for r in recs])
        err = next(r for r in recs if r["evt"] == "http.error")
        self.assertEqual((err["status"], err["rid"], err["err"]["type"]), (500, rid, "RuntimeError"))
        self.assertIn("kaboom", err["err"]["trace"])
        ce = next(r for r in recs if r["evt"] == "http.client_error")
        self.assertEqual((ce["status"], ce["err"]["type"]), (404, "FileNotFoundError"))
        self.assertNotIn("trace", ce["err"])
        self.assertIn("http.request", evts)
        obslog.flush_http_summary()
        summ = lines(self.path)[-1]
        self.assertEqual(summ["evt"], "http.summary")
        self.assertEqual(summ["routes"]["GET /ok"]["n"], 3)
        self.assertEqual(summ["routes"]["GET /boom"]["codes"], {"5xx": 1})

    def test_expected_discovery_404_is_summary_only(self):
        self.assertEqual(self.get("/.well-known/oauth-protected-resource")[0], 200)  # _H answers 200 to all GETs
        import time
        for _ in range(50):  # the server counts a request after it has answered it
            if "GET /.well-known/oauth-protected-resource" in obslog._http:
                break
            time.sleep(0.02)
        obslog.http_request("GET", "/.well-known/oauth-protected-resource", 404, 1.0)
        self.assertEqual([r for r in lines(self.path) if r["evt"] == "http.client_error"], [])
        obslog.flush_http_summary()
        self.assertEqual(lines(self.path)[-1]["routes"]["GET /.well-known/oauth-protected-resource"]["codes"],
                         {"2xx": 1, "4xx": 1})

    def test_a_client_that_left_is_not_a_server_error(self):
        class Gone(_H):
            def do_GET(self):
                try:
                    raise BrokenPipeError(32, "Broken pipe")   # e.g. writing to a client that left
                except Exception:
                    self.send_response(500)                   # the catch-all answers... into the void
                    self.end_headers()
        srv = platform_compat.http_server(("127.0.0.1", 0), Gone)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/x" % srv.server_address[1], timeout=5).read()
            except urllib.error.HTTPError:
                pass
            import time
            time.sleep(0.2)
        finally:
            srv.shutdown()
            srv.server_close()
        evts = [r["evt"] for r in lines(self.path)]
        self.assertNotIn("http.error", evts)
        self.assertIn("http.client_gone", evts)

    def test_request_ids_are_unique(self):
        ids = {self.get("/ok")[1] for _ in range(5)}
        self.assertEqual(len(ids), 5)


class TurnEndTests(Base):
    def test_turn_end_carries_ttft_ms(self):
        from unittest import mock
        import session
        sess = session.AgentSession("s1")
        sess._turn_t0 = 1000.0
        sess.turn_started_at = 1000.0
        sess.ttft_ms = None
        with mock.patch("time.time", return_value=1000.25):
            sess._emit({"event": "delta", "text": "hello"})
        self.assertEqual(sess.ttft_ms, 250.0)
        sess._obs_turn_end("result")
        recs = lines(self.path)
        te = next(r for r in recs if r["evt"] == "turn.end")
        self.assertEqual(te["ttft_ms"], 250.0)

    def test_turn_end_carries_null_ttft_when_no_tokens(self):
        import session
        sess = session.AgentSession("s2")
        sess._turn_t0 = 1000.0
        sess.turn_started_at = 1000.0
        sess.ttft_ms = None
        sess._obs_turn_end("error")
        recs = lines(self.path)
        te = next(r for r in recs if r["evt"] == "turn.end")
        self.assertIsNone(te.get("ttft_ms"))


if __name__ == "__main__":
    unittest.main()
