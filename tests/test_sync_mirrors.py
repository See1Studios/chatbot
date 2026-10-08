"""Korean mirrors of the standing documents (MIRROR_SYNC_v1, tools/sync_mirrors.py): machine-translated for the
operator to follow, never read by agents. Masking keeps code, links and the glossary's terms out of the translator;
the hook syncs a staged document and only warns when offline; the mirrors in the repo match their sources.
Run: engine/run-tests.sh test_sync_mirrors
"""
import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from engine.tools import sync_mirrors
from tests._paths import REPO  # noqa: E402


def fake_translate(text, **_kw):
    return text.replace("keeps", "지킨다").replace("Heading", "제목")


class Masking(unittest.TestCase):
    def test_code_and_links_round_trip_with_their_spaces(self):
        doc = ("# Heading\n\nHere is `inline code` and text, see [a plan](docs/plans/x.md#y).\n\n"
               "```python\ndef foo():\n    return 42\n```\n\nAnother line with `another_inline`.")
        masked, keys = sync_mirrors.mask_markdown(doc)
        for gone in ("def foo():", "`inline code`", "docs/plans/x.md"):
            self.assertNotIn(gone, masked)
        self.assertEqual(sync_mirrors.unmask_markdown(masked, keys), doc)

    def test_glossary_terms_come_back_as_the_fixed_word(self):
        masked, keys = sync_mirrors.mask_markdown("Agents keep the lore; the harnesses of providers. A lorebook.")
        out = sync_mirrors.unmask_markdown(masked, keys)
        self.assertEqual(out, "에이전트 keep the 로어; the 하네스 of 제공자. A 로어북.")

    def test_the_particle_after_a_term_fits_the_word(self):
        _, keys = sync_mirrors.mask_markdown("identity agent plugin")
        g = sorted(keys)   # XZG0ZX identity -> 정체성, XZG1ZX agent -> 에이전트, XZG2ZX plugin -> 플러그인
        text = "%s는 x, %s을 y, %s가 z, %s는가" % (g[0], g[1], g[2], g[0])
        self.assertEqual(sync_mirrors.unmask_markdown(text, keys), "정체성은 x, 에이전트를 y, 플러그인이 z, 정체성는가")

    def test_a_term_inside_a_word_or_code_stays(self):
        masked, keys = sync_mirrors.mask_markdown("agentic `agent.py` lorem")
        self.assertEqual(sync_mirrors.unmask_markdown(masked, keys), "agentic `agent.py` lorem")

    def test_every_glossary_term_is_matched(self):
        for term, ko in sync_mirrors.GLOSSARY.items():
            masked, keys = sync_mirrors.mask_markdown("x %s y" % term)
            self.assertEqual(sync_mirrors.unmask_markdown(masked, keys), "x %s y" % ko, term)


class SyncFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src, self.mir = self.dir / "TEST.md", self.dir / "TEST.ko.md"
        self.src.write_text("# Heading\n\nThe agent keeps `x.md`.", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_translates_keeps_code_and_writes_the_header(self):
        with patch.object(sync_mirrors, "translate_text_chunk", side_effect=fake_translate):
            status, _ = sync_mirrors.sync_file(self.src, self.mir)
        self.assertEqual(status, "ok")
        text = self.mir.read_text(encoding="utf-8")
        self.assertEqual(sync_mirrors.read_mirror_hash(text), sync_mirrors.calc_sha256(self.src.read_text(encoding="utf-8")))
        self.assertTrue(text.endswith("# 제목\n\nThe 에이전트 지킨다 `x.md`."), text)

    def test_skips_when_the_hash_matches_and_reports_stale_otherwise(self):
        with patch.object(sync_mirrors, "translate_text_chunk", side_effect=fake_translate):
            sync_mirrors.sync_file(self.src, self.mir)
        self.assertEqual(sync_mirrors.sync_file(self.src, self.mir)[0], "skipped")
        self.src.write_text("# Heading\n\nchanged", encoding="utf-8")
        self.assertEqual(sync_mirrors.sync_file(self.src, self.mir, check_only=True)[0], "stale")


class TranslationMemory(unittest.TestCase):
    """MIRROR_TM_v1 (2026-10-08): one new rule row resent the whole document and the endpoint answered 429 for
    hours. Only what changed goes to the translator; the rest comes from the mirror and the source it was made from."""

    V1 = ("# Heading\n\nThe agent keeps `x.md`.\n\n```\ncode\n\nmore code\n```\n\n"
          "| Rule | Who |\n|---|---|\n| one keeps | all |\n| two keeps | all |\n\nLast paragraph keeps.\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src, self.mir = self.dir / "TEST.md", self.dir / "TEST.ko.md"
        self.git("init", "-q")
        self.src.write_text(self.V1, encoding="utf-8")
        with patch.object(sync_mirrors, "translate_text_chunk", side_effect=fake_translate):
            sync_mirrors.sync_file(self.src, self.mir)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.dir), *args], check=True, capture_output=True)

    def sync(self, text):
        self.src.write_text(text, encoding="utf-8")
        sent = []
        with patch.object(sync_mirrors, "translate_text_chunk", side_effect=lambda t, **k: sent.append(t) or fake_translate(t)):
            self.assertEqual(sync_mirrors.sync_file(self.src, self.mir)[0], "ok")
        return sent

    def test_only_a_changed_paragraph_and_a_new_table_row_are_sent(self):
        v2 = self.V1.replace("| two keeps | all |", "| two keeps | all |\n| three keeps | all |").replace(
            "Last paragraph keeps.", "Last paragraph changed.")
        sent = self.sync(v2)
        self.assertEqual(len(sent), 1, sent)
        self.assertNotIn("one keeps", sent[0])
        self.assertIn("three keeps", sent[0])
        self.assertIn("Last paragraph changed.", sent[0])
        mirror = self.mir.read_text(encoding="utf-8")
        with patch.object(sync_mirrors, "translate_text_chunk", side_effect=fake_translate):
            sync_mirrors.sync_file(self.src, self.mir, force=True)
        self.assertEqual(mirror, self.mir.read_text(encoding="utf-8"), "same as translating it all")

    def test_without_the_old_source_in_git_the_whole_document_is_translated(self):
        (self.dir / ".git").rename(self.dir / "no-git")                  # the source it was made from is gone
        sent = self.sync(self.V1 + "\nNew.\n")
        self.assertTrue(any("one keeps" in t for t in sent), sent)

    def test_a_rate_limit_is_waited_out(self):
        import urllib.error
        tries, waits = [], []

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=0):
            tries.append(1)
            if len(tries) < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return Answer(b'[[["hi",null]]]')

        with patch.object(sync_mirrors.urllib.request, "urlopen", side_effect=urlopen), \
                patch.object(sync_mirrors.time, "sleep", side_effect=waits.append):
            self.assertEqual(sync_mirrors.translate_text_chunk("hello"), "hi")
        self.assertEqual(len(tries), 3)
        self.assertIn(sync_mirrors.BACKOFF_SEC[0], waits)
        self.assertIn(sync_mirrors.BACKOFF_SEC[1], waits)


class Hook(unittest.TestCase):
    def load_hook(self):
        spec = importlib.util.spec_from_file_location("check_staged_mirror", REPO / ".githooks" / "check_staged.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_offline_the_hook_warns_and_lets_the_commit_go(self):
        hook = self.load_hook()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "RULES.md").write_text("# Rules", encoding="utf-8")
            with patch.object(hook, "_repo_module", return_value=sync_mirrors), \
                 patch.object(sync_mirrors, "translate_text_chunk", side_effect=RuntimeError("offline")):
                out = io.StringIO()
                with redirect_stdout(out):
                    hook.sync_mirrors(d, ["RULES.md", "engine/x.py"])
            self.assertIn("warning: RULES.md: Korean mirror not synced (offline)", out.getvalue())
            self.assertFalse((Path(d) / "RULES.ko.md").exists())

    def test_the_hook_reads_the_tool_s_one_target_list(self):
        src = (REPO / ".githooks" / "check_staged.py").read_text(encoding="utf-8")
        self.assertIn("sm.DEFAULT_MIRROR_TARGETS", src)
        for name in sync_mirrors.DEFAULT_MIRROR_TARGETS:
            self.assertNotIn('"%s"' % name, src, "the hook names no mirror target of its own")


class RepoMirrors(unittest.TestCase):
    def test_standing_docs_mirrors_up_to_date(self):
        for target in sync_mirrors.DEFAULT_MIRROR_TARGETS:
            src = REPO / target
            self.assertTrue(src.is_file(), target)
            mirror = src.parent / (src.name[:-3] + ".ko.md")
            self.assertTrue(mirror.exists(), "Mirror missing for %s: run python3 engine/tools/sync_mirrors.py" % target)
            status, msg = sync_mirrors.sync_file(src, mirror, check_only=True)
            self.assertEqual(status, "skipped", "%s -- run python3 engine/tools/sync_mirrors.py %s" % (msg, target))


if __name__ == "__main__":
    unittest.main()
