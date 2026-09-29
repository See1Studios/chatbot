"""The user-data directory is decided in one place (user-data-separation uds/B): host_config.DATA from DATA_ENV
(CHATBOT_DATA > PE_HOME > PRIVATEENGINE_HOME > AGY_CHAT_DATA > repo data/). Nothing else reads those variables or
builds its own data/ path -- except tickets.py (a core module, which may not import host_config) whose resolver must
give the same answer, and a short allowlist with reasons. chatbot-ctl.sh follows the same order.
Run: python3 -m unittest tests.test_data_paths  (from services/chatbot)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_NAMES = ("CHATBOT_DATA", "PE_HOME", "PRIVATEENGINE_HOME", "AGY_CHAT_DATA")
ENV_READ = re.compile(r"environ(?:\.get\(|\[)\s*[\"'](%s)[\"']" % "|".join(ENV_NAMES))
OWN_DATA_DIR = re.compile(r"""(?:ROOT|_ROOT|CODE_DIR|SERVICES|parent)\s*/\s*["']chatbot["']\s*/\s*["']data["']|(?:ROOT|_ROOT|CODE_DIR|parent)\s*/\s*["']data["']""")
ENV_READERS = {"host_config.py", "tickets.py"}
ALLOWED_OWN_DATA = {
    "tools/st_import.py": "fallback only when characters/host_config cannot be imported",
    "tools/worktree_runner.py": "fallback only when host_config cannot be imported (dev-build runner)",
    "nas_mcp_host.py": "another site's data folder (TECH_ROOT), not ours",
}


def modules():
    return sorted(list(ROOT.glob("*.py")) + list(ROOT.glob("providers/*.py")) + list(ROOT.glob("tools/*.py")))


class DataPaths(unittest.TestCase):
    def test_only_the_resolvers_read_the_data_variables(self):
        for p in modules():
            rel = p.relative_to(ROOT).as_posix()
            if rel in ENV_READERS:
                continue
            m = ENV_READ.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, "%s reads %s: use host_config.DATA" % (rel, m and m.group(1)))

    def test_no_module_builds_its_own_data_dir(self):
        for p in modules():
            rel = p.relative_to(ROOT).as_posix()
            if rel in ENV_READERS or rel in ALLOWED_OWN_DATA:   # the two resolvers own the repo-data default
                continue
            m = OWN_DATA_DIR.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, "%s builds its own data path (%r): use host_config.DATA/WORKSPACE/SESSIONS" % (rel, m and m.group(0)))

    def test_tickets_resolves_the_same_directory_as_host_config(self):
        probe = "import json, host_config, tickets; print(json.dumps([str(host_config.DATA), str(tickets._data_dir())]))"
        base = {k: v for k, v in os.environ.items() if k not in ENV_NAMES}
        cases = [{}] + [{k: tempfile.mkdtemp()} for k in ENV_NAMES] + [{"PE_HOME": "/tmp/pe-a", "AGY_CHAT_DATA": "/tmp/pe-b"}]
        for extra in cases:
            r = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), env=dict(base, **extra),
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            hc, tk = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(hc, tk, "host_config and tickets disagree for %s" % extra)
            if extra:
                want = (extra.get("CHATBOT_DATA") or extra.get("PE_HOME") or extra.get("PRIVATEENGINE_HOME")
                        or extra.get("AGY_CHAT_DATA"))
                self.assertEqual(hc, str(Path(want)))   # the OS's own spelling: \\tmp\\pe-a on Windows (#403)

    def test_ctl_follows_the_same_order(self):
        ctl = (ROOT / "chatbot-ctl.sh").read_text(encoding="utf-8")
        self.assertIn('DATA="${CHATBOT_DATA:-${PE_HOME:-${PRIVATEENGINE_HOME:-${AGY_CHAT_DATA:-$CODE/data}}}}"', ctl)


if __name__ == "__main__":
    unittest.main()
