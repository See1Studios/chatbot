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

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE / "tools"))
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


def usage(fresh, cached, out, think=0):
    return {"input_tokens": fresh, "cache_read_tokens": cached, "output_tokens": out, "thinking_tokens": think}


class Split(unittest.TestCase):
    def test_each_cli_gives_the_answer_and_its_tokens_in_the_chats_definition(self):
        # input_tokens = the uncached input, cache_read_tokens = the cached part, for every CLI alike
        self.assertEqual(U.split("agy", AGY), ("ok", usage(47260, 0, 25, 24)))
        self.assertEqual(U.split("claude", CLAUDE), ("ok", usage(11015, 12413, 40)))
        self.assertEqual(U.split("grok", GROK), ("ok", usage(22767, 12032, 23)))
        self.assertEqual(U.split("codex", CODEX), ("ok", usage(11134, 8960, 5)))   # cached is inside codex's input

    def test_the_numbers_are_the_chat_adapters_own(self):
        sys.path.insert(0, str(ENGINE))
        from providers.adapters import AGENT_ADAPTERS
        raw = json.loads(CLAUDE)["usage"]
        want = AGENT_ADAPTERS["claude"].normalize_usage(raw)
        got = U.split("claude", CLAUDE)[1]
        self.assertEqual(got, {k: want[k] for k in got})

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
        self.assertEqual({k: line[k] for k in ("ticket", "role", "provider", "input_tokens", "cache_read_tokens")},
                         {"ticket": 77, "role": "reviewer", "provider": "agy", "input_tokens": 47260, "cache_read_tokens": 0})



class CodexCountsCachedOnce(unittest.TestCase):
    def test_cached_input_is_inside_codexs_input_tokens(self):
        # measured 2026-10-04: the same prompt twice gave input_tokens 20141 with cached 2816, then 0
        sys.path.insert(0, str(ENGINE))
        from providers.adapters import AGENT_ADAPTERS
        u = AGENT_ADAPTERS["codex"].normalize_usage({"input_tokens": 20141, "cached_input_tokens": 2816,
                                                     "output_tokens": 5})
        self.assertEqual((u["input_tokens"], u["cache_read_tokens"], u["total_tokens"]), (17325, 2816, 17330))


if __name__ == "__main__":
    unittest.main()
