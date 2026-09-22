"""wiki MCP: compact search/get/sources against ~/wiki plus the tech catalog.
Run: python3 -m unittest tests.test_sphere_memory  (from services/chatbot)
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
import nas_mcp_host as H  # noqa: E402
import mcp_server as mcp  # noqa: E402


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _md(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig_tech = H.TECH_ROOT
        self.orig_wiki = H.WIKI
        H.TECH_ROOT = self.tmp / "tech"
        H.WIKI = self.tmp / "wiki"
        H._index_cache["mtime"] = None
        H._index_cache["cards"] = []
        H._wiki_cache["stamp"] = None
        H._wiki_cache["pages"] = []
        _write(H.TECH_ROOT / "data" / "index.json", {
            "schema": "tech-agent-index/v1",
            "cards": [
                {
                    "id": "card-geeknews-claude",
                    "title": "Claude news",
                    "title_kr": "클로드 소식",
                    "kind": "rss_item",
                    "source": "GeekNews",
                    "url": "https://news.hada.io/topic?id=1",
                    "tags": ["geeknews", "ai"],
                    "digest": "SHOULD NOT APPEAR IN SEARCH HITS " + ("x" * 200),
                },
                {
                    "id": "card-glossary-blinn",
                    "title": "Blinn-Phong",
                    "kind": "glossary_term",
                    "source": "3D Graphics Maniax (Nishikawa)",
                    "url": "http://diskstation/wiki/x",
                    "tags": ["glossary", "3d-graphics-maniax"],
                },
            ],
        })
        _write(H.TECH_ROOT / "data" / "cards" / "card-geeknews-claude.json", {
            "id": "card-geeknews-claude",
            "title": "Claude news",
            "title_kr": "클로드 소식",
            "kind": "rss_item",
            "source": "GeekNews",
            "url": "https://news.hada.io/topic?id=1",
            "origin_ref": "https://news.hada.io/topic?id=1",
            "tags": ["geeknews", "ai"],
            "digest": "short digest of the item",
            "judge": {"status": "PASS", "reasons": ["too", "many", "to", "return"]},
        })
        _write(H.TECH_ROOT / "data" / "sources" / "registry.json", {
            "sources": [
                {"id": "geeknews", "name": "GeekNews", "kind": "rss_blog", "status": "active", "quality": "allowlist"},
                {"id": "cedec", "name": "CEDEC", "kind": "conference", "status": "paused", "quality": "curated"},
            ],
        })
        _md(H.WIKI / "articles" / "simcore.md", """---
title: "SimCore engine"
description: "State machine bot engine for character chat"
tags:
  - character-ai
  - simcore
---

# SimCore engine

The engine binds affinity and stress gauges to scenario acts.
""")
        _md(H.WIKI / "raw" / "secret.md", """# leaked

simcore dump that must not be searchable
""")

    def tearDown(self):
        H.TECH_ROOT = self.orig_tech
        H.WIKI = self.orig_wiki
        H._index_cache["mtime"] = None
        H._index_cache["cards"] = []
        H._wiki_cache["stamp"] = None
        H._wiki_cache["pages"] = []
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, **args):
        return H.call_tool("wiki", args)


class Schema(unittest.TestCase):
    def test_one_tool_three_actions_and_not_memory_md(self):
        defs = [t for t in H.EXTRA_TOOL_DEFS if t["name"] == "wiki"]
        self.assertEqual(len(defs), 1)
        schema = defs[0]["inputSchema"]
        self.assertEqual(schema["properties"]["action"]["enum"], ["search", "get", "sources"])
        self.assertIn("not MEMORY.md", defs[0]["description"])
        self.assertNotIn("tech_memory", [t["name"] for t in H.EXTRA_TOOL_DEFS])
        self.assertNotIn('"name": "wiki"', Path(mcp.__file__).read_text(encoding="utf-8"))


class SearchGetSources(Fixture):
    def test_search_is_compact_and_omits_digest(self):
        r = self.call(action="search", query="claude")
        self.assertTrue(r["success"], r)
        hits = r["data"]["hits"]
        self.assertEqual([h["id"] for h in hits], ["card-geeknews-claude"])
        self.assertEqual(set(hits[0]), {"id", "title", "kind", "source", "url", "tags"})
        self.assertNotIn("digest", hits[0])

    def test_wiki_page_beats_raw_and_is_compact(self):
        r = self.call(action="search", query="simcore")
        self.assertTrue(r["success"], r)
        ids = [h["id"] for h in r["data"]["hits"]]
        self.assertEqual(ids, ["articles/simcore"])
        self.assertEqual(r["data"]["hits"][0]["source"], "wiki")
        self.assertNotIn("digest", r["data"]["hits"][0])

    def test_source_wiki_hides_catalog(self):
        r = self.call(action="search", query="claude", source="wiki")
        self.assertEqual(r["data"]["hits"], [])

    def test_source_catalog_hides_wiki(self):
        r = self.call(action="search", query="simcore", source="catalog")
        self.assertEqual(r["data"]["hits"], [])

    def test_short_query_is_refused(self):
        self.assertFalse(self.call(action="search", query="c")["success"])

    def test_kind_filter(self):
        r = self.call(action="search", query="card", kind="glossary_term")
        self.assertEqual([h["id"] for h in r["data"]["hits"]], ["card-glossary-blinn"])

    def test_get_returns_digest_and_origin_not_judge_dump(self):
        r = self.call(action="get", id="card-geeknews-claude")
        self.assertTrue(r["success"], r)
        item = r["data"]["item"]
        self.assertEqual(item["digest"], "short digest of the item")
        self.assertEqual(item["origin_ref"], "https://news.hada.io/topic?id=1")
        self.assertEqual(item["judge"], "PASS")

    def test_get_wiki_page_returns_frontmatter_digest(self):
        r = self.call(action="get", id="articles/simcore")
        self.assertTrue(r["success"], r)
        item = r["data"]["item"]
        self.assertEqual(item["title"], "SimCore engine")
        self.assertIn("State machine", item["digest"])
        self.assertEqual(item["path"], "articles/simcore.md")
        self.assertLessEqual(len(item["digest"]), H._DIGEST_MAX)

    def test_unknown_id_and_unknown_action_fail(self):
        self.assertFalse(self.call(action="get", id="nope")["success"])
        self.assertFalse(self.call(action="wipe")["success"])

    def test_sources_lists_vault_then_registry(self):
        r = self.call(action="sources")
        self.assertTrue(r["success"], r)
        ids = [s["id"] for s in r["data"]["sources"]]
        self.assertEqual(ids[:4], ["wiki", "catalog", "geeknews", "cedec"])
        self.assertEqual(set(r["data"]["sources"][0]), {"id", "name", "kind", "status", "quality"})


class LiveCatalog(unittest.TestCase):
    def test_this_nas_catalog_answers_a_known_glossary_card(self):
        if not (H.WEB / "tech" / "data" / "index.json").is_file():
            self.skipTest("no live tech catalog")
        saved_tech, saved_wiki = H.TECH_ROOT, H.WIKI
        try:
            H.TECH_ROOT = H.WEB / "tech"
            H._index_cache["mtime"] = None
            H._index_cache["cards"] = []
            r = H.call_tool("wiki", {"action": "search", "query": "blinn", "source": "catalog"})
            self.assertTrue(r["success"], r)
            self.assertTrue(r["data"]["hits"], r)
            cid = r["data"]["hits"][0]["id"]
            g = H.call_tool("wiki", {"action": "get", "id": cid})
            self.assertTrue(g["success"], g)
            self.assertIn("digest", g["data"]["item"])
        finally:
            H.TECH_ROOT = saved_tech
            H.WIKI = saved_wiki
            H._index_cache["mtime"] = None
            H._index_cache["cards"] = []

    def test_this_nas_wiki_answers_a_known_article(self):
        page = H.HOME / "wiki" / "articles" / "characterai-bot-crafting.md"
        if not page.is_file():
            self.skipTest("no live wiki article")
        saved_tech, saved_wiki = H.TECH_ROOT, H.WIKI
        try:
            H.WIKI = H.HOME / "wiki"
            H._wiki_cache["stamp"] = None
            H._wiki_cache["pages"] = []
            r = H.call_tool("wiki", {"action": "search", "query": "simcore", "source": "wiki"})
            self.assertTrue(r["success"], r)
            self.assertTrue(r["data"]["hits"], r)
            self.assertTrue(all(h["source"] == "wiki" for h in r["data"]["hits"]))
            pid = r["data"]["hits"][0]["id"]
            g = H.call_tool("wiki", {"action": "get", "id": pid})
            self.assertTrue(g["success"], g)
            self.assertTrue(g["data"]["item"].get("digest"))
            self.assertLessEqual(len(g["data"]["item"]["digest"]), H._DIGEST_MAX)
        finally:
            H.TECH_ROOT = saved_tech
            H.WIKI = saved_wiki
            H._wiki_cache["stamp"] = None
            H._wiki_cache["pages"] = []


class ClaudeAllowlist(unittest.TestCase):
    def test_claude_may_call_wiki(self):
        import adapters
        self.assertIn("wiki", adapters.ClaudeAdapter._NAS_MCP_TOOLS)
        self.assertNotIn("tech_memory", adapters.ClaudeAdapter._NAS_MCP_TOOLS)


if __name__ == "__main__":
    unittest.main()
