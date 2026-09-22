"""LoopGuard: catches the 2026-09-20 Gemini runaway without flagging honest work.
Run: python3 -m unittest tests.test_loop_guard  (from services/chatbot)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from loop_guard import LoopGuard, extract_tool_calls, extract_tool_steps, is_read_only, output_hash, signature  # noqa: E402

APP = "/volume1/homes/me/services/chatbot/static/app.js"


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
        self.assertIn("동일", [v for _, v in got if v.level == "stop"][0].text)

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
        self.assertIn("출력 미확인", got[0][1].text)

    def test_the_output_fingerprint_is_stable_and_none_means_unknown(self):
        self.assertIsNone(output_hash(None))
        self.assertEqual(output_hash("abc"), output_hash("abc"))
        self.assertNotEqual(output_hash("abc"), output_hash("abd"))
        self.assertEqual(output_hash({"b": 1, "a": 2}), output_hash({"a": 2, "b": 1}))
        self.assertIsNotNone(output_hash(""))          # an empty answer is still an answer


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


if __name__ == "__main__":
    unittest.main()
