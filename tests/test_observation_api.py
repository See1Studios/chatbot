"""/api/observations: list, detail, resolve, review -- what the status tab manages observations with.

The handler runs on an ephemeral port with a temp workspace, so the real observation log is never read or written.
Run: python3 -m unittest tests.test_observation_api  (from services/chatbot)
"""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import server  # noqa: E402
import workspace_status as W  # noqa: E402

TODAY = time.strftime("%Y-%m-%d")


def entry(oid, title, status="open", resolved="", body="Body of %d."):
    return ("---\nid: %d\ntitle: %s\nstatus: %s\ntype: internal\nskill: []\narea: ui\ndate: 2026-09-01\nparked_until:\n"
            "resolved: %s\nresolution:\nreference:\n---\n\n%s\n" % (oid, title, status, resolved, body % oid if "%d" in body else body))


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.obs = self.ws / "skill-observations"
        self.log = self.obs / "observation-log"
        self.log.mkdir(parents=True)
        self._ws = W.WORKSPACE
        W.WORKSPACE = self.ws
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.host = "127.0.0.1:%d" % self.port
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        W.WORKSPACE = self._ws

    def put(self, oid, title="A finding", **kw):
        (self.log / ("%04d-x.md" % oid)).write_text(entry(oid, title, **kw), encoding="utf-8")

    def req(self, method, path, body=None, own_origin=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if own_origin and method != "GET":
            h["Origin"] = "http://" + self.host
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw.decode("utf-8"))

    def status_of(self, oid):
        text = next(self.log.glob("%04d-*.md" % oid)).read_text(encoding="utf-8")
        return [l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("status:")][0]


class ListTest(ApiCase):
    def test_lists_the_log_with_counts_and_recent_candidates(self):
        self.put(1, "Open one")
        self.put(2, "Parked one", status="parked")
        self.put(3, "Done today", status="actioned", resolved=TODAY)
        rows = [{"epoch": 100.0 + i, "ts": "t%d" % i, "signal": "correction", "provider": "agy", "detail": {"user": "u%d" % i}}
                for i in range(25)]
        (self.obs / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        code, d = self.req("GET", "/api/observations")
        self.assertEqual(code, 200)
        self.assertEqual([(o["id"], o["status"]) for o in d["observations"]], [(1, "open"), (2, "parked"), (3, "actioned")])
        self.assertEqual((d["unreviewed_candidates"], len(d["candidates"]), d["last_review"]), (25, 20, "never"))
        self.assertEqual((d["candidates"][0]["user"], d["candidates"][0]["ref"]), ("u24", "candidate:124.0"))  # newest first

    def test_an_empty_or_missing_log_is_an_empty_list_not_an_error(self):
        self.assertEqual(self.req("GET", "/api/observations")[1]["observations"], [])
        import shutil
        shutil.rmtree(str(self.obs))
        code, d = self.req("GET", "/api/observations")
        self.assertEqual((code, d["observations"], d["unreviewed_candidates"]), (200, [], 0))

    def test_files_that_do_not_parse_are_reported_as_a_broken_scan(self):
        (self.log / "0001-x.md").write_text("no header\n", encoding="utf-8")
        code, d = self.req("GET", "/api/observations")
        self.assertEqual(code, 500)
        self.assertIn("scan is broken", d["error"])

    def test_listing_changes_nothing(self):
        self.put(1, status="actioned", resolved="2020-01-01")
        self.req("GET", "/api/observations")
        self.assertTrue((self.log / "0001-x.md").exists(), "a GET must not archive")

    def test_detail_returns_the_body_and_unknown_ids_are_404(self):
        self.put(1, "T", body="**Issue:** it broke <script>alert(1)</script>")
        code, d = self.req("GET", "/api/observations/1")
        self.assertEqual(code, 200)
        self.assertIn("<script>alert(1)</script>", d["observation"]["body"])  # returned as data; the UI shows it as text
        self.assertEqual(self.req("GET", "/api/observations/99")[0], 404)
        self.assertEqual(self.req("GET", "/api/observations/abc")[0], 404)


class ResolveTest(ApiCase):
    def test_resolving_changes_the_file_and_answers_with_the_new_state(self):
        self.put(1)
        code, d = self.req("POST", "/api/observations/1/resolve", {"status": "actioned", "resolution": "Fixed in session.py"})
        self.assertEqual(code, 200, d)
        self.assertEqual((d["observation"]["status"], d["observation"]["resolved"]), ("actioned", TODAY))
        self.assertEqual(self.status_of(1), "actioned")

    def test_parking_needs_a_date(self):
        self.put(1)
        self.assertEqual(self.req("POST", "/api/observations/1/resolve", {"status": "parked", "resolution": "later"})[0], 400)
        code, d = self.req("POST", "/api/observations/1/resolve", {"status": "parked", "resolution": "later", "until": "2026-12-01"})
        self.assertEqual((code, d["observation"]["parked_until"]), (200, "2026-12-01"))

    def test_bad_requests_are_400_and_change_nothing(self):
        self.put(1)
        for body in ({}, {"status": "actioned"}, {"status": "actioned", "resolution": "  "}, {"status": "closed", "resolution": "x"},
                     {"status": "open", "resolution": "x"}, {"resolution": "x"}):
            code, d = self.req("POST", "/api/observations/1/resolve", body)
            self.assertEqual(code, 400, body)
            self.assertFalse(d["ok"])
        self.assertEqual(self.status_of(1), "open")

    def test_an_already_resolved_one_and_an_unknown_one(self):
        self.put(1, status="declined", resolved=TODAY)
        self.assertEqual(self.req("POST", "/api/observations/1/resolve", {"status": "actioned", "resolution": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/observations/9/resolve", {"status": "actioned", "resolution": "x"})[0], 404)

    def test_only_this_servers_own_ui_may_change_things(self):
        self.put(1)
        body = {"status": "actioned", "resolution": "x"}
        self.assertEqual(self.req("POST", "/api/observations/1/resolve", body, own_origin=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/observations/1/resolve", body, own_origin=False,
                                  headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/observations/1/resolve", body, own_origin=False,
                                  headers={"Origin": "http://127.0.0.1:9"})[0], 403)  # another port of this machine
        self.assertEqual(self.status_of(1), "open")

    def test_a_shell_style_call_without_headers_is_refused_too(self):
        self.put(1)
        code, d = self.req("POST", "/api/observations/reviewed", {"summary": "x"}, own_origin=False)
        self.assertEqual(code, 403)
        self.assertFalse((self.obs / "last-review-date.txt").exists())


class ReviewTest(ApiCase):
    def test_reviewed_needs_a_summary_and_then_moves_the_review_date(self):
        for body in ({}, {"summary": ""}, {"summary": "   "}, {"summary": None}):
            self.assertEqual(self.req("POST", "/api/observations/reviewed", body)[0], 400, body)
        self.assertFalse((self.obs / "last-review-date.txt").exists())
        code, d = self.req("POST", "/api/observations/reviewed", {"summary": "read 2 open, closed 1"})
        self.assertEqual((code, d["last_review"]), (200, TODAY))
        self.assertEqual(self.req("GET", "/api/observations")[1]["last_review"], TODAY)
        self.assertIn("read 2 open", (self.obs / "review-history.log").read_text(encoding="utf-8"))


class RoutingTest(ApiCase):
    def test_unknown_paths_and_methods_are_404_and_other_routes_are_untouched(self):
        self.assertEqual(self.req("GET", "/api/observations/1/resolve")[0], 404)
        self.assertEqual(self.req("POST", "/api/observations/nope", {})[0], 404)
        self.assertEqual(self.req("POST", "/api/observations/5", {})[0], 404)
        self.assertEqual(self.req("GET", "/healthz")[0], 200)
        self.assertEqual(self.req("GET", "/api/self-status")[0], 200)

    def test_without_the_core_module_the_routes_answer_503(self):
        saved = W.observations
        W.observations = None
        try:
            self.assertEqual(self.req("GET", "/api/observations")[0], 503)
        finally:
            W.observations = saved

    def test_no_wildcard_cors_on_these_routes(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/observations", headers={"Origin": "http://evil.example"})
        resp = conn.getresponse()
        resp.read()
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
