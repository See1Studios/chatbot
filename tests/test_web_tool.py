"""The `web` tool (WEB_TOOL_v1, web_tool.py): public internet only -- a host resolving to loopback, private,
link-local or tailnet space is refused before connecting and at every redirect, so a model cannot read the host's
own services through it; pages become readable text; DuckDuckGo's no-key pages become result lists; a private
session gets nothing. Offline: fake DNS, fake responses, no network.
Run: python3 -m unittest tests.test_web_tool  (from services/chatbot)
"""
import io
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from tests._paths import ENGINE, REPO  # noqa: E402
ROOT = REPO
sys.path.insert(0, str(ENGINE))
import web_tool as W  # noqa: E402

DNS = {"example.com": ["93.184.215.14"], "evil.test": ["127.0.0.1"], "nas.test": ["192.168.0.10"],
       "tail.test": ["100.101.102.103"], "mixed.test": ["93.184.215.14", "10.0.0.5"], "v6.test": ["::1"],
       "mapped.test": ["::ffff:127.0.0.1"], "link.test": ["169.254.169.254"]}
resolve = lambda h: DNS[h]  # noqa: E731
env = lambda ok, m, d: {"ok": ok, "message": m, "data": d}  # noqa: E731


class FakeResponse(io.BytesIO):
    def __init__(self, body, ctype, url):
        super().__init__(body)
        self.headers = {"Content-Type": ctype}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, body, ctype="text/html; charset=utf-8"):
        self.body, self.ctype, self.seen = body, ctype, []

    def open(self, req, timeout=None):
        self.seen.append(req.full_url)
        return FakeResponse(self.body, self.ctype, req.full_url)


class PublicOnly(unittest.TestCase):
    def test_only_global_addresses_pass(self):
        self.assertEqual(W.check_public("https://example.com/a", resolve), "https://example.com/a")
        for url in ("http://evil.test/", "http://nas.test/", "http://tail.test/", "http://mixed.test/",
                    "http://v6.test/", "http://mapped.test/", "http://link.test/latest/meta-data"):
            with self.assertRaises(W.WebError, msg=url):
                W.check_public(url, resolve)
        for url in ("file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)", "", "https:///nohost"):
            with self.assertRaises(W.WebError, msg=url):
                W.check_public(url, resolve)

    def test_a_redirect_into_the_house_is_refused(self):
        handler = W._CheckedRedirects(resolve)
        req = urllib.request.Request("https://example.com/start")
        with self.assertRaises(W.WebError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.test/api/sessions")
        self.assertIsNotNone(handler.redirect_request(req, None, 302, "Found", {}, "/elsewhere"))

    def test_nothing_is_fetched_from_a_private_address(self):
        opener = FakeOpener(b"secret")
        with self.assertRaises(W.WebError):
            W.fetch("http://127.0.0.1:3011/api/sessions", lambda h: [h], opener)
        self.assertEqual(opener.seen, [], "refused before connecting")


@mock.patch.dict("os.environ", {"CHATBOT_WEB_READER": "direct"})
class Reading(unittest.TestCase):
    def test_a_page_becomes_its_title_and_readable_text(self):
        html = ("<html><head><title> 노노의 방 </title><style>p{}</style><script>var x=1</script></head>"
                "<body><h1>제목</h1><p>첫 문단&nbsp;입니다.</p><p>둘째</p><noscript>no</noscript></body></html>")
        r = W.read("https://example.com/", resolve=resolve, opener=FakeOpener(html.encode("utf-8")))
        self.assertEqual(r["title"], "노노의 방")
        self.assertEqual(r["text"], "제목\n\n첫 문단 입니다.\n\n둘째")
        self.assertNotIn("var x", r["text"])

    def test_long_pages_are_capped_and_binaries_refused(self):
        r = W.read("https://example.com/", max_chars=1000, resolve=resolve,
                   opener=FakeOpener(b"a" * 5000, "text/plain"))
        self.assertEqual((len(r["text"]), r["truncated"]), (1000, True))
        with self.assertRaises(W.WebError):
            W.read("https://example.com/x.png", resolve=resolve, opener=FakeOpener(b"\x89PNG", "image/png"))


class JinaReading(unittest.TestCase):
    DNS = dict(DNS, **{"r.jina.ai": ["104.26.12.1"]})

    def test_jina_gives_clean_text_and_the_house_is_never_handed_to_it(self):
        body = b"Title: Doc\n\nURL Source: https://example.com/\n\nMarkdown Content:\n## Head\n\nBody text."
        opener = FakeOpener(body, "text/plain")
        r = W.read("https://example.com/", resolve=lambda h: self.DNS[h], opener=opener)
        self.assertEqual((r["via"], r["title"], r["text"]), ("jina", "Doc", "## Head\n\nBody text."))
        self.assertEqual(opener.seen, ["https://r.jina.ai/https://example.com/"])
        opener = FakeOpener(body, "text/plain")
        with self.assertRaises(W.WebError):
            W.read("http://evil.test/", resolve=lambda h: self.DNS[h], opener=opener)
        self.assertEqual(opener.seen, [], "a house address never reaches the third party")

    def test_an_empty_jina_answer_falls_back_to_the_direct_fetch(self):
        class TwoStep(FakeOpener):
            def open(self, req, timeout=None):
                self.seen.append(req.full_url)
                body = b"" if "r.jina.ai" in req.full_url else b"<title>T</title><p>direct</p>"
                return FakeResponse(body, "text/html", req.full_url)
        opener = TwoStep(b"")
        r = W.read("https://example.com/", resolve=lambda h: self.DNS[h], opener=opener)
        self.assertEqual((r["via"], r["text"]), ("direct", "direct"))


EXA = ("Title: Character Expressions | docs.ST.app\nURL: https://docs.sillytavern.app/extensions/expression-images/\n"
       "Published: N/A\nHighlights:\nExpression images are sprites.\n...\nMore.\n\n"
       "Title: Second\nURL: https://example.com/2\nHighlights:\nTwo.")


LITE = """<table><tr><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2FSillyTavern%2FDocs&amp;rut=1"
class='result-link'>SillyTavern Docs</a></td></tr><tr><td class='result-snippet'>Expression images are
<b>sprites</b>.</td></tr><tr><td><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F" class='result-link'>Example</a>
</td></tr><tr><td class='result-snippet'>An example.</td></tr></table>"""
HTMLPAGE = """<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.test%2F">A</a>
<a class="result__snippet">About A</a></div>"""


class Searching(unittest.TestCase):
    def test_both_no_key_pages_parse_to_results(self):
        self.assertEqual(W.parse_duckduckgo(LITE, 5), [
            {"title": "SillyTavern Docs", "url": "https://github.com/SillyTavern/Docs", "snippet": "Expression images are sprites."},
            {"title": "Example", "url": "https://example.com/", "snippet": "An example."}])
        self.assertEqual(W.parse_duckduckgo(LITE, 1)[0]["title"], "SillyTavern Docs")
        self.assertEqual(W.parse_duckduckgo(HTMLPAGE, 5), [{"title": "A", "url": "https://a.test/", "snippet": "About A"}])

    def test_exa_text_parses_to_results(self):
        self.assertEqual(W.parse_exa(EXA, 5), [
            {"title": "Character Expressions | docs.ST.app", "url": "https://docs.sillytavern.app/extensions/expression-images/",
             "snippet": "Expression images are sprites. More."},
            {"title": "Second", "url": "https://example.com/2", "snippet": "Two."}])

    def test_auto_asks_exa_then_falls_back_to_duckduckgo(self):
        import json
        dns = dict(DNS, **{"lite.duckduckgo.com": ["52.142.124.215"], "mcp.exa.ai": ["34.1.2.3"]})
        sse = ("event: message\ndata: " + json.dumps({"result": {"content": [{"type": "text", "text": EXA}]}})).encode()
        r = W.search("sprites", 5, resolve=lambda h: dns[h], opener=FakeOpener(sse, "text/event-stream"))
        self.assertEqual((r["backend"], len(r["results"])), ("exa", 2))

        class ExaDown(FakeOpener):
            def open(self, req, timeout=None):
                self.seen.append(req.full_url)
                if "exa.ai" in req.full_url:
                    raise OSError("down")
                return FakeResponse(LITE.encode(), "text/html", req.full_url)
        opener = ExaDown(b"")
        r = W.search("sprites", 5, resolve=lambda h: dns[h], opener=opener)
        self.assertEqual((r["backend"], len(r["results"])), ("duckduckgo", 2))
        self.assertEqual(len(opener.seen), 2)

    @mock.patch.dict("os.environ", {"CHATBOT_WEB_SEARCH": "duckduckgo"})
    def test_search_asks_the_backend_and_can_be_turned_off(self):
        dns = dict(DNS, **{"lite.duckduckgo.com": ["52.142.124.215"]})
        opener = FakeOpener(LITE.encode())
        r = W.search("sprites 표정", 3, resolve=lambda h: dns[h], opener=opener)
        self.assertEqual(len(r["results"]), 2)
        self.assertIn("q=sprites+%ED%91%9C%EC%A0%95", opener.seen[0])
        with mock.patch.dict("os.environ", {"CHATBOT_WEB_SEARCH": "off"}):
            with self.assertRaises(W.WebError):
                W.search("x")


class TheTool(unittest.TestCase):
    def test_a_private_session_gets_nothing(self):
        r = W.call({"action": "read", "url": "https://example.com"}, env, private=True)
        self.assertFalse(r["ok"])
        self.assertIn("private", r["message"])

    def test_bad_calls_are_refusals_not_crashes(self):
        self.assertFalse(W.call({"action": "delete"}, env)["ok"])
        self.assertFalse(W.call({"action": "read", "url": "http://127.0.0.1/"}, env)["ok"])

    def test_the_mcp_server_offers_and_routes_it(self):
        src = (ENGINE / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn("defs += list(web_tool.TOOL_DEFS)", src)
        self.assertIn('return web_tool.call(args, envelope, private=_live_scope("web")[0])', src)


if __name__ == "__main__":
    unittest.main()
