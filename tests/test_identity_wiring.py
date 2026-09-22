"""Identity is wired through prompts, HTTP and the page -- and nothing hardcodes a name.
Run: python3 -m unittest tests.test_identity_wiring  (from services/chatbot)
"""
import ast
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import identity  # noqa: E402
import server  # noqa: E402
import session  # noqa: E402

OLD_NAMES = ("냥피디", "냥PD", "실장님")


def _workspace(title=None, persona=None, user_title=None, voice=None) -> Path:
    ws = Path(tempfile.mkdtemp())
    if title is not None:
        (ws / "AGENTS.md").write_text(f"---\ntitle: {title}\n---\n# 헌장\n", encoding="utf-8")
    lines = [f"{k}: {v}" for k, v in (("persona", persona), ("user_title", user_title), ("voice", voice)) if v is not None]
    if lines:
        (ws / "PERSONA.md").write_text("---\n" + "\n".join(lines) + "\n---\n# 페르소나\n", encoding="utf-8")
    return ws


class Base(unittest.TestCase):
    def use(self, ws: Path):
        identity.WORKSPACE = ws
        identity._cache.clear()

    def setUp(self):
        self._orig = identity.WORKSPACE

    def tearDown(self):
        identity.WORKSPACE = self._orig
        identity._cache.clear()


class PromptsTest(Base):
    def test_another_bot_never_leaks_this_ones_names(self):
        self.use(_workspace("아트디렉터", "루나", "대표님", "차분한 존댓말"))
        btw_idle = session._btw_prompt("지금 뭐 해?", False, ["[맥락]"])
        btw_busy = session._btw_prompt("지금 뭐 해?", True, [])
        handoff = session._handoff_prompt("대표님: 안녕\n루나: 네")
        for text in (btw_idle, btw_busy, handoff):
            for old in OLD_NAMES:
                self.assertNotIn(old, text)
        self.assertIn("아트디렉터 루나입니다. (사용자: 대표님)", btw_idle)
        self.assertIn("대표님 질문: 지금 뭐 해?", btw_idle)
        self.assertIn("차분한 존댓말로", btw_busy)
        self.assertIn("- 대표님의 최근 요구사항:", handoff)
        self.assertIn("아트디렉터 루나 챗봇 인계 요약기", handoff)

    def test_no_voice_means_no_tone_clause_and_still_reads_naturally(self):
        self.use(_workspace("테크디렉터", None, "팀장님", None))
        text = session._btw_prompt("상태?", True, [])
        self.assertIn("핵심만 2~3문장으로 간결하게 즉답하세요.", text)
        self.assertIn("테크디렉터입니다.", text)      # no persona: named by its title
        self.assertNotIn("말투", text)

    def test_this_deployment_reads_from_its_real_instruction_files(self):
        # Structure, not values: the title/persona/user_title are the operator's data and
        # change (that is the point), so assert they are read and used, never what they are.
        self.use(ROOT / "data" / "workspace")
        i = identity.get_identity()
        self.assertNotEqual(i["title"], identity.DEFAULTS["title"], "AGENTS.md has no `title:` front matter")
        self.assertTrue(i["persona"], "PERSONA.md has no `persona:` front matter")
        self.assertNotEqual(i["user_title"], identity.DEFAULTS["user_title"])
        prompt = session._btw_prompt("q", False, [])
        self.assertIn(f"{identity.self_label()}입니다. (사용자: {i['user_title']})", prompt)


class HttpTest(Base):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as r:
            return r.read().decode("utf-8")

    def test_api_identity_follows_the_files_and_the_catalog_stays_vendor_only(self):
        self.use(_workspace("아트디렉터", "루나", "대표님", "차분한"))
        self.assertEqual(json.loads(self.get("/api/identity"))["persona"], "루나")
        catalog = json.loads(self.get("/api/providers"))["providers"]
        agy = next(p for p in catalog if p["id"] == "agy")
        grok = next(p for p in catalog if p["id"] == "grok")
        # a provider is a vendor: the persona ("루나") and title never leak into the catalog
        self.assertEqual(agy["name"], "Antigravity")
        self.assertEqual(agy["theme"], "spark")
        self.assertEqual(grok["theme"], "mono")
        self.assertIn("grok.webp", grok["icon"])
        for leaked in ("루나", "아트디렉터", "냥피디"):
            self.assertNotIn(leaked, json.dumps(agy, ensure_ascii=False))

    def test_index_html_carries_the_identity_and_survives_hostile_values(self):
        self.use(_workspace("</script><script>alert(1)</script>", "루나", "대표님"))
        html = self.get("/")
        self.assertIn("window.__IDENTITY__=", html)
        self.assertNotIn("<script>alert(1)", html)              # cannot break out of the inline script
        self.assertNotIn("<!--IDENTITY-->", html)               # the marker was consumed
        payload = html.split("window.__IDENTITY__=", 1)[1].split(";</script>", 1)[0]
        self.assertEqual(json.loads(payload)["title"], "</script><script>alert(1)</script>")

    def test_index_html_has_no_baked_in_names(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for old in OLD_NAMES:
            self.assertNotIn(old, html)


class NoHardcodedNamesGuard(unittest.TestCase):
    """The principle, enforced: runtime code holds no persona/title/user-title literal."""

    FILES = ["server.py", "session.py", "adapters.py", "host_config.py", "instructions.py",
             "accounts.py", "identity.py", "tool_format.py"]

    def test_no_string_literal_names_the_persona_or_user(self):
        offenders = []
        for name in self.FILES:
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            docstrings = set()
            for n in ast.walk(tree):
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
                    first = n.body[0]
                    if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                        docstrings.add(id(first.value))
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                    if any(w in n.value for w in OLD_NAMES):
                        offenders.append(f"{name}:{n.lineno}: {n.value[:50]!r}")
        self.assertEqual(offenders, [], "hardcoded identity in runtime code")

    def test_shipped_static_ui_holds_no_baked_in_names(self):
        offenders = []
        for name in ("app.js",):
            for no, line in enumerate((ROOT / "static" / name).read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//", 1)[0] if "//" in line and "://" not in line else line
                if line.lstrip().startswith(("//", "*", "/*")):
                    continue
                if any(w in code for w in OLD_NAMES):
                    offenders.append(f"{name}:{no}: {line.strip()[:60]}")
        self.assertEqual(offenders, [], "hardcoded identity in the UI")


if __name__ == "__main__":
    unittest.main()
