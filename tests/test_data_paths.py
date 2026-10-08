"""The user-data directory is decided in one place (user-data-separation uds/B): host_config.DATA from DATA_ENV
(CHATBOT_DATA > PE_HOME > PRIVATEENGINE_HOME > data-pin.env > ~/.pe). Nothing else reads those variables or
builds its own data/ path -- except tickets.py (a core module, which may not import host_config) whose resolver must
give the same answer, and a short allowlist with reasons. chatbot-ctl.sh follows the same order.
Run: engine/run-tests.sh test_data_paths
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests._paths import ENGINE, REPO, code_files, rel as _rel  # noqa: E402

ROOT = REPO
ENV_NAMES = ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME")
ENV_READ = re.compile(r"environ(?:\.get\(|\[)\s*[\"'](%s)[\"']" % "|".join(ENV_NAMES))
OWN_DATA_DIR = re.compile(r"""(?:ROOT|_ROOT|CODE_DIR|SERVICES|parent)\s*/\s*["']chatbot["']\s*/\s*["']data["']|(?:ROOT|_ROOT|CODE_DIR|parent)\s*/\s*["']data["']""")
ENV_READERS = {"host_config.py", "tickets.py", "evolution.py"}   # evolution: data/ protection follows the live dir
ALLOWED_OWN_DATA = {
    "tools/st_import.py": "fallback only when characters/host_config cannot be imported",
    "tools/worktree_runner.py": "fallback only when host_config cannot be imported (dev-build runner)",
    "nas_mcp_host.py": "another site's data folder (TECH_ROOT), not ours",
    "tools/run_modules.py": "the test runner without bash: points the suite at the repo's scratch data, as run-tests.sh",
}


def modules():
    return code_files()


class DataPaths(unittest.TestCase):
    def test_only_the_resolvers_read_the_data_variables(self):
        for p in modules():
            rel = _rel(p)
            if rel in ENV_READERS:
                continue
            m = ENV_READ.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, "%s reads %s: use host_config.DATA" % (rel, m and m.group(1)))

    def test_no_module_builds_its_own_data_dir(self):
        for p in modules():
            rel = _rel(p)
            if rel in ENV_READERS or rel in ALLOWED_OWN_DATA:   # the two resolvers own the repo-data default
                continue
            m = OWN_DATA_DIR.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, "%s builds its own data path (%r): use host_config.DATA/WORKSPACE/SESSIONS" % (rel, m and m.group(0)))

    def test_only_the_resolvers_read_the_pin_file(self):
        for p in modules():
            rel = _rel(p)
            if rel in ENV_READERS:
                continue
            self.assertNotIn("data-pin.env", p.read_text(encoding="utf-8"), rel)

    def test_tickets_resolves_the_same_directory_as_host_config(self):
        probe = "import json, host_config, tickets; print(json.dumps([str(host_config.DATA), str(tickets._data_dir())]))"
        home = tempfile.mkdtemp()
        base = {k: v for k, v in os.environ.items() if k not in ENV_NAMES}
        base["HOME"] = home
        base["CHATBOT_ROOT"] = tempfile.mkdtemp()  # no pin file: the checkout pin must not hide the shipped default
        cases = [{}] + [{k: tempfile.mkdtemp()} for k in ENV_NAMES] + [{"PE_HOME": "/tmp/pe-a", "PRIVATEENGINE_HOME": "/tmp/pe-b"}]
        for extra in cases:
            r = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), env=dict(base, **extra),
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            hc, tk = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(hc, tk, "host_config and tickets disagree for %s" % extra)
            if extra:
                want = extra.get("CHATBOT_DATA") or extra.get("PE_HOME") or extra.get("PRIVATEENGINE_HOME")
                self.assertEqual(hc, str(Path(want)))   # the OS's own spelling: \\tmp\\pe-a on Windows (#403)
            else:
                self.assertEqual(hc, str(Path(home) / ".pe"))
        pinned_root = Path(tempfile.mkdtemp())
        pinned_data = tempfile.mkdtemp()
        (pinned_root / "data-pin.env").write_text("CHATBOT_DATA=%s\n" % pinned_data, encoding="utf-8")
        env = dict(base)
        env["CHATBOT_ROOT"] = str(pinned_root)
        r = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        hc, tk = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(hc, tk)
        self.assertEqual(hc, str(Path(pinned_data)))
        env["CHATBOT_DATA"] = "/tmp/explicit-over-pin"
        r = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        hc, tk = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((hc, tk), ("/tmp/explicit-over-pin", "/tmp/explicit-over-pin"))
        (pinned_root / "data-pin.env").write_text('CHATBOT_DATA="${CODE}/data"\n', encoding="utf-8")
        env.pop("CHATBOT_DATA")
        r = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        hc, tk = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(hc, str(Path(home) / ".pe"), "a $ pin must not be taken literally")

    def test_evolution_reads_the_same_variables_in_the_same_order(self):
        import evolution
        import host_config
        self.assertEqual(evolution._DATA_ENV, host_config.DATA_ENV)

    def test_ctl_follows_the_same_order(self):
        ctl = (ENGINE / "chatbot-ctl.sh").read_text(encoding="utf-8")
        start = ctl.index("# DATA_RESOLVE_START\n") + len("# DATA_RESOLVE_START\n")
        body = ctl[start:ctl.index("# DATA_RESOLVE_END")]
        self.assertIn("${HOME:-$HOME_DIR}/.pe", body)
        self.assertNotIn(":-$CODE/data", body)
        self.assertIn('"$CODE/data-pin.env"', body)
        runner = (ENGINE / "run-tests.sh").read_text(encoding="utf-8")
        self.assertIn('export CHATBOT_DATA="$ENGINE_DIR/data"', runner)
        self.assertNotIn('if [ -z "${CHATBOT_DATA', runner, "the suite ignores a caller's data dir: never an install's")
        self.assertIn("unset PE_HOME PRIVATEENGINE_HOME", runner)

        def resolve(code, home, extra=None, pin=None):
            if pin is not None:
                Path(code, "data-pin.env").write_text(pin, encoding="utf-8")
            env = {"HOME": home, "PATH": "/usr/bin:/bin"}
            if extra:
                env.update(extra)
            script = "CODE=$1; HOME=$2; HOME_DIR=$HOME\n" + body + "\nprintf %s \"$DATA\""
            r = subprocess.run(["bash", "-c", script, "bash", code, home], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

        home = tempfile.mkdtemp()
        self.assertEqual(resolve(tempfile.mkdtemp(), home), str(Path(home) / ".pe"))
        code = tempfile.mkdtemp()
        pinned = str(Path(code) / "kept")
        self.assertEqual(resolve(code, home, pin="CHATBOT_DATA=%s\n" % pinned), pinned)
        self.assertEqual(resolve(code, home, extra={"CHATBOT_DATA": "/tmp/explicit"}), "/tmp/explicit")
        self.assertEqual(resolve(code, home, extra={"PE_HOME": "/tmp/pe-alias", "PRIVATEENGINE_HOME": "/tmp/other"}),
                         "/tmp/pe-alias")

if __name__ == "__main__":
    unittest.main()
