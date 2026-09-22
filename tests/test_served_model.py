"""Per-turn served_model (OpenRouter router vs actual id) on history, SSE, footer.
Run: python3 -m unittest tests.test_served_model  (from services/chatbot)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from adapters import openai_chunk_model, stamp_served_model

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP = STATIC / "app.js"
CSS = STATIC / "chat.css"
HTML = STATIC / "index.html"
MD = STATIC / "markdown.js"
ADAPTERS = ROOT / "adapters.py"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('function shortServedModel');
const b = src.indexOf('function attachMessageFooter');
if (a < 0 || b < 0) throw new Error('markers missing');
const shortServedModel = new Function(src.slice(a, b) + '; return shortServedModel;')();
const out = {
  grok: shortServedModel('grok-4.6'),
  ling: shortServedModel('inclusionai/ling-3.0-flash-sante:free'),
  router: shortServedModel('openrouter/free'),
  qwen: shortServedModel('qwen/qwen3.8-27b:free'),
  empty: shortServedModel(''),
};
process.stdout.write(JSON.stringify(out));
"""


class _Sess:
    def __init__(self, model: str = "") -> None:
        self.model = model


class ServedModelStamp(unittest.TestCase):
    def test_chunk_model_reads_wire_field(self) -> None:
        self.assertEqual(openai_chunk_model({"model": " inclusionai/ling-3.0-flash-sante:free "}),
                         "inclusionai/ling-3.0-flash-sante:free")
        self.assertEqual(openai_chunk_model({"choices": []}), "")
        self.assertEqual(openai_chunk_model(None), "")
        self.assertEqual(openai_chunk_model({"model": 3}), "")

    def test_captured_beats_session_model(self) -> None:
        hist, out = {}, {}
        stamp_served_model(_Sess("openrouter/free"), hist, out,
                           captured="inclusionai/ling-3.0-flash-sante:free")
        self.assertEqual(hist["served_model"], "inclusionai/ling-3.0-flash-sante:free")
        self.assertEqual(out["served_model"], hist["served_model"])

    def test_cli_falls_back_to_session_model(self) -> None:
        hist, out = {}, {}
        stamp_served_model(_Sess("grok-4.6"), hist, out)
        self.assertEqual(hist["served_model"], "grok-4.6")
        self.assertEqual(out["served_model"], "grok-4.6")

    def test_blank_is_omitted(self) -> None:
        hist, out = {}, {}
        stamp_served_model(_Sess(""), hist, out, captured="  ")
        self.assertNotIn("served_model", hist)
        self.assertNotIn("served_model", out)

    def test_does_not_rewrite_session_model(self) -> None:
        s = _Sess("openrouter/free")
        stamp_served_model(s, {}, {}, captured="z-ai/glm-5.2:free")
        self.assertEqual(s.model, "openrouter/free")


class ServedModelWiring(unittest.TestCase):
    def test_http_stream_returns_five_tuple(self) -> None:
        src = ADAPTERS.read_text(encoding="utf-8")
        self.assertIn("finish_reason, hop_model = yield from self._stream_once", src)
        self.assertIn("return \"\".join(text_buf), tool_calls, usage, finish_reason, served_model", src)
        self.assertIn("chunk_model = openai_chunk_model(obj)", src)

    def test_footer_and_cache_busters(self) -> None:
        app = APP.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        css = CSS.read_text(encoding="utf-8")
        md = MD.read_text(encoding="utf-8")
        self.assertIn("function shortServedModel", app)
        self.assertIn("data.served_model", app)
        self.assertIn("h.served_model", app)
        self.assertIn(".served-model{", css)
        self.assertIn("servedModel", md)
        self.assertRegex(html, r"app\.js\?v=\d+")
        self.assertRegex(html, r"markdown\.js\?v=\d+")
        self.assertIn("chat.css?v=20", html)
        self.assertNotIn("app.js?v=100", html)
        self.assertNotIn("chat.css?v=19", html)

    def test_short_label(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        proc = subprocess.run(
            [node, "-e", HARNESS, str(APP)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["grok"], "grok-4.6")
        self.assertEqual(out["ling"], "ling-3.0-flash-sante:free")
        self.assertEqual(out["router"], "openrouter/free")
        self.assertEqual(out["qwen"], "qwen3.8-27b:free")
        self.assertEqual(out["empty"], "")

    def test_conditional_served_model_visibility(self) -> None:
        app = APP.read_text(encoding="utf-8")
        # Footer prints served_model whenever the host stamped one.
        self.assertIn("if (served) {", app)
        self.assertIn("tag.className = 'served-model'", app)
        self.assertIn("tag.textContent = shortServedModel(served)", app)
        css = CSS.read_text(encoding="utf-8")
        self.assertIn(".served-model{", css)
        self.assertIn("white-space:nowrap", css)


if __name__ == "__main__":
    unittest.main()
