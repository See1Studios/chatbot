"""character-settings cs/A + cs/B: every setting of a character as one schema list; a change is merged into its own
file by the server (the rest of the file stays -- the drawer once wrote an empty card when its read failed), the
previous version is kept first, and a version can be restored.
Run: engine/run-tests.sh test_character_settings
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import characters  # noqa: E402
from character_settings import fields as F  # noqa: E402
from character_settings import store as S  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.ws = self.data / "workspace"
        self.cid = characters.new_id()
        d = self.ws / "characters" / self.cid
        d.mkdir(parents=True)
        (self.ws / "roles" / "lead").mkdir(parents=True)
        (self.ws / "roles" / "art").mkdir(parents=True)
        self.card = {"spec": "chara_card_v2", "spec_version": "2.0",
                     "data": {"name": "Kit", "description": "d", "first_mes": "hello there", "scenario": "s",
                              "mes_example": "<START>", "tags": ["a"],
                              "extensions": {"chatbot": {"brains": {"work": [{"provider": "agy", "model": "m-high"}]},
                                                         "display": {"user_title": "coach"}}}}}
        (d / "card.json").write_text(json.dumps(self.card), encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.data, True)

    def get(self, key):
        return next(f for f in S.read(self.cid, self.ws) if f["key"] == key)

    def versions(self, key):
        return S.versions(self.cid, key, self.ws)


class Read(Base):
    def test_every_field_with_its_tab_type_label_and_value(self):
        fields = S.read(self.cid, self.ws)
        self.assertEqual([f["key"] for f in fields], [f[0] for f in F.FIELDS])
        self.assertEqual({f["tab"] for f in fields}, {"character", "relationship", "settings"})
        self.assertEqual(self.get("card.first_mes")["value"], "hello there")
        self.assertEqual(self.get("display.user_title")["value"], "coach")
        self.assertEqual(self.get("card.name")["label"], {"key": "charset.card.name", "vars": {}})
        self.assertEqual(self.get("brain.work")["default"], {"provider": "agy", "model": "m-high"})
        self.assertEqual(self.get("team.roles")["options"], ["art", "lead"])
        self.assertEqual(self.get("state.threshold")["options"], list(F.THRESHOLD))
        self.assertTrue(self.get("file.private_memory")["sensitive"])

    def test_every_label_has_words_in_both_catalogs(self):
        for lang in ("ko", "en"):
            cat = json.loads((ENGINE.parent / "static" / "i18n" / ("%s.json" % lang)).read_text(encoding="utf-8"))
            self.assertEqual([k for k in F.by_key() if "charset." + k not in cat], [], lang)


class Patch(Base):
    def test_a_change_is_merged_and_the_rest_of_the_card_stays(self):
        out = S.patch(self.cid, {"card.personality": "shy", "display.voice": "v1"}, self.ws)
        self.assertEqual(out, {"changed": ["card.personality", "display.voice"], "errors": {}})
        card = characters.load(self.cid, self.ws)
        self.assertEqual(card["data"]["first_mes"], "hello there", "untouched fields stay")
        self.assertEqual(card["data"]["extensions"]["chatbot"]["brains"]["work"][0]["model"], "m-high")
        self.assertEqual(card["data"]["extensions"]["chatbot"]["display"], {"user_title": "coach", "voice": "v1"})
        self.assertEqual(len(self.versions("card.personality")), 1, "one version kept for one write of the file")

    def test_refused_keys_are_reported_and_the_others_written(self):
        out = S.patch(self.cid, {"card.name": 3, "nope": "x", "state.threshold": "loud", "team.roles": ["ghost"],
                                 "card.tags": ["x", " ", "y"]}, self.ws)
        self.assertEqual(out["changed"], ["card.tags"])
        self.assertEqual(set(out["errors"]), {"card.name", "nope", "state.threshold", "team.roles"})
        self.assertEqual(self.get("card.tags")["value"], ["x", "y"])

    def test_brain_state_roles_and_files(self):
        S.patch(self.cid, {"brain.work": {"provider": "agy", "model": "m-low"}, "state.auto_scene": False,
                           "team.roles": ["art"], "file.private_memory": "- [2026-10-09] x"}, self.ws)
        self.assertEqual(self.get("brain.work")["value"]["model"], "m-low")
        self.assertIs(self.get("state.auto_scene")["value"], False)
        self.assertEqual(self.get("team.roles")["value"], ["art"])
        self.assertEqual(self.get("file.private_memory")["value"], "- [2026-10-09] x")
        S.patch(self.cid, {"brain.work": None}, self.ws)
        self.assertIsNone(self.get("brain.work")["value"], "back to the card's default")

    def test_the_log_names_keys_never_values(self):
        seen = []
        with mock.patch("telemetry.obslog.event", lambda evt, **kw: seen.append((evt, kw))):
            S.patch(self.cid, {"file.private_memory": "secret words"}, self.ws)
        self.assertEqual(seen[-1][0], "character.setting")
        self.assertNotIn("secret", json.dumps(seen[-1][1]))


class Versions(Base):
    def test_a_version_restores_the_file_and_the_restore_is_kept_too(self):
        S.patch(self.cid, {"card.first_mes": "second"}, self.ws)
        S.patch(self.cid, {"card.first_mes": "third"}, self.ws)
        vs = self.versions("card.first_mes")
        self.assertEqual(len(vs), 2)
        oldest = vs[-1]["version"]
        S.restore(self.cid, "card.first_mes", oldest, self.ws)
        self.assertEqual(self.get("card.first_mes")["value"], "hello there")
        self.assertEqual(len(self.versions("card.first_mes")), 3, "the state before the restore is kept")

    def test_only_the_newest_are_kept_and_bad_versions_are_refused(self):
        with mock.patch.object(S, "KEEP", 3):
            for i in range(5):
                S.patch(self.cid, {"card.scenario": "s%d" % i}, self.ws)
        self.assertEqual(len(self.versions("card.scenario")), 3)
        with self.assertRaises(KeyError):
            S.restore(self.cid, "card.scenario", "../../etc", self.ws)
        with self.assertRaises(KeyError):
            S.restore(self.cid, "nope", "1", self.ws)


class Api(unittest.TestCase):
    def test_routes(self):
        self.assertIsNone(S.api("GET", "/api/characters/x/session", None))
        self.assertEqual(S.api("GET", "/api/characters/nope/settings", None)[0], 404)
        self.assertEqual(S.api("PATCH", "/api/characters/nope/settings", {})[0], 404)

    def test_the_server_wires_them(self):
        src = (ENGINE / "server.py").read_text(encoding="utf-8")
        self.assertIn('(None, _api(character_settings.api, "GET"))', src)
        self.assertIn('("/api/characters/*/settings", _api(character_settings.api, "PATCH"))', src)
        self.assertIn('("/api/characters/*/settings/restore", _api(character_settings.api, "POST"))', src)


if __name__ == "__main__":
    unittest.main()
