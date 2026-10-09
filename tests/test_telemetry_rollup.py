"""tl/C (docs/plans/telemetry.md): one summary per day in logs/metrics/, built by the engine from the event log, kept
forever, the backlog filled once; today is never written while it is still going on.
Run: engine/run-tests.sh test_telemetry_rollup
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from telemetry import obslog, rollup  # noqa: E402
import platform_compat  # noqa: E402


def ev(day, hh, evt, **kw):
    return dict({"ts": "%sT%02d:00:00.000+09:00" % (day, hh), "lvl": "info", "src": "chat", "evt": evt, "pid": 1}, **kw)


EVENTS = [
    ev("2026-10-01", 23, "context.inject", sid="s1", character="c1", mode="work", provider="agy", chars=5000),
    ev("2026-10-02", 9, "turn.end", sid="s1", provider="agy", model="m", outcome="result", dur_s=10.0, ttft_ms=800.0),
    ev("2026-10-02", 10, "turn.end", sid="s1", provider="agy", model="m", outcome="process_died", dur_s=30.0),
    ev("2026-10-02", 11, "http.summary", routes={"GET /api/x": {"n": 3, "codes": {"2xx": 3}, "p95": 120.0, "max": 150.0},
                                                 "GET /api/sessions/:sid/events": {"n": 1, "p95": 9e6, "max": 9e6},
                                                 "…": "cut"}),
    ev("2026-10-02", 12, "react.defer", reason="quiet_hours", repeat=4),
    ev("2026-10-02", 12, "http.error", lvl="error", err={"fp": "abc1234567", "msg": "x"}),
    ev("2026-10-02", 13, "proc.start"),
    ev("2026-10-03", 9, "turn.end", sid="s2", provider="claude", model="o", outcome="result", dur_s=5.0),
]


class Rollup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "events.jsonl"

    def tearDown(self):
        obslog._state["path"] = None
        obslog._state.pop("rolled_at", None)
        self.tmp.cleanup()

    def day(self, day):
        return json.loads((rollup.dir_for(self.log) / ("%s.json" % day)).read_text(encoding="utf-8"))

    def test_a_day_sums_turns_by_provider_model_mode_and_character(self):
        self.assertEqual(rollup.build(self.log, EVENTS, today="2026-10-03"), ["2026-10-01", "2026-10-02"])
        r = self.day("2026-10-02")
        t = r["turns"]["agy|m|work|c1"]                   # character and mode from the session's inject, the day before
        self.assertEqual(t["outcomes"], {"result": 1, "process_died": 1})
        self.assertEqual((t["dur_s"]["n"], t["dur_s"]["max"], t["ttft_ms"]["n"]), (2, 30.0, 1))
        self.assertEqual(r["http"]["chat GET /api/x"]["n"], 3)
        self.assertNotIn("chat …", r["http"])         # obslog's cut entry is not a route
        self.assertEqual(r["messages"]["react_defer"], {"quiet_hours": 5})   # the folded repeats count
        self.assertEqual(r["errors"]["top_fp"], {"abc1234567": 1})
        self.assertEqual(r["proc"]["starts"], {"chat": 1})
        self.assertFalse((rollup.dir_for(self.log) / "2026-10-03.json").exists(), "today is not finished")

    def test_the_backlog_is_filled_once_and_only_missing_days(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(e) + "\n" for e in EVENTS))
        now = time.mktime(time.strptime("2026-10-03 12:00", "%Y-%m-%d %H:%M"))
        self.assertEqual(rollup.build_missing(self.log, now), ["2026-10-01", "2026-10-02"])
        self.assertEqual(rollup.build_missing(self.log, now), [])
        self.assertEqual(rollup.missing(self.log, "2026-09-30", "2026-10-03"), ["2026-09-30"])   # before the log

    def test_turn_meters_are_summed_and_older_days_get_tokens_from_the_sessions(self):
        # tl/D: turn.end carries tokens from 2026-10-09; days before it take them from the sessions' usage
        events = EVENTS + [ev("2026-10-02", 14, "turn.end", sid="s1", provider="agy", model="m", outcome="result",
                              dur_s=4.0, tool_calls=20, read_kb=43, tok_in=1000, tok_out=50, tok_total=1050,
                              prep_ms=850.0, spawn_ms=600.0, first_tool_ms=2100.0)]
        sessions = Path(self.tmp.name) / "sessions"
        (sessions / "a").mkdir(parents=True)
        day1 = time.mktime(time.strptime("2026-10-01 12:00", "%Y-%m-%d %H:%M"))
        day2 = day1 + 86400
        (sessions / "a" / "meta.json").write_text(json.dumps({
            "provider": "agy", "model": "m", "character": "c1",
            "history": [{"role": "user", "ts": day1, "text": "never read"},
                        {"role": "assistant", "ts": day1, "usage": {"input_tokens": 700, "total_tokens": 720}},
                        {"role": "assistant", "ts": day2, "usage": {"input_tokens": 999, "total_tokens": 999}}]}),
            encoding="utf-8")
        rollup.build(self.log, events, today="2026-10-03", usage=rollup.session_usage(sessions))
        t = self.day("2026-10-02")["turns"]["agy|m|work|c1"]
        self.assertEqual((t["tool_calls"]["max"], t["read_kb"]["max"], t["tokens_from"]), (20.0, 43.0, "turns"))
        self.assertEqual(t["tokens"], {"tok_in": 1000, "tok_out": 50, "tok_total": 1050})   # not added twice
        self.assertEqual((t["prep_ms"]["max"], t["spawn_ms"]["n"], t["first_tool_ms"]["p50"]), (850.0, 1, 2100.0))
        t1 = self.day("2026-10-01")["turns"]["agy|m|work|c1"]
        self.assertEqual((t1["tokens"], t1["tokens_from"]), ({"tok_in": 700, "tok_total": 720}, "sessions"))

    def test_a_rollup_an_older_version_wrote_is_rebuilt(self):
        d = rollup.dir_for(self.log)
        d.mkdir()
        (d / "2026-10-01.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
        (d / "2026-10-02.json").write_text(json.dumps({"version": rollup.VERSION}), encoding="utf-8")
        self.assertEqual(rollup.missing(self.log, "2026-10-01", "2026-10-03"), ["2026-10-01"])

    def test_memory_calls_hits_and_injected_memory(self):
        # tl/E: what was remembered and recalled, as counts (mcp.call metadata, context.inject layer sizes)
        events = [ev("2026-10-02", 9, "context.inject", sid="s9", character="c", mode="work", provider="agy", chars=900,
                     layers=[{"id": "charter", "chars": 500}, {"id": "house_memory", "chars": 300},
                             {"id": "own_memory", "chars": 100}]),
                  ev("2026-10-02", 10, "mcp.call", src="mcp", tool="memory", ok=True, args={"action": "add"},
                     result={"status": "added"}),
                  ev("2026-10-02", 11, "mcp.call", src="mcp", tool="memory", ok=True, args={"action": "search"},
                     result={"hits": 3})]
        rollup.build(self.log, events, today="2026-10-03")
        m = self.day("2026-10-02")["memory"]
        self.assertEqual((m["calls"], m["added"], m["search_hits"]["max"]), ({"add": 1, "search": 1}, 1, 3.0))
        self.assertEqual(sorted(m["injected_chars"]), ["house_memory", "own_memory"])

    def test_one_builder_at_a_time(self):
        d = rollup.dir_for(self.log)
        d.mkdir()
        self.log.write_text(json.dumps(EVENTS[1]) + "\n", encoding="utf-8")
        with open(d / ".lock", "a", encoding="utf-8", newline="\n") as held:
            self.assertTrue(platform_compat.lock_file(held, blocking=False))
            self.assertEqual(rollup.build_missing(self.log), [])
            platform_compat.unlock_file(held)

    def test_the_background_tick_runs_hourly_and_logs_what_it_wrote(self):
        obslog.configure("test", path=self.log, mirror="error")
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev("2020-01-01", 9, "turn.end", sid="x", provider="p", model="m", outcome="result")) + "\n")
        days = obslog.rollup_tick(now=time.time())
        self.assertIn("2020-01-01", days)
        self.assertIsNone(obslog.rollup_tick(now=time.time() + 60))
        self.assertIn("log.rollup", self.log.read_text(encoding="utf-8"))

    def test_the_show_line_leaves_out_streams(self):
        rollup.build(self.log, EVENTS, today="2026-10-03")
        line = rollup._line(self.day("2026-10-02"))
        self.assertIn("chat GET /api/x", line)
        self.assertNotIn("/events", line)


if __name__ == "__main__":
    unittest.main()
