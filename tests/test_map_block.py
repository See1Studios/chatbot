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
class MapBlockMultiMarker(unittest.TestCase):
    """Multi-marker parsing and bounds tests."""

    def test_parse_json_markers_array(self):
        js = ('parseMapConfig(JSON.stringify({lat: 37.5, lon: 127.0,'
              ' markers: [{lat: 37.55, lon: 126.97, label: "A"}, {lat: 37.56, lon: 126.98, label: "B"}]}))')
        res = run_map_js(js)
        self.assertEqual(len(res["markers"]), 2)
        self.assertEqual(res["markers"][0]["label"], "A")
        self.assertEqual(res["markers"][1]["lat"], 37.56)

    def test_parse_json_markers_only_infers_center(self):
        js = ('parseMapConfig(JSON.stringify({markers: ['
              '{lat: 37.55, lon: 126.97, label: "A"}, {lat: 37.56, lon: 126.98, label: "B"}]}))')
        res = run_map_js(js)
        self.assertIsNotNone(res)
        self.assertEqual(res["lat"], 37.55, "lat inferred from first marker")
        self.assertEqual(res["lon"], 126.97, "lon inferred from first marker")
        self.assertEqual(len(res["markers"]), 2)

    def test_parse_kv_marker_with_coords_and_label(self):
        raw = "marker: 37.55, 126.97 | Seoul Station\nmarker: 37.56, 126.98 | City Hall"
        res = run_map_js(f"parseMapConfig({json.dumps(raw)})")
        self.assertIsNotNone(res)
        self.assertGreaterEqual(len(res["markers"]), 1)
        labels = [m["label"] for m in res["markers"]]
        self.assertIn("Seoul Station", labels)

    def test_parse_kv_marker_label_only_backward_compat(self):
        raw = "lat: 37.5\nlon: 127.0\nmarker: My Place"
        res = run_map_js(f"parseMapConfig({json.dumps(raw)})")
        self.assertEqual(res["marker"], "My Place")
        self.assertEqual(len(res["markers"]), 0)

    def test_parse_json_invalid_markers_filtered(self):
        js = ('parseMapConfig(JSON.stringify({lat: 37.5, lon: 127.0,'
              ' markers: [{lat: 999, lon: 0, label: "bad"}, {lat: 37.5, lon: 127.0, label: "ok"}]}))')
        res = run_map_js(js)
        self.assertEqual(len(res["markers"]), 1)
        self.assertEqual(res["markers"][0]["label"], "ok")

    def test_render_block_multi_markers_span(self):
        raw = '{"lat":37.5,"lon":127.0,"markers":[{"lat":37.55,"lon":126.97,"label":"A"},{"lat":37.56,"lon":126.98,"label":"B"}]}'
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertIn('class="chat-map-markers"', html)
        self.assertIn("37.55", html)

    def test_render_block_no_markers_no_span(self):
        raw = "lat: 37.5\nlon: 127.0\nmarker: Solo"
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertNotIn('chat-map-markers', html)

    def test_parse_kv_plural_markers_key(self):
        raw = "markers: 37.55, 126.97 | Place A\nmarkers: 37.56, 126.98 | Place B"
        res = run_map_js(f"parseMapConfig({json.dumps(raw)})")
        self.assertIsNotNone(res)
        self.assertEqual(len(res["markers"]), 2)
        self.assertEqual(res["markers"][0]["label"], "Place A")
        self.assertEqual(res["markers"][1]["label"], "Place B")

    def test_parse_kv_coords_only_marker(self):
        raw = "lat: 37.5\nlon: 127.0\nmarker: 37.55, 126.97"
        res = run_map_js(f"parseMapConfig({json.dumps(raw)})")
        self.assertIsNotNone(res)
        self.assertEqual(len(res["markers"]), 1)
        self.assertEqual(res["markers"][0]["lat"], 37.55)
        self.assertEqual(res["markers"][0]["lon"], 126.97)
        self.assertEqual(res["markers"][0]["label"], "")

    def test_render_block_multi_markers_label_summary(self):
        raw = '{"lat":37.5,"lon":127.0,"markers":[{"lat":37.55,"lon":126.97,"label":"Spot A"},{"lat":37.56,"lon":126.98,"label":"Spot B"}]}'
        html = run_map_js(f"renderMapBlock({json.dumps(raw)})")
        self.assertIn('Spot A \u00B7 Spot B', html)


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
class MapBlockPopup(unittest.TestCase):
    """Popup DOM creation and Google Maps link tests."""

    def test_build_popup_content_with_label(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(),
      className: '',
      href: '',
      target: '',
      rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      children
    }};
  }}
}};

const popup = buildPopupContent(37.5, 127.0, 'Seoul');
console.log(JSON.stringify({{
  className: popup.className,
  childCount: popup.children.length,
  labelText: popup.children[0] && popup.children[0].textContent,
  labelClass: popup.children[0] && popup.children[0].className,
  linkHref: popup.children[1] && popup.children[1].href,
  linkTarget: popup.children[1] && popup.children[1].target,
  linkRel: popup.children[1] && popup.children[1].rel,
  linkText: popup.children[1] && popup.children[1].textContent,
  linkClass: popup.children[1] && popup.children[1].className
}}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["className"], "chat-map-popup")
        self.assertEqual(res["childCount"], 2, "label + link")
        self.assertEqual(res["labelText"], "Seoul")
        self.assertEqual(res["labelClass"], "chat-map-popup-label")
        self.assertIn("google.com/maps/search", res["linkHref"])
        self.assertIn("37.5", res["linkHref"])
        self.assertIn("127", res["linkHref"])
        self.assertEqual(res["linkTarget"], "_blank")
        self.assertEqual(res["linkRel"], "noopener")
        self.assertEqual(res["linkClass"], "chat-map-popup-btn")

    def test_build_popup_content_no_label(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      children
    }};
  }}
}};
const popup = buildPopupContent(37.5, 127.0, '');
console.log(JSON.stringify({{
  childCount: popup.children.length,
  linkText: popup.children[0] && popup.children[0].textContent
}}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["childCount"], 1, "link only, no label")

    def test_popup_xss_label(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', href: '', target: '', rel: '',
      innerHTML: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      children
    }};
  }}
}};
const popup = buildPopupContent(37.5, 127.0, '<img src=x onerror=alert(1)>');
const label = popup.children[0];
console.log(JSON.stringify({{
  labelText: label.textContent,
  labelInnerHTML: label.innerHTML
}}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["labelText"], "<img src=x onerror=alert(1)>")
        self.assertEqual(res["labelInnerHTML"], "", "innerHTML must be empty")

    def test_popup_google_maps_negative_coords(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      children
    }};
  }}
}};
const popup = buildPopupContent(-33.8688, 151.2093, 'Sydney');
const link = popup.children[1];
console.log(JSON.stringify({{
  linkHref: link.href,
  linkTarget: link.target,
  linkRel: link.rel,
  linkText: link.textContent
}}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertIn("-33.8688", res["linkHref"])
        self.assertIn("151.2093", res["linkHref"])
        self.assertEqual(res["linkTarget"], "_blank")
        self.assertEqual(res["linkRel"], "noopener")
        self.assertEqual(res["linkText"], "Google \uC9C0\uB3C4")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapBlockMultiMarkerRendering(unittest.TestCase):
    """renderMapsIn with multi-marker: fitBounds, multiple L.marker calls."""

    def test_multi_marker_fit_bounds(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

const calls = [];
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', type: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}},
      children
    }};
  }},
  addEventListener() {{}}
}};

window = {{
  L: {{
    map: (canvas, opts) => {{
      calls.push({{action: 'mapOpts', opts}});
      const mapObj = {{
        setView: (c, z) => {{ calls.push({{action: 'setView', center: c, zoom: z}}); return mapObj; }},
        fitBounds: (b, o) => {{ calls.push({{action: 'fitBounds', bounds: b, opts: o}}); return mapObj; }},
        invalidateSize: () => {{}},
        dragging: {{ enable() {{}}, disable() {{}} }},
        touchZoom: {{ enable() {{}}, disable() {{}} }},
        doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
        scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
      }};
      return mapObj;
    }},
    tileLayer: () => ({{ addTo: () => ({{}}) }}),
    marker: (coords) => ({{
      addTo: () => ({{
        bindPopup: (content) => ({{
          openPopup: () => calls.push({{action: 'marker', coords}})
        }})
      }})
    }}),
    latLngBounds: (arr) => {{ calls.push({{action: 'latLngBounds', arr}}); return 'bounds-obj'; }}
  }}
}};

const markersData = JSON.stringify([
  {{lat: 37.55, lon: 126.97, label: "A"}},
  {{lat: 37.56, lon: 126.98, label: "B"}}
]);
const box = {{
  attrs: {{ 'data-lat': '37.55', 'data-lon': '126.97', 'data-zoom': '14' }},
  classes: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') {{
      return {{ textContent: markersData }};
    }}
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{ box.classes.push(c); }}, contains(c) {{ return box.classes.includes(c); }} }},
  appendChild() {{}}
}};
const container = {{ querySelectorAll: () => [box] }};

(async () => {{
  await renderMapsIn(container);
  const hasFitBounds = calls.some(c => c.action === 'fitBounds');
  const hasSetView = calls.some(c => c.action === 'setView');
  const markerCalls = calls.filter(c => c.action === 'marker');
  const boundsCalls = calls.filter(c => c.action === 'latLngBounds');
  console.log(JSON.stringify({{
    hasFitBounds,
    hasSetView,
    markerCount: markerCalls.length,
    boundsCoords: boundsCalls.length > 0 ? boundsCalls[0].arr : null,
    processed: box.attrs['data-processed']
  }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertTrue(res["hasFitBounds"], "Multi-marker must use fitBounds")
        self.assertFalse(res["hasSetView"], "Multi-marker must not use setView")
        self.assertEqual(res["processed"], "true")
        self.assertIsNotNone(res["boundsCoords"])
        self.assertEqual(len(res["boundsCoords"]), 2, "Two marker coords in bounds")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapMarkdownIntegration(unittest.TestCase):
    def test_markdown_full_render(self):
        md_text = "Here is the map:\n\n```map\nlat: 37.5665\nlon: 126.9780\nzoom: 14\nmarker: Seoul\n```\n\nEnjoy!"
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

const mdInput = {json.dumps(md_text)};
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
    const children = [];
    return {{
      tagName: tag.toUpperCase(),
      nodeType: 1,
      innerHTML: '',
      className: '',
      type: '',
      href: '',
      target: '',
      rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}},
      children
    }};
  }},
  addEventListener() {{}}
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
      }},
      invalidateSize: () => {{}},
      dragging: {{ enable() {{}}, disable() {{}} }},
      touchZoom: {{ enable() {{}}, disable() {{}} }},
      doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
      scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
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
            isNode: typeof content === 'object' && content !== null && typeof content.tagName === 'string',
            className: content && content.className
          }})
        }})
      }})
    }})
  }}
}};

const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0', 'data-zoom': '14', 'data-marker': 'Spot' }},
  classes: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') return null;
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{ box.classes.push(c); }}, contains(c) {{ return box.classes.includes(c); }} }},
  appendChild() {{}}
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
        self.assertEqual(marker_calls[0]["className"], "chat-map-popup")

    def test_render_maps_in_popup_xss_protection(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let popupArg = null;
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(),
      nodeType: 1,
      innerHTML: '',
      className: '',
      type: '',
      href: '',
      target: '',
      rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}},
      children
    }};
  }},
  addEventListener() {{}}
}};

window = {{
  L: {{
    map: () => ({{
      setView: () => ({{ invalidateSize: () => {{}} }}),
      invalidateSize: () => {{}},
      dragging: {{ enable() {{}}, disable() {{}} }},
      touchZoom: {{ enable() {{}}, disable() {{}} }},
      doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
      scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
    }}),
    tileLayer: () => ({{ addTo: () => ({{}}) }}),
    marker: () => ({{
      addTo: () => ({{
        bindPopup: (content) => {{
          popupArg = {{
            isString: typeof content === 'string',
            isObject: typeof content === 'object' && content !== null,
            tagName: content && content.tagName,
            className: content && content.className
          }};
          return {{ openPopup: () => {{}} }};
        }}
      }})
    }})
  }}
}};

const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0', 'data-marker': '<img src=x onerror=alert(1)>' }},
  classes: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') return null;
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{ box.classes.push(c); }}, contains(c) {{ return box.classes.includes(c); }} }},
  appendChild() {{}}
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
        self.assertEqual(res["className"], "chat-map-popup")

    def test_render_maps_in_osm_attribution(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let mapOpts = null;
let tileOpts = null;

global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', type: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}},
      children
    }};
  }},
  addEventListener() {{}}
}};
window = {{
  L: {{
    map: (canvas, opts) => {{
      mapOpts = opts;
      return {{
        setView: () => ({{ invalidateSize: () => {{}} }}),
        invalidateSize: () => {{}},
        dragging: {{ enable() {{}}, disable() {{}} }},
        touchZoom: {{ enable() {{}}, disable() {{}} }},
        doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
        scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
      }};
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
  classes: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute() {{}},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') return null;
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{}}, contains(c) {{ return false; }} }},
  appendChild() {{}}
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


    def test_ensure_leaflet_loaded_sri_and_attributes(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

const elements = [];
global.document = {{
  querySelector: () => null,
  createElement: (tag) => {{
    const el = {{ tag, dataset: {{}} }};
    elements.push(el);
    return el;
  }},
  head: {{ appendChild: () => {{}} }}
}};
global.window = {{}};
global.setTimeout = () => 1;

ensureLeafletLoaded().catch(() => {{}});

const link = elements.find(e => e.tag === 'link');
const script = elements.find(e => e.tag === 'script');

console.log(JSON.stringify({{
  linkHref: link && link.href,
  linkIntegrity: link && link.integrity,
  linkCrossOrigin: link && link.crossOrigin,
  scriptSrc: script && script.src,
  scriptIntegrity: script && script.integrity,
  scriptCrossOrigin: script && script.crossOrigin
}}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["linkIntegrity"], "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=")
        self.assertEqual(res["linkCrossOrigin"], "anonymous")
        self.assertEqual(res["scriptIntegrity"], "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=")
        self.assertEqual(res["scriptCrossOrigin"], "anonymous")

    def test_render_maps_in_scroll_wheel_zoom(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let mapOpts = null;
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', type: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}},
      children
    }};
  }},
  addEventListener() {{}}
}};
window = {{
  L: {{
    map: (canvas, opts) => {{
      mapOpts = opts;
      return {{
        setView: () => ({{ invalidateSize: () => {{}} }}),
        invalidateSize: () => {{}},
        dragging: {{ enable() {{}}, disable() {{}} }},
        touchZoom: {{ enable() {{}}, disable() {{}} }},
        doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
        scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
      }};
    }},
    tileLayer: () => ({{ addTo: () => ({{}}) }}),
    marker: () => ({{ addTo: () => ({{ bindPopup: () => ({{ openPopup: () => {{}} }}) }}) }})
  }}
}};
const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0' }},
  classes: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute() {{}},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') return null;
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{}}, contains(c) {{ return false; }} }},
  appendChild() {{}}
}};
const container = {{ querySelectorAll: () => [box] }};
(async () => {{
  await renderMapsIn(container);
  console.log(JSON.stringify({{ mapOpts }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertIsNotNone(res["mapOpts"])
        self.assertFalse(res["mapOpts"].get("scrollWheelZoom"), "scrollWheelZoom must be false")
        self.assertTrue(res["mapOpts"].get("zoomControl"), "zoomControl must be enabled")

    def test_render_maps_in_dragging_disabled_by_default(self):
        """Default embedded state must disable dragging and touch zoom to prevent scroll trapping."""
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let mapOpts = null;
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tagName: tag.toUpperCase(), className: '', type: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}},
      children
    }};
  }},
  addEventListener() {{}}
}};
window = {{
  L: {{
    map: (canvas, opts) => {{
      mapOpts = opts;
      return {{
        setView: () => ({{ invalidateSize: () => {{}} }}),
        invalidateSize: () => {{}},
        dragging: {{ enable() {{}}, disable() {{}} }},
        touchZoom: {{ enable() {{}}, disable() {{}} }},
        doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
        scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
      }};
    }},
    tileLayer: () => ({{ addTo: () => ({{}}) }}),
    marker: () => ({{ addTo: () => ({{ bindPopup: () => ({{ openPopup: () => {{}} }}) }}) }})
  }}
}};
const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0' }},
  classes: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute() {{}},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') return null;
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{}}, contains(c) {{ return false; }} }},
  appendChild() {{}}
}};
const container = {{ querySelectorAll: () => [box] }};
(async () => {{
  await renderMapsIn(container);
  console.log(JSON.stringify({{ mapOpts }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertFalse(res["mapOpts"].get("dragging"), "dragging must be disabled by default")
        self.assertFalse(res["mapOpts"].get("touchZoom"), "touchZoom must be disabled by default")
        self.assertFalse(res["mapOpts"].get("doubleClickZoom"), "doubleClickZoom must be disabled by default")

    def test_render_maps_in_leaflet_load_failure_fallback(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

let scriptErrorFired = false;
global.document = {{
  querySelector: () => null,
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    return {{
      tag: tag.toLowerCase(),
      tagName: tag.toUpperCase(),
      dataset: {{}},
      className: '',
      type: '',
      href: '',
      target: '',
      rel: '',
      get textContent() {{
        if (children.length) return children.map(c => c.textContent || '').join('');
        return _text;
      }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener() {{}}
    }};
  }},
  head: {{
    appendChild: (el) => {{
      if ((el.tag === 'script' || el.tagName === 'SCRIPT') && typeof el.onerror === 'function') {{
        setTimeout(() => {{
          scriptErrorFired = true;
          el.onerror(new Error('Network error'));
        }}, 1);
      }}
    }}
  }}
}};
global.window = {{}};

const box1 = {{
  attrs: {{ 'data-lat': '37.5665', 'data-lon': '126.9780', 'data-marker': 'Seoul <script>xss</script>' }},
  classes: ['chat-map-box'],
  children: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  classList: {{
    add(c) {{ if (!box1.classes.includes(c)) box1.classes.push(c); }},
    contains(c) {{ return box1.classes.includes(c); }}
  }},
  appendChild(child) {{ this.children.push(child); }},
  get textContent() {{
    return this.children.map(c => c.textContent || '').join('');
  }},
  set textContent(v) {{ this.children = []; }}
}};

const container = {{ querySelectorAll: () => [box1] }};

(async () => {{
  let loadError = null;
  try {{
    await ensureLeafletLoaded();
  }} catch (e) {{
    loadError = e ? e.message : String(e);
  }}
  await renderMapsIn(container);
  console.log(JSON.stringify({{
    loadError,
    scriptErrorFired,
    processed: box1.attrs['data-processed'],
    isFallback: box1.classList.contains('chat-map-fallback'),
    textContent: box1.textContent,
    classes: box1.classes
  }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertTrue(res["scriptErrorFired"], "Script onerror must be invoked on load failure")
        self.assertEqual(res["loadError"], "Network error", "ensureLeafletLoaded must reject with onerror Network error, not a mock TypeError")
        self.assertNotIn("TypeError", res.get("loadError", ""), "Must not fail due to mock TypeError")
        self.assertEqual(res["processed"], "true")
        self.assertTrue(res["isFallback"], "Must add chat-map-fallback class")
        self.assertIn("37.5665", res["textContent"])
        self.assertIn("126.9780", res["textContent"])
        self.assertIn("Seoul <script>xss</script>", res["textContent"])
        self.assertIn("chat-map-fallback", res["classes"])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapBlockFullscreen(unittest.TestCase):
    """Fullscreen toggle: dragging enable/disable, icon change, ESC key."""

    def test_fullscreen_toggle_enables_dragging(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

const log = [];
const mapObj = {{
  dragging: {{
    enable() {{ log.push('dragging.enable'); }},
    disable() {{ log.push('dragging.disable'); }}
  }},
  touchZoom: {{
    enable() {{ log.push('touchZoom.enable'); }},
    disable() {{ log.push('touchZoom.disable'); }}
  }},
  doubleClickZoom: {{
    enable() {{ log.push('dblClick.enable'); }},
    disable() {{ log.push('dblClick.disable'); }}
  }},
  scrollWheelZoom: {{
    enable() {{ log.push('scroll.enable'); }},
    disable() {{ log.push('scroll.disable'); }}
  }},
  invalidateSize() {{ log.push('invalidate'); }}
}};
const el = {{
  _classes: [],
  classList: {{
    contains(c) {{ return el._classes.includes(c); }},
    toggle(c) {{
      const i = el._classes.indexOf(c);
      if (i >= 0) el._classes.splice(i, 1);
      else el._classes.push(c);
    }}
  }}
}};
let btnText = '\\u26F6';
const fsBtn = {{
  get textContent() {{ return btnText; }},
  set textContent(v) {{ btnText = v; }}
}};

// Enter fullscreen
toggleMapFullscreen(el, mapObj, fsBtn);
const afterEnter = {{
  classes: [...el._classes],
  log: [...log],
  btnText
}};

log.length = 0;
// Exit fullscreen
toggleMapFullscreen(el, mapObj, fsBtn);
const afterExit = {{
  classes: [...el._classes],
  log: [...log],
  btnText
}};

console.log(JSON.stringify({{ afterEnter, afterExit }}));
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)

        enter = res["afterEnter"]
        self.assertIn("chat-map-fullscreen", enter["classes"])
        self.assertIn("dragging.enable", enter["log"])
        self.assertIn("touchZoom.enable", enter["log"])
        self.assertIn("scroll.enable", enter["log"])
        self.assertIn("invalidate", enter["log"])
        self.assertEqual(enter["btnText"], "\u2715", "Button must show close icon in fullscreen")

        exit_ = res["afterExit"]
        self.assertNotIn("chat-map-fullscreen", exit_["classes"])
        self.assertIn("dragging.disable", exit_["log"])
        self.assertIn("touchZoom.disable", exit_["log"])
        self.assertIn("scroll.disable", exit_["log"])
        self.assertEqual(exit_["btnText"], "\u26F6", "Button must show expand icon after exit")

    def test_fullscreen_button_created_in_render(self):
        harness = f"""
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(MAP_JS))}, 'utf8'));

const appendedChildren = [];
const keydownListeners = [];
global.document = {{
  createElement: (tag) => {{
    let _text = '';
    const children = [];
    const listeners = {{}};
    return {{
      tagName: tag.toUpperCase(), className: '', type: '', href: '', target: '', rel: '',
      get textContent() {{ return _text; }},
      set textContent(v) {{ _text = String(v); }},
      appendChild(child) {{ children.push(child); }},
      addEventListener(ev, fn) {{
        if (!listeners[ev]) listeners[ev] = [];
        listeners[ev].push(fn);
        if (ev === 'keydown') keydownListeners.push(fn);
      }},
      children, _listeners: listeners
    }};
  }},
  addEventListener(ev, fn) {{
    if (ev === 'keydown') keydownListeners.push(fn);
  }}
}};

window = {{
  L: {{
    map: (canvas, opts) => ({{
      setView: () => ({{ invalidateSize: () => {{}} }}),
      invalidateSize: () => {{}},
      dragging: {{ enable() {{}}, disable() {{}} }},
      touchZoom: {{ enable() {{}}, disable() {{}} }},
      doubleClickZoom: {{ enable() {{}}, disable() {{}} }},
      scrollWheelZoom: {{ enable() {{}}, disable() {{}} }}
    }}),
    tileLayer: () => ({{ addTo: () => ({{}}) }}),
    marker: () => ({{ addTo: () => ({{ bindPopup: () => ({{ openPopup: () => {{}} }}) }}) }})
  }}
}};

const box = {{
  attrs: {{ 'data-lat': '37.5', 'data-lon': '127.0', 'data-marker': 'Test' }},
  _children: [],
  getAttribute(k) {{ return this.attrs[k] || null; }},
  setAttribute(k, v) {{ this.attrs[k] = String(v); }},
  querySelector(sel) {{
    if (sel === '.chat-map-markers') return null;
    if (sel === '.chat-map-canvas') return {{}};
    return null;
  }},
  classList: {{ toggle() {{}}, add(c) {{}}, contains(c) {{ return false; }} }},
  appendChild(child) {{ this._children.push(child); appendedChildren.push(child); }}
}};
const container = {{ querySelectorAll: () => [box] }};

(async () => {{
  await renderMapsIn(container);
  const fsBtns = appendedChildren.filter(c => c.className === 'chat-map-fs-btn');
  console.log(JSON.stringify({{
    fsBtnCount: fsBtns.length,
    fsBtnText: fsBtns.length > 0 ? fsBtns[0].textContent : null,
    fsBtnType: fsBtns.length > 0 ? fsBtns[0].type : null,
    hasKeydownListener: keydownListeners.length > 0
  }}));
}})();
"""
        out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        res = json.loads(out.stdout)
        self.assertEqual(res["fsBtnCount"], 1, "Exactly one fullscreen button must be created")
        self.assertEqual(res["fsBtnText"], "\u26F6", "Initial button text must be expand icon")
        self.assertEqual(res["fsBtnType"], "button")
        self.assertTrue(res["hasKeydownListener"], "ESC keydown listener must be registered")


class MapStaticAssets(unittest.TestCase):
    def test_index_html_links_markdown_map_js(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('<script src="./markdown-map.js', html)

    def test_chat_features_css_has_map_styles(self):
        # touch-action: pan-y is an intentional mobile trade-off to permit vertical page scrolling
        # while preventing touch gestures on the map canvas from hijacking document scroll.
        css = CSS.read_text(encoding="utf-8")
        self.assertIn('.chat-map-box', css)
        self.assertIn('.chat-map-canvas', css)
        self.assertIn('.chat-map-label', css)
        self.assertIn('.leaflet-container', css)
        self.assertIn('.chat-map-fallback', css)
        self.assertIn('touch-action: pan-y', css)
        self.assertIn('.chat-map-popup-btn', css)
        self.assertIn('.chat-map-fullscreen', css)
        self.assertIn('.chat-map-markers', css)
        self.assertIn('.chat-map-fs-btn', css)
        self.assertIn('.chat-map-label-multi', css)
        self.assertIn('.leaflet-pane', css)

    def test_fullscreen_touch_action_auto(self):
        """Fullscreen mode must set touch-action: auto to unlock all gestures."""
        css = CSS.read_text(encoding="utf-8")
        # Find the fullscreen block and verify it contains touch-action: auto
        self.assertIn('.chat-map-box.chat-map-fullscreen', css)
        # Check that fullscreen canvas has touch-action: auto
        self.assertIn('.chat-map-fullscreen .chat-map-canvas', css)
        self.assertIn('.chat-map-fullscreen .leaflet-container', css)
        # Count occurrences of touch-action: auto (at least 3: box, canvas, leaflet-container)
        auto_count = css.count('touch-action: auto')
        self.assertGreaterEqual(auto_count, 3, "Fullscreen must set touch-action: auto on box, canvas, and leaflet-container")


if __name__ == "__main__":
    unittest.main()
