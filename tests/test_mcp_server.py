"""MCP tool server: call_tool contract (run_command / write_file / read side), and how the core adapters and the host
plugin (service tools) are wired in.

Nothing here runs a real command or writes outside a temp dir: `_run` is always
replaced by a recorder and the write/read roots are pointed at temp dirs. The one
class that uses real paths (RealPathsTest) makes every filesystem write raise.
Run: python3 -m unittest tests.test_mcp_server  (from services/chatbot)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mcp_server as mcp  # noqa: E402  -- the only place tests import the tool server

CODE = Path(__file__).resolve().parent.parent
CTL = "chatbot-ctl.sh"
CTL_ABS = str(mcp.SERVICES / "chatbot-ctl.sh")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.calls = []
        self._orig = {k: getattr(mcp, k) for k in ("_run", "ALLOW_ROOTS", "READ_ROOTS", "CODE_ROOT", "evolution", "DATA", "mcp_core")}
        # the adapter module's own switches (a core module that is "not installed"), put back after each test
        self._core_orig = {k: getattr(mcp.mcp_core, k) for k in ("memory_store", "observations", "tickets")}

        def fake_run(cmd, timeout=20, cwd=None):
            self.calls.append(list(cmd))
            return 0, "out", ""

        mcp._run = fake_run
        mcp.ALLOW_ROOTS = [self.tmp]
        mcp.READ_ROOTS = [self.tmp]

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(mcp, k, v)
        for k, v in self._core_orig.items():
            setattr(mcp.mcp_core, k, v)

    def run_cmd(self, cmd):
        return mcp.call_tool("run_command", {"cmd": cmd})

    def assertRan(self, cmd):
        self.calls.clear()
        r = self.run_cmd(cmd)
        self.assertTrue(r["success"], "expected %r to run: %s" % (cmd, r["message"]))
        self.assertEqual(self.calls, [["bash", "-lc", cmd]])

    def assertRefused(self, cmd):
        self.calls.clear()
        r = self.run_cmd(cmd)
        self.assertFalse(r["success"], "expected %r to be refused" % cmd)
        self.assertEqual(self.calls, [], "refused command must never reach _run: %r" % cmd)


class RunCommandTest(Base):
    def test_read_only_basics_run(self):
        for cmd in ("ls -la /tmp", "cat /etc/hostname", "head -n 3 x", "tail -n 3 x", "df -h",
                    "free -m", "ps aux", "du -sh .", "stat x", "pwd", "whoami", "date", "uname -a",
                    "ls /nope 2>/dev/null", "ls /nope 2> /dev/null"):
            self.assertRan(cmd)

    def test_ctl_status_doctor_probe_guard_run(self):
        for ctl in (CTL, CTL_ABS):
            for sub in ("status", "guard", "doctor", "probe", "probe 8"):
                self.assertRan("%s %s" % (ctl, sub))
        self.assertRan(CTL)  # bare == status

    def test_localhost_curl_get_runs(self):
        for cmd in ("curl -fsS http://127.0.0.1:3011/healthz", "curl -sS http://localhost:3012/healthz",
                    "curl -fsS http://127.0.0.1:3011/api/sessions/active -m 5",
                    "curl -sS http://localhost:3011/x --max-time 3 -i"):
            self.assertRan(cmd)

    def test_empty_and_metacharacters_are_refused(self):
        for cmd in ("", "   ", "ls; rm x", "ls | cat", "ls && pwd", "ls `pwd`", "ls $(pwd)", "ls\npwd", "ls 'a b"):
            self.assertRefused(cmd)

    def test_unlisted_programs_are_refused(self):
        for cmd in ("rm -rf x", "python3 x.py", "bash -c ls", "sudo ls", "wget http://127.0.0.1:1/x",
                    "curl https://example.com", "curl -fsS https://example.com", "FOO=1 ls"):
            self.assertRefused(cmd)

    def test_secret_related_commands_are_refused(self):
        for cmd in ("cat ~/.env", "cat auth.json", "cat my_token.txt", "ls antigravity-oauth"):
            self.assertRefused(cmd)

    def test_result_envelope_carries_exit_code_and_streams(self):
        r = self.run_cmd("pwd")
        self.assertEqual(r["data"], {"code": 0, "stdout": "out", "stderr": ""})

    # -- H1: lifecycle subcommands are for people, not for tools
    def test_ctl_lifecycle_subcommands_are_refused(self):
        for ctl in (CTL, CTL_ABS):
            for sub in ("repair", "stop", "restart", "start", "defibrillate", "shock", "cpr", "bogus", "-h"):
                self.assertRefused("%s %s" % (ctl, sub))

    def test_ctl_doctor_cannot_reach_repair(self):
        for cmd in (CTL + " doctor --auto-repair", CTL + " doctor auto", CTL_ABS + " doctor --auto-repair"):
            self.assertRefused(cmd)

    def test_ctl_extra_arguments_are_refused(self):
        for cmd in (CTL + " status x", CTL + " guard --now", CTL + " probe abc", CTL + " probe 5 6",
                    CTL + " probe 123"):
            self.assertRefused(cmd)

    def test_ctl_subcommand_cannot_be_smuggled_through_quoting_or_expansion(self):
        for cmd in (CTL + ' "repair"', CTL + " re''pair", CTL + " re\\pair", CTL + " {repair,status}",
                    CTL + " stat[u]s", CTL + " $X"):
            self.assertRefused(cmd)

    def test_ctl_lookalikes_are_refused(self):
        for cmd in (CTL + "-evil status", "./" + CTL + " status", "~/services/" + CTL + " status",
                    "/tmp/" + CTL + " status", CTL_ABS + "x status"):
            self.assertRefused(cmd)

    # -- H6: token match, not string prefix
    def test_prefix_match_is_per_token(self):
        for cmd in ("psql -h x", "lsof -i", "catx a", "dateutil", "header", "freebsd", "pwdx 1", "dux"):
            self.assertRefused(cmd)

    # -- H6: curl cannot write files or send bodies
    def test_curl_write_and_post_forms_are_refused(self):
        u = "http://127.0.0.1:3011/x"
        for tail in ("-o /tmp/f", "-o/tmp/f", "--output /tmp/f", "--output=/tmp/f", "-O", "-T /tmp/f",
                     "--upload-file /tmp/f", "--data x", "--data=@/tmp/f", "-d x", "--data-binary x",
                     "--data-raw x", "-X POST", "-XPOST", "--request POST", "-F a=b", "--json {}",
                     "-K /tmp/cfg", "--config /tmp/cfg", "-H x:y", "-L", "--next", "-m", "-m x", "-m 1000"):
            self.assertRefused("curl -fsS %s %s" % (u, tail))
        self.assertRefused("curl -fsSo /tmp/f " + u)
        self.assertRefused("curl -fsS -o /tmp/f " + u)
        self.assertRefused("curl -fsS -X POST " + u)

    def test_curl_targets_only_local_ports(self):
        for url in ("http://127.0.0.1:3011@evil.example/", "http://localhost:3011.evil.example/", "http://127.0.0.1/",
                    "http://127.0.0.1:3011evil", "https://127.0.0.1:3011/", "http://0.0.0.0:3011/",
                    "http://127.0.0.2:3011/", "file:///etc/passwd", "127.0.0.1:3011"):
            self.assertRefused("curl -fsS " + url)
        self.assertRefused("curl -fsS http://127.0.0.1:3011/ http://evil.example/")
        self.assertRefused("curl -fsS")
        self.assertRefused("curl")

    def test_curl_cannot_reach_the_defibrillate_endpoint(self):
        self.assertRefused("curl -fsS http://127.0.0.1:3011/api/host/defibrillate")
        self.assertRefused("curl -fsS http://localhost:3011/api/host/Defibrillate")
        self.assertRefused("curl -fsS http://127.0.0.1:3011/api/host/defibrillate -X POST")

    # -- output redirection would write past write_file's checks
    def test_redirection_is_refused(self):
        for cmd in ("date > /tmp/x", "ls >> /tmp/x", "cat < /etc/hostname", "ls >/tmp/x", "ls 2>/tmp/x",
                    "ls 1>/dev/null", "ls >/dev/null", "ls 2>/dev/nullx", "ls a2>/dev/null"):
            self.assertRefused(cmd)

    # -- the host plugin's extra prefixes are honoured per token too
    def test_plugin_prefixes_match_per_token(self):
        if not mcp.HOST_PLUGIN:
            self.skipTest("no host plugin")
        self.assertRan("hermes status")
        self.assertRefused("hermes stop")
        self.assertRefused("hermes statusx")


class ServiceCtlTest(Base):
    """service_ctl / list_services / ping_nas are the host plugin's tools; the server itself has none."""

    def setUp(self):
        super().setUp()
        if not mcp.HOST_PLUGIN:
            self.skipTest("no host plugin")

    def call(self, name, action):
        return mcp.call_tool("service_ctl", {"name": name, "action": action})

    def test_invalid_action_and_unknown_service_and_mcp_are_refused(self):
        self.assertFalse(self.call("chatbot", "nuke")["success"])
        self.assertFalse(self.call("nope", "status")["success"])
        self.assertFalse(self.call("nas-mcp", "status")["success"])
        self.assertEqual(self.calls, [])

    def test_chatbot_status_runs_the_ctl(self):
        self.assertTrue(self.call("chatbot", "status")["success"])
        self.assertEqual(self.calls, [[CTL_ABS, "status"]])

    def test_chatbot_lifecycle_is_refused(self):
        for action in ("start", "stop", "restart"):
            r = self.call("chatbot", action)
            self.assertFalse(r["success"], action)
            self.assertIn("status only", r["message"])
        self.assertEqual(self.calls, [])

    def test_chatbot_name_is_gated_even_when_its_ctl_is_missing(self):
        with mock.patch.object(mcp.Path, "exists", return_value=False):
            r = self.call("chatbot", "start")
        self.assertIn("status only", r["message"])  # not "unknown service": the name check comes first

    def test_any_service_backed_by_the_chatbot_ctl_is_gated_too(self):
        real = mcp.SERVICES / "chatbot" / "chatbot-ctl.sh"
        with mock.patch.object(mcp.HOST_PLUGIN, "_service_ctls", return_value={"alias": str(real)}):
            self.assertFalse(self.call("alias", "start")["success"])
            self.assertTrue(self.call("alias", "status")["success"])

    def test_other_services_keep_their_lifecycle(self):
        with mock.patch.object(mcp.HOST_PLUGIN, "_service_ctls", return_value={"sibling": CTL_ABS.replace("chatbot", "sibling")}), \
                mock.patch.object(mcp.Path, "exists", return_value=True), \
                mock.patch.object(mcp.Path, "resolve", return_value=Path("/x/sibling-ctl.sh")):
            self.assertTrue(self.call("sibling", "restart")["success"])
        self.assertEqual(self.calls, [[CTL_ABS.replace("chatbot", "sibling"), "restart"]])


class WriteFileTest(Base):
    """Temp code root with the SHIPPED registry; nothing outside self.tmp is ever touched."""

    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.code = self.tmp
        shutil.copy(str(CODE / "protected_paths.json"), str(self.code / "protected_paths.json"))
        mcp.CODE_ROOT = self.code
        mcp.ALLOW_ROOTS = [self.code, self.home / ".agents"]
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, content="hello"):
        return mcp.call_tool("write_file", {"path": str(path), "content": content})

    def assertProtected(self, rel_or_path):
        p = Path(rel_or_path) if Path(str(rel_or_path)).is_absolute() else self.code / rel_or_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("ORIGINAL", encoding="utf-8")
        r = self.write(p, "CHANGED")
        self.assertFalse(r["success"], "expected %s to be protected" % rel_or_path)
        self.assertIn("protected", r["message"])
        self.assertEqual(p.read_text(encoding="utf-8"), "ORIGINAL")
        self.assertEqual([x.name for x in p.parent.iterdir() if x.name.endswith(".tmp")], [])

    def test_writes_inside_allowed_root_atomically(self):
        target = self.code / "data" / "workspace" / "a.txt"
        r = self.write(target, "안녕")
        self.assertTrue(r["success"])
        self.assertEqual(target.read_text(encoding="utf-8"), "안녕")
        self.assertEqual([p.name for p in target.parent.iterdir()], ["a.txt"])  # no .tmp left behind

    def test_overwrite_replaces_content(self):
        target = self.code / "notes.md"
        self.write(target, "one")
        self.write(target, "two")
        self.assertEqual(target.read_text(encoding="utf-8"), "two")

    def test_host_modules_are_protected(self):
        for rel in ("server.py", "session.py", "adapters.py", "mcp_server.py", "mcp_core.py", "nas_mcp_host.py", "evolution.py",
                    "brand_new_module.py"):
            self.assertProtected(rel)

    def test_guard_ticket_rules_and_registry_are_protected(self):
        for rel in ("chatbot-ctl.sh", "protected_paths.json", "tests/test_x.py", "tests/probes/p.py",
                    "data/workspace/SELF-MODIFY.md", "data/workspace/AGENTS.md", "docs/SELF-MODIFY.md",
                    "docs/EMERGENCY.md", "data/host-force.ticket", "__pycache__/server.cpython-38.pyc"):
            self.assertProtected(rel)

    def test_global_shared_skills_directory_is_protected(self):
        self.assertProtected(self.home / ".agents" / "skills" / "x" / "SKILL.md")

    def test_static_ui_is_the_explicit_exception(self):
        for rel in ("static/app.js", "static/vendor/lib.js", "static/new/page.html"):
            self.assertTrue(self.write(self.code / rel)["success"], rel)

    def test_instance_layer_and_plans_stay_writable(self):
        for rel in ("data/workspace/PERSONA.md", "data/workspace/memory/MEMORY.md",
                    "data/workspace/.agents/skills/nas-sphere/SKILL.md",
                    "data/workspace/skill-observations/observation-log/0001-x.md",
                    "docs/plans/recursive-self-evolution.md", "docs/DEVLOG.md", "notes/sub/helper.py"):
            self.assertTrue(self.write(self.code / rel)["success"], rel)

    def test_dotdot_and_symlink_routes_do_not_bypass(self):
        (self.code / "server.py").write_text("ORIGINAL", encoding="utf-8")
        (self.code / "data").mkdir()
        self.assertFalse(self.write(self.code / "data" / ".." / "server.py", "CHANGED")["success"])
        (self.code / "data" / "alias.txt").symlink_to(self.code / "server.py")
        self.assertFalse(self.write(self.code / "data" / "alias.txt", "CHANGED")["success"])
        (self.code / "data" / "tdir").symlink_to(self.code / "tests")
        self.assertFalse(self.write(self.code / "data" / "tdir" / "new.txt", "CHANGED")["success"])
        self.assertEqual((self.code / "server.py").read_text(encoding="utf-8"), "ORIGINAL")
        self.assertFalse((self.code / "tests" / "new.txt").exists())

    def test_outside_allowed_roots_keeps_its_own_message(self):
        other = Path(tempfile.mkdtemp()).resolve() / "a.txt"
        r = self.write(other)
        self.assertEqual(r["message"], "write path not allowlisted")
        self.assertFalse(other.exists())

    def test_missing_or_broken_registry_refuses_every_write(self):
        (self.code / "protected_paths.json").write_text("{broken", encoding="utf-8")
        r = self.write(self.code / "notes.md")
        self.assertFalse(r["success"])
        self.assertIn("registry unavailable", r["message"])
        (self.code / "protected_paths.json").unlink()
        self.assertFalse(self.write(self.code / "notes.md")["success"])
        self.assertFalse((self.code / "notes.md").exists())

    def test_unimportable_core_refuses_every_write(self):
        mcp.evolution = None
        r = self.write(self.code / "notes.md")
        self.assertFalse(r["success"])
        self.assertIn("registry unavailable", r["message"])

    def test_secret_names_and_contents_and_size_are_still_refused(self):
        self.assertFalse(self.write(self.code / ".env")["success"])
        self.assertFalse(self.write(self.code / "my_token.txt")["success"])
        self.assertFalse(self.write(self.code / "a.txt", "api_key = 123")["success"])
        self.assertFalse(self.write(self.code / "big.txt", "x" * 2_000_001)["success"])
        self.assertEqual([p.name for p in self.code.iterdir()], ["protected_paths.json"])

    def test_symlink_pointing_outside_is_refused(self):
        outside = Path(tempfile.mkdtemp()).resolve()
        (self.code / "link").symlink_to(outside)
        self.assertFalse(self.write(self.code / "link" / "a.txt")["success"])
        self.assertEqual(list(outside.iterdir()), [])


class RealPathsTest(unittest.TestCase):
    """Phase 0 completion criteria against the REAL paths and REAL allowlist.
    Every filesystem write is made to raise, so a broken guard cannot damage the live tree."""

    def setUp(self):
        for name in ("write_text", "replace", "mkdir", "write_bytes"):
            p = mock.patch.object(Path, name, side_effect=AssertionError("filesystem write attempted: " + name))
            p.start()
            self.addCleanup(p.stop)

    def refused(self, path):
        r = mcp.call_tool("write_file", {"path": str(path), "content": "x"})
        self.assertFalse(r["success"], str(path))
        self.assertIn("protected", r["message"], "%s: %s" % (path, r["message"]))

    def test_host_modules_and_guards_are_refused(self):
        self.assertEqual(mcp.CODE_ROOT, CODE)
        for path in sorted(CODE.glob("*.py")):
            self.refused(path)
        for rel in ("chatbot-ctl.sh", "tests/test_mcp_server.py", "protected_paths.json",
                    "data/workspace/SELF-MODIFY.md", "data/workspace/AGENTS.md", "docs/EMERGENCY.md",
                    "data/host-force.ticket"):
            self.refused(CODE / rel)

    def test_the_symlink_to_the_ctl_is_refused_too(self):
        link = mcp.SERVICES / "chatbot-ctl.sh"
        if link.exists():
            self.refused(link)

    def test_global_agents_directory_is_refused(self):
        self.refused(mcp.AGENTS / "skills" / "some-skill" / "SKILL.md")

    def test_static_ui_is_not_protected(self):
        self.assertIsNone(mcp.evolution.match_protected(mcp.CODE_ROOT, CODE / "static" / "app.js"))

    def test_lifecycle_calls_are_refused_without_running_anything(self):
        with mock.patch.object(mcp, "_run", side_effect=AssertionError("must not run")):
            for cmd in ("chatbot-ctl.sh repair", CTL_ABS + " repair", "chatbot-ctl.sh restart",
                        "chatbot-ctl.sh defibrillate", "chatbot-ctl.sh doctor --auto-repair"):
                self.assertFalse(mcp.call_tool("run_command", {"cmd": cmd})["success"], cmd)
            self.assertFalse(mcp.call_tool("service_ctl", {"name": "chatbot", "action": "start"})["success"])


class ObservationToolTest(Base):
    """The `observation` tool: a thin adapter over observations.py. Recording or closing an observation starts nothing."""

    def setUp(self):
        super().setUp()
        self._data = mcp.DATA
        mcp.DATA = self.tmp
        self.root = self.tmp / "workspace" / "skill-observations"
        self.log = self.root / "observation-log"

    def tearDown(self):
        mcp.DATA = self._data
        super().tearDown()

    def call(self, action, **kw):
        return mcp.call_tool("observation", dict(kw, action=action))

    def add(self, **kw):
        args = {"title": "Provider swap loses context", "body": "After swapping to claude the answer ignored the persona."}
        args.update(kw)
        return self.call("add", **args)

    def test_add_records_one_open_entry_in_the_observation_log(self):
        r = self.add(area="handoff")
        self.assertTrue(r["success"], r["message"])
        (path,) = list(self.log.iterdir())
        self.assertEqual(path.name, "0001-provider-swap-loses-context.md")
        text = path.read_text(encoding="utf-8")
        self.assertRegex(text[:400], r"status:\s*open")
        self.assertIn("persona", text)
        self.assertEqual(r["data"]["name"], path.name)

    def test_numbers_continue(self):
        self.add()
        self.add(title="Another thing")
        self.assertEqual(sorted(p.name[:4] for p in self.log.iterdir()), ["0001", "0002"])

    def test_title_and_body_are_required_and_none_is_not_a_title(self):
        for kw in ({"title": ""}, {"body": ""}, {"title": "   "}, {"title": None}, {"body": None}):
            self.assertFalse(self.add(**kw)["success"], kw)
        self.assertFalse(self.log.exists() and list(self.log.iterdir()))

    def test_secret_like_content_is_refused_in_every_text_field(self):
        self.assertFalse(self.add(body="my api_key = abc123")["success"])
        self.assertFalse(self.add(title="Bearer abcdef.ghi")["success"])
        self.assertFalse(self.add(area="client_secret")["success"])
        self.assertFalse(self.log.exists() and list(self.log.iterdir()))

    def test_a_runaway_is_stopped_after_ten_an_hour(self):
        for i in range(mcp.mcp_core.RECENT_LIMIT):
            self.assertTrue(self.add(title="note %d" % i)["success"])
        r = self.add(title="one too many")
        self.assertFalse(r["success"])
        self.assertIn("ask the operator", r["message"])
        self.assertEqual(len(list(self.log.iterdir())), mcp.mcp_core.RECENT_LIMIT)

    def test_list_get_and_resolve(self):
        oid = int(self.add()["data"]["name"][:4])
        self.assertEqual([o["id"] for o in self.call("list")["data"]["observations"]], [oid])
        self.assertEqual(self.call("list", status="parked")["data"]["observations"], [])
        self.assertIn("persona", self.call("get", id=oid)["data"]["observation"]["body"])
        r = self.call("resolve", id=oid, status="actioned", resolution="Handoff now carries the persona")
        self.assertTrue(r["success"], r["message"])
        self.assertEqual(r["data"]["observation"]["status"], "actioned")
        self.assertFalse(self.call("resolve", id=oid, status="declined", resolution="again")["success"])

    def test_closing_needs_a_reason_and_a_known_status(self):
        oid = int(self.add()["data"]["name"][:4])
        for kw in ({"status": "actioned"}, {"status": "actioned", "resolution": None}, {"status": "closed", "resolution": "x"},
                   {"status": "parked", "resolution": "later"}):
            self.assertFalse(self.call("resolve", id=oid, **kw)["success"], kw)
        self.assertEqual(self.call("get", id=oid)["data"]["observation"]["status"], "open")
        self.assertFalse(self.call("get", id=99)["success"])

    def test_review_lists_what_a_review_looks_at_and_reviewed_needs_a_summary(self):
        self.add(title="Open one")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "candidates.jsonl").write_text(
            json.dumps({"epoch": 1789908287.39, "ts": "t", "signal": "correction", "provider": "agy", "detail": {"user": "왜 안돼?"}}) + "\n",
            encoding="utf-8")
        d = self.call("review")["data"]
        self.assertEqual((len(d["open"]), d["unreviewed_candidates"], d["last_review"]), (1, 1, "never"))
        self.assertEqual(d["recent_candidates"][0]["ref"], "candidate:1789908287.39")
        self.assertFalse(self.call("reviewed")["success"])
        self.assertFalse(self.call("reviewed", text="  ")["success"])
        r = self.call("reviewed", text="read 1 open observation, ticketed none")
        self.assertTrue(r["success"], r["message"])
        self.assertEqual(self.call("review")["data"]["unreviewed_candidates"], 0)

    def test_unknown_action_and_unavailable_core_refuse_instead_of_crashing(self):
        r = self.call("delete", id=1)
        self.assertFalse(r["success"])
        self.assertIn("unknown action", r["message"])
        mcp.mcp_core.observations = None
        r = self.call("list")
        self.assertFalse(r["success"])
        self.assertIn("unavailable", r["message"])

    def test_the_old_tool_name_is_gone_and_the_new_one_lists_its_actions(self):
        names = {t["name"] for t in mcp.tool_defs()}
        self.assertNotIn("observe_add", names)
        (tool,) = [t for t in mcp.tool_defs() if t["name"] == "observation"]
        self.assertEqual(tool["inputSchema"]["properties"]["action"]["enum"],
                         ["add", "list", "get", "resolve", "review", "reviewed"])
        self.assertIn("starts any change", tool["description"])


class MemoryToolTest(Base):
    """The `memory` tool: a thin adapter over memory_store.py, so a shell-less provider follows the same rules."""

    def setUp(self):
        super().setUp()
        self._data = mcp.DATA
        mcp.DATA = self.tmp
        self.file = self.tmp / "workspace" / "memory" / "MEMORY.md"

    def tearDown(self):
        mcp.DATA = self._data
        super().tearDown()

    def call(self, action, **kw):
        return mcp.call_tool("memory", dict(kw, action=action))

    def test_show_creates_the_template_and_returns_it(self):
        r = self.call("show")
        self.assertTrue(r["success"], r["message"])
        self.assertIn("## 실장님", r["data"]["content"])
        self.assertTrue(self.file.exists())

    def test_add_then_search_then_show(self):
        r = self.call("add", text="[2001-01-01] 실장님 따님 이름은 시원이다.")
        self.assertTrue(r["success"], r["message"])
        self.assertEqual(r["data"]["status"], "added")
        self.assertEqual(r["data"]["line"].count("["), 1)  # the date is ours, and only once (never "[d] [d] ...")
        hits = self.call("search", query="시원")["data"]["hits"]
        self.assertEqual([h["section"] for h in hits], ["실장님"])
        self.assertIn("시원", self.call("show")["data"]["content"])

    def test_a_known_fact_is_reported_not_added_twice(self):
        self.call("add", text="커피는 아메리카노")
        r = self.call("add", text="커피는 아메리카노")
        self.assertTrue(r["success"])
        self.assertEqual((r["data"]["status"], r["message"]), ("duplicate", "already known; nothing added"))
        self.assertEqual(len([l for l in self.file.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]), 1)

    def test_sections_and_limits_are_the_core_s(self):
        self.assertTrue(self.call("add", text="포트 3014", section="운영 결정")["success"])
        self.assertFalse(self.call("add", text="x", section="없는 섹션")["success"])
        self.assertFalse(self.call("add", text="가" * 400)["success"])
        for bad in ({"text": ""}, {"text": None}, {"text": "[2026-09-20]"}):
            self.assertFalse(self.call("add", **bad)["success"], bad)

    def test_a_broad_forget_is_refused_and_all_is_explicit(self):
        for fact in ("실장님은 A", "실장님은 B"):
            self.call("add", text=fact)
        r = self.call("forget", query="실장님")
        self.assertFalse(r["success"])
        self.assertIn("2줄이 일치합니다", r["message"])
        self.assertFalse(self.call("forget", query="실장님", all="true")["success"])  # a string is not the boolean
        r = self.call("forget", query="실장님", all=True)
        self.assertTrue(r["success"], r["message"])
        self.assertEqual(len(r["data"]["removed"]), 2)

    def test_forget_one_and_nothing_to_forget(self):
        self.call("add", text="keep this")
        self.call("add", text="drop me please")
        self.assertEqual(len(self.call("forget", query="drop me")["data"]["removed"]), 1)
        r = self.call("forget", query="absent")
        self.assertEqual((r["success"], r["message"]), (True, "no matching line"))
        self.assertFalse(self.call("forget", query="k")["success"])
        self.assertIn("keep this", self.call("show")["data"]["content"])

    def test_a_missing_query_is_refused_and_never_becomes_the_word_none(self):
        self.call("add", text="None of this should be forgotten by accident")
        for action in ("forget", "search"):
            r = self.call(action)  # no query at all
            self.assertFalse(r["success"], action)
        r = mcp.call_tool("memory", {"action": "forget", "query": None})
        self.assertFalse(r["success"])
        self.assertIn("None of this", self.call("show")["data"]["content"])

    def test_secret_like_text_is_never_stored(self):
        self.assertFalse(self.call("add", text="my api_key = abc123")["success"])
        self.assertFalse(self.call("search", query="Bearer abcdef")["success"])
        self.assertFalse(self.file.exists())

    def test_unknown_action_and_unavailable_core_refuse_instead_of_crashing(self):
        r = self.call("wipe")
        self.assertFalse(r["success"])
        self.assertIn("unknown action", r["message"])
        mcp.mcp_core.memory_store = None
        r = self.call("show")
        self.assertFalse(r["success"])
        self.assertIn("unavailable", r["message"])

    def test_the_tool_is_listed_with_its_four_actions(self):
        (tool,) = [t for t in mcp.tool_defs() if t["name"] == "memory"]
        self.assertEqual(tool["inputSchema"]["properties"]["action"]["enum"], ["show", "search", "add", "forget"])
        self.assertIn("only when siljangnim asks", tool["description"])


class TicketToolTest(Base):
    """The `ticket` tool: a thin adapter over tickets.py. Deciding (approve/decline/reopen) is not on it."""

    def setUp(self):
        super().setUp()
        mcp.DATA = self.tmp
        (self.tmp / "sessions" / "s1").mkdir(parents=True)
        (self.tmp / "sessions" / "s1" / "events.jsonl").write_text('{"event":"system"}\n{"event":"error"}\n', encoding="utf-8")

    def call(self, action, **kw):
        return mcp.call_tool("ticket", dict(kw, action=action))

    def propose(self, **kw):
        args = {"title": "Steer loses the queue", "target": "session.py: steer", "evidence": ["event:s1#2"]}
        args.update(kw)
        return self.call("propose", **args)

    def approve_outside_the_tool(self, tid):
        import tickets as core  # the operator's command line, not a tool call
        core.approve(self.tmp, tid, operator=core.OPERATOR_CONFIRMED)

    def test_propose_list_get(self):
        r = self.propose()
        self.assertTrue(r["success"], r["message"])
        self.assertIn("waiting for the operator", r["message"])
        tid = r["data"]["ticket"]["id"]
        self.assertEqual([t["id"] for t in self.call("list")["data"]["tickets"]], [tid])
        self.assertEqual(self.call("get", id=tid)["data"]["ticket"]["status"], "proposed")
        self.assertEqual(self.call("list", status="approved")["data"]["tickets"], [])

    def test_same_target_merges(self):
        self.propose()
        r = self.propose(evidence=["event:s1#1"])
        self.assertTrue(r["data"]["merged"])
        self.assertEqual(len(self.call("list")["data"]["tickets"]), 1)

    def test_a_proposal_needs_real_evidence(self):
        for kw in ({"evidence": ["event:s1#9"]}, {"evidence": []}, {"evidence": ["it felt slow"]}, {"title": ""}):
            self.assertFalse(self.propose(**kw)["success"], kw)
        self.assertEqual(self.call("list")["data"]["tickets"], [])

    def test_the_whole_working_cycle(self):
        tid = self.propose()["data"]["ticket"]["id"]
        self.assertFalse(self.call("claim", id=tid)["success"])          # not approved yet
        self.approve_outside_the_tool(tid)
        c = self.call("claim", id=tid)
        self.assertTrue(c["success"], c["message"])
        token = c["data"]["token"]
        self.assertEqual(c["data"]["attempts_left"], 2)
        self.assertTrue(self.call("note", id=tid, text="reading the code", token=token)["success"])
        self.assertFalse(self.call("release", id=tid, token="wrong", outcome="done")["success"])
        r = self.call("release", id=tid, token=token, outcome="done", text="tests pass")
        self.assertEqual(r["data"]["ticket"]["status"], "done")

    def test_a_second_author_is_told_to_stop_not_to_wait(self):
        a = self.propose(target="a")["data"]["ticket"]["id"]
        b = self.propose(target="b")["data"]["ticket"]["id"]
        self.approve_outside_the_tool(a)
        self.approve_outside_the_tool(b)
        self.assertTrue(self.call("claim", id=a)["success"])
        r = self.call("claim", id=b)
        self.assertFalse(r["success"])
        self.assertIn("not waiting", r["message"])

    def test_deciding_is_not_a_tool_action(self):
        tid = self.propose()["data"]["ticket"]["id"]
        for action in ("approve", "decline", "reopen", "drop_lease", "drop-lease", "", "delete"):
            r = self.call(action, id=tid)
            self.assertFalse(r["success"], action)
            self.assertIn("operator", r["message"])
        self.assertEqual(self.call("get", id=tid)["data"]["ticket"]["status"], "proposed")
        (tool,) = [t for t in mcp.tool_defs() if t["name"] == "ticket"]
        self.assertEqual(tool["inputSchema"]["properties"]["action"]["enum"],
                         ["propose", "list", "get", "claim", "note", "release"])
        self.assertTrue(tool["description"].startswith("The only way to create an evolution ticket"))

    def test_secret_like_text_is_refused(self):
        self.assertFalse(self.propose(title="api_key = abc")["success"])
        self.assertEqual(self.call("list")["data"]["tickets"], [])

    def test_unavailable_core_refuses_instead_of_crashing(self):
        mcp.mcp_core.tickets = None
        r = self.call("list")
        self.assertFalse(r["success"])
        self.assertIn("unavailable", r["message"])

    def test_the_stores_cannot_be_forged_through_write_file(self):
        # write_file may not create a pre-approved ticket, a lease, a candidate or an event line
        mcp.CODE_ROOT = self.tmp
        shutil.copy(str(CODE / "protected_paths.json"), str(self.tmp / "protected_paths.json"))
        mcp.ALLOW_ROOTS = [self.tmp]
        for rel in ("workspace/skill-observations/tickets/0001.json", "workspace/skill-observations/tickets/author.lease",
                    "workspace/skill-observations/candidates.jsonl", "sessions/s1/events.jsonl"):
            r = mcp.call_tool("write_file", {"path": str(self.tmp / "data" / rel), "content": "{}"})
            self.assertIn("protected", r["message"], rel)
        # ... while the rest of the same directories stay writable
        self.assertTrue(mcp.call_tool("write_file", {"path": str(self.tmp / "data" / "sessions/s1/meta.json"), "content": "{}"})["success"])


class EntryPointsTest(unittest.TestCase):
    """The server is started as a script (chatbot-ctl.sh does), so the entry points are tested as real processes on a
    free port with an empty HOME: they must come up, list the plugin's tools and answer a plugin tool."""

    @staticmethod
    def free_port():
        import socket
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            return sk.getsockname()[1]

    def rpc(self, port, method, params=None):
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d/mcp" % port, method="POST",
                                     data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))["result"]

    def check_entry(self, script):
        import subprocess
        import time
        import urllib.request
        home = tempfile.mkdtemp()
        port = self.free_port()
        env = dict(os.environ, HOME=home, NAS_MCP_PORT=str(port))
        proc = subprocess.Popen([sys.executable, str(CODE / script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(75):
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=1).read()
                    break
                except Exception:
                    if proc.poll() is not None:
                        self.fail("%s exited: %s" % (script, proc.stderr.read().decode("utf-8", "replace")[-800:]))
                    time.sleep(0.2)
            else:
                self.fail("%s did not come up" % script)
            names = {t["name"] for t in self.rpc(port, "tools/list")["tools"]}
            self.assertTrue({"read_file", "write_file", "run_command", "memory", "observation", "ticket"} <= names, names)
            if mcp.HOST_PLUGIN:
                self.assertTrue({"ping_nas", "list_services", "service_ctl"} <= names, names)
                out = json.loads(self.rpc(port, "tools/call", {"name": "ping_nas", "arguments": {}})["content"][0]["text"])
                self.assertEqual((out["success"], out["data"]["port"]), (True, port))  # the plugin sees THIS server's module
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            proc.stdout.close()
            proc.stderr.close()

    def test_the_server_script_comes_up_and_serves_the_plugin(self):
        self.check_entry("mcp_server.py")

    def test_the_control_script_starts_the_server_by_its_real_name(self):
        ctl = (CODE / "chatbot-ctl.sh").read_text(encoding="utf-8")
        self.assertIn('python3 "$CODE/mcp_server.py"', ctl)
        self.assertNotIn("nas_mcp.py", ctl)
        self.assertTrue((CODE / "mcp_server.py").is_file())
        self.assertFalse((CODE / "nas_mcp.py").exists(), "the compatibility shim was removed once the control script moved")


class ReadSideTest(Base):
    def test_read_file_and_clamp(self):
        (self.tmp / "a.txt").write_text("abcdef", encoding="utf-8")
        r = mcp.call_tool("read_file", {"path": str(self.tmp / "a.txt"), "max_bytes": 3})
        self.assertTrue(r["success"])
        self.assertEqual((r["data"]["content"], r["data"]["truncated"]), ("abc", True))

    def test_read_file_scrubs_secret_lines_and_blocks_secret_names(self):
        (self.tmp / "a.txt").write_text("ok\nAuthorization: Bearer abc\n", encoding="utf-8")
        (self.tmp / ".env").write_text("K=V", encoding="utf-8")
        r = mcp.call_tool("read_file", {"path": str(self.tmp / "a.txt")})
        self.assertEqual(r["data"]["content"], "ok\n[redacted]")
        self.assertFalse(mcp.call_tool("read_file", {"path": str(self.tmp / ".env")})["success"])

    def test_read_outside_roots_is_refused(self):
        self.assertFalse(mcp.call_tool("read_file", {"path": "/etc/hostname"})["success"])
        self.assertFalse(mcp.call_tool("list_dir", {"path": "/etc"})["success"])

    def test_list_dir_hides_secret_names(self):
        (self.tmp / "a.txt").write_text("x", encoding="utf-8")
        (self.tmp / "secret.txt").write_text("x", encoding="utf-8")
        names = [e["name"] for e in mcp.call_tool("list_dir", {"path": str(self.tmp)})["data"]["entries"]]
        self.assertEqual(names, ["a.txt"])

    def test_search_text_finds_lines(self):
        (self.tmp / "a.md").write_text("one\nneedle here\n", encoding="utf-8")
        r = mcp.call_tool("search_text", {"path": str(self.tmp), "pattern": "needle"})
        self.assertEqual([(h["line"], h["text"]) for h in r["data"]["hits"]], [(2, "needle here")])
        self.assertFalse(mcp.call_tool("search_text", {"path": str(self.tmp), "pattern": "("})["success"])


class ToolSurfaceTest(unittest.TestCase):
    def test_core_tools_are_listed_and_unknown_tool_fails(self):
        names = {t["name"] for t in mcp.tool_defs()}
        self.assertTrue({"ping_nas", "list_services", "service_ctl", "list_dir", "read_file",
                         "write_file", "run_command", "search_text"} <= names)
        self.assertFalse(mcp.call_tool("no_such_tool", {})["success"])
        self.assertTrue(mcp.call_tool("ping_nas", {})["success"])

    def test_the_cores_tools_come_from_the_adapter_module_exactly_once(self):
        names = [t["name"] for t in mcp.tool_defs()]
        for tool in mcp.mcp_core.NAMES:
            self.assertEqual(names.count(tool), 1, tool)

    def test_a_server_without_the_adapter_module_just_lacks_those_tools(self):
        saved = mcp.mcp_core
        mcp.mcp_core = None
        try:
            names = {t["name"] for t in mcp.tool_defs()}
            self.assertTrue({"read_file", "write_file", "run_command"} <= names)
            self.assertFalse(names & set(saved.NAMES))
            for tool in saved.NAMES:
                r = mcp.call_tool(tool, {"action": "list"})
                self.assertEqual((r["success"], r["message"]), (False, "unknown tool: " + tool))
            self.assertTrue(mcp.call_tool("ping_nas", {})["success"])
        finally:
            mcp.mcp_core = saved

    def test_the_server_no_longer_carries_the_adapters_logic(self):
        src = Path(mcp.__file__).read_text(encoding="utf-8")
        for gone in ("memory_store", "observations.", "tickets.", "OBSERVE_RECENT_LIMIT", "_memory_dir", "_observation_root"):
            self.assertNotIn(gone, src, gone)
        self.assertLess(len(src.splitlines()), 700)

    def test_the_machine_specific_tools_come_from_the_plugin_and_the_server_has_none_of_its_own(self):
        if not mcp.HOST_PLUGIN:
            self.skipTest("no host plugin")
        plugin_tools = {t["name"] for t in mcp.HOST_PLUGIN.EXTRA_TOOL_DEFS}
        self.assertTrue({"ping_nas", "list_services", "service_ctl"} <= plugin_tools)
        names = [t["name"] for t in mcp.tool_defs()]
        for tool in ("ping_nas", "list_services", "service_ctl"):
            self.assertEqual(names.count(tool), 1, tool)
        for gone in ("SERVICE_CTLS", "_service_ctls", "PORT_CHAT_HINT"):
            self.assertFalse(hasattr(mcp, gone), gone)

    def test_a_server_without_the_plugin_serves_only_the_generic_tools_and_the_core_adapters(self):
        saved = mcp.HOST_PLUGIN
        mcp.HOST_PLUGIN = None
        try:
            names = {t["name"] for t in mcp.tool_defs()}
            self.assertEqual(names, {"list_dir", "read_file", "write_file", "run_command", "search_text"} | set(mcp.mcp_core.NAMES))
            for tool in ("ping_nas", "list_services", "service_ctl"):
                r = mcp.call_tool(tool, {})
                self.assertEqual((r["success"], r["message"]), (False, "unknown tool: " + tool))
        finally:
            mcp.HOST_PLUGIN = saved

    def test_the_plugin_reaches_the_server_through_its_module_so_a_fake_run_reaches_it_too(self):
        if not mcp.HOST_PLUGIN:
            self.skipTest("no host plugin")
        import re
        src = Path(mcp.HOST_PLUGIN.__file__).read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?<![.\w])_run\(", src), [], "a bare _run( call would bind the real one")
        self.assertIn("_srv._run(", src)

    def test_tool_definitions_stay_json_serialisable(self):
        json.dumps(mcp.tool_defs())


if __name__ == "__main__":
    unittest.main()
