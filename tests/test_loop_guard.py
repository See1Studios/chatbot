"""LoopGuard: catches the 2026-09-20 Gemini runaway without flagging honest work, and holds a turn to its budget.
Rules A-C are tested with the budget (rule D) out of the way; rule D has its own class below.
Run: python3 -m unittest tests.test_loop_guard  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from loop_guard import LoopGuard as _Guard, extract_tool_calls, extract_tool_steps, is_read_only, output_hash, read_size, signature  # noqa: E402,E501

NO_BUDGET = dict(budget_calls=(10 ** 6, 10 ** 6), budget_bytes=(10 ** 12, 10 ** 12))


def LoopGuard(**kw):   # rules A-C, with rule D's budget out of the way
    return _Guard(**{**NO_BUDGET, **kw})

APP = str(Path(__file__).resolve().parent.parent / "static" / "app.js")


def view(guard, start, end, path=APP, summary="Viewing app.js", output="default"):
    """One view_file call. Its output is the content of that window unless the test says otherwise (None = not known)."""
    if output == "default":
        output = "lines %s-%s of %s" % (start, end, path)
    return guard.observe("view_file", {"AbsolutePath": path, "StartLine": start, "EndLine": end,
                                       "toolAction": "Viewing", "toolSummary": summary}, output)


def first_verdicts(guard, calls):
    """Feed calls; return [(call_number, verdict)] for every verdict raised."""
    out = []
    for i, fn in enumerate(calls, 1):
        v = fn(guard)
        if v:
            out.append((i, v))
    return out


class IncidentReplay(unittest.TestCase):
    def test_same_window_over_and_over_warns_then_stops(self):
        g = LoopGuard()
        got = first_verdicts(g, [lambda g: view(g, 2020, 2035)] * 12)
        levels = [(n, v.level, v.rule) for n, v in got]
        self.assertEqual(levels[0], (5, "warn", "consecutive"))
        self.assertIn((8, "stop", "consecutive"), levels)
        # the session kills the process at the FIRST stop, so what matters is when that comes:
        # call 8 = ~30s at the observed 4s/call, instead of 23 minutes
        self.assertEqual(min(n for n, v in got if v.level == "stop"), 8)

    def test_paging_a_huge_file_in_tiny_windows_is_caught_even_though_no_call_repeats(self):
        g = LoopGuard()
        calls = [(lambda g, i=i: view(g, i * 15, i * 15 + 15)) for i in range(120)]
        got = first_verdicts(g, calls)
        self.assertEqual([(n, v.level, v.rule) for n, v in got][:2], [(24, "warn", "run"), (48, "stop", "run")])

    def test_prose_that_changes_every_call_does_not_hide_a_repeat(self):
        g = LoopGuard()
        got = first_verdicts(g, [(lambda g, i=i: view(g, 10, 20, summary=f"attempt {i}")) for i in range(8)])
        self.assertTrue(got, "toolSummary differs per call but the call itself is identical")
        self.assertEqual(signature("view_file", {"AbsolutePath": APP, "toolSummary": "a"}),
                         signature("view_file", {"AbsolutePath": APP, "toolSummary": "b"}))


class SameCallMeansNoNewInformation(unittest.TestCase):
    """2026-09-21: six reads of different ranges of app.js were flagged as "the same call" (the arguments the host
    saw had no line numbers) and a stop was one step away. Different output = progress."""

    def rangeless_view(self, g, i, output):
        return g.observe("view_file", {"AbsolutePath": APP, "toolSummary": "try %d" % i}, output)

    def test_identical_arguments_with_different_outputs_never_trip_the_repeat_rules(self):
        g = LoopGuard()
        got = first_verdicts(g, [(lambda g, i=i: self.rangeless_view(g, i, "window %d" % i)) for i in range(20)])
        self.assertEqual([(n, v.rule) for n, v in got if v.rule in ("exact", "consecutive")], [])

    def test_a_real_loop_with_confirmed_equal_outputs_still_stops_at_the_usual_count(self):
        g = LoopGuard()
        got = first_verdicts(g, [(lambda g: self.rangeless_view(g, 0, "same text"))] * 12)
        stops = [(n, v.rule) for n, v in got if v.level == "stop"]
        self.assertEqual(min(n for n, _ in stops), 8)
        self.assertIn("the same", [v for _, v in got if v.level == "stop"][0].text)

    def test_a_run_that_changes_its_output_midway_is_not_a_repeat(self):
        g = LoopGuard()
        outputs = ["same"] * 4 + ["different"] + ["same"] * 3
        got = first_verdicts(g, [(lambda g, o=o: self.rangeless_view(g, 0, o)) for o in outputs])
        self.assertEqual([v for _, v in got if v.level == "stop"], [])

    def test_without_any_output_it_can_warn_but_a_stop_takes_twice_the_count(self):
        g = LoopGuard()
        got = first_verdicts(g, [(lambda g: self.rangeless_view(g, 0, None))] * 20)
        stops = [(n, v.rule) for n, v in got if v.level == "stop"]
        self.assertEqual((got[0][0], got[0][1].level), (5, "warn"))
        self.assertEqual(min(n for n, _ in stops), 16)
        self.assertIn("output unchecked", got[0][1].text)

    def test_the_output_fingerprint_is_stable_and_none_means_unknown(self):
        self.assertIsNone(output_hash(None))
        self.assertEqual(output_hash("abc"), output_hash("abc"))
        self.assertNotEqual(output_hash("abc"), output_hash("abd"))
        self.assertEqual(output_hash({"b": 1, "a": 2}), output_hash({"a": 2, "b": 1}))
        self.assertIsNotNone(output_hash(""))          # an empty answer is still an answer


class StatOnlyOutputIsNotEvidence(unittest.TestCase):
    """2026-09-25: agy's view_file reported only {AbsolutePath} and "868 lines, 36259 bytes" for every range,
    so paging app-session.js was stopped as "the same call 3 times" after the course-change notice."""

    def stat_view(self, g):
        return g.observe("view_file", {"AbsolutePath": APP}, "868 lines, 36259 bytes")

    def test_paging_with_stat_only_output_trips_no_repeat_rule_even_when_tightened(self):
        g = LoopGuard()
        g.tighten(3)
        got = first_verdicts(g, [self.stat_view] * 20)
        self.assertEqual([(n, v.rule) for n, v in got if v.rule in ("exact", "consecutive")], [])

    def test_a_stat_only_runaway_is_still_stopped_by_the_run_rule(self):
        g = LoopGuard()
        got = first_verdicts(g, [self.stat_view] * 60)
        self.assertEqual([(n, v.level, v.rule) for n, v in got], [(24, "warn", "run"), (48, "stop", "run")])

    def test_only_a_bare_size_summary_counts_as_stat_only(self):
        from loop_guard import is_stat_only
        self.assertTrue(is_stat_only("868 lines, 36259 bytes"))
        self.assertTrue(is_stat_only(" 1 line, 5 bytes\n"))
        self.assertFalse(is_stat_only("868 lines, 36259 bytes\nfunction enterSession(id, opts) {"))
        self.assertFalse(is_stat_only(None))
        self.assertFalse(is_stat_only({"lines": 868}))

    def test_real_content_repeats_are_still_caught_around_stat_only_calls(self):
        g = LoopGuard()
        got = first_verdicts(g, [self.stat_view, lambda g: view(g, 1, 20)] + [lambda g: view(g, 1, 20)] * 10)
        self.assertIn("consecutive", [v.rule for _, v in got if v.level == "stop"])


class HonestWorkIsLeftAlone(unittest.TestCase):
    def test_reading_a_file_in_a_few_windows_then_acting_resets_the_run(self):
        g = LoopGuard()
        calls = []
        for round_ in range(6):
            calls += [(lambda g, i=i: view(g, i * 200, i * 200 + 200)) for i in range(15)]      # long read...
            calls.append(lambda g: g.observe("replace_file_content", {"TargetFile": APP, "n": 1}))  # ...then an edit
        self.assertEqual(first_verdicts(g, calls), [])

    def test_edit_run_tests_edit_cycle_may_rerun_the_same_command_many_times(self):
        g = LoopGuard()
        calls = []
        for i in range(20):
            calls.append(lambda g, i=i: g.observe("replace_file_content", {"TargetFile": APP, "chunk": i}))
            calls.append(lambda g: g.observe("run_command", {"CommandLine": "python3 -m unittest"}))
        self.assertEqual(first_verdicts(g, calls), [])

    def test_reading_many_different_files_is_fine(self):
        g = LoopGuard()
        calls = [(lambda g, i=i: view(g, 1, 50, path=f"/src/file{i}.py")) for i in range(80)]
        self.assertEqual(first_verdicts(g, calls), [])

    def test_a_reread_or_two_of_the_same_range_is_normal(self):
        g = LoopGuard()
        calls = [lambda g: view(g, 1, 40), lambda g: g.observe("grep_search", {"Query": "x"}),
                 lambda g: view(g, 1, 40), lambda g: g.observe("run_command", {"CommandLine": "ls"}),
                 lambda g: view(g, 1, 40)]
        self.assertEqual(first_verdicts(g, calls), [])


class Bookkeeping(unittest.TestCase):
    def test_each_rule_and_level_fires_once_per_turn_and_reset_rearms(self):
        g = LoopGuard()
        first = first_verdicts(g, [lambda g: view(g, 1, 2)] * 30)
        keys = [(v.rule, v.level) for _, v in first]
        self.assertEqual(len(keys), len(set(keys)))
        g.reset()
        self.assertEqual(first_verdicts(g, [lambda g: view(g, 1, 2)] * 5)[0][1].level, "warn")

    def test_read_only_classification(self):
        for t in ("view_file", "view_code_item", "grep_search", "list_dir", "find_by_name", "read_url_content"):
            self.assertTrue(is_read_only(t), t)
        for t in ("replace_file_content", "run_command", "write_to_file", "manage_task"):
            self.assertFalse(is_read_only(t), t)

    def test_verdict_text_names_the_tool_and_target(self):
        g = LoopGuard()
        v = first_verdicts(g, [lambda g: view(g, 1, 2)] * 5)[0][1]
        self.assertIn("view_file", v.text)
        self.assertIn("app.js", v.text)


class ExtractToolCalls(unittest.TestCase):
    STEP = {"event": "step_update", "step_update": {"step_index": 3, "state": "DONE", "step_type": "tool",
            "tool_name": "view_file", "tool_info": {"name": "view_file", "parameters": {"AbsolutePath": APP},
                                                    "output": "22 lines"}}}

    def test_real_agy_stream_shape_counts_the_done_step_once(self):
        self.assertEqual(extract_tool_calls(self.STEP), [("view_file", {"AbsolutePath": APP})])
        self.assertEqual(extract_tool_steps(self.STEP), [("view_file", {"AbsolutePath": APP}, "22 lines")])
        active = {"event": "step_update", "step_update": {**self.STEP["step_update"], "state": "ACTIVE"}}
        self.assertEqual(extract_tool_calls(active), [])

    def test_a_finished_subagent_call_is_a_tool_call(self):
        # agy 1.2.16 sends the DONE of invoke_subagent as step_type "subagent" (director-handoff, 2026-10-05)
        done = {"step_update": {"state": "DONE", "step_type": "subagent", "tool_name": "invoke_subagent",
                                "tool_info": {"name": "invoke_subagent", "parameters": {"Subagents": []}}}}
        self.assertEqual([n for n, _, _ in extract_tool_steps(done)], ["invoke_subagent"])

    def test_other_step_types_and_plain_events_are_not_tool_calls(self):
        for step_type in ("agent_response", "user_input", "unknown", "checkpoint"):
            self.assertEqual(extract_tool_calls({"step_update": {"state": "DONE", "step_type": step_type}}), [])
        self.assertEqual(extract_tool_calls({"event": "result", "result": {}}), [])

    def test_older_shapes_are_still_understood(self):
        self.assertEqual(extract_tool_calls({"tool_calls": [{"name": "view_file", "args": {"path": "/a"}}]}),
                         [("view_file", {"path": "/a"})])
        self.assertEqual(extract_tool_calls({"event": "tool_use", "name": "run_command", "input": {"c": 1}}),
                         [("run_command", {"c": 1})])

    def test_missing_tool_info_falls_back_to_tool_name(self):
        self.assertEqual(extract_tool_calls({"step_update": {"state": "DONE", "step_type": "tool", "tool_name": "manage_task"}}),
                         [("manage_task", {})])



class TurnBudget(unittest.TestCase):
    """Rule D (token-economy.md): every read goes back to the model on each later call of the turn."""

    def read(self, g, n, size=1000):
        return g.observe("view_file", {"AbsolutePath": "/r/f%d.py" % n}, "10 lines, %d bytes" % size)

    def test_many_calls_warn_then_stop(self):
        g = _Guard()
        got = [(i, v.level, v.rule) for i in range(1, 46) for v in [self.read(g, i)] if v]
        self.assertEqual(got, [(20, "warn", "budget"), (40, "stop", "budget")])

    def test_a_few_big_reads_cross_the_byte_line(self):
        g = _Guard()
        got = [(i, v.level, v.rule, v.text) for i in range(1, 6) for v in [self.read(g, i, 300_000)] if v]
        self.assertEqual([x[:3] for x in got], [(2, "warn", "budget"), (4, "stop", "budget")])   # 600 KB, then 1.2 MB
        self.assertIn("1200 KB", got[1][3])

    def test_writes_and_commands_count_as_calls_not_reads(self):
        g = _Guard()
        g.observe("run_command", {"CommandLine": "ls"}, "x" * 900_000)
        self.assertEqual((g.calls, g.read_bytes), (1, 0))

    def test_after_the_notice_the_turn_has_only_the_rest(self):
        g = _Guard()
        g.tighten()
        g.reset()   # the resumed turn
        got = [(i, v.level) for i in range(1, 25) for v in [self.read(g, i)] if v]
        self.assertEqual(got, [(20, "stop")], "the 20 calls left above the warning, and no second warning")
        g.relax()
        g.reset()
        got = [(i, v.level) for i in range(1, 25) for v in [self.read(g, i)] if v]
        self.assertEqual(got, [(20, "warn")])

    def test_read_size_takes_the_stat_line_or_the_text(self):
        self.assertEqual(read_size("868 lines, 36259 bytes"), 36259)
        self.assertEqual(read_size("abc"), 3)
        self.assertEqual(read_size(None), 0)


if __name__ == "__main__":
    unittest.main()
