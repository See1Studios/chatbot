"""improvement-layers il/D: the log digest's findings become incidents the engine keeps -- opened, made worse,
resolved -- decided from the findings' fields alone, and an incident is ticket evidence (`incident:<id>`).
Run: engine/run-tests.sh test_health_incidents
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from health import incidents as I  # noqa: E402
from telemetry import obslog  # noqa: E402
import tickets  # noqa: E402

T0 = 1_800_000_000.0
DAY = 86400


def f(code, sev="warn", **ev):
    return {"code": code, "severity": sev, "title": code + " title", "hint": "look", "evidence": ev}


class Incidents(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "dev" / "incidents.json"
        self.state = I.load(self.path)

    def changes(self, findings, now):
        return [(c["change"], c["incident"]["id"]) for c in I.judge(self.state, findings, now)]

    def test_a_restart_is_not_a_new_incident(self):
        # the key holds no pid or time: unclean_restart of the chat server stays one incident
        a = I.key_of(f("unclean_restart", "error", src="chat", prev_pid=1, restart_at="x"))
        b = I.key_of(f("unclean_restart", "error", src="chat", prev_pid=2, restart_at="y"))
        self.assertEqual(a, b)
        self.assertNotEqual(I.key_of(f("http_slow", route="GET /a")), I.key_of(f("http_slow", route="GET /b")))

    def test_open_then_quiet_then_worse_then_resolved(self):
        self.assertEqual(self.changes([f("http_slow", route="GET /a")], T0), [("open", 1)])
        self.assertEqual(self.changes([f("http_slow", route="GET /a")], T0 + 3600), [])          # seen again: quiet
        self.assertEqual(self.changes([f("http_slow", "error", route="GET /a")], T0 + 7200), [("worse", 1)])
        self.assertEqual(self.changes([], T0 + 7200 + DAY - 1), [])                               # not a day yet
        self.assertEqual(self.changes([], T0 + 7200 + DAY), [("resolved", 1)])
        self.assertEqual(self.changes([f("http_slow", route="GET /a")], T0 + 3 * DAY), [("open", 2)])   # it came back

    def test_an_ignored_incident_speaks_again_only_when_it_gets_worse(self):
        self.changes([f("repair_frequent")], T0)
        self.state["incidents"]["repair_frequent"]["status"] = "ignored"
        self.assertEqual(self.changes([f("repair_frequent")], T0 + 3600), [])
        self.assertEqual(self.changes([f("repair_frequent", "error")], T0 + 7200), [("worse", 1)])
        self.assertEqual(self.state["incidents"]["repair_frequent"]["status"], "open")

    def test_a_tick_keeps_the_state_and_logs_each_change(self):
        log = self.tmp / "events.jsonl"
        saved = dict(obslog._state)
        self.addCleanup(lambda: (obslog._state.clear(), obslog._state.update(saved)))
        obslog.configure("test", path=log, mirror="error")
        got = I.tick(self.path, T0, digest={"findings": [f("main_red", "error", sha="abc")]})
        self.assertEqual([c["change"] for c in got], ["open"])
        self.assertEqual(I.get(self.path, 1)["code"], "main_red")
        self.assertEqual(I.tick(self.path, T0 + 60, digest={"findings": [f("main_red", "error")]}), [])
        evts = [json.loads(l)["evt"] for l in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(evts, ["incident.open"])

    def test_a_red_main_check_is_ticket_evidence(self):
        data = self.tmp
        (data / "logs").mkdir()
        (data / "logs" / "events.jsonl").write_text(json.dumps(
            {"evt": "main.check", "sha": "7a713ee6df27", "ok": False}, separators=(",", ":")) + "\n", encoding="utf-8")
        tickets.verify_evidence(data, "main:7a713ee6df27")
        with self.assertRaises(tickets.TicketError):
            tickets.verify_evidence(data, "main:000000000000")

    def test_an_incident_is_ticket_evidence(self):
        data = self.tmp
        I.tick(data / "dev" / "incidents.json", T0, digest={"findings": [f("http_slow", route="GET /x")]})
        tickets.verify_evidence(data, "incident:1")
        with self.assertRaises(tickets.TicketError):
            tickets.verify_evidence(data, "incident:2")


if __name__ == "__main__":
    unittest.main()
