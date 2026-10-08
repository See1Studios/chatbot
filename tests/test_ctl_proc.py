"""WATCHDOG_OS_FACTS_v1: ctl_proc.py decides from OS facts only (process table, /proc cwd, ctl's pid file).
Pure-function tests on fake tables; nothing is killed or sampled for real.
Run: engine/run-tests.sh test_ctl_proc
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import ctl_proc  # noqa: E402
from telemetry import obslog  # noqa: E402

AGY = "/h/.local/bin/agy --input-format stream-json --output-format stream-json --model gemini-3.8-flash-low"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.code = os.path.realpath(self.tmp.name)
        self.ws = os.path.join(self.code, "data", "workspace")
        os.makedirs(os.path.join(self.code, "logs"))
        self.pidfile(100)
        self._state = dict(obslog._state)

    def tearDown(self):
        obslog._state.clear()
        obslog._state.update(self._state)
        self.tmp.cleanup()

    def pidfile(self, pid):
        with open(os.path.join(self.code, "logs", "chatbot.pid"), "w") as f:
            f.write(str(pid))

    def p(self, pid, ppid, args, cwd=None, age=300):
        return {"pid": pid, "ppid": ppid, "age": age, "args": args, "cwd": self.ws if cwd is None else cwd}

    def table(self):
        return [
            self.p(100, 1, "python3 /x/services/chatbot/server.py", cwd=self.code),
            self.p(200, 100, AGY + " --conversation standby"),                  # standby / session: owned
            self.p(300, 1, AGY + " --conversation old"),                         # orphan of a dead server
            self.p(310, 777, AGY + " --conversation old2"),                      # reparented to a subreaper
            self.p(400, 100, "/h/.local/bin/codex exec --json x"),               # codex wrapper...
            self.p(401, 400, "/h/node_modules/@openai/codex/bin/codex exec --json x"),  # ...and native child
            self.p(500, 999, AGY + " --conversation term", cwd="/home/someone"), # a person's own agy
            self.p(600, 1, "/h/.local/bin/agy", cwd=self.code),                  # interactive agy in the repo dir
            self.p(777, 1, "systemd --user", cwd="/"),
            self.p(999, 1, "bash", cwd="/home/someone"),
        ]


class ReapTest(Base):
    def reap(self, table):
        killed = []
        ctl_proc.reap(self.code, table=table, kill=lambda pid, sig: killed.append(pid))
        return sorted(killed)

    def test_only_our_orphans_are_reaped(self):
        self.assertEqual(self.reap(self.table()), [300, 310])

    def test_a_stale_pid_file_protects_nothing_of_ours_and_still_spares_others(self):
        self.pidfile(999)   # not a server.py: not trusted
        self.assertEqual(self.reap(self.table()), [200, 300, 310, 400, 401])

    def test_no_service_files_are_read(self):
        # the old reaper read sessions/*/meta.json, live_pids.json and standby.pid; none exist here
        for name in ("sessions", "live_pids.json", "standby.pid"):
            self.assertFalse(os.path.exists(os.path.join(self.code, "data", name)))
        self.assertEqual(self.reap(self.table()), [300, 310])

    def test_agents_in_a_data_dir_outside_the_code_are_ours(self):
        # uds/F: the live data dir is ~/.pe, not CODE/data. Agents there must count, or busy waits for nothing
        data = os.path.join(self.code, "elsewhere", ".pe")
        moved = [dict(r, cwd=os.path.join(data, "workspace")) if r["cwd"] == self.ws else r for r in self.table()]
        killed = []
        ctl_proc.reap(self.code, table=moved, kill=lambda pid, sig: killed.append(pid), data_dir=data)
        self.assertEqual(sorted(killed), [300, 310])
        self.assertEqual(self.reap(moved), [])   # without the data dir they are invisible


class BusyTest(Base):
    def busy(self, table, activity_seq):
        seq = iter(activity_seq)
        return ctl_proc.busy(self.code, table_fn=lambda: table, activity=lambda pid: next(seq)[pid],
                             sleep=lambda s: None)

    def owned_only(self):
        return [r for r in self.table() if r["pid"] in (100, 200)]

    def test_quiet_agents_are_idle_after_three_windows(self):
        still = {200: (188, 7253611)}
        self.assertFalse(self.busy(self.owned_only(), [still] * 6))

    def test_calibrated_work_is_busy(self):
        before, after = {200: (221, 25131235)}, {200: (227, 25237781)}   # a real 2 s sample of a working agy
        self.assertTrue(self.busy(self.owned_only(), [before, after]))

    def test_quiet_then_active_is_busy(self):
        q = {200: (10, 1000)}
        self.assertTrue(self.busy(self.owned_only(), [q, q, q, {200: (10, 9000)}]))

    def test_a_oneshot_turn_process_is_busy(self):
        self.assertTrue(self.busy(self.table(), []))   # codex under the server

    def test_no_server_means_nothing_to_wait_for(self):
        self.pidfile(12345)
        self.assertFalse(self.busy(self.table(), []))


class CtlWiringTest(unittest.TestCase):
    def test_ctl_uses_os_facts_only(self):
        ctl = (ENGINE / "chatbot-ctl.sh").read_text(encoding="utf-8")
        for dep in ("live_pids", "standby.pid", "/api/sessions/active", "kill_stale_session_agy"):
            self.assertNotIn(dep, ctl)
        self.assertIn('ctl_proc.py" reap "$CODE" "$DATA"', ctl)   # $DATA: agents run in $DATA/workspace (uds/F)
        self.assertIn('ctl_proc.py" busy "$CODE" "$DATA"', ctl)

    def test_ctl_proc_imports_nothing_from_the_service(self):
        import ast
        tree = ast.parse((ENGINE / "ctl_proc.py").read_text(encoding="utf-8"))
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        service = {p.stem for p in ENGINE.glob("*.py")} - {"ctl_proc", "obslog"}
        self.assertEqual(mods & service, set())


if __name__ == "__main__":
    unittest.main()
