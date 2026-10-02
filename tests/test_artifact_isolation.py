"""Unit tests for artifact isolation (tickets #575, #576):
- 1:1 sessions collect only their own artifacts and predecessor_session_id chain artifacts.
- Global workspace/artifacts and legacy ARTIFACTS_CACHE are no longer leaked into sessions.
- Group room artifacts are isolated per room (DATA / 'rooms' / rid / 'artifacts').
- Room artifacts endpoint GET /api/rooms/<rid>/artifacts via room_chat.api.
- Non-media brain paths (md/txt) in an answer are staged into the session and pass preview_guard.

Note on artifact generation in group rooms:
Ticket #575 establishes the room-scoped storage directory (DATA / 'rooms' / rid / 'artifacts'),
the isolation in the /api/rooms/<rid>/artifacts API, and drawer isolation in static/artifacts.js.
Actively populating/writing artifacts into this directory (by agent tools, file generation actions,
or user uploads) is outside the scope of ticket #575 and will be handled by future room tools/delegation runners.

Run: python3 -m unittest tests.test_artifact_isolation (from services/chatbot)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import characters as C
import room_chat as RC
import session as S


class TestArtifactIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.ws = self.tmp / "workspace"
        self.ws.mkdir(parents=True)
        self.sessions_dir = self.tmp / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.data_dir = self.tmp / "data"
        self.data_dir.mkdir(parents=True)
        self.rooms_dir = self.data_dir / "rooms"
        self.rooms_dir.mkdir(parents=True)
        self.cache_dir = self.tmp / "cache"
        self.cache_dir.mkdir(parents=True)

        self._saved_sessions = S.SESSIONS
        self._saved_ws = S.WORKSPACE
        self._saved_data = S.DATA
        self._saved_cache = getattr(S, "ARTIFACTS_CACHE", None)

        S.SESSIONS = self.sessions_dir
        S.WORKSPACE = self.ws
        S.DATA = self.data_dir
        S.ARTIFACTS_CACHE = self.cache_dir

        self.patches = [
            mock.patch.object(RC, "_dir", lambda: self.rooms_dir),
            mock.patch.object(C, "_default_ws", return_value=self.ws),
        ]
        for p in self.patches:
            p.start()

        # Setup characters for rooms
        self.c1, self.c2 = sorted(C.new_id() for _ in range(2))
        for cid, name in ((self.c1, "Chara1"), (self.c2, "Chara2")):
            C.save(cid, C.new_card(name), self.ws)
        C.save_team({"default": self.c1, "members": {self.c1: [], self.c2: []}}, self.ws)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        S.SESSIONS = self._saved_sessions
        S.WORKSPACE = self._saved_ws
        S.DATA = self._saved_data
        if self._saved_cache is not None:
            S.ARTIFACTS_CACHE = self._saved_cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_session(self, sid: str, predecessor_id: str = "") -> S.AgentSession:
        sdir = self.sessions_dir / sid
        sdir.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": sid,
            "provider": "agy",
            "model": "gemini-2.5-flash",
            "predecessor_session_id": predecessor_id,
        }
        (sdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        sess = S.AgentSession(sid, provider="agy")
        sess.predecessor_session_id = predecessor_id
        return sess

    def test_session_artifacts_isolated_between_sessions(self):
        s1 = self._create_session("sess_1")
        s2 = self._create_session("sess_2")

        a1_dir = self.sessions_dir / "sess_1" / "artifacts"
        a1_dir.mkdir(parents=True, exist_ok=True)
        (a1_dir / "art1.png").write_bytes(b"PNG1")

        a2_dir = self.sessions_dir / "sess_2" / "artifacts"
        a2_dir.mkdir(parents=True, exist_ok=True)
        (a2_dir / "art2.png").write_bytes(b"PNG2")

        arts1 = s1.get_artifacts()
        names1 = {a["name"] for a in arts1}
        self.assertIn("art1.png", names1)
        self.assertNotIn("art2.png", names1)
        self.assertTrue(any(a["url"].startswith("/artifacts/sess_1/") for a in arts1))

        arts2 = s2.get_artifacts()
        names2 = {a["name"] for a in arts2}
        self.assertIn("art2.png", names2)
        self.assertNotIn("art1.png", names2)
        self.assertTrue(any(a["url"].startswith("/artifacts/sess_2/") for a in arts2))

    def test_predecessor_session_chain_artifacts_included(self):
        s1 = self._create_session("sess_ancestor")
        s2 = self._create_session("sess_parent", predecessor_id="sess_ancestor")
        s3 = self._create_session("sess_child", predecessor_id="sess_parent")

        (self.sessions_dir / "sess_ancestor" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "sess_parent" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "sess_child" / "artifacts").mkdir(parents=True, exist_ok=True)

        (self.sessions_dir / "sess_ancestor" / "artifacts" / "doc_ancestor.md").write_text("# A", encoding="utf-8")
        (self.sessions_dir / "sess_parent" / "artifacts" / "code_parent.py").write_text("print(1)", encoding="utf-8")
        (self.sessions_dir / "sess_child" / "artifacts" / "img_child.png").write_bytes(b"PNG3")

        child_arts = s3.get_artifacts()
        child_names = {a["name"] for a in child_arts}
        self.assertEqual(child_names, {"doc_ancestor.md", "code_parent.py", "img_child.png"})

        # URL prefixes match original owning sessions
        url_map = {a["name"]: a["url"] for a in child_arts}
        self.assertIn("/artifacts/sess_ancestor/", url_map["doc_ancestor.md"])
        self.assertIn("/artifacts/sess_parent/", url_map["code_parent.py"])
        self.assertIn("/artifacts/sess_child/", url_map["img_child.png"])

        parent_arts = s2.get_artifacts()
        parent_names = {a["name"] for a in parent_arts}
        self.assertEqual(parent_names, {"doc_ancestor.md", "code_parent.py"})

        ancestor_arts = s1.get_artifacts()
        ancestor_names = {a["name"] for a in ancestor_arts}
        self.assertEqual(ancestor_names, {"doc_ancestor.md"})

    def test_predecessor_chain_cycle_protection(self):
        s1 = self._create_session("loop_1", predecessor_id="loop_2")
        self._create_session("loop_2", predecessor_id="loop_1")

        (self.sessions_dir / "loop_1" / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "loop_1" / "artifacts" / "file1.txt").write_text("loop", encoding="utf-8")

        # Must not hang or raise RecursionError
        arts = s1.get_artifacts()
        names = {a["name"] for a in arts}
        self.assertIn("file1.txt", names)

    def test_global_workspace_and_cache_not_scanned(self):
        s = self._create_session("clean_sess")
        (self.ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.ws / "artifacts" / "leaked_ws.png").write_bytes(b"WS")
        (self.cache_dir / "leaked_cache.png").write_bytes(b"CACHE")

        arts = s.get_artifacts()
        names = {a["name"] for a in arts}
        self.assertNotIn("leaked_ws.png", names)
        self.assertNotIn("leaked_cache.png", names)

    def test_room_artifacts_isolation(self):
        r1 = RC.create("Test Room 1", [self.c1, self.c2])
        r2 = RC.create("Test Room 2", [self.c1, self.c2])

        r1_dir = RC.artifacts_dir(r1["id"])
        r1_dir.mkdir(parents=True, exist_ok=True)
        (r1_dir / "room1_art.png").write_bytes(b"ROOM1")

        r2_dir = RC.artifacts_dir(r2["id"])
        r2_dir.mkdir(parents=True, exist_ok=True)
        (r2_dir / "room2_art.png").write_bytes(b"ROOM2")

        arts1 = RC.artifacts(r1["id"])
        names1 = {a["name"] for a in arts1}
        self.assertIn("room1_art.png", names1)
        self.assertNotIn("room2_art.png", names1)
        self.assertTrue(any("/api/file/raw" in a["url"] for a in arts1))

        arts2 = RC.artifacts(r2["id"])
        names2 = {a["name"] for a in arts2}
        self.assertIn("room2_art.png", names2)
        self.assertNotIn("room1_art.png", names2)

        # 1:1 sessions do not see room artifacts
        s = self._create_session("sess_alone")
        sess_arts = s.get_artifacts()
        sess_names = {a["name"] for a in sess_arts}
        self.assertNotIn("room1_art.png", sess_names)
        self.assertNotIn("room2_art.png", sess_names)

    def test_room_artifacts_api(self):
        r = RC.create("API Room", [self.c1, self.c2])
        r_dir = RC.artifacts_dir(r["id"])
        r_dir.mkdir(parents=True, exist_ok=True)
        (r_dir / "chart.png").write_bytes(b"CHART")

        # GET /api/rooms/<rid>/artifacts
        res = RC.api("GET", f"/api/rooms/{r['id']}/artifacts", None)
        self.assertIsNotNone(res)
        code, body = res
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["total"], 1)
        self.assertIsNone(body["next_before"])
        names = {a["name"] for a in body["artifacts"]}
        self.assertIn("chart.png", names)

        # Non-existent room -> 404
        res_404 = RC.api("GET", "/api/rooms/room_999999999999/artifacts", None)
        self.assertIsNotNone(res_404)
        self.assertEqual(res_404[0], 404)
        self.assertFalse(res_404[1]["ok"])

    def test_seen_names_omits_duplicate_filenames_in_subfolders(self):
        """Current specification test: when two files share the exact same filename in different
        subfolders of a session or room artifacts directory, seen_names de-duplicates by basename,
        so the second occurrence is omitted from results."""
        # 1. In a 1:1 session
        s = self._create_session("sess_dups")
        sub1 = self.sessions_dir / "sess_dups" / "artifacts" / "sub_a"
        sub2 = self.sessions_dir / "sess_dups" / "artifacts" / "sub_b"
        sub1.mkdir(parents=True, exist_ok=True)
        sub2.mkdir(parents=True, exist_ok=True)
        (sub1 / "result.png").write_bytes(b"RESULT_A")
        (sub2 / "result.png").write_bytes(b"RESULT_B")

        sess_arts = s.get_artifacts()
        matching = [a for a in sess_arts if a["name"] == "result.png"]
        # Exactly one is returned; the other duplicate filename in another subfolder is omitted
        self.assertEqual(len(matching), 1)

        # 2. In a group room
        r = RC.create("Dup Room", [self.c1, self.c2])
        r_dir = RC.artifacts_dir(r["id"])
        r_sub1 = r_dir / "dir_1"
        r_sub2 = r_dir / "dir_2"
        r_sub1.mkdir(parents=True, exist_ok=True)
        r_sub2.mkdir(parents=True, exist_ok=True)
        (r_sub1 / "report.pdf").write_bytes(b"PDF_A")
        (r_sub2 / "report.pdf").write_bytes(b"PDF_B")

        room_arts = RC.artifacts(r["id"])
        r_matching = [a for a in room_arts if a["name"] == "report.pdf"]
        self.assertEqual(len(r_matching), 1)

    def test_room_artifacts_exception_logging(self):
        r = RC.create("Log Room", [self.c1, self.c2])
        r_dir = RC.artifacts_dir(r["id"])
        r_dir.mkdir(parents=True, exist_ok=True)

        with mock.patch.object(Path, "rglob", side_effect=OSError("disk failure")):
            with self.assertLogs("room_chat", level="WARNING") as cm:
                arts = RC.artifacts(r["id"])
                self.assertEqual(arts, [])
            self.assertTrue(any("failed to collect room artifacts" in msg for msg in cm.output))

    def _brain_home(self):
        home = (self.tmp / "home").resolve()
        brain = home / ".gemini" / "antigravity-cli" / "brain"
        return home, brain

    def _swap_brain(self, home: Path, brain: Path):
        saved = (S.HOME, getattr(S, "BRAIN", None))
        S.HOME = home
        S.BRAIN = brain
        return saved

    def _restore_brain(self, saved):
        home, brain = saved
        S.HOME = home
        if brain is None:
            delattr(S, "BRAIN")
        else:
            S.BRAIN = brain

    def test_brain_markdown_link_is_staged_and_previewable(self):
        import preview_guard as PG
        import server as SV

        home, brain = self._brain_home()
        cid = "conv_md"
        src = brain / cid / "notes.md"
        src.parent.mkdir(parents=True)
        src.write_text("# staged notes\n", encoding="utf-8")
        tilde = "~/" + src.relative_to(home).as_posix()
        saved = self._swap_brain(home, brain)
        try:
            sess = self._create_session("sess_md")
            sess.conversation_id = cid
            text = "see [notes](file://%s) and (%s)" % (src, tilde)
            out = sess._rewrite_artifact_paths(text)
            want = "/artifacts/sess_md/brain/notes.md"
            self.assertIn(want, out)
            self.assertNotIn("file://", out)
            self.assertNotIn(str(src), out)
            self.assertNotIn(tilde, out)
            staged = self.sessions_dir / "sess_md" / "artifacts" / "brain" / "notes.md"
            self.assertTrue(staged.is_file())
            self.assertEqual(staged.read_text(encoding="utf-8"), "# staged notes\n")

            arts = sess.get_artifacts()
            hit = next(a for a in arts if a["name"] == "notes.md")
            self.assertEqual(hit["kind"], "document")
            self.assertEqual(hit["url"], want)

            allowed = [self.sessions_dir.resolve(), self.data_dir.resolve()]
            with mock.patch.object(SV, "_PREVIEW_ALLOWED_ROOTS", allowed):
                ok, why = PG._resolve_safe_preview_file(str(staged))
                self.assertIsNotNone(ok, why)
                self.assertEqual(ok, staged.resolve())
                self.assertIsNone(PG._resolve_safe_preview_file(str(src))[0])
        finally:
            self._restore_brain(saved)

    def test_get_artifacts_stages_brain_documents(self):
        home, brain = self._brain_home()
        cid = "conv_txt"
        src = brain / cid / "log.txt"
        src.parent.mkdir(parents=True)
        src.write_text("hello\n", encoding="utf-8")
        saved = self._swap_brain(home, brain)
        try:
            sess = self._create_session("sess_txt")
            sess.conversation_id = cid
            arts = sess.get_artifacts()
            hit = next(a for a in arts if a["name"] == "log.txt")
            self.assertEqual(hit["kind"], "document")
            self.assertEqual(hit["url"], "/artifacts/sess_txt/brain/log.txt")
            staged = self.sessions_dir / "sess_txt" / "artifacts" / "brain" / "log.txt"
            self.assertTrue(staged.is_file())
            self.assertEqual(staged.read_text(encoding="utf-8"), "hello\n")
        finally:
            self._restore_brain(saved)

    def test_non_media_artifacts_classification_and_listing(self):
        sess = self._create_session("sess_nonmedia")
        art_dir = self.sessions_dir / "sess_nonmedia" / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        (art_dir / "report.md").write_text("# Report", encoding="utf-8")
        (art_dir / "notes.txt").write_text("plain text notes", encoding="utf-8")
        (art_dir / "config.json").write_text("{\"k\": \"v\"}", encoding="utf-8")
        (art_dir / "data.csv").write_text("a,b,c\n1,2,3", encoding="utf-8")
        (art_dir / "main.py").write_text("print('hello')", encoding="utf-8")
        (art_dir / "script.sh").write_text("echo hi", encoding="utf-8")
        (art_dir / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
        (art_dir / "app.js").write_text("console.log(1);", encoding="utf-8")
        (art_dir / "photo.png").write_bytes(b"PNG_DATA")

        arts = sess.get_artifacts()
        kind_map = {a["name"]: a["kind"] for a in arts}
        ext_map = {a["name"]: a["ext"] for a in arts}
        url_map = {a["name"]: a["url"] for a in arts}

        # Documents
        for doc_name in ("report.md", "notes.txt", "config.json", "data.csv"):
            self.assertEqual(kind_map[doc_name], "document", f"{doc_name} should be document")
            self.assertTrue(url_map[doc_name].startswith("/artifacts/sess_nonmedia/"))

        # Code
        for code_name in ("main.py", "script.sh", "style.css", "app.js"):
            self.assertEqual(kind_map[code_name], "code", f"{code_name} should be code")
            self.assertTrue(url_map[code_name].startswith("/artifacts/sess_nonmedia/"))

        # Image
        self.assertEqual(kind_map["photo.png"], "image")

        # Extensions
        self.assertEqual(ext_map["report.md"], "md")
        self.assertEqual(ext_map["main.py"], "py")
        self.assertEqual(ext_map["config.json"], "json")
        self.assertEqual(ext_map["style.css"], "css")

    def test_room_non_media_artifacts_listing(self):
        r = RC.create("NonMedia Room", [self.c1, self.c2])
        r_dir = RC.artifacts_dir(r["id"])
        r_dir.mkdir(parents=True, exist_ok=True)
        (r_dir / "summary.md").write_text("# Room Summary", encoding="utf-8")
        (r_dir / "bot.py").write_text("x = 1", encoding="utf-8")
        (r_dir / "view.png").write_bytes(b"PNG")

        arts = RC.artifacts(r["id"])
        kind_map = {a["name"]: a["kind"] for a in arts}
        self.assertEqual(kind_map["summary.md"], "document")
        self.assertEqual(kind_map["bot.py"], "code")
        self.assertEqual(kind_map["view.png"], "image")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_markdown_artifacts_link_rendering_no_target_blank(self):
        import subprocess
        js = r"""
const fs = require('fs');
const mdSrc = fs.readFileSync(process.argv[1], 'utf8');
const vm = require('vm');
const ctx = {
  console,
  absArtifact: (u) => u,
  parseFileRef: () => null,
  fileRefTarget: (r) => '',
  splitChoices: (s) => ({ text: s, choices: [] }),
  parseExpression: (s) => ({ expression: null, text: s }),
  parseThought: (s) => ({ thought: null, cleanText: s }),
  dedupeMarkdownImages: (s) => s,
  marked: { parse: (s) => s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>') },
  DOMPurify: { sanitize: (s) => s },
  document: { getElementById: () => null, createElement: () => ({ classList: { add() {} } }) }
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(mdSrc, ctx);
const renderedMd = ctx.renderMarkdown('[리포트](/artifacts/sess_1/report.md) [외부](https://example.com)', true);
const renderedPlain = ctx.renderPlainText('[코드](/artifacts/sess_1/script.py) [외부](https://example.com)');
console.log(JSON.stringify({ md: renderedMd, plain: renderedPlain }));
"""
        r = subprocess.run(["node", "-e", js, str(ROOT / "static" / "markdown.js")], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout.strip())
        self.assertIn('class="artifact-link"', res["md"])
        self.assertNotIn('href="/artifacts/sess_1/report.md" target="_blank"', res["md"])
        self.assertIn('href="https://example.com" target="_blank"', res["md"])
        self.assertIn('class="artifact-link"', res["plain"])
        self.assertNotIn('href="/artifacts/sess_1/script.py" target="_blank"', res["plain"])
        self.assertIn('href="https://example.com" target="_blank"', res["plain"])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_artifacts_link_click_intercepts_to_open_modal(self):
        import subprocess
        js = r"""
const fs = require('fs');
const artSrc = fs.readFileSync(process.argv[1], 'utf8');
const mdSrc = fs.readFileSync(process.argv[2], 'utf8');
const vm = require('vm');

let modalOpened = null;
let preventDefaultCalled = false;
let stopPropagationCalled = false;

function makeEl(tag) {
  const attrs = {}, classes = new Set(), listeners = {}, children = [];
  return {
    tagName: tag.toUpperCase(),
    style: {},
    dataset: {},
    children,
    textContent: '',
    get className() { return Array.from(classes).join(' '); },
    set className(v) { classes.clear(); (v||'').split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    setAttribute: (k, v) => { attrs[k] = String(v); },
    getAttribute: (k) => attrs[k] !== undefined ? attrs[k] : null,
    removeAttribute: (k) => { delete attrs[k]; },
    appendChild: (c) => { children.push(c); c.parentElement = this; return c; },
    addEventListener: (evt, fn) => { if (!listeners[evt]) listeners[evt] = []; listeners[evt].push(fn); },
    dispatchEvent: (evt) => { (listeners[evt.type] || []).forEach(fn => fn(evt)); },
    querySelectorAll: function(sel) {
      const out = [];
      const walk = (el) => {
        for (const c of (el.children || [])) {
          const h = c.getAttribute('href') || '';
          if (sel.includes('.artifact-bound') && c.classList.contains('artifact-bound')) {}
          else if (sel.includes('href*="/artifacts/"') && h.includes('/artifacts/')) out.push(c);
          else if (sel.includes('.artifact-link') && c.classList.contains('artifact-link')) out.push(c);
          walk(c);
        }
      };
      walk(this);
      return out;
    }
  };
}

const doc = {
  getElementById: (id) => makeEl('div'),
  createElement: (tag) => makeEl(tag),
  querySelectorAll: () => []
};

const ctx = {
  console,
  document: doc,
  window: {},
  openArtifactModal: (item) => { modalOpened = item; },
  setTimeout: () => 0,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(mdSrc, ctx);

const container = makeEl('div');
const link = makeEl('a');
link.setAttribute('href', '/artifacts/sess_1/test_report.md');
link.setAttribute('target', '_blank');
link.className = 'artifact-link';
link.textContent = 'test_report.md';
container.appendChild(link);

ctx.attachArtifactLinkInterceptors(container);

const targetAttr = link.getAttribute('target');
const hasBoundClass = link.classList.contains('artifact-bound');

link.dispatchEvent({
  type: 'click',
  preventDefault: () => { preventDefaultCalled = true; },
  stopPropagation: () => { stopPropagationCalled = true; }
});

console.log(JSON.stringify({
  targetAttr,
  hasBoundClass,
  preventDefaultCalled,
  stopPropagationCalled,
  modalOpened
}));
"""
        r = subprocess.run(["node", "-e", js, str(ROOT / "static" / "artifacts.js"), str(ROOT / "static" / "markdown.js")], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip())
        self.assertIsNone(out["targetAttr"], "target attribute should be removed by interceptor")
        self.assertTrue(out["hasBoundClass"], "artifact-bound class should be added")
        self.assertTrue(out["preventDefaultCalled"], "e.preventDefault() must be called")
        self.assertTrue(out["stopPropagationCalled"], "e.stopPropagation() must be called")
        self.assertIsNotNone(out["modalOpened"])
        self.assertEqual(out["modalOpened"]["url"], "/artifacts/sess_1/test_report.md")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_open_artifact_modal_supports_document_and_code(self):
        import subprocess
        js = r"""
const fs = require('fs');
const artSrc = fs.readFileSync(process.argv[1], 'utf8');
const vm = require('vm');

function makeEl(tag) {
  const attrs = {}, classes = new Set(), children = [];
  return {
    tagName: tag.toUpperCase(),
    style: {},
    children,
    innerHTML: '',
    textContent: '',
    appendChild: (c) => { children.push(c); return c; },
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
    addEventListener: () => {},
    setAttribute: (k, v) => { attrs[k] = v; },
    getAttribute: (k) => attrs[k] || null,
    removeAttribute: (k) => { delete attrs[k]; },
  };
}

const modalBodyEl = makeEl('div');
const artModalEl = makeEl('div');
const ctx = {
  console,
  document: {
    getElementById: (id) => {
      if (id === 'artModal') return artModalEl;
      if (id === 'modalBody') return modalBodyEl;
      return makeEl('div');
    },
    createElement: (tag) => makeEl(tag),
    querySelectorAll: () => []
  },
  addEventListener: () => {},
  copyText: async () => true,
  resolveArtifactUrl: (u) => u,
  fetch: async (u) => ({ ok: true, text: async () => 'content from fetch' }),
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(artSrc, ctx);

async function run() {
  const results = {};
  await ctx.openArtifactModal({ name: 'spec.md', kind: 'document', content: '# Markdown Spec' });
  results.docSupported = !modalBodyEl.innerHTML.includes('미리보기를 지원하지 않는');

  await ctx.openArtifactModal({ name: 'main.py', kind: 'code', content: 'print(42)' });
  results.codeSupported = !modalBodyEl.innerHTML.includes('미리보기를 지원하지 않는');

  await ctx.openArtifactModal('/artifacts/sess_1/algo.py');
  results.urlNormalized = !modalBodyEl.innerHTML.includes('미리보기를 지원하지 않는');

  console.log(JSON.stringify(results));
}
run();
"""
        r = subprocess.run(["node", "-e", js, str(ROOT / "static" / "artifacts.js")], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip())
        self.assertTrue(out["docSupported"], "document artifact must be previewed via text viewer")
        self.assertTrue(out["codeSupported"], "code artifact must be previewed via code/text viewer")
        self.assertTrue(out["urlNormalized"], "string URL artifact must be normalized and opened in modal")


if __name__ == "__main__":
    unittest.main()
