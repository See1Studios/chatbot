"""PROVIDER_NEUTRAL_v1, recurrence guard: agy is one provider among several. Common code names no
provider in its classes, functions, variables or protocol; provider knowledge lives in the
provider modules (adapters.py, accounts.py, account_login.py) and in configuration (host_config.py,
ctl_proc.py's process classifier). Provider features are asked for by capability (adapter hooks).
Run: python3 -m unittest tests.test_provider_neutrality  (from services/chatbot)
"""
import ast
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import adapters  # noqa: E402

# ADAPTER_SPLIT_v1: one module per provider may name it; adapter_base.py is common code and stays neutral
PROVIDER_MODULES = {"adapters.py", "adapter_agy.py", "adapter_claude.py", "adapter_grok.py", "adapter_codex.py",
                    "adapter_openai.py", "accounts.py", "account_login.py", "host_config.py", "ctl_proc.py"}
# every registered provider id, plus the vendor/CLI names behind them
PROVIDERS = sorted(set(adapters.AGENT_ADAPTERS) | {"agy", "claude", "grok", "codex", "gemini", "antigravity"})
NAME_RE = re.compile("|".join(re.escape(p) for p in PROVIDERS), re.I)


def identifiers(tree):
    for n in ast.walk(tree):
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n.name, n.lineno
        elif isinstance(n, ast.Name):
            yield n.id, n.lineno
        elif isinstance(n, ast.Attribute):
            yield n.attr, n.lineno
        elif isinstance(n, ast.arg):
            yield n.arg, n.lineno
        elif isinstance(n, ast.alias):
            yield (n.asname or n.name), getattr(n, "lineno", 0)


class CommonCodeTest(unittest.TestCase):
    def test_common_python_names_no_provider(self):
        bad = []
        for f in sorted(ROOT.glob("*.py")):
            if f.name in PROVIDER_MODULES:
                continue
            for name, line in identifiers(ast.parse(f.read_text(encoding="utf-8"))):
                if NAME_RE.search(name):
                    bad.append("%s:%d %s" % (f.name, line, name))
        self.assertEqual(sorted(set(bad)), [], "provider name in common code; use an adapter capability")

    def test_ui_code_names_no_provider(self):
        bad = []
        for f in sorted((ROOT / "static").glob("*.js")):
            text = f.read_text(encoding="utf-8")
            keep_lines = lambda m: "\n" * m.group(0).count("\n")   # so reported line numbers stay real
            text = re.sub(r"/\*.*?\*/", keep_lines, text, flags=re.S)
            text = re.sub(r"(^|[^:])//.*$", r"\1", text, flags=re.M)
            text = re.sub(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"", "''", text)   # string literals
            text = re.sub(r"`(?:\\.|[^`\\])*`", keep_lines, text)
            for no, line in enumerate(text.splitlines(), 1):
                for tok in re.findall(r"[A-Za-z_$][\w$]*", line):
                    if NAME_RE.search(tok):
                        bad.append("static/%s:%d %s" % (f.name, no, tok))
        self.assertEqual(bad, [], "provider name in a UI identifier")

    def test_no_event_is_named_after_a_provider(self):
        src = "\n".join(p.read_text(encoding="utf-8") for p in sorted(ROOT.glob("adapter*.py")))
        for pid in PROVIDERS:
            self.assertNotIn('"event": "%s"' % pid, src)

    def test_capabilities_not_ids_decide(self):
        base = adapters.AgentAdapter
        for hook in ("oneshot", "native_compact", "has_conversation", "available"):
            self.assertTrue(callable(getattr(base, hook, None)), hook)
        self.assertFalse(base.supports_steer)
        self.assertIsNone(base.oneshot(adapters.AgentAdapter(), "x"))   # not supported unless a provider says so
        for f in ("session.py", "server.py", "standby_pool.py", "media_handler.py"):
            src = (ROOT / f).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\.id\s*[!=]=\s*[\"'](%s)[\"']" % "|".join(PROVIDERS), src), f)
            self.assertIsNone(re.search(r"provider\s*[!=]=\s*[\"'](%s)[\"']" % "|".join(PROVIDERS), src), f)


class ConfigTest(unittest.TestCase):
    def host_config(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("CHATBOT_", "AGY_CHAT_"))}
        clean.update(env)
        out = subprocess.check_output([sys.executable, "-c", "import host_config as h; print(h.PORT, h.ROOT)"],
                                      cwd=str(ROOT), env=clean).decode().split()
        return out

    def test_service_settings_are_chatbot_named_and_old_names_still_work(self):
        self.assertEqual(self.host_config(CHATBOT_PORT="4011")[0], "4011")
        self.assertEqual(self.host_config(AGY_CHAT_PORT="4012")[0], "4012")          # legacy
        self.assertEqual(self.host_config(CHATBOT_PORT="4013", AGY_CHAT_PORT="1")[0], "4013")

    def test_ctl_exports_the_service_names(self):
        ctl = (ROOT / "chatbot-ctl.sh").read_text(encoding="utf-8")
        self.assertIn("export CHATBOT_HOST=0.0.0.0", ctl)
        self.assertNotIn("export AGY_CHAT_", ctl)
        self.assertIn("reap_orphan_agents", ctl)


class HealthTest(unittest.TestCase):
    def test_health_reports_every_provider_none_singled_out(self):
        import server
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with urlopen("http://127.0.0.1:%d/healthz" % httpd.server_address[1], timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(set(d["providers"]), set(adapters.AGENT_ADAPTERS))
        self.assertFalse(set(d) & set(PROVIDERS), "a provider as a top-level health field")


if __name__ == "__main__":
    unittest.main()
