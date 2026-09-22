"""Core standalone check (docs/plans/recursive-self-evolution.md §4.6, P3-2): with every layer absent the core still
collects observations, reviews them, runs tickets with their budget and single-author lock, checks protected paths,
keeps long-term memory and runs the lifecycle helpers.

"Layers" are all top-level modules that are not listed in core_modules.json (skills, tool server, HTTP server,
provider adapters, ...). The scenario runs in a fresh process on a temp instance that has only the core modules and
their data files, with imports of every layer module forbidden, an empty HOME and no PATH. A core module that reaches
for a layer fails here, at the import.
Run: python3 -m unittest tests.test_core_standalone  (from services/chatbot)
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
CORE = json.loads((CODE / "core_modules.json").read_text(encoding="utf-8"))["core"]
DATA_FILES = ("protected_paths.json", "observation_signals.json", "core_modules.json")
LAYERS = sorted(p.stem for p in CODE.glob("*.py") if p.stem not in CORE)

SCENARIO = r'''
import importlib.abc, json, os, sys, time
from pathlib import Path

root, data, layers = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
sys.path.insert(0, str(root))


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in layers:
            raise ImportError("layer module imported by the core: " + fullname)


sys.meta_path.insert(0, Block())
import evolution, observations, tickets, memory_store

obs = data / "workspace" / "skill-observations"
mem = data / "workspace" / "memory"
done = []


def step(name):
    done.append(name)
    print("PASS " + name, flush=True)


def refused(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    return False


# 1. protected paths: data, not code; fail closed without the registry
assert evolution.is_protected(root, root / "server.py") and evolution.is_protected(root, root / "anything.py")
assert not evolution.is_protected(root, root / "static" / "app.js")           # this instance's explicit exception
assert not evolution.is_protected(root, data / "workspace" / "notes.md")
assert evolution.is_protected(data, data / "workspace" / "notes.md")          # no registry there: everything is protected
step("protected paths")

# 2. observation collection: what the host hands to on_turn_end
assert evolution.on_turn_end(root, obs, "s1", "claude", "result", [], "안녕") == []
assert evolution.on_turn_end(root, obs, "s1", "claude", "result", [], "왜 안돼?") == ["correction"]
assert evolution.on_turn_end(root, obs, "s1", "claude", "process_died", ["error"], "이거 해줘") == ["process_died"]
assert evolution.on_turn_end(root, obs, "s1", "claude", "steer", [], "이것도") == []
assert len((obs / "candidates.jsonl").read_text(encoding="utf-8").splitlines()) == 2
step("observation collection")

# 3. observation life cycle: record, review, resolve, archive, mark reviewed
path = observations.add(obs, "Steer loses the queue", "After a steer the queue was empty.", "session", recent_limit=10)
assert [o["status"] for o in observations.scan(obs)] == ["open"]
d = observations.digest(obs)
assert (len(d["open"]), d["unreviewed_candidates"], d["last_review"]) == (1, 2, "never")
assert refused(observations.ObservationError, observations.resolve, obs, 1, "actioned", "")
assert observations.resolve(obs, 1, "actioned", "fixed in session.py")["status"] == "actioned"
assert observations.mark_reviewed(obs, "read 1 observation, closed it") == time.strftime("%Y-%m-%d")
assert observations.digest(obs)["unreviewed_candidates"] == 0
step("observation life cycle")

# 4. tickets: real evidence only, approval is not the agent's, budget, one author
epoch = json.loads((obs / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])["epoch"]
(data / "sessions" / "s1").mkdir(parents=True, exist_ok=True)
(data / "sessions" / "s1" / "events.jsonl").write_text('{"event":"a"}\n{"event":"b"}\n', encoding="utf-8")
assert refused(tickets.TicketError, tickets.propose, data, "t", "x", ["candidate:1.5"])
t1, _ = tickets.propose(data, "Steer queue", "session.py: steer", ["candidate:%s" % epoch, "event:s1#2"])
_, merged = tickets.propose(data, "Steer queue again", "SESSION.py: steer", ["event:s1#1"])
assert merged
assert refused(tickets.TicketError, tickets.approve, data, t1["id"])                      # no one said who is asking
tickets.approve(data, t1["id"], operator=tickets.OPERATOR_CONFIRMED)
t2, _ = tickets.propose(data, "Other", "other target", ["event:s1#1"])
tickets.approve(data, t2["id"], operator=tickets.OPERATOR_CONFIRMED)
c1 = tickets.claim(data, t1["id"])
assert refused(tickets.TicketError, tickets.claim, data, t2["id"])                        # busy: no waiting
assert tickets.release(data, t1["id"], c1["token"], "gate_failed")["ticket"]["status"] == "approved"
c2 = tickets.claim(data, t1["id"])
assert "change the approach" in tickets.release(data, t1["id"], c2["token"], "gate_failed")["advice"]
c3 = tickets.claim(data, t1["id"])
last = tickets.release(data, t1["id"], c3["token"], "failed")["ticket"]
assert (last["status"], last["closed_reason"], last["attempts"]) == ("wontfix", "needs-human", 3)
assert refused(tickets.TicketError, tickets.claim, data, t1["id"])
c = tickets.claim(data, t2["id"])                                                         # the lock was freed
tickets.release(data, t2["id"], c["token"], "done")
step("tickets budget and lock")

# 5. long-term memory
assert memory_store.add(mem, "[2020-01-01] 커피는 아메리카노")[0] == "added"
assert memory_store.add(mem, "커피는 아메리카노")[0] == "duplicate"
memory_store.add(mem, "커피 주문은 오전에")
assert refused(memory_store.MemoryRefused, memory_store.forget, mem, "커피")               # two lines: refused
assert len(memory_store.forget(mem, "커피", all_matches=True)) == 2
assert (mem / "MEMORY.md.bak").exists() and memory_store.search(mem, "커피") == []
step("long-term memory")

# 6. lifecycle helpers that the control script only calls into
lock = data / "lifecycle.lock"
code = "import os; raise SystemExit(0 if os.environ.get('CHATBOT_LOCK_PPID') else 3)"
assert evolution.run_locked(lock, 0, [sys.executable, "-c", code]) == 0
held = evolution.acquire_lock(lock, 0)
assert evolution.run_locked(lock, 0, [sys.executable, "-c", "print('never')"]) == 0       # busy: skipped, not run
held.close()
flag = data / "maintenance.flag"
assert evolution.maintenance_note(flag) is None
flag.write_text("", encoding="utf-8")
assert evolution.maintenance_note(flag) is not None
assert evolution.write_manifest(root) >= 4                                               # the core files themselves
assert evolution.check_manifest(root)[0] == "ok"
(root / "evolution.py").write_text((root / "evolution.py").read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
assert evolution.check_manifest(root)[0] == "differs"
step("lifecycle helpers")

# 7. nothing but the core was loaded
loaded = sorted(m for m in sys.modules if m in layers)
assert loaded == [], loaded
step("no layer module loaded")
print("RESULT " + json.dumps(done))
'''

EXPECTED_STEPS = ["protected paths", "observation collection", "observation life cycle", "tickets budget and lock",
                  "long-term memory", "lifecycle helpers", "no layer module loaded"]


class Instance:
    """A temp instance: only the core modules and their data files, no skills, no hooks, no servers."""

    def __init__(self, mutate=None):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.root = self.tmp / "code"
        self.data = self.tmp / "data"
        self.home = self.tmp / "home"
        self.root.mkdir()
        for d in (self.home, self.data / "workspace" / "skill-observations", self.data / "workspace" / "memory",
                  self.data / "sessions"):
            d.mkdir(parents=True)
        for name in CORE:
            shutil.copy(str(CODE / (name + ".py")), str(self.root / (name + ".py")))
        for name in DATA_FILES:
            shutil.copy(str(CODE / name), str(self.root / name))
        if mutate:
            mutate(self.root)
        self.script = self.tmp / "scenario.py"
        self.script.write_text(SCENARIO, encoding="utf-8")

    def run(self):
        env = {"HOME": str(self.home), "LANG": "C.UTF-8", "PATH": "/nonexistent"}  # no ~/.agents, no watchdog, no tools
        return subprocess.run([sys.executable, str(self.script), str(self.root), str(self.data), json.dumps(LAYERS)],
                              cwd=str(self.tmp), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=120)


class StandaloneTest(unittest.TestCase):
    def test_the_core_does_its_job_with_every_layer_absent_and_forbidden(self):
        r = Instance().run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        result = [l for l in r.stdout.splitlines() if l.startswith("RESULT ")]
        self.assertEqual(json.loads(result[0][7:]), EXPECTED_STEPS)

    def test_the_instance_really_has_no_layers(self):
        inst = Instance()
        self.assertEqual(sorted(p.stem for p in inst.root.glob("*.py")), sorted(CORE))
        self.assertFalse((inst.data / "workspace" / ".agents").exists())
        self.assertGreater(len(LAYERS), 10)  # the check has something to forbid

    def test_a_core_module_that_reaches_for_a_layer_fails_the_check(self):
        for layer in ("session", "mcp_server", "mcp_core", "host_config", "server"):
            def mutate(root, layer=layer):
                p = root / "tickets.py"
                p.write_text(p.read_text(encoding="utf-8").replace("import evolution\n", "import evolution\nimport %s\n" % layer, 1),
                             encoding="utf-8")
            r = Instance(mutate).run()
            self.assertNotEqual(r.returncode, 0, layer)
            self.assertIn("layer module imported by the core: " + layer, r.stderr)

    def test_a_broken_core_behaviour_fails_the_check_too(self):
        def mutate(root):  # the ticket budget quietly disappears
            p = root / "tickets.py"
            s = p.read_text(encoding="utf-8")
            assert "MAX_ATTEMPTS = 3" in s
            p.write_text(s.replace("MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 300"), encoding="utf-8")
        r = Instance(mutate).run()
        self.assertNotEqual(r.returncode, 0)


class StaticBoundaryTest(unittest.TestCase):
    def imports_of(self, name):
        tree = ast.parse((CODE / (name + ".py")).read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                found.add((node.module or "").split(".")[0])
        return found

    def test_the_core_list_names_real_modules(self):
        self.assertGreaterEqual(len(CORE), 4)
        for name in CORE:
            self.assertTrue((CODE / (name + ".py")).is_file(), name)

    def test_core_modules_import_only_the_standard_library_and_each_other(self):
        for name in CORE:
            reached = self.imports_of(name) & set(LAYERS)
            self.assertEqual(reached, set(), "%s reaches for a layer" % name)

    def test_the_data_files_that_define_the_check_are_write_protected(self):
        import evolution
        for name in ("core_modules.json", "bundle_budget.json", "protected_paths.json", "observation_signals.json"):
            self.assertTrue(evolution.is_protected(CODE, CODE / name), name)


if __name__ == "__main__":
    unittest.main()
