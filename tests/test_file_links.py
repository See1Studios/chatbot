"""FILE_LINKS_v1: a path in an answer opens the file preview. Agents write paths in backticks (`static/app-sse.js`,
`docs/plans/INDEX.md:120`, `tickets.py::claim`) or bare (~/services/x.md); only explicit markdown links used to
work, and not ~/ or relative ones, which the sanitiser drops. Recognition is in static/markdown.js (the REAL
functions run in node here); whether a file may be shown stays the server's allow-list (preview_guard.py), and a
relative path now also resolves against the engine repo.
Run: engine/run-tests.sh test_file_links
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
from tests._paths import ENGINE, REPO  # noqa: E402

ROOT = REPO
sys.path.insert(0, str(ENGINE))
MD = ROOT / "static" / "markdown.js"


def run_js(expr):
    src = MD.read_text(encoding="utf-8")
    a, b = src.index("const FILE_EXTS"), src.index("function linkifyFilePaths")
    out = subprocess.run(["node", "-e", src[a:b] + "\nconsole.log(JSON.stringify(" + expr + "));"],
                         capture_output=True, text=True, timeout=20)
    if out.returncode:
        raise AssertionError(out.stderr[-800:])
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Recognise(unittest.TestCase):
    def test_what_is_a_file_reference(self):
        cases = {
            "static/app-sse.js": ["static/app-sse.js", 0, 0],
            "docs/plans/INDEX.md:120": ["docs/plans/INDEX.md", 120, 120],
            "providers/adapter_base.py#L30-42": ["providers/adapter_base.py", 30, 42],
            "tickets.py::claim": ["tickets.py", 0, 0],
            "~/services/chatbot/AGENTS.md": ["~/services/chatbot/AGENTS.md", 0, 0],
            "/srv/pe/data/notes.txt": ["/srv/pe/data/notes.txt", 0, 0],
            "./tools/ticket_quick.py": ["./tools/ticket_quick.py", 0, 0],
            "file:///srv/x/y.md": ["/srv/x/y.md", 0, 0],
        }
        got = run_js("%s.map(t => { const r = parseFileRef(t, true); return r && [r.path, r.start, r.end]; })"
                     % json.dumps(list(cases)))
        self.assertEqual(dict(zip(cases, got)), cases)

    def test_what_is_not(self):
        nots = ["e.g.", "v1.2", "https://example.com/a.md", "/api/file/raw", "/chat/app.js", "/defib",
                "a b.md", "//cdn.example.com/x.js", "3/4", "and/or", "", "그냥 글"]
        self.assertEqual(run_js("%s.map(t => parseFileRef(t, false))" % json.dumps(nots, ensure_ascii=False)),
                         [None] * len(nots))

    def test_a_bare_name_counts_only_in_a_code_span(self):
        self.assertEqual(run_js("[parseFileRef('app.js', true) && parseFileRef('app.js', true).path, "
                                "parseFileRef('app.js', false)]"), ["app.js", None])

    def test_paths_are_found_in_prose_without_their_punctuation(self):
        text = "수정은 static/app-sse.js 에서, 설정은 (~/services/chatbot/data/host.env). 그리고 docs/plans/INDEX.md:12, and/or 3/4."
        got = run_js("findBarePaths(%s).map(h => [h.token, h.ref.start])" % json.dumps(text, ensure_ascii=False))
        self.assertEqual(got, [["static/app-sse.js", 0], ["~/services/chatbot/data/host.env", 0],
                               ["docs/plans/INDEX.md:12", 12]])

    def test_the_preview_target_carries_the_lines(self):
        self.assertEqual(run_js("[fileRefTarget(parseFileRef('a/b.py:7', true)), fileRefTarget(parseFileRef('a/b.py:7-9', true)),"
                                " fileRefTarget(parseFileRef('a/b.py', true))]"),
                         ["a/b.py#L7", "a/b.py#L7-9", "a/b.py"])


class ServerResolves(unittest.TestCase):
    def test_a_relative_path_resolves_in_the_engine_repo_and_the_guard_still_holds(self):
        import preview_guard as g
        import server
        # The allow-list is the host's (~/services, ...); a delegated run tests a copy under ~/.worktrees, so the copy
        # joins the list here and the test asks only what it means to: resolution + the guard's refusals (#380).
        roots = list(server._PREVIEW_ALLOWED_ROOTS) + [ROOT]
        with mock.patch.object(server, "_PREVIEW_ALLOWED_ROOTS", roots):
            for rel in ("docs/plans/INDEX.md", "static/app-sse.js", "tickets.py::claim"):
                fp, why = g._resolve_safe_preview_file(rel)
                self.assertIsNotNone(fp, "%s: %s" % (rel, why))
                self.assertTrue(str(fp).startswith(str(ROOT)), fp)
            for bad in ("../../../etc/passwd", "data/secrets.env", "~/.ssh/config"):
                self.assertIsNone(g._resolve_safe_preview_file(bad)[0], bad)

    def test_no_host_path_is_baked_into_the_recogniser(self):
        src = MD.read_text(encoding="utf-8")
        a, b = src.index("const FILE_EXTS"), src.index("function attachFileLinkInterceptors")
        for host in ("/volume1", "/var/", "/home/", "DiskStation"):
            self.assertNotIn(host, src[a:b])


if __name__ == "__main__":
    unittest.main()
