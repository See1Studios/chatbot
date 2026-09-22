"""/api/tickets: list, detail and the operator's decisions from the status tab.

The handler runs on an ephemeral port with a temp data dir, so the real tickets are never read or written.
Run: python3 -m unittest tests.test_ticket_api  (from services/chatbot)
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import server  # noqa: E402
import tickets  # noqa: E402
import workspace_status as W  # noqa: E402

EVENT = "event:s1#2"


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        (self.data / "sessions" / "s1").mkdir(parents=True)
        (self.data / "sessions" / "s1" / "events.jsonl").write_text('{"event":"a"}\n{"event":"b"}\n', encoding="utf-8")
        (self.data / "workspace" / "skill-observations").mkdir(parents=True)
        self._ws = W.WORKSPACE
        W.WORKSPACE = self.data / "workspace"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        W.WORKSPACE = self._ws

    def propose(self, target="session.py: steer", title="Steer loses the queue"):
        return tickets.propose(self.data, title, target, [EVENT])[0]

    def req(self, method, path, body=None, origin="own", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if origin == "own" and method != "GET":
            h["Origin"] = "http://127.0.0.1:%d" % self.port
        elif origin:
            h["Origin"] = origin
        conn.request(method, path, body=json.dumps(body).encode("utf-8") if body is not None else None, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw.decode("utf-8"))

    def status_of(self, tid):
        return tickets.get(self.data, tid)["status"]


class ListTest(ApiCase):
    def test_lists_tickets_with_their_evidence_and_notes(self):
        t = self.propose()
        code, d = self.req("GET", "/api/tickets")
        self.assertEqual(code, 200)
        self.assertEqual([(x["id"], x["status"], x["evidence"]) for x in d["tickets"]], [(t["id"], "proposed", [EVENT])])

    def test_no_tickets_is_an_empty_list_and_detail_of_a_missing_one_is_404(self):
        self.assertEqual(self.req("GET", "/api/tickets")[1]["tickets"], [])
        self.assertEqual(self.req("GET", "/api/tickets/9")[0], 404)
        self.assertEqual(self.req("GET", "/api/tickets/abc")[0], 404)

    def test_detail_returns_the_ticket_as_data(self):
        t = self.propose(title="<script>alert(1)</script>")
        code, d = self.req("GET", "/api/tickets/%d" % t["id"])
        self.assertEqual((code, d["ticket"]["title"]), (200, "<script>alert(1)</script>"))


class DecisionTest(ApiCase):
    def test_approve_and_the_record_says_the_ui_did_it(self):
        t = self.propose()
        code, d = self.req("POST", "/api/tickets/%d/approve" % t["id"], {})
        self.assertEqual((code, d["ticket"]["status"]), (200, "approved"))
        self.assertEqual(self.status_of(t["id"]), "approved")
        self.assertEqual(d["ticket"]["notes"][-1]["by"], "operator (ui)")

    def test_decline_a_proposed_and_an_approved_ticket(self):
        a = self.propose("a.py")
        b = self.propose("b.py")
        tickets.approve(self.data, b["id"], operator=tickets.OPERATOR_CONFIRMED)
        for t in (a, b):
            self.assertEqual(self.req("POST", "/api/tickets/%d/decline" % t["id"], {})[0], 200)
            self.assertEqual(self.status_of(t["id"]), "declined")

    def test_reopen_gives_a_wontfix_ticket_a_fresh_budget(self):
        t = self.propose()
        tickets.approve(self.data, t["id"], operator=tickets.OPERATOR_CONFIRMED)
        for _ in range(tickets.MAX_ATTEMPTS):
            c = tickets.claim(self.data, t["id"])
            tickets.release(self.data, t["id"], c["token"], "failed")
        self.assertEqual(self.status_of(t["id"]), "wontfix")
        code, d = self.req("POST", "/api/tickets/%d/reopen" % t["id"], {})
        self.assertEqual((code, d["ticket"]["status"], d["ticket"]["attempts"]), (200, "approved", 0))

    def test_the_core_rules_still_apply(self):
        t = self.propose()
        self.req("POST", "/api/tickets/%d/decline" % t["id"], {})
        code, d = self.req("POST", "/api/tickets/%d/approve" % t["id"], {})   # declined is final
        self.assertEqual(code, 400)
        self.assertIn("declined", d["error"])
        self.assertEqual(self.status_of(t["id"]), "declined")
        self.assertEqual(self.req("POST", "/api/tickets/99/approve", {})[0], 404)

    def test_nothing_but_the_three_decisions_can_be_posted(self):
        t = self.propose()
        for path in ("/api/tickets", "/api/tickets/%d" % t["id"], "/api/tickets/%d/claim" % t["id"],
                     "/api/tickets/%d/release" % t["id"], "/api/tickets/%d/approve/x" % t["id"], "/api/tickets/drop-lease"):
            self.assertEqual(self.req("POST", path, {"title": "x"})[0], 404, path)
        self.assertEqual(self.status_of(t["id"]), "proposed")
        self.assertEqual(len(tickets.list_tickets(self.data)), 1)


class OriginTest(ApiCase):
    def test_a_decision_needs_this_servers_own_page(self):
        t = self.propose()
        path = "/api/tickets/%d/approve" % t["id"]
        for origin in (None, "http://evil.example", "http://127.0.0.1:%d.evil.example" % self.port, "null"):
            self.assertEqual(self.req("POST", path, {}, origin=origin)[0], 403, origin)
        self.assertEqual(self.status_of(t["id"]), "proposed")
        self.assertEqual(self.req("POST", path, {})[0], 200)

    def test_a_browser_fetch_without_origin_is_same_origin_only_when_it_says_so(self):
        t = self.propose()
        path = "/api/tickets/%d/approve" % t["id"]
        self.assertEqual(self.req("POST", path, {}, origin=None, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.status_of(t["id"]), "proposed")


class AgentCannotUseItTest(unittest.TestCase):
    def test_the_tool_adapters_never_pass_an_operator(self):
        src = (CODE / "mcp_core.py").read_text(encoding="utf-8")
        self.assertNotIn("OPERATOR", src)
        self.assertNotIn("operator=", src)


if __name__ == "__main__":
    unittest.main()
