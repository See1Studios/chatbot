"""evt/D (event_react.py): a character speaks first about the events the operator turned on -- ending work phases,
restarts -- in its work session, as a host notice. Off by default; at most per_hour per character; none in quiet
hours or while any conversation runs; an event spoken about is not told again before the next turn.
Run: python3 -m unittest tests.test_event_react  (from services/chatbot)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import event_react as R  # noqa: E402
import events as E  # noqa: E402

NOON = time.mktime((2026, 9, 30, 12, 0, 0, 0, 0, -1))
NIGHT = time.mktime((2026, 9, 30, 3, 0, 0, 0, 0, -1))


class FakeSession:
    def __init__(self, sid):
        self.sid, self.busy, self.sent, self.done = sid, False, [], threading.Event()
        self.level = "ok"

    def weight(self):
        return {"level": self.level}

    def _send_direct(self, text, notice=False):
        self.sent.append((text, notice))
        self.done.set()


class FakeReg:
    def __init__(self, sessions):
        self.lock = threading.Lock()
        self.sessions = {s.sid: s for s in sessions.values()}
        self.by_char = sessions

    def _newest(self, mode, character):
        return self.by_char.get(character) if mode == "work" else None


class Reactions(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CHATBOT_EVENTS_DIR": str(self.dir / "ev")})
        self.env.start()
        self.clock = NOON                       # the mailbox's clock: events are stamped at test time, not wall time
        self.time = mock.patch.object(E, "time", SimpleNamespace(time=lambda: self.clock))
        self.time.start()
        self.kit = FakeSession("s-kit")
        self.reg = FakeReg({"kit": self.kit})
        self.cfg = R.clean({"auto": ["work.phase"], "per_hour": 2, "quiet": [0, 8]})
        self.note = mock.patch.object(R, "_note", lambda evts, cid: "work %s" % ",".join(e["payload"]["phase"] for e in evts))
        self.note.start()
        R.react_once(self.reg, now=NOON, cfg=self.cfg, characters_list=["kit"])   # first sight: sets the cursor

    def tearDown(self):
        self.note.stop()
        self.time.stop()
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def phase(self, phase, to=("kit",)):
        return E.publish("work.phase", list(to), subject="7", phase=phase, title="t")

    def once(self, now=NOON, cfg=None):
        out = R.react_once(self.reg, now=now, cfg=cfg or self.cfg, characters_list=["kit"])
        if out:
            self.kit.done.wait(5)
        return out

    def test_off_by_default_and_history_is_never_reacted_to(self):
        self.assertEqual(R.clean({})["auto"], [])
        self.assertEqual(R.load_config(self.dir)["auto"], [], "no settings file: off")
        self.phase("done")
        self.assertEqual(R.react_once(self.reg, now=NOON, cfg=R.clean({}), characters_list=["kit"]), [])

    def test_an_ending_phase_makes_the_worker_speak_first_as_a_notice(self):
        self.phase("writing")
        self.assertEqual(self.once(), [], "a phase that is not an ending is only told before the next turn")
        e = self.phase("done")
        sent = self.once()
        self.assertEqual([s["events"] for s in sent], [[e["id"]]])
        text, notice = self.kit.sent[0]
        self.assertTrue(notice, "a host notice, not a user bubble")
        self.assertIn("work done", text)
        self.assertIn("the user did not write this", text)
        self.assertEqual(E.cursor("s-kit"), e["id"], "told now: the next turn does not tell it again")

    def test_limits_rate_quiet_hours_and_a_running_conversation(self):
        for p in ("done", "failed"):
            self.phase(p)
            self.once()
            self.kit.done.clear()
        self.clock = NOON + 1800
        self.phase("gate_failed")
        self.assertEqual(self.once(), [], "per_hour reached")
        self.assertEqual(self.once(now=NOON + 3601)[0]["character"], "kit", "an hour later it goes")
        self.kit.done.clear()
        self.clock = NOON + 86400
        self.phase("done")
        self.assertEqual(self.once(now=NIGHT + 86400), [], "quiet hours: waits")
        self.kit.busy = True
        self.assertEqual(self.once(now=NOON + 86400), [], "someone is talking: waits")
        self.kit.busy = False
        self.assertEqual(len(self.once(now=NOON + 86400)), 1, "then it goes")

    def test_an_event_older_than_the_ttl_is_dropped_not_spoken(self):
        e = self.phase("done")
        with mock.patch.object(E, "_log") as log:
            self.assertEqual(self.once(now=NOON + R.TTL_SEC + 1), [], "stale news: not spoken")
        self.assertIn(mock.call("react.skip", reason="expired", character="kit", n=1), log.call_args_list)
        self.assertEqual(self.kit.sent, [])
        self.assertEqual(E.cursor("react:kit"), e["id"], "the cursor moves past it")
        self.assertEqual(self.once(now=NOON + R.TTL_SEC + 2), [], "and it is not tried again")

    def test_a_heavy_session_is_not_pushed_into(self):
        for level in R.HEAVY:
            self.kit.level = level
            e = self.phase("done")
            with mock.patch.object(E, "_log") as log:
                self.assertEqual(self.once(), [], level)
            self.assertIn(mock.call("react.skip", reason="session_heavy", character="kit", sid="s-kit"),
                          log.call_args_list)
            self.assertEqual(E.cursor("react:kit"), e["id"], "the cursor moves past it")
        self.assertEqual(self.kit.sent, [])
        self.kit.level = "ok"
        self.phase("done")
        self.assertEqual(len(self.once()), 1, "a light session hears it")

    def test_an_event_for_everyone_is_answered_by_the_default_character_alone(self):
        e = E.publish("host.restart", E.ALL, ts=NOON, landed=[])
        cfg = R.clean({"auto": ["host.restart"]})
        self.assertFalse(R._wanted(e, cfg, "kit", "boss"), "not the default: stays quiet")
        self.assertTrue(R._wanted(e, cfg, "boss", "boss"))

    def test_settings_are_cleaned_and_saved_in_the_workspace(self):
        cfg = R.save_config({"auto": ["work.phase", "rm -rf"], "per_hour": 99, "quiet": [25, 1]}, self.dir)
        self.assertEqual(cfg, {"auto": ["work.phase"], "per_hour": 20, "quiet": [0, 8]})
        self.assertEqual(json.loads((self.dir / R.CONFIG_NAME).read_text())["auto"], ["work.phase"])
        self.assertTrue(R._quiet({"quiet": [22, 7]}, time.mktime((2026, 9, 30, 23, 0, 0, 0, 0, -1))))
        self.assertFalse(R._quiet({"quiet": [22, 7]}, NOON))


class Wiring(unittest.TestCase):
    def test_the_server_runs_the_reactor_and_the_team_tab_edits_it(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('__import__("event_react").loop', src)
        import workspace_status as W
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(W, "WORKSPACE", tmp):
            code, body = W.experts_api("PUT", "/api/experts/auto-react", {"auto": ["host.restart"]})
            self.assertEqual((code, body["auto_react"]["auto"]), (200, ["host.restart"]))
            self.assertEqual(W._auto_react()["choices"], list(R.CHOICES))
        shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_the_page_sends_only_the_ticked_choices(self):
        harness = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const document = { getElementById: () => null };
const { autoReactBody } = new Function('document', src + '; return { autoReactBody };')(document);
console.log(JSON.stringify(autoReactBody({ choices: ['work.phase', 'host.restart'] }, { 'work.phase': true }, '3', '0', '8')));
"""
        r = subprocess.run(["node", "-e", harness, str(ROOT / "static" / "app-team.js")], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-1000:])
        self.assertEqual(json.loads(r.stdout.strip()), {"auto": ["work.phase"], "per_hour": 3, "quiet": [0, 8]})


if __name__ == "__main__":
    unittest.main()
