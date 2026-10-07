"""Route tables (monolith-split split/B, route_table.py): patterns match the way the old if-chains did, the first
route that takes a request answers it, and a handler can pass a request on.
Run: engine/run-tests.sh test_route_table
"""
import sys
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import route_table as RT  # noqa: E402


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, body, content_type, **kw):
        self.sent.append((code, body, content_type, kw))


class Match(unittest.TestCase):
    def test_exact_prefix_suffix_tuple_and_any(self):
        self.assertEqual(RT.match("/api/models", "/api/models"), (True, ""))
        self.assertEqual(RT.match("/api/models", "/api/models/x")[0], False)
        self.assertEqual(RT.match("/api/sessions/*/log", "/api/sessions/s1/log"), (True, "s1"))
        self.assertEqual(RT.match("/api/sessions/*/log", "/api/sessions/a/b/log"), (True, "a/b"))   # as path[a:-b] did
        self.assertEqual(RT.match("/api/sessions/*/log", "/api/sessions/log"), (True, ""))          # overlap, as before
        self.assertEqual(RT.match("/artifacts/*", "/artifacts/x/y.png"), (True, "x/y.png"))
        self.assertEqual(RT.match(("/a", "/b/*"), "/b/c"), (True, "c"))
        self.assertEqual(RT.match(None, "/anything"), (True, "/anything"))


class Dispatch(unittest.TestCase):
    def test_first_route_that_takes_it_answers_and_next_passes_on(self):
        seen = []
        routes = [
            (None, lambda req: seen.append("pass") or RT.NEXT),
            ("/api/sessions/*", lambda req: seen.append("one:" + req.arg)),
            ("/api/sessions/*/log", lambda req: seen.append("log")),        # shadowed: order is the contract
        ]
        req = RT.Req(FakeHandler(), "/api/sessions/s1/log")
        self.assertTrue(RT.dispatch(routes, req))
        self.assertEqual(seen, ["pass", "one:s1/log"])
        self.assertFalse(RT.dispatch([("/x", lambda req: None)], RT.Req(FakeHandler(), "/y")))

    def test_adapters_answer_json_or_pass_on(self):
        h = FakeHandler()
        api = RT.api(lambda method, path, body: (201, {"m": method}) if path == "/mine" else None, "POST")
        self.assertIs(api(RT.Req(h, "/other")), RT.NEXT)
        api(RT.Req(h, "/mine"))
        self.assertEqual(h.sent[-1][:3], (201, b'{"m": "POST"}', RT.JSON))
        self.assertIs(RT.gift(lambda req: None)(RT.Req(h, "/x")), RT.NEXT)
        both = RT.first(lambda req: RT.NEXT, lambda req: None)
        self.assertIsNone(both(RT.Req(h, "/x")))
        self.assertIs(RT.first(lambda req: RT.NEXT)(RT.Req(h, "/x")), RT.NEXT)

    def test_query_helpers(self):
        req = RT.Req(FakeHandler(), "/api/usage", "provider=agy&force=1")
        self.assertEqual((req.q("provider"), req.q("force", "0"), req.q("none", None)), ("agy", "1", None))


if __name__ == "__main__":
    unittest.main()
