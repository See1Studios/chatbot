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

global.document = {{
  createElement: (tag) => {{
    let _text = '';
    return {{
      tagName: tag.toUpperCase(),
      nodeType: 1,
      innerHTML: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }}
    }};
  }}
}};

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
        calls.push({{ action: 'tileLayer', url, opts }});
        return {{}};
      }}
    }}),
    marker: (coords) => ({{
      addTo: (m) => ({{
        bindPopup: (content) => ({{
          openPopup: () => calls.push({{
            action: 'marker',
            coords,
            isString: typeof content === 'string',
            isNode: typeof content === 'object' && content !== null && typeof content.textContent === 'string',
            textContent: content && content.textContent
          }})
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
        marker_calls = [c for c in res["calls"] if c.get("action") == "marker"]
        self.assertEqual(len(marker_calls), 1)
        self.assertTrue(marker_calls[0]["isNode"], "bindPopup must receive a DOM element")
        self.assertFalse(marker_calls[0]["isString"], "bindPopup must not receive a raw string")
        self.assertEqual(marker_calls[0]["textContent"], "Spot")

    def test_render_maps_in_popup_xss_protection(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let popupArg = null;
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    return {{
      tagName: tag.toUpperCase(),
      nodeType: 1,
      innerHTML: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }}
    }};
  }}
}};

window = {{
  L: {{
    map: () => ({{ setView: () => ({{ invalidateSize: () => {{}} }}) }}),
    tileLayer: () => ({{ addTo: () => ({{}}) }}),
    marker: () => ({{
      addTo: () => ({{
        bindPopup: (content) => {{
          popupArg = {{
            isString: typeof content === 'string',
            isObject: typeof content === 'object' && content !== null,
            tagName: content && content.tagName,
            textContent: content && content.textContent,
            innerHTML: content && content.innerHTML
          }};
          return {{ openPopup: () => {{}} }};
        }}
      }})
    }})
  }}
}};

const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0', 'data-marker': '<img src=x onerror=alert(1)>' }},
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  querySelector() {{ return {{}}; }}
}};
const container = {{ querySelectorAll: () => [box] }};

(async () => {{
  await renderMapsIn(container);
  console.log(JSON.stringify(popupArg));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertFalse(res["isString"], "bindPopup must never receive a raw string (DOM XSS risk)")
        self.assertTrue(res["isObject"], "bindPopup must receive a DOM element node")
        self.assertEqual(res["tagName"], "DIV")
        self.assertEqual(res["textContent"], "<img src=x onerror=alert(1)>")
        self.assertEqual(res["innerHTML"], "", "innerHTML must remain empty")

    def test_render_maps_in_osm_attribution(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let mapOpts = null;
let tileOpts = null;

global.document = {{
  createElement: (tag) => ({{ tagName: tag.toUpperCase(), textContent: '' }})
}};
window = {{
  L: {{
    map: (canvas, opts) => {{
      mapOpts = opts;
      return {{ setView: () => ({{ invalidateSize: () => {{}} }}) }};
    }},
    tileLayer: (url, opts) => {{
      tileOpts = opts;
      return {{ addTo: () => ({{}}) }};
    }},
    marker: () => ({{ addTo: () => ({{ bindPopup: () => ({{ openPopup: () => {{}} }}) }}) }})
  }}
}};

const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0', 'data-marker': 'Attribution Test' }},
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute() {{}},
  querySelector() {{ return {{}}; }}
}};
const container = {{ querySelectorAll: () => [box] }};

(async () => {{
  await renderMapsIn(container);
  console.log(JSON.stringify({{ mapOpts, tileOpts }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertTrue(res["mapOpts"].get("attributionControl"), "attributionControl must not be disabled")
        self.assertIn("attribution", res["tileOpts"], "tileLayer must specify attribution")
        self.assertIn("OpenStreetMap", res["tileOpts"]["attribution"], "attribution must cite OpenStreetMap")

    def test_ensure_leaflet_loaded_timeout_and_retry(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let timerCb = null;
global.setTimeout = (cb, ms) => {{
  timerCb = cb;
  return 123;
}};
global.clearTimeout = () => {{}};

let scriptCount = 0;
global.document = {{
  querySelector: () => null,
  createElement: (tag) => {{
    if (tag === 'script') scriptCount++;
    return {{ tag, rel: '', href: '', src: '', dataset: {{}} }};
  }},
  head: {{ appendChild: () => {{}} }}
}};
global.window = {{}};

(async () => {{
  const p1 = ensureLeafletLoaded();
  const countAfterP1 = scriptCount;
  if (timerCb) timerCb();
  let err1 = null;
  try {{
    await p1;
  }} catch (e) {{
    err1 = e.message;
  }}
  const p2 = ensureLeafletLoaded();
  const countAfterP2 = scriptCount;
  console.log(JSON.stringify({{ err1, countAfterP1, countAfterP2 }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["err1"], "Leaflet load timeout")
        self.assertEqual(res["countAfterP1"], 1)
        self.assertEqual(res["countAfterP2"], 2, "Second attempt after timeout must retry script creation")


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
