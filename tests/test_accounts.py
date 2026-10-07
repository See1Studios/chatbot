"""accounts.snapshot(): the 2026-09-19 incident replayed with fake procs + logs,
plus the change-observation rule used for providers with no per-process account.
Run: engine/run-tests.sh test_accounts
"""
import base64
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
from providers import accounts  # noqa: E402

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

    def test_a_delegated_worker_on_the_old_login_is_a_worker_to_stop(self):
        # ACCOUNT_SWITCH_v1: the runner's child is the chatbot's own work, not an "external" process
        self.add_proc("agy", 7, 500, ppid=70, log_email=OLD)   # worker, old login  -> stop
        self.add_proc("agy", 8, 520, ppid=80, log_email=NEW)   # worker, new login  -> keep
        self.add_proc("agy", 9, 540, ppid=90, log_email=OLD)   # external           -> never
        orig = accounts._is_runner
        accounts._is_runner = lambda pid: pid in (70, 80)
        try:
            snap = accounts.snapshot()
        finally:
            accounts._is_runner = orig
        by_pid = {p["pid"]: p for p in snap["providers"]["agy"]["processes"]}
        self.assertEqual((by_pid[7]["owner"], by_pid[9]["owner"]), ("worker", "external"))
        self.assertNotIn("kill_cmd", by_pid[7], "the server stops it; no hand-copied kill")
        self.assertEqual(accounts.stale_workers(snap), {7})
        self.assertEqual(accounts.stale_owned(snap), set(), "a worker is not a session to recycle")

    def test_stop_workers_rechecks_the_parent_before_signalling(self):
        sent = []
        orig = (accounts._stat_fields, accounts._is_runner, accounts.platform_compat.terminate)
        accounts._stat_fields = lambda pid: ["S", str(pid * 10)]
        accounts._is_runner = lambda pid: pid == 70
        accounts.platform_compat.terminate = lambda pid: sent.append(pid) or True
        try:
            self.assertEqual(accounts.stop_workers({7, 8}), [7])
        finally:
            accounts._stat_fields, accounts._is_runner, accounts.platform_compat.terminate = orig
        self.assertEqual(sent, [7], "a reused pid whose parent is no longer the runner is left alone")

    def test_login_fingerprint_follows_the_refresh_token_not_the_file(self):
        accounts.AGY_TOKEN.write_text(json.dumps({"id_token": _jwt(NEW), "refresh_token": "r1"}))
        a = accounts.login_fingerprint("agy")
        accounts.AGY_TOKEN.write_text(json.dumps({"id_token": _jwt(NEW) + "x", "refresh_token": "r1"}))
        self.assertEqual(accounts.login_fingerprint("agy"), a, "an access-token refresh is not a new login")
        accounts.AGY_TOKEN.write_text(json.dumps({"id_token": _jwt(NEW), "refresh_token": "r2"}))
        self.assertNotEqual(accounts.login_fingerprint("agy"), a)
        self.assertNotIn("r2", a)
        self.assertIsNone(accounts.login_fingerprint("claude"))

    def rerun(self, codes, logins, provider="agy"):
        calls, it = [], iter(logins)
        orig = accounts.current_email
        accounts.current_email = lambda p: next(it)
        try:
            res = accounts.rerun_on_switch(provider, lambda: (calls.append(1) or (codes[len(calls) - 1], "o")))
        finally:
            accounts.current_email = orig
        return res, len(calls)

    def test_a_run_stopped_by_an_account_switch_runs_again(self):
        self.assertEqual(self.rerun([-15, 0], ["old", "new", "new"]), ((0, "o"), 2))

    def test_no_rerun_without_a_switch_or_when_the_login_is_unknown(self):
        self.assertEqual(self.rerun([1], ["a", "a"])[1], 1)
        self.assertEqual(self.rerun([1], [None, None])[1], 1)
        self.assertEqual(self.rerun([1], ["a", None])[1], 1)
        self.assertEqual(self.rerun([1], [], provider="claude")[1], 1, "a provider that does not keep its login")

    def test_reruns_are_capped(self):
        self.assertEqual(self.rerun([-15] * 3, ["a", "b", "b", "c", "c", "d"])[1], 1 + accounts.SWITCH_RERUNS)

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

class ProfilesTest(Base):
    """Saved agy logins: save, list (adopting logout backups), and the atomic switch."""

    def setUp(self):
        super().setUp()
        self.orig_prof = (accounts.AGY_PROFILES_DIR, accounts.reap_stray_cli_procs)
        accounts.AGY_PROFILES_DIR = self.tmp / "tokens"
        accounts.reap_stray_cli_procs = lambda provider: []

    def tearDown(self):
        accounts.AGY_PROFILES_DIR, accounts.reap_stray_cli_procs = self.orig_prof
        super().tearDown()

    def login(self, email, refresh="r"):
        accounts.AGY_TOKEN.write_text(json.dumps({"id_token": _jwt(email), "refresh_token": refresh}))

    def test_save_profile_keeps_the_active_token_under_its_email_privately(self):
        r = accounts.save_profile()
        saved = accounts.AGY_PROFILES_DIR / (NEW + ".json")
        self.assertEqual((r["ok"], r["email"]), (True, NEW))
        self.assertEqual(saved.read_bytes(), accounts.AGY_TOKEN.read_bytes())
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in accounts.AGY_PROFILES_DIR.iterdir()], [NEW + ".json"], "no temp file left")

    def test_save_profile_without_a_login_fails_cleanly(self):
        accounts.AGY_TOKEN.unlink()
        self.assertFalse(accounts.save_profile()["ok"])
        accounts.AGY_TOKEN.write_text(json.dumps({"id_token": _jwt("../evil@x")}))
        self.assertFalse(accounts.save_profile()["ok"], "an email that is not file-safe is never a path")

    def test_usage_snapshot_is_kept_per_account_and_never_listed_as_a_profile(self):
        rows = [{"group": "Gemini", "remaining_pct": "80%"}]
        accounts.save_usage_snapshot(OLD, rows, 100.0)
        accounts.save_usage_snapshot(NEW, [], 200.0)   # nothing to remember
        accounts.save_usage_snapshot(None, rows, 300.0)
        self.assertEqual(accounts.usage_snapshots(), {OLD: {"rows": rows, "checked_at": 100.0}})
        self.login(OLD)
        accounts.save_profile()
        self.assertEqual([p["email"] for p in accounts.list_profiles()], [OLD])
        self.assertEqual(accounts.AGY_PROFILES_DIR.joinpath("usage.snapshots").stat().st_mode & 0o777, 0o600)

    ROWS = [
        {"group": "Gemini Models", "limit_type": "Weekly Limit Remaining", "remaining_pct": "32%", "reset_at": "w1"},
        {"group": "Gemini Models", "limit_type": "Five Hour Limit Remaining", "remaining_pct": "100%", "reset_at": "h1"},
        {"group": "Claude and GPT models", "limit_type": "Weekly Limit Remaining", "remaining_pct": "85%", "reset_at": "w2"},
    ]

    def test_agy_quota_view_picks_the_group_of_the_model_short_window_first(self):
        from providers.adapter_agy import AgyAdapter
        a = AgyAdapter.__new__(AgyAdapter)
        v = a.quota_view("gemini-3.8-flash-low", self.ROWS)
        self.assertEqual((v["scope"], v["headline"]), ("Gemini Models", "5h 100% \u00b7 week 32%"))
        self.assertEqual([(w["label"], w["pct"], w["reset_at"]) for w in v["windows"]], [("5h", 100, "h1"), ("week", 32, "w1")])
        for model in ("claude-opus-4-6-thinking", "gpt-5"):
            self.assertEqual(a.quota_view(model, self.ROWS)["headline"], "week 85%")

    def test_a_model_no_group_claims_gets_every_group_and_an_empty_report_an_empty_view(self):
        from providers.adapter_agy import AgyAdapter
        a = AgyAdapter.__new__(AgyAdapter)
        for model in ("mystery-1", ""):
            v = a.quota_view(model, self.ROWS)
            self.assertEqual((v["scope"], len(v["windows"])), ("", 3))
            self.assertIn("Claude and GPT models week 85%", v["headline"])
        self.assertEqual(a.quota_view("gemini-x", []), {"scope": "", "headline": "", "windows": []})

    def test_usage_and_profiles_routes_carry_the_view_for_the_model_asked_about(self):
        import route_accounts
        from unittest import mock
        from route_table import Req
        sent = []
        class H:   # the two handler hooks Req.json() uses
            def _send(self, code, raw, ctype, **kw):
                sent.append((code, json.loads(raw)))
        rows = self.ROWS[1:2]
        data = {"ok": True, "supported": True, "rows": rows, "checked_at": 1.0}
        self.login(NEW)
        accounts.save_profile()
        with mock.patch.object(route_accounts, "_get_usage", lambda provider="agy", force=False: data):
            route_accounts.usage(Req(H(), "/api/usage", "provider=agy&model=gemini-3.8-flash-low"))
        code, u = sent.pop()
        self.assertEqual((code, u["view"]["headline"], u["rows"]), (200, "5h 100%", rows), "rows stay as they were")
        accounts.save_usage_snapshot(NEW, rows, 2.0)
        route_accounts.profiles(Req(H(), "/api/accounts/profiles", "model=claude-sonnet-4-6"))
        view = sent.pop()[1]["profiles"][0]["usage"]["view"]
        self.assertEqual((view["scope"], view["headline"]), ("", "Gemini Models 5h 100%"), "no group claims it: all rows")

    def _view(self, cls_path, model, rows, **attrs):
        import importlib
        mod, cls = cls_path.rsplit(".", 1)
        a = getattr(importlib.import_module(mod), cls).__new__(getattr(importlib.import_module(mod), cls))
        for k, v in attrs.items():
            setattr(a, k, v)
        return a.quota_view(model, rows)

    def test_one_window_providers_name_the_window_by_its_limit_type(self):
        rows = [{"group": "codex", "limit_type": "30d", "remaining_pct": "95%", "reset_at": "r"}]
        for cls in ("providers.adapter_codex.CodexAdapter", "providers.adapter_grok.GrokAdapter"):
            v = self._view(cls, "any", rows)
            self.assertEqual((v["scope"], v["headline"], v["windows"][0]["pct"]), ("codex", "30d 95%", 95))

    def test_claude_keeps_the_limits_and_leaves_the_request_counts_to_the_plain_rows(self):
        rows = [{"group": "Current session", "limit_type": "use", "remaining_pct": "98%", "reset_at": "a"},
                {"group": "Current week (all models)", "limit_type": "use", "remaining_pct": "68%", "reset_at": "b"},
                {"group": "Claude (24h)", "limit_type": "15 sessions", "remaining_pct": "896 reqs", "reset_at": "c"}]
        v = self._view("providers.adapter_claude.ClaudeAdapter", "claude-sonnet-4-6", rows)
        self.assertEqual(v["headline"], "Current session 98% \u00b7 Current week (all models) 68%")

    def test_openrouter_shows_the_free_quota_for_a_free_model_and_the_credit_for_the_others(self):
        rows = [{"group": "Credit", "limit_type": "c", "remaining_pct": "$9.81 / $20.00", "reset_at": "x"},
                {"group": "Free quota", "limit_type": "d", "remaining_pct": "100% (1000/1000)", "reset_at": "y"},
                {"group": "Free status", "limit_type": "s", "remaining_pct": "17 ok", "reset_at": "z"}]
        cls = "providers.adapter_openai.OpenAIDialectAdapter"
        free = self._view(cls, "qwen/qwen3.8-27b:free", rows, id="openrouter")
        paid = self._view(cls, "anthropic/claude-x", rows, id="openrouter")
        self.assertEqual((free["headline"], free["windows"][0]["pct"]), ("Free quota 100% (1000/1000)", 100))
        self.assertEqual((paid["headline"], paid["windows"][0]["pct"]), ("Credit $9.81 / $20.00", None), "dollars are text, not a percentage")
        self.assertEqual(self._view(cls, "openrouter/free", rows, id="openrouter")["headline"], free["headline"])
        self.assertEqual(self._view(cls, "m", [rows[2]], id="openrouter")["headline"], "Free status 17 ok", "nothing to pick: all rows")

    def test_omniroute_picks_every_account_of_the_connection_the_model_names(self):
        rows = [{"group": "codex (a@x)", "limit_type": "l", "remaining_pct": "ok (100%)", "reset_at": "-"},
                {"group": "nvidia (main)", "limit_type": "l", "remaining_pct": "ok (100%)", "reset_at": "-"},
                {"group": "codex (b@x)", "limit_type": "l", "remaining_pct": "warn (0%)", "reset_at": "-"}]
        cls = "providers.adapter_openai.OpenAIDialectAdapter"
        v = self._view(cls, "codex/gpt-5", rows, id="omniroute")
        self.assertEqual((v["scope"], [w["pct"] for w in v["windows"]]), ("codex", [100, 0]))
        v = self._view(cls, "antigravity/claude-sonnet-4-6", rows, id="omniroute")
        self.assertEqual((v["scope"], len(v["windows"])), ("", 3), "no connection of that name: all of them")

    def test_the_default_view_keeps_every_row_and_marks_non_percentages_as_text_only(self):
        from providers.adapter_base import AgentAdapter, parse_pct
        rows = [{"group": "Claude (7d)", "limit_type": "3 sessions", "remaining_pct": "42 reqs", "reset_at": "r"},
                {"group": "Free", "limit_type": "daily", "remaining_pct": "45% (9/20)", "reset_at": "u"}]
        v = AgentAdapter.quota_view(object(), "any-model", rows)
        self.assertEqual([(w["pct"], w["text"]) for w in v["windows"]], [(None, "42 reqs"), (45, "45% (9/20)")])
        self.assertEqual(v["windows"][0]["label"], "Claude (7d) 3 sessions")
        self.assertEqual([parse_pct(x) for x in ("32%", " 7 %", "150%", "n/a", None, "ok (100%)", "warn (0%)")], [32, 7, 100, None, None, 100, 0])

    def test_list_profiles_numbers_by_email_and_marks_the_active_one(self):
        self.login(OLD)
        accounts.save_profile()
        self.login(NEW)
        accounts.save_profile()
        got = accounts.list_profiles()
        self.assertEqual([(p["index"], p["email"], p["active"]) for p in got], [(1, NEW, True), (2, OLD, False)])
        self.assertNotIn("refresh", json.dumps(got))

    def test_list_profiles_adopts_logout_backups_and_archives_them(self):
        bak = accounts.AGY_TOKEN.with_name(accounts.AGY_TOKEN.name + ".bak-100")
        bak.write_text(json.dumps({"id_token": _jwt(OLD), "refresh_token": "old-r"}))
        junk = accounts.AGY_TOKEN.with_name(accounts.AGY_TOKEN.name + ".bak-200")
        junk.write_text("not json")
        self.assertEqual([p["email"] for p in accounts.list_profiles()], [OLD])
        self.assertIn("old-r", (accounts.AGY_PROFILES_DIR / (OLD + ".json")).read_text())
        self.assertFalse(bak.exists())
        self.assertTrue((accounts.AGY_PROFILES_DIR / "bak" / bak.name).exists(), "archived, never deleted")
        self.assertTrue(junk.exists(), "an unreadable backup is left where it was")

    def test_an_older_backup_never_overwrites_a_newer_profile(self):
        self.login(OLD, "newest")
        accounts.save_profile()
        bak = accounts.AGY_TOKEN.with_name(accounts.AGY_TOKEN.name + ".bak-1")
        bak.write_text(json.dumps({"id_token": _jwt(OLD), "refresh_token": "older"}))
        import os
        os.utime(bak, (1, 1))
        accounts.list_profiles()
        self.assertIn("newest", (accounts.AGY_PROFILES_DIR / (OLD + ".json")).read_text())

    def test_switch_by_index_or_email_swaps_the_token_and_saves_the_old_one(self):
        self.login(OLD, "old-r")
        accounts.save_profile()
        self.login(NEW, "new-r")
        r = accounts.switch_profile("2")   # 1 = new, 2 = old
        self.assertEqual((r["ok"], r["email_before"], r["email"]), (True, NEW, OLD))
        self.assertIn("old-r", accounts.AGY_TOKEN.read_text())
        self.assertEqual(accounts.AGY_TOKEN.stat().st_mode & 0o777, 0o600)
        self.assertIn("new-r", (accounts.AGY_PROFILES_DIR / (NEW + ".json")).read_text(), "saved before the swap")
        self.assertEqual(accounts.switch_profile(NEW.upper())["email"], NEW)
        self.assertNotIn("-r", json.dumps(r))

    def test_switch_recycles_owned_processes_on_the_old_login_and_observes(self):
        self.login(OLD)
        accounts.save_profile()
        self.login(NEW)
        accounts.observe("agy", {"ok": True, "email": NEW})
        self.add_proc("agy", 11, 500, log_email=NEW)   # owned, on the login being left -> recycled
        self.add_proc("agy", 12, 520, log_email=NEW)   # external                        -> named only
        self.add_proc("agy", 13, 540, log_email=OLD)   # owned, already on the target    -> kept
        got, killed = [], []
        accounts.reap_stray_cli_procs = lambda provider: killed.append(provider) or []
        r = accounts.switch_profile(OLD, owned={11: {"owner": "session", "sid": "a"}, 13: {"owner": "session"}},
                                    recycle=lambda pids: got.append(pids) or {"recycled": sorted(pids)})
        self.assertEqual((got, r["recycle"], r["stale_pids"]), ([{11}], {"recycled": [11]}, [11, 12]))
        self.assertEqual(killed, ["agy"])
        self.assertEqual(accounts.snapshot(providers=("agy",))["providers"]["agy"]["changed_from"], NEW)

    def test_switch_outside_the_server_reaps_nothing(self):
        killed = []
        accounts.reap_stray_cli_procs = lambda provider: killed.append(provider) or []
        r = accounts.switch_profile("1")
        self.assertEqual((r["ok"], killed, r["recycle"]), (True, [], None))

    def test_a_chat_turn_that_mentions_login_is_not_a_helper(self):
        self.assertFalse(accounts._is_cli_helper(["-p", "fix the login page", "--output-format", "stream-json"]))
        self.assertFalse(accounts._is_cli_helper(["-p", "check /usage and login "]))
        self.assertTrue(accounts._is_cli_helper(["login", "--device-auth"]))
        self.assertTrue(accounts._is_cli_helper(["app-server"]))
        self.assertTrue(accounts._is_cli_helper(["auth", "login"]))
        self.assertFalse(accounts._is_cli_helper([]))
        self.assertTrue(accounts._is_cli_helper(["--print", "/usage"]))
        self.assertTrue(accounts._is_cli_helper(["-p", "/cost"]))

    def test_unknown_target_or_provider_changes_nothing(self):
        before = accounts.AGY_TOKEN.read_bytes()
        r = accounts.switch_profile("9")
        self.assertEqual((r["ok"], accounts.AGY_TOKEN.read_bytes()), (False, before))
        self.assertFalse(accounts.switch_profile("nobody@example.com")["ok"])
        with self.assertRaises(ValueError):
            accounts.list_profiles("claude")


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
