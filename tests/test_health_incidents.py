"""improvement-layers il/D: the log digest's findings become incidents the engine keeps -- opened, made worse,
resolved -- decided from the findings' fields alone, and an incident is ticket evidence (`incident:<id>`).
Run: engine/run-tests.sh test_health_incidents
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
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


    def test_the_operator_hears_an_error_at_once_a_warning_after_a_day_each_once_a_day(self):
        ch = I.judge(self.state, [f("main_red", "error", sha="a"), f("http_slow", route="GET /a")], T0)
        self.assertEqual([i["code"] for i in I.to_notify(self.state, ch, T0)], ["main_red"])
        self.assertEqual(I.to_notify(self.state, [], T0 + 3600), [], "told once a day, not every tick")
        later = T0 + DAY
        self.assertEqual(sorted(i["code"] for i in I.to_notify(self.state, [], later)), ["http_slow", "main_red"])
        self.state["incidents"]["http_slow|GET /a"]["status"] = "ignored"
        got = [i["code"] for i in I.to_notify(self.state, [], later + DAY)]
        self.assertEqual(got, ["main_red"], "an ignored one stays quiet")

    def test_at_most_a_few_at_a_time_the_worst_first(self):
        ch = I.judge(self.state, [f("w%d" % n, src="s%d" % n) for n in range(5)], T0)
        I.judge(self.state, [f("e1", "error"), f("e2", "error")] + [f("w%d" % n, src="s%d" % n) for n in range(5)], T0 + DAY)
        got = [i["code"] for i in I.to_notify(self.state, ch, T0 + DAY)]
        self.assertEqual(got, ["e1", "e2", "w0"][:I.NOTIFY_MAX])
        rest = [i["code"] for i in I.to_notify(self.state, [], T0 + DAY + 3600)]
        self.assertEqual(rest, ["w1", "w2", "w3"], "the rest wait for the next tick")

    def test_a_worse_warning_is_told_at_once(self):
        I.judge(self.state, [f("http_slow", route="GET /a")], T0)
        self.assertEqual(I.to_notify(self.state, [], T0), [])
        ch = I.judge(self.state, [f("http_slow", "error", route="GET /a")], T0 + 60)
        self.assertEqual([i["id"] for i in I.to_notify(self.state, ch, T0 + 60)], [1])

    def test_notify_is_an_event_to_the_default_character_with_metadata_only(self):
        import events
        with mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.tmp / "ev")}), \
                mock.patch("characters.load_team", return_value={"default": "pd"}):
            I.notify([{"id": 3, "code": "main_red", "severity": "error", "title": "secret words"}])
            got = events.recent("host.incident")
        self.assertEqual([(e["to"], e["subject"], e["payload"]["code"]) for e in got], [(["pd"], "3", "main_red")])
        self.assertNotIn("secret words", json.dumps(got))

    def test_the_pd_is_told_the_engine_facts_and_references(self):
        I.tick(self.path, T0, digest={"findings": [f("err_repeat", "error", fp="abc123")]})
        text = I.note([1, 9], self.path)
        self.assertIn("Incident #1 (err_repeat, error", text)
        self.assertIn("incident:1, log:fp:abc123", text)
        self.assertNotIn("#9", text)

    def test_the_operator_decides_ticket_or_ignore(self):
        I.tick(self.path, T0, digest={"findings": [f("http_slow", route="GET /x"), f("repair_frequent")]})
        out = I.decide(self.path, 1, "ticket")
        t = out["ticket"]
        self.assertEqual((t["status"], t["evidence"]), ("approved", ["incident:1"]))
        self.assertEqual(I.decide(self.path, 1, "ticket").get("ticket"), None, "one ticket per incident")
        self.assertEqual(I.get(self.path, 1)["ticket"], t["id"])
        self.assertEqual(I.decide(self.path, 2, "ignore")["incident"]["status"], "ignored")
        with self.assertRaises(KeyError):
            I.decide(self.path, 7, "ignore")
        with self.assertRaises(ValueError):
            I.decide(self.path, 1, "delete")

    def test_api_lists_and_decides(self):
        I.tick(self.path, T0, digest={"findings": [f("http_slow", route="GET /x")]})
        with mock.patch("host_config.INCIDENTS", self.path):
            self.assertIsNone(I.api("GET", "/api/tickets", None))
            code, body = I.api("GET", "/api/incidents", None)
            self.assertEqual((code, [i["id"] for i in body["incidents"]]), (200, [1]))
            self.assertEqual(I.api("POST", "/api/incidents/1/ignore", {})[0], 200)
            self.assertEqual(I.api("POST", "/api/incidents/5/ignore", {})[0], 404)
            self.assertEqual(I.api("POST", "/api/incidents/1/close", {})[0], 404)


    def test_the_first_check_comes_minutes_after_start_then_hourly(self):
        # #865: restarts came more often than hourly, and the first check waited an hour: none ran
        waits = []
        with mock.patch.object(I, "tick", lambda: None):
            I.loop(sleep=waits.append, rounds=3)
        self.assertEqual(waits, [I.FIRST_TICK_SEC, I.TICK_SEC, I.TICK_SEC])
        self.assertLessEqual(I.FIRST_TICK_SEC, 600)

    def test_a_check_after_a_restart_repeats_no_notice(self):
        I.tick(self.path, T0, digest={"findings": [f("main_red", "error", sha="a")]})
        state = I.load(self.path)
        self.assertEqual(I.to_notify(state, [], T0 + 300), [], "told before the restart: not again within the day")

    def test_the_pd_gets_the_log_lines_of_its_incident(self):
        # #867: the engine hands over the evidence; the PD no longer searches whole log files
        I.tick(self.path, T0, digest={"findings": [f("unclean_restart", "error", src="chat", prev_pid=19499),
                                                   f("err_repeat", "error", fp="abc123")]})
        logs = [{"ts": "2026-10-09T02:16:%02d" % n, "src": "chat", "pid": 19499, "evt": "turn.end", "lvl": "info"}
                for n in range(20)]
        logs += [{"ts": "2026-10-09T02:17:00", "src": "chat", "pid": 7, "evt": "proc.start", "lvl": "warn"},
                 {"ts": "2026-10-09T02:18:00", "src": "chat", "pid": 7, "evt": "http.error", "lvl": "error",
                  "err": {"type": "KeyError", "msg": "x", "fp": "abc123"}},
                 {"ts": "2026-10-09T02:18:01", "src": "chat", "pid": 19499, "evt": "http.summary"}]
        text = I.note([1, 2], self.path, events=logs)
        one, two = text.split("Incident #2")
        self.assertEqual(one.count("turn.end"), I.EXCERPT_LINES, "the last lines of that pid, no more")
        self.assertNotIn("proc.start", one)
        self.assertIn("02:16:19", one, "newest kept")
        self.assertIn("fp=abc123", two)
        self.assertNotIn("http.summary", text)
        self.assertIn("prev_pid=19499", one)
        self.assertIn("never open whole log files", text)

    def test_a_signal_without_log_fields_still_gives_its_numbers(self):
        I.tick(self.path, T0, digest={"findings": []},
               improvements=[{"code": "memory_unused", "severity": "warn", "title": "t", "hint": "h",
                              "evidence": {"days": "a..b", "injected": 39, "calls": 0}}])
        text = I.note([1], self.path, events=[])
        self.assertIn("injected=39", text)
        self.assertNotIn("Log lines", text)

if __name__ == "__main__":
    unittest.main()
