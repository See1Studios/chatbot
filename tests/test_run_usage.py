"""tools/run_usage.py: each delegated CLI call's tokens, read from the CLI's own JSON (token-economy.md T6).
The outputs below are the real shapes the four CLIs printed for "Reply with just: ok" on 2026-10-04.
Run: python3 -m unittest tests.test_run_usage  (from services/chatbot)
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import run_usage as U  # noqa: E402
import worktree_runner as wr  # noqa: E402

AGY = json.dumps({"conversation_id": "c", "duration_seconds": 3, "num_turns": 1, "response": "ok", "status": "ok",
                  "usage": {"input_tokens": 47260, "output_tokens": 25, "thinking_tokens": 24, "cache_read_tokens": 0,
                            "total_tokens": 47285}})
CLAUDE = json.dumps({"result": "ok", "usage": {"input_tokens": 10, "cache_creation_input_tokens": 11005,
                                               "cache_read_input_tokens": 12413, "output_tokens": 40}})
GROK = json.dumps({"text": "ok", "usage": {"input_tokens": 22767, "cache_read_input_tokens": 12032,
                                           "cache_creation_input_tokens": 0, "output_tokens": 23}})
CODEX = "\n".join(json.dumps(e) for e in (
    {"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "skills shortened"}},
    {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "ok"}},
    {"type": "turn.completed", "usage": {"input_tokens": 20094, "cached_input_tokens": 8960, "output_tokens": 5}}))


class Split(unittest.TestCase):
    def test_each_cli_gives_the_answer_and_its_tokens(self):
        self.assertEqual(U.split("agy", AGY), ("ok", {"input": 47260, "cached": 0, "output": 25}))
        self.assertEqual(U.split("claude", CLAUDE), ("ok", {"input": 23428, "cached": 12413, "output": 40}))
        self.assertEqual(U.split("grok", GROK), ("ok", {"input": 34799, "cached": 12032, "output": 23}))
        self.assertEqual(U.split("codex", CODEX), ("ok", {"input": 20094, "cached": 8960, "output": 5}))

    def test_an_output_of_another_shape_is_passed_through_untouched(self):
        for provider in ("agy", "claude", "grok", "codex"):
            self.assertEqual(U.split(provider, "plain text answer"), ("plain text answer", None))
        self.assertEqual(U.split("agy", '{"error": "quota"}'), ('{"error": "quota"}', None))


class Machine(unittest.TestCase):
    def test_the_switch_goes_where_each_cli_reads_it(self):
        self.assertEqual(U.machine("agy", ["agy", "--dangerously-skip-permissions", "-p", "do it"]),
                         ["agy", "--dangerously-skip-permissions", "--output-format", "json", "-p", "do it"])
        self.assertEqual(U.machine("codex", ["codex", "exec", "-s", "read-only", "-"]),
                         ["codex", "exec", "--json", "-s", "read-only", "-"])
        cmd = ["claude", "--output-format", "json", "-p", "x"]
        self.assertEqual(U.machine("claude", cmd), cmd, "never twice")
        self.assertEqual(U.machine("other", ["other", "-p", "x"]), ["other", "-p", "x"])


class RunnerRecords(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, str(self.base), True)

    def test_a_call_returns_the_text_and_leaves_one_usage_line(self):
        seen = []
        with mock.patch.object(wr, "WORKTREE_BASE", self.base), \
                mock.patch.object(wr, "host_module", side_effect=ImportError("no host")), \
                mock.patch.object(wr, "run_cmd", side_effect=lambda cmd, **kw: (seen.append(cmd), (0, AGY, ""))[1]), \
                mock.patch.dict(U.CONTEXT, {"ticket": 77}):
            got = wr.run_as_login("agy", ["agy", "-p", "do it"], cwd=self.base / "review-room")
        self.assertEqual(got, (0, "ok", ""), "the runner sees the answer, as before")
        self.assertIn("--output-format", seen[0])
        line = json.loads((self.base / "runs" / "usage.jsonl").read_text(encoding="utf-8"))
        self.assertEqual({k: line[k] for k in ("ticket", "role", "provider", "input", "cached", "output")},
                         {"ticket": 77, "role": "reviewer", "provider": "agy", "input": 47260, "cached": 0, "output": 25})


if __name__ == "__main__":
    unittest.main()
