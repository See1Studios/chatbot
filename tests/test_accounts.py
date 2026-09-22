"""accounts.snapshot(): the 2026-09-19 incident replayed with fake procs + logs,
plus the change-observation rule used for providers with no per-process account.
Run: python3 -m unittest tests.test_accounts  (from services/chatbot)
"""
import base64
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import accounts  # noqa: E402

OLD, NEW = "old@example.com", "new@example.com"


def _jwt(email: str, **extra) -> str:
    seg = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")  # noqa: E731
    return f"{seg({'alg': 'none'})}.{seg({'email': email, 'iat': 1, 'exp': 2, **extra})}.x"


def _write_log(d: Path, started: float, pid: int, email: str) -> None:
    name = time.strftime("cli-%Y%m%d_%H%M%S.log", time.localtime(started))
    (d / name).write_text(
        f"I0919 00:00:00.000000      50 server.go:1568] Starting language server process with pid {pid}\n"
        f"I0919 00:00:01.000000       1 server_oauth.go:201] OAuth: authenticated successfully as {email}\n"
    )


class Base(unittest.TestCase):
    PATCHED = ("AGY_LOG_DIR", "AGY_TOKEN", "CODEX_AUTH", "GROK_AUTH", "STATE_FILE",
               "_scan_procs", "_tty", "_comm", "claude_account")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig = {k: getattr(accounts, k) for k in self.PATCHED}
        self.orig_fn = dict(accounts._ACCOUNT_FN)
        accounts.AGY_LOG_DIR = self.tmp
        accounts.AGY_TOKEN = self.tmp / "agy-token"
        accounts.CODEX_AUTH = self.tmp / "codex.json"
        accounts.GROK_AUTH = self.tmp / "grok.json"
        accounts.STATE_FILE = self.tmp / "state.json"
        accounts._tty = lambda pid: "pts/2"
        accounts._comm = lambda pid: "sh"
        accounts.claude_account = lambda: {"ok": True, "email": NEW, "plan": "pro", "source": "claude auth status"}
        accounts._ACCOUNT_FN["claude"] = accounts.claude_account
        accounts._ACCOUNT_FN["agy"] = accounts.agy_account
        accounts.AGY_TOKEN.write_text(json.dumps({"id_token": _jwt(NEW), "auth_method": "consumer"}))
        accounts._log_account_cache.clear()
        self.now = time.time()
        self.procs = {p: [] for p in accounts.PROVIDERS}
        accounts._scan_procs = lambda: {k: [dict(x) for x in v] for k, v in self.procs.items()}

    def tearDown(self):
        for k, v in self.orig.items():
            setattr(accounts, k, v)
        accounts._ACCOUNT_FN.clear()
        accounts._ACCOUNT_FN.update(self.orig_fn)

    def add_proc(self, prov, pid, age_sec, ppid=1, log_email=None):
        started = self.now - age_sec
        self.procs[prov].append({"pid": pid, "ppid": ppid, "started_at": started, "cmd": prov})
        if log_email:
            _write_log(self.tmp, started, pid, log_email)


class AgyTest(Base):
    def test_old_process_is_stale_and_new_is_not(self):
        self.add_proc("agy", 14804, 2.7 * 86400, log_email=OLD)
        self.add_proc("agy", 26662, 400, log_email=NEW)
        snap = accounts.snapshot()
        agy = snap["providers"]["agy"]
        by_pid = {p["pid"]: p for p in agy["processes"]}
        self.assertEqual(agy["current"]["email"], NEW)
        self.assertEqual(by_pid[14804]["account"], OLD)
        self.assertTrue(by_pid[14804]["stale"])
        self.assertFalse(by_pid[26662]["stale"])
        self.assertEqual(snap["stale_count"], 1)

    def test_owner_classification_and_kill_hint(self):
        self.add_proc("agy", 100, 500, log_email=OLD)
        self.add_proc("agy", 200, 560, log_email=OLD)
        snap = accounts.snapshot({100: {"owner": "session", "sid": "s1", "busy": True}})
        by_pid = {p["pid"]: p for p in snap["providers"]["agy"]["processes"]}
        self.assertEqual(by_pid[100]["owner"], "session")
        self.assertEqual(by_pid[100]["sid"], "s1")
        self.assertNotIn("kill_cmd", by_pid[100])  # owned: recycled by the server, never a copied kill
        self.assertEqual(by_pid[200]["owner"], "external")
        self.assertEqual(by_pid[200]["kill_cmd"], "kill 200")

    def test_log_matched_by_pid_not_by_nearest_time(self):
        self.add_proc("agy", 300, 100, log_email=OLD)
        started = self.now - 100
        self.procs["agy"].append({"pid": 301, "ppid": 1, "started_at": started, "cmd": "agy"})
        (self.tmp / time.strftime("cli-%Y%m%d_%H%M%S.log", time.localtime(started + 2))).write_text(
            "Starting language server process with pid 301\nauthenticated successfully as " + NEW + "\n")
        by_pid = {p["pid"]: p for p in accounts.snapshot()["providers"]["agy"]["processes"]}
        self.assertEqual(by_pid[300]["account"], OLD)
        self.assertEqual(by_pid[301]["account"], NEW)

    def test_no_log_means_unknown_not_stale(self):
        self.add_proc("agy", 400, 5)
        p = accounts.snapshot()["providers"]["agy"]["processes"][0]
        self.assertIsNone(p["account"])
        self.assertFalse(p["stale"])

    def test_token_values_never_leak(self):
        accounts.AGY_TOKEN.write_text(json.dumps({
            "id_token": _jwt(NEW), "token": {"access_token": "SECRET-A", "refresh_token": "SECRET-R"}}))
        self.assertNotIn("SECRET", json.dumps(accounts.snapshot()))

    def test_missing_token_file(self):
        accounts.AGY_TOKEN.unlink()
        snap = accounts.snapshot()
        self.assertFalse(snap["providers"]["agy"]["current"]["ok"])
        self.assertEqual(snap["stale_count"], 0)


class TtyTest(unittest.TestCase):
    def test_only_real_terminals_are_named(self):
        import os
        real = os.readlink
        try:
            for target, want in (("/dev/pts/3", "pts/3"), ("/dev/tty1", "tty1"),
                                 ("/dev/null", "-"), ("pipe:[123]", "-"), ("socket:[9]", "-")):
                os.readlink = lambda p, t=target: t
                self.assertEqual(accounts._tty(1), want, target)
        finally:
            os.readlink = real


class OtherProvidersTest(Base):
    def test_codex_email_and_plan_from_id_token(self):
        accounts.CODEX_AUTH.write_text(json.dumps({"tokens": {
            "id_token": _jwt("c@example.com", **{"https://api.openai.com/auth": {"chatgpt_plan_type": "free"}}),
            "access_token": "SECRET-A", "refresh_token": "SECRET-R"}}))
        a = accounts.codex_account()
        self.assertEqual((a["email"], a["plan"]), ("c@example.com", "free"))
        self.assertNotIn("SECRET", json.dumps(a))

    def test_grok_picks_newest_entry_email(self):
        accounts.GROK_AUTH.write_text(json.dumps({
            "a": {"email": "older@example.com", "key": "SECRET-1", "expires_at": "2026-01-01T00:00:00Z"},
            "b": {"email": "newer@example.com", "key": "SECRET-2", "expires_at": "2026-09-01T00:00:00Z"},
            "c": {"key": "no-email-entry", "expires_at": "2027-01-01T00:00:00Z"},
        }))
        a = accounts.grok_account()
        self.assertEqual(a["email"], "newer@example.com")
        self.assertNotIn("SECRET", json.dumps(a))

    def test_logged_out_files_report_error_not_crash(self):
        self.assertFalse(accounts.codex_account()["ok"])
        self.assertFalse(accounts.grok_account()["ok"])

    def test_no_account_evidence_for_non_agy_processes(self):
        self.add_proc("claude", 500, 3600)
        snap = accounts.snapshot()
        cl = snap["providers"]["claude"]
        self.assertEqual(cl["account_evidence"], "none")
        self.assertIsNone(cl["processes"][0]["account"])
        self.assertFalse(cl["processes"][0]["stale"])
        self.assertEqual(snap["stale_count"], 0)  # only agy log evidence counts as stale

    def test_predates_change_only_when_certainly_before_the_change(self):
        # claude seen as OLD at now-1000, first seen as NEW at now-900
        accounts.claude_account = lambda: {"ok": True, "email": OLD}
        accounts._ACCOUNT_FN["claude"] = accounts.claude_account
        accounts.observe("claude", accounts.claude_account(), self.now - 1000)
        accounts.claude_account = lambda: {"ok": True, "email": NEW}
        accounts._ACCOUNT_FN["claude"] = accounts.claude_account
        accounts.observe("claude", accounts.claude_account(), self.now - 900)

        self.add_proc("claude", 1, 5000)   # started long before the last old sighting
        self.add_proc("claude", 2, 950)    # inside the ambiguous window -> must NOT be flagged
        self.add_proc("claude", 3, 100)    # started after the change
        by_pid = {p["pid"]: p for p in accounts.snapshot()["providers"]["claude"]["processes"]}
        self.assertTrue(by_pid[1]["predates_change"])
        self.assertFalse(by_pid[2]["predates_change"])
        self.assertFalse(by_pid[3]["predates_change"])

    def test_no_prior_observation_flags_nothing(self):
        self.add_proc("codex", 9, 99999)
        p = accounts.snapshot()["providers"]["codex"]["processes"][0]
        self.assertFalse(p["predates_change"])

    def test_same_account_repeated_never_creates_a_window(self):
        for t in (100, 50, 10):
            accounts.observe("claude", {"ok": True, "email": NEW}, self.now - t)
        self.assertIsNone(accounts.observe("claude", {"ok": True, "email": NEW}, self.now))


class HelpersTest(Base):
    def test_stale_owned_is_agy_owned_and_proven_only(self):
        # distinct ages: agy logs are named by start SECOND, same-second ones would overwrite
        self.add_proc("agy", 1, 500, log_email=OLD)   # owned session, stale        -> yes
        self.add_proc("agy", 2, 520, log_email=OLD)   # owned standby, stale        -> yes
        self.add_proc("agy", 3, 540, log_email=NEW)   # owned, current account      -> no
        self.add_proc("agy", 4, 560, log_email=OLD)   # EXTERNAL, stale             -> no
        self.add_proc("agy", 5, 580)                  # owned, no log evidence      -> no
        self.add_proc("claude", 6, 99999)             # never: no per-process evidence
        owned = {1: {"owner": "session", "sid": "a"}, 2: {"owner": "standby"},
                 3: {"owner": "session", "sid": "c"}, 5: {"owner": "session", "sid": "e"},
                 6: {"owner": "session", "sid": "f"}}
        self.assertEqual(accounts.stale_owned(accounts.snapshot(owned)), {1, 2})

    def test_snapshot_can_be_limited_to_agy_without_touching_claude(self):
        calls = []
        accounts._ACCOUNT_FN["claude"] = lambda: calls.append(1) or {"ok": True, "email": NEW}
        snap = accounts.snapshot(providers=("agy",))
        self.assertEqual(list(snap["providers"]), ["agy"])
        self.assertEqual(calls, [])

    def test_current_email_unknown_is_none_never_a_change(self):
        self.assertEqual(accounts.current_email("agy"), NEW)
        self.assertIsNone(accounts.current_email("omniroute"))   # no account concept
        accounts.AGY_TOKEN.unlink()
        self.assertIsNone(accounts.current_email("agy"))         # logged out

    def test_snapshot_reports_last_switch(self):
        accounts.observe("agy", {"ok": True, "email": OLD}, self.now - 500)
        accounts.observe("agy", {"ok": True, "email": NEW}, self.now - 400)
        agy = accounts.snapshot()["providers"]["agy"]
        self.assertEqual(agy["changed_from"], OLD)
        self.assertAlmostEqual(agy["changed_at"], self.now - 400, delta=1)

class ParseProvidersTest(unittest.TestCase):
    def test_query_to_provider_set(self):
        self.assertEqual(accounts.parse_providers(None), accounts.PROVIDERS)
        self.assertEqual(accounts.parse_providers(""), accounts.PROVIDERS)
        self.assertEqual(accounts.parse_providers("claude"), ("claude",))
        self.assertEqual(accounts.parse_providers("omniroute"), ())   # API key, no login
        self.assertEqual(accounts.parse_providers("openrouter"), ())  # API key, no login
        self.assertEqual(accounts.parse_providers("../etc"), ())      # never passed on to anything

    def test_empty_provider_set_snapshots_nothing_and_stays_valid(self):
        snap = accounts.snapshot(providers=())
        self.assertEqual((snap["providers"], snap["stale_count"]), ({}, 0))


if __name__ == "__main__":
    unittest.main()
