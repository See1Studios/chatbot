"""Identity is wired through prompts, HTTP and the page -- and nothing hardcodes a name.
Run: python3 -m unittest tests.test_identity_wiring  (from services/chatbot)
"""
import ast
import json
import shutil
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
import session_weights  # noqa: E402
import platform_compat  # noqa: E402  (exclusive port on Windows, #409)

OLD_NAMES = ("냥피디", "냥PD", "실장님")


def _workspace(title=None, persona=None, user_title=None, voice=None) -> Path:
    ws = Path(tempfile.mkdtemp())
    (ws / "AGENTS.md").write_text("# 헌장\n", encoding="utf-8")
    if any(v is not None for v in (title, persona, user_title, voice)):   # the default character's card (CARD_ONLY_v1)
        import characters
        cid = characters.new_id()
        display = {k: v for k, v in (("title", title), ("user_title", user_title), ("voice", voice)) if v}
        characters.save(cid, characters.new_card(persona or "", display=display), ws)
        characters.save_team({"default": cid, "members": {cid: []}}, ws)
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
        btw_idle = session_weights._btw_prompt("지금 뭐 해?", False, ["[맥락]"])
        btw_busy = session_weights._btw_prompt("지금 뭐 해?", True, [])
        handoff = session._handoff_prompt("대표님: 안녕\n루나: 네")
        for text in (btw_idle, btw_busy, handoff):
            for old in OLD_NAMES:
                self.assertNotIn(old, text)
        self.assertIn("You are 아트디렉터 루나. (The user: 대표님)", btw_idle)
        self.assertIn("대표님's question: 지금 뭐 해?", btw_idle)
        self.assertIn("차분한 존댓말", btw_busy)
        self.assertIn("- 대표님's latest requests:", handoff)
        self.assertIn("You summarize a handover for 아트디렉터 루나", handoff)

    def test_no_voice_means_no_tone_clause_and_still_reads_naturally(self):
        self.use(_workspace("테크디렉터", None, "팀장님", None))
        text = session_weights._btw_prompt("상태?", True, [])
        self.assertIn("briefly in 2-3 sentences, with only what matters", text)
        self.assertIn("You are 테크디렉터.", text)      # no persona: named by its title
        self.assertIn("in 2-3 sentences, with only what matters", text)   # no voice: no tone clause between them

    def test_the_dev_charter_with_a_card_yields_a_full_identity(self):
        # Structure, not values. uds/F: an install's cards are user data outside the repo, so the dev build's real
        # charter is paired with a fixture card here; the values are the fixture's, what is asserted is that they flow.
        ws = _workspace("아트디렉터", "루나", "대표님")
        shutil.copy(ROOT / "templates" / "dev-workspace" / "AGENTS.md", ws / "AGENTS.md")
        self.use(ws)
        i = identity.get_identity()
        self.assertNotEqual(i["title"], identity.DEFAULTS["title"], "no job title: neither the card nor its role pack names one")
        self.assertTrue(i["persona"], "the default character's card has no name")
        self.assertNotEqual(i["user_title"], identity.DEFAULTS["user_title"])
        prompt = session_weights._btw_prompt("q", False, [])
        self.assertIn(f"You are {identity.self_label()}. (The user: {i['user_title']})", prompt)


class HttpTest(Base):
    @classmethod
    def setUpClass(cls):
        cls.httpd = platform_compat.http_server(("127.0.0.1", 0), server.Handler)
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

    FILES = ["server.py", "session.py", "providers/adapters.py", "host_config.py", "instructions.py",
             "providers/accounts.py", "identity.py", "tool_format.py"]

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
        for name in sorted(p.name for p in (ROOT / "static").glob("app*.js")):   # app.js and its parts (APP_SPLIT_v1)
            for no, line in enumerate((ROOT / "static" / name).read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//", 1)[0] if "//" in line and "://" not in line else line
                if line.lstrip().startswith(("//", "*", "/*")):
                    continue
                if any(w in code for w in OLD_NAMES):
                    offenders.append(f"{name}:{no}: {line.strip()[:60]}")
        self.assertEqual(offenders, [], "hardcoded identity in the UI")


def instance_names():
    """The names that must never be identifiers: the known old ones plus this instance's own persona
    name, title and word for the user, read from its identity files -- so the guard follows a rename.
    Generic defaults (identity.DEFAULTS, e.g. 사용자) are words, not names."""
    names = set(OLD_NAMES)
    try:
        import characters
        # a role pack's title (PD, Staff) is role vocabulary the code may use, not a name the user gave
        vocabulary = {characters.role_pack(r, identity.WORKSPACE)["title"] for r in characters.roles(identity.WORKSPACE)}
        roles = [""] + [c["id"] for c in characters.listing(identity.WORKSPACE)]
        for role in roles:
            ident = identity.get_identity(role)
            for key in ("persona", "title", "user_title", "name"):
                v = str(ident.get(key) or "").strip()
                if v and v not in identity.DEFAULTS.values() and v not in vocabulary and len(v) >= 2:
                    names.add(v)
    except Exception:
        pass
    return sorted(names)


def _front_matter_stripped(text):
    if text.startswith("---\n"):
        head, sep, body = text[4:].partition("\n---\n")
        return body if sep else text
    return text


class NameNeutralityGuard(unittest.TestCase):
    """NAME_NEUTRAL_v1, recurrence guard. The persona's name and its word for the user are display,
    per instance (identity files). They must not be used as identifiers, keys, stored actor values or
    rules anywhere in code, static UI, instance tools/skills or rule documents. Comments and docstrings
    may quote history; tests are fixtures."""

    NAMES = instance_names()

    def py_offenders(self, path):
        out = []
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            return out
        docstrings = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
                first = n.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                    docstrings.add(id(first.value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                if any(w in n.value for w in self.NAMES):
                    out.append("%s:%d: %r" % (path.relative_to(ROOT), n.lineno, n.value[:50]))
        return out

    def test_python_everywhere(self):
        files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "providers").glob("*.py"))
        for ws in (ROOT / "templates" / "workspace", ROOT / "templates" / "dev-workspace"):   # the agents' tools (uds/F)
            files += sorted((ws / "tools").glob("*.py"))
            files += sorted(p for p in (ws / ".agents" / "skills").rglob("*.py")
                            if "sessions" not in p.parts and "__pycache__" not in p.parts)
        offenders = [o for f in files for o in self.py_offenders(f)]
        self.assertEqual(offenders, [], "persona name/title used in code")

    def test_static_ui(self):
        import re
        offenders = []
        for f in sorted((ROOT / "static").glob("*")):
            if f.suffix not in (".js", ".html") or not f.is_file():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            for no, line in enumerate(text.splitlines(), 1):
                code = re.sub(r"(^|\s)//.*$", "", line)
                if any(w in code for w in self.NAMES):
                    offenders.append("static/%s:%d: %s" % (f.name, no, line.strip()[:60]))
        self.assertEqual(offenders, [], "persona name/title baked into the UI")

    def test_the_page_keeps_its_identity_marker(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("<!--IDENTITY-->"), 1, "the served page was written back over the source")
        self.assertNotIn("window.__IDENTITY__=", html)

    def test_rule_documents(self):
        docs = [ROOT / "templates" / "dev-workspace" / n for n in ("AGENTS.md", "SELF-MODIFY.md", "PROJECT.md")]
        docs += [ROOT / "docs" / "plans" / "recursive-self-evolution.md", ROOT / "docs" / "LOGGING.md"]
        offenders = []
        for d in docs:
            if not d.exists():
                continue
            body = _front_matter_stripped(d.read_text(encoding="utf-8"))
            for no, line in enumerate(body.splitlines(), 1):
                if any(w in line for w in self.NAMES):
                    offenders.append("%s:%d: %s" % (d.relative_to(ROOT), no, line.strip()[:60]))
        self.assertEqual(offenders, [], "a rule names the persona or its word for the user; say 사용자/chat-agent")

    def test_stored_actors_are_role_ids(self):
        import evolution
        import observations
        bad = []
        for f in sorted((ROOT / "data" / "workspace" / "skill-observations" / "tickets").glob("*.json")):
            t = json.loads(f.read_text(encoding="utf-8"))
            for k in ("actor", "worked_by", "closed_by"):
                if t.get(k) and not evolution.ROLE_ID_RE.match(str(t[k])):
                    bad.append("%s %s=%r" % (f.name, k, t[k]))
            if any(w in str(t.get("approved_by") or "") for w in self.NAMES):
                bad.append("%s approved_by=%r" % (f.name, t["approved_by"]))
        for e in observations.scan(ROOT / "data" / "workspace" / "skill-observations", include_archive=True):
            for k in ("actor", "resolved_by"):
                if e.get(k) and not evolution.ROLE_ID_RE.match(str(e[k])):
                    bad.append("obs %s %s=%r" % (e["id"], k, e[k]))
        self.assertEqual(bad, [], "stored who-fields must be role ids")


if __name__ == "__main__":
    unittest.main()
