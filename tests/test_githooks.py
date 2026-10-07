"""Commit hooks (.githooks/, plan-execution-workflow pew/E) refuse what the rules forbid, in a throwaway repo: a
non-Conventional subject, a docs/plans change without a `Plan:` trailer, a committed secrets file, a key-shaped added
line. The delegation runner's own commit subjects must pass.
Run: engine/run-tests.sh test_githooks
"""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from tests._platform import dev_only_bash  # noqa: E402
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO
spec = importlib.util.spec_from_file_location("check_staged", ROOT / ".githooks" / "check_staged.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@dev_only_bash
class Hooks(unittest.TestCase):
    def setUp(self):
        # /tmp is mounted noexec on this NAS, and git silently skips a hook it cannot execute
        base = Path(os.environ.get("HOOK_TEST_DIR") or Path.home() / ".cache" / "chatbot-hook-tests")
        base.mkdir(parents=True, exist_ok=True)
        self.repo = Path(tempfile.mkdtemp(dir=str(base)))
        shutil.copytree(str(ROOT / ".githooks"), str(self.repo / ".githooks"))
        self.git("init", "-q")
        self.git("config", "core.hooksPath", ".githooks")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")

    def tearDown(self):
        shutil.rmtree(str(self.repo), ignore_errors=True)

    def git(self, *args):
        # inside a hook git exports the outer commit's author and its `-c` settings; the test repo's own config decides
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG_"))}
        return subprocess.run(["git", *args], cwd=str(self.repo), capture_output=True, text=True, env=env)

    def commit(self, rel, text, msg):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.git("add", rel)
        return self.git("commit", "-qm", msg)

    def test_the_guards_never_inherit_a_commits_dash_c_config(self):
        # `git -c user.name=agy commit -- <path>` (the runner's diary line) handed GIT_CONFIG_PARAMETERS to the guard
        # tests; their own git then wrote as agy and test_githooks failed: the line stayed staged after every merge
        saved = dict(os.environ)
        try:
            os.environ.update({"GIT_CONFIG_PARAMETERS": "'user.name=agy'", "GIT_CONFIG_COUNT": "1",
                               "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "agy", "GIT_INDEX_FILE": "x"})
            env = check._clean_git_env()
            self.assertFalse([k for k in env if k.startswith("GIT_CONFIG_") or k == "GIT_INDEX_FILE"])
            self.assertIn("PATH", env)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_a_conventional_subject_passes_and_others_do_not(self):
        self.assertNotEqual(self.commit("a.txt", "1", "update stuff").returncode, 0)
        self.assertEqual(self.commit("a.txt", "1", "fix(core): update stuff\n\nTicket: #1").returncode, 0)

    def test_a_code_change_names_its_ticket(self):
        # review of #505-#525: 27 of 29 delegated commits had no Ticket trailer
        r = self.commit("a.txt", "1", "feat(ui): something")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Ticket: #<n>", r.stdout + r.stderr)
        self.assertEqual(self.commit("a.txt", "2", "feat(ui): something\n\nTicket: #4").returncode, 0)
        self.assertEqual(self.commit("b.txt", "1", "docs: notes").returncode, 0)          # not a code change
        self.assertEqual(self.commit("c.txt", "1", "chore(tickets): close #4 -- t").returncode, 0)

    def test_a_code_change_carries_its_test_or_says_why_not(self):
        # TEST_PAIRING_v1: 19 of 200 feat/fix commits before 2026-10-07 changed code with no test and nothing said why
        (self.repo / "tools").mkdir()
        shutil.copy(str(ENGINE / "tools" / "review_checklist.py"), str(self.repo / "tools" / "review_checklist.py"))
        r = self.commit("app.py", "x = 1\n", "fix(core): a bug\n\nTicket: #1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No-Test:", r.stdout + r.stderr)
        self.assertEqual(self.git("commit", "-qm", "fix(core): a bug\n\nNo-Test: rename only\nTicket: #1").returncode, 0)
        p = self.repo / "tests" / "test_app.py"
        p.parent.mkdir()
        p.write_text("pass\n", encoding="utf-8")
        self.git("add", "tests/test_app.py")
        self.assertEqual(self.commit("app.py", "x = 2\n", "feat(core): more\n\nTicket: #2").returncode, 0)
        self.assertEqual(self.commit("notes.md", "n\n", "fix(docs): typo\n\nTicket: #3").returncode, 0)   # no code
        self.assertEqual(self.commit("app.py", "x = 3\n", "chore: tidy").returncode, 0)                  # not a product type

    def test_a_worker_on_its_ticket_branch_gets_the_trailer_written(self):
        self.assertEqual(self.commit("a.txt", "1", "chore: start").returncode, 0)
        self.git("checkout", "-q", "-b", "worktree/ticket-77")
        self.assertEqual(self.commit("a.txt", "2", "feat(ui): from a worker").returncode, 0)
        self.assertIn("Ticket: #77", self.git("log", "-1", "--format=%B").stdout)

    def test_plan_changes_need_a_plan_trailer(self):
        self.assertNotEqual(self.commit("docs/plans/x.md", "x", "docs(plans): x").returncode, 0)
        self.assertEqual(self.commit("docs/plans/x.md", "x", "docs(plans): x\n\nPlan: x/A").returncode, 0)

    def test_secrets_are_refused_without_echoing_them(self):
        r = self.commit("data/secrets.env", "K=1", "chore: keys")
        self.assertNotEqual(r.returncode, 0)
        self.git("rm", "-q", "--cached", "data/secrets.env")
        fake = "sk-" + "A" * 30
        r = self.commit("b.py", "KEY = '%s'\n" % fake, "feat: add b")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(fake, r.stdout + r.stderr)
        self.assertEqual(self.commit("b.py", "KEY = '%s'  # %s\n" % (fake, check.ALLOW), "test: fixture").returncode, 0)

    def test_guards_judge_the_staged_snapshot_not_the_shared_tree(self):
        # pew/Q: agents share one working tree; another agent's unstaged work must not decide my commit
        (self.repo / "run-tests.sh").write_text('grep -q bad guard.txt && { echo "failed: guard"; exit 1; }; exit 0\n',
                                                encoding="utf-8")
        self.assertEqual(self.commit("guard.txt", "ok\n", "chore: start").returncode, 0)   # first commit: no HEAD yet
        self.git("add", "run-tests.sh")
        self.assertEqual(self.git("commit", "-qm", "chore: runner").returncode, 0)
        (self.repo / "guard.txt").write_text("bad\n", encoding="utf-8")                   # someone else's unstaged work
        self.assertEqual(self.commit("mine.txt", "x\n", "feat: mine\n\nTicket: #1").returncode, 0)
        (self.repo / "only.txt").write_text("y\n", encoding="utf-8")
        self.git("add", "only.txt")
        self.assertEqual(self.git("commit", "-qm", "feat: by path\n\nTicket: #1", "--", "only.txt").returncode, 0)   # temp index
        self.git("add", "guard.txt")                                                        # now I stage the breakage
        self.assertNotEqual(self.git("commit", "-qm", "feat: breaks").returncode, 0)
        self.git("reset", "-q", "guard.txt")
        self.assertNotEqual(self.git("commit", "-qam", "feat: all").returncode, 0)          # -a stages it too
        worktrees = self.git("worktree", "list").stdout.strip().splitlines()
        self.assertEqual(len(worktrees), 1, "the snapshot worktree must be removed: %s" % worktrees)

    def test_the_hooks_are_committed_executable(self):
        # a hook that lost its exec bit is skipped with only a hint -- the check would vanish silently
        out = subprocess.run(["git", "ls-files", "-s", ".githooks"], cwd=str(ROOT), capture_output=True, text=True).stdout
        modes = {l.split()[-1]: l.split()[0] for l in out.splitlines()}
        for hook in (".githooks/pre-commit", ".githooks/commit-msg", ".githooks/reference-transaction"):
            if modes:   # tracked: the index must say 100755
                self.assertEqual(modes.get(hook), "100755", hook)
            self.assertTrue(os.access(str(ROOT / hook), os.X_OK), hook)

    def test_the_runner_commit_subjects_pass(self):
        for s in ("chore(tickets): close #12 -- title", "chore(tickets): #12 gate_failed -- t",
                  "chore(ticket #12): changes the agent left uncommitted"):
            self.assertTrue(check.SUBJECT.match(s), s)

    # --- ENGINE_DECIDES_A5: who commits and who lands is decided by the engine, not typed by the agent ---

    def _with_core(self):
        for name in ("evolution.py", "platform_compat.py", "repo_layout.py"):
            shutil.copy(str(ENGINE / name), str(self.repo / name))

    def test_a_ticket_record_with_a_persona_actor_is_refused(self):
        # 2026-10-03: a chat agent wrote closed_by "Coco" around tickets.py; the guards then broke main for everyone
        self._with_core()
        rel = "data/workspace/skill-observations/tickets/0583.json"
        bad = '{"id": 583, "closed_by": "Coco", "notes": [{"by": "agent:Coco", "text": "done"}]}'
        r = self.commit(rel, bad, "chore(tickets): close #583 -- t")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("closed_by", r.stdout + r.stderr)
        self.assertIn("agent:Coco", r.stdout + r.stderr)
        good = '{"id": 583, "closed_by": "agy", "notes": [{"by": "agent:agy", "text": "done"}, {"by": "host", "text": "x"}]}'
        self.assertEqual(self.commit(rel, good, "chore(tickets): close #583 -- t").returncode, 0)

    def test_a_persona_name_is_never_the_author(self):
        card = '{"data": {"name": "코코"}}'
        self.assertEqual(self.commit("data/workspace/characters/char_x/card.json", card, "chore: card").returncode, 0)
        self.git("config", "user.name", "코코")
        r = self.commit("a.txt", "1", "chore: x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("character's name", r.stdout + r.stderr)

    def test_a_live_chat_agent_commits_as_the_app(self):
        self.git("config", "user.name", "Coco")
        def refuse(actor):
            return check.author_refusal(self.repo, lambda: actor)
        cwd = os.getcwd()
        os.chdir(str(self.repo))
        try:
            self.assertIn("commits as the app 'PE'", refuse("chat-agent:agy"))     # whatever its brain
            self.assertIn("commits as the app 'PE'", refuse("chat-agent:claude"))
            self.git("config", "user.name", "PE")
            self.assertEqual(refuse("chat-agent:agy"), "")
            self.assertEqual(refuse("chat-agent:claude"), "")
            self.git("config", "user.name", "Coco")
            self.assertEqual(refuse("chat-agent:?"), "")       # the host itself or a runner it started
            self.assertEqual(refuse("claude-code"), "")        # an agent outside the chat names itself
        finally:
            os.chdir(cwd)

    def test_a_live_chat_agents_commit_also_runs_the_tests_related_to_its_files(self):
        # AGENT_COMMIT_RELATED_v1: #689-#691 (2026-10-06) were committed from chat past the FAST guards only
        # a module whose test is not a FAST guard: guards run anyway and are left out of the related list
        mods = check.related_for(ROOT, ["room_chat.py"], lambda: "chat-agent:agy")
        self.assertIn("test_room_chat", mods)
        self.assertTrue(all(m.startswith("test_") for m in mods), mods)
        self.assertEqual(check.related_for(ROOT, ["dialog_handoff.py"], lambda: "chat-agent:?"), [])   # the host
        self.assertEqual(check.related_for(ROOT, ["dialog_handoff.py"], lambda: "claude-code"), [])
        self.assertEqual(check.related_for(ROOT, [], lambda: "chat-agent:agy"), [])
        self.assertEqual(check.related_for(self.repo, ["x.py"], lambda: "chat-agent:agy"), [])          # no runner here

    def test_only_a_live_chat_agent_landing_a_worker_branch_is_refused(self):
        main = [("0" * 40, "a" * 40, "refs/heads/main")]
        on_worker = lambda sha: True
        self.assertIn("landing is the operator's", check.ref_refusal(main, lambda: "chat-agent:agy", on_worker))
        self.assertEqual(check.ref_refusal(main, lambda: "chat-agent:?", on_worker), "")      # the runner's merge
        self.assertEqual(check.ref_refusal(main, lambda: "claude-code", on_worker), "")       # an outside agent
        self.assertEqual(check.ref_refusal(main, lambda: "chat-agent:agy", lambda sha: False), "")   # its own commit
        other = [("0" * 40, "a" * 40, "refs/heads/worktree/ticket-1")]
        self.assertEqual(check.ref_refusal(other, lambda: "chat-agent:agy", on_worker), "")
        gone = [("a" * 40, "0" * 40, "refs/heads/main")]
        self.assertEqual(check.ref_refusal(gone, lambda: "chat-agent:agy", on_worker), "")

    def test_the_ref_hook_lets_ordinary_main_updates_through(self):
        self.assertEqual(self.commit("a.txt", "1", "chore: start").returncode, 0)
        self.git("checkout", "-q", "-b", "worktree/ticket-9")
        self.assertEqual(self.commit("a.txt", "2", "chore: work").returncode, 0)
        self.git("checkout", "-q", "-")
        r = self.git("merge", "-q", "--ff-only", "worktree/ticket-9")   # no repo modules here: caller unknown
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
