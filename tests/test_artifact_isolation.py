"""Unit tests for artifact isolation (ticket #575):
- 1:1 sessions collect only their own artifacts and predecessor_session_id chain artifacts.
- Global workspace/artifacts and legacy ARTIFACTS_CACHE are no longer leaked into sessions.
- Group room artifacts are isolated per room (DATA / 'rooms' / rid / 'artifacts').
- Room artifacts endpoint GET /api/rooms/<rid>/artifacts and route_sessions.room_artifacts support.

Run: python3 -m unittest tests.test_artifact_isolation (from services/chatbot)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import characters as C
import room_chat as RC
import route_sessions as RS
import session as S


class TestArtifactIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir(parents=True)
        self.sessions_dir = self.tmp / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.data_dir = self.tmp / "data"
        self.data_dir.mkdir(parents=True)
        self.rooms_dir = self.data_dir / "rooms"
        self.rooms_dir.mkdir(parents=True)
        self.cache_dir = self.tmp / "cache"
        self.cache_dir.mkdir(parents=True)

        self._saved_sessions = S.SESSIONS
        self._saved_ws = S.WORKSPACE
        self._saved_data = S.DATA
        self._saved_cache = getattr(S, "ARTIFACTS_CACHE", None)

        S.SESSIONS = self.sessions_dir
        S.WORKSPACE = self.ws
        S.DATA = self.data_dir
        S.ARTIFACTS_CACHE = self.cache_dir

        self.patches = [
            mock.patch.object(RC, "_dir", lambda: self.rooms_dir),
            mock.patch.object(C, "_default_ws", return_value=self.ws),
        ]
        for p in self.patches:
            p.start()

        # Setup characters for rooms
        self.c1, self.c2 = sorted(C.new_id() for _ in range(2))
        for cid, name in ((self.c1, "Chara1"), (self.c2, "Chara2")):
            C.save(cid, C.new_card(name), self.ws)
        C.save_team({"default": self.c1, "members": {self.c1: [], self.c2: []}}, self.ws)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        S.SESSIONS = self._saved_sessions
        S.WORKSPACE = self._saved_ws
        S.DATA = self._saved_data
        if self._saved_cache is not None:
            S.ARTIFACTS_CACHE = self._saved_cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_session(self, sid: str, predecessor_id: str = "") -> S.AgentSession:
        sdir = self.sessions_dir / sid
        sdir.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": sid,
            "provider": "agy",
            "model": "gemini-2.5-flash",
            "predecessor_session_id": predecessor_id,
        }
        (sdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        sess = S.AgentSession(sid, provider="agy")
        sess.predecessor_session_id = predecessor_id
        return sess

    def test_session_artifacts_isolated_between_sessions(self):
        s1 = self._create_session("sess_1")
        s2 = self._create_session("sess_2")

        a1_dir = self.sessions_dir / "sess_1" / "artifacts"
        a1_dir.mkdir(parents=True, exist_ok=True)
        (a1_dir / "art1.png").write_bytes(b"PNG1")

        a2_dir = self.sessions_dir / "sess_2" / "artifacts"
        a2_dir.mkdir(parents=True, exist_ok=True)
        (a2_dir / "art2.png").write_bytes(b"PNG2")

        arts1 = s1.get_artifacts()
        names1 = {a["name"] for a in arts1}
        self.assertIn("art1.png", names1)
        self.assertNotIn("art2.png", names1)
        self.assertTrue(any(a["url"].startswith("/artifacts/sess_1/") for a in arts1))

        arts2 = s2.get_artifacts()
        names2 = {a["name"] for a in arts2}
        self.assertIn("art2.png", names2)
        self.assertNotIn("art1.png", names2)
        self.assertTrue(any(a["url"].startswith("/artifacts/sess_2/") for a in arts2))

    def test_predecessor_session_chain_artifacts_included(self):
        s1 = self._create_session("sess_ancestor")
        s2 = self._create_session("sess_parent", predecessor_id="sess_ancestor")
        s3 = self._create_session("sess_child", predecessor_id="sess_parent")

        (self.sessions_dir / "sess_ancestor" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "sess_parent" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "sess_child" / "artifacts").mkdir(parents=True, exist_ok=True)

        (self.sessions_dir / "sess_ancestor" / "artifacts" / "doc_ancestor.md").write_text("# A", encoding="utf-8")
        (self.sessions_dir / "sess_parent" / "artifacts" / "code_parent.py").write_text("print(1)", encoding="utf-8")
        (self.sessions_dir / "sess_child" / "artifacts" / "img_child.png").write_bytes(b"PNG3")

        child_arts = s3.get_artifacts()
        child_names = {a["name"] for a in child_arts}
        self.assertEqual(child_names, {"doc_ancestor.md", "code_parent.py", "img_child.png"})

        # URL prefixes match original owning sessions
        url_map = {a["name"]: a["url"] for a in child_arts}
        self.assertIn("/artifacts/sess_ancestor/", url_map["doc_ancestor.md"])
        self.assertIn("/artifacts/sess_parent/", url_map["code_parent.py"])
        self.assertIn("/artifacts/sess_child/", url_map["img_child.png"])

        parent_arts = s2.get_artifacts()
        parent_names = {a["name"] for a in parent_arts}
        self.assertEqual(parent_names, {"doc_ancestor.md", "code_parent.py"})

        ancestor_arts = s1.get_artifacts()
        ancestor_names = {a["name"] for a in ancestor_arts}
        self.assertEqual(ancestor_names, {"doc_ancestor.md"})

    def test_predecessor_chain_cycle_protection(self):
        s1 = self._create_session("loop_1", predecessor_id="loop_2")
        self._create_session("loop_2", predecessor_id="loop_1")

        (self.sessions_dir / "loop_1" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "loop_1" / "artifacts" / "file1.txt").write_text("loop", encoding="utf-8")

        # Must not hang or raise RecursionError
        arts = s1.get_artifacts()
        names = {a["name"] for a in arts}
        self.assertIn("file1.txt", names)

    def test_global_workspace_and_cache_not_scanned(self):
        s = self._create_session("clean_sess")
        (self.ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.ws / "artifacts" / "leaked_ws.png").write_bytes(b"WS")
        (self.cache_dir / "leaked_cache.png").write_bytes(b"CACHE")

        arts = s.get_artifacts()
        names = {a["name"] for a in arts}
        self.assertNotIn("leaked_ws.png", names)
        self.assertNotIn("leaked_cache.png", names)

    def test_room_artifacts_isolation(self):
        r1 = RC.create("Test Room 1", [self.c1, self.c2])
        r2 = RC.create("Test Room 2", [self.c1, self.c2])

        r1_dir = RC.artifacts_dir(r1["id"])
        r1_dir.mkdir(parents=True, exist_ok=True)
        (r1_dir / "room1_art.png").write_bytes(b"ROOM1")

        r2_dir = RC.artifacts_dir(r2["id"])
        r2_dir.mkdir(parents=True, exist_ok=True)
        (r2_dir / "room2_art.png").write_bytes(b"ROOM2")

        arts1 = RC.artifacts(r1["id"])
        names1 = {a["name"] for a in arts1}
        self.assertIn("room1_art.png", names1)
        self.assertNotIn("room2_art.png", names1)
        self.assertTrue(any("/api/file/raw" in a["url"] for a in arts1))

        arts2 = RC.artifacts(r2["id"])
        names2 = {a["name"] for a in arts2}
        self.assertIn("room2_art.png", names2)
        self.assertNotIn("room1_art.png", names2)

        # 1:1 sessions do not see room artifacts
        s = self._create_session("sess_alone")
        sess_arts = s.get_artifacts()
        sess_names = {a["name"] for a in sess_arts}
        self.assertNotIn("room1_art.png", sess_names)
        self.assertNotIn("room2_art.png", sess_names)

    def test_room_artifacts_api(self):
        r = RC.create("API Room", [self.c1, self.c2])
        r_dir = RC.artifacts_dir(r["id"])
        r_dir.mkdir(parents=True, exist_ok=True)
        (r_dir / "chart.png").write_bytes(b"CHART")

        # GET /api/rooms/<rid>/artifacts
        res = RC.api("GET", f"/api/rooms/{r['id']}/artifacts", None)
        self.assertIsNotNone(res)
        code, body = res
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        names = {a["name"] for a in body["artifacts"]}
        self.assertIn("chart.png", names)

        # Non-existent room
        res_404 = RC.api("GET", "/api/rooms/room_999999999999/artifacts", None)
        self.assertIsNotNone(res_404)
        self.assertEqual(res_404[0], 404)

    def test_route_sessions_room_artifacts(self):
        r = RC.create("Route Room", [self.c1, self.c2])
        r_dir = RC.artifacts_dir(r["id"])
        r_dir.mkdir(parents=True, exist_ok=True)
        (r_dir / "report.pdf").write_bytes(b"%PDF")

        # Direct string call
        res = RS.room_artifacts(r["id"])
        self.assertIn("report.pdf", {a["name"] for a in res["artifacts"]})

        # Fake Req call
        class FakeReq:
            def __init__(self, path):
                self.path = path
                self.arg = path.split("/")[3]
            def qs(self):
                return {}
            def json(self, payload, code=200):
                return code, payload
            def send(self, code, body, ct):
                return code, body

        fake_req = FakeReq(f"/api/rooms/{r['id']}/artifacts")
        code, payload = RS.room_artifacts(fake_req)
        self.assertEqual(code, 200)
        self.assertIn("report.pdf", {a["name"] for a in payload["artifacts"]})


if __name__ == "__main__":
    unittest.main()
