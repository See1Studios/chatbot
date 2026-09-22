"""Host lifecycle safeguards (docs/plans/recursive-self-evolution.md §3 0-6 and decision 4):
shared lifecycle lock, maintenance flag, protected-file hash manifest, and how chatbot-ctl.sh calls them.

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
        r = self.helper(0, "sh", "-c", "echo $PPID:$CHATBOT_LOCK_PPID; exit 3")
        self.assertEqual(r.returncode, 3)
        ppid, marker = r.stdout.strip().split(":")
        self.assertEqual(ppid, marker)

    def test_a_process_the_child_leaves_running_does_not_keep_the_lock(self):
        # the host server is started by ctl and outlives it: it must not inherit the lock
        r = self.helper(0, "sh", "-c", "sleep 3 >/dev/null 2>&1 & echo started")
        self.assertEqual(r.returncode, 0)
        evolution.acquire_lock(self.lock, 0).close()

    def test_busy_doctor_style_run_skips_without_running(self):
        held = evolution.acquire_lock(self.lock, 0)
        r = self.helper(0, "sh", "-c", "echo BODY")
        held.close()
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped", r.stdout)
        self.assertNotIn("BODY", r.stdout)

    def test_busy_start_style_run_waits_then_exits_75_without_running(self):
        held = evolution.acquire_lock(self.lock, 0)
        r = self.helper(0.3, "sh", "-c", "echo BODY")
        held.close()
        self.assertEqual(r.returncode, evolution.BUSY_EXIT)
        self.assertNotIn("BODY", r.stdout)

    def test_unusable_lock_file_still_runs_the_command(self):
        bad = tmpdir() / "no" / "such" / "dir" / "x.lock"
        r = subprocess.run([PY, str(CODE / "evolution.py"), "run-locked", str(bad), "0", "--", "sh", "-c", "echo BODY"],
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


class ManifestTest(unittest.TestCase):
    def test_covers_protected_files_only_minus_exceptions_and_volatile(self):
        root = make_root()
        self.assertEqual(evolution.protected_files(root), ["data/secret.md", "server.py", "tests/t.py"])

    def test_no_manifest_yet_is_information_not_a_warning(self):
        root = make_root()
        self.assertEqual(evolution.check_manifest(root)[0], "none")
        self.assertNotIn("WARN", evolution.manifest_report(root))

    def test_unchanged_files_report_ok(self):
        root = make_root()
        self.assertEqual(evolution.write_manifest(root), 3)
        self.assertEqual(evolution.check_manifest(root), ("ok", {"modified": [], "missing": [], "new": []}))
        self.assertEqual(evolution.manifest_report(root), "manifest OK")

    def test_volatile_and_excepted_changes_are_ignored(self):
        root = make_root()
        evolution.write_manifest(root)
        (root / "data" / "state.txt").write_text("different", encoding="utf-8")
        (root / "static" / "app.js").write_text("2", encoding="utf-8")
        (root / "notes.md").write_text("edited", encoding="utf-8")
        self.assertEqual(evolution.check_manifest(root)[0], "ok")

    def test_modified_missing_and_new_files_are_reported(self):
        root = make_root()
        evolution.write_manifest(root)
        (root / "server.py").write_text("print('b')\n", encoding="utf-8")
        (root / "data" / "secret.md").unlink()
        (root / "brand_new.py").write_text("y", encoding="utf-8")
        status, diffs = evolution.check_manifest(root)
        self.assertEqual(status, "differs")
        self.assertEqual(diffs, {"modified": ["server.py"], "missing": ["data/secret.md"], "new": ["brand_new.py"]})
        report = evolution.manifest_report(root)
        self.assertTrue(report.startswith("WARN "))
        for word in ("server.py", "data/secret.md", "brand_new.py", "warning only"):
            self.assertIn(word, report)

    def test_a_broken_manifest_warns_and_never_raises(self):
        root = make_root()
        for text in ("{not json", "[]", '{"sha256": []}', "{}"):
            (root / evolution.MANIFEST_NAME).write_text(text, encoding="utf-8")
            self.assertEqual(evolution.check_manifest(root)[0], "unreadable", text)
            self.assertTrue(evolution.manifest_report(root).startswith("WARN "))

    def test_a_broken_registry_warns_and_never_raises(self):
        root = make_root()
        evolution.write_manifest(root)
        (root / evolution.REGISTRY_NAME).write_text("{nope", encoding="utf-8")
        self.assertTrue(evolution.manifest_report(root).startswith("WARN "))

    def test_long_lists_are_shortened(self):
        root = make_root()
        evolution.write_manifest(root)
        for i in range(20):
            (root / ("m%02d.py" % i)).write_text("x", encoding="utf-8")
        self.assertIn("(+12 more)", evolution.manifest_report(root))

    def test_shipped_registry_hashes_code_and_skips_caches_and_state(self):
        files = evolution.protected_files(CODE)
        self.assertIn("server.py", files)
        self.assertIn("chatbot-ctl.sh", files)
        self.assertIn("protected_paths.json", files)
        self.assertFalse([f for f in files if "__pycache__" in f or f.endswith(".pyc")])
        self.assertFalse([f for f in files if f.startswith("static/")])
        for state in ("data/host-force.ticket", "data/lifecycle.lock", "data/maintenance.flag", evolution.MANIFEST_NAME):
            self.assertNotIn(state, files)

    def test_cli_check_never_fails_and_update_writes_the_manifest(self):
        out = subprocess.run([PY, str(CODE / "evolution.py"), "manifest-check"], stdout=subprocess.PIPE,
                             universal_newlines=True)
        self.assertEqual(out.returncode, 0)  # even when files differ
        self.assertTrue(out.stdout.strip())


CTL_TEXT = (CODE / "chatbot-ctl.sh").read_text(encoding="utf-8")
WRAPPER = re.search(r"(case \"\$\{1:-status\}\" in\n  start\|doctor.*?\nesac\n)", CTL_TEXT, re.S)


class WrapperTest(unittest.TestCase):
    """The real wrapper text from chatbot-ctl.sh, run around a body that only echoes."""

    def setUp(self):
        self.assertIsNotNone(WRAPPER, "lock wrapper not found in chatbot-ctl.sh")
        self.tree = tmpdir()
        self.code = self.tree / "code"
        self.data = self.tree / "data"
        self.code.mkdir()
        self.data.mkdir()
        shutil.copy(str(CODE / "evolution.py"), str(self.code / "evolution.py"))
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


class RealCtlTest(unittest.TestCase):
    """The real chatbot-ctl.sh in a throw-away tree, only where it returns before doing anything.

    Even if a regression let it run further, it cannot touch the live host: the script puts
    $HOME_DIR/.local/bin first on PATH, and there `ps`, `kill`, `setsid`, `nohup` and `curl` are
    stubs that only log (the real kill_orphan_agy scans every process on the machine)."""

    def setUp(self):
        home = tmpdir()
        self.home = home
        self.code = home / "services" / "chatbot"
        (self.code / "data").mkdir(parents=True)
        for name in ("chatbot-ctl.sh", "evolution.py", "protected_paths.json"):
            shutil.copy(str(CODE / name), str(self.code / name))
        stubs = home / ".local" / "bin"
        stubs.mkdir(parents=True)
        for name in ("ps", "kill", "pkill", "setsid", "nohup", "curl"):
            (stubs / name).write_text('#!/bin/sh\necho "%s $*" >> "%s"\nexit 0\n' % (name, home / "stub.log"),
                                     encoding="utf-8")
            (stubs / name).chmod(0o755)
        self.env = dict(os.environ, HOME_DIR=str(home), AGY_CHAT_PORT="1", NAS_MCP_PORT="1")
        self.env.pop("CHATBOT_LOCK_PPID", None)

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
        self.assertIn('evolution.py" manifest-check', CTL_TEXT)
        self.assertNotRegex(CTL_TEXT, r"(?m)^\s*(exec\s+)?flock\b|\bflock\s+-")  # no bash flock command (macOS has none)


if __name__ == "__main__":
    unittest.main()
