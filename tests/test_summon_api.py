"""Summon wizard REST (cgs/F): choices land on a chara_card_v2 card, regen stays on named keys.

Run: python3 -m unittest tests.test_summon_api
"""
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import characters  # noqa: E402
import host_config  # noqa: E402
import summon_api  # noqa: E402
import platform_compat  # noqa: E402


def _model(system, user):
    assert "별" in user
    return json.dumps({
        "name": "FromModel",
        "description": "A model written description.",
        "personality": "Model personality that must not stick.",
        "first_message": "The model opens in the middle of a scene.",
        "scenario": "Model scenario that must not stick.",
        "message_examples": "model examples",
    })


def _down(system, user):
    raise RuntimeError("adapter down")


class SummonApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _card(self, cid):
        return json.loads((self.ws / "characters" / cid / "card.json").read_text(encoding="utf-8"))

    def test_steps_cover_the_summon_scenario(self):
        spec = summon_api.public_spec()
        self.assertEqual([s["id"] for s in spec["steps"]],
                         ["call", "look", "personality", "voice", "bond", "name", "summon"])
        self.assertIn("summon_now", spec)

    def test_choices_win_and_join_the_roster(self):
        elder = characters.new_id()
        characters.save(elder, characters.new_card("Elder"), self.ws)
        characters.save_team({"default": elder, "members": {elder: []}}, self.ws)
        status, payload = summon_api.summon({
            "choices": {"name": "별", "look": "sharp", "personality": ["kind", "calm"],
                        "voice": "casual", "bond": "friend", "user_title": "코치", "idea": "fox"},
            "ws": str(self.tmp / "nope"),
        }, _model, ws=self.ws)
        self.assertEqual(status, 200)
        self.assertTrue(payload["woven"])
        self.assertNotEqual(payload["id"], elder)
        card = self._card(payload["id"])
        data = card["data"]
        self.assertEqual(card["spec"], "chara_card_v2")
        self.assertEqual(data["name"], "별")
        self.assertEqual(data["first_mes"], "The model opens in the middle of a scene.")
        self.assertIn("다정", data["personality"])
        self.assertNotIn("must not stick", data["personality"])
        self.assertIn("친구", data["scenario"])
        self.assertIn("또렷한", data["description"])
        self.assertIn("model written", data["description"])
        # #899: SillyTavern form -- <START>, macros kept (the engine fills them when a prompt is built)
        self.assertTrue(data["mes_example"].startswith("<START>\n{{user}}: "), data["mes_example"])
        self.assertIn("{{char}}: ", data["mes_example"])
        ext = data["extensions"]["chatbot"]
        self.assertEqual(ext["display"]["user_title"], "코치")
        self.assertEqual(ext["display"]["voice"], "편한 반말")
        self.assertNotIn("role", ext)
        visual = (self.ws / "characters" / payload["id"] / "visual.md").read_text(encoding="utf-8")
        self.assertIn("sharp features", visual)
        team = json.loads((self.ws / "team.json").read_text(encoding="utf-8"))
        self.assertEqual(team["default"], elder)
        self.assertIn(payload["id"], team["members"])
        self.assertFalse((self.tmp / "nope").exists())

    def test_failed_weave_still_summons_from_picks(self):
        status, payload = summon_api.summon({}, _down, ws=self.ws)
        self.assertEqual(status, 200)
        self.assertFalse(payload["woven"])
        self.assertEqual(payload["name"], "하루")
        card = self._card(payload["id"])
        first = card["data"]["first_mes"]
        self.assertTrue(first.startswith("*") and '* "' in first, "an action in asterisks, then the line: %r" % first)
        team = json.loads((self.ws / "team.json").read_text(encoding="utf-8"))
        self.assertEqual(team["default"], payload["id"])

    def test_quick_cards_follow_both_picks(self):
        # #899: two quick-summoned characters with the same voice had the same example; a casual pick opened polite
        seen = {}
        for bond in ("friend", "lover"):
            for voice in ("polite", "casual"):
                _, made = summon_api.summon({"choices": {"name": "별", "bond": bond, "voice": voice}}, _down, ws=self.ws)
                d = self._card(made["id"])["data"]
                seen[(bond, voice)] = (d["first_mes"], d["mes_example"])
        self.assertEqual(len({v[1] for v in seen.values()}), 4, "four picks, four examples")
        self.assertIn("드디어 만났네.", seen[("lover", "casual")][0])
        self.assertIn("드디어 만났네요.", seen[("lover", "polite")][0])

    def test_regenerate_keeps_other_fields(self):
        _, made = summon_api.summon({"choices": {"name": "별"}}, _model, ws=self.ws)
        before = self._card(made["id"])

        def regen(system, user):
            return json.dumps({
                "personality": "Sharp, impatient, and nothing like the previous line.",
                "name": "Hijack",
            })

        status, payload = summon_api.regenerate(made["id"], {"keys": ["personality"]}, regen, ws=self.ws)
        self.assertEqual(status, 200)
        self.assertEqual(payload["changed"], ["personality"])
        after = self._card(made["id"])
        self.assertEqual(after["data"]["name"], before["data"]["name"])
        self.assertNotEqual(after["data"]["personality"], before["data"]["personality"])
        self.assertNotIn("Hijack", json.dumps(after, ensure_ascii=False))

    def test_regenerate_refuses_unknown_keys_and_ids(self):
        _, made = summon_api.summon({"choices": {"name": "별"}}, _down, ws=self.ws)
        path = self.ws / "characters" / made["id"] / "card.json"
        raw = path.read_bytes()
        status, payload = summon_api.regenerate(made["id"], {"keys": ["role"]}, _model, ws=self.ws)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "unknown key")
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(summon_api.regenerate("../" + made["id"], {"keys": ["name"]}, _model, ws=self.ws)[0], 400)
        missing = characters.new_id()
        self.assertEqual(summon_api.regenerate(missing, {"keys": ["name"]}, _model, ws=self.ws)[0], 404)
        self.assertEqual(summon_api.regenerate(made["id"], {"keys": []}, _model, ws=self.ws)[0], 400)


class SummonRouteTest(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()
        self.orig = host_config.WORKSPACE
        self.orig_server = server.WORKSPACE
        self.orig_llm = summon_api.LLM
        host_config.WORKSPACE = self.ws
        server.WORKSPACE = self.ws
        summon_api.LLM = _down
        self.httpd = platform_compat.http_server(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        host_config.WORKSPACE = self.orig
        self.server.WORKSPACE = self.orig_server
        summon_api.LLM = self.orig_llm
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

    def test_routes_are_wired(self):
        post = [p for p, _ in self.server.POST_ROUTES]
        get = [p for p, _ in self.server.GET_ROUTES]
        self.assertIn("/api/characters/summon", post)
        self.assertIn("/api/characters/*/regenerate", post)
        self.assertLess(post.index("/api/characters/summon"), post.index("/api/characters/*/session"))
        self.assertIn("/api/summon", get)

    def test_get_steps_and_post_summon_and_regen(self):
        status, raw = self._req("GET", "/api/summon")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["menu"], "새로운 캐릭터 찾기")
        denied, _ = self._req("POST", "/api/characters/summon", {"choices": {"name": "별"}}, origin=False)
        self.assertEqual(denied, 403)
        status, raw = self._req("POST", "/api/characters/summon", {"choices": {"name": "별"}})
        self.assertEqual(status, 200)
        made = json.loads(raw.decode("utf-8"))
        self.assertTrue(made["ok"])
        self.assertNotIn("dir", made)
        # test cloning character
        cstatus, craw = self._req("POST", "/api/characters/%s/clone" % made["id"], {"name": "별 (IF)", "user_title": "파트너"})
        self.assertEqual(cstatus, 200)
        cloned = json.loads(craw.decode("utf-8"))
        self.assertTrue(cloned["ok"])
        self.assertEqual(cloned["name"], "별 (IF)")
        self.assertNotEqual(cloned["id"], made["id"])
        summon_api.LLM = lambda s, u: json.dumps({
            "first_message": "A different opening, already in the middle of the room.",
        })
        status, raw = self._req("POST", "/api/characters/%s/regenerate" % made["id"], {"keys": ["first_mes"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["changed"], ["first_message"])
