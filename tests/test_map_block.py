"""Tests for Leaflet-based in-app dynamic map renderer for markdown ```map blocks (CHAT_MAP_v1).
Run: python3 -m unittest tests.test_map_block (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
MAP_JS = STATIC / "markdown-map.js"
MD_JS = STATIC / "markdown.js"
INDEX_HTML = STATIC / "index.html"
CSS = STATIC / "chat-features.css"


def run_map_js(expr):
    harness = f"""
const fs = require('fs');
const mapJs = fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8');
eval(mapJs);
console.log(JSON.stringify({expr}));
"""
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-1000:])
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapBlockParsing(unittest.TestCase):
    def test_parse_json_config(self):
        js = 'parseMapConfig(JSON.stringify({lat: 37.5665, lon: 126.9780, zoom: 14, marker: "Seoul City Hall"}))'
        res = run_map_js(js)
        self.assertEqual(res["lat"], 37.5665)
        self.assertEqual(res["lon"], 126.9780)
        self.assertEqual(res["zoom"], 14)
        self.assertEqual(res["marker"], "Seoul City Hall")

    def test_parse_json_alternative_keys(self):
        js = 'parseMapConfig(JSON.stringify({latitude: 35.1796, lng: 129.0756, text: "Busan City"}))'
        res = run_map_js(js)
        self.assertEqual(res["lat"], 35.1796)
        self.assertEqual(res["lon"], 129.0756)
        self.assertEqual(res["zoom"], 13)
        self.assertEqual(res["marker"], "Busan City")

        js2 = 'parseMapConfig(JSON.stringify({lat: 33.4996, longitude: 126.5312, label: "Jeju"}))'
        res2 = run_map_js(js2)
        self.assertEqual(res2["lat"], 33.4996)
        self.assertEqual(res2["lon"], 126.5312)
        self.assertEqual(res2["marker"], "Jeju")

    def test_parse_key_value_lines(self):
        raw = "lat: 37.5665\nlon: 126.9780\nzoom: 15\nmarker: Namsan Tower"
        res = run_map_js(f"parseMapConfig({json.dumps(raw)})")
        self.assertEqual(res["lat"], 37.5665)
        self.assertEqual(res["lon"], 126.9780)
        self.assertEqual(res["zoom"], 15)
        self.assertEqual(res["marker"], "Namsan Tower")

    def test_parse_key_value_equals_and_quotes(self):
        raw = 'latitude = 35.6895\nlng = 139.6917\nzoom = 12\nmarker = "Tokyo"'
        res = run_map_js(f"parseMapConfig({json.dumps(raw)})")
        self.assertEqual(res["lat"], 35.6895)
        self.assertEqual(res["lon"], 139.6917)
        self.assertEqual(res["zoom"], 12)
        self.assertEqual(res["marker"], "Tokyo")

    def test_invalid_coordinates(self):
        invalids = [
            "",
            "not a map",
            "lat: 95.0\nlon: 126.0",
            "lat: -91.0\nlon: 126.0",
            "lat: 37.0\nlon: 185.0",
            "lat: 37.0\nlon: -185.0",
            "lat: abc\nlon: def",
            "lat: 37.0",
            "lon: 126.0",
        ]
        for item in invalids:
            res = run_map_js(f"parseMapConfig({json.dumps(item)})")
            self.assertIsNone(res, f"Expected None for invalid input: {item}")

    def test_zoom_bounds_handling(self):
        raw_low = "lat: 37.5\nlon: 127.0\nzoom: 0"
        res_low = run_map_js(f"parseMapConfig({json.dumps(raw_low)})")
        self.assertEqual(res_low["zoom"], 13)

        raw_high = "lat: 37.5\nlon: 127.0\nzoom: 25"
        res_high = run_map_js(f"parseMapConfig({json.dumps(raw_high)})")
        self.assertEqual(res_high["zoom"], 13)

        raw_valid = "lat: 37.5\nlon: 127.0\nzoom: 18"
        res_valid = run_map_js(f"parseMapConfig({json.dumps(raw_valid)})")
        self.assertEqual(res_valid["zoom"], 18)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapBlockRendering(unittest.TestCase):
    def test_render_map_block_html(self):
        raw = "lat: 37.5665\nlon: 126.9780\nzoom: 14\nmarker: City Hall"
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertIn('class="chat-map-box"', html)
        self.assertIn('data-lat="37.5665"', html)
        self.assertIn('data-lon="126.978"', html)
        self.assertIn('data-zoom="14"', html)
        self.assertIn('data-marker="City Hall"', html)
        self.assertIn('class="chat-map-canvas"', html)
        self.assertIn('<div class="chat-map-label">City Hall</div>', html)

    def test_render_map_block_no_marker(self):
        raw = "lat: 37.5665\nlon: 126.9780"
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertIn('class="chat-map-box"', html)
        self.assertNotIn('data-marker=', html)
        self.assertNotIn('class="chat-map-label"', html)

    def test_render_map_block_xss_protection(self):
        raw = 'lat: 37.5\nlon: 127.0\nmarker: <script>alert(1)</script>" onmouseover="alert(2)'
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('&quot;', html)

    def test_render_map_block_fallback_on_invalid(self):
        raw = "just plain text"
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertEqual(html, '<pre><code class="language-map">just plain text</code></pre>')


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapMarkdownIntegration(unittest.TestCase):
    def test_markdown_full_render(self):
        harness = f"""
const fs = require('fs');
const window = {{}};
const marked = {{
  parse: (str) => str.replace(/```map\\s*([\\s\\S]*?)```/g, (_, code) => `<pre><code class="language-map">${{code}}</code></pre>`)
}};
window.marked = marked;
let addAttrs = [];
const DOMPurify = {{
  sanitize: (html, opts) => {{
    if (opts && opts.ADD_ATTR) addAttrs = opts.ADD_ATTR;
    return html;
  }}
}};
window.DOMPurify = DOMPurify;
const document = {{ createElement: () => ({{}}), head: {{ appendChild() {{}} }} }};
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));
eval(fs.readFileSync({json.dumps(str(MD_JS))}, 'utf8'));

const mdInput = "Here is the map:\\n\\n```map\\nlat: 37.5665\\nlon: 126.9780\\nzoom: 14\\nmarker: Seoul\\n```\\n\\nEnjoy!";
const streamHtml = renderMarkdown(mdInput, false);
const finalHtml = renderMarkdown(mdInput, true);

console.log(JSON.stringify({{
  streamHasBox: streamHtml.includes('chat-map-box'),
  streamHasCode: streamHtml.includes('class="language-map"'),
  finalHasBox: finalHtml.includes('chat-map-box'),
  finalHasLat: finalHtml.includes('data-lat="37.5665"'),
  finalHasMarker: finalHtml.includes('data-marker="Seoul"'),
  addAttrs: addAttrs,
}}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertFalse(res["streamHasBox"], "Streaming should keep raw code block")
        self.assertTrue(res["streamHasCode"], "Streaming should keep map code block")
        self.assertTrue(res["finalHasBox"], "Final render should produce chat-map-box")
        self.assertTrue(res["finalHasLat"], "Final render should preserve data-lat")
        self.assertTrue(res["finalHasMarker"], "Final render should preserve data-marker")
        for attr in ['data-lat', 'data-lon', 'data-zoom', 'data-marker']:
            self.assertIn(attr, res["addAttrs"], f"DOMPurify ADD_ATTR must include {attr}")

    def test_render_maps_in_processes_nodes(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

const calls = [];
window = {{
  L: {{
    map: (canvas, opts) => ({{
      setView: (center, zoom) => {{
        calls.push({{ action: 'map', center, zoom, opts }});
        return {{
          invalidateSize: () => calls.push({{ action: 'invalidate' }})
        }};
      }}
    }}),
    tileLayer: (url, opts) => ({{
      addTo: (m) => {{
        calls.push({{ action: 'tileLayer', url }});
        return {{}};
      }}
    }}),
    marker: (coords) => ({{
      addTo: (m) => ({{
        bindPopup: (text) => ({{
          openPopup: () => calls.push({{ action: 'marker', coords, text }})
        }})
      }})
    }})
  }}
}};

const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0', 'data-zoom': '14', 'data-marker': 'Spot' }},
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  querySelector(sel) {{ return {{}}; }}
}};
const container = {{
  querySelectorAll(sel) {{
    if (sel.includes('not([data-processed="true"])')) {{
      return box.attrs['data-processed'] === 'true' ? [] : [box];
    }}
    return [];
  }}
}};

(async () => {{
  await renderMapsIn(container);
  const firstProcessed = box.attrs['data-processed'];
  const firstCallsCount = calls.length;
  await renderMapsIn(container);
  console.log(JSON.stringify({{
    firstProcessed,
    firstCallsCount,
    secondCallsCount: calls.length,
    calls
  }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["firstProcessed"], "true")
        self.assertGreater(res["firstCallsCount"], 0)
        self.assertEqual(res["firstCallsCount"], res["secondCallsCount"], "Already processed boxes should not be re-rendered")


class MapStaticAssets(unittest.TestCase):
    def test_index_html_links_markdown_map_js(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('<script src="./markdown-map.js', html)

    def test_chat_features_css_has_map_styles(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertIn('.chat-map-box', css)
        self.assertIn('.chat-map-canvas', css)
        self.assertIn('.chat-map-label', css)
        self.assertIn('.leaflet-container', css)


if __name__ == "__main__":
    unittest.main()
