"""Host lifecycle safeguards (docs/plans/recursive-self-evolution.md §3 0-6 and decision 4):
shared lifecycle lock, maintenance flag, the protected-file check against git HEAD, and how chatbot-ctl.sh calls them.

Safety: no test runs a real start/doctor/repair. The lock wrapper is exercised through a stub script whose
body only echoes, and the real chatbot-ctl.sh is run in a temp tree only on paths that return before doing
anything (maintenance flag present, lock busy).
Run: python3 -m unittest tests.test_lifecycle  (from services/chatbot)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import evolution  # noqa: E402
from tests._platform import dev_only_bash  # noqa: E402

PY = sys.executable


def tmpdir():
    return Path(tempfile.mkdtemp()).resolve()


class LockTest(unittest.TestCase):
    def setUp(self):
        self.lock = tmpdir() / "lifecycle.lock"

    def test_second_holder_is_refused_until_the_first_lets_go(self):
        first = evolution.acquire_lock(self.lock, 0)
        with self.assertRaises(evolution.LockBusy):
            evolution.acquire_lock(self.lock, 0)
        first.close()
        evolution.acquire_lock(self.lock, 0).close()

    def test_waiting_gives_up_after_the_wait(self):
        first = evolution.acquire_lock(self.lock, 0)
        t0 = time.time()
        with self.assertRaises(evolution.LockBusy):
            evolution.acquire_lock(self.lock, 0.5)
        self.assertGreaterEqual(time.time() - t0, 0.45)
        first.close()

    def test_a_waiter_gets_the_lock_when_it_frees_up(self):
        first = evolution.acquire_lock(self.lock, 0)
        holder = subprocess.Popen([PY, "-c", "import time; time.sleep(1)"])
        try:
            first.close()
            evolution.acquire_lock(self.lock, 2).close()
        finally:
            holder.kill()
            holder.wait()


class RunLockedTest(unittest.TestCase):
    def setUp(self):
        self.lock = tmpdir() / "lifecycle.lock"

    def helper(self, wait, *argv, **kw):
        return subprocess.run([PY, str(CODE / "evolution.py"), "run-locked", str(self.lock), str(wait), "--"] + list(argv),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)

    def test_child_status_is_returned_and_child_knows_it_is_inside(self):
        r = self.helper(0, PY, "-c", "import os, sys; print('%d:%s' % (os.getppid(), os.environ.get('CHATBOT_LOCK_PPID', ''))); "
                                     "sys.exit(3)")   # python, not sh: the core's lock runs on Windows too (#411)
        self.assertEqual(r.returncode, 3)
        ppid, marker = r.stdout.strip().split(":")
        if os.name == "posix":   # the marker is the parent pid; a Windows venv python.exe is a launcher, so the child's
            self.assertEqual(ppid, marker)   # parent is the launcher. Only chatbot-ctl.sh (bash, dev) reads it (#411)

    def test_a_process_the_child_leaves_running_does_not_keep_the_lock(self):
        # the host server is started by ctl and outlives it: it must not inherit the lock
        r = self.helper(0, PY, "-c", "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; "
                                     "time.sleep(3)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print('started')")
        self.assertEqual(r.returncode, 0)
        evolution.acquire_lock(self.lock, 0).close()

    def test_busy_doctor_style_run_skips_without_running(self):
        held = evolution.acquire_lock(self.lock, 0)
        r = self.helper(0, PY, "-c", "print('BODY')")
        held.close()
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped", r.stdout)
        self.assertNotIn("BODY", r.stdout)

    def test_busy_start_style_run_waits_then_exits_75_without_running(self):
        held = evolution.acquire_lock(self.lock, 0)
        r = self.helper(0.3, PY, "-c", "print('BODY')")
        held.close()
        self.assertEqual(r.returncode, evolution.BUSY_EXIT)
        self.assertNotIn("BODY", r.stdout)

    def test_unusable_lock_file_still_runs_the_command(self):
        bad = tmpdir() / "no" / "such" / "dir" / "x.lock"
        r = subprocess.run([PY, str(CODE / "evolution.py"), "run-locked", str(bad), "0", "--", PY, "-c", "print('BODY')"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertIn("BODY", r.stdout)
        self.assertIn("without it", r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_self_check_passes_when_usable_and_fails_when_not(self):
        ok = subprocess.run([PY, str(CODE / "evolution.py"), "self-check", str(self.lock)])
        self.assertEqual(ok.returncode, 0)
        held = evolution.acquire_lock(self.lock, 0)
        busy = subprocess.run([PY, str(CODE / "evolution.py"), "self-check", str(self.lock)])
        held.close()
        self.assertEqual(busy.returncode, 0)  # busy is not "broken"
        bad = subprocess.run([PY, str(CODE / "evolution.py"), "self-check", str(tmpdir() / "no" / "x.lock")],
                             stderr=subprocess.PIPE)
        self.assertNotEqual(bad.returncode, 0)


class MaintenanceTest(unittest.TestCase):
    def test_flag_file_is_detected_with_its_age(self):
        d = tmpdir()
        self.assertIsNone(evolution.maintenance_note(d / "maintenance.flag"))
        (d / "maintenance.flag").write_text("", encoding="utf-8")
        self.assertRegex(evolution.maintenance_note(d / "maintenance.flag"), r"^age \d+s$")

    def test_cli_exit_status(self):
        d = tmpdir()
        flag = d / "maintenance.flag"
        absent = subprocess.run([PY, str(CODE / "evolution.py"), "maintenance", str(flag)], stdout=subprocess.PIPE)
        self.assertEqual(absent.returncode, 1)
        flag.write_text("", encoding="utf-8")
        present = subprocess.run([PY, str(CODE / "evolution.py"), "maintenance", str(flag)], stdout=subprocess.PIPE)
        self.assertEqual(present.returncode, 0)


def make_root(volatile=("data/state.txt",), protect=("*.py", "tests/", "static/", "data/state.txt", "data/secret.md"),
              except_=("static/",)):
    root = tmpdir()
    (root / evolution.REGISTRY_NAME).write_text(json.dumps(
        {"protect": list(protect), "except": list(except_), "volatile": list(volatile)}), encoding="utf-8")
    (root / "server.py").write_text("print('a')\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
    (root / "static").mkdir()
    (root / "static" / "app.js").write_text("1", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "state.txt").write_text("changes all the time", encoding="utf-8")
    (root / "data" / "secret.md").write_text("rules", encoding="utf-8")
    (root / "notes.md").write_text("not protected", encoding="utf-8")
    return root


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=True).stdout


def committed_root(**kw):
    root = make_root(**kw)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


class ProtectedChangesTest(unittest.TestCase):
    """split/E: doctor warns about protected files that differ from git HEAD (no hand-kept hash baseline)."""

    def test_a_clean_tree_reports_ok(self):
        root = committed_root()
        self.assertEqual(evolution.protected_changes(root), ("ok", {"modified": [], "missing": [], "new": []}))
        self.assertEqual(evolution.protected_report(root), "protected files OK (all committed)")

    def test_volatile_excepted_and_unprotected_changes_are_ignored(self):
        root = committed_root()
        (root / "data" / "state.txt").write_text("different", encoding="utf-8")
        (root / "static" / "app.js").write_text("2", encoding="utf-8")
        (root / "notes.md").write_text("edited", encoding="utf-8")
        (root / "static" / "new.js").write_text("3", encoding="utf-8")
        self.assertEqual(evolution.protected_changes(root)[0], "ok")

    def test_modified_missing_and_new_files_are_reported(self):
        root = committed_root()
        (root / "server.py").write_text("print('b')\n", encoding="utf-8")
        (root / "data" / "secret.md").unlink()
        (root / "brand_new.py").write_text("y", encoding="utf-8")
        (root / "tests" / "staged.py").write_text("z", encoding="utf-8")
        git(root, "add", "tests/staged.py")
        status, diffs = evolution.protected_changes(root)
        self.assertEqual(status, "differs")
        self.assertEqual(diffs, {"modified": ["server.py"], "missing": ["data/secret.md"],
                                 "new": ["brand_new.py", "tests/staged.py"]})
        report = evolution.protected_report(root)
        self.assertTrue(report.startswith("WARN "))
        for word in ("server.py", "data/secret.md", "brand_new.py", "warning only"):
            self.assertIn(word, report)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "reviewed")
        self.assertEqual(evolution.protected_changes(root)[0], "ok", "a commit is the approval")

    def test_outside_a_git_tree_is_information_not_a_warning(self):
        root = make_root()
        self.assertEqual(evolution.protected_changes(root)[0], "nogit")
        self.assertNotIn("WARN", evolution.protected_report(root))

    def test_a_broken_registry_warns_and_never_raises(self):
        root = committed_root()
        (root / evolution.REGISTRY_NAME).write_text("{nope", encoding="utf-8")
        self.assertEqual(evolution.protected_changes(root)[0], "unreadable")
        self.assertTrue(evolution.protected_report(root).startswith("WARN "))

    def test_long_lists_are_shortened(self):
        root = committed_root()
        for i in range(20):
            (root / ("m%02d.py" % i)).write_text("x", encoding="utf-8")
        self.assertIn("(+12 more)", evolution.protected_report(root))

    def test_this_repository_is_checked_without_caches_or_run_time_state(self):
        status, diffs = evolution.protected_changes(CODE)
        self.assertIn(status, ("ok", "differs"))
        listed = [f for v in diffs.values() for f in v]
        self.assertFalse([f for f in listed if "__pycache__" in f or "/tickets/" in f or f.endswith("events.jsonl")])

    def test_cli_check_never_fails(self):
        out = subprocess.run([PY, str(CODE / "evolution.py"), "protected-check"], stdout=subprocess.PIPE,
                             universal_newlines=True)
        self.assertEqual(out.returncode, 0)  # even when files differ
        self.assertTrue(out.stdout.strip())


CTL_TEXT = (CODE / "chatbot-ctl.sh").read_text(encoding="utf-8")
WRAPPER = re.search(r"(case \"\$\{1:-status\}\" in\n  start\|doctor.*?\nesac\n)", CTL_TEXT, re.S)


@dev_only_bash
class WrapperTest(unittest.TestCase):
    """The real wrapper text from chatbot-ctl.sh, run around a body that only echoes."""

    def setUp(self):
        self.assertIsNotNone(WRAPPER, "lock wrapper not found in chatbot-ctl.sh")
        self.tree = tmpdir()
        self.code = self.tree / "code"
        self.data = self.tree / "data"
        self.code.mkdir()
        self.data.mkdir()
        for m in json.loads((CODE / "core_modules.json").read_text(encoding="utf-8"))["core"]:   # PP5: siblings too
            shutil.copy(str(CODE / (m + ".py")), str(self.code / (m + ".py")))
        self.stub = self.tree / "stub.sh"
        self.stub.write_text(
            "#!/bin/bash\nset -euo pipefail\nCODE=%s\nDATA=%s\n%s"
            'echo "BODY ppid=$PPID lock=${CHATBOT_LOCK_PPID:-none} args=$*"\n' % (self.code, self.data, WRAPPER.group(1)),
            encoding="utf-8")
        self.lock = self.data / "lifecycle.lock"

    def run_stub(self, *args, **env):
        e = dict(os.environ)
        e.pop("CHATBOT_LOCK_PPID", None)
        e.update(env)
        return subprocess.run(["bash", str(self.stub)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, env=e, timeout=20)  # a hang must fail, not stall the suite

    def test_lifecycle_commands_run_inside_the_lock(self):
        for cmd in ("start", "doctor", "repair", "defibrillate", "shock", "cpr"):
            r = self.run_stub(cmd, "--auto-repair")
            self.assertEqual(r.returncode, 0, cmd + r.stderr)
            m = re.search(r"BODY ppid=(\d+) lock=(\d+) args=%s --auto-repair" % cmd, r.stdout)
            self.assertTrue(m and m.group(1) == m.group(2), r.stdout)

    def test_other_commands_do_not_touch_the_lock(self):
        held = evolution.acquire_lock(self.lock, 0)
        for cmd in ("status", "guard", "probe", "stop", "restart"):
            r = self.run_stub(cmd)
            self.assertIn("lock=none", r.stdout, cmd)
        self.assertIn("lock=none", self.run_stub().stdout)  # bare == status
        held.close()

    def test_doctor_skips_when_busy_and_start_or_repair_give_up(self):
        held = evolution.acquire_lock(self.lock, 0)
        doc = self.run_stub("doctor")
        self.assertEqual(doc.returncode, 0)
        self.assertIn("skipped", doc.stdout)
        for cmd in ("start", "repair"):
            r = self.run_stub(cmd, CHATBOT_LOCK_WAIT_SEC="0.3")
            self.assertEqual(r.returncode, evolution.BUSY_EXIT, cmd)
            self.assertNotIn("BODY", r.stdout)
        held.close()
        self.assertIn("BODY", self.run_stub("doctor").stdout)

    def test_a_leaked_marker_does_not_bypass_the_lock(self):
        held = evolution.acquire_lock(self.lock, 0)
        r = self.run_stub("doctor", CHATBOT_LOCK_PPID="1")
        held.close()
        self.assertNotIn("BODY", r.stdout)

    def test_a_broken_helper_leaves_the_host_startable(self):
        (self.code / "evolution.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
        for cmd in ("start", "repair", "doctor"):
            r = self.run_stub(cmd)
            self.assertIn("lock=none", r.stdout, cmd)
        (self.code / "evolution.py").unlink()
        self.assertIn("lock=none", self.run_stub("repair").stdout)


@dev_only_bash
class RealCtlTest(unittest.TestCase):
    """The real chatbot-ctl.sh in a throw-away tree, only where it returns before doing anything.

    Even if a regression let it run further, it cannot touch the live host: the script puts
    $HOME_DIR/.local/bin first on PATH, and there `ps`, `kill`, `setsid`, `nohup` and `curl` are
    stubs that only log (the real reap_orphan_agents scans every process on the machine)."""

    def setUp(self):
        home = tmpdir()
        self.home = home
        self.code = home / "services" / "chatbot"
        (self.code / "data").mkdir(parents=True)
        # the ctl runs evolution.py on its own, and evolution imports its core siblings (PP5: platform_compat)
        core = json.loads((CODE / "core_modules.json").read_text(encoding="utf-8"))["core"]
        for name in ["chatbot-ctl.sh", "protected_paths.json"] + [m + ".py" for m in core]:
            shutil.copy(str(CODE / name), str(self.code / name))
        stubs = home / ".local" / "bin"
        stubs.mkdir(parents=True)
        for name in ("ps", "kill", "pkill", "setsid", "nohup", "curl"):
            (stubs / name).write_text('#!/bin/sh\necho "%s $*" >> "%s"\nexit 0\n' % (name, home / "stub.log"),
                                     encoding="utf-8")
            (stubs / name).chmod(0o755)
        # CHATBOT_CALLER named here: without it the ctl asks `ps` who called it when no terminal is attached, and
        # these tests assert that the skip paths run no ps at all -- they passed or failed by how the suite was run
        self.env = dict(os.environ, HOME_DIR=str(home), AGY_CHAT_PORT="1", NAS_MCP_PORT="1", CHATBOT_CALLER="test")
        self.env.pop("CHATBOT_LOCK_PPID", None)
        # uds/F: the ctl takes its data dir from the environment first; run-tests.sh exports the repo's data/, so
        # pin the fixture tree's data/ or the ctl would lock and flag a directory outside this test
        for k in ("PE_HOME", "PRIVATEENGINE_HOME", "AGY_CHAT_DATA"):
            self.env.pop(k, None)
        self.env["CHATBOT_DATA"] = str(self.code / "data")

    def ctl(self, *args, **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run(["bash", str(self.code / "chatbot-ctl.sh")] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, env=e, timeout=20)

    def stubbed_calls(self):
        p = self.home / "stub.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def log(self):
        p = self.code / "logs" / "chatbot-doctor.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_doctor_skips_everything_while_the_maintenance_flag_exists(self):
        (self.code / "data" / "maintenance.flag").write_text("", encoding="utf-8")
        for args in (("doctor",), ("doctor", "--auto-repair")):
            r = self.ctl(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("maintenance flag present", r.stdout)
            self.assertNotIn("starting", r.stdout)
        self.assertIn("maintenance flag present", self.log())
        self.assertFalse((self.code / "logs" / "chatbot.pid").exists())
        self.assertEqual(self.stubbed_calls(), "", "the skip path must not run ps/kill/setsid/curl at all")

    def test_doctor_skips_when_another_lifecycle_operation_holds_the_lock(self):
        held = evolution.acquire_lock(self.code / "data" / "lifecycle.lock", 0)
        r = self.ctl("doctor", "--auto-repair")
        held.close()
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped", r.stdout)
        self.assertNotIn("=== chatbot doctor ===", r.stdout)
        self.assertEqual(self.stubbed_calls(), "")

    def test_repair_and_start_give_up_when_the_lock_stays_busy(self):
        held = evolution.acquire_lock(self.code / "data" / "lifecycle.lock", 0)
        for cmd in ("repair", "defibrillate", "start"):
            r = self.ctl(cmd, CHATBOT_LOCK_WAIT_SEC="0.3")
            self.assertEqual(r.returncode, evolution.BUSY_EXIT, cmd + r.stdout)
        held.close()
        self.assertFalse((self.code / "data" / "host-force.ticket").exists())
        self.assertEqual(self.stubbed_calls(), "")

    def test_the_maintenance_flag_does_not_block_a_person_pressing_the_button(self):
        # ⚡/repair is human-initiated: with the flag present it is still allowed to take the lock and run.
        # Proven safely: hold the lock so it stops at the lock, i.e. it got past everything that depends on the flag.
        (self.code / "data" / "maintenance.flag").write_text("", encoding="utf-8")
        held = evolution.acquire_lock(self.code / "data" / "lifecycle.lock", 0)
        r = self.ctl("repair", CHATBOT_LOCK_WAIT_SEC="0.3")
        held.close()
        self.assertEqual(r.returncode, evolution.BUSY_EXIT)
        self.assertNotIn("maintenance", r.stdout)

    def test_ctl_carries_the_wiring_the_tests_above_rely_on(self):
        self.assertIn('evolution.py" maintenance "$DATA/maintenance.flag"', CTL_TEXT)
        self.assertIn('evolution.py" protected-check', CTL_TEXT)
        self.assertNotRegex(CTL_TEXT, r"(?m)^\s*(exec\s+)?flock\b|\bflock\s+-")  # no bash flock command (macOS has none)


if __name__ == "__main__":
    unittest.main()
