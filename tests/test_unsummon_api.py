"""Homecoming / unsummon REST (sp/N). Fixtures only -- never live characters.

Run: python3 -m unittest tests.test_unsummon_api
"""
import json
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import characters  # noqa: E402
import host_config  # noqa: E402
import platform_compat  # noqa: E402
import unsummon_api  # noqa: E402


class UnsummonApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.dialogs = self.tmp / "dialogs"
        self.dialogs.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _make(self, name):
        cid = characters.new_id()
        characters.save(cid, characters.new_card(name), self.ws)
        return cid

    def test_steps_cover_confirm_only(self):
        spec = unsummon_api.public_spec()
        self.assertEqual([s["id"] for s in spec["steps"]], ["confirm"])
        self.assertIn("confirm_btn", spec)

    def test_confirm_zips_dialogs_then_moves(self):
        keep = self._make("Keep")
        go = self._make("Go")
        characters.save_team({"default": go, "members": {keep: [], go: []}}, self.ws)
        (self.ws / "characters" / go / "relationship.md").write_text("secret bond", encoding="utf-8")
        mine = self.dialogs / ("dm_%s_other.log.jsonl" % go)
        mine.write_text('{"t":1}\n', encoding="utf-8")
        other = self.dialogs / ("dm_%s_x.log.jsonl" % keep)
        other.write_text('{"t":2}\n', encoding="utf-8")
        (self.dialogs / "noise.sqlite").write_bytes(b"SQLite")
        (self.dialogs / "positions.json").write_text("{}", encoding="utf-8")
        status, payload = unsummon_api.unsummon(go, {"confirm": True}, ws=self.ws, dialogs=self.dialogs)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        archive = Path(payload["archive"])
        self.assertTrue(archive.is_file())
        self.assertTrue(archive.name.endswith(".zip"))
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
            self.assertIn("character/card.json", names)
            self.assertIn("character/relationship.md", names)
            self.assertIn("dialogs/" + mine.name, names)
            self.assertNotIn("dialogs/" + other.name, names)
            self.assertFalse(any("sessions/" in n for n in names))
            self.assertFalse(any(n.endswith(".sqlite") for n in names))
            self.assertIsNone(zf.testzip())
        self.assertFalse((self.ws / "characters" / go).exists())
        self.assertFalse(mine.exists())
        self.assertTrue(other.exists())
        side = archive.with_suffix("")
        self.assertTrue((side / "character" / "card.json").is_file())
        self.assertTrue((side / "dialogs" / mine.name).is_file())
        self.assertTrue((self.ws / "characters" / keep / "card.json").is_file())
        man = (self.tmp / "archive" / "characters" / "manifest.jsonl").read_text(encoding="utf-8")
        row = json.loads(man.strip().splitlines()[-1])
        self.assertEqual(row["id"], go)
        self.assertTrue(row["archived"])
        self.assertEqual(row["dialogs"], [mine.name])
        team = json.loads((self.ws / "team.json").read_text(encoding="utf-8"))
        self.assertEqual(team["default"], keep)
        self.assertNotIn(go, team["members"])

    def test_refuses_without_confirm_and_last_character(self):
        only = self._make("Only")
        characters.save_team({"default": only, "members": {only: []}}, self.ws)
        status, payload = unsummon_api.unsummon(only, {}, ws=self.ws, dialogs=self.dialogs)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "confirm required")
        status, payload = unsummon_api.unsummon(only, {"confirm": True}, ws=self.ws, dialogs=self.dialogs)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "last character")
        self.assertTrue((self.ws / "characters" / only / "card.json").is_file())

    def test_refuses_bad_id_and_missing(self):
        self.assertEqual(unsummon_api.unsummon("../x", {"confirm": True}, ws=self.ws)[0], 400)
        missing = characters.new_id()
        self.assertEqual(unsummon_api.unsummon(missing, {"confirm": True}, ws=self.ws)[0], 404)


class UnsummonRouteTest(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.orig = host_config.WORKSPACE
        self.orig_server = server.WORKSPACE
        host_config.WORKSPACE = self.ws
        server.WORKSPACE = self.ws
        self.httpd = platform_compat.http_server(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        host_config.WORKSPACE = self.orig
        self.server.WORKSPACE = self.orig_server
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _req(self, method, path, body=None, origin=True):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = "http://127.0.0.1:%d" % self.port
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def _make(self, name):
        cid = characters.new_id()
        characters.save(cid, characters.new_card(name), self.ws)
        return cid

    def test_routes_and_post(self):
        post = [p for p, _ in self.server.POST_ROUTES]
        get = [p for p, _ in self.server.GET_ROUTES]
        self.assertIn("/api/characters/*/unsummon", post)
        self.assertIn("/api/unsummon", get)
        status, raw = self._req("GET", "/api/unsummon")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["menu"], "소환 해제")
        keep = self._make("Keep")
        go = self._make("Go")
        characters.save_team({"default": keep, "members": {keep: [], go: []}}, self.ws)
        denied, _ = self._req("POST", "/api/characters/%s/unsummon" % go, {"confirm": True}, origin=False)
        self.assertEqual(denied, 403)
        status, raw = self._req("POST", "/api/characters/%s/unsummon" % go, {"confirm": True})
        self.assertEqual(status, 200)
        payload = json.loads(raw.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertTrue(str(payload["archive"]).endswith(".zip"))
        self.assertFalse((self.ws / "characters" / go).exists())
