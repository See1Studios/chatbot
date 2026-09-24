"""The page's own script as one text (APP_SPLIT_v1): static/app.js is split into app-*.js parts that load before it
(static/index.html). Tests that slice the page's code between markers read this bundle, so they do not depend on
which file holds a function."""
import atexit
import os
import re
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def app_files():
    """app-*.js and app.js, in the order index.html loads them."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return [STATIC / n for n in re.findall(r'<script src="\./(app(?:-[a-z-]+)?\.js)', html)]


def css_files():
    """The chat stylesheet parts (chat-*.css), in the order index.html links them -- which is the cascade order."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return [STATIC / n for n in re.findall(r'<link rel="stylesheet" href="\./(chat-[a-z-]+\.css)', html)]


def css_source() -> str:
    """The whole chat stylesheet as one text, as the browser applies it (CSS_SPLIT_v1)."""
    return "\n".join(p.read_text(encoding="utf-8") for p in css_files())


FILE_MARK = "// ==== file: "   # starts each file in the bundle, so a slice can stop at the end of its file


def app_source() -> str:
    return "".join("%s%s\n%s\n" % (FILE_MARK, p.name, p.read_text(encoding="utf-8")) for p in app_files())


_bundle = None


def app_bundle() -> Path:
    """app_source() in a temporary file, for node harnesses that read a path. Removed at exit."""
    global _bundle
    if _bundle is None:
        fd, name = tempfile.mkstemp(suffix="-app-bundle.js")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(app_source())
        _bundle = Path(name)
        atexit.register(lambda: _bundle.unlink() if _bundle.exists() else None)
    return _bundle
