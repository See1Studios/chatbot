"""Slash popular pins are enabled workspace skills, not a hardcoded k-skill list.
Run: python3 -m unittest tests.test_slash_catalog  (from services/chatbot)
"""
import re
import shutil
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(CODE))
import workspace_status as W  # noqa: E402


BANNED = (
    "korea-weather", "geeknews-search", "kopis-performance-search",
    "naver-news-search", "naver-shopping-search", "delivery-tracking",
    "daangn-used-goods-search", "lotto-results", "korean-stock-search",
    "express-bus-booking",
)


def _write_skill(root: Path, name: str, desc: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: %s\ndescription: %s\n---\n" % (name, desc), encoding="utf-8")


class PopularFromWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig = W.WS_SKILLS_DIR
        W.WS_SKILLS_DIR = self.tmp

    def tearDown(self):
        W.WS_SKILLS_DIR = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enabled_skills_are_the_pin_list_and_disabled_are_not(self):
        _write_skill(self.tmp, "nas-sphere", "Operate Sphere")
        _write_skill(self.tmp, "_korea-weather", "날씨")
        _write_skill(self.tmp, "anime-layer-animator", "A " + ("long " * 40) + "description")
        pops = W._popular_slash_skills()
        names = [p["skill"] for p in pops]
        self.assertEqual(names, ["anime-layer-animator", "nas-sphere"])
        self.assertTrue(all(p["template"] == "/skill %s " % p["skill"] for p in pops))
        self.assertLessEqual(len(pops[0]["desc"]), 80)
        self.assertTrue(pops[0]["desc"].endswith("…"))

    def test_empty_workspace_means_no_pins(self):
        self.assertEqual(W._popular_slash_skills(), [])


class StaticFallback(unittest.TestCase):
    def test_slash_js_does_not_hardcode_the_retired_k_skill_pins(self):
        text = (CODE / "static" / "slash.js").read_text(encoding="utf-8")
        for name in BANNED:
            self.assertNotIn(name, text, name)
        self.assertIn("if (Array.isArray(data.popular))", text)

    def test_server_does_not_hardcode_the_retired_k_skill_pins(self):
        text = (CODE / "server.py").read_text(encoding="utf-8")
        for name in BANNED:
            self.assertNotIn(name, text, name)
        self.assertIn("_popular_slash_skills", text)


def _static(name: str) -> str:
    return (CODE / "static" / name).read_text(encoding="utf-8")


def _catalog_names(text: str) -> list:
    return re.findall(r'\{ name: "(/[^"]+)"', text)


class CommandCatalog(unittest.TestCase):
    def test_act_and_me_alias_are_listed(self):
        names = _catalog_names(_static("slash.js"))
        self.assertIn("/act", names)
        self.assertIn("/me", names)

    def test_every_ticket_decision_has_a_catalog_entry(self):
        names = set(_catalog_names(_static("slash.js")))
        evo = _static("app-evolution.js")
        m = re.search(r"\^\\/ticket\\s\+\(([a-z|]+)\)", evo)
        self.assertIsNotNone(m, "parseTicketCommand regex moved")
        actions = set(m.group(1).split("|")) | {"rework"}
        for a in actions:
            self.assertIn("/ticket " + a, names, a)

    def test_catalog_entries_carry_label_desc_template(self):
        text = _static("slash.js")
        for line in text.splitlines():
            if line.strip().startswith('{ name: "/'):
                for key in ("label:", "desc:", "template:"):
                    self.assertIn(key, line, line)

    def test_server_commands_merge_not_replace(self):
        text = _static("slash.js")
        self.assertNotIn("slashCatalog.commands = data.commands;", text)
        self.assertIn("!served.has(c.name)", text)


class ActionAndHelp(unittest.TestCase):
    def test_me_is_an_action_alias_and_payload_is_structured(self):
        text = _static("app.js")
        self.assertIn("(?:act|action|me)", text)
        self.assertIn("type: 'action'", text)
        self.assertIn("action_text: actionText", text)

    def test_help_lists_current_commands_not_legacy_skill_shortcuts(self):
        text = _static("app.js")
        start = text.index("if (text === '/help')")
        help_block = text[start:text.index("currentSessionHasUser = hadUser;", start)]
        self.assertNotIn("날씨·뉴스·주식", help_block)
        for cmd in ("/act", "/me", "/ticket", "/skill", "/btw", "/status"):
            self.assertIn(cmd, help_block, cmd)


class LiveWorkspace(unittest.TestCase):
    def test_this_deployment_pins_only_enabled_workspace_skills(self):
        enabled = {s["name"] for s in W._get_workspace_skills() if s.get("enabled")}
        pins = {p["skill"] for p in W._popular_slash_skills()}
        self.assertEqual(pins, enabled)
        self.assertTrue(pins.isdisjoint(BANNED))


class ActionParens(unittest.TestCase):
    """#153: "(x)"/"((x))" is one action; wire form is always "(x)", never "((x))"."""

    def _action_text_of(self, samples):
        import json, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        src = (CODE / "static" / "app-sse.js").read_text(encoding="utf-8")
        fn = re.search(r"^function actionTextOf\(text\) \{.*?^\}", src, re.S | re.M).group(0)
        md = (CODE / "static" / "markdown.js").read_text(encoding="utf-8")   # actionTextOf calls stripOuterParens
        fn = re.search(r"^function stripOuterParens\(s\) \{.*?^\}", md, re.S | re.M).group(0) + "\n" + fn
        js = fn + "\nconsole.log(JSON.stringify(%s.map(actionTextOf)));" % json.dumps(samples, ensure_ascii=False)
        out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_action_text_of_normalizes_parens(self):
        got = self._action_text_of(["(고개를 끄덕인다)", "((고개를 끄덕인다))", "  (웃는다)  ",
                                    "안녕", "(a) 그리고 (b)", "()", ""])
        self.assertEqual(got, ["고개를 끄덕인다", "고개를 끄덕인다", "웃는다", "", "", "", ""])

    def test_pick_choice_strips_wrapping_parens_before_act(self):
        # behaviour, not source text: the helpers moved and were renamed in #243 and the string check went stale
        import json, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        src = (CODE / "static" / "markdown.js").read_text(encoding="utf-8")
        a, b = src.index("function stripOuterParens"), src.index("function splitChoices")
        c, d = src.index("function pickChoice"), src.index("function sendPickedChoice")
        js = ("var inputEl = { value: '' }; var sent = []; function sendPickedChoice() {}\n" + src[a:b] + src[c:d] +
              "\nvar sendAction = t => sent.push(t);\n"
              "pickChoice({ label: 'x', kind: 'action', payload: '(고개를 끄덕인다)' });\n"
              "pickChoice('A -> ((웃는다))');\n"
              "sendAction = undefined; pickChoice({ label: 'y', kind: 'action', payload: '(손을 흔든다)' });\n"
              "console.log(JSON.stringify({ sent: sent, input: inputEl.value }));")
        out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out["sent"], ["고개를 끄덕인다", "웃는다"])
        self.assertEqual(out["input"], "/act 손을 흔든다")

    def test_send_wire_form_is_single_parens(self):
        text = (CODE / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn(": actionTextOf(text);", text)
        self.assertIn("isAction ? ('(' + actionText + ')') : text", text)

    def test_ack_and_history_route_through_add_user_entry(self):
        sse = (CODE / "static" / "app-sse.js").read_text(encoding="utf-8")
        sess = (CODE / "static" / "app-session.js").read_text(encoding="utf-8")
        self.assertIn("addUserEntry(text, false, false, data.ts);", sse)
        self.assertEqual(sess.count("addUserEntry(h.text"), 4)


if __name__ == "__main__":
    unittest.main()
